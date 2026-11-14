"""SES 핵과 확장 계약의 공통 정리를 세 확장(DEVS 결합, 속성, 문서 조립)에 대해 검증한다.

정리 번호는 docs/ses-platform/11_ses_core_and_extensions.md 를 따른다.
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_algebra import rand_formula, rand_pattern, rand_selection, rand_tree  # noqa: E402
from test_coupling import rand_ann  # noqa: E402

from ses_core import load_ses, load_ses_dict  # noqa: E402
from ses_core import coupling as old  # noqa: E402
from ses_core.algebra import (  # noqa: E402
    ASP, ENT, SPEC, SES, Tree, asp, build, ent, is_pes, leq, reduce, restrict, sem, spec,
    variants)
from ses_core.coupling import Coupling  # noqa: E402
from ses_core.ext_attr import AttrDecl, Attributes  # noqa: E402
from ses_core.ext_text import Text  # noqa: E402
from ses_core.extension import (  # noqa: E402
    Extension, Layered, family_wellformed, ill_formed, interpret, prune, violations,
    wellformed, wf_core, wf_pattern)
from ses_core.skeleton import core_violations, skeleton  # noqa: E402
from ses_core.unfold import pruning_patterns, unfold, unfold_layered  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")
SEEDS = range(200)
KINDS = ["devs", "attr", "text", "devs+attr", "attr+text", "devs+attr+text"]


# ---------------------------------------------------------------------------
# 무작위 확장 자료
# ---------------------------------------------------------------------------

def rand_void(rng, T):
    # 정렬해서 돈다. 집합의 순회 순서는 실행마다 달라 표본이 재현되지 않는다
    return frozenset(e for e in sorted(T.nodes) if T.kind(e) == ENT and len(e) > 1
                     and T.kind(e[:-1]) == SPEC and not T.children(e) and rng.random() < 0.25)


def rand_attrs(rng, T, void):
    decls = {}
    for e in sorted(T.nodes):
        if T.kind(e) != ENT or e in void:
            continue
        d = {}
        for name in ("a", "b"):
            if rng.random() < 0.5:
                value = rng.choice([None, None, 1, 2])
                d[name] = AttrDecl("int" if rng.random() < 0.95 else "str", value, rng.random() < 0.3)
        if d:
            decls[e] = d
    return Attributes(decls)


def rand_text(rng, T, void):
    templates, layouts = {}, {}
    for e in sorted(T.nodes):
        if T.kind(e) != ENT or e in void or rng.random() < 0.5:
            continue
        names = sorted({q[-1] for a in T.aspects(e) for q in T.children(a)})
        slot = rng.choice(names) if names and rng.random() < 0.8 else "ghost"
        templates[e] = rng.choice(["<{*}>", "[" + e[-1] + "]", "{" + slot + "}", "{!" + slot + "}"])
    for a in sorted(n for n in T.nodes if T.kind(n) == ASP):
        names = [q[-1] for q in T.children(a)]
        rng.shuffle(names)
        layouts[a] = (tuple(names), rng.choice(["", ",", " "]))
    return Text(templates, layouts)


def rand_layered(seed, kind):
    rng = random.Random(seed)
    T = rand_tree(rng)
    ann = rand_ann(rng, T, noise=rng.choice([0.0, 0.0, 0.03]))
    exts = []
    for name in kind.split("+"):
        if name == "devs":
            exts.append(Coupling(ann.ports, ann.coup))
        elif name == "attr":
            exts.append(rand_attrs(rng, T, ann.void))
        else:
            exts.append(rand_text(rng, T, ann.void))
    return rng, Layered(SES(T, rand_formula(rng, T)), ann.void, tuple(exts))


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.ses.tree == b.ses.tree and set(sem(a.ses)) == set(sem(b.ses))


# ---------------------------------------------------------------------------
# 정리 14: 내재성과 보존 (모든 확장에 대해)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", SEEDS)
def test_theorem14_intrinsic_and_preserved(seed, kind):
    rng, L = rand_layered(seed, kind)
    T = L.ses.tree
    K = rand_selection(rng, T)
    sub = Layered(SES(restrict(T, K)), L.void, L.extensions)
    for V in variants(sub.ses.tree)[:40]:
        assert violations(sub, V) == violations(L, V)               # 적격성은 변이만으로 정해진다
        assert interpret(sub, V) == interpret(L, V)                 # 해석도 그렇다
    core = wf_core(L)
    if core is None:
        return
    assert family_wellformed(core)
    P = SES(rand_pattern(rng, T, extras=True), rand_formula(rng, T))
    R = prune(core, P)
    if R is not None:
        assert family_wellformed(R)                                 # 가지치기는 족 수준 적격성을 보존


# ---------------------------------------------------------------------------
# 정리 15: 적격 핵 (모든 확장에 대해)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", SEEDS)
def test_theorem15_wellformed_core(seed, kind):
    rng, L = rand_layered(seed, kind)
    good = {V for V in sem(L.ses) if wellformed(L, V)}
    core = wf_core(L)
    assert (set(sem(core.ses)) if core is not None else set()) == good
    if core is not None:
        assert same(wf_core(core), core)                            # 멱등
        assert leq(core.ses.tree, L.ses.tree)
    red = reduce(L.ses)
    assert family_wellformed(L) == same(core, Layered(red) if red is not None else None)
    P = SES(rand_pattern(rng, L.ses.tree, extras=True), rand_formula(rng, L.ses.tree))
    lp = prune(L, P)                                                # 가지치기와 교환
    assert same(wf_core(lp) if lp is not None else None,
                prune(core, P) if core is not None else None)
    assert same(wf_core(L, syntactic=False), core)                  # 술어 제약으로 해도 같다


# ---------------------------------------------------------------------------
# 정리 16: 확장의 합성은 순서와 무관하다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_theorem16_composition(seed):
    rng, L = rand_layered(seed, "devs+attr+text")
    x, y, z = L.extensions
    joint = wf_core(L)

    def chain(*order):
        cur = Layered(L.ses, L.void, ())
        for ext in order:
            step = wf_core(Layered(cur.ses, L.void, (ext,)))
            if step is None:
                return None
            cur = Layered(step.ses, L.void, ())
        return cur

    for order in ((x, y, z), (z, y, x), (y, x, z)):
        assert same(chain(*order), joint)
    for V in sem(L.ses)[:30]:                                       # 적격성은 계층별 적격성의 곱
        assert wellformed(L, V) == all(wellformed(Layered(L.ses, L.void, (e,)), V) for e in (x, y, z))
        out = interpret(L, V)                                       # 해석은 계층별 해석의 묶음
        if out is not None:
            for e in (x, y, z):
                assert out[e.name] == interpret(Layered(L.ses, L.void, (e,)), V)[e.name]


# ---------------------------------------------------------------------------
# 08 문서의 결합 이론은 확장 계약의 한 사례다
# ---------------------------------------------------------------------------

def flatten(node, path, out):
    out[path] = {k: sorted(map(repr, node[k])) for k in ("eic", "eoc", "ic")}
    out[path]["children"] = sorted(node["children"])
    for name, child in node["children"].items():
        flatten(child, path + (name,), out)
    return out


@pytest.mark.parametrize("seed", range(300))
def test_coupling_extension_agrees_with_direct_definition(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    ann = rand_ann(rng, T, noise=rng.choice([0.0, 0.0, 0.02, 0.06]))
    for profile in (False, True):
        L = Layered(SES(T), ann.void, (Coupling(ann.ports, ann.coup, profile),))
        for V in variants(T):
            assert wellformed(L, V) == old.wellformed(T, ann, V, profile)
    L = Layered(SES(T), ann.void, (Coupling(ann.ports, ann.coup),))
    for V in variants(T)[:20]:
        direct = old.realize(T, ann, V)
        mine = interpret(L, V)
        if mine is None:
            assert direct == {}
            continue
        if core_violations(T, ann.void, V):
            continue                    # 분해가 둘인 변이의 해석은 정의하지 않는다
        got = flatten(mine["devs"], (), {})
        assert len(got) == len(direct)
        for comp, node in direct.items():                           # 같은 결합 모델 구조
            key = next(k for k in got if _same_component(T, comp, k))
            assert sorted(node["children"]) == got[key]["children"]
            for part in ("eic", "eoc", "ic"):
                assert sorted(map(repr, node[part])) == got[key][part]


def _same_component(T, comp_path, name_path):
    # 구성 노드(aspect의 부분)의 이름만 모은다. 대안은 부모의 병합체에 합쳐진다
    names = tuple(comp_path[i] for i in range(1, len(comp_path)) if T.kind(comp_path[:i]) == ASP)
    return names == name_path


# ---------------------------------------------------------------------------
# 정의 표지: 09 문서의 결함 1.1의 회귀 테스트
# ---------------------------------------------------------------------------

POOL = {"ses": "1.0", "name": "x", "variables": {"n": {"type": "int", "range": [1, 3]}},
        "entities": {
            "Pool": {"root": True, "multi_aspects": {"m": {
                "part": "Server", "cardinality": {"var": "n"}, "naming": "server_{i}"}}},
            "Server": {"specializations": {"kind": {"alternatives": ["Fast", "Slow"]}}},
            "Fast": {"extends": "Server"}, "Slow": {"extends": "Server"}}}
ONLY_FAST = {"ses": "1.0", "name": "p", "entities": {
    "Pool": {"root": True},
    "Server": {"specializations": {"kind": {"alternatives": ["Fast"]}}},
    "Fast": {"extends": "Server"}}}


def test_definition_level_pattern_reaches_replicas():
    S = unfold(load_ses_dict(POOL))
    assert len(sem(S)) == 2 + 4 + 8
    from ses_core.algebra import is_uniform, prune as prune_ses
    R = prune_ses(S, *pruning_patterns(load_ses_dict(ONLY_FAST)))
    assert len(sem(R)) == 3                                         # 개수 선택만 남는다
    assert is_uniform(R.tree)                                       # 정의 수준 가지치기는 uniformity 보존


def test_definition_level_pattern_reaches_aliased_parts():
    doc = {"ses": "1.0", "name": "x", "entities": {
        "Sys": {"root": True, "aspects": {"dec": {"parts": [
            {"def": "Server", "alias": "primary"}, {"def": "Server", "alias": "backup"}]}}},
        "Server": {"specializations": {"kind": {"alternatives": ["Fast", "Slow"]}}},
        "Fast": {"extends": "Server"}, "Slow": {"extends": "Server"}}}
    S = unfold(load_ses_dict(doc))
    only_fast = dict(ONLY_FAST, entities=dict(ONLY_FAST["entities"], Sys={"root": True}))
    del only_fast["entities"]["Pool"]
    from ses_core.algebra import prune as prune_ses
    assert len(sem(S)) == 4
    assert len(sem(prune_ses(S, *pruning_patterns(load_ses_dict(only_fast))))) == 1


# ---------------------------------------------------------------------------
# 정준 YAML: SES + DEVS + Attr
# ---------------------------------------------------------------------------

def test_example_layers_from_yaml():
    L = unfold_layered(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))
    assert [x.name for x in L.extensions] == ["devs", "attr"]
    assert family_wellformed(L) and same(wf_core(L), Layered(reduce(L.ses)))
    P = pruning_patterns(load_ses(os.path.join(EXAMPLES, "processing_system.pruning.ses.yaml")))
    R = prune(L, *P)
    V, = sem(R.ses)
    out = interpret(R, V)
    top = out["devs"]
    assert sorted(top["children"]) == ["Buffer", "Collector", "Generator", "ServerPool"]
    assert len(top["children"]["ServerPool"]["eoc"]) == 8
    params = out["attr"]
    buf = params["children"]["Buffer"]
    assert buf["def"] == "PriorityBuffer"                           # 병합체의 확정된 정의
    assert buf["params"] == {"capacity": 100, "levels": 3}          # 부모와 대안의 속성이 합쳐짐
    servers = params["children"]["ServerPool"]["children"]
    assert sorted(servers) == [f"server_{i}" for i in range(4)]
    assert servers["server_0"]["params"] == {"service_time": 2.0}


def test_attribute_conflict_between_sibling_specializations():
    """한 엔티티의 두 specialization이 같은 속성에 다른 값을 주면 순서로 풀지 않고 충돌로 본다."""
    T = build(ent("Car", spec("engine", ent("Petrol"), ent("Electric")),
                  spec("trim", ent("Base"), ent("Sport"))))
    decls = {("Car",): {"power": AttrDecl("int", 100)},
             ("Car", "engine", "Electric"): {"power": AttrDecl("int", 150)},
             ("Car", "trim", "Sport"): {"power": AttrDecl("int", 200)}}
    L = Layered(SES(T), frozenset(), (Attributes(decls),))
    results = {}
    for V in sem(L.ses):
        key = tuple(sorted(n[-1] for n in V if len(n) == 3))
        results[key] = (wellformed(L, V), interpret(L, V)["attr"]["params"]["power"])
    assert results[("Base", "Petrol")] == (True, 100)               # 부모의 값
    assert results[("Base", "Electric")] == (True, 150)             # 대안이 덮어씀
    assert results[("Petrol", "Sport")] == (True, 200)
    assert results[("Electric", "Sport")][0] is False               # 두 대안이 다른 값: 충돌
    core = wf_core(L)
    assert len(sem(core.ses)) == 3


# ---------------------------------------------------------------------------
# 시뮬레이션이 아닌 분야: 문서 조립
# ---------------------------------------------------------------------------

def report(appendix_required: bool):
    T = build(ent("Report", asp("body",
                                ent("Intro", spec("tone", ent("Formal"), ent("Casual"))),
                                ent("Findings"),
                                ent("Appendix", spec("opt", ent("Tables"), ent("NoAppendix"))))))
    body = ("Report", "body")
    slot = "{!Appendix}" if appendix_required else "{Appendix}"
    templates = {
        ("Report",): "# 보고서\n{Intro}\n{Findings}\n" + slot,
        body + ("Intro", "tone", "Formal"): "본 보고서는 결과를 요약한다.",
        body + ("Intro", "tone", "Casual"): "결과를 간단히 정리했다.",
        body + ("Findings",): "변이는 15개다.",
        body + ("Appendix", "opt", "Tables"): "부록: 표",
    }
    void = frozenset({body + ("Appendix", "opt", "NoAppendix")})
    return Layered(SES(T), void, (Text(templates, {body: (("Intro", "Findings", "Appendix"), "\n")}),))


def test_text_extension_renders_every_variant():
    L = report(appendix_required=False)
    assert len(sem(L.ses)) == 4 and family_wellformed(L)
    docs = {interpret(L, V)["text"] for V in sem(L.ses)}
    assert "# 보고서\n본 보고서는 결과를 요약한다.\n변이는 15개다.\n부록: 표" in docs
    assert "# 보고서\n결과를 간단히 정리했다.\n변이는 15개다.\n" in docs      # 부록 없음
    assert len(docs) == 4


def test_text_extension_family_check_uses_the_same_core():
    L = report(appendix_required=True)
    assert not family_wellformed(L)
    bad = ill_formed(L)
    assert len(bad) == 2 and all(v[0][:2] == ("text", "X2") for _, v in bad)
    core = wf_core(L)                                               # 적격 핵: 부록이 사실상 필수
    assert len(sem(core.ses)) == 2
    assert ("Report", "body", "Appendix", "opt", "NoAppendix") not in core.ses.tree.nodes


def test_extension_sees_only_the_skeleton():
    """확장은 View만 받는다. 선택되지 않은 노드는 보이지 않는다."""
    seen = []

    class Spy(Extension):
        name = "spy"

        def entity(self, path):
            return path

        def merge(self, tree, items):
            return tuple(p for p, _ in items), []

        def check(self, v):
            seen.append(set(v.ann))
            return []

    T = build(ent("A", asp("d", ent("B", spec("s", ent("C1"), ent("C2"))))))
    L = Layered(SES(T), frozenset(), (Spy(),))
    V = next(v for v in variants(T) if ("A", "d", "B", "s", "C1") in v)
    assert wellformed(L, V)
    assert all(members <= V for members in seen)
    assert ("A", "d", "B", "s", "C2") not in set().union(*seen)


# ---------------------------------------------------------------------------
# 확장이 하나도 없을 때: 핵 적격성만으로도 적격 핵이 정해진다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(150))
def test_core_wellformedness_without_extensions(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    void = rand_void(rng, T)
    L = Layered(SES(T, rand_formula(rng, T)), void, ())
    good = {V for V in sem(L.ses) if not core_violations(T, void, V)}
    for V in sem(L.ses):
        assert wellformed(L, V) == (V in good)
    core = wf_core(L)
    assert (set(sem(core.ses)) if core is not None else set()) == good
    if core is not None:
        assert all(skeleton(T, void, V) is not None for V in sem(core.ses))


def test_core_only_sample_is_not_vacuous():
    mixed = 0
    for seed in range(150):
        rng = random.Random(seed)
        T = rand_tree(rng)
        void = rand_void(rng, T)
        vs = variants(T)
        bad = sum(bool(core_violations(T, void, V)) for V in vs)
        mixed += 0 < bad < len(vs)
    assert mixed >= 30
