"""처음 오는 연구자를 위한 안내서(docs/ses-platform/GUIDE.md)의 걸음을 그대로 돌린다.

안내서가 낡지 않게 하려는 것이다. 고칠 내용(yaml, python 의 글 상자)은 안내서에서 읽어 와서 쓰고,
안내서가 적은 출력(text 의 글 상자)은 실제로 나온 출력에 줄마다 있어야 한다.
"""

import contextlib
import io
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from ses_core import cli  # noqa: E402

GUIDE = os.path.join(ROOT, "docs", "ses-platform", "GUIDE.md")


def boxes() -> list:
    """안내서의 글 상자들: (말, 내용)."""
    with open(GUIDE, encoding="utf-8") as f:
        text = f.read()
    return [(lang, body.rstrip("\n")) for lang, body in re.findall(r"```(\w+)\n(.*?)```", text, flags=re.S)]


def box(lang: str, starts: str) -> str:
    """그 말의 글 상자 가운데 starts 로 시작하는 것 하나."""
    found = [body for kind, body in boxes() if kind == lang and body.lstrip().startswith(starts)]
    assert len(found) == 1, (lang, starts, len(found))
    return found[0]


def ses(*argv) -> tuple:
    out = io.StringIO()
    return cli.main([str(a) for a in argv], out), out.getvalue()


def edit(path: str, old: str, new: str) -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1, (path, old)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def test_the_walk_of_the_guide(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    try:
        import pyevsim  # noqa: F401
        engines, have = "pyevsim 같다, cevsim 건너뜀", ("pyevsim",)
    except ImportError:
        engines, have = "pyevsim 건너뜀, cevsim 건너뜀", ()
    seen = []                                                # 지금까지 나온 출력의 줄들

    def plain(line: str) -> str:
        """엔진이 있고 없음은 컴퓨터마다 다르다. 견주기 전에 지운다. 줄 번호는 지우지 않는다. 안내서가 적은 그대로여야 한다."""
        return line.replace(engines, "pyevsim 건너뜀, cevsim 건너뜀")

    def run(*argv, code=0):
        got, out = ses(*argv)
        assert got == code, (argv, out)
        seen.extend(plain(line) for line in out.splitlines())
        return out

    def write(path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def append(path: str, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    # 2절. 첫 묶음
    run("pack", "new", "mylab")
    monkeypatch.chdir(tmp_path / "mylab")
    assert sorted(n for n in os.listdir(".") if n != "cases") == ["binding.yaml", "model_base.py", "mylab.ses.yaml", "pack.yaml",
                                                                    "records.yaml"]
    doc, mb, binding = "mylab.ses.yaml", "model_base.py", "binding.yaml"
    # 3절과 4절. 묻고, 돌린다
    run("check", doc)
    run("choices", doc)
    run("choices", doc, "--decisions", "cases/slow.decisions.yaml")
    run("build", doc, "--decisions", "cases/slow.decisions.yaml")
    assert "ses plan mylab.ses.yaml --decisions cases/fast.decisions.yaml" in run("pack", "show", ".")
    run("pack", "run", ".", "fast", "--log", "4")
    assert run("pack", "check", ".").strip().endswith("묶음 mylab: 통과")
    # 9절의 줄. 모델이 예외를 내면 자리를 알린다
    edit(mb, 'job["id"]) for job in bag.get("in", [])]', 'job["idd"]) for job in bag.get("in", [])]')
    run("pack", "check", ".", code=1)
    edit(mb, 'job["idd"]) for job in bag.get("in", [])]', 'job["id"]) for job in bag.get("in", [])]')

    # 6절 걸음 1. 대안을 하나 더한다. 고칠 글은 안내서에서 읽는다
    edit(doc, "        alternatives: [Fast, Slow]", box("yaml", "alternatives: [Fast, Careful, Slow]"))
    edit(doc, "  Slow:\n", box("yaml", "Careful:\n    extends") + "\n\n  Slow:\n")
    edit(binding, "  Slow: {module: Worker}\n", box("yaml", "Careful: {module: Worker}") + "\n  Slow: {module: Worker}\n")
    write("cases/careful.decisions.yaml", box("yaml", 'decisions: "1.0"\nname: careful'))
    append("pack.yaml", box("yaml", "- {name: careful"))
    assert run("pack", "check", ".").strip().endswith("묶음 mylab: 통과, 경고 1건")
    run("pack", "check", ".", "--record")

    # 걸음 2. 일부러 틀려 본다
    edit(doc, "      service: {type: float, default: 2.0}", "      service: {type: float, value: 2.0}")
    run("pack", "check", ".", code=1)
    edit(doc, "      service: {type: float, value: 2.0}", "      service: {type: float, default: 2.0}")

    # 걸음 3. 원자 모델을 하나 더한다
    old = ("        parts: [Source, Worker, Sink]\n        couplings:\n"
           "          - {from: Source.out, to: Worker.in}\n          - {from: Worker.out, to: Sink.in}")
    edit(doc, old, box("yaml", "parts: [Source, Worker, Inspector, Sink]"))
    edit(doc, "  Sink:\n", box("yaml", "Inspector:\n    ports") + "\n\n  Sink:\n")
    run("pack", "check", ".", code=1)                        # 구조는 맞고 행동이 없다
    edit(mb, "class Sink(Atomic):", box("python", "class Inspector(Atomic):") + "\n\n\nclass Sink(Atomic):")
    edit(mb, "LIBRARY = {m.name: m for m in (module_of(c) for c in (Source, Worker, Sink))}", box("python", "LIBRARY ="))
    edit(binding, "  Sink: {module: Sink}", box("yaml", "Inspector: {module: Inspector}") + "\n  Sink: {module: Sink}")
    run("pack", "check", ".", code=1)                        # 기록이 달라졌다
    assert run("pack", "check", ".", "--record").strip().endswith("묶음 mylab: 통과")

    # 걸음 4. 사례마다 값을 달리한다
    write("cases/rush.decisions.yaml", box("yaml", 'decisions: "1.0"\nname: rush'))
    append("pack.yaml", box("yaml", "- {name: rush"))
    run("plan", doc, "--decisions", "cases/rush.decisions.yaml", "--binding", binding, "--library", "model_base:LIBRARY")
    assert run("pack", "check", ".", "--record").strip().endswith("묶음 mylab: 통과")

    # 7절 걸음 5. 있을 수도 없을 수도 있는 부분
    edit(doc, "entities:\n", box("yaml", "variables:\n  inspect: {type") + "\n\nentities:\n")
    flow = doc_text(doc)
    start, stop = flow.index("    aspects:\n"), flow.index("  Source:\n")
    write(doc, (flow[:start] + box("yaml", "aspects:\n      inspected:") + "\n\n" + flow[stop:]).rstrip("\n"))
    edit(doc, "      every: {type: int, default: 3, doc: 이 번째 작업마다 하나를 버린다}\n",
         "      every: {type: int, default: 3, doc: 이 번째 작업마다 하나를 버린다}\n" + box("yaml", "specializations:\n      presence:") + "\n")
    run("pack", "check", ".", code=1)                        # 사례마다 변수의 값을 묻는다
    for name in ("fast", "slow", "careful", "rush"):
        edit(f"cases/{name}.decisions.yaml", "target: Line\n", "target: Line\n\n" + box("yaml", "variables:\n  inspect: 1") + "\n")
    write("cases/direct.decisions.yaml", box("yaml", 'decisions: "1.0"\nname: direct'))
    append("pack.yaml", box("yaml", "- {name: direct"))
    run("build", doc, "--decisions", "cases/direct.decisions.yaml")
    assert run("pack", "check", ".", "--record").strip().endswith("묶음 mylab: 통과")
    assert "남은 변이 1개" in run("choices", doc, "--decisions", "cases/direct.decisions.yaml")

    # 걸음 6. 같은 부분을 여러 개 둔다
    edit(doc, "  inspect: {type: int, range: [0, 1], doc: 검사기를 두는가. 1 이면 둔다}\n",
         "  inspect: {type: int, range: [0, 1], doc: 검사기를 두는가. 1 이면 둔다}\n" + box("yaml", "workers: {type: int") + "\n")
    text = doc_text(doc)
    places = (text.count("[Source, Worker, Inspector, Sink]") + text.count("to: Worker.in}") + text.count("from: Worker.out,"))
    assert places == 6                                       # 안내서가 여섯 군데라고 했다
    text = (text.replace("[Source, Worker, Inspector, Sink]", "[Source, Workers, Inspector, Sink]")
            .replace("to: Worker.in}", "to: Workers.in}").replace("from: Worker.out,", "from: Workers.out,"))
    write(doc, text.rstrip("\n"))
    worker = "  Worker:\n    ports:\n      in: {type: Job, direction: in, required: true}\n      out: {type: Job, direction: out}\n"
    edit(doc, worker, box("yaml", "Workers:\n    ports:") + "\n\n" + worker + box("yaml", "attributes:\n      me:") + "\n")
    edit(mb, '    PARAMS = {"service": ("time", 1.0)}', box("python", 'PARAMS = {"service"'))
    edit(mb, '        self.queue += bag.get("in", [])\n        if self.left == INF:\n            self.left = self.service',
         box("python", "self.queue += [job for job"))
    for name in ("fast", "slow", "careful", "rush", "direct"):
        path = f"cases/{name}.decisions.yaml"
        value = "  inspect: 0\n" if name == "direct" else "  inspect: 1\n"
        edit(path, value, value + "  workers: 1\n")
    write("cases/pair.decisions.yaml", box("yaml", 'decisions: "1.0"\nname: pair'))
    append("pack.yaml", box("yaml", "- {name: pair"))
    run("build", doc, "--decisions", "cases/pair.decisions.yaml")
    run("pack", "check", ".", code=1)                        # 자리가 바뀌어 기록이 달라졌다
    assert run("pack", "check", ".", "--record").strip().endswith("묶음 mylab: 통과")
    run("pack", "run", ".", "pair", "--log", "4")
    assert ses("pack", "check", ".")[0] == 0

    # 정의로 적은 결정(at)과 자리로 적은 결정(path)은 둘 다 적용된다
    pair = doc_text("cases/pair.decisions.yaml")
    at_line = "  - {at: Worker, specialization: speed, alternative: Slow}"
    append("cases/pair.decisions.yaml", box("yaml", "- {path: [Line, Workers, w1]"))
    run("choices", doc, "--decisions", "cases/pair.decisions.yaml", code=1)
    edit("cases/pair.decisions.yaml", at_line, box("yaml", "- {path: [Line, Workers, w0]"))
    run("choices", doc, "--decisions", "cases/pair.decisions.yaml")
    run("build", doc, "--decisions", "cases/pair.decisions.yaml")
    write("cases/pair.decisions.yaml", pair.rstrip("\n"))     # 안내서가 말한 대로 처음의 한 줄로 되돌린다
    assert ses("pack", "check", ".")[0] == 0

    # 7절의 끝. 대안마다 포트가 다를 때와 제약
    crossing = str(tmp_path / "crossing.ses.yaml")
    write(crossing, box("yaml", 'ses: "1.0"\nname: Crossing'))
    run("check", crossing, code=1)
    append(crossing, "\n" + box("yaml", "constraints:\n  - name: fixed_time_has_no_detector"))
    run("check", crossing)
    only = str(tmp_path / "actuated.yaml")                   # 제약이 정하는 선택은 다시 적지 않아도 된다
    write(only, 'decisions: "1.0"\ntarget: Crossing\nchoose:\n  - {at: Controller, specialization: kind, alternative: Actuated}')
    assert "Detector: Detector, Installed" in run("build", crossing, "--decisions", only)
    write(only, 'decisions: "1.0"\ntarget: Crossing\nchoose:\n  - {at: Controller, specialization: kind, alternative: FixedTime}\n'
                '  - {at: Detector, specialization: presence, alternative: Installed}')
    assert "제약 fixed_time_has_no_detector 을 어긴다" in run("build", crossing, "--decisions", only, code=1)

    # 11절. 기록을 JSON 으로 받는다
    got, out = ses("call", "pack_run", "--args", '{"dir": ".", "case": "fast", "limit": 1000}')
    env = json.loads(out.splitlines()[-1])
    assert got == 0 and env["ok"] and len(env["result"]["log"]) == env["result"]["events"] == 25

    # 11절. 값을 바꿔 가며 돌리는 스크립트. 안내서의 글을 그대로 돌린다
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(box("python", "from ses_core import pack as P"), "sweep.py", "exec"), {})
    seen.extend(printed.getvalue().splitlines())

    # 2절. 틀의 full 은 걸음을 끝까지 따라간 상태와 같다
    from ses_core import pack as P
    full = str(tmp_path / "full")
    P.scaffold(full, "mylab", "full")
    assert P.check(full, record=True).ok
    mine = sorted(os.path.relpath(os.path.join(base, n), ".") for base, _, names in os.walk(".") for n in names
                  if "__pycache__" not in base)
    assert mine == sorted(os.path.relpath(os.path.join(base, n), full) for base, _, names in os.walk(full) for n in names)
    for name in mine:                                        # 기록까지 같다
        assert doc_text(name) == doc_text(os.path.join(full, name)), name

    # 안내서가 적은 출력은 모두 실제로 나온 것이다
    quoted = [plain(line) for lang, body in boxes() if lang == "text" for line in body.splitlines() if line.strip()]
    quoted = [line for line in quoted if not any(line.startswith(f"info P7 {name}") for name in have)]
    assert len(quoted) >= 65
    missing = [line for line in quoted if line not in seen]
    assert not missing, missing


def doc_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_the_structure_only_pack_of_the_guide(tmp_path, monkeypatch):
    """12절. 선언에서 모델 베이스와 바인딩을 지우면 구조만 가진 묶음이다. 사례마다 구조의 지문을 적어 둔다."""
    monkeypatch.chdir(tmp_path)
    assert ses("pack", "new", "mylab")[0] == 0
    monkeypatch.chdir(tmp_path / "mylab")
    with open("pack.yaml", "w", encoding="utf-8") as f:
        f.write(box("yaml", 'pack: "1.0"') + "\n")
    for name in ("model_base.py", "binding.yaml"):
        os.remove(name)
    code, out = ses("pack", "check", ".", "--record")
    assert code == 0 and out.strip().endswith("묶음 mylab: 통과")
    assert re.search(r"사례 fast: 구성요소 4개. 구조의 지문 [0-9a-f]{16}", out)
    with open("records.yaml", encoding="utf-8") as f:
        assert "fast: {structure:" in f.read()
    assert ses("pack", "check", ".")[0] == 0
    code, out = ses("build", "mylab.ses.yaml", "--decisions", "cases/fast.decisions.yaml", "--attributes")
    assert code == 0 and '{"service": 1.0}' in out


def test_the_commands_of_the_guide_exist():
    """안내서의 bash 글 상자에 적힌 ses 명령은 모두 이 도구가 아는 명령이다."""
    known = {"check", "choices", "variants", "build", "plan", "run", "pack", "ops", "call", "--help"}
    for lang, body in boxes():
        if lang != "bash":
            continue
        for line in body.splitlines():
            words = line.split()
            if "ses" in words:
                assert words[words.index("ses") + 1] in known, line


def test_the_large_case_of_the_guide_answers_quickly():
    """9절. 변이가 9,000개인 족의 선택지를 열거하지 않고 낸다."""
    import time
    old = os.getcwd()
    os.chdir(ROOT)
    try:
        started = time.time()
        code, out = ses("choices", "packs/wsn/wsn.ses.yaml", "--functions", "packs.wsn.model_base:FUNCTIONS")
    finally:
        os.chdir(old)
    assert code == 0 and out.startswith("남은 변이 9000개\n") and time.time() - started < 10
