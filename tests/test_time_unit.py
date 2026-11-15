"""시간 단위 (docs/ses-platform/17_time_unit.md).

계약. 바인딩에 시간 단위를 적는다. 공통 모델 기반의 시간 전진은 그 정수배다. 참조 시뮬레이터와
실행기는 시각을 눈금의 정수로 세고, 모델과 기록에 보이는 시각은 눈금 수에 시간 단위를 곱한 값이다.
그래서 같은 계획의 사건 기록이 실행기에 상관없이 같다. 시간 단위가 이진수로 정확히 적히지 않아도 같다.

pyevsim이 없거나 cevsim(환경 변수 CEVSIM_HOME)이 없으면 그 실행기와의 대조만 빠진다.
"""

import json
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from pdevs_models import as_plan  # noqa: E402
from test_executor import Witness, generic, state  # noqa: E402
from test_structure import rand_structure  # noqa: E402

from ses_core import cevsim_executor as C  # noqa: E402
from ses_core import devs, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core import structure as st  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.devs import INF, Atomic, DevsExecutor, simulate  # noqa: E402
from ses_core.diagnose import analyze  # noqa: E402
from ses_core.executor import Bind, Binding, Module, OffGrid, grid, last_tick, same_unit, ticks, time_unit  # noqa: E402
from ses_core.extension import violations  # noqa: E402
from ses_core.unfold import unfold_layered  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")
HOME = os.environ.get("CEVSIM_HOME", "")
STATS: dict = {"runs": 0, "events": 0, "pyevsim": 0, "cevsim": 0}


def others() -> list:
    """참조 실행기 말고 이 환경에서 쓸 수 있는 실행기들. (이름, 실행기를 만드는 함수)"""
    out = []
    try:
        from ses_core.pyevsim_executor import PyevsimExecutor
        out.append(("pyevsim", PyevsimExecutor))
    except ModuleNotFoundError:
        pass
    if C.available(HOME):
        out.append(("cevsim", lambda unit=None: C.CevsimExecutor(HOME, unit)))
    return out


def run_on(make, plan: dict, lib: dict, until: float) -> tuple:
    sim = make().build(plan, lib)
    try:
        return list(sim.run(until)), state(sim.leaves())
    finally:
        sim.close()


# ---------------------------------------------------------------------------
# 눈금: 값에서 정수로
# ---------------------------------------------------------------------------

def test_grid_reads_a_value_as_a_multiple_of_the_unit():
    assert grid(0.3, 0.1) == 3 and grid(0.1 + 0.2, 0.1) == 3 and grid(3 * 0.1, 0.1) == 3      # 끝자리가 달라도 같은 눈금이다
    assert grid(0.0, 0.1) == 0 and grid(2.5, 2.5) == 1 and grid(7, 1) == 7 and grid(1.0, 1 / 3) == 3
    assert grid(0.35, 0.1) is None and grid(0.5, 1.0) is None and grid(0.1, 0.3) is None
    assert grid(1 + 1e-10, 1.0) == 1 and grid(1 + 1e-8, 1.0) is None                         # 상대 오차 1e-9까지
    assert grid(1e6 + 1e-4, 1.0) == 1000000 and grid(1e6 + 1e-2, 1.0) is None                # 큰 값에서는 그 값에 견준다
    # 한계 (문서 17의 T2). 허용 폭이 눈금 번호에 비례하므로 눈금 1e8에서는 0.1눈금이고,
    # 눈금 5e8부터는 반 눈금을 넘어서 어떤 값이든 가장 가까운 눈금으로 읽힌다
    assert grid(1e8 + 0.05, 1.0) == 100000000 and grid(1e8 + 0.2, 1.0) is None
    assert grid(4e8 + 0.45, 1.0) is None and grid(5e8 + 0.4, 1.0) == 500000000
    assert grid(INF, 1.0) is None and grid(float("nan"), 1.0) is None
    assert grid(-0.2, 0.1) == -2                                                             # 부호는 부르는 쪽이 본다


def test_ticks_turns_a_time_advance_into_a_count():
    assert ticks("m", 0.3, 0.1) == 3 and ticks("m", 0.0, 0.1) == 0 and ticks("m", 2, 0.5) == 4
    assert ticks("m", INF, 0.1) is None                                                      # 쉬고 있다
    with pytest.raises(OffGrid, match="m: 시간 전진 0.35 이 시간 단위 0.1 의 배수가 아니다"):
        ticks("m", 0.35, 0.1)
    for bad in (-0.1, float("nan")):
        with pytest.raises(ValueError, match="m: 시간 전진 .* 이 음수이거나 수가 아니다") as e:
            ticks("m", bad, 0.1)
        assert not isinstance(e.value, OffGrid)
    assert issubclass(OffGrid, ValueError)


def test_last_tick_of_a_run():
    assert last_tick(0.3, 0.1) == 3 and last_tick(0.1 + 0.2, 0.1) == 3                       # 0.3은 눈금 3의 시각이다
    assert last_tick(0.29, 0.1) == 2 and last_tick(0.31, 0.1) == 3 and last_tick(0.0, 0.1) == 0
    assert last_tick(2.6, 0.25) == 10 and last_tick(8.0, 0.25) == 32 and last_tick(7, 2) == 3
    # 눈금이 많아지면 나눗셈의 끝자리 차이가 커진다. 그 크기에 견줘서 판정한다
    assert 98765432.1 / 0.1 == 987654320.9999999 and last_tick(98765432.1, 0.1) == 987654321
    # 한계 (문서 17의 T2). 끝 시각이 어떤 눈금에서 허용 폭 안에 있으면 그 눈금까지 간다. 조금 못 미쳐도 그렇다.
    # 눈금 5e8부터는 가장 가까운 눈금까지 가므로 반 눈금까지 뒤의 눈금이 될 수 있다
    assert last_tick(1e6 - 0.0005, 1.0) == 1000000 and last_tick(1e6 - 0.002, 1.0) == 999999
    assert last_tick(4e8 + 0.55, 1.0) == 400000000 and last_tick(5e8 + 0.6, 1.0) == 500000001


def test_the_unit_written_in_several_places_must_be_one_value():
    assert same_unit() == 1.0 and same_unit(None, None) == 1.0                               # 어디에도 없으면 1이다
    assert same_unit(None, 0.25) == 0.25 and same_unit(0.1, None, 0.1) == 0.1 and same_unit(2) == 2.0
    assert isinstance(same_unit(2), float)
    with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
        same_unit(0.1, 0.2)
    for bad in (0, -1.0, INF, float("nan"), True):
        with pytest.raises(ValueError, match="0보다 큰 유한한 수"):
            same_unit(bad)
    plan = st.node({}, {"a": st.node({}), "b": st.node({}, {"c": st.node({}, time_unit=0.5)})})
    assert time_unit(plan) == 0.5 and time_unit(plan, 0.5) == 0.5 and time_unit(st.node({})) == 1.0
    assert time_unit(st.node({}), 0.2) == 0.2
    with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
        time_unit(plan, 0.25)
    plan["children"]["a"]["time_unit"] = 0.1                                                 # 계획의 두 자리에 다른 값
    with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
        time_unit(plan)


# ---------------------------------------------------------------------------
# 선언: 바인딩에 적고 계획에 실려 간다
# ---------------------------------------------------------------------------

class Clock(Atomic):
    """주기마다 낸다. 주기는 시간 값이다."""
    PORTS = {"o": ("T", "out")}
    PARAMS = {"period": ("time", 1.0)}

    def init(self):
        self.k = 0

    def ta(self):
        return self.period

    def output(self):
        return {"o": [self.k]}

    def internal(self):
        self.k += 1


TIMED = {
    "ses": "1.0", "name": "R", "port_types": {"T": {}},
    "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["Src", "Dst"],
                                              "couplings": [{"from": "Src.o", "to": "Dst.i"}]}}},
        "Src": {"ports": {"o": {"type": "T", "direction": "out"}},
                "attributes": {"period": {"type": "float", "default": 0.5}},
                "specializations": {"pace": {"alternatives": ["Slow", "Fast"]}}},
        "Slow": {"extends": "Src", "attributes": {"period": {"type": "float", "default": 1.5}}},
        "Fast": {"extends": "Src", "attributes": {"period": {"type": "float", "default": 0.3}}},
        "Dst": {"ports": {"i": {"type": "T", "direction": "in"}}},
    },
}
LIB = {"Clock": devs.module_of(Clock), "Witness": devs.module_of(Witness)}
MAP = {"Src": Bind("Clock"), "Dst": Bind("Witness")}


def pace(V) -> str:
    return next(n[-1] for n in V if n[-1] in ("Slow", "Fast"))


def test_binding_carries_the_time_unit():
    b = Binding.from_dict({"binding": "1.0", "executor": "devs", "time_unit": 0.5, "map": {"Src": {"module": "Clock"}}})
    assert b.time_unit == 0.5 and b.to_dict() == {"binding": "1.0", "executor": "devs", "time_unit": 0.5, "map": {"Src": {"module": "Clock"}}}
    plain = Binding.from_dict({"binding": "1.0", "executor": "devs", "map": {}})
    assert plain.time_unit is None and "time_unit" not in plain.to_dict()                    # 적지 않은 것은 적지 않은 채로 둔다
    for bad in (0, -0.5, INF, True, "0.5"):
        with pytest.raises(ValueError, match="0보다 큰 유한한 수"):
            Binding("devs", {}, None, bad)
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(EXAMPLES, "..", "schema", "binding.schema.json"), encoding="utf-8") as f:
        validator = jsonschema.Draft202012Validator(json.load(f))
    assert list(validator.iter_errors(b.to_dict())) == []
    for bad in (0, -0.5, "0.5"):
        assert list(validator.iter_errors(dict(b.to_dict(), time_unit=bad))), bad
    timed = {"library": "1.0", "executor": "devs", "modules": {"Clock": {"params": {"period": {"type": "time", "default": 1.0}}}}}
    assert list(validator.iter_errors(timed)) == []                                          # 매개변수의 타입 time


def test_the_plan_carries_the_unit_from_the_binding_to_the_executor():
    L0 = unfold_layered(load_ses_dict(TIMED))
    dx = DevsExecutor()
    L, ext = X.attach(L0, dx, Binding("devs", MAP, None, 0.1), LIB)
    assert ext.unit == 0.1
    for V in sem(L.ses):
        p = X.plan(L, ext, V)
        assert {c.get("time_unit") for _, c in st.walk(p)} == {0.1} and time_unit(p) == 0.1    # 계획의 모든 구성요소에 실린다
        model = X.realize(L, ext, dx, V)
        period = {"Slow": 1.5, "Fast": 0.3}[pace(V)]
        log = simulate(model, 3.0)                                                           # 시간 단위는 모델에 적혀 있다
        assert [t for t, *_ in log] == [k * round(period / 0.1) * 0.1 for k in range(1, int(3.0 / period + 1e-9) + 1)]
        with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
            simulate(model, 3.0, unit=0.5)
    L, plain = X.attach(L0, dx, Binding("devs", MAP), LIB)                                   # 적지 않은 바인딩: 계획에 싣지 않는다
    assert plain.unit == 1.0 and all("time_unit" not in c for V in sem(L.ses) for _, c in st.walk(X.plan(L, plain, V)))
    L, given = X.attach(L0, DevsExecutor(0.1), Binding("devs", MAP), LIB)                    # 실행기에 준 것도 같은 자리에 쓰인다
    assert given.unit == 0.1
    with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
        X.attach(L0, DevsExecutor(0.5), Binding("devs", MAP, None, 0.1), LIB)


def test_time_parameters_are_checked_against_the_unit_in_the_plan():
    """타입이 time인 매개변수의 값이 시간 단위의 정수배가 아니면 그 변이는 실행 가능하지 않다 (B5)."""
    L0 = unfold_layered(load_ses_dict(TIMED))

    def verdicts(unit):
        L, ext = X.attach(L0, DevsExecutor(), Binding("devs", MAP, None, unit), LIB)
        return L, ext, {pace(V): sorted({code for _, code, _, _ in violations(X.alone(L, ext), V)}) for V in sem(L.ses)}

    assert verdicts(0.1)[2] == {"Slow": [], "Fast": []}                                      # 1.5와 0.3은 0.1의 정수배다
    L, ext, got = verdicts(0.5)
    assert got == {"Slow": [], "Fast": ["B5"]}                                               # 0.3은 0.5의 정수배가 아니다
    (good,) = X.executable_variants(L, ext)
    assert pace(good) == "Slow" and set(sem(X.exec_core(L, ext).ses)) == {good}              # 실행 가능 핵에서 빠진다
    (bad,) = [V for V in sem(L.ses) if V != good]
    with pytest.raises(ValueError, match="실행 가능하지 않은 변이"):
        X.realize(L, ext, DevsExecutor(), bad)
    (msg,) = [m for _, code, _, m in violations(X.alone(L, ext), bad) if code == "B5"]
    assert msg == "매개변수 period 의 값 0.3 이 시간 단위 0.5 의 음이 아닌 정수배가 아니다"
    L, ext, got = verdicts(None)
    assert got == {"Slow": ["B5"], "Fast": ["B5"]} and X.exec_core(L, ext) is None           # 적지 않으면 1이다
    a = analyze(E.from_dict(TIMED), attach=lambda L1: X.attach(L1, DevsExecutor(), Binding("devs", MAP, None, 0.5), LIB)[0])
    (d,) = a.of("B5")                                                                        # 편집기의 진단으로 나온다
    assert (d.code, d.layer, d.address, d.affected) == ("B5", "exec:devs", "entities/Src", (1, 2))
    # 기본값도, 무한도, 타입이 time이 아닌 것도
    late = {"Clock": Module("Clock", Clock.PORTS, (), {"period": ("time", 0.7)}, Clock), "Witness": LIB["Witness"]}
    bare = json.loads(json.dumps(TIMED))
    for name in ("Src", "Slow", "Fast"):
        bare["entities"][name].pop("attributes")                                             # 속성이 없으면 모듈의 기본값을 쓴다
    Lb = unfold_layered(load_ses_dict(bare))

    def codes(lib, unit):
        L, ext = X.attach(Lb, DevsExecutor(), Binding("devs", MAP, None, unit), lib)
        return {code for V in sem(L.ses) for _, code, _, _ in violations(X.alone(L, ext), V)}

    assert codes(late, 0.5) == {"B5"} and codes(late, 0.1) == set()
    assert codes({**late, "Clock": Module("Clock", Clock.PORTS, (), {"period": ("time", INF)}, Clock)}, 0.5) == set()
    assert codes({**late, "Clock": Module("Clock", Clock.PORTS, (), {"period": ("time", -1.0)}, Clock)}, 0.5) == {"B5"}
    assert codes({**late, "Clock": Module("Clock", Clock.PORTS, (), {"period": ("float", 0.7)}, Clock)}, 0.5) == set()
    whole = json.loads(json.dumps(TIMED))                                                    # 정수로 적은 시간 값도 시간 값이다
    for name, value in (("Src", 1), ("Slow", 2), ("Fast", 3)):
        whole["entities"][name]["attributes"] = {"period": {"type": "int", "default": value}}
    Lw = unfold_layered(load_ses_dict(whole))
    L, ext = X.attach(Lw, DevsExecutor(), Binding("devs", MAP), LIB)
    assert X.executable_variants(L, ext) == sem(L.ses)
    assert sorted(len(simulate(X.realize(L, ext, DevsExecutor(), V), 6.0)) for V in sem(L.ses)) == [2, 3]


# ---------------------------------------------------------------------------
# 참조 시뮬레이터: 시각을 눈금으로 센다
# ---------------------------------------------------------------------------

class TwoSteps(Atomic):
    """0.1 뒤에 한 번, 거기서 0.2 뒤에 한 번 낸다."""
    PORTS = {"o": ("T", "out")}
    STEPS = (0.1, 0.2)

    def init(self):
        self.todo = list(self.STEPS)

    def ta(self):
        return self.todo[0] if self.todo else INF

    def output(self):
        return {"o": [self.name]}

    def internal(self):
        self.todo.pop(0)


class OneStep(TwoSteps):
    """0.3 뒤에 한 번 낸다."""
    STEPS = (0.3,)


def meeting():
    return devs.Coupled("", {}, {"a": TwoSteps("a"), "b": OneStep("b"), "w": Witness("w")},
                        ic=[(("a", "o"), ("w", "i")), (("b", "o"), ("w", "i"))])


def test_reference_counts_time_in_ticks():
    """0.1 더하기 0.2와 0.3은 실수의 덧셈으로는 다른 값이다. 눈금으로 세면 같은 시각이다."""
    assert 0.1 + 0.2 != 0.3
    for flat in (False, True):
        model = meeting()
        log = simulate(model, 1.0, flat=flat, unit=0.1)
        assert log == [(0.1, ("a",), "o", "a"), (3 * 0.1, ("a",), "o", "a"), (3 * 0.1, ("b",), "o", "b")]
        # 받는 쪽은 눈금 3에서 둘을 한 묶음으로 받는다. 흐른 시간은 눈금 둘에 시간 단위를 곱한 값이다
        assert model.children["w"].seen == [(0.1, 0.1, {"i": ["a"]}), (3 * 0.1, 2 * 0.1, {"i": ["a", "b"]})]
    assert len(simulate(meeting(), 0.3, unit=0.1)) == 3                                      # 끝 시각 0.3은 눈금 3이다
    assert len(simulate(meeting(), 0.29, unit=0.1)) == 1 and simulate(meeting(), 0.0, unit=0.1) == []
    assert len(simulate(meeting(), INF, unit=0.1)) == 3                                      # 끝 시각이 무한이면 사건이 없어질 때까지
    assert len(simulate(meeting(), 0.3, unit=0.05)) == 3                                     # 더 잘게 세어도 같다
    with pytest.raises(OffGrid, match="a: 시간 전진 0.1 이 시간 단위 1.0 의 배수가 아니다"):
        simulate(meeting(), 1.0)                                                             # 시간 단위를 주지 않으면 1이다
    with pytest.raises(OffGrid, match="a: 시간 전진 0.1 이 시간 단위 0.2 의 배수가 아니다"):
        simulate(meeting(), 1.0, unit=0.2)
    drifting = devs.Coupled("", {}, {"a": TwoSteps("a")})                                    # 처음에는 눈금 위에 있다가 벗어난다
    drifting.children["a"].todo = [0.5, 0.25]
    with pytest.raises(OffGrid, match="a: 시간 전진 0.25 이 시간 단위 0.5 의 배수가 아니다"):
        simulate(drifting, 2.0, unit=0.5)


def test_devs_executor_writes_the_unit_on_the_model():
    plan = st.node({}, {"c": st.node(Clock.PORTS, module="Clock", params={"period": 0.3})})
    # 같은 모델이라도 기록의 시각은 시간 단위에 따라 끝자리가 다르다. 그래서 시간 단위를 한곳에 적어 둔다
    for unit, times in ((0.1, [3 * 0.1, 6 * 0.1, 9 * 0.1]), (0.3, [0.3, 2 * 0.3, 3 * 0.3])):
        model = DevsExecutor(unit).build(plan, LIB)
        assert model._time_unit == unit and [t for t, *_ in simulate(model, 0.9)] == times
    assert 9 * 0.1 != 3 * 0.3
    declared = dict(plan, time_unit=0.1)
    assert DevsExecutor().build(declared, LIB)._time_unit == 0.1
    with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
        DevsExecutor(0.3).build(declared, LIB)
    solo = st.node(Clock.PORTS, module="Clock", params={"period": 2.0}, time_unit=0.5)       # 뿌리가 원자인 계획
    assert [t for t, *_ in simulate(DevsExecutor().build(solo, LIB), 4.0)] == [2.0, 4.0]


# ---------------------------------------------------------------------------
# 세 실행기: 같은 계획, 같은 시간 단위, 같은 기록
# ---------------------------------------------------------------------------

class Sooner(TwoSteps):
    """0.1 뒤에 한 번, 거기서 0.3 뒤에 한 번 낸다."""
    STEPS = (0.1, 0.3)


class Later(TwoSteps):
    """0.4 뒤에 한 번 낸다."""
    STEPS = (0.4,)


@pytest.mark.parametrize("first, second", [(Sooner, Later), (Later, Sooner)])
def test_models_due_at_one_tick_fire_in_path_order_whatever_their_history(first, second):
    """눈금 4에 두 모델이 낸다. 하나는 눈금 1에서 전이한 뒤 0.3을 기다렸고 하나는 처음부터 0.4를 기다렸다.

    엔진에서 0.1에 0.3을 더한 값과 0.4는 끝자리가 다르다. 그래도 같은 눈금이고, 내는 순서는 경로의 순서다.
    """
    plan = st.node({}, {"a": st.node(first.PORTS, module="A", params={}), "b": st.node(second.PORTS, module="B", params={})},
                   time_unit=0.1)
    lib = {"A": devs.module_of(first, "A"), "B": devs.module_of(second, "B")}
    ref = simulate(DevsExecutor().build(plan, lib), 1.0)
    early = "a" if first is Sooner else "b"
    assert ref == [(0.1, (early,), "o", early), (4 * 0.1, ("a",), "o", "a"), (4 * 0.1, ("b",), "o", "b")]
    for name, make in others():
        assert run_on(make, plan, lib, 1.0)[0] == ref, name


def stepped(unit: float):
    """generic과 같은 모델. 지연이 시간 단위의 정수배다 (눈금 2개에서 8개)."""
    def body(ports: dict):
        class Stepped(generic(ports)):
            def init(self):
                super().init()
                self.delay = (2 + sum(map(ord, self.name)) % 7) * unit
                self.left = self.delay
        return Stepped
    return body


@pytest.mark.parametrize("unit", [0.1, 0.3, 0.7, 1 / 3, 2.5, 0.25, 1e-3])
@pytest.mark.parametrize("seed", range(12))
def test_executors_give_the_same_log_for_any_time_unit(unit, seed):
    plan, lib = as_plan(rand_structure(random.Random(seed)), body=stepped(unit), unit=unit)
    until = 30 * unit
    model = DevsExecutor().build(plan, lib)
    ref = simulate(model, until)
    assert ref == simulate(DevsExecutor().build(plan, lib), until, flat=True)
    assert all(t == grid(t, unit) * unit for t, *_ in ref)                                   # 기록의 시각은 눈금 수에 단위를 곱한 값이다
    for name, make in others():
        log, final = run_on(make, plan, lib, until)
        assert log == ref and final == state(devs._leaves(model)), name
        STATS[name] += 1
    STATS["runs"] += 1
    STATS["events"] += len(ref)


def forever(unit: float):
    """끝없이 내는 모델. 긴 실행에 쓴다."""
    def body(ports: dict):
        class Forever(generic(ports)):
            def init(self):
                super().init()
                self.delay = (1 + sum(map(ord, self.name)) % 5) * unit
                self.left = self.delay

            def internal(self):
                self.sent += 1
                self.left = self.delay
        return Forever
    return body


def test_executors_agree_on_a_long_run_with_a_unit_that_is_not_binary():
    """눈금 3,000개. 엔진이 시각을 더하면서 반올림이 쌓이는 길이에서도 눈금으로 센 기록은 같다."""
    unit = 0.1
    plan, lib = as_plan(rand_structure(random.Random(2)), body=forever(unit), unit=unit)
    model = DevsExecutor().build(plan, lib)
    ref = simulate(model, 3000 * unit, max_steps=10 ** 6)
    assert len(ref) > 5000 and ref[-1][0] == 3000 * unit and any(t != round(t, 9) for t, *_ in ref)
    for name, make in others():
        log, final = run_on(make, plan, lib, 3000 * unit)
        assert log == ref and final == state(devs._leaves(model)), name


@pytest.mark.parametrize("until, count", [(0.3, 3), (0.1 + 0.2, 3), (0.31, 3), (0.29, 2), (0.26, 2), (0.05, 0), (0.0, 0)])
def test_executors_read_the_end_time_as_the_same_tick(until, count):
    """끝 시각의 눈금은 세 실행기가 같은 함수로 읽는다(executor.last_tick).

    0.1마다 내는 모델을 돌린다. 0.3을 0.1로 나눈 값은 3보다 조금 작지만 눈금 3의 사건까지 처리한다.
    0.26과 0.29는 눈금 3에 더 가깝지만 눈금 2까지만 처리한다.
    """
    plan = st.node({}, {"c": st.node(Clock.PORTS, module="Clock", params={"period": 0.1})}, time_unit=0.1)
    want = [(k * 0.1, ("c",), "o", k - 1) for k in range(1, count + 1)]
    assert simulate(DevsExecutor().build(plan, LIB), until) == want
    for name, make in others():
        log, _ = run_on(make, plan, LIB, until)
        assert log == want, name


def test_executors_agree_on_the_example_with_a_declared_unit():
    """시간 값을 바꾼 예시: 도착 간격 0.3, 서비스 시간 0.7. 시간 단위 0.1에서 세 실행기의 기록이 같다."""
    L0 = unfold_layered(load_ses_dict(TIMED))
    fast = next(V for V in sem(L0.ses) if pace(V) == "Fast")
    logs = []
    for name, make in [("devs", DevsExecutor)] + others():
        cx = make()
        L, ext = X.attach(L0, cx, Binding(name, MAP, None, 0.1), LIB)
        assert X.executable(L, ext, fast)
        art = X.realize(L, ext, cx, fast)
        if name == "devs":
            logs.append(simulate(art, 2.0))
        else:
            logs.append(list(art.run(2.0)))
            art.close()
    assert all(log == logs[0] for log in logs) and [t for t, *_ in logs[0]] == [3 * k * 0.1 for k in range(1, 7)]


def test_time_unit_samples_are_not_vacuous():
    if not STATS["runs"]:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["runs"] == 84 and STATS["events"] >= 600, STATS
    for name, _ in others():
        assert STATS[name] == 84, STATS
    assert math.isclose(0.1 * 3, 0.3) and 0.1 * 3 != 0.3                                     # 이 시험들이 다룬 차이
