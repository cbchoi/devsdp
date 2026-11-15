"""처리 시스템(processing_system.ses.yaml)의 DEVS 모델베이스.

SES는 구조만 정한다. 구성요소가 무엇을 하는지는 여기 있다. 클래스마다 인터페이스
(PORTS, REQUIRED, PARAMS)를 선언하고, 바인딩이 정의 이름을 이 클래스들에 잇는다.

시간 전진으로 쓰는 매개변수(도착 간격, 서비스 시간)는 타입을 time으로 적는다. 그 값은 바인딩이
적은 시간 단위의 정수배여야 하고, 아니면 그 변이는 실행 가능하지 않다(B5).

서버 풀의 결합은 일감을 모든 서버에 뿌린다. 그래서 버퍼가 일감에 받을 서버의 이름을 적고,
서버는 자기 이름이 적힌 일감만 받는다. 서버는 비게 되면 버퍼에 알린다.
"""

import random

from ses_core.devs import INF, Atomic, module_of


class Generator(Atomic):
    PORTS = {"out": ("Job", "out")}
    PARAMS = {"interarrival": ("time", 1.0), "seed": ("int", 0)}

    def init(self):
        self.rng = random.Random(self.seed)
        self.count = 0

    def ta(self):
        return self.interarrival

    def output(self):
        return {"out": [{"id": self.count, "priority": self.rng.randrange(3), "created_at": self.now}]}

    def internal(self):
        self.count += 1


class FifoBuffer(Atomic):
    PORTS = {"in": ("Job", "in"), "ack": ("Ack", "in"), "out": ("Job", "out")}
    REQUIRED = ("in",)
    PARAMS = {"capacity": ("int", 100)}

    def init(self):
        self.queue, self.free, self.sending, self.dropped = [], [], None, 0

    def pick(self):
        return self.queue.pop(0)

    def _dispatch(self):
        if self.sending is None and self.queue and self.free:
            self.sending = dict(self.pick(), to=self.free.pop(0))

    def ta(self):
        return 0.0 if self.sending is not None else INF

    def output(self):
        return {"out": [self.sending]}

    def internal(self):
        self.sending = None
        self._dispatch()

    def external(self, elapsed, bag):
        for job in bag.get("in", ()):
            if len(self.queue) < self.capacity:
                self.queue.append(job)
            else:
                self.dropped += 1
        self.free += [ack["server"] for ack in bag.get("ack", ())]
        self._dispatch()


class PriorityBuffer(FifoBuffer):
    PARAMS = {"capacity": ("int", 100), "levels": ("int", 3)}

    def pick(self):
        best = min(range(len(self.queue)), key=lambda i: (self.queue[i]["priority"], i))
        return self.queue.pop(best)


class Server(Atomic):
    PORTS = {"in": ("Job", "in"), "out": ("Job", "out"), "done": ("Ack", "out")}
    REQUIRED = ("in",)
    PARAMS = {"service_time": ("time", 2.0)}

    def init(self):
        self.phase, self.job, self.served, self.left = "announce", None, 0, 0.0

    def ta(self):
        return {"announce": 0.0, "idle": INF, "busy": self.left}[self.phase]

    def output(self):
        if self.phase == "announce":
            return {"done": [{"server": self.name, "job_id": -1}]}
        return {"out": [self.job], "done": [{"server": self.name, "job_id": self.job["id"]}]}

    def internal(self):
        if self.phase == "busy":
            self.served += 1
        self.phase, self.job = "idle", None

    def external(self, elapsed, bag):
        if self.phase == "busy":                              # 다른 서버로 가는 일감이 지나가도 남은 시간은 흐른다
            self.left -= elapsed
        for job in bag.get("in", ()):
            if job.get("to") == self.name and self.phase == "idle":
                self.phase, self.job, self.left = "busy", job, self.service_time


class Collector(Atomic):
    PORTS = {"in": ("Job", "in")}
    REQUIRED = ("in",)
    PARAMS = {"log_path": ("str", "")}

    def init(self):
        self.done = []

    def external(self, elapsed, bag):
        self.done += [(job["id"], self.now) for job in bag.get("in", ())]


class Pool(Atomic):
    """서버 풀 전체를 모델 하나로 본 것. 서버 풀 정의에 바로 묶으면 그 아래는 펼치지 않는다."""
    PORTS = {"in": ("Job", "in"), "out": ("Job", "out"), "done": ("Ack", "out")}
    REQUIRED = ("in",)
    PARAMS = {"service_time": ("time", 2.0)}

    init = Server.init
    ta = Server.ta
    output = Server.output
    internal = Server.internal
    external = Server.external


LIBRARY = {m.name: m for m in (module_of(c) for c in
                               (Generator, FifoBuffer, PriorityBuffer, Server, Collector, Pool))}
