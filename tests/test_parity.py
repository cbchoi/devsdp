"""전통적인 SES가 하던 것 가운데 빠져 있던 것 (docs/ses-platform/18_classic_parity.md).

1. 선택에 대한 제약 (selected). "A를 고르면 B는 안 된다", "전부 없음은 금지".
2. 이름으로 등록한 함수 (call). 규칙과 제약에서 변수의 값을 함수로 판정한다.
3. 우선순위 (priority). 겹친 규칙을 가르고, 대안을 합쳐서 형제가 된 분해 가운데 하나를 고른다.

세 길로 확인한다. 손으로 만든 예, 문헌의 서술을 따라 적은 고전 절차(classic.py)와의
무작위 대조, 그리고 식으로 번역하지 않고 변이에서 직접 평가한 값과의 대조다.
"""

import collections
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import _system_attempt  # noqa: E402
from test_executor import labelled  # noqa: E402

from ses_core import LoadError, classic, load_ses_dict  # noqa: E402
from ses_core.direct import build as build_directly  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core import unfold as U  # noqa: E402
from ses_core import coupling as CP  # noqa: E402
from ses_core.algebra import ASP, AlgebraError, count_variants, holds, is_pes, sem  # noqa: E402
from ses_core.coupling import Coupling  # noqa: E402
from ses_core.decisions import (Choice, DecisionSet, apply, choice_table, component_path, family,  # noqa: E402
                                split_count, witness)
from ses_core.diagnose import analyze  # noqa: E402
from ses_core.extension import Layered, interpret, violations  # noqa: E402
from ses_core.skeleton import GONE, NO_ASPECT, core_psi, core_violations, members, real_aspects, skeleton  # noqa: E402
from ses_core.algebra import prune  # noqa: E402
from ses_core.unfold import pruning_patterns, unfold, unfold_annotated  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform")
STATS: collections.Counter = collections.Counter()


def n_variants(d: dict, functions=None) -> tuple:
    """(대수의 길이 낸 변이 수, 고전 절차가 낸 구조 수)."""
    doc = load_ses_dict(d)
    return len(sem(unfold(doc, functions))), len(classic.enumerate_classic(doc, functions))


# ---------------------------------------------------------------------------
# 1. 선택에 대한 제약
# ---------------------------------------------------------------------------

TWO = {"ses": "1.0", "name": "R",
       "entities": {
           "R": {"root": True, "aspects": {"d": {"parts": ["A", "B"]}}},
           "A": {"specializations": {"speed": {"alternatives": ["Fast", "Slow"]}}},
           "Fast": {"extends": "A"}, "Slow": {"extends": "A"},
           "B": {"specializations": {"size": {"alternatives": ["Big", "Small"]}}},
           "Big": {"extends": "B"}, "Small": {"extends": "B"}}}


def constrained(base: dict, *constraints) -> dict:
    return dict(base, constraints=[dict(c, name=f"c{i}") for i, c in enumerate(constraints)])


def test_a_choice_can_exclude_another_choice():
    """문헌의 선택 제약: A에서 Fast를 고르면 B에서 Big은 안 된다."""
    assert n_variants(TWO) == (4, 4)
    excl = {"when": {"selected": "A/speed=Fast"}, "require": {"not": {"selected": "B/size=Big"}}}
    assert n_variants(constrained(TWO, excl)) == (3, 3)
    same = {"forbid": {"all": [{"selected": "A/speed=Fast"}, {"selected": "B/size=Big"}]}}
    assert n_variants(constrained(TWO, same)) == (3, 3)
    forces = {"when": {"selected": "A/speed=Fast"}, "require": {"selected": "B/size=Small"}}    # 고르면 저것도 골라야 한다
    assert n_variants(constrained(TWO, forces)) == (3, 3)
    both = constrained(TWO, excl, {"when": {"selected": "A/speed=Slow"}, "require": {"selected": "B/size=Big"}})
    assert n_variants(both) == (2, 2)
    never = constrained(TWO, {"forbid": {"any": [{"selected": "A/speed=Fast"}, {"selected": "A/speed=Slow"}]}})
    assert n_variants(never) == (0, 0)
    # 객체로 적어도 같다. path 는 구성요소 한 곳만 가리킨다
    obj = {"when": {"selected": {"at": "A", "specialization": "speed", "alternative": "Fast"}},
           "forbid": {"selected": {"path": ["R", "B"], "specialization": "size", "alternative": "Big"}}}
    assert len(sem(unfold(load_ses_dict(constrained(TWO, obj))))) == 3


OPTIONAL = {"ses": "1.0", "name": "R",
            "entities": {
                "R": {"root": True, "aspects": {"d": {"parts": ["B", "C"]}}},
                "B": {"specializations": {"has": {"alternatives": ["Bs", "NoB"]}}},
                "Bs": {"extends": "B"}, "NoB": {"extends": "B", "stereotype": "void"},
                "C": {"specializations": {"has": {"alternatives": ["Cs", "NoC"]}}},
                "Cs": {"extends": "C"}, "NoC": {"extends": "C", "stereotype": "void"}}}


def test_at_least_one_optional_part_must_stay():
    """문헌의 OR 패턴: 선택적인 부분이 여럿일 때 전부 없음은 금지. 없음을 고른 것도 선택이다."""
    assert n_variants(OPTIONAL) == (4, 4)
    not_all_gone = {"forbid": {"all": [{"selected": "B/has=NoB"}, {"selected": "C/has=NoC"}]}}
    assert n_variants(constrained(OPTIONAL, not_all_gone)) == (3, 3)
    one_stays = {"require": {"any": [{"selected": "B/has=Bs"}, {"selected": "C/has=Cs"}]}}
    assert n_variants(constrained(OPTIONAL, one_stays)) == (3, 3)


NESTED = {"ses": "1.0", "name": "R",
          "entities": {
              "R": {"root": True, "aspects": {"d": {"parts": ["Box", "Lamp"]}}},
              "Box": {"specializations": {"has": {"alternatives": ["Full", "NoBox"]}},
                      "aspects": {"in": {"parts": ["Lamp"]}}},
              "Full": {"extends": "Box"}, "NoBox": {"extends": "Box", "stereotype": "void"},
              "Lamp": {"specializations": {"colour": {"alternatives": ["Red", "Blue"]}}},
              "Red": {"extends": "Lamp"}, "Blue": {"extends": "Lamp"}}}


def test_a_choice_under_a_removed_component_does_not_count():
    """빠진 구성요소 아래에서는 아무것도 고르지 않는다. 그 구성요소는 만들어지지 않기 때문이다.

    고치기 전에는 대수가 빠진 상자 안의 등의 색도 골라 변이가 8개였다(18 문서 5.3절).
    """
    doc = load_ses_dict(NESTED)
    assert len(sem(unfold(doc))) == len(classic.enumerate_classic(doc)) == 6
    no_red = constrained(NESTED, {"forbid": {"selected": "Lamp/colour=Red"}})
    # 남는 구조: 상자가 있고 두 등이 모두 파랑(1), 상자가 없고 바깥 등이 파랑(1)
    assert n_variants(no_red) == (2, 2)
    d = load_ses_dict(no_red)
    S = unfold(d)
    (gone,) = [V for V in sem(S) if ("R", "d", "Box", "has", "NoBox") in V]
    assert ("R", "d", "Lamp", "colour", "Blue") in gone and ("R", "d", "Box", GONE) in gone
    assert not [n for n in gone if n[:4] == ("R", "d", "Box", "in")]       # 빠진 상자의 분해와 그 아래는 고르지 않는다
    # 분해를 고른 것도 살아 있는 구성요소의 것만 센다
    inner = constrained(NESTED, {"require": {"selected": "Box=in"}})
    assert n_variants(inner) == (4, 4)                        # 상자가 있는 넷만 남는다


def test_a_count_of_a_removed_component_does_not_count():
    """개수를 고른 것도 살아 있는 구성요소의 것만 센다. 구성요소가 빠지면 그 multi-aspect 는 만들어지지 않는다."""
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "aspects": {"d": {"parts": ["X"]}}},
                      "X": {"specializations": {"has": {"alternatives": ["WithX", "NoX"]}},
                            "multi_aspects": {"m": {"part": "Y", "cardinality": {"min": 1, "max": 2}}}},
                      "WithX": {"extends": "X"}, "NoX": {"extends": "X", "stereotype": "void"}, "Y": {}}}
    assert n_variants(d) == (3, 3)                            # X 없음 하나, X 가 있고 복제본이 하나와 둘
    two = constrained(d, {"forbid": {"selected": "X/m=2"}})
    assert n_variants(two) == (2, 2)                          # 빠진 X 는 개수를 고르지 않으므로 걸리지 않는다
    must = constrained(d, {"require": {"selected": "X/m=2"}})
    assert n_variants(must) == (1, 1)                         # X 가 있고 복제본이 둘인 것 하나


POOL = {"ses": "1.0", "name": "R",
        "entities": {
            "R": {"root": True, "aspects": {"plain": {"parts": ["W"]}},
                  "multi_aspects": {"pool": {"part": "W", "cardinality": {"min": 1, "max": 3}}}},
            "W": {"specializations": {"kind": {"alternatives": ["Fast", "Slow"]}}},
            "Fast": {"extends": "W"}, "Slow": {"extends": "W"}}}


def test_selected_can_name_a_decomposition_a_count_and_one_replica():
    assert n_variants(POOL) == (2 + 2 + 4 + 8, 16)
    assert n_variants(constrained(POOL, {"require": {"selected": "R=pool"}})) == (14, 14)
    assert n_variants(constrained(POOL, {"require": {"selected": "R=plain"}})) == (2, 2)
    assert n_variants(constrained(POOL, {"require": {"selected": "R/pool=2"}})) == (4, 4)
    assert n_variants(constrained(POOL, {"forbid": {"selected": "R/pool=3"}})) == (8, 8)
    # 정의로 가리키면 "하나라도 그렇게 골랐으면"이다. 개수 2에서 Fast가 하나도 없는 것은 한 가지다
    some_fast = constrained(POOL, {"require": {"selected": "R/pool=2"}}, {"require": {"selected": "W/kind=Fast"}})
    assert n_variants(some_fast) == (3, 3)
    # 복제본 하나만 가리킨다. 고전 절차는 정의마다 한 번 만들기 때문에 이것을 적을 수 없다
    first = constrained(POOL, {"require": {"selected": "R/pool=2"}},
                        {"require": {"selected": {"path": ["R", "W_0"], "specialization": "kind", "alternative": "Fast"}}})
    d = load_ses_dict(first)
    assert len(sem(unfold(d))) == 2
    with pytest.raises(ValueError, match="절차적 의미가 다루지 않는 식"):
        classic.enumerate_classic(d)
    by_object = constrained(POOL, {"require": {"selected": {"at": "R", "multi_aspect": "pool", "count": 2}}},
                            {"require": {"selected": {"at": "R", "aspect": "pool"}}})
    assert n_variants(by_object) == (4, 4)


def test_selected_must_point_at_something():
    with pytest.raises(LoadError, match="selected 는 선택 제약\\(constraints\\)에서만 쓴다"):
        bad = json.loads(json.dumps(TWO))
        bad["entities"]["R"]["aspects"]["d"]["rule"] = {"selected": "A/speed=Fast"}
        load_ses_dict(bad)
    for text, why in [("Nope/speed=Fast", "selected 가 가리키는 정의 Nope 이 없다"),
                      ("A/nope=Fast", "A 에 specialization 이나 multi-aspect nope 이 없다"),
                      ("A/speed=Nope", "A/speed 에 대안 Nope 가 없다"),
                      ("A=nope", "A 에 분해 nope 가 없다")]:
        with pytest.raises(LoadError, match=why):
            load_ses_dict(constrained(TWO, {"require": {"selected": text}}))
    with pytest.raises(LoadError, match="selected: R/pool 의 선택지는 개수"):
        load_ses_dict(constrained(POOL, {"require": {"selected": "R/pool=many"}}))
    for text in ("A/speed", "=Fast", ""):
        with pytest.raises(LoadError, match="selected 는 '정의/이름=선택지' 또는 '정의=분해' 형식"):
            load_ses_dict(constrained(TWO, {"require": {"selected": text}}))
    for obj, why in [({"at": "A", "path": ["R"], "aspect": "d"}, "at 과 path 가운데 정확히 하나"),
                     ({"specialization": "speed", "alternative": "Fast"}, "at 과 path 가운데 정확히 하나"),
                     ({"at": "A"}, "specialization, multi_aspect, aspect 가운데 정확히 하나"),
                     ({"at": "A", "specialization": "speed", "aspect": "d", "alternative": "Fast"}, "가운데 정확히 하나"),
                     ({"at": "A", "specialization": "speed"}, "선택지 하나"),
                     ({"at": "A", "specialization": "speed", "alternative": ["Fast", "Slow"]}, "선택지 하나")]:
        with pytest.raises(LoadError, match=why):
            load_ses_dict(constrained(TWO, {"require": {"selected": obj}}))
    # 경로는 펼친 나무에서 찾는다. 그런 구성요소가 없거나 거기에 그 선택 지점이 없으면 알린다
    for path, spec, why in [(["R", "Nope"], "speed", "selected 가 가리키는 곳이 없다: R/Nope"),
                            (["R", "A"], "size", "selected 가 가리키는 선택지가 구성요소 R/A 에 없다: size=Fast")]:
        d = load_ses_dict(constrained(TWO, {"require": {"selected": {"path": path, "specialization": spec, "alternative": "Fast"}}}))
        with pytest.raises(AlgebraError, match=why):
            unfold(d)
    # 범위 밖의 개수는 참이 될 수 없다
    assert n_variants(constrained(POOL, {"require": {"selected": "R/pool=7"}})) == (0, 0)


# ---------------------------------------------------------------------------
# 2. 이름으로 등록한 함수
# ---------------------------------------------------------------------------

SIZED = {"ses": "1.0", "name": "R",
         "variables": {"n": {"type": "int", "range": [1, 6]}, "k": {"type": "int", "range": [1, 3]}},
         "entities": {
             "R": {"root": True, "aspects": {
                 "small": {"parts": ["A"], "rule": {"call": "fits", "args": [{"var": "n"}, {"var": "k"}]}},
                 "large": {"parts": ["A", "B"], "rule": {"not": {"call": "fits", "args": [{"var": "n"}, {"var": "k"}]}}}}},
             "A": {}, "B": {}}}
FUNCTIONS = {"fits": lambda n, k: n <= 2 * k, "half": lambda n: n // 2, "boom": lambda n: 1 // (n - 3)}


def picked(d: dict, functions=None) -> dict:
    """변수 값에서 뿌리가 고른 분해로."""
    out = {}
    for V in sem(unfold(load_ses_dict(d), functions)):
        sigma = tuple(int(x[2]) for x in sorted(x for x in V if len(x) == 3 and x[1].startswith("$")))
        out[sigma] = [x[1] for x in V if len(x) == 2 and not x[1].startswith("$")]
    return out


def test_a_registered_function_decides_a_rule():
    """규칙의 조건을 함수로 적는다. 문서에는 이름만 남고 본문은 코드에 있다."""
    assert n_variants(SIZED, FUNCTIONS) == (18, 18)
    got = picked(SIZED, FUNCTIONS)                             # 열쇠는 (k, n)
    assert got == {(k, n): (["small"] if n <= 2 * k else ["large"]) for k in (1, 2, 3) for n in range(1, 7)}
    with pytest.raises(AlgebraError, match="등록되지 않은 함수 fits"):
        unfold(load_ses_dict(SIZED))
    with pytest.raises(AlgebraError, match="등록되지 않은 함수 fits"):
        unfold(load_ses_dict(SIZED), {"half": FUNCTIONS["half"]})
    a = analyze(E.from_dict(SIZED))                           # 편집기에서는 예외가 아니라 진단이다
    assert [(d.code, d.severity) for d in a.diagnostics if d.code == "ANALYZE"] == [("ANALYZE", "error")]
    assert "등록되지 않은 함수 fits" in next(d.message for d in a.diagnostics if d.code == "ANALYZE")
    assert not [d for d in analyze(E.from_dict(SIZED), functions=FUNCTIONS).diagnostics if d.severity == "error"]


def test_the_value_of_a_function_and_of_a_variable_can_be_compared():
    half_fits = constrained(SIZED, {"require": {"call": "half", "args": [{"var": "n"}], "le": {"var": "k"}}})
    assert n_variants(half_fits, FUNCTIONS) == (14, 14)
    assert set(picked(half_fits, FUNCTIONS)) == {(k, n) for k in (1, 2, 3) for n in range(1, 7) if n // 2 <= k}
    two_vars = constrained(SIZED, {"require": {"var": "n", "gt": {"var": "k"}}})
    assert set(picked(two_vars, FUNCTIONS)) == {(k, n) for k in (1, 2, 3) for n in range(1, 7) if n > k}
    constant = constrained(SIZED, {"require": {"call": "half", "args": [4], "eq": 2}}, {"forbid": {"call": "half", "args": [1]}})
    assert n_variants(constant, FUNCTIONS) == (18, 18)       # 변수가 없는 조건은 상수다
    assert n_variants(constrained(SIZED, {"require": {"call": "half", "args": [1]}}), FUNCTIONS) == (0, 0)
    member = constrained(SIZED, {"require": {"call": "half", "args": [{"var": "n"}], "in": [1, 3]}})
    assert set(picked(member, FUNCTIONS)) == {(k, n) for k in (1, 2, 3) for n in (2, 3, 6)}
    nested = constrained(SIZED, {"require": {"call": "fits", "args": [{"call": "half", "args": [{"var": "n"}]}, {"var": "k"}]}})
    assert set(picked(nested, FUNCTIONS)) == {(k, n) for k in (1, 2, 3) for n in range(1, 7) if n // 2 <= 2 * k}


def test_a_function_must_answer_for_every_value():
    failing = constrained(SIZED, {"require": {"call": "boom", "args": [{"var": "n"}]}})
    with pytest.raises(AlgebraError, match="함수 boom 가 인자 \\[3\\] 에서 실패했다"):
        unfold(load_ses_dict(failing), FUNCTIONS)
    wide = {"ses": "1.0", "name": "R",
            "variables": {f"v{i}": {"type": "int", "range": [1, 30]} for i in range(3)},
            "entities": {"R": {"root": True}},
            "constraints": [{"name": "c", "require": {"call": "f", "args": [{"var": "v0"}, {"var": "v1"}, {"var": "v2"}]}}]}
    with pytest.raises(AlgebraError, match="조건의 표가 너무 크다. 변수 \\['v0', 'v1', 'v2'\\] 의 값 조합이 27000 가지다"):
        unfold(load_ses_dict(wide), {"f": lambda a, b, c: True})
    assert U.MAX_ROWS == 20000
    with pytest.raises(LoadError, match="정의되지 않은 변수 nope"):
        load_ses_dict(constrained(SIZED, {"require": {"call": "half", "args": [{"var": "nope"}]}}))
    with pytest.raises(LoadError, match="var 비교 연산자가 없다"):
        load_ses_dict(constrained(SIZED, {"require": {"var": "n", "about": 3}}))
    with pytest.raises(AlgebraError, match="견줄 수 없는 값이다: 1 ge \\[0, 3\\]"):
        unfold(load_ses_dict(constrained(SIZED, {"require": {"var": "n", "ge": [0, 3]}})), FUNCTIONS)


def test_new_expression_forms_are_in_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(ROOT, "schema", "ses.schema.json"), encoding="utf-8") as f:
        validator = jsonschema.Draft202012Validator(json.load(f))
    good = [constrained(TWO, {"when": {"selected": "A/speed=Fast"}, "require": {"not": {"selected": "B/size=Big"}}}),
            constrained(TWO, {"forbid": {"selected": {"path": ["R", "B"], "specialization": "size", "alternative": "Big"}}}),
            SIZED,
            constrained(SIZED, {"require": {"call": "half", "args": [{"var": "n"}], "le": {"var": "k"}}}),
            constrained(SIZED, {"require": {"var": "n", "gt": {"var": "k"}}}),
            constrained(SIZED, {"require": {"call": "half", "args": [{"var": "n"}], "in": [1, 3]}})]
    for d in good:
        assert not list(validator.iter_errors(d)), d.get("constraints")
    for bad in ({"var": "n", "about": 3}, {"selected": 3}, {"call": "f", "args": 3}, {"var": "n", "eq": 1, "ne": 2}):
        assert list(validator.iter_errors(constrained(SIZED, {"require": bad}))), bad


# ---------------------------------------------------------------------------
# 3. 우선순위
# ---------------------------------------------------------------------------

def figure12(a_dec, e_dec) -> dict:
    """Deatcu et al. (2019)의 그림 12. a는 aDEC로 b와 c를 가지고, 대안 e는 eDEC로 f와 g를 가진다."""
    def aspect(parts, priority):
        return dict({"parts": parts}, **({} if priority is None else {"priority": priority}))
    return {"ses": "1.0", "name": "a",
            "entities": {
                "a": {"root": True, "aspects": {"aDEC": aspect(["b", "c"], a_dec)},
                      "specializations": {"aSPEC": {"alternatives": ["d", "e"]}}},
                "d": {"extends": "a"},
                "e": {"extends": "a", "aspects": {"eDEC": aspect(["f", "g"], e_dec)}},
                "b": {}, "c": {}, "f": {}, "g": {}}}


def shapes(d: dict, functions=None) -> set:
    """고전 절차가 낸 구조들을 (합쳐진 정의들, 부분들의 이름)으로."""
    return {(tuple(n["labels"]), tuple(sorted(n["children"]))) for _, n in classic.enumerate_classic(load_ses_dict(d), functions)}


def realized(d: dict, functions=None) -> set:
    """대수의 길이 낸 구조들을 같은 꼴로. 핵 적격인 변이만."""
    S, ann = unfold_annotated(load_ses_dict(d), functions)
    out = set()
    for V in sem(S):
        if not core_violations(S.tree, ann.void, V):
            sk = skeleton(S.tree, ann.void, V)
            out.add((tuple(sorted(sk.labels)), tuple(sorted(sk.parts))))
    return out


def test_merged_decompositions_are_decided_by_priority():
    """문헌의 패턴 12. 대안을 고르면 대안의 분해와 바탕의 분해가 형제가 된다. 우선순위가 높은 쪽이 남는다."""
    d_kept = (("a", "d"), ("b", "c"))
    higher_child = figure12(2, 1)                             # 작은 수가 앞선다
    assert shapes(higher_child) == realized(higher_child) == {d_kept, (("a", "e"), ("f", "g"))}
    higher_base = figure12(1, 2)
    assert shapes(higher_base) == realized(higher_base) == {d_kept, (("a", "e"), ("b", "c"))}
    assert shapes(figure12(None, 1)) == realized(figure12(None, 1)) == {d_kept, (("a", "e"), ("f", "g"))}    # 없는 것은 가장 뒤다
    assert shapes(figure12(None, 100)) == realized(figure12(None, 100)) == {d_kept, (("a", "e"), ("f", "g"))}  # 어떤 수든 없는 것을 누른다
    assert shapes(figure12(0, None)) == realized(figure12(0, None)) == {d_kept, (("a", "e"), ("b", "c"))}      # 0도 수다
    assert shapes(figure12(-1, 0)) == realized(figure12(-1, 0)) == {d_kept, (("a", "e"), ("b", "c"))}
    for tie in (figure12(None, None), figure12(1, 1)):       # 가를 수 없으면 합칠 수 없다
        assert shapes(tie) == realized(tie) == {d_kept}
        S, ann = unfold_annotated(load_ses_dict(tie))
        assert len(sem(S)) == 2
        assert sorted(len(core_violations(S.tree, ann.void, V)) for V in sem(S)) == [0, 1]
        # 분해를 정할 수 없는 병합체는 분해를 하나도 고르지 않는다. 두 구성원이 모두 "분해 없음"을 고르고 그 아래는 없다
        stuck = next(V for V in sem(S) if ("a", "aSPEC", "e") in V)
        assert stuck == {("a",), ("a", NO_ASPECT), ("a", "aSPEC"), ("a", "aSPEC", "e"), ("a", "aSPEC", "e", NO_ASPECT)}
        assert [msg for _, _, msg in core_violations(S.tree, ann.void, stuck)] == ["분해를 하나로 정할 수 없다"]
    # 밀린 쪽은 "분해 없음"을 고른다. 그 아래의 선택을 따로 세지 않으므로 변이는 구조마다 하나다
    S, ann = unfold_annotated(load_ses_dict(higher_child))
    assert len(sem(S)) == 2 and all(not core_violations(S.tree, ann.void, V) for V in sem(S))
    e_variant = next(V for V in sem(S) if ("a", "aSPEC", "e") in V)
    assert ("a", NO_ASPECT) in e_variant and ("a", "aDEC") not in e_variant and ("a", "aSPEC", "e", "eDEC") in e_variant
    # 표시는 넉넉하게 만든다. 함께 골라질 수 있는 구성원이 분해를 가지면 둘 다 받는다. 실제로 고르는지는 제약식이 정한다
    assert ("a", "aSPEC", "e", NO_ASPECT) in S.tree.nodes and not any(("a", "aSPEC", "e", NO_ASPECT) in V for V in sem(S))


OVERLAP = {"ses": "1.0", "name": "R",
           "variables": {"v": {"type": "enum", "values": ["a", "b", "c"]}},
           "entities": {
               "R": {"root": True, "aspects": {
                   "d1": {"parts": ["A"], "rule": {"var": "v", "eq": "a"}},
                   "d2": {"parts": ["B"], "rule": {"var": "v", "in": ["a", "b"]}}}},
               "A": {}, "B": {}}}


def with_priorities(d: dict, **priorities) -> dict:
    d = json.loads(json.dumps(d))
    for name, p in priorities.items():
        for body in d["entities"].values():
            for kind in ("aspects", "multi_aspects"):
                if name in (body.get(kind) or {}):
                    body[kind][name]["priority"] = p
    return d


def by_variable(d: dict, functions=None) -> dict:
    """변수 v의 값에서 뿌리가 가질 수 있는 분해들로 (대수 쪽). 분해를 정할 수 없으면 None 이다."""
    S, ann = unfold_annotated(load_ses_dict(d), functions)
    out: dict = {}
    for V in sem(S):
        v = next(x[2] for x in V if len(x) == 3 and x[1] == "$v")
        sk = skeleton(S.tree, ann.void, V)
        assert sk.stuck == (sk.aspect is None) == bool(core_violations(S.tree, ann.void, V))
        out.setdefault(v, set()).add(None if sk.stuck else family(sk.aspect[-1]))
    return out


def test_overlapping_rules_are_decided_by_priority():
    """한 엔티티의 두 분해 규칙이 함께 참이면 우선순위가 높은 것이 적용된다 (09 문서의 결함 1.2)."""
    # v가 a이면 두 규칙이 다툰다. 그 변수 값은 사라지지 않고, 분해를 정할 수 없는 부적격 변이 하나로 남는다
    assert by_variable(OVERLAP) == {"a": {None}, "b": {"d2"}, "c": {"d1", "d2"}}
    assert n_variants(OVERLAP) == (4, 3)
    first = with_priorities(OVERLAP, d1=1, d2=2)
    assert by_variable(first) == {"a": {"d1"}, "b": {"d2"}, "c": {"d1", "d2"}} and n_variants(first) == (4, 4)
    second = with_priorities(OVERLAP, d1=2, d2=1)
    assert by_variable(second) == {"a": {"d2"}, "b": {"d2"}, "c": {"d1", "d2"}} and n_variants(second) == (4, 4)
    assert by_variable(with_priorities(OVERLAP, d1=1)) == by_variable(first)    # 없는 것은 가장 뒤다
    for tie in (with_priorities(OVERLAP, d1=3, d2=3), with_priorities(OVERLAP, d2=None)):
        assert by_variable(tie) == by_variable(OVERLAP) and n_variants(tie) == (4, 3)


POOLS = {"ses": "1.0", "name": "R",
         "variables": {"v": {"type": "int", "range": [1, 3]}},
         "entities": {
             "R": {"root": True, "aspects": {"one": {"parts": ["W"]}},
                   "multi_aspects": {"few": {"part": "W", "cardinality": {"min": 1, "max": 2}, "rule": {"var": "v", "eq": 1}},
                                     "many": {"part": "W", "cardinality": 3, "rule": {"var": "v", "le": 2}}}},
             "W": {}}}


def test_rules_of_multi_aspects_are_applied():
    """문헌의 패턴 6과 7. multi-aspect 형제도 규칙으로 고른다. 고치기 전에는 multi-aspect의 규칙을 읽지 않았다."""
    assert by_variable(POOLS) == {"1": {None}, "2": {"many"}, "3": {"one", "few", "many"}}
    assert n_variants(POOLS) == (1 + 1 + 4, 5)                # v가 1이면 두 규칙이 다툰다. 부적격 변이 하나다
    assert by_variable(with_priorities(POOLS, few=5)) == {"1": {"few"}, "2": {"many"}, "3": {"one", "few", "many"}}
    assert n_variants(with_priorities(POOLS, few=5)) == (2 + 1 + 4, 7)
    assert by_variable(with_priorities(POOLS, many=5))["1"] == {"many"}


def chain(*priorities) -> dict:
    """바탕 X와, 대안 Y와, 대안의 대안 Z가 각자 분해를 가진다. 인자는 세 분해의 우선순위다."""
    px, py, pz = priorities

    def aspect(part, p):
        return dict({"parts": [part]}, **({} if p is None else {"priority": p}))
    return {"ses": "1.0", "name": "X",
            "entities": {
                "X": {"root": True, "aspects": {"ax": aspect("P", px)}, "specializations": {"s": {"alternatives": ["Y", "Y0"]}}},
                "Y0": {"extends": "X"},
                "Y": {"extends": "X", "aspects": {"ay": aspect("Q", py)}, "specializations": {"t": {"alternatives": ["Z", "Z0"]}}},
                "Z0": {"extends": "Y"},
                "Z": {"extends": "Y", "aspects": {"az": aspect("R", pz)}},
                "P": {}, "Q": {}, "R": {}}}


def test_three_members_with_decompositions():
    def got(d):
        both_ways = shapes(d)
        assert both_ways == realized(d)
        return {labels[-1]: parts for labels, parts in both_ways}          # 가장 깊이 고른 대안에서 부분으로

    assert got(chain(3, 2, 1)) == {"Y0": ("P",), "Z0": ("Q",), "Z": ("R",)}
    assert got(chain(1, 2, 3)) == {"Y0": ("P",), "Z0": ("P",), "Z": ("P",)}
    assert got(chain(3, 1, 2)) == {"Y0": ("P",), "Z0": ("Q",), "Z": ("Q",)}
    assert got(chain(2, 2, 1)) == {"Y0": ("P",), "Z": ("R",)}              # X와 Y는 가를 수 없지만 Z가 둘 다 누른다
    assert got(chain(1, 1, 3)) == {"Y0": ("P",)}                           # 가장 앞선 둘이 같으면 합칠 수 없다
    assert got(chain(None, None, None)) == {"Y0": ("P",)}


FREE = {"ses": "1.0", "name": "X",
        "entities": {
            "X": {"root": True, "aspects": {"hi": {"parts": ["P"], "priority": 1}, "lo": {"parts": ["Q"], "priority": 5}},
                  "specializations": {"s": {"alternatives": ["Y", "Y0"]}}},
            "Y0": {"extends": "X"},
            "Y": {"extends": "X", "aspects": {"mid": {"parts": ["R"], "priority": 3}}},
            "P": {}, "Q": {}, "R": {}}}


def test_alternatives_of_one_specialization_do_not_compete():
    """한 specialization 의 두 대안은 함께 골라지지 않는다. 둘 다 분해를 가지고 우선순위가 달라도 다툼이 아니다.
    밀려났다는 표시를 만들지 않고, 변이는 대안마다 그 대안의 분해다."""
    d = {"ses": "1.0", "name": "X",
         "entities": {"X": {"root": True, "specializations": {"s": {"alternatives": ["A", "B"]}}},
                      "A": {"extends": "X", "aspects": {"da": {"parts": ["P"], "priority": 1}}},
                      "B": {"extends": "X", "aspects": {"db": {"parts": ["Q"], "priority": 2}}},
                      "P": {}, "Q": {}}}
    S, ann = unfold_annotated(load_ses_dict(d))
    assert not [n for n in S.tree.nodes if n[-1] == NO_ASPECT]
    assert shapes(d) == realized(d) == {(("A", "X"), ("P",)), (("B", "X"), ("Q",))}


def test_alternatives_of_two_specializations_compete():
    """한 엔티티의 서로 다른 specialization 에서 고른 두 대안은 함께 골라진다. 둘 다 분해를 가지면 다툰다."""
    d = {"ses": "1.0", "name": "X",
         "entities": {"X": {"root": True, "specializations": {"s": {"alternatives": ["A", "A0"]},
                                                              "t": {"alternatives": ["C", "C0"]}}},
                      "A": {"extends": "X", "aspects": {"da": {"parts": ["P"], "priority": 1}}},
                      "C": {"extends": "X", "aspects": {"dc": {"parts": ["Q"], "priority": 2}}},
                      "A0": {"extends": "X"}, "C0": {"extends": "X"}, "P": {}, "Q": {}}}
    expected = {(("A", "C", "X"), ("P",)), (("A", "C0", "X"), ("P",)), (("A0", "C", "X"), ("Q",)), (("A0", "C0", "X"), ())}
    assert shapes(d) == realized(d) == expected
    S, ann = unfold_annotated(load_ses_dict(d))
    marks = [n for n in S.tree.nodes if n[-1] == NO_ASPECT]
    assert sorted(marks) == [("X", "s", "A", NO_ASPECT), ("X", "t", "C", NO_ASPECT)]      # 함께 골라질 수 있는 둘이 모두 받는다
    assert {m for V in sem(S) for m in marks if m in V} == {("X", "t", "C", NO_ASPECT)}    # 고르는 것은 밀리는 쪽뿐이다


def test_a_member_is_pushed_out_only_by_what_it_could_have_chosen():
    """바탕이 높은 분해와 낮은 분해를 가지고 대안이 그 사이의 분해를 가진다.

    바탕이 높은 것을 고르면 바탕이 이기고, 낮은 것을 고르면 대안이 이긴다. 규칙이 높은 것을 강제하면
    바탕은 밀려날 수 없다.
    """
    assert shapes(FREE) == realized(FREE) == {(("X", "Y0"), ("P",)), (("X", "Y0"), ("Q",)), (("X", "Y"), ("P",)), (("X", "Y"), ("R",))}
    forced = json.loads(json.dumps(FREE))
    forced["variables"] = {"v": {"type": "int", "range": [1, 2]}}
    forced["entities"]["X"]["aspects"]["hi"]["rule"] = {"var": "v", "eq": 1}
    got = {}
    for sigma, n in classic.enumerate_classic(load_ses_dict(forced)):
        got.setdefault(sigma["v"], set()).add((n["labels"][-1], tuple(n["children"])))
    assert got == {1: {("Y0", ("P",)), ("Y", ("P",))},                     # 규칙이 hi를 강제한다. 대안의 mid는 밀린다
                   2: {("Y0", ("P",)), ("Y0", ("Q",)), ("Y", ("P",)), ("Y", ("R",))}}
    S, ann = unfold_annotated(load_ses_dict(forced))
    assert len(sem(S)) == 6 and all(not core_violations(S.tree, ann.void, V) for V in sem(S))


def test_decisions_and_diagnostics_know_the_pushed_out_marker():
    """밀려났다는 표시는 사람이 고르는 선택지가 아니다. 결정은 구성요소의 분해를 고르고, 표시는 따라 정해진다."""
    S, ann = unfold_annotated(load_ses_dict(FREE))
    assert {n for n in S.tree.nodes if n[-1] == NO_ASPECT} == {("X", NO_ASPECT), ("X", "s", "Y", NO_ASPECT)}
    table = choice_table(S, S)
    assert all(NO_ASPECT not in dict(p.options) for p in table)
    assert [(p.owner, p.kind, [o for o, _ in p.options]) for p in table] == [("X", "aspect", ["hi", "lo"]), ("X", "alternative", ["Y", "Y0"])]
    # 구성요소 경로로 분해를 고르면 그 분해를 가진 구성원이 이기고 나머지는 밀린다
    mid = apply(S, DecisionSet(choose=(Choice(path=("X",), aspect=("mid",)),)))
    assert is_pes(mid) and ("X", NO_ASPECT) in mid.tree.nodes and ("X", "s", "Y", "mid") in mid.tree.nodes
    hi = apply(S, DecisionSet(choose=(Choice(path=("X",), aspect=("hi",)),)))
    assert len(sem(hi)) == 2 and all(("X", "hi") in V for V in sem(hi))
    assert apply(S, DecisionSet(choose=(Choice(path=("X",), aspect=("hi", "mid")),))) is not None
    # 변이마다 그것을 정확히 재현하는 결정 집합이 있다
    for V in sem(S):
        w = witness(S.tree, V)
        R = apply(S, w)
        assert R is not None and sem(R) == [V], w.to_dict()
    # 늘 밀리는 분해는 죽은 선택지로 진단된다
    never = with_priorities(FREE, lo=9, hi=8, mid=1)
    never["entities"].pop("Y0")
    never["entities"]["X"]["specializations"]["s"]["alternatives"] = ["Y", "Y1"]
    never["entities"]["Y1"] = {"extends": "X", "aspects": {"other": {"parts": ["R"], "priority": 2}}}
    a = analyze(E.from_dict(never))
    dead = sorted(d.data["option"] for d in a.diagnostics if d.code == "DEAD")
    assert dead == ["hi", "lo"] and not [d for d in a.diagnostics if d.severity == "error"]
    assert all(NO_ASPECT not in d.message for d in a.diagnostics)


# ---------------------------------------------------------------------------
# 없음이 된 구성요소의 규칙 (무작위 대조가 찾아낸 결함의 회귀 시험)
# ---------------------------------------------------------------------------

REMOVED = {"ses": "1.0", "name": "R",
           "variables": {"v": {"type": "int", "range": [1, 3]}},
           "entities": {
               "R": {"root": True, "aspects": {"d": {"parts": ["X"]}}},
               "X": {"specializations": {"has": {"alternatives": ["Xs", "NoX"]}},
                     "aspects": {"a": {"parts": ["P"], "rule": {"var": "v", "eq": 1}},
                                 "b": {"parts": ["Q"], "rule": {"var": "v", "le": 2}}}},
               "Xs": {"extends": "X"}, "NoX": {"extends": "X", "stereotype": "void"},
               "P": {}, "Q": {}}}


def test_the_removal_marker_goes_only_to_members_that_can_be_removed_with_it():
    """빠짐 표시는 분해를 가진 구성원 가운데 없음 대안과 함께 골라질 수 있는 것에만 붙는다(18 문서 5.3절).

    Big 은 NoX 와 같은 specialization 의 다른 대안이라 함께 골라지지 않는다. 바탕 X 와 다른 specialization 의
    대안 Warm 은 함께 골라진다.
    """
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "aspects": {"d": {"parts": ["X"]}}},
                      "X": {"specializations": {"has": {"alternatives": ["NoX", "Big"]},
                                                "tone": {"alternatives": ["Warm", "Cold"]}},
                            "aspects": {"a": {"parts": ["P"], "priority": 3}}},
                      "NoX": {"extends": "X", "stereotype": "void"},
                      "Big": {"extends": "X", "aspects": {"big": {"parts": ["P"], "priority": 1}}},
                      "Warm": {"extends": "X", "aspects": {"w": {"parts": ["Q"], "priority": 2}}},
                      "Cold": {"extends": "X"}, "P": {}, "Q": {}}}
    S, ann = unfold_annotated(load_ses_dict(d))
    gone = sorted(n for n in S.tree.nodes if n[-1] == GONE)
    assert gone == [("R", "d", "X", GONE), ("R", "d", "X", "tone", "Warm", GONE)]
    assert shapes(d) == realized(d)
    assert len(sem(S)) == len(classic.enumerate_classic(load_ses_dict(d))) == 4     # 빠진 X 둘(온기 둘), Big 둘
    decompositions = [a for a in S.tree.kinds if S.tree.kind(a) == ASP and a[-1] not in (GONE, NO_ASPECT)
                      and a[:3] == ("R", "d", "X")]
    for V in sem(S):
        removed = ("R", "d", "X", "has", "NoX") in V
        assert (("R", "d", "X", GONE) in V) == removed
        assert len([a for a in decompositions if a in V]) == (0 if removed else 1)   # 빠지면 분해가 없고, 있으면 하나다


def test_a_decision_on_the_decomposition_of_a_removable_component_keeps_its_absence():
    """분해에 대한 결정은 "구성요소가 있으면 이 분해"다. 빠진 변이를 지우지 않는다. 접힌 가지치기 SES도 같다."""
    doc = load_ses_dict(NESTED)
    S = unfold(doc)
    keep_in = DecisionSet(choose=(Choice(at="Box", aspect=("in",)),))
    assert len(sem(apply(S, keep_in))) == len(sem(S)) == 6
    folded = {"ses": "1.0", "name": "R",
              "entities": {"R": {"root": True}, "Box": {"aspects": {"in": {"parts": ["Lamp"]}}}, "Lamp": {}}}
    assert len(sem(prune(S, *pruning_patterns(load_ses_dict(folded))))) == 6
    gone = DecisionSet(choose=(Choice(at="Box", aspect=("in",)), Choice(at="Box", specialization="has", alternative=("NoBox",)),
                               Choice(at="Lamp", specialization="colour", alternative=("Blue",))))
    b = build_directly(doc, gone)
    assert sem(apply(S, gone)) == [b.variant] and b.unused == (gone.choose[0].key,)


def test_a_witness_does_not_write_what_the_marker_clauses_decide():
    """변이를 재현하는 결정 집합은 빠짐을 적지 않고, 빠짐 말고는 분해가 하나뿐인 엔티티의 분해도 적지 않는다.
    상자의 분해는 in 하나다. 증거는 고른 대안만 적는다."""
    S = unfold(load_ses_dict(NESTED))
    for V in sem(S):
        w = witness(S.tree, V)
        assert sem(apply(S, w)) == [V]
        assert all(c.kind == "specialization" for c in w.choose), w.to_dict()


def test_markers_are_not_options_in_the_table_or_the_diagnostics():
    """빠짐과 밀림은 사람이 고르는 선택지가 아니다. 늘 빠지는 구성요소의 분해는 죽은 선택지로 알리지 않는다.
    원인은 그 구성요소를 빠지게 한 대안 선택이고, 그것만 알린다."""
    d = json.loads(json.dumps(NESTED))
    d["entities"]["Box"]["aspects"]["out"] = {"parts": ["Lamp"]}                 # 상자의 분해가 둘이면 선택 지점이 된다
    S = unfold(load_ses_dict(d))
    table = choice_table(S, S)
    assert ("Box", "aspect", "") in {(p.owner, p.kind, p.group) for p in table}
    assert all(o not in (GONE, NO_ASPECT) for p in table for o, _ in p.options)
    always_gone = constrained(d, {"require": {"selected": "Box/has=NoBox"}})
    a = analyze(E.from_dict(always_gone))
    dead = sorted((x.data["owner"], x.data["option"]) for x in a.diagnostics if x.code == "DEAD")
    assert dead == [("Box", "Full")] and not a.errors


def test_rules_of_a_removed_component_do_not_remove_variants():
    """분해의 규칙은 살아 있는 구성요소에서만 적용된다.

    v가 1이면 X의 두 규칙이 함께 참이라 X가 있는 구조는 만들 수 없다. 그러나 X가 없음이면 그 규칙은
    평가할 일이 없으므로 X가 빠진 구조는 남아야 한다. 고치기 전에는 대수 쪽이 v가 1인 변이를 모두 지웠다.
    """
    doc = load_ses_dict(REMOVED)
    by_value = collections.Counter(sigma["v"] for sigma, _ in classic.enumerate_classic(doc))
    assert by_value == {1: 1, 2: 2, 3: 3}                     # 값마다: X 없음 하나, 그리고 규칙이 허락하는 분해들
    S, ann = unfold_annotated(doc)
    alive = collections.Counter()
    for V in sem(S):
        v = next(int(x[2]) for x in V if len(x) == 3 and x[1] == "$v")
        alive[(v, skeleton(S.tree, ann.void, V).parts.keys() == {"X"})] += 1
    # 빠진 X 는 분해를 고르지 않으므로 X 없음이 값마다 하나다. v가 1이고 X가 있으면 분해를 정할 수 없는 부적격 변이 하나다
    assert alive == {(1, False): 1, (1, True): 1, (2, False): 1, (2, True): 1, (3, False): 1, (3, True): 2}
    algebraic, procedural, skipped = both(doc, None)
    assert algebraic == procedural and len(procedural) == 6 and skipped == 1


# ---------------------------------------------------------------------------
# 무작위 대조
# ---------------------------------------------------------------------------

def table(seed: int, arity: int):
    """인자에서 참과 거짓으로 가는, 씨앗으로 정해진 함수."""
    return lambda *args: random.Random(f"{seed}:{arity}:{args}").random() < 0.6


def score(seed: int):
    return lambda *args: random.Random(f"s{seed}:{args}").randint(0, 3)


def choice_points(d: dict) -> list:
    """문서에서 selected 로 가리킬 수 있는 것들을 글자로."""
    out = []
    for name, body in d["entities"].items():
        for sp, spec in (body.get("specializations") or {}).items():
            out += [f"{name}/{sp}={alt}" for alt in spec["alternatives"]]
        out += [f"{name}={a}" for a in list(body.get("aspects") or {}) + list(body.get("multi_aspects") or {})]
        for ma, m in (body.get("multi_aspects") or {}).items():
            c = m["cardinality"]
            counts = [c] if isinstance(c, int) else [1, 2, 3] if "var" in c else list(range(c["min"], c["max"] + 1))
            out += [f"{name}/{ma}={n}" for n in counts]
    return out


def rand_condition(rng: random.Random, d: dict, functions: dict, selections: bool, depth: int = 2) -> dict:
    variables = list(d.get("variables") or {})
    points = choice_points(d) if selections else []
    kinds = (["sel"] * 3 if points else []) + (["cmp", "call", "call", "two", "value"] if variables else []) + \
        (["all", "any", "not"] if depth > 0 else [])
    if not kinds:
        return {"all": []}
    k = rng.choice(kinds)
    if k == "sel":
        return {"selected": rng.choice(points)}
    if k == "cmp":
        return {"var": rng.choice(variables), rng.choice(["eq", "ne", "ge", "lt"]): rng.randint(1, 3)}
    if k == "two":
        return {"var": rng.choice(variables), rng.choice(["eq", "lt", "ge"]): {"var": rng.choice(variables)}}
    if k in ("call", "value"):
        args = [{"var": rng.choice(variables)} if rng.random() < 0.8 else rng.randint(0, 2) for _ in range(rng.randint(1, 2))]
        name = f"f{len(functions)}"
        if k == "call":
            functions[name] = table(rng.randint(0, 10 ** 6), len(args))
            return {"call": name, "args": args}
        functions[name] = score(rng.randint(0, 10 ** 6))
        op = rng.choice(["eq", "ge", "lt", "in"])
        return {"call": name, "args": args, op: [0, 3] if op == "in" else rng.choice([1, 2])}
    if k == "not":
        return {"not": rand_condition(rng, d, functions, selections, depth - 1)}
    return {k: [rand_condition(rng, d, functions, selections, depth - 1) for _ in range(rng.randint(1, 3))]}


def decorated(seed: int) -> tuple:
    """무작위 문서에 함수를 쓰는 규칙과, 선택과 함수를 쓰는 제약을 더한다. (문서, 함수들)"""
    rng = random.Random(seed)
    while True:
        d = _system_attempt(rng)
        functions: dict = {}
        for body in d["entities"].values():
            aspects = body.get("aspects") or {}
            if len(aspects) > 1 or (aspects and body.get("multi_aspects")):
                for a in aspects.values():
                    if rng.random() < 0.6 and d.get("variables"):
                        a["rule"] = rand_condition(rng, d, functions, False, 1)
            for spec in (body.get("specializations") or {}).values():
                if "select" not in spec and len(spec["alternatives"]) == 2 and d.get("variables") and rng.random() < 0.3:
                    spec["select"] = {"when": rand_condition(rng, d, functions, False, 1),
                                      "then": spec["alternatives"][0], "else": spec["alternatives"][1]}
        constraints = []
        for i in range(rng.choice([1, 1, 2, 3])):
            c = {"name": f"c{i}"}
            for key in rng.choice([("require",), ("forbid",), ("when", "require"), ("when", "forbid"), ("when", "require", "forbid")]):
                c[key] = rand_condition(rng, d, functions, True)
            constraints.append(c)
        d["constraints"] = constraints
        try:
            doc = load_ses_dict(d)
            n = count_variants(unfold(doc, functions).tree)
        except (LoadError, AlgebraError):
            continue
        if 2 <= n <= 150:
            return d, doc, functions


def both(doc, functions) -> tuple:
    """대수의 길과 고전 절차가 내는 (변수 값, 구조)의 집합. test_executor.both_semantics 에 함수를 더한 것이다."""
    S, ann = unfold_annotated(doc, functions)
    L = Layered(S, ann.void, (Coupling(ann.ports, ann.coup),))
    core = Layered(S, ann.void)
    algebraic, skipped = set(), 0
    for V in sem(S):
        if violations(core, V) or any(code == "M" for _, code, _, _ in violations(L, V)):
            skipped += 1
            continue
        sigma = tuple(sorted((n[1][1:], n[2]) for n in V if len(n) == 3 and n[1].startswith("$")))
        sk = skeleton(S.tree, ann.void, V)

        def attach(n, comp):
            return dict(n, labels=list(comp.labels),
                        children={k: attach(c, comp.parts[k]) for k, c in n["children"].items()})

        algebraic.add((sigma, labelled(attach(interpret(L, V)["devs"], sk), lambda n: n["labels"])))
    procedural = {(tuple(sorted((k, str(v)) for k, v in sigma.items())), labelled(n, lambda n: n["labels"]))
                  for sigma, n in classic.enumerate_classic(doc, functions)}
    return algebraic, procedural, skipped


@pytest.mark.parametrize("seed", range(300))
def test_classic_procedure_agrees_on_selection_constraints_and_functions(seed):
    """선택 제약과 함수를 쓴 무작위 문서에서, 고전 절차와 대수의 길이 같은 모델들을 낸다."""
    d, doc, functions = decorated(seed)
    algebraic, procedural, skipped = both(doc, functions)
    assert algebraic == procedural
    free = dict(d, constraints=[])
    before = len(both(load_ses_dict(free), functions)[1])
    STATS["models"] += len(procedural)
    STATS["cut_by_constraints"] += before - len(procedural)
    STATS["docs_cut"] += before > len(procedural) > 0
    STATS["docs_with_functions"] += bool(functions)
    STATS["docs_empty"] += not procedural


def prioritized(seed: int) -> tuple:
    """무작위 문서에 우선순위를 더한다. 대안에 분해를 더 주어 병합으로 형제가 되는 분해가 자주 생기게 하고,
    aspect와 multi-aspect에 규칙을 준다. (문서, 적재한 문서, 함수들)"""
    rng = random.Random(seed)
    while True:
        d = _system_attempt(rng)
        functions: dict = {}
        ents = d["entities"]
        order = [n for n in ents if "extends" not in ents[n]]
        for name, body in list(ents.items()):
            base = name.split("_")[0]
            later = order[order.index(base) + 1:] if base in order else []
            if "extends" in body and body.get("stereotype") != "void" and later and rng.random() < 0.5:
                if rng.random() < 0.7:                       # 대안이 자기 분해를 가진다
                    part = rng.choice(later)
                    body.setdefault("aspects", {})[f"p{len(body.get('aspects') or {})}"] = {
                        "parts": [part], "couplings": [{"from": "i", "to": f"{part}.i"}, {"from": f"{part}.o", "to": "o"}]}
                else:
                    body.setdefault("multi_aspects", {})["q0"] = {"part": rng.choice(later), "cardinality": rng.choice([1, 2])}
        for body in ents.values():
            fams = list((body.get("aspects") or {}).values()) + list((body.get("multi_aspects") or {}).values())
            for a in fams:
                if rng.random() < 0.7:
                    a["priority"] = rng.randint(1, 3)
                if len(fams) > 1 and d.get("variables") and rng.random() < 0.5:
                    a["rule"] = rand_condition(rng, d, functions, False, 1)
        constraints = []
        for i in range(rng.choice([0, 0, 1, 2])):
            c = {"name": f"c{i}"}
            for key in rng.choice([("require",), ("forbid",), ("when", "require"), ("when", "forbid")]):
                c[key] = rand_condition(rng, d, functions, True)
            constraints.append(c)
        if constraints:
            d["constraints"] = constraints
        try:
            doc = load_ses_dict(d)
            n = count_variants(unfold(doc, functions).tree)
        except (LoadError, AlgebraError):
            continue
        if 2 <= n <= 300:
            return d, doc, functions


@pytest.mark.parametrize("seed", range(300))
def test_classic_procedure_agrees_on_priorities(seed):
    """우선순위와 규칙을 가진 무작위 문서에서, 고전 절차와 대수의 길이 같은 모델들을 낸다.

    특성식도 함께 본다. 밀려났다는 표시가 든 나무에서도, 정의를 그대로 평가한 적격성과 특성식의 값이 같다.
    """
    d, doc, functions = prioritized(seed)
    algebraic, procedural, skipped = both(doc, functions)
    assert algebraic == procedural
    S, ann = unfold_annotated(doc, functions)
    T = S.tree
    marked = {n for n in T.nodes if n[-1] == NO_ASPECT}
    psi, kpsi = CP.psi(T, ann), core_psi(T, ann.void)
    variants = sem(S)
    for V in variants:
        assert (not CP.violations(T, ann, V)) == holds(psi, V)
        assert (not core_violations(T, ann.void, V)) == holds(kpsi, V)
        STATS["prio_pushed_variants"] += bool(marked & V)
        STATS["prio_unmergeable"] += any(code == "K1" for code, _, _ in core_violations(T, ann.void, V))
    for V in variants[:6]:                                   # 변이를 정확히 재현하는 결정 집합이 있다
        R = apply(S, witness(T, V))
        assert R is not None and sem(R) == [V]
    plain = json.loads(json.dumps(d))
    for body in plain["entities"].values():
        for a in list((body.get("aspects") or {}).values()) + list((body.get("multi_aspects") or {}).values()):
            a.pop("priority", None)
    STATS["prio_models"] += len(procedural)
    STATS["prio_docs_marked"] += bool(marked)
    STATS["prio_docs_changed"] += both(load_ses_dict(plain), functions)[1] != procedural
    STATS["prio_variants"] += len(variants)


def made_choices(T, void, V) -> set:
    """변이에서 실제로 한 선택들을 식을 거치지 않고 읽는다.

    뿌리에서 내려가며, 놓일 자리가 살아 있는 구성요소마다 고른 대안을 적고, 없음이 아니면 고른 분해를
    적고 그 부분들로 내려간다. 원소는 (종류, 정의, 이름, 선택지, 구성요소 경로)다.
    """
    out: set = set()

    def visit(e):
        ms = [y for y in members(T, e) if y in V]
        where = component_path(T, e)
        for y in ms:
            for s in T.specs(y):
                if len(s) == 2 and s[-1].startswith("$"):
                    continue
                out.update(("spec", T.label(y), s[-1], x[-1], where) for x in T.children(s) if x in V)
        if any(y in void for y in ms):
            return
        for y in ms:
            for a in T.aspects(y):
                if a in V:
                    name, n = split_count(a[-1])
                    out.add(("aspect", T.label(y), "", name, where))
                    if n is not None:
                        out.add(("count", T.label(y), name, n, where))
                    for q in T.children(a):
                        visit(q)

    visit(T.root)
    return out


def direct(e, env: dict, functions: dict, made: set, doc) -> bool:
    """제약의 식을 변이 하나에서 직접 평가한다."""
    if isinstance(e, U.m.And):
        return all(direct(x, env, functions, made, doc) for x in e.items)
    if isinstance(e, U.m.Or):
        return any(direct(x, env, functions, made, doc) for x in e.items)
    if isinstance(e, U.m.Not):
        return not direct(e.item, env, functions, made, doc)
    if isinstance(e, U.m.Selected):
        if e.path is None:
            def_name, _, group = e.node.partition("/")
            choice = e.choice
            if group and group in doc.entities[def_name].multi_aspects:
                choice = int(choice)
            return any(k[1] == def_name and k[2] == group and k[3] == choice for k in made)
        return any(k[2] == e.node and str(k[3]) == str(e.choice) and k[4] == tuple(e.path) for k in made)
    return bool(U.evaluate(e, env, functions))


def with_paths(rng: random.Random, d: dict, doc, functions) -> dict:
    """제약 가운데 일부를 구성요소 경로로 한 곳만 가리키는 것으로 바꾼다."""
    T = unfold(load_ses_dict(dict(d, constraints=[])), functions).tree
    spots = []
    for q in T.kinds:                                  # 문서에 적힌 순서. 집합의 순서는 실행마다 다르다
        if T.kind(q) == ASP:
            continue
        for s in T.specs(q) if T.kinds[q] == "ent" else ():
            if not (len(s) == 2 and s[-1].startswith("$")):
                for x in T.children(s):
                    spots.append({"path": list(component_path(T, q)), "specialization": s[-1], "alternative": x[-1]})
        for a in real_aspects(T, q) if T.kinds[q] == "ent" else ():     # 펼침이 만든 표시는 문서의 분해가 아니다
            spots.append({"path": list(component_path(T, q)), "aspect": family(a[-1])})
    if not spots:
        return d
    extra = [{"name": f"p{i}", rng.choice(["require", "forbid"]): {"selected": rng.choice(spots)}} for i in range(rng.choice([1, 2]))]
    if rng.random() < 0.5:
        extra.append({"name": "pw", "when": {"selected": rng.choice(spots)}, "forbid": {"selected": rng.choice(spots)}})
    return dict(d, constraints=d["constraints"] + extra)


@pytest.mark.parametrize("seed", range(200))
def test_constraints_mean_what_a_direct_reading_of_the_variant_says(seed):
    """제약을 명제식으로 번역한 결과가, 변이에서 실제로 한 선택을 읽어 평가한 값과 같다. 경로로 가리킨 것도 본다."""
    d, doc, functions = decorated(1000 + seed)
    d = with_paths(random.Random(seed), d, doc, functions)
    doc = load_ses_dict(d)
    S, ann = unfold_annotated(doc, functions)
    rules_only = unfold(load_ses_dict(dict(d, constraints=[])), functions)
    domains = U.variable_domains(doc)
    kept = 0
    for V in sem(rules_only):
        env = {}
        for x in V:
            if len(x) == 3 and x[1].startswith("$"):
                env[x[1][1:]] = next(v for v in domains[x[1][1:]] if str(v) == x[2])
        made = made_choices(S.tree, ann.void, V)

        def ok(c):
            if c.when is not None and not direct(c.when, env, functions, made, doc):
                return True
            return (c.require is None or direct(c.require, env, functions, made, doc)) and \
                (c.forbid is None or not direct(c.forbid, env, functions, made, doc))

        expected = all(ok(c) for c in doc.constraints)
        assert holds(S.phi, V) == expected
        kept += expected
        STATS["direct_variants"] += 1
        STATS["direct_rejected"] += not expected
    assert kept == len(sem(S))
    STATS["direct_docs_mixed"] += 0 < kept < len(sem(rules_only))


def test_parity_samples_are_not_vacuous():
    if not STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["models"] >= 1500 and STATS["cut_by_constraints"] >= 1500 and STATS["docs_cut"] >= 100, STATS
    assert STATS["docs_with_functions"] >= 100 and STATS["docs_empty"] <= 150, STATS
    assert STATS["direct_variants"] >= 2000 and STATS["direct_rejected"] >= 500 and STATS["direct_docs_mixed"] >= 60, STATS
    assert STATS["prio_models"] >= 1500 and STATS["prio_docs_marked"] >= 60 and STATS["prio_docs_changed"] >= 60, STATS
    assert STATS["prio_pushed_variants"] >= 300 and STATS["prio_unmergeable"] >= 100, STATS
