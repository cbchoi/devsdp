"""cevsim 실행기 (docs/ses-platform/16_cevsim_executor.md).

합격 기준은 pyevsim 실행기와 같다 (14 문서의 결정 D1).
- 충실성: 엔진에서 다시 읽은 모델과 연결이 계획의 것과 같다. 연결은 길의 수까지 같다.
- 사건 기록: 같은 모델베이스를 참조 시뮬레이터(devs.py)와 cevsim에서 돌린 출력 사건의 열이 같다.

cevsim의 소스와 C++ 컴파일러가 있어야 돈다. 환경 변수 CEVSIM_HOME에 cevsim을 받아 둔 자리를 준다.
없으면 건너뛴다. 엔진의 성질을 적어 둔 시험은 확인한 커밋(a9886a6)에서만 돈다.
"""

import collections
import os
import random
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from ses_core import cevsim_executor as C  # noqa: E402

HOME = os.environ.get("CEVSIM_HOME", "")
if not C.available(HOME):
    pytest.skip("cevsim의 소스(CEVSIM_HOME)나 C++ 컴파일러가 없다", allow_module_level=True)

from docgen import rand_binding, rand_system_document  # noqa: E402
from pdevs_models import NOTE, Burst, Keep, Pair, Ring, Spin, as_plan, flat_plan, note  # noqa: E402
from test_executor import Sometimes, Witness, generic, library_of, quirky, state  # noqa: E402
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


PINNED = commit() == "a9886a6b3c74b3168a8cae33c5f6ae3228e59514"
fact = pytest.mark.skipif(not PINNED, reason="cevsim a9886a6에서 확인한 사실이다. 다른 커밋에서는 다시 확인해야 한다")


def executor(step: float = 1.0, **options) -> CevsimExecutor:
    """시험은 모두 같은 라이브러리를 쓴다. 고유 모델의 소스를 함께 컴파일한 것이다."""
    return CevsimExecutor(HOME, step, sources=[MODELS], **options)


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


def on_both(plan: dict, lib: dict, until: float, step: float = 0.25, **options) -> tuple:
    """같은 계획과 같은 라이브러리를 두 실행기로 만들어 돌린다."""
    model = DevsExecutor().build(plan, lib)
    log = simulate(model, until)
    cx = executor(step, **options)
    sim = cx.build(plan, lib)
    try:
        faithful(cx, sim, plan)
        mine = list(sim.run(until))
        faithful(cx, sim, plan)                              # 돌린 뒤에도 같다
        return log, mine, devs._leaves(model), sim.leaves()
    finally:
        sim.close()


def attach_both(doc_name: str, binding_name: str, library: dict, step: float = 1.0):
    L = unfold_layered(load_ses(os.path.join(EXAMPLES, doc_name)))
    b = X.load_binding(os.path.join(EXAMPLES, binding_name))
    dx, cx = DevsExecutor(), executor(step)
    L, de = X.attach(L, dx, b, library)
    L, ce = X.attach(L, cx, Binding("cevsim", b.map, b.target), library)
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
    cx = executor(1.0)
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
    dx, cx = DevsExecutor(), executor(1.0)
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
    ref, log, r_leaves, leaves = on_both(plan, lib, 8.0)
    assert log == ref and state(leaves) == state(r_leaves)
    STATS["quirky_events"] += len(log)
    STATS["quirky_bags"] += sum(1 for a in leaves.values() for h in a.heard if h[0] != "both")


@pytest.mark.parametrize("seed", range(150))
def test_random_documents_faithful_and_same_log(seed):
    rng = random.Random(seed)
    d = rand_system_document(rng)
    b, mods = rand_binding(rng, d, "cevsim")
    dx, cx = DevsExecutor(), executor(0.25)
    L = unfold_layered(load_ses_dict(d))
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


def test_output_on_an_undeclared_port_is_recorded_and_goes_nowhere():
    """모듈이 계획에 없는 포트로 낸 것은 기록에 남고 어디에도 전달되지 않는다. 참조 시뮬레이터와 같다."""
    wide = {"o": ("T", "out"), "spare": ("T", "out")}
    plan = st.node({}, {"g": st.node({"o": ("T", "out")}, module="G", params={}), "w": st.node(Witness.PORTS, module="W", params={})},
                   ic=[(("g", "o"), ("w", "i"))])
    lib = {"G": Module("G", wide, (), {}, generic(wide)), "W": devs.module_of(Witness, "W")}
    ref, log, r_leaves, leaves = on_both(plan, lib, 4.0)
    assert log == ref and sorted(port for _, _, port, _ in log) == ["o", "spare"]
    assert leaves[("w",)].seen == r_leaves[("w",)].seen and len(leaves[("w",)].seen) == 1


def test_a_missed_event_is_not_silent():
    """엔진이 어떤 모델의 사건을 지나쳤다면 다음에 그 모델의 시각을 물을 때 드러난다."""
    plan, lib = flat_plan({"r": Ring})
    sim = executor(1.0).build(plan, lib)
    i = sim.models[("r",)]
    assert sim._ta(i) == 1 and sim._ta(sim.keeper) == -1     # 한 눈금 뒤에 낸다. 전이를 맡는 모델은 쉬고 있다
    sim.run(3.0)                                             # 시계는 눈금 4에 있다
    sim.cells[i].due = 2
    with pytest.raises(RuntimeError, match="지나쳤다"):
        sim._ta(i)
    sim.close()


def test_endless_zero_time_transitions_are_stopped():
    plan, lib = flat_plan({"s": Spin})
    sim = executor(1.0, max_rounds=50).build(plan, lib)
    with pytest.raises(RuntimeError, match="걸음 수"):
        sim.run(1.0)
    sim.close()


def test_time_advance_must_be_on_the_grid():
    plan, lib = as_plan(st.node({}, {"b": st.node({"o": ("T", "out")})}))        # 이 모델의 지연은 0.5다
    for step, ok in ((0.25, True), (0.125, True), (1.0, False), (0.4, False)):
        if ok:
            sim = executor(step).build(plan, lib)
            assert sim.run(4.0) == simulate(DevsExecutor().build(plan, lib), 4.0)
            sim.close()
        else:
            with pytest.raises(OffGrid, match="배수"):
                executor(step).build(plan, lib)

    class Drift(Atomic):                                     # 처음에는 격자 위에 있다가 벗어난다
        PORTS = {"o": ("T", "out")}

        def init(self):
            self.left = 1.0

        def ta(self):
            return self.left

        def internal(self):
            self.left = 0.5

    plan, lib = flat_plan({"d": Drift})
    sim = executor(1.0).build(plan, lib)
    with pytest.raises(OffGrid, match="d: 시간 전진 0.5"):
        sim.run(3.0)
    sim.close()
    with pytest.raises(ValueError):
        CevsimExecutor(HOME, 0)


def test_an_exception_in_a_model_comes_back_from_run():
    """Python의 예외는 C++을 건너지 못한다. 실행기가 적어 두었다가 run에서 다시 낸다."""
    class Fragile(Atomic):
        PORTS = {"i": ("T", "in")}

        def external(self, elapsed, bag):
            raise KeyError("fragile")

    plan, lib = flat_plan({"p": Pair, "f": Fragile}, ic=[(("p", "o"), ("f", "i"))])
    sim = executor(1.0).build(plan, lib)
    with pytest.raises(KeyError, match="fragile"):
        sim.run(5.0)
    assert [t for t, *_ in sim.log] == [1.0, 1.0]            # 예외가 난 뒤로는 아무것도 하지 않는다
    with pytest.raises(KeyError):
        sim.run(9.0)
    sim.close()
    sim.close()                                              # 두 번 닫아도 된다


def test_a_plan_that_is_one_atom():
    plan = st.node({"o": ("T", "out")}, module="G", params={}, name="Solo")
    lib = {"G": Module("G", {"o": ("T", "out")}, (), {}, generic({"o": ("T", "out")}))}
    ref, log, _, leaves = on_both(plan, lib, 6.0)
    assert log == ref and len(log) == 1 and list(leaves) == [()]
    cx = executor(0.25)
    sim = cx.build(plan, lib)
    assert sim.names[sim.models[()]] == "Solo" and cx.observe(sim)["ports"] == {}
    sim.close()


def test_run_can_be_continued_and_engines_are_independent():
    plan, lib = as_plan(rand_structure(random.Random(3)))
    whole = simulate(DevsExecutor().build(plan, lib), 8.0)
    one, two = executor(0.25).build(plan, lib), executor(0.25).build(plan, lib)
    part = list(one.run(2.6))                                # 격자 위에 없는 끝 시각: 2.5까지 처리한다
    assert part == [e for e in whole if e[0] <= 2.6] and 0 < len(part) < len(whole)
    assert two.run(8.0) == whole                             # 다른 엔진은 영향을 받지 않는다
    assert one.run(8.0) == whole and one.run(1.0) == whole   # 이어서 돌리고, 지난 시각까지는 아무 일도 없다
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
    cx = executor(1.0)
    assert C.modules(cx.lib) == ["Nothing", "Relay", "Tick"]
    plan = st.node({"x": ("T", "in"), "y": ("T", "out")}, {"a": tick(period=2.0), "b": relay(), "c": relay()},
                   eic=[("x", ("c", "inp"))], eoc=[(("b", "out"), "y"), (("c", "out"), "y")], ic=[(("a", "out"), ("b", "inp"))])
    sim = cx.build(plan, NATIVE)
    faithful(cx, sim, plan, exact_ports=False)
    assert sim.cells == {} and sim.leaves() == {} and sim.infrastructure()["models"] == []      # 엔진에 더 올린 것이 없다
    assert cx.observe(sim)["children"]["a"]["ports"] == {"inp": ("T", "in"), "out": ("T", "out"), "out2": (None, "out")}
    assert sim.dump()["models"] == {0: ("tapped", "a"), 1: ("tapped", "b"), 2: ("tapped", "c")}
    sim.inject("x", 3.0)
    log = sim.run(4.0)
    assert log == [(2.0, ("a",), "out", None), (2.0, ("b",), "out", None), (4.0, ("c",), "out", None),
                   (4.0, ("a",), "out", None), (4.0, ("b",), "out", None)]      # 고유 모델의 메시지에는 값이 없다
    assert sim.outputs() == {(("b",), "out"): 2, (("c",), "out"): 1}
    faithful(cx, sim, plan, exact_ports=False)
    sim.close()
    quiet = executor(1.0, record=False).build(plan, NATIVE)
    assert quiet.dump()["models"][0] == ("native", "a")
    assert quiet.run(4.0) == [] and quiet.outputs() == {(("b",), "out"): 2}
    quiet.close()
    again = cx.build(plan, NATIVE)
    with pytest.raises(ValueError, match="입력 포트 nope"):
        again.inject("nope")
    again.close()


def test_native_module_must_exist_and_have_the_declared_interface():
    cx = executor(1.0)
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


def test_native_and_common_models_in_one_plan():
    """섞으면 고유 모델이 보낸 것은 값 없는 입력으로 온다. 같은 시각이면 고유 모델이 공통 모델보다 나중에 처리된다."""
    plan = st.node({}, {"n": tick(), "busy": note(period=2.0), "quiet": note(), "r": relay()},
                   ic=[(("n", "out"), ("busy", "i")), (("n", "out"), ("quiet", "i")), (("busy", "o"), ("r", "inp"))])
    cx = executor(1.0)
    sim = cx.build(plan, {**NATIVE, "Note": NOTE})
    faithful(cx, sim, plan, exact_ports=False)
    log = sim.run(4.0)
    leaves = sim.leaves()
    assert sorted(leaves) == [("busy",), ("quiet",)]
    assert leaves[("quiet",)].seen == [("ext", float(t), 1.0, []) for t in (1, 2, 3, 4)]
    assert leaves[("busy",)].seen == [("ext", 1.0, 1.0, []), ("ext", 2.0, 0.0, []), ("ext", 3.0, 1.0, []), ("ext", 4.0, 0.0, [])]
    assert log == [(1.0, ("n",), "out", None),
                   (2.0, ("busy",), "o", ("busy", 0)), (2.0, ("n",), "out", None), (2.0, ("r",), "out", None),
                   (3.0, ("n",), "out", None),
                   (4.0, ("busy",), "o", ("busy", 1)), (4.0, ("n",), "out", None), (4.0, ("r",), "out", None)]
    faithful(cx, sim, plan, exact_ports=False)
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
    """뿌리의 입력 포트로 밖에서 입력을 넣고, 뿌리의 출력 포트로 나간 것을 읽는다. cevsim의 메시지에는 값이 없다."""
    plan = st.node({"x": ("T", "in"), "y": ("T", "out")},
                   {"k": st.node(Echo.PORTS, module="Echo", params={}), "clock": st.node(Pair.PORTS, module="Pair", params={})},
                   eic=[("x", ("k", "i"))], eoc=[(("k", "o"), "y")])
    lib = {"Echo": devs.module_of(Echo), "Pair": devs.module_of(Pair)}
    cx = executor(1.0)
    sim = cx.build(plan, lib)
    faithful(cx, sim, plan)
    sim.inject("x", 2.0)
    sim.inject("x", 2.0)                                     # 같은 시각의 입력 둘도 따로 전달된다
    sim.inject("x", 4.0)
    log = sim.run(5.0)
    k = sim.leaves()[("k",)]
    assert k.seen == [(2.0, 2.0, {"i": []}), (4.0, 2.0, {"i": []})]      # 같은 시각의 입력 둘은 한 묶음이다
    assert [e for e in log if e[1] == ("k",)] == [(2.0, ("k",), "o", "k"), (4.0, ("k",), "o", "k")]
    assert sim.outputs() == {(("k",), "o"): 2}               # 시각과 뿌리의 포트 이름은 엔진에 남지 않는다
    sim.close()


def test_two_external_inputs_at_one_time_are_both_delivered():
    """cevsim은 예약 시각이 같은 외부 입력을 하나만 전달한다. 실행기는 입력마다 시각을 아주 조금 다르게 해서 넣는다."""
    plan = st.node({"x": ("T", "in")}, {"w": st.node(Witness.PORTS, module="W", params={})}, eic=[("x", ("w", "i"))])
    sim = executor(1.0).build(plan, {"W": devs.module_of(Witness, "W")})
    sim.inject("x", 2.0)
    sim.inject("x", 2.0)
    sim.run(4.0)
    assert sim.leaves()[("w",)].seen == [(2.0, 2.0, {"i": []}), (2.0, 0.0, {"i": []})]
    sim.close()


def test_external_input_with_no_due_model_is_processed_late_and_reported():
    """밖에서 온 입력으로 그 시각에 임박해진 모델을 cevsim은 다음 눈금에 처리한다. 실행기는 그것을 오류로 알린다."""
    plan = st.node({"x": ("T", "in")}, {"k": st.node(Echo.PORTS, module="Echo", params={})}, eic=[("x", ("k", "i"))])
    sim = executor(1.0).build(plan, {"Echo": devs.module_of(Echo)})
    sim.inject("x", 2.0)
    with pytest.raises(RuntimeError, match="눈금 2 의 사건을 엔진이 눈금 3 에 처리했다"):
        sim.run(5.0)
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
    dx, cx = DevsExecutor(), executor(0.25)
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


def test_the_library_is_needed_only_to_build():
    """실행 가능성의 판정은 컴파일 없이 한다. cevsim을 찾지 못하면 조립할 때 알린다."""
    lost = CevsimExecutor("/no/such/place", 1.0)
    assert lost.check(st.node({"o": ("T", "out")})) == [] and not C.available("/no/such/place")
    with pytest.raises(BuildError, match="찾지 못했다"):
        lost.build(st.node({"o": ("T", "out")}, module="G", params={}), {})
    with pytest.raises(BuildError, match="찾지 못했다"):
        C.load(HOME, compiler="no-such-compiler")
    with pytest.raises(BuildError, match="컴파일하지 못했다"):
        C.load(HOME, sources=[MODELS], compiler="false", cache=os.path.join(C.tempfile.gettempdir(), "ses_cevsim_never"))


# ---------------------------------------------------------------------------
# 확인한 사실: cevsim a9886a6의 엔진 (16 문서 2절의 표)
# ---------------------------------------------------------------------------

EXPECTED = {
    "horizon_first": "3", "horizon_continued": "6",                      # simulate는 끝 시각을 포함한다
    "off_grid_half_period": "6", "off_grid_other_model": "3",           # 격자 밖의 시각은 다음 눈금으로 올려진다
    "equal_time_receiver": "2", "equal_time_bystander": "0",            # 시각이 같은 다른 모델이 일정에서 빠진다
    "two_messages_first": "3", "two_messages_second": "0",              # 한 번의 출력에서 둘째 메시지가 사라진다
    "coupling_twice": "4",                                              # 두 번 등록한 결합은 두 번 전달한다
    "receiver_timer": "0", "receiver_timer_kept": "2",                  # 입력을 받으면 다음 사건 시각을 다시 잡는다
    "simultaneous_order": "b@1,a@1,a@2,b@2,b@3,a@3,a@4,b@4",            # 같은 시각의 순서가 눈금마다 뒤바뀐다
    "self_coupled": "6",
    "boundary_count": "4", "boundary_ports": "a.out,a.out,a.out,a.out",    # 경계로 나간 출력에 경계의 포트 이름이 없다
    "external_input_passive": "ext-r@3", "external_input_same_time": "1",
    "external_input_zero_delay": "r@3",                                 # 시각 2의 입력에 바로 반응할 모델이 시각 3에 낸다
    "late_creation": "b@3,b@5,b@7,b@9",                                 # 시각 3에 만든 주기 2의 모델이 시각 3에 낸다
    "flat_boundary": "30", "flat_relays": "10,10,10",
    "nested_boundary": "12", "nested_relays": "1,1,10",                 # 결합 모델 안에 넣으면 결과가 다르다
    "destructor_never_run": "0", "destructor_after_run": "0", "virtual_destructor_model": "0",
}


@fact
def test_fact_engine_properties(tmp_path):
    lib = executor().lib
    program = str(tmp_path / "facts")
    built = subprocess.run(["g++", "-std=c++20", "-O1", "-pthread", "-I", os.path.join(HOME, "cevsim", "include"), FACTS,
                            lib._name, f"-Wl,-rpath,{os.path.dirname(lib._name)}", "-o", program], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr[-2000:]
    out = subprocess.run([program], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    got = dict(line.split(" ", 1) for line in out.stdout.splitlines() if " " in line)
    assert got == EXPECTED


@fact
def test_fact_native_models_show_the_same_properties_through_the_executor():
    """실행기가 고유 모델을 그대로 올리므로 엔진의 성질이 그대로 나타난다."""
    cx = executor(1.0)
    plan = st.node({}, {"a": tick(), "c": tick(period=5.0, keep=True), "d": tick(period=5.0)}, ic=[(("a", "out"), ("c", "inp"))])
    sim = cx.build(plan, NATIVE)
    fired = collections.Counter(p for _, p, _, _ in sim.run(12.0))
    assert fired == {("a",): 12, ("c",): 2}                  # d는 한 번도 내지 못한다
    sim.close()
    plan = st.node({}, {"a": tick(twice=True), "b": relay(), "c": relay()},
                   ic=[(("a", "out"), ("b", "inp")), (("a", "out2"), ("c", "inp"))])
    plan["children"]["a"]["ports"]["out2"] = ("T", "out")
    sim = cx.build(plan, NATIVE)
    fired = collections.Counter((p, port) for _, p, port, _ in sim.run(3.0))
    assert fired == {(("a",), "out"): 3, (("a",), "out2"): 3, (("b",), "out"): 3}      # out2로 낸 것은 c에 닿지 않는다
    sim.close()


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
