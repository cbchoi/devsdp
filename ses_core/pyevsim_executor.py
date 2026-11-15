"""pyevsim 실행기 (docs/ses-platform/15_pyevsim_executor.md).

SES에 pyevsim을 붙인다. 계약은 DevsExecutor, HwExecutor와 같다. 계획을 받아 산출물을 만들고
(build), 산출물에서 구조를 다시 읽는다(observe). 이 모듈을 가져오려면 pyevsim이 설치되어
있어야 한다. 1.1.7에서 확인했다.

pyevsim의 엔진은 계층이 없는 모델 목록과 연결 표(port_map)다. 그래서 계획의 평탄화를
그대로 등록한다. 길이 둘인 연결은 두 번 등록하고, 엔진은 그만큼 전달한다. pyevsim의
StructuralModel은 쓰지 않는다. 안쪽 출력 하나를 바깥 출력 둘에 이으면 하나만 남기 때문이다.

모듈의 본체는 둘 가운데 하나다.
- pyevsim 모델. BehaviorModelExecutor를 만드는 호출 가능 객체이며 pyevsim의 관례대로
  body(0, Infinite, 이름, 엔진 이름, **매개변수)로 부른다. 엔진이 그 모델을 그대로 돌린다.
  행위는 pyevsim의 의미를 따른다.
- 공통 모델 기반. devs.Atomic의 하위 클래스이며 Adapted가 감싸서 엔진에 올린다. 같은
  모델베이스를 참조 시뮬레이터와 pyevsim에서 돌려 사건 기록을 비교할 수 있게 한다.

Adapted가 하는 일. pyevsim의 엔진은 같은 시각의 사건을 객체 번호 순서로 하나씩 처리하고
받는 쪽의 전이를 바로 부른다. 병렬 DEVS는 같은 시각에 임박한 모델이 모두 출력한 뒤에
전이한다. Adapted는 엔진이 부르는 순서 위에서 그 규약을 지킨다.
- 출력(output)은 전이하기 전의 상태에서 낸다.
- 받은 것(ext_trans)은 묶음에 모아 두기만 한다. 값이 없는 출력은 보내지 않는다.
- 그 시각에 임박한 모델 가운데 마지막 것이 출력을 마치면(int_trans) 모아 둔 전이를 한꺼번에
  한다. 임박했고 받은 것이 있으면 겹친 전이, 임박했을 뿐이면 내부 전이, 받기만 했으면 외부 전이다.
- 시각은 시간 단위의 눈금으로 센다. 참조 시뮬레이터와 같은 방법이다(executor.ticks). 엔진의
  시간 간격을 시간 단위로 맞춘다. 시간 전진이 시간 단위의 정수배가 아니면 OffGrid로 알린다.
엔진에 더하는 것은 없다. 모델도 연결도 계획에 있는 것뿐이다.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Optional

from pyevsim import BehaviorModelExecutor, Infinite, SysMessage, SystemSimulator
from pyevsim.system_executor import SysExecutor

from . import structure as st
from .devs import Atomic
from .executor import Executor, OffGrid, last_tick, ticks, time_unit

_SERIAL = itertools.count(1)


def ref(path: tuple) -> str:
    return "/".join(path)


# ---------------------------------------------------------------------------
# 공통 모델 기반을 pyevsim에 올리는 어댑터
# ---------------------------------------------------------------------------

class _Hub:
    """Adapted들이 함께 쓰는 것: 눈금으로 센 시계와, 한 차례의 출력이 끝났는지 아는 일."""

    def __init__(self, sim: "Simulation", max_rounds: int) -> None:
        self.sim, self.max_rounds = sim, max_rounds
        self.members: list = []                  # 만든 순서. 엔진이 같은 시각의 모델을 처리하는 순서다
        self._at, self._rounds = -1, 0

    def tick(self) -> int:
        return self.sim.tick()

    def ticks(self, who: str, ta: float) -> Optional[int]:
        """시간 전진을 눈금의 수로 바꾼다. 무한이면 None."""
        return ticks(who, ta, self.sim.step)

    def waiting(self, n: int) -> bool:
        """이 시각에 임박했는데 아직 출력하지 않은 모델이 있는가."""
        return any(a._due == n and not a._fired for a in self.members)

    def in_round(self, n: int) -> bool:
        """이 시각에 임박한 모델이 있는가. 출력을 마친 모델도 전이하기 전까지는 임박한 것으로 남는다."""
        return any(a._due == n for a in self.members)

    def settle(self) -> None:
        """임박한 모델이 모두 출력했으면 이 차례의 전이를 한꺼번에 한다."""
        n = self.tick()
        if self.waiting(n):
            return
        if n != self._at:
            self._at, self._rounds = n, 0
        self._rounds += 1
        if self._rounds > self.max_rounds:
            raise RuntimeError("시뮬레이션이 정해진 걸음 수 안에 끝나지 않았다. 시간 전진이 0인 전이가 되풀이된다")
        for a in self.members:
            if a._fired or a._inbox:
                a._commit(n)


class Adapted(BehaviorModelExecutor):
    """공통 모델 기반(devs.Atomic)의 모델 하나를 pyevsim 모델로 올린 것."""

    _OWN = ("_atom", "_hub", "_path", "_last", "_fired", "_inbox", "_due")

    def __init__(self, name: str, engine_name: str, atom: Atomic, hub: _Hub, path: tuple, ports: Mapping) -> None:
        BehaviorModelExecutor.__init__(self, 0, Infinite, name, engine_name)
        self.init_state("RUN")
        self.insert_state("RUN", Infinite)
        for p, (_, direction) in ports.items():
            (self.insert_input_port if direction == st.IN else self.insert_output_port)(p)
        self._atom, self._hub, self._path = atom, hub, path
        self._last, self._fired, self._inbox = 0, False, {}      # 묶음: 포트에서 (출처, 값)의 목록으로
        self._due = hub.ticks(name, atom.ta())
        hub.members.append(self)

    # 엔진이 부르는 것 --------------------------------------------------------

    def output(self):
        hub, atom = self._hub, self._atom
        atom.now = hub.sim.now()
        self._fired = True
        messages = []
        for port, values in sorted((atom.output() or {}).items()):
            values = list(values)
            hub.sim.log.extend((atom.now, self._path, port, v) for v in values)
            if values:
                m = SysMessage(self.get_name(), port)
                m.extend(values)
                messages.append(m)
        return messages or None

    def int_trans(self) -> None:
        self._hub.settle()

    def ext_trans(self, port, msg) -> None:
        hub = self._hub
        sender = hub.sim.names.get(msg.get_src())
        src = (0, sender, msg.get_dst()) if sender is not None else (1, str(msg.get_src()), str(msg.get_dst()))
        # 값이 없는 메시지(pyevsim 모델이 신호로 보낸 것)도 입력이다. 그 포트가 빈 목록으로 묶음에 든다
        self._inbox.setdefault(port, []).extend(((src, i), v) for i, v in enumerate(msg.retrieve()))
        n = hub.tick()
        if not hub.in_round(n):                  # 임박한 모델이 없는 시각에 밖에서 온 것: 바로 전이한다
            self._commit(n)

    def time_advance(self):
        n = self._hub.tick()
        if self._due == n and not self._fired:
            return 0
        if self._fired or self._inbox or self._due is None:
            return Infinite
        return (self._due - n) * self._hub.sim.step

    def get_req_time(self):
        hub = self._hub
        n = hub.tick()
        if self._due is not None and self._due < n:
            hub.sim.check()                      # 앞에 놓인 pyevsim 모델이 엔진을 멈춘 것이면 그 모델을 알린다
            raise RuntimeError(f"{self.get_name()}: 눈금 {self._due} 의 사건을 엔진이 지나쳤다")
        if self._due == n and not self._fired:
            return hub.sim.engine.global_time    # 지금 낼 차례다. 엔진의 시계와 똑같은 값을 내놓는다
        if self._fired or self._inbox or self._due is None:
            return Infinite                      # 전이를 기다리거나 쉬고 있다
        return self._due * hub.sim.step

    def set_req_time(self, global_time, elapsed_time=0) -> None:
        self.RequestedTime = self.get_req_time()     # 요청 시각은 상태에서 정해진다. 엔진이 준 값은 쓰지 않는다

    # 전이 -------------------------------------------------------------------

    def _bag(self) -> dict:
        """받은 것을 포트마다 출처의 순서로 늘어놓는다. 참조 시뮬레이터와 같은 순서다."""
        return {port: [v for _, v in sorted(items, key=lambda x: x[0])] for port, items in sorted(self._inbox.items())}

    def _commit(self, n: int) -> None:
        hub, atom = self._hub, self._atom
        bag = self._bag()
        atom.now = n * hub.sim.step
        if self._fired and bag:
            atom.confluent(bag)
        elif self._fired:
            atom.internal()
        else:
            atom.external((n - self._last) * hub.sim.step, bag)
        self._last, self._fired, self._inbox = n, False, {}
        k = hub.ticks(self.get_name(), atom.ta())
        self._due = None if k is None else n + k


# ---------------------------------------------------------------------------
# 산출물
# ---------------------------------------------------------------------------

@dataclass
class Simulation:
    """pyevsim 실행기의 산출물: 모델과 연결이 등록된 엔진 하나."""

    engine: SysExecutor
    name: str                                    # 엔진 이름. SystemSimulator.get_engine(name)으로 찾을 수 있다
    step: float                                  # 엔진의 시간 간격. 계획의 시간 단위다
    models: dict = field(default_factory=dict)   # 경로에서 pyevsim 모델로
    where: dict = field(default_factory=dict)    # 모델(의 id)에서 경로로
    names: dict = field(default_factory=dict)    # 모델 이름에서 경로로
    types: dict = field(default_factory=dict)    # 경로에서 {포트: 타입}으로. pyevsim의 포트에는 타입이 없어 따로 적어 둔다
    log: list = field(default_factory=list)      # 출력 사건: (시각, 원자의 경로, 포트, 값)
    hub: Optional[_Hub] = None

    def tick(self) -> int:
        return round(self.engine.global_time / self.step)

    def now(self) -> float:
        return self.tick() * self.step

    def run(self, until: float) -> list:
        """시각 until까지 돌린다. 그 시각의 사건도 처리한다. 출력 사건의 기록을 돌려준다.

        pyevsim의 simulate(T)는 T보다 앞선 시각만 처리하므로 마지막 눈금의 반 칸 뒤까지 돌린다.
        """
        last = last_tick(until, self.step)
        span = (last + 0.5) * self.step - self.engine.global_time
        if span > 0:
            self.engine.simulate(span, _tm=False)
        self.check()
        lost = [t for t, _ in self.engine.input_event_queue if t <= last * self.step]
        if lost:                                 # 모든 모델이 쉬고 있으면 엔진은 예약된 외부 입력이 남아 있어도 끝난다
            raise RuntimeError(f"엔진이 시각 {self.now()} 에서 끝나 예약된 외부 입력 {len(lost)}개가 전달되지 않았다")
        return self.log

    def check(self) -> None:
        """격자 밖의 요청 시각 때문에 엔진이 멈춰 있지 않은지 본다.

        pyevsim은 요청 시각이 현재 시각과 같은 모델만 처리한다. 지나간 시각을 요청한 모델이
        있으면 오류 없이 그 모델과 그 뒤의 모든 모델이 멈춘다.
        """
        g = self.engine.global_time
        for path, m in self.models.items():
            if isinstance(m, Adapted):
                continue
            req = m.RequestedTime
            if req < g and not math.isclose(req, g, rel_tol=1e-9):
                raise OffGrid(f"{m.get_name()}: 요청 시각 {req} 이 지나갔거나 시간 간격 {self.step} 의 격자 위에 "
                              f"없어 엔진이 이 모델과 그 뒤의 모델을 처리하지 못한다")

    def leaves(self) -> dict:
        """경로에서 모델로. 공통 모델 기반이면 감싸기 전의 모델을 준다."""
        return {p: (m._atom if isinstance(m, Adapted) else m) for p, m in self.models.items()}

    def connections(self) -> Counter:
        """엔진에 등록된 연결을 개수와 함께 센다. 열쇠는 structure.flatten과 같은 꼴이다.

        엔진이 받는 곳 없는 출력을 위해 스스로 더하는 기본 수신 모델(dc)로 가는 연결은 뺀다.
        """
        out: Counter = Counter()
        for (src, sp), dests in self.engine.port_map.items():
            for dst, dp in dests:
                if dst is not self.engine.dmc:
                    out[((self._path_of(src), sp), (self._path_of(dst), dp))] += 1
        return out

    def _path_of(self, model) -> tuple:
        if model is None:
            return ()                            # 엔진의 경계: 뿌리의 포트
        if id(model) not in self.where:
            raise st.StructureError(f"계획에 없는 모델이 엔진에 있다: {model.get_name()}")
        return self.where[id(model)]

    def close(self) -> None:
        """엔진을 SystemSimulator의 등록부에서 지운다."""
        if SystemSimulator.get_engine_map().get(self.name) is self.engine:
            del SystemSimulator.get_engine_map()[self.name]

    def _tap(self, model, path: tuple) -> None:
        """pyevsim 모델의 출력을 사건 기록에 적는다. 모델의 행위는 바꾸지 않는다."""
        inner = model.output

        def output():
            msg = inner()
            if msg is not None:
                t = self.now()
                for m in (msg if isinstance(msg, list) else [msg]):
                    self.log.extend((t, path, m.get_dst(), v) for v in m.retrieve())
            return msg

        model.output = output


# ---------------------------------------------------------------------------
# 실행기
# ---------------------------------------------------------------------------

def _reserved() -> tuple:
    """pyevsim은 포트를 등록할 때 같은 이름의 속성을 객체에 만든다. 가려지면 안 되는 이름들."""
    model = set(dir(BehaviorModelExecutor(0, 0, "", ""))) | set(dir(Adapted)) | set(Adapted._OWN)
    engine = set(dir(SysExecutor(1, "reserved")))
    return frozenset(model), frozenset(engine)


_MODEL_NAMES, _ENGINE_NAMES = _reserved()


class PyevsimExecutor(Executor):
    """계획을 pyevsim 엔진으로 만든다.

    시간 단위는 계획에 실려 온 것(바인딩이 적은 것)을 쓴다. time_unit을 주면 그것과 같아야 하고, 어디에도
    없으면 1이다. 엔진의 시간 간격을 그 값으로 둔다. 모든 사건 시각이 그 정수배여야 한다. engine_name을
    주면 그 이름으로 엔진을 등록하고(같은 이름의 앞선 엔진을 대신한다), 주지 않으면 조립할 때마다 새 이름을 쓴다.
    """

    name = "pyevsim"

    def __init__(self, time_unit: Optional[float] = None, engine_name: Optional[str] = None, record: bool = True,
                 max_rounds: int = 100000) -> None:
        if time_unit is not None and not time_unit > 0:
            raise ValueError("시간 단위는 0보다 커야 한다")
        self.time_unit, self.engine_name, self.record, self.max_rounds = time_unit, engine_name, record, max_rounds

    # 규약 -------------------------------------------------------------------

    def conventions(self) -> list:
        return [self.check]

    def check(self, plan: dict) -> list:
        """P1: 포트 이름이 pyevsim 객체의 속성 이름과 겹치면 안 된다.

        pyevsim의 insert_input_port와 insert_output_port는 setattr(객체, 포트, 포트)를 한다. 포트
        이름이 output이면 모델의 출력 함수가 문자열로 바뀌어 엔진이 그 모델을 부르지 못한다.
        """
        out = []
        for path, c in st.walk(plan):
            if st.is_atom(c):
                out += [("P1", path, f"포트 이름 {p} 가 pyevsim 모델의 속성과 겹친다")
                        for p in sorted(c["ports"]) if p in _MODEL_NAMES]
            elif not path:
                out += [("P1", path, f"포트 이름 {p} 가 pyevsim 엔진의 속성과 겹친다")
                        for p in sorted(c["ports"]) if p in _ENGINE_NAMES]
        return out

    # 조립 -------------------------------------------------------------------

    def build(self, plan: dict, library: Mapping) -> Simulation:
        clash = self.check(plan)
        if clash:
            raise ValueError("pyevsim으로 만들 수 없는 계획이다: " + "; ".join(msg for _, _, msg in clash))
        unit = time_unit(plan, self.time_unit)
        name = self.engine_name or f"ses-{next(_SERIAL)}"
        sim = Simulation(SystemSimulator.register_engine(name, "VIRTUAL_TIME", unit), name, unit)
        try:
            self._fill(sim, plan, library)
        except Exception:
            sim.close()                              # 만들다 만 엔진을 등록부에 남기지 않는다
            raise
        return sim

    def _fill(self, sim: Simulation, plan: dict, library: Mapping) -> None:
        name = sim.name
        for path in sorted(st.atoms(plan)):          # 만든 순서가 객체 번호의 순서이고 엔진은 그 순서로 처리한다
            n = st.subtree(plan, path)
            body = library[n["module"]].body
            label = ref(path) or n.get("name", "")
            if isinstance(body, type) and issubclass(body, Atomic):
                if sim.hub is None:
                    sim.hub = _Hub(sim, self.max_rounds)
                model = Adapted(label or "root", name, body(label, **n["params"]), sim.hub, path, n["ports"])
            else:
                model = body(0, Infinite, label or "root", name, **n["params"])
                self._conforms(model, n, label or "root")
                if self.record:
                    sim._tap(model, path)
            sim.engine.register_entity(model)
            sim.models[path], sim.where[id(model)], sim.names[model.get_name()] = model, path, path
            sim.types[path] = {p: t for p, (t, _) in n["ports"].items()}
        if not st.is_atom(plan):
            for p, (_, direction) in plan["ports"].items():      # 뿌리의 포트는 엔진의 경계다
                (sim.engine.insert_input_port if direction == st.IN else sim.engine.insert_output_port)(p)
            sim.types[()] = {p: t for p, (t, _) in plan["ports"].items()}
        for ((a, ap), (b, bp)), count in sorted(st.flatten(plan).items()):
            for _ in range(count):                   # 길의 수만큼 등록한다. 엔진은 등록된 만큼 전달한다
                sim.engine.coupling_relation(sim.models[a] if a else None, ap, sim.models[b] if b else None, bp)

    @staticmethod
    def _conforms(model, n: dict, label: str) -> None:
        """본체가 만든 pyevsim 모델이 계획의 인터페이스를 가졌는지 본다."""
        who = f"모듈 {n['module']} 의 본체"
        if not isinstance(model, BehaviorModelExecutor):
            raise TypeError(f"{who}가 pyevsim 모델(BehaviorModelExecutor)을 만들지 않았다")
        if model.get_name() != label:
            raise ValueError(f"{who}가 만든 모델의 이름이 {label} 이 아니다. 엔진에서는 이름으로 원자를 찾는다")
        if model.get_create_time() != 0 or model.get_destruct_time() != Infinite:
            raise ValueError(f"{who}가 만든 모델의 생성 시각이 0이 아니거나 소멸 시각이 있다. 계획은 고정된 구조다")
        ins, outs = model.retrieve_input_ports(), model.retrieve_output_ports()
        for p, (_, direction) in n["ports"].items():
            if p not in (ins if direction == st.IN else outs):
                raise ValueError(f"{who}에 {'입력' if direction == st.IN else '출력'} 포트 {p} 가 없다")
        for p in list(ins) + list(outs):
            if hasattr(type(model), p):
                raise ValueError(f"{who}의 포트 이름 {p} 가 그 클래스의 속성을 가린다")

    # 관찰 -------------------------------------------------------------------

    def observe(self, sim: Simulation) -> dict:
        """엔진에서 구조를 다시 읽는다. 엔진에 계층이 없으므로 한 층짜리 구조가 된다.

        원자의 이름은 경로를 이은 것이다. 구조에서 결합은 관계이므로 여러 번 등록된 연결도 한 번
        적힌다. 등록된 횟수는 Simulation.connections로 센다. 엔진이 스스로 두는 기본 수신 모델은 뺀다.
        """
        eng = sim.engine
        kids: dict = {}
        for models in eng.model_map.values():
            for m in models:
                if m is eng.dmc:
                    continue
                types = sim.types.get(sim._path_of(m), {})
                ports = {p: (types.get(p), st.IN) for p in m.retrieve_input_ports()}
                ports.update({p: (types.get(p), st.OUT) for p in m.retrieve_output_ports()})
                if m.get_name() in kids:
                    raise st.StructureError(f"이름이 같은 모델이 둘이다: {m.get_name()}")
                kids[m.get_name()] = st.node(ports)
        types = sim.types.get((), {})
        ports = {p: (types.get(p), st.IN) for p in eng.retrieve_input_ports()}
        ports.update({p: (types.get(p), st.OUT) for p in eng.retrieve_output_ports()})
        eic, eoc, ic = [], [], []
        for (src, sp), dests in eng.port_map.items():
            for dst, dp in dests:
                if dst is eng.dmc:
                    continue
                sim._path_of(src), sim._path_of(dst)         # 계획에 없는 모델이면 여기서 알린다
                if src is None:
                    eic.append((sp, (dst.get_name(), dp)))
                elif dst is None:
                    eoc.append(((src.get_name(), sp), dp))
                else:
                    ic.append(((src.get_name(), sp), (dst.get_name(), dp)))
        return st.node(ports, kids, eic, eoc, ic)
