"""정준 YAML/JSON 을 SesDocument 로 적재하고 참조 무결성을 검사한다.

스키마 검증(형태)은 jsonschema 로 따로 하고, 여기서는 이름 해석과
기본 불변식(댕글링 참조, extends 순환, 루트 유일성, 포트 타입 일치)을 검사한다.
공리 검증 전체는 ses_ops 의 AxiomValidator 과제다.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import model as m
from .skeleton import MARKERS


_IDENTIFIER = re.compile(r"[A-Za-z_가-힣][A-Za-z0-9_가-힣]*\Z")       # 스키마의 identifier


class LoadError(ValueError):
    pass


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
        raise LoadError(f"알 수 없는 스칼라 타입: {t}")


def _variable(name: str, d: dict) -> m.Variable:
    domain = None
    if "range" in d:
        domain = m.Range(d["range"][0], d["range"][1])
    elif "values" in d:
        domain = m.EnumSet(tuple(d["values"]))
    return m.Variable(name, _scalar(d["type"]), d.get("default"), domain, d.get("doc"))


def _port_type(name: str, d: dict) -> m.PortType:
    return m.PortType(name, {k: _scalar(v) for k, v in (d.get("fields") or {}).items()}, d.get("doc"))


def _port(name: str, d: dict) -> m.Port:
    return m.Port(name, d["type"], m.Direction(d["direction"]), d.get("doc"),
                  bool(d.get("required", False)))


def _attribute(name: str, d: dict) -> m.Attribute:
    if "expr" in d and "each" in d:
        raise LoadError(f"속성 {name}: expr 과 each 를 함께 쓸 수 없다")
    if "each" in d and not isinstance(d["each"], list):
        raise LoadError(f"속성 {name}: each 는 복제본마다의 값을 적은 목록이어야 한다")
    return m.Attribute(
        name, _scalar(d["type"]), d.get("default"), d.get("unit"),
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
    return m.Coupling(m.PortRef.parse(d["from"]), m.PortRef.parse(d["to"]), d.get("doc"))


def _part_ref(x: Any) -> m.PartRef:
    if isinstance(x, str):
        return m.PartRef(x)
    return m.PartRef(x["def"], x.get("alias"))


def _aspect(name: str, d: dict) -> m.Aspect:
    return m.Aspect(
        name, tuple(_part_ref(p) for p in d["parts"]),
        tuple(_coupling(c) for c in d.get("couplings", [])),
        parse_expr(d["rule"]) if "rule" in d else None,
        d.get("priority"), d.get("doc"))


def _cardinality(x: Any) -> m.Cardinality:
    if isinstance(x, int):
        return m.Fixed(x)
    if "var" in x:
        return m.VarCard(x["var"])
    return m.RangeCard(x["min"], x.get("max"))


def _pattern(d: dict) -> m.CouplingPattern:
    cp = lambda key: tuple(_coupling(c) for c in d.get(key, []))  # noqa: E731
    return m.CouplingPattern(m.PatternKind(d.get("pattern", "custom")),
                             cp("fan_out"), cp("fan_in"), cp("between"), cp("custom"),
                             cp("first"), cp("last"))


def _multi_aspect(name: str, d: dict) -> m.MultiAspect:
    return m.MultiAspect(
        name, _part_ref(d["part"]), _cardinality(d["cardinality"]),
        d.get("naming", "{part}_{i}"),
        _pattern(d["couplings"]) if "couplings" in d else None,
        parse_expr(d["rule"]) if "rule" in d else None,
        d.get("priority"), d.get("doc"))


def _select_rule(d: dict) -> m.SelectRule:
    other = d.get("else")
    if isinstance(other, dict):
        other = _select_rule(other)
    return m.SelectRule(parse_expr(d["when"]), d["then"], other)


def _specialization(name: str, d: dict) -> m.Specialization:
    return m.Specialization(
        name, tuple(d["alternatives"]),
        _select_rule(d["select"]) if "select" in d else None,
        d.get("default"), d.get("doc"))


def _entity(name: str, d: dict) -> m.EntityDef:
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
    g = lambda k: parse_expr(d[k]) if k in d else None  # noqa: E731
    return m.Constraint(d["name"], g("when"), g("require"), g("forbid"), d.get("doc"))


# ---------------------------------------------------------------------------
# 문서 적재와 무결성 검사
# ---------------------------------------------------------------------------

def load_ses_dict(d: dict) -> m.SesDocument:
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
    import yaml  # 지연 임포트. 코어 자료구조 자체는 yaml 에 의존하지 않는다
    with open(path, encoding="utf-8") as f:
        return load_ses_dict(yaml.safe_load(f))


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
            errors.append(f"{where}: 정의되지 않은 엔티티 참조 {name}")

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
            except (ValueError, KeyError) as e:
                errors.append(f"{name}: {e}")
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
            if x not in MARKERS and not _IDENTIFIER.match(str(x)):
                errors.append(f"{name}: 이름 {x!r} 는 쓸 수 없다. 글자, 숫자, 밑줄로 쓰고 숫자로 시작하지 않는다")
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
            for alt in sp.alternatives:
                ref_ok(alt, f"{name}/{sp.name}.alternatives")
                if alt in ents and name not in doc.ancestors(alt):
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
        if isinstance(var.domain, m.EnumSet):                 # 값은 글자로 적어 구별한다 (theory.md 의 W5)
            written = [str(v) for v in var.domain.values]
            twice = sorted({w for w in written if written.count(w) > 1})
            if twice:
                errors.append(f"variables.{vname}: 값 {twice} 가 글자로 적으면 같다. 값은 서로 달라야 한다")

    # strict hierarchy: 펼친 경로에서 같은 정의 반복 금지
    try:
        _check_strict_hierarchy(doc, doc.root.name, (), errors)
    except ValueError:
        pass

    if errors:
        raise LoadError("무결성 오류 " + str(len(errors)) + "건:\n  " + "\n  ".join(errors))


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


def _check_couplings(doc, ent, parts, couplings, where, errors) -> None:
    ents = doc.entities
    try:
        own_ports = doc.all_ports(ent.name)
    except (KeyError, ValueError):
        own_ports = dict(ent.ports)   # extends 오류는 별도로 보고된다
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
            errors.append(f"{where}: 부분 {ref.part} 가 없다")
            return None
        port = doc.all_ports(d).get(ref.port)
        if port is None:
            errors.append(f"{where}: {ref.part}({d}) 에 포트 {ref.port} 가 없다")
            return None
        want = m.Direction.OUT if end == "src" else m.Direction.IN
        if port.direction != want:
            errors.append(f"{where}: {ref} 의 방향이 맞지 않다")
        return port

    for c in couplings:
        a = resolve(c.src, "src")
        b = resolve(c.dst, "dst")
        if a and b and a.type != b.type:
            errors.append(f"{where}: 결합 {c.src} 에서 {c.dst} 의 포트 타입이 다르다 ({a.type}, {b.type})")


def _check_strict_hierarchy(doc, def_name, path, errors) -> None:
    if def_name in path:
        errors.append("strict hierarchy 위반: " + "/".join(path + (def_name,)))
        return
    ent = doc.entities.get(def_name)
    if ent is None:
        return
    nxt = path + (def_name,)
    for asp in ent.aspects.values():
        for p in asp.parts:
            _check_strict_hierarchy(doc, p.def_name, nxt, errors)
    for ma in ent.multi_aspects.values():
        _check_strict_hierarchy(doc, ma.part.def_name, nxt, errors)
    for sp in ent.specializations.values():
        for alt in sp.alternatives:
            _check_strict_hierarchy(doc, alt, nxt, errors)
