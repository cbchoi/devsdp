"""결정 집합을 정의 표 위에서 계산한다 (ses_core/folded.py 의 Restriction, docs/ses-platform/theory.md 7절).

펼친 나무를 가지치기한 결과(decisions.apply)와 대조한다.
1. 뜻 (정리 9): 결정을 따르는 변이가, 펼친 나무에서 그 결정이 배제한 노드를 고르지 않는 변이와 하나씩 대응한다.
2. 계산: 결정을 따르는 변이의 수와 남은 선택지를 열거하지 않고 낸 것이, 가지치기한 SES 에서 본 것과 같다.
3. 맞지 않는 결정은 두 길이 같은 글로 거부한다.
"""

import collections
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import bounded_docs  # noqa: E402
from test_decisions import rand_choice, selection_points  # noqa: E402
from test_folded import pool, sample  # noqa: E402

from ses_core import load_ses_dict  # noqa: E402
from ses_core import folded as F  # noqa: E402
from ses_core.algebra import AlgebraError, sem  # noqa: E402
from ses_core.decisions import (Choice, DecisionSet, apply, choice_table, choices_on_definitions,  # noqa: E402
                                component_path, problems)
from ses_core.extension import Layered, violations  # noqa: E402
from ses_core.unfold import unfold_annotated, variable_domains  # noqa: E402

STATS: collections.Counter = collections.Counter()


def rand_decisions(rng, T, levels=("at", "at", "path")) -> DecisionSet:
    """정의나 자리를 가리키는 결정 몇 개와 변수의 결정."""
    ds = DecisionSet()
    for _ in range(rng.randint(1, 4)):
        c = rand_choice(rng, T, rng.choice(levels))
        if c is not None:
            ds = ds.decide(c)
    for q in T.specs(T.root):
        if q[-1].startswith("$") and rng.random() < 0.5:
            values = [c[-1] for c in T.children(q)]
            ds = ds.assign(q[-1][1:], *rng.sample(values, rng.randint(1, len(values))))
    return ds


def table_of(points) -> list:
    """표의 줄들. 순서까지 견준다."""
    return [(p.owner, p.kind, p.group, tuple(p.options)) for p in points]


@pytest.mark.parametrize("seed", range(600))
def test_decided_variants_are_the_variants_of_the_pruned_tree(seed):
    """정리 9. 결정을 따르는 변이와, 가지치기한 SES 의 변이가 하나씩 대응한다. 수와 선택 지점 표도 같다."""
    d, doc, functions = sample(seed)
    rng = random.Random(seed)
    S, ann = unfold_annotated(doc, functions)
    T = S.tree
    ds = rand_decisions(rng, T)
    assert problems(S, ds) == []
    R = apply(S, ds)
    theirs = set(sem(R)) if R is not None else set()
    theirs_wf = {V for V in theirs if not violations(Layered(S, ann.void), V)}
    s = F.Semantics(doc, functions)
    rest = F.Restriction(doc, ds)
    mine = [(s.nodes(sigma, kappa), s.well_formed(kappa)) for sigma, kappa in s.variants()
            if rest.obeys(s.root, sigma, kappa)]
    assert {V for V, _ in mine} == theirs and len(mine) == len(theirs)
    assert {V for V, ok in mine if ok} == theirs_wf
    assert F.count(doc, functions, ds) == (len(theirs), len(theirs_wf))          # 열거하지 않고 센 수
    domains = variable_domains(doc)
    assert table_of(choices_on_definitions(doc, ds, functions)) == table_of(choice_table(S, R, domains))
    everything = sum(1 for _ in s.variants())
    STATS["docs"] += 1
    STATS["nothing_to_decide" if not everything else "emptied" if not theirs
          else "partial" if len(theirs) < everything else "no_effect"] += 1
    STATS["variants"] += len(theirs)
    STATS["ill"] += len(theirs) - len(theirs_wf)
    for c in ds.choose:
        STATS[c.key[0]] += 1
        STATS[c.kind] += 1
    STATS["variables"] += bool(ds.variables)


def spoil(rng, T, ds: DecisionSet) -> DecisionSet:
    """결정 하나를 문서에 맞지 않게 바꾼다."""
    kind = rng.randrange(6)
    points = selection_points(T)
    y, what, group, options = rng.choice(points)
    label = T.label(y)
    if kind == 0:
        return ds.decide(Choice(at="Nowhere", aspect=("a",)))                          # 없는 정의
    if kind == 1:
        return ds.decide(Choice(path=(T.label(T.root), "nowhere"), aspect=("a",)))     # 없는 자리
    if kind == 2:
        return ds.decide(Choice(at=label, specialization="zz", alternative=("A",)))    # 없는 선택 지점
    if kind == 3:
        return ds.assign("no_such_variable", 1)
    if what == "specialization":                                                       # 없는 선택지
        return ds.decide(Choice(at=label, specialization=group, alternative=(options[0], "Nope")))
    if what == "multi_aspect":
        return ds.decide(Choice(at=label, multi_aspect=group, count=(options[0], 99)))
    return ds.decide(Choice(at=label, aspect=(options[0], "nope")))


@pytest.mark.parametrize("seed", range(200))
def test_decisions_that_do_not_fit_are_refused_alike(seed):
    """낡은 결정(가리키는 곳, 선택 지점, 남길 선택지가 문서에 없다)은 두 길이 같은 글로 거부한다."""
    d, doc, functions = sample(seed)
    rng = random.Random(seed)
    S, _ = unfold_annotated(doc, functions)
    if not selection_points(S.tree):
        return
    ds = spoil(rng, S.tree, rand_decisions(rng, S.tree))
    theirs = None
    try:
        apply(S, ds)
    except AlgebraError as e:
        theirs = str(e)
    mine = None
    try:
        F.Restriction(doc, ds)
    except AlgebraError as e:
        mine = str(e)
    assert theirs is not None and mine == theirs
    STATS["refused"] += 1


def single_decisions(T) -> list:
    """나무가 내는 선택 지점마다, 정의로도 자리로도 가리킨, 선택지 하나나 둘을 남기는 결정 전부."""
    out = []
    seen = set()
    for y, kind, group, options in selection_points(T):
        keeps = [(o,) for o in options] + ([tuple(options[:2]), tuple(options[-2:])] if len(options) > 2 else [])
        for where in (dict(at=T.label(y)), dict(path=component_path(T, y))):
            for keep in dict.fromkeys(keeps):
                what = {"specialization": dict(specialization=group, alternative=keep),
                        "multi_aspect": dict(multi_aspect=group, count=keep),
                        "aspect": dict(aspect=keep)}[kind]
                c = Choice(**where, **what)
                if (c.key, keep) not in seen:
                    seen.add((c.key, keep))
                    out.append(c)
    return out


@pytest.mark.parametrize("family", list(bounded_docs.FAMILIES))
def test_every_single_decision_of_small_documents(family):
    """작은 문서의 전수 검사(bounded_docs.py)의 97번째 문서마다, 그 문서가 내는 결정 하나하나를 견준다.

    결정마다 남은 변이의 수, 핵 적격인 수, 선택 지점 표가 가지치기한 SES 에서 본 것과 같다.
    """
    for i, d in enumerate(bounded_docs.FAMILIES[family]()):
        if i % 97:
            continue
        doc = load_ses_dict(d)
        S, ann = unfold_annotated(doc)
        T = S.tree
        core = Layered(S, ann.void)
        domains = variable_domains(doc)
        everything = F.count(doc)[0]
        STATS["small_docs"] += 1
        for c in single_decisions(T):
            ds = DecisionSet().decide(c)
            R = apply(S, ds)
            theirs = sem(R) if R is not None else []
            wf = sum(1 for V in theirs if not violations(core, V))
            where = f"{family}/{i} {c.to_dict()}"
            assert F.count(doc, None, ds) == (len(theirs), wf), where
            assert table_of(choices_on_definitions(doc, ds)) == table_of(choice_table(S, R, domains)), where
            STATS["small_decisions"] += 1
            STATS["small_emptied"] += bool(everything) and not theirs
            STATS["small_must_give"] += c.kind == "aspect" and 0 < len(theirs) < everything


def merged(base: dict, alt: dict) -> dict:
    """뿌리 R 에 대안 E 가 합쳐진다. 둘 다 분해를 가질 수 있다."""
    return {"ses": "1.0", "name": "R",
            "entities": {"R": {"root": True, "aspects": base, "specializations": {"s": {"alternatives": ["D", "E"]}}},
                         "D": {"extends": "R"}, "E": {"extends": "R", "aspects": alt}, "P": {}, "Q": {}}}


def test_a_decision_on_a_decomposition_requires_that_member_to_give_it():
    """분해의 결정은 그 구성원이 그 분해를 내는 변이만 남긴다. 밀리거나 정할 수 없는 변이는 남지 않는다."""
    doc = load_ses_dict(merged({"a": {"parts": ["P"], "priority": 5}},
                               {"b": {"parts": ["Q"], "priority": 5}, "c": {"parts": ["Q"], "priority": 9}}))
    assert F.count(doc) == (3, 2)                            # D: a.  E: a 가 c 를 누르거나, a 와 b 가 맞선다
    keep_a = DecisionSet().decide(Choice(at="R", aspect=("a",)))
    assert F.count(doc, None, keep_a) == (2, 2)              # 맞서서 정할 수 없는 변이가 빠진다
    keep_b = DecisionSet().decide(Choice(at="E", aspect=("b",)))
    assert F.count(doc, None, keep_b) == (1, 1)              # E 가 없는 변이(D)만 남는다. E 는 b 를 낼 수 없다
    keep_c = DecisionSet().decide(Choice(at="E", aspect=("c",)))
    assert F.count(doc, None, keep_c) == (1, 1)
    here = DecisionSet().decide(Choice(path=("R",), aspect=("a",)))      # 그 자리의 구성원 전부를 가리킨다
    assert F.count(doc, None, here) == (2, 2)                # R 은 a 를 내야 하고 E 는 분해를 내지 않아야 한다
    both = keep_a.decide(Choice(at="R", specialization="s", alternative=("E",)))
    fam = F.analyze(doc, None, both)
    assert (fam.variants, fam.wellformed) == (1, 1)
    assert ("spec", "R", "s", "E") in fam.live and ("spec", "R", "s", "D") not in fam.live
    assert ("pushed", "E") in fam.live


def test_decisions_are_counted_without_enumeration():
    """복제본이 1,000개까지인 풀. 결정을 따르는 변이의 수가 닫힌 식과 같다. 변이를 열거했다면 끝나지 않는다."""
    doc = load_ses_dict(pool(1000, 3))
    two = DecisionSet().decide(Choice(at="Leaf", specialization="k", alternative=("K0", "K1")))
    assert F.count(doc, None, two)[0] == sum(2 ** n for n in range(1, 1001))
    few = two.decide(Choice(at="R", multi_aspect="m", count=(10, 20)))
    assert F.count(doc, None, few) == (2 ** 10 + 2 ** 20,) * 2
    first = few.decide(Choice(path=("R", "Leaf_0"), specialization="k", alternative=("K2",)))
    assert F.count(doc, None, first) == (0, 0)               # 두 결정이 맞선다. 첫 복제본에 남는 대안이 없다
    first = DecisionSet().decide(Choice(at="R", multi_aspect="m", count=(10,))) \
        .decide(Choice(path=("R", "Leaf_0"), specialization="k", alternative=("K2",)))
    assert F.count(doc, None, first) == (3 ** 9,) * 2
    table = {row[:3]: dict(row[3]) for row in table_of(choices_on_definitions(doc, first))}
    assert table[("Leaf", "alternative", "k")] == {"K0": True, "K1": True, "K2": True}
    assert [n for n, alive in table[("R", "count", "m")].items() if alive] == [10]


def test_the_choice_table_has_no_rows_for_definitions_that_are_never_placed():
    """개수가 늘 0 인 multi-aspect 의 부분은 어디에도 놓이지 않는다. 그 선택 지점은 표에 없다. 펼친 표와 같다."""
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": 0}},
                            "specializations": {"s": {"alternatives": ["A", "B"]}}},
                      "A": {"extends": "R"}, "B": {"extends": "R"},
                      "P": {"specializations": {"k": {"alternatives": ["P1", "P2"]}}},
                      "P1": {"extends": "P"}, "P2": {"extends": "P"}}}
    doc = load_ses_dict(d)
    S, _ = unfold_annotated(doc)
    mine = table_of(choices_on_definitions(doc))
    assert mine == table_of(choice_table(S, apply(S, DecisionSet()), variable_domains(doc)))
    assert [row[:3] for row in mine] == [("R", "alternative", "s")]
    with pytest.raises(AlgebraError, match="가리키는 곳이 대상에 없다"):
        F.count(doc, None, DecisionSet().decide(Choice(at="P", specialization="k", alternative=("P1",))))


def test_a_node_decision_is_not_computed_on_the_definitions():
    """펼친 나무의 노드를 가리킨 결정은 그 표현에 딸린 것이다. 정의 표 위에서는 거부한다."""
    doc = load_ses_dict(pool(2, 2))
    ds = DecisionSet().decide(Choice(node=("R",), multi_aspect="m", count=(1,)))
    with pytest.raises(AlgebraError, match="node"):
        F.count(doc, None, ds)
    assert F.count(doc, None, DecisionSet()) == F.count(doc)


def test_decision_samples_are_not_vacuous():
    if not STATS["docs"]:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["docs"] == 600 and STATS["partial"] >= 200 and STATS["emptied"] >= 80 and STATS["no_effect"] >= 50, STATS
    assert STATS["variants"] >= 1000 and STATS["ill"] >= 50, STATS
    assert STATS["at"] >= 400 and STATS["path"] >= 200, STATS
    assert STATS["specialization"] >= 200 and STATS["aspect"] >= 100 and STATS["multi_aspect"] >= 50, STATS
    assert STATS["variables"] >= 100 and STATS["refused"] >= 150, STATS
    if STATS["small_docs"]:                                  # 작은 문서의 시험도 함께 돌았을 때
        assert STATS["small_docs"] >= 700 and STATS["small_decisions"] >= 8000 and STATS["small_emptied"] >= 500, STATS
        assert STATS["small_must_give"] >= 300, STATS
