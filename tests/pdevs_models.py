"""실행기 시험이 함께 쓰는 공통 모델 기반의 모델과 계획 만들기.

pyevsim 실행기와 cevsim 실행기의 시험이 같은 모델을 같은 기대값으로 돌린다. 어느 엔진에도 기대지 않는다.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_executor import UNIT, generic  # noqa: E402

from ses_core import devs  # noqa: E402
from ses_core import structure as st  # noqa: E402
from ses_core.devs import INF, Atomic  # noqa: E402
from ses_core.executor import Module  # noqa: E402


def as_plan(n: dict, body=generic, unit=UNIT) -> tuple:
    """구조의 원자마다 그 인터페이스에 맞는 모듈을 붙여 (계획, 라이브러리)로 만든다.

    unit은 계획에 적을 시간 단위다. 바인딩이 적어 준 것처럼 뿌리에 싣는다. None이면 적지 않는다.
    """
    plan, lib = st.copy(n), {}
    if unit is not None:
        plan["time_unit"] = unit
    for path, c in st.walk(plan):
        if st.is_atom(c):
            c["module"], c["params"] = "M_" + "_".join(path), {}
            lib[c["module"]] = Module(c["module"], dict(c["ports"]), (), {}, body(c["ports"]))
    return plan, lib


def flat_plan(children: dict, ic=(), ports=None, eic=(), eoc=()) -> tuple:
    """원자 모델 클래스들로 한 층짜리 계획과 라이브러리를 만든다."""
    lib = {name: devs.module_of(cls, name) for name, cls in children.items()}
    kids = {name: st.node(cls.PORTS, module=name, name=name,
                          params={k: v[1] for k, v in cls.PARAMS.items() if len(v) > 1})
            for name, cls in children.items()}
    return st.node(ports or {}, kids, eic, eoc, ic), lib


class Ring(Atomic):
    """겹친 전이를 따로 정한 모델. 기본(내부 전이 뒤에 외부 전이)과 다른 길을 간다."""
    PORTS = {"i": ("T", "in"), "o": ("T", "out")}

    def init(self):
        self.trace, self.left = [], 1.0

    def ta(self):
        return self.left

    def output(self):
        return {"o": [(self.name, len(self.trace))]}

    def internal(self):
        self.trace.append(("int", self.now))
        self.left = 1.0

    def external(self, elapsed, bag):
        self.trace.append(("ext", self.now, elapsed, tuple(bag["i"])))
        self.left -= elapsed

    def confluent(self, bag):
        self.trace.append(("con", self.now, tuple(bag["i"])))
        self.left = 2.0


class Pair(Atomic):
    PORTS = {"o": ("T", "out")}

    def init(self):
        self.k = 0

    def ta(self):
        return 1.0

    def output(self):
        return {"o": [(self.name, self.k, 0), (self.name, self.k, 1)]}

    def internal(self):
        self.k += 1


class Keep(Atomic):
    PORTS = {"i": ("T", "in")}

    def init(self):
        self.seen = []

    def external(self, elapsed, bag):
        self.seen.append((self.now, elapsed, {p: list(v) for p, v in bag.items()}))


class Burst(Atomic):
    """시간 전진이 0인 전이를 이어서 한다. 같은 시각에 여러 차례가 돈다."""
    PORTS = {"i": ("T", "in"), "o": ("T", "out")}
    PARAMS = {"bursts": ("int", 3)}

    def init(self):
        self.left, self.todo, self.got = 1.0, self.bursts, []

    def ta(self):
        return self.left

    def output(self):
        return {"o": [(self.name, self.todo)]}

    def internal(self):
        self.todo -= 1
        self.left = 0.0 if self.todo > 0 else INF

    def external(self, elapsed, bag):
        self.got.append((self.now, elapsed, tuple(bag["i"])))
        if self.left != INF:
            self.left -= elapsed


class Spin(Atomic):
    PORTS = {"o": ("T", "out")}

    def ta(self):
        return 0.0


class Note(Atomic):
    """받은 것을 적는 공통 모델 기반의 모델. 주기가 있으면 스스로도 낸다."""
    PORTS = {"i": ("T", "in"), "o": ("T", "out")}
    PARAMS = {"period": ("time", INF)}

    def init(self):
        self.left, self.seen, self.k = self.period, [], 0

    def ta(self):
        return self.left

    def output(self):
        return {"o": [(self.name, self.k)]}

    def internal(self):
        self.k += 1
        self.left = self.period

    def external(self, elapsed, bag):
        self.seen.append(("ext", self.now, elapsed, list(bag["i"])))
        if self.left != INF:
            self.left -= elapsed

    def confluent(self, bag):
        self.seen.append(("con", self.now, list(bag["i"])))
        self.internal()


NOTE = devs.module_of(Note)


def note(**params) -> dict:
    return st.node(Note.PORTS, module="Note", params=dict({"period": INF}, **params))
