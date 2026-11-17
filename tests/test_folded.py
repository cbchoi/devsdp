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
from ses_core.algebra import AlgebraError, sem  # noqa: E402
from ses_core.decisions import family  # noqa: E402
from ses_core.extension import Layered, violations  # noqa: E402
from ses_core.skeleton import component_path, skeleton  # noqa: E402
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


def skeleton_shape(T, c):
    """뼈대(skeleton.py)를 Semantics.shape 와 같은 꼴로. 빠진 부분은 이름만 남는다."""
    chosen = (T.label(c.aspect[:-1]), family(c.aspect[-1])) if c.aspect is not None else None
    names = [q[-1] for q in T.children(c.aspect)] if c.aspect is not None else []
    assert sorted(names) == sorted(list(c.parts) + list(c.absent))
    return tuple(sorted(c.labels)), chosen, \
        tuple((name, skeleton_shape(T, c.parts[name]) if name in c.parts else None) for name in names)


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
    S, ann = unfold_annotated(doc, functions)                # 따름정리 5.1: 뼈대가 정의 표 위의 구조와 같다
    for sigma, kappa in s.variants():
        sk = skeleton(S.tree, ann.void, s.nodes(sigma, kappa))
        assert (sk is None) == (kappa.state == F.GONE)
        if sk is not None:
            assert skeleton_shape(S.tree, sk) == s.shape(kappa)
            assert {q for q, c in kappa.walk((s.root,)) if c.state == F.STUCK} == \
                {component_path(S.tree, c.path) for c in walk_skeleton(sk) if c.stuck}
    STATS["variants"] += len(mine)
    STATS["ill"] += sum(not ok for _, ok in mine)
    STATS["docs_with_ill"] += any(not ok for _, ok in mine)
    STATS["docs_empty"] += not mine
    hidden = False
    for sigma in s.assignments():                            # 정리 2: 닫힌 꼴이 정의 3을 그대로 계산한 것과 같다
        for name in doc.entities:
            for mu in s.members(name, sigma):
                if not s.removed(mu) and s.owners(mu):
                    dec, amb = s.outcomes(s.owners(mu), sigma)
                    assert s.outcomes_closed(s.owners(mu), sigma) == (dec, amb)
                    hidden = hidden or (amb and bool(dec))
                    STATS["clusters"] += 1
    STATS["docs_with_hidden_ties"] += hidden


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


@pytest.mark.parametrize("seed", range(400))
def test_family_analysis_sees_what_enumeration_sees(seed):
    """정의 표 위의 분석이 낸 것(변이 수, 살아 있는 선택지, 분해를 정할 수 없는 곳, 변이가 있는 변수 값)이
    변이를 모두 열거해서 본 것과 같다."""
    d, doc, functions = sample(seed)
    s = F.Semantics(doc, functions)
    some, good = set(), set()
    values = {name: (set(), set()) for name in doc.variables}
    n = wf = 0
    for sigma, kappa in s.variants():
        events = {(k, y, g, c) for _, k, y, g, c in s.choices(kappa)}
        events |= {("stuck", c.member.name, tuple(sorted(s.owners(c.member))))
                   for _, c in kappa.walk((s.root,)) if c.state == F.STUCK}
        events |= {("pushed", z) for _, c in kappa.walk((s.root,)) if c.state == F.SPLIT
                   for z in s.owners(c.member) if z != c.owner}
        if kappa.state == F.GONE:
            events.add(F.ROOT_GONE)
        ok = s.well_formed(kappa)
        n, wf = n + 1, wf + ok
        some |= events
        for name, v in sigma.items():
            values[name][0].add(v)
            if ok:
                values[name][1].add(v)
        if ok:
            good |= events
    fam = F.analyze(doc, functions)
    assert (fam.variants, fam.wellformed) == (n, wf)
    assert fam.live == some and fam.live_wf == good and fam.values == values
    assert set(fam.examples) == {e for e in some if e == F.ROOT_GONE or e[0] == "stuck"}
    dead = fam.dead(doc)
    assert all((c[:4] in some) == c[4] for c in dead if c[0] != "variable")
    STATS["dead"] += len(dead)
    STATS["dead_but_in_some_variant"] += sum(c[4] for c in dead)
    STATS["docs_with_dead"] += bool(dead)
    STATS["stuck_places"] += sum(e[0] == "stuck" for e in fam.examples)
    STATS["root_gone_docs"] += F.ROOT_GONE in fam.examples


def spoiled(seed: int) -> tuple:
    """무작위 문서에 뜻을 정할 수 없는 것을 하나 넣는다. (문서, 함수들, 넣었는가)"""
    d, _, functions = decorated(seed)
    d = json.loads(json.dumps(d))
    root = d["name"]
    kind = seed % 5
    extra = None
    if kind == 0:                                            # 어떤 선택에도 없는 자리
        extra = {"name": "z", "forbid": {"selected": {"path": [root, "nowhere"], "aspect": "a0"}}}
    elif kind == 1:                                          # 있는 자리이지만 그 구성요소에 없는 선택 지점
        extra = {"name": "z", "forbid": {"selected": {"path": [root], "specialization": "zz", "alternative": "E9"}}}
    elif kind == 2:                                          # 뿌리에서 닿지 않는 정의
        d["entities"]["Lonely"] = {"specializations": {"u": {"alternatives": ["LonelyA"]}}}
        d["entities"]["LonelyA"] = {"extends": "Lonely"}
        extra = {"name": "z", "forbid": {"selected": "Lonely/u=LonelyA"}}
    elif kind == 3:                                          # 앞의 항이 참이라 평가가 닿지 않는, 견줄 수 없는 조건
        d.setdefault("variables", {}).setdefault("vz", {"type": "int", "range": [1, 2]})
        extra = {"name": "z", "require": {"any": [{"all": []}, {"var": "vz", "lt": "x"}]}}
    if extra is not None:
        d["constraints"] = list(d.get("constraints") or []) + [extra]
    return d, functions, extra is not None


@pytest.mark.parametrize("seed", range(150))
def test_documents_without_a_meaning_are_refused_by_both(seed):
    """가리키는 곳이 없는 selected 와 값이 없는 조건을 가진 문서는 정의 표 위의 의미도 펼침도 거부한다.
    한쪽만 답하는 문서가 없어야 두 길의 수가 어긋나지 않는다."""
    d, functions, bad = spoiled(seed)
    doc = load_ses_dict(d)
    outcomes = []
    for build in (lambda: F.Semantics(doc, functions), lambda: unfold_annotated(doc, functions)):
        try:
            build()
            outcomes.append("ok")
        except AlgebraError:
            outcomes.append("refused")
    assert outcomes == (["refused", "refused"] if bad else ["ok", "ok"])
    STATS["refused"] += bad


def walk_skeleton(c):
    yield c
    for k in c.parts.values():
        yield from walk_skeleton(k)


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
    mine = collections.Counter((tuple(sorted(sigma.items())), F.live_shape(s.shape(kappa)))
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


def test_a_removed_root_is_an_ill_formed_variant():
    """뿌리가 없음 대안을 고른 것은 변이이되 핵 적격이 아니다 (K0). 세 길이 같은 답을 낸다."""
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "specializations": {"s": {"alternatives": ["A", "Gone"]}},
                            "aspects": {"d": {"parts": ["P"]}}},
                      "A": {"extends": "R"}, "Gone": {"extends": "R", "stereotype": "void"}, "P": {}}}
    doc = load_ses_dict(d)
    s = F.Semantics(doc)
    assert sorted((k.state, s.well_formed(k)) for _, k in s.variants()) == [("gone", False), ("split", True)]
    assert F.count(doc) == (2, 1)
    fam = F.analyze(doc)
    gone = ("spec", "R", "s", "Gone")
    assert F.ROOT_GONE in fam.examples and gone in fam.live and gone not in fam.live_wf
    assert ("spec", "R", "s", "A") in fam.live_wf
    theirs, theirs_wf, n = unfolded(doc, None)
    assert (n, len(theirs_wf)) == (2, 1)
    assert {s.nodes(sigma, k) for sigma, k in s.variants() if s.well_formed(k)} == theirs_wf


def refusals(d: dict) -> list:
    """정의 표 위의 의미와 펼침이 그 문서를 받는가. 거부하면 그 글의 앞머리."""
    doc = load_ses_dict(d)
    out = []
    for build in (lambda: F.Semantics(doc), lambda: unfold_annotated(doc)):
        try:
            build()
            out.append("ok")
        except AlgebraError as e:
            out.append(str(e).split(":")[0])
    return out


def test_a_selected_must_point_at_a_definition_that_is_placed_somewhere():
    """정의 수준의 selected 가 가리키는 정의는 어떤 선택에든 놓일 수 있어야 한다 (W7).

    개수가 늘 0 인 multi-aspect 의 부분은 쓰이기는 하나 어디에도 놓이지 않는다. 전에는 정의 표 위의 의미가
    그런 문서에 답을 내고 펼침은 거부했다. 변수의 값이 그 정의의 이름과 같은 글이면 펼침이 값의 노드를
    그 정의가 놓인 곳으로 읽어 거부하지 않던 것도 같이 본다.
    """
    def doc(card, variables=None):
        d = {"ses": "1.0", "name": "R",
             "entities": {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": card}}},
                          "P": {"specializations": {"k": {"alternatives": ["A", "B"]}}},
                          "A": {"extends": "P"}, "B": {"extends": "P"}},
             "constraints": [{"name": "c", "forbid": {"selected": "P/k=A"}}]}
        if variables:
            d["variables"] = variables
        return d
    nowhere = "selected 가 가리키는 곳이 없다"
    assert refusals(doc(0)) == [nowhere, nowhere]
    assert refusals(doc({"min": 0, "max": 0})) == [nowhere, nowhere]
    assert refusals(doc(0, {"v": {"type": "enum", "values": ["P", "Q"]}})) == [nowhere, nowhere]
    assert refusals(doc({"min": 0, "max": 1})) == ["ok", "ok"]
    assert refusals(doc({"var": "n"}, {"n": {"type": "int", "values": [0]}})) == [nowhere, nowhere]
    assert refusals(doc({"var": "n"}, {"n": {"type": "int", "values": [0, 2]}})) == ["ok", "ok"]
    ok = load_ses_dict(doc({"min": 0, "max": 1}))
    assert F.count(ok) == (2, 2) and unfolded(ok, None)[2] == 2          # 개수 0, 그리고 개수 1 에서 B
    assert "P" in F.reachable(load_ses_dict(doc(0))) and "P" not in F.occurring(load_ses_dict(doc(0)))


def test_definitions_that_are_never_placed_do_not_matter_and_open_counts_are_refused_at_once():
    """놓이지 않는 정의의 조건은 보지 않는다. 위가 열린 개수는 그 분해가 쓰이지 않아도 거부한다. 펼침과 같다.

    전에는 정의 표 위의 계산이 닿는 정의 전부의 조건을 미리 보아, 놓이지 않는 정의의 조건 때문에 거부했다.
    위가 열린 개수는 그 분해에 닿을 때만 거부해서, 선택 규칙이 그 대안을 고르지 않으면 답을 냈다.
    """
    never = {"ses": "1.0", "name": "R", "variables": {"v": {"type": "int", "range": [1, 2]}},
             "entities": {"R": {"root": True, "specializations": {"s": {"alternatives": ["D", "E"]}},
                                "multi_aspects": {"m": {"part": "Q", "cardinality": 0}}},
                          "D": {"extends": "R"}, "E": {"extends": "R"},
                          "Q": {"aspects": {"a": {"parts": ["L"], "rule": {"call": "f", "args": [{"var": "v"}], "eq": 1}}}},
                          "L": {}}}
    assert refusals(never) == ["ok", "ok"]
    doc = load_ses_dict(never)
    assert F.count(doc) == (4, 4) and unfolded(doc, None)[2] == 4
    placed = json.loads(json.dumps(never))
    placed["entities"]["R"]["multi_aspects"]["m"]["cardinality"] = 1          # 이제 Q 가 놓인다
    assert refusals(placed) == ["등록되지 않은 함수 f", "등록되지 않은 함수 f"]
    open_count = {"ses": "1.0", "name": "R",
                  "entities": {"R": {"root": True, "specializations": {"s": {
                      "alternatives": ["D", "E"], "select": {"when": {"all": []}, "then": "D"}}}},
                      "D": {"extends": "R"},
                      "E": {"extends": "R", "multi_aspects": {"m": {"part": "L", "cardinality": {"min": 1}}}},
                      "L": {}}}
    assert refusals(open_count) == ["multi-aspect m 의 개수에 상한이 필요하다"] * 2


def test_the_structure_keeps_the_names_of_removed_parts():
    """정의 8. 구조는 빠진 부분의 이름을 남긴다. 결합이 그것을 보기 때문이다.

    개수 1 과, 개수 2 에서 둘째 복제본이 빠진 것은 살아 있는 부분이 같다. 그러나 "마지막 복제본"이 다르므로
    결합이 다르고, 구조도 달라야 한다. 문헌의 절차와 견줄 때 쓰는 꼴(live_shape)에서는 둘이 같다.
    """
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": {"min": 1, "max": 2}}}},
                      "P": {"specializations": {"k": {"alternatives": ["On", "Off"]}}},
                      "On": {"extends": "P"}, "Off": {"extends": "P", "stereotype": "void"}}}
    doc = load_ses_dict(d)
    s = F.Semantics(doc)
    shapes = {}
    for _, kappa in s.variants():
        states_of = tuple(c.state for _, c in kappa.parts)
        shapes[states_of] = s.shape(kappa)
    one, two = shapes[("atom",)], shapes[("atom", "gone")]
    assert one == (("R",), ("R", "m"), (("P_0", (("On", "P"), None, ())),))
    assert two == (("R",), ("R", "m"), (("P_0", (("On", "P"), None, ())), ("P_1", None)))
    assert one != two and F.live_shape(one) == F.live_shape(two)
    assert len(set(shapes.values())) == 6 and len({F.live_shape(x) for x in shapes.values()}) == 4
    S, ann = unfold_annotated(doc)                           # 뼈대도 같은 것을 적는다
    for sigma, kappa in s.variants():
        assert skeleton_shape(S.tree, skeleton(S.tree, ann.void, s.nodes(sigma, kappa))) == s.shape(kappa)


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


def test_the_calculation_does_not_enumerate_clusters_demands_paths_or_replicas():
    """정리 4. 독립된 검토가 짚은 네 모양이다. 고치기 전에는 크기가 하나 늘 때마다 시간이 두 배가 되었다."""
    import time

    def timed(d: dict, limit: float = 5.0) -> tuple:
        doc = load_ses_dict(d)
        started = time.time()
        out = F.count(doc)
        assert time.time() - started < limit
        return out

    # 1. 대안이 마름모로 겹치는 병합체. 병합체 선택이 2의 k 제곱 개다
    k = 40
    ents = {"R": {"root": True, "specializations": {"s": {"alternatives": ["A1", "B1"]}}}}
    below = "R"
    for i in range(1, k + 1):
        ents[f"A{i}"], ents[f"B{i}"] = {"extends": below}, {"extends": f"A{i}"}
        if i < k:
            for name in (f"A{i}", f"B{i}"):
                ents[name]["specializations"] = {"t": {"alternatives": [f"A{i + 1}", f"B{i + 1}"]}}
        below = f"B{i}"
    assert timed({"ses": "1.0", "name": "R", "entities": ents}) == (2 ** k, 2 ** k)

    # 2. 주인이 k 명이고 저마다 분해가 둘인 병합체. 요구의 조합이 2의 k 제곱 가지다
    k = 30
    ents = {"L": {}}
    for i in range(k):
        name = "R" if i == 0 else f"A{i}"
        ents[name] = {"aspects": {f"hi{i}": {"parts": ["L"], "priority": 2 * i}, f"lo{i}": {"parts": ["L"], "priority": 2 * i + 1}}}
        if i == 0:
            ents[name]["root"] = True
        else:
            ents[name]["extends"] = "R" if i == 1 else f"A{i - 1}"
        if i < k - 1:
            ents[name]["specializations"] = {"s": {"alternatives": [f"A{i + 1}"]}}
    # 뿌리가 hi0 을 내면 hi0 이, lo0 을 내면 lo0 이 가장 앞선다. 다른 주인의 분해는 모두 그 뒤다
    assert timed({"ses": "1.0", "name": "R", "entities": ents}) == (2, 2)

    # 3. 깊이 D 의 사슬. 층마다 분해가 둘이고 맨 아래를 경로로 가리키는 제약이 하나 있다
    depth = 40
    ents = {f"E{depth}": {"specializations": {"k": {"alternatives": ["K0", "K1"]}}},
            "K0": {"extends": f"E{depth}"}, "K1": {"extends": f"E{depth}"}}
    for i in range(depth):
        ents[f"E{i}"] = {"aspects": {"a": {"parts": [{"def": f"E{i + 1}", "alias": "p"}]},
                                     "b": {"parts": [{"def": f"E{i + 1}", "alias": "p"}]}}}
    ents["E0"]["root"] = True
    d = {"ses": "1.0", "name": "E0", "entities": ents,
         "constraints": [{"name": "c", "require": {"selected": {"path": ["E0"] + ["p"] * depth, "specialization": "k",
                                                               "alternative": "K0"}}}]}
    assert timed(d) == (2 ** depth, 2 ** depth)

    # 4. 복제본 백만 개, 그리고 개수가 1에서 4,000까지인 범위
    assert timed(pool(1, 1) | {"entities": dict(pool(1, 1)["entities"], R={"root": True, "multi_aspects": {
        "m": {"part": "Leaf", "cardinality": 10 ** 6}}})}) == (1, 1)
    assert timed(pool(4000, 1)) == (4000, 4000)


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
    assert STATS["models"] >= 1500 and STATS["docs_with_hidden_ties"] >= 5 and STATS["clusters"] >= 2000, STATS
    assert STATS["docs_with_dead"] >= 100 and STATS["dead_but_in_some_variant"] >= 30 and STATS["stuck_places"] >= 60, STATS
