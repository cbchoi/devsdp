"""센서 노드(sensor_node.ses.yaml)의 DEVS 모델베이스.

같은 SES에 하드웨어 모듈 라이브러리(sensor_node.hwlib.yaml)를 붙이면 배선표가 되고,
이 모델베이스를 붙이면 시뮬레이션 모델이 된다. 여기의 모델은 전원이 들어온 뒤에 움직인다.
"""

from ses_core.devs import INF, Atomic, module_of


class PowerSource(Atomic):
    PORTS = {"out": ("Power", "out")}
    PARAMS = {"capacity_ma": ("int",)}

    def init(self):
        self.started = False

    def ta(self):
        return INF if self.started else 0.0

    def output(self):
        return {"out": [{"capacity_ma": self.capacity_ma}]}

    def internal(self):
        self.started = True


class Powered(Atomic):
    """전원이 들어와야 주기적으로 일하는 모델의 바탕."""

    def init(self):
        self.on, self.left, self.ticks = False, INF, 0

    def ta(self):
        return self.left

    def internal(self):
        self.ticks += 1
        self.left = self.period

    def external(self, elapsed, bag):
        if self.on:
            self.left -= elapsed
        elif bag.get("pwr"):
            self.on, self.left = True, self.period
        self.receive(bag)

    def receive(self, bag):
        pass


class Probe(Powered):
    PORTS = {"pwr": ("Power", "in"), "data": ("Reading", "out")}
    REQUIRED = ("pwr",)
    PARAMS = {"address": ("int",), "period": ("float", 1.0), "load_ma": ("int", 1)}

    def output(self):
        return {"data": [{"address": self.address, "value": self.address * 10 + self.ticks}]}


class Controller(Powered):
    PORTS = {"pwr": ("Power", "in"), "sense": ("Reading", "in"),
             "tx": ("Packet", "out"), "show": ("Frame", "out")}
    REQUIRED = ("pwr", "sense")
    PARAMS = {"period": ("float", 1.0), "load_ma": ("int", 20)}

    def init(self):
        super().init()
        self.readings, self.addresses = [], set()

    def receive(self, bag):
        for r in bag.get("sense", ()):
            self.readings.append(r["value"])
            self.addresses.add(r["address"])

    def output(self):
        packet = {"seq": self.ticks, "count": len(self.readings), "sources": sorted(self.addresses)}
        return {"tx": [packet], "show": [{"text": f"{len(self.addresses)} sources"}]}

    def internal(self):
        super().internal()
        self.readings = []


class Sink(Atomic):
    """받기만 하는 모델: 무선과 화면."""
    INPUT = ""

    def init(self):
        self.on, self.received = False, []

    def external(self, elapsed, bag):
        self.on = self.on or bool(bag.get("pwr"))
        if self.on:
            self.received += bag.get(self.INPUT, ())


class Radio(Sink):
    PORTS = {"pwr": ("Power", "in"), "rx": ("Packet", "in")}
    REQUIRED = ("pwr", "rx")
    PARAMS = {"load_ma": ("int", 0)}
    INPUT = "rx"


class Display(Sink):
    PORTS = {"pwr": ("Power", "in"), "frame": ("Frame", "in")}
    REQUIRED = ("pwr",)
    PARAMS = {"load_ma": ("int", 0)}
    INPUT = "frame"


LIBRARY = {m.name: m for m in (module_of(c) for c in (PowerSource, Probe, Controller, Radio, Display))}
