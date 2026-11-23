"""분야 묶음 (ses_core/pack.py, docs/ses-platform/20_packs.md).

묶음은 연구자가 자기 분야를 올리는 단위다. 여기서 보는 것은 셋이다.
1. 뼈대(ses pack new)가 그대로 검사를 통과한다. 처음 오는 사람이 받는 것이 돌아가는 것이어야 한다.
2. 저장소의 묶음들이 검사를 통과하고, 적어 둔 기록과 같은 기록을 낸다.
3. 계약을 어긴 묶음을 검사가 잡고, 어디가 틀렸는지를 부호로 알린다. 뼈대를 한 군데씩 틀리게 고쳐 본다.
"""

import io
import os
import shutil
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from ses_core import cli  # noqa: E402
from ses_core import pack as P  # noqa: E402

PACKS = os.path.join(ROOT, "packs")
try:
    import pyevsim  # noqa: F401
    PYEVSIM = True
except ImportError:
    PYEVSIM = False


def ses(*argv) -> tuple:
    out = io.StringIO()
    return cli.main([str(a) for a in argv], out), out.getvalue()


@pytest.fixture
def line(tmp_path) -> str:
    """뼈대로 만든 묶음. 기록까지 적어 둔다."""
    root = str(tmp_path / "line")
    P.scaffold(root)
    assert P.check(root, record=True).ok
    return root


def edit(root: str, name: str, old: str, new: str) -> None:
    path = os.path.join(root, name)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1, (name, old)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def codes(report) -> set:
    return {f.code for f in report.errors}


def said(report, code: str) -> str:
    return " | ".join(f.message for f in report.of(code))


# ---------------------------------------------------------------------------
# 1. 뼈대
# ---------------------------------------------------------------------------

def test_a_new_pack_passes_as_it_is(line):
    report = P.check(line)
    assert report.ok and report.family == (2, 2)
    fast, slow = report.cases["fast"], report.cases["slow"]
    assert (fast["atoms"], fast["links"]) == (3, 2)
    assert fast["events"] == 19 and slow["events"] == 16 and fast["digest"] != slow["digest"]
    assert not [f for f in report.findings if f.severity == "warning"]
    if PYEVSIM:                                              # 같은 모델 베이스가 다른 엔진에서 같은 기록을 낸다
        assert fast["executors"]["pyevsim"] == slow["executors"]["pyevsim"] == "같다"
    assert sorted(P.read_records(P.load(line))) == ["fast", "slow"]


def test_the_commands_make_check_show_and_run_a_pack(tmp_path):
    root = str(tmp_path / "queue")
    code, out = ses("pack", "new", root)
    assert code == 0 and "사례 fast" in out and out.count("만들었다") == 6
    assert ses("pack", "new", root)[0] == 1                  # 비어 있지 않은 곳에는 만들지 않는다
    code, out = ses("pack", "check", root)
    assert code == 0 and out.strip().endswith("묶음 queue: 통과")
    code, out = ses("pack", "show", root)
    assert code == 0 and "ses check queue.ses.yaml" in out and "--library model_base:LIBRARY" in out
    code, out = ses("pack", "run", root, "slow", "--log", "2")
    assert code == 0 and out.splitlines()[0].startswith("2.0 Source.out") and "출력 사건 16개" in out
    assert ses("pack", "run", root, "slow", "--until", "5")[1].strip().endswith("출력 사건 3개, 마지막 시각 5.0")
    assert ses("pack", "run", root, "nope") == (1, "사례 nope 가 없다. 있는 사례는 ['fast', 'slow'] 다\n")
    assert ses("pack", "check", str(tmp_path / "nothing"))[0] == 1
    assert ses("pack", "new", str(tmp_path / "my-pack"))[0] == 1          # 이름은 식별자여야 한다
    assert ses("pack", "new", str(tmp_path / "my-pack"), "--name", "mine")[0] == 0


# ---------------------------------------------------------------------------
# 2. 저장소의 묶음들
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(os.listdir(PACKS)))
def test_the_packs_of_the_repository_pass_and_reproduce_their_records(name):
    """적어 둔 기록(records.yaml)과 지금 돌린 기록이 같다. 다른 컴퓨터와 다른 파이썬에서도 같아야 한다."""
    report = P.check(os.path.join(PACKS, name), executors=("pyevsim",))
    assert report.ok, [(f.code, f.where, f.message) for f in report.errors]
    assert not [f for f in report.findings if f.code == "P6"], report.of("P6")     # 기록이 없다는 알림도 없어야 한다
    ran = [c for c in report.cases.values() if "digest" in c]
    assert ran
    if PYEVSIM:
        assert all(c["executors"]["pyevsim"] == "같다" for c in ran)


def test_the_wsn_pack_is_the_large_case():
    report = P.check(os.path.join(PACKS, "wsn"), executors=())
    assert report.family == (9000, 9000)
    assert report.cases["field_1000"]["atoms"] == 1003 and "digest" not in report.cases["field_1000"]


def test_a_pack_does_not_depend_on_where_it_is(tmp_path):
    """묶음은 디렉터리째 옮겨도 같은 기록을 낸다."""
    moved = str(tmp_path / "elsewhere")
    shutil.copytree(os.path.join(PACKS, "feedback_control"), moved)
    report = P.check(moved, executors=())
    assert report.ok and not report.of("P6")


# ---------------------------------------------------------------------------
# 3. 계약을 어긴 묶음
# ---------------------------------------------------------------------------

def test_the_declaration_is_checked(line, tmp_path):
    assert codes(P.check(str(tmp_path))) == {"P0"}           # pack.yaml 이 없다
    edit(line, "pack.yaml", "title:", "titel:")
    assert "모르는 항목" in said(P.check(line), "P0")
    edit(line, "pack.yaml", "titel:", "title:")
    edit(line, "pack.yaml", "document: line.ses.yaml", "document: ../line.ses.yaml")
    assert "묶음 밖을 가리킨다" in said(P.check(line), "P0")
    edit(line, "pack.yaml", "document: ../line.ses.yaml", "document: missing.ses.yaml")
    assert "파일 missing.ses.yaml 가 없다" in said(P.check(line), "P0")
    edit(line, "pack.yaml", "document: missing.ses.yaml", "document: line.ses.yaml")
    edit(line, "pack.yaml", "name: slow,", "name: fast,")
    assert "사례의 이름은 서로 달라야 한다" in said(P.check(line), "P0")


def test_a_misspelt_key_in_the_document_is_reported(line):
    """속성의 값을 default 가 아니라 value 로 적으면 값이 없는 속성이 된다. 조용히 넘기지 않는다."""
    edit(line, "line.ses.yaml", "service: {type: float, default: 3.0}", "service: {type: float, value: 3.0}")
    report = P.check(line)
    assert codes(report) == {"P1"}
    assert "Slow: 속성 service: 모르는 항목 value 가 있다. default 를 뜻했는가" in said(report, "P1")


def test_the_model_base_is_checked(line):
    edit(line, "model_base.py", "class Sink(Atomic):", "class Sink:")
    report = P.check(line)
    assert codes(report) == {"P2"} and "Sink 는 공통 모델 기반" in said(report, "P2")
    edit(line, "model_base.py", "class Sink:", "class Sink(Atomic):")
    edit(line, "model_base.py", '        return {"out": [{"id": self.count}]}', '        return {"oops": [{"id": self.count}]}')
    assert "선언하지 않은 출력 포트 oops" in said(P.check(line), "P2")
    edit(line, "model_base.py", '        return {"oops": [{"id": self.count}]}', '        return {"out": [{"id": self.count}]}')
    edit(line, "model_base.py", '    PARAMS = {"period": ("time", 2.0)}', '    PARAMS = {"period": ("time", 2.5)}')
    assert "시간 단위 1.0 의 정수배가 아니다" in said(P.check(line), "P2")
    edit(line, "model_base.py", '    PARAMS = {"period": ("time", 2.5)}', '    PARAMS = {"period": ("time", 2.0)}')
    edit(line, "model_base.py", "from ses_core.devs import INF, Atomic, module_of", "from ses_core.devs import INF, Atomic, module_off")
    assert "모델 베이스를 실을 수 없다: ImportError" in said(P.check(line), "P2")


def test_the_binding_is_checked(line):
    edit(line, "binding.yaml", "target: Line", "target: Lime")
    assert "target 이 Lime 인데 문서의 이름은 Line 이다" in said(P.check(line), "P3")
    edit(line, "binding.yaml", "target: Lime", "target: Line")
    edit(line, "binding.yaml", "  Sink: {module: Sink}", "  Sunk: {module: Sink}")
    report = P.check(line)
    assert "문서에 없는 정의 Sunk 를 묶었다" in said(report, "P3")
    edit(line, "binding.yaml", "  Sunk: {module: Sink}", "  Sink: {module: Drain}")
    assert "모듈 Drain 이 라이브러리에 없다" in said(P.check(line), "P3")


def test_the_cases_are_checked(line):
    edit(line, "cases/fast.decisions.yaml", "alternative: Fast", "alternative: Faster")
    report = P.check(line)
    assert codes(report) == {"P4"} and "fast" in {f.where for f in report.errors} and "slow" not in {f.where for f in report.errors}
    assert "남기려는 선택지가 대상에 없다" in said(report, "P4") or "Faster" in said(report, "P4")
    edit(line, "cases/fast.decisions.yaml", "alternative: Faster", "alternative: Fast")
    edit(line, "cases/fast.decisions.yaml", "  - {at: Worker, specialization: speed, alternative: Fast}", "  []")
    assert "결정이 모자라다" in said(P.check(line), "P4")


def test_a_variant_that_cannot_be_executed_is_reported(line):
    edit(line, "binding.yaml", "  Sink: {module: Sink}\n", "")
    report = P.check(line)
    assert codes(report) == {"P5"} and "B1" in said(report, "P5")
    edit(line, "binding.yaml", "  Slow: {module: Worker}\n", "  Slow: {module: Worker}\n  Sink: {module: Sink}\n")
    edit(line, "line.ses.yaml", "service: {type: float, default: 3.0}", "service: {type: float, default: 2.5}")
    report = P.check(line)
    assert codes(report) == {"P5"} and "B5" in said(report, "P5") and {f.where for f in report.errors} == {"slow"}


def test_a_changed_record_and_a_run_that_does_not_reproduce_are_reported(line):
    edit(line, "line.ses.yaml", "service: {type: float, default: 3.0}", "service: {type: float, default: 4.0}")
    report = P.check(line)
    assert codes(report) == {"P6"} and "기록이 적어 둔 것과 다르다" in said(report, "P6")
    assert P.check(line, record=True).ok and P.check(line).ok                # 뜻한 변화이면 다시 적는다
    edit(line, "model_base.py", "        self.count += 1", "        self.count += __import__('random').randrange(1, 9)")
    report = P.check(line)
    assert codes(report) == {"P6"} and "재현되지 않는다" in said(report, "P6")
    edit(line, "model_base.py", "        self.count += __import__('random').randrange(1, 9)", "        self.count += 1")
    edit(line, "model_base.py", '        return {"out": [self.queue[0]]}', '        return {"done": [self.queue[0]]}')
    report = P.check(line)
    assert "선언하지 않은 출력 포트 done 로 냈다" in said(report, "P6")


@pytest.mark.skipif(not PYEVSIM, reason="pyevsim 이 설치되어 있지 않다")
def test_a_model_that_only_works_on_one_engine_is_reported(line):
    """받은 값을 고치는 모델. 참조 시뮬레이터는 같은 객체를 넘기고 pyevsim 은 복사해서 넘긴다. 기록이 달라진다."""
    edit(line, "model_base.py", '        self.queue += bag.get("in", [])',
         '        self.queue += bag.get("in", [])\n        for job in bag.get("in", []):\n            job["seen"] = self.now')
    report = P.check(line, record=True)
    assert codes(report) == {"P7"} and "pyevsim 의 기록이 참조 시뮬레이터와 다르다" in said(report, "P7")


def test_a_pack_without_a_model_base_is_a_structure_only_pack(tmp_path):
    """모델 베이스가 없는 묶음. 문서와 사례의 결정만 본다. 시뮬레이션이 아닌 분야가 이렇게 올라온다."""
    root = str(tmp_path / "plain")
    os.makedirs(os.path.join(root, "cases"))
    domains = os.path.join(ROOT, "docs", "ses-platform", "domains")
    shutil.copy(os.path.join(domains, "curriculum_intro_programming.ses.yaml"), os.path.join(root, "course.ses.yaml"))
    shutil.copy(os.path.join(domains, "curriculum.profile.yaml"), os.path.join(root, "curriculum.profile.yaml"))
    with open(os.path.join(root, "pack.yaml"), "w", encoding="utf-8") as f:
        f.write('pack: "1.0"\nname: course\ndocument: course.ses.yaml\nprofile: curriculum.profile.yaml\n')
    report = P.check(root)
    assert report.ok and report.family == (12, 4)
    # 족의 일부가 프로파일의 규칙을 어긴다. 그것은 경고다. 족을 좁혀 가는 중에는 흔한 일이다
    assert any("적격이 아닌 변이가 있다" in f.message for f in report.findings if f.severity == "warning")
    with open(os.path.join(root, "pack.yaml"), "a", encoding="utf-8") as f:
        f.write("cases:\n  - {name: run, until: 3}\n")
    assert "돌리려면 모델 베이스와 바인딩이 있어야 한다" in said(P.check(root), "P0")
