"""가지치기 대수의 정리를 무작위 SES에서 전수 열거로 검증한다.

각 테스트 이름의 번호는 docs/ses-platform/07_pruning_algebra.md 의 정리 번호다.
"""

import itertools
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ses_core import load_ses, load_ses_dict  # noqa: E402
from ses_core.algebra import (  # noqa: E402
    ASP, ENT, SPEC, SES, TRUE, AlgebraError, Tree, admissible, asp, build, compatible,
    count_variants, determinate, ent, f_and, f_imp, f_not, f_or, interior, is_pes,
    is_uniform, keep_set, lattice_join, lattice_meet, leq, masp, meet, prune, reduce,
    restrict, sel, sem, spec, variants)
from ses_core.unfold import pruning_patterns, unfold, var_node  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")
SEEDS = range(300)


# ---------------------------------------------------------------------------
# 무작위 생성기
# ---------------------------------------------------------------------------

def rand_tree(rng: random.Random, depth: int = 3) -> Tree:
    while True:
        counter = itertools.count()
        kinds = {}

        def grow(path, d):
            kinds[path] = ENT
            if d == 0:
                return
            for _ in range(rng.choice([0, 0, 1, 2])):
                s = path + (f"s{next(counter)}",)
                kinds[s] = SPEC
                for _ in range(rng.randint(1, 3)):
                    grow(s + (f"e{next(counter)}",), d - 1)
            for _ in range(rng.choice([0, 1, 1, 2, 3])):
                a = path + (f"a{next(counter)}",)
                kinds[a] = ASP
                for _ in range(rng.randint(0, 2)):
                    grow(a + (f"e{next(counter)}",), d - 1)

        grow(("r",), depth)
        T = Tree(kinds)
        if 2 <= count_variants(T) <= 400:
            return T


def rand_selection(rng: random.Random, T: Tree) -> frozenset:
    K = set()

    def some(xs):
        k = rng.randint(1, len(xs))
        return rng.sample(list(xs), k)

    def pick(e):
        K.add(e)
        for s in T.specs(e):
            K.add(s)
            for c in some(T.children(s)):
                pick(c)
        if T.aspects(e):
            for a in some(T.aspects(e)):
                K.add(a)
                for c in T.children(a):
                    pick(c)

    pick(T.root)
    return frozenset(K)


def rand_pattern(rng: random.Random, T: Tree, extras: bool = False) -> Tree:
    """T의 임의 부분 트리(완전성 요구 없음). extras면 T에 없는 선택지도 섞는다."""
    kinds = {}
    counter = itertools.count()

    def walk(p):
        kinds[p] = T.kind(p)
        for c in T.children(p):
            if rng.random() < 0.7:
                walk(c)
        if extras and rng.random() < 0.2:
            if T.kind(p) == SPEC:
                kinds[p + (f"x{next(counter)}",)] = ENT
            elif T.kind(p) == ENT:
                kinds[p + (f"x{next(counter)}",)] = ASP

    walk(T.root)
    return Tree(kinds)


def rand_formula(rng: random.Random, T: Tree):
    nodes = sorted(T.nodes)
    clauses = []
    for _ in range(rng.randint(0, 2)):
        a, b = rng.choice(nodes), rng.choice(nodes)
        clauses.append(rng.choice([f_imp(sel(a), f_not(sel(b))), f_or(sel(a), f_not(sel(b))),
                                   f_imp(sel(a), sel(b))]))
    return f_and(*clauses)


def var_in(T: Tree, K) -> set:
    return {V for V in variants(T) if V <= K}


# ---------------------------------------------------------------------------
# 보조정리 1, 정리 1, 정리 2
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_lemma1_closure_and_union(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    K1, K2 = rand_selection(rng, T), rand_selection(rng, T)
    assert admissible(T, K1) and admissible(T, K2)
    assert admissible(T, lattice_join(K1, K2))                      # 합집합 닫힘
    sub = restrict(T, K1)                                           # T|K 는 SES 트리
    assert leq(sub, T)
    assert set(variants(sub)) == var_in(T, K1)                      # Var(T|K) = {V | V ⊆ K}


@pytest.mark.parametrize("seed", SEEDS)
def test_lemma1_interior_is_greatest(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    X = frozenset(n for n in sorted(T.nodes) if rng.random() < 0.85) | {T.root}
    inside = var_in(T, X)
    K = interior(T, X)
    if not inside:
        assert K is None
    else:
        assert K == frozenset().union(*inside) and admissible(T, K)


@pytest.mark.parametrize("seed", SEEDS)
def test_theorem1_order_and_minimal_elements(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    K1 = rand_selection(rng, T)
    T1 = restrict(T, K1)
    K2 = rand_selection(rng, T1)
    T2 = restrict(T1, K2)
    assert leq(T, T) and leq(T1, T) and leq(T2, T1) and leq(T2, T)  # 반사, 추이
    if leq(T, T1):
        assert T == T1                                              # 반대칭
    for V in variants(T)[:20]:                                      # 극소 원소는 확정 SES
        assert determinate(T, V)
        assert variants(restrict(T, V)) == [V]


@pytest.mark.parametrize("seed", SEEDS)
def test_theorem2_variant_semantics(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    K1, K2 = rand_selection(rng, T), rand_selection(rng, T)
    v1, v2 = var_in(T, K1), var_in(T, K2)
    assert K1 == frozenset().union(*v1)                             # (a) K 는 변이의 합집합
    assert (K1 <= K2) == (v1 <= v2)                                 # (b) 포함 동치
    M = lattice_meet(T, K1, K2)                                     # (c) 교는 변이 공간의 교집합
    assert (var_in(T, M) if M is not None else set()) == v1 & v2
    assert (M is None) == (not (v1 & v2))                           # (d)


# ---------------------------------------------------------------------------
# 정리 3: 연산의 닫힘과 의미
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_theorem3_operation_semantics(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    S = SES(T, rand_formula(rng, T))
    P = SES(rand_pattern(rng, T, extras=rng.random() < 0.5), rand_formula(rng, T))
    R = prune(S, P)
    expected = set(compatible(S, P))
    if R is None:
        assert not expected
        return
    assert leq(R.tree, T)                                           # (a) 닫힘, S ▷ P ⊑ S
    assert set(sem(R)) == expected                                  # (b) 의미
    assert R.tree.nodes == frozenset().union(*expected)             # 축약형


@pytest.mark.parametrize("seed", SEEDS)
def test_theorem3c_projection_characterisation(seed):
    """P가 S 위에 있을 때: V가 P와 양립 iff V ∩ N_P 가 P의 변이."""
    rng = random.Random(seed)
    T = rand_tree(rng)
    P = rand_pattern(rng, T)
    X = keep_set(T, P)
    p_vars = set(variants(P))
    for V in variants(T):
        assert (V <= X) == ((V & P.nodes) in p_vars)


# ---------------------------------------------------------------------------
# 정리 4: 관계와 연산의 일치
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_theorem4_relation_equals_operation(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    K1, K2 = rand_selection(rng, T), rand_selection(rng, T)
    T1, T2 = restrict(T, K1), restrict(T, K2)
    assert meet(SES(T), SES(T1)).tree == T1                         # T' ⊑ T 이면 T ⊗ T' = T'
    M = lattice_meet(T, K1, K2)
    R12, R21 = meet(SES(T1), SES(T2)), meet(SES(T2), SES(T1))
    if M is None:
        assert R12 is None and R21 is None
    else:
        assert R12.tree == R21.tree == restrict(T, M)               # ⊗ 는 격자의 교
    Q = rand_pattern(rng, T, extras=True)                           # 역방향: T ⊗ Q = Q 이면 Q ⊑ T
    RQ = meet(SES(T), SES(Q))
    if RQ is not None and RQ.tree == Q:
        assert leq(Q, T)


# ---------------------------------------------------------------------------
# 정리 5: 대수 법칙
# ---------------------------------------------------------------------------

def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.tree == b.tree and set(sem(a)) == set(sem(b))


@pytest.mark.parametrize("seed", SEEDS)
def test_theorem5_laws(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    S = SES(T, rand_formula(rng, T))
    P = SES(rand_pattern(rng, T, extras=True), rand_formula(rng, T))
    Q = SES(rand_pattern(rng, T, extras=True), rand_formula(rng, T))
    sp, sq = prune(S, P), prune(S, Q)
    assert same(prune(S, P, P), sp)                                 # 멱등
    assert same(prune(S, P, Q), prune(S, Q, P))                     # 교환
    spq = prune(S, P, Q)                                            # 단계 적용과 일괄 적용
    assert same(prune(sp, Q) if sp is not None else None, spq)
    expected = set(compatible(S, P)) & set(compatible(S, Q))        # 순서 무관한 의미
    assert (set(sem(spq)) if spq is not None else set()) == expected
    if sp is not None and spq is not None:
        assert leq(spq.tree, sp.tree)                               # 단조 감소
    K = rand_selection(rng, T)                                      # S' ⊑ S 이면 S' ▷ P ⊑ S ▷ P
    sub = prune(SES(restrict(T, K), S.phi), P)
    if sub is not None:
        assert sp is not None and leq(sub.tree, sp.tree)


# ---------------------------------------------------------------------------
# 정리 6: PES 판정과 표현 완전성
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(100))
def test_theorem6_pes_and_completeness(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    S = SES(T, rand_formula(rng, T))
    for V in sem(S)[:10]:
        R = prune(S, SES(restrict(T, V)))                           # 모든 변이는 어떤 P로 얻어진다
        assert R is not None and R.tree.nodes == V and is_pes(R)
    P = SES(rand_pattern(rng, T))
    R = prune(S, P)
    if R is not None:
        assert is_pes(R) == (len(compatible(S, P)) == 1)            # PES 판정


# ---------------------------------------------------------------------------
# 명제 7: uniformity와 정의 수준 가지치기
# ---------------------------------------------------------------------------

def unit():
    return ent("Unit", spec("kind", ent("A"), ent("B")), asp("solo"), asp("pair", ent("X"), ent("Y")))


def plant() -> Tree:
    return build(ent("System", asp("dec", ent("Left", asp("ldec", unit())),
                                   ent("Right", asp("rdec", unit())))))


def test_proposition7_definition_level_preserves_uniformity():
    T = plant()
    assert is_uniform(T)
    P = build(ent("Unit", spec("kind", ent("A")), asp("pair")))     # 정의 수준: 모든 출현에 적용
    R = meet(SES(T), SES(P)).tree
    assert is_uniform(R)
    assert count_variants(T) == 16 and count_variants(R) == 1
    for side, d in (("Left", "ldec"), ("Right", "rdec")):
        base = ("System", "dec", side, d, "Unit")
        assert base + ("kind", "B") not in R.nodes and base + ("solo",) not in R.nodes


def test_proposition7_path_level_may_break_uniformity():
    T = plant()
    P = build(ent("System", asp("dec", ent("Left", asp("ldec", ent("Unit", spec("kind", ent("A"))))))))
    R = meet(SES(T), SES(P)).tree
    assert not is_uniform(R)                                        # 한쪽 Unit만 제한됨
    assert count_variants(R) == 8


def test_kind_mismatch_is_rejected():
    T = plant()
    with pytest.raises(AlgebraError):
        keep_set(T, Tree({("System",): ENT, ("System", "dec"): SPEC}))


def test_multi_aspect_per_replica_decision():
    """복제본마다 다른 결정: 경로 수준 가지치기 SES로 표현된다."""
    def valve(i):
        return ent(f"valve_{i}", spec("ctrl", ent("PID"), ent("MPC"), ent("FUZZY")))
    T = build(ent("Plant", masp("valves", [1, 2, 3], valve)))
    assert count_variants(T) == 3 + 9 + 27
    P = build(ent("Plant", asp("valves[2]",
                               ent("valve_0", spec("ctrl", ent("MPC"))),
                               ent("valve_1", spec("ctrl", ent("FUZZY"))))))
    R = prune(SES(T), SES(P))
    assert is_pes(R)
    assert ("Plant", "valves[2]", "valve_0", "ctrl", "MPC") in R.tree.nodes
    assert ("Plant", "valves[2]", "valve_1", "ctrl", "FUZZY") in R.tree.nodes


# ---------------------------------------------------------------------------
# 정준 YAML과의 연결: SES ▷ 가지치기 SES = PES
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def S():
    return unfold(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))


def pattern_doc(**overrides):
    base = {
        "ses": "1.0", "name": "p",
        "entities": {"ProcessingSystem": {"root": True}},
    }
    base["entities"].update(overrides)
    return pruning_patterns(load_ses_dict(base))


PRIORITY = {"Buffer": {"specializations": {"policySpec": {"alternatives": ["PriorityBuffer"]}}},
            "PriorityBuffer": {"extends": "Buffer"}}
FIFO = {"Buffer": {"specializations": {"policySpec": {"alternatives": ["FifoBuffer"]}}},
        "FifoBuffer": {"extends": "Buffer"}}


def servers(n):
    return {"ServerPool": {"multi_aspects": {"serversMAsp": {"part": "Server", "cardinality": n}}},
            "Server": {}}


def test_example_variant_space(S):
    assert len(variants(S.tree)) == 256
    assert len(sem(S)) == 15                    # fifo 8 가지, priority 7 가지
    assert reduce(S).tree == S.tree             # 죽은 노드 없음


def test_example_pruning_ses_file_yields_pes(S):
    doc = load_ses(os.path.join(EXAMPLES, "processing_system.pruning.ses.yaml"))
    R = prune(S, *pruning_patterns(doc))
    assert R is not None and is_pes(R)
    root = ("ProcessingSystem",)
    pool = root + ("pipelineDec", "ServerPool", "serversMAsp[4]")
    assert root + ("pipelineDec", "Buffer", "policySpec", "PriorityBuffer") in R.tree.nodes
    assert {pool + (f"server_{i}",) for i in range(4)} <= R.tree.nodes
    assert root + (var_node("policy"), "priority") in R.tree.nodes    # 변수 값이 축약으로 결정됨
    assert root + (var_node("num_servers"), "4") in R.tree.nodes
    assert leq(R.tree, S.tree)


def test_example_contradiction_is_bottom(S):
    assert prune(S, *pattern_doc(**PRIORITY, **servers(1))) is None   # priority는 서버 2대 이상


def test_example_staged_pruning_is_order_independent(S):
    p, n = pattern_doc(**PRIORITY), pattern_doc(**servers(4))
    partial = prune(S, *p)
    assert len(sem(partial)) == 7 and not is_pes(partial)             # 부분 가지치기도 SES
    a, b = prune(partial, *n), prune(prune(S, *n), *p)
    assert a.tree == b.tree and is_pes(a)
    assert len(sem(prune(S, *pattern_doc(**FIFO)))) == 8


def test_example_dead_alternative_removed_by_reduction(S):
    root = ("ProcessingSystem",)
    forbid_fifo = f_not(sel(root + (var_node("policy"), "fifo")))
    R = reduce(SES(S.tree, f_and(S.phi, forbid_fifo)))
    assert root + ("pipelineDec", "Buffer", "policySpec", "FifoBuffer") not in R.tree.nodes
    assert root + ("pipelineDec", "ServerPool", "serversMAsp[1]") not in R.tree.nodes
    assert len(sem(R)) == 7
