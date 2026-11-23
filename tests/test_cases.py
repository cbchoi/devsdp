"""문헌 사례의 재현 (docs/ses-platform/18_classic_parity.md 6절).

1. 큰 무선 센서 네트워크. Nam, Kim (2021)의 WSN-SES/MB 구조를 따른다. 센서 1,000개짜리 모델을
   결정 파일 하나로 만들고 돌린다. 족 전체를 펼치는 길로는 만들 수 없는 크기다.
2. 피드포워드 제어를 켜고 끌 수 있는 피드백 제어. Folkerts et al. (2019)의 그림 3에서 7을 따른다.
   문헌의 실험 과정(구조 둘, PID 설정 넷)을 그대로 돌려 같은 결론에 닿는지 본다.

사례의 원자 모델은 문헌의 것을 옮긴 것이 아니다. 그래서 수치는 문헌과 견주지 않고, 따로 계산한
값(센서의 감지 범위, 차분식)과 견준다. 문헌과 견주는 것은 구조와 결론이다.
"""

import copy
import math
import os
import sys
import time

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_direct import facts  # noqa: E402

from packs.feedback_control import experiment  # noqa: E402
from packs.wsn import model_base as wsn_mb  # noqa: E402
from ses_core import direct, load_ses, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.decisions import DecisionSet, decide, load_decisions  # noqa: E402
from ses_core.devs import DevsExecutor, _leaves, simulate  # noqa: E402
from ses_core.diagnose import analyze, unfolded_size  # noqa: E402
from ses_core.extension import Layered  # noqa: E402
from ses_core.skeleton import assignment, skeleton  # noqa: E402
from ses_core.unfold import unfold_layered, variable_domains  # noqa: E402

PACKS = os.path.join(os.path.dirname(__file__), "..", "packs")
WSN = os.path.join(PACKS, "wsn")
FEEDBACK = os.path.join(PACKS, "feedback_control")
fb = experiment.mb                           # 실험 제어가 실은, 그 묶음의 모델 베이스


def raw(name: str) -> dict:
    with open(os.path.join(WSN if name.startswith("wsn") else FEEDBACK, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 1. 무선 센서 네트워크
# ---------------------------------------------------------------------------

def wsn(limit: int = None) -> dict:
    d = raw("wsn.ses.yaml")
    if limit is not None:
        d["variables"]["sensors"]["range"] = [1, limit]
    return d


def test_wsn_family_and_direct_build_agree_on_small_fields():
    """센서가 넷까지이면 족 전체를 펼칠 수 있다. 변이마다, 변수 값만 적은 결정으로 직접 만든 것이 같다."""
    doc = load_ses_dict(wsn(4))
    L = unfold_layered(doc, functions=wsn_mb.FUNCTIONS)
    typed = {n: {str(v): v for v in vs} for n, vs in variable_domains(doc).items()}
    variants = sem(L.ses)
    assert len(variants) == 4 * 3 * 3
    for V in variants:
        sigma = {n: typed[n][s] for n, s in assignment(L.ses.tree, V).items()}
        b = direct.build(doc, DecisionSet(variables={n: (v,) for n, v in sigma.items()}), functions=wsn_mb.FUNCTIONS)
        assert facts(b.layered, b.variant) == facts(L, V) and b.unused == ()


def test_the_editor_handles_the_wsn_case_with_its_functions():
    """편집기의 범용 시험은 함수를 모르므로 이 문서를 펼치지 않는다(tests/test_edit.py 의 PLAIN).
    같은 성질을 함수와 함께 여기서 본다. 노드 수를 펼치지 않고 세는 것, 이름을 모두 바꿔도 분석이 같은 것."""
    d = wsn(3)
    L = unfold_layered(load_ses_dict(d), functions=wsn_mb.FUNCTIONS)
    assert unfolded_size(E.from_dict(d)) == len(L.ses.tree.nodes)
    m = E.from_dict(d)
    before = analyze(m, functions=wsn_mb.FUNCTIONS)
    assert (before.variants, before.wellformed, before.errors) == (27, 27, [])
    ed = E.Editor(m)
    targets = [el.id for el in m.all() if el.type in ("entity", "variable", "aspect", "multi_aspect", "specialization")]
    for i, id in enumerate(targets):
        ed.rename(id, f"이름_{i}")
    after = analyze(m, functions=wsn_mb.FUNCTIONS)
    assert (after.variants, after.wellformed, after.errors) == (27, 27, [])
    renamed = E.to_dict(m)                                   # 속성의 식이 부르는 변수의 이름도 따라 바뀌었다
    assert "field" not in renamed["variables"] and "sensing" not in str(renamed["entities"])
    for _ in targets:
        ed.undo()
    assert E.to_dict(m) == d


def test_the_family_analysis_of_a_thousand_sensors_stops_at_its_limit():
    """족 수준의 분석은 개수 1부터 1,000까지를 모두 펼쳐야 한다. 한도에서 멈추고 그렇다고 알린다."""
    m = E.load(os.path.join(WSN, "wsn.ses.yaml"))
    assert unfolded_size(m) > 500000                         # 복제본만 500,500개다
    a = analyze(m, functions=wsn_mb.FUNCTIONS)
    assert [d.code for d in a.diagnostics if d.scope == "document" and d.severity != "info"] == []
    (limit,) = a.of("LIMIT")
    assert "펼친 나무의 노드가 한도" in limit.message and a.variants is None


def test_a_thousand_sensors_are_built_run_and_detect_what_they_can_reach():
    doc = load_ses(os.path.join(WSN, "wsn.ses.yaml"))
    ds = load_decisions(os.path.join(WSN, "cases", "field_1000.decisions.yaml"))
    started = time.perf_counter()
    b = direct.build(doc, ds, functions=wsn_mb.FUNCTIONS)
    L, ext = X.attach(b.layered, DevsExecutor(), X.load_binding(os.path.join(WSN, "binding.yaml")),
                      wsn_mb.LIBRARY)
    assert X.executable(L, ext, b.variant) and b.unused == ()
    plan = X.plan(L, ext, b.variant)
    sensors = plan["children"]["WSN"]["children"]["SENSORS"]
    assert len(sensors["children"]) == 1000
    assert len(sensors["eic"]) == len(sensors["eoc"]) == 1000           # 결합 틀이 낸 연결
    k, cell = 32, 1000 / 32                                              # 센서 1,000개는 32 x 32 격자에 놓인다
    for i in (0, 1, 31, 32, 500, 999):
        params = sensors["children"][f"sensor_{i}"]["params"]
        assert params["id"] == i and params["reach"] == 40
        assert (params["x"], params["y"]) == (math.floor(i % k * cell) + 15, math.floor(i // k * cell) + 15)
    assert plan["children"]["EF"]["children"]["GENR"]["params"]["events"] == 40      # 결정 파일의 재정의

    model = X.realize(L, ext, DevsExecutor(), b.variant)
    log = simulate(model, 200.0)
    elapsed = time.perf_counter() - started
    leaves = _leaves(model)
    spots = [(math.floor(i % k * cell) + 15, math.floor(i // k * cell) + 15) for i in range(1000)]
    expected = {}
    for e, (ex, ey) in enumerate(wsn_mb.events_of(7, 1000, 40)):        # 감지 범위를 따로 계산한다
        near = [i for i, (x, y) in enumerate(spots) if (ex - x) ** 2 + (ey - y) ** 2 <= 40 ** 2]
        if near:
            expected[e] = near
    transd = leaves[("EF", "TRANSD")]
    assert {e: sorted(s) for e, s in transd.by_event.items()} == expected
    reports = [(t, v) for t, p, port, v in log if p == ("WSN", "BS") and port == "report"]
    assert all(t == 2.0 * (v["event"] + 1) + 1.0 for t, v in reports)   # 사건 다음 눈금에 보고된다
    assert len(reports) == sum(map(len, expected.values())) > 100 and len(expected) >= 30
    assert elapsed < 30, elapsed


# ---------------------------------------------------------------------------
# 2. 피드백 제어
# ---------------------------------------------------------------------------

def feedback() -> tuple:
    doc = load_ses(os.path.join(FEEDBACK, "feedback_control.ses.yaml"))
    binding = X.load_binding(os.path.join(FEEDBACK, "binding.yaml"))
    return doc, binding


def test_feedback_control_has_the_two_structures_of_the_paper():
    doc, binding = feedback()
    L0 = unfold_layered(doc)
    L, ext = X.attach(L0, DevsExecutor(), binding, fb.LIBRARY)
    variants = sem(L.ses)
    assert len(variants) == 2
    by = {assignment(L.ses.tree, V)["feedforward"]: V for V in variants}
    plain = skeleton(L.ses.tree, L.void, by["0"])
    full = skeleton(L.ses.tree, L.void, by["1"])
    common = {"sourceSys", "feedbackSys", "ctrlPIDSys", "procUnitSys", "sourceDist", "tfDist", "addDist"}
    assert set(plain.parts) == common and plain.absent == ("feedforwardCtrl",)
    assert set(full.parts) == common | {"feedforwardCtrl"}
    ff = full.parts["feedforwardCtrl"]
    assert ff.labels == ("feedforwardCtrl", "fc") and set(ff.parts) == {"addFeedforward", "tfFeedforward"}
    assert all(X.executable(L, ext, V) for V in variants)
    for V in variants:                                       # 두 길이 같은 구조를 낸다
        b = direct.build(doc, DecisionSet(variables={"feedforward": (int(assignment(L.ses.tree, V)["feedforward"]),)}))
        assert facts(b.layered, b.variant) == facts(L0, V)


def difference_equations(feedforward: bool, k: float, ti: float, until: float, h: float, start: float = 0.5) -> list:
    """같은 시스템을 차분식으로 직접 계산한다(전진 오일러). 모델베이스와 실행기를 쓰지 않는다.

    공정 1/(20s+1), 외란의 길 1/(10s+1), 피드포워드 (20s+1)/(10s+1), PID k(e + 적분(e)/Ti), 목표값 0.
    """
    xp = xd = xf = integral = 0.0
    d_before = u_before = e_before = 0.0
    out, n = [], 0
    while n * h <= until + 1e-12:
        t = n * h
        if n > 0:
            xd += h * (d_before - xd) / 10
            xp += h * (u_before - xp) / 20
            xf += h * (d_before - xf) / 10
            integral += h * e_before
        d = 1.0 if t >= start - 1e-12 else 0.0
        y = xp + xd
        e = 0.0 - y
        u = k * (e + integral / ti)
        if feedforward:
            u -= 2 * d - xf                                  # 피드포워드 출력 (20s+1)/(10s+1) d = 2d - xf
        out.append((t, y))
        d_before, u_before, e_before = d, u, e
        n += 1
    return out


def test_the_study_of_the_paper_reaches_the_same_conclusion():
    """문헌의 결론: 피드포워드 없이는 살핀 PID 설정 어느 것도 목표(정착 15초 미만, 벗어남 5% 미만)에 닿지
    못했고, 피드포워드를 넣자 닿았다(그림 7)."""
    tried, good = experiment.study()
    assert [(r["feedforward"], r["k"], r["Ti"]) for r in tried] == \
        [(f, k, ti) for f in (0, 1) for k in (1.0, 5.0) for ti in (1.0, 0.5)]
    assert not any(r["met"] for r in tried if r["feedforward"] == 0)
    assert all(r["met"] for r in tried if r["feedforward"] == 1) and good == tried[4:]
    by = {(r["feedforward"], r["k"], r["Ti"]): r for r in tried}
    # 그림 7의 (a)와 (b)에서 눈으로 읽은 가장 큰 벗어남은 약 0.28과 약 0.1이다. 넉넉하게 견준다
    assert 0.25 < by[(0, 1.0, 1.0)]["peak"] < 0.31 and 0.08 < by[(0, 5.0, 0.5)]["peak"] < 0.13
    assert by[(0, 5.0, 0.5)]["settle"] < 15 < by[(0, 1.0, 1.0)]["settle"]   # (b)는 정착하지만 벗어남이 크다
    assert max(r["peak"] for r in tried if r["feedforward"] == 1) < 1e-12     # (c): 외란이 완전히 상쇄된다


@pytest.mark.parametrize("feedforward", [0, 1])
@pytest.mark.parametrize("k,ti", [(1.0, 1.0), (1.0, 0.5), (5.0, 1.0), (5.0, 0.5)])
def test_the_runs_equal_the_difference_equations(feedforward, k, ti):
    """사건으로 옮긴 모델의 응답이 같은 이산 시스템을 차분식으로 계산한 값과 같다."""
    r = experiment.run(feedforward, k, ti)
    ref = difference_equations(bool(feedforward), k, ti, experiment.UNTIL, fb.H)
    assert [t for t, _ in r["response"]] == [t for t, _ in ref]
    assert max(abs(a - b) for (_, a), (_, b) in zip(r["response"], ref)) <= 1e-12


def test_the_step_size_does_not_change_the_verdict():
    """간격 0.125초의 이산화 오차. 간격을 0.001초로 줄이면 벗어남은 0.01 안에서, 정착 시간은 1초 안에서
    달라지고, 판정(목표에 못 닿음)은 같다."""
    for k, ti in [(1.0, 1.0), (1.0, 0.5), (5.0, 1.0), (5.0, 0.5)]:
        coarse = fb.quality(difference_equations(False, k, ti, 60.0, fb.H), 0.5)
        fine = fb.quality(difference_equations(False, k, ti, 60.0, 0.001), 0.5)
        assert abs(coarse[0] - fine[0]) < 0.01 and abs(coarse[1] - fine[1]) < 1.0
        assert coarse[0] > 0.05 and fine[0] > 0.05                  # 어느 간격에서도 벗어남이 5%를 넘는다


def test_the_gains_are_overrides_not_structure():
    """k 와 Ti 는 구조가 아니다. 재정의는 변이를 늘리거나 줄이지 않고 계획의 매개변수만 바꾼다."""
    doc, binding = feedback()
    L0 = unfold_layered(doc)
    ds = experiment.configuration(0, 5.0, 0.5)
    L1 = decide(L0, ds)
    assert len(sem(L0.ses)) == 2 and len(sem(L1.ses)) == 1
    L, ext = X.attach(L1, DevsExecutor(), binding, fb.LIBRARY)
    (V,) = sem(L.ses)
    pid = X.plan(L, ext, V)["children"]["ctrlPIDSys"]["params"]
    assert pid == {"k": 5.0, "Ti": 0.5, "Td": 0.0}
    b = direct.build(doc, ds)
    assert facts(b.layered, b.variant) == facts(Layered(L1.ses, L1.void, L1.extensions), V)
    plain = copy.deepcopy(raw("feedback_control.ses.yaml"))
    assert "k" not in plain["variables"] and "Ti" not in plain["variables"]
