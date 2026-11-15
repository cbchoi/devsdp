"""사례마다 다른 매개변수 (docs/ses-platform/18_classic_parity.md 4절).

전통적인 SES는 속성의 값을 상수, SES 변수, SES 함수로 주고 복제본에는 값을 하나씩 나눠 준다.
여기서는 네 가지를 확인한다.
1. 속성의 식(expr): 변수, 등록한 함수, 복제본의 번호와 개수에서 값이 정해진다.
2. 복제본마다의 값(each): 문헌의 패턴 2.
3. 결정 집합의 속성 재정의(set): 정의 수준과 구성요소 수준.
4. 그 값이 실행기의 계획과 실행에 닿는다.

확인하는 길은 셋이다. 손으로 만든 예, 문헌의 서술을 따라 따로 적은 고전 절차(classic.py)와의
무작위 대조, 가지치기 앞뒤에서 값이 같다는 것(정리 14)의 무작위 확인이다.
"""

import collections
import copy
import json
import os
import random
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import _system_attempt  # noqa: E402

from examples import processing_mb  # noqa: E402
from ses_core import LoadError, classic, devs, load_ses_dict  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core.algebra import AlgebraError, count_variants, sem  # noqa: E402
from ses_core.decisions import (Choice, DecisionSet, Override, apply, choice_table, decide,  # noqa: E402
                                load_decisions, override_problems, problems, with_overrides)
from ses_core.devs import DevsExecutor, simulate  # noqa: E402
from ses_core.executor import Bind, Binding, Module  # noqa: E402
from ses_core.ext_attr import AttrDecl, Attributes  # noqa: E402
from ses_core.extension import Layered, interpret, violations  # noqa: E402
from ses_core.skeleton import assignment, component_path, skeleton  # noqa: E402
from ses_core.unfold import unfold, unfold_layered, variable_domains  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform")
EXAMPLES = os.path.join(ROOT, "examples")
STATS: collections.Counter = collections.Counter()


def flat(tree: dict, path: tuple = ()) -> dict:
    """속성 확장의 해석을 구성요소 경로에서 속성 값으로 가는 표로."""
    out = {path: tree["params"]}
    for name, child in tree["children"].items():
        out.update(flat(child, path + (name,)))
    return out


def values(d: dict, functions=None, ds: DecisionSet = None) -> dict:
    """변수 값마다, 구성요소 경로에서 속성 값으로 가는 표들. 적격인 변이만 센다."""
    L = unfold_layered(load_ses_dict(d), functions=functions).only("attr")
    if ds is not None:
        L = decide(L, ds)
    out: dict = {}
    for V in sem(L.ses):
        if not violations(L, V):
            sigma = tuple(sorted(assignment(L.ses.tree, V).items()))
            out.setdefault(sigma, []).append(flat(interpret(L, V)["attr"]))
    return out


def only(d: dict, functions=None, ds: DecisionSet = None) -> dict:
    """변이가 하나뿐인 문서의 속성 값."""
    (tables,) = values(d, functions, ds).values()
    (table,) = tables
    return table


# ---------------------------------------------------------------------------
# 1. 문헌의 패턴 2: 복제본마다의 값
# ---------------------------------------------------------------------------

FIGURE3 = {"ses": "1.0", "name": "as",
           "variables": {"VAR": {"type": "int", "range": [2, 3]}},
           "entities": {
               "as": {"root": True, "multi_aspects": {
                   "aMASP": {"part": "b", "cardinality": {"var": "VAR"}, "naming": "b{i}"}}},
               "b": {"attributes": {"p": {"type": "enum", "each": [1, "a", 200]}}}}}


def test_figure3_each_replica_takes_its_own_value():
    """Deatcu et al. (2019)의 그림 3. 복제본이 둘이면 앞의 두 값을, 셋이면 세 값을 차례로 가진다."""
    got = values(FIGURE3)
    assert got[(("VAR", "2"),)] == [{(): {}, ("b0",): {"p": 1}, ("b1",): {"p": "a"}}]
    assert got[(("VAR", "3"),)] == [{(): {}, ("b0",): {"p": 1}, ("b1",): {"p": "a"}, ("b2",): {"p": 200}}]
    assert {tuple(n["children"][k]["attrs"]["p"] for k in sorted(n["children"]))       # 고전 절차도 같다
            for _, n in classic.enumerate_classic(load_ses_dict(FIGURE3))} == {(1, "a"), (1, "a", 200)}


def test_each_falls_back_to_the_default():
    """목록이 모자라거나 복제본이 아닌 자리에서는 default를 쓴다. default도 없으면 값이 없다."""
    d = copy.deepcopy(FIGURE3)
    d["entities"]["b"]["attributes"]["p"] = {"type": "int", "each": [7], "default": 0}
    d["entities"]["b"]["attributes"]["q"] = {"type": "int", "each": [5]}
    d["entities"]["as"]["aspects"] = {"single": {"parts": [{"def": "b", "alias": "alone"}]}}
    got = values(d)
    three = next(t for t in got[(("VAR", "3"),)] if ("b2",) in t)
    assert [three[(f"b{i}",)] for i in range(3)] == [{"p": 7, "q": 5}, {"p": 0, "q": None}, {"p": 0, "q": None}]
    alone = next(t for t in got[(("VAR", "3"),)] if ("alone",) in t)
    assert alone[("alone",)] == {"p": 0, "q": None}


# ---------------------------------------------------------------------------
# 2. 속성의 식
# ---------------------------------------------------------------------------

GRID = {"ses": "1.0", "name": "Field",
        "variables": {"rows": {"type": "int", "range": [1, 2]}, "gain": {"type": "int", "range": [1, 3]}},
        "entities": {
            "Field": {"root": True,
                      "attributes": {"total": {"type": "int", "expr": {"call": "area", "args": [{"var": "rows"}, 3]}}},
                      "multi_aspects": {"lines": {"part": "Row", "cardinality": {"var": "rows"}, "naming": "row{i}"}}},
            "Row": {"attributes": {"y": {"type": "int", "expr": {"replica": "index"}}},
                    "multi_aspects": {"cells": {"part": "Cell", "cardinality": 3, "naming": "c{i}"}}},
            "Cell": {"attributes": {
                "x": {"type": "int", "expr": {"replica": "index"}},
                "row": {"type": "int", "expr": {"replica": "index", "up": 1}},
                "id": {"type": "int", "expr": {"call": "cell_id", "args": [{"replica": "index", "up": 1},
                                                                      {"replica": "index"}, {"replica": "count"}]}},
                "k": {"type": "int", "expr": {"var": "gain"}},
                "last": {"type": "bool", "expr": {"call": "is_last", "args": [{"replica": "index"}, {"replica": "count"}]}},
                "edge": {"type": "bool", "expr": {"replica": "index", "eq": 0}},
                "size": {"type": "int", "expr": {"replica": "count", "up": 1}}},
                "aspects": {"inside": {"parts": ["Probe"]}}},
            "Probe": {"attributes": {"owner": {"type": "int", "expr": {"replica": "index"}}}}}}

GRID_FUNCTIONS = {"area": lambda r, c: r * c, "cell_id": lambda r, c, n: r * n + c, "is_last": lambda i, n: i == n - 1}


def test_values_come_from_variables_functions_and_replica_numbers():
    got = values(GRID, GRID_FUNCTIONS)
    assert len(got) == 6 and all(len(tables) == 1 for tables in got.values())
    for sigma, (table,) in got.items():
        rows, gain = int(dict(sigma)["rows"]), int(dict(sigma)["gain"])
        assert table[()] == {"total": rows * 3}
        for r in range(rows):
            assert table[(f"row{r}",)] == {"y": r}
            for c in range(3):
                assert table[(f"row{r}", f"c{c}")] == {"x": c, "row": r, "id": r * 3 + c, "k": gain,
                                                       "last": c == 2, "edge": c == 0, "size": rows}
                assert table[(f"row{r}", f"c{c}", "Probe")] == {"owner": c}        # 복제본 아래의 부분은 그 복제본의 번호를 본다
        assert len(table) == 1 + rows * (1 + 3 * 2)


def test_a_value_that_does_not_depend_on_variables_is_fixed_when_unfolding():
    L = unfold_layered(load_ses_dict(GRID), functions=GRID_FUNCTIONS)
    attr = next(x for x in L.extensions if x.name == "attr")
    by_name: dict = collections.defaultdict(list)
    for decls in attr.decls.values():
        for name, d in decls.items():
            by_name[name].append(d)
    static = ("x", "y", "row", "id", "last", "edge", "size")      # 개수는 펼친 나무에서 노드마다 정해져 있다
    assert all(d.compute is None and d.value is not None for n in static for d in by_name[n])
    assert all(d.compute is not None and d.value is None for n in ("k", "total") for d in by_name[n])
    assert len({id(d) for d in by_name["k"]}) == 1          # 같은 정의의 같은 식은 한 번만 표로 만든다


def test_expression_errors_are_reported_when_loading_or_unfolding():
    def load(attrs: dict, **more):
        d = {"ses": "1.0", "name": "R", "variables": {"n": {"type": "int", "range": [1, 3]}},
             "entities": {"R": {"root": True, "multi_aspects": {"m": {"part": "A", "cardinality": 2}}, **more},
                          "A": {"attributes": attrs}}}
        return unfold(load_ses_dict(d), {"inv": lambda n: 1 // (n - 2), "text": lambda n: "x"})

    with pytest.raises(LoadError, match="expr 과 each 를 함께"):
        load({"a": {"type": "int", "expr": {"var": "n"}, "each": [1]}})
    with pytest.raises(LoadError, match="each 는 복제본마다의 값을 적은 목록"):
        load({"a": {"type": "int", "each": 3}})
    with pytest.raises(LoadError, match=r"each\[1\]: 값 'x' 이 타입 int"):
        load({"a": {"type": "int", "each": [1, "x"]}})
    with pytest.raises(LoadError, match="each.*True"):                   # bool은 수가 아니다
        load({"a": {"type": "int", "each": [True]}})
    with pytest.raises(LoadError, match="정의되지 않은 변수 nope"):
        load({"a": {"type": "int", "expr": {"var": "nope"}}})
    with pytest.raises(LoadError, match="selected 는 선택 제약"):
        load({"a": {"type": "bool", "expr": {"selected": "R=m"}}})
    with pytest.raises(LoadError, match="replica 는 index 또는 count"):
        load({"a": {"type": "int", "expr": {"replica": "position"}}})
    with pytest.raises(LoadError, match="replica 는 index 또는 count"):
        load({"a": {"type": "int", "expr": {"replica": "index", "up": -1}}})
    with pytest.raises(AlgebraError, match="감싼 multi-aspect 가 1 겹뿐"):
        load({"a": {"type": "int", "expr": {"replica": "index", "up": 1}}})
    with pytest.raises(AlgebraError, match="감싼 multi-aspect 가 0 겹뿐"):
        load({}, attributes={"a": {"type": "int", "expr": {"replica": "count"}}})
    with pytest.raises(AlgebraError, match="타입 int 에 맞지 않는 값 'x'"):
        load({"a": {"type": "int", "expr": {"call": "text", "args": [{"var": "n"}]}}})
    with pytest.raises(AlgebraError, match="함수 inv 가 인자"):
        load({"a": {"type": "int", "expr": {"call": "inv", "args": [{"var": "n"}]}}})
    with pytest.raises(AlgebraError, match="등록되지 않은 함수 missing"):
        load({"a": {"type": "int", "expr": {"call": "missing", "args": []}}})
    load({"a": {"type": "float", "expr": {"var": "n"}}})                 # float 자리에 정수는 온다


def test_replica_numbers_are_not_available_in_rules_and_constraints():
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "multi_aspects": {"m": {"part": "A", "cardinality": 2}}},
                      "A": {"specializations": {"s": {"alternatives": ["B", "C"], "select": {
                          "when": {"replica": "index", "eq": 0}, "then": "B", "else": "C"}}}},
                      "B": {"extends": "A"}, "C": {"extends": "A"}}}
    with pytest.raises(LoadError, match="replica 는 속성의 식에서만"):
        load_ses_dict(d)
    del d["entities"]["A"]["specializations"]["s"]["select"]
    d["constraints"] = [{"name": "c", "require": {"replica": "count", "ge": 1}}]
    with pytest.raises(LoadError, match="replica 는 속성의 식에서만"):
        load_ses_dict(d)


def test_a_table_that_is_too_large_is_refused():
    d = {"ses": "1.0", "name": "R",
         "variables": {f"v{i}": {"type": "int", "range": [1, 30]} for i in range(3)},
         "entities": {"R": {"root": True, "attributes": {"a": {"type": "int", "expr": {
             "call": "sum3", "args": [{"var": "v0"}, {"var": "v1"}, {"var": "v2"}]}}}}}}
    with pytest.raises(AlgebraError, match="표가 너무 크다"):
        unfold(load_ses_dict(d), {"sum3": lambda a, b, c: a + b + c})


def test_new_attribute_forms_are_in_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(ROOT, "schema", "ses.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(GRID, schema)
    jsonschema.validate(FIGURE3, schema)
    bad = copy.deepcopy(GRID)
    bad["entities"]["Row"]["attributes"]["y"]["expr"] = {"replica": "position"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    bad = copy.deepcopy(FIGURE3)
    bad["entities"]["b"]["attributes"]["p"]["each"] = 3
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


# ---------------------------------------------------------------------------
# 3. 병합: 대안이 준 값이 바탕의 값을 덮고, 어긋나면 그 변이만 부적격이다
# ---------------------------------------------------------------------------

MERGE = {"ses": "1.0", "name": "R",
         "variables": {"n": {"type": "int", "range": [1, 3]}},
         "entities": {
             "R": {"root": True, "attributes": {"a": {"type": "int", "default": 0}},
                   "specializations": {"s": {"alternatives": ["S1", "S2"]}, "t": {"alternatives": ["T1", "T2"]}}},
             "S1": {"extends": "R", "attributes": {"a": {"type": "int", "expr": {"var": "n"}}}},
             "S2": {"extends": "R"},
             "T1": {"extends": "R", "attributes": {"a": {"type": "int", "default": 2}}},
             "T2": {"extends": "R"}}}


def test_values_that_depend_on_variables_merge_like_constants():
    L = unfold_layered(load_ses_dict(MERGE)).only("attr")
    got, clashes = {}, set()
    for V in sem(L.ses):
        labels = frozenset(skeleton(L.ses.tree, L.void, V).labels) - {"R"}
        n = int(assignment(L.ses.tree, V)["n"])
        if violations(L, V):
            clashes.add((n, labels))
        else:
            got[(n, labels)] = interpret(L, V)["attr"]["params"]["a"]
    assert clashes == {(1, frozenset({"S1", "T1"})), (3, frozenset({"S1", "T1"}))}     # n = 2에서는 두 값이 같다
    for n in (1, 2, 3):
        assert got[(n, frozenset({"S2", "T2"}))] == 0          # 바탕의 값
        assert got[(n, frozenset({"S1", "T2"}))] == n          # 대안의 식이 덮는다
        assert got[(n, frozenset({"S2", "T1"}))] == 2
    assert got[(2, frozenset({"S1", "T1"}))] == 2
    assert len(got) == 10


# ---------------------------------------------------------------------------
# 4. 결정 집합의 속성 재정의
# ---------------------------------------------------------------------------

POOL = {"ses": "1.0", "name": "Plant",
        "entities": {
            "Plant": {"root": True, "aspects": {"d": {"parts": ["Pool", {"def": "Server", "alias": "spare"}]}}},
            "Pool": {"multi_aspects": {"servers": {"part": "Server", "cardinality": 3, "naming": "s{i}"}}},
            "Server": {"attributes": {"t": {"type": "float", "default": 2.0}, "tag": {"type": "str"}},
                       "specializations": {"kind": {"alternatives": ["Fast", "Slow"]}}},
            "Fast": {"extends": "Server", "attributes": {"t": {"type": "float", "default": 1.0}}},
            "Slow": {"extends": "Server"}}}
FAST = DecisionSet(choose=(Choice(at="Server", specialization="kind", alternative=("Fast",)),))
SLOW = DecisionSet(choose=(Choice(at="Server", specialization="kind", alternative=("Slow",)),))


def test_an_override_at_a_definition_follows_the_merge_rule():
    """정의 수준의 재정의는 그 정의가 준 값을 바꾼다. 더 구체적인 대안이 준 값은 여전히 그것을 덮는다."""
    servers = [("Pool", "s0"), ("Pool", "s1"), ("Pool", "s2"), ("spare",)]
    table = only(POOL, ds=FAST)
    assert all(table[p]["t"] == 1.0 for p in servers) and set(table) == set(servers) | {(), ("Pool",)}
    table = only(POOL, ds=FAST.override(Override("t", 5.0, at="Server")))
    assert all(table[p]["t"] == 1.0 for p in servers)                   # 대안 Fast가 준 값이 여전히 덮는다
    table = only(POOL, ds=SLOW.override(Override("t", 5.0, at="Server")))
    assert all(table[p]["t"] == 5.0 for p in servers)
    table = only(POOL, ds=FAST.override(Override("t", 0.5, at="Fast")))
    assert all(table[p]["t"] == 0.5 for p in servers)
    table = only(POOL, ds=SLOW.override(Override("t", 0.5, at="Fast")))  # Fast가 구성원이 아닌 곳에는 미치지 않는다
    assert all(table[p]["t"] == 2.0 for p in servers)


def test_an_override_at_a_component_wins_and_reaches_one_replica():
    ds = FAST.override(Override("t", 0.5, at="Fast")).override(Override("t", 9.0, path=("Plant", "Pool", "s1"))) \
             .override(Override("tag", "hot", path=("Plant", "spare")))
    table = only(POOL, ds=ds)
    assert [table[("Pool", f"s{i}")]["t"] for i in range(3)] == [0.5, 9.0, 0.5]
    assert table[("spare",)] == {"t": 0.5, "tag": "hot"} and table[("Pool", "s0")]["tag"] is None
    assert len(values(POOL)[()]) == len(values(POOL, ds=DecisionSet(set=ds.set))[()]) == 16     # 재정의는 변이를 줄이지 않는다
    again = ds.override(Override("t", 3.0, path=("Plant", "Pool", "s1")))                       # 같은 곳의 재정의는 바뀐다
    assert len(again.set) == 3 and only(POOL, ds=again)[("Pool", "s1")]["t"] == 3.0
    undone = again.undecide(("set", "path", ("Plant", "Pool", "s1"), "t"))
    assert len(undone.set) == 2 and only(POOL, ds=undone)[("Pool", "s1")]["t"] == 0.5


def test_an_override_at_a_component_settles_a_clash_of_values():
    """서로 다른 대안이 다른 값을 주어 합칠 수 없던 구성요소도, 그 구성요소에 값을 직접 주면 적격이 된다."""
    L = unfold_layered(load_ses_dict(MERGE)).only("attr")
    bad = [V for V in sem(L.ses) if violations(L, V)]
    assert len(bad) == 2
    fixed = with_overrides(L, DecisionSet(set=(Override("a", 7, path=("R",)),)))
    assert not any(violations(fixed, V) for V in sem(fixed.ses))
    assert {interpret(fixed, V)["attr"]["params"]["a"] for V in sem(fixed.ses)} == {7}
    still = with_overrides(L, DecisionSet(set=(Override("a", 7, at="R"),)))          # 정의 수준의 것은 병합 규칙을 따른다
    assert [V for V in sem(still.ses) if violations(still, V)] == bad


def test_overrides_that_do_not_fit_the_target_are_reported():
    L = unfold_layered(load_ses_dict(POOL))
    cases = [
        (Override("t", 1.0, at="Nobody"), "가리키는 곳이 대상에 없다"),
        (Override("t", 1.0, path=("Plant", "Pool", "s9")), "가리키는 곳이 대상에 없다"),
        (Override("speed", 1.0, at="Server"), "정의 Server 에 속성 speed 가 없다"),
        (Override("t", 1.0, path=("Plant", "Pool")), "구성요소 Plant/Pool 에 속성 t 가 없다"),
        (Override("t", "quick", at="Server"), "타입 float 에 맞지 않다"),
        (Override("tag", 3, path=("Plant", "spare")), "타입 str 에 맞지 않다"),
        (Override("t", True, at="Server"), "타입 float 에 맞지 않다"),
        (Override("t", 1.0), "at 과 path 가운데 정확히 하나"),
        (Override("t", 1.0, at="Server", path=("Plant", "spare")), "at 과 path 가운데 정확히 하나"),
        (Override("t", None, at="Server"), "value 는 값 하나"),
        (Override("t", [1.0], at="Server"), "value 는 값 하나"),
        (Override("", 1.0, at="Server"), "attribute 에 속성의 이름"),
    ]
    for o, why in cases:
        ds = DecisionSet(set=(o,))
        ((key, said),) = override_problems(L, ds)
        assert why in said and key == o.key, (o, said)
        with pytest.raises(AlgebraError, match=re.escape(why)):
            with_overrides(L, ds)
        skipped = next(x for x in with_overrides(L, ds, skip_invalid=True).extensions if x.name == "attr")
        assert skipped.by_def == {} and skipped.by_path == {}
    good = Override("t", 4, at="Server")                                # float 자리에 정수는 온다
    assert override_problems(L, DecisionSet(set=(good,))) == []
    mixed = DecisionSet(set=(good, cases[0][0]))
    kept = with_overrides(L, mixed, skip_invalid=True)
    assert next(x for x in kept.extensions if x.name == "attr").by_def == {("Server", "t"): 4}
    assert problems(L.ses, mixed) == []                                 # 선택에 대한 결정의 검사는 재정의를 보지 않는다
    assert with_overrides(L, DecisionSet()) is L


def test_overrides_are_part_of_the_decision_file():
    jsonschema = pytest.importorskip("jsonschema")
    ds = DecisionSet("tuned", "Plant", {}, FAST.choose,
                     (Override("t", 0.5, at="Fast"), Override("t", 9.0, path=("Plant", "Pool", "s1"))))
    d = ds.to_dict()
    assert d["set"] == [{"at": "Fast", "attribute": "t", "value": 0.5},
                        {"path": ["Plant", "Pool", "s1"], "attribute": "t", "value": 9.0}]
    assert DecisionSet.from_dict(json.loads(json.dumps(d))) == ds
    with open(os.path.join(ROOT, "schema", "decisions.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(d, schema)
    for bad in ({"attribute": "t", "value": 1}, {"at": "A", "path": ["A"], "attribute": "t", "value": 1},
                {"at": "A", "attribute": "t"}, {"at": "A", "attribute": "t", "value": [1]},
                {"at": "A", "attribute": "t", "value": 1, "node": ["A"]}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(dict(d, set=[bad]), schema)
    assert "set" not in FAST.to_dict()


def test_overrides_follow_renames():
    ds = DecisionSet(set=(Override("t", 0.5, at="Fast"), Override("t", 9.0, path=("Plant", "Pool", "s1")),
                          Override("tag", "x", at="Server")))
    moved = ds.renamed("entity", "Fast", "Quick").renamed("entity", "Pool", "Farm")
    assert [o.at for o in moved.set] == ["Quick", None, "Server"]
    assert moved.set[1].path == ("Plant", "Farm", "s1")
    named = ds.renamed("attribute", "t", "service_time", owner="Fast")
    assert [o.attribute for o in named.set] == ["service_time", "t", "tag"]


# ---------------------------------------------------------------------------
# 5. 값이 실행기에 닿는다
# ---------------------------------------------------------------------------

def processing(change=None, functions=None, ds: DecisionSet = None):
    import yaml
    with open(os.path.join(EXAMPLES, "processing_system.ses.yaml"), encoding="utf-8") as f:
        d = yaml.safe_load(f)
    if change:
        change(d)
    L0 = unfold_layered(load_ses_dict(d), functions=functions)
    binding = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.devs.yaml"))
    pruned = decide(L0, ds) if ds is not None else L0
    L, ext = X.attach(pruned, DevsExecutor(), binding, processing_mb.LIBRARY)
    return L, ext


FOUR = DecisionSet(variables={"policy": ("priority",), "num_servers": (4,)})


def service_times(L, ext, V) -> dict:
    return {p[-1]: c["params"]["service_time"] for p, c in X.st.walk(X.plan(L, ext, V)) if c.get("module") == "Server"}


def test_replicas_run_with_their_own_parameters():
    """서버마다 서비스 시간이 다른 처리 시스템. 세 길(each, 식, 재정의)이 같은 계획과 같은 실행을 낸다."""
    def each(d):
        d["entities"]["Server"]["attributes"]["service_time"] = {"type": "float", "each": [1.0, 2.0, 3.0, 4.0]}

    def expr(d):
        d["entities"]["Server"]["attributes"]["service_time"] = {
            "type": "float", "expr": {"call": "nth_time", "args": [{"replica": "index"}]}}

    by_set = FOUR
    for i in range(4):
        by_set = by_set.override(Override("service_time", float(i + 1), path=("ProcessingSystem", "ServerPool", f"server_{i}")))
    runs = []
    for change, functions, ds in ((each, None, FOUR), (expr, {"nth_time": lambda i: float(i + 1)}, FOUR), (None, None, by_set)):
        L, ext = processing(change, functions, ds)
        (V,) = sem(L.ses)
        assert X.executable(L, ext, V)
        assert service_times(L, ext, V) == {f"server_{i}": float(i + 1) for i in range(4)}
        model = X.realize(L, ext, DevsExecutor(), V)
        log = simulate(model, 40.0)
        leaves = devs._leaves(model)
        assert [leaves[("ServerPool", f"server_{i}")].service_time for i in range(4)] == [1.0, 2.0, 3.0, 4.0]
        runs.append((X.plan(L, ext, V), log, len(leaves[("Collector",)].done)))
    assert runs[0] == runs[1] == runs[2]
    L, ext = processing(None, None, FOUR)                               # 모두 2.0인 원래 문서와는 실행이 다르다
    (V,) = sem(L.ses)
    plain = simulate(X.realize(L, ext, DevsExecutor(), V), 40.0)
    assert plain != runs[0][1]


def test_decision_file_with_overrides_to_running_model():
    """예시 파일: 결정 집합의 set 이 서버마다 다른 서비스 시간을 주고, 그 값으로 모델이 돈다."""
    import yaml
    jsonschema = pytest.importorskip("jsonschema")
    path = os.path.join(EXAMPLES, "processing_system.decisions.tuned.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    with open(os.path.join(ROOT, "schema", "decisions.schema.json"), encoding="utf-8") as f:
        jsonschema.validate(raw, json.load(f))
    ds = load_decisions(path)
    assert len(ds.set) == 3 and ds.to_dict() == raw
    L, ext = processing(None, None, ds)
    (V,) = sem(L.ses)
    assert X.executable(L, ext, V)
    assert service_times(L, ext, V) == {"server_0": 1.0, "server_1": 3.0, "server_2": 3.0, "server_3": 5.0}
    model = X.realize(L, ext, DevsExecutor(), V)
    simulate(model, 40.0)
    leaves = devs._leaves(model)
    assert [leaves[("ServerPool", f"server_{i}")].service_time for i in range(4)] == [1.0, 3.0, 3.0, 5.0]
    assert len(leaves[("Collector",)].done) > 0


def test_a_value_from_a_variable_reaches_the_plan():
    def change(d):
        d["variables"]["speed"] = {"type": "int", "range": [1, 3]}
        d["entities"]["Server"]["attributes"]["service_time"] = {"type": "float", "expr": {"var": "speed"}}

    L, ext = processing(change, None, FOUR)
    seen = {}
    for V in sem(L.ses):
        assert X.executable(L, ext, V)
        seen[assignment(L.ses.tree, V)["speed"]] = set(service_times(L, ext, V).values())
    assert seen == {"1": {1}, "2": {2}, "3": {3}}


def test_time_values_from_expressions_and_overrides_are_checked_against_the_time_unit():
    """시간 값이 시간 단위의 정수배가 아니면 그 변이는 실행 가능하지 않다(B5). 값이 어디서 왔든 같다."""
    def change(d):
        d["variables"]["half"] = {"type": "int", "range": [1, 4]}
        d["entities"]["Server"]["attributes"]["service_time"] = {
            "type": "float", "expr": {"call": "halves", "args": [{"var": "half"}]}}

    L, ext = processing(change, {"halves": lambda h: h / 2}, FOUR)
    ok = {assignment(L.ses.tree, V)["half"]: X.executable(L, ext, V) for V in sem(L.ses)}
    assert ok == {"1": False, "2": True, "3": False, "4": True}
    V = next(V for V in sem(L.ses) if assignment(L.ses.tree, V)["half"] == "3")
    found = [(code, path[-1]) for _, code, path, _ in violations(X.alone(L, ext), V)]
    assert sorted(found) == [("B5", f"server_{i}") for i in range(4)]

    one = FOUR.override(Override("service_time", 2.5, path=("ProcessingSystem", "ServerPool", "server_2")))
    L, ext = processing(None, None, one)
    (V,) = sem(L.ses)
    assert [(code, path[-1]) for _, code, path, _ in violations(X.alone(L, ext), V)] == [("B5", "server_2")]


def test_a_missing_value_and_a_wrong_type_are_reported_by_the_executor():
    """값이 없는 매개변수(B4)와 타입이 맞지 않는 값(B4)은 계획에서 걸린다."""
    lib = dict(processing_mb.LIBRARY)
    old = lib["Server"]
    lib["Server"] = Module("Server", old.ports, old.required, {"service_time": ("time",)}, old.body)

    def change(d):
        d["entities"]["Server"]["attributes"]["service_time"] = {"type": "float", "each": [1.0, 2.0]}

    import yaml
    with open(os.path.join(EXAMPLES, "processing_system.ses.yaml"), encoding="utf-8") as f:
        d = yaml.safe_load(f)
    change(d)
    L0 = decide(unfold_layered(load_ses_dict(d)), FOUR)
    binding = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.devs.yaml"))
    L, ext = X.attach(L0, DevsExecutor(), binding, lib)
    (V,) = sem(L.ses)
    found = sorted((code, path[-1]) for _, code, path, _ in violations(X.alone(L, ext), V))
    assert found == [("B4", "server_2"), ("B4", "server_3")]             # 목록이 모자란 복제본에 줄 값이 없다

    d["entities"]["Server"]["attributes"]["service_time"] = {"type": "str", "each": ["a", "b", "c", "d"]}
    L0 = decide(unfold_layered(load_ses_dict(d)), FOUR)
    L, ext = X.attach(L0, DevsExecutor(), binding, lib)
    (V,) = sem(L.ses)
    found = sorted((code, path[-1], msg) for _, code, path, msg in violations(X.alone(L, ext), V))
    assert [(c, p) for c, p, _ in found] == [("B4", f"server_{i}") for i in range(4)]
    assert "'a' 이 타입 time 이 아니다" in found[0][2]                   # 값은 있지만 모듈이 바라는 타입이 아니다


def test_attach_keeps_working_without_attributes_and_with_hand_made_ones():
    """속성이 없는 문서, 손으로 만든 속성 확장에도 실행기를 붙일 수 있다."""
    d = {"ses": "1.0", "name": "R", "entities": {"R": {"root": True, "aspects": {"a": {"parts": ["A"]}}}, "A": {}}}
    L0 = unfold_layered(load_ses_dict(d))
    lib = {"M": Module("M", {}, (), {"w": ("int", 3)})}
    L, ext = X.attach(L0, X.Executor(), Binding("x", {"A": Bind("M")}), lib)
    (V,) = sem(L.ses)
    assert X.plan(L, ext, V)["children"]["A"]["params"] == {"w": 3}
    hand = Layered(L0.ses, L0.void, (Attributes({("R", "a", "A"): {"w": AttrDecl("int", 8)}}),))
    L, ext = X.attach(hand, X.Executor(), Binding("x", {"A": Bind("M")}), lib)
    assert X.plan(L, ext, V)["children"]["A"]["params"] == {"w": 8}
    over = with_overrides(hand, DecisionSet(set=(Override("w", 5, at="A"),)))
    L, ext = X.attach(over, X.Executor(), Binding("x", {"A": Bind("M")}), lib)
    assert X.plan(L, ext, V)["children"]["A"]["params"] == {"w": 5}


# ---------------------------------------------------------------------------
# 6. 고전 절차와의 무작위 대조
# ---------------------------------------------------------------------------

FUNCTIONS = {"mix": lambda a, b: a * 10 + b, "nth": lambda i, n: (i + 1) * 100 + n, "one": lambda: 1,
             "odd": lambda a: a % 2 == 1}
NAMES = ("w", "x", "y")


def replica_depths(d: dict) -> dict:
    """정의마다, 그 정의가 놓이는 자리를 감싼 multi-aspect 의 겹 수 가운데 가장 작은 것."""
    ents, depth = d["entities"], {}
    stack = [(next(n for n, b in ents.items() if b.get("root")), 0)]
    while stack:
        name, k = stack.pop()
        if depth.get(name, 99) <= k:
            continue
        depth[name] = k
        body = ents[name]
        for a in (body.get("aspects") or {}).values():
            stack += [(p if isinstance(p, str) else p["def"], k) for p in a["parts"]]
        for ma in (body.get("multi_aspects") or {}).values():
            stack.append((ma["part"] if isinstance(ma["part"], str) else ma["part"]["def"], k + 1))
        for sp in (body.get("specializations") or {}).values():
            stack += [(alt, k) for alt in sp["alternatives"]]
    return depth


def rand_value(rng: random.Random, variables: list, depth: int) -> dict:
    """속성 하나의 선언. 값을 주는 길을 고루 섞는다. depth 는 그 정의를 감싼 multi-aspect 의 겹 수다."""
    kinds = ["default", "default", "default", "each", "var", "call", "const_call", "none", "bool"]
    if depth:                                   # 복제본 안에서는 번호를 쓰는 값을 자주 고른다
        kinds += ["index", "index", "index", "nth", "nth", "each", "each"]
    kind = rng.choice(kinds)
    if kind in ("var", "call") and not variables:
        kind = "default"
    if kind == "default":
        return {"type": "int", "default": rng.randint(1, 3)}
    if kind == "each":
        out = {"type": "int", "each": [rng.randint(1, 3) for _ in range(rng.randint(1, 3))]}
        if rng.random() < 0.5:
            out["default"] = rng.randint(1, 3)
        return out
    if kind == "var":
        return {"type": "int", "expr": {"var": rng.choice(variables)}}
    if kind == "call":
        return {"type": "int", "expr": {"call": "mix", "args": [{"var": rng.choice(variables)}, rng.randint(1, 3)]}}
    if kind == "index":
        return {"type": "int", "expr": {"replica": rng.choice(["index", "count"]), "up": rng.randrange(depth)}}
    if kind == "nth":
        return {"type": "int", "expr": {"call": "nth", "args": [{"replica": "index"}, {"replica": "count"}]}}
    if kind == "const_call":
        return {"type": "int", "expr": {"call": "one", "args": []}}
    if kind == "bool":                          # 타입이 다른 선언. 같은 이름의 int 선언과 만나면 합칠 수 없다
        return {"type": "bool", "default": rng.random() < 0.5}
    return {"type": "int"}


def with_values(seed: int) -> tuple:
    """무작위 문서의 속성을 여러 길로 값을 주는 속성으로 바꾼다. (사전, 문서)"""
    rng = random.Random(seed)
    while True:
        d = _system_attempt(rng)
        variables = sorted(d.get("variables") or {})
        for name in list(d["entities"]):        # 둘째 specialization: 서로 조상이 아닌 대안들이 같은 속성에 값을 줄 수 있게
            body = d["entities"][name]
            if "specializations" in body and "extends" not in body and rng.random() < 0.4:
                alts = [f"{name}_z{j}" for j in range(2)]
                body["specializations"]["s1"] = {"alternatives": alts}
                for alt in alts:
                    d["entities"][alt] = {"extends": name}
        ports = lambda: {"i": {"type": "T", "direction": "in"}, "o": {"type": "T", "direction": "out"}}   # noqa: E731
        for name in list(d["entities"]):        # 복제본으로만 쓰이는 정의: 그 안에서만 복제본의 번호를 물을 수 있다
            for mname, ma in (d["entities"][name].get("multi_aspects") or {}).items():
                if rng.random() < 0.7:
                    new = f"{name}_{mname}_r"
                    d["entities"][new] = {"ports": ports()}
                    ma["part"] = new
                    if rng.random() < 0.5:      # 복제본의 대안. 같은 구성요소이므로 같은 번호를 본다
                        alts = [f"{new}_k{j}" for j in range(2)]
                        d["entities"][new]["specializations"] = {"k": {"alternatives": alts}}
                        for alt in alts:
                            d["entities"][alt] = {"extends": new}
                    if rng.random() < 0.4:      # 복제본의 부분. 가장 가까운 복제본의 번호를 본다
                        inner = f"{new}_in"
                        d["entities"][inner] = {"ports": ports()}
                        d["entities"][new]["aspects"] = {"g": {"parts": [inner], "couplings": [
                            {"from": "i", "to": f"{inner}.i"}, {"from": f"{inner}.o", "to": "o"}]}}
                    elif rng.random() < 0.4:    # 복제본 안의 복제본. 바깥의 번호는 up 으로 묻는다
                        deep = f"{new}_deep"
                        d["entities"][deep] = {"ports": ports()}
                        d["entities"][new]["multi_aspects"] = {"h": {"part": deep, "cardinality": 2}}
        depth = replica_depths(d)
        for name, body in d["entities"].items():
            body.pop("attributes", None)
            if body.get("stereotype") == "void" or name not in depth:
                continue
            often = 0.6 if "extends" in body else 0.4        # 대안이 값을 주어야 바탕의 값을 덮거나 서로 어긋난다
            attrs = {n: rand_value(rng, variables, depth[name]) for n in NAMES if rng.random() < often}
            if depth[name] >= 2 and rng.random() < 0.8:      # 두 겹 안쪽에서는 바깥 복제본의 번호도 묻는다
                attrs["y"] = {"type": "int", "expr": {"call": "nth", "args": [{"replica": "index", "up": 1},
                                                                           {"replica": "index"}]}}
            if attrs:
                body["attributes"] = attrs
        try:
            doc = load_ses_dict(d)
            n = count_variants(unfold(doc, FUNCTIONS).tree)
        except (LoadError, AlgebraError):
            continue
        if 2 <= n <= 150:
            return d, doc


def rand_overrides(rng: random.Random, L: Layered) -> tuple:
    """대상에 맞는 무작위 재정의들. 정의 수준과 구성요소 수준을 섞는다."""
    T = L.ses.tree
    attr = next((x for x in L.extensions if x.name == "attr"), None)
    if attr is None:
        return ()
    spots = sorted(attr.decls)
    out: dict = {}
    for _ in range(rng.choice([1, 2, 3])):
        y = rng.choice(spots)
        ints = sorted(n for n, decl in attr.decls[y].items() if decl.type == "int")
        if not ints:
            continue
        o = (Override(rng.choice(ints), rng.randint(5, 7), at=T.label(y)) if rng.random() < 0.5
             else Override(rng.choice(ints), rng.randint(5, 7), path=component_path(T, y)))
        if not override_problems(L, DecisionSet(set=(o,))):      # 같은 이름의 bool 선언과 만나는 곳은 뺀다
            out[o.key] = o
    return tuple(out.values())


def key(labels, params: dict, clash, kids) -> tuple:
    return (tuple(sorted(labels)), tuple(sorted((n, repr(v)) for n, v in params.items() if n not in clash)),
            tuple(sorted(clash)), tuple(sorted(kids)))


def algebraic(doc, overrides=()) -> tuple:
    """대수의 길: 변이마다 (변수 값, 속성 값을 적은 구조). 포트나 분해를 합칠 수 없는 변이는 뺀다."""
    L = unfold_layered(doc, functions=FUNCTIONS)
    if overrides:
        L = with_overrides(L, DecisionSet(set=tuple(overrides)))
    T = L.ses.tree
    structure, attrs = L.only("devs"), L.only("attr")
    out, clashing = set(), collections.Counter()
    for V in sem(L.ses):
        if any(layer == "core" or code == "M" for layer, code, _, _ in violations(structure, V)):
            continue
        clash: dict = {}
        found = violations(attrs, V)
        for _, code, path, msg in found:
            assert code == "M"
            clash.setdefault(path, set()).add(re.match(r"속성 (\S+) ", msg).group(1))
        tree = interpret(attrs, V)["attr"] if attrs.extensions else None
        clashing["any"] += bool(clash)
        clashing["value"] += any("다른 값" in msg for _, _, _, msg in found)
        clashing["type"] += any("타입" in msg for _, _, _, msg in found)

        def walk(comp, t):
            params = t["params"] if t is not None else {}
            return key(comp.labels, params, clash.get(comp.path, ()),
                       [(k, walk(c, t["children"][k] if t is not None else None)) for k, c in comp.parts.items()])

        out.add((tuple(sorted(assignment(T, V).items())), walk(skeleton(T, L.void, V), tree)))
    return out, clashing


def procedural(doc, overrides=()) -> set:
    """고전 절차: (변수 값, 속성 값을 적은 구조)."""
    given = [("at", o.at, o.attribute, o.value) if o.at is not None else ("path", o.path, o.attribute, o.value)
             for o in overrides]

    def walk(n):
        return key(n["labels"], n["attrs"], n["attr_clash"], [(k, walk(c)) for k, c in n["children"].items()])

    return {(tuple(sorted((k, str(v)) for k, v in sigma.items())), walk(n))
            for sigma, n in classic.enumerate_classic(doc, FUNCTIONS, given)}


@pytest.mark.parametrize("seed", range(300))
def test_classic_procedure_agrees_on_attribute_values(seed):
    """속성 값을 정하는 두 길(펼친 나무와 확장, 위에서 아래로 가는 절차)이 같은 값을 낸다."""
    d, doc = with_values(seed)
    mine, clashing = algebraic(doc)
    theirs = procedural(doc)
    assert mine == theirs
    text = json.dumps(d)
    STATS["docs"] += 1
    STATS["models"] += len(theirs)
    STATS["clashing_variants"] += clashing["any"]
    STATS["value_clash_variants"] += clashing["value"]
    STATS["type_clash_variants"] += clashing["type"]
    STATS["docs_with_value_clash"] += bool(clashing["value"])
    STATS["docs_with_type_clash"] += bool(clashing["type"])
    STATS["docs_with_each"] += '"each"' in text
    STATS["docs_with_variable_values"] += '"expr": {"var"' in text or '"mix"' in text
    STATS["docs_with_replica_numbers"] += '"replica"' in text
    STATS["docs_with_outer_replica_numbers"] += '"up": 1' in text
    STATS["distinct_values"] += len({v for _, tree in theirs for v in re.findall(r"'(\d+)'", repr(tree))})


@pytest.mark.parametrize("seed", range(300))
def test_classic_procedure_agrees_on_overrides(seed):
    """결정 집합의 속성 재정의도 두 길에서 같은 값을 낸다."""
    d, doc = with_values(seed)
    L = unfold_layered(doc, functions=FUNCTIONS)
    overrides = rand_overrides(random.Random(seed + 7), L)
    assert override_problems(L, DecisionSet(set=overrides)) == []
    mine, _ = algebraic(doc, overrides)
    theirs = procedural(doc, overrides)
    assert mine == theirs
    plain = procedural(doc)
    STATS["override_docs"] += bool(overrides)
    STATS["override_changed"] += theirs != plain
    STATS["override_at"] += sum(o.at is not None for o in overrides)
    STATS["override_path"] += sum(o.path is not None for o in overrides)


# ---------------------------------------------------------------------------
# 7. 가지치기 앞뒤에서 값이 같다 (정리 14)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(200))
def test_values_are_the_same_before_and_after_pruning(seed):
    """변이의 속성 값과 적격성은 그 변이가 어느 가지치기된 SES의 변이로 보이든 같다.

    속성의 값이 변수 값에 달려 있어도 그렇다. 변수 값은 변이가 고른 것이기 때문이다.
    """
    d, doc = with_values(seed)
    L = unfold_layered(doc, functions=FUNCTIONS).only("attr")
    if not L.extensions:
        return
    rng = random.Random(seed)
    variants = sem(L.ses)
    before = {V: (violations(L, V), interpret(L, V)) for V in variants}
    ds = DecisionSet()
    points = choice_table(L.ses, L.ses, variable_domains(doc))
    for point in rng.sample(points, min(len(points), rng.choice([1, 1, 2]))):
        options = [o for o, _ in point.options]
        ds = ds.pick(point, *rng.sample(options, rng.randint(1, len(options) - 1)))
    R = apply(L.ses, ds)
    if R is None:
        return
    pruned = Layered(R, L.void, L.extensions)
    kept = sem(R)
    assert set(kept) <= set(variants)
    for V in kept:
        assert (violations(pruned, V), interpret(pruned, V)) == before[V]
    STATS["pruned_docs"] += len(kept) < len(variants)
    STATS["pruned_variants"] += len(kept)


def test_parameter_samples_are_not_vacuous():
    if STATS["docs"] < 300:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["models"] >= 2000 and STATS["clashing_variants"] >= 300, STATS
    assert STATS["docs_with_value_clash"] >= 40 and STATS["docs_with_type_clash"] >= 40, STATS
    assert STATS["docs_with_each"] >= 150 and STATS["docs_with_variable_values"] >= 60, STATS
    assert STATS["docs_with_replica_numbers"] >= 80 and STATS["docs_with_outer_replica_numbers"] >= 20, STATS
    assert STATS["override_docs"] >= 250 and STATS["override_changed"] >= 150, STATS
    assert STATS["override_at"] >= 150 and STATS["override_path"] >= 150, STATS
    assert STATS["pruned_docs"] >= 40 and STATS["pruned_variants"] >= 1000, STATS
