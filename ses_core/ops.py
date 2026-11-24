"""에이전트가 부르는 연산 (docs/ses-platform/21_agent_operations.md).

플랫폼이 에이전트에게 내놓는 것은 묶음에 대한 판정이다. 에이전트는 묶음의 파일을 글로 고치고, 연산을 불러
판정을 읽고, 다시 고친다. 연산은 사람이 쓰는 명령 ses pack 과 같은 계산을 하고 결과를 JSON 값으로 낸다.

약속
- 입력과 결과는 JSON 값이다. 결과는 늘 같은 모양의 봉투다: op, version, ok, findings, result, output.
- 연산은 예외를 내지 않는다. 잘못은 findings 의 줄이 된다. 줄은 severity, code, where, message 를 가지고,
  기계가 읽을 kind, data, next 를 가질 수 있다. kind 는 같은 부호 안에서 할 일이 다른 것을 가른다.
- ok 는 findings 에 error 가 없다는 뜻이다. ok 가 거짓이어도 result 에는 그때까지 구한 것이 든다.
- 연산은 작업 자리(root) 안의 디렉터리만 다룬다. 묶음 안의 링크가 묶음 밖을 가리키면 따라가지 않는다.
  파일을 쓰는 연산은 pack_new 와 record 를 켠 pack_check 뿐이다.
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
OPTIONS_LIMIT = 200              # 선택 지점 하나가 늘어놓는 선택지의 수
FINDINGS_LIMIT = 200             # 봉투에 싣는 줄의 수
MESSAGE_LIMIT = 2000             # 줄 하나의 글의 글자 수
VALUES_LIMIT = 200000            # 결과에 싣는 값의 수. 넘으면 결과를 싣지 않고 A2 로 알린다
DEPTH_LIMIT = 100                # 결과의 값이 겹친 깊이. 넘는 곳은 글로 줄인다
MAX_ASSIGNMENTS = 200000         # pack_choices 가 돌아보는 변수 값의 조합의 한도 (cli.py 와 같다)
SAFE_INTEGER = 2 ** 53           # 이보다 큰 수는 수로 싣지 않고 글로만 싣는다

# 실행기 사이의 일치의 결과를 기계가 읽는 이름으로
EXECUTOR_STATUS = {P.REFERENCE: "reference", P.SAME: "same", P.DIFFERENT: "different", P.SKIPPED: "skipped",
                   P.SKIPPED_NATIVE: "skipped_native", P.VIOLATES: "violates_convention", P.STOPPED: "stopped"}

# 줄의 종류(kind)마다 그다음에 할 일. 연산을 부르는 쪽의 말로 적는다
NEXT = {
    "input": "입력을 고쳐 다시 부른다. 묶음은 건드리지 않는다",
    "unknown_operation": "연산의 이름을 고친다",
    "not_supported": "줄이 적은 대로 입력이나 결정을 바꾼다",
    "limit": "입력을 좁혀 다시 부른다",
    "tool_fault": "고치려 하지 말고 이 입력과 함께 사람에게 알린다",
    "pack_code_exit": "모델 베이스에서 프로세스를 끝내는 코드를 지운다",
    "declaration": "pack.yaml 을 고친다",
    "document_load": "문서 파일을 고친다. 줄이 어느 정의의 무엇인지 적는다",
    "document_diagnostic": "문서 파일을 고친다. data.address 가 틀린 곳이다",
    "document_expression": "문서의 식이나 제약을 고친다",
    "document_note": "할 일이 없다",
    "family_violation": "사례가 그 변이를 고르지 않으면 두어도 된다. 족 전체를 맞추려면 문서의 결합이나 규칙을 고친다",
    "family_unbounded": "족의 검사를 받으려면 문서의 cardinality 에 max 를 적는다",
    "no_wellformed_variant": "문서의 결합이나 규칙을 고친다. family_violation 의 줄이 어긋난 곳을 알린다",
    "profile_load": "프로파일 파일을 고친다",
    "model_base_load": "모델 베이스 파일을 고친다. data.line 이 줄이다",
    "function_failed": "문서의 식이 부르는 함수를 고친다",
    "functions_shape": "모델 베이스 파일에서 함수의 사전을 고친다",
    "library_shape": "모델 베이스 파일에서 LIBRARY 를 고친다. module_of(클래스) 로 만든다",
    "not_common_base": "그 모델을 ses_core.devs.Atomic 의 하위 클래스로 쓴다",
    "port_declaration": "모델의 PORTS 를 고친다",
    "required_not_input": "모델의 REQUIRED 를 고친다",
    "param_declaration": "모델의 PARAMS 를 고친다",
    "initial_ta": "모델의 ta 를 고친다",
    "initial_output": "모델의 output 을 고친다",
    "initial_state_error": "모델의 init, ta, output 을 고친다",
    "native_missing": "pack.yaml 의 model_base.native 를 고친다",
    "lint": "모델 베이스 파일의 data.line 번째 줄을 고친다",
    "binding_load": "바인딩 파일을 고친다",
    "binding_target": "바인딩의 target 을 문서의 name 과 같게 적는다",
    "unknown_definition": "바인딩의 map 에서 그 이름을 data.definitions 가운데 하나로 고치거나 지운다",
    "unknown_module": "바인딩의 map 에서 모듈의 이름을 data.modules 가운데 하나로 고친다",
    "decisions_load": "결정 집합 파일을 고친다",
    "decisions_target": "결정 집합의 target 을 문서의 name 과 같게 적는다",
    "undecided": "그 사례의 결정 집합에 결정을 더한다. data.at 이 자리, data.choice 가 종류, data.group 이 이름, "
                 "data.options 가 고를 수 있는 것이다",
    "contradiction": "결정들이 서로 어긋나거나 규칙과 제약에 걸린다. pack_choices 로 결정을 하나씩 빼며 본다",
    "misfit": "결정이 가리키는 이름을 문서의 것으로 고친다",
    "unused_decision": "그 결정을 지우거나 가리키는 곳을 고친다",
    "defaults_ignored": "할 일이 없다. 조립은 pack_build 로 본다",
    "not_assembled": "data.component 의 결합이나 포트를 문서에서 고친다. data.check 가 어긴 조건이다",
    "not_executable": "data.component 를 바인딩에 묶거나, 문서의 포트와 속성을 모델의 것에 맞춘다. data.check 가 어긴 조건이다",
    "model_only_port": "문서의 그 정의의 ports 에 data.port 를 적는다",
    "each_too_short": "문서의 그 속성의 each 에 값을 더 적거나 default 를 적는다. data.component 가 값을 받지 못한 복제본이다",
    "attribute_not_passed": "문서의 속성 이름을 모델의 매개변수 이름으로 고치거나 모델에 그 매개변수를 더한다",
    "model_error": "모델 베이스 파일의 data.line 번째 줄을 본다. data.component 의 data.function 이 data.time 에 예외를 냈다",
    "off_grid": "바인딩의 time_unit 을 줄이거나 그 시간 값을 time_unit 의 정수배로 고친다",
    "step_limit": "시간 전진이 0 인 고리가 있는지 본다. 긴 사례이면 pack.yaml 의 그 사례에 max_steps 를 적는다",
    "run_stopped": "모델을 고친다",
    "run_failed": "pack_check 를 불러 같은 잘못의 종류와 자료를 본다. 결정 집합 파일을 돌렸으면 pack_build 로 본다",
    "stray_port": "모델의 PORTS 와 문서의 ports 에 data.port 를 적는다",
    "mutated_input": "data.component 의 data.function 에서 받은 값을 고치지 않게 한다. 고쳐야 하면 복사해서 고친다",
    "depends_on_copying": "낸 값을 낸 뒤에 고치는 모델을 찾아 복사한 것을 내게 한다",
    "not_reproducible": "전역 난수와 벽시계를 쓰는 곳을 고친다. lint 의 줄이 있으면 그곳이다",
    "no_record": "pack_check 를 record: true 로 부른다",
    "record_differs": "뜻한 변화이면 pack_check 를 record: true 로 부른다. 뜻하지 않은 변화이면 원인을 고친다. 기록을 다시 적어 덮지 않는다",
    "structure_differs": "뜻한 변화이면 pack_check 를 record: true 로 부른다. 뜻하지 않은 변화이면 원인을 고친다. 기록을 다시 적어 덮지 않는다",
    "stale_record": "pack_check 를 record: true 로 부르면 지워진다",
    "records_file": "pack_check 를 record: true 로 부르면 다시 적는다",
    "engine_missing": "할 일이 없다. 그 엔진이 이 컴퓨터에 없다",
    "engine_convention": "모델을 그 엔진의 규약에 맞춘다",
    "engine_stopped": "모델이 계약을 어긴 곳을 찾는다",
    "engine_differs": "모델이 계약을 어긴 곳을 찾는다. 받은 값을 고치는 곳과 같은 시각의 사건의 순서에 기대는 곳이다",
}


class _Fail(Exception):
    """연산을 멈추고 줄 하나로 알린다."""

    def __init__(self, code: str, where: str, message: str, kind: str = "input", **data) -> None:
        super().__init__(message)
        self.finding = _line("error", code, where, message, kind, **data)


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

def _plain(x, budget: Optional[list] = None, depth: int = 0):
    """JSON 으로 옮길 수 있는 값으로. 유한하지 않은 수와 모르는 객체는 글이 된다.

    값의 수가 한도를 넘으면 _Fail(A2) 이다. 너무 깊이 겹친 곳은 글로 줄인다.
    """
    budget = [VALUES_LIMIT] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise _Fail("A2", "result", f"결과가 값 {VALUES_LIMIT}개를 넘는다. 묶음의 파일이나 모델이 내는 값이 지나치게 크다", "limit")
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, int):
        return x if -SAFE_INTEGER < x < SAFE_INTEGER else _decimal(x)
    if isinstance(x, float):
        return x if math.isfinite(x) else ("INF" if x > 0 else "-INF" if x < 0 else "NaN")
    if depth >= DEPTH_LIMIT:
        return "(너무 깊이 겹친 값)"
    if isinstance(x, dict):
        return {_key(k): _plain(v, budget, depth + 1) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v, budget, depth + 1) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((_plain(v, budget, depth + 1) for v in x), key=repr)
    return _text(x)


def _text(x) -> str:
    try:
        return str(x)[:MESSAGE_LIMIT]
    except Exception:                                        # noqa: BLE001  글로 옮기는 것조차 실패하는 객체
        return f"({type(x).__name__})"


def _key(k) -> str:
    return k if isinstance(k, str) else _text(k)


def _decimal(n: int) -> str:
    """큰 정수를 글로. 아주 큰 수는 글로 다 옮길 수 없어 어림으로 적는다."""
    from .cli import _count
    return str(n) if abs(n) < 10 ** 4000 else _count(n)


def _number(n: int) -> dict:
    """클 수 있는 수. value 는 수로 실을 수 있을 때만 있고 text 는 늘 있다. text 는 4,000자리까지 정확한 십진수다."""
    return {"value": n if n < SAFE_INTEGER else None, "text": _decimal(n), "exact": n < 10 ** 4000}


def _line(severity: str, code: str, where, message: str, kind: str = "", **data) -> dict:
    """봉투의 줄 하나."""
    text = _text(message)
    out = {"severity": severity, "code": code, "where": _text(where)[:200],
           "message": text if len(text) < MESSAGE_LIMIT else text[:MESSAGE_LIMIT] + " (뒤는 잘렸다)"}
    if kind:
        out["kind"] = kind
        out["data"] = data
        if kind in NEXT:
            out["next"] = NEXT[kind]
    return out


def _finding(f) -> dict:
    return _line(f.severity, f.code, f.where, f.message, f.kind, **f.data)


# ---------------------------------------------------------------------------
# 입력의 검사 (JSON Schema 가운데 여기서 쓰는 부분)
# ---------------------------------------------------------------------------

_TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float), "array": list, "object": dict}


def _shown(value) -> str:
    """입력의 값을 줄에 적는다. 긴 것은 줄인다. 아주 큰 수는 글로 옮기는 것부터 실패할 수 있다."""
    try:
        text = repr(value)
    except Exception:                                        # noqa: BLE001
        text = f"({type(value).__name__})"
    return text if len(text) <= 80 else text[:80] + " ..."


def problems(schema: dict, value, at: str = "입력") -> list:
    """value 가 schema 에 맞지 않는 곳들. 여기서 쓰는 스키마의 부분만 안다: type, properties, required,
    additionalProperties false, items, enum."""
    t = schema["type"]
    if t == "object":
        if not isinstance(value, dict):
            return [f"{at}: 이름과 값의 표여야 한다"]
        props = schema.get("properties", {})
        out = [f"{at}: 모르는 항목 {_shown(key)}. 쓸 수 있는 것은 {sorted(props)} 다" for key in sorted(map(str, set(value) - set(props)))]
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
        return [f"{at}: {t} 여야 한다. 받은 것은 {_shown(value)} 다"]
    if t == "number" and not math.isfinite(value):
        return [f"{at}: 유한한 수여야 한다"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{at}: {schema['enum']} 가운데 하나여야 한다. 받은 것은 {_shown(value)} 다"]
    return []


# ---------------------------------------------------------------------------
# 연산이 같이 쓰는 것
# ---------------------------------------------------------------------------

def _directory(root: str, given: str) -> str:
    """작업 자리 안의 디렉터리의 절대 경로. 밖을 가리키면 A0."""
    if "\x00" in given or not given.strip():
        raise _Fail("A0", "dir", "dir 은 작업 자리 안의 상대 경로를 글로 적는다")
    base = os.path.realpath(root)
    path = os.path.realpath(os.path.join(base, given))
    try:
        inside = os.path.commonpath([base, path]) == base
    except ValueError:
        inside = False
    if not inside:
        raise _Fail("A0", "dir", f"{_shown(given)} 는 작업 자리 밖이다. 작업 자리 안의 상대 경로로 적는다")
    return path


def _pack(root: str, args: dict) -> P.Pack:
    path = _directory(root, args["dir"])
    if not os.path.isdir(path):
        raise _Fail("A0", "dir", f"디렉터리 {_shown(args['dir'])} 가 없다")
    try:
        return P.load(path)
    except P.PackError as e:
        raise _Fail(e.code, P.MANIFEST, str(e), "declaration")


def _sayer(findings: list) -> Callable:
    def say(severity: str, code: str, where: str, message: str, kind: str = "", **data) -> None:
        findings.append(_line(severity, code, where, message, kind, **data))
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
            raise _Fail("A0", "case", f"사례 {_shown(args['case'])} 가 없다. 있는 사례는 {[c.name for c in pack.cases]} 다",
                        cases=[c.name for c in pack.cases])
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
        row["ran"] = "events" in info
        cases[name] = row
    family = None
    if report.family is not None:
        # scope 가 full 이면 변이를 열거해 모든 검사를 한 수이고, core 이면 열거하지 않고 선택의 핵만 센 수다
        family = {"variants": _number(report.family[0]), "wellformed": _number(report.family[1]),
                  "scope": report.family_scope or "core"}
    return {"name": report.pack.name if report.pack else None, "family": family, "cases": cases,
            "errors": len(report.errors), "warnings": sum(f.severity == "warning" for f in report.findings)}


# ---------------------------------------------------------------------------
# 연산
# ---------------------------------------------------------------------------

def _pack_new(root: str, args: dict) -> tuple:
    path = _directory(root, args["dir"])
    name = args.get("name") or os.path.basename(path)
    if os.path.lexists(path) and not os.path.isdir(path):
        raise _Fail("A0", "dir", f"{_shown(args['dir'])} 는 디렉터리가 아니다")
    if os.path.isdir(path) and os.listdir(path):
        raise _Fail("A0", "dir", f"{_shown(args['dir'])} 가 비어 있지 않다. 없거나 빈 디렉터리에 만든다")
    if not (name.isidentifier() and name.isascii() and len(name) <= 60):
        raise _Fail("A0", "name" if "name" in args else "dir",
                    "묶음의 이름은 영문자, 숫자, 밑줄로 60자 이하로 적는다. 디렉터리의 이름이 그렇지 않으면 name 으로 따로 준다")
    try:
        written = P.scaffold(path, name, args.get("template", "minimal"))
    except P.PackError as e:
        raise _Fail("P0", "dir", str(e), "declaration")
    report = P.check(path, record=True)
    result = _report(report)
    result["files"] = sorted(os.path.relpath(w, path) for w in written) + [P.RECORDS]
    return [_finding(f) for f in report.findings], result


def _pack_check(root: str, args: dict) -> tuple:
    path = _directory(root, args["dir"])
    if not os.path.isdir(path):
        raise _Fail("A0", "dir", f"디렉터리 {_shown(args['dir'])} 가 없다")
    wanted = tuple(args["executors"]) if "executors" in args else None
    report = P.check(path, record=args.get("record", False), executors=wanted)
    result = _report(report)
    if args.get("record", False):                            # 무엇을 적었는가. 오류가 있는 사례는 적지 않는다
        try:
            result["recorded"] = sorted(P.read_records(report.pack)) if report.pack is not None else []
        except P.PackError:
            result["recorded"] = []
    return [_finding(f) for f in report.findings], result


def _pack_show(root: str, args: dict) -> tuple:
    pack = _pack(root, args)
    findings: list = []
    try:
        records = P.read_records(pack)
    except P.PackError as e:
        records = {}
        findings.append(_line("warning", e.code, P.RECORDS, str(e), "records_file"))
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
                   "max_steps": c.max_steps, "recorded": records.get(c.name)} for c in pack.cases],
        "experiments": list(pack.experiments),
        # 점으로 시작하는 이름과 __pycache__ 는 빼고 늘어놓는다
        "files": files[:FILES_LIMIT], "files_truncated": len(files) > FILES_LIMIT,
    }
    return findings, result


def _context(pack: P.Pack, findings: list, need_library: bool = False) -> tuple:
    """묶음의 (문서, 프로파일, 함수 사전, 모듈 라이브러리). 모델 베이스 파일은 문서의 식이 함수를 부르거나
    need_library 일 때만 싣는다."""
    say = _sayer(findings)
    library = functions = None
    if pack.model_file and (pack.functions or need_library):
        library, functions = P.model_base(pack, say)
    doc, profile = P.document(pack, say)
    return doc, profile, functions, library


def _pack_choices(root: str, args: dict) -> tuple:
    from . import direct, folded
    from .algebra import AlgebraError
    from .decisions import ChoicePoint
    pack = _pack(root, args)
    relative, where, defaults = _chosen(pack, args)
    findings: list = []
    say = _sayer(findings)
    doc, _, functions, _ = _context(pack, findings)
    if doc is None or _failed(findings):
        return findings, None
    ds = P.decisions_of(pack, relative, where, doc, say)
    if ds is P.FAILED:
        return findings, None
    if ds is not None and any(c.node is not None for c in ds.choose):
        raise _Fail("A2", where, "펼친 나무의 노드를 가리킨 결정(node)은 이 연산이 다루지 않는다. 정의(at)나 자리(path)로 적는다",
                    "not_supported")

    def analyze(decisions):
        return folded.analyze(doc, functions, decisions, max_assignments=MAX_ASSIGNMENTS)

    try:
        fam = analyze(ds)
    except folded.TooManyAssignments as e:
        raise _Fail("A2", where, f"돌아볼 변수 값의 조합이 {_number(e.count)['text']}가지로 한도 {MAX_ASSIGNMENTS}가지를 넘는다. "
                                 "변수의 값을 결정으로 줄인다", "limit")
    except AlgebraError as e:
        own = ds is not None                                 # 결정의 탓인가 문서의 탓인가. 결정 없이도 같은 일이 나면 문서다
        if own:
            try:
                analyze(None)
            except (AlgebraError, folded.TooManyAssignments):
                own = False
        if "상한이 필요하다" in str(e):
            raise _Fail("A2", pack.document, f"이 족은 셀 수 없다. {e}. 문서의 cardinality 에 max 를 적는다. 사례 하나의 구조는 "
                                             "pack_build 가 만든다", "family_unbounded")
        if own:
            say("error", "P4", where, f"결정 집합이 문서에 맞지 않다. {e}", "misfit")
        else:
            say("error", "P1", pack.document, f"변이 공간을 만들 수 없다. {e}", "document_expression")
        return findings, None
    except (AttributeError, TypeError) as e:
        say("error", "P4", where, f"결정 집합의 모양이 틀렸다: {type(e).__name__}: {e}", "decisions_load")
        return findings, None
    points = []
    for row in folded.choice_rows(doc, fam):
        p = ChoicePoint(*row)
        remaining, options = list(p.remaining), [o for o, _ in p.options]
        # 변이가 하나인데 한 정의의 줄에 여럿이 남았으면, 그 정의가 놓인 자리마다 다른 것이 정해진 것이다
        state = ("decided" if p.decided else "none_left" if not p.active else
                 "decided_per_place" if fam.variants == 1 else "open")
        point = {"owner": p.owner, "kind": p.kind, "group": p.group, "state": state,
                 "remaining": remaining[:OPTIONS_LIMIT], "remaining_count": len(remaining),
                 "options": options[:OPTIONS_LIMIT], "options_count": len(options)}
        if len(options) > OPTIONS_LIMIT:
            point["truncated"] = True
        points.append(point)
    if not fam.variants:
        why = direct.why_none(doc, ds, functions)                # 어느 자리에서 무엇이 어긋나는가
        say("error", "P4" if ds is not None else "P1", where, "남은 변이가 없다" + (f". {why}" if why else ""),
            "contradiction" if ds is not None else "no_wellformed_variant")
    if defaults:
        say("info", "P4", where, "이 사례는 defaults 를 쓴다. 이 표는 적힌 결정만 본다. 문서의 기본값이 채우는 것은 세지 않았다",
            "defaults_ignored")
    # core_wellformed 는 선택의 핵만 본 수다. 결합과 속성과 프로파일의 검사는 들지 않는다. pack_check 의 family 를 본다
    return findings, {"variants": _number(fam.variants), "core_wellformed": _number(fam.wellformed), "points": points}


def _couplings(devs: dict) -> list:
    """구성요소 하나의 결합을 글의 쌍으로. 자신의 포트는 포트 이름만, 부분의 포트는 부분.포트 다."""
    out = [{"from": port, "to": f"{child}.{q}"} for port, (child, q) in devs.get("eic", ())]
    out += [{"from": f"{a}.{p}", "to": f"{b}.{q}"} for (a, p), (b, q) in devs.get("ic", ())]
    out += [{"from": f"{child}.{p}", "to": port} for (child, p), port in devs.get("eoc", ())]
    return out


def _pack_build(root: str, args: dict) -> tuple:
    from . import executor as X
    from . import structure as st
    from .devs import DevsExecutor
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
    doc, profile, functions, library = _context(pack, findings, need_library=bool(pack.library))
    if doc is None:
        return findings, None
    ds = P.decisions_of(pack, relative, where, doc, say)
    if ds is P.FAILED:
        return findings, None
    built = P.build_variant(doc, ds, profile, functions, defaults, where, say, pack)
    if built is P.FAILED:
        return findings, None
    found = violations(built.layered, built.variant)
    for line, data in zip(P.shown(built, found), P.violation_data(built, found)):
        say("error", "P5", where, "이 변이는 조립되지 않는다. " + line, "not_assembled", **data)
    sk = skeleton(built.layered.ses.tree, built.layered.void, built.variant)
    if sk is None:
        say("error", "P5", where, "뿌리가 없음 대안을 골랐다. 만들 구조가 없다", "not_assembled")
        return findings, {"variables": dict(built.sigma), "components": 0, "nodes": len(built.variant), "tree": None,
                          "structure": P.structure_digest(built), "truncated": False}
    seen = interpret(built.layered, built.variant) or {}
    values, wiring = seen.get("attr"), seen.get("devs")      # 속성의 값(식과 재정의를 거친 것)과, 포트와 결합
    bound = {}                                               # 원자 구성요소의 자리에서 (모듈, 모델이 받는 매개변수)로
    if library is not None and pack.binding and not found:
        try:
            binding = X.load_binding(pack.path(pack.binding))
            L, ext = X.attach(built.layered, DevsExecutor(), binding, library)
            if not violations(X.alone(L, ext), built.variant):
                plan = X.plan(L, ext, built.variant)
                bound = {tuple(p): (st.subtree(plan, p).get("module"), st.subtree(plan, p).get("params") or {})
                         for p in X.frontier(plan)}
        except Exception:                                    # noqa: BLE001  바인딩의 잘못은 pack_check 가 알린다
            bound = {}
    counts = {"all": 0, "listed": 0, "cut": False}

    def total(c) -> None:
        counts["all"] += 1
        for child in c.parts.values():
            total(child)

    def node(c, level: int, attr, devs, path: tuple) -> dict:
        counts["listed"] += 1
        out = {"name": c.name, "labels": list(c.labels), "attributes": dict((attr or {}).get("params") or {}),
               "ports": {p: {"type": d[0], "direction": d[1], "required": p in (devs or {}).get("required", ())}
                         for p, d in ((devs or {}).get("ports") or {}).items()},
               "absent": list(c.absent), "parts": []}
        if path in bound:                                    # 모델에 실제로 가는 값. 문서의 속성과 이름이 다르면 가지 않는다
            out["module"], out["params"] = bound[path]
        if c.parts:
            out["couplings"] = _couplings(devs or {})
        if depth is not None and level >= depth:
            hidden = len(c.parts)
        else:
            hidden = 0
            for name, child in c.parts.items():
                if counts["listed"] >= limit:
                    hidden += 1
                else:
                    out["parts"].append(node(child, level + 1, (attr or {}).get("children", {}).get(name),
                                             (devs or {}).get("children", {}).get(name), path + (name,)))
        if hidden:
            out["parts_not_listed"] = hidden
            counts["cut"] = True
        return out

    total(sk)
    tree = node(sk, 0, values, wiring, ())
    return findings, {"variables": dict(built.sigma), "components": counts["all"], "nodes": len(built.variant),
                      "structure": P.structure_digest(built), "tree": tree, "truncated": counts["cut"]}


def _pack_run(root: str, args: dict) -> tuple:
    path = _directory(root, args["dir"])
    limit, offset = args.get("limit", 50), args.get("offset", 0)
    if not 0 <= limit <= LOG_LIMIT:
        raise _Fail("A0", "limit", f"limit 은 0 이상 {LOG_LIMIT} 이하다")
    if not 0 <= offset < SAFE_INTEGER:
        raise _Fail("A0", "offset", "offset 은 0 이상이다")
    if "until" in args and args["until"] < 0:
        raise _Fail("A0", "until", "until 은 0 이상이다")
    pack = _pack(root, args)
    if "case" not in args and "decisions" not in args:
        raise _Fail("A0", "case", "돌릴 것을 case 나 decisions 로 준다")
    relative, where, _ = _chosen(pack, args)
    case = next((c for c in pack.cases if c.name == args.get("case")), None)
    if not pack.library:
        raise _Fail("A2", pack.name, "모델 베이스가 없는 묶음은 돌릴 수 없다. 구조는 pack_build 로 본다", "not_supported")
    until = args.get("until", case.until if case is not None else None)
    if until is None:
        raise _Fail("A0", "until", f"{where} 에 돌릴 시각이 없다. until 을 준다")
    findings: list = []
    try:
        log, sigma, atoms = P.run(path, case.name if case is not None else None, until,
                                  decisions=None if case is not None else relative, defaults=args.get("defaults"))
    except P.PackError as e:
        # 같은 잘못을 pack_check 와 pack_build 는 더 자세히 알린다. 종류와 자료는 거기서 본다
        raise _Fail(e.code, where, str(e), "run_failed")
    rows = [{"t": t, "at": "/".join(map(str, where)), "port": port, "value": value}
            for t, where, port, value in log[offset:offset + limit]]
    try:
        fingerprint = P.digest(log)
    except (TypeError, ValueError) as e:
        raise _Fail("P6", where, f"모델이 낸 값의 지문을 낼 수 없다: {type(e).__name__}: {e}", "run_stopped")
    return findings, {"variables": sigma, "atoms": atoms, "until": until, "events": len(log),
                      "last": log[-1][0] if log else None, "digest": fingerprint,
                      "offset": offset, "log": rows, "truncated": offset + len(rows) < len(log)}


def _formats(root: str, args: dict) -> tuple:
    """묶음의 파일마다 쓸 수 있는 항목. 적재기가 아는 표를 그대로 낸다."""
    from . import decisions as D
    from . import executor as X
    from . import loader
    return [], {
        "pack": {"file": P.MANIFEST, "keys": sorted(P.KEYS), "model_base": sorted(P.MODEL_BASE_KEYS),
                 "case": sorted(P.CASE_KEYS), "executors": list(P.EXECUTORS), "version": P.VERSION},
        "document": {kind: sorted(keys) for kind, keys in sorted(loader.KEYS.items())},
        "attribute_types": sorted(t.value for t in loader.m.ScalarType),
        "decisions": {"keys": sorted(D._FILE_KEYS), "choose": sorted(D._CHOICE_KEYS), "set": sorted(D._SET_KEYS)},
        "binding": {"keys": sorted(X._BINDING_KEYS), "map": sorted(X._BIND_KEYS)},
        "model": {"base": "ses_core.devs.Atomic",
                  "fill": ["PORTS", "REQUIRED", "PARAMS", "init", "ta", "output", "internal", "external", "confluent"],
                  "param_types": sorted(X._TYPES)},
        "templates": sorted(P.TEMPLATES),
        "example": "pack_new 를 template: full 로 부르면 변수, 없음 대안, 복제, 사례마다 다른 값을 모두 쓰는 묶음이 생긴다. "
                   "그 파일들이 형식의 본보기다",
    }


def _schema(properties: dict, required: tuple) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_DIR = {"type": "string", "description": "묶음의 디렉터리. 작업 자리 안의 상대 경로"}
_CASE = {"type": "string", "description": "pack.yaml 의 cases 에 적힌 사례의 이름"}
_DECISIONS = {"type": "string", "description": "묶음 안의 결정 집합 파일의 상대 경로. case 와 함께 주지 않는다"}

OPERATIONS = {op.name: op for op in (
    Operation(
        "pack_new",
        "돌아가는 묶음을 새 디렉터리에 만들고 바로 검사한다. 새 분야를 시작할 때 한 번 부른다. "
        "만든 파일마다 맨 위에 설명이 있으니 읽고 자기 분야의 것으로 고친다. template 가 minimal 이면 가장 작은 묶음이고, "
        "full 이면 변수, 없음 대안, 복제, 사례마다 다른 값을 모두 쓰는 묶음이다. 형식의 본보기가 필요하면 full 을 쓴다. "
        "비어 있지 않은 디렉터리에는 만들지 않는다.",
        _schema({"dir": {"type": "string", "description": "만들 디렉터리. 작업 자리 안의 상대 경로. 없거나 비어 있어야 한다"},
                 "name": {"type": "string", "description": "묶음의 이름. 영문자, 숫자, 밑줄. 주지 않으면 디렉터리의 이름"},
                 "template": {"type": "string", "enum": ["minimal", "full"], "description": "뼈대의 종류. 기본은 minimal"}},
                ("dir",)),
        "files 만든 파일들. 그 밖에는 pack_check 의 결과와 같다", True, _pack_new),
    Operation(
        "pack_check",
        "묶음이 플랫폼의 계약을 지키는지 본다. 묶음의 파일을 고칠 때마다 부른다. findings 의 error 가 고칠 것이다. "
        "부호는 P0 선언, P1 문서, P2 모델 베이스, P3 바인딩, P4 사례의 결정, P5 조립과 실행 가능성, P6 실행과 기록, "
        "P7 실행기 사이의 일치다. 줄의 kind 가 종류, data 가 자료, next 가 그다음에 할 일이다. 모델이나 문서를 뜻대로 고쳐 "
        "기록이 달라졌다는 줄(kind record_differs, structure_differs)이 나오면 record 를 켜고 다시 부른다. "
        "뜻하지 않은 변화이면 record 를 켜지 말고 원인을 고친다.",
        _schema({"dir": _DIR,
                 "record": {"type": "boolean", "description": "참이면 사례의 기록을 records.yaml 에 적는다. 기본은 거짓"},
                 "executors": {"type": "array", "items": {"type": "string", "enum": list(P.EXECUTORS)},
                               "description": "실행기 사이의 일치를 볼 실행기들. 주지 않으면 쓸 수 있는 것 전부"}}, ("dir",)),
        "name, family(variants, wellformed, scope. scope 가 full 이면 모든 검사를 한 수, core 이면 선택의 핵만 센 수), "
        "cases(사례마다 built, ran, variables, components. 돌린 사례는 atoms, links, events, last, digest, executors. "
        "돌리지 않는 사례는 structure), errors, warnings, record 를 켰으면 recorded(기록이 있는 사례들)",
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
        "variants 가 1 이면 pack_build 가 그 변이를 만든다. 선택의 핵만 본다. 결합과 속성의 검사는 pack_check 가 한다. "
        "문서의 식이 함수를 부르면 모델 베이스 파일을 싣는다.",
        _schema({"dir": _DIR, "case": _CASE, "decisions": _DECISIONS}, ("dir",)),
        "variants, core_wellformed(각각 value, text, exact), points(선택 지점마다 owner, kind, group, state, remaining, "
        "remaining_count, options, options_count). state 는 open, decided, decided_per_place, none_left 가운데 하나. "
        "표는 정의마다 한 줄이다. decided_per_place 는 변이가 하나로 정해졌고 그 정의가 놓인 자리마다 다른 것을 골랐다는 뜻이다",
        False, _pack_choices),
    Operation(
        "pack_build",
        "결정이 끝난 변이 하나의 구조를 만든다. 사례가 뜻한 구조인지, 값이 뜻한 대로인지 확인할 때 부른다. 구성요소마다 "
        "포트, 결합, 문서의 속성 값(attributes), 그리고 묶인 모델과 그 모델이 실제로 받는 값(module, params)을 낸다. "
        "결정이 모자라면 무엇이 정해지지 않았는지를 P4 의 undecided 로 알린다. 모델을 돌리지는 않는다. "
        "모델 베이스 파일은 싣는다.",
        _schema({"dir": _DIR, "case": _CASE, "decisions": _DECISIONS,
                 "defaults": {"type": "boolean", "description": "정해지지 않은 곳에 문서의 기본값을 쓴다. 주지 않으면 사례의 선언을 따른다"},
                 "depth": {"type": "integer", "description": "이 깊이까지만 낸다. 뿌리가 0"},
                 "limit": {"type": "integer", "description": f"낼 구성요소의 수. 기본 200, 최대 {COMPONENTS_LIMIT}"}}, ("dir",)),
        "variables, components, nodes, structure(구조의 지문), tree(구성요소마다 name, labels, attributes, ports, absent, parts. "
        "부분이 있으면 couplings, 모델에 묶였으면 module 과 params, 잘렸으면 parts_not_listed), truncated",
        False, _pack_build),
    Operation(
        "pack_run",
        "변이 하나를 참조 시뮬레이터로 돌려 출력 사건을 낸다. 모델의 행동을 볼 때 부른다. 기록은 적지 않는다. "
        "돌릴 것은 선언의 사례(case)나 묶음 안의 결정 집합 파일(decisions) 가운데 하나로 준다. 값을 바꿔 가며 여러 번 "
        "돌리려면 결정 집합 파일을 적어 decisions 로 준다. 그때는 until 을 꼭 준다. "
        "사건이 많으면 offset 과 limit 으로 나눠 읽는다. digest 는 기록 전체의 지문이고 pack_check 가 견주는 것과 같다. "
        "기록에는 출력 사건만 있다. 모델 안의 상태를 보려면 모델이 포트로 내게 한다. ok 가 거짓이면 result 는 null 이다.",
        _schema({"dir": _DIR, "case": _CASE, "decisions": _DECISIONS,
                 "defaults": {"type": "boolean", "description": "정해지지 않은 곳에 문서의 기본값을 쓴다. 주지 않으면 사례의 선언을 따른다"},
                 "until": {"type": "number", "description": "이 시각까지 돌린다. 주지 않으면 사례에 적힌 시각"},
                 "offset": {"type": "integer", "description": "이 번째 사건부터 낸다. 기본 0"},
                 "limit": {"type": "integer", "description": f"낼 사건의 수. 기본 50, 최대 {LOG_LIMIT}"}}, ("dir",)),
        "variables, atoms, until, events, last, digest, offset, log(사건마다 t, at, port, value), truncated",
        False, _pack_run),
    Operation(
        "formats",
        "묶음의 파일마다 쓸 수 있는 항목의 이름을 낸다. 선언, 문서, 결정 집합, 바인딩, 모델이 채우는 것. 형식을 모를 때 부른다. "
        "본보기가 필요하면 pack_new 를 template: full 로 부른다.",
        _schema({}, ()),
        "pack, document, attribute_types, decisions, binding, model, templates, example",
        False, _formats),
)}

_FINDING = {
    "type": "object",
    "properties": {"severity": {"type": "string", "enum": ["error", "warning", "info"]},
                   "code": {"type": "string"}, "where": {"type": "string"}, "message": {"type": "string"},
                   "kind": {"type": "string"}, "data": {"type": "object"}, "next": {"type": "string"}},
    "required": ["severity", "code", "where", "message"], "additionalProperties": False}

ENVELOPE = {
    "type": "object",
    "properties": {
        "op": {"type": "string"},
        "version": {"type": "string"},
        "ok": {"type": "boolean"},
        "findings": {"type": "array", "items": _FINDING},
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
    return {"version": VERSION, "envelope": ENVELOPE, "kinds": dict(NEXT),
            "operations": [{"name": op.name, "description": op.description, "input_schema": op.input_schema,
                            "result": op.result, "writes": op.writes} for op in OPERATIONS.values()]}


def call(name: str, args: Optional[dict] = None, root: Optional[str] = None) -> dict:
    """연산 하나를 부른다. 늘 봉투를 돌려주고 예외를 내지 않는다. root 는 작업 자리이고 주지 않으면 지금 디렉터리다."""
    env = {"op": _text(name)[:80], "version": VERSION, "ok": False, "findings": [], "result": None, "output": ""}
    try:
        return _call(env, name, args, root)
    except KeyboardInterrupt:
        raise
    except BaseException as e:                               # noqa: BLE001  무엇이 나도 봉투를 낸다
        env.update(ok=False, result=None, findings=[_line(
            "error", "A9", env["op"], f"도구의 결함이다. 이 입력과 함께 알려 달라: {type(e).__name__}: {_text(e)[:500]}", "tool_fault")])
        return env


def _call(env: dict, name, args, root) -> dict:
    op = OPERATIONS.get(name) if isinstance(name, str) else None
    if op is None:
        env["findings"] = [_line("error", "A1", env["op"], f"그런 연산이 없다. 있는 연산은 {sorted(OPERATIONS)} 다",
                                 "unknown_operation", operations=sorted(OPERATIONS))]
        return env
    args = {} if args is None else args
    bad = problems(op.input_schema, args)
    if bad:
        env["findings"] = [_line("error", "A0", op.name, line, "input") for line in bad[:FINDINGS_LIMIT]]
        return env
    seen = io.StringIO()
    findings, result = [], None
    try:
        with contextlib.redirect_stdout(seen), P.quiet_bytecode():       # 묶음의 코드가 찍는 것이 결과에 섞이지 않게
            findings, result = op.run(os.path.abspath(root or os.getcwd()), args)
        result = _plain(result)
    except _Fail as e:
        findings, result = list(findings) + [e.finding], None
    except KeyboardInterrupt:
        raise
    except SystemExit as e:
        findings, result = [_line("error", "P2", op.name, f"묶음의 코드가 프로세스를 끝내려 했다(SystemExit {_shown(e.code)}). "
                                  "모델 베이스에서 exit 를 부르지 않는다", "pack_code_exit")], None
    except MemoryError:
        findings, result = [_line("error", "A2", op.name, "기억이 모자라다. 묶음의 파일이나 변수의 범위가 지나치게 크다", "limit")], None
    except RecursionError:
        findings, result = [_line("error", "A2", op.name, "값이 너무 깊이 겹쳐 있다. 묶음의 파일이나 모델이 내는 값을 본다", "limit")], None
    except Exception as e:                                   # noqa: BLE001  도구의 결함이다. 예외를 밖으로 내지 않는다
        findings, result = [_line("error", "A9", op.name, f"도구의 결함이다. 이 입력과 함께 알려 달라: {type(e).__name__}: "
                                  f"{_text(e)[:500]}", "tool_fault")], None
    except BaseException as e:                               # noqa: BLE001  묶음의 코드가 낸 잡을 수 없는 예외
        findings, result = [_line("error", "P2", op.name, f"묶음의 코드가 잡을 수 없는 예외를 냈다: {type(e).__name__}. "
                                  "모델 베이스에서 BaseException 을 직접 내지 않는다", "pack_code_exit")], None
    try:
        text = seen.getvalue()
    except ValueError:                                       # 묶음의 코드가 표준 출력을 닫았다
        text = ""
    env["output"] = text if len(text) <= OUTPUT_LIMIT else "(앞은 잘렸다) " + text[-OUTPUT_LIMIT:]
    lines = [_plain(f) for f in findings]
    if len(lines) > FINDINGS_LIMIT:                          # 줄이 지나치게 많으면 오류를 앞세워 자르고 그 수를 알린다
        lines.sort(key=lambda f: {"error": 0, "warning": 1}.get(f["severity"], 2))
        rest = len(lines) - FINDINGS_LIMIT + 1
        lines = lines[:FINDINGS_LIMIT - 1] + [_line("info", "A2", op.name, f"줄이 {rest}건 더 있다. 앞의 것을 고치고 다시 부른다",
                                                    "limit", more=rest)]
    env["findings"] = lines
    env["result"] = result
    env["ok"] = not _failed(lines)
    return env
