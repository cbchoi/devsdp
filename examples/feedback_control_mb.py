"""피드백 제어 사례(docs/ses-platform/examples/feedback_control.ses.yaml)의 DEVS 모델베이스.

Folkerts et al. (2019)의 기본 모델(Constant, Step, Feedback, PID, TransferFunction, Add)은
OpenModelica 의 연속 시간 모델이다. 여기서는 고정 간격 h(바인딩의 시간 단위)로 이산화했다.

신호 흐름을 사건으로 옮기는 방법
- 상태를 가진 블록(전달함수, PID)과 원천은 h 마다 한 걸음 간다. 지난 시각의 입력으로 상태를 올리고
  (전진 오일러) 출력을 낸다.
- 상태가 없는 블록(Feedback, Add)과, 입력이 출력에 바로 비치는 블록은 입력을 받으면 같은 시각에
  출력을 다시 낸다. 한 시각 안에서 값이 여러 번 나갈 수 있고 마지막 값이 그 시각의 값이다.
- 되먹임 고리는 공정(입력이 출력에 바로 비치지 않는 전달함수)에서 끊긴다. 그래서 같은 시각의 사건이
  끝없이 돌지 않는다.

문헌의 수치와 견주려고 만든 것이 아니다. 구조 변이마다 모델이 만들어지고 돌아가는 것을 보이기 위한 것이다.
"""

from ses_core.devs import INF, Atomic, module_of

H = 0.125                                    # 이산화 간격. 바인딩의 time_unit 과 같아야 한다


class _Clocked(Atomic):
    """h 마다 한 걸음 가고, 입력이 출력에 바로 비치면 입력을 받은 시각에 다시 출력하는 블록.

    출력 함수는 상태를 바꾸지 않는다. 걸음의 시각에는 한 걸음 간 뒤의 상태(ahead)로 출력을 계산하고,
    내부 전이가 그 상태로 옮긴다. 한 걸음은 지난 시각에 마지막으로 받은 입력으로 간다(전진 오일러).
    """

    PORTS = {"y": ("Signal", "out")}
    direct = False                           # 입력이 출력에 바로 비치는가

    def init(self):
        self.left, self.dirty = 0.0, False   # 시각 0에 첫 출력을 낸다
        self.u, self.state = 0.0, self.begin()

    def begin(self):
        """초기 상태."""
        return None

    def ahead(self):
        """한 걸음 간 뒤의 상태. 지금의 상태와 지난 시각의 입력에서 정해진다."""
        return self.state

    def value(self, state) -> float:
        raise NotImplementedError

    def ta(self):
        return 0.0 if self.dirty else self.left

    def output(self):
        return {"y": [{"value": self.value(self.state if self.dirty else self.ahead())}]}

    def internal(self):
        if self.dirty:
            self.dirty = False
        else:
            self.state, self.left = self.ahead(), H

    def external(self, elapsed, bag):
        self.left -= elapsed
        self.receive(bag)

    def confluent(self, bag):
        self.internal()
        self.receive(bag)

    def receive(self, bag):
        for values in bag.values():
            self.u = values[-1]["value"]
        self.dirty = self.direct


class Constant(_Clocked):
    PARAMS = {"k": ("float", 0.0)}

    def value(self, state):
        return self.k


class Step(_Clocked):
    PARAMS = {"height": ("float", 1.0), "start": ("time", 1.0)}

    def value(self, state):
        return self.height if self.now >= self.start else 0.0


class TransferFunction(_Clocked):
    """1차 전달함수 (b1 s + b0) / (a1 s + a0). b1 이 0이 아니면 입력이 출력에 바로 비친다.

    상태 x 는 x' = (u - a0 x) / a1 을 따르고 출력은 y = (b0 - b1 a0 / a1) x + (b1 / a1) u 다.
    """

    PORTS = {"u": ("Signal", "in"), "y": ("Signal", "out")}
    REQUIRED = ("u",)
    PARAMS = {"b1": ("float", 0.0), "b0": ("float", 1.0), "a1": ("float", 1.0), "a0": ("float", 1.0)}

    def begin(self):
        self.direct = self.b1 != 0.0
        return 0.0

    def ahead(self):
        return self.state + H * (self.u - self.a0 * self.state) / self.a1

    def value(self, x):
        return (self.b0 - self.b1 * self.a0 / self.a1) * x + (self.b1 / self.a1) * self.u


class PID(_Clocked):
    """y = k (e + (1 / Ti) 적분(e) + Td e'). 입력이 출력에 바로 비친다. 상태는 (적분, 지난 시각의 입력)이다."""

    PORTS = {"u": ("Signal", "in"), "y": ("Signal", "out")}
    REQUIRED = ("u",)
    PARAMS = {"k": ("float", 1.0), "Ti": ("float", 1.0), "Td": ("float", 0.0)}
    direct = True

    def begin(self):
        return (0.0, 0.0)

    def ahead(self):
        return (self.state[0] + H * self.u, self.u)

    def value(self, state):
        integral, before = state
        return self.k * (self.u + integral / self.Ti + self.Td * (self.u - before) / H)


class _Static(Atomic):
    """상태가 없는 블록. 입력을 받으면 같은 시각에 출력을 낸다."""

    def init(self):
        self.u1, self.u2, self.dirty = 0.0, 0.0, False

    def ta(self):
        return 0.0 if self.dirty else INF

    def output(self):
        return {"y": [{"value": self.value()}]}

    def internal(self):
        self.dirty = False

    def external(self, elapsed, bag):
        for port, values in bag.items():
            setattr(self, port, values[-1]["value"])
        self.dirty = True

    def confluent(self, bag):
        self.external(0.0, bag)


class Feedback(_Static):
    PORTS = {"u1": ("Signal", "in"), "u2": ("Signal", "in"), "y": ("Signal", "out")}
    REQUIRED = ("u1", "u2")

    def value(self):
        return self.u1 - self.u2


class Add(_Static):
    PORTS = {"u1": ("Signal", "in"), "u2": ("Signal", "in"), "y": ("Signal", "out")}
    REQUIRED = ("u1", "u2")
    PARAMS = {"k1": ("float", 1.0), "k2": ("float", 1.0)}

    def value(self):
        return self.k1 * self.u1 + self.k2 * self.u2


LIBRARY = {m.name: m for m in (module_of(c) for c in (Constant, Step, TransferFunction, PID, Feedback, Add))}


def response(log: list, path: tuple) -> list:
    """사건 기록에서 한 블록의 출력을 (시각, 값)의 열로 읽는다. 한 시각의 마지막 값이 그 시각의 값이다."""
    out: dict = {}
    for t, p, port, v in log:
        if p == path and port == "y":
            out[t] = v["value"]
    return sorted(out.items())


def quality(ys: list, start: float, band: float = 0.05) -> tuple:
    """외란이 들어온 뒤의 (가장 큰 벗어남, 벗어남이 band 안으로 들어와 머무는 데 걸린 시간)."""
    after = [(t, y) for t, y in ys if t >= start]
    peak = max(abs(y) for _, y in after)
    outside = [t for t, y in after if abs(y) > band]
    return peak, (outside[-1] - start if outside else 0.0)
