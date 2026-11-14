"""처리 시스템(processing_system.ses.yaml)의 pyevsim 모델베이스.

examples/processing_mb.py와 같은 인터페이스를 pyevsim의 모델(BehaviorModelExecutor)로 쓴 것이다.
SES와 바인딩은 그대로이고 모듈의 본체만 다르다. pyevsim 실행기가 본체를
body(0, Infinite, 이름, 엔진 이름, **매개변수)로 불러 엔진에 등록한다.

pyevsim의 의미에 맞춰 쓴 곳이 둘 있다 (docs/ses-platform/15_pyevsim_executor.md 2절).
- 엔진은 입력을 받은 모델의 다음 사건 시각을 다시 잡는다. 서버는 다른 서버로 가는 일감이
  지나갈 때 cancel_rescheduling으로 남은 처리 시간을 지킨다.
- 엔진은 같은 시각의 사건을 하나씩 처리하고 입력을 바로 전이로 넘긴다. 버퍼는 입력을 받을
  때마다 보낼 수 있는지 다시 본다.
"""

import random

from pyevsim import BehaviorModelExecutor, Infinite, SysMessage, SystemSimulator

from ses_core.executor import Module

from . import processing_mb


class Native(BehaviorModelExecutor):
    """공통 부분: 상태와 포트를 표로 적는다."""

    STATES: dict = {}                            # 상태 이름에서 머무는 시간으로. 첫 상태가 초기 상태다
    INPUTS: tuple = ()
    OUTPUTS: tuple = ()

    def __init__(self, instance_time, destruct_time, name, engine_name, **params):
        BehaviorModelExecutor.__init__(self, instance_time, destruct_time, name, engine_name)
        for key, value in params.items():
            setattr(self, key, value)
        for state, stay in self.states().items():
            self.insert_state(state, stay)
        self.init_state(next(iter(self.states())))
        for p in self.INPUTS:
            self.insert_input_port(p)
        for p in self.OUTPUTS:
            self.insert_output_port(p)
        self.init()

    def states(self) -> dict:
        return self.STATES

    def init(self) -> None:
        pass

    def clock(self) -> float:
        return SystemSimulator.get_engine(self.engine_name).get_global_time()

    def message(self, port, *values):
        msg = SysMessage(self.get_name(), port)
        msg.extend(values)
        return msg

    def ext_trans(self, port, msg) -> None:
        pass

    def int_trans(self) -> None:
        pass

    def output(self):
        return None


class Generator(Native):
    OUTPUTS = ("out",)

    def states(self):
        return {"GENERATE": self.interarrival}

    def init(self):
        self.rng, self.count = random.Random(self.seed), 0

    def output(self):
        return self.message("out", {"id": self.count, "priority": self.rng.randrange(3), "created_at": self.clock()})

    def int_trans(self):
        self.count += 1


class FifoBuffer(Native):
    STATES = {"WAIT": Infinite, "SEND": 0}
    INPUTS = ("in", "ack")
    OUTPUTS = ("out",)

    def init(self):
        self.queue, self.free, self.sending, self.dropped = [], [], None, 0

    def pick(self):
        return self.queue.pop(0)

    def _dispatch(self):
        if self.sending is None and self.queue and self.free:
            self.sending = dict(self.pick(), to=self.free.pop(0))
        self._cur_state = "SEND" if self.sending is not None else "WAIT"

    def ext_trans(self, port, msg):
        if port == "in":
            for job in msg.retrieve():
                if len(self.queue) < self.capacity:
                    self.queue.append(job)
                else:
                    self.dropped += 1
        elif port == "ack":
            self.free += [ack["server"] for ack in msg.retrieve()]
        self._dispatch()

    def output(self):
        return self.message("out", self.sending)

    def int_trans(self):
        self.sending = None
        self._dispatch()


class PriorityBuffer(FifoBuffer):
    def pick(self):
        best = min(range(len(self.queue)), key=lambda i: (self.queue[i]["priority"], i))
        return self.queue.pop(best)


class Server(Native):
    INPUTS = ("in",)
    OUTPUTS = ("out", "done")

    def states(self):
        return {"ANNOUNCE": 0, "IDLE": Infinite, "BUSY": self.service_time}

    def init(self):
        self.job, self.served = None, 0

    def ext_trans(self, port, msg):
        for job in msg.retrieve():
            if job.get("to") == self.get_name() and self._cur_state == "IDLE":
                self._cur_state, self.job = "BUSY", job
                return
        self.cancel_rescheduling()               # 내 일감이 아니다. 남은 시간은 그대로 흐른다

    def output(self):
        if self._cur_state == "ANNOUNCE":
            return self.message("done", {"server": self.get_name(), "job_id": -1})
        return [self.message("done", {"server": self.get_name(), "job_id": self.job["id"]}),
                self.message("out", self.job)]

    def int_trans(self):
        if self._cur_state == "BUSY":
            self.served += 1
        self._cur_state, self.job = "IDLE", None


class Collector(Native):
    STATES = {"WAIT": Infinite}
    INPUTS = ("in",)

    def init(self):
        self.done = []

    def ext_trans(self, port, msg):
        self.done += [(job["id"], self.clock()) for job in msg.retrieve()]


class Pool(Server):
    """서버 풀 전체를 모델 하나로 본 것."""


def _module(cls) -> Module:
    """인터페이스 선언은 공통 모델베이스의 것을 그대로 쓰고 본체만 바꾼다."""
    m = processing_mb.LIBRARY[cls.__name__]
    return Module(m.name, m.ports, m.required, m.params, cls)


LIBRARY = {m.name: m for m in map(_module, (Generator, FifoBuffer, PriorityBuffer, Server, Collector, Pool))}
