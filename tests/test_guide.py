"""처음 오는 연구자를 위한 안내서(docs/ses-platform/GUIDE.md)의 걸음을 그대로 돌린다.

안내서가 낡지 않게 하려는 것이다. 고칠 내용(yaml, python 의 글 상자)은 안내서에서 읽어 와서 쓰고,
안내서가 적은 출력(text 의 글 상자)은 실제로 나온 출력에 줄마다 있어야 한다.
"""

import io
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
        engines = "pyevsim 같다, cevsim 건너뜀"
    except ImportError:
        engines = "pyevsim 건너뜀, cevsim 건너뜀"
    seen = []                                                # 지금까지 나온 출력의 줄들

    def run(*argv, code=0):
        got, out = ses(*argv)
        assert got == code, (argv, out)
        seen.extend(line.replace(engines, "pyevsim 건너뜀, cevsim 건너뜀") for line in out.splitlines())
        return out

    # 2절. 첫 묶음
    run("pack", "new", "mylab")
    monkeypatch.chdir(tmp_path / "mylab")
    doc, mb, binding = "mylab.ses.yaml", "model_base.py", "binding.yaml"
    # 3절과 4절. 묻고, 돌린다
    run("check", doc)
    run("choices", doc)
    run("choices", doc, "--decisions", "cases/slow.decisions.yaml")
    run("build", doc, "--decisions", "cases/slow.decisions.yaml")
    run("pack", "run", ".", "fast", "--log", "4")
    assert run("pack", "check", ".").strip().endswith("묶음 mylab: 통과")

    # 6절 걸음 1. 대안을 하나 더한다. 고칠 글은 안내서에서 읽는다
    edit(doc, "        alternatives: [Fast, Slow]", box("yaml", "alternatives: [Fast, Careful, Slow]"))
    edit(doc, "  Slow:\n", box("yaml", "Careful:\n    extends") + "\n\n  Slow:\n")
    edit(binding, "  Slow: {module: Worker}\n", box("yaml", "Careful: {module: Worker}") + "\n  Slow: {module: Worker}\n")
    with open("cases/careful.decisions.yaml", "w", encoding="utf-8") as f:
        f.write(box("yaml", 'decisions: "1.0"') + "\n")
    with open("pack.yaml", "a", encoding="utf-8") as f:
        f.write(box("yaml", "- {name: careful") + "\n")
    run("pack", "check", ".")
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
    assert ses("pack", "check", ".")[0] == 0

    # 안내서가 적은 출력은 모두 실제로 나온 것이다
    quoted = [line for lang, body in boxes() if lang == "text" for line in body.splitlines() if line.strip()]
    assert len(quoted) >= 25
    missing = [line for line in quoted if line not in seen]
    assert not missing, missing


def test_the_commands_of_the_guide_exist():
    """안내서의 bash 글 상자에 적힌 ses 명령은 모두 이 도구가 아는 명령이다."""
    known = {"check", "choices", "variants", "build", "plan", "run", "pack", "--help"}
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
