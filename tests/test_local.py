"""결합의 족 수준 검사를 정의 표 위에서 한다 (ses_core/local.py).

변이를 모두 열거해서 한 검사(diagnose.analyze)와 견준다. 포트의 병합 충돌(M)과 C1에서 C4의 위반이
같은 정의에서 같은 글로 나와야 한다. 복제본이 많을 때는 절단 정리로 개수 3이 그 위를 대표하는지도 본다.
"""

import collections
import os
import random
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import rand_system_document  # noqa: E402
from test_parity import decorated, prioritized  # noqa: E402

from ses_core import edit as E  # noqa: E402
from ses_core import LoadError, load_ses, load_ses_dict, local  # noqa: E402
from ses_core.diagnose import analyze  # noqa: E402

STATS: collections.Counter = collections.Counter()
CODES = ("M", "C1", "C2", "C3", "C4")


def enumerated(d: dict, functions=None) -> set:
    """변이를 열거한 분석이 낸 결합의 위반: (부호, 정의, 글)."""
    m = E.from_dict(d)
    a = analyze(m, functions=functions)
    assert a.variants is not None
    return {(x.code, m.get(x.element).props.get("name"), x.message) for x in a.diagnostics
            if x.scope == "family" and x.layer == "devs" and x.code in CODES}


@pytest.mark.parametrize("seed", range(300))
def test_local_check_finds_exactly_the_violations_of_enumeration(seed):
    """선택 제약이 없는 문서에서 위반의 집합이 열거한 것과 같다. 우선순위와 분해의 규칙이 있는 문서도 본다."""
    kind = seed % 3
    if kind == 0:
        d, functions = rand_system_document(random.Random(seed)), None
    else:
        d, _, functions = prioritized(seed) if kind == 1 else decorated(seed)
        d = {k: v for k, v in d.items() if k != "constraints"}
    found, possible = local.check(load_ses_dict(d), functions)
    assert not possible
    mine = {(f.code, f.definition, f.message) for f in found}
    assert mine == enumerated(d, functions)
    STATS["docs"] += 1
    STATS["violations"] += len(mine)
    STATS["docs_with_violations"] += bool(mine)


def ports_to_alternatives(d: dict, rng: random.Random) -> int:
    """정의가 적은 포트를 그 정의의 대안들 가운데 몇에게로 옮긴다. 옮긴 포트의 수를 돌려준다.

    그러면 그 포트는 어떤 대안이 골라진 변이에만 있다. 인터페이스가 구성원들의 선언을 합친 것(theory.md 정의 12)이라는
    것을 변이마다 다른 인터페이스로 시험한다."""
    moved = 0
    ents = d["entities"]
    for name in sorted(ents):
        e = ents[name]
        alts = sorted(a for sp in (e.get("specializations") or {}).values() for a in sp["alternatives"]
                      if ents[a].get("stereotype") != "void")
        if not alts or not e.get("ports"):
            continue
        for port in sorted(e["ports"]):
            if rng.random() < 0.5:
                decl = e["ports"].pop(port)
                for a in rng.sample(alts, rng.randint(1, len(alts))):
                    ents[a].setdefault("ports", {})[port] = dict(decl)
                moved += 1
    return moved


@pytest.mark.parametrize("seed", range(300))
def test_local_check_agrees_when_only_some_alternatives_have_a_port(seed):
    """대안만 가진 포트로 결합이 갈 때도 국소 검사와 열거가 같은 위반을 낸다."""
    rng = random.Random(seed)
    d = rand_system_document(rng)
    moved = ports_to_alternatives(d, rng)
    try:
        doc = load_ses_dict(d)
    except LoadError:
        STATS["moved_refused"] += 1                          # 어느 대안에도 남지 않은 포트로 가는 결합 등
        return
    found, possible = local.check(doc, None)
    assert not possible
    mine = {(f.code, f.definition, f.message) for f in found}
    assert mine == enumerated(d, None)
    STATS["moved_docs"] += bool(moved)
    STATS["moved_violations"] += bool(moved) and bool(mine)
    STATS["moved_clean"] += bool(moved) and not mine


@pytest.mark.parametrize("seed", range(120))
def test_diagnostics_beyond_the_limit_report_the_same_coupling_violations(seed):
    """한도를 넘어 변이를 열거하지 않을 때에도 진단이 결합의 위반을 같은 요소에 같은 글로 알린다."""
    d = rand_system_document(random.Random(1000 + seed))
    m = E.from_dict(d)
    limited = analyze(m, max_variants=0)
    assert limited.variants is None and limited.core is not None
    got = {(x.code, m.get(x.element).props.get("name"), x.message) for x in limited.diagnostics
           if x.scope == "family" and x.layer == "devs"}
    assert got == enumerated(d)
    for x in limited.diagnostics:
        if x.layer == "devs":
            assert x.severity == "error" and x.data["members"] and not x.data["possible"]
    STATS["limited_docs"] += 1
    STATS["limited_violations"] += len(got)


def pool(rng: random.Random) -> dict:
    """복제본의 풀. 결합 틀, 필수 포트, 없음 대안, 포트를 더하는 대안이 무작위다. 개수는 5까지다."""
    kind = rng.choice(["fan", "chain", "ring", "broadcast"])
    need = lambda: rng.random() < 0.5                         # noqa: E731
    part = {"ports": {"i": {"type": "T", "direction": "in", "required": need()},
                      "o": {"type": "T", "direction": "out"}},
            "specializations": {"k": {"alternatives": ["P0"]}}}
    ents = {"P": part, "P0": {"extends": "P"}}
    if rng.random() < 0.6:
        part["specializations"]["k"]["alternatives"].append("PV")
        ents["PV"] = {"extends": "P", "stereotype": "void"}
    if rng.random() < 0.5:                                    # 대안이 필수 입력을 더한다. 틀이 그것을 잇지 않으면 C4 다
        part["specializations"]["k"]["alternatives"].append("PZ")
        ents["PZ"] = {"extends": "P", "ports": {"z": {"type": "T", "direction": "in", "required": True}}}
    keep = lambda rules: [r for r in rules if rng.random() < 0.8]   # noqa: E731
    if kind == "fan":
        cp = {"pattern": "fan_out_fan_in", "fan_out": keep([{"from": "i", "to": "{part}.i"}]),
              "fan_in": keep([{"from": "{part}.o", "to": "o"}])}
    elif kind == "chain":
        cp = {"pattern": "chain", "first": keep([{"from": "i", "to": "{part}.i"}]),
              "between": keep([{"from": "{i}.o", "to": "{next}.i"}]), "last": keep([{"from": "{part}.o", "to": "o"}])}
    elif kind == "ring":
        cp = {"pattern": "ring", "between": [{"from": "{i}.o", "to": "{next}.i"}],
              "last": keep([{"from": "{part}.o", "to": "o"}])}
    else:
        cp = {"pattern": "broadcast", "between": [{"from": "{i}.o", "to": "{j}.i"}],
              "fan_in": keep([{"from": "{part}.o", "to": "o"}])}
    lo, hi = rng.randint(0, 2), rng.randint(3, 5)
    ents["R"] = {"root": True,
                 "ports": {"i": {"type": "T", "direction": "in"}, "o": {"type": "T", "direction": "out", "required": need()}},
                 "multi_aspects": {"m": {"part": "P", "cardinality": {"min": lo, "max": hi}, "couplings": cp}}}
    return {"ses": "1.0", "name": "R", "port_types": {"T": {}}, "entities": ents}


@pytest.mark.parametrize("seed", range(200))
def test_three_replicas_stand_for_more(seed):
    """절단 정리. 복제본이 3개 이상인 경우를 3개로 대표해도, 어떤 부호의 위반이 어느 정의에서 생기는지가 같다.
    열거는 개수 5까지를 모두 본다. 복제본의 이름이 달라 글은 견주지 않는다."""
    d = pool(random.Random(seed))
    found, _ = local.check(load_ses_dict(d))
    assert all(f.count is None or f.count <= local.CUT for f in found)
    assert {(f.code, f.definition) for f in found} == {(code, name) for code, name, _ in enumerated(d)}
    STATS["pools"] += 1
    STATS["pools_with_violations"] += bool(found)


def test_the_middle_replica_needs_three():
    """절단 값 3은 줄일 수 없다. 첫째와 마지막 복제본만 입력을 받는 틀에서는 가운데 복제본이 있어야 위반이 드러난다."""
    d = {"ses": "1.0", "name": "R", "port_types": {"T": {}},
         "entities": {"R": {"root": True, "ports": {"i": {"type": "T", "direction": "in"}},
                            "multi_aspects": {"m": {"part": "P", "cardinality": {"min": 1, "max": 40}, "couplings": {
                                "pattern": "custom", "first": [{"from": "i", "to": "{part}.i"}],
                                "last": [{"from": "i", "to": "{part}.i"}]}}}},
                      "P": {"ports": {"i": {"type": "T", "direction": "in", "required": True}}}}}
    found, _ = local.check(load_ses_dict(d))
    assert [(f.code, f.definition, f.count) for f in found] == [("C4", "R", 3)]
    small = dict(d, entities=dict(d["entities"], R=dict(d["entities"]["R"], multi_aspects={
        "m": dict(d["entities"]["R"]["multi_aspects"]["m"], cardinality={"min": 1, "max": 2})})))
    assert local.check(load_ses_dict(small))[0] == [] and enumerated(small) == set()


def test_ports_declared_differently_by_two_alternatives_clash():
    """한 엔티티의 두 specialization 에서 고른 대안이 같은 이름의 포트를 다르게 선언하면 합칠 수 없다 (M)."""
    d = {"ses": "1.0", "name": "R", "port_types": {"T": {}, "U": {}},
         "entities": {"R": {"root": True, "aspects": {"a": {"parts": ["X"]}}},
                      "X": {"specializations": {"s": {"alternatives": ["A", "A0"]}, "t": {"alternatives": ["C", "C0"]}}},
                      "A": {"extends": "X", "ports": {"z": {"type": "T", "direction": "in"}}},
                      "C": {"extends": "X", "ports": {"z": {"type": "U", "direction": "in"}}},
                      "A0": {"extends": "X"}, "C0": {"extends": "X"}}}
    found, _ = local.check(load_ses_dict(d))
    assert [(f.code, f.definition, f.members) for f in found] == [("M", "X", ("X", "A", "C"))]
    assert {(f.code, f.definition, f.message) for f in found} == enumerated(d)


def test_constraints_on_selections_make_the_result_an_upper_bound():
    """선택 제약이 있으면 본 조합 가운데 제약이 막는 것이 있을 수 있다. 그 사실을 함께 돌려준다."""
    d = pool(random.Random(3))
    d["constraints"] = [{"name": "c", "forbid": {"selected": "P/k=P0"}}]
    found, possible = local.check(load_ses_dict(d))
    assert possible
    assert {(f.code, f.definition) for f in found} >= {(code, name) for code, name, _ in enumerated(d)}


def test_the_sensor_network_is_checked_without_enumeration():
    """문헌 사례. 센서가 1,000개까지인 족의 결합을 몇 초 안에 본다."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from packs.wsn import model_base as wsn_mb
    doc = load_ses(os.path.join(os.path.dirname(__file__), "..", "packs", "wsn", "wsn.ses.yaml"))
    started = time.time()
    assert local.check(doc, wsn_mb.FUNCTIONS) == ([], False)
    assert time.time() - started < 30


def test_local_samples_are_not_vacuous():
    if not STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["docs"] == 300 and STATS["docs_with_violations"] >= 60 and STATS["violations"] >= 100, STATS
    assert STATS["pools"] == 200 and STATS["pools_with_violations"] >= 60, STATS
    assert STATS["limited_docs"] == 120 and STATS["limited_violations"] >= 20, STATS
    assert STATS["moved_docs"] >= 120 and STATS["moved_violations"] >= 50 and STATS["moved_clean"] >= 50, STATS
