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
STATS = {"calls": 0, "failed": 0, "kinds": set()}


def call(name, args=None, root=None) -> dict:
    """연산을 부르고, 결과가 봉투의 모양이며 JSON 으로 오가는지 본다."""
    env = ops.call(name, args, root=root)
    ENVELOPE.validate(env)
    assert json.loads(json.dumps(env, ensure_ascii=False, allow_nan=False)) == env
    assert env["ok"] == (not any(f["severity"] == "error" for f in env["findings"]))
    for f in env["findings"]:                                # 종류가 있는 줄은 그다음에 할 일을 싣는다
        if "kind" in f:
            assert f["kind"] in ops.NEXT and f["next"] == ops.NEXT[f["kind"]] and isinstance(f["data"], dict), f
            STATS["kinds"].add(f["kind"])
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
    assert [t["name"] for t in tools] == ["pack_new", "pack_check", "pack_show", "pack_choices", "pack_build", "pack_run", "formats"]
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
    two = {"value": 2, "text": "2", "exact": True}
    assert r["name"] == "lab" and r["errors"] == 0 and r["family"] == {"variants": two, "wellformed": two, "scope": "full"}
    report = P.check(made)                                   # 사람이 쓰는 검사와 같은 것을 낸다
    assert {n: (c["events"], c["digest"]) for n, c in r["cases"].items()} == \
        {n: (c["events"], c["digest"]) for n, c in report.cases.items()} == {"fast": (19, "253f991d865d276f"),
                                                                              "slow": (16, "a1eec6a2077ace65")}
    assert all(c["built"] and c["executors"]["devs"] == "reference" for c in r["cases"].values())
    assert {c["executors"]["pyevsim"] for c in r["cases"].values()} <= {"same", "skipped"}
    assert [f["code"] for f in env["findings"]] == [f.code for f in report.findings]

    again = call("pack_new", {"dir": "lab"}, root=lab)       # 비어 있지 않은 곳에는 만들지 않는다
    assert codes(again) == {"A0"} and "비어 있지 않다" in said(again)        # 틀린 것은 입력이다. 묶음이 아니다
    bad = call("pack_new", {"dir": "new", "name": "not a name"}, root=lab)
    assert codes(bad) == {"A0"} and bad["findings"][0]["where"] == "name" and not os.path.exists(os.path.join(lab, "new"))
    with open(os.path.join(lab, "afile"), "w", encoding="utf-8") as f:
        f.write("x")
    assert "디렉터리가 아니다" in said(call("pack_new", {"dir": "afile"}, root=lab))
    long = call("pack_new", {"dir": "long", "name": "a" * 300}, root=lab)
    assert codes(long) == {"A0"} and not os.path.exists(os.path.join(lab, "long"))
    assert call("pack_new", {"dir": "long", "name": "long"}, root=lab)["ok"]         # 실패한 뒤에 다시 만들 수 있다


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
    assert r["variants"] == {"value": 2, "text": "2", "exact": True} and r["core_wellformed"]["value"] == 2
    assert r["points"] == [{"owner": "Worker", "kind": "alternative", "group": "speed", "state": "open",
                            "remaining": ["Fast", "Slow"], "remaining_count": 2, "options": ["Fast", "Slow"], "options_count": 2}]
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
    assert r["variants"] == {"value": 9000, "text": "9000", "exact": True} and r["core_wellformed"]["value"] == 9000
    count = next(p for p in r["points"] if p["kind"] == "count")
    assert count["options_count"] == count["remaining_count"] == 1000 and count["state"] == "open"
    assert len(count["options"]) == ops.OPTIONS_LIMIT and count["truncated"] is True     # 늘어놓는 것은 한도까지다
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
    ("pack_check", {"dir": "lab", "recrod": True}, "A0", "모르는 항목 'recrod'"),
    ("pack_check", {"dir": 3}, "A0", "string 여야 한다"),
    ("pack_check", {"dir": "lab", "record": "yes"}, "A0", "boolean 여야 한다"),
    ("pack_check", {"dir": "lab", "executors": ["spice"]}, "A0", "가운데 하나여야 한다"),
    ("pack_check", {"dir": "lab", "executors": "devs"}, "A0", "목록이어야 한다"),
    ("pack_check", {"dir": "nowhere"}, "A0", "디렉터리 'nowhere' 가 없다"),
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
    ("pack_run", {"dir": "lab"}, "A0", "돌릴 것을 case 나 decisions 로 준다"),
    ("pack_run", {"dir": "lab", "case": "fast", "decisions": "cases/fast.decisions.yaml"}, "A0", "하나만 준다"),
    ("pack_run", {"dir": "lab", "decisions": "cases/fast.decisions.yaml"}, "A0", "돌릴 시각이 없다"),
    ("pack_run", {"dir": "lab", "decisions": "../lab/cases/fast.decisions.yaml", "until": 5}, "A0", "묶음 밖을 가리킨다"),
    ("pack_run", {"dir": "lab", "case": "medium"}, "A0", "있는 사례는"),
    ("pack_run", {"dir": "lab", "case": "fast", "until": -1}, "A0", "until 은 0 이상"),
    ("pack_run", {"dir": "lab", "case": "fast", "limit": 1001}, "A0", "limit 은 0 이상 1000 이하"),
    ("pack_run", {"dir": "lab", "case": "fast", "offset": -1}, "A0", "offset 은 0 이상"),
    ("pack_run", {"dir": "lab", "case": "fast", "until": float("inf")}, "A0", "유한한 수"),
    ("pack_run", {"dir": "lab", "case": "fast", "until": 10 ** 400}, "A0", "유한한 수"),
    ("pack_run", {"dir": "lab", "case": "fast", "limit": 10 ** 5000}, "A0", "limit 은 0 이상 1000 이하"),
    ("pack_show", {"dir": "\ud800"}, "A0", "글자로 옮길 수 없는 것"),
    ("pack_choices", {"dir": "lab", "decisions": "cases/\udfff.yaml"}, "A0", "글자로 옮길 수 없는 것"),
    ("pack_new", {"dir": "new", "name": "x\ud800"}, "A0", "글자로 옮길 수 없는 것"),
    ("pack_show", {"dir": "la\x00b"}, "A0", "상대 경로를 글로 적는다"),
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


def test_a_helper_file_of_a_pack_is_read_again_and_does_not_leak(lab, monkeypatch):
    """묶음 안의 보조 파일. 고치면 고친 것이 읽히고, 다른 묶음의 같은 이름의 파일과 섞이지 않는다."""
    monkeypatch.setattr(sys, "dont_write_bytecode", False)   # 바이트코드를 쓰는 환경에서도 묶음에 남기지 않는다는 것을 본다
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
    assert code == 1 and "하나만 준다" in said(json.loads(text)) and codes(json.loads(text)) == {"A0"}
    code, text = run_cli("call", "pack_show", "--args-file", tmp_path / "none.json")
    assert code == 1 and "입력 파일을 읽을 수 없다" in said(json.loads(text))


# ---------------------------------------------------------------------------
# 에이전트에게 맡겨 본 검토에서 나온 것 (21 문서의 8절)
# ---------------------------------------------------------------------------

def test_a_line_says_what_kind_it_is_and_what_to_do_next(lab):
    """같은 부호 안에서 할 일이 다른 것은 kind 로 가른다. 자료는 data 에 있다. 글을 읽지 않고도 고칠 곳을 안다."""
    root = os.path.join(lab, "lab")

    def kinds(env) -> dict:
        """종류마다 첫 오류."""
        out: dict = {}
        for f in env["findings"]:
            if f["severity"] == "error":
                out.setdefault(f["kind"], f)
        return out

    edit(os.path.join(root, "cases/fast.decisions.yaml"), "  - {at: Worker, specialization: speed, alternative: Fast}\n", "")
    found = kinds(call("pack_build", {"dir": "lab", "case": "fast"}, root=lab))
    assert found["undecided"]["data"] == {"at": ["Line", "Worker"], "choice": "alternative", "group": "speed",
                                          "options": ["Fast", "Slow"]}
    assert found["undecided"]["code"] == "P4" and "결정 집합에 결정을 더한다" in found["undecided"]["next"]
    shutil.rmtree(root)
    call("pack_new", {"dir": "lab"}, root=lab)

    edit(os.path.join(root, "model_base.py"), "self.received += [", "self.gone += [")
    found = kinds(call("pack_check", {"dir": "lab"}, root=lab))
    data = found["model_error"]["data"]
    assert (data["component"], data["function"], data["time"], data["file"], data["line"]) == (
        "Sink", "external", 3.0, "model_base.py", 76) and data["exception"] == "AttributeError"
    assert found["model_error"]["code"] == "P6" and found["model_error"]["where"] == "fast"
    shutil.rmtree(root)
    call("pack_new", {"dir": "lab"}, root=lab)

    edit(os.path.join(root, "lab.ses.yaml"), "service: {type: float, default: 1.0, doc: 작업 하나를 처리하는 시간}",
         "service: {type: float, default: 2.0}")
    env = call("pack_check", {"dir": "lab"}, root=lab)
    found = kinds(env)
    data = found["record_differs"]["data"]
    assert data["recorded"]["digest"] == "253f991d865d276f" and data["now"]["digest"] != data["recorded"]["digest"]
    assert "뜻하지 않은 변화이면 원인을 고친다" in found["record_differs"]["next"]
    assert env["result"]["cases"]["fast"]["ran"] and env["result"]["cases"]["fast"]["built"]
    shutil.rmtree(root)
    call("pack_new", {"dir": "lab"}, root=lab)

    edit(os.path.join(root, "binding.yaml"), "Sink: {module: Sink}", "Sink: {module: Drain}")
    found = kinds(call("pack_check", {"dir": "lab"}, root=lab))
    assert found["unknown_module"]["data"]["modules"] == ["Sink", "Source", "Worker"]
    assert set(ops.manifest()["kinds"]) == set(ops.NEXT) and all(isinstance(v, str) and v for v in ops.NEXT.values())


def test_a_warning_of_the_model_base_does_not_stop_the_cases(lab):
    """모델 베이스의 경고 하나가 모든 사례를 건너뛰게 하면 검사는 아무것도 돌리지 않고 통과한다. 그런 일이 없어야 한다."""
    root = os.path.join(lab, "lab")
    edit(os.path.join(root, "model_base.py"), "from ses_core.devs import", "import random\nfrom ses_core.devs import")
    edit(os.path.join(root, "model_base.py"), 'return {"out": [{"id": self.count}]}',
         'return {"out": [{"id": self.count, "luck": random.random()}]}')
    env = call("pack_check", {"dir": "lab"}, root=lab)
    lint = [f for f in env["findings"] if f.get("kind") == "lint"]
    assert len(lint) == 1 and lint[0]["severity"] == "warning" and lint[0]["data"] == {"file": "model_base.py", "line": 36}
    assert all(c["ran"] for c in env["result"]["cases"].values())
    assert not env["ok"] and {f["kind"] for f in env["findings"] if f["severity"] == "error"} == {"not_reproducible"}


BOMB = "a: &a [x,x,x,x,x,x,x,x,x,x]\n" + "".join(
    f"{c}: &{c} [{','.join(['*' + p] * 10)}]\n" for p, c in zip("abcdefgh", "bcdefghi"))


@pytest.mark.parametrize("file,code,kind", [
    ("pack.yaml", "P0", "declaration"), ("lab.ses.yaml", "P1", "document_load"), ("binding.yaml", "P3", "binding_load"),
    ("cases/fast.decisions.yaml", "P4", "decisions_load"), ("records.yaml", "P6", "records_file")])
@pytest.mark.parametrize("text,word", [
    (BOMB, "별칭(&, *)이 파일을 값 1000000개 넘게 부풀린다"), ("a: &a [*a]\n", "자기 자신을 가리키는 별칭이 있다"),
    (b"\xff\xfe\x00bad", "UTF-8 로 적힌 글이 아니다"), ("a: 1\x00\n", "NUL 문자"), ("a: [1, 2\n", "YAML 문법이 틀렸다")])
def test_a_file_that_cannot_be_read_is_a_line_of_that_file(lab, file, code, kind, text, word):
    """몇 줄의 파일이 수억 개의 값으로 펼쳐지거나 자기 자신을 가리켜도 연산은 멈추지 않고, 도구의 결함(A9)으로 알리지도 않는다."""
    path = os.path.join(lab, "lab", file)
    with open(path, "wb" if isinstance(text, bytes) else "w", **({} if isinstance(text, bytes) else {"encoding": "utf-8"})) as f:
        f.write(text)
    before = snapshot(lab)
    for op, args in (("pack_check", {}), ("pack_show", {}), ("pack_choices", {"case": "fast"}),
                     ("pack_build", {"case": "fast"}), ("pack_run", {"case": "fast"})):
        env = call(op, {"dir": "lab", **args}, root=lab)
        assert "A9" not in {f["code"] for f in env["findings"]}, (op, env)
        mine = [f for f in env["findings"] if f["code"] == code and f["severity"] == "error"]
        reads = {"pack.yaml": ("pack_show", "pack_choices", "pack_build", "pack_run"),      # 그 파일을 읽는 연산들
                 "lab.ses.yaml": ("pack_choices", "pack_build", "pack_run"), "binding.yaml": ("pack_run",),
                 "cases/fast.decisions.yaml": ("pack_choices", "pack_build", "pack_run"), "records.yaml": ()}[file]
        if op == "pack_check":
            assert [f["kind"] for f in mine] == [kind] and word in mine[0]["message"] and not env["ok"], env
        elif op in reads:
            assert mine and word in mine[0]["message"] and not env["ok"], (op, env)
    assert snapshot(lab) == before
    if file == "records.yaml":                               # 깨진 기록은 다시 적으면 된다
        shown = call("pack_show", {"dir": "lab"}, root=lab)
        assert shown["ok"] and [f["kind"] for f in shown["findings"]] == ["records_file"]
        assert all(c["recorded"] is None for c in shown["result"]["cases"])
        env = call("pack_check", {"dir": "lab", "record": True}, root=lab)
        assert env["ok"] and env["result"]["recorded"] == ["fast", "slow"]
        assert call("pack_check", {"dir": "lab"}, root=lab)["ok"]


def test_a_link_inside_the_pack_is_not_followed_out_of_it(lab, tmp_path_factory):
    outside = str(tmp_path_factory.mktemp("outside"))
    root = os.path.join(lab, "lab")
    shutil.move(os.path.join(root, "model_base.py"), os.path.join(outside, "mb.py"))
    with open(os.path.join(outside, "mb.py"), "a", encoding="utf-8") as f:
        f.write('\nopen(__file__ + ".ran", "w").close()\n')          # 실리면 흔적을 남긴다
    os.symlink(os.path.join(outside, "mb.py"), os.path.join(root, "model_base.py"))
    for op, args in (("pack_check", {}), ("pack_check", {"record": True}), ("pack_run", {"case": "fast"}),
                     ("pack_build", {"case": "fast"}), ("pack_show", {})):
        env = call(op, {"dir": "lab", **args}, root=lab)
        assert codes(env) == {"P0"} and "묶음 밖의 파일로 가는 링크다" in said(env), (op, env)
    assert not os.path.exists(os.path.join(outside, "mb.py.ran"))        # 묶음 밖의 코드는 돌지 않았다
    os.remove(os.path.join(root, "model_base.py"))
    shutil.rmtree(root)
    call("pack_new", {"dir": "lab"}, root=lab)
    kept = "# 묶음 밖의 파일\n"
    with open(os.path.join(outside, "rec.yaml"), "w", encoding="utf-8") as f:
        f.write(kept)
    os.remove(os.path.join(root, "records.yaml"))
    os.symlink(os.path.join(outside, "rec.yaml"), os.path.join(root, "records.yaml"))
    env = call("pack_check", {"dir": "lab", "record": True}, root=lab)
    assert env["ok"] and env["result"]["recorded"] == ["fast", "slow"]
    with open(os.path.join(outside, "rec.yaml"), encoding="utf-8") as f:
        assert f.read() == kept                              # 링크를 따라 쓰지 않았다
    assert not os.path.islink(os.path.join(root, "records.yaml"))


def test_the_formats_and_the_full_template(tmp_path):
    """형식을 모를 때 부르는 것. 파일마다 쓸 수 있는 항목의 이름과, 그 항목들을 모두 쓰는 본보기 묶음."""
    env = call("formats", {}, root=str(tmp_path))
    r = env["result"]
    assert env["ok"] and r["templates"] == ["full", "minimal"]
    assert r["pack"]["case"] == ["decisions", "defaults", "doc", "max_steps", "name", "until"]
    assert r["decisions"]["set"] == ["at", "attribute", "path", "value"] and "variables" in r["decisions"]["keys"]
    assert r["binding"]["map"] == ["module", "params"] and "each" in r["document"]["attribute"]
    assert "cardinality" in r["document"]["multiAspect"] and "range" in r["document"]["variable"]
    assert r["model"]["base"] == "ses_core.devs.Atomic" and "time" in r["model"]["param_types"]
    assert codes(call("formats", {"dir": "x"}, root=str(tmp_path))) == {"A0"}

    env = call("pack_new", {"dir": "mylab", "template": "full"}, root=str(tmp_path))
    assert env["ok"] and env["result"]["family"] == {"variants": {"value": 78, "text": "78", "exact": True},
                                                      "wellformed": {"value": 78, "text": "78", "exact": True}, "scope": "full"}
    assert sorted(env["result"]["cases"]) == ["careful", "direct", "fast", "pair", "rush", "slow"]
    assert all(c["built"] and c["ran"] for c in env["result"]["cases"].values())
    assert "cases/pair.decisions.yaml" in env["result"]["files"] and "records.yaml" in env["result"]["files"]
    assert codes(call("pack_new", {"dir": "other", "template": "huge"}, root=str(tmp_path))) == {"A0"}
    assert not os.path.exists(os.path.join(str(tmp_path), "other"))


def test_choices_say_why_nothing_is_left_and_when_places_differ(tmp_path):
    """정의로 적은 결정(at)과 자리로 적은 결정(path)은 둘 다 적용된다. 어긋나면 어느 결정들인지를 알린다."""
    root = str(tmp_path)
    assert call("pack_new", {"dir": "mylab", "template": "full"}, root=root)["ok"]
    pair = os.path.join(root, "mylab", "cases", "pair.decisions.yaml")
    edit(pair, "  - {at: Worker, specialization: speed, alternative: Slow}\n",
         "  - {at: Worker, specialization: speed, alternative: Slow}\n"
         "  - {path: [Line, Workers, w1], specialization: speed, alternative: Fast}\n")
    env = call("pack_choices", {"dir": "mylab", "case": "pair"}, root=root)
    text = said(env)
    assert codes(env) == {"P4"} and env["findings"][0]["kind"] == "contradiction" and env["result"]["variants"]["value"] == 0
    assert "남은 변이가 없다. Line/Workers/w1: specialization speed 에 남는 대안이 없다" in text
    assert "결정 at/Worker 는 ['Slow'] 를 남긴다" in text and "결정 path/Line/Workers/w1 는 ['Fast'] 를 남긴다" in text
    assert "둘 다 적용되고 서로 덮지 않는다" in text
    assert "Line/Workers/w1: specialization speed 에 남는 대안이 없다" in said(call("pack_build", {"dir": "mylab", "case": "pair"}, root=root))
    out = io.StringIO()
    code = cli.main(["choices", os.path.join(root, "mylab", "mylab.ses.yaml"), "--decisions", pair], out)
    assert code == 1 and out.getvalue().startswith("남은 변이가 없다\n어긋난 곳: Line/Workers/w1: specialization speed 에 남는 대안이 없다")

    edit(pair, "  - {at: Worker, specialization: speed, alternative: Slow}\n",
         "  - {path: [Line, Workers, w0], specialization: speed, alternative: Slow}\n")
    env = call("pack_choices", {"dir": "mylab", "case": "pair"}, root=root)
    states = {p["owner"]: p["state"] for p in env["result"]["points"]}
    assert env["ok"] and env["result"]["variants"]["value"] == 1
    assert states == {"inspect": "decided", "workers": "decided", "Line": "decided", "Workers": "decided",
                      "Worker": "decided_per_place", "Inspector": "decided"}
    out = io.StringIO()
    assert cli.main(["choices", os.path.join(root, "mylab", "mylab.ses.yaml"), "--decisions", pair], out) == 0
    assert "Worker alternative speed: 자리마다 정해짐. 남은 선택지 ['Fast', 'Slow']" in out.getvalue()
    assert "열림" not in out.getvalue()
    built = call("pack_build", {"dir": "mylab", "case": "pair"}, root=root)
    workers = next(p for p in built["result"]["tree"]["parts"] if p["name"] == "Workers")["parts"]
    assert built["ok"] and [(w["name"], w["labels"][-1]) for w in workers] == [("w0", "Slow"), ("w1", "Fast")]


def test_build_shows_ports_couplings_and_what_the_model_gets(lab):
    """문서의 속성 값(attributes)과 모델이 실제로 받는 값(params)은 다를 수 있다. 둘 다 낸다."""
    root = os.path.join(lab, "lab")
    env = call("pack_build", {"dir": "lab", "case": "slow"}, root=lab)
    tree = env["result"]["tree"]
    parts = {p["name"]: p for p in tree["parts"]}
    assert tree["couplings"] == [{"from": "Source.out", "to": "Worker.in"}, {"from": "Worker.out", "to": "Sink.in"}]
    assert "module" not in tree and "couplings" not in parts["Worker"]
    assert parts["Worker"]["ports"] == {"in": {"type": "Job", "direction": "in", "required": True},
                                        "out": {"type": "Job", "direction": "out", "required": False}}
    assert (parts["Worker"]["module"], parts["Worker"]["params"], parts["Worker"]["attributes"]) == (
        "Worker", {"service": 3.0}, {"service": 3.0})
    assert parts["Source"]["params"] == {"period": 2.0} and parts["Sink"]["params"] == {}
    # 속성의 이름을 잘못 적으면 문서에는 값이 있고 모델에는 가지 않는다
    edit(os.path.join(root, "lab.ses.yaml"), "service: {type: float, default: 3.0}", "servce: {type: float, default: 3.0}")
    worker = {p["name"]: p for p in call("pack_build", {"dir": "lab", "case": "slow"}, root=lab)["result"]["tree"]["parts"]}["Worker"]
    assert worker["attributes"] == {"servce": 3.0} and worker["params"] == {"service": 1.0}      # 모델은 자기 기본값으로 돈다


def test_a_variant_is_run_from_a_decisions_file(lab):
    """값을 바꿔 가며 돌릴 때는 결정 집합 파일을 적고 그 파일로 돌린다. 선언에 없어도 된다. 기록은 건드리지 않는다."""
    root = os.path.join(lab, "lab")
    case = call("pack_run", {"dir": "lab", "case": "fast", "limit": 0}, root=lab)["result"]
    trial = os.path.join(root, "cases", "trial.yaml")
    with open(trial, "w", encoding="utf-8") as f:
        f.write('decisions: "1.0"\ntarget: Line\nchoose:\n  - {at: Worker, specialization: speed, alternative: Fast}\n')
    before = snapshot(lab)
    env = call("pack_run", {"dir": "lab", "decisions": "cases/trial.yaml", "until": 20, "limit": 0}, root=lab)
    assert env["ok"] and (env["result"]["digest"], env["result"]["events"]) == (case["digest"], case["events"])
    with open(trial, "a", encoding="utf-8") as f:
        f.write("set:\n  - {at: Source, attribute: period, value: 1.0}\n")
    quick = call("pack_run", {"dir": "lab", "decisions": "cases/trial.yaml", "until": 20, "limit": 1}, root=lab)
    assert quick["ok"] and quick["result"]["events"] > case["events"] and quick["result"]["log"][0]["t"] == 1.0
    with open(trial, "w", encoding="utf-8") as f:
        f.write('decisions: "1.0"\ntarget: Line\n')
    env = call("pack_run", {"dir": "lab", "decisions": "cases/trial.yaml", "until": 5}, root=lab)
    assert codes(env) == {"P4"} and env["findings"][0]["where"] == "cases/trial.yaml" and "결정이 모자라다" in said(env)
    os.remove(trial)
    assert snapshot(lab) == {k: v for k, v in before.items() if k != os.path.join("lab", "cases", "trial.yaml")}


def test_the_size_of_the_answer_is_bounded(lab):
    """줄의 수, 값의 수, 값이 겹친 깊이. 넘으면 잘랐다고 알리거나 A2 로 거부한다."""
    root = os.path.join(lab, "lab")
    edit(os.path.join(root, "cases/fast.decisions.yaml"), "choose:", "set:\n" + "".join(
        f"  - {{path: [Line, Nowhere{i}], attribute: x, value: 1}}\n" for i in range(300)) + "choose:")
    env = call("pack_build", {"dir": "lab", "case": "fast"}, root=lab)
    assert env["ok"] and len(env["findings"]) == ops.FINDINGS_LIMIT
    assert env["findings"][-1]["kind"] == "limit" and env["findings"][-1]["data"] == {"more": 101}
    shutil.rmtree(root)
    call("pack_new", {"dir": "lab"}, root=lab)

    edit(os.path.join(root, "model_base.py"), 'return {"out": [{"id": self.count}]}',
         'return {"out": [{"id": self.count, "big": list(range(300000))}]}')
    env = call("pack_run", {"dir": "lab", "case": "fast", "limit": 1}, root=lab)
    assert codes(env) == {"A2"} and env["result"] is None and "결과가 값 200000개를 넘는다" in said(env)
    edit(os.path.join(root, "model_base.py"), 'return {"out": [{"id": self.count, "big": list(range(300000))}]}',
         'v = []\n        for _ in range(150):\n            v = [v]\n        return {"out": [{"id": self.count, "deep": v}]}')
    env = call("pack_run", {"dir": "lab", "case": "fast", "limit": 1}, root=lab)
    deep, depth = env["result"]["log"][0]["value"]["deep"], 0
    while isinstance(deep, list):
        deep, depth = deep[0], depth + 1
    assert env["ok"] and deep == "(너무 깊이 겹친 값)" and depth < ops.DEPTH_LIMIT


def test_each_values_that_do_not_reach_a_replica_are_reported(tmp_path):
    """복제본마다의 값이 모자라고 default 도 없으면 그 복제본의 모델은 말없이 자기 기본값으로 돈다. 사례에서 알린다."""
    root = str(tmp_path)
    assert call("pack_new", {"dir": "mylab", "template": "full"}, root=root)["ok"]
    doc = os.path.join(root, "mylab", "mylab.ses.yaml")
    edit(doc, "me: {type: int, expr: {replica: index}, doc: 몇 번째 복제본인가}", "me: {type: int, each: [0]}")
    env = call("pack_check", {"dir": "mylab"}, root=root)
    found = [f for f in env["findings"] if f["severity"] == "error"]
    assert [(f["code"], f["kind"], f["where"]) for f in found] == [("P5", "each_too_short", "pair")]
    assert found[0]["data"] == {"component": ["Line", "Workers", "w1"], "attribute": "me", "values": 1}
    assert codes(call("pack_run", {"dir": "mylab", "case": "pair"}, root=root)) == {"P5"}
    edit(doc, "me: {type: int, each: [0]}", "me: {type: int, each: [0], default: 0}")      # default 를 적으면 그것을 쓴다
    assert not codes(call("pack_build", {"dir": "mylab", "case": "pair"}, root=root))


def test_the_call_command_writes_one_ascii_line(lab, tmp_path):
    """봉투의 줄은 ASCII 글자로만 적는다. 받는 쪽의 글자 인코딩이 무엇이든 깨지지 않는다. --out 은 파일에도 적는다."""
    out = io.StringIO()
    target = tmp_path / "env.json"
    code = cli.main(["call", "pack_build", "--args", '{"dir": "lab"}', "--root", lab, "--out", str(target)], out)
    line = out.getvalue()
    assert code == 1 and line.count("\n") == 1 and line.isascii() and "\\uacb0\\uc815" in line
    env = json.loads(line)
    ENVELOPE.validate(env)
    assert "결정이 모자라다" in said(env) and json.loads(target.read_text(encoding="utf-8")) == env
    out = io.StringIO()
    assert cli.main(["call", "pack_build", "--args", '{"dir": "lab"}', "--root", lab, "--pretty"], out) == 1
    assert "결정이 모자라다" in out.getvalue() and out.getvalue().count("\n") > 5 and json.loads(out.getvalue()) == env
    out = io.StringIO()
    assert cli.main(["call", "pack_show", "--args", '{"dir": "lab"}', "--root", lab, "--out", str(tmp_path / "no" / "x.json")], out) == 2


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
