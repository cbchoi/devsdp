"""pyevsim 실행기 (docs/ses-platform/15_pyevsim_executor.md).

합격 기준은 둘이다 (14 문서의 결정 D1).
- 충실성: 엔진에서 다시 읽은 모델과 연결이 계획의 것과 같다. 연결은 길의 수까지 같다.
- 사건 기록: 같은 모델베이스를 참조 시뮬레이터(devs.py)와 pyevsim에서 돌린 출력 사건의 열이 같다.

pyevsim이 설치되어 있지 않으면 건너뛴다. 엔진의 성질을 적어 둔 시험(확인한 사실)은 확인한
판(1.1.7)에서만 돈다.
"""

import collections
import importlib.metadata
import os
import random
import sys

import pytest
import yaml

pytest.importorskip("pyevsim")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import rand_binding, rand_system_document  # noqa: E402
from pyevsim import BehaviorModelExecutor, Infinite, SysMessage, SystemSimulator  # noqa: E402
from pyevsim.structural_model import StructuralModel  # noqa: E402
from pyevsim.system_executor import SysExecutor  # noqa: E402
from pdevs_models import NOTE, Burst, Keep, Pair, Ring, Spin, as_plan, flat_plan, note  # noqa: E402
from test_executor import UNIT, Sometimes, Witness, generic, library_of, quirky, state  # noqa: E402
from test_structure import rand_structure  # noqa: E402

from examples import processing_mb, processing_pyevsim, sensor_node_mb  # noqa: E402
from ses_core import devs, hw, load_ses, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core import pyevsim_executor as P  # noqa: E402
from ses_core import structure as st  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.decisions import load_decisions, patterns  # noqa: E402
from ses_core.devs import Atomic, DevsExecutor, simulate  # noqa: E402
from ses_core.diagnose import analyze  # noqa: E402
from ses_core.executor import Bind, Binding, Module  # noqa: E402
from ses_core.extension import interpret, prune, violations  # noqa: E402
from ses_core.pyevsim_executor import OffGrid, PyevsimExecutor  # noqa: E402
from ses_core.unfold import unfold_layered  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")
PINNED = importlib.metadata.version("pyevsim") == "1.1.7"
fact = pytest.mark.skipif(not PINNED, reason="pyevsim 1.1.7에서 확인한 사실이다. 다른 판에서는 다시 확인해야 한다")
STATS: collections.Counter = collections.Counter()


# ---------------------------------------------------------------------------
# 도구
# ---------------------------------------------------------------------------

def label(plan: dict, path: tuple) -> str:
    return P.ref(path) or plan.get("name", "") or "root"


def faithful(px: PyevsimExecutor, sim, plan: dict, exact_ports: bool = True) -> None:
    """충실성: 엔진에서 다시 읽은 것이 계획의 평탄한 꼴이다."""
    assert sim.connections() == st.flatten(plan)             # 연결과 그 길의 수
    seen = px.observe(sim)
    assert st.is_atom(plan) or seen["ports"] == dict(plan["ports"])     # 뿌리의 포트는 엔진의 경계다
    want = {label(plan, p): dict(st.subtree(plan, p)["ports"]) for p in st.atoms(plan)}
    got = {k: c["ports"] for k, c in seen["children"].items()}
    assert set(got) == set(want)                             # 모델은 계획의 원자들이고 그것뿐이다
    for k, ports in want.items():
        assert got[k] == ports if exact_ports else ports.items() <= got[k].items()

    def end(pt):
        return ((label(plan, pt[0]),) if pt[0] else (), pt[1])

    assert set(st.flatten(seen)) == {(end(s), end(t)) for s, t in st.flatten(plan)}
    assert st.violations(seen) == []


def on_both(plan: dict, lib: dict, until: float, step: float = None, **options) -> tuple:
    """같은 계획과 같은 라이브러리를 두 실행기로 만들어 돌린다. 시간 단위는 계획에 적힌 것을 쓴다."""
    model = DevsExecutor().build(plan, lib)
    log = simulate(model, until)
    px = PyevsimExecutor(step, **options)
    sim = px.build(plan, lib)
    try:
        faithful(px, sim, plan)
        mine = list(sim.run(until))
        faithful(px, sim, plan)                              # 돌린 뒤에도 같다. 엔진이 스스로 더한 것은 세지 않는다
        return log, mine, devs._leaves(model), sim.leaves()
    finally:
        sim.close()


def attach_both(doc_name: str, binding_name: str, library: dict, step: float = 1.0, px_library=None):
    L = unfold_layered(load_ses(os.path.join(EXAMPLES, doc_name)))
    b = X.load_binding(os.path.join(EXAMPLES, binding_name))
    dx, px = DevsExecutor(), PyevsimExecutor(step)
    L, de = X.attach(L, dx, b, library)
    L, pe = X.attach(L, px, Binding("pyevsim", b.map, b.target, b.time_unit), px_library or library)
    return L, (dx, de), (px, pe)


def run_both(L, de_pair, pe_pair, V, until, exact_ports=True):
    (dx, de), (px, pe) = de_pair, pe_pair
    model = X.realize(L, de, dx, V)
    log = simulate(model, until)
    sim = X.realize(L, pe, px, V)
    try:
        faithful(px, sim, X.plan(L, pe, V), exact_ports)
        mine = list(sim.run(until))
        faithful(px, sim, X.plan(L, pe, V), exact_ports)
        return log, mine, devs._leaves(model), sim.leaves()
    finally:
        sim.close()


# ---------------------------------------------------------------------------
# 예시: 같은 SES, 같은 모델베이스, 실행기만 pyevsim
# ---------------------------------------------------------------------------

def test_processing_system_on_pyevsim_gives_the_reference_log():
    L, D, Px = attach_both("processing_system.ses.yaml", "processing_system.binding.devs.yaml", processing_mb.LIBRARY)
    variants = sem(L.ses)
    assert len(variants) == 15 and X.executable_variants(L, Px[1]) == variants
    for V in variants:
        ref, log, _, leaves = run_both(L, D, Px, V, 20.0)
        assert log == ref                                    # 사건의 열이 같다. 순서까지
        servers = [a for p, a in leaves.items() if p[0] == "ServerPool"]
        assert leaves[("Generator",)].count == 20            # 시각 20의 사건도 처리한다
        assert len(leaves[("Collector",)].done) == (9 if len(servers) == 1 else 18)
        STATS["example_events"] += len(log)


def test_pyevsim_binding_file_and_decision_file_to_a_running_engine():
    L0 = unfold_layered(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))
    binding = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.pyevsim.yaml"))
    assert binding.executor == "pyevsim" == PyevsimExecutor.name
    px = PyevsimExecutor(1.0, engine_name="processing")
    L, ext = X.attach(L0, px, binding, processing_pyevsim.LIBRARY)
    ds = load_decisions(os.path.join(EXAMPLES, "processing_system.decisions.yaml"))
    (V,) = sem(prune(L, *patterns(L.ses, ds)).ses)
    sim = X.realize(L, ext, px, V)
    try:
        assert SystemSimulator.get_engine("processing") is sim.engine    # pyevsim의 방식으로 찾을 수 있다
        assert sim.engine.get_entity("Buffer") == [sim.models[("Buffer",)]]
        assert type(sim.models[("Buffer",)]).__name__ == "PriorityBuffer"
        assert sorted(p[1] for p in sim.models if p[0] == "ServerPool") == ["server_0", "server_1", "server_2", "server_3"]
        sim.run(20.0)
        assert len(sim.leaves()[("Collector",)].done) == 18
    finally:
        sim.close()
    assert "processing" not in SystemSimulator.get_engine_map()


def test_black_box_binding_on_pyevsim():
    b = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.devs.yaml"))
    box = Binding("pyevsim", {**{k: v for k, v in b.map.items() if k != "Server"}, "ServerPool": Bind("Pool")}, b.target)
    L0 = unfold_layered(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))
    dx, px = DevsExecutor(), PyevsimExecutor(1.0)
    L, de = X.attach(L0, dx, box, processing_mb.LIBRARY)
    L, pe = X.attach(L, px, box, processing_mb.LIBRARY)
    for V in sem(L.ses):
        ref, log, _, leaves = run_both(L, (dx, de), (px, pe), V, 20.0)
        assert log == ref and sorted(leaves) == [("Buffer",), ("Collector",), ("Generator",), ("ServerPool",)]
        assert len(leaves[("Collector",)].done) == 9


def sensor_node():
    doc = load_ses(os.path.join(EXAMPLES, "sensor_node.ses.yaml"))
    L, D, Px = attach_both("sensor_node.ses.yaml", "sensor_node.binding.devs.yaml", sensor_node_mb.LIBRARY)
    with open(os.path.join(EXAMPLES, "sensor_node.hwlib.yaml"), encoding="utf-8") as f:
        lib = yaml.safe_load(f)
    hx = hw.HwExecutor(hw.load_rules(lib))
    L, he = X.attach(L, hx, X.load_binding(os.path.join(EXAMPLES, "sensor_node.binding.hw.yaml")),
                     X.load_library_dict(lib))
    return doc, L, D, Px, (hx, he)


def test_sensor_node_three_executors():
    doc, L, D, Px, (hx, he) = sensor_node()
    variants = sem(L.ses)
    devs_ok, px_ok = set(X.executable_variants(L, D[1])), set(X.executable_variants(L, Px[1]))
    hw_ok = set(X.executable_variants(L, he))
    assert (len(variants), len(px_ok), len(px_ok & hw_ok)) == (112, 56, 8) and px_ok == devs_ok
    for V in sorted(px_ok, key=sorted):
        ref, log, _, leaves = run_both(L, D, Px, V, 5.0)
        assert log == ref and len(leaves[("Radio",)].received) == 5
        STATS["example_events"] += len(log)
    # 정리 19: 실행 가능 핵은 실행기를 얹는 순서와 무관하다. pyevsim도 다른 실행기와 같은 자리에 있다
    core = X.exec_core(X.exec_core(L, Px[1]), he)
    assert set(sem(core.ses)) == set(sem(X.exec_core(X.exec_core(L, he), Px[1]).ses)) == px_ok & hw_ok
    # 따름정리 18.1: 엔진의 연결과 배선표의 연결이 같다
    for V in px_ok & hw_ok:
        sim, board = X.realize(L, Px[1], Px[0], V), X.realize(L, he, hx, V)
        try:
            wires = {((hw.ref(s), sp), (hw.ref(t), tp)) for ((s, sp), (t, tp)) in sim.connections()}
            assert wires == {((s[0], sp), (t[0], tp)) for ((s, sp), (t, tp)) in st.flatten(hx.observe(board))}
        finally:
            sim.close()


# ---------------------------------------------------------------------------
# 무작위 구조와 무작위 문서: 충실성과 사건 기록
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(300))
def test_random_structures_same_log_as_the_reference(seed):
    n = rand_structure(random.Random(seed))
    plan, lib = as_plan(n)
    ref, log, r_leaves, leaves = on_both(plan, lib, 8.0)
    assert log == ref and state(leaves) == state(r_leaves)
    flat = st.flatten(plan)
    STATS["events"] += len(log)
    STATS["delivered"] += sum(1 for _, _, _, (_, _, seen) in log if seen > 0)
    STATS["connections"] += len(flat)
    STATS["multiple"] += sum(1 for k in flat.values() if k > 1)
    STATS["to_itself"] += sum(1 for (s, _), (t, _) in flat if s == t and s)
    STATS["boundary"] += sum(1 for (s, _), (t, _) in flat if not s or not t)
    at = collections.Counter(t for t, _ in {(t, p) for t, p, _, _ in log})
    STATS["same_instant"] += sum(1 for k in at.values() if k > 1)       # 둘 이상의 모델이 함께 낸 시각


@pytest.mark.parametrize("seed", range(200))
def test_random_structures_with_empty_and_multiple_outputs(seed):
    """출력이 값을 0개, 1개, 2개 가질 때에도 기록과 상태가 참조와 같다. 묶음의 내용과 순서까지 본다."""
    plan, lib = as_plan(rand_structure(random.Random(seed)), body=quirky)
    ref, log, r_leaves, leaves = on_both(plan, lib, 8.0)
    assert log == ref and state(leaves) == state(r_leaves)
    STATS["quirky_events"] += len(log)
    STATS["quirky_bags"] += sum(1 for a in leaves.values() for h in a.heard if h[0] != "both")


@pytest.mark.parametrize("seed", range(150))
def test_random_documents_faithful_and_same_log(seed):
    rng = random.Random(seed)
    d = rand_system_document(rng)
    b, mods = rand_binding(rng, d, "pyevsim")
    dx, px = DevsExecutor(), PyevsimExecutor()
    L = unfold_layered(load_ses_dict(d))
    b = dict(b, time_unit=UNIT)                              # 시간 단위는 바인딩에 적는다. 두 실행기가 계획에서 읽는다
    L, de = X.attach(L, dx, Binding.from_dict(b), library_of(mods))
    L, pe = X.attach(L, px, Binding.from_dict(b), library_of(mods))
    variants = sem(L.ses)
    good = [V for V in variants if X.executable(L, pe, V)]
    assert good == [V for V in variants if X.executable(L, de, V)]      # 이 문서들에는 pyevsim의 규약에 걸리는 이름이 없다
    for V in good[:4]:
        ref, log, r_leaves, leaves = run_both(L, (dx, de), (px, pe), V, 6.0)
        assert log == ref and state(leaves) == state(r_leaves)
        p, whole = X.plan(L, pe, V), interpret(L, V)["devs"]
        STATS["realized"] += 1
        STATS["doc_events"] += len(log)
        STATS["black_box"] += any(not st.is_atom(st.subtree(whole, a)) for a in X.frontier(p))
        STATS["root_atom"] += st.is_atom(p)
    for bad in [V for V in variants if V not in good][:1]:
        with pytest.raises(ValueError):
            X.realize(L, pe, px, bad)


# ---------------------------------------------------------------------------
# 어댑터: 병렬 DEVS의 규약을 엔진의 호출 순서 위에서 지킨다
# ---------------------------------------------------------------------------

def test_confluent_transition_is_the_models_own():
    plan, lib = flat_plan({"a": Ring, "b": Ring}, ic=[(("a", "o"), ("b", "i")), (("b", "o"), ("a", "i"))])
    ref, log, r_leaves, leaves = on_both(plan, lib, 7.0, step=1.0)
    assert log == ref and len(log) == 8
    for p in r_leaves:
        assert leaves[p].trace == r_leaves[p].trace
    assert [kind for kind, *_ in leaves[("a",)].trace] == ["con"] * 4      # 둘이 늘 같은 시각에 낸다


def test_bag_order_and_path_counts():
    """길이 둘인 연결로 값 둘을 보내면 받는 묶음은 넷이고, 순서는 참조 시뮬레이터의 것이다."""
    box = st.node({"x": ("T", "out"), "y": ("T", "out")},
                  {"e": st.node(Pair.PORTS, module="Pair", params={})},
                  eoc=[(("e", "o"), "x"), (("e", "o"), "y")])
    plan = st.node({}, {"box": box, "z": st.node(Pair.PORTS, module="Pair", params={}),
                        "k": st.node(Keep.PORTS, module="Keep", params={})},
                   ic=[(("box", "x"), ("k", "i")), (("box", "y"), ("k", "i")), (("z", "o"), ("k", "i"))])
    lib = {"Pair": devs.module_of(Pair), "Keep": devs.module_of(Keep)}
    assert st.flatten(plan)[((("box", "e"), "o"), (("k",), "i"))] == 2
    ref, log, r_leaves, leaves = on_both(plan, lib, 2.0, step=1.0)
    assert log == ref
    assert leaves[("k",)].seen == r_leaves[("k",)].seen
    first = leaves[("k",)].seen[0]
    assert first[:2] == (1.0, 1.0)
    assert first[2]["i"] == [("box/e", 0, 0), ("box/e", 0, 0), ("box/e", 0, 1), ("box/e", 0, 1), ("z", 0, 0), ("z", 0, 1)]


def test_zero_time_rounds_at_one_instant():
    plan, lib = flat_plan({"a": Burst, "b": Burst}, ic=[(("a", "o"), ("b", "i")), (("b", "o"), ("a", "i"))])
    ref, log, r_leaves, leaves = on_both(plan, lib, 3.0, step=1.0)
    assert log == ref and [t for t, *_ in log] == [1.0] * 6      # 세 차례가 모두 시각 1에 돈다
    assert leaves[("a",)].got == r_leaves[("a",)].got


def test_an_output_without_values_is_not_sent():
    plan, lib = flat_plan({"s": Sometimes, "w": Witness}, ic=[(("s", "o"), ("w", "i"))])
    ref, log, r_leaves, leaves = on_both(plan, lib, 4.0, step=1.0)
    assert log == ref == [(2.0, ("s",), "o", 1), (4.0, ("s",), "o", 3)]
    assert leaves[("w",)].seen == r_leaves[("w",)].seen == [(2.0, 2.0, {"i": [1]}), (4.0, 2.0, {"i": [3]})]


def test_endless_zero_time_transitions_are_stopped():
    plan, lib = flat_plan({"s": Spin})
    sim = PyevsimExecutor(1.0, max_rounds=50).build(plan, lib)
    with pytest.raises(RuntimeError, match="걸음 수"):
        sim.run(1.0)
    sim.close()


def test_time_advance_must_be_a_multiple_of_the_time_unit():
    # 이 모델의 지연은 0.5다. 계획에 시간 단위를 적지 않고 실행기에 준다. 주지 않으면 1이다
    plan, lib = as_plan(st.node({}, {"b": st.node({"o": ("T", "out")})}), unit=None)
    for step, ok in ((0.25, True), (0.125, True), (0.5, True), (1.0, False), (0.4, False), (None, False)):
        if ok:
            sim = PyevsimExecutor(step).build(plan, lib)
            assert sim.run(4.0) == simulate(DevsExecutor(step).build(plan, lib), 4.0) == [(0.5, ("b",), "o", ("b", 0, 0))]
            assert sim.step == step
            sim.close()
        else:
            with pytest.raises(OffGrid, match="배수"):
                PyevsimExecutor(step).build(plan, lib).run(4.0)
            with pytest.raises(OffGrid, match="b: 시간 전진 0.5 이 시간 단위"):     # 참조 시뮬레이터도 같은 판정을 한다
                simulate(DevsExecutor(step).build(plan, lib), 4.0)
    declared, _ = as_plan(st.node({}, {"b": st.node({"o": ("T", "out")})}))       # 계획에 시간 단위 0.25가 적혀 있다
    sim = PyevsimExecutor().build(declared, lib)
    assert sim.step == UNIT and len(sim.run(4.0)) == 1
    sim.close()
    for px in (PyevsimExecutor(0.5), DevsExecutor(0.5)):     # 실행기에 준 값이 계획의 것과 다르면 조립하지 않는다
        with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):
            px.build(declared, lib)

    class Drift(Atomic):                                     # 처음에는 격자 위에 있다가 벗어난다
        PORTS = {"o": ("T", "out")}

        def init(self):
            self.left = 1.0

        def ta(self):
            return self.left

        def internal(self):
            self.left = 0.5

    plan, lib = flat_plan({"d": Drift})
    sim = PyevsimExecutor(1.0).build(plan, lib)
    with pytest.raises(OffGrid):
        sim.run(3.0)
    sim.close()
    with pytest.raises(ValueError):
        PyevsimExecutor(0)
    plan, lib = as_plan(st.node({}, {"b": st.node({"o": ("T", "out")})}), unit=None)
    with pytest.raises(OffGrid):
        PyevsimExecutor(1.0, engine_name="half").build(plan, lib)
    assert "half" not in SystemSimulator.get_engine_map()   # 만들다 만 엔진이 등록부에 남지 않는다


def test_request_time_is_the_engines_own_clock_value():
    """엔진은 요청 시각이 자기 시계와 (상대 오차 1e-9 안에서) 같은 모델만 처리한다.

    엔진의 시계는 시간 간격을 거듭 더한 값이라 눈금 수와 간격의 곱에서 조금씩 멀어진다. 어댑터는
    낼 차례가 되면 엔진의 시계 값을 그대로 내놓으므로 그 차이가 얼마든 처리된다.
    """
    plan, lib = flat_plan({"r": Ring})
    sim = PyevsimExecutor(1.0).build(plan, lib)
    m = sim.models[("r",)]
    assert m.get_req_time() == 1.0 and m.time_advance() == 1.0
    sim.engine.global_time = 1.0 + 3e-9                      # 멀어진 시계. 눈금은 여전히 1이다
    assert m.get_req_time() == sim.engine.global_time and m.time_advance() == 0
    sim.engine.global_time = 3.0                             # 지나친 눈금은 조용히 넘어가지 않는다
    with pytest.raises(RuntimeError, match="지나쳤다"):
        m.get_req_time()
    sim.close()


def test_a_plan_that_is_one_atom():
    plan = st.node({"o": ("T", "out")}, module="G", params={}, name="Solo", time_unit=UNIT)
    lib = {"G": Module("G", {"o": ("T", "out")}, (), {}, generic({"o": ("T", "out")}))}
    ref, log, _, leaves = on_both(plan, lib, 6.0)
    assert log == ref and len(log) == 1 and list(leaves) == [()]
    sim = PyevsimExecutor(0.25).build(plan, lib)
    assert sim.models[()].get_name() == "Solo" and PyevsimExecutor().observe(sim)["ports"] == {}
    sim.close()


def test_run_can_be_continued():
    plan, lib = as_plan(rand_structure(random.Random(3)))
    whole = simulate(DevsExecutor().build(plan, lib), 8.0)
    sim = PyevsimExecutor(0.25).build(plan, lib)
    part = list(sim.run(2.6))                                # 격자 위에 없는 끝 시각: 2.5까지 처리한다
    assert part == [e for e in whole if e[0] <= 2.6] and 0 < len(part) < len(whole)
    assert sim.run(8.0) == whole and sim.run(1.0) == whole   # 이어서 돌리고, 지난 시각까지는 아무 일도 없다
    sim.close()


# ---------------------------------------------------------------------------
# pyevsim 모델을 본체로
# ---------------------------------------------------------------------------

def test_native_model_base_runs_the_processing_system():
    """본체가 pyevsim 모델이면 행위는 pyevsim의 의미를 따른다. 여기서는 같은 사건이 나오고 한 시각 안의 순서만 다르다."""
    L, D, Px = attach_both("processing_system.ses.yaml", "processing_system.binding.devs.yaml",
                           processing_mb.LIBRARY, px_library=processing_pyevsim.LIBRARY)
    variants = sem(L.ses)
    assert X.executable_variants(L, Px[1]) == variants
    same_order = 0
    for V in variants:
        ref, log, r_leaves, leaves = run_both(L, D, Px, V, 20.0)
        assert all(isinstance(m, BehaviorModelExecutor) and not isinstance(m, P.Adapted) for m in leaves.values())
        assert sorted(map(repr, log)) == sorted(map(repr, ref))          # 사건의 모음은 같다
        assert leaves[("Collector",)].done == r_leaves[("Collector",)].done
        assert leaves[("Generator",)].count == r_leaves[("Generator",)].count == 20
        assert len(leaves[("Buffer",)].queue) == len(r_leaves[("Buffer",)].queue)
        servers = [p for p in leaves if p[0] == "ServerPool"]
        assert [leaves[p].served for p in servers] == [r_leaves[p].served for p in servers]
        same_order += log == ref
    assert same_order == 3                                   # 서버가 둘 이하인 변이에서만 순서까지 같다


def test_native_server_without_cancel_rescheduling_goes_wrong():
    """pyevsim의 의미에 맞추지 않으면 같은 SES에서 다른 결과가 나온다. 서버가 많을수록 완료가 준다."""
    class Forgetful(processing_pyevsim.Server):
        def ext_trans(self, port, msg):                      # 지나가는 일감에도 다음 사건이 다시 잡힌다
            for job in msg.retrieve():
                if job.get("to") == self.get_name() and self._cur_state == "IDLE":
                    self._cur_state, self.job = "BUSY", job
                    return

    lib = dict(processing_pyevsim.LIBRARY)
    old = lib["Server"]
    lib["Server"] = Module("Server", old.ports, old.required, old.params, Forgetful)
    L, D, Px = attach_both("processing_system.ses.yaml", "processing_system.binding.devs.yaml",
                           processing_mb.LIBRARY, px_library=lib)
    done = {}
    for V in sem(L.ses):
        _, _, _, leaves = run_both(L, D, Px, V, 20.0)
        done[sum(1 for p in leaves if p[0] == "ServerPool")] = len(leaves[("Collector",)].done)
    assert done == {1: 9, 2: 9, 3: 8, 4: 8, 5: 7, 6: 7, 7: 6, 8: 6}      # 바르게 쓰면 9, 18, 18, ...


class Tick(BehaviorModelExecutor):
    """주기마다 값을 내고, 받은 것을 적는 pyevsim 모델."""

    def __init__(self, instance_time, destruct_time, name, engine_name, period=1.0, keep=False):
        BehaviorModelExecutor.__init__(self, instance_time, destruct_time, name, engine_name)
        self.init_state("RUN")
        self.insert_state("RUN", period)
        self.insert_input_port("i")
        self.insert_output_port("o")
        self.keep, self.n, self.got = keep, 0, []

    def ext_trans(self, port, msg):
        self.got.append((SystemSimulator.get_engine(self.engine_name).get_global_time(), port, list(msg.retrieve())))
        if self.keep:
            self.cancel_rescheduling()

    def output(self):
        msg = SysMessage(self.get_name(), "o")
        msg.insert((self.get_name(), self.n))
        return msg

    def int_trans(self):
        self.n += 1


TICK = Module("Tick", {"i": ("T", "in"), "o": ("T", "out")}, (), {"period": ("float", 1.0), "keep": ("bool", False)}, Tick)


def native(name: str, **params) -> dict:
    return st.node({"i": ("T", "in"), "o": ("T", "out")}, module="Tick", params=params, name=name)


def test_native_bodies_are_called_the_pyevsim_way_and_recorded():
    plan = st.node({}, {"a": native("a", period=1.0), "b": native("b", period=100.0)}, ic=[(("a", "o"), ("b", "i"))])
    px = PyevsimExecutor(1.0, engine_name="native")
    sim = px.build(plan, {"Tick": TICK})
    faithful(px, sim, plan)
    a, b = sim.models[("a",)], sim.models[("b",)]
    assert (a.get_name(), a.get_engine_name(), a.get_create_time(), a.get_destruct_time()) == ("a", "native", 0, Infinite)
    assert sim.run(3.0) == [(1.0, ("a",), "o", ("a", 0)), (2.0, ("a",), "o", ("a", 1)), (3.0, ("a",), "o", ("a", 2))]
    assert b.got == [(1, "i", [("a", 0)]), (2, "i", [("a", 1)]), (3, "i", [("a", 2)])]
    assert sim.leaves() == {("a",): a, ("b",): b}
    sim.close()
    quiet = PyevsimExecutor(1.0, record=False).build(plan, {"Tick": TICK})
    assert quiet.run(3.0) == [] and quiet.models[("b",)].got == b.got
    quiet.close()


def test_native_body_must_have_the_declared_interface():
    px = PyevsimExecutor(1.0)
    plan = st.node({}, {"a": native("a")})
    with pytest.raises(TypeError, match="pyevsim 모델"):
        px.build(plan, {"Tick": Module("Tick", TICK.ports, (), {}, lambda *a, **k: object())})

    def late(t0, t1, name, engine, **params):                # 관례의 생성 시각을 쓰지 않는 본체
        return Tick(Infinite, t1, name, engine)

    with pytest.raises(ValueError, match="생성 시각"):
        px.build(plan, {"Tick": Module("Tick", TICK.ports, (), {}, late)})
    with pytest.raises(ValueError, match="소멸 시각"):
        px.build(plan, {"Tick": Module("Tick", TICK.ports, (), {}, lambda t0, t1, n, e: Tick(t0, 5, n, e))})
    with pytest.raises(ValueError, match="이름이 a 이 아니다"):
        px.build(plan, {"Tick": Module("Tick", TICK.ports, (), {}, lambda t0, t1, n, e: Tick(t0, t1, "mine", e))})
    more = st.node({}, {"a": st.node({"i": ("T", "in"), "o": ("T", "out"), "aux": ("T", "out")}, module="Tick", params={})})
    with pytest.raises(ValueError, match="출력 포트 aux"):
        px.build(more, {"Tick": TICK})
    flipped = st.node({}, {"a": st.node({"o": ("T", "in")}, module="Tick", params={})})
    with pytest.raises(ValueError, match="입력 포트 o"):
        px.build(flipped, {"Tick": TICK})

    class Shadow(Tick):
        def helper(self):
            return 1

        def __init__(self, *args):
            Tick.__init__(self, *args)
            self.insert_output_port("helper")

    with pytest.raises(ValueError, match="가린다"):
        px.build(plan, {"Tick": Module("Tick", TICK.ports, (), {}, Shadow)})
    fewer = st.node({}, {"a": st.node({"o": ("T", "out")}, module="Tick", params={})})       # 모듈의 남는 포트는 써도 된다
    sim = px.build(fewer, {"Tick": TICK})
    faithful(px, sim, fewer, exact_ports=False)
    assert px.observe(sim)["children"]["a"]["ports"] == {"i": (None, "in"), "o": ("T", "out")}
    sim.close()


def test_models_outside_the_plan_are_reported():
    plan = st.node({}, {"a": native("a"), "b": native("b")}, ic=[(("a", "o"), ("b", "i"))])
    px = PyevsimExecutor(1.0)
    sim = px.build(plan, {"Tick": TICK})
    faithful(px, sim, plan)
    stranger = Tick(0, Infinite, "stranger", sim.name)
    sim.engine.coupling_relation(sim.models[("a",)], "o", stranger, "i")       # 계획에 없는 모델로 가는 연결
    with pytest.raises(st.StructureError, match="stranger"):
        sim.connections()
    with pytest.raises(st.StructureError, match="stranger"):
        px.observe(sim)
    sim.close()
    sim = px.build(plan, {"Tick": TICK})
    sim.engine.register_entity(Tick(0, Infinite, "stranger", sim.name))        # 계획에 없는 모델
    with pytest.raises(st.StructureError, match="stranger"):
        px.observe(sim)
    sim.close()
    sim = px.build(plan, {"Tick": TICK})
    twin = Tick(0, Infinite, "a", sim.name)
    sim.engine.register_entity(twin)
    sim.where[id(twin)] = ("a",)
    with pytest.raises(st.StructureError, match="이름이 같은"):
        px.observe(sim)
    sim.close()


def test_native_and_common_models_in_one_plan():
    """섞으면 pyevsim 모델이 보낸 것은 pyevsim의 방식으로 온다.

    임박한 공통 모델이 아직 출력하지 않은 시각에 온 것은 그 차례의 묶음에 들고(겹친 전이), 그 밖에는
    받은 즉시 외부 전이가 된다. 엔진이 번호 순서로 처리하므로 어느 쪽인지는 만든 순서로 정해진다.
    """
    px = PyevsimExecutor(1.0)
    seen = {}
    for sender in ("a", "z"):                                # busy보다 앞선 이름과 뒤선 이름
        plan = st.node({}, {sender: native(sender, period=1.0), "busy": note(period=2.0), "quiet": note(),
                            "sink": native("sink", period=100.0)},
                       ic=[((sender, "o"), ("busy", "i")), ((sender, "o"), ("quiet", "i")), (("busy", "o"), ("sink", "i"))])
        sim = px.build(plan, {"Tick": TICK, "Note": NOTE})
        faithful(px, sim, plan)
        log = sim.run(4.0)
        leaves = sim.leaves()
        assert leaves[("quiet",)].seen == [("ext", float(t), 1.0, [(sender, t - 1)]) for t in (1, 2, 3, 4)]
        assert sim.models[("sink",)].got == [(2, "i", [("busy", 0)]), (4, "i", [("busy", 1)])]      # 공통 모델에서 pyevsim 모델로
        assert sorted((t, p) for t, p, _, _ in log) == sorted(
            [(float(t), (sender,)) for t in (1, 2, 3, 4)] + [(2.0, ("busy",)), (4.0, ("busy",))])
        seen[sender] = leaves[("busy",)].seen
        sim.close()
    assert seen["a"] == [("ext", 1.0, 1.0, [("a", 0)]), ("con", 2.0, [("a", 1)]),
                         ("ext", 3.0, 1.0, [("a", 2)]), ("con", 4.0, [("a", 3)])]
    assert seen["z"] == [("ext", 1.0, 1.0, [("z", 0)]), ("ext", 2.0, 0.0, [("z", 1)]),
                         ("ext", 3.0, 1.0, [("z", 2)]), ("ext", 4.0, 0.0, [("z", 3)])]


class Signal(Tick):
    """값이 없는 메시지를 신호로 보내는 pyevsim 모델."""

    def output(self):
        return SysMessage(self.get_name(), "o")


def test_a_bare_pyevsim_signal_reaches_a_common_model():
    plan = st.node({}, {"a": native("a", period=1.0), "k": note(period=2.0)}, ic=[(("a", "o"), ("k", "i"))])
    signal = Module("Tick", TICK.ports, (), TICK.params, Signal)
    sim = PyevsimExecutor(1.0).build(plan, {"Tick": signal, "Note": NOTE})
    sim.run(2.0)
    assert sim.leaves()[("k",)].seen == [("ext", 1.0, 1.0, []), ("con", 2.0, [])]      # 값은 없지만 입력은 왔다
    sim.close()


def test_root_ports_are_the_engine_boundary():
    plan = st.node({"x": ("T", "in"), "y": ("T", "out")}, {"k": note(period=2.0)},
                   eic=[("x", ("k", "i"))], eoc=[(("k", "o"), "y")])
    px = PyevsimExecutor(1.0)
    sim = px.build(plan, {"Note": NOTE})
    faithful(px, sim, plan)
    assert sim.engine.retrieve_input_ports() == ["x"] and sim.engine.retrieve_output_ports() == ["y"]
    sim.engine.insert_external_event("x", "early")           # pyevsim의 외부 입력
    sim.engine.insert_external_event("x", "with", 2)         # 모델이 낼 시각과 겹친다
    sim.run(3.0)
    k = sim.leaves()[("k",)]
    assert k.seen == [("ext", 0.0, 0.0, ["early"]), ("con", 2.0, ["with"])]
    assert [(t, v) for t, v in sim.engine.get_generated_event()] == [(2, [("k", 0)])]      # 포트 이름은 남지 않는다
    sim.close()


def test_lost_external_input_is_reported():
    plan = st.node({"x": ("T", "in")}, {"k": note()}, eic=[("x", ("k", "i"))])
    sim = PyevsimExecutor(1.0).build(plan, {"Note": NOTE})
    sim.engine.insert_external_event("x", "late", 3)
    with pytest.raises(RuntimeError, match="외부 입력 1개"):
        sim.run(5.0)                                         # 모든 모델이 쉬고 있어 엔진이 시각 0에서 끝난다
    sim.close()


def test_stalled_native_models_are_reported():
    """pyevsim은 격자 밖의 시각을 요청한 모델에서 오류 없이 멈춘다. run이 그것을 알린다."""
    plan = st.node({}, {"a": native("a", period=0.5), "b": native("b", period=2.0)})
    sim = PyevsimExecutor(1.0).build(plan, {"Tick": TICK})
    with pytest.raises(OffGrid, match="a: 요청 시각 0.5"):
        sim.run(6.0)
    assert sim.log == []                                     # 격자 위에 있는 b도 처리되지 않았다
    sim.close()
    fine = PyevsimExecutor(0.5).build(plan, {"Tick": TICK})
    assert len(fine.run(6.0)) == 12 + 3
    fine.close()

    mixed = st.node({}, {"a": native("a", period=0.5), "k": note(period=2.0)})
    sim = PyevsimExecutor(1.0).build(mixed, {"Tick": TICK, "Note": NOTE})
    with pytest.raises(OffGrid, match="a: 요청 시각 0.5"):    # 뒤에 놓인 공통 모델이 아니라 멈추게 한 모델을 알린다
        sim.run(6.0)
    sim.close()

    class Lost(Tick):                                        # 등록하지 않은 상태로 가면 시간 전진이 -1이 된다
        def int_trans(self):
            self._cur_state = "NOPE"

    sim = PyevsimExecutor(1.0).build(st.node({}, {"a": native("a")}), {"Tick": Module("Tick", TICK.ports, (), {}, Lost)})
    with pytest.raises(OffGrid):
        sim.run(4.0)
    sim.close()


# ---------------------------------------------------------------------------
# 규약 P1: 포트 이름
# ---------------------------------------------------------------------------

NAMES = {
    "ses": "1.0", "name": "R", "port_types": {"T": {}},
    "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["Src", "Dst"],
                                              "couplings": [{"from": "Src.output", "to": "Dst.i"}]}}},
        "Src": {"ports": {"output": {"type": "T", "direction": "out"}}},
        "Dst": {"ports": {"i": {"type": "T", "direction": "in"}}},
    },
}


def test_port_names_must_not_shadow_pyevsim_attributes():
    lib = {"S": Module("S", {"output": ("T", "out")}, (), {}, generic({"output": ("T", "out")})),
           "D": Module("D", {"i": ("T", "in")}, (), {}, generic({"i": ("T", "in")}))}
    binding = Binding("x", {"Src": Bind("S"), "Dst": Bind("D")})
    L0 = unfold_layered(load_ses_dict(NAMES))
    dx, px = DevsExecutor(), PyevsimExecutor(0.25)
    L, de = X.attach(L0, dx, binding, lib)
    L, pe = X.attach(L, px, binding, lib)
    (V,) = sem(L.ses)
    assert X.executable(L, de, V) and not X.executable(L, pe, V)         # 같은 SES가 참조 실행기로는 된다
    found = violations(X.alone(L, pe), V)
    assert [(code, path) for _, code, path, _ in found] == [("P1", ("R", "a", "Src"))]
    with pytest.raises(ValueError, match="output"):
        px.build(X.plan(L, pe, V), lib)
    a = analyze(E.from_dict(NAMES), attach=lambda L1: X.attach(L1, px, binding, lib)[0])      # 편집기의 진단으로 나온다
    assert [x.code for x in a.errors] == ["P1", "NOWF"]                   # 이름 하나 때문에 만들 수 있는 변이가 없다
    (d,) = a.of("P1")
    assert (d.code, d.layer, d.address, d.affected) == ("P1", "exec:pyevsim", "entities/Src", (1, 1))
    # 뿌리의 포트는 엔진의 속성과 겹치면 안 된다. 복합의 포트는 엔진에 오르지 않으므로 상관없다
    inner = st.node({"simulate": ("T", "out"), "output": ("T", "out")}, {"a": st.node({"o": ("T", "out")})})
    plan = st.node({"port_map": ("T", "out"), "output": ("T", "out"), "fine": ("T", "in")}, {"box": inner})
    assert [(c, p, m.split()[2]) for c, p, m in px.check(plan)] == [("P1", (), "port_map")]
    assert px.check(st.node({"_atom": ("T", "in"), "RequestedTime": ("T", "in"), "in": ("T", "in")})) != []
    assert [m.split()[2] for _, _, m in px.check(st.node({"_atom": ("T", "in"), "_states": ("T", "in"),
                                                       "in": ("T", "in"), "out": ("T", "out")}))] == ["_atom", "_states"]


@fact
def test_fact_port_registration_overwrites_attributes():
    m = BehaviorModelExecutor(0, Infinite, "m", "e")
    assert callable(m.output)
    m.insert_output_port("output")
    assert m.output == "output"                              # 출력 함수가 문자열로 바뀌었다


# ---------------------------------------------------------------------------
# 확인한 사실: pyevsim 1.1.7의 엔진 (15 문서 2절의 표)
# ---------------------------------------------------------------------------

def engine(step=1) -> SysExecutor:
    return SystemSimulator.register_engine("fact", "VIRTUAL_TIME", step)


def ticks(e, *specs, cls=Tick) -> list:
    out = []
    for name, period, keep in specs:
        m = cls(0, Infinite, name, "fact", period, keep)
        e.register_entity(m)
        out.append(m)
    return out


@fact
def test_fact_structural_model_keeps_one_external_output_coupling():
    s, inner = StructuralModel("s"), Tick(0, Infinite, "i", "fact")
    s.insert_model(inner)
    s.insert_external_output_coupling(inner, "o", "x")
    s.insert_external_output_coupling(inner, "o", "y")
    assert list(s.retrieve_external_output_coupling().values()) == [(s, "y")]       # x로 가는 결합이 사라졌다


@fact
def test_fact_a_coupling_registered_twice_delivers_twice():
    e = engine()
    a, b = ticks(e, ("a", 1, False), ("b", 100, False))
    e.coupling_relation(a, "o", b, "i")
    e.coupling_relation(a, "o", b, "i")
    e.simulate(2, False)
    assert b.got == [(1, "i", [("a", 0)]), (1, "i", [("a", 0)])]


@fact
def test_fact_events_off_the_time_grid_stall_the_engine_silently():
    e = engine(1)
    a, b = ticks(e, ("a", 0.5, False), ("b", 2, False))
    e.simulate(6, False)
    assert (a.n, b.n, e.get_global_time()) == (0, 0, 6)      # 오류 없이 끝까지 가고 아무것도 처리되지 않았다


@fact
def test_fact_simulate_excludes_the_end_time():
    e = engine(1)
    (a,) = ticks(e, ("a", 1, False))
    e.simulate(3, False)
    assert (a.n, e.get_global_time()) == (2, 3)              # 시각 1과 2만 처리했다


@fact
def test_fact_a_receiver_due_at_the_same_time_loses_its_turn():
    e = engine()
    a, b = ticks(e, ("a", 1, False), ("b", 1, False))
    e.coupling_relation(a, "o", b, "i")
    e.simulate(5, False)
    assert (a.n, b.n) == (4, 0)                              # b는 받을 때마다 다음 사건이 미뤄져 한 번도 내지 못한다
    class Trace(Tick):
        def output(self):
            self.got.append("out")
            return Tick.output(self)

    e = engine()
    (a,), (b,) = ticks(e, ("a", 1, False)), ticks(e, ("b", 1, True), cls=Trace)
    e.coupling_relation(a, "o", b, "i")
    e.simulate(5, False)
    assert (a.n, b.n) == (4, 4)                              # cancel_rescheduling을 부르면 차례를 지킨다
    assert b.got[:2] == [(1, "i", [("a", 0)]), "out"]        # 그때에도 같은 시각의 입력이 출력보다 먼저 반영된다


@fact
def test_fact_input_restarts_the_receivers_timer():
    for keep, outputs in ((False, 0), (True, 2)):
        e = engine()
        a, b = ticks(e, ("a", 1, False), ("b", 3, keep))
        e.coupling_relation(a, "o", b, "i")
        e.simulate(8, False)
        assert b.n == outputs                                # 주기 3인 모델이 시각 7까지 낸 횟수


@fact
def test_fact_a_model_coupled_to_itself_waits_twice():
    e = engine()
    (s,) = ticks(e, ("s", 2, False))
    e.coupling_relation(s, "o", s, "i")
    e.simulate(13, False)
    assert [t for t, _, _ in s.got] == [2, 6, 10]            # 주기 2가 4가 된다


@fact
def test_fact_boundary_output_has_no_port_name_and_passive_engines_drop_input():
    e = engine()
    (a,) = ticks(e, ("a", 1, False))
    e.coupling_relation(a, "o", None, "x")
    e.coupling_relation(a, "o", None, "y")
    e.simulate(2, False)
    assert list(e.get_generated_event()) == [(1, [("a", 0)]), (1, [("a", 0)])]
    for when, received in ((0, 1), (3, 0)):
        e = engine()
        (r,) = ticks(e, ("r", Infinite, False))
        e.insert_input_port("x")
        e.coupling_relation(None, "x", r, "i")
        e.insert_external_event("x", "hello", when)
        e.simulate(10, False)
        assert len(r.got) == received                        # 시각 3의 입력은 전달되지 않는다. 엔진이 시각 0에서 끝난다


@fact
def test_fact_unconnected_output_adds_a_route_to_the_default_catcher():
    e = engine()
    (a,) = ticks(e, ("a", 1, False))
    assert e.port_map == {}
    e.simulate(2, False)
    assert e.port_map == {(a, "o"): [(e.dmc, "uncaught")]}


@fact
def test_fact_default_creation_time_is_infinite_and_list_output_is_copied():
    assert BehaviorModelExecutor(name="m", engine_name="e").get_create_time() == Infinite
    e = engine()
    never = Tick(Infinite, Infinite, "never", "fact")
    e.register_entity(never)
    e.simulate(5, False)
    assert never.n == 0                                      # 시작되지 않는다

    class Send(Tick):
        def output(self):
            self.sent = {"k": 1}
            msg = SysMessage(self.get_name(), "o")
            msg.insert(self.sent)
            return [msg] if self.keep else msg

    for as_list, same in ((False, True), (True, False)):
        e = engine()
        a, b = ticks(e, ("a", 1, as_list), cls=Send) + ticks(e, ("b", 100, False))
        e.coupling_relation(a, "o", b, "i")
        e.simulate(2, False)
        assert (b.got[0][2][0] is a.sent) == same


# ---------------------------------------------------------------------------
# 표본이 공허하지 않은가
# ---------------------------------------------------------------------------

def test_pyevsim_samples_are_not_vacuous():
    if not STATS["events"]:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["events"] >= 3000 and STATS["delivered"] >= 500 and STATS["same_instant"] >= 300, STATS
    assert STATS["multiple"] >= 10 and STATS["to_itself"] >= 20 and STATS["boundary"] >= 100, STATS
    assert STATS["realized"] >= 300 and STATS["doc_events"] >= 500, STATS
    assert STATS["black_box"] >= 100 and STATS["realized"] - STATS["root_atom"] >= 100, STATS
    assert STATS["quirky_events"] >= 1000 and STATS["quirky_bags"] >= 500, STATS
