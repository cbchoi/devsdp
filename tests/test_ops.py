"""에이전트가 부르는 연산 (ses_core/ops.py, docs/ses-platform/21_agent_operations.md).

지키는지 보는 약속
- 결과는 늘 봉투의 모양이고 JSON 으로 옮겨진다.
- 연산은 예외를 내지 않는다. 잘못은 부호가 붙은 줄이 된다.
- 사람이 쓰는 명령과 같은 답을 낸다.
- 작업 자리 밖을 다루지 않고, 쓰지 않는다고 한 연산은 파일을 하나도 바꾸지 않는다.
"""

import dataclasses
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys

import jsonschema
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from ses_core import cli, ops  # noqa: E402
from ses_core import pack as P  # noqa: E402

PACKS = os.path.join(ROOT, "packs")
ENVELOPE = jsonschema.Draft202012Validator(ops.ENVELOPE)
STATS = {"calls": 0, "failed": 0}


def call(name, args=None, root=None) -> dict:
    """연산을 부르고, 결과가 봉투의 모양이며 JSON 으로 오가는지 본다."""
    env = ops.call(name, args, root=root)
    ENVELOPE.validate(env)
    assert json.loads(json.dumps(env, ensure_ascii=False, allow_nan=False)) == env
    assert env["ok"] == (not any(f["severity"] == "error" for f in env["findings"]))
    STATS["calls"] += 1
    STATS["failed"] += not env["ok"]
    return env


def codes(env) -> set:
    return {f["code"] for f in env["findings"] if f["severity"] == "error"}


def said(env) -> str:
    return " | ".join(f["message"] for f in env["findings"])


def snapshot(root) -> dict:
    """디렉터리 아래 모든 파일의 내용의 지문."""
    out = {}
    for base, _, names in os.walk(root):
        for n in names:
            path = os.path.join(base, n)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return out


def edit(path, old, new) -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1, (path, old)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


@pytest.fixture
def lab(tmp_path):
    """작업 자리와, 그 안에 갓 만든 묶음 lab."""
    env = call("pack_new", {"dir": "lab"}, root=str(tmp_path))
    assert env["ok"], said(env)
    return str(tmp_path)


# ---------------------------------------------------------------------------
# 연산의 목록
# ---------------------------------------------------------------------------

def test_the_manifest_is_a_list_of_tool_definitions():
    tools = ops.tools()
    assert [t["name"] for t in tools] == ["pack_new", "pack_check", "pack_show", "pack_choices", "pack_build", "pack_run"]
    allowed = {"type", "properties", "required", "additionalProperties", "description", "items", "enum"}

    def walk(schema):
        assert set(schema) <= allowed, schema                # 수의 범위 같은 조건은 스키마에 두지 않고 연산이 본다
        for sub in schema.get("properties", {}).values():
            assert sub.get("description"), sub               # 입력마다 설명이 있다
            walk(sub)
        if "items" in schema:
            walk(schema["items"])

    for t in tools:
        assert set(t) == {"name", "description", "input_schema"}
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", t["name"])
        assert len(t["description"]) > 40
        s = t["input_schema"]
        jsonschema.Draft202012Validator.check_schema(s)
        assert s["type"] == "object" and s["additionalProperties"] is False and set(s["required"]) <= set(s["properties"])
        walk(s)
    m = ops.manifest()
    jsonschema.Draft202012Validator.check_schema(m["envelope"])
    assert m["version"] == ops.VERSION == "1.0"
    assert [o["name"] for o in m["operations"]] == [t["name"] for t in tools]
    assert {o["name"] for o in m["operations"] if o["writes"]} == {"pack_new", "pack_check"}
    assert json.loads(json.dumps(m, ensure_ascii=False)) == m


def test_the_input_check_agrees_with_json_schema():
    """ops.problems 는 JSON Schema 의 작은 부분만 안다. 그 부분에서 jsonschema 와 같은 판정을 낸다."""
    rng = random.Random(7)
    pool = ["x", "", "lab", 0, 1, -1, 7, 3.5, True, False, None, [], ["devs"], ["nope"], [1], ["devs", "pyevsim"], {}, {"a": 1}]
    agreed = {"valid": 0, "invalid": 0}
    for op in ops.OPERATIONS.values():
        validator = jsonschema.Draft202012Validator(op.input_schema)
        keys = list(op.input_schema["properties"]) + ["extra"]
        for _ in range(600):
            args = {k: rng.choice(pool) for k in keys if rng.random() < 0.5}
            if rng.random() < 0.3:                           # 맞는 입력이 드물지 않게 한다
                args = {"dir": "lab", **{k: v for k, v in args.items() if k in ("dir",)}}
            valid = validator.is_valid(args)
            assert (ops.problems(op.input_schema, args) == []) == valid, (op.name, args)
            agreed["valid" if valid else "invalid"] += 1
    for bad in (None, [], "x", 3):                           # 표가 아닌 입력
        assert ops.problems(ops.OPERATIONS["pack_show"].input_schema, bad)
    assert agreed["valid"] > 300 and agreed["invalid"] > 2000, agreed
    assert ops.problems({"type": "number"}, float("nan")) and ops.problems({"type": "number"}, float("inf"))


# ---------------------------------------------------------------------------
# 연산마다: 사람이 쓰는 명령과 같은 답
# ---------------------------------------------------------------------------

def test_a_new_pack_and_its_check(lab):
    made = os.path.join(lab, "lab")
    env = call("pack_check", {"dir": "lab"}, root=lab)
    assert env["ok"] and env["output"] == ""
    r = env["result"]
    assert r["name"] == "lab" and r["errors"] == 0 and r["family"] == {"variants": {"value": 2, "text": "2"},
                                                                         "wellformed": {"value": 2, "text": "2"}}
    report = P.check(made)                                   # 사람이 쓰는 검사와 같은 것을 낸다
    assert {n: (c["events"], c["digest"]) for n, c in r["cases"].items()} == \
        {n: (c["events"], c["digest"]) for n, c in report.cases.items()} == {"fast": (19, "253f991d865d276f"),
                                                                              "slow": (16, "a1eec6a2077ace65")}
    assert all(c["built"] and c["executors"]["devs"] == "reference" for c in r["cases"].values())
    assert {c["executors"]["pyevsim"] for c in r["cases"].values()} <= {"same", "skipped"}
    assert [f["code"] for f in env["findings"]] == [f.code for f in report.findings]

    again = call("pack_new", {"dir": "lab"}, root=lab)       # 비어 있지 않은 곳에는 만들지 않는다
    assert codes(again) == {"P0"} and "비어 있지 않다" in said(again)
    bad = call("pack_new", {"dir": "new", "name": "not a name"}, root=lab)
    assert codes(bad) == {"P0"} and not os.path.exists(os.path.join(lab, "new", "pack.yaml"))


def test_show_lists_what_is_in_the_pack(lab):
    r = call("pack_show", {"dir": "lab"}, root=lab)["result"]
    assert r["name"] == "lab" and r["document"] == "lab.ses.yaml" and r["binding"] == "binding.yaml"
    assert r["model_base"] == {"file": "model_base.py", "library": "LIBRARY", "functions": None, "native": []}
    assert [(c["name"], c["decisions"], c["until"], c["recorded"]["digest"]) for c in r["cases"]] == [
        ("fast", "cases/fast.decisions.yaml", 20.0, "253f991d865d276f"),
        ("slow", "cases/slow.decisions.yaml", 20.0, "a1eec6a2077ace65")]
    assert set(r["files"]) == {"pack.yaml", "lab.ses.yaml", "model_base.py", "binding.yaml", "records.yaml",
                               os.path.join("cases", "fast.decisions.yaml"), os.path.join("cases", "slow.decisions.yaml")}
    assert r["files_truncated"] is False


def test_choices_narrow_with_the_decisions(lab):
    r = call("pack_choices", {"dir": "lab"}, root=lab)["result"]
    assert r["variants"] == {"value": 2, "text": "2"}
    assert r["points"] == [{"owner": "Worker", "kind": "alternative", "group": "speed", "state": "open",
                            "remaining": ["Fast", "Slow"], "options": ["Fast", "Slow"]}]
    for given in ({"case": "slow"}, {"decisions": "cases/slow.decisions.yaml"}):
        r = call("pack_choices", {"dir": "lab", **given}, root=lab)["result"]
        assert r["variants"]["value"] == 1 and r["points"][0]["state"] == "decided" and r["points"][0]["remaining"] == ["Slow"]
    out = io.StringIO()                                      # 명령 ses choices 와 같은 수
    assert cli.main(["choices", os.path.join(lab, "lab", "lab.ses.yaml")], out) == 0 and "남은 변이 2개" in out.getvalue()


def test_build_gives_the_structure_of_one_variant(lab):
    r = call("pack_build", {"dir": "lab", "case": "slow"}, root=lab)["result"]
    assert (r["components"], r["nodes"], r["truncated"], r["variables"]) == (4, 7, False, {})
    assert r["tree"]["name"] == "Line" and [(p["name"], p["labels"]) for p in r["tree"]["parts"]] == [
        ("Source", ["Source"]), ("Worker", ["Worker", "Slow"]), ("Sink", ["Sink"])]
    assert [p["attributes"] for p in r["tree"]["parts"]] == [{"period": 2.0}, {"service": 3.0}, {}]     # 속성의 값도 낸다
    assert re.fullmatch(r"[0-9a-f]{16}", r["structure"])
    fast = call("pack_build", {"dir": "lab", "case": "fast"}, root=lab)["result"]
    assert fast["structure"] != r["structure"] and fast["tree"]["parts"][1]["attributes"] == {"service": 1.0}
    shallow = call("pack_build", {"dir": "lab", "case": "slow", "depth": 0}, root=lab)["result"]
    assert shallow["tree"]["parts"] == [] and shallow["tree"]["parts_not_listed"] == 3 and shallow["truncated"] is True
    assert shallow["components"] == 4                        # 잘라 보여도 수는 전체의 것이다
    few = call("pack_build", {"dir": "lab", "case": "slow", "limit": 2}, root=lab)["result"]
    assert [p["name"] for p in few["tree"]["parts"]] == ["Source"] and few["tree"]["parts_not_listed"] == 2

    env = call("pack_build", {"dir": "lab"}, root=lab)       # 결정이 모자라면 무엇이 남았는지 알린다
    assert codes(env) == {"P4"} and env["result"] is None
    assert "결정이 모자라다" in said(env) and "['Fast', 'Slow']" in said(env)


def test_run_gives_the_events_in_pages(lab):
    whole = call("pack_run", {"dir": "lab", "case": "fast", "limit": 1000}, root=lab)["result"]
    assert (whole["events"], whole["last"], whole["digest"], whole["atoms"], whole["until"]) == \
        (19, 20.0, "253f991d865d276f", 3, 20.0)
    assert len(whole["log"]) == 19 and whole["truncated"] is False
    assert whole["log"][0] == {"t": 2.0, "at": "Source", "port": "out", "value": {"id": 0}}
    pages, offset = [], 0
    while True:
        r = call("pack_run", {"dir": "lab", "case": "fast", "limit": 7, "offset": offset}, root=lab)["result"]
        pages += r["log"]
        offset += len(r["log"])
        if not r["truncated"]:
            break
    assert pages == whole["log"] and offset == 19            # 나눠 읽은 것을 이으면 전체다
    log, _, _ = P.run(os.path.join(lab, "lab"), "fast")
    assert [(e["t"], e["at"], e["port"], e["value"]) for e in whole["log"]] == [(t, "/".join(p), port, v) for t, p, port, v in log]
    short = call("pack_run", {"dir": "lab", "case": "fast", "until": 5, "limit": 0}, root=lab)["result"]
    assert (short["events"], short["log"], short["truncated"], short["until"]) == (4, [], True, 5)


@pytest.mark.parametrize("name", sorted(os.listdir(PACKS)))
def test_the_packs_of_the_repository(name, tmp_path):
    shutil.copytree(os.path.join(PACKS, name), tmp_path / name)
    before = snapshot(tmp_path)
    env = call("pack_check", {"dir": name, "executors": ["devs"]}, root=str(tmp_path))
    assert env["ok"], said(env)
    report = P.check(str(tmp_path / name), executors=("devs",))
    assert env["result"]["family"]["variants"]["value"] == report.family[0]
    assert {n: c.get("digest") for n, c in env["result"]["cases"].items()} == {n: c.get("digest") for n, c in report.cases.items()}
    show = call("pack_show", {"dir": name}, root=str(tmp_path))["result"]
    for case in show["cases"]:
        r = call("pack_choices", {"dir": name, "case": case["name"]}, root=str(tmp_path))["result"]
        assert r["variants"]["value"] == 1 and all(p["state"] == "decided" for p in r["points"])
        b = call("pack_build", {"dir": name, "case": case["name"], "depth": 1}, root=str(tmp_path))["result"]
        assert b["components"] >= env["result"]["cases"][case["name"]]["atoms"]
    assert snapshot(tmp_path) == before                      # 읽기만 하는 연산은 아무것도 남기지 않는다


def test_the_large_case_is_answered_and_cut_to_size(tmp_path):
    shutil.copytree(os.path.join(PACKS, "wsn"), tmp_path / "wsn")
    r = call("pack_choices", {"dir": "wsn"}, root=str(tmp_path))["result"]
    assert r["variants"] == {"value": 9000, "text": "9000"} and r["wellformed"]["value"] == 9000
    count = next(p for p in r["points"] if p["kind"] == "count")
    assert len(count["options"]) == 1000 and count["state"] == "open"
    b = call("pack_build", {"dir": "wsn", "case": "field_1000"}, root=str(tmp_path))["result"]
    assert b["components"] > 1000 and b["truncated"] is True

    def listed(node) -> int:
        return 1 + sum(listed(p) for p in node["parts"])

    assert listed(b["tree"]) == 200                          # 기본 한도
    env = call("pack_build", {"dir": "wsn", "case": "field_1000", "limit": 5000}, root=str(tmp_path))
    assert codes(env) == {"A0"} and "limit" in said(env)


# ---------------------------------------------------------------------------
# 잘못은 줄이 된다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,args,code,word", [
    ("nothing", {}, "A1", "그런 연산이 없다"),
    ("pack.check", {"dir": "lab"}, "A1", "pack_check"),
    ("pack_check", {}, "A0", "dir 가 없다"),
    ("pack_check", {"dir": "lab", "recrod": True}, "A0", "모르는 항목 recrod"),
    ("pack_check", {"dir": 3}, "A0", "string 여야 한다"),
    ("pack_check", {"dir": "lab", "record": "yes"}, "A0", "boolean 여야 한다"),
    ("pack_check", {"dir": "lab", "executors": ["spice"]}, "A0", "가운데 하나여야 한다"),
    ("pack_check", {"dir": "lab", "executors": "devs"}, "A0", "목록이어야 한다"),
    ("pack_check", {"dir": "nowhere"}, "A0", "디렉터리 nowhere 가 없다"),
    ("pack_check", {"dir": ".."}, "A0", "작업 자리 밖이다"),
    ("pack_check", {"dir": "lab/../.."}, "A0", "작업 자리 밖이다"),
    ("pack_check", {"dir": "/"}, "A0", "작업 자리 밖이다"),
    ("pack_new", {"dir": "../escaped"}, "A0", "작업 자리 밖이다"),
    ("pack_show", {"dir": "."}, "P0", "pack.yaml 가 없다"),
    ("pack_choices", {"dir": "lab", "case": "fast", "decisions": "cases/fast.decisions.yaml"}, "A0", "하나만 준다"),
    ("pack_choices", {"dir": "lab", "case": "medium"}, "A0", "있는 사례는 ['fast', 'slow']"),
    ("pack_choices", {"dir": "lab", "decisions": "../lab/cases/fast.decisions.yaml"}, "A0", "묶음 밖을 가리킨다"),
    ("pack_choices", {"dir": "lab", "decisions": "cases/none.yaml"}, "A0", "가 없다"),
    ("pack_build", {"dir": "lab", "case": "fast", "limit": 0}, "A0", "limit 은 1 이상"),
    ("pack_build", {"dir": "lab", "case": "fast", "depth": -1}, "A0", "depth 는 0 이상"),
    ("pack_build", {"dir": "lab", "case": "fast", "depth": True}, "A0", "integer 여야 한다"),
    ("pack_run", {"dir": "lab"}, "A0", "case 가 없다"),
    ("pack_run", {"dir": "lab", "case": "medium"}, "A0", "있는 사례는"),
    ("pack_run", {"dir": "lab", "case": "fast", "until": -1}, "A0", "until 은 0 이상"),
    ("pack_run", {"dir": "lab", "case": "fast", "limit": 1001}, "A0", "limit 은 0 이상 1000 이하"),
    ("pack_run", {"dir": "lab", "case": "fast", "offset": -1}, "A0", "offset 은 0 이상"),
    ("pack_run", {"dir": "lab", "case": "fast", "until": float("inf")}, "A0", "유한한 수"),
])
def test_wrong_input_is_reported_not_raised(lab, name, args, code, word):
    before = snapshot(lab)
    env = ops.call(name, args, root=lab)
    ENVELOPE.validate(env)
    assert not env["ok"] and env["result"] is None and codes(env) == {code}, env
    assert word in said(env), said(env)
    assert snapshot(lab) == before                           # 틀린 입력은 아무것도 바꾸지 않는다
    assert not os.path.exists(os.path.join(os.path.dirname(lab), "escaped"))


def test_what_is_not_a_table_is_wrong_input(lab):
    for args in ([], "dir", 3, [{"dir": "lab"}]):
        env = ops.call("pack_show", args, root=lab)
        assert codes(env) == {"A0"} and "이름과 값의 표여야 한다" in said(env)
    assert codes(ops.call(None, {}, root=lab)) == {"A1"} and codes(ops.call(["pack_show"], {}, root=lab)) == {"A1"}


def test_a_link_out_of_the_working_place_is_refused(lab, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    call("pack_new", {"dir": "other"}, root=str(outside))
    os.symlink(os.path.join(str(outside), "other"), os.path.join(lab, "linked"))
    env = call("pack_check", {"dir": "linked"}, root=lab)
    assert codes(env) == {"A0"} and "작업 자리 밖이다" in said(env)


@pytest.mark.parametrize("file,old,new,op,args,code,word", [
    ("pack.yaml", 'pack: "1.0"', 'pack: "9"', "pack_check", {}, "P0", "첫 항목은"),
    ("pack.yaml", 'pack: "1.0"', 'pack: "9"', "pack_run", {"case": "fast"}, "P0", "첫 항목은"),
    ("lab.ses.yaml", "default: 1.0", "value: 1.0", "pack_choices", {}, "P1", "모르는 항목 value"),
    ("lab.ses.yaml", "default: 1.0", "value: 1.0", "pack_build", {"case": "fast"}, "P1", "모르는 항목 value"),
    ("lab.ses.yaml", "default: 1.0", "value: 1.0", "pack_run", {"case": "fast"}, "P1", "모르는 항목 value"),
    ("model_base.py", "class Sink(Atomic):", "class Sink(Atomic:", "pack_check", {}, "P2", "SyntaxError"),
    ("model_base.py", "class Sink(Atomic):", "class Sink(Atomic:", "pack_run", {"case": "fast"}, "P2", "SyntaxError"),
    ("binding.yaml", "Sink: {module: Sink}", "Sink: {module: Drain}", "pack_check", {}, "P3", "라이브러리에 없다"),
    ("cases/fast.decisions.yaml", "alternative: Fast", "alternative: Faster", "pack_choices", {"case": "fast"}, "P4",
     "남기려는 선택지가 대상에 없다"),
    ("cases/fast.decisions.yaml", "alternative: Fast", "alternative: Faster", "pack_build", {"case": "fast"}, "P4", "Faster"),
    ("cases/fast.decisions.yaml", "alternative: Fast", "alternative: Faster", "pack_run", {"case": "fast"}, "P4", "Faster"),
    ("cases/fast.decisions.yaml", "target: Line", "target: Other", "pack_choices", {"case": "fast"}, "P4", "target 이 Other"),
    ("cases/fast.decisions.yaml", "{at: Worker, specialization: speed, alternative: Fast}",
     "{node: [Line, flow, Worker], specialization: speed, alternative: Fast}", "pack_choices", {"case": "fast"}, "A2", "node"),
    ("binding.yaml", "  Sink: {module: Sink}\n", "", "pack_run", {"case": "fast"}, "P5", "실행 가능하지 않다"),
    ("model_base.py", "self.received += [", "self.gone += [", "pack_run", {"case": "fast"}, "P6", "AttributeError"),
])
def test_a_broken_pack_is_reported_with_the_code_of_the_place(lab, file, old, new, op, args, code, word):
    edit(os.path.join(lab, "lab", file), old, new)
    before = snapshot(lab)
    env = call(op, {"dir": "lab", **args}, root=lab)
    assert code in codes(env) and word in said(env), env
    assert not env["ok"]
    assert snapshot(lab) == before


def test_the_code_of_the_pack_cannot_break_the_envelope(lab):
    path = os.path.join(lab, "lab", "model_base.py")
    with open(path, encoding="utf-8") as f:
        original = f.read()
    with open(path, "w", encoding="utf-8") as f:             # 묶음의 코드가 찍는 것은 output 에 든다
        f.write(original + '\nprint("실을 때 찍는 글")\n')
    env = call("pack_run", {"dir": "lab", "case": "fast", "limit": 1}, root=lab)
    assert env["ok"] and "실을 때 찍는 글" in env["output"]
    out = io.StringIO()                                      # 명령은 봉투를 마지막 줄에 한 줄로 낸다
    assert cli.main(["call", "pack_run", "--args", '{"dir": "lab", "case": "fast", "limit": 1}', "--root", lab], out) == 0
    assert json.loads(out.getvalue().splitlines()[-1]) == env and len(out.getvalue().splitlines()) == 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(original + '\nprint("x" * 9000)\n')
    env = call("pack_show", {"dir": "lab"}, root=lab)        # 아무것도 돌리지 않는 연산은 찍힌 것이 없다
    assert env["output"] == ""
    env = call("pack_check", {"dir": "lab", "executors": ["devs"]}, root=lab)
    assert env["ok"] and env["output"].startswith("(앞은 잘렸다) ") and len(env["output"]) < ops.OUTPUT_LIMIT + 20

    with open(path, "w", encoding="utf-8") as f:             # 프로세스를 끝내려 해도 줄이 된다
        f.write(original + "\nraise SystemExit(3)\n")
    for op, args in (("pack_check", {}), ("pack_run", {"case": "fast"})):
        env = call(op, {"dir": "lab", **args}, root=lab)
        assert codes(env) == {"P2"} and "SystemExit" in said(env)

    with open(path, "w", encoding="utf-8") as f:             # JSON 으로 옮길 수 없는 값을 내도 봉투는 JSON 이다
        f.write(original.replace('{"out": [{"id": self.count}]}', '{"out": [{"id": self.count, "at": float("inf"), "who": self}]}'))
    env = call("pack_run", {"dir": "lab", "case": "fast", "limit": 1}, root=lab)
    value = env["result"]["log"][0]["value"]
    assert value["at"] == "INF" and isinstance(value["who"], str)


def test_a_fault_of_the_tool_is_a_finding_too(lab, monkeypatch):
    def boom(root, args):
        raise ZeroDivisionError("안에서 난 일")

    monkeypatch.setitem(ops.OPERATIONS, "pack_show", dataclasses.replace(ops.OPERATIONS["pack_show"], run=boom))
    env = call("pack_show", {"dir": "lab"}, root=lab)
    assert codes(env) == {"A9"} and "ZeroDivisionError: 안에서 난 일" in said(env) and env["result"] is None


def test_a_helper_file_of_a_pack_is_read_again_and_does_not_leak(lab):
    """묶음 안의 보조 파일. 고치면 고친 것이 읽히고, 다른 묶음의 같은 이름의 파일과 섞이지 않는다."""
    call("pack_new", {"dir": "second"}, root=lab)
    for name, base in (("lab", 100), ("second", 200)):
        with open(os.path.join(lab, name, "helper.py"), "w", encoding="utf-8") as f:
            f.write(f"BASE = {base}\n")
        edit(os.path.join(lab, name, "model_base.py"), '{"out": [{"id": self.count}]}', '{"out": [{"id": self.count + helper.BASE}]}')
        edit(os.path.join(lab, name, "model_base.py"), "from ses_core.devs import", "import helper\nfrom ses_core.devs import")

    def first(name) -> int:
        return call("pack_run", {"dir": name, "case": "fast", "limit": 1}, root=lab)["result"]["log"][0]["value"]["id"]

    assert [first("lab"), first("second"), first("lab")] == [100, 200, 100]      # 묶음마다 자기 보조 파일
    assert "helper" not in sys.modules
    with open(os.path.join(lab, "lab", "helper.py"), "w", encoding="utf-8") as f:
        f.write("BASE = 300\n")
    assert first("lab") == 300                               # 고친 것이 읽힌다
    assert not [n for n in snapshot(lab) if "__pycache__" in n]


# ---------------------------------------------------------------------------
# 쓰는 연산과 쓰지 않는 연산
# ---------------------------------------------------------------------------

def test_only_a_recording_check_writes(lab):
    edit(os.path.join(lab, "lab", "lab.ses.yaml"), "default: 1.0", "default: 1.5")     # 빠른 처리기를 조금 느리게
    edit(os.path.join(lab, "lab", "binding.yaml"), "time_unit: 1.0", "time_unit: 0.5")
    before = snapshot(lab)
    env = call("pack_check", {"dir": "lab", "executors": ["devs"]}, root=lab)
    assert codes(env) == {"P6"} and "기록이 적어 둔 것과 다르다" in said(env)
    for op, args in (("pack_show", {}), ("pack_choices", {"case": "fast"}), ("pack_build", {"case": "fast"}),
                     ("pack_run", {"case": "fast"})):
        assert call(op, {"dir": "lab", **args}, root=lab)["ok"]
    assert snapshot(lab) == before
    env = call("pack_check", {"dir": "lab", "record": True, "executors": ["devs"]}, root=lab)
    after = snapshot(lab)
    assert env["ok"] and {n for n in after if after[n] != before.get(n)} == {os.path.join("lab", "records.yaml")}
    assert call("pack_check", {"dir": "lab", "executors": ["devs"]}, root=lab)["ok"]


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------

def run_cli(*argv) -> tuple:
    out = io.StringIO()
    code = cli.main([str(a) for a in argv], out)
    return code, out.getvalue()


def test_the_commands(lab, tmp_path, monkeypatch):
    code, text = run_cli("ops")
    assert code == 0 and json.loads(text) == ops.manifest()
    code, text = run_cli("ops", "--tools")
    assert code == 0 and json.loads(text) == ops.tools()

    code, text = run_cli("call", "pack_choices", "--args", '{"dir": "lab", "case": "slow"}', "--root", lab)
    assert code == 0 and json.loads(text) == ops.call("pack_choices", {"dir": "lab", "case": "slow"}, root=lab)
    assert len(text.splitlines()) == 1
    code, text = run_cli("call", "pack_choices", "--args", '{"dir": "lab"}', "--root", lab, "--pretty")
    assert code == 0 and len(text.splitlines()) > 5 and json.loads(text)["result"]["variants"]["value"] == 2

    args = tmp_path / "args.json"
    args.write_text('{"dir": "lab", "case": "fast", "limit": 2}', encoding="utf-8")
    code, text = run_cli("call", "pack_run", "--args-file", args, "--root", lab)
    assert code == 0 and len(json.loads(text)["result"]["log"]) == 2
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"dir": "lab"}'))
    code, text = run_cli("call", "pack_show", "--args-file", "-", "--root", lab)
    assert code == 0 and json.loads(text)["result"]["name"] == "lab"

    monkeypatch.chdir(lab)                                   # root 를 주지 않으면 지금 디렉터리가 작업 자리다
    code, text = run_cli("call", "pack_show", "--args", '{"dir": "lab"}')
    assert code == 0 and json.loads(text)["ok"]

    for argv, word in ((("call", "pack_show", "--args", "{bad"), "입력이 JSON 이 아니다"),
                       (("call", "pack_show"), "dir 가 없다"),
                       (("call", "nothing"), "그런 연산이 없다"),
                       (("call", "pack_build", "--args", '{"dir": "lab"}'), "결정이 모자라다")):
        code, text = run_cli(*argv)
        env = json.loads(text)
        ENVELOPE.validate(env)
        assert code == 1 and not env["ok"] and word in said(env)
    code, text = run_cli("call", "pack_show", "--args", "{}", "--args-file", args)
    assert code == 2 and "하나만 준다" in text
    code, text = run_cli("call", "pack_show", "--args-file", tmp_path / "none.json")
    assert code == 2 and "입력 파일을 읽을 수 없다" in text


def test_the_document_says_what_the_code_does():
    """21 문서의 표가 코드와 어긋나지 않는가. 연산의 이름, 부호, 한도, 실행기의 상태."""
    with open(os.path.join(ROOT, "docs", "ses-platform", "21_agent_operations.md"), encoding="utf-8") as f:
        text = f.read()
    for name, op in ops.OPERATIONS.items():
        assert text.count(f"| `{name}` |") == 2, name          # 연산의 표와 결과의 표
        for key in op.input_schema["properties"]:
            assert f"`{key}`" in text, (name, key)
    for code in ("A0", "A1", "A2", "A9", "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"):
        assert f"| {code} |" in text
    for status in ops.EXECUTOR_STATUS.values():
        assert status in text
    for limit in (ops.COMPONENTS_LIMIT, ops.LOG_LIMIT, ops.MAX_ASSIGNMENTS, ops.OUTPUT_LIMIT):
        assert f"{limit:,}" in text, limit
    assert f"| `pack_show`가 늘어놓는 파일의 수 | {ops.FILES_LIMIT} |" in text
    assert f'"version": "{ops.VERSION}"' in text
    for key in ops.ENVELOPE["properties"]:
        assert f"| `{key}` |" in text


def test_the_tests_called_the_operations():
    """위의 시험들이 실제로 연산을 불렀는가. 이 파일만 돌렸을 때를 기준으로 한다."""
    if STATS["calls"]:
        assert STATS["calls"] > 60 and STATS["failed"] > 20, STATS
