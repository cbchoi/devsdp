"""cevsim 실행기 (docs/ses-platform/16_cevsim_executor.md).

합격 기준은 pyevsim 실행기와 같다 (14 문서의 결정 D1).
- 충실성: 엔진에서 다시 읽은 모델과 연결이 계획의 것과 같다. 연결은 길의 수까지 같다.
- 사건 기록: 같은 모델베이스를 참조 시뮬레이터(devs.py)와 cevsim에서 돌린 출력 사건의 열이 같다.

cevsim의 소스와 C++ 컴파일러가 있어야 돈다. 환경 변수 CEVSIM_HOME에 cevsim의 main을 받아 둔 자리를 준다.
없으면 건너뛴다. 엔진의 성질을 적어 둔 시험은 확인한 커밋(45e7fa9)에서만 돈다.
"""

import collections
import glob
import os
import random
import shutil
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from ses_core import cevsim_executor as C  # noqa: E402

HOME = os.environ.get("CEVSIM_HOME", "")
if not C.available(HOME):
    pytest.skip("실행기가 맞춘 cevsim의 소스(CEVSIM_HOME)나 C++ 컴파일러가 없다", allow_module_level=True)

from docgen import rand_binding, rand_system_document  # noqa: E402
from pdevs_models import NOTE, Burst, Keep, Pair, Ring, Spin, as_plan, flat_plan, note  # noqa: E402
from test_executor import UNIT, Sometimes, Witness, generic, library_of, quirky, state  # noqa: E402
from test_structure import rand_structure  # noqa: E402

from examples import processing_mb, sensor_node_mb  # noqa: E402
from ses_core import devs, hw, load_ses, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core import structure as st  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.cevsim_executor import BuildError, CevsimExecutor, Native  # noqa: E402
from ses_core.devs import INF, Atomic, DevsExecutor, simulate  # noqa: E402
from ses_core.diagnose import analyze  # noqa: E402
from ses_core.executor import Bind, Binding, Module, OffGrid  # noqa: E402
from ses_core.decisions import load_decisions, patterns  # noqa: E402
from ses_core.extension import interpret, prune, violations  # noqa: E402
from ses_core.unfold import unfold_layered  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")
MODELS = os.path.join(os.path.dirname(__file__), "cevsim_models.cpp")
FACTS = os.path.join(os.path.dirname(__file__), "cevsim_facts.cpp")
STATS: collections.Counter = collections.Counter()


def commit() -> str:
    done = subprocess.run(["git", "-C", HOME, "rev-parse", "HEAD"], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


PINNED = commit() == "45e7fa966214734339b39ef393e536a6f6fefc17"
fact = pytest.mark.skipif(not PINNED, reason="cevsim 45e7fa9에서 확인한 사실이다. 다른 커밋에서는 다시 확인해야 한다")


def executor(**options) -> CevsimExecutor:
    """시험은 모두 같은 라이브러리를 쓴다. 고유 모델의 소스를 함께 컴파일한 것이다."""
    return CevsimExecutor(HOME, sources=[MODELS], **options)


# ---------------------------------------------------------------------------
# 도구
# ---------------------------------------------------------------------------

def label(plan: dict, path: tuple) -> str:
    return C.ref(path) or plan.get("name", "") or "root"


def faithful(cx: CevsimExecutor, sim, plan: dict, exact_ports: bool = True) -> None:
    """충실성: 엔진에서 다시 읽은 것이 계획의 평탄한 꼴이다. 엔진에 더 올린 것은 정해진 것뿐이다."""
    assert sim.connections() == st.flatten(plan)             # 연결과 그 길의 수
    seen = cx.observe(sim)
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
    extra = sim.infrastructure()                             # 계획에 없는 것: 전이를 맡는 모델과 공통 모델마다 연결 둘
    names = sorted(c.name for c in sim.cells.values())
    assert extra["models"] == ([C.KEEPER] if names else [])
    assert extra["couplings"] == collections.Counter(
        [(n, C.WAKE, C.KEEPER, C.WAKE) for n in names] + [(C.KEEPER, C.COMMIT, n, C.COMMIT) for n in names])


def boundary(log: list, plan: dict, first=lambda value: True) -> list:
    """기록과 계획에서 셈한, 뿌리의 출력 포트로 나갔어야 할 것: (시각, 뿌리의 포트, 낸 원자의 경로).

    엔진은 한 번의 출력에서 포트마다 메시지 하나를 내고, 그것을 경계로 가는 길의 수만큼 내보낸다.
    first는 기록의 값이 그 메시지의 첫 값인지를 답한다.
    """
    roots: dict = {}
    for ((a, ap), (b, bp)), k in sorted(st.flatten(plan).items()):
        if not b:
            roots.setdefault((a, ap), []).extend([bp] * k)
    return [(t, root, p) for t, p, port, value in log if first(value) for root in roots.get((p, port), ())]


def on_both(plan: dict, lib: dict, until: float, first=lambda value: True, **options) -> tuple:
    """같은 계획과 같은 라이브러리를 두 실행기로 만들어 돌린다."""
    model = DevsExecutor().build(plan, lib)
    log = simulate(model, until)
    cx = executor(**options)
    sim = cx.build(plan, lib)
    try:
        faithful(cx, sim, plan)
        mine = list(sim.run(until))
        faithful(cx, sim, plan)                              # 돌린 뒤에도 같다
        assert sim.outputs() == boundary(mine, plan, first)  # 엔진의 경계로 나간 것이 계획의 연결대로다
        STATS["boundary_outputs"] += len(sim.outputs())
        return log, mine, devs._leaves(model), sim.leaves()
    finally:
        sim.close()


def attach_both(doc_name: str, binding_name: str, library: dict):
    L = unfold_layered(load_ses(os.path.join(EXAMPLES, doc_name)))
    b = X.load_binding(os.path.join(EXAMPLES, binding_name))
    dx, cx = DevsExecutor(), executor()
    L, de = X.attach(L, dx, b, library)
    L, ce = X.attach(L, cx, Binding("cevsim", b.map, b.target, b.time_unit), library)
    return L, (dx, de), (cx, ce)


def run_both(L, de_pair, ce_pair, V, until):
    (dx, de), (cx, ce) = de_pair, ce_pair
    model = X.realize(L, de, dx, V)
    log = simulate(model, until)
    sim = X.realize(L, ce, cx, V)
    try:
        faithful(cx, sim, X.plan(L, ce, V))
        mine = list(sim.run(until))
        faithful(cx, sim, X.plan(L, ce, V))
        assert sim.outputs() == boundary(mine, X.plan(L, ce, V))
        return log, mine, devs._leaves(model), sim.leaves()
    finally:
        sim.close()


# ---------------------------------------------------------------------------
# 예시: 같은 SES, 같은 모델베이스, 실행기만 cevsim
# ---------------------------------------------------------------------------

def test_processing_system_on_cevsim_gives_the_reference_log():
    L, D, Cx = attach_both("processing_system.ses.yaml", "processing_system.binding.devs.yaml", processing_mb.LIBRARY)
    variants = sem(L.ses)
    assert len(variants) == 15 and X.executable_variants(L, Cx[1]) == variants
    for V in variants:
        ref, log, r_leaves, leaves = run_both(L, D, Cx, V, 20.0)
        assert log == ref and state(leaves) == state(r_leaves)       # 사건의 열과 마지막 상태가 같다
        servers = [a for p, a in leaves.items() if p[0] == "ServerPool"]
        assert leaves[("Generator",)].count == 20            # 시각 20의 사건도 처리한다
        assert leaves[("Collector",)].done == r_leaves[("Collector",)].done
        assert len(leaves[("Collector",)].done) == (9 if len(servers) == 1 else 18)
        STATS["example_events"] += len(log)


def test_cevsim_binding_file_and_decision_file_to_a_running_engine():
    L0 = unfold_layered(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))
    binding = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.cevsim.yaml"))
    assert binding.executor == "cevsim" == CevsimExecutor.name
    cx = executor()
    L, ext = X.attach(L0, cx, binding, processing_mb.LIBRARY)
    ds = load_decisions(os.path.join(EXAMPLES, "processing_system.decisions.yaml"))
    (V,) = sem(prune(L, *patterns(L.ses, ds)).ses)
    sim = X.realize(L, ext, cx, V)
    leaves = sim.leaves()
    assert type(leaves[("Buffer",)]).__name__ == "PriorityBuffer"
    assert sorted(p[1] for p in leaves if p[0] == "ServerPool") == ["server_0", "server_1", "server_2", "server_3"]
    assert sim.dump()["models"][sim.models[("ServerPool", "server_2")]] == ("hosted", "ServerPool/server_2")
    sim.run(20.0)
    assert len(leaves[("Collector",)].done) == 18
    sim.close()


def test_black_box_binding_on_cevsim():
    b = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.devs.yaml"))
    box = Binding("cevsim", {**{k: v for k, v in b.map.items() if k != "Server"}, "ServerPool": Bind("Pool")}, b.target)
    L0 = unfold_layered(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))
    dx, cx = DevsExecutor(), executor()
    L, de = X.attach(L0, dx, box, processing_mb.LIBRARY)
    L, ce = X.attach(L, cx, box, processing_mb.LIBRARY)
    for V in sem(L.ses):
        ref, log, _, leaves = run_both(L, (dx, de), (cx, ce), V, 20.0)
        assert log == ref and sorted(leaves) == [("Buffer",), ("Collector",), ("Generator",), ("ServerPool",)]
        assert len(leaves[("Collector",)].done) == 9


def test_sensor_node_on_cevsim_and_hardware():
    L, D, Cx = attach_both("sensor_node.ses.yaml", "sensor_node.binding.devs.yaml", sensor_node_mb.LIBRARY)
    with open(os.path.join(EXAMPLES, "sensor_node.hwlib.yaml"), encoding="utf-8") as f:
        lib = yaml.safe_load(f)
    hx = hw.HwExecutor(hw.load_rules(lib))
    L, he = X.attach(L, hx, X.load_binding(os.path.join(EXAMPLES, "sensor_node.binding.hw.yaml")), X.load_library_dict(lib))
    variants = sem(L.ses)
    cx_ok, hw_ok = set(X.executable_variants(L, Cx[1])), set(X.executable_variants(L, he))
    assert (len(variants), len(cx_ok), len(cx_ok & hw_ok)) == (112, 56, 8)
    assert cx_ok == set(X.executable_variants(L, D[1]))
    for V in sorted(cx_ok, key=sorted):
        ref, log, r_leaves, leaves = run_both(L, D, Cx, V, 5.0)
        assert log == ref and len(leaves[("Radio",)].received) == 5
        assert leaves[("Radio",)].received == r_leaves[("Radio",)].received
        STATS["example_events"] += len(log)
    # 정리 19: 실행 가능 핵은 실행기를 얹는 순서와 무관하다
    core = X.exec_core(X.exec_core(L, Cx[1]), he)
    assert set(sem(core.ses)) == set(sem(X.exec_core(X.exec_core(L, he), Cx[1]).ses)) == cx_ok & hw_ok
    # 따름정리 18.1: 엔진의 연결과 배선표의 연결이 같다
    for V in cx_ok & hw_ok:
        sim, board = X.realize(L, Cx[1], Cx[0], V), X.realize(L, he, hx, V)
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
    plan, lib = as_plan(rand_structure(random.Random(seed)))
    ref, log, r_leaves, leaves = on_both(plan, lib, 8.0)
    assert log == ref and state(leaves) == state(r_leaves)
    flat = st.flatten(plan)
    at = collections.Counter(t for t, _ in {(t, p) for t, p, _, _ in log})
    STATS["events"] += len(log)
    STATS["connections"] += len(flat)
    STATS["multiple"] += sum(1 for k in flat.values() if k > 1)
    STATS["to_itself"] += sum(1 for (s, _), (t, _) in flat if s == t and s)
    STATS["boundary"] += sum(1 for (s, _), (t, _) in flat if not s or not t)
    STATS["same_instant"] += sum(1 for k in at.values() if k > 1)


@pytest.mark.parametrize("seed", range(200))
def test_random_structures_with_empty_and_multiple_outputs(seed):
    """출력이 값을 0개, 1개, 2개 가질 때에도 기록과 상태가 참조와 같다. 묶음의 내용과 순서까지 본다."""
    plan, lib = as_plan(rand_structure(random.Random(seed)), body=quirky)
    ref, log, r_leaves, leaves = on_both(plan, lib, 8.0, first=lambda value: value[2] == 0)
    assert log == ref and state(leaves) == state(r_leaves)
    STATS["quirky_events"] += len(log)
    STATS["quirky_bags"] += sum(1 for a in leaves.values() for h in a.heard if h[0] != "both")


@pytest.mark.parametrize("seed", range(150))
def test_random_documents_faithful_and_same_log(seed):
    rng = random.Random(seed)
    d = rand_system_document(rng)
    b, mods = rand_binding(rng, d, "cevsim")
    dx, cx = DevsExecutor(), executor()
    L = unfold_layered(load_ses_dict(d))
    b = dict(b, time_unit=UNIT)                              # 시간 단위는 바인딩에 적는다. 두 실행기가 계획에서 읽는다
    L, de = X.attach(L, dx, Binding.from_dict(b), library_of(mods))
    L, ce = X.attach(L, cx, Binding.from_dict(b), library_of(mods))
    variants = sem(L.ses)
    good = [V for V in variants if X.executable(L, ce, V)]
    assert good == [V for V in variants if X.executable(L, de, V)]      # 이 문서들에는 cevsim의 규약에 걸리는 이름이 없다
    for V in good[:4]:
        ref, log, r_leaves, leaves = run_both(L, (dx, de), (cx, ce), V, 6.0)
        assert log == ref and state(leaves) == state(r_leaves)
        p, whole = X.plan(L, ce, V), interpret(L, V)["devs"]
        STATS["realized"] += 1
        STATS["doc_events"] += len(log)
        STATS["black_box"] += any(not st.is_atom(st.subtree(whole, a)) for a in X.frontier(p))
        STATS["root_atom"] += st.is_atom(p)
    for bad in [V for V in variants if V not in good][:1]:
        with pytest.raises(ValueError):
            X.realize(L, ce, cx, bad)


# ---------------------------------------------------------------------------
# 공통 모델 기반을 올렸을 때: 병렬 DEVS의 규약
# ---------------------------------------------------------------------------

def test_confluent_transition_is_the_models_own():
    plan, lib = flat_plan({"a": Ring, "b": Ring}, ic=[(("a", "o"), ("b", "i")), (("b", "o"), ("a", "i"))])
    ref, log, r_leaves, leaves = on_both(plan, lib, 7.0)
    assert log == ref and len(log) == 8
    for p in r_leaves:
        assert leaves[p].trace == r_leaves[p].trace
    assert [kind for kind, *_ in leaves[("a",)].trace] == ["con"] * 4      # 둘이 늘 같은 시각에 낸다


def test_a_model_that_only_receives_does_not_take_a_turn():
    """공통 모델끼리 주고받을 때 받기만 한 모델에는 차례가 오지 않는다. 낸 모델이 전이를 맡는 모델을 이미 깨웠기 때문이다."""
    plan, lib = flat_plan({"p": Pair, "k": Keep}, ic=[(("p", "o"), ("k", "i"))])
    sim = executor().build(plan, lib)
    assert len(sim.run(5.0)) == 10 and len(sim.leaves()[("k",)].seen) == 5
    assert sim.turns == 5                                    # p가 다섯 번 냈다. k는 한 번도 차례를 받지 않았다
    sim.close()


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
    ref, log, r_leaves, leaves = on_both(plan, lib, 2.0, first=lambda value: value[2] == 0)
    assert log == ref
    assert leaves[("k",)].seen == r_leaves[("k",)].seen
    first = leaves[("k",)].seen[0]
    assert first[:2] == (1.0, 1.0)
    assert first[2]["i"] == [("box/e", 0, 0), ("box/e", 0, 0), ("box/e", 0, 1), ("box/e", 0, 1), ("z", 0, 0), ("z", 0, 1)]


def test_zero_time_rounds_at_one_instant():
    plan, lib = flat_plan({"a": Burst, "b": Burst}, ic=[(("a", "o"), ("b", "i")), (("b", "o"), ("a", "i"))])
    ref, log, r_leaves, leaves = on_both(plan, lib, 3.0)
    assert log == ref and [t for t, *_ in log] == [1.0] * 6      # 세 차례가 모두 시각 1에 돈다
    assert leaves[("a",)].got == r_leaves[("a",)].got


def test_an_output_without_values_is_not_sent():
    plan, lib = flat_plan({"s": Sometimes, "w": Witness}, ic=[(("s", "o"), ("w", "i"))])
    ref, log, r_leaves, leaves = on_both(plan, lib, 4.0)
    assert log == ref == [(2.0, ("s",), "o", 1), (4.0, ("s",), "o", 3)]
    assert leaves[("w",)].seen == r_leaves[("w",)].seen == [(2.0, 2.0, {"i": [1]}), (4.0, 2.0, {"i": [3]})]


def test_output_on_an_undeclared_port_is_recorded_and_goes_nowhere():
    """모듈이 계획에 없는 포트로 낸 것은 기록에 남고 어디에도 전달되지 않는다. 참조 시뮬레이터와 같다."""
    wide = {"o": ("T", "out"), "spare": ("T", "out")}
    plan = st.node({}, {"g": st.node({"o": ("T", "out")}, module="G", params={}), "w": st.node(Witness.PORTS, module="W", params={})},
                   ic=[(("g", "o"), ("w", "i"))], time_unit=UNIT)
    lib = {"G": Module("G", wide, (), {}, generic(wide)), "W": devs.module_of(Witness, "W")}
    ref, log, r_leaves, leaves = on_both(plan, lib, 4.0)
    assert log == ref and sorted(port for _, _, port, _ in log) == ["o", "spare"]
    assert leaves[("w",)].seen == r_leaves[("w",)].seen and len(leaves[("w",)].seen) == 1


def test_ticks_and_engine_times_must_agree():
    """공통 모델의 눈금과 엔진의 시각이 어긋나면 드러난다. 엔진이 사건을 지나쳤거나 다른 눈금에 차례를 준 경우다."""
    plan, lib = flat_plan({"r": Ring})
    sim = executor().build(plan, lib)
    i = sim.models[("r",)]
    c = sim.cells[i]
    assert sim._ta(i) == 1.0 and sim._ta(sim.keeper) == -1.0     # 한 눈금 뒤에 낸다. 전이를 맡는 모델은 쉬고 있다
    sim.run(3.0)
    assert (sim.tick(), c.due, c.last) == (3, 4, 3) and sim._ta(i) == 1.0
    sim._ext(i, C.COMMIT.encode(), sim.keeper, C.COMMIT.encode())    # 전이 신호: 아무 일도 없던 모델은 전이하지 않는다
    assert sim.leaves()[("r",)].trace == [("int", 1.0), ("int", 2.0), ("int", 3.0)] and (c.due, c.last) == (4, 3)
    assert sim.turns == 3                                    # 낼 때마다 차례가 한 번씩 왔다
    c.due = 2
    with pytest.raises(RuntimeError, match="r: 눈금 2 의 사건을 엔진이 지나쳤다"):
        sim._ta(i)
    with pytest.raises(RuntimeError, match="r: 눈금 2 의 사건을 엔진이 눈금 3 에 처리했다"):
        sim._out(i)
    sim.close()


def test_the_transition_model_first_gives_a_turn_to_a_model_that_is_due():
    """전이를 맡는 모델의 차례가 왔는데 그 눈금에 낼 모델이 아직 내지 않았으면, 전이 신호 대신 차례를 주는 신호를 보낸다."""
    plan, lib = flat_plan({"a": Ring, "b": Ring})
    sim = executor().build(plan, lib)
    a, b = sim.models[("a",)], sim.models[("b",)]
    sim.run(0.0)                                             # 엔진이 모델을 올렸다. 시각 0이고 둘 다 눈금 1에 낸다
    sim.cells[a].due = sim.cells[b].due = 0                  # 둘 다 지금 낼 차례인데 엔진이 차례를 주지 않았다고 하자
    sim._awake = True
    sim._out(sim.keeper)
    assert sim._giving and sim._awake                        # 차례를 주는 신호를 보냈고, 다시 차례를 받으려고 깨어 있다

    def signal(i):
        return (i, C.COMMIT.encode(), sim.keeper, C.COMMIT.encode())

    sim.cells[b].due = 5
    sim._ext(*signal(a))
    sim._ext(*signal(b))                                     # 신호를 받은 뒤에 엔진이 다음 사건까지 남은 시간을 다시 묻는다
    assert sim._ta(a) == 0.0 and sim._ta(b) == 5.0           # 낼 차례인 모델은 지금, 아닌 모델은 제 눈금에
    assert sim.leaves()[("a",)].trace == [] and sim._rounds == 0     # 누구도 전이하지 않았고 차례 수에도 세지 않는다
    sim.close()
    passive = executor().build(*flat_plan({"k": Echo}))      # 엔진에 잡힌 사건이 없는데 낼 눈금이 남았다면 드러난다
    passive.run(1.0)
    passive.cells[passive.models[("k",)]].due = 1
    with pytest.raises(RuntimeError, match="엔진의 일정에 남은 사건이 없다"):
        passive.run(1.0)
    passive.close()


def test_endless_zero_time_transitions_are_stopped():
    plan, lib = flat_plan({"s": Spin})
    sim = executor(max_rounds=50).build(plan, lib)
    with pytest.raises(RuntimeError, match="걸음 수"):
        sim.run(1.0)
    assert len(sim.log) == 0 and sim.now() == 0.0            # Spin은 값을 내지 않는다. 시계는 시각 0에 멈췄다
    sim.close()
    sim = executor(max_rounds=3).build(*flat_plan({"a": Burst, "b": Burst}, ic=[(("a", "o"), ("b", "i")), (("b", "o"), ("a", "i"))]))
    assert len(sim.run(3.0)) == 6                            # 한 시각에 세 차례까지는 된다
    sim.close()
    sim = executor(max_rounds=1).build(*flat_plan({"p": Pair}))
    assert len(sim.run(3.0)) == 6                            # 한도는 한 시각 안의 차례 수다. 시각이 바뀌면 다시 센다
    sim.close()


class Tenth(Atomic):
    """0.1마다 낸다. 0.1은 이진수로 정확히 적을 수 없는 수다."""
    PORTS = {"o": ("T", "out")}

    def init(self):
        self.k = 0

    def ta(self):
        return 0.1

    def output(self):
        return {"o": [self.k]}

    def internal(self):
        self.k += 1


def test_common_model_time_is_counted_in_ticks():
    """공통 모델의 시각은 시간 단위의 눈금이다. 엔진이 시각을 더하면서 생기는 끝자리 차이가 기록에 들어오지 않는다."""
    plan, lib = flat_plan({"d": Tenth})                      # 0.1마다 낸다. 0.1은 이진수로 정확히 적히지 않는다
    with pytest.raises(OffGrid, match="d: 시간 전진 0.1 이 시간 단위 1.0 의 배수가 아니다"):
        executor().build(plan, lib)                          # 시간 단위를 적지 않으면 1이다
    ref = simulate(DevsExecutor(0.1).build(plan, lib), 1.0)
    sim = executor(time_unit=0.1).build(plan, lib)
    log = list(sim.run(1.0))
    assert log == ref and [t for t, *_ in log] == [k * 0.1 for k in range(1, 11)]      # 눈금 수에 시간 단위를 곱한 값
    # 엔진에서 열째 사건의 시각은 0.1을 열 번 더한 값이고 1.0보다 끝자리만큼 뒤다. 그래도 눈금 10의 사건으로 처리한다
    assert sim.tick() == 10 and sim.cells[sim.models[("d",)]].due == 11
    assert sim.run(1.0) == ref and sim.run(0.5) == ref       # 같은 끝 시각이나 지난 시각으로 다시 불러도 그대로다
    assert [t for t, *_ in sim.run(1.2)][10:] == [11 * 0.1, 12 * 0.1]
    sim.close()
    with pytest.raises(ValueError, match="시간 단위가 서로 다르다"):       # 계획에 적힌 것과 실행기에 준 것이 다르다
        executor(time_unit=0.5).build(*as_plan(st.node({}, {"b": st.node({"o": ("T", "out")})})))
    with pytest.raises(ValueError, match="0보다 커야 한다"):
        executor(time_unit=0)


def test_an_input_at_the_tick_of_the_engines_clock_is_an_input_now():
    """엔진의 시계가 눈금의 시각보다 끝자리만큼 뒤에 있어도, 그 눈금의 시각으로 넣은 입력은 지금의 입력이다."""
    plan = st.node({"x": ("T", "in")}, {"d": st.node(Tenth.PORTS, module="Tenth", params={}),
                                        "k": st.node(Echo.PORTS, module="Echo", params={})}, eic=[("x", ("k", "i"))], time_unit=0.1)
    sim = executor().build(plan, {"Tenth": devs.module_of(Tenth), "Echo": devs.module_of(Echo)})
    sim.run(0.3)
    assert sim.tick() == 3 and [e[0] for e in sim.log] == [0.1, 0.2, 3 * 0.1]
    sim.inject("x", 0.3)                                     # 0.3은 엔진의 시각(0.1을 세 번 더한 값)보다 끝자리만큼 앞이다
    assert sim.run(0.3)[3:] == [(3 * 0.1, ("k",), "o", "k")]
    assert sim.leaves()[("k",)].seen == [(3 * 0.1, 3 * 0.1, {"i": [None]})]
    with pytest.raises(ValueError, match="이미 지난 시각"):
        sim.inject("x", 0.2)                                 # 앞선 눈금은 지난 시각이다
    sim.close()


def test_a_native_event_off_the_grid_cannot_reach_a_common_model():
    """고유 모델은 눈금 밖의 시각에도 낼 수 있다. 그 출력이 공통 모델에 닿으면 OffGrid다."""
    alone = st.node({}, {"n": tick(period=0.5)})
    sim = executor().build(alone, NATIVE)
    assert sim.run(1.0) == [(0.5, ("n",), "out", None), (1.0, ("n",), "out", None)]      # 눈금 밖의 시각은 그대로 적는다
    with pytest.raises(OffGrid, match="엔진의 시각 1.5"):
        sim.run(1.5) and sim.tick()
    sim.close()
    mixed = st.node({}, {"n": tick(period=0.5), "w": st.node(Witness.PORTS, module="W", params={})}, ic=[(("n", "out"), ("w", "i"))])
    sim = executor().build(mixed, {**NATIVE, "W": devs.module_of(Witness, "W")})
    with pytest.raises(OffGrid, match="w: 시각 0.5 에 입력을 받았다. 시간 단위 1.0 의 정수배가 아니다"):
        sim.run(2.0)
    sim.close()
    fine = executor(time_unit=0.5).build(mixed, {**NATIVE, "W": devs.module_of(Witness, "W")})
    fine.run(1.0)
    assert fine.leaves()[("w",)].seen == [(0.5, 0.5, {"i": [None]}), (1.0, 0.5, {"i": [None]})]
    fine.close()


def test_a_native_event_a_last_digit_away_joins_the_round_of_its_tick():
    """고유 모델의 사건 시각이 공통 모델의 것과 끝자리만 다르면 같은 눈금의 한 차례로 처리한다.

    시간 단위 0.1에서 고유 모델은 0.3을 더해 가고 공통 모델은 눈금 3의 시각(0.1의 세 배)에 잡힌다. 두 값은
    끝자리가 다르고 고유 모델의 것이 앞선다. 전이를 맡는 모델이 그 눈금에 낼 공통 모델에 먼저 차례를 준다.
    """
    plan = st.node({}, {"h1": note(period=0.3), "h2": note(), "n": tick(period=0.3)},
                   ic=[(("n", "out"), ("h2", "i")), (("h1", "o"), ("h2", "i"))], time_unit=0.1)
    cx = executor()
    sim = cx.build(plan, {**NATIVE, "Note": NOTE})
    log = sim.run(0.6)
    t3, t6 = 3 * 0.1, 6 * 0.1
    assert log == [(t3, ("n",), "out", None), (t3, ("h1",), "o", ("h1", 0)),      # 고유 모델이 끝자리만큼 먼저다
                   (t6, ("n",), "out", None), (t6, ("h1",), "o", ("h1", 1))]
    # h2는 눈금마다 두 입력을 한 묶음으로 받는다. 따로 받았다면 전이가 두 번이다
    assert sim.leaves()[("h2",)].seen == [("ext", t3, t3, [("h1", 0), None]), ("ext", t6, t6 - t3, [("h1", 1), None])]
    faithful(cx, sim, plan, exact_ports=False)
    sim.close()


def test_common_models_return_to_the_grid_after_a_native_event_a_little_off():
    """고유 모델의 사건이 눈금에서 허용 폭 안으로 벗어난 시각에 공통 모델에 닿아도, 공통 모델의 다음 사건은 눈금의 시각에 잡힌다.

    엔진에는 시간 전진을 그 눈금의 시각에서 엔진의 지금 시각을 뺀 값으로 내놓는다. 남은 눈금 수에 시간 단위를 곱한 값을
    내놓으면 벗어난 만큼이 그 뒤의 사건에 그대로 이어지고, 엔진이 더해 가면서 생기는 끝자리의 오차도 쌓인다.
    """
    off = 0.3 * (1 + 1e-10)                                  # 눈금 3에서 3e-10눈금 뒤다. 허용 폭(3e-9눈금) 안이다
    plan = st.node({}, {"h": note(period=0.6), "n": tick(period=off)}, ic=[(("n", "out"), ("h", "i"))], time_unit=0.1)
    sim = executor().build(plan, {**NATIVE, "Note": NOTE})
    t3, t6 = 3 * 0.1, 6 * 0.1
    assert sim.run(0.6) == [(t3, ("n",), "out", None), (t6, ("h",), "o", ("h", 0))]      # 벗어난 시각의 사건도 눈금 3의 것이다
    assert sim.leaves()[("h",)].seen == [("ext", t3, t3, [None])]
    assert off + t3 != t6                                    # 벗어난 만큼이 이어졌다면 엔진의 시각이 이 값이다
    assert sim.now() == t6                                   # 엔진의 시각이 눈금 6의 시각으로 돌아왔다
    sim.close()


def test_time_advance_must_not_be_negative():
    class Backward(Atomic):
        PORTS = {"o": ("T", "out")}

        def init(self):
            self.left = 1.0

        def ta(self):
            return self.left

        def internal(self):
            self.left = -0.5

    plan, lib = flat_plan({"d": Backward})
    sim = executor().build(plan, lib)
    with pytest.raises(ValueError, match="d: 시간 전진 -0.5 이 음수"):
        sim.run(3.0)
    assert sim.now() == 1.0                                  # 엔진은 그 사건을 마치고 멈췄다
    sim.close()

    class Undefined(Backward):
        def internal(self):
            self.left = float("nan")

    sim = executor().build(*flat_plan({"d": Undefined}))
    with pytest.raises(ValueError, match="수가 아니다"):
        sim.run(3.0)
    sim.close()


def test_an_exception_in_a_model_comes_back_from_run():
    """Python의 예외는 C++을 건너지 못한다. 실행기가 적어 두고 엔진을 멈춘 뒤 run에서 다시 낸다."""
    class Fragile(Atomic):
        PORTS = {"i": ("T", "in")}

        def external(self, elapsed, bag):
            raise KeyError("fragile")

    plan, lib = flat_plan({"p": Pair, "f": Fragile}, ic=[(("p", "o"), ("f", "i"))])
    sim = executor().build(plan, lib)
    with pytest.raises(KeyError, match="fragile"):
        sim.run(5.0)
    assert [t for t, *_ in sim.log] == [1.0, 1.0]
    assert sim.leaves()[("p",)].k == 0                       # 예외가 난 뒤로는 아무것도 하지 않는다. p는 전이하지 못했다
    assert sim.now() == 1.0                                  # 엔진은 끝 시각까지 가지 않고 그 시각에 멈췄다
    with pytest.raises(KeyError):
        sim.run(9.0)
    assert sim.now() == 1.0
    sim.close()
    sim.close()                                              # 두 번 닫아도 된다


def test_an_exception_in_a_native_model_comes_back_from_run():
    """고유 모델이 던진 C++ 예외는 다리가 잡아 run에서 알린다. 그 뒤로는 엔진을 다시 돌리지 않는다."""
    thrower = Module("Thrower", {}, (), {"at": ("float", 1.0)}, Native("Thrower"))
    plan = st.node({}, {"p": st.node(Pair.PORTS, module="Pair", params={}), "t": st.node({}, module="Thrower", params={"at": 2.0})})
    sim = executor().build(plan, {"Pair": devs.module_of(Pair), "Thrower": thrower})
    with pytest.raises(RuntimeError, match="실행 중의 예외: thrower"):
        sim.run(5.0)
    assert [t for t, *_ in sim.log] == [1.0, 1.0, 2.0, 2.0]  # 시각 2에 p가 낸 뒤에 t의 차례에서 예외가 났다
    with pytest.raises(RuntimeError, match="thrower"):
        sim.run(5.0)
    assert len(sim.log) == 4 and sim.now() == 2.0
    sim.close()


def test_a_plan_that_is_one_atom():
    plan = st.node({"o": ("T", "out")}, module="G", params={}, name="Solo", time_unit=UNIT)
    lib = {"G": Module("G", {"o": ("T", "out")}, (), {}, generic({"o": ("T", "out")}))}
    ref, log, _, leaves = on_both(plan, lib, 6.0)
    assert log == ref and len(log) == 1 and list(leaves) == [()]
    cx = executor()
    sim = cx.build(plan, lib)
    assert sim.names[sim.models[()]] == "Solo" and cx.observe(sim)["ports"] == {}
    sim.close()
    nameless = cx.build(st.node({"o": ("T", "out")}, module="G", params={}, time_unit=UNIT), lib)
    assert nameless.names[nameless.models[()]] == "root"
    nameless.close()


def test_run_can_be_continued_and_engines_are_independent():
    plan, lib = as_plan(rand_structure(random.Random(3)))
    whole = simulate(DevsExecutor().build(plan, lib), 8.0)
    one, two = executor().build(plan, lib), executor().build(plan, lib)
    part = list(one.run(2.6))                                # 사건이 없는 끝 시각
    assert part == [e for e in whole if e[0] <= 2.6] and 0 < len(part) < len(whole)
    assert one.now() == 2.6 and two.now() == 0.0
    assert two.run(8.0) == whole                             # 다른 엔진은 영향을 받지 않는다
    assert one.run(8.0) == whole and one.run(1.0) == whole   # 이어서 돌리고, 지난 시각까지는 아무 일도 없다
    assert one.now() == 8.0
    one.close()
    two.close()


# ---------------------------------------------------------------------------
# 고유 모델과 섞인 계획
# ---------------------------------------------------------------------------

PORTS = {"inp": ("T", "in"), "out": ("T", "out")}
TICK = Module("Tick", {**PORTS, "out2": ("T", "out")}, (), {"period": ("float", 1.0), "keep": ("bool", False),
                                                           "twice": ("bool", False)}, Native("Tick"))
RELAY = Module("Relay", PORTS, (), {}, "Relay")              # 본체는 등록된 모듈의 이름만 적어도 된다
NATIVE = {"Tick": TICK, "Relay": RELAY}


def tick(**params) -> dict:
    return st.node(PORTS, module="Tick", params=dict({"period": 1.0, "keep": False, "twice": False}, **params))


def relay() -> dict:
    return st.node(PORTS, module="Relay", params={})


def test_native_modules_are_built_from_registered_factories():
    cx = executor()
    assert C.modules(cx.lib) == ["Again", "Count", "Even", "Nothing", "Reads", "Relay", "Thrower", "Tick"]
    plan = st.node({"x": ("T", "in"), "y": ("T", "out")}, {"a": tick(period=2.0), "b": relay(), "c": relay()},
                   eic=[("x", ("c", "inp"))], eoc=[(("b", "out"), "y"), (("c", "out"), "y")], ic=[(("a", "out"), ("b", "inp"))])
    sim = cx.build(plan, NATIVE)
    faithful(cx, sim, plan, exact_ports=False)
    assert sim.cells == {} and sim.leaves() == {} and sim.infrastructure()["models"] == []      # 엔진에 더 올린 것이 없다
    assert cx.observe(sim)["children"]["a"]["ports"] == {"inp": ("T", "in"), "out": ("T", "out"), "out2": (None, "out")}
    assert sim.dump()["models"] == {0: ("tapped", "a"), 1: ("tapped", "b"), 2: ("tapped", "c")}
    sim.inject("x", 3.0)
    log = sim.run(4.0)
    assert log == [(2.0, ("a",), "out", None), (2.0, ("b",), "out", None), (3.0, ("c",), "out", None),
                   (4.0, ("a",), "out", None), (4.0, ("b",), "out", None)]      # 고유 모델의 메시지는 값을 읽지 않는다
    assert sim.outputs() == [(2.0, "y", ("b",)), (3.0, "y", ("c",)), (4.0, "y", ("b",))] == boundary(log, plan)
    faithful(cx, sim, plan, exact_ports=False)
    sim.close()
    quiet = executor(record=False).build(plan, NATIVE)
    assert quiet.dump()["models"][0] == ("native", "a")
    assert quiet.run(4.0) == [] and quiet.outputs() == [(2.0, "y", None), (4.0, "y", None)]     # 누가 냈는지는 모른다
    quiet.close()
    # 기록하지 않을 때에도 공통 모델이 낸 것은 누가 냈는지 안다. 그 뒤에 고유 모델이 낸 것을 공통 모델의 것으로 적지 않는다
    mixed = st.node({"y": ("T", "out")}, {"h": note(period=1.0), "n": tick()}, eoc=[(("h", "o"), "y"), (("n", "out"), "y")])
    quiet = executor(record=False).build(mixed, {**NATIVE, "Note": NOTE})
    assert quiet.run(2.0) == [(1.0, ("h",), "o", ("h", 0)), (2.0, ("h",), "o", ("h", 1))]
    assert quiet.outputs() == [(1.0, "y", ("h",)), (1.0, "y", None), (2.0, "y", ("h",)), (2.0, "y", None)]
    quiet.close()


def test_native_parameters_arrive_as_the_doubles_written_in_the_plan():
    """고유 모델의 매개변수는 계획에 적힌 배정밀도 값 그대로 간다.

    주기가 0.1인 고유 모델의 셋째 사건 시각은 배정밀도의 0.1을 세 번 더한 값이다. 글자 0.1을 long double로 읽으면
    계획의 값과 끝자리가 다른 수가 되어 셋째 시각이 0.3으로 나오고, 그 결과가 long double의 폭에 따라 달라진다.
    """
    sim = executor().build(st.node({}, {"n": tick(period=0.1)}), NATIVE)
    third = 0.1 + 0.1 + 0.1
    assert third != 0.3
    assert sim.run(0.35) == [(0.1, ("n",), "out", None), (0.2, ("n",), "out", None), (third, ("n",), "out", None)]
    sim.close()


def test_the_bridge_reads_infinite_and_missing_parameters():
    """다리가 고유 모델의 공장에 주는 매개변수: 무한인 시간 값은 엔진의 Infinity가 되고, 없는 것에는 기본값이 온다.

    시험용 모듈 Reads는 읽은 값이 모두 기대와 같을 때에만 out2로도 낸다 (tests/cevsim_models.cpp).
    """
    ports = {**PORTS, "out2": ("T", "out")}
    reads = Module("Reads", ports, (), {"never": ("float", INF), "count": ("int", 12), "label": ("str", "abc")}, Native("Reads"))
    plan = st.node({}, {"r": st.node(ports, module="Reads", params={"never": INF, "count": 12, "label": "abc"})})
    sim = executor().build(plan, {"Reads": reads})
    assert sim.run(1.0) == [(1.0, ("r",), "out", None), (1.0, ("r",), "out2", None)]
    sim.close()


def test_native_module_must_exist_and_have_the_declared_interface():
    cx = executor()
    one = st.node({}, {"a": tick()})
    with pytest.raises(ValueError, match="등록되지 않은 모듈"):
        cx.build(one, {"Tick": Module("Tick", PORTS, (), {}, Native("Missing"))})
    with pytest.raises(ValueError, match="만들지 않았다"):
        cx.build(one, {"Tick": Module("Tick", PORTS, (), {}, Native("Nothing"))})
    with pytest.raises(TypeError, match="본체"):
        cx.build(one, {"Tick": Module("Tick", PORTS, (), {}, object())})
    more = st.node({}, {"a": st.node({**PORTS, "aux": ("T", "out")}, module="Tick", params={})})
    with pytest.raises(ValueError, match="출력 포트 aux"):
        cx.build(more, NATIVE)
    flipped = st.node({}, {"a": st.node({"out": ("T", "in")}, module="Tick", params={})})
    with pytest.raises(ValueError, match="입력 포트 out"):
        cx.build(flipped, NATIVE)


def test_a_factory_must_make_a_new_model_each_time():
    """엔진이 모델을 넘겨받아 지우므로 한 모델을 두 번 올릴 수 없다."""
    again = Module("Again", PORTS, (), {"again": ("bool", False)}, Native("Again"))
    plan = st.node({}, {"a": st.node(PORTS, module="Again", params={"again": False}),
                        "b": st.node(PORTS, module="Again", params={"again": True})})
    with pytest.raises(ValueError, match="같은 모델을 두 번"):
        executor().build(plan, {"Again": again})


def test_native_models_keep_the_engines_own_behaviour():
    """고유 모델은 cevsim의 의미대로 움직인다. 병렬 DEVS가 아니라 하나씩 차례로 처리하는 의미다."""
    cx = executor()
    plan = st.node({}, {"a": tick(), "b": tick(period=3.0), "c": tick(period=5.0, keep=True), "d": tick(period=5.0)},
                   ic=[(("a", "out"), ("b", "inp")), (("a", "out"), ("c", "inp"))])
    sim = cx.build(plan, NATIVE)
    fired = collections.Counter(p for _, p, _, _ in sim.run(12.0))
    # b는 입력을 받을 때마다 다음 사건 시각을 다시 잡아 한 번도 내지 못한다. c는 지키겠다고 해서 낸다
    assert fired == {("a",): 12, ("c",): 2, ("d",): 2}
    sim.close()
    plan = st.node({}, {"a": tick(twice=True), "b": relay(), "c": relay()},
                   ic=[(("a", "out"), ("b", "inp")), (("a", "out2"), ("c", "inp"))])
    plan["children"]["a"]["ports"]["out2"] = ("T", "out")
    sim = cx.build(plan, NATIVE)
    assert sim.run(1.0) == [(1.0, ("a",), "out", None), (1.0, ("a",), "out2", None),
                            (1.0, ("b",), "out", None), (1.0, ("c",), "out", None)]
    sim.close()


VALUED = {"Count": Module("Count", {"out": ("N", "out")}, (), {"period": ("float", 1.0)}, Native("Count")),
          "Even": Module("Even", {"inp": ("N", "in"), "out": ("T", "out")}, (), {}, Native("Even")),
          "Keep": devs.module_of(Keep)}


def test_value_messages_pass_between_native_models():
    """cevsim의 값 메시지는 고유 모델 사이에서 값째로 전달된다. 실행기의 기록에는 포트만 남는다."""
    count = st.node({"out": ("N", "out")}, module="Count", params={"period": 1.0})
    plan = st.node({"y": ("T", "out")}, {"c": count, "e": st.node({"inp": ("N", "in"), "out": ("T", "out")}, module="Even", params={})},
                   ic=[(("c", "out"), ("e", "inp"))], eoc=[(("e", "out"), "y")])
    cx = executor()
    sim = cx.build(plan, VALUED)
    faithful(cx, sim, plan)
    assert sim.run(4.0) == [(1.0, ("c",), "out", None), (1.0, ("e",), "out", None), (2.0, ("c",), "out", None),
                            (3.0, ("c",), "out", None), (3.0, ("e",), "out", None), (4.0, ("c",), "out", None)]
    assert sim.outputs() == [(1.0, "y", ("e",)), (3.0, "y", ("e",))]      # 짝수(0과 2)를 받았을 때에만 낸다
    sim.close()
    quiet = executor(record=False).build(plan, VALUED)
    assert quiet.run(4.0) == [] and quiet.outputs() == [(1.0, "y", None), (3.0, "y", None)]
    quiet.close()
    # 값을 싣는 포트는 값을 싣는 포트에만 이을 수 있다. 공통 모델과 엔진의 경계의 포트는 값을 싣지 않는다
    to_common = st.node({}, {"c": count, "k": st.node(Keep.PORTS, module="Keep", params={})}, ic=[(("c", "out"), ("k", "i"))])
    with pytest.raises(ValueError, match=r"결합을 등록할 수 없다: c.out 에서 k.i \(엔진이 결합을 거절했다"):
        cx.build(to_common, VALUED)
    to_root = st.node({"y": ("N", "out")}, {"c": count}, eoc=[(("c", "out"), "y")])
    with pytest.raises(ValueError, match="c.out 에서 경계.y"):
        cx.build(to_root, VALUED)


def test_native_and_common_models_in_one_plan():
    """섞으면 고유 모델이 보낸 것은 값이 None인 입력으로 온다. 같은 시각의 것은 한 묶음으로 받는다."""
    plan = st.node({}, {"n": tick(), "busy": note(period=2.0), "quiet": note(), "r": relay()},
                   ic=[(("n", "out"), ("busy", "i")), (("n", "out"), ("quiet", "i")), (("busy", "o"), ("r", "inp"))])
    cx = executor()
    sim = cx.build(plan, {**NATIVE, "Note": NOTE})
    faithful(cx, sim, plan, exact_ports=False)
    log = sim.run(4.0)
    leaves = sim.leaves()
    assert sorted(leaves) == [("busy",), ("quiet",)]
    assert leaves[("quiet",)].seen == [("ext", float(t), 1.0, [None]) for t in (1, 2, 3, 4)]
    # busy는 시각 2와 4에 스스로도 낸다. 같은 시각에 n이 보낸 것과 겹쳐 겹친 전이가 된다
    assert leaves[("busy",)].seen == [("ext", 1.0, 1.0, [None]), ("con", 2.0, [None]), ("ext", 3.0, 1.0, [None]), ("con", 4.0, [None])]
    assert log == [(1.0, ("n",), "out", None),
                   (2.0, ("busy",), "o", ("busy", 0)), (2.0, ("n",), "out", None), (2.0, ("r",), "out", None),
                   (3.0, ("n",), "out", None),
                   (4.0, ("busy",), "o", ("busy", 1)), (4.0, ("n",), "out", None), (4.0, ("r",), "out", None)]
    faithful(cx, sim, plan, exact_ports=False)
    sim.close()


def test_same_instant_order_is_the_order_of_paths():
    """같은 시각의 모델은 경로의 순서로 차례가 온다. 공통 모델과 고유 모델을 가리지 않는다."""
    plan = st.node({}, {"m": tick(), "a": note(period=1.0), "z": note(period=1.0), "b": tick()})
    sim = executor().build(plan, {**NATIVE, "Note": NOTE})
    assert [(t, p[0]) for t, p, _, _ in sim.run(2.0)] == [(1.0, "a"), (1.0, "b"), (1.0, "m"), (1.0, "z"),
                                                          (2.0, "a"), (2.0, "b"), (2.0, "m"), (2.0, "z")]
    sim.close()


class Echo(Atomic):
    """받으면 그 시각에 한 번 낸다."""
    PORTS = {"i": ("T", "in"), "o": ("T", "out")}

    def init(self):
        self.left, self.seen = INF, []

    def ta(self):
        return self.left

    def output(self):
        return {"o": [self.name]}

    def internal(self):
        self.left = INF

    def external(self, elapsed, bag):
        self.seen.append((self.now, elapsed, {p: list(v) for p, v in bag.items()}))
        self.left = 0.0


def test_root_ports_are_the_engine_boundary():
    """뿌리의 입력 포트로 밖에서 입력을 넣고, 뿌리의 출력 포트로 나간 것을 읽는다. 경계를 지나는 메시지에는 값이 없다."""
    plan = st.node({"x": ("T", "in"), "y": ("T", "out")},
                   {"k": st.node(Echo.PORTS, module="Echo", params={}), "clock": st.node(Pair.PORTS, module="Pair", params={})},
                   eic=[("x", ("k", "i"))], eoc=[(("k", "o"), "y")])
    lib = {"Echo": devs.module_of(Echo), "Pair": devs.module_of(Pair)}
    cx = executor()
    sim = cx.build(plan, lib)
    faithful(cx, sim, plan)
    sim.inject("x", 2.0)
    sim.inject("x", 2.0)
    sim.inject("x", 4.0)
    log = sim.run(5.0)
    k = sim.leaves()[("k",)]
    assert k.seen == [(2.0, 2.0, {"i": [None, None]}), (4.0, 2.0, {"i": [None]})]     # 같은 시각의 입력 둘은 한 묶음이다
    assert [e for e in log if e[1] == ("k",)] == [(2.0, ("k",), "o", "k"), (4.0, ("k",), "o", "k")]
    assert sim.outputs() == [(2.0, "y", ("k",)), (4.0, "y", ("k",))]
    with pytest.raises(ValueError, match="입력 포트 nope"):
        sim.inject("nope")
    with pytest.raises(ValueError, match="시각 3.0 에는 입력을 넣을 수 없다. 이미 지난 시각"):
        sim.inject("x", 3.0)
    with pytest.raises(ValueError, match="유한한 수가 아니다"):
        sim.inject("x", INF)
    sim.inject("x", 5.0)                                     # 지금 시각의 입력은 받는다. 시각을 더 나아가지 않고 처리한다
    assert len(sim.run(3.0)) == len(log) and len(k.seen) == 2        # 지난 시각까지 돌리라는 것으로는 처리하지 않는다
    assert [e for e in sim.run(5.0) if e[1] == ("k",)][2:] == [(5.0, ("k",), "o", "k")] and k.seen[2] == (5.0, 1.0, {"i": [None]})
    sim.close()


def test_external_input_to_an_idle_model_is_processed_at_that_time():
    """아무도 임박하지 않은 시각에 입력을 받은 모델은 그 시각에 차례를 청해 전이하고, 그 시각에 낸다."""
    plan = st.node({"x": ("T", "in")}, {"k": st.node(Echo.PORTS, module="Echo", params={}),
                                        "w": st.node(Witness.PORTS, module="W", params={})}, eic=[("x", ("k", "i")), ("x", ("w", "i"))])
    sim = executor().build(plan, {"Echo": devs.module_of(Echo), "W": devs.module_of(Witness, "W")})
    sim.inject("x", 2.0)
    sim.inject("x", 2.0)
    assert sim.run(4.0) == [(2.0, ("k",), "o", "k")]
    assert sim.leaves()[("k",)].seen == [(2.0, 2.0, {"i": [None, None]})]
    assert sim.leaves()[("w",)].seen == [(2.0, 2.0, {"i": [None, None]})]
    assert sim.turns == 3                                    # 입력을 받은 둘이 차례를 청해 깨웠고, k가 그 눈금에 한 번 냈다
    sim.close()


def test_input_at_the_deadline_is_a_confluent_transition():
    """낼 시각과 같은 시각에 밖에서 입력이 오면 먼저 내고 겹친 전이를 한다. 낼 시각이 아니면 내지 않고 외부 전이만 한다."""
    plan = st.node({"x": ("T", "in")}, {"m": note(period=2.0)}, eic=[("x", ("m", "i"))])
    sim = executor().build(plan, {"Note": NOTE})
    sim.inject("x", 2.0)                                     # 낼 시각이다
    sim.inject("x", 3.0)                                     # 낼 시각이 아니다
    log = sim.run(4.0)
    assert sim.leaves()[("m",)].seen == [("con", 2.0, [None]), ("ext", 3.0, 1.0, [None])]
    assert log == [(2.0, ("m",), "o", ("m", 0)), (4.0, ("m",), "o", ("m", 1))]
    sim.close()


def test_the_bridge_answers_a_wrong_call_with_an_error_value():
    """다리의 함수를 잘못 부르면 엔진까지 가지 않고 오류 값이 돌아온다. 실행기는 이런 부름을 하지 않는다."""
    plan = st.node({"x": ("T", "in"), "y": ("T", "out")}, {"k": st.node(Echo.PORTS, module="Echo", params={})},
                   eic=[("x", ("k", "i"))], eoc=[(("k", "o"), "y")])
    sim = executor().build(plan, {"Echo": devs.module_of(Echo)})
    lib, h, k = sim.lib, sim.handle, sim.models[("k",)]
    assert lib.ses_add_port(h, b"x", 1) == -1 and lib.ses_add_port(h, b"y", 0) == -1     # 이미 있는 뿌리의 포트
    assert lib.ses_add_port(h, b"x", 0) == 0                                             # 방향이 다르면 다른 포트다
    assert lib.ses_couple(h, 99, b"o", k, b"i") == -1 and lib.ses_couple(h, k, b"o", 99, b"i") == -1     # 없는 모델
    assert lib.ses_couple(h, -1, b"x", -1, b"y") == -1                                   # 경계에서 경계로
    assert lib.ses_couple(h, k, b"nope", -1, b"y") == -2 and lib.ses_couple(h, -1, b"x", k, b"nope") == -2     # 없는 포트
    assert lib.ses_couple(h, k, b"i", -1, b"y") == -2                                    # 입력 포트에서 나가는 결합
    for nobody in (1 << 30, -(1 << 30), 99):
        lib.ses_emit(h, nobody, b"o")                                                    # 없는 모델의 출력은 버린다
    assert lib.ses_last_error(h) == b"" and sim.connections() == st.flatten(plan)        # 결합은 그대로다
    sim.inject("x", 1.0)
    assert sim.run(2.0) == [(1.0, ("k",), "o", "k")]
    sim.close()


# ---------------------------------------------------------------------------
# 규약 V1: 실행기가 쓰는 포트 이름
# ---------------------------------------------------------------------------

NAMES = {
    "ses": "1.0", "name": "R", "port_types": {"T": {}},
    "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["Src", "Dst"],
                                              "couplings": [{"from": "Src.__wake__", "to": "Dst.i"}]}}},
        "Src": {"ports": {"__wake__": {"type": "T", "direction": "out"}}},
        "Dst": {"ports": {"i": {"type": "T", "direction": "in"}}},
    },
}


def test_port_names_used_by_the_executor_are_reserved():
    lib = {"S": Module("S", {"__wake__": ("T", "out")}, (), {}, generic({"__wake__": ("T", "out")})),
           "D": Module("D", {"i": ("T", "in")}, (), {}, generic({"i": ("T", "in")}))}
    binding = Binding("x", {"Src": Bind("S"), "Dst": Bind("D")})
    L0 = unfold_layered(load_ses_dict(NAMES))
    dx, cx = DevsExecutor(), executor()
    L, de = X.attach(L0, dx, binding, lib)
    L, ce = X.attach(L, cx, binding, lib)
    (V,) = sem(L.ses)
    assert X.executable(L, de, V) and not X.executable(L, ce, V)         # 같은 SES가 참조 실행기로는 된다
    assert [(code, path) for _, code, path, _ in violations(X.alone(L, ce), V)] == [("V1", ("R", "a", "Src"))]
    with pytest.raises(ValueError, match="__wake__"):
        cx.build(X.plan(L, ce, V), lib)
    a = analyze(E.from_dict(NAMES), attach=lambda L1: X.attach(L1, cx, binding, lib)[0])      # 편집기의 진단으로 나온다
    (d,) = a.of("V1")
    assert (d.code, d.layer, d.address, d.affected) == ("V1", "exec:cevsim", "entities/Src", (1, 1))
    plan = st.node({"__commit__": ("T", "in")}, {"box": st.node({"__wake__": ("T", "out")}, {"a": st.node({"__commit__": ("T", "in")})})})
    assert [(c, p) for c, p, _ in cx.check(plan)] == [("V1", ("box", "a"))]      # 원자의 포트만 엔진의 모델에 오른다


# ---------------------------------------------------------------------------
# 컴파일과 적재
# ---------------------------------------------------------------------------

def test_the_library_is_needed_only_to_build(tmp_path):
    """실행 가능성의 판정은 컴파일 없이 한다. cevsim을 찾지 못하면 조립할 때 알린다."""
    lost = CevsimExecutor("/no/such/place")
    assert lost.check(st.node({"o": ("T", "out")})) == [] and not C.available("/no/such/place")
    with pytest.raises(BuildError, match="찾지 못했다"):
        lost.build(st.node({"o": ("T", "out")}, module="G", params={}), {})
    with pytest.raises(BuildError, match="찾지 못했다"):
        C.load(HOME, compiler="no-such-compiler")
    with pytest.raises(BuildError, match="컴파일하지 못했다"):
        C.load(HOME, sources=[MODELS], compiler="false", cache=str(tmp_path / "never"))
    old = tmp_path / "old" / "cevsim" / "include"            # 실행기가 맞춘 것보다 앞선 cevsim: 값 메시지의 헤더가 없다
    old.mkdir(parents=True)
    (old / "system_executor.hpp").write_text("")
    assert not C.available(str(tmp_path / "old"))
    with pytest.raises(BuildError, match="앞선 것이다"):
        C.load(str(tmp_path / "old"))


def test_the_engine_is_compiled_once_and_shared(tmp_path):
    """cevsim의 소스는 한 번 컴파일해 둔다. 고유 모델의 소스가 다르면 그것만 다시 컴파일해 묶는다."""
    with_models, plain = executor().lib, CevsimExecutor(HOME).lib
    assert with_models._name != plain._name and C.modules(plain) == []
    root = os.path.dirname(os.path.dirname(with_models._name))
    assert root == os.path.dirname(os.path.dirname(plain._name))
    (engine,) = glob.glob(os.path.join(root, "engine-*", "system_executor.o"))       # 두 라이브러리가 같은 것을 묶었다
    assert C.load(HOME, sources=[MODELS]) is with_models     # 내용이 같으면 앞서 실은 것을 다시 쓴다
    plan, lib = flat_plan({"p": Pair})
    sim = CevsimExecutor(HOME).build(plan, lib)
    assert len(sim.run(2.0)) == 4
    sim.close()
    made = os.path.getmtime(engine)
    extra = tmp_path / "extra.cpp"                           # 새 고유 모델의 소스: cevsim은 다시 컴파일하지 않는다
    extra.write_text('#include "ses_cevsim.hpp"\n'
                     'SES_MODULE(Extra, [](const std::string&, const ses::Params&) -> evsim::CAtomicModel* { return nullptr; });\n')
    more = C.load(HOME, sources=[str(extra)])
    try:
        assert C.modules(more) == ["Extra"] and os.path.getmtime(engine) == made
        assert os.path.dirname(os.path.dirname(more._name)) == root
    finally:
        C._LOADED.pop(more._name)
        shutil.rmtree(os.path.dirname(more._name))           # 이 시험이 만든 라이브러리는 남기지 않는다


# ---------------------------------------------------------------------------
# 확인한 사실: cevsim 45e7fa9의 엔진 (16 문서 2절의 표). 주석은 앞선 커밋 a9886a6에서의 값이다
# ---------------------------------------------------------------------------

EXPECTED = {
    "horizon_first": "3", "horizon_continued": "5",                      # 6. 이어서 돌릴 때 경계의 시각을 두 번 처리했다
    "clock_after_run": "2.5,2.5",
    "off_grid_half_period": "12", "off_grid_other_model": "3",           # 6. 격자 밖의 시각을 다음 눈금으로 올렸다
    "equal_time_receiver": "2", "equal_time_bystander": "2",             # 0. 시각이 같은 다른 모델이 일정에서 빠졌다
    "two_messages_first": "3", "two_messages_second": "3",               # 0. 한 번의 출력에서 둘째 메시지가 사라졌다
    "coupling_twice": "4",                                               # 두 번 등록한 결합은 두 번 전달한다
    "receiver_timer": "0", "receiver_timer_kept": "2",                   # 입력을 받으면 다음 사건 시각을 다시 잡는다
    "simultaneous_order": "a@1,b@1,a@2,b@2,a@3,b@3,a@4,b@4",             # b@1,a@1,a@2,b@2,... 눈금마다 뒤바뀌었다
    "creation_order": "b@1,a@1,b@2,a@2",                                 # 같은 시각의 순서는 모델을 만든 순서다
    "woken_model_made_first": "a@1,r@1,b@1", "woken_model_made_last": "a@1,b@1,r@1",
    "message_order": "ext-b@1,ext-c@1", "message_order_reversed": "ext-c@1,ext-b@1",
    "self_coupled": "6",
    "boundary_count": "4", "boundary_ports": "default.x,default.y,default.x,default.y",      # a.out이 네 번. 경계의 포트가 없었다
    "boundary_handler": "x@1,x@2,0",
    "external_input_passive": "ext-r@3", "external_input_same_time": "2",                    # 1
    "external_input_at_deadline": "ext-r@3", "external_input_at_deadline_kept": "ext-r@3,r@3",
    "external_input_now": "ext-r@2", "external_input_past": "invalid_argument",
    "external_input_zero_delay": "r@2",                                  # r@3. 다음 눈금에 처리했다
    "late_creation": "b@5,b@7,b@9",                                      # b@3,b@5,b@7,b@9. 만든 시각에 한 번 냈다
    "flat_boundary": "30", "flat_relays": "10,10,10",
    "nested_boundary": "30", "nested_relays": "10,10,10",                # 12와 1,1,10. 결합 모델 안에 넣으면 결과가 달랐다
    "destructor_never_run": "1", "destructor_after_run": "1", "virtual_destructor_model": "1",      # 모두 0
    "negative_time_advance": "domain_error", "value_port_to_plain_port": "invalid_argument",
}


@fact
def test_fact_engine_properties(tmp_path):
    lib = executor().lib
    program = str(tmp_path / "facts")
    built = subprocess.run(["g++", *C.FLAGS, "-I", os.path.join(HOME, "cevsim", "include"), FACTS,
                            lib._name, f"-Wl,-rpath,{os.path.dirname(lib._name)}", "-o", program], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr[-2000:]
    out = subprocess.run([program], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    got = dict(line.split(" ", 1) for line in out.stdout.splitlines() if " " in line)
    assert got == EXPECTED


# ---------------------------------------------------------------------------
# 표본이 공허하지 않은가
# ---------------------------------------------------------------------------

def test_cevsim_samples_are_not_vacuous():
    if not STATS["events"]:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["events"] >= 3000 and STATS["same_instant"] >= 300, STATS
    assert STATS["multiple"] >= 10 and STATS["to_itself"] >= 20 and STATS["boundary"] >= 100, STATS
    assert STATS["realized"] >= 300 and STATS["doc_events"] >= 500, STATS
    assert STATS["black_box"] >= 100 and STATS["realized"] - STATS["root_atom"] >= 100, STATS
    assert STATS["quirky_events"] >= 1000 and STATS["quirky_bags"] >= 500, STATS
    assert STATS["boundary_outputs"] >= 300, STATS
