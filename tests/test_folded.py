"""접힌 형태 위의 의미 (ses_core/folded.py, docs/ses-platform/theory.md).

세 가지를 무작위 문서에서 본다.
1. 표현 (정리 5): 정의 표 위에서 직접 정한 변이와, 펼친 나무의 선택 대수가 내는 변이가 하나씩 대응한다.
2. 계산 (정리 3): 변이를 열거하지 않고 정의 표 위에서 센 수가, 열거해서 센 수와 같다.
3. 고전 절차: 적격 변이의 구조가 문헌의 절차를 따라 적은 것(classic.py)과 같다.
"""

import collections
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_parity import decorated, prioritized, with_paths  # noqa: E402

from ses_core import classic, load_ses_dict  # noqa: E402
from ses_core import folded as F  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.extension import Layered, violations  # noqa: E402
from ses_core.unfold import unfold_annotated  # noqa: E402

STATS: collections.Counter = collections.Counter()


def sample(seed: int) -> tuple:
    """(문서, 적재한 문서, 함수들). 우선순위와 규칙, 선택 제약, 경로로 가리킨 제약이 섞인다."""
    kind = seed % 3
    if kind == 0:
        d, doc, functions = prioritized(seed)
    else:
        d, doc, functions = decorated(seed)
        if kind == 2:
            d = with_paths(random.Random(seed), d, doc, functions)
            doc = load_ses_dict(d)
    return d, doc, functions


def unfolded(doc, functions) -> tuple:
    """(펼친 나무의 변이들, 그 가운데 핵 적격인 것들)."""
    S, ann = unfold_annotated(doc, functions)
    core = Layered(S, ann.void)
    variants = sem(S)
    return set(variants), {V for V in variants if not violations(core, V)}, len(variants)


@pytest.mark.parametrize("seed", range(600))
def test_variants_are_the_variants_of_the_unfolded_tree(seed):
    """정리 5. 접힌 형태의 변이와 펼친 나무의 변이가 하나씩 대응하고, 핵 적격인 것끼리 대응한다."""
    d, doc, functions = sample(seed)
    s = F.Semantics(doc, functions)
    mine = [(s.nodes(sigma, kappa), s.well_formed(kappa)) for sigma, kappa in s.variants()]
    theirs, theirs_wf, n = unfolded(doc, functions)
    assert len({V for V, _ in mine}) == len(mine)            # 서로 다른 변이는 서로 다른 노드 집합이다
    assert {V for V, ok in mine if ok} == theirs_wf
    assert {V for V, _ in mine} == theirs
    STATS["variants"] += len(mine)
    STATS["ill"] += sum(not ok for _, ok in mine)
    STATS["docs_with_ill"] += any(not ok for _, ok in mine)
    STATS["docs_empty"] += not mine
    STATS["docs_with_hidden_ties"] += any(
        amb and dec for sigma in s.assignments() for name in doc.entities
        for mu in s.members(name, sigma) if not s.removed(mu) and s.owners(mu)
        for dec, amb in [s.outcomes(s.owners(mu), sigma)])


@pytest.mark.parametrize("seed", range(600))
def test_counting_on_the_definitions_equals_enumeration(seed):
    """정리 3. 정의 표 위에서 센 변이 수와 적격 변이 수가 열거한 것과 같다. 변수 값마다 본다."""
    d, doc, functions = sample(seed)
    s = F.Semantics(doc, functions)
    listed: dict = {}
    for sigma, kappa in s.variants():
        key = tuple(sorted(sigma.items()))
        total, wf = listed.get(key, (0, 0))
        listed[key] = (total + 1, wf + s.well_formed(kappa))
    counted = {tuple(sorted(sigma.items())): (total, wf)
               for sigma, total, wf in F.Evaluator(doc, functions).per_assignment() if total}
    assert counted == listed
    assert F.count(doc, functions) == (sum(t for t, _ in listed.values()), sum(w for _, w in listed.values()))
    STATS["counted"] += sum(t for t, _ in listed.values())
    STATS["docs_with_selected"] += any(F.selected_atoms(x) for c in doc.constraints for x in (c.when, c.require, c.forbid))
    STATS["docs_with_paths"] += any(a.path is not None for c in doc.constraints
                                    for x in (c.when, c.require, c.forbid) for a in F.selected_atoms(x))


def stripped(d: dict) -> dict:
    """포트와 결합을 뗀 문서. 고전 절차는 포트를 합칠 수 없는 구조를 내놓지 않으므로 구조만 견준다."""
    d = json.loads(json.dumps(d))
    d.pop("port_types", None)
    for body in d["entities"].values():
        body.pop("ports", None)
        for a in list((body.get("aspects") or {}).values()) + list((body.get("multi_aspects") or {}).values()):
            a.pop("couplings", None)
    return d


def classic_shape(n: dict):
    return tuple(n["labels"]), tuple((name, classic_shape(c)) for name, c in n["children"].items())


@pytest.mark.parametrize("seed", range(300))
def test_well_formed_variants_are_the_models_of_the_classic_procedure(seed):
    """적격 변이의 (변수 값, 구조)가 고전 절차가 내는 것과 같다. 여러 변이가 같은 구조를 낼 수 있다."""
    d, _, functions = prioritized(seed) if seed % 2 == 0 else decorated(seed)    # 고전 절차는 경로로 가리킨 제약을 읽지 않는다
    doc = load_ses_dict(stripped(d))
    s = F.Semantics(doc, functions)
    mine = collections.Counter((tuple(sorted(sigma.items())), s.shape(kappa))
                               for sigma, kappa in s.variants() if s.well_formed(kappa))
    theirs = collections.Counter((tuple(sorted(sigma.items())), classic_shape(n))
                                 for sigma, n in classic.enumerate_classic(doc, functions))
    assert mine == theirs
    STATS["models"] += sum(mine.values())


# ---------------------------------------------------------------------------
# 손으로 만든 예
# ---------------------------------------------------------------------------

def merged(base: dict, alt: dict, variables=None) -> dict:
    """뿌리 R 과 그 대안 E 가 저마다 분해를 가진다. 대안 D 는 분해가 없다. 분해의 부분은 이름이 같은 잎이다."""
    def aspects(spec: dict) -> dict:
        return {name: dict({"parts": [name.upper()]}, **body) for name, body in spec.items()}
    leaves = {name.upper(): {} for name in list(base) + list(alt)}
    d = {"ses": "1.0", "name": "R",
         "entities": dict({"R": {"root": True, "aspects": aspects(base),
                                 "specializations": {"s": {"alternatives": ["D", "E"]}}},
                           "D": {"extends": "R"}, "E": {"extends": "R", "aspects": aspects(alt)}}, **leaves)}
    if variables:
        d["variables"] = variables
    return d


def states(d: dict) -> list:
    """병합체 {R, E} 가 가질 수 있는 상태들: 고른 분해의 이름이거나 stuck."""
    s = F.Semantics(load_ses_dict(d))
    return sorted(k.dec if k.state == F.SPLIT else k.state
                  for _, k in s.variants() if "E" in k.member.names())


def test_the_decomposition_of_a_cluster_is_the_strict_first_of_what_its_members_demand():
    """정의 3. 구성원마다 분해 하나를 내고, 우선순위가 홀로 가장 앞선 것이 그 병합체의 분해다."""
    assert states(merged({"a": {"priority": 1}}, {"b": {"priority": 2}})) == ["a"]
    assert states(merged({"a": {"priority": 2}}, {"b": {"priority": 1}})) == ["b"]
    assert states(merged({"a": {}}, {"b": {"priority": 7}})) == ["b"]                    # 없는 것은 가장 뒤다
    assert states(merged({"a": {}}, {"b": {}})) == ["stuck"]                             # 가를 수 없다
    assert states(merged({"a": {"priority": 3}}, {"b": {"priority": 3}})) == ["stuck"]
    # 바탕이 a 와 c 가운데 하나를 고른다. a 를 내면 a 가, c 를 내면 b 가 그 병합체의 분해다
    assert states(merged({"a": {"priority": 1}, "c": {"priority": 5}}, {"b": {"priority": 3}})) == ["a", "b"]


def test_a_tie_is_not_hidden_by_another_choice():
    """a 와 b 의 우선순위가 같으면 그 둘을 낸 조합은 정할 수 없다. 대안이 b 대신 낼 수 있는 c 가 있어도 그렇다.

    c 를 내면 a 가 이기므로 a 는 그 병합체의 분해가 될 수 있다. 그러나 b 를 낸 조합이 남아 있으므로 족은 적격이 아니다.
    """
    d = merged({"a": {"priority": 5}}, {"b": {"priority": 5}, "c": {"priority": 9}})
    assert states(d) == ["a", "stuck"]
    s = F.Semantics(load_ses_dict(d))
    assert s.outcomes(["R", "E"], {}) == ([("R", load_ses_dict(d).entities["R"].aspects["a"])], True)
    assert F.count(load_ses_dict(d)) == (3, 2)                                           # D 하나, E 에서 a 와 stuck
    theirs, theirs_wf, n = unfolded(load_ses_dict(d), None)
    assert (n, len(theirs_wf)) == (3, 2)


def test_rules_that_demand_two_decompositions_leave_an_ill_formed_variant():
    """두 규칙이 함께 참이고 우선순위로 가를 수 없으면 그 변수 값은 사라지지 않고 부적격 변이로 남는다."""
    v = {"v": {"type": "int", "range": [1, 3]}}
    d = merged({"a": {"rule": {"var": "v", "le": 2}}, "c": {"rule": {"var": "v", "ge": 2}}}, {}, v)
    d["entities"]["R"].pop("specializations")
    for name in ("D", "E"):
        d["entities"].pop(name)
    s = F.Semantics(load_ses_dict(d))
    got = {sigma["v"]: (k.dec if k.state == F.SPLIT else k.state) for sigma, k in s.variants()}
    assert got == {1: "a", 2: "stuck", 3: "c"}
    d["entities"]["R"]["aspects"]["c"]["priority"] = 1                                   # 우선순위가 가르면 정해진다
    s = F.Semantics(load_ses_dict(d))
    assert {sigma["v"]: k.dec for sigma, k in s.variants()} == {1: "a", 2: "c", 3: "c"}


def test_a_member_whose_rules_tie_can_still_lose_to_another_member():
    """바탕의 두 규칙이 다투어도, 대안의 분해가 그 둘보다 앞서면 대안의 분해로 정해진다."""
    base = {"a": {"rule": {"all": []}, "priority": 5}, "c": {"rule": {"all": []}, "priority": 5}}
    assert states(merged(base, {"b": {"priority": 1}})) == ["b"]
    assert states(merged(base, {"b": {"priority": 9}})) == ["stuck"]


def pool(top: int, kinds: int, depth: int = 1) -> dict:
    """복제본이 1개에서 top 개인 풀. 복제본마다 kinds 가지 가운데 하나다. depth 겹으로 쌓는다."""
    ents = {"Leaf": {"specializations": {"k": {"alternatives": [f"K{i}" for i in range(kinds)]}}}}
    ents.update({f"K{i}": {"extends": "Leaf"} for i in range(kinds)})
    below = "Leaf"
    for level in range(depth):
        name = "R" if level == depth - 1 else f"P{level}"
        ents[name] = {"multi_aspects": {"m": {"part": below, "cardinality": {"min": 1, "max": top}}}}
        below = name
    ents["R"]["root"] = True
    return {"ses": "1.0", "name": "R", "entities": ents}


def test_counting_does_not_depend_on_the_number_of_variants():
    """정리 3. 복제본이 천 개까지인 풀의 변이 수를 열거 없이 센다. 답은 닫힌 식과 같다."""
    assert F.count(load_ses_dict(pool(6, 2))) == (sum(2 ** n for n in range(1, 7)),) * 2
    big = F.count(load_ses_dict(pool(1000, 3)))
    assert big[0] == big[1] == sum(3 ** n for n in range(1, 1001)) and len(str(big[0])) == 478
    inner = sum(2 ** n for n in range(1, 31))                                            # 두 겹
    assert F.count(load_ses_dict(pool(30, 2, depth=2)))[0] == sum(inner ** n for n in range(1, 31))


def test_a_constraint_on_one_replica_is_counted_at_that_replica_only():
    """경로로 가리킨 제약은 그 자리의 복제본만 따로 세고, 나머지 복제본은 한 번 센 값을 거듭제곱한다."""
    d = pool(40, 3)
    d["constraints"] = [{"name": "first", "require": {"selected": {"path": ["R", "Leaf_0"], "specialization": "k",
                                                                    "alternative": "K0"}}},
                        {"name": "any", "forbid": {"selected": "Leaf/k=K2"}}]
    # 첫 복제본은 K0, 나머지는 K2 가 아닌 둘 가운데 하나
    assert F.count(load_ses_dict(d))[0] == sum(2 ** (n - 1) for n in range(1, 41))


def test_folded_samples_are_not_vacuous():
    if not STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["variants"] >= 3000 and STATS["ill"] >= 150 and STATS["docs_with_ill"] >= 60, STATS
    assert STATS["counted"] >= 3000 and STATS["docs_with_selected"] >= 200 and STATS["docs_with_paths"] >= 60, STATS
    assert STATS["models"] >= 1500 and STATS["docs_with_hidden_ties"] >= 5, STATS
