"""센서 네트워크 사례(docs/ses-platform/examples/wsn.ses.yaml)의 DEVS 모델베이스.

구조는 Nam, Kim (2021)의 WSN-SES/MB를 따랐지만 원자 모델의 행위는 문헌의 상태도를 옮긴 것이
아니다. 같은 역할을 하는 작은 모델이다. 사건 생성기가 센서장의 한 점에서 사건을 내고, 그 점에서
감지 거리 안에 있는 센서가 한 눈금 뒤에 기지국에 알리고, 기지국이 변환기에 보고한다.

FUNCTIONS 는 문서의 식이 이름으로 부르는 함수들이다. 센서를 정사각 격자에 놓는다.
"""

import math
import random

from ses_core.devs import INF, Atomic, module_of


def side(count: int) -> int:
    """센서 count 개를 놓을 정사각 격자의 한 변의 칸 수."""
    return max(1, math.isqrt(count - 1) + 1)


def grid_x(index: int, count: int, field: int) -> int:
    k = side(count)
    return (index % k) * field // k + field // (2 * k)


def grid_y(index: int, count: int, field: int) -> int:
    k = side(count)
    return (index // k) * field // k + field // (2 * k)


FUNCTIONS = {"grid_x": grid_x, "grid_y": grid_y}


def events_of(seed: int, field: int, count: int) -> list:
    """생성기가 내는 사건들의 위치. 시험이 같은 것을 따로 계산할 때도 쓴다."""
    rng = random.Random(seed)
    return [(rng.randrange(field), rng.randrange(field)) for _ in range(count)]


class Genr(Atomic):
    PORTS = {"event": ("Event", "out")}
    PARAMS = {"field": ("int",), "period": ("time", 2.0), "events": ("int", 50), "seed": ("int", 7)}

    def init(self):
        self.where = events_of(self.seed, self.field, self.events)
        self.sent = 0

    def ta(self):
        return self.period if self.sent < len(self.where) else INF

    def output(self):
        x, y = self.where[self.sent]
        return {"event": [{"id": self.sent, "x": x, "y": y}]}

    def internal(self):
        self.sent += 1


class Sensor(Atomic):
    PORTS = {"event": ("Event", "in"), "packet": ("Packet", "out")}
    REQUIRED = ("event",)
    PARAMS = {"id": ("int",), "x": ("int",), "y": ("int",), "reach": ("int",), "delay": ("time", 1.0)}

    def init(self):
        self.pending, self.left, self.detected = [], INF, 0

    def ta(self):
        return self.left if self.pending else INF

    def output(self):
        return {"packet": [{"event": e, "sensor": self.id} for e in self.pending]}

    def internal(self):
        self.pending, self.left = [], INF

    def external(self, elapsed, bag):
        if self.pending:
            self.left -= elapsed
        for e in bag.get("event", ()):
            if (e["x"] - self.x) ** 2 + (e["y"] - self.y) ** 2 <= self.reach ** 2:
                if not self.pending:
                    self.left = self.delay
                self.pending.append(e["id"])
                self.detected += 1


class Bs(Atomic):
    PORTS = {"packet": ("Packet", "in"), "report": ("Report", "out")}
    REQUIRED = ("packet",)

    def init(self):
        self.buffer, self.received = [], 0

    def ta(self):
        return 0.0 if self.buffer else INF

    def output(self):
        return {"report": list(self.buffer)}

    def internal(self):
        self.buffer = []

    def external(self, elapsed, bag):
        packets = bag.get("packet", ())
        self.buffer += packets
        self.received += len(packets)


class Transd(Atomic):
    PORTS = {"report": ("Report", "in")}
    REQUIRED = ("report",)

    def init(self):
        self.by_event, self.last = {}, None

    def external(self, elapsed, bag):
        for r in bag.get("report", ()):
            self.by_event.setdefault(r["event"], []).append(r["sensor"])
            self.last = self.now


LIBRARY = {m.name: m for m in (module_of(c) for c in (Genr, Sensor, Bs, Transd))}
