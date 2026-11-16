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
WSN = ("--functions", "examples.wsn_mb:FUNCTIONS")


def test_check_reports_the_family_and_the_limit():
    assert ses("check", PROCESSING) == (0, "변이 15개, 그 가운데 적격 15개\n")
    code, out = ses("check", path("wsn.ses.yaml"), *WSN)
    assert code == 0 and "info LIMIT" in out and "변이 분석을 하지 않았다" in out


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
    assert code == 0 and lines[0] == "변이 15개" and len(lines) == 4
    for line in lines[1:]:                                   # 줄마다 그 변이를 재현하는 결정 집합이다
        d = dict(json.loads(line), decisions="1.0")
        f = tmp_path / "one.yaml"
        f.write_text(json.dumps(d), encoding="utf-8")
        assert ses("choices", PROCESSING, "--decisions", f)[1].startswith("남은 변이 1개\n")
    f = tmp_path / "none.yaml"
    f.write_text('{"decisions": "1.0", "variables": {"policy": "priority", "num_servers": 1}}', encoding="utf-8")
    assert ses("choices", PROCESSING, "--decisions", f) == (1, "남은 변이가 없다\n")
    assert ses("variants", PROCESSING, "--max-variants", 3)[0] == 1


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
    args = ("plan", path("wsn.ses.yaml"), "--decisions", path("wsn.decisions.yaml"),
            "--binding", path("wsn.binding.devs.yaml"), "--library", "examples.wsn_mb:LIBRARY", *WSN)
    code, out = ses(*args)
    assert code == 0 and out.endswith("원자 구성요소 1003개, 원자 사이의 연결 2001개\n")
    code, out = ses(*args, "--json")
    plan = json.loads(out)
    sys.path.insert(0, ROOT)
    from examples import wsn_mb
    b = direct.build(load_ses(path("wsn.ses.yaml")), load_decisions(path("wsn.decisions.yaml")),
                     functions=wsn_mb.FUNCTIONS)
    L, ext = X.attach(b.layered, DevsExecutor(), X.load_binding(path("wsn.binding.devs.yaml")), wsn_mb.LIBRARY)
    assert plan == json.loads(json.dumps(X.plan(L, ext, b.variant), default=str))
    lib = tmp_path / "shortlib.py"                           # 센서 모듈이 빠진 라이브러리
    lib.write_text("from examples.wsn_mb import LIBRARY as ALL\nLIBRARY = {k: v for k, v in ALL.items() if k != 'Sensor'}\n",
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
                                      ("examples.wsn_mb:NOTHING", "를 찾을 수 없다")])
def test_bad_module_references_are_reported(spec, why):
    code, out = ses("build", path("wsn.ses.yaml"), "--decisions", path("wsn.decisions.yaml"), "--functions", spec)
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
    args = ["plan", path("wsn.ses.yaml"), "--decisions", path("wsn.decisions.yaml"), "--binding",
            path("wsn.binding.devs.yaml"), "--library", "examples.wsn_mb:LIBRARY", *WSN]
    r = subprocess.run([sys.executable, "-c", script, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.endswith("원자 구성요소 1003개, 원자 사이의 연결 2001개\n"), r.stdout + r.stderr


def test_the_module_can_be_run_as_a_program():
    r = subprocess.run([sys.executable, "-m", "ses_core", "check", PROCESSING], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout == "변이 15개, 그 가운데 적격 15개\n"
