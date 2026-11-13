"""결합을 가진 SES와 족 수준 적격성의 정리를 무작위 SES에서 전수 열거로 검증한다.

정리 번호는 docs/ses-platform/08_coupling_wellformedness.md 를 따른다.
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_algebra import rand_formula, rand_pattern, rand_selection, rand_tree  # noqa: E402

from ses_core.algebra import (  # noqa: E402
    ASP, ENT, SPEC, SES, AlgebraError, Tree, asp, build, ent, holds, is_pes, leq, prune,
    reduce, restrict, sem, spec, variants)
from ses_core.coupling import (  # noqa: E402
    IN, OUT, SELF, Ann, PortDecl, cut_cardinalities, discipline_violations,
    family_wellformed, family_wellformed_by_formula, ill_formed, instantiate, psi, realize,
    validate, violations, wellformed, wf_core, wf_pattern)

SEEDS = range(300)
POOL = {"i1": ("T1", IN), "i2": ("T2", IN), "o1": ("T1", OUT), "o2": ("T2", OUT)}
INS = {"T1": "i1", "T2": "i2"}
OUTS = {"T1": "o1", "T2": "o2"}


# ---------------------------------------------------------------------------
# 무작위 주석 생성기
# ---------------------------------------------------------------------------

def rand_ann(rng: random.Random, T: Tree, noise: float = 0.06) -> Ann:
    """noise가 클수록 포트 누락, 타입과 방향 오류, 잘못된 결합이 많아진다."""
    ports, void, coup = {}, set(), {}
    for e in sorted(T.nodes):
        if T.kind(e) != ENT:
            continue
        is_alt = len(e) > 1 and T.kind(e[:-1]) == SPEC
        if is_alt and not T.children(e) and rng.random() < 0.3:
            void.add(e)
            continue
        d = {}
        for name, (t, dr) in POOL.items():
            if rng.random() < (0.2 if is_alt else 1.0 - 2 * noise):
                if rng.random() < noise:
                    t = "T2" if t == "T1" else "T1"
                if rng.random() < noise:
                    dr = IN if dr == OUT else OUT
                d[name] = PortDecl(t, dr, rng.random() < 0.1)
        if d:
            ports[e] = d

    for a in sorted(n for n in T.nodes if T.kind(n) == ASP):
        names = [q[-1] for q in T.children(a)]
        ks = set()
        for _ in range(rng.randint(0, 6)):
            t = rng.choice(["T1", "T2"])
            t2 = t if rng.random() > noise else ("T2" if t == "T1" else "T1")
            r = rng.random()
            if not names:
                if r < noise:
                    ks.add(((SELF, INS[t]), (SELF, OUTS[t2])))
            elif r < noise / 2:
                ks.add(((SELF, INS[t]), (SELF, OUTS[t2])))
            elif r < 0.45:
                ks.add(((SELF, INS[t]), (rng.choice(names), INS[t2])))
            elif r < 0.75:
                ks.add(((rng.choice(names), OUTS[t]), (SELF, OUTS[t2])))
            else:
                ks.add(((rng.choice(names), OUTS[t]), (rng.choice(names), INS[t2])))
        if ks:
            coup[a] = tuple(sorted(ks, key=repr))
    ann = Ann(ports, frozenset(void), coup)
    validate(T, ann)
    return ann


def case(seed: int):
    rng = random.Random(seed)
    T = rand_tree(rng)
    return rng, T, rand_ann(rng, T, noise=rng.choice([0.0, 0.0, 0.02, 0.06]))


# ---------------------------------------------------------------------------
# 정리 8: 적격성은 변이 자체의 성질이다 (내재성)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_theorem8_wellformedness_is_intrinsic(seed):
    rng, T, ann = case(seed)
    K = rand_selection(rng, T)
    sub = restrict(T, K)
    for V in variants(sub):
        assert violations(sub, ann, V) == violations(T, ann, V)
        assert violations(restrict(T, V), ann, V) == violations(T, ann, V)


# ---------------------------------------------------------------------------
# 정리 9: 가지치기는 족 수준 적격성을 보존한다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_theorem9_pruning_preserves_family_wellformedness(seed):
    rng, T, ann = case(seed)
    S = SES(T, rand_formula(rng, T))
    core = wf_core(S, ann)                      # 족 수준 적격인 SES를 하나 만든다
    if core is None:
        return
    assert family_wellformed(core, ann)
    P = SES(rand_pattern(rng, T, extras=True), rand_formula(rng, T))
    R = prune(core, P)
    if R is not None:
        assert family_wellformed(R, ann)        # (b) 어떤 가지치기 SES를 적용해도 유지
        assert leq(R.tree, core.tree)
    for V in sem(core)[:10]:                    # (c) 모든 PES가 적격
        pes = prune(core, SES(restrict(T, V)))
        assert is_pes(pes) and wellformed(pes.tree, ann, V)


# ---------------------------------------------------------------------------
# 정리 10: 특성식
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("no_self_loop", [False, True])
def test_theorem10_characteristic_formula(seed, no_self_loop):
    rng, T, ann = case(seed)
    f = psi(T, ann, no_self_loop)
    for V in variants(T):
        assert holds(f, V) == wellformed(T, ann, V, no_self_loop)
    S = SES(T, rand_formula(rng, T))
    assert family_wellformed_by_formula(S, ann, no_self_loop) == \
        family_wellformed(S, ann, no_self_loop)


# ---------------------------------------------------------------------------
# 정리 11: 적격 핵
# ---------------------------------------------------------------------------

def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.tree == b.tree and set(sem(a)) == set(sem(b))


@pytest.mark.parametrize("seed", SEEDS)
def test_theorem11_wellformed_core(seed):
    rng, T, ann = case(seed)
    S = SES(T, rand_formula(rng, T))
    good = {V for V in sem(S) if wellformed(T, ann, V)}
    core = wf_core(S, ann)
    assert (set(sem(core)) if core is not None else set()) == good      # (a) 적격 변이 전체
    if core is not None:
        assert family_wellformed(core, ann) and leq(core.tree, T)
        assert same(wf_core(core, ann), core)                           # (b) 멱등
    assert family_wellformed(S, ann) == same(core, reduce(S))           # (c) 부동점 판정
    P = SES(rand_pattern(rng, T, extras=True), rand_formula(rng, T))    # (d) 가지치기와 교환
    sp = prune(S, P)
    left = wf_core(sp, ann) if sp is not None else None
    right = prune(core, P) if core is not None else None
    assert same(left, right)
    K = rand_selection(rng, T)                                          # (e) 가장 큰 적격 가지치기
    sub = reduce(SES(restrict(T, K), S.phi))
    if sub is not None and family_wellformed(sub, ann):
        assert core is not None and leq(sub.tree, core.tree)


# ---------------------------------------------------------------------------
# 정리 12: 정적 규율은 족 수준 적격성의 충분조건이다
# ---------------------------------------------------------------------------

def disciplined_ann(rng: random.Random, T: Tree) -> Ann:
    """정적 규율을 만족하도록 편향된 주석."""
    from ses_core.coupling import components, members
    ports, void, coup = {}, set(), {}
    for e in components(T):
        ports[e] = {n: PortDecl(t, d) for n, (t, d) in POOL.items()}
    for e in sorted(T.nodes):
        if T.kind(e) == ENT and len(e) > 1 and T.kind(e[:-1]) == SPEC \
                and not T.children(e) and rng.random() < 0.3 and len(e) > 3:
            void.add(e)
    never_void = {e: not any(y in void for y in members(T, e)) for e in components(T)}
    for a in sorted(n for n in T.nodes if T.kind(n) == ASP):
        ks = set()
        for q in T.children(a):
            for t in ("T1", "T2"):
                if rng.random() < 0.5:                     # 필수 입력과 자신에서 오는 결합
                    d = ports[q][INS[t]]
                    ports[q][INS[t]] = PortDecl(d.type, d.direction, True)
                    ks.add(((SELF, INS[t]), (q[-1], INS[t])))
                if rng.random() < 0.4 and never_void[q]:
                    ks.add(((q[-1], OUTS[t]), (SELF, OUTS[t])))
                if rng.random() < 0.3:
                    other = rng.choice(T.children(a))
                    ks.add(((q[-1], OUTS[t]), (other[-1], INS[t])))
        if ks:
            coup[a] = tuple(sorted(ks, key=repr))
    ann = Ann(ports, frozenset(void), coup)
    validate(T, ann)
    return ann


def test_theorem12_static_discipline_is_sufficient():
    passed = rejected_but_fw = 0
    for seed in range(600):
        rng = random.Random(seed)
        T = rand_tree(rng)
        ann = disciplined_ann(rng, T)
        S = SES(T, rand_formula(rng, T))
        if not discipline_violations(T, ann):
            passed += 1
            assert family_wellformed(SES(T), ann)          # 제약이 없어도
            assert family_wellformed(S, ann)               # 어떤 제약 아래에서도
        elif family_wellformed(S, ann):
            rejected_but_fw += 1
    assert passed >= 100            # 공허하지 않음
    assert rejected_but_fw >= 1     # 충분조건일 뿐 필요조건이 아님


@pytest.mark.parametrize("seed", range(200))
def test_theorem12_on_noisy_annotations(seed):
    rng, T, ann = case(seed)
    if not discipline_violations(T, ann):
        assert family_wellformed(SES(T, rand_formula(rng, T)), ann)


# ---------------------------------------------------------------------------
# 정리 13: 결합 틀의 절단
# ---------------------------------------------------------------------------

RULE_POOL = [("in_each", "i", "x"), ("in_first", "i", "x"), ("in_last", "i", "x"),
             ("out_each", "y", "o"), ("out_first", "y", "o"), ("out_last", "y", "o"),
             ("next", "y", "x"), ("wrap", "y", "x"), ("pairs", "y", "x"),
             ("in_each", "i", "z"), ("next", "y", "z"), ("in_first", "i", "z")]


def rand_family(rng: random.Random):
    """소유자, 복제 틀, 결합 틀을 무작위로 고른다."""
    owner_ports = {"i": PortDecl("T", IN), "o": PortDecl("T", OUT, rng.random() < 0.5)}
    base = {"x": PortDecl("T", IN, rng.random() < 0.7), "y": PortDecl("T", OUT)}
    alts = []
    for _ in range(rng.choice([0, 0, 2, 3])):
        r = rng.random()
        if r < 0.35:
            alts.append("void")
        elif r < 0.7:
            alts.append({"z": PortDecl(rng.choice(["T", "T", "U"]), IN, rng.random() < 0.6)})
        else:
            alts.append({})
    rules = [r for r in RULE_POOL if rng.random() < 0.3]
    return owner_ports, base, alts, rules


def family_tree(family, cards):
    owner_ports, base, alts, rules = family
    kinds, ports, void, coup = {("X",): ENT}, {("X",): owner_ports}, set(), {}
    for n in cards:
        a = ("X", f"m[{n}]")
        kinds[a] = ASP
        names = [f"u{i}" for i in range(n)]
        for name in names:
            u = a + (name,)
            kinds[u] = ENT
            ports[u] = base
            if alts:
                kinds[u + ("s",)] = SPEC
                for j, alt in enumerate(alts):
                    c = u + ("s", f"c{j}")
                    kinds[c] = ENT
                    if alt == "void":
                        void.add(c)
                    elif alt:
                        ports[c] = alt
        coup[a] = instantiate(rules, names)
    T = Tree(kinds)
    ann = Ann(ports, frozenset(void), coup)
    validate(T, ann)
    return SES(T), ann


def test_theorem13_cutoff_at_three():
    outcomes, differs_at_two = set(), 0
    for seed in range(400):
        fam = rand_family(random.Random(seed))
        for profile in (False, True):                  # 자기 결합 금지 규약이 있어도 성립
            fw = {n: family_wellformed(*family_tree(fam, [n]), no_self_loop=profile)
                  for n in (2, 3, 4, 5)}
            assert fw[3] == fw[4] == fw[5]             # 3 이상은 모두 같다
            outcomes.add(fw[3])
            differs_at_two += fw[2] != fw[3]
            full = family_wellformed(*family_tree(fam, range(0, 6)), no_self_loop=profile)
            cut = family_wellformed(*family_tree(fam, cut_cardinalities(range(0, 6))),
                                    no_self_loop=profile)
            assert full == cut                         # 개수 집합을 {0, 1, 2, 3}으로 줄여도 같다
    assert outcomes == {True, False}                   # 두 결과가 모두 나타남
    assert differs_at_two >= 1                         # 절단 값 3은 더 줄일 수 없다


def test_cut_cardinalities():
    assert cut_cardinalities(range(1, 9)) == [1, 2, 3]
    assert cut_cardinalities([0, 5, 9]) == [0, 5]
    assert cut_cardinalities([2]) == [2]


# ---------------------------------------------------------------------------
# 손으로 만든 예: 선택적 구성요소
# ---------------------------------------------------------------------------

def optional_filter(bypass: bool):
    T = build(ent("System", asp("dec",
                                ent("Source"),
                                ent("Filter", spec("opt", ent("Real"), ent("NONE"))),
                                ent("Sink"))))
    dec = ("System", "dec")
    ports = {
        dec + ("Source",): {"o": PortDecl("Job", OUT)},
        dec + ("Filter",): {"i": PortDecl("Job", IN, True), "o": PortDecl("Job", OUT)},
        dec + ("Sink",): {"i": PortDecl("Job", IN, True)},
    }
    ks = [(("Source", "o"), ("Filter", "i")), (("Filter", "o"), ("Sink", "i"))]
    if bypass:
        ks.append((("Source", "o"), ("Sink", "i")))
    ann = Ann(ports, frozenset({dec + ("Filter", "opt", "NONE")}), {dec: tuple(ks)})
    validate(T, ann)
    return SES(T), ann


def test_optional_component_starves_required_port():
    S, ann = optional_filter(bypass=False)
    assert len(sem(S)) == 2 and not family_wellformed(S, ann)
    (V, vs), = ill_formed(S, ann)
    assert ("System", "dec", "Filter", "opt", "NONE") in V
    assert [code for code, _, _ in vs] == ["C4"]            # Sink.i 에 들어오는 결합이 사라짐
    assert discipline_violations(S.tree, ann)               # 정적 규율도 같은 결함을 잡는다
    core = wf_core(S, ann)                                  # 적격 핵: Filter가 사실상 필수
    assert is_pes(core)
    assert ("System", "dec", "Filter", "opt", "NONE") not in core.tree.nodes


def test_optional_component_with_bypass_is_family_wellformed():
    S, ann = optional_filter(bypass=True)
    assert family_wellformed(S, ann) and not discipline_violations(S.tree, ann)
    none = next(V for V in sem(S) if ("System", "dec", "Filter", "opt", "NONE") in V)
    model = realize(S.tree, ann, none)
    assert sorted(model[("System",)]["children"]) == ["Sink", "Source"]
    assert model[("System",)]["ic"] == [(("Source", "o"), ("Sink", "i"))]


def test_alternative_specific_port_needs_constraint():
    """대안이 추가한 포트를 가리키는 결합: 제약이 있어야 족 수준 적격이 된다."""
    T = build(ent("Sys",
                  asp("plain", ent("A")),
                  asp("wired", ent("B", spec("kind", ent("Basic"), ent("Extended"))))))
    wired = ("Sys", "wired")
    ext = wired + ("B", "kind", "Extended")
    ann = Ann({("Sys",): {"i": PortDecl("T", IN)}, ext: {"aux": PortDecl("T", IN)}},
              frozenset(), {wired: (((SELF, "i"), ("B", "aux")),)})
    assert not family_wellformed(SES(T), ann)               # Basic을 고르면 B.aux가 없다
    assert discipline_violations(T, ann)                    # 정적 규율은 항상 거부한다
    from ses_core.algebra import f_imp, sel
    S = SES(T, f_imp(sel(wired), sel(ext)))                 # wired이면 Extended
    assert family_wellformed(S, ann)                        # 제약 아래에서는 족 수준 적격
    assert family_wellformed_by_formula(S, ann)


def test_validate_rejects_bad_annotations():
    T = build(ent("S", asp("d", ent("A"))))
    with pytest.raises(AlgebraError):
        validate(T, Ann(coup={("S", "d"): (((SELF, "i"), ("Ghost", "i")),)}))
    with pytest.raises(AlgebraError):
        validate(T, Ann(void=frozenset({("S", "d", "A")})))


# ---------------------------------------------------------------------------
# 정준 YAML과의 연결
# ---------------------------------------------------------------------------

import copy  # noqa: E402

import yaml  # noqa: E402

from ses_core import load_ses, load_ses_dict  # noqa: E402
from ses_core.unfold import pruning_patterns, unfold_annotated, var_node  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")


@pytest.fixture
def raw():
    with open(os.path.join(EXAMPLES, "processing_system.ses.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_example_is_family_wellformed(raw):
    S, ann = unfold_annotated(load_ses_dict(raw))
    assert len(sem(S)) == 15
    assert family_wellformed(S, ann) and family_wellformed_by_formula(S, ann)
    assert family_wellformed(S, ann, no_self_loop=True)
    assert discipline_violations(S.tree, ann) == []       # 변이 열거 없이도 판정된다
    assert same(wf_core(S, ann), reduce(S))


def test_example_pes_realizes_a_coupled_model(raw):
    S, ann = unfold_annotated(load_ses_dict(raw))
    P = pruning_patterns(load_ses(os.path.join(EXAMPLES, "processing_system.pruning.ses.yaml")))
    R = prune(S, *P)
    V, = sem(R)
    assert wellformed(R.tree, ann, V)
    model = realize(R.tree, ann, V)
    top = model[("ProcessingSystem",)]
    assert sorted(top["children"]) == ["Buffer", "Collector", "Generator", "ServerPool"]
    assert len(top["ic"]) == 4 and not top["eic"] and not top["eoc"]
    pool = model[("ProcessingSystem", "pipelineDec", "ServerPool")]
    assert pool["children"] == [f"server_{i}" for i in range(4)]
    assert len(pool["eic"]) == 4 and len(pool["eoc"]) == 8 and not pool["ic"]


def test_example_with_zero_servers_is_not_family_wellformed(raw):
    bad = copy.deepcopy(raw)
    bad["variables"]["num_servers"]["range"] = [0, 8]
    S, ann = unfold_annotated(load_ses_dict(bad))
    assert len(sem(S)) == 16
    assert not family_wellformed(S, ann)
    (V, vs), = ill_formed(S, ann)                           # 서버가 0대인 변이 하나
    zero = ("ProcessingSystem", "pipelineDec", "ServerPool", "serversMAsp[0]")
    assert zero in V
    assert [(code, node) for code, node, _ in vs] == [("C4", zero)]   # ServerPool.out 이 구동되지 않음
    assert any(code == "D4" for code, _, _ in discipline_violations(S.tree, ann))
    core = wf_core(S, ann)                                  # 적격 핵은 0대를 제거한다
    assert len(sem(core)) == 15 and zero not in core.tree.nodes
    assert ("ProcessingSystem", var_node("num_servers"), "0") not in core.tree.nodes
    assert family_wellformed(core, ann)


def test_definition_level_type_error_is_rejected_by_loader(raw):
    bad = copy.deepcopy(raw)
    bad["entities"]["Server"]["ports"]["out"]["type"] = "Ack"   # 적재기는 통과하지만 풀의 out은 Job
    from ses_core import LoadError
    with pytest.raises(LoadError):
        load_ses_dict(bad)                                  # 정의 수준 검사가 먼저 잡는다


OPTIONAL = {
    "ses": "1.0", "name": "optional",
    "port_types": {"Job": {}},
    "entities": {
        "System": {"root": True, "aspects": {"dec": {
            "parts": ["Source", "Filter", "Sink"],
            "couplings": [{"from": "Source.o", "to": "Filter.i"},
                          {"from": "Filter.o", "to": "Sink.i"}]}}},
        "Source": {"ports": {"o": {"type": "Job", "direction": "out"}}},
        "Filter": {"ports": {"i": {"type": "Job", "direction": "in", "required": True},
                             "o": {"type": "Job", "direction": "out"}},
                   "specializations": {"opt": {"alternatives": ["RealFilter", "NoFilter"]}}},
        "RealFilter": {"extends": "Filter"},
        "NoFilter": {"extends": "Filter", "stereotype": "void"},
        "Sink": {"ports": {"i": {"type": "Job", "direction": "in", "required": True}}},
    },
}


def test_yaml_void_alternative():
    S, ann = unfold_annotated(load_ses_dict(OPTIONAL))
    assert not family_wellformed(S, ann)
    fixed = copy.deepcopy(OPTIONAL)
    fixed["entities"]["System"]["aspects"]["dec"]["couplings"].append(
        {"from": "Source.o", "to": "Sink.i"})
    S2, ann2 = unfold_annotated(load_ses_dict(fixed))
    assert family_wellformed(S2, ann2) and not discipline_violations(S2.tree, ann2)


def pipeline(max_n: int, with_first: bool = True, ring: bool = False):
    couplings = {"pattern": "ring" if ring else "chain",
                 "between": [{"from": "{i}.out", "to": "{next}.in"}],
                 "last": [{"from": "{part}.out", "to": "out"}]}
    if with_first:
        couplings["first"] = [{"from": "in", "to": "{part}.in"}]
    job_in = {"type": "Job", "direction": "in", "required": True}
    job_out = {"type": "Job", "direction": "out"}
    return {
        "ses": "1.0", "name": "pipeline", "port_types": {"Job": {}},
        "entities": {
            "Pipeline": {"root": True,
                         "ports": {"in": {"type": "Job", "direction": "in"},
                                   "out": {"type": "Job", "direction": "out", "required": True}},
                         "multi_aspects": {"stages": {
                             "part": "Stage", "cardinality": {"min": 1, "max": max_n},
                             "naming": "stage_{i}", "couplings": couplings}}},
            "Stage": {"ports": {"in": job_in, "out": job_out}},
        },
    }


def test_yaml_chain_pattern_and_cutoff():
    S, ann = unfold_annotated(load_ses_dict(pipeline(6)))
    assert len(sem(S)) == 6 and family_wellformed(S, ann)
    chain = ann.coup[("Pipeline", "stages[3]")]
    assert (("stage_0", "out"), ("stage_1", "in")) in chain and len(chain) == 4
    broken, ann_b = unfold_annotated(load_ses_dict(pipeline(6, with_first=False)))
    assert not family_wellformed(broken, ann_b)             # 첫 단의 입력이 구동되지 않음
    assert len(ill_formed(broken, ann_b)) == 6
    for with_first in (True, False):                        # 개수 범위를 3까지로 줄여도 판정이 같다
        full = unfold_annotated(load_ses_dict(pipeline(6, with_first)))
        cut = unfold_annotated(load_ses_dict(pipeline(3, with_first)))
        assert family_wellformed(*full) == family_wellformed(*cut)


def test_yaml_ring_pattern_self_loop_profile():
    S, ann = unfold_annotated(load_ses_dict(pipeline(4, with_first=False, ring=True)))
    assert family_wellformed(S, ann)                        # 고리가 모든 단의 입력을 구동
    assert not family_wellformed(S, ann, no_self_loop=True) # 1단이면 자기 자신으로의 결합
    bad = ill_formed(S, ann, no_self_loop=True)
    assert len(bad) == 1 and ("Pipeline", "stages[1]") in bad[0][0]
