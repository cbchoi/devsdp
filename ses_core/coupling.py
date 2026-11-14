"""결합을 가진 SES와 족 수준 적격성의 참조 구현
(docs/ses-platform/08_coupling_wellformedness.md).

algebra.py 의 SES 트리에 포트, 없음 대안, 결합을 주석으로 붙이고 다음을 정의한다.
- 병합체(cluster): 구성 노드와 그 아래에서 선택된 대안들을 합친 것.
- 변이 적격성 WF(V): 변이 하나가 조립 가능한 결합 모델을 낳는가 (조건 C0 ~ C4).
- 특성식 psi(T): 변이 V가 적격인 것과 V가 psi를 만족하는 것이 같다.
- 족 수준 적격성 FW(S): S의 모든 변이가 적격.
- 적격성 가지치기 SES와 적격 핵 wf(S) = S ▷ W.
- 국소 충분조건(정적 규율)과 multi-aspect 결합 틀.

전수 열거 기반이며 효율을 고려하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .algebra import (ASP, ENT, SPEC, SES, AlgebraError, Tree, f_and, f_imp, f_not, f_or,
                      holds, prune, sel, sem)
from .extension import Extension, View
from .skeleton import component_of, components, is_component, members, owner  # noqa: F401

IN, OUT = "in", "out"
SELF = None          # 결합 끝점의 "자기 자신" (결합 모델의 외부 포트)
FALSE = ("or",)


@dataclass(frozen=True)
class PortDecl:
    type: str
    direction: str
    required: bool = False


@dataclass(frozen=True)
class Ann:
    """SES 트리의 주석. 경로를 열쇠로 하며 가지치기에 대해 불변이다.

    ports: 엔티티 노드에서 {포트 이름: PortDecl} 로.
    void:  없음 대안 노드의 집합.
    coup:  aspect 노드에서 결합의 튜플로. 결합은 ((누구, 포트), (누구, 포트)).
           누구는 SELF 또는 그 aspect의 부분 이름.
    """
    ports: Mapping[tuple, Mapping[str, PortDecl]] = field(default_factory=dict)
    void: frozenset = frozenset()
    coup: Mapping[tuple, tuple] = field(default_factory=dict)


def validate(T: Tree, ann: Ann) -> None:
    for e in ann.ports:
        if e in T.nodes and T.kind(e) != ENT:
            raise AlgebraError(f"포트는 엔티티에만 붙는다: {e}")
    for v in ann.void:
        if v not in T.nodes:
            continue
        if len(v) == 1 or T.kind(v[:-1]) != SPEC:
            raise AlgebraError(f"없음 대안은 specialization의 대안이어야 한다: {v}")
        if T.children(v) or ann.ports.get(v):
            raise AlgebraError(f"없음 대안은 포트와 하위 구조를 가질 수 없다: {v}")
    for a, ks in ann.coup.items():
        if a not in T.nodes:
            continue
        if T.kind(a) != ASP:
            raise AlgebraError(f"결합은 aspect에만 붙는다: {a}")
        names = {q[-1] for q in T.children(a)}
        for (sw, _), (dw, _) in ks:
            for w in (sw, dw):
                if w is not SELF and w not in names:
                    raise AlgebraError(f"{a}: 결합이 가리키는 부분 {w} 가 없다")


def _want(sw, dw, no_self_loop: bool):
    """결합 끝점의 종류에 따라 요구되는 (출발 방향, 도착 방향)."""
    if sw is SELF and dw is SELF:
        return None
    if sw is SELF:
        return (IN, IN)            # 외부 입력 결합
    if dw is SELF:
        return (OUT, OUT)          # 외부 출력 결합
    if sw == dw and no_self_loop:
        return None
    return (OUT, IN)               # 내부 결합


# ---------------------------------------------------------------------------
# 변이 적격성 (정의를 그대로 평가)
# ---------------------------------------------------------------------------

def violations(T: Tree, ann: Ann, V: frozenset, no_self_loop: bool = False) -> list:
    """변이 V의 적격성 위반 목록. 비어 있으면 V는 적격이다."""
    out: list = []
    cache: dict = {}

    def info(e: tuple):
        if e not in cache:
            ms = [y for y in members(T, e) if y in V]
            decls: dict = {}
            for y in ms:
                for p, d in ann.ports.get(y, {}).items():
                    decls.setdefault(p, []).append(d)
            merged = {p: PortDecl(ds[0].type, ds[0].direction, any(d.required for d in ds))
                      for p, ds in decls.items()}
            conflicts = [p for p, ds in decls.items()
                         if len({(d.type, d.direction) for d in ds}) > 1]
            asps = [a for y in ms for a in T.aspects(y) if a in V]
            cache[e] = (merged, conflicts, asps, any(y in ann.void for y in ms))
        return cache[e]

    def check(e: tuple) -> None:
        merged, conflicts, asps, _ = info(e)
        for p in conflicts:
            out.append(("C0", e, f"포트 {p} 의 선언이 충돌한다"))
        if len(asps) > 1:
            out.append(("C0", e, "분해가 둘 이상 선택되었다"))
        for a in asps:
            parts = {q[-1]: q for q in T.children(a)}
            dead = {n for n, q in parts.items() if info(q)[3]}
            live = [k for k in ann.coup.get(a, ()) if not ({k[0][0], k[1][0]} & dead)]
            for (sw, sp), (dw, dp) in live:
                sd = (merged if sw is SELF else info(parts[sw])[0]).get(sp)
                dd = (merged if dw is SELF else info(parts[dw])[0]).get(dp)
                label = f"{sw or 'self'}.{sp} 에서 {dw or 'self'}.{dp}"
                if sd is None or dd is None:
                    out.append(("C1", a, f"{label}: 포트가 없다"))
                    continue
                want = _want(sw, dw, no_self_loop)
                if want is None or (sd.direction, dd.direction) != want:
                    out.append(("C2", a, f"{label}: 방향이 맞지 않다"))
                if sd.type != dd.type:
                    out.append(("C3", a, f"{label}: 타입이 다르다 ({sd.type}, {dd.type})"))
            driven = {k[1] for k in live}
            for n, q in parts.items():
                if n in dead:
                    continue
                for p, d in info(q)[0].items():
                    if d.direction == IN and d.required and (n, p) not in driven:
                        out.append(("C4", a, f"{n}.{p}: 필수 입력 포트에 들어오는 결합이 없다"))
            for p, d in merged.items():
                if d.direction == OUT and d.required and (SELF, p) not in driven:
                    out.append(("C4", a, f"self.{p}: 필수 출력 포트로 나가는 결합이 없다"))
            for n, q in parts.items():
                if n not in dead:
                    check(q)

    if info(T.root)[3]:
        return [("C0", T.root, "뿌리가 없음 대안을 골랐다")]
    check(T.root)
    return out


def wellformed(T: Tree, ann: Ann, V: frozenset, no_self_loop: bool = False) -> bool:
    return not violations(T, ann, V, no_self_loop)


def realize(T: Tree, ann: Ann, V: frozenset) -> dict:
    """변이 V의 실현 모델 R(V): 살아 있는 구성요소의 계층과 결합.

    반환: {구성 노드: {"children": [...], "eic": [...], "eoc": [...], "ic": [...]}}.
    children이 비어 있고 결합도 없는 항목은 원자 구성요소다.
    """
    model: dict = {}

    def cl(e):
        return [y for y in members(T, e) if y in V]

    def void(e):
        return any(y in ann.void for y in cl(e))

    def visit(e):
        node = {"children": [], "eic": [], "eoc": [], "ic": []}
        model[e] = node
        for a in [a for y in cl(e) for a in T.aspects(y) if a in V]:
            parts = {q[-1]: q for q in T.children(a)}
            dead = {n for n, q in parts.items() if void(q)}
            node["children"] += [n for n in parts if n not in dead]
            for (sw, sp), (dw, dp) in ann.coup.get(a, ()):
                if {sw, dw} & dead:
                    continue
                if sw is SELF:
                    node["eic"].append((sp, (dw, dp)))
                elif dw is SELF:
                    node["eoc"].append(((sw, sp), dp))
                else:
                    node["ic"].append(((sw, sp), (dw, dp)))
            for n, q in parts.items():
                if n not in dead:
                    visit(q)

    if not void(T.root):
        visit(T.root)
    return model


# ---------------------------------------------------------------------------
# 특성식: WF(V) 와 V |= psi(T) 가 같다
# ---------------------------------------------------------------------------

def psi(T: Tree, ann: Ann, no_self_loop: bool = False):
    comps = components(T)
    M = {e: members(T, e) for e in comps}
    void = {e: f_or(*(sel(y) for y in M[e] if y in ann.void)) for e in comps}

    def live(e: tuple):
        chain, c = [], e
        while True:
            chain.append(c)
            if len(c) == 1:
                break
            c = owner(T, c[:-1])
        return f_and(sel(e), *(f_not(void[c]) for c in chain))

    clauses = [f_not(void[T.root])]

    for e in comps:
        le = live(e)
        ms = M[e]
        for i, y in enumerate(ms):                       # C0: 포트 선언 충돌
            for y2 in ms[i + 1:]:
                for p, d in ann.ports.get(y, {}).items():
                    d2 = ann.ports.get(y2, {}).get(p)
                    if d2 is not None and (d.type, d.direction) != (d2.type, d2.direction):
                        clauses.append(f_imp(le, f_not(f_and(sel(y), sel(y2)))))
        asps = [(y, a) for y in ms for a in T.aspects(y)]
        for i, (y, a) in enumerate(asps):                # C0: 분해는 하나까지
            for y2, a2 in asps[i + 1:]:
                if y != y2:
                    clauses.append(f_imp(le, f_not(f_and(sel(a), sel(a2)))))

    for a in sorted(n for n in T.nodes if T.kind(n) == ASP):
        e = owner(T, a)
        guard = f_and(live(e), sel(a))
        parts = {q[-1]: q for q in T.children(a)}

        def comp(who):
            return e if who is SELF else parts[who]

        def live_k(k):
            return f_and(*(f_not(void[parts[w]]) for w in {k[0][0], k[1][0]} if w is not SELF))

        ks = ann.coup.get(a, ())
        for k in ks:                                     # C1 ~ C3
            (sw, sp), (dw, dp) = k
            want = _want(sw, dw, no_self_loop)
            witnesses = []
            if want is not None:
                for y in M[comp(sw)]:
                    sd = ann.ports.get(y, {}).get(sp)
                    if sd is None or sd.direction != want[0]:
                        continue
                    for y2 in M[comp(dw)]:
                        dd = ann.ports.get(y2, {}).get(dp)
                        if dd is not None and dd.direction == want[1] and dd.type == sd.type:
                            witnesses.append(f_and(sel(y), sel(y2)))
            clauses.append(f_imp(f_and(guard, live_k(k)), f_or(*witnesses)))
        for n, q in parts.items():                       # C4: 부분의 필수 입력
            for y in M[q]:
                for p, d in ann.ports.get(y, {}).items():
                    if d.direction == IN and d.required:
                        drivers = [live_k(k) for k in ks if k[1] == (n, p)]
                        clauses.append(f_imp(f_and(guard, f_not(void[q]), sel(y)), f_or(*drivers)))
        for y in M[e]:                                   # C4: 자신의 필수 출력
            for p, d in ann.ports.get(y, {}).items():
                if d.direction == OUT and d.required:
                    drivers = [live_k(k) for k in ks if k[1] == (SELF, p)]
                    clauses.append(f_imp(f_and(guard, sel(y)), f_or(*drivers)))

    return f_and(*clauses)


# ---------------------------------------------------------------------------
# 족 수준 적격성, 적격성 가지치기 SES, 적격 핵
# ---------------------------------------------------------------------------

def ill_formed(S: SES, ann: Ann, no_self_loop: bool = False) -> list:
    """적격이 아닌 변이와 그 위반 목록."""
    out = []
    for V in sem(S):
        vs = violations(S.tree, ann, V, no_self_loop)
        if vs:
            out.append((V, vs))
    return out


def family_wellformed(S: SES, ann: Ann, no_self_loop: bool = False) -> bool:
    """FW(S): 모든 변이가 적격. 정의를 그대로 평가한다."""
    return all(wellformed(S.tree, ann, V, no_self_loop) for V in sem(S))


def family_wellformed_by_formula(S: SES, ann: Ann, no_self_loop: bool = False) -> bool:
    """FW(S)를 특성식으로 판정: S의 제약과 psi의 부정을 함께 만족하는 변이가 없다."""
    f = psi(S.tree, ann, no_self_loop)
    return all(holds(f, V) for V in sem(S))


def wf_pattern(T: Tree, ann: Ann, no_self_loop: bool = False) -> SES:
    """적격성 가지치기 SES W: 뿌리만 가진 트리와 특성식."""
    return SES(Tree({T.root: ENT}), psi(T, ann, no_self_loop))


def wf_core(S: SES, ann: Ann, no_self_loop: bool = False) -> Optional[SES]:
    """적격 핵 wf(S) = S ▷ W."""
    return prune(S, wf_pattern(S.tree, ann, no_self_loop))


# ---------------------------------------------------------------------------
# 국소 충분조건 (정적 규율)
# ---------------------------------------------------------------------------

def discipline_violations(T: Tree, ann: Ann, no_self_loop: bool = False) -> list:
    """정적 규율 위반 목록. 비어 있으면 어떤 제약 아래에서도 족 수준 적격이다.

    변이를 열거하지 않고 트리 크기에 대해 다항 시간에 계산한다. 충분조건이며
    필요조건은 아니다.
    """
    out: list = []
    comps = components(T)
    M = {e: members(T, e) for e in comps}
    never_void = {e: not any(y in ann.void for y in M[e]) for e in comps}

    if not never_void[T.root]:
        out.append(("D0", T.root, "뿌리의 병합체에 없음 대안이 있다"))
    for e in comps:
        sigs: dict = {}
        for y in M[e]:
            for p, d in ann.ports.get(y, {}).items():
                sigs.setdefault(p, set()).add((d.type, d.direction))
        for p, s in sigs.items():
            if len(s) > 1:
                out.append(("D0", e, f"포트 {p} 가 병합체 안에서 다르게 선언되었다"))
        if len([y for y in M[e] if T.aspects(y)]) > 1:
            out.append(("D0", e, "병합체 안의 둘 이상의 노드가 분해를 가진다"))

    for a in sorted(n for n in T.nodes if T.kind(n) == ASP):
        e = owner(T, a)
        parts = {q[-1]: q for q in T.children(a)}
        chain, z = [], a[:-1]
        while True:
            chain.append(z)
            if z == e:
                break
            z = z[:-2]

        def decl(who, p):
            if who is SELF:
                for z in chain:                      # a가 선택되면 항상 있는 노드
                    d = ann.ports.get(z, {}).get(p)
                    if d is not None:
                        return d
                return None
            return ann.ports.get(parts[who], {}).get(p)   # 부분의 구성 노드 자체

        ks = ann.coup.get(a, ())
        for (sw, sp), (dw, dp) in ks:
            sd, dd = decl(sw, sp), decl(dw, dp)
            label = f"{sw or 'self'}.{sp} 에서 {dw or 'self'}.{dp}"
            if sd is None or dd is None:
                out.append(("D1", a, f"{label}: 항상 존재하는 노드에 포트가 선언되어 있지 않다"))
                continue
            want = _want(sw, dw, no_self_loop)
            if want is None or (sd.direction, dd.direction) != want:
                out.append(("D2", a, f"{label}: 방향이 맞지 않다"))
            if sd.type != dd.type:
                out.append(("D3", a, f"{label}: 타입이 다르다"))

        def sure(k):
            return k[0][0] is SELF or never_void[parts[k[0][0]]]

        for n, q in parts.items():
            for y in M[q]:
                for p, d in ann.ports.get(y, {}).items():
                    if d.direction == IN and d.required and \
                            not any(k[1] == (n, p) and sure(k) for k in ks):
                        out.append(("D4", a, f"{n}.{p}: 결코 비지 않는 출발점에서 오는 결합이 없다"))
        for y in M[e]:
            for p, d in ann.ports.get(y, {}).items():
                if d.direction == OUT and d.required and \
                        not any(k[1] == (SELF, p) and sure(k) for k in ks):
                    out.append(("D4", a, f"self.{p}: 결코 비지 않는 부분에서 오는 결합이 없다"))
    return out


# ---------------------------------------------------------------------------
# multi-aspect의 결합 틀
# ---------------------------------------------------------------------------

RULE_KINDS = ("in_each", "in_first", "in_last", "out_each", "out_first", "out_last",
              "next", "wrap", "pairs")


def instantiate(rules, names) -> tuple:
    """결합 틀을 복제본 이름 열에 대해 사례화한다.

    규칙은 (종류, 출발 포트, 도착 포트).
    in_*  : 자신의 포트에서 복제본의 포트로 (each는 모두, first는 첫째, last는 마지막)
    out_* : 복제본의 포트에서 자신의 포트로
    next  : i번째에서 i+1번째로.  wrap: 마지막에서 첫째로.  pairs: 서로 다른 모든 쌍.
    """
    names = list(names)
    n = len(names)
    out: list = []
    for kind, a, b in rules:
        if kind == "in_each":
            out += [((SELF, a), (x, b)) for x in names]
        elif kind == "in_first" and n:
            out.append(((SELF, a), (names[0], b)))
        elif kind == "in_last" and n:
            out.append(((SELF, a), (names[-1], b)))
        elif kind == "out_each":
            out += [((x, a), (SELF, b)) for x in names]
        elif kind == "out_first" and n:
            out.append(((names[0], a), (SELF, b)))
        elif kind == "out_last" and n:
            out.append(((names[-1], a), (SELF, b)))
        elif kind == "next":
            out += [((names[i], a), (names[i + 1], b)) for i in range(n - 1)]
        elif kind == "wrap" and n:
            out.append(((names[-1], a), (names[0], b)))
        elif kind == "pairs":
            out += [((x, a), (y, b)) for x in names for y in names if x != y]
        elif kind not in RULE_KINDS:
            raise AlgebraError(f"알 수 없는 결합 규칙: {kind}")
    return tuple(dict.fromkeys(out))


def cut_cardinalities(cards) -> list:
    """절단 정리: 개수 집합을 0, 1, 2와 3 이상의 대표 하나로 줄인다."""
    cards = sorted(set(cards))
    small = [n for n in cards if n <= 2]
    large = [n for n in cards if n >= 3]
    return small + large[:1]


# ---------------------------------------------------------------------------
# 확장으로서의 결합: SES + DEVS
# ---------------------------------------------------------------------------

class Coupling(Extension):
    """포트와 결합을 얹는 확장. 위의 함수들과 같은 적격성을 확장 계약으로 다시 쓴 것이다.

    주석: 엔티티에는 포트 선언, aspect에는 결합.
    병합: 포트 선언의 합집합. 같은 이름이 다른 타입이나 방향이면 충돌.
    검사: C1 ~ C4.
    해석: 계층적 결합 모델 구조.
    """

    name = "devs"

    def __init__(self, ports: Mapping, coup: Mapping, no_self_loop: bool = False):
        self.ports, self.coup, self.no_self_loop = ports, coup, no_self_loop

    def entity(self, path):
        return self.ports.get(path) or None

    def aspect(self, path):
        return self.coup.get(path, ())

    def merge(self, tree, items):
        decls: dict = {}
        for _, ports in items:
            for p, d in ports.items():
                decls.setdefault(p, []).append(d)
        merged = {p: PortDecl(ds[0].type, ds[0].direction, any(d.required for d in ds))
                  for p, ds in decls.items()}
        conflicts = [f"포트 {p} 의 선언이 충돌한다" for p, ds in decls.items()
                     if len({(d.type, d.direction) for d in ds}) > 1]
        return merged, conflicts

    def _live(self, v: View) -> list:
        dead = set(v.absent)
        return [k for k in (v.aspect_ann or ()) if not ({k[0][0], k[1][0]} & dead)]

    def check(self, v: View) -> list:
        if v.comp.aspect is None:
            return []
        out = []
        ports = v.ann or {}
        live = self._live(v)

        def decl(who, p):
            return (ports if who is SELF else (v.children[who].ann or {})).get(p)

        for (sw, sp), (dw, dp) in live:
            sd, dd = decl(sw, sp), decl(dw, dp)
            label = f"{sw or 'self'}.{sp} 에서 {dw or 'self'}.{dp}"
            if sd is None or dd is None:
                out.append(("C1", f"{label}: 포트가 없다"))
                continue
            want = _want(sw, dw, self.no_self_loop)
            if want is None or (sd.direction, dd.direction) != want:
                out.append(("C2", f"{label}: 방향이 맞지 않다"))
            if sd.type != dd.type:
                out.append(("C3", f"{label}: 타입이 다르다 ({sd.type}, {dd.type})"))
        driven = {k[1] for k in live}
        for n, child in v.children.items():
            for p, d in (child.ann or {}).items():
                if d.direction == IN and d.required and (n, p) not in driven:
                    out.append(("C4", f"{n}.{p}: 필수 입력 포트에 들어오는 결합이 없다"))
        for p, d in ports.items():
            if d.direction == OUT and d.required and (SELF, p) not in driven:
                out.append(("C4", f"self.{p}: 필수 출력 포트로 나가는 결합이 없다"))
        return out

    def interpret(self, v: View, children):
        node = {"ports": {p: (d.type, d.direction) for p, d in (v.ann or {}).items()},
                "required": sorted(p for p, d in (v.ann or {}).items() if d.required),
                "children": dict(children), "eic": [], "eoc": [], "ic": []}
        for (sw, sp), (dw, dp) in self._live(v):
            if sw is SELF:
                node["eic"].append((sp, (dw, dp)))
            elif dw is SELF:
                node["eoc"].append(((sw, sp), dp))
            else:
                node["ic"].append(((sw, sp), (dw, dp)))
        return node

    def psi(self, tree, void):
        return psi(tree, Ann(self.ports, void, self.coup), self.no_self_loop)
