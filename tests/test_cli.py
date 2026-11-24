"""명령줄 도구 ses (ses_core/cli.py, docs/ses-platform/18_classic_parity.md 6절).

명령마다 예시 문서에서 결과와 종료 코드를 본다. 결과가 라이브러리를 직접 부른 것과 같은지도 본다.
"""

import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from ses_core import cli, direct, load_ses  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core.decisions import load_decisions  # noqa: E402
from ses_core.devs import DevsExecutor, simulate  # noqa: E402

E = os.path.join(ROOT, "docs", "ses-platform", "examples")


def ses(*argv) -> tuple:
    """(종료 코드, 출력)."""
    out = io.StringIO()
    old = os.getcwd()
    os.chdir(ROOT)                                           # 모듈:이름 은 저장소의 뿌리에서 찾는다
    try:
        code = cli.main([str(a) for a in argv], out)
    finally:
        os.chdir(old)
    return code, out.getvalue()


def path(name: str) -> str:
    return os.path.join(E, name)


PROCESSING = path("processing_system.ses.yaml")
WSN = ("--functions", "packs.wsn.model_base:FUNCTIONS")
PACKS = os.path.join(ROOT, "packs")
WSN_DOC = os.path.join(PACKS, "wsn", "wsn.ses.yaml")
WSN_DECISIONS = os.path.join(PACKS, "wsn", "cases", "field_1000.decisions.yaml")
WSN_BINDING = os.path.join(PACKS, "wsn", "binding.yaml")


def test_check_reports_the_family_and_the_limit():
    assert ses("check", PROCESSING) == (0, "변이 15개, 그 가운데 적격 15개\n")
    code, out = ses("check", WSN_DOC, *WSN)
    assert code == 0 and "info LIMIT" in out
    assert "변이 9000개, 그 가운데 핵 적격 9000개 (열거하지 않고 정의 표 위에서 셌다. 확장은 결합의 국소 검사만 했다)" in out


def test_check_fails_on_a_broken_document(tmp_path):
    bad = tmp_path / "bad.ses.yaml"
    bad.write_text('ses: "1.0"\nname: R\nentities:\n  R: {root: true, aspects: {a: {parts: [Nobody]}}}\n',
                   encoding="utf-8")
    code, out = ses("check", bad)
    assert code == 1 and "error" in out and "Nobody" in out


def test_choices_and_variants_follow_the_decisions(tmp_path):
    code, out = ses("choices", PROCESSING, "--decisions", path("processing_system.decisions.yaml"))
    assert code == 0 and out.startswith("남은 변이 1개\n")
    assert "Buffer alternative policySpec: 정해짐. 남은 선택지 ['PriorityBuffer']" in out
    code, out = ses("choices", PROCESSING)
    assert code == 0 and out.startswith("남은 변이 15개\n") and out.count("열림") == 4
    code, out = ses("variants", PROCESSING, "--limit", 3)
    lines = out.splitlines()
    assert code == 0 and lines[0] == "변이 15개. 앞의 3개만 보인다. --limit 로 늘린다" and len(lines) == 4
    for line in lines[1:]:                                   # 줄마다 그 변이를 재현하는 결정 집합이다
        d = dict(json.loads(line), decisions="1.0")
        f = tmp_path / "one.yaml"
        f.write_text(json.dumps(d), encoding="utf-8")
        assert ses("choices", PROCESSING, "--decisions", f)[1].startswith("남은 변이 1개\n")
    f = tmp_path / "none.yaml"
    f.write_text('{"decisions": "1.0", "variables": {"policy": "priority", "num_servers": 1}}', encoding="utf-8")
    assert ses("choices", PROCESSING, "--decisions", f) == (1, "남은 변이가 없다\n어긋난 곳: 제약 priority_needs_pool 을 어긴다\n")
    assert ses("variants", PROCESSING, "--max-variants", 3)[0] == 1


BASE = {"R": {"root": True, "specializations": {"s": {"alternatives": ["D", "E"]}}},
        "D": {"extends": "R"}, "E": {"extends": "R"}}


def written(tmp_path, name: str, content) -> str:
    f = tmp_path / name
    f.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return str(f)


def test_choices_reads_back_what_variants_prints(tmp_path):
    """variants 가 변이마다 내는 결정 집합을 choices 가 받아 정확히 그 변이 하나를 센다.

    분해를 내지 않은 구성원이 있는 변이의 증거에는 "분해를 내지 않는다"(~)는 결정이 든다. 독립된 검토가
    찾았을 때 정의 표 위의 계산은 그것을 거부했고, 도구가 자기가 낸 것을 읽지 못했다.
    """
    tie = written(tmp_path, "tie.ses.yaml", {"ses": "1.0", "name": "R", "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["P"], "priority": 5}},
              "specializations": {"s": {"alternatives": ["D", "E"]}}},
        "D": {"extends": "R"},
        "E": {"extends": "R", "aspects": {"b": {"parts": ["Q"], "priority": 5}, "c": {"parts": ["Q"], "priority": 9}}},
        "P": {}, "Q": {}}})
    code, out = ses("variants", tie)
    lines = out.splitlines()
    assert code == 0 and lines[0] == "변이 3개" and sum("~" in line for line in lines[1:]) == 2
    for i, line in enumerate(lines[1:]):
        f = written(tmp_path, f"w{i}.yaml", dict(json.loads(line), decisions="1.0"))
        assert ses("choices", tie, "--decisions", f)[1].startswith("남은 변이 1개\n")
        assert ses("variants", tie, "--decisions", f)[1].startswith("변이 1개\n")


def test_choices_does_not_walk_variable_values_that_are_decided_or_excluded(tmp_path):
    """변수 값의 조합은 결정과, 변수 하나만 보는 제약으로 줄인 뒤에 돌아본다. 한도도 그 수에 건다."""
    from ses_core import folded as F
    from ses_core.decisions import DecisionSet
    big = {"ses": "1.0", "name": "R", "entities": BASE,
           "variables": {f"v{i}": {"type": "int", "range": [1, 300]} for i in range(3)}}
    doc = written(tmp_path, "big.ses.yaml", big)
    assert ses("choices", doc)[1].startswith("돌아볼 변수 값의 조합이 27000000가지로 한도 200000가지를 넘는다")
    decided = written(tmp_path, "d.yaml", {"decisions": "1.0", "variables": {"v0": 1, "v1": 1, "v2": 1}})
    code, out = ses("choices", doc, "--decisions", decided)
    assert code == 0 and out.startswith("남은 변이 2개\n")
    ds = DecisionSet().assign("v0", 1).assign("v1", 1).assign("v2", 1)
    assert F.Evaluator(load_ses(doc), decisions=ds).assignment_count() == 1
    two = dict(big, variables={"v0": {"type": "int", "range": [1, 1000]}, "v1": {"type": "int", "range": [1, 1000]}},
               constraints=[{"name": "c0", "require": {"var": "v0", "le": 2}},
                            {"name": "c1", "require": {"var": "v1", "le": 2}},
                            {"name": "c2", "forbid": {"all": [{"var": "v0", "eq": 2}, {"var": "v1", "eq": 2}]}}])
    doc2 = written(tmp_path, "two.ses.yaml", two)
    assert F.Evaluator(load_ses(doc2)).assignment_count() == 4       # 변수 둘을 보는 제약은 조합마다 본다
    code, out = ses("choices", doc2)
    assert code == 0 and out.startswith("남은 변이 6개\n")
    small = dict(big, variables={"v0": {"type": "int", "range": [1, 30]}, "v1": {"type": "int", "range": [1, 30]}})
    doc3 = written(tmp_path, "small.ses.yaml", small)
    assert ses("choices", doc3, "--max-assignments", 100)[0] == 1    # 한도는 명령줄에서 정한다
    assert ses("choices", doc3, "--max-assignments", 900)[1].startswith("남은 변이 1800개\n")


def test_a_count_too_large_to_write_is_abbreviated(tmp_path):
    """변이의 수가 수천 자리이면 앞의 몇 자리와 자릿수만 적는다. 전에는 수를 글로 옮기다가 오류로 끝났다."""
    assert cli._count(15) == "15" and cli._count(10 ** 30 - 1) == "9" * 30
    assert cli._count(10 ** 30) == "약 1.00000e+30 (31자리)"
    assert cli._count(123456789 * 10 ** 5000) == "약 1.23456e+5008 (5009자리)"
    ents = {"Leaf": {"specializations": {"k": {"alternatives": ["K0", "K1"]}}},
            "K0": {"extends": "Leaf"}, "K1": {"extends": "Leaf"},
            "P0": {"multi_aspects": {"m": {"part": "Leaf", "cardinality": {"min": 1, "max": 30}}}},
            "P1": {"multi_aspects": {"m": {"part": "P0", "cardinality": {"min": 1, "max": 30}}}},
            "R": {"root": True, "multi_aspects": {"m": {"part": "P1", "cardinality": {"min": 1, "max": 30}}}}}
    deep = written(tmp_path, "deep.ses.yaml", {"ses": "1.0", "name": "R", "entities": ents})
    code, out = ses("choices", deep)
    assert code == 0 and out.startswith("남은 변이 약 5.45605e+8398 (8399자리)개\n")
    code, out = ses("check", deep)
    assert code == 0 and "변이 약 5.45605e+8398 (8399자리)개" in out
    assert ses("variants", deep) == (1, "변이가 약 5.45605e+8398 (8399자리)개로 한도 5000개를 넘어 열거하지 않는다\n")


def test_choices_and_variants_report_bad_input_without_a_traceback(tmp_path):
    """범위 없는 변수, 모양이 틀린 결정 집합, 남길 값이 없는 변수의 결정은 글로 알리고 종료 코드 1 로 끝난다."""
    doc = written(tmp_path, "base.ses.yaml", {"ses": "1.0", "name": "R", "entities": BASE,
                                             "variables": {"x": {"type": "int", "range": [1, 3]}}})
    floating = written(tmp_path, "float.ses.yaml", {"ses": "1.0", "name": "R", "entities": BASE,
                                                   "variables": {"x": {"type": "float", "range": [0.0, 1.0]}}})
    for command in ("choices", "variants"):
        assert ses(command, floating) == (1, "변이 공간을 만들 수 없다. 변수 x 에 유한 범위가 필요하다\n")
        empty = written(tmp_path, "empty.yaml", 'decisions: "1.0"\nvariables:\n  x:\n')
        assert ses(command, doc, "--decisions", empty) == \
            (1, "변이 공간을 만들 수 없다. variable/x: specialization 에는 남길 alternative 가 있어야 한다\n")
        broken = written(tmp_path, "broken.yaml", "decisions: [1, 2\nchoose: }")
        code, out = ses(command, doc, "--decisions", broken)
        assert code == 1 and out.startswith("결정 집합의 모양이 틀렸다. YAML 문법이 틀렸다. 2번째 줄")
        listed = written(tmp_path, "listed.yaml",
                         'decisions: "1.0"\nchoose: [{at: [R], specialization: s, alternative: D}]\n')
        code, out = ses(command, doc, "--decisions", listed)
        assert code == 1 and out.startswith("결정 집합의 모양이 틀렸다")


def test_variants_uses_the_exact_count_for_its_limit():
    """variants 의 한도는 남은 변이의 정확한 수에 건다. 전에는 구조상의 수(256)에 걸려 15개를 내지 못했다."""
    assert ses("variants", PROCESSING, "--max-variants", 14) == (1, "변이가 15개로 한도 14개를 넘어 열거하지 않는다\n")
    code, out = ses("variants", PROCESSING, "--max-variants", 15, "--limit", 1)
    assert code == 0 and out.startswith("변이 15개. 앞의 1개만 보인다. --limit 로 늘린다\n")


def test_build_names_what_is_missing_or_contradictory(tmp_path):
    code, out = ses("build", PROCESSING, "--decisions", path("processing_system.decisions.tuned.yaml"))
    assert code == 0 and "    server_3: Server" in out and "  Buffer: Buffer, PriorityBuffer" in out
    assert out.endswith("구성요소 9개, 노드 17개\n")
    partial = tmp_path / "partial.yaml"
    partial.write_text('decisions: "1.0"\nvariables: {policy: fifo}\n', encoding="utf-8")
    code, out = ses("build", PROCESSING, "--decisions", partial)
    assert code == 3 and "변수 num_servers" in out
    code, out = ses("build", PROCESSING, "--decisions", partial, "--defaults", "--depth", 0)
    assert code == 0 and out.splitlines()[0] == "ProcessingSystem" and "num_servers': 2" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text('decisions: "1.0"\nvariables: {policy: priority, num_servers: 1}\n', encoding="utf-8")
    assert ses("build", PROCESSING, "--decisions", bad) == (1, "만들 수 없다. 제약 priority_needs_pool 을 어긴다\n")
    stale = tmp_path / "stale.yaml"
    stale.write_text('decisions: "1.0"\nvariables: {speed: 1}\n', encoding="utf-8")
    code, out = ses("build", PROCESSING, "--decisions", stale)
    assert code == 1 and "결정이 가리키는 선택 지점이 대상에 없다" in out
    broken = tmp_path / "broken.yaml"
    broken.write_text("[1, 2]\n", encoding="utf-8")
    assert ses("build", PROCESSING, "--decisions", broken)[0] == 1


def test_build_reports_a_removed_root_instead_of_crashing(tmp_path):
    """뿌리가 없음 대안을 고르면 만들 구조가 없다. 예외가 아니라 오류로 알린다."""
    doc = tmp_path / "gone.ses.yaml"
    doc.write_text('ses: "1.0"\nname: R\nentities:\n'
                   '  R: {root: true, specializations: {s: {alternatives: [A, NoR]}}, aspects: {d: {parts: [P]}}}\n'
                   '  A: {extends: R}\n  NoR: {extends: R, stereotype: void}\n  P: {}\n', encoding="utf-8")
    ds = tmp_path / "gone.yaml"
    ds.write_text('decisions: "1.0"\nchoose:\n  - {at: R, specialization: s, alternative: NoR}\n', encoding="utf-8")
    assert ses("build", doc, "--decisions", ds) == (1, "뿌리가 없음 대안을 골랐다. 만들 구조가 없다 (K0)\n")


def test_plan_matches_the_library_and_reports_violations(tmp_path):
    args = ("plan", WSN_DOC, "--decisions", WSN_DECISIONS,
            "--binding", WSN_BINDING, "--library", "packs.wsn.model_base:LIBRARY", *WSN)
    code, out = ses(*args)
    assert code == 0 and out.endswith("원자 구성요소 1003개, 원자 사이의 연결 2001개\n")
    code, out = ses(*args, "--json")
    plan = json.loads(out)
    sys.path.insert(0, ROOT)
    from packs.wsn import model_base as wsn_mb
    b = direct.build(load_ses(WSN_DOC), load_decisions(WSN_DECISIONS),
                     functions=wsn_mb.FUNCTIONS)
    L, ext = X.attach(b.layered, DevsExecutor(), X.load_binding(WSN_BINDING), wsn_mb.LIBRARY)
    assert plan == json.loads(json.dumps(X.plan(L, ext, b.variant), default=str))
    lib = tmp_path / "shortlib.py"                           # 센서 모듈이 빠진 라이브러리
    lib.write_text("from packs.wsn.model_base import LIBRARY as ALL\nLIBRARY = {k: v for k, v in ALL.items() if k != 'Sensor'}\n",
                   encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        code, out = ses(*args[:-4], "--library", "shortlib:LIBRARY", *WSN)
    finally:
        sys.path.remove(str(tmp_path))
    assert code == 1 and "B1 EF_WSN/WSN/SENSORS/sensor_0: 라이브러리에 모듈 Sensor 이 없다" in out
    assert out.rstrip().endswith("위반 1000건")


def test_run_equals_running_the_library_directly():
    code, out = ses("run", PROCESSING, "--decisions", path("processing_system.decisions.tuned.yaml"),
                    "--binding", path("processing_system.binding.devs.yaml"),
                    "--library", "examples.processing_mb:LIBRARY", "--until", 20, "--log", 0)
    sys.path.insert(0, ROOT)
    from examples import processing_mb
    b = direct.build(load_ses(PROCESSING), load_decisions(path("processing_system.decisions.tuned.yaml")))
    L, ext = X.attach(b.layered, DevsExecutor(), X.load_binding(path("processing_system.binding.devs.yaml")),
                      processing_mb.LIBRARY)
    log = simulate(X.realize(L, ext, DevsExecutor(), b.variant), 20.0)
    assert code == 0 and out == f"출력 사건 {len(log)}개, 마지막 시각 {log[-1][0]}\n"
    code, out = ses("run", PROCESSING, "--decisions", path("processing_system.decisions.yaml"),
                    "--binding", path("processing_system.binding.pyevsim.yaml"),
                    "--library", "examples.processing_mb:LIBRARY", "--until", 5)
    assert code == 1 and "run 은 참조 시뮬레이터(devs)만 돌린다" in out


@pytest.mark.parametrize("spec,why", [("nowhere", "'모듈:이름' 꼴"), ("examples.nowhere:LIB", "를 찾을 수 없다"),
                                      ("packs.wsn.model_base:NOTHING", "를 찾을 수 없다")])
def test_bad_module_references_are_reported(spec, why):
    code, out = ses("build", WSN_DOC, "--decisions", WSN_DECISIONS, "--functions", spec)
    assert code == 1 and why in out


def test_usage_errors_exit_with_two():
    with pytest.raises(SystemExit) as e:
        cli.main(["build", PROCESSING])
    assert e.value.code == 2


def test_modules_are_found_in_the_current_directory_like_an_installed_command():
    """설치된 명령 ses 에서는 sys.path 에 지금 디렉터리가 없다. 그래도 모듈:이름 을 지금 디렉터리에서 찾는다."""
    script = ("import os, sys; sys.path.insert(0, os.getcwd()); from ses_core import cli; "
              "here = os.getcwd(); sys.path[:] = [p for p in sys.path if p not in ('', '.', here)]; "
              "raise SystemExit(cli.main(sys.argv[1:]))")
    args = ["plan", WSN_DOC, "--decisions", WSN_DECISIONS, "--binding",
            WSN_BINDING, "--library", "packs.wsn.model_base:LIBRARY", *WSN]
    r = subprocess.run([sys.executable, "-c", script, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.endswith("원자 구성요소 1003개, 원자 사이의 연결 2001개\n"), r.stdout + r.stderr


def test_the_module_can_be_run_as_a_program():
    r = subprocess.run([sys.executable, "-m", "ses_core", "check", PROCESSING], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout == "변이 15개, 그 가운데 적격 15개\n"


def test_a_family_violation_says_in_which_variants_it_happens(tmp_path):
    """족의 위반은 어느 변이에서 나는지를 함께 적는다. 변이가 많을 때 어디를 고칠지 알 수 있어야 한다."""
    doc = tmp_path / "crossing.ses.yaml"
    doc.write_text(
        'ses: "1.0"\nname: Crossing\nport_types:\n  Call: {fields: {lane: int}}\nentities:\n'
        "  Crossing:\n    root: true\n    aspects:\n      main:\n        parts: [Detector, Controller]\n"
        "        couplings:\n          - {from: Detector.call, to: Controller.call}\n"
        "  Controller:\n    specializations:\n      kind:\n        alternatives: [FixedTime, Actuated]\n"
        "  FixedTime:\n    extends: Controller\n"
        "  Actuated:\n    extends: Controller\n    ports:\n      call: {type: Call, direction: in, required: true}\n"
        "  Detector:\n    ports:\n      call: {type: Call, direction: out}\n", encoding="utf-8")
    code, out = ses("check", doc)
    assert code == 1
    assert ("error C1 entities/Crossing: Detector.call 에서 Controller.call: 포트가 없다 "
            "(변이 2개 가운데 1개. Controller/kind=FixedTime 일 때)") in out.splitlines()
    assert out.splitlines()[-1] == "변이 2개, 그 가운데 적격 1개"


def test_choices_say_that_they_do_not_look_at_the_profile(tmp_path):
    """선택지 표는 선택의 핵만 본다. 문서가 프로파일을 가리키면 그 규칙을 보지 않았다고 알린다."""
    with open(PROCESSING, encoding="utf-8") as f:
        text = f.read()
    assert "\nprofile:" not in text
    assert "프로파일" not in ses("choices", PROCESSING)[1]
    doc = tmp_path / "with_profile.ses.yaml"
    doc.write_text(text.replace("\nname:", "\nprofile: some.profile.yaml\nname:", 1), encoding="utf-8")
    code, out = ses("choices", doc)
    assert code == 0 and out.splitlines()[-1] == (
        "문서가 프로파일 some.profile.yaml 을 가리킨다. 이 표는 프로파일의 규칙을 보지 않았다. ses check --profile 로 본다")


def test_a_library_that_is_not_found_says_where_it_looked():
    code, out = ses("choices", PROCESSING, "--functions", "nowhere.at.all:FUNCTIONS")
    assert code == 1 and "모듈은 지금 디렉터리에서 찾는다" in out and "Traceback" not in out
