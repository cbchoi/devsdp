"""결정이 끝난 변이 하나를 위에서 아래로 만드는 길 (docs/ses-platform/18_classic_parity.md 5절).

족 전체를 펼치는 길(unfold, 결정 집합의 적용, 변이 열거)과 같은 결과를 내는지를 본다.
- 만들어지면: 결정 집합을 적용한 족에서 합칠 수 있는 변이는 정확히 하나이고, 직접 만든 변이와 노드까지 같다.
  뼈대, 위반 목록, 해석, 계획도 같다. 합칠 수 없는 변이(분해가 둘 이상 선택된 것, K1)는 직접 만드는 길이
  내놓지 않는다.
- 만들 수 없다고 하면: 족 전체를 펼친 길에도 합칠 수 있는 변이가 없다.
- 결정이 모자라다고 하면: 아무것도 주장하지 않는다.
빠진 구성요소의 아래에 걸린 결정은 두 길 모두 쓰지 않는다(18 문서 5.3절).
그리고 족 전체를 펼칠 수 없는 크기에서 실제로 만들어지는지를 본다.
"""

import collections
import os
import random
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import rand_binding, rand_system_document  # noqa: E402
from test_executor import UNIT, library_of, named  # noqa: E402
from test_params import FUNCTIONS as VALUE_FUNCTIONS, with_values  # noqa: E402
from test_parity import decorated, prioritized  # noqa: E402

from ses_core import direct, load_ses, load_ses_dict  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core.algebra import AlgebraError, occurrences, sem  # noqa: E402
from ses_core.decisions import (Choice, DecisionSet, Override, apply, choice_table, component_path,  # noqa: E402
                                decide, load_decisions, patterns, with_overrides, witness)
from ses_core.direct import Contradiction, Undecided  # noqa: E402
from ses_core.executor import Binding  # noqa: E402
from ses_core.extension import Layered, interpret, violations  # noqa: E402
from ses_core.skeleton import GONE, NO_ASPECT, assignment, core_violations, skeleton  # noqa: E402
from ses_core.unfold import unfold_layered, variable_domains  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")
STATS: collections.Counter = collections.Counter()


def facts(L: Layered, V: frozenset) -> tuple:
    """변이에서 확장과 실행기가 보는 것 전부: 변수 값, 뼈대, 위반 목록, 해석."""
    T = L.ses.tree
    return (tuple(sorted(assignment(T, V).items())), skeleton(T, L.void, V), violations(L, V), interpret(L, V))


def mergeable(L: Layered, V: frozenset) -> bool:
    """병합체마다 분해가 하나 이하인가. 아니면 절차로는 만들 수 없는 변이다."""
    return not any(code == "K1" for code, _, _ in core_violations(L.ses.tree, L.void, V))


def classes(L: Layered, variants) -> set:
    """합칠 수 있는 변이들이 이루는 서로 다른 facts 의 모음. 없음이 된 곳에서만 다른 변이들은 하나로 모인다."""
    return {repr(facts(L, V)) for V in variants if mergeable(L, V)}


def document(kind: str, seed: int) -> tuple:
    """무작위 문서와 그 문서의 식이 부르는 함수들. 네 가지 생성기를 돌려 쓴다."""
    if kind == "plain":
        return load_ses_dict(rand_system_document(random.Random(seed))), None
    if kind == "rules":
        _, doc, functions = decorated(seed)
        return doc, functions
    if kind == "priorities":
        _, doc, functions = prioritized(seed)
        return doc, functions
    _, doc = with_values(seed)
    return doc, VALUE_FUNCTIONS


KINDS = ("plain", "rules", "priorities", "values")


# ---------------------------------------------------------------------------
# 1. 변이를 정확히 재현하는 결정 집합에서: 직접 만든 것이 그 변이와 같다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(100))
def test_a_variant_named_by_its_witness_is_built_directly(kind, seed):
    """족의 변이 하나를 고르고, 그것을 재현하는 결정 집합으로 직접 만든다. 같은 것이 나와야 한다."""
    doc, functions = document(kind, seed)
    L = unfold_layered(doc, functions=functions)
    T = L.ses.tree
    rng = random.Random(seed)
    variants = sem(L.ses)
    for V in rng.sample(variants, min(3, len(variants))):
        ds = witness(T, V, variable_domains(doc))
        if not mergeable(L, V):
            with pytest.raises(Contradiction, match="분해"):
                direct.build(doc, ds, functions=functions)       # 합칠 수 없는 변이는 만들지 않는다
            STATS["witness_unmergeable"] += 1
            continue
        b = direct.build(doc, ds, functions=functions)
        assert b.variant == V                                    # 족의 변이와 노드까지 같다. 빠짐과 밀림의 표시도 같다
        assert facts(b.layered, b.variant) == facts(L, V)
        assert sem(b.layered.ses) == [b.variant]                 # 만든 것은 변이가 하나뿐인 SES다
        assert b.unused == ()                                    # 증거는 빠진 곳을 가리키지 않는다
        STATS["witness_built"] += 1
        STATS["witness_with_gone"] += any(n[-1] == GONE for n in V)
        STATS["witness_with_pushed"] += any(n[-1] == NO_ASPECT for n in V)
        assert sem(apply(L.ses, ds)) == [V]


@pytest.mark.parametrize("seed", range(150))
def test_direct_plans_equal_the_plans_of_the_family(seed):
    """실행기를 붙였을 때의 계획과 실행 가능성도 같다."""
    rng = random.Random(seed)
    d = rand_system_document(rng)
    doc = load_ses_dict(d)
    L0 = unfold_layered(doc)
    b, mods = rand_binding(rng, d, "x")
    binding, library = Binding.from_dict(dict(b, time_unit=UNIT)), library_of(mods)
    L, ext = X.attach(L0, named("x"), binding, library)
    variants = sem(L.ses)
    for V in rng.sample(variants, min(3, len(variants))):
        if not mergeable(L, V):
            continue                                             # 합칠 수 없는 변이는 직접 만들지 않는다
        built = direct.build(doc, witness(L.ses.tree, V, variable_domains(doc)))
        LD, extD = X.attach(built.layered, named("x"), binding, library)
        assert X.plan(LD, extD, built.variant) == X.plan(L, ext, V)
        assert violations(X.alone(LD, extD), built.variant) == violations(X.alone(L, ext), V)
        assert X.executable(LD, extD, built.variant) == X.executable(L, ext, V)
        STATS["plans"] += 1
        STATS["plans_executable"] += X.executable(L, ext, V)


# ---------------------------------------------------------------------------
# 2. 사람이 적는 결정에서: 변수 값과 정의 수준, 구성요소 수준의 결정을 무작위로
# ---------------------------------------------------------------------------

def rand_decisions(rng: random.Random, doc, L: Layered) -> DecisionSet:
    """변수 값을 모두 정하고, 선택 지점 몇 곳에 정의 수준이나 구성요소 수준의 결정을 둔다. 서로 어긋날 수 있다."""
    T = L.ses.tree
    ds = DecisionSet()
    for name, domain in variable_domains(doc).items():
        ds = ds.assign(name, rng.choice(domain))
    points = [p for p in choice_table(L.ses, L.ses) if p.kind != "variable"]
    for point in rng.sample(points, min(len(points), rng.randint(0, 5))):
        option = rng.choice([o for o, _ in point.options])
        ds = ds.pick(point, option)                              # 정의 수준
        if rng.random() < 0.4:                                   # 같은 선택 지점을 구성요소 하나에서 다르게
            y = rng.choice(occurrences(T, point.owner))
            other = rng.choice([o for o, _ in point.options])
            what = {"aspect": dict(aspect=(other,)), "count": dict(multi_aspect=point.group, count=(other,)),
                    "alternative": dict(specialization=point.group, alternative=(other,))}[point.kind]
            ds = ds.decide(Choice(path=component_path(T, y), **what))
    return ds


def inferred(doc, functions, L, ds) -> None:
    """적힌 결정만으로는 모자랄 때. 결정 집합이 족을 변이 하나로 줄이면 infer 가 그 변이를 만든다."""
    R = apply(L.ses, ds)
    left = sem(R) if R is not None else []
    more = direct.completed(doc, ds, functions)
    assert (more is not None) == (len(left) == 1)                # 남은 변이가 하나일 때, 그때만 채운다
    try:
        b = direct.build(doc, ds, functions=functions, infer=True)
    except Undecided:
        STATS["infer_still_undecided"] += len(left) == 1         # 자리마다 다르게 정해져 정의의 결정으로 적을 수 없는 경우
        return
    except Contradiction:
        assert len(left) == 1 and not mergeable(L, left[0])      # 하나 남은 변이가 합칠 수 없는 것이다
        STATS["infer_contradiction"] += 1
        return
    assert left == [b.variant]                                   # 만든 것이 그 하나 남은 변이다
    assert set(b.unused) <= {c.key for c in ds.choose} | {o.key for o in ds.set}
    STATS["infer_built"] += 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(150))
def test_direct_build_agrees_with_the_family_under_random_decisions(kind, seed):
    doc, functions = document(kind, seed)
    L = unfold_layered(doc, functions=functions)
    rng = random.Random(seed * 7 + 1)
    for _ in range(4):
        ds = rand_decisions(rng, doc, L)
        try:
            patterns(L.ses, ds)
        except AlgebraError:
            STATS["random_stale"] += 1                           # 대상에 없는 선택지를 남기려는 결정. 여기서는 보지 않는다
            continue
        try:
            b = direct.build(doc, ds, functions=functions)
        except Undecided:
            STATS["random_undecided"] += 1
            inferred(doc, functions, L, ds)
            continue
        except Contradiction:
            R = apply(L.ses, ds)                                 # 만들 수 없다고 했으면 족에도 합칠 수 있는 변이가 없다
            assert R is None or not any(mergeable(L, W) for W in sem(R))
            STATS["random_contradiction"] += 1
            STATS["random_contradiction_empty"] += R is None
            continue
        R = apply(L.ses, ds)                                     # 결정 집합 전체. 쓰이지 않은 결정도 족을 비우지 않는다
        assert R is not None
        assert [W for W in sem(R) if mergeable(L, W)] == [b.variant]
        STATS["random_built"] += 1
        STATS["random_unused"] += bool(b.unused)
        STATS["random_with_gone"] += any(n[-1] == GONE for n in b.variant)


# ---------------------------------------------------------------------------
# 3. 손으로 만든 예
# ---------------------------------------------------------------------------

SHOP = {"ses": "1.0", "name": "Shop",
        "variables": {"n": {"type": "int", "range": [1, 3], "default": 2},
                      "mode": {"type": "enum", "values": ["a", "b"]}},
        "entities": {
            "Shop": {"root": True, "aspects": {"d": {"parts": ["Line", "Store"]}}},
            "Line": {"multi_aspects": {"cells": {"part": "Cell", "cardinality": {"var": "n"}, "naming": "c{i}"}}},
            "Cell": {"attributes": {"t": {"type": "int", "default": 1}},
                     "specializations": {"kind": {"alternatives": ["Fast", "Slow"], "default": "Slow"}}},
            "Fast": {"extends": "Cell", "attributes": {"t": {"type": "int", "default": 9}}},
            "Slow": {"extends": "Cell"},
            "Store": {"specializations": {
                "size": {"alternatives": ["Big", "Small", "NoStore"],
                         "select": {"when": {"var": "mode", "eq": "a"}, "then": "Big"}}},
                      "aspects": {"racks": {"parts": ["Rack"]}}},
            "Big": {"extends": "Store"}, "Small": {"extends": "Store"},
            "NoStore": {"extends": "Store", "stereotype": "void"},
            "Rack": {"specializations": {"r": {"alternatives": ["Steel", "Wood"]}}},
            "Steel": {"extends": "Rack"}, "Wood": {"extends": "Rack"}}}
ALL_FAST = Choice(at="Cell", specialization="kind", alternative=("Fast",))
STEEL = Choice(at="Rack", specialization="r", alternative=("Steel",))


def shop(**variables):
    return DecisionSet(variables={k: (v,) for k, v in variables.items()})


def test_undecided_choice_points_are_named():
    doc = load_ses_dict(SHOP)
    with pytest.raises(Undecided, match="변수 n") as e:
        direct.build(doc, shop(mode="a"))
    assert (e.value.where, e.value.kind, e.value.group, e.value.options) == ((), "variable", "n", [1, 2, 3])
    with pytest.raises(Undecided, match="Shop/Line/c0: specialization kind 의 대안") as e:
        direct.build(doc, shop(mode="a", n=2))
    assert (e.value.where, e.value.options) == (("Shop", "Line", "c0"), ["Fast", "Slow"])
    with pytest.raises(Undecided, match="Shop/Store/Rack") as e:           # 규칙이 Big 을 고른 뒤의 선택 지점
        direct.build(doc, shop(mode="a", n=2).decide(ALL_FAST))
    with pytest.raises(Undecided, match="Shop/Store: specialization size") as e:
        direct.build(doc, shop(mode="b", n=2).decide(ALL_FAST))            # 규칙이 정하지 않는 변수 값
    assert e.value.options == ["Big", "Small", "NoStore"]
    b = direct.build(doc, shop(mode="a", n=2).decide(ALL_FAST).decide(STEEL))
    sk = skeleton(b.layered.ses.tree, b.layered.void, b.variant)
    assert sorted(sk.parts["Line"].parts) == ["c0", "c1"] and sk.parts["Store"].labels == ("Store", "Big")
    assert b.sigma == {"n": 2, "mode": "a"} and b.unused == ()
    assert set(b.used) == {ALL_FAST.key, STEEL.key}


def test_a_removed_component_is_not_built_and_its_decisions_are_not_needed():
    doc = load_ses_dict(SHOP)
    none = Choice(at="Store", specialization="size", alternative=("NoStore",))
    b = direct.build(doc, shop(mode="b", n=1).decide(ALL_FAST).decide(none))     # Rack 의 종류를 묻지 않는다
    sk = skeleton(b.layered.ses.tree, b.layered.void, b.variant)
    assert sk.absent == ("Store",) and not any("Rack" in n for n in b.variant)
    again = direct.build(doc, shop(mode="b", n=1).decide(ALL_FAST).decide(none).decide(STEEL))
    assert again.variant == b.variant and again.unused == (STEEL.key,)          # 쓰이지 않은 결정을 알려 준다


def test_defaults_are_used_only_when_asked():
    doc = load_ses_dict(SHOP)
    big = Choice(at="Store", specialization="size", alternative=("Big",))
    ds = shop(mode="b").decide(big).decide(STEEL)
    with pytest.raises(Undecided):
        direct.build(doc, ds)
    b = direct.build(doc, ds, use_defaults=True)
    assert b.sigma["n"] == 2                                                    # 변수의 기본값
    sk = skeleton(b.layered.ses.tree, b.layered.void, b.variant)
    assert [sk.parts["Line"].parts[c].labels for c in ("c0", "c1")] == [("Cell", "Slow")] * 2   # specialization 의 기본값


def test_decisions_by_component_path_and_overrides_reach_single_replicas():
    doc = load_ses_dict(SHOP)
    ds = shop(mode="a", n=3).decide(STEEL).decide(ALL_FAST) \
        .decide(Choice(path=("Shop", "Line", "c1"), specialization="kind", alternative=("Fast", "Slow")))
    b = direct.build(doc, ds)                                                   # 정의 수준과 경로 수준은 모두 적용된다
    assert b.unused == ()
    ds = shop(mode="a", n=3).decide(STEEL) \
        .decide(Choice(path=("Shop", "Line", "c0"), specialization="kind", alternative=("Fast",))) \
        .decide(Choice(path=("Shop", "Line", "c1"), specialization="kind", alternative=("Slow",))) \
        .decide(Choice(path=("Shop", "Line", "c2"), specialization="kind", alternative=("Fast",))) \
        .override(Override("t", 5, path=("Shop", "Line", "c2"))) \
        .override(Override("t", 3, at="Cell")) \
        .override(Override("t", 7, path=("Shop", "Line", "c9")))
    b = direct.build(doc, ds)
    line = interpret(b.layered, b.variant)["attr"]["children"]["Line"]["children"]
    assert [line[c]["params"]["t"] for c in ("c0", "c1", "c2")] == [9, 3, 5]
    assert b.unused == (("set", "path", ("Shop", "Line", "c9"), "t"),)
    L = with_overrides(unfold_layered(doc), ds, skip_invalid=True)              # 족 전체를 펼친 길과 같다
    (V,) = sem(apply(L.ses, ds))
    assert facts(Layered(apply(L.ses, ds), L.void, L.extensions), V) == facts(b.layered, b.variant)


def test_contradictions_are_reported_where_they_arise():
    doc = load_ses_dict(SHOP)
    small = Choice(at="Store", specialization="size", alternative=("Small",))
    with pytest.raises(Contradiction, match="Shop/Store: specialization size 에 남는 대안이 없다"):
        direct.build(doc, shop(mode="a", n=1).decide(ALL_FAST).decide(small))    # 규칙은 Big, 결정은 Small
    d = dict(SHOP, constraints=[{"name": "no_fast_with_three", "when": {"var": "n", "eq": 3},
                                 "forbid": {"selected": "Cell/kind=Fast"}}])
    doc = load_ses_dict(d)
    with pytest.raises(Contradiction, match="제약 no_fast_with_three 을 어긴다"):
        direct.build(doc, shop(mode="a", n=3).decide(ALL_FAST).decide(STEEL))
    direct.build(doc, shop(mode="a", n=2).decide(ALL_FAST).decide(STEEL))


def test_decisions_that_do_not_fit_the_document_are_refused_like_in_the_family():
    """정의 수준의 결정과 재정의가 문서에 맞지 않으면, 족 전체를 펼친 길과 같은 까닭으로 멈춘다."""
    doc = load_ses_dict(SHOP)
    L = unfold_layered(doc)
    base = shop(mode="a", n=1).decide(ALL_FAST).decide(STEEL)
    cases = [
        (base.decide(Choice(at="Nobody", aspect=("d",))), "결정이 가리키는 곳이 대상에 없다"),
        (base.decide(Choice(at="Cell", specialization="colour", alternative=("Red",))), "선택 지점이 대상에 없다"),
        (base.decide(Choice(at="Cell", specialization="kind", alternative=("Quick",))), "남기려는 선택지가 대상에 없다"),
        (base.decide(Choice(at="Line", multi_aspect="cells", count=(7,))), "남기려는 선택지가 대상에 없다"),
        (base.decide(Choice(at="Line", multi_aspect="rows", count=(1,))), "선택 지점이 대상에 없다"),
        (base.decide(Choice(at="Shop", aspect=("e",))), "남기려는 선택지가 대상에 없다"),
        (base.decide(Choice(at="Cell", aspect=("x",))), "선택 지점이 대상에 없다"),
        (base.decide(Choice(at="Cell")), "aspect, specialization, multi_aspect 가운데 정확히 하나"),
        (base.assign("n", 9), "남기려는 선택지가 대상에 없다"),
        (base.assign("speed", 1), "선택 지점이 대상에 없다"),
    ]
    for ds, why in cases:
        with pytest.raises(AlgebraError, match=why):
            direct.build(doc, ds)
        with pytest.raises(AlgebraError, match=why):
            patterns(L.ses, ds)
    for o, why in [(Override("t", 1, at="Nobody"), "가리키는 곳이 대상에 없다"),
                   (Override("u", 1, at="Cell"), "정의 Cell 에 속성 u 가 없다"),
                   (Override("t", "x", at="Cell"), "타입 int 에 맞지 않다"),
                   (Override("t", "x", path=("Shop", "Line", "c0")), "타입 int 에 맞지 않다"),
                   (Override("t", None, at="Cell"), "value 는 값 하나")]:
        with pytest.raises(AlgebraError, match=why):
            direct.build(doc, base.override(o))
        with pytest.raises(AlgebraError, match=why):
            with_overrides(L, base.override(o))


def test_decisions_under_a_removed_component_are_not_used_by_either_path():
    """없음이 된 구성요소 아래에서 결정이 규칙과 어긋나도 두 길 모두 그 결정을 쓰지 않는다.

    고치기 전에는 족 전체를 펼친 길이 남는 변이가 없다고 했다. 대수가 빠진 구성요소의 아래에서도 선택을
    요구했기 때문이다(18 문서 5.3절)."""
    d = {"ses": "1.0", "name": "R", "variables": {"v": {"type": "int", "range": [1, 2]}},
         "entities": {
             "R": {"root": True, "aspects": {"d": {"parts": ["Opt"]}}},
             "Opt": {"specializations": {"opt": {"alternatives": ["NoOpt", "WithOpt"]}},
                     "aspects": {"inner": {"parts": ["Leaf"]}}},
             "NoOpt": {"extends": "Opt", "stereotype": "void"}, "WithOpt": {"extends": "Opt"},
             "Leaf": {"specializations": {"k": {"alternatives": ["A", "B"], "select": {
                 "when": {"var": "v", "eq": 1}, "then": "A", "else": "B"}}}},
             "A": {"extends": "Leaf"}, "B": {"extends": "Leaf"}}}
    doc = load_ses_dict(d)
    L = unfold_layered(doc)
    none = Choice(at="Opt", specialization="opt", alternative=("NoOpt",))
    stray = Choice(at="Leaf", specialization="k", alternative=("B",))             # v = 1 에서 규칙은 A 를 고른다
    ds = DecisionSet(variables={"v": (1,)}, choose=(none, stray))
    b = direct.build(doc, ds)
    assert skeleton(b.layered.ses.tree, b.layered.void, b.variant).absent == ("Opt",) and b.unused == (stray.key,)
    assert sem(apply(L.ses, ds)) == [b.variant]
    assert ("R", "d", "Opt", GONE) in b.variant and not [n for n in b.variant if "inner" in n]
    live = DecisionSet(variables={"v": (1,)}, choose=(Choice(at="Opt", specialization="opt", alternative=("WithOpt",)),
                                                      stray))
    with pytest.raises(Contradiction):                                            # 살아 있는 곳에서는 두 길 모두 어긋남이다
        direct.build(doc, live)
    assert apply(L.ses, live) is None
    # 개수 변수와 결정이 빠진 곳에서 어긋나는 경우, 같은 곳에 결정 둘이 어긋나는 경우도 같다
    pool = {"ses": "1.0", "name": "R", "variables": {"n": {"type": "int", "range": [1, 3]}},
            "entities": {"R": {"root": True, "aspects": {"d": {"parts": ["X"]}}},
                         "X": {"specializations": {"has": {"alternatives": ["NoX", "WithX"]}},
                               "multi_aspects": {"m": {"part": "Y", "cardinality": {"var": "n"}}}},
                         "NoX": {"extends": "X", "stereotype": "void"}, "WithX": {"extends": "X"},
                         "Y": {"specializations": {"k": {"alternatives": ["A", "B"]}}},
                         "A": {"extends": "Y"}, "B": {"extends": "Y"}}}
    doc = load_ses_dict(pool)
    L = unfold_layered(doc)
    gone = Choice(at="X", specialization="has", alternative=("NoX",))
    for odd in (DecisionSet(variables={"n": (3,)}, choose=(gone, Choice(at="X", multi_aspect="m", count=(2,)))),
                DecisionSet(variables={"n": (1,)}, choose=(gone, Choice(at="Y", specialization="k", alternative=("A",)),
                                                           Choice(path=("R", "X", "Y_0"), specialization="k",
                                                                  alternative=("B",))))):
        b = direct.build(doc, odd)
        assert sem(apply(L.ses, odd)) == [b.variant] and len(b.unused) == len(odd.choose) - 1


def test_overrides_at_a_removed_component_are_reported_unused():
    """빠진 구성요소를 가리킨 속성 재정의는 쓰이지 않는다. 경로로 가리켜도, 그 구성요소에만 있는 정의로 가리켜도 그렇다.
    족을 비우지도 않는다."""
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "aspects": {"d": {"parts": ["Opt", "Keep"]}}},
                      "Opt": {"attributes": {"w": {"type": "int", "default": 1}},
                              "specializations": {"opt": {"alternatives": ["NoOpt", "WithOpt"]}}},
                      "NoOpt": {"extends": "Opt", "stereotype": "void"}, "WithOpt": {"extends": "Opt"},
                      "Keep": {"attributes": {"w": {"type": "int", "default": 1}}}}}
    doc = load_ses_dict(d)
    by_path, by_def, kept = Override("w", 5, path=("R", "Opt")), Override("w", 6, at="Opt"), Override("w", 7, at="Keep")
    gone = DecisionSet(choose=(Choice(at="Opt", specialization="opt", alternative=("NoOpt",)),), set=(by_path, by_def, kept))
    b = direct.build(doc, gone)
    assert b.unused == (by_path.key, by_def.key)
    assert interpret(b.layered, b.variant)["attr"]["children"] == {"Keep": {"def": "Keep", "params": {"w": 7}, "children": {}}}
    L = decide(unfold_layered(doc), gone)
    assert sem(L.ses) == [b.variant] and interpret(L, b.variant) == interpret(b.layered, b.variant)
    here = DecisionSet(choose=(Choice(at="Opt", specialization="opt", alternative=("WithOpt",)),), set=(by_path, by_def, kept))
    b = direct.build(doc, here)
    assert b.unused == () and interpret(b.layered, b.variant)["attr"]["children"]["Opt"]["params"] == {"w": 5}


def test_an_unmergeable_component_is_named():
    """분해를 가진 정의가 둘 합쳐졌는데 우선순위로 가를 수 없으면, 결정이 모자란 것이 아니라 합칠 수 없는 것이다."""
    d = {"ses": "1.0", "name": "a",
         "entities": {"a": {"root": True, "aspects": {"aDEC": {"parts": ["b"]}},
                            "specializations": {"aSPEC": {"alternatives": ["d", "e"]}}},
                      "d": {"extends": "a"}, "e": {"extends": "a", "aspects": {"eDEC": {"parts": ["f"]}}},
                      "b": {}, "f": {}}}
    doc = load_ses_dict(d)
    pick = DecisionSet(choose=(Choice(at="a", specialization="aSPEC", alternative=("e",)),))
    with pytest.raises(Contradiction, match="a: 분해를 하나로 정할 수 없다. 분해를 가진 정의 \\['a', 'e'\\]"):
        direct.build(doc, pick)
    d["entities"]["e"]["aspects"]["eDEC"]["priority"] = 1                       # 우선순위를 주면 합쳐진다
    b = direct.build(load_ses_dict(d), pick)
    assert skeleton(b.layered.ses.tree, b.layered.void, b.variant).parts.keys() == {"f"}


def test_an_unbounded_cardinality_is_built_once_the_count_is_decided():
    """개수에 상한이 없는 multi-aspect 는 족으로 펼칠 수 없다. 개수가 정해지면 직접 만들 수 있다."""
    d = {"ses": "1.0", "name": "Farm",
         "entities": {"Farm": {"root": True, "multi_aspects": {"m": {"part": "Unit", "cardinality": {"min": 2}}}},
                      "Unit": {"attributes": {"i": {"type": "int", "expr": {"replica": "index"}}}}}}
    doc = load_ses_dict(d)
    with pytest.raises(AlgebraError, match="상한이 필요하다"):
        unfold_layered(doc)
    with pytest.raises(Undecided, match="개수") as e:
        direct.build(doc)
    assert e.value.options == ["2 이상"]
    with pytest.raises(AlgebraError, match="남기려는 선택지가 대상에 없다"):
        direct.build(doc, DecisionSet(choose=(Choice(at="Farm", multi_aspect="m", count=(1,)),)))
    b = direct.build(doc, DecisionSet(choose=(Choice(at="Farm", multi_aspect="m", count=(40,)),)))
    units = interpret(b.layered, b.variant)["attr"]["children"]
    assert len(units) == 40 and [u["params"]["i"] for u in units.values()] == list(range(40))


def test_the_example_decision_files_build_the_same_model_directly():
    doc = load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml"))
    L = unfold_layered(doc)
    for name in ("processing_system.decisions.yaml", "processing_system.decisions.tuned.yaml"):
        ds = load_decisions(os.path.join(EXAMPLES, name))
        over = with_overrides(L, ds)
        R = apply(L.ses, ds)
        (V,) = sem(R)
        b = direct.build(doc, ds)
        assert facts(b.layered, b.variant) == facts(Layered(R, over.void, over.extensions), V)
        assert b.variant == V and b.unused == ()


# ---------------------------------------------------------------------------
# 4. 규모: 족으로 펼칠 수 없는 크기
# ---------------------------------------------------------------------------

def field(limit: int) -> dict:
    """복제본이 limit 개까지인 센서장. 노드마다 감지기와 무선기를 가지고 종류가 둘이다."""
    port = lambda d: {"type": "M", "direction": d}                                # noqa: E731
    return {"ses": "1.0", "name": "Field", "port_types": {"M": {}},
            "variables": {"nodes": {"type": "int", "range": [1, limit]}},
            "entities": {
                "Field": {"root": True, "aspects": {"d": {"parts": ["Sink", "Net"], "couplings": [
                    {"from": "Net.out", "to": "Sink.in"}]}}},
                "Sink": {"ports": {"in": port("in")}},
                "Net": {"ports": {"out": port("out")},
                        "multi_aspects": {"nodes": {"part": "Node", "cardinality": {"var": "nodes"}, "naming": "n{i}",
                                                    "couplings": {"pattern": "fan_out_fan_in",
                                                                  "fan_in": [{"from": "{part}.out", "to": "out"}]}}}},
                "Node": {"ports": {"out": port("out")},
                         "attributes": {"id": {"type": "int", "expr": {"replica": "index"}},
                                        "x": {"type": "int", "expr": {"call": "col", "args": [{"replica": "index"}]}}},
                         "specializations": {"kind": {"alternatives": ["Temp", "Humid"]}},
                         "aspects": {"parts": {"parts": ["Sensor", "Radio"], "couplings": [
                             {"from": "Sensor.out", "to": "Radio.in"}, {"from": "Radio.out", "to": "out"}]}}},
                "Temp": {"extends": "Node"}, "Humid": {"extends": "Node"},
                "Sensor": {"ports": {"out": port("out")}},
                "Radio": {"ports": {"in": port("in"), "out": port("out")}}}}


FIELD_FUNCTIONS = {"col": lambda i: i % 32}


def field_decisions(n: int) -> DecisionSet:
    ds = DecisionSet(variables={"nodes": (n,)}, choose=(Choice(at="Node", specialization="kind", alternative=("Temp",)),))
    for i in range(0, n, 10):                                                     # 열 번째마다 다른 종류
        ds = ds.decide(Choice(path=("Field", "Net", f"n{i}"), specialization="kind", alternative=("Temp", "Humid")))
    return ds


def test_small_fields_agree_with_the_family():
    doc = load_ses_dict(field(6))
    L = unfold_layered(doc, functions=FIELD_FUNCTIONS)
    for n in (1, 3, 6):
        ds = field_decisions(n)
        (V,) = sem(apply(L.ses, ds))
        b = direct.build(doc, ds, functions=FIELD_FUNCTIONS)
        assert facts(b.layered, b.variant) == facts(L, V) and b.variant == V


@pytest.mark.parametrize("n", [1000])
def test_a_field_of_a_thousand_nodes_is_built_planned_and_checked(n):
    """복제본 1,000개. 족으로 펼치면 개수 1부터 1,000까지의 전개가 모두 필요하다(복제본 500,500개)."""
    doc = load_ses_dict(field(n))
    started = time.perf_counter()
    b = direct.build(doc, field_decisions(n), functions=FIELD_FUNCTIONS)
    built = time.perf_counter() - started
    T = b.layered.ses.tree
    assert len(b.variant) == len(T.nodes) == 7 + 6 * n     # 노드마다 엔티티, specialization, 대안, 분해, 부분 둘. 그 밖에 일곱
    lib = {name: X.Module(name, ports, (), {"id": ("int",), "x": ("int",)} if name == "Node" else {})
           for name, ports in {"Sink": {"in": ("M", "in")}, "Sensor": {"out": ("M", "out")},
                               "Radio": {"in": ("M", "in"), "out": ("M", "out")}}.items()}
    binding = Binding("x", {k: X.Bind(k) for k in lib})
    L, ext = X.attach(b.layered, named("x"), binding, lib)
    started = time.perf_counter()
    assert X.executable(L, ext, b.variant)
    plan = X.plan(L, ext, b.variant)
    planned = time.perf_counter() - started
    assert len(X.frontier(plan)) == 1 + 2 * n
    assert len(plan["children"]["Net"]["eoc"]) == n
    values = interpret(b.layered, b.variant)["attr"]["children"]["Net"]["children"]
    assert [values[f"n{i}"]["params"] for i in (0, 31, 32, 999)] == [
        {"id": 0, "x": 0}, {"id": 31, "x": 31}, {"id": 32, "x": 0}, {"id": 999, "x": 7}]
    STATS["field_build_ms"] = int(built * 1000)
    STATS["field_plan_ms"] = int(planned * 1000)
    assert built < 30 and planned < 60, (built, planned)


def test_direct_samples_are_not_vacuous():
    if STATS["witness_built"] + STATS["witness_unmergeable"] < 1000 or STATS["plans"] < 300:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["witness_built"] >= 800 and STATS["witness_unmergeable"] >= 60, STATS
    assert STATS["witness_with_gone"] >= 25 and STATS["witness_with_pushed"] >= 30, STATS
    assert STATS["random_with_gone"] >= 15, STATS
    assert STATS["plans_executable"] >= 100, STATS
    assert STATS["random_built"] >= 500 and STATS["random_contradiction"] >= 500, STATS
    assert STATS["random_undecided"] >= 500 and STATS["random_unused"] >= 100, STATS
    assert STATS["infer_built"] >= 40 and STATS["infer_contradiction"] >= 5, STATS
    assert STATS["infer_still_undecided"] <= 5, STATS


FLAGGED = {"ses": "1.0", "name": "Sys",
           "variables": {"flag": {"type": "int", "range": [0, 1]}},
           "entities": {
               "Sys": {"root": True, "aspects": {
                   "with": {"parts": ["A", "Opt"], "rule": {"var": "flag", "eq": 1}},
                   "without": {"parts": ["A", "Opt"], "rule": {"var": "flag", "eq": 0}}}},
               "A": {},
               "Opt": {"specializations": {"presence": {
                   "alternatives": ["Absent", "Present"],
                   "select": {"when": {"var": "flag", "eq": 0}, "then": "Absent", "else": "Present"}}}},
               "Absent": {"extends": "Opt", "stereotype": "void"},
               "Present": {"extends": "Opt"}}}


def test_what_the_rules_already_fix_need_not_be_written_again():
    """대안만 고르면 선택 규칙이 변수 값을 정한다. 남은 변이는 하나다. infer 가 그것을 만든다.

    처음 온 연구자의 역할을 맡은 검증에서 나왔다. 선택지 표는 "남은 변이 1개"라고 하는데 조립은
    "변수가 정해지지 않았다"고 했다."""
    doc = load_ses_dict(FLAGGED)
    absent = DecisionSet().decide(Choice(at="Opt", specialization="presence", alternative=("Absent",)))
    with pytest.raises(Undecided, match="변수 flag"):
        direct.build(doc, absent)                                # 적힌 것만 보는 길은 그대로다
    more = direct.completed(doc, absent)
    assert more.variables == {"flag": (0,)}
    assert Choice(at="Sys", aspect=("without",)).key in {c.key for c in more.choose}
    b = direct.build(doc, absent, infer=True)
    assert b.sigma == {"flag": 0} and b.unused == ()
    assert b.variant == direct.build(doc, absent.assign("flag", 0)).variant      # 사람이 다 적은 것과 같다
    assert direct.completed(doc, DecisionSet()) is None          # 변이가 둘 남으면 채우지 않는다
    with pytest.raises(Undecided, match="변수 flag"):
        direct.build(doc, DecisionSet(), infer=True)
    clash = absent.assign("flag", 1)                             # 서로 어긋나는 결정. 남은 변이가 없다
    assert direct.completed(doc, clash) is None
    with pytest.raises(Contradiction):
        direct.build(doc, clash, infer=True)
