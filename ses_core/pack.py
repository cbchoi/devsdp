"""분야 묶음 (docs/ses-platform/20_packs.md).

묶음은 연구자가 자기 분야를 이 플랫폼에 올리는 단위다. 디렉터리 하나이고, 그 안의 pack.yaml 이 무엇이
어디 있는지를 적는다. 묶음에 드는 것은 다음과 같다.

- 정준 SES 문서 하나. 그 분야의 구조의 족이다.
- 분야 프로파일(선택). 그 분야의 어휘와 규칙이다.
- 모델 베이스(선택). 원자 모델들과, 문서의 식이 부르는 함수들이다. 파이썬 파일 하나다.
- 바인딩. 정의를 모델 베이스의 모듈에 잇고 시간 단위를 적는다.
- 사례들. 결정 집합 하나가 변이 하나를 정한다. 돌릴 시각을 적으면 돌려 본다.
- 실험(선택). 연구자의 스크립트다. 검사는 파일이 있는지만 본다.

플랫폼이 묶음에 요구하는 것은 check 가 본다. 통과한 묶음은 다른 사람의 컴퓨터에서 같은 결과를 낸다.
모델의 계약은 공통 모델 기반(ses_core.devs.Atomic)이다. 그것을 지킨 모델 베이스는 참조 시뮬레이터,
pyevsim, cevsim 에서 같은 기록을 낸다(15 문서의 Z1, 16 문서의 U5).

검사의 부호
  P0 선언(pack.yaml)        P1 문서                P2 모델 베이스         P3 바인딩
  P4 사례의 결정            P5 조립과 실행 가능성   P6 실행과 기록         P7 실행기 사이의 일치
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Mapping, Optional

MANIFEST = "pack.yaml"
RECORDS = "records.yaml"
VERSION = "1.0"
EXECUTORS = ("devs", "pyevsim", "cevsim")
KEYS = {"pack", "name", "title", "document", "profile", "model_base", "binding", "executors", "cases", "experiments"}
MODEL_BASE_KEYS = {"file", "library", "functions", "native"}
CASE_KEYS = {"name", "decisions", "defaults", "until", "max_steps", "doc"}
MAX_STEPS = 1000000                 # 사례를 돌릴 때의 걸음 수의 한도. 사례의 max_steps 로 바꾼다


# 실행기 사이의 일치를 본 결과. 사람에게 보이는 글이다. 기계가 읽는 이름은 ops.py 가 붙인다
REFERENCE, SAME, DIFFERENT, SKIPPED = "기준", "같다", "다르다", "건너뜀"
SKIPPED_NATIVE, VIOLATES, STOPPED = "건너뜀(특정 엔진의 모듈이 들어 있다)", "규약 위반", "멈춤"


class PackError(Exception):
    """묶음의 선언을 읽을 수 없거나 사례를 돌릴 수 없다. code 는 검사의 부호(P0 에서 P7)다."""

    def __init__(self, message: str, code: str = "P0") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Case:
    name: str
    decisions: Optional[str] = None     # 결정 집합의 파일. 없으면 문서의 기본값으로 정해져야 한다
    defaults: bool = False              # 정해지지 않은 곳에 문서의 기본값을 쓰는가
    until: Optional[float] = None       # 이 시각까지 돌린다. 없으면 계획까지만 만든다
    max_steps: int = MAX_STEPS          # 걸음 수의 한도. 끝나지 않는 모델을 멈추기 위한 것이다


@dataclass(frozen=True)
class Pack:
    root: str
    name: str
    document: str
    title: str = ""
    profile: Optional[str] = None
    model_file: Optional[str] = None
    library: Optional[str] = None       # 모델 베이스 파일 안의 모듈 라이브러리의 이름
    functions: Optional[str] = None     # 모델 베이스 파일 안의 함수 사전의 이름
    native: tuple = ()                  # 공통 모델 기반이 아닌 모듈들. 특정 엔진의 것이다
    binding: Optional[str] = None
    executors: tuple = EXECUTORS
    cases: tuple = ()
    experiments: tuple = ()

    def path(self, relative: str) -> str:
        return os.path.join(self.root, relative)


@dataclass(frozen=True)
class Finding:
    severity: str                       # error, warning, info
    code: str                           # P0 에서 P7
    where: str                          # 파일, 모듈, 사례의 이름
    message: str


@dataclass
class Report:
    pack: Optional[Pack]
    findings: list = field(default_factory=list)
    family: Optional[tuple] = None      # (변이 수, 적격 변이 수). 구하지 못했으면 None
    cases: dict = field(default_factory=dict)       # 사례 이름에서 그 사례의 요약으로

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def of(self, code: str) -> list:
        return [f for f in self.findings if f.code == code]


# ---------------------------------------------------------------------------
# 선언을 읽는다
# ---------------------------------------------------------------------------

def _inside(root: str, relative, what: str) -> str:
    """묶음 안의 파일인가. 묶음은 디렉터리째 옮겨도 돌아야 하므로 밖을 가리키지 못한다."""
    if not isinstance(relative, str) or not relative:
        raise PackError(f"{what}: 파일의 경로를 글로 적어야 한다")
    if os.path.isabs(relative) or ".." in relative.replace("\\", "/").split("/"):
        raise PackError(f"{what}: {relative} 는 묶음 밖을 가리킨다. 묶음 안의 상대 경로로 적는다")
    if not os.path.isfile(os.path.join(root, relative)):
        raise PackError(f"{what}: 파일 {relative} 가 없다")
    return relative


def load(root: str) -> Pack:
    """디렉터리 root 의 묶음을 읽는다. 선언이 틀렸으면 PackError 를 낸다."""
    import yaml
    path = os.path.join(root, MANIFEST)
    if not os.path.isfile(path):
        raise PackError(f"{root} 에 {MANIFEST} 가 없다. 묶음이 아니다")
    try:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PackError(f"{MANIFEST} 를 읽을 수 없다: {str(e).splitlines()[0]}")
    if not isinstance(d, dict):
        raise PackError(f"{MANIFEST} 는 이름과 값의 표여야 한다")
    unknown = sorted(set(d) - KEYS)
    if unknown:
        raise PackError(f"{MANIFEST} 에 모르는 항목이 있다: {unknown}. 쓸 수 있는 것은 {sorted(KEYS)} 다")
    if str(d.get("pack")) != VERSION:
        raise PackError(f'{MANIFEST} 의 첫 항목은 pack: "{VERSION}" 이어야 한다')
    name = d.get("name")
    if not isinstance(name, str) or not name.isidentifier():
        raise PackError("name: 묶음의 이름을 글자, 숫자, 밑줄로 적는다")
    if "document" not in d:
        raise PackError("document: SES 문서의 파일을 적어야 한다")
    document = _inside(root, d["document"], "document")
    profile = _inside(root, d["profile"], "profile") if d.get("profile") else None
    mb = d.get("model_base") or {}
    if not isinstance(mb, dict) or set(mb) - MODEL_BASE_KEYS:
        raise PackError(f"model_base: 쓸 수 있는 항목은 {sorted(MODEL_BASE_KEYS)} 다")
    model_file = _inside(root, mb["file"], "model_base.file") if mb else None
    if mb and "file" not in mb:
        raise PackError("model_base.file: 모델 베이스의 파이썬 파일을 적어야 한다")
    library = mb.get("library", "LIBRARY" if mb and "functions" not in mb else None) if mb else None
    functions = mb.get("functions") if mb else None
    native = tuple(mb.get("native") or ()) if mb else ()
    binding = _inside(root, d["binding"], "binding") if d.get("binding") else None
    if library and not binding:
        raise PackError("binding: 모듈 라이브러리가 있으면 정의를 모듈에 잇는 바인딩이 있어야 한다")
    if binding and not library:
        raise PackError("model_base: 바인딩이 있으면 모듈 라이브러리가 있어야 한다")
    executors = tuple(d.get("executors") or EXECUTORS)
    bad = [x for x in executors if x not in EXECUTORS]
    if bad or "devs" not in executors:
        raise PackError(f"executors: {list(EXECUTORS)} 가운데에서 고르고 devs(참조 시뮬레이터)는 늘 든다")
    cases = []
    for i, c in enumerate(d.get("cases") or ()):
        if not isinstance(c, dict) or set(c) - CASE_KEYS or not isinstance(c.get("name"), str):
            raise PackError(f"cases[{i}]: 사례는 name 을 가지고, 쓸 수 있는 항목은 {sorted(CASE_KEYS)} 다")
        until = c.get("until")
        if until is not None and (isinstance(until, bool) or not isinstance(until, (int, float)) or until < 0):
            raise PackError(f"cases[{i}].until: 돌릴 시각은 0 이상의 수여야 한다")
        if until is not None and not library:
            raise PackError(f"cases[{i}].until: 돌리려면 모델 베이스와 바인딩이 있어야 한다")
        steps = c.get("max_steps", MAX_STEPS)
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
            raise PackError(f"cases[{i}].max_steps: 걸음 수의 한도는 1 이상의 정수여야 한다")
        cases.append(Case(c["name"], _inside(root, c["decisions"], f"cases[{i}].decisions") if c.get("decisions") else None,
                          bool(c.get("defaults", False)), None if until is None else float(until), steps))
    names = [c.name for c in cases]
    if len(set(names)) != len(names):
        raise PackError("cases: 사례의 이름은 서로 달라야 한다")
    experiments = tuple(_inside(root, x, "experiments") for x in (d.get("experiments") or ()))
    return Pack(os.path.abspath(root), name, document, str(d.get("title") or ""), profile, model_file, library,
                functions, native, binding, executors, tuple(cases), experiments)


def module(pack: Pack):
    """묶음의 모델 베이스 파일을 싣는다. 부를 때마다 파일을 다시 읽는다.

    묶음마다 다른 이름으로 싣고, 싣는 동안 불러온 묶음 안의 보조 파일은 끝나면 모듈 표에서 뺀다. 그래서 두 묶음이
    같은 이름의 보조 파일을 가져도 섞이지 않고, 파일을 고친 뒤 다시 실으면 고친 것이 읽힌다. 싣는 동안에는
    바이트코드 파일을 쓰지 않는다. 검사는 묶음의 디렉터리에 아무것도 남기지 않는다.
    """
    path = pack.path(pack.model_file)
    name = "ses_pack_" + pack.name + "_" + hashlib.sha256(path.encode()).hexdigest()[:8]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    before = set(sys.modules)
    sys.modules[name] = mod
    sys.path.insert(0, pack.root)                            # 묶음 안의 다른 파일을 불러 쓸 수 있게
    quiet, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = quiet
        sys.path.remove(pack.root)
        inside = os.path.join(os.path.realpath(pack.root), "")
        for other in set(sys.modules) - before - {name}:
            file = getattr(sys.modules[other], "__file__", None)
            if file and os.path.realpath(file).startswith(inside):
                del sys.modules[other]
    return mod


# ---------------------------------------------------------------------------
# 기록
# ---------------------------------------------------------------------------

def digest(log: list) -> str:
    """사건 기록의 지문. 같은 기록이면 어느 컴퓨터에서나 같다."""
    rows = [[t, "/".join(map(str, path)), port, value] for t, path, port, value in log]
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def summary(log: list, until: float) -> dict:
    return {"until": until, "events": len(log), "last": log[-1][0] if log else None, "digest": digest(log)}


def read_records(pack: Pack) -> dict:
    import yaml
    path = pack.path(RECORDS)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def structure_digest(built) -> str:
    """만든 변이의 구조의 지문. 구성요소, 포트, 결합, 속성의 값, 변수의 값을 담는다."""
    from .extension import interpret
    whole = {"variables": dict(built.sigma), "structure": interpret(built.layered, built.variant)}
    text = json.dumps(whole, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_records(pack: Pack, records: dict) -> None:
    lines = ["# 사례의 기록의 요약. ses pack check --record 가 적는다. 손으로 고치지 않는다.",
             "# 돌린 사례는 참조 시뮬레이터의 사건 기록의 지문을, 돌리지 않는 사례는 만든 구조의 지문을 적는다.",
             "# 모델 베이스나 문서를 고쳐 기록이 달라지면 검사가 알린다. 뜻한 변화이면 다시 적는다."]
    for name in sorted(records):
        r = records[name]
        if "structure" in r:
            lines.append(f"{name}: {{structure: \"{r['structure']}\"}}")
            continue
        lines.append(f"{name}: {{until: {r['until']}, events: {r['events']}, "
                     f"last: {'null' if r['last'] is None else r['last']}, digest: \"{r['digest']}\"}}")
    with open(pack.path(RECORDS), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 검사
# ---------------------------------------------------------------------------

def _interface(name: str, mod, unit: Optional[float], say) -> None:
    """모듈 하나가 공통 모델 기반의 계약을 지키는가. 인터페이스의 선언과 처음 상태만 본다."""
    from .devs import INF, Atomic
    from .executor import _TYPES
    body = mod.body
    if not (isinstance(body, type) and issubclass(body, Atomic)):
        say("error", "P2", name, "공통 모델 기반(ses_core.devs.Atomic 의 하위 클래스)이 아니다. 특정 엔진의 모델이면 "
                                 "pack.yaml 의 model_base.native 에 이름을 적는다. 그 모듈은 다른 실행기에서 돌지 않는다")
        return
    for port, decl in mod.ports.items():
        if not (isinstance(decl, tuple) and len(decl) == 2 and decl[1] in ("in", "out")):
            say("error", "P2", name, f"포트 {port} 의 선언은 (타입, 'in' 또는 'out') 이어야 한다: {decl!r}")
    ins = {p for p, decl in mod.ports.items() if isinstance(decl, tuple) and len(decl) == 2 and decl[1] == "in"}
    outs = set(mod.ports) - ins
    for port in mod.required:
        if port not in ins:
            say("error", "P2", name, f"REQUIRED 의 {port} 는 입력 포트가 아니다")
    defaults = {}
    for param, decl in mod.params.items():
        if not (isinstance(decl, tuple) and 1 <= len(decl) <= 2 and decl[0] in _TYPES):
            say("error", "P2", name, f"매개변수 {param} 의 선언은 (타입,) 또는 (타입, 기본값) 이고 타입은 "
                                     f"{sorted(_TYPES)} 가운데 하나다: {decl!r}")
            return
        if len(decl) == 2:
            defaults[param] = decl[1]
    if len(defaults) < len(mod.params):
        return                                               # 기본값이 없는 매개변수가 있다. 만들어 보지 않는다
    try:
        atom = body("check", **defaults)
        ta = atom.ta()
        if isinstance(ta, bool) or not isinstance(ta, (int, float)) or ta != ta or ta < 0:
            say("error", "P2", name, f"처음 상태의 ta() 가 0 이상의 수나 INF 가 아니다: {ta!r}")
        elif ta != INF:                                      # 시간 단위의 정수배인지는 실제 값으로 본다(P5 의 B5, P6)
            out = atom.output()
            if not isinstance(out, dict):
                say("error", "P2", name, f"output() 은 포트 이름에서 값의 목록으로 가는 사전을 내야 한다: {out!r}")
            else:
                for port, values in out.items():
                    if port not in outs:
                        say("error", "P2", name, f"output() 이 선언하지 않은 출력 포트 {port} 로 낸다")
                    elif not isinstance(values, (list, tuple)):
                        say("error", "P2", name, f"output() 의 포트 {port} 의 값은 목록이어야 한다: {values!r}")
    except Exception as e:                                   # noqa: BLE001  모델의 코드가 낸 것은 무엇이든 알린다
        say("error", "P2", name, f"기본값으로 만들어 처음 상태를 볼 수 없다: {type(e).__name__}: {e}")


def _engine(name: str):
    """다른 실행기 하나. (실행기, 쓸 수 없는 까닭). 쓸 수 없으면 실행기의 자리에 None."""
    if name == "pyevsim":
        try:
            from .pyevsim_executor import PyevsimExecutor
        except ImportError:
            return None, "pyevsim 이 설치되어 있지 않다"
        return PyevsimExecutor(), None
    from . import cevsim_executor as C
    home = os.environ.get("CEVSIM_HOME", "")
    if not home or not C.available(home):
        return None, "cevsim 의 소스(환경 변수 CEVSIM_HOME)나 C++ 컴파일러가 없다"
    return C.CevsimExecutor(home), None


def _first_difference(a: list, b: list) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"{i}번째 사건이 다르다. 참조 {x!r}, 이 실행기 {y!r}"
    return f"사건의 수가 다르다. 참조 {len(a)}개, 이 실행기 {len(b)}개"


FAILED = object()                       # 읽거나 만들지 못했다는 표지. 까닭은 say 로 적었다


def model_base(pack: Pack, say) -> tuple:
    """묶음의 모델 베이스에서 (모듈 라이브러리, 함수 사전). 없거나 읽지 못한 것은 None 이고 까닭을 P2 로 적는다."""
    from . import executor as X
    library, functions = None, None
    if not pack.model_file:
        return library, functions
    try:
        mod = module(pack)
    except (Exception, SystemExit) as e:                     # noqa: BLE001  묶음의 코드가 낸 것은 무엇이든 알린다
        say("error", "P2", pack.model_file, f"모델 베이스를 실을 수 없다: {type(e).__name__}: {e}")
        return library, functions
    if pack.functions:
        functions = getattr(mod, pack.functions, None)
        if not isinstance(functions, Mapping) or not all(callable(f) for f in functions.values()):
            say("error", "P2", pack.model_file, f"{pack.functions} 는 이름에서 함수로 가는 사전이어야 한다")
            functions = None
    if pack.library:
        library = getattr(mod, pack.library, None)
        if not isinstance(library, Mapping) or not all(isinstance(m, X.Module) for m in library.values()):
            say("error", "P2", pack.model_file, f"{pack.library} 는 모듈의 이름에서 모듈로 가는 사전이어야 한다. "
                                               "ses_core.devs.module_of(클래스) 로 만든다")
            library = None
    return library, functions


def document(pack: Pack, say) -> tuple:
    """묶음의 (문서, 프로파일). 읽지 못한 것은 None 이고 까닭을 P1 로 적는다."""
    from .loader import LoadError, load_ses
    from .profile import load_profile
    doc = profile = None
    try:
        profile = load_profile(pack.path(pack.profile)) if pack.profile else None
    except Exception as e:                                   # noqa: BLE001
        say("error", "P1", pack.profile, f"프로파일을 읽을 수 없다: {type(e).__name__}: {e}")
    try:
        doc = load_ses(pack.path(pack.document))
    except LoadError as e:
        say("error", "P1", pack.document, f"문서를 적재할 수 없다. {e}")
    except Exception as e:                                   # noqa: BLE001
        say("error", "P1", pack.document, f"문서를 읽을 수 없다: {type(e).__name__}: {e}")
    return doc, profile


def decisions_of(pack: Pack, relative: Optional[str], where: str, doc, say):
    """묶음 안의 결정 집합 하나. relative 가 없으면 None, 읽지 못했거나 다른 문서의 것이면 FAILED (P4)."""
    from .decisions import DecisionError, load_decisions
    if not relative:
        return None
    try:
        ds = load_decisions(pack.path(relative))
    except DecisionError as e:
        say("error", "P4", where, f"결정 집합의 모양이 틀렸다. {e}")
        return FAILED
    except Exception as e:                                   # noqa: BLE001
        say("error", "P4", where, f"결정 집합을 읽을 수 없다: {type(e).__name__}: {str(e).splitlines()[0]}")
        return FAILED
    if ds.target is not None and ds.target != doc.name:
        say("error", "P4", where, f"결정 집합의 target 이 {ds.target} 인데 문서의 이름은 {doc.name} 이다")
        return FAILED
    return ds


def build_variant(doc, ds, profile, functions, defaults: bool, where: str, say):
    """결정 집합이 정하는 변이 하나를 만든다. 만들지 못하면 FAILED 이고 까닭을 P4 로 적는다."""
    from . import direct
    from .algebra import AlgebraError
    try:
        built = direct.build(doc, ds, profile=profile, functions=functions, use_defaults=defaults, infer=True)
    except direct.Undecided as e:
        say("error", "P4", where, f"결정이 모자라다. {e}")
        return FAILED
    except direct.Contradiction as e:
        say("error", "P4", where, f"만들 수 없다. {e}")
        return FAILED
    except AlgebraError as e:
        say("error", "P4", where, f"결정 집합이 문서에 맞지 않다. {e}")
        return FAILED
    for key in built.unused:
        say("warning", "P4", where, "쓰이지 않은 결정: " + "/".join(str(k) for k in key))
    return built


def shown(built, found: list) -> list:
    """위반들을 사람이 읽는 줄로. 나무의 경로 대신 구성요소 경로로 적는다."""
    from .algebra import ENT
    from .skeleton import component_path
    T = built.layered.ses.tree
    out = []
    for layer, code, path, msg in found:
        where = component_path(T, path) if T.kinds.get(path) == ENT else path
        out.append(f"{layer} {code} {'/'.join(map(str, where))}: {msg}")
    return out


def _longer(e: BaseException) -> str:
    """걸음 수의 한도에 걸렸을 때 덧붙이는 말."""
    return ". 더 길게 돌리려면 pack.yaml 의 그 사례에 max_steps 를 적는다" if "정해진 걸음 수" in str(e) else ""


def components_of(built) -> int:
    """만든 변이의 구성요소의 수."""
    from .skeleton import skeleton
    sk = skeleton(built.layered.ses.tree, built.layered.void, built.variant)

    def count(c) -> int:
        return 1 + sum(count(x) for x in c.parts.values())

    return count(sk) if sk is not None else 0


def few(lines: list, limit: int = 8) -> list:
    """줄이 많으면 앞의 몇 줄과 나머지의 수만 낸다. 복제본마다 같은 잘못이 되풀이될 때를 위해서다."""
    if len(lines) <= limit:
        return lines
    return lines[:limit - 1] + [f"같은 종류의 줄이 {len(lines) - limit + 1}건 더 있다. 앞의 것을 고치고 다시 본다"]


def unconsumed(doc, binding, library: Mapping, plan: dict, atoms: list, told: set) -> list:
    """모델에 전해지지 않는 속성들. 묶인 원자 구성요소의 정의가 가진 속성 가운데 모듈의 매개변수가 아닌 것이다.

    속성의 이름을 잘못 적으면 모델은 아무 말 없이 기본값으로 돈다. 그것을 알리려는 것이다. 문서의 식은 속성을
    읽지 않으므로 모델에 가지 않는 속성은 설명으로만 남는다. 뜻한 것이면 경고를 그대로 둔다.
    """
    from . import structure as st
    out = []
    for p in atoms:
        node = st.subtree(plan, p)
        mod = library.get(node.get("module"))
        if mod is None:
            continue
        labels = [x for x in node.get("labels", ()) if x in doc.entities]
        renamed = {a for x in labels if x in binding.map for a in binding.map[x].params.values()}
        for label in labels:
            for attr in doc.entities[label].attributes:
                if attr in mod.params or attr in renamed or (label, attr) in told:
                    continue
                told.add((label, attr))
                out.append(f"정의 {label} 의 속성 {attr} 은 모듈 {mod.name} 의 매개변수가 아니다. 모델에 전해지지 않는다. "
                           f"모듈의 매개변수는 {sorted(mod.params)} 다")
    return out


def check(root: str, record: bool = False, executors: Optional[tuple] = None) -> Report:
    """묶음을 검사한다. record 이면 사례의 기록을 records.yaml 에 적는다.

    executors 를 주면 그 실행기들에서만 실행기 사이의 일치를 본다. 주지 않으면 선언에 적힌 것 가운데
    이 컴퓨터에서 쓸 수 있는 것을 모두 본다.
    """
    try:
        pack = load(root)
    except PackError as e:
        return Report(None, [Finding("error", "P0", MANIFEST, str(e))])
    report = Report(pack)

    def say(severity: str, code: str, where: str, message: str) -> None:
        report.findings.append(Finding(severity, code, where, message))

    from . import edit
    from . import executor as X
    from . import structure as st
    from .devs import DevsExecutor, simulate
    from .diagnose import analyze
    from .extension import violations

    # P2 모델 베이스 (문서의 식이 부르는 함수가 여기 있으므로 문서보다 먼저 싣는다) -------------
    library, functions = model_base(pack, say)

    # P1 문서 ---------------------------------------------------------------------------------
    doc, profile = document(pack, say)
    if doc is not None:
        a = analyze(edit.load(pack.path(pack.document)), profile, functions=functions)
        broken = False
        for d in a.diagnostics:
            text = f"{d.code} {d.address or '-'}: {d.message}"
            if d.severity == "error" and d.scope == "family":
                # 족의 어떤 변이가 규칙을 어긴다. 족을 좁혀 가는 중에는 흔한 일이다. 사례로 고른 변이는 따로 본다
                say("warning", "P1", pack.document, "적격이 아닌 변이가 있다. " + text)
            elif d.severity in ("error", "warning"):
                say(d.severity, "P1", pack.document, text)
                broken = broken or d.severity == "error"
        if a.variants is not None:
            report.family = (a.variants, a.wellformed)
        elif a.core is not None:
            report.family = (a.core.variants, a.core.wellformed)
        if report.family is not None and not broken and report.family[1] == 0:
            say("error", "P1", pack.document, f"변이 {report.family[0]}개 가운데 적격인 것이 하나도 없다")
        if broken:
            doc = None                                       # 문서가 틀렸으면 사례를 보지 않는다

    # P3 바인딩 -------------------------------------------------------------------------------
    binding = None
    if pack.binding:
        try:
            binding = X.load_binding(pack.path(pack.binding))
        except Exception as e:                               # noqa: BLE001
            say("error", "P3", pack.binding, f"바인딩을 읽을 수 없다: {type(e).__name__}: {e}")
    if binding is not None and doc is not None:
        if binding.target is not None and binding.target != doc.name:
            say("error", "P3", pack.binding, f"target 이 {binding.target} 인데 문서의 이름은 {doc.name} 이다")
        for name, bind in binding.map.items():
            if name not in doc.entities:
                say("error", "P3", pack.binding, f"문서에 없는 정의 {name} 를 묶었다")
            if library is not None and bind.module not in library:
                say("error", "P3", pack.binding, f"정의 {name} 를 묶은 모듈 {bind.module} 이 라이브러리에 없다")

    # P2 모듈마다의 계약 ----------------------------------------------------------------------
    if library is not None:
        unit = binding.time_unit if binding is not None and binding.time_unit is not None else 1.0
        for name in pack.native:
            if name not in library:
                say("error", "P2", name, "model_base.native 에 적힌 모듈이 라이브러리에 없다")
        for name, mod_ in library.items():
            if name not in pack.native:
                _interface(name, mod_, unit, say)

    # 사례 ------------------------------------------------------------------------------------
    records = read_records(pack)
    new_records = dict(records)
    skipped: set = set()
    if doc is not None and library is not None and any(c.until is not None for c in pack.cases):
        for name in pack.executors:                          # 이 컴퓨터에 없는 실행기는 사례를 보기 전에 한 번 알린다
            if name != "devs" and (executors is None or name in executors):
                engine, why = _engine(name)
                if engine is None:
                    skipped.add(name)
                    say("info", "P7", name, f"이 실행기에서는 돌리지 않았다. {why}")
    told: set = set()                                        # 이미 알린 (정의, 속성). 사례마다 되풀이하지 않는다
    can_run = doc is not None and not report.of("P2") and not [f for f in report.of("P3") if f.severity == "error"]
    for case in pack.cases if doc is not None else ():
        info: dict = {}
        report.cases[case.name] = info
        ds = decisions_of(pack, case.decisions, case.name, doc, say)
        if ds is FAILED:
            continue
        built = build_variant(doc, ds, profile, functions, case.defaults, case.name, say)
        if built is FAILED:
            continue
        V = built.variant
        info["variables"] = dict(built.sigma)

        info["components"] = components_of(built)

        def keep_structure() -> None:
            """돌리지 않는 사례. 만든 구조의 지문을 적어 둔 것과 견준다."""
            mine = {"structure": structure_digest(built)}
            info["structure"] = mine["structure"]
            old = records.get(case.name)
            if record:
                new_records[case.name] = mine
            elif old is None:
                say("warning", "P6", case.name, "적어 둔 기록이 없다. ses pack check --record 로 적는다")
            elif old != mine:
                say("error", "P6", case.name, f"구조가 적어 둔 것과 다르다. 적어 둔 지문은 {old.get('structure') or old.get('digest')}, "
                                              f"지금은 {mine['structure']} 이다. 뜻한 변화이면 --record 로 다시 적는다")

        found = violations(built.layered, V)
        for line in few(shown(built, found)):
            say("error", "P5", case.name, "이 변이는 조립되지 않는다. " + line)
        if found:
            continue
        if not pack.library:                                 # 구조만 가진 묶음. 모델 베이스를 선언하지 않았다
            keep_structure()
            continue
        if library is None or binding is None or not can_run:
            continue                                         # 모델 베이스나 바인딩에 오류가 있다. 위에서 알렸다
        dx = DevsExecutor()
        L, ext = X.attach(built.layered, dx, binding, library)
        found = violations(X.alone(L, ext), V)
        for line in few(shown(built, found)):
            say("error", "P5", case.name, "이 변이는 실행 가능하지 않다. " + line)
        if found:
            continue
        plan = X.plan(L, ext, V)
        atoms = X.frontier(plan)
        info["atoms"], info["links"] = len(atoms), sum(st.flatten(plan).values())
        portable = all(st.subtree(plan, p).get("module") not in pack.native for p in atoms)
        extra: dict = {}                                     # 모델에만 있는 포트: (모듈, 포트)에서 자리들로
        for p in atoms:
            node = st.subtree(plan, p)
            mod = library.get(node.get("module"))
            for port in sorted(set(mod.ports) - set(node["ports"])) if mod is not None else ():
                extra.setdefault((mod.name, port), []).append("/".join(p))
        for (mod_name, port), places in extra.items():
            say("error", "P5", case.name, f"{places[0]}" + (f" 등 {len(places)}곳" if len(places) > 1 else "")
                + f": 모듈 {mod_name} 의 포트 {port} 가 문서의 그 정의에 없다. 모델의 PORTS 에 적은 포트는 문서의 ports 에도 적는다")
        for line in unconsumed(doc, binding, library, plan, atoms, told):
            say("warning", "P5", case.name, line)
        if extra:
            continue
        if case.until is None:
            keep_structure()
            continue

        # P6 실행과 기록 ----------------------------------------------------------------------
        def run_reference(probe: Optional[list] = None) -> list:
            return simulate(X.realize(L, ext, dx, V), case.until, max_steps=case.max_steps, probe=probe)

        touched: list = []
        try:
            log = run_reference()
            again = run_reference(touched)                   # 받는 모델마다 값을 베껴서 넘기며 한 번 더
        except Exception as e:                               # noqa: BLE001
            say("error", "P6", case.name, f"참조 시뮬레이터에서 돌다가 멈췄다: {type(e).__name__}: {e}" + _longer(e))
            continue
        outs = {p: {port for port, decl in st.subtree(plan, p)["ports"].items() if decl[1] == "out"} for p in atoms}
        strays = sorted({("/".join(p), port) for _, p, port, _ in log if port not in outs.get(tuple(p), ())})
        for where, port in strays:
            say("error", "P6", case.name, f"{where} 가 선언하지 않은 출력 포트 {port} 로 냈다. "
                                          "모델의 PORTS 와 문서의 ports 에 그 포트를 적는다")
        mine = summary(log, case.until)
        info.update(events=mine["events"], last=mine["last"], digest=mine["digest"])
        mutated = sorted({(who, function, port) for who, function, port, _ in touched})
        for who, function, port in mutated[:5]:
            say("error", "P6", case.name, f"{who} 의 {function}() 이 포트 {port} 에서 받은 값을 고쳤다. 받은 값은 고치지 않는다. "
                                          "고쳐야 하면 복사해서 고친다. 엔진마다 값을 넘기는 방식이 달라 기록이 달라진다")
        if digest(again) != mine["digest"] and not mutated:
            try:
                third = run_reference()
            except Exception:                                # noqa: BLE001
                third = None
            if third is None or digest(third) != mine["digest"]:
                say("error", "P6", case.name, "같은 사례를 두 번 돌린 기록이 다르다. 재현되지 않는다. 난수는 씨앗을 "
                                              "매개변수로 받아 모델 안에서 만들고, 시각은 self.now 만 쓴다")
            else:
                say("error", "P6", case.name, "받는 모델마다 값을 베껴서 넘기면 기록이 달라진다. 낸 값을 낸 뒤에 고치는 모델이 "
                                              "있다. 낸 값은 다시 고치지 않는다. 엔진마다 값을 넘기는 방식이 달라 기록이 달라진다")
        if strays or mutated or digest(again) != mine["digest"]:
            continue
        old = records.get(case.name)
        if record:
            new_records[case.name] = mine
        elif old is None:
            say("warning", "P6", case.name, "적어 둔 기록이 없다. ses pack check --record 로 적는다")
        elif (old.get("digest"), old.get("until")) != (mine["digest"], mine["until"]):
            say("error", "P6", case.name, f"기록이 적어 둔 것과 다르다. 적어 둔 것은 사건 {old.get('events')}개 "
                                          f"(지문 {old.get('digest')}), 지금은 {mine['events']}개 (지문 {mine['digest']}). "
                                          "뜻한 변화이면 --record 로 다시 적는다")

        # P7 실행기 사이의 일치 ----------------------------------------------------------------
        info["executors"] = {"devs": REFERENCE}
        for name in pack.executors:
            if name == "devs" or (executors is not None and name not in executors):
                continue
            if not portable:
                info["executors"][name] = SKIPPED_NATIVE
                continue
            if name in skipped:
                info["executors"][name] = SKIPPED
                continue
            engine, why = _engine(name)
            if engine is None:
                info["executors"][name] = SKIPPED
                continue
            try:
                L2, ext2 = X.attach(built.layered, engine, X.Binding(name, binding.map, binding.target, binding.time_unit),
                                    library)
                found = violations(X.alone(L2, ext2), V)
                if found:
                    for line in shown(built, found):
                        say("error", "P7", case.name, f"{name} 의 규약을 어긴다. " + line)
                    info["executors"][name] = VIOLATES
                    continue
                sim = X.realize(L2, ext2, engine, V)
                try:
                    theirs = list(sim.run(case.until))
                finally:
                    sim.close()
            except Exception as e:                           # noqa: BLE001
                say("error", "P7", case.name, f"{name} 에서 돌다가 멈췄다: {type(e).__name__}: {e}")
                info["executors"][name] = STOPPED
                continue
            if theirs == log:
                info["executors"][name] = SAME
            else:
                info["executors"][name] = DIFFERENT
                say("error", "P7", case.name, f"{name} 의 기록이 참조 시뮬레이터와 다르다. " + _first_difference(log, theirs))
    stale = sorted(set(records) - {c.name for c in pack.cases})
    if record:                                               # 없어진 사례의 기록은 지운다
        new_records = {name: r for name, r in new_records.items() if name not in stale}
        if new_records != records:
            write_records(pack, new_records)
    else:
        for name in stale:
            say("warning", "P6", name, f"{RECORDS} 에 사례 {name} 의 기록이 있는데 그런 사례가 없다. "
                                       "ses pack check --record 가 지운다")
    return report


def run(root: str, case_name: str, until: Optional[float] = None) -> tuple:
    """묶음의 사례 하나를 참조 시뮬레이터로 돌린다. (사건 기록, 변수 값, 원자 구성요소의 수)를 돌려준다.

    until 을 주지 않으면 선언에 적힌 시각까지 돌린다. 만들 수 없거나 돌릴 수 없으면 PackError 를 낸다.
    그 code 는 막힌 곳의 부호다(P0 선언, P1 문서, P2 모델 베이스, P3 바인딩, P4 결정, P5 실행 가능성, P6 실행).
    """
    from . import executor as X
    from .devs import DevsExecutor, simulate
    from .extension import violations
    pack = load(root)
    case = next((c for c in pack.cases if c.name == case_name), None)
    if case is None:
        raise PackError(f"사례 {case_name} 가 없다. 있는 사례는 {[c.name for c in pack.cases]} 다")
    if not pack.library:
        raise PackError("모델 베이스가 없는 묶음은 돌릴 수 없다")
    until = case.until if until is None else until
    if until is None:
        raise PackError(f"사례 {case_name} 에 돌릴 시각이 없다. --until 로 준다")
    said: list = []

    def say(severity: str, code: str, where: str, message: str) -> None:
        if severity == "error":
            said.append((code, message))

    def stop() -> None:
        if said:
            raise PackError(f"사례 {case_name} 를 돌릴 수 없다. {said[0][1]}", said[0][0])

    library, functions = model_base(pack, say)
    stop()
    doc, profile = document(pack, say)
    stop()
    ds = decisions_of(pack, case.decisions, case_name, doc, say)
    stop()
    built = build_variant(doc, ds, profile, functions, case.defaults, case_name, say)
    stop()
    try:
        binding = X.load_binding(pack.path(pack.binding))
    except Exception as e:                                   # noqa: BLE001
        raise PackError(f"사례 {case_name} 를 돌릴 수 없다. 바인딩을 읽을 수 없다: {type(e).__name__}: {e}", "P3")
    dx = DevsExecutor()
    try:
        L, ext = X.attach(built.layered, dx, binding, library)
        found = violations(built.layered, built.variant) or violations(X.alone(L, ext), built.variant)
    except Exception as e:                                   # noqa: BLE001
        raise PackError(f"사례 {case_name} 를 돌릴 수 없다. {type(e).__name__}: {e}", "P5")
    if found:
        raise PackError(f"이 변이는 실행 가능하지 않다. 위반 {len(found)}건. 첫째: {shown(built, found)[0]}. "
                        "ses pack check 가 모두 알린다", "P5")
    try:
        log = simulate(X.realize(L, ext, dx, built.variant), until, max_steps=case.max_steps)
        atoms = len(X.frontier(X.plan(L, ext, built.variant)))
    except (Exception, SystemExit) as e:                     # noqa: BLE001  모델의 코드가 낸 것은 무엇이든 알린다
        raise PackError(f"사례 {case_name} 를 돌릴 수 없다. 참조 시뮬레이터에서 멈췄다: {type(e).__name__}: {e}" + _longer(e), "P6")
    return log, dict(built.sigma), atoms


# ---------------------------------------------------------------------------
# 뼈대
# ---------------------------------------------------------------------------

TEMPLATE = {
    "pack.yaml": '''# 분야 묶음의 선언. 이 디렉터리에 무엇이 어디 있는지를 적는다.
# 검사: ses pack check .      사례를 돌려 보기: ses pack run . fast
pack: "1.0"
name: {name}
title: 작업 하나를 받아 처리하는 줄. 처리기는 빠른 것과 느린 것 가운데 하나다

document: {name}.ses.yaml          # 구조의 족
model_base:
  file: model_base.py              # 원자 모델들. 공통 모델 기반(ses_core.devs.Atomic)으로 쓴다
  library: LIBRARY
binding: binding.yaml              # 정의를 모듈에 잇는다. 시간 단위를 적는다

cases:                             # 사례 하나가 변이 하나다. until 을 적으면 그 시각까지 돌려 본다
  - {{name: fast, decisions: cases/fast.decisions.yaml, until: 20}}
  - {{name: slow, decisions: cases/slow.decisions.yaml, until: 20}}
''',
    "{name}.ses.yaml": '''# 구조의 족. 무엇으로 이루어지는가(aspect)와 무엇 가운데 하나인가(specialization)를 적는다.
# 검사: ses check {name}.ses.yaml       남은 선택지: ses choices {name}.ses.yaml
ses: "1.0"
name: Line
description: 원천이 낸 작업을 처리기가 처리하고 수집기가 모은다

port_types:
  Job: {{fields: {{id: int}}}}

entities:

  Line:
    root: true
    aspects:
      flow:                                  # 분해: Line 은 세 부분으로 이루어진다
        parts: [Source, Worker, Sink]
        couplings:
          - {{from: Source.out, to: Worker.in}}
          - {{from: Worker.out, to: Sink.in}}

  Source:
    ports:
      out: {{type: Job, direction: out}}
    attributes:
      period: {{type: float, default: 2.0, doc: 작업을 내는 간격}}

  Worker:
    ports:
      in: {{type: Job, direction: in, required: true}}
      out: {{type: Job, direction: out}}
    specializations:
      speed:                                 # 대안: Worker 는 둘 가운데 하나다
        alternatives: [Fast, Slow]

  Fast:
    extends: Worker
    attributes:
      service: {{type: float, default: 1.0, doc: 작업 하나를 처리하는 시간}}

  Slow:
    extends: Worker
    attributes:
      service: {{type: float, default: 3.0}}

  Sink:
    ports:
      in: {{type: Job, direction: in, required: true}}
''',
    "model_base.py": '''"""모델 베이스. 구성요소가 무엇을 하는지를 적는다. SES 문서는 구조만 정한다.

모델은 공통 모델 기반(ses_core.devs.Atomic)의 하위 클래스로 쓴다. 채우는 것은 다음과 같다.
  PORTS      포트 이름에서 (타입, "in" 또는 "out")으로. 문서의 포트와 같아야 한다
  REQUIRED   구동되어야 하는 입력 포트
  PARAMS     매개변수 이름에서 (타입, 기본값)으로. 문서의 같은 이름의 속성이 값을 준다.
             시간 전진으로 쓰는 값은 타입을 time 으로 적는다. 바인딩의 시간 단위의 정수배여야 한다
             타입은 bool, int, float, str, time 가운데 하나다
  init       처음 상태
  ta         다음 내부 사건까지 남은 시간. 쉬고 있으면 INF
  output     내부 사건 직전의 출력. 포트 이름에서 값의 목록으로
  internal   내부 전이
  external   입력을 받았을 때의 전이. elapsed 는 이 모델의 마지막 전이에서 흐른 시간, bag 은 포트 이름에서 값의 목록으로
  confluent  내부 사건과 입력이 같은 시각에 겹쳤을 때. 적지 않으면 internal() 뒤에 external(0.0, bag) 이다
self.now 는 지금 처리하는 사건의 시각이다.
이 계약을 지킨 모델은 참조 시뮬레이터, pyevsim, cevsim 에서 같은 기록을 낸다.
난수가 필요하면 씨앗을 매개변수로 받아 random.Random(씨앗)을 모델 안에 둔다. 그래야 기록이 재현된다.
받은 값과 낸 값은 고치지 않는다. 고쳐야 하면 복사해서 고친다.
"""

from ses_core.devs import INF, Atomic, module_of


class Source(Atomic):
    PORTS = {{"out": ("Job", "out")}}
    PARAMS = {{"period": ("time", 2.0)}}

    def init(self):
        self.count = 0

    def ta(self):
        return self.period

    def output(self):
        return {{"out": [{{"id": self.count}}]}}

    def internal(self):
        self.count += 1


class Worker(Atomic):
    """작업을 하나씩 처리한다. 처리하는 동안 온 작업은 줄을 선다."""
    PORTS = {{"in": ("Job", "in"), "out": ("Job", "out")}}
    REQUIRED = ("in",)
    PARAMS = {{"service": ("time", 1.0)}}

    def init(self):
        self.queue, self.left = [], INF

    def ta(self):
        return self.left

    def output(self):
        return {{"out": [self.queue[0]]}}

    def internal(self):
        self.queue.pop(0)
        self.left = self.service if self.queue else INF

    def external(self, elapsed, bag):
        if self.queue:
            self.left -= elapsed                 # 처리하던 작업의 남은 시간
        self.queue += bag.get("in", [])
        if self.left == INF:
            self.left = self.service


class Sink(Atomic):
    PORTS = {{"in": ("Job", "in")}}
    REQUIRED = ("in",)

    def init(self):
        self.received = []

    def external(self, elapsed, bag):
        self.received += [(self.now, job["id"]) for job in bag.get("in", [])]


LIBRARY = {{m.name: m for m in (module_of(c) for c in (Source, Worker, Sink))}}
''',
    "binding.yaml": '''# 정의를 모델 베이스의 모듈에 잇는다. 결합 모델(Line)은 묶지 않는다. 문서의 구조에서 만들어진다.
# 대안(Fast, Slow)에 묶으면 그 대안을 고른 변이에서 쓰인다. 둘 다 같은 모듈이고 속성 service 의 값만 다르다.
binding: "1.0"
executor: devs
target: Line
time_unit: 1.0          # 모든 시간 전진이 이 값의 정수배다

map:
  Source: {{module: Source}}
  Fast: {{module: Worker}}
  Slow: {{module: Worker}}
  Sink: {{module: Sink}}
''',
    "cases/fast.decisions.yaml": '''# 사례: 빠른 처리기. 결정 집합은 선택 지점마다 남길 선택지를 적는다.
decisions: "1.0"
name: fast
target: Line

choose:
  - {{at: Worker, specialization: speed, alternative: Fast}}
''',
    "cases/slow.decisions.yaml": '''# 사례: 느린 처리기. 처리 시간(3)이 도착 간격(2)보다 길어 줄이 쌓인다.
decisions: "1.0"
name: slow
target: Line

choose:
  - {{at: Worker, specialization: speed, alternative: Slow}}
''',
}


def scaffold(root: str, name: Optional[str] = None) -> list:
    """돌아가는 가장 작은 묶음을 root 에 만든다. 만든 파일들을 돌려준다. 비어 있지 않은 디렉터리에는 만들지 않는다."""
    name = name or os.path.basename(os.path.abspath(root))
    if not name.isidentifier():
        raise PackError(f"묶음의 이름 {name!r} 는 글자, 숫자, 밑줄로 적는다. --name 으로 따로 줄 수 있다")
    if os.path.exists(root) and os.listdir(root):
        raise PackError(f"{root} 가 비어 있지 않다. 새 디렉터리에 만든다")
    written = []
    for relative, text in TEMPLATE.items():
        path = os.path.join(root, relative.format(name=name))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.format(name=name))
        written.append(path)
    return written
