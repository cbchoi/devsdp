"""가지치기 대수의 참조 구현 (docs/ses-platform/07_pruning_algebra.md).

이 모듈은 이론의 정의를 그대로 옮긴 것이며 효율을 고려하지 않는다.
변이 열거는 지수 시간이고 축약(reduce)은 전수 열거로 계산한다.
정리의 무작위 검증과 작은 예제 계산이 목적이다.

핵심 개념
- SES 트리: 이름 경로로 식별되는 노드와 종류(ent, asp, spec). multi-aspect는
  개수별 aspect로 전개한 형태로 다룬다.
- 적격 선택 K: 가지치기 관계 T|K ⊑ T 를 정하는 노드 집합.
- 가지치기 SES P: 그 자체가 SES. 연산 S ⊗ P 와 S ▷ P = red(S ⊗ P).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from itertools import product
from typing import Iterable, Mapping, Optional

Path = tuple
ENT, ASP, SPEC = "ent", "asp", "spec"


class AlgebraError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 정의 1. SES 트리
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tree:
    """이름 경로의 접두사 닫힌 집합과 종류 함수.

    labels는 엔티티 노드의 정의 표지다. 노드의 이름(경로의 마지막 요소)과 별개로
    그 노드가 어느 정의의 사례인지를 기록한다. 복제본 server_0과 별칭 부분
    primary는 이름이 달라도 표지는 Server다. 표지가 없으면 이름을 표지로 본다.
    """
    kinds: Mapping[Path, str]
    labels: Mapping[Path, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        roots = [p for p in self.kinds if len(p) == 1]
        if len(roots) != 1 or self.kinds[roots[0]] != ENT:
            raise AlgebraError("뿌리는 하나의 엔티티여야 한다")
        for p, k in self.kinds.items():
            if len(p) == 1:
                continue
            parent = self.kinds.get(p[:-1])
            if parent is None:
                raise AlgebraError(f"접두사 닫힘 위반: {p}")
            if (parent == ENT) == (k == ENT):
                raise AlgebraError(f"alternating mode 위반: {p}")

    @cached_property
    def root(self) -> Path:
        return next(p for p in self.kinds if len(p) == 1)

    @cached_property
    def nodes(self) -> frozenset:
        return frozenset(self.kinds)

    @cached_property
    def _children(self) -> dict:
        # 자식의 순서는 kinds에 넣은 순서, 곧 문서에 적은 순서다. 정렬하지 않는다.
        # 편집기의 표시 순서와 순서에 뜻이 있는 확장(문서 조립)이 이 순서를 쓴다.
        ch: dict = {p: [] for p in self.kinds}
        for p in self.kinds:
            if len(p) > 1:
                ch[p[:-1]].append(p)
        return {p: tuple(c) for p, c in ch.items()}

    def kind(self, p: Path) -> str:
        return self.kinds[p]

    def label(self, p: Path) -> str:
        return self.labels.get(p, p[-1])

    def children(self, p: Path) -> tuple:
        return self._children[p]

    def aspects(self, e: Path) -> tuple:
        return tuple(c for c in self._children[e] if self.kinds[c] == ASP)

    def specs(self, e: Path) -> tuple:
        return tuple(c for c in self._children[e] if self.kinds[c] == SPEC)


# 트리 작성 도우미 -----------------------------------------------------------

def ent(name: str, *children):
    return (ENT, name, children)


def asp(name: str, *parts):
    return (ASP, name, parts)


def spec(name: str, *alts):
    return (SPEC, name, alts)


def masp(name: str, cards: Iterable[int], part):
    """multi-aspect의 전개. 개수 n마다 aspect name[n]을 만들고 part(i)를 n번 둔다."""
    return [asp(f"{name}[{n}]", *(part(i) for i in range(n))) for n in cards]


def build(node) -> Tree:
    kinds: dict = {}

    def rec(n, prefix: Path) -> None:
        if isinstance(n, list):
            for m in n:
                rec(m, prefix)
            return
        kind, name, children = n
        path = prefix + (name,)
        if path in kinds:
            raise AlgebraError(f"valid brothers 위반: {path}")
        kinds[path] = kind
        for c in children:
            rec(c, path)

    rec(node, ())
    return Tree(kinds)


# ---------------------------------------------------------------------------
# 정의 3. 적격 선택, 확정, 변이
# ---------------------------------------------------------------------------

def _violates(T: Tree, K: set, n: Path) -> bool:
    if len(n) > 1 and n[:-1] not in K:
        return True
    k = T.kind(n)
    if k == ENT:
        if any(s not in K for s in T.specs(n)):
            return True
        a = T.aspects(n)
        return bool(a) and not any(x in K for x in a)
    if k == ASP:
        return any(c not in K for c in T.children(n))
    return not any(c in K for c in T.children(n))


def admissible(T: Tree, K: Iterable[Path]) -> bool:
    K = set(K)
    if T.root not in K or not K <= T.nodes:
        return False
    return not any(_violates(T, K, n) for n in K)


def determinate(T: Tree, K: Iterable[Path]) -> bool:
    K = set(K)
    if not admissible(T, K):
        return False
    for n in K:
        k = T.kind(n)
        if k == ENT and len([a for a in T.aspects(n) if a in K]) > 1:
            return False
        if k == SPEC and len([c for c in T.children(n) if c in K]) != 1:
            return False
    return True


def interior(T: Tree, X: Iterable[Path]) -> Optional[frozenset]:
    """X에 포함된 가장 큰 적격 선택. 없으면 None (모순, ⊥)."""
    K = set(X) & T.nodes
    changed = True
    while changed:
        changed = False
        for n in list(K):
            if n in K and _violates(T, K, n):
                K.discard(n)
                changed = True
    return frozenset(K) if T.root in K else None


def restrict(T: Tree, K: Iterable[Path]) -> Tree:
    """T|K. K는 적격 선택이어야 한다. T의 노드 순서를 그대로 물려받는다."""
    K = K if isinstance(K, (set, frozenset)) else set(K)
    return Tree({n: k for n, k in T.kinds.items() if n in K},
                {n: l for n, l in T.labels.items() if n in K})


def variants(T: Tree) -> list:
    """Var(T): 확정 적격 선택 전체."""

    def of_entity(e: Path) -> list:
        factors = []
        for s in T.specs(e):
            factors.append([v | {s} for c in T.children(s) for v in of_entity(c)])
        a_nodes = T.aspects(e)
        if a_nodes:
            opts = []
            for a in a_nodes:
                for combo in product(*(of_entity(c) for c in T.children(a))):
                    opts.append(frozenset({a}).union(*combo))
            factors.append(opts)
        return [frozenset({e}).union(*combo) for combo in product(*factors)]

    return of_entity(T.root)


def count_variants(T: Tree) -> int:
    def of_entity(e: Path) -> int:
        total = 1
        for s in T.specs(e):
            total *= sum(of_entity(c) for c in T.children(s))
        a_nodes = T.aspects(e)
        if a_nodes:
            acc = 0
            for a in a_nodes:
                p = 1
                for c in T.children(a):
                    p *= of_entity(c)
                acc += p
            total *= acc
        return total

    return of_entity(T.root)


# ---------------------------------------------------------------------------
# 정의 4. 가지치기 관계와 격자 연산
# ---------------------------------------------------------------------------

def leq(T1: Tree, T2: Tree) -> bool:
    """T1 ⊑ T2: T1이 T2의 가지치기다."""
    return all(T2.kinds.get(n) == k for n, k in T1.kinds.items()) and admissible(T2, T1.nodes)


def lattice_meet(T: Tree, K1: Iterable[Path], K2: Iterable[Path]) -> Optional[frozenset]:
    return interior(T, set(K1) & set(K2))


def lattice_join(K1: Iterable[Path], K2: Iterable[Path]) -> frozenset:
    return frozenset(K1) | frozenset(K2)


# ---------------------------------------------------------------------------
# 정의 2. 제약을 가진 SES와 제약식
# ---------------------------------------------------------------------------

TRUE = ("true",)


def sel(p: Iterable[str]):
    return ("sel", tuple(p))


def f_not(a):
    return ("not", a)


def f_and(*fs):
    fs = tuple(f for f in fs if f != TRUE)
    if not fs:
        return TRUE
    return fs[0] if len(fs) == 1 else ("and",) + fs


def f_or(*fs):
    return ("or",) + tuple(fs)


def f_imp(a, b):
    return ("imp", a, b)


def holds(f, V: frozenset) -> bool:
    op = f[0]
    if op == "true":
        return True
    if op == "sel":
        return f[1] in V
    if op == "not":
        return not holds(f[1], V)
    if op == "and":
        return all(holds(g, V) for g in f[1:])
    if op == "or":
        return any(holds(g, V) for g in f[1:])
    if op == "imp":
        return (not holds(f[1], V)) or holds(f[2], V)
    if op == "pred":                    # 변이에 대한 임의의 술어 (문법적 식이 없는 확장용)
        return bool(f[1](V))
    raise AlgebraError(f"알 수 없는 제약식: {f!r}")


def _rebase(f, old_root: str, new_prefix: Path):
    op = f[0]
    if op == "true":
        return f
    if op == "pred":
        if new_prefix != (old_root,):
            raise AlgebraError("술어 제약은 뿌리에 놓인 가지치기 SES에서만 쓸 수 있다")
        return f
    if op == "sel":
        p = f[1]
        if not p or p[0] != old_root:
            raise AlgebraError(f"가지치기 SES의 제약 원자는 자신의 뿌리에서 시작해야 한다: {p}")
        return ("sel", new_prefix + p[1:])
    return (op,) + tuple(_rebase(g, old_root, new_prefix) for g in f[1:])


@dataclass(frozen=True)
class SES:
    tree: Tree
    phi: tuple = TRUE


def sem(S: SES) -> list:
    """Var(S): 제약을 만족하는 변이."""
    return [V for V in variants(S.tree) if holds(S.phi, V)]


def reduce(S: SES) -> Optional[SES]:
    """red(S): 어떤 변이에도 나타나지 않는 노드를 제거한다. 변이가 없으면 None."""
    vs = sem(S)
    if not vs:
        return None
    return SES(restrict(S.tree, frozenset().union(*vs)), S.phi)


def is_pes(S: SES) -> bool:
    vs = sem(S)
    return len(vs) == 1 and vs[0] == S.tree.nodes


# ---------------------------------------------------------------------------
# 정의 5 ~ 7. 가지치기 SES와 연산
# ---------------------------------------------------------------------------

def occurrences(T: Tree, name: str) -> list:
    """정의 표지가 name인 엔티티 노드."""
    return sorted(q for q in T.nodes if T.kind(q) == ENT and T.label(q) == name)


def matches(T: Tree, P: Tree) -> list:
    """대응 쌍 (p, q). P의 뿌리 표지가 T에서 출현하는 곳마다 P를 접붙인다."""
    out = []
    for o in occurrences(T, P.label(P.root)):
        for p in P.nodes:
            q = o + p[1:]
            if q in T.nodes:
                if T.kind(q) != P.kind(p):
                    raise AlgebraError(f"종류 불일치: {q} 는 {T.kind(q)}, 가지치기 SES에서는 {P.kind(p)}")
                out.append((p, q))
    return out


def keep_set(T: Tree, P: Tree) -> frozenset:
    """허용 집합 X_P: P가 배제하는 선택지와 그 후손을 뺀 노드 집합."""
    excluded = set()
    for p, q in matches(T, P):
        if P.kind(p) == ENT:
            named = {a[-1] for a in P.aspects(p)}
            if named:
                excluded |= {a for a in T.aspects(q) if a[-1] not in named}
        elif P.kind(p) == SPEC:
            named = {c[-1] for c in P.children(p)}
            excluded |= {c for c in T.children(q) if c[-1] not in named}
    return frozenset(n for n in T.nodes
                     if not any(n[:len(x)] == x for x in excluded))


def lift_formula(T: Tree, P: SES):
    if P.phi == TRUE:
        return TRUE
    name = P.tree.root[0]
    return f_and(*(f_imp(sel(o), _rebase(P.phi, name, o))
                   for o in occurrences(T, P.tree.label(P.tree.root))))


def meet(S: SES, P: SES) -> Optional[SES]:
    """S ⊗ P. 구조는 int(X_P)로 제한하고 제약은 합친다. 모순이면 None."""
    K = interior(S.tree, keep_set(S.tree, P.tree))
    if K is None:
        return None
    return SES(restrict(S.tree, K), f_and(S.phi, lift_formula(S.tree, P)))


def prune(S: SES, *patterns: SES) -> Optional[SES]:
    """S ▷ P1 ▷ ... ▷ Pk = red(S ⊗ P1 ⊗ ... ⊗ Pk)."""
    cur: Optional[SES] = S
    for P in patterns:
        cur = meet(cur, P)
        if cur is None:
            return None
    return reduce(cur)


def compatible(S: SES, P: SES) -> list:
    """C_S(P) ∩ Var(S): P와 양립하는 S의 변이 (정리 3의 우변)."""
    X = keep_set(S.tree, P.tree)
    lifted = lift_formula(S.tree, P)
    return [V for V in sem(S) if V <= X and holds(lifted, V)]


def is_uniform(T: Tree) -> bool:
    """uniformity: 같은 정의 표지의 엔티티는 같은 하위 구조를 가진다."""
    shapes: dict = {}
    for q in T.nodes:
        if T.kind(q) != ENT:
            continue
        shape = frozenset((n[len(q):], T.kind(n)) for n in T.nodes if n[:len(q)] == q)
        if shapes.setdefault(T.label(q), shape) != shape:
            return False
    return True
