"""핵의 구성 구조 (docs/ses-platform/11_ses_core_and_extensions.md 의 K1 계층).

선택 대수(algebra.py)가 "무엇을 고를 수 있는가"를 다룬다면, 이 모듈은
"고른 결과가 무엇인가"를 분야와 무관하게 정한다.

- 구성 노드: 뿌리이거나 aspect의 부분인 엔티티.
- 병합체: 구성 노드와 그 아래에서 선택된 대안들. inheritance 공리의 구조적 부분.
- 없음 대안: 선택되면 그 구성요소가 빠진다.
- 뼈대 Sk(V): 변이 V의 살아 있는 병합체들이 이루는 나무. 확장은 뼈대만 본다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .algebra import ASP, ENT, SPEC, Tree, f_and, f_imp, f_not, f_or, sel


def is_component(T: Tree, e: tuple) -> bool:
    """뿌리이거나 aspect의 부분인 엔티티."""
    return len(e) == 1 or T.kind(e[:-1]) == ASP


def component_of(T: Tree, y: tuple) -> tuple:
    """엔티티 y가 속할 수 있는 병합체의 구성 노드."""
    while len(y) > 1 and T.kind(y[:-1]) == SPEC:
        y = y[:-2]
    return y


VARIABLE_PREFIX = "$"       # 변수는 뿌리의 specialization으로 부호화된다 (unfold.var_node)
NO_ASPECT = "~"             # 우선순위에 밀린 구성원이 고르는 "분해 없음". 펼침이 만든다 (18 문서 3절)
GONE = "-"                  # 구성요소가 없음 대안을 골라 빠졌을 때 구성원이 고르는 "분해 없음". 펼침이 만든다 (5.3절)
MARKERS = frozenset({NO_ASPECT, GONE})   # 펼침이 만드는 표시. 분해도 아니고 사람이 고르는 선택지도 아니다


def real_aspects(T: Tree, y: tuple) -> tuple:
    """엔티티 노드 y에 적힌 분해. 펼침이 만든 표시("분해 없음")는 분해가 아니다."""
    return tuple(a for a in T.aspects(y) if a[-1] not in MARKERS)


def members(T: Tree, e: tuple) -> list:
    """M(e): 구성 노드 e의 병합체에 들어갈 수 있는 엔티티 노드.

    변수를 부호화한 specialization의 값 노드는 들지 않는다. 변수 값은 선택의 일부이지
    뿌리 구성요소에 합쳐지는 정의가 아니다.
    """
    out, stack = [e], [e]
    while stack:
        y = stack.pop()
        for s in T.specs(y):
            if len(s) == 2 and s[-1].startswith(VARIABLE_PREFIX):
                continue
            for c in T.children(s):
                out.append(c)
                stack.append(c)
    return out


def owner(T: Tree, a: tuple) -> tuple:
    """aspect a를 가진 병합체의 구성 노드."""
    return component_of(T, a[:-1])


def component_path(T: Tree, q: tuple) -> tuple:
    """구성요소 경로: 뿌리에서 그 구성요소까지의 부분 이름들. aspect와 대안의 이름은 빠진다."""
    q = component_of(T, q)
    return (q[0],) + tuple(q[i] for i in range(1, len(q)) if T.kind(q[:i]) == ASP)


def assignment(T: Tree, V: frozenset) -> dict:
    """변이 V가 고른 변수 값: 변수 이름에서 값 노드의 이름으로.

    변수는 전역이다. 확장의 주석이 변수 값에 달려 있을 때(속성의 식) 확장이 이것을 받는다.
    """
    out = {}
    for s in T.specs(T.root):
        if s[-1].startswith(VARIABLE_PREFIX):
            for c in T.children(s):
                if c in V:
                    out[s[-1][len(VARIABLE_PREFIX):]] = c[-1]
    return out


def components(T: Tree) -> list:
    return sorted(e for e in T.nodes if T.kind(e) == ENT and is_component(T, e))


@dataclass(frozen=True)
class Comp:
    """뼈대의 노드: 살아 있는 병합체 하나."""
    path: tuple                       # 구성 노드의 경로
    members: tuple                    # 병합체 구성원 (구성 노드가 첫째)
    labels: tuple                     # 구성원들의 정의 표지
    aspects: tuple                    # 선택된 분해. 핵 적격이면 하나 이하
    parts: Mapping[str, "Comp"]       # 살아 있는 부분 (이름에서 Comp로)
    absent: tuple                     # 없음이 된 부분의 이름

    @property
    def name(self) -> str:
        return self.path[-1]

    @property
    def aspect(self) -> Optional[tuple]:
        return self.aspects[0] if len(self.aspects) == 1 else None

    @property
    def is_atomic(self) -> bool:
        return not self.aspects


def skeleton(T: Tree, void: frozenset, V: frozenset) -> Optional[Comp]:
    """변이 V의 뼈대. 뿌리가 없음이면 None."""

    def cluster(e):
        return [y for y in members(T, e) if y in V]

    def build(e) -> Optional[Comp]:
        ms = cluster(e)
        if any(y in void for y in ms):
            return None
        asps = tuple(a for y in ms for a in real_aspects(T, y) if a in V)
        parts, absent = {}, []
        for a in asps:
            for q in T.children(a):
                c = build(q)
                if c is None:
                    absent.append(q[-1])
                else:
                    parts[q[-1]] = c
        return Comp(e, tuple(ms), tuple(T.label(y) for y in ms), asps, parts, tuple(absent))

    return build(T.root)


def core_violations(T: Tree, void: frozenset, V: frozenset) -> list:
    """핵 적격성: 뿌리는 없음이 아니고, 살아 있는 병합체의 분해는 하나 이하."""
    sk = skeleton(T, void, V)
    if sk is None:
        return [("K0", T.root, "뿌리가 없음 대안을 골랐다")]
    out: list = []

    def walk(c: Comp) -> None:
        if len(c.aspects) > 1:
            out.append(("K1", c.path, "분해가 둘 이상 선택되었다"))
        for child in c.parts.values():
            walk(child)

    walk(sk)
    return out


def void_formula(T: Tree, void: frozenset, e: tuple):
    return f_or(*(sel(y) for y in members(T, e) if y in void))


def live_formula(T: Tree, void: frozenset, e: tuple):
    chain, c = [], e
    while True:
        chain.append(c)
        if len(c) == 1:
            break
        c = owner(T, c[:-1])
    return f_and(sel(e), *(f_not(void_formula(T, void, c)) for c in chain))


def core_psi(T: Tree, void: frozenset):
    """핵 적격성의 특성식."""
    clauses = [f_not(void_formula(T, void, T.root))]
    for e in components(T):
        asps = [(y, a) for y in members(T, e) for a in real_aspects(T, y)]
        le = None
        for i, (y, a) in enumerate(asps):
            for y2, a2 in asps[i + 1:]:
                if y != y2:
                    le = le or live_formula(T, void, e)
                    clauses.append(f_imp(le, f_not(f_and(sel(a), sel(a2)))))
    return f_and(*clauses)
