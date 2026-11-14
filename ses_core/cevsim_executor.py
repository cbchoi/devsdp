"""cevsim 실행기 (docs/ses-platform/16_cevsim_executor.md).

SES에 cevsim(C++ 이산 사건 엔진)을 붙인다. 계약은 다른 실행기와 같다. 계획을 받아 산출물을
만들고(build), 산출물에서 구조를 다시 읽는다(observe). cevsim의 a9886a6에서 확인했다.

cevsim은 C++ 라이브러리다. 이 모듈은 cevsim의 소스와 다리(cevsim_bridge/bridge.cpp)와 고유
모델의 소스를 하나의 공유 라이브러리로 컴파일하고 ctypes로 부른다. C++ 컴파일러(g++)와 cevsim의
소스가 있어야 한다. cevsim의 위치는 cevsim_home 인자나 환경 변수 CEVSIM_HOME으로 준다.

엔진에는 계획의 평탄화를 올린다. cevsim의 계층 실행은 평탄 실행과 결과가 다르기 때문이다.

모듈의 본체는 둘 가운데 하나다.
- 고유 모델. 본체가 Native("이름") 또는 글자이면, ses_cevsim.hpp의 SES_MODULE로 등록한 C++ 공장을
  그 이름으로 불러 cevsim의 원자 모델을 만든다. 행위는 cevsim의 의미를 따른다.
- 공통 모델 기반. devs.Atomic의 하위 클래스이면 모델은 Python에 남고, 엔진에는 그것을 대신하는
  모델이 오른다. 엔진이 일정과 전달을 맡고 전이는 Python에서 한다. cevsim의 메시지에는 값이 없으므로
  값은 Python에 두고, 받는 쪽이 메시지의 출처를 보고 찾아 읽는다.

공통 모델 기반을 올릴 때 병렬 DEVS의 규약을 지키는 방법 (pyevsim 실행기와 같은 규약이다).
- 출력은 전이하기 전의 상태에서 내고, 받은 것은 묶음에 모아 두기만 한다.
- 출력한 모델은 전이를 맡는 모델을 깨운다. 그 모델은 그 시각에 임박한 모델이 모두 출력한 뒤에
  차례가 와서 모든 모델에 전이 신호를 보내고, 신호를 받은 모델이 모아 둔 전이를 한다.
그래서 엔진에는 계획에 없는 것이 오른다. 전이를 맡는 모델 하나와, 공통 모델마다 깨우는 연결과
전이 신호의 연결 하나씩이다. observe와 connections는 이것을 빼고 읽고, Simulation.infrastructure가
따로 내놓는다.
"""

from __future__ import annotations

import ctypes
import glob
import hashlib
import math
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from . import structure as st
from .devs import INF, Atomic
from .executor import Executor, OffGrid

BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cevsim_bridge")
WAKE, COMMIT = "__wake__", "__commit__"          # 전이를 맡는 모델과 주고받는 포트의 이름. 계획에서는 쓸 수 없다
KEEPER = "__ses_transition__"                    # 전이를 맡는 모델의 이름
FLAGS = ("-std=c++20", "-O1", "-fPIC", "-shared", "-pthread")

_TA = ctypes.CFUNCTYPE(ctypes.c_longlong, ctypes.c_int)
_OUT = ctypes.CFUNCTYPE(None, ctypes.c_int)
_INT = ctypes.CFUNCTYPE(None, ctypes.c_int)
_EXT = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
_NOTE = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p)

_LOADED: dict = {}


class BuildError(RuntimeError):
    """cevsim과 다리를 컴파일하지 못했다."""


@dataclass(frozen=True)
class Native:
    """고유 모델의 본체: SES_MODULE로 등록한 C++ 공장의 이름."""
    module: str


def ref(path: tuple) -> str:
    return "/".join(path)


# ---------------------------------------------------------------------------
# 컴파일과 적재
# ---------------------------------------------------------------------------

def available(cevsim_home: Optional[str] = None, compiler: str = "g++") -> bool:
    """cevsim의 소스와 컴파일러가 있는가."""
    home = cevsim_home or os.environ.get("CEVSIM_HOME") or ""
    return os.path.isfile(os.path.join(home, "cevsim", "include", "system_executor.hpp")) and shutil.which(compiler) is not None


def load(cevsim_home: Optional[str] = None, sources: Sequence[str] = (), cache: Optional[str] = None,
         compiler: str = "g++") -> ctypes.CDLL:
    """cevsim, 다리, 고유 모델의 소스를 하나의 공유 라이브러리로 컴파일해 싣는다.

    소스의 내용과 컴파일러가 같으면 앞서 만든 것을 다시 쓴다. cevsim의 소스는 고치지 않는다.
    """
    home = cevsim_home or os.environ.get("CEVSIM_HOME")
    if not home or not available(home, compiler):
        raise BuildError("cevsim의 소스나 컴파일러를 찾지 못했다. cevsim_home 인자나 CEVSIM_HOME 환경 변수로 "
                         "cevsim을 받아 둔 자리를 준다")
    include = os.path.join(home, "cevsim", "include")
    units = sorted(glob.glob(os.path.join(home, "cevsim", "src", "*.cpp"))) + [os.path.join(BRIDGE, "bridge.cpp")] + \
        [os.path.abspath(s) for s in sources]
    seen = units + sorted(glob.glob(os.path.join(include, "*.hpp"))) + [os.path.join(BRIDGE, "ses_cevsim.hpp")]
    digest = hashlib.sha256()
    digest.update(subprocess.run([compiler, "--version"], capture_output=True, text=True).stdout.encode())
    digest.update(" ".join(FLAGS).encode())
    for path in seen:
        digest.update(path.encode())
        with open(path, "rb") as f:
            digest.update(f.read())
    root = cache or os.environ.get("SES_CEVSIM_CACHE") or os.path.join(tempfile.gettempdir(), "ses_cevsim")
    target = os.path.join(root, digest.hexdigest()[:24], "libses_cevsim.so")
    if target in _LOADED:
        return _LOADED[target]
    if not os.path.isfile(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        partial = f"{target}.{os.getpid()}.tmp"
        done = subprocess.run([compiler, *FLAGS, "-I", include, "-I", BRIDGE, *units, "-o", partial],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise BuildError("cevsim과 다리를 컴파일하지 못했다:\n" + done.stderr[-4000:])
        os.replace(partial, target)
    lib = ctypes.CDLL(target)
    lib.ses_new.restype = ctypes.c_void_p
    lib.ses_new.argtypes = [ctypes.c_double, ctypes.c_double, _TA, _OUT, _INT, _EXT, _NOTE]
    lib.ses_free.argtypes = [ctypes.c_void_p]
    lib.ses_add_hosted.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_double]
    lib.ses_add_native.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    lib.ses_add_port.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.ses_couple.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
    lib.ses_emit.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
    lib.ses_inject.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]
    lib.ses_run.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.ses_time.restype = ctypes.c_double
    lib.ses_time.argtypes = [ctypes.c_void_p]
    lib.ses_dump.restype = ctypes.c_char_p
    lib.ses_dump.argtypes = [ctypes.c_void_p]
    lib.ses_last_error.restype = ctypes.c_char_p
    lib.ses_last_error.argtypes = [ctypes.c_void_p]
    lib.ses_modules.restype = ctypes.c_char_p
    _LOADED[target] = lib
    return lib


def modules(lib: ctypes.CDLL) -> list:
    """라이브러리에 등록된 고유 모델의 모듈 이름들."""
    return sorted(lib.ses_modules().decode().split())


# ---------------------------------------------------------------------------
# 산출물
# ---------------------------------------------------------------------------

@dataclass
class _Cell:
    """엔진에 올린 공통 모델 하나: Python에 남은 모델과, 한 차례 동안의 사정."""
    atom: Atomic
    path: tuple
    name: str
    outs: frozenset
    last: int = 0
    due: Optional[int] = None
    fired: bool = False
    inbox: dict = field(default_factory=dict)        # 포트에서 (출처, 값)의 목록으로
    outbox: dict = field(default_factory=dict)       # 방금 낸 것: 포트에서 값의 목록으로. 받는 쪽이 여기서 읽는다


class Simulation:
    """cevsim 실행기의 산출물: 모델과 연결이 올라간 cevsim 엔진 하나."""

    def __init__(self, lib: ctypes.CDLL, step: float, max_rounds: int) -> None:
        self.lib, self.step, self.max_rounds = lib, step, max_rounds
        self.cells: dict = {}                        # 번호에서 공통 모델로
        self.keeper: Optional[int] = None            # 전이를 맡는 모델의 번호
        self.models: dict = {}                       # 경로에서 번호로
        self.paths: dict = {}                        # 번호에서 경로로
        self.names: dict = {}                        # 번호에서 엔진에 올린 이름으로
        self.types: dict = {}                        # 경로에서 {포트: 타입}으로. cevsim의 포트에는 타입이 없다
        self.log: list = []                          # 출력 사건: (시각, 원자의 경로, 포트, 값). 고유 모델의 값은 None
        self.error: Optional[BaseException] = None
        self._awake, self._at, self._rounds = False, -1, 0
        self._calls = (_TA(self._guard(self._ta, -1)), _OUT(self._guard(self._out)), _INT(self._guard(self._int)),
                       _EXT(self._guard(self._ext)), _NOTE(self._guard(self._note)))
        self.handle = lib.ses_new(step, step / 2 ** 20, *self._calls)

    # 시계 ---------------------------------------------------------------

    def tick(self) -> int:
        return round(self.lib.ses_time(self.handle) / self.step)

    def now(self) -> float:
        return self.tick() * self.step

    # 실행 ---------------------------------------------------------------

    def run(self, until: float) -> list:
        """시각 until까지 돌린다. 그 시각의 사건도 처리한다. 출력 사건의 기록을 돌려준다."""
        last = math.floor(until / self.step + 1e-9)
        span = (last + 0.5) * self.step - self.lib.ses_time(self.handle)
        if span > 0:
            failed = self.lib.ses_run(self.handle, span)
            if self.error is not None:
                raise self.error
            if failed:
                raise RuntimeError(self.lib.ses_last_error(self.handle).decode())
        return self.log

    def leaves(self) -> dict:
        """경로에서 Python에 있는 모델로. 고유 모델은 C++에 있으므로 들지 않는다."""
        return {c.path: c.atom for c in self.cells.values()}

    def inject(self, port: str, at: float = 0.0) -> None:
        """뿌리의 입력 포트로 밖에서 입력을 넣는다. cevsim의 메시지에는 값이 없으므로 값 없는 입력이 된다."""
        if self.lib.ses_inject(self.handle, port.encode(), at) != 0:
            raise ValueError(f"엔진의 경계에 입력 포트 {port} 가 없다")

    def outputs(self) -> Counter:
        """뿌리의 출력 포트로 나간 것: (낸 원자의 경로, 그 포트)마다의 횟수. 시각과 뿌리의 포트 이름은 엔진에 남지 않는다."""
        return Counter((self._path_of(i), port) for i, port in self.dump()["outputs"])

    def close(self) -> None:
        if self.handle is not None:
            self.lib.ses_free(self.handle)
            self.handle = None

    # 엔진에서 다시 읽기 --------------------------------------------------

    def dump(self) -> dict:
        """엔진이 가진 모델, 포트, 결합. 다리가 엔진의 자료에서 읽어 준 것이다."""
        out: dict = {"models": {}, "ports": {}, "couplings": [], "outputs": [], "unknown": []}
        for line in self.lib.ses_dump(self.handle).decode().splitlines():
            tag, *rest = line.split("\t")
            if tag == "M":
                out["models"][int(rest[0])] = (rest[1], rest[2])
            elif tag == "P":
                out["ports"].setdefault(int(rest[0]), {})[rest[2]] = rest[1]
            elif tag == "C":
                out["couplings"].append((rest[0], (int(rest[1]), rest[2]), (int(rest[3]), rest[4])))
            elif tag == "O":
                out["outputs"].append((int(rest[0]), rest[1]))
            else:
                out["unknown"].append(rest)
        return out

    def _hidden(self, coupling: tuple) -> bool:
        _, (a, ap), (b, bp) = coupling
        return self.keeper is not None and (a == self.keeper or b == self.keeper)

    def _path_of(self, i: int) -> tuple:
        if i < 0:
            return ()                                # 엔진의 경계: 뿌리의 포트
        if i not in self.paths:
            raise st.StructureError(f"계획에 없는 모델이 엔진에 있다: {i}")
        return self.paths[i]

    def connections(self) -> Counter:
        """엔진에 등록된 계획의 연결을 개수와 함께 센다. 열쇠는 structure.flatten과 같은 꼴이다."""
        d = self.dump()
        if d["unknown"]:
            raise st.StructureError(f"계획에 없는 것이 엔진에 있다: {d['unknown']}")
        out: Counter = Counter()
        for c in d["couplings"]:
            if not self._hidden(c):
                _, (a, ap), (b, bp) = c
                out[((self._path_of(a), ap), (self._path_of(b), bp))] += 1
        return out

    def infrastructure(self) -> dict:
        """계획에 없는데 엔진에 올린 것: 전이를 맡는 모델과 그 연결. 공통 모델이 없으면 비어 있다."""
        d = self.dump()
        return {"models": [name for i, (_, name) in d["models"].items() if i == self.keeper],
                "couplings": Counter((self.names.get(a, a), ap, self.names.get(b, b), bp)
                                     for c in d["couplings"] if self._hidden(c) for _, (a, ap), (b, bp) in [c])}

    # 엔진이 부르는 것 (공통 모델 기반) -------------------------------------

    def _guard(self, fn, fallback=None):
        """Python의 예외는 C++을 건너지 못한다. 적어 두었다가 run이 다시 낸다. 그 뒤로는 아무것도 하지 않는다."""
        def call(*args):
            if self.error is not None:
                return fallback
            try:
                return fn(*args)
            except BaseException as e:               # noqa: B902
                self.error = e
                return fallback
        return call

    def _ticks(self, who: str, ta: float) -> Optional[int]:
        if ta == INF:
            return None
        k = ta / self.step
        if ta < 0 or abs(k - round(k)) > 1e-9 * max(1.0, abs(k)):
            raise OffGrid(f"{who}: 시간 전진 {ta} 이 시간 간격 {self.step} 의 배수가 아니다")
        return round(k)

    def _in_round(self, n: int) -> bool:
        return any(c.due == n for c in self.cells.values())

    def _ta(self, i: int) -> int:
        """남은 눈금 수. 음수는 무한이다. 다리가 여기에 모델마다 다른 아주 작은 값을 빼서 엔진에 준다."""
        if i == self.keeper:
            return 0 if self._awake else -1
        c, n = self.cells[i], self.tick()
        if c.due == n and not c.fired:
            return 0                                 # 지금 낼 차례다
        if c.fired or c.inbox or c.due is None:
            return -1                                # 전이를 기다리거나 쉬고 있다
        if c.due < n:
            raise RuntimeError(f"{c.name}: 눈금 {c.due} 의 사건을 엔진이 지나쳤다")
        return c.due - n

    def _out(self, i: int) -> None:
        n = self.tick()
        if i == self.keeper:                         # 전이 신호를 모든 공통 모델에 보낸다
            if n != self._at:
                self._at, self._rounds = n, 0
            self._rounds += 1
            if self._rounds > self.max_rounds:
                raise RuntimeError("시뮬레이션이 정해진 걸음 수 안에 끝나지 않았다. 시간 전진이 0인 전이가 되풀이된다")
            self.lib.ses_emit(self.handle, i, COMMIT.encode())
            return
        c = self.cells[i]
        if c.due != n:                               # 밖에서 온 입력으로 그 시각에 임박해진 모델을 엔진은 다음 눈금에 처리한다
            raise RuntimeError(f"{c.name}: 눈금 {c.due} 의 사건을 엔진이 눈금 {n} 에 처리했다")
        c.atom.now = n * self.step
        c.fired, c.outbox = True, {}
        for port, values in sorted((c.atom.output() or {}).items()):
            values = list(values)
            self.log.extend((c.atom.now, c.path, port, v) for v in values)
            if values and port in c.outs:            # 값이 없는 출력은 보내지 않는다
                c.outbox[port] = values
                self.lib.ses_emit(self.handle, i, port.encode())
        # 전이를 맡는 모델을 깨운다. 그 모델의 차례는 이 시각에 임박한 모델이 모두 출력한 뒤에 온다
        self.lib.ses_emit(self.handle, i, WAKE.encode())

    def _int(self, i: int) -> None:
        if i == self.keeper:
            self._awake = False                      # 전이 신호를 다 보냈다. 다시 깨울 때까지 쉰다

    def _ext(self, i: int, port: bytes, src: int, src_port: bytes) -> None:
        if i == self.keeper:
            self._awake = True
            return
        c, n, port, src_port = self.cells[i], self.tick(), port.decode(), src_port.decode()
        if port == COMMIT:
            if c.fired or c.inbox:
                self._commit(c, n)
            return
        sender = self.cells.get(src)                 # 값은 보낸 모델이 방금 낸 것에서 읽는다. 고유 모델과 밖에서 온 것에는 값이 없다
        values = sender.outbox.get(src_port, []) if sender is not None else []
        key = (0, sender.path, src_port) if sender is not None else (1, self.names.get(src, ""), src_port)
        c.inbox.setdefault(port, []).extend(((key, k), v) for k, v in enumerate(values))
        if not self._in_round(n):                    # 임박한 공통 모델이 없는 시각에 온 것: 바로 전이한다
            self._commit(c, n)

    def _commit(self, c: _Cell, n: int) -> None:
        bag = {port: [v for _, v in sorted(items, key=lambda x: x[0])] for port, items in sorted(c.inbox.items())}
        c.atom.now = n * self.step
        if c.fired and bag:
            c.atom.confluent(bag)
        elif c.fired:
            c.atom.internal()
        else:
            c.atom.external((n - c.last) * self.step, bag)
        c.last, c.fired, c.inbox = n, False, {}
        k = self._ticks(c.name, c.atom.ta())
        c.due = None if k is None else n + k

    def _note(self, i: int, port: bytes) -> None:
        self.log.append((self.now(), self.paths[i], port.decode(), None))


# ---------------------------------------------------------------------------
# 실행기
# ---------------------------------------------------------------------------

class CevsimExecutor(Executor):
    """계획을 cevsim 엔진으로 만든다.

    time_step은 엔진의 시간 간격이다. 공통 모델 기반의 사건 시각은 모두 그 배수여야 한다. sources는 고유
    모델을 등록하는 C++ 소스들이다. 라이브러리는 처음 조립할 때 컴파일한다.
    """

    name = "cevsim"

    def __init__(self, cevsim_home: Optional[str] = None, time_step: float = 1.0, sources: Sequence[str] = (),
                 record: bool = True, max_rounds: int = 100000, cache: Optional[str] = None) -> None:
        if not time_step > 0:
            raise ValueError("시간 간격은 0보다 커야 한다")
        self.cevsim_home, self.time_step, self.sources = cevsim_home, time_step, tuple(sources)
        self.record, self.max_rounds, self.cache = record, max_rounds, cache
        self._lib: Optional[ctypes.CDLL] = None

    @property
    def lib(self) -> ctypes.CDLL:
        if self._lib is None:
            self._lib = load(self.cevsim_home, self.sources, self.cache)
        return self._lib

    # 규약 -------------------------------------------------------------------

    def conventions(self) -> list:
        return [self.check]

    def check(self, plan: dict) -> list:
        """V1: 원자의 포트 이름이 전이를 맡는 모델과 주고받는 포트의 이름과 겹치면 안 된다."""
        return [("V1", path, f"포트 이름 {p} 는 cevsim 실행기가 쓰는 이름이다")
                for path, c in st.walk(plan) if st.is_atom(c) for p in sorted(c["ports"]) if p in (WAKE, COMMIT)]

    # 조립 -------------------------------------------------------------------

    def build(self, plan: dict, library: Mapping) -> Simulation:
        clash = self.check(plan)
        if clash:
            raise ValueError("cevsim으로 만들 수 없는 계획이다: " + "; ".join(msg for _, _, msg in clash))
        sim = Simulation(self.lib, self.time_step, self.max_rounds)
        try:
            self._fill(sim, plan, library)
        except Exception:
            sim.close()
            raise
        return sim

    def _fill(self, sim: Simulation, plan: dict, library: Mapping) -> None:
        lib, h = self.lib, sim.handle
        atoms = [(path, st.subtree(plan, path)) for path in sorted(st.atoms(plan))]
        common = [path for path, n in atoms if self._is_common(library[n["module"]].body)]
        for path, n in atoms:
            body = library[n["module"]].body
            label = ref(path) or n.get("name", "")
            ins = [p for p, (_, d) in n["ports"].items() if d == st.IN]
            outs = [p for p, (_, d) in n["ports"].items() if d == st.OUT]
            if self._is_common(body):
                atom = body(label, **n["params"])
                # 같은 시각의 처리 순서는 다음 사건 시각에서 빼는 값의 크기로 정해진다. 경로가 앞선 모델이 먼저다
                units = len(common) - common.index(path)
                i = lib.ses_add_hosted(h, (label or "root").encode(), "\n".join(ins + [COMMIT]).encode(),
                                       "\n".join(outs + [WAKE]).encode(), float(units))
                cell = sim.cells[i] = _Cell(atom, path, label or "root", frozenset(outs))
                cell.due = sim._ticks(cell.name, atom.ta())
            else:
                module = body.module if isinstance(body, Native) else body
                if not isinstance(module, str):
                    raise TypeError(f"모듈 {n['module']} 의 본체가 공통 모델 기반도 cevsim 모듈의 이름도 아니다")
                params = "\n".join(f"{k}={self._text(v)}" for k, v in n["params"].items())
                i = lib.ses_add_native(h, module.encode(), (label or "root").encode(), params.encode(), int(self.record))
                if i < 0:
                    raise ValueError(lib.ses_last_error(h).decode())
            sim.models[path], sim.paths[i], sim.names[i] = i, path, label or "root"
            sim.types[path] = {p: t for p, (t, _) in n["ports"].items()}
        if sim.cells:                                # 전이를 맡는 모델과 그 연결
            sim.keeper = lib.ses_add_hosted(h, KEEPER.encode(), WAKE.encode(), COMMIT.encode(), 0.5)
            sim.names[sim.keeper] = KEEPER
            for i in sim.cells:
                self._couple(sim, i, WAKE, sim.keeper, WAKE)
                self._couple(sim, sim.keeper, COMMIT, i, COMMIT)
        self._conforms(sim, plan)
        if not st.is_atom(plan):
            for p, (_, direction) in plan["ports"].items():      # 뿌리의 포트는 엔진의 경계다
                if lib.ses_add_port(h, p.encode(), int(direction == st.IN)) != 0:
                    raise ValueError(f"엔진의 경계에 포트 {p} 를 둘 수 없다")
            sim.types[()] = {p: t for p, (t, _) in plan["ports"].items()}
        for ((a, ap), (b, bp)), count in sorted(st.flatten(plan).items()):
            for _ in range(count):                   # 길의 수만큼 등록한다. 엔진은 등록된 만큼 전달한다
                self._couple(sim, sim.models[a] if a else -1, ap, sim.models[b] if b else -1, bp)

    @staticmethod
    def _is_common(body) -> bool:
        return isinstance(body, type) and issubclass(body, Atomic)

    @staticmethod
    def _text(value) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return repr(float(value)) if isinstance(value, float) else str(value)

    def _couple(self, sim: Simulation, a: int, ap: str, b: int, bp: str) -> None:
        if self.lib.ses_couple(sim.handle, a, ap.encode(), b, bp.encode()) != 0:
            raise ValueError(f"결합을 등록할 수 없다: {sim.names.get(a, '경계')}.{ap} 에서 {sim.names.get(b, '경계')}.{bp}")

    @staticmethod
    def _conforms(sim: Simulation, plan: dict) -> None:
        """고유 모델이 계획의 포트를 그 방향으로 가졌는지 본다. 공장이 만든 모델의 포트는 엔진에서 읽는다."""
        ports = sim.dump()["ports"]
        for path, i in sim.models.items():
            if i in sim.cells:
                continue
            n = st.subtree(plan, path)
            for p, (_, direction) in n["ports"].items():
                if ports.get(i, {}).get(p) != direction:
                    raise ValueError(f"모듈 {n['module']} 의 cevsim 모델에 {'입력' if direction == st.IN else '출력'} 포트 {p} 가 없다")

    # 관찰 -------------------------------------------------------------------

    def observe(self, sim: Simulation) -> dict:
        """엔진에서 구조를 다시 읽는다. 한 층짜리 구조이고 원자의 이름은 경로를 이은 것이다.

        전이를 맡는 모델과 그 포트와 연결은 뺀다. 그것들은 Simulation.infrastructure가 내놓는다.
        """
        d = sim.dump()
        if d["unknown"]:
            raise st.StructureError(f"계획에 없는 것이 엔진에 있다: {d['unknown']}")
        kids: dict = {}
        for i, (_, name) in d["models"].items():
            if i == sim.keeper:
                continue
            types = sim.types.get(sim._path_of(i), {})
            if name in kids:
                raise st.StructureError(f"이름이 같은 모델이 둘이다: {name}")
            kids[name] = st.node({p: (types.get(p), direction) for p, direction in d["ports"].get(i, {}).items()
                                  if not (i in sim.cells and p in (WAKE, COMMIT))})
        types = sim.types.get((), {})
        ports = {p: (types.get(p), direction) for p, direction in d["ports"].get(-1, {}).items()}
        eic, eoc, ic = [], [], []
        for c in d["couplings"]:
            if sim._hidden(c):
                continue
            kind, (a, ap), (b, bp) = c
            sim._path_of(a), sim._path_of(b)
            if a < 0:
                eic.append((ap, (d["models"][b][1], bp)))
            elif b < 0:
                eoc.append(((d["models"][a][1], ap), bp))
            else:
                ic.append(((d["models"][a][1], ap), (d["models"][b][1], bp)))
        return st.node(ports, kids, eic, eoc, ic)
