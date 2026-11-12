"""정준 SES 문서(SesDocument)와 가지치기 대수(algebra) 사이의 다리.

- unfold(doc): 정의 테이블을 뿌리에서 펼쳐 SES 트리와 제약식을 만든다.
  multi-aspect는 개수별 aspect로 전개하고, 변수는 뿌리의 specialization으로,
  선택 규칙과 선택 제약은 제약식으로 부호화한다.
- pruning_patterns(doc): 접힌 형태의 가지치기 SES를 정의별 높이 2 패턴의
  모음으로 바꾼다. 각 패턴은 그 정의의 모든 출현에 적용된다.

기본값(default)과 우선순위(priority)는 변이 공간을 바꾸지 않는 선호이므로
여기서는 다루지 않는다.
"""

from __future__ import annotations

import operator

from . import model as m
from .algebra import (ASP, ENT, SPEC, SES, TRUE, AlgebraError, Tree,
                      f_and, f_imp, f_not, f_or, sel)

_OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le,
        "gt": operator.gt, "ge": operator.ge, "in": lambda v, c: v in c}


def var_node(name: str) -> str:
    return "$" + name


def _domain(doc: m.SesDocument, name: str) -> list:
    var = doc.variables[name]
    if isinstance(var.domain, m.EnumSet):
        return list(var.domain.values)
    if isinstance(var.domain, m.Range) and var.type == m.ScalarType.INT:
        return list(range(int(var.domain.min), int(var.domain.max) + 1))
    if var.type == m.ScalarType.BOOL:
        return [True, False]
    raise AlgebraError(f"변수 {name} 에 유한 범위가 필요하다")


def _card_set(doc: m.SesDocument, ma: m.MultiAspect) -> list:
    c = ma.cardinality
    if isinstance(c, m.Fixed):
        return [c.n]
    if isinstance(c, m.VarCard):
        return _domain(doc, c.var)
    if c.max is None:
        raise AlgebraError(f"multi-aspect {ma.name} 의 개수에 상한이 필요하다")
    return list(range(c.min, c.max + 1))


def _replica_name(ma: m.MultiAspect, i: int, n: int) -> str:
    return ma.naming.format(i=i, n=n, part=ma.part.part_name)


def unfold(doc: m.SesDocument) -> SES:
    root = (doc.root.name,)
    kinds: dict = {}
    clauses: list = []

    def value(name: str, v) -> tuple:
        return root + (var_node(name), str(v))

    def tr(e: m.Expr):
        if isinstance(e, m.Compare) and isinstance(e.left, m.Var) and isinstance(e.right, m.Const):
            name, c, op = e.left.name, e.right.value, _OPS[e.op]
            return f_or(*(sel(value(name, v)) for v in _domain(doc, name) if op(v, c)))
        if isinstance(e, m.And):
            return f_and(*(tr(x) for x in e.items))
        if isinstance(e, m.Or):
            return f_or(*(tr(x) for x in e.items))
        if isinstance(e, m.Not):
            return f_not(tr(e.item))
        raise AlgebraError(f"분석 가능 단편 밖의 표현식: {e!r}")

    def select(rule: m.SelectRule, sp_path: tuple):
        cond = tr(rule.when)
        other = rule.otherwise
        if isinstance(other, m.SelectRule):
            rest = select(other, sp_path)
        elif other is None:
            rest = TRUE
        else:
            rest = sel(sp_path + (other,))
        return f_and(f_imp(cond, sel(sp_path + (rule.then,))), f_imp(f_not(cond), rest))

    def rec(def_name: str, path: tuple) -> None:
        kinds[path] = ENT
        e = doc.entities[def_name]
        for sp in e.specializations.values():
            sp_path = path + (sp.name,)
            kinds[sp_path] = SPEC
            for alt in sp.alternatives:
                rec(alt, sp_path + (alt,))
            if sp.select is not None:
                clauses.append(f_imp(sel(sp_path), select(sp.select, sp_path)))
        for a in e.aspects.values():
            a_path = path + (a.name,)
            kinds[a_path] = ASP
            for part in a.parts:
                rec(part.def_name, a_path + (part.part_name,))
            if a.rule is not None:
                clauses.append(f_imp(f_and(sel(path), tr(a.rule)), sel(a_path)))
        for ma in e.multi_aspects.values():
            for n in _card_set(doc, ma):
                a_path = path + (f"{ma.name}[{n}]",)
                kinds[a_path] = ASP
                for i in range(n):
                    rec(ma.part.def_name, a_path + (_replica_name(ma, i, n),))
                if isinstance(ma.cardinality, m.VarCard):
                    clauses.append(f_imp(sel(a_path), sel(value(ma.cardinality.var, n))))

    rec(doc.root.name, root)
    for name in doc.variables:
        s = root + (var_node(name),)
        kinds[s] = SPEC
        for v in _domain(doc, name):
            kinds[s + (str(v),)] = ENT
    for c in doc.constraints:
        body = f_and(*([tr(c.require)] if c.require is not None else []),
                     *([f_not(tr(c.forbid))] if c.forbid is not None else []))
        clauses.append(f_imp(tr(c.when), body) if c.when is not None else body)
    return SES(Tree(kinds), f_and(*clauses))


def pruning_patterns(doc: m.SesDocument) -> list:
    """접힌 형태의 가지치기 SES를 정의별 패턴으로 바꾼다."""
    if doc.variables or doc.constraints:
        raise AlgebraError("접힌 가지치기 SES의 변수와 제약은 아직 지원하지 않는다")
    out = []
    for name, e in doc.entities.items():
        kinds: dict = {(name,): ENT}
        for sp in e.specializations.values():
            if sp.select is not None:
                raise AlgebraError("접힌 가지치기 SES의 선택 규칙은 아직 지원하지 않는다")
            kinds[(name, sp.name)] = SPEC
            for alt in sp.alternatives:
                kinds[(name, sp.name, alt)] = ENT
        for a in e.aspects.values():
            kinds[(name, a.name)] = ASP
        for ma in e.multi_aspects.values():
            for n in _card_set(doc, ma):
                kinds[(name, f"{ma.name}[{n}]")] = ASP
        if len(kinds) > 1:
            out.append(SES(Tree(kinds)))
    return out
