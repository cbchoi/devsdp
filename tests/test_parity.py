"""전통적인 SES가 하던 것 가운데 빠져 있던 것 (docs/ses-platform/18_classic_parity.md).

1. 선택에 대한 제약 (selected). "A를 고르면 B는 안 된다", "전부 없음은 금지".
2. 이름으로 등록한 함수 (call). 규칙과 제약에서 변수의 값을 함수로 판정한다.

두 가지 모두 세 길로 확인한다. 손으로 만든 예, 문헌의 서술을 따라 적은 고전 절차(classic.py)와의
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
from ses_core import edit as E  # noqa: E402
from ses_core import unfold as U  # noqa: E402
from ses_core.algebra import ASP, AlgebraError, count_variants, holds, sem  # noqa: E402
from ses_core.coupling import Coupling  # noqa: E402
from ses_core.decisions import component_path, family, split_count  # noqa: E402
from ses_core.diagnose import analyze  # noqa: E402
from ses_core.extension import Layered, interpret, violations  # noqa: E402
from ses_core.skeleton import members, skeleton  # noqa: E402
from ses_core.unfold import unfold, unfold_annotated  # noqa: E402

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
    """빠진 구성요소 아래에서 한 선택은 세지 않는다. 그 구성요소는 만들어지지 않기 때문이다."""
    doc = load_ses_dict(NESTED)
    assert len(sem(unfold(doc))) == 8 and len(classic.enumerate_classic(doc)) == 6    # 대수는 빠진 상자 안의 선택도 센다
    no_red = constrained(NESTED, {"forbid": {"selected": "Lamp/colour=Red"}})
    # 남는 구조: 상자가 있고 두 등이 모두 파랑(1), 상자가 없고 바깥 등이 파랑(1).
    # 상자가 없을 때 그 안의 등이 빨강이라는 선택은 제약에 걸리지 않으므로 변이로는 둘이 남는다
    assert n_variants(no_red) == (3, 2)
    d = load_ses_dict(no_red)
    S = unfold(d)
    gone = [V for V in sem(S) if ("R", "d", "Box", "has", "NoBox") in V]
    assert len(gone) == 2 and all(("R", "d", "Lamp", "colour", "Blue") in V for V in gone)
    assert {("R", "d", "Box", "in", "Lamp", "colour", c) in V for V in gone for c in ("Red",)} == {True, False}
    # 분해를 고른 것도 살아 있는 구성요소의 것만 센다
    inner = constrained(NESTED, {"require": {"selected": "Box=in"}})
    assert n_variants(inner) == (4, 4)                        # 상자가 있는 넷만 남는다


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
    # 대수는 빠진 X 안의 선택(a 또는 b)도 변이로 세므로 X 없음이 값마다 둘이다
    assert alive == {(1, False): 2, (2, False): 2, (2, True): 1, (3, False): 2, (3, True): 2}
    algebraic, procedural, skipped = both(doc, None)
    assert algebraic == procedural and len(procedural) == 6 and skipped == 0


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
    for q in T.nodes:
        if T.kind(q) == ASP:
            continue
        for s in T.specs(q) if T.kinds[q] == "ent" else ():
            if not (len(s) == 2 and s[-1].startswith("$")):
                for x in T.children(s):
                    spots.append({"path": list(component_path(T, q)), "specialization": s[-1], "alternative": x[-1]})
        for a in T.aspects(q) if T.kinds[q] == "ent" else ():
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
