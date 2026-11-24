"""정준 YAML/JSON 을 SesDocument 로 적재하고 참조 무결성을 검사한다.

스키마 검증(형태)은 jsonschema 로 따로 하고, 여기서는 이름 해석과
기본 불변식(댕글링 참조, extends 순환, 루트 유일성, 포트 타입 일치)을 검사한다.
공리 검증 전체는 ses_ops 의 AxiomValidator 과제다.
"""

from __future__ import annotations

import contextlib

import re
from typing import Any, Optional

from . import model as m
from .skeleton import MARKERS


_IDENTIFIER = re.compile(r"[A-Za-z_가-힣][A-Za-z0-9_가-힣]*\Z")       # 스키마의 identifier


class LoadError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 항목의 이름. 모르는 항목은 거부한다
#
# 잘못 적은 항목을 조용히 넘기면 문서의 뜻이 적은 사람의 뜻과 달라진다. 속성의 값을 default 가 아니라
# value 로 적으면 값이 없는 속성이 된다. 스키마(ses.schema.json)는 그것을 막지만 스키마 검증은 따로 하는
# 일이라 빠지기 쉽다. 그래서 적재기가 직접 본다. 아래의 표는 스키마의 properties 와 같아야 하고,
# tests/test_loader.py 가 둘이 같은지 본다.
# ---------------------------------------------------------------------------

KEYS = {
    "document": {"ses", "name", "version", "description", "variables", "port_types", "entities", "constraints",
                 "experimental_frames", "metadata", "profile"},
    "variable": {"type", "default", "range", "values", "doc"},
    "portType": {"fields", "doc"},
    "port": {"type", "direction", "required", "doc"},
    "attribute": {"type", "default", "unit", "expr", "values", "each", "doc"},
    "entity": {"root", "extends", "stereotype", "ports", "attributes", "aspects", "multi_aspects", "specializations",
               "doc", "metadata", "kind", "fields", "links"},
    "partRef": {"def", "alias"},
    "aspect": {"parts", "couplings", "rule", "priority", "doc"},
    "multiAspect": {"part", "cardinality", "naming", "couplings", "rule", "priority", "doc"},
    "pattern": {"pattern", "fan_out", "fan_in", "between", "custom", "first", "last"},
    "specialization": {"alternatives", "select", "default", "doc"},
    "selectRule": {"when", "then", "else"},
    "coupling": {"from", "to", "doc"},
    "constraint": {"name", "when", "require", "forbid", "doc"},
    "frame": {"ref", "attach_to"},
}
_MEANT = {("attribute", "value"): "default", ("variable", "value"): "default", ("aspect", "part"): "parts",
          ("multiAspect", "parts"): "part", ("specialization", "alternative"): "alternatives",
          ("entity", "aspect"): "aspects", ("entity", "specialization"): "specializations",
          ("entity", "multi_aspect"): "multi_aspects", ("entity", "attribute"): "attributes", ("entity", "port"): "ports"}


def _known(d: Any, kind: str, where: str, required: tuple = ()) -> None:
    """d 가 그 종류의 항목만 가진 표인가. 아니면 어디가 틀렸는지를 적어 LoadError 를 낸다."""
    if not isinstance(d, dict):
        raise LoadError(f"{where}: 이름과 값의 표로 적어야 한다. 적힌 것은 {d!r} 다. 내용이 없으면 {{}} 를 적는다")
    for key in sorted(map(str, set(d) - KEYS[kind])):
        meant = _MEANT.get((kind, key))
        raise LoadError(f"{where}: 모르는 항목 {key} 가 있다. " + (f"{meant} 를 뜻했는가. " if meant else "")
                        + f"쓸 수 있는 것은 {sorted(KEYS[kind])} 다")
    for key in required:
        if key not in d:
            raise LoadError(f"{where}: {key} 가 없다")


def _list(x: Any, where: str, what: str = "항목") -> list:
    """목록으로 적어야 하는 곳. 아니면 어디가 틀렸는지를 적는다."""
    if not isinstance(x, list):
        raise LoadError(f"{where}: {what}의 목록으로 적는다. 적힌 것은 {x!r} 다")
    return x


def _close(name, known) -> str:
    """이름을 잘못 적었을 때 뜻했을 만한 이름. 없으면 빈 글."""
    import difflib
    found = difflib.get_close_matches(str(name), [str(k) for k in known], n=1, cutoff=0.6)
    return f". {found[0]} 를 뜻했는가" if found else ""


# ---------------------------------------------------------------------------
# 표현식: 저장 축약형을 AST 로 펼친다
# ---------------------------------------------------------------------------

_CMP_OPS = ("eq", "ne", "lt", "le", "gt", "ge", "in")


def _operand(x: Any) -> m.Expr:
    """비교의 오른쪽이나 함수의 인자. 객체이면 값으로 쓰는 식(변수, 함수 호출)이고 아니면 상수다."""
    return parse_expr(x) if isinstance(x, dict) else m.Const(x)


def _selected(s: Any) -> m.Selected:
    if isinstance(s, dict):
        at, path = s.get("at"), s.get("path")
        if (at is None) == (path is None):
            raise LoadError(f"selected 에는 at 과 path 가운데 정확히 하나가 있어야 한다: {s!r}")
        kinds = [k for k in ("specialization", "multi_aspect", "aspect") if k in s]
        if len(kinds) != 1:
            raise LoadError(f"selected 에는 specialization, multi_aspect, aspect 가운데 정확히 하나가 있어야 한다: {s!r}")
        group, choice = {"specialization": (s.get("specialization"), s.get("alternative")),
                         "multi_aspect": (s.get("multi_aspect"), s.get("count")),
                         "aspect": ("", s.get("aspect"))}[kinds[0]]
        if choice is None or isinstance(choice, (list, dict)):
            raise LoadError(f"selected 에는 선택지 하나(alternative, count, aspect)가 있어야 한다: {s!r}")
        if at is not None:
            return m.Selected(f"{at}/{group}" if group else str(at), choice)
        return m.Selected(group, choice, tuple(path))
    node, _, choice = str(s).partition("=")
    if not node or not choice:
        raise LoadError(f"selected 는 '정의/이름=선택지' 또는 '정의=분해' 형식이어야 한다: {s}")
    return m.Selected(node, choice)


def parse_expr(d: Any) -> m.Expr:
    if not isinstance(d, dict):
        raise LoadError(f"표현식은 객체여야 한다: {d!r}")
    if "var" in d:
        for op in _CMP_OPS:
            if op in d:
                return m.Compare(op, m.Var(d["var"]), _operand(d[op]))
        if set(d) == {"var"}:
            return m.Var(d["var"])               # 값으로 쓰는 변수: 함수의 인자, 비교의 오른쪽, 속성의 식
        raise LoadError(f"var 비교 연산자가 없다: {d!r}")
    if "all" in d:
        return m.And(tuple(parse_expr(x) for x in d["all"]))
    if "any" in d:
        return m.Or(tuple(parse_expr(x) for x in d["any"]))
    if "not" in d:
        return m.Not(parse_expr(d["not"]))
    if "selected" in d:
        return _selected(d["selected"])
    if "call" in d:
        call = m.Call(d["call"], tuple(_operand(a) for a in d.get("args", [])))
        for op in _CMP_OPS:
            if op in d:
                return m.Compare(op, call, _operand(d[op]))   # 함수의 값을 견준다
        return call
    if "replica" in d:
        what, up = d["replica"], d.get("up", 0)
        if what not in ("index", "count") or not isinstance(up, int) or isinstance(up, bool) or up < 0:
            raise LoadError(f"replica 는 index 또는 count 이고 up 은 0 이상의 정수여야 한다: {d!r}")
        replica = m.Replica(what, up)
        for op in _CMP_OPS:
            if op in d:
                return m.Compare(op, replica, _operand(d[op]))
        return replica
    raise LoadError(f"알 수 없는 표현식: {d!r}")


# ---------------------------------------------------------------------------
# 개별 구조
# ---------------------------------------------------------------------------

def _scalar(t: str) -> m.ScalarType:
    try:
        return m.ScalarType(t)
    except ValueError:
        allowed = sorted(x.value for x in m.ScalarType)
        hint = ". 시간 값은 문서에 float 로 적고 모델의 PARAMS 에서 time 으로 적는다" if t == "time" else ""
        raise LoadError(f"알 수 없는 타입 {t!r}. 쓸 수 있는 것은 {allowed} 다{hint}")


def _variable(name: str, d: dict) -> m.Variable:
    _known(d, "variable", f"variables.{name}", ("type",))
    domain = None
    kind = _scalar(d["type"])
    if "range" in d:
        r = d["range"]
        whole = kind == m.ScalarType.INT
        if not (isinstance(r, list) and len(r) == 2 and all(_plain_number(x, whole) for x in r)):
            raise LoadError(f"variables.{name}.range: [가장 작은 값, 가장 큰 값] 으로 " + ("정수" if whole else "수")
                            + f" 둘을 적는다. 적힌 것은 {r!r} 다")
        domain = m.Range(r[0], r[1])
    elif "values" in d:
        vs = d["values"]
        if not isinstance(vs, list) or any(isinstance(v, (list, dict)) for v in vs):
            raise LoadError(f"variables.{name}.values: 값의 목록으로 적는다. 값은 수, 글, 참과 거짓 가운데 하나다")
        if len(vs) > RANGE_LIMIT:
            raise LoadError(f"variables.{name}.values: 값이 {RANGE_LIMIT}개를 넘는다. 변수는 구조를 가르는 값에 쓴다")
        domain = m.EnumSet(tuple(vs))
    return m.Variable(name, kind, d.get("default"), domain, d.get("doc"))


def _plain_number(x, whole: bool = False) -> bool:
    """유한한 수인가. whole 이면 정수여야 한다. 참과 거짓은 수가 아니다."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    if whole:
        return isinstance(x, int)
    return x == x and abs(x) != float("inf")


def _port_type(name: str, d: dict) -> m.PortType:
    _known(d, "portType", f"port_types.{name}")
    return m.PortType(name, {k: _scalar(v) for k, v in (d.get("fields") or {}).items()}, d.get("doc"))


def _port(name: str, d: dict) -> m.Port:
    _known(d, "port", f"포트 {name}", ("type", "direction"))
    return m.Port(name, d["type"], m.Direction(d["direction"]), d.get("doc"),
                  bool(d.get("required", False)))


def _attribute(name: str, d: dict) -> m.Attribute:
    _known(d, "attribute", f"속성 {name}", ("type",))
    if "expr" in d and "each" in d:
        raise LoadError(f"속성 {name}: expr 과 each 를 함께 쓸 수 없다")
    if "each" in d and not isinstance(d["each"], list):
        raise LoadError(f"속성 {name}: each 는 복제본마다의 값을 적은 목록이어야 한다")
    try:
        kind = _scalar(d["type"])
    except LoadError as e:
        raise LoadError(f"속성 {name}: {e}") from None
    return m.Attribute(
        name, kind, d.get("default"), d.get("unit"),
        parse_expr(d["expr"]) if "expr" in d else None,
        tuple(d["values"]) if "values" in d else None, d.get("doc"),
        tuple(d["each"]) if "each" in d else None)


def fits(value: Any, type_: m.ScalarType) -> bool:
    """값이 속성의 타입에 맞는가. bool은 수가 아니다. float 자리에는 정수도 온다."""
    if type_ == m.ScalarType.BOOL:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if type_ == m.ScalarType.INT:
        return isinstance(value, int)
    if type_ == m.ScalarType.FLOAT:
        return isinstance(value, (int, float))
    if type_ == m.ScalarType.STR:
        return isinstance(value, str)
    return isinstance(value, (str, int, float))          # enum: 허용 값은 values 가 정한다


def _coupling(d: dict) -> m.Coupling:
    _known(d, "coupling", "결합", ("from", "to"))
    return m.Coupling(m.PortRef.parse(d["from"]), m.PortRef.parse(d["to"]), d.get("doc"))


def _part_ref(x: Any) -> m.PartRef:
    if isinstance(x, str):
        return m.PartRef(x)
    _known(x, "partRef", "부분", ("def",))
    return m.PartRef(x["def"], x.get("alias"))


def _aspect(name: str, d: dict) -> m.Aspect:
    _known(d, "aspect", f"aspect {name}", ("parts",))
    return m.Aspect(
        name, tuple(_part_ref(p) for p in _list(d["parts"], f"aspect {name}.parts", "부분")),
        tuple(_coupling(c) for c in _list(d.get("couplings") or [], f"aspect {name}.couplings", "결합")),
        parse_expr(d["rule"]) if "rule" in d else None,
        d.get("priority"), d.get("doc"))


def _cardinality(x: Any) -> m.Cardinality:
    if isinstance(x, int) and not isinstance(x, bool):
        return m.Fixed(x)
    if isinstance(x, dict) and set(x) == {"var"}:
        return m.VarCard(x["var"])
    if isinstance(x, dict) and "min" in x and set(x) <= {"min", "max"}:
        return m.RangeCard(x["min"], x.get("max"))
    raise LoadError(f"cardinality: 개수는 정수, {{var: 변수}}, {{min: 수, max: 수}} 가운데 하나다. 적힌 것은 {x!r} 다")


def _pattern(d: dict) -> m.CouplingPattern:
    _known(d, "pattern", "결합의 틀")
    cp = lambda key: tuple(_coupling(c) for c in _list(d.get(key) or [], f"결합의 틀의 {key}", "결합"))  # noqa: E731
    return m.CouplingPattern(m.PatternKind(d.get("pattern", "custom")),
                             cp("fan_out"), cp("fan_in"), cp("between"), cp("custom"),
                             cp("first"), cp("last"))


def _multi_aspect(name: str, d: dict) -> m.MultiAspect:
    _known(d, "multiAspect", f"multi-aspect {name}", ("part", "cardinality"))
    if not isinstance(d.get("naming", ""), str):
        raise LoadError(f"multi-aspect {name}.naming: 복제본의 이름의 틀을 글로 적는다. 예: \"w{{i}}\". 적힌 것은 {d['naming']!r} 다")
    return m.MultiAspect(
        name, _part_ref(d["part"]), _cardinality(d["cardinality"]),
        d.get("naming", "{part}_{i}"),
        _pattern(d["couplings"]) if "couplings" in d else None,
        parse_expr(d["rule"]) if "rule" in d else None,
        d.get("priority"), d.get("doc"))


def _select_rule(d: dict) -> m.SelectRule:
    _known(d, "selectRule", "선택 규칙", ("when", "then"))
    other = d.get("else")
    if isinstance(other, dict):
        other = _select_rule(other)
    return m.SelectRule(parse_expr(d["when"]), d["then"], other)


def _specialization(name: str, d: dict) -> m.Specialization:
    _known(d, "specialization", f"specialization {name}", ("alternatives",))
    return m.Specialization(
        name, tuple(d["alternatives"]),
        _select_rule(d["select"]) if "select" in d else None,
        d.get("default"), d.get("doc"))


def _entity(name: str, d: dict) -> m.EntityDef:
    """정의 하나. 그 안에서 난 오류에는 정의의 이름을 앞에 붙인다."""
    try:
        return _entity_body(name, d)
    except LoadError as e:
        raise LoadError(f"{name}: {e}") from None
    except (LookupError, TypeError, AttributeError, ValueError) as e:   # 모양이 틀린 곳을 미리 다 막지는 못했다
        raise LoadError(f"{name}: 적힌 값의 모양이 형식과 다르다 ({type(e).__name__}: {e}). 이 정의의 항목마다 표, 목록, 글 "
                        "가운데 무엇으로 적는지를 본다") from None


def _entity_body(name: str, d: dict) -> m.EntityDef:
    _known(d, "entity", "정의")
    return m.EntityDef(
        name=name,
        root=bool(d.get("root", False)),
        extends=d.get("extends"),
        stereotype=m.Stereotype(d["stereotype"]) if "stereotype" in d else None,
        ports={k: _port(k, v) for k, v in (d.get("ports") or {}).items()},
        attributes={k: _attribute(k, v) for k, v in (d.get("attributes") or {}).items()},
        aspects={k: _aspect(k, v) for k, v in (d.get("aspects") or {}).items()},
        multi_aspects={k: _multi_aspect(k, v) for k, v in (d.get("multi_aspects") or {}).items()},
        specializations={k: _specialization(k, v) for k, v in (d.get("specializations") or {}).items()},
        doc=d.get("doc"),
        metadata=d.get("metadata") or {},
        kind=d.get("kind"),
        fields=d.get("fields") or {},
        links={k: tuple(v) for k, v in (d.get("links") or {}).items()},
    )


def _constraint(d: dict) -> m.Constraint:
    _known(d, "constraint", "제약", ("name",))
    g = lambda k: parse_expr(d[k]) if k in d else None  # noqa: E731
    return m.Constraint(d["name"], g("when"), g("require"), g("forbid"), d.get("doc"))


# ---------------------------------------------------------------------------
# 문서 적재와 무결성 검사
# ---------------------------------------------------------------------------

def load_ses_dict(d: dict) -> m.SesDocument:
    """사전으로 읽은 정준 문서를 자료구조로. 틀린 문서는 LoadError 로만 알린다."""
    try:
        return _load_ses_dict(d)
    except LoadError:
        raise
    except (LookupError, TypeError, AttributeError, ValueError, RecursionError) as e:   # 모양이 틀린 곳을 미리 다 막지는 못했다
        raise LoadError(f"적힌 값의 모양이 형식과 다르다 ({type(e).__name__}: {e}). 항목마다 표, 목록, 글 가운데 무엇으로 "
                        "적는지를 본다") from None


def _load_ses_dict(d: dict) -> m.SesDocument:
    _known(d, "document", "문서", ("ses", "name", "entities"))
    for f in d.get("experimental_frames") or ():
        _known(f, "frame", "experimental_frames", ("ref",))
    doc = m.SesDocument(
        format_version=str(d["ses"]),
        name=d["name"],
        version=d.get("version"),
        description=d.get("description"),
        variables={k: _variable(k, v) for k, v in (d.get("variables") or {}).items()},
        port_types={k: _port_type(k, v) for k, v in (d.get("port_types") or {}).items()},
        entities={k: _entity(k, v) for k, v in d["entities"].items()},
        constraints=tuple(_constraint(c) for c in d.get("constraints", [])),
        experimental_frames=tuple(m.FrameAttachment(f["ref"], f.get("attach_to"))
                                  for f in d.get("experimental_frames", [])),
        metadata=d.get("metadata") or {},
        profile=d.get("profile"),
    )
    check_integrity(doc)
    return doc


def load_ses(path: str) -> m.SesDocument:
    from . import safeyaml
    try:
        d = safeyaml.load(path)
    except safeyaml.YamlError as e:
        raise LoadError(str(e)) from None
    return load_ses_dict(d)


def check_integrity(doc: m.SesDocument) -> None:
    errors: list[str] = []
    ents = doc.entities

    # 루트 유일성
    try:
        doc.root
    except ValueError as e:
        errors.append(str(e))

    def ref_ok(name: str, where: str) -> None:
        if name not in ents:
            errors.append(f"{where}: 정의되지 않은 엔티티 참조 {name}{_close(name, ents)}")

    def chain(name: str):
        """extends 를 따라간 정의들. extends 가 없는 정의를 가리키거나 돌면 None 이다. 그것은 따로 알린다."""
        try:
            return doc.ancestors(name)
        except (ValueError, KeyError):
            return None

    def expr_vars(e: m.Expr | None, where: str, constraint: bool = False, attribute: bool = False) -> None:
        if e is None:
            return
        if isinstance(e, m.Var) and e.name not in doc.variables:
            errors.append(f"{where}: 정의되지 않은 변수 {e.name}")
        if isinstance(e, m.Replica) and not attribute:
            errors.append(f"{where}: replica 는 속성의 식에서만 쓴다")
        if isinstance(e, m.Selected):
            if not constraint:
                errors.append(f"{where}: selected 는 선택 제약(constraints)에서만 쓴다")
            elif e.path is None:
                why = selected_problem(doc, e)
                if why:
                    errors.append(f"{where}: {why}")
        for child in getattr(e, "items", ()) or ():
            expr_vars(child, where, constraint, attribute)
        for attr in ("left", "right", "item"):
            if hasattr(e, attr):
                expr_vars(getattr(e, attr), where, constraint, attribute)
        if isinstance(e, m.Call):
            for a in e.args:
                expr_vars(a, where, constraint, attribute)

    for name, ent in ents.items():
        # extends 와 순환
        if ent.extends is not None:
            ref_ok(ent.extends, f"{name}.extends")
            try:
                doc.ancestors(name)
            except ValueError as e:
                errors.append(f"{name}: {e}")
            except KeyError:                                  # 없는 정의를 가리킨다. 바로 위나 그 정의의 줄에서 알렸다
                pass
        # valid brothers
        names = ent.decomposition_names
        if len(names) != len(set(names)):
            errors.append(f"{name}: 형제 이름 충돌 {names}")
        for reserved in sorted(MARKERS & set(names)):        # 펼침이 표시 노드의 이름으로 쓴다 (18 문서 3절, 5.3절)
            errors.append(f"{name}: 이름 {reserved} 는 쓸 수 없다. 펼침이 표시로 쓰는 이름이다")
        # 이름은 스키마의 identifier 다. 펼친 나무는 이름을 노드의 경로에 그대로 쓰고 변수($), 개수([n]),
        # 주소(/)에 다른 글자를 쓴다. 이름이 그 글자를 가지면 정의 표 위의 뜻과 펼친 나무가 어긋난다 (theory.md 의 W4)
        aliases = [p.alias for a in ent.aspects.values() for p in a.parts if p.alias is not None] + \
                  [ma.part.alias for ma in ent.multi_aspects.values() if ma.part.alias is not None]
        for x in dict.fromkeys([name] + list(names) + aliases):
            if not _IDENTIFIER.match(str(x)) and x not in MARKERS & set(names):     # 표시의 이름은 위에서 알렸다
                errors.append(f"{name}: 이름 {x!r} 는 쓸 수 없다. 글자, 숫자, 밑줄로 쓰고 숫자로 시작하지 않는다")
        # 분해의 우선순위는 정수다. 정수가 아니면 "같은 자리"가 동치 관계가 아닐 수 있다 (theory.md 정의 1)
        for x in list(ent.aspects.values()) + list(ent.multi_aspects.values()):
            if x.priority is not None and (not isinstance(x.priority, int) or isinstance(x.priority, bool)):
                errors.append(f"{name}/{x.name}.priority: 우선순위는 정수여야 한다: {x.priority!r}")
        # 포트 타입
        for p in ent.ports.values():
            if p.type not in doc.port_types:
                errors.append(f"{name}.ports.{p.name}: 정의되지 않은 포트 타입 {p.type}")
        # 속성의 식과 복제본마다의 값
        for a in ent.attributes.values():
            expr_vars(a.expr, f"{name}.attributes.{a.name}.expr", attribute=True)
            for i, v in enumerate(a.each or ()):
                if not fits(v, a.type) or (a.values is not None and v not in a.values):
                    errors.append(f"{name}.attributes.{a.name}.each[{i}]: 값 {v!r} 이 타입 {a.type.value} 에 맞지 않다")
        # 상속 포트 재선언 검사
        if ent.extends in ents and ent.extends != name:
            parent_ports = doc.all_ports(ent.extends)
            for pn, p in ent.ports.items():
                pp = parent_ports.get(pn)
                if pp and (pp.type != p.type or pp.direction != p.direction):
                    errors.append(f"{name}.ports.{pn}: 부모 포트와 타입 또는 방향이 다르다")
        # aspect
        for asp in ent.aspects.values():
            part_names = [p.part_name for p in asp.parts]
            if len(part_names) != len(set(part_names)):
                errors.append(f"{name}/{asp.name}: 부분 이름 충돌 {part_names}")
            for p in asp.parts:
                ref_ok(p.def_name, f"{name}/{asp.name}.parts")
            expr_vars(asp.rule, f"{name}/{asp.name}.rule")
            _check_couplings(doc, ent, asp.parts, asp.couplings, f"{name}/{asp.name}", errors)
        # multi-aspect
        for ma in ent.multi_aspects.values():
            ref_ok(ma.part.def_name, f"{name}/{ma.name}.part")
            # 복제본의 이름은 번호마다 달라야 하고 이름의 글자로만 이루어져야 한다 (theory.md 정의 1, W4).
            # 틀에 {i} 가 없으면 복제본들이 한 자리에 겹친다
            try:
                sample = [ma.naming.format(i=i, n=2, part=ma.part.part_name) for i in range(2)]
            except (KeyError, IndexError, ValueError) as err:
                sample = None
                errors.append(f"{name}/{ma.name}.naming: 이름의 틀을 채울 수 없다: {err!r}")
            if sample is not None and ("{i}" not in ma.naming or sample[0] == sample[1]
                                       or not all(_IDENTIFIER.match(x) for x in sample)):
                errors.append(f"{name}/{ma.name}.naming: 복제본의 이름의 틀 {ma.naming!r} 는 쓸 수 없다. "
                              "{i} 를 담아 번호마다 다른 이름을 내고, 그 이름은 글자, 숫자, 밑줄이어야 한다")
            card, where = ma.cardinality, f"{name}/{ma.name}.cardinality"
            if isinstance(card, m.VarCard):
                var = doc.variables.get(card.var)
                if var is None:
                    errors.append(f"{where}: 정의되지 않은 변수 {card.var}")
                elif not _counts(var):
                    errors.append(f"{where}: 개수 변수 {card.var} 의 값은 0 이상의 정수여야 한다")

            elif isinstance(card, m.Fixed):
                if not _count(card.n):
                    errors.append(f"{where}: 개수는 0 이상의 정수여야 한다: {card.n!r}")

            elif not _count(card.min) or (card.max is not None and (not _count(card.max) or card.max < card.min)):
                errors.append(f"{where}: 개수의 범위는 0 이상의 정수이고 비어 있지 않아야 한다: "
                              f"min {card.min!r}, max {card.max!r}")

            expr_vars(ma.rule, f"{name}/{ma.name}.rule")
            if ma.pattern is not None and ma.part.def_name in ents:
                # 자리표시자 {part} 를 실제 부분 이름으로 치환한 뒤 결합을 검사한다
                part = m.PartRef(ma.part.def_name, ma.part.alias or "{part}")
                all_c = (ma.pattern.fan_out + ma.pattern.fan_in + ma.pattern.custom
                         + ma.pattern.first + ma.pattern.last)
                _check_couplings(doc, ent, (part,), all_c, f"{name}/{ma.name}", errors)
        # specialization
        for sp in ent.specializations.values():
            if not sp.alternatives:
                errors.append(f"{name}/{sp.name}: 대안이 하나도 없다")
            twice = sorted({a for a in sp.alternatives if sp.alternatives.count(a) > 1})
            if twice:                                         # 같은 대안을 두 번 적으면 선택지가 하나인지 둘인지 정해지지 않는다
                errors.append(f"{name}/{sp.name}: 대안 {twice} 를 두 번 적었다")
            for alt in sp.alternatives:
                ref_ok(alt, f"{name}/{sp.name}.alternatives")
                if alt in ents and chain(alt) is not None and name not in chain(alt):
                    errors.append(f"{name}/{sp.name}: 대안 {alt} 가 {name} 을 extends 하지 않는다")
            if sp.default is not None and sp.default not in sp.alternatives:
                errors.append(f"{name}/{sp.name}.default: {sp.default} 는 대안이 아니다")
            rule = sp.select
            while rule is not None:
                expr_vars(rule.when, f"{name}/{sp.name}.select")
                if rule.then not in sp.alternatives:
                    errors.append(f"{name}/{sp.name}.select: {rule.then} 는 대안이 아니다")
                nxt = rule.otherwise
                if isinstance(nxt, str) and nxt not in sp.alternatives:
                    errors.append(f"{name}/{sp.name}.select: {nxt} 는 대안이 아니다")
                rule = nxt if isinstance(nxt, m.SelectRule) else None
        # 스테레오타입 일관성
        if ent.stereotype == m.Stereotype.ATOMIC and not ent.is_leaf:
            errors.append(f"{name}: atomic 인데 분해를 가진다")
        for ltype, targets in ent.links.items():
            for t in targets:
                if t not in ents:
                    errors.append(f"{name}.links.{ltype}: 정의되지 않은 엔티티 {t}")
        if ent.stereotype == m.Stereotype.VOID:
            if ent.ports or ent.attributes or ent.decomposition_names or ent.fields or ent.links:
                errors.append(f"{name}: 없음 대안은 포트, 속성, 필드, 관계, 분해를 가질 수 없다")
            if ent.root:
                errors.append(f"{name}: 없음 대안은 뿌리가 될 수 없다")
        for asp in ent.aspects.values():
            for p in asp.parts:
                if p.def_name in ents and ents[p.def_name].stereotype == m.Stereotype.VOID:
                    errors.append(f"{name}/{asp.name}: 없음 대안 {p.def_name} 은 부분이 될 수 없다")
        for ma in ent.multi_aspects.values():
            if ma.part.def_name in ents and ents[ma.part.def_name].stereotype == m.Stereotype.VOID:
                errors.append(f"{name}/{ma.name}: 없음 대안 {ma.part.def_name} 은 부분이 될 수 없다")

    # 한 구성요소에 같은 정의가 두 번 합쳐질 수 없다. 한 엔티티의 서로 다른 specialization 은 함께 골라지므로,
    # 둘이 같은 정의에 닿으면 그 정의가 병합체에 두 번 든다. 대수는 그것을 분해 둘, 바인딩 둘로 보고
    # 고전 절차는 하나로 본다 (18 문서 7절)
    below: dict = {}

    def merged_under(d: str, trail: tuple = ()) -> frozenset:
        """정의 d 를 대안으로 고르면 함께 합쳐질 수 있는 정의들. d 자신을 포함한다."""
        if d in below:
            return below[d]
        if d in trail or d not in ents:                       # 순환과 없는 정의는 다른 검사가 알린다
            return frozenset({d})
        out = {d}
        for sp in ents[d].specializations.values():
            for alt in sp.alternatives:
                out |= merged_under(alt, trail + (d,))
        below[d] = frozenset(out)
        return below[d]

    for name, ent in ents.items():
        reach = {sp.name: frozenset().union(*(merged_under(alt, (name,)) for alt in sp.alternatives))
                 for sp in ent.specializations.values()}
        seen = sorted(reach)
        for i, s in enumerate(seen):
            for t in seen[i + 1:]:
                twice = sorted(reach[s] & reach[t])
                if twice:
                    errors.append(f"{name}: specialization {s} 와 {t} 가 같은 정의 {twice} 에 닿는다. "
                                  "한 구성요소에 같은 정의가 두 번 합쳐질 수 없다")

    for c in doc.constraints:
        for e in (c.when, c.require, c.forbid):
            expr_vars(e, f"constraint {c.name}", constraint=True)

    for vname, var in doc.variables.items():
        if not _IDENTIFIER.match(str(vname)):
            errors.append(f"variables.{vname}: 이름 {vname!r} 는 쓸 수 없다. 글자, 숫자, 밑줄로 쓰고 숫자로 시작하지 않는다")
        if (isinstance(var.domain, m.Range) and var.domain.min > var.domain.max) or \
                (isinstance(var.domain, m.EnumSet) and not var.domain.values):
            errors.append(f"variables.{vname}: 가질 수 있는 값이 하나도 없다")
        if isinstance(var.domain, m.EnumSet):                 # 값은 글자로 적어 구별한다 (theory.md 의 W5)
            written = [str(v) for v in var.domain.values]
            twice = sorted({w for w in written if written.count(w) > 1})
            if twice:
                errors.append(f"variables.{vname}: 값 {twice} 가 글자로 적으면 같다. 값은 서로 달라야 한다")
            # 값으로도 서로 달라야 한다. 0 과 false, 1 과 true, 1 과 1.0 은 글자는 달라도 같은 값으로 읽힌다.
            # 그런 값들을 함께 두면 선택 지점 표가 둘을 구별하지 못한다
            first: dict = {}                                  # 값에서 처음 적힌 것으로. 값이 많아도 한 번만 돈다
            alike = []
            for v in var.domain.values:
                try:
                    if v in first and str(first[v]) != str(v):
                        alike.append((first[v], v))
                    first.setdefault(v, v)
                except TypeError:
                    continue
            if alike:
                errors.append(f"variables.{vname}: 값 {alike[0][0]!r} 와 {alike[0][1]!r} 는 같은 값으로 읽힌다. "
                              "값은 서로 달라야 한다")
        # 범위는 값을 하나씩 늘어놓아 쓴다. 지나치게 넓은 범위는 기억을 다 쓴다. 넓은 범위가 필요한 값은 변수가 아니라
        # 속성으로 두고 결정 집합의 set 으로 준다
        if isinstance(var.domain, m.Range) and var.type == m.ScalarType.INT and _whole(var.domain.min) \
                and _whole(var.domain.max) and var.domain.max - var.domain.min >= RANGE_LIMIT:
            errors.append(f"variables.{vname}: 범위의 값이 {RANGE_LIMIT}개를 넘는다. 변수는 구조를 가르는 값에 쓴다. "
                          "넓은 범위의 값은 속성으로 두고 결정 집합의 set 으로 준다")
        # 기본값은 가질 수 있는 값 가운데 하나여야 한다. 아니면 기본값을 쓰는 사례가 "결정이 모자라다"만 듣는다
        if var.default is not None and not _in_domain(var, var.default):
            errors.append(f"variables.{vname}: 기본값 {var.default!r} 이 가질 수 있는 값에 들지 않는다")

    # strict hierarchy: 펼친 경로에서 같은 정의 반복 금지
    try:
        # 뿌리에서 닿는 정의들만 본다. 닿지 않는 정의는 문서의 뜻에 관여하지 않는다 (theory.md 의 W1).
        # 편집 중인 문서에는 쓰이지 않는 정의가 흔하고, 편집기의 진단은 그것을 경고(UNUSED)로만 알린다
        _check_strict_hierarchy(doc, doc.root.name, (), errors)
    except ValueError:
        pass

    if errors:
        raise LoadError("무결성 오류 " + str(len(errors)) + "건:\n  " + "\n  ".join(errors))


RANGE_LIMIT = 100000               # 정수 변수의 범위가 가질 수 있는 값의 수의 한도


def _whole(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool)


def _in_domain(var: m.Variable, value) -> bool:
    """값이 변수가 가질 수 있는 값 가운데 하나인가. 범위가 없는 변수는 타입만 본다."""
    if isinstance(var.domain, m.EnumSet):
        return any(value == v and str(value) == str(v) for v in var.domain.values)
    if isinstance(var.domain, m.Range):
        try:
            return fits(value, var.type) and var.domain.min <= value <= var.domain.max
        except TypeError:
            return False
    return fits(value, var.type)


def _count(n) -> bool:
    """복제본의 수로 쓸 수 있는 값인가. 0 이상의 정수다. 참과 거짓은 아니다."""
    return isinstance(n, int) and not isinstance(n, bool) and n >= 0


def _counts(var: m.Variable) -> bool:
    """개수로 쓰는 변수의 값이 모두 복제본의 수가 될 수 있는가."""
    if isinstance(var.domain, m.EnumSet):
        return all(_count(v) for v in var.domain.values)
    if isinstance(var.domain, m.Range):
        return var.type == m.ScalarType.INT and _count(var.domain.min)
    return var.type == m.ScalarType.INT                  # 범위가 없으면 펼칠 때 유한 범위를 요구한다


def selected_target(doc: m.SesDocument, e: m.Selected, def_name: str, group: str) -> tuple:
    """selected 가 정의 def_name 안에서 가리키는 것: (종류, 선택지). 가리키는 것이 없으면 (None, 까닭).

    종류는 spec(대안), count(multi-aspect의 개수), aspect(분해의 이름) 가운데 하나다.
    """
    ent = doc.entities.get(def_name)
    if ent is None:
        return None, f"selected 가 가리키는 정의 {def_name} 이 없다"
    if not group:
        if e.choice in ent.aspects or e.choice in ent.multi_aspects:
            return "aspect", e.choice
        return None, f"selected: {def_name} 에 분해 {e.choice} 가 없다"
    if group in ent.specializations:
        if e.choice in ent.specializations[group].alternatives:
            return "spec", e.choice
        return None, f"selected: {def_name}/{group} 에 대안 {e.choice} 가 없다"
    if group in ent.multi_aspects:
        try:
            return "count", int(e.choice)
        except (TypeError, ValueError):
            return None, f"selected: {def_name}/{group} 의 선택지는 개수(정수)여야 한다: {e.choice!r}"
    return None, f"selected: {def_name} 에 specialization 이나 multi-aspect {group} 이 없다"


def selected_problem(doc: m.SesDocument, e: m.Selected) -> Optional[str]:
    """정의 수준의 selected 가 가리키는 곳이 문서에 있는가. 없으면 까닭을 돌려준다."""
    def_name, _, group = e.node.partition("/")
    kind, why = selected_target(doc, e, def_name, group)
    return why if kind is None else None


def reach_ports(doc, def_name: str, seen: frozenset = frozenset()) -> dict:
    """정의가 놓인 구성요소가 가질 수 있는 포트: 이름에서 선언들로. 그 정의가 적은 것이 앞에 온다.

    구성요소의 인터페이스는 구성원들의 선언을 합친 것이다(theory.md 정의 12). 구성원은 그 정의와, 그 정의의
    specialization 에서 고른 대안들이다. 그래서 대안만 적은 포트도 그 대안이 골라진 변이에서는 인터페이스에 든다.
    extends 로 가리킨 정의의 포트는 여기 들지 않는다. 그것은 대안으로 골라져 합쳐질 때만 함께 있다. 부분으로
    직접 놓인 정의가 그것을 물려받는가는 정해지지 않았다(ROADMAP 의 정해야 할 것 5).
    """
    e = doc.entities.get(def_name)
    if e is None or def_name in seen:
        return {}
    out = {n: [p] for n, p in e.ports.items()}
    for sp in e.specializations.values():
        for a in sp.alternatives:
            for n, found in reach_ports(doc, a, seen | {def_name}).items():
                out.setdefault(n, []).extend(found)
    return out


def _check_couplings(doc, ent, parts, couplings, where, errors) -> None:
    """결합의 끝이 가리키는 부분과 포트가 있을 수 있는가. 어느 변이에도 없는 포트만 여기서 거부한다.

    어떤 대안에만 있는 포트는 받는다. 그 대안이 골라지지 않은 변이에서 결합이 살아 있으면 족의 검사(C1)가 알린다.
    """
    ents = doc.entities
    try:
        own_ports = doc.all_ports(ent.name)       # 대안으로 골라져 합쳐질 때는 바탕의 포트도 자신의 포트다
    except (KeyError, ValueError):
        own_ports = dict(ent.ports)   # extends 오류는 별도로 보고된다
    for n, found in reach_ports(doc, ent.name).items():
        own_ports.setdefault(n, found[0])
    part_defs = {p.part_name: p.def_name for p in parts}

    def resolve(ref: m.PortRef, end: str):
        if ref.part is None:
            port = own_ports.get(ref.port)
            if port is None:
                errors.append(f"{where}: 자신의 포트 {ref.port} 가 없다")
                return None
            want = m.Direction.IN if end == "src" else m.Direction.OUT
            if port.direction != want:
                errors.append(f"{where}: 외부 포트 {ref.port} 의 방향이 맞지 않다")
            return port
        d = part_defs.get(ref.part)
        if d is None or d not in ents:
            hint = ""
            if ref.part in set(part_defs.values()):          # 부분을 정의의 이름으로 적었다
                names = sorted(n for n, x in part_defs.items() if x == ref.part)
                hint = (". 복제된 부분은 결합에서 {part} 로 적는다" if names == ["{part}"] else
                        f". 정의 {ref.part} 는 여기서 {names} 라는 이름의 부분이다")
            errors.append(f"{where}: 부분 {ref.part} 가 없다{hint}")
            return None
        found = list(reach_ports(doc, d).get(ref.port, ()))
        with contextlib.suppress(KeyError, ValueError):
            inherited = doc.all_ports(d).get(ref.port)       # extends 로 가리킨 정의의 포트. 지금까지 받아 온 대로 받는다
            if inherited is not None and not found:
                found = [inherited]
        if not found:
            errors.append(f"{where}: {ref.part}({d}) 에 포트 {ref.port} 가 없다")
            return None
        if len({(p.type, p.direction) for p in found}) > 1:
            return None                                      # 대안마다 선언이 다르다. 변이마다의 검사(C2, C3)가 본다
        port = found[0]
        want = m.Direction.OUT if end == "src" else m.Direction.IN
        if port.direction != want:
            errors.append(f"{where}: {ref} 의 방향이 맞지 않다")
        return port

    for c in couplings:
        a = resolve(c.src, "src")
        b = resolve(c.dst, "dst")
        if a and b and a.type != b.type:
            errors.append(f"{where}: 결합 {c.src} 에서 {c.dst} 의 포트 타입이 다르다 ({a.type}, {b.type})")


def _check_strict_hierarchy(doc, def_name, path, errors, done=None) -> None:
    """쓰임 관계에 순환이 없는가 (theory.md 의 W1). 한 번 끝까지 본 정의는 다시 보지 않는다.

    같은 정의를 여러 곳에서 쓰는 깊은 문서는 경로의 수가 지수적이다. 경로마다 내려가면 끝나지 않는다.
    """
    done = set() if done is None else done
    if def_name in path:
        errors.append("strict hierarchy 위반: " + "/".join(path + (def_name,)))
        return
    if def_name in done:
        return
    ent = doc.entities.get(def_name)
    if ent is None:
        return
    nxt = path + (def_name,)
    for asp in ent.aspects.values():
        for p in asp.parts:
            _check_strict_hierarchy(doc, p.def_name, nxt, errors, done)
    for ma in ent.multi_aspects.values():
        _check_strict_hierarchy(doc, ma.part.def_name, nxt, errors, done)
    for sp in ent.specializations.values():
        for alt in sp.alternatives:
            _check_strict_hierarchy(doc, alt, nxt, errors, done)
    done.add(def_name)
