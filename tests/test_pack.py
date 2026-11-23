"""분야 묶음 (ses_core/pack.py, docs/ses-platform/20_packs.md).

묶음은 연구자가 자기 분야를 올리는 단위다. 여기서 보는 것은 셋이다.
1. 뼈대(ses pack new)가 그대로 검사를 통과한다. 처음 오는 사람이 받는 것이 돌아가는 것이어야 한다.
2. 저장소의 묶음들이 검사를 통과하고, 적어 둔 기록과 같은 기록을 낸다.
3. 계약을 어긴 묶음을 검사가 잡고, 어디가 틀렸는지를 부호로 알린다. 뼈대를 한 군데씩 틀리게 고쳐 본다.
"""

import io
import os
import re
import shutil
import sys

import pytest
import yaml

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
    assert P.check(line).ok                                      # 쓰이지 않는 기본값은 따지지 않는다. 문서가 2.0 을 준다
    edit(line, "line.ses.yaml", "      period: {type: float, default: 2.0, doc: 작업을 내는 간격}\n", "")
    report = P.check(line)                                       # 문서가 주지 않으면 그 기본값이 쓰인다. 실제 값으로 본다
    assert codes(report) == {"P5"} and "매개변수 period 의 값 2.5 이 시간 단위 1.0 의 음이 아닌 정수배가 아니다" in said(report, "P5")
    edit(line, "model_base.py", '    PARAMS = {"period": ("time", 2.5)}', '    PARAMS = {"period": ("time", 2.0)}')
    assert P.check(line).ok
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


def records_of(root: str) -> dict:
    with open(os.path.join(root, "records.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_a_model_that_changes_what_it_received_is_reported(line):
    """받은 값을 고치는 모델. 참조 시뮬레이터는 같은 객체를 넘기고 pyevsim 은 복사해서 넘긴다.

    다른 엔진이 없어도 잡는다. 받는 모델마다 값을 베껴서 넘기며 한 번 더 돌리고, 넘긴 값이 고쳐졌는지 본다.
    기록의 값은 낸 때의 값이다. 받은 쪽이 고쳐도 낸 쪽의 줄은 바뀌지 않는다."""
    before = records_of(line)
    edit(line, "model_base.py", '        self.queue += bag.get("in", [])',
         '        self.queue += bag.get("in", [])\n        for job in bag.get("in", []):\n            job["id"] += 100')
    report = P.check(line, record=True, executors=("devs",))
    assert codes(report) == {"P6"} and "Worker 의 external() 이 포트 in 에서 받은 값을 고쳤다" in said(report, "P6")
    assert len(report.of("P6")) <= 4                             # 사례와 함수마다 한 줄. 사건마다가 아니다
    assert records_of(line) == before                            # 잘못된 기록은 적지 않는다
    log, _, _ = P.run(line, "fast")
    assert log[0] == (2.0, ("Source",), "out", {"id": 0})        # 낸 쪽의 줄은 낸 때의 값이다
    assert log[1] == (3.0, ("Worker",), "out", {"id": 100})


def test_a_model_that_changes_what_it_sent_is_reported(line):
    """낸 값을 낸 뒤에 고치는 모델. 받은 쪽은 아무것도 고치지 않았는데 값을 넘기는 방식에 따라 기록이 달라진다."""
    edit(line, "model_base.py", '        return {"out": [{"id": self.count}]}',
         '        self.last = {"id": self.count}\n        return {"out": [self.last]}')
    edit(line, "model_base.py", "        self.count += 1", '        self.count += 1\n        self.last["id"] += 100')
    report = P.check(line, executors=("devs",))
    assert codes(report) == {"P6"} and "받는 모델마다 값을 베껴서 넘기면 기록이 달라진다" in said(report, "P6")
    assert "재현되지 않는다" not in said(report, "P6") and "받은 값을 고쳤다" not in said(report, "P6")


@pytest.mark.skipif(not PYEVSIM, reason="pyevsim 이 설치되어 있지 않다")
def test_a_record_that_differs_on_another_engine_is_reported(line, monkeypatch):
    """다른 실행기의 기록이 참조 시뮬레이터와 다르면 알린다. 마지막 사건을 빼먹는 실행기를 세워 본다."""
    from ses_core.pyevsim_executor import PyevsimExecutor

    class Forgetful(PyevsimExecutor):
        def build(self, plan, library):
            sim = super().build(plan, library)
            run = sim.run
            sim.run = lambda until: list(run(until))[:-1]
            return sim

    monkeypatch.setattr(P, "_engine", lambda name: (Forgetful(), None) if name == "pyevsim" else (None, "없다"))
    report = P.check(line)
    assert codes(report) == {"P7"} and "pyevsim 의 기록이 참조 시뮬레이터와 다르다" in said(report, "P7")
    assert "사건의 수가 다르다" in said(report, "P7")
    assert {c["executors"]["pyevsim"] for c in report.cases.values()} == {P.DIFFERENT}


def test_a_failing_model_is_located(line):
    """모델의 코드가 예외를 내면 어느 구성요소의 어느 함수가 언제 어느 줄에서 냈는지를 알린다."""
    edit(line, "model_base.py", "        self.received += [", "        self.gone += [")
    report = P.check(line)
    text = said(report, "P6")
    assert codes(report) == {"P6"} and "Sink 의 external() 이 시각 3.0 에서 예외를 냈다: AttributeError" in text
    assert re.search(r"\(model_base\.py \d+번째 줄\)", text)
    with pytest.raises(P.PackError, match=r"Sink 의 external\(\) 이 시각 3.0 에서 예외를 냈다") as e:
        P.run(line, "fast")
    assert e.value.code == "P6"
    code, out = ses("run", os.path.join(line, "line.ses.yaml"), "--decisions", os.path.join(line, "cases/fast.decisions.yaml"),
                    "--binding", os.path.join(line, "binding.yaml"), "--library", "nowhere:LIBRARY", "--until", 5)
    assert code == 1 and "Traceback" not in out
    edit(line, "model_base.py", "        self.gone += [", "        self.received += [")
    edit(line, "model_base.py", '        return {"out": [{"id": self.count}]}', "        return [self.count]")
    assert "output() 은 포트 이름에서 값의 목록으로 가는 사전을 내야 한다" in said(P.check(line), "P2")      # 처음 상태에서 이미 틀렸다


def test_a_port_that_only_the_model_has_is_reported_before_running(line):
    """모델의 PORTS 에만 있는 포트. 그 포트로 한 번도 내지 않아도 알린다."""
    edit(line, "model_base.py", '    PORTS = {"in": ("Job", "in")}', '    PORTS = {"in": ("Job", "in"), "spare": ("Job", "out")}')
    report = P.check(line)
    assert codes(report) == {"P5"} and "Sink: 모듈 Sink 의 포트 spare 가 문서의 그 정의에 없다" in said(report, "P5")
    assert all("events" not in c for c in report.cases.values())     # 돌려 보기 전에 멈춘다
    edit(line, "line.ses.yaml", "  Sink:\n    ports:\n      in: {type: Job, direction: in, required: true}\n",
         "  Sink:\n    ports:\n      in: {type: Job, direction: in, required: true}\n      spare: {type: Job, direction: out}\n")
    assert P.check(line).ok                                      # 문서에도 적으면 된다. 이어지지 않은 출력 포트는 괜찮다


def test_an_attribute_that_does_not_reach_the_model_is_a_warning(line):
    """속성의 이름을 잘못 적으면 모델은 기본값으로 돈다. 아무 말이 없으면 찾기 어렵다."""
    assert not [f for f in P.check(line).findings if f.severity == "warning"]
    edit(line, "line.ses.yaml", "service: {type: float, default: 3.0}", "service_time: {type: float, default: 3.0}")
    report = P.check(line)
    warned = [f.message for f in report.findings if f.severity == "warning" and f.code == "P5"]
    assert warned == ["정의 Slow 의 속성 service_time 은 모듈 Worker 의 매개변수가 아니다. 모델에 전해지지 않는다. "
                      "모듈의 매개변수는 ['service'] 다"]
    assert codes(report) == {"P6"} and "기록이 적어 둔 것과 다르다" in said(report, "P6")    # 그리고 결과가 달라졌다


def test_records_follow_the_cases(line):
    """없어진 사례의 기록은 --record 가 지운다. 기록이 없는 사례는 경고다."""
    edit(line, "pack.yaml", "  - {name: slow, decisions: cases/slow.decisions.yaml, until: 20}\n", "")
    report = P.check(line)
    stale = [f for f in report.findings if f.severity == "warning"]
    assert report.ok and len(stale) == 1 and "사례 slow 의 기록이 있는데 그런 사례가 없다. ses pack check --record 가 지운다" in stale[0].message
    report = P.check(line, record=True)
    assert report.ok and not [f for f in report.findings if f.severity == "warning"] and set(records_of(line)) == {"fast"}
    os.remove(os.path.join(line, "records.yaml"))
    report = P.check(line)
    assert report.ok and [f.message for f in report.findings if f.severity == "warning"] == [
        "적어 둔 기록이 없다. ses pack check --record 로 적는다"]
    code, out = ses("pack", "check", line)
    assert code == 0 and out.strip().endswith("묶음 line: 통과, 경고 1건")


def test_the_same_fault_in_many_replicas_is_told_once(tmp_path):
    """복제본 1,000개가 모두 같은 잘못을 가질 때. 줄 1,000개를 내지 않는다."""
    root = str(tmp_path / "wsn")
    shutil.copytree(os.path.join(PACKS, "wsn"), root)
    edit(root, "binding.yaml", "  SENSOR: {module: Sensor}\n", "")
    report = P.check(root)
    told = [f.message for f in report.of("P5") if f.where == "field_1000"]
    assert len(told) == 8 and "바인딩의 map 에 정의 SENSOR 를 적는다" in told[0] and "993건 더 있다" in told[-1]
    edit(root, "binding.yaml", "  BS: {module: Bs}\n", "  BS: {module: Bs}\n  SENSOR: {module: Sensor}\n")
    edit(root, "model_base.py", 'PORTS = {"event": ("Event", "in"),', 'PORTS = {"spare": ("Event", "in"), "event": ("Event", "in"),')
    told = [f.message for f in P.check(root).of("P5") if f.where == "field_1000"]
    assert len(told) == 1 and "등 1000곳" in told[0] and "포트 spare 가 문서의 그 정의에 없다" in told[0]


def test_what_the_rules_fix_need_not_be_decided_again(line):
    """선택지 표가 남은 변이 1개라고 하면 조립도 된다. 규칙이 정한 변수 값을 사례에 다시 적지 않아도 된다."""
    edit(line, "line.ses.yaml", "entities:\n", "variables:\n  quick: {type: int, range: [0, 1]}\n\nentities:\n")
    edit(line, "line.ses.yaml", "        alternatives: [Fast, Slow]\n",
         "        alternatives: [Fast, Slow]\n        select: {when: {var: quick, eq: 1}, then: Fast, else: Slow}\n")
    code, out = ses("choices", os.path.join(line, "line.ses.yaml"), "--decisions", os.path.join(line, "cases/slow.decisions.yaml"))
    assert code == 0 and "남은 변이 1개" in out and "quick variable: 정해짐. 남은 선택지 [0] / 전체 [0, 1]" in out
    code, out = ses("build", os.path.join(line, "line.ses.yaml"), "--decisions", os.path.join(line, "cases/slow.decisions.yaml"))
    assert code == 0 and "변수 값 {'quick': 0}" in out and "쓰이지 않은 결정" not in out
    report = P.check(line)
    assert report.ok and {n: c["variables"] for n, c in report.cases.items()} == {"fast": {"quick": 1}, "slow": {"quick": 0}}
    empty = os.path.join(line, "cases", "empty.decisions.yaml")
    with open(empty, "w", encoding="utf-8") as f:
        f.write('decisions: "1.0"\nname: empty\ntarget: Line\n')
    code, out = ses("build", os.path.join(line, "line.ses.yaml"), "--decisions", empty)
    assert code == 3 and "결정이 모자라다" in out                # 변이가 둘 남으면 여전히 묻는다


def test_a_component_path_starts_at_the_root(line):
    with open(os.path.join(line, "cases/fast.decisions.yaml"), "a", encoding="utf-8") as f:
        f.write("\nset:\n  - {path: [Worker], attribute: service, value: 2.0}\n")
    report = P.check(line)
    assert {f.where for f in report.errors} == {"fast"} and "구성요소 경로는 뿌리의 이름 Line 에서 시작한다" in said(report, "P4")
    edit(line, "cases/fast.decisions.yaml", "{path: [Worker],", "{path: [Line, Worker],")
    report = P.check(line)
    assert "P4" not in codes(report) and "기록이 적어 둔 것과 다르다" in said(report, "P6")     # 이제 값이 전해졌다


def test_the_commands_do_not_print_tracebacks_for_common_mistakes(line, tmp_path):
    doc = os.path.join(line, "line.ses.yaml")
    edit(line, "line.ses.yaml", "        parts: [Source, Worker, Sink]", "        parts: [Source, Worker, Sink")
    for argv in (("check", doc), ("choices", doc), ("variants", doc), ("build", doc, "--decisions", os.path.join(line, "cases/fast.decisions.yaml"))):
        code, out = ses(*argv)
        assert code == 1 and "YAML 문법이 틀렸다" in out and "번째 줄" in out, (argv, out)
    report = P.check(line)
    assert codes(report) == {"P1"} and "YAML 문법이 틀렸다" in said(report, "P1")

    class Closed(io.StringIO):
        def write(self, text):
            raise BrokenPipeError(32, "Broken pipe")

    assert cli.main(["pack", "show", os.path.join(PACKS, "wsn")], Closed()) == 0     # 받는 쪽이 닫아도 조용히 끝난다
    code, out = ses("choices", os.path.join(PACKS, "wsn", "wsn.ses.yaml"), "--functions", "packs.wsn.model_base:FUNCTIONS")
    assert code == 0 and "[1 ... 1000] (1000개)" in out and len(out) < 1500


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


def test_a_run_that_does_not_end_is_stopped_and_the_limit_can_be_raised(line):
    """걸음 수의 한도. 끝나지 않는 모델을 멈춘다. 긴 사례는 선언에서 한도를 올린다."""
    edit(line, "pack.yaml", "{name: fast, decisions: cases/fast.decisions.yaml, until: 20}",
         "{name: fast, decisions: cases/fast.decisions.yaml, until: 20, max_steps: 5}")
    report = P.check(line)
    text = said(report, "P6")
    assert codes(report) == {"P6"} and "정해진 걸음 수 안에 끝나지 않았다. 걸음 5개를 돌았고" in text
    assert "pack.yaml 의 그 사례에 max_steps 를 적는다" in text
    with pytest.raises(P.PackError, match="max_steps 를 적는다"):
        P.run(line, "fast")
    edit(line, "pack.yaml", "max_steps: 5}", "max_steps: 50}")
    assert P.check(line).ok
    edit(line, "pack.yaml", "max_steps: 50}", "max_steps: 0}")
    assert "max_steps: 걸음 수의 한도는 1 이상의 정수여야 한다" in said(P.check(line), "P0")
    assert P.MAX_STEPS == 1000000


def test_a_structure_only_pack_records_the_structure_of_its_cases(line):
    """모델 베이스가 없는 묶음의 사례. 돌릴 것이 없으므로 만든 구조의 지문을 적어 두고 견준다.

    처음 온 연구자의 역할을 맡은 검증에서 나왔다. 구조만 가진 묶음은 사례마다 "만들지 못했다"고 나왔고
    적어 둘 기록이 없었다."""
    with open(os.path.join(line, "pack.yaml"), "w", encoding="utf-8") as f:
        f.write('pack: "1.0"\nname: line\ndocument: line.ses.yaml\ncases:\n'
                "  - {name: fast, decisions: cases/fast.decisions.yaml}\n  - {name: slow, decisions: cases/slow.decisions.yaml}\n")
    for name in ("model_base.py", "binding.yaml", "records.yaml"):
        os.remove(os.path.join(line, name))
    report = P.check(line)
    assert report.ok and [f.message for f in report.findings if f.severity == "warning"] == [
        "적어 둔 기록이 없다. ses pack check --record 로 적는다"] * 2
    assert {n: c["components"] for n, c in report.cases.items()} == {"fast": 4, "slow": 4}
    fast, slow = report.cases["fast"]["structure"], report.cases["slow"]["structure"]
    assert fast != slow and re.fullmatch(r"[0-9a-f]{16}", fast)
    assert P.check(line, record=True).ok
    assert records_of(line) == {"fast": {"structure": fast}, "slow": {"structure": slow}}
    code, out = ses("pack", "check", line)
    assert code == 0 and f"사례 fast: 구성요소 4개. 구조의 지문 {fast}" in out and "만들지 못했다" not in out
    assert out.strip().endswith("묶음 line: 통과")

    edit(line, "line.ses.yaml", "service: {type: float, default: 1.0,", "service: {type: float, default: 1.5,")
    report = P.check(line)                                   # 속성의 값도 구조에 든다
    assert codes(report) == {"P6"} and {f.where for f in report.errors} == {"fast"}
    assert f"구조가 적어 둔 것과 다르다. 적어 둔 지문은 {fast}" in said(report, "P6")
    code, out = ses("build", os.path.join(line, "line.ses.yaml"), "--decisions", os.path.join(line, "cases/fast.decisions.yaml"),
                    "--attributes")
    assert code == 0 and '  Worker: Worker, Fast {"service": 1.5}' in out and '  Source {"period": 2.0}' in out
    assert P.check(line, record=True).ok and P.check(line).ok


def test_the_large_case_of_the_repository_keeps_its_structure():
    report = P.check(os.path.join(PACKS, "wsn"), executors=("devs",))
    assert report.ok and report.cases["field_1000"]["structure"] == records_of(os.path.join(PACKS, "wsn"))["field_1000"]["structure"]
    assert report.cases["field_1000"]["components"] == 1007


def test_a_misspelt_key_in_a_decision_file_is_reported(line):
    """결정 집합의 오타. variables 를 variable 로 적으면 결정이 없는 것처럼 읽혀 먼 곳에서 틀렸다고 나왔다."""
    import json
    from ses_core import decisions as D
    with open(os.path.join(ROOT, "docs", "ses-platform", "schema", "decisions.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    assert D._FILE_KEYS == set(schema["properties"])             # 적재기가 아는 항목은 스키마의 것과 같다
    assert D._CHOICE_KEYS == set(schema["$defs"]["choice"]["properties"])
    assert D._SET_KEYS == set(schema["$defs"]["override"]["properties"])

    path = os.path.join(line, "cases", "fast.decisions.yaml")
    original = open(path, encoding="utf-8").read()
    for text, word in ((original.replace("choose:", "chose:"), "결정 집합: 모르는 항목 chose 가 있다. choose 를 뜻했는가"),
                       (original.replace("alternative: Fast", "alternatives: Fast"),
                        "choose[0]: 모르는 항목 alternatives 가 있다. alternative 를 뜻했는가"),
                       (original + "variable:\n  n: 3\n", "모르는 항목 variable 가 있다. variables 를 뜻했는가"),
                       (original + "variables: [n, 3]\n", "variables: 변수 이름에서 값으로 가는 표로 적는다"),
                       (original + "set:\n  - {at: Fast, attr: service, value: 2.0}\n", "set[0]: 모르는 항목 attr 가 있다. attribute 를 뜻했는가"),
                       (original + "set:\n  - {path: Line/Worker, attribute: service, value: 2.0}\n", "set[0].path: 이름의 목록으로 적는다"),
                       (original.split("choose:")[0] + "choose: {at: Worker}\n", "choose: 목록으로 적는다"),
                       ("", "파일이 비어 있다"),
                       ("- 1\n- 2\n", "결정 집합: 이름과 값의 표로 적어야 한다")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        with pytest.raises(D.DecisionError) as e:
            D.load_decisions(path)
        assert word in str(e.value), (word, str(e.value))
        report = P.check(line)
        assert codes(report) == {"P4"} and "결정 집합의 모양이 틀렸다. " in said(report, "P4") and word in said(report, "P4")
        code, out = ses("choices", os.path.join(line, "line.ses.yaml"), "--decisions", path)
        assert code == 1 and word in out and "Error" not in out
    with open(path, "w", encoding="utf-8") as f:
        f.write(original)
    assert P.check(line).ok


def test_small_things_the_trial_asked_for(line, tmp_path):
    """검증에서 나온 작은 것들: 프로파일을 따르는 문서의 조립, 잘린 목록의 알림, 타입의 이름."""
    domains = os.path.join(ROOT, "docs", "ses-platform", "domains")
    doc, profile = os.path.join(domains, "curriculum_intro_programming.ses.yaml"), os.path.join(domains, "curriculum.profile.yaml")
    ds = tmp_path / "one.decisions.yaml"
    ds.write_text('decisions: "1.0"\nname: one\ntarget: 프로그래밍입문\nvariables:\n  실습주수: 1\nchoose:\n'
                  "  - {at: 심화알고리즘, specialization: 개설여부, alternative: 심화개설}\n"
                  "  - {at: 응용영역, aspect: 자료처리트랙}\n", encoding="utf-8")
    code, out = ses("build", doc, "--decisions", ds)
    assert code == 1 and "프로파일을 함께 주어야 한다" in out
    code, out = ses("build", doc, "--decisions", ds, "--profile", profile)
    assert code == 0 and "변수 값 {'실습주수': 1}" in out
    code, out = ses("check", doc, "--profile", profile)
    assert code == 1 and "총시수: 값이 48 이다. 규칙은 최소 30, 최대 45 이다" in out

    code, out = ses("variants", doc, "--limit", 3)
    assert code == 0 and out.splitlines()[0] == "변이 12개. 앞의 3개만 보인다. --limit 로 늘린다" and len(out.splitlines()) == 4
    code, out = ses("variants", doc, "--limit", 12)
    assert out.splitlines()[0] == "변이 12개"

    edit(line, "line.ses.yaml", "period: {type: float, default: 2.0,", "period: {type: time, default: 2.0,")
    text = said(P.check(line), "P1")
    assert "Source: 속성 period: 알 수 없는 타입 'time'" in text and "시간 값은 문서에 float 로 적고 모델의 PARAMS 에서 time 으로 적는다" in text
    edit(line, "line.ses.yaml", "period: {type: time, default: 2.0,", "period: {type: float, default: 2.0,")
    edit(line, "pack.yaml", 'pack: "1.0"', 'pack: "2"')
    code, out = ses("pack", "check", line)
    assert code == 1 and out.strip().endswith("묶음 line: 오류 1건")      # 선언을 읽지 못해도 디렉터리의 이름으로 부른다


def test_an_edit_made_within_the_same_second_is_seen(line):
    """같은 초 안에 같은 크기로 고친 모델 베이스. 파이썬의 바이트코드 캐시는 그것을 옛 코드로 읽는다.

    검증자가 찾았다. 뼈대를 만든 직후에 모델을 고치고 검사하면 열 번에 열 번 옛 코드가 돌았다.
    고치고 바로 검사하는 것이 이 도구를 쓰는 방식이므로 캐시를 거치지 않고 원본을 읽는다."""
    import importlib.util
    import py_compile
    path = os.path.join(line, "model_base.py")
    with open(path, "a", encoding="utf-8") as f:
        f.write("MARK = 1\n")
    stamp = os.stat(path)
    py_compile.compile(path)                                 # 누군가 이 파일을 불러와 캐시가 생겼다
    with open(path, encoding="utf-8") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace("MARK = 1", "MARK = 2").replace("        self.count += 1", "        self.count += 2"))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))    # 같은 시각, 같은 크기
    assert os.stat(path).st_size == stamp.st_size
    spec = importlib.util.spec_from_file_location("stale_probe", path)
    stale = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stale)
    assert stale.MARK == 1                                   # 보통의 불러오기는 옛 코드를 읽는다. 이 시험의 전제다
    assert P.module(P.load(line)).MARK == 2                  # 묶음의 싣기는 고친 것을 읽는다
    log, _, _ = P.run(line, "fast")
    assert [v["id"] for _, p, _, v in log if p == ("Source",)][:3] == [0, 2, 4]
    assert codes(P.check(line)) == {"P6"}                    # 그래서 검사가 달라진 기록을 알린다


def test_global_randomness_and_wall_clocks_are_pointed_out(line):
    """전역 난수와 벽시계. 돌려 봐서는 드러나지 않을 수 있어 글에서 찾아 경고한다."""
    found = P.lint("import random\nimport time as t\nfrom datetime import datetime\nfrom random import randint, Random\n"
                   "a = random.Random(3)\nb = random.random()\nrandom.seed(1)\nc = randint(1, 2)\nd = Random(4)\n"
                   "e = t.time()\nf = datetime.now()\ng = a.random()\n")
    assert [n for n, _ in found] == [6, 7, 8, 10, 11]
    assert "전역 난수 random.random()" in found[0][1] and "전역 난수 randint()" in found[2][1]
    assert "벽시계 time.time()" in found[3][1] and "벽시계 datetime.now()" in found[4][1]
    assert P.lint("def broken(:\n") == [] and P.lint("") == []
    for name in sorted(os.listdir(PACKS)):                   # 저장소의 묶음은 지킨다
        with open(os.path.join(PACKS, name, "model_base.py"), encoding="utf-8") as f:
            assert P.lint(f.read()) == []

    edit(line, "model_base.py", "from ses_core.devs import", "import random\nfrom ses_core.devs import")
    edit(line, "model_base.py", "        self.count = 0", "        self.count = 0\n        random.seed(7)")
    edit(line, "model_base.py", '        return {"out": [{"id": self.count}]}',
         '        return {"out": [{"id": self.count, "luck": random.random()}]}')
    report = P.check(line)
    warned = [f.message for f in report.findings if f.severity == "warning" and f.code == "P2"]
    assert len(warned) == 2 and all("전역 난수 random." in w and "번째 줄" in w for w in warned)
    # 씨앗을 주었으므로 두 번 돌린 기록은 같다. 돌려 봐서는 재현되지 않는다는 것이 드러나지 않는다
    assert "재현되지 않는다" not in said(report, "P6")


def test_an_unknown_key_of_a_case_is_named(line):
    edit(line, "pack.yaml", "{name: slow, decisions: cases/slow.decisions.yaml, until: 20}",
         "{name: slow, decisions: cases/slow.decisions.yaml, untill: 20}")
    text = said(P.check(line), "P0")
    assert "cases[1]: 모르는 항목 ['untill'] 가 있다" in text and "'until'" in text
    edit(line, "pack.yaml", "{name: slow, decisions: cases/slow.decisions.yaml, untill: 20}", "{decisions: cases/slow.decisions.yaml}")
    assert "cases[1]: 사례에 name 이 없다" in said(P.check(line), "P0")


def test_a_document_without_a_wellformed_variant_is_an_error(line):
    """족의 어떤 변이가 규칙을 어기는 것은 경고다. 적격인 변이가 하나도 없으면 오류다."""
    edit(line, "line.ses.yaml", "          - {from: Source.out, to: Worker.in}\n", "")
    report = P.check(line)
    assert report.family == (2, 0) and "P1" in codes(report)
    assert "변이 2개 가운데 적격인 것이 하나도 없다" in said(report, "P1")
    assert any(f.severity == "warning" and "적격이 아닌 변이가 있다" in f.message for f in report.of("P1"))
