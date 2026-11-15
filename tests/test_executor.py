"""실행기를 붙이는 SES: 바인딩, 실행 가능성, 실현, 실행기 사이의 대응
(docs/ses-platform/14_executors.md 의 정리 18, 19, 22와 예시).
"""

import collections
import json
import os
import random
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import rand_binding, rand_system_document  # noqa: E402
from test_structure import rand_structure  # noqa: E402

from examples import processing_mb, sensor_node_mb  # noqa: E402
from ses_core import classic, devs, hw, load_ses, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core import structure as st  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.coupling import Coupling  # noqa: E402
from ses_core.decisions import Choice, DecisionSet, apply, choice_table, load_decisions, patterns  # noqa: E402
from ses_core.devs import INF, Atomic, DevsExecutor, simulate  # noqa: E402
from ses_core.diagnose import analyze  # noqa: E402
from ses_core.executor import Bind, Binding, Executor, Module  # noqa: E402
from ses_core.extension import Layered, interpret, prune, violations  # noqa: E402
from ses_core.skeleton import skeleton  # noqa: E402
from ses_core.unfold import unfold_annotated, unfold_layered, variable_domains  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "examples")


def shape(n: dict) -> tuple:
    """구조의 모양: 구성요소, 포트, 결합. 필수 표시와 모듈은 뺀다."""
    return (tuple(sorted((p, tuple(d)) for p, d in n["ports"].items())),
            tuple((k, shape(c)) for k, c in sorted(n["children"].items())),
            tuple(sorted(set(n["eic"]))), tuple(sorted(set(n["eoc"]))), tuple(sorted(set(n["ic"]))))


def named(name):
    class Named(Executor):
        pass
    Named.name = name
    return Named()


# ---------------------------------------------------------------------------
# 예시 1: DEVS 실행기를 붙이면 SES/MB가 된다
# ---------------------------------------------------------------------------

def processing(binding=None, library=None):
    L0 = unfold_layered(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))
    binding = binding or X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.devs.yaml"))
    return X.attach(L0, DevsExecutor(), binding, library or processing_mb.LIBRARY)


def run(L, ext, V, until=20.0, flat=False):
    model = X.realize(L, ext, DevsExecutor(), V)
    return model, devs._leaves(model), simulate(model, until, flat=flat)


def test_processing_system_runs_as_ses_mb():
    L, ext = processing()
    variants = sem(L.ses)
    assert len(variants) == 15 and X.executable_variants(L, ext) == variants
    seen = set()
    for V in variants:
        model, leaves, log = run(L, ext, V)
        servers = [a for p, a in leaves.items() if p[0] == "ServerPool"]
        gen, buf, col = leaves[("Generator",)], leaves[("Buffer",)], leaves[("Collector",)]
        busy = sum(s.phase == "busy" for s in servers)
        assert gen.count == 20 == len(col.done) + len(buf.queue) + busy + buf.dropped      # 일감은 사라지지 않는다
        assert len(col.done) == (9 if len(servers) == 1 else 18)                           # 서버가 둘이면 밀리지 않는다
        assert log == run(L, ext, V, flat=True)[2]                                         # 계층 실행과 평탄 실행이 같다
        assert shape(devs.observe(model)) == shape(interpret(L, V)["devs"])                 # 만든 모델의 구조가 R(V)다
        seen.add((type(buf).__name__, len(servers)))
    assert len(seen) == 15


def test_decision_file_to_running_model():
    """결정 집합으로 변이 하나를 정하고, 그 변이를 모델로 만들어 돌린다."""
    L, ext = processing()
    ds = load_decisions(os.path.join(EXAMPLES, "processing_system.decisions.yaml"))
    pes = prune(L, *patterns(L.ses, ds))
    (V,) = sem(pes.ses)
    assert X.plan(pes, ext, V) == X.plan(L, ext, V)          # 계획은 변이만으로 정해진다
    model, leaves, log = run(pes, ext, V)
    assert type(leaves[("Buffer",)]).__name__ == "PriorityBuffer"
    assert sorted(p[1] for p in leaves if p[0] == "ServerPool") == ["server_0", "server_1", "server_2", "server_3"]
    assert shape(devs.observe(model)) == shape(interpret(L, V)["devs"])     # 만든 모델의 구조가 실현 모델 R(V)다
    assert len(leaves[("Collector",)].done) == 18


def test_behaviour_lives_in_the_model_base_and_is_invisible_to_the_ses():
    """모듈의 본체를 바꿔도 SES 쪽의 모든 판정이 같다. 달라지는 것은 실행 결과뿐이다."""
    class Hasty(processing_mb.Server):                       # 인터페이스는 같고 하는 일이 다른 본체
        def external(self, elapsed, bag):
            was = self.phase
            super().external(elapsed, bag)
            if was == "idle" and self.phase == "busy":
                self.left = self.service_time / 2

    L, ext = processing()
    lib = dict(processing_mb.LIBRARY)
    old = lib["Server"]
    lib["Server"] = Module("Server", old.ports, old.required, old.params, Hasty)
    L2, ext2 = processing(library=lib)
    differ = 0
    for V in sem(L.ses):
        assert violations(X.alone(L, ext), V) == violations(X.alone(L2, ext2), V)
        assert X.plan(L, ext, V) == X.plan(L2, ext2, V)
        differ += run(L, ext, V)[2] != run(L2, ext2, V)[2]
    assert differ == 15


def test_black_box_binding_moves_the_frontier():
    """분해를 가진 정의에 모듈을 묶으면 그 아래는 펼치지 않는다. 바깥은 그대로다."""
    b = X.load_binding(os.path.join(EXAMPLES, "processing_system.binding.devs.yaml"))
    box = Binding("devs", {**{k: v for k, v in b.map.items() if k != "Server"}, "ServerPool": Bind("Pool")}, b.target)
    L, ext = processing()
    Lb, extb = processing(binding=box)
    assert len(X.executable_variants(Lb, extb)) == 15        # Server에 묶인 것이 없어도 된다
    for V in sem(L.ses):
        full, cut = X.plan(L, ext, V), X.plan(Lb, extb, V)
        assert X.frontier(cut) == [("Generator",), ("Buffer",), ("ServerPool",), ("Collector",)]
        assert cut["children"]["ServerPool"]["module"] == "Pool"
        assert shape(cut) == shape(st.quotient(full, X.frontier(cut)))          # 몫: 같은 인터페이스의 원자로 바꾼 것
        assert st.flatten(cut) == st.flatten(st.quotient(full, X.frontier(cut)))
        model, leaves, log = run(Lb, extb, V)
        assert len(leaves) == 4 and len(leaves[("Collector",)].done) == 9       # 풀 전체가 서버 하나처럼 움직인다


# ---------------------------------------------------------------------------
# 예시 2: 같은 SES에 실행기 둘
# ---------------------------------------------------------------------------

def sensor_node():
    doc = load_ses(os.path.join(EXAMPLES, "sensor_node.ses.yaml"))
    L = unfold_layered(doc)
    with open(os.path.join(EXAMPLES, "sensor_node.hwlib.yaml"), encoding="utf-8") as f:
        lib = yaml.safe_load(f)
    dx, hx = DevsExecutor(), hw.HwExecutor(hw.load_rules(lib))
    L, de = X.attach(L, dx, X.load_binding(os.path.join(EXAMPLES, "sensor_node.binding.devs.yaml")),
                     sensor_node_mb.LIBRARY)
    L, he = X.attach(L, hx, X.load_binding(os.path.join(EXAMPLES, "sensor_node.binding.hw.yaml")),
                     X.load_library_dict(lib))
    return doc, L, (dx, de), (hx, he)


def has(V, name):
    return any(n[-1] == name for n in V)


def test_one_ses_two_executors():
    doc, L, (dx, de), (hx, he) = sensor_node()
    variants = sem(L.ses)
    D, H = set(X.executable_variants(L, de)), set(X.executable_variants(L, he))
    assert (len(variants), len(D), len(H), len(D & H)) == (112, 56, 24, 8)
    assert all(not violations(L.only("devs", "attr"), V) for V in variants)   # 구조만 보면 112개가 모두 적격이다
    assert D == {V for V in variants if has(V, "WifiRadio")}                  # LoRa의 시뮬레이션 모델이 없다
    for V in H:
        kinds = sorted(n[-1] for n in V if n[-1] in ("TempProbe", "HumidityProbe"))
        assert kinds in (["TempProbe"], ["HumidityProbe"], ["HumidityProbe", "TempProbe"])     # 주소가 겹치지 않는다
        assert not (has(V, "Battery") and has(V, "WifiRadio"))                # 전지로는 와이파이를 못 돌린다
    codes = collections.Counter(code for V in variants for _, code, _, _ in violations(X.alone(L, he), V))
    assert set(codes) == {"H2", "H3"}
    assert {code for V in variants for _, code, _, _ in violations(X.alone(L, de), V)} == {"B1"}

    # 정리 19: 실행 가능 핵은 가지치기이고, 실행기를 얹는 순서와 무관하다
    core_d, core_h = X.exec_core(L, de), X.exec_core(L, he)
    assert set(sem(core_d.ses)) == D and set(sem(core_h.ses)) == H
    both = X.exec_core(core_d, he)
    assert set(sem(both.ses)) == set(sem(X.exec_core(core_h, de).ses)) == D & H
    assert set(sem(X.exec_core(both, he).ses)) == D & H                      # 멱등
    # 둘 다 되는 변이들의 선택 지점 표: 무엇이 남는가
    table = {(p.owner, p.group): p.remaining
             for p in choice_table(L.ses, both.ses, variable_domains(doc))}
    assert table[("probes", "")] == (1, 2)
    assert table[("Radio", "link")] == ("WifiRadio",) and table[("Supply", "source")] == ("UsbSupply",)
    assert table[("Display", "fitted")] == ("Oled", "NoDisplay")


def test_the_two_realizations_have_the_same_connections():
    doc, L, (dx, de), (hx, he) = sensor_node()
    ds = DecisionSet(variables={"probes": (2,)}, choose=(
        Choice(path=("SensorNode", "Sensing", "probe_0"), specialization="kind", alternative=("TempProbe",)),
        Choice(path=("SensorNode", "Sensing", "probe_1"), specialization="kind", alternative=("HumidityProbe",)),
        Choice(at="Radio", specialization="link", alternative=("WifiRadio",)),
        Choice(at="Supply", specialization="source", alternative=("UsbSupply",)),
        Choice(at="Display", specialization="fitted", alternative=("Oled",))))
    (V,) = sem(apply(L.ses, ds))
    assert X.executable(L, de, V) and X.executable(L, he, V)
    p_devs, p_hw = X.plan(L, de, V), X.plan(L, he, V)
    assert shape(p_devs) == shape(p_hw) == shape(interpret(L, V)["devs"])     # 전선이 같으면 계획의 구조가 같다
    assert [c["module"] for _, c in st.walk(p_devs) if st.is_atom(c)] == \
        ["PowerSource", "Controller", "Probe", "Probe", "Radio", "Display"]
    assert [c["module"] for _, c in st.walk(p_hw) if st.is_atom(c)] == \
        ["UsbPower", "McuBoard", "TempSensor", "HumiditySensor", "WifiModule", "OledPanel"]

    board = X.realize(L, he, hx, V)                                          # 하드웨어: 부품표, 배선표, 설정
    assert [(e["ref"], e["part"]) for e in board["bom"]] == [
        ("Supply", "USB-5V"), ("Controller", "MCU-A"), ("Sensing/probe_0", "TEMP-A"),
        ("Sensing/probe_1", "HUMI-A"), ("Radio", "WIFI-A"), ("Display", "OLED-A")]
    assert board["config"]["Sensing/probe_0"] == {"address": 72, "load_ma": 1}
    assert {"from": "Sensing/probe_1.data", "to": "Controller.sense", "type": "Reading", "bus": "I2C"} in board["nets"]
    assert collections.Counter(n["bus"] for n in board["nets"]) == {"rail": 5, "I2C": 2, "UART": 1, "SPI": 1}

    model = X.realize(L, de, dx, V)                                          # DEVS: 돌아가는 모델
    log = simulate(model, until=5.0)
    leaves = devs._leaves(model)
    assert len(leaves[("Radio",)].received) == 5 and leaves[("Radio",)].received[-1]["sources"] == [64, 72]
    assert log == simulate(X.realize(L, de, dx, V), until=5.0, flat=True)

    # 따름정리 18.1: 두 산출물에서 구조를 다시 읽으면 평탄화된 연결이 같다
    flat = lambda n: {((hw.ref(s), sp), (hw.ref(t), tp)) for ((s, sp), (t, tp)) in st.flatten(n)}      # noqa: E731
    from_board = {((s[0], sp), (t[0], tp)) for ((s, sp), (t, tp)) in st.flatten(hx.observe(board))}
    assert flat(dx.observe(model)) == from_board == flat(p_hw)
    assert shape(dx.observe(model)) == shape(p_devs)                         # 실행기는 받은 구조를 그대로 만든다


def test_mixed_realization_has_an_exact_seam():
    """제어기와 무선은 실물로, 나머지는 시뮬레이션으로 둘 때 둘 사이를 잇는 선이 정확히 정해진다."""
    doc, L, (dx, de), (hx, he) = sensor_node()
    V = next(V for V in sem(L.ses) if X.executable(L, de, V) and X.executable(L, he, V)
             and has(V, "Oled") and has(V, "array[1]"))
    p = X.plan(L, he, V)
    grouped, seam = X.assign(p, lambda path, c: "hw" if path[0] in ("Controller", "Radio") else "sim")
    text = sorted(f"{s[0][1]}.{s[1]} > {t[0][1]}.{t[1]}" for s, t in seam)
    assert text == ["Controller.show > Display.frame", "Sensing/probe_0.data > Controller.sense",
                    "Supply.out > Controller.pwr", "Supply.out > Radio.pwr"]
    assert sorted(grouped["children"]) == ["hw", "sim"] and len(grouped["ic"]) == 4
    inside = {(s, t) for s, t in st.flatten(grouped) if s[0][0] == t[0][0]}
    assert len(inside) + len(seam) == len(st.flatten(p))                     # 연결은 안쪽과 이음매로 나뉜다


def test_executor_diagnostics_reach_the_editor():
    doc, L, (dx, de), (hx, he) = sensor_node()
    with open(os.path.join(EXAMPLES, "sensor_node.ses.yaml"), encoding="utf-8") as f:
        m = E.from_dict(yaml.safe_load(f))
    a = analyze(m, attach=lambda L0: X.attach(L0, dx, de.binding, de.library)[0])
    assert (a.variants, a.wellformed) == (112, 56)
    (d,) = a.errors
    assert (d.code, d.layer, d.address, d.affected, d.cause_covers) == ("B1", "exec:devs", "entities/Radio", (56, 112), 56)
    assert d.cause["choose"] == [{"at": "Radio", "specialization": "link", "alternative": "LoraRadio"}]
    assert [x.data["option"] for x in a.of("DEAD")] == ["LoraRadio"]

    a = analyze(m, attach=lambda L0: X.attach(L0, hx, he.binding, he.library)[0])
    assert (a.variants, a.wellformed) == (112, 24)
    budget = [d for d in a.errors if d.code == "H3"]
    assert [(d.address, d.affected, d.cause_covers) for d in budget] == [("entities/Supply", (28, 112), 28)]
    assert budget[0].cause["choose"] == [
        {"at": "Supply", "specialization": "source", "alternative": "Battery"},
        {"at": "Radio", "specialization": "link", "alternative": "WifiRadio"}]
    clash = [d for d in a.errors if d.code == "H2"]
    assert {d.address for d in clash} == {"entities/Controller"} and len(clash) == 2
    assert sorted(x.data["option"] for x in a.of("DEAD")) == [3, 3]          # 탐침 셋은 하드웨어로 만들 수 없다


# ---------------------------------------------------------------------------
# 바인딩의 규칙
# ---------------------------------------------------------------------------

SMALL = {
    "ses": "1.0", "name": "R", "port_types": {"T": {}},
    "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["Src", "Dev"],
                                              "couplings": [{"from": "Src.o", "to": "Dev.i"}]}}},
        "Src": {"ports": {"o": {"type": "T", "direction": "out"}}},
        "Dev": {"ports": {"i": {"type": "T", "direction": "in"}},
                "attributes": {"gain": {"type": "int", "default": 2}},
                "specializations": {"size": {"alternatives": ["Small", "Large"]},
                                    "grade": {"alternatives": ["Basic", "Pro"]}}},
        "Small": {"extends": "Dev"},
        "Large": {"extends": "Dev", "attributes": {"gain": {"type": "int", "default": 5}}},
        "Basic": {"extends": "Dev"},
        "Pro": {"extends": "Dev"},
    },
}

SRC = Module("S", {"o": ("T", "out")})
DEV = {"i": ("T", "in")}


def small(entries, library, doc=None):
    L0 = unfold_layered(load_ses_dict(doc or SMALL))
    L, ext = X.attach(L0, Executor(), Binding("x", {k: Bind(*v) if isinstance(v, tuple) else Bind(v)
                                                    for k, v in entries.items()}), library)
    out = {}
    for V in sem(L.ses):
        key = tuple(n for n in ("Small", "Large", "Basic", "Pro") if has(V, n))
        p = X.plan(L, ext, V)
        dev = p["children"]["Dev"]
        out[key] = (sorted({code for _, code, _, _ in violations(X.alone(L, ext), V)}), dev["module"], dev["params"])
    return out


def test_binding_is_inherited_and_the_most_specific_wins():
    lib = {m.name: m for m in (SRC, Module("D", DEV), Module("DL", DEV), Module("DP", DEV))}
    got = small({"Src": "S", "Dev": "D"}, lib)
    assert {v[1] for v in got.values()} == {"D"} and all(v[0] == [] for v in got.values())    # 바탕에 묶으면 대안이 물려받는다
    got = small({"Src": "S", "Dev": "D", "Large": "DL"}, lib)
    assert got[("Large", "Basic")][1] == got[("Large", "Pro")][1] == "DL"                     # 더 구체적인 것이 이긴다
    assert got[("Small", "Basic")][1] == "D"
    got = small({"Src": "S", "Large": "DL", "Pro": "DP"}, lib)
    assert got[("Small", "Basic")][0] == ["B1"]                                             # 묶인 것이 없다
    assert got[("Large", "Basic")][:2] == ([], "DL") and got[("Small", "Pro")][:2] == ([], "DP")
    assert got[("Large", "Pro")][:2] == (["B2"], None)                                      # 서로 다른 갈래가 각각 묶였다
    got = small({"Src": "S", "Dev": "D", "Large": "DL", "Pro": "DP"}, lib)
    assert got[("Large", "Pro")][0] == ["B2"] and got[("Small", "Basic")][:2] == ([], "D")
    assert small({"Src": "S", "Dev": "Nope"}, lib)[("Small", "Basic")][0] == ["B1"]         # 라이브러리에 없는 모듈


def test_module_interface_and_parameters_are_checked():
    only = lambda entries, mod: small(entries, {"S": SRC, mod.name: mod})[("Small", "Basic")]    # noqa: E731
    assert only({"Src": "S", "Dev": "D"}, Module("D", {"i": ("T", "out")}))[0] == ["B3"]    # 방향이 다르다
    assert only({"Src": "S", "Dev": "D"}, Module("D", {}))[0] == ["B3"]                     # 포트가 없다
    assert only({"Src": "S", "Dev": "D"}, Module("D", {**DEV, "en": ("T", "in")}, ("en",)))[0] == ["B3"]
    assert only({"Src": "S", "Dev": "D"}, Module("D", {**DEV, "aux": ("T", "out")}))[0] == []   # 남는 포트는 써도 된다
    assert only({"Src": "S", "Dev": "D"}, Module("D", DEV, (), {"k": ("int",)}))[0] == ["B4"]   # 줄 값이 없다
    assert only({"Src": "S", "Dev": "D"}, Module("D", DEV, (), {"k": ("int", 7)}))[2] == {"k": 7}
    assert only({"Src": "S", "Dev": "D"}, Module("D", DEV, (), {"gain": ("int",)}))[2] == {"gain": 2}
    assert only({"Src": "S", "Dev": "D"}, Module("D", DEV, (), {"gain": ("str",)}))[0] == ["B4"]
    renamed = small({"Src": "S", "Dev": ("D", {"k": "gain"})}, {"S": SRC, "D": Module("D", DEV, (), {"k": ("int",)})})
    assert renamed[("Small", "Basic")][2] == {"k": 2} and renamed[("Large", "Pro")][2] == {"k": 5}


def test_module_requirements_join_the_end_to_end_condition():
    """모듈이 요구하는 입력은 SES가 필수로 표시하지 않았어도 원천에 닿아야 한다."""
    lib = {"S": SRC, "D": Module("D", DEV, ("i",))}
    assert small({"Src": "S", "Dev": "D"}, lib)[("Small", "Basic")][0] == []
    cut = json.loads(json.dumps(SMALL))
    cut["entities"]["R"]["aspects"]["a"]["couplings"] = []
    L0 = unfold_layered(load_ses_dict(cut))
    assert all(not violations(L0, V) for V in sem(L0.ses))                                  # 구조 계층은 문제 삼지 않는다
    assert small({"Src": "S", "Dev": "D"}, lib, cut)[("Small", "Basic")][0] == ["C5"]


DANGLING = {
    "ses": "1.0", "name": "R", "port_types": {"T": {}},
    "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["A", "Box"]}}},
        "A": {"ports": {"o": {"type": "T", "direction": "out"}}},
        "Box": {"ports": {"i": {"type": "T", "direction": "in"}},
                "aspects": {"b": {"parts": ["L"], "couplings": [{"from": "i", "to": "L.x"}]}}},
        "L": {"ports": {"x": {"type": "T", "direction": "in", "required": True}}},
    },
}


def test_c5_catches_what_the_one_step_condition_misses():
    """08 문서의 C4까지 통과하는 문서에서 원자의 필수 입력에 아무것도 닿지 않는다."""
    L0 = unfold_layered(load_ses_dict(DANGLING))
    (V,) = sem(L0.ses)
    assert violations(L0, V) == []
    lib = {"MA": Module("MA", {"o": ("T", "out")}), "ML": Module("ML", {"x": ("T", "in")})}
    L, ext = X.attach(L0, Executor(), Binding("x", {"A": Bind("MA"), "L": Bind("ML")}), lib)
    found = violations(X.alone(L, ext), V)
    assert [(code, path) for _, code, path, _ in found] == [("C5", ("R", "a", "Box", "b", "L"))]
    fixed = json.loads(json.dumps(DANGLING))
    fixed["entities"]["R"]["aspects"]["a"]["couplings"] = [{"from": "A.o", "to": "Box.i"}]
    L0 = unfold_layered(load_ses_dict(fixed))
    L, ext = X.attach(L0, Executor(), Binding("x", {"A": Bind("MA"), "L": Bind("ML")}), lib)
    assert X.executable_variants(L, ext) == sem(L.ses)


def test_example_files_conform_to_the_binding_schema():
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(EXAMPLES, "..", "schema", "binding.schema.json"), encoding="utf-8") as f:
        validator = jsonschema.Draft202012Validator(json.load(f))
    for name in ("processing_system.binding.devs.yaml", "processing_system.binding.pyevsim.yaml",
                 "processing_system.binding.cevsim.yaml",
                 "sensor_node.binding.devs.yaml", "sensor_node.binding.hw.yaml", "sensor_node.hwlib.yaml"):
        with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
            d = yaml.safe_load(f)
        assert list(validator.iter_errors(d)) == [], name
        if "binding" in d:
            assert Binding.from_dict(d).to_dict() == d
    assert list(validator.iter_errors({"binding": "1.0", "map": {}}))        # 실행기 이름이 없다
    assert list(validator.iter_errors({"library": "1.0", "executor": "hw", "modules": {"M": {"ports": {"p": {}}}}}))


# ---------------------------------------------------------------------------
# 무작위 문서와 무작위 바인딩
# ---------------------------------------------------------------------------

UNIT = 0.25                                                 # generic과 quirky의 시간 전진은 모두 이 시간 단위의 정수배다


def generic(ports: dict):
    """인터페이스만으로 움직이는 모델. 받은 것의 수가 내보내는 값에 들어가므로 전달이 달라지면 기록이 달라진다."""
    class Generic(Atomic):
        PORTS = dict(ports)

        def init(self):
            self.delay = 0.5 + (sum(map(ord, self.name)) % 7) / 4
            self.left, self.sent, self.seen = self.delay, 0, 0

        def ta(self):
            return self.left

        def output(self):
            return {p: [(self.name, self.sent, self.seen)] for p, (_, d) in sorted(ports.items()) if d == "out"}

        def internal(self):
            self.sent += 1
            self.left = INF

        def external(self, elapsed, bag):
            if self.left != INF:
                self.left -= elapsed
            self.seen += sum(len(v) for v in bag.values())
            if self.left == INF and self.sent < 4:
                self.left = self.delay

    return Generic


def quirky(ports: dict):
    """출력마다 값을 0개에서 2개까지 내는 모델. 받은 것을 그대로 적어 두므로 전달의 횟수, 내용, 순서가 달라지면 상태가 달라진다."""
    outs = sorted(p for p, (_, d) in ports.items() if d == "out")

    class Quirky(Atomic):
        PORTS = dict(ports)

        def init(self):
            self.delay = 0.5 + (sum(map(ord, self.name)) % 7) / 4
            self.left, self.sent, self.heard = self.delay, 0, []

        def ta(self):
            return self.left

        def output(self):
            return {p: [(self.name, self.sent, k) for k in range((self.sent + i) % 3)] for i, p in enumerate(outs)}

        def internal(self):
            self.sent += 1
            self.left = self.delay if self.sent < 3 else INF

        def external(self, elapsed, bag):
            if self.left != INF:
                self.left -= elapsed
            self.heard.append((self.now, elapsed, [(p, list(v)) for p, v in bag.items()]))     # 묶음을 훑는 순서 그대로
            if self.left == INF and self.sent < 5:
                self.left = self.delay

        def confluent(self, bag):
            self.heard.append(("both", self.now))
            self.internal()
            self.external(0.0, bag)

    return Quirky


def state(leaves: dict) -> dict:
    """원자 모델의 마지막 상태. 사건 기록에 드러나지 않는 차이를 본다."""
    return {p: {k: v for k, v in vars(a).items() if k in ("left", "sent", "seen", "heard")} for p, a in leaves.items()}


def library_of(mods: dict) -> dict:
    return {n: Module(n, m["ports"], tuple(m["required"]), m["params"], generic(m["ports"])) for n, m in mods.items()}


def model_of(n: dict, path=(), body=generic):
    """구조에서 바로 DEVS 모델을 만든다. 원자마다 인터페이스에 맞는 모델을 둔다."""
    if st.is_atom(n):
        return body(n["ports"])("/".join(path))
    return devs.Coupled("", n["ports"], {k: model_of(c, path + (k,), body) for k, c in n["children"].items()},
                        n["eic"], n["eoc"], n["ic"])


def setup(seed, executors=("x",)):
    rng = random.Random(seed)
    d = rand_system_document(rng)
    L = unfold_layered(load_ses_dict(d))
    exts = []
    for name in executors:
        b, mods = rand_binding(rng, d, name)
        L, ext = X.attach(L, named(name), Binding.from_dict(dict(b, time_unit=UNIT)), library_of(mods))
        exts.append(ext)
    return rng, d, L, exts


def rand_pruning(rng, L):
    from test_decisions import rand_decisions
    ds = rand_decisions(rng, L.ses)
    return prune(L, *patterns(L.ses, ds))


STATS: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(200))
def test_theorem18_realization_exists_is_intrinsic_and_faithful(seed):
    rng, d, L, (ext,) = setup(seed)
    variants = sem(L.ses)
    good = [V for V in variants if X.executable(L, ext, V)]
    sub = rand_pruning(rng, L)                               # 다른 가지치기에서 보아도 같은 판정, 같은 계획
    for V in (sem(sub.ses) if sub is not None else []):
        assert X.executable(sub, ext, V) == (V in good)
        assert X.plan(sub, ext, V) == X.plan(L, ext, V)
        STATS["seen_in_pruning"] += 1
    for V in rng.sample(good, min(6, len(good))):
        p = X.plan(L, ext, V)
        assert st.violations(p) == [] and st.ungrounded(p) == []
        whole = interpret(L, V)["devs"]                      # 실현 모델 R(V)
        assert shape(p) == shape(st.quotient(whole, X.frontier(p)))      # 계획은 R(V)를 전선에서 자른 몫이다
        model = X.realize(L, ext, DevsExecutor(), V)
        assert shape(devs.observe(model)) == shape(p)        # 충실성: 만든 것의 구조가 받은 구조다
        assert all(c["module"] in ext.library for _, c in st.walk(p) if st.is_atom(c))
        STATS["realized"] += 1
        STATS["black_box"] += any(not st.is_atom(st.subtree(whole, a)) for a in X.frontier(p))
    for bad in [V for V in variants if V not in good][:1]:
        with pytest.raises(ValueError):
            X.realize(L, ext, DevsExecutor(), bad)
    STATS["docs"] += 1


@pytest.mark.parametrize("seed", range(200))
def test_theorem19_executable_core_and_two_executors(seed):
    rng, d, L, (a, b) = setup(seed, ("a", "b"))
    variants = sem(L.ses)
    A = {V for V in variants if X.executable(L, a, V)}
    B = {V for V in variants if X.executable(L, b, V)}
    var = lambda M: set(sem(M.ses)) if M is not None else set()             # noqa: E731
    core_a, core_b = X.exec_core(L, a), X.exec_core(L, b)
    assert var(core_a) == A and var(core_b) == B             # 실행 가능 핵의 변이가 실행 가능한 변이 전체다
    if core_a is not None:
        assert var(X.exec_core(core_a, a)) == A              # 멱등
        assert var(X.exec_core(core_a, b)) == A & B          # 두 실행기: 순서와 무관하게 교집합
    if core_b is not None:
        assert var(X.exec_core(core_b, a)) == A & B
    sub = rand_pruning(rng, L)                               # 결정을 먼저 하든 핵을 먼저 구하든 같다
    if sub is not None:
        assert var(X.exec_core(sub, a)) == var(sub) & A
        if core_a is not None:
            assert var(X.exec_core(sub, a)) == {V for V in var(core_a) if V in var(sub)}
    STATS["both"] += len(A & B)
    STATS["only_one"] += len(A ^ B)
    STATS["all_executable_docs"] += A == set(variants)


@pytest.mark.parametrize("seed", range(200))
def test_corollary_two_executors_agree_at_a_common_cut(seed):
    """전선이 달라도, 둘보다 굵은 절단에서 보면 두 계획은 같은 구조다."""
    rng, d, L, (a, b) = setup(seed, ("a", "b"))
    for V in sem(L.ses):
        if not (X.executable(L, a, V) and X.executable(L, b, V)):
            continue
        pa, pb = X.plan(L, a, V), X.plan(L, b, V)
        union = set(X.frontier(pa)) | set(X.frontier(pb))
        cut = [c for c in union if not any(o != c and c[:len(o)] == o for o in union)]
        if () in cut:
            continue
        assert shape(st.quotient(pa, cut)) == shape(st.quotient(pb, cut))
        assert st.flatten(st.quotient(pa, cut)) == st.flatten(st.quotient(pb, cut))
        STATS["agree"] += 1
        STATS["different_frontiers"] += X.frontier(pa) != X.frontier(pb)


@pytest.mark.parametrize("seed", range(300))
def test_devs_closure_under_coupling(seed):
    """계층대로 실행한 것과 평탄화해서 실행한 것의 사건 기록이 같다. 문헌의 정리를 확인만 한다."""
    n = rand_structure(random.Random(seed))
    hier, flat = model_of(n), model_of(n)
    log = simulate(hier, until=8.0, unit=UNIT)
    assert log == simulate(flat, until=8.0, flat=True, unit=UNIT)
    assert state(devs._leaves(hier)) == state(devs._leaves(flat))
    STATS["events"] += len(log)
    STATS["delivered"] += sum(1 for _, _, _, (_, _, seen) in log if seen > 0)


@pytest.mark.parametrize("seed", range(200))
def test_devs_closure_with_empty_and_multiple_outputs(seed):
    """출력이 값을 0개, 1개, 2개 가질 때에도 두 실행이 같다. 상태까지 본다."""
    n = rand_structure(random.Random(seed))
    hier, flat = model_of(n, body=quirky), model_of(n, body=quirky)
    log = simulate(hier, until=8.0, unit=UNIT)
    assert log == simulate(flat, until=8.0, flat=True, unit=UNIT)
    assert state(devs._leaves(hier)) == state(devs._leaves(flat))
    heard = [h for a in devs._leaves(hier).values() for h in a.heard if h[0] != "both"]
    STATS["quirky_events"] += len(log)
    STATS["quirky_bags"] += len(heard)
    STATS["quirky_long_bags"] += sum(1 for _, _, bag in heard if any(len(v) > 1 for _, v in bag))
    STATS["quirky_wide_bags"] += sum(1 for _, _, bag in heard if len(bag) > 1)


@pytest.mark.parametrize("seed", range(100))
def test_devs_closure_on_realized_plans(seed):
    rng, d, L, (ext,) = setup(seed)
    for V in [V for V in sem(L.ses) if X.executable(L, ext, V)][:4]:
        hier, flat = X.realize(L, ext, DevsExecutor(), V), X.realize(L, ext, DevsExecutor(), V)
        assert simulate(hier, until=6.0) == simulate(flat, until=6.0, flat=True)
        assert state(devs._leaves(hier)) == state(devs._leaves(flat))


def labelled(n: dict, labels) -> tuple:
    """구조와, 구성요소마다 합쳐진 정의들의 이름. labels는 구성요소에서 이름 목록을 읽는 함수다."""
    return (tuple(sorted(labels(n))), st.canon(dict(n, children={})),
            tuple((k, labelled(c, labels)) for k, c in sorted(n["children"].items())))


def both_semantics(doc):
    S, ann = unfold_annotated(doc)
    L = Layered(S, ann.void, (Coupling(ann.ports, ann.coup),))
    core = Layered(S, ann.void)
    algebraic, skipped = set(), 0
    for V in sem(S):
        if violations(core, V) or any(code == "M" for _, code, _, _ in violations(L, V)):
            skipped += 1                                     # 합칠 수 없는 변이: 두 쪽 모두 내놓지 않는다
            continue
        sigma = tuple(sorted((n[1][1:], n[2]) for n in V if len(n) == 3 and n[1].startswith("$")))
        sk = skeleton(S.tree, ann.void, V)                   # 대수 쪽의 정의 이름은 뼈대에서 읽는다

        def attach(n, comp):
            return dict(n, labels=list(comp.labels),
                        children={k: attach(c, comp.parts[k]) for k, c in n["children"].items()})

        algebraic.add((sigma, labelled(attach(interpret(L, V)["devs"], sk), lambda n: n["labels"])))
    procedural = {(tuple(sorted((k, str(v)) for k, v in sigma.items())), labelled(n, lambda n: n["labels"]))
                  for sigma, n in classic.enumerate_classic(doc)}
    return algebraic, procedural, skipped


@pytest.mark.parametrize("seed", range(300))
def test_theorem22_classic_procedure_gives_the_same_models(seed):
    """위에서 아래로 고르고 조립하는 고전 절차와, 펼치고 열거하고 해석하는 대수의 길이 같은 모델들을 낸다."""
    doc = load_ses_dict(rand_system_document(random.Random(seed)))
    algebraic, procedural, skipped = both_semantics(doc)
    assert algebraic == procedural
    STATS["classic_models"] += len(procedural)
    STATS["classic_skipped"] += skipped


@pytest.mark.parametrize("name", ["processing_system.ses.yaml", "sensor_node.ses.yaml"])
def test_theorem22_on_the_examples(name):
    algebraic, procedural, skipped = both_semantics(load_ses(os.path.join(EXAMPLES, name)))
    assert algebraic == procedural and skipped == 0
    assert len(procedural) == {"processing_system.ses.yaml": 15, "sensor_node.ses.yaml": 112}[name]


def test_executor_samples_are_not_vacuous():
    if not STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["realized"] >= 300 and STATS["black_box"] >= 30 and STATS["seen_in_pruning"] >= 500, STATS
    assert STATS["both"] >= 100 and STATS["only_one"] >= 300 and STATS["all_executable_docs"] >= 5, STATS
    assert STATS["agree"] >= 100 and STATS["different_frontiers"] >= 20, STATS
    assert STATS["events"] >= 3000 and STATS["delivered"] >= 500, STATS
    assert STATS["quirky_events"] >= 1000 and STATS["quirky_bags"] >= 500, STATS
    assert STATS["quirky_long_bags"] >= 100 and STATS["quirky_wide_bags"] >= 20, STATS
    assert STATS["classic_models"] >= 2000 and STATS["classic_skipped"] >= 500, STATS


def test_variable_values_are_not_members_of_the_root_component():
    """변수는 뿌리의 specialization으로 부호화되지만, 그 값은 뿌리 구성요소에 합쳐지는 정의가 아니다.

    값과 같은 이름의 엔티티에 모듈이 묶여 있어도 뿌리가 그 모듈로 바뀌지 않는다.
    """
    d = {"ses": "1.0", "name": "R", "variables": {"mode": {"type": "enum", "values": ["fast", "slow"]}},
         "entities": {"R": {"root": True, "aspects": {"a": {"parts": ["fast"]}}}, "fast": {}}}
    L0 = unfold_layered(load_ses_dict(d))
    L, ext = X.attach(L0, Executor(), Binding("x", {"fast": Bind("M")}), {"M": Module("M")})
    for V in sem(L.ses):
        assert skeleton(L.ses.tree, L.void, V).labels == ("R",)
        p = X.plan(L, ext, V)
        assert p["module"] is None and X.frontier(p) == [("fast",)] and X.executable(L, ext, V)


TWICE = {
    "ses": "1.0", "name": "R", "port_types": {"T": {}},
    "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["A", "B"], "couplings": [
            {"from": "A.o", "to": "B.i"}, {"from": "A.o", "to": "B.i"}]}}},
        "A": {"ports": {"o": {"type": "T", "direction": "out"}}},
        "B": {"ports": {"i": {"type": "T", "direction": "in"}}},
    },
}


def test_a_coupling_written_twice_is_one_coupling():
    """결합은 관계다. 문서에 같은 결합을 두 번 적어도 구조와 실행은 한 번 적은 것과 같다.

    평탄화는 결합을 집합으로 보는데 계층 실행은 적힌 횟수만큼 날랐다. 두 실행이 어긋나던 자리다.
    """
    one = (("A", "o"), ("B", "i"))
    assert st.node({}, {}, ic=[one, one])["ic"] == [one]
    assert devs.Coupled("", {}, {}, ic=[one, one]).ic == [one]
    L0 = unfold_layered(load_ses_dict(TWICE))
    (V,) = sem(L0.ses)
    assert interpret(L0, V)["devs"]["ic"] == [one]
    assert [n["ic"] for _, n in classic.enumerate_classic(load_ses_dict(TWICE))] == [[one]]
    lib = library_of({"MA": {"ports": {"o": ("T", "out")}, "required": [], "params": {}},
                      "MB": {"ports": {"i": ("T", "in")}, "required": [], "params": {}}})
    L, ext = X.attach(L0, DevsExecutor(), Binding("devs", {"A": Bind("MA"), "B": Bind("MB")}, time_unit=UNIT), lib)
    p = X.plan(L, ext, V)
    assert p["ic"] == [one] and st.flatten(p) == {((("A",), "o"), (("B",), "i")): 1}
    received = []
    for flat in (False, True):
        model = X.realize(L, ext, DevsExecutor(), V)
        assert len(simulate(model, until=8.0, flat=flat)) == 1
        received.append(devs._leaves(model)[("B",)].seen)
    assert received == [1, 1]                                # 계층 실행과 평탄 실행에서 받은 수가 같다


class Sometimes(Atomic):
    """홀수 번째에만 값을 낸다. 짝수 번째의 출력은 값이 없는 목록이다."""
    PORTS = {"o": ("T", "out")}

    def init(self):
        self.k = 0

    def ta(self):
        return 1.0

    def output(self):
        return {"o": [self.k] if self.k % 2 else []}

    def internal(self):
        self.k += 1


class Witness(Atomic):
    PORTS = {"i": ("T", "in")}

    def init(self):
        self.seen = []

    def external(self, elapsed, bag):
        self.seen.append((self.now, elapsed, {p: list(v) for p, v in bag.items()}))


def test_an_output_without_values_is_not_an_event():
    """값이 없는 출력은 보내지 않은 것이다. 받는 쪽에 외부 전이가 일어나지 않는다.

    평탄 실행은 빈 묶음으로 외부 전이를 일으켰고 계층 실행은 일으키지 않았다. 두 실행이 어긋나던 자리다.
    """
    seen = []
    for flat in (False, True):
        model = devs.Coupled("", {}, {"s": Sometimes("s"), "w": Witness("w")}, ic=[(("s", "o"), ("w", "i"))])
        assert simulate(model, until=4.0, flat=flat) == [(2.0, ("s",), "o", 1), (4.0, ("s",), "o", 3)]
        seen.append(model.children["w"].seen)
    assert seen[0] == seen[1] == [(2.0, 2.0, {"i": [1]}), (4.0, 2.0, {"i": [3]})]


def test_structural_errors_above_the_frontier_block_execution():
    """적재기를 거치지 않고 만든 SES에서 결합의 방향이 틀리면 실행기가 그것을 먼저 알린다."""
    from ses_core.algebra import SES, asp, build, ent
    from ses_core.coupling import PortDecl
    T = build(ent("R", asp("a", ent("A"), ent("B"))))
    ports = {("R", "a", "A"): {"o": PortDecl("T", "out")}, ("R", "a", "B"): {"i": PortDecl("T", "out")}}
    coup = {("R", "a"): ((("A", "o"), ("B", "i")),)}
    L0 = Layered(SES(T), frozenset(), (Coupling(ports, coup),))
    lib = {"MA": Module("MA", {"o": ("T", "out")}), "MB": Module("MB", {"i": ("T", "out")})}
    L, ext = X.attach(L0, Executor(), Binding("x", {"A": Bind("MA"), "B": Bind("MB")}), lib)
    (V,) = sem(L.ses)
    assert [code for _, code, _, _ in violations(L0, V)] == ["C2"]
    assert [(code, path) for _, code, path, _ in violations(X.alone(L, ext), V)] == [("C2", ("R",))]
    assert not X.executable(L, ext, V)
