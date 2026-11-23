"""에이전트가 부르는 연산 (docs/ses-platform/21_agent_operations.md).

플랫폼이 에이전트에게 내놓는 것은 묶음에 대한 판정이다. 에이전트는 묶음의 파일을 글로 고치고, 연산을 불러
판정을 읽고, 다시 고친다. 연산은 사람이 쓰는 명령 ses pack 과 같은 계산을 하고 결과를 JSON 값으로 낸다.

약속
- 입력과 결과는 JSON 값이다. 결과는 늘 같은 모양의 봉투다: op, version, ok, findings, result, output.
- 연산은 예외를 내지 않는다. 잘못은 findings 의 줄이 된다. 줄은 severity, code, where, message 를 가진다.
- ok 는 findings 에 error 가 없다는 뜻이다. ok 가 거짓이어도 result 에는 그때까지 구한 것이 든다.
- 연산은 작업 자리(root) 안의 디렉터리만 다룬다. 파일을 쓰는 연산은 pack_new 와 record 를 켠 pack_check 뿐이다.
- 결과의 크기에는 한도가 있다. 잘린 곳에는 잘렸다는 표시가 있다.
- 묶음의 모델 베이스는 파이썬 코드이고 검사와 실행은 그것을 이 프로세스에서 돌린다. 연산은 그 코드를 가두지
  않는다. 믿을 수 없는 코드를 돌릴 때의 격리는 부르는 쪽의 일이다.

부호
  A0 입력이 틀렸다   A1 그런 연산이 없다   A2 이 연산이 하지 않는 일이다(한도를 넘은 것 포함)   A9 도구의 결함이다
  P0 에서 P7 은 묶음의 검사와 같다(pack.py): P0 선언, P1 문서, P2 모델 베이스, P3 바인딩, P4 사례의 결정,
  P5 조립과 실행 가능성, P6 실행과 기록, P7 실행기 사이의 일치

쓰는 법
    from ses_core import ops
    ops.call("pack_check", {"dir": "packs/wsn"})      # 봉투(dict)
    ops.tools()                                       # 도구 정의의 목록: name, description, input_schema
"""

from __future__ import annotations

import contextlib
import io
import math
import os
from dataclasses import dataclass
from typing import Callable, Optional

from . import pack as P

VERSION = "1.0"
OUTPUT_LIMIT = 4000              # 봉투에 싣는 표준 출력의 글자 수. 넘으면 끝쪽만 싣는다
FILES_LIMIT = 200                # pack_show 가 늘어놓는 파일의 수
LOG_LIMIT = 1000                 # pack_run 이 한 번에 내는 사건의 수의 상한
COMPONENTS_LIMIT = 2000          # pack_build 가 한 번에 내는 구성요소의 수의 상한
MAX_ASSIGNMENTS = 200000         # pack_choices 가 돌아보는 변수 값의 조합의 한도 (cli.py 와 같다)
SAFE_INTEGER = 2 ** 53           # 이보다 큰 수는 수로 싣지 않고 글로만 싣는다

# 실행기 사이의 일치의 결과를 기계가 읽는 이름으로
EXECUTOR_STATUS = {P.REFERENCE: "reference", P.SAME: "same", P.DIFFERENT: "different", P.SKIPPED: "skipped",
                   P.SKIPPED_NATIVE: "skipped_native", P.VIOLATES: "violates_convention", P.STOPPED: "stopped"}


class _Fail(Exception):
    """연산을 멈추고 줄 하나로 알린다."""

    def __init__(self, code: str, where: str, message: str) -> None:
        super().__init__(message)
        self.finding = {"severity": "error", "code": code, "where": where, "message": message}


@dataclass(frozen=True)
class Operation:
    name: str
    description: str
    input_schema: dict
    result: str                      # 결과에 드는 것의 설명
    writes: bool                     # 파일을 쓰는가
    run: Callable                    # (작업 자리, 입력) -> (줄들, 결과)


# ---------------------------------------------------------------------------
# JSON 값으로
# ---------------------------------------------------------------------------

def _plain(x):
    """JSON 으로 옮길 수 있는 값으로. 유한하지 않은 수와 모르는 객체는 글이 된다."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, int):
        return x if -SAFE_INTEGER < x < SAFE_INTEGER else str(x)
    if isinstance(x, float):
        return x if math.isfinite(x) else ("INF" if x > 0 else "-INF" if x < 0 else "NaN")
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((_plain(v) for v in x), key=repr)
    return str(x)


def _number(n: int) -> dict:
    """큰 수. value 는 수로 실을 수 있을 때만 있고 text 는 늘 있다."""
    from .cli import _count
    return {"value": n if n < SAFE_INTEGER else None, "text": _count(n)}


def _finding(f) -> dict:
    return {"severity": f.severity, "code": f.code, "where": str(f.where), "message": f.message}


# ---------------------------------------------------------------------------
# 입력의 검사 (JSON Schema 가운데 여기서 쓰는 부분)
# ---------------------------------------------------------------------------

_TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float), "array": list, "object": dict}


def problems(schema: dict, value, at: str = "입력") -> list:
    """value 가 schema 에 맞지 않는 곳들. 여기서 쓰는 스키마의 부분만 안다: type, properties, required,
    additionalProperties false, items, enum."""
    t = schema["type"]
    if t == "object":
        if not isinstance(value, dict):
            return [f"{at}: 이름과 값의 표여야 한다"]
        props = schema.get("properties", {})
        out = [f"{at}: 모르는 항목 {key}. 쓸 수 있는 것은 {sorted(props)} 다" for key in sorted(map(str, set(value) - set(props)))]
        out += [f"{at}: {key} 가 없다" for key in schema.get("required", ()) if key not in value]
        for key, sub in props.items():
            if key in value:
                out += problems(sub, value[key], f"{at}.{key}")
        return out
    if t == "array":
        if not isinstance(value, list):
            return [f"{at}: 목록이어야 한다"]
        return [p for i, x in enumerate(value) for p in problems(schema["items"], x, f"{at}[{i}]")]
    if (isinstance(value, bool) and t != "boolean") or not isinstance(value, _TYPES[t]):
        return [f"{at}: {t} 여야 한다. 받은 것은 {value!r} 다"]
    if t == "number" and not math.isfinite(value):
        return [f"{at}: 유한한 수여야 한다"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{at}: {schema['enum']} 가운데 하나여야 한다. 받은 것은 {value!r} 다"]
    return []


# ---------------------------------------------------------------------------
# 연산이 같이 쓰는 것
# ---------------------------------------------------------------------------

def _directory(root: str, given: str) -> str:
    """작업 자리 안의 디렉터리의 절대 경로. 밖을 가리키면 A0."""
    base = os.path.realpath(root)
    path = os.path.realpath(os.path.join(base, given))
    try:
        inside = os.path.commonpath([base, path]) == base
    except ValueError:
        inside = False
    if not inside:
        raise _Fail("A0", "dir", f"{given} 는 작업 자리 밖이다. 작업 자리 안의 상대 경로로 적는다")
    return path


def _pack(root: str, args: dict) -> P.Pack:
    path = _directory(root, args["dir"])
    if not os.path.isdir(path):
        raise _Fail("A0", "dir", f"디렉터리 {args['dir']} 가 없다")
    try:
        return P.load(path)
    except P.PackError as e:
        raise _Fail(e.code, P.MANIFEST, str(e))


def _sayer(findings: list) -> Callable:
    def say(severity: str, code: str, where: str, message: str) -> None:
        findings.append({"severity": severity, "code": code, "where": str(where), "message": message})
    return say


def _failed(findings: list) -> bool:
    return any(f["severity"] == "error" for f in findings)


def _chosen(pack: P.Pack, args: dict) -> tuple:
    """입력이 가리키는 결정 집합: (묶음 안의 파일 또는 None, 적을 이름, 기본값을 쓰는가)."""
    if "case" in args and "decisions" in args:
        raise _Fail("A0", "case", "case 와 decisions 가운데 하나만 준다")
    if "case" in args:
        case = next((c for c in pack.cases if c.name == args["case"]), None)
        if case is None:
            raise _Fail("A0", "case", f"사례 {args['case']} 가 없다. 있는 사례는 {[c.name for c in pack.cases]} 다")
        return case.decisions, case.name, case.defaults
    if "decisions" in args:
        try:
            return P._inside(pack.root, args["decisions"], "decisions"), args["decisions"], False
        except P.PackError as e:
            raise _Fail("A0", "decisions", str(e))
    return None, pack.document, False


def _report(report: P.Report) -> dict:
    """묶음의 검사 결과를 JSON 값으로."""
    cases = {}
    for name, info in report.cases.items():
        row = dict(info)
        if "executors" in row:
            row["executors"] = {k: EXECUTOR_STATUS.get(v, v) for k, v in row["executors"].items()}
        row["built"] = "variables" in info
        cases[name] = row
    family = None
    if report.family is not None:
        family = {"variants": _number(report.family[0]), "wellformed": _number(report.family[1])}
    return {"name": report.pack.name if report.pack else None, "family": family, "cases": cases,
            "errors": len(report.errors), "warnings": sum(f.severity == "warning" for f in report.findings)}


# ---------------------------------------------------------------------------
# 연산
# ---------------------------------------------------------------------------

def _pack_new(root: str, args: dict) -> tuple:
    path = _directory(root, args["dir"])
    try:
        written = P.scaffold(path, args.get("name"))
    except P.PackError as e:
        raise _Fail("P0", "dir", str(e))
    report = P.check(path, record=True)
    result = _report(report)
    result["files"] = sorted(os.path.relpath(w, path) for w in written) + [P.RECORDS]
    return [_finding(f) for f in report.findings], result


def _pack_check(root: str, args: dict) -> tuple:
    path = _directory(root, args["dir"])
    if not os.path.isdir(path):
        raise _Fail("A0", "dir", f"디렉터리 {args['dir']} 가 없다")
    wanted = tuple(args["executors"]) if "executors" in args else None
    report = P.check(path, record=args.get("record", False), executors=wanted)
    return [_finding(f) for f in report.findings], _report(report)


def _pack_show(root: str, args: dict) -> tuple:
    pack = _pack(root, args)
    records = {}
    with contextlib.suppress(Exception):
        records = P.read_records(pack)
    files = []
    for base, dirs, names in os.walk(pack.root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        files += [os.path.relpath(os.path.join(base, n), pack.root) for n in sorted(names) if not n.startswith(".")]
    result = {
        "name": pack.name, "title": pack.title, "document": pack.document, "profile": pack.profile,
        "model_base": ({"file": pack.model_file, "library": pack.library, "functions": pack.functions,
                        "native": list(pack.native)} if pack.model_file else None),
        "binding": pack.binding, "executors": list(pack.executors),
        "cases": [{"name": c.name, "decisions": c.decisions, "defaults": c.defaults, "until": c.until,
                   "recorded": records.get(c.name) if isinstance(records, dict) else None} for c in pack.cases],
        "experiments": list(pack.experiments),
        "files": files[:FILES_LIMIT], "files_truncated": len(files) > FILES_LIMIT,
    }
    return [], result


def _pack_choices(root: str, args: dict) -> tuple:
    from . import folded
    from .algebra import AlgebraError
    from .decisions import ChoicePoint
    pack = _pack(root, args)
    relative, where, _ = _chosen(pack, args)
    findings: list = []
    say = _sayer(findings)
    _, functions = P.model_base(pack, say) if pack.functions else (None, None)
    doc, _ = P.document(pack, say)
    if doc is None or _failed(findings):
        return findings, None
    ds = P.decisions_of(pack, relative, where, doc, say)
    if ds is P.FAILED:
        return findings, None
    if ds is not None and any(c.node is not None for c in ds.choose):
        raise _Fail("A2", where, "펼친 나무의 노드를 가리킨 결정(node)은 이 연산이 다루지 않는다. 정의(at)나 자리(path)로 적는다")
    blame = "P4" if ds is not None else "P1"
    try:
        fam = folded.analyze(doc, functions, ds, max_assignments=MAX_ASSIGNMENTS)
    except folded.TooManyAssignments as e:
        raise _Fail("A2", where, f"돌아볼 변수 값의 조합이 {_number(e.count)['text']}가지로 한도 {MAX_ASSIGNMENTS}가지를 넘는다. "
                                 "변수의 값을 결정으로 줄인다")
    except AlgebraError as e:
        say("error", blame, where, f"변이 공간을 만들 수 없다. {e}")
        return findings, None
    except (AttributeError, TypeError) as e:
        say("error", "P4", where, f"결정 집합의 모양이 틀렸다: {type(e).__name__}: {e}")
        return findings, None
    points = []
    for row in folded.choice_rows(doc, fam):
        p = ChoicePoint(*row)
        points.append({"owner": p.owner, "kind": p.kind, "group": p.group,
                       "state": "decided" if p.decided else ("open" if p.active else "none_left"),
                       "remaining": list(p.remaining), "options": [o for o, _ in p.options]})
    if not fam.variants:
        say("error", blame, where, "남은 변이가 없다")
    return findings, {"variants": _number(fam.variants), "wellformed": _number(fam.wellformed), "points": points}


def _pack_build(root: str, args: dict) -> tuple:
    from .extension import interpret, violations
    from .skeleton import skeleton
    pack = _pack(root, args)
    relative, where, defaults = _chosen(pack, args)
    defaults = args.get("defaults", defaults)
    limit = args.get("limit", 200)
    depth = args.get("depth")
    if not 1 <= limit <= COMPONENTS_LIMIT:
        raise _Fail("A0", "limit", f"limit 은 1 이상 {COMPONENTS_LIMIT} 이하다")
    if depth is not None and depth < 0:
        raise _Fail("A0", "depth", "depth 는 0 이상이다")
    findings: list = []
    say = _sayer(findings)
    _, functions = P.model_base(pack, say) if pack.functions else (None, None)
    doc, profile = P.document(pack, say)
    if doc is None or _failed(findings):
        return findings, None
    ds = P.decisions_of(pack, relative, where, doc, say)
    if ds is P.FAILED:
        return findings, None
    built = P.build_variant(doc, ds, profile, functions, defaults, where, say)
    if built is P.FAILED:
        return findings, None
    for line in P.shown(built, violations(built.layered, built.variant)):
        say("error", "P5", where, "이 변이는 조립되지 않는다. " + line)
    sk = skeleton(built.layered.ses.tree, built.layered.void, built.variant)
    if sk is None:
        say("error", "P5", where, "뿌리가 없음 대안을 골랐다. 만들 구조가 없다")
        return findings, {"variables": dict(built.sigma), "components": 0, "nodes": len(built.variant), "tree": None,
                          "truncated": False}
    counts = {"all": 0, "listed": 0, "cut": False}
    values = (interpret(built.layered, built.variant) or {}).get("attr")     # 속성의 값. 식과 재정의를 거친 것이다

    def total(c) -> None:
        counts["all"] += 1
        for child in c.parts.values():
            total(child)

    def node(c, level: int, attr) -> dict:
        counts["listed"] += 1
        out = {"name": c.name, "labels": list(c.labels), "attributes": dict((attr or {}).get("params") or {}),
               "absent": list(c.absent), "parts": []}
        if depth is not None and level >= depth:
            hidden = len(c.parts)
        else:
            hidden = 0
            for name, child in c.parts.items():
                if counts["listed"] >= limit:
                    hidden += 1
                else:
                    out["parts"].append(node(child, level + 1, (attr or {}).get("children", {}).get(name)))
        if hidden:
            out["parts_not_listed"] = hidden
            counts["cut"] = True
        return out

    total(sk)
    tree = node(sk, 0, values)
    return findings, {"variables": dict(built.sigma), "components": counts["all"], "nodes": len(built.variant),
                      "structure": P.structure_digest(built), "tree": tree, "truncated": counts["cut"]}


def _pack_run(root: str, args: dict) -> tuple:
    path = _directory(root, args["dir"])
    limit, offset = args.get("limit", 50), args.get("offset", 0)
    if not 0 <= limit <= LOG_LIMIT:
        raise _Fail("A0", "limit", f"limit 은 0 이상 {LOG_LIMIT} 이하다")
    if offset < 0:
        raise _Fail("A0", "offset", "offset 은 0 이상이다")
    if "until" in args and args["until"] < 0:
        raise _Fail("A0", "until", "until 은 0 이상이다")
    pack = _pack(root, args)
    case = next((c for c in pack.cases if c.name == args["case"]), None)
    if case is None:
        raise _Fail("A0", "case", f"사례 {args['case']} 가 없다. 있는 사례는 {[c.name for c in pack.cases]} 다")
    try:
        log, sigma, atoms = P.run(path, case.name, args.get("until"))
    except P.PackError as e:
        raise _Fail(e.code, case.name, str(e))
    until = args.get("until", case.until)
    rows = [{"t": t, "at": "/".join(map(str, where)), "port": port, "value": value}
            for t, where, port, value in log[offset:offset + limit]]
    return [], {"variables": sigma, "atoms": atoms, "until": until, "events": len(log),
                "last": log[-1][0] if log else None, "digest": P.digest(log),
                "offset": offset, "log": rows, "truncated": offset + len(rows) < len(log)}


def _schema(properties: dict, required: tuple) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_DIR = {"type": "string", "description": "묶음의 디렉터리. 작업 자리 안의 상대 경로"}
_CASE = {"type": "string", "description": "pack.yaml 의 cases 에 적힌 사례의 이름"}
_DECISIONS = {"type": "string", "description": "묶음 안의 결정 집합 파일의 상대 경로. case 와 함께 주지 않는다"}

OPERATIONS = {op.name: op for op in (
    Operation(
        "pack_new",
        "돌아가는 가장 작은 묶음을 새 디렉터리에 만들고 바로 검사한다. 새 분야를 시작할 때 한 번 부른다. "
        "만든 파일마다 맨 위에 설명이 있으니 읽고 자기 분야의 것으로 고친다. 비어 있지 않은 디렉터리에는 만들지 않는다.",
        _schema({"dir": {"type": "string", "description": "만들 디렉터리. 작업 자리 안의 상대 경로. 없거나 비어 있어야 한다"},
                 "name": {"type": "string", "description": "묶음의 이름. 글자, 숫자, 밑줄. 주지 않으면 디렉터리의 이름"}}, ("dir",)),
        "files 만든 파일들. 그 밖에는 pack_check 의 결과와 같다", True, _pack_new),
    Operation(
        "pack_check",
        "묶음이 플랫폼의 계약을 지키는지 본다. 묶음의 파일을 고칠 때마다 부른다. findings 의 error 가 고칠 것이다. "
        "부호는 P0 선언, P1 문서, P2 모델 베이스, P3 바인딩, P4 사례의 결정, P5 조립과 실행 가능성, P6 실행과 기록, "
        "P7 실행기 사이의 일치다. 모델이나 문서를 뜻대로 고쳐 기록이 달라졌다는 P6 가 나오면 record 를 켜고 다시 부른다. "
        "뜻하지 않은 변화이면 record 를 켜지 말고 원인을 고친다.",
        _schema({"dir": _DIR,
                 "record": {"type": "boolean", "description": "참이면 사례의 기록을 records.yaml 에 적는다. 기본은 거짓"},
                 "executors": {"type": "array", "items": {"type": "string", "enum": list(P.EXECUTORS)},
                               "description": "실행기 사이의 일치를 볼 실행기들. 주지 않으면 쓸 수 있는 것 전부"}}, ("dir",)),
        "name, family(변이의 수 variants 와 적격인 변이의 수 wellformed. 각각 value 와 text), cases(사례마다 built, variables, "
        "components, 돌린 사례는 atoms, links, events, last, digest, executors, 돌리지 않는 사례는 structure), errors, warnings",
        True, _pack_check),
    Operation(
        "pack_show",
        "묶음에 무엇이 들었는지 읽는다. 선언의 내용, 사례와 적어 둔 기록, 파일의 목록. 묶음을 처음 볼 때 부른다. "
        "아무것도 돌리지 않는다.",
        _schema({"dir": _DIR}, ("dir",)),
        "name, title, document, profile, model_base, binding, executors, cases, experiments, files, files_truncated",
        False, _pack_show),
    Operation(
        "pack_choices",
        "문서의 족에서 무엇을 고를 수 있는지 본다. 결정 집합을 주면 그 결정을 따르는 변이만 남기고, 남은 변이의 수와 "
        "선택 지점마다 남은 선택지를 낸다. 변이를 하나씩 만들지 않으므로 큰 족에서도 답한다. 결정을 좁혀 가며 부른다. "
        "선택의 핵만 본다. 결합과 속성의 검사는 pack_check 가 한다.",
        _schema({"dir": _DIR, "case": _CASE, "decisions": _DECISIONS}, ("dir",)),
        "variants, wellformed(각각 value 와 text), points(선택 지점마다 owner, kind, group, state, remaining, options). "
        "state 는 open, decided, none_left 가운데 하나", False, _pack_choices),
    Operation(
        "pack_build",
        "결정이 끝난 변이 하나의 구조를 만든다. 사례가 뜻한 구조인지, 속성의 값이 뜻한 대로인지 확인할 때 부른다. "
        "결정이 모자라면 무엇이 정해지지 않았는지를 P4 로 알린다. 모델 베이스는 돌리지 않는다.",
        _schema({"dir": _DIR, "case": _CASE, "decisions": _DECISIONS,
                 "defaults": {"type": "boolean", "description": "정해지지 않은 곳에 문서의 기본값을 쓴다. 주지 않으면 사례의 선언을 따른다"},
                 "depth": {"type": "integer", "description": "이 깊이까지만 낸다. 뿌리가 0"},
                 "limit": {"type": "integer", "description": f"낼 구성요소의 수. 기본 200, 최대 {COMPONENTS_LIMIT}"}}, ("dir",)),
        "variables, components, nodes, structure(구조의 지문), tree(구성요소마다 name, labels, attributes, absent, parts, "
        "잘렸으면 parts_not_listed), truncated",
        False, _pack_build),
    Operation(
        "pack_run",
        "사례 하나를 참조 시뮬레이터로 돌려 출력 사건을 낸다. 모델의 행동을 볼 때 부른다. 기록은 적지 않는다. "
        "사건이 많으면 offset 과 limit 으로 나눠 읽는다. digest 는 기록 전체의 지문이고 pack_check 가 견주는 것과 같다.",
        _schema({"dir": _DIR, "case": _CASE,
                 "until": {"type": "number", "description": "이 시각까지 돌린다. 주지 않으면 사례에 적힌 시각"},
                 "offset": {"type": "integer", "description": "이 번째 사건부터 낸다. 기본 0"},
                 "limit": {"type": "integer", "description": f"낼 사건의 수. 기본 50, 최대 {LOG_LIMIT}"}}, ("dir", "case")),
        "variables, atoms, until, events, last, digest, offset, log(사건마다 t, at, port, value), truncated",
        False, _pack_run),
)}

ENVELOPE = {
    "type": "object",
    "properties": {
        "op": {"type": "string"},
        "version": {"type": "string"},
        "ok": {"type": "boolean"},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["error", "warning", "info"]},
                           "code": {"type": "string"}, "where": {"type": "string"}, "message": {"type": "string"}},
            "required": ["severity", "code", "where", "message"], "additionalProperties": False}},
        "result": {"type": ["object", "null"]},
        "output": {"type": "string"},
    },
    "required": ["op", "version", "ok", "findings", "result", "output"],
    "additionalProperties": False,
}


def tools() -> list:
    """도구 정의의 목록. 하나는 name, description, input_schema 다."""
    return [{"name": op.name, "description": op.description, "input_schema": op.input_schema}
            for op in OPERATIONS.values()]


def manifest() -> dict:
    """연산의 목록과 봉투의 모양."""
    return {"version": VERSION, "envelope": ENVELOPE,
            "operations": [{"name": op.name, "description": op.description, "input_schema": op.input_schema,
                            "result": op.result, "writes": op.writes} for op in OPERATIONS.values()]}


def call(name: str, args: Optional[dict] = None, root: Optional[str] = None) -> dict:
    """연산 하나를 부른다. 늘 봉투를 돌려주고 예외를 내지 않는다. root 는 작업 자리이고 주지 않으면 지금 디렉터리다."""
    env = {"op": str(name), "version": VERSION, "ok": False, "findings": [], "result": None, "output": ""}
    op = OPERATIONS.get(name) if isinstance(name, str) else None
    if op is None:
        env["findings"] = [{"severity": "error", "code": "A1", "where": str(name),
                            "message": f"그런 연산이 없다. 있는 연산은 {sorted(OPERATIONS)} 다"}]
        return env
    args = {} if args is None else args
    bad = problems(op.input_schema, args)
    if bad:
        env["findings"] = [{"severity": "error", "code": "A0", "where": op.name, "message": line} for line in bad]
        return env
    seen = io.StringIO()
    findings, result = [], None
    try:
        with contextlib.redirect_stdout(seen):               # 묶음의 코드가 찍는 것이 결과에 섞이지 않게
            findings, result = op.run(os.path.abspath(root or os.getcwd()), args)
    except _Fail as e:
        findings = [e.finding]
    except SystemExit as e:
        findings = [{"severity": "error", "code": "P2", "where": op.name,
                     "message": f"묶음의 코드가 프로세스를 끝내려 했다(SystemExit {e.code!r}). 모델 베이스에서 exit 를 부르지 않는다"}]
    except Exception as e:                                   # noqa: BLE001  도구의 결함이다. 예외를 밖으로 내지 않는다
        findings = [{"severity": "error", "code": "A9", "where": op.name,
                     "message": f"도구의 결함이다. 이 입력과 함께 알려 달라: {type(e).__name__}: {e}"}]
    text = seen.getvalue()
    env["output"] = text if len(text) <= OUTPUT_LIMIT else "(앞은 잘렸다) " + text[-OUTPUT_LIMIT:]
    env["findings"] = _plain(findings)
    env["result"] = _plain(result)
    env["ok"] = not _failed(findings)
    return env
