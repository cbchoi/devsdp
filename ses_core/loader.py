"""정준 YAML/JSON 을 SesDocument 로 적재하고 참조 무결성을 검사한다.

스키마 검증(형태)은 jsonschema 로 따로 하고, 여기서는 이름 해석과
기본 불변식(댕글링 참조, extends 순환, 루트 유일성, 포트 타입 일치)을 검사한다.
공리 검증 전체는 ses_ops 의 AxiomValidator 과제다.
"""

from __future__ import annotations

from typing import Any

from . import model as m


class LoadError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 표현식: 저장 축약형을 AST 로 펼친다
# ---------------------------------------------------------------------------

_CMP_OPS = ("eq", "ne", "lt", "le", "gt", "ge", "in")


def parse_expr(d: Any) -> m.Expr:
    if not isinstance(d, dict):
        raise LoadError(f"표현식은 객체여야 한다: {d!r}")
    if "var" in d:
        for op in _CMP_OPS:
            if op in d:
                return m.Compare(op, m.Var(d["var"]), m.Const(d[op]))
        raise LoadError(f"var 비교 연산자가 없다: {d!r}")
    if "all" in d:
        return m.And(tuple(parse_expr(x) for x in d["all"]))
    if "any" in d:
        return m.Or(tuple(parse_expr(x) for x in d["any"]))
    if "not" in d:
        return m.Not(parse_expr(d["not"]))
    if "selected" in d:
        node, _, choice = d["selected"].partition("=")
        if not choice:
            raise LoadError(f"selected 는 'NodeId=choice' 형식이어야 한다: {d['selected']}")
        return m.Selected(node, choice)
    if "call" in d:
        return m.Call(d["call"], tuple(parse_expr(a) if isinstance(a, dict) else m.Const(a)
                                       for a in d.get("args", [])))
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
    return m.Port(name, d["type"], m.Direction(d["direction"]), d.get("doc"))


def _attribute(name: str, d: dict) -> m.Attribute:
    return m.Attribute(
        name, _scalar(d["type"]), d.get("default"), d.get("unit"),
        parse_expr(d["expr"]) if "expr" in d else None,
        tuple(d["values"]) if "values" in d else None, d.get("doc"))


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
                             cp("fan_out"), cp("fan_in"), cp("between"), cp("custom"))


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

    def expr_vars(e: m.Expr | None, where: str) -> None:
        if e is None:
            return
        if isinstance(e, m.Var) and e.name not in doc.variables:
            errors.append(f"{where}: 정의되지 않은 변수 {e.name}")
        for child in getattr(e, "items", ()) or ():
            expr_vars(child, where)
        for attr in ("left", "right", "item"):
            if hasattr(e, attr):
                expr_vars(getattr(e, attr), where)
        if isinstance(e, m.Call):
            for a in e.args:
                expr_vars(a, where)

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
        # 포트 타입
        for p in ent.ports.values():
            if p.type not in doc.port_types:
                errors.append(f"{name}.ports.{p.name}: 정의되지 않은 포트 타입 {p.type}")
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
            if isinstance(ma.cardinality, m.VarCard) and ma.cardinality.var not in doc.variables:
                errors.append(f"{name}/{ma.name}.cardinality: 정의되지 않은 변수 {ma.cardinality.var}")
            expr_vars(ma.rule, f"{name}/{ma.name}.rule")
            if ma.pattern is not None and ma.part.def_name in ents:
                # 자리표시자 {part} 를 실제 부분 이름으로 치환한 뒤 결합을 검사한다
                part = m.PartRef(ma.part.def_name, ma.part.alias or "{part}")
                all_c = ma.pattern.fan_out + ma.pattern.fan_in + ma.pattern.custom
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

    for c in doc.constraints:
        for e in (c.when, c.require, c.forbid):
            expr_vars(e, f"constraint {c.name}")

    # strict hierarchy: 펼친 경로에서 같은 정의 반복 금지
    try:
        _check_strict_hierarchy(doc, doc.root.name, (), errors)
    except ValueError:
        pass

    if errors:
        raise LoadError("무결성 오류 " + str(len(errors)) + "건:\n  " + "\n  ".join(errors))


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
