"""모델 베이스. 구성요소가 무엇을 하는지를 적는다. SES 문서는 구조만 정한다.

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
    PORTS = {"out": ("Job", "out")}
    PARAMS = {"period": ("time", 2.0)}

    def init(self):
        self.count = 0

    def ta(self):
        return self.period

    def output(self):
        return {"out": [{"id": self.count}]}

    def internal(self):
        self.count += 1


class Worker(Atomic):
    """작업을 하나씩 처리한다. 처리하는 동안 온 작업은 줄을 선다."""
    PORTS = {"in": ("Job", "in"), "out": ("Job", "out")}
    REQUIRED = ("in",)
    PARAMS = {"service": ("time", 1.0), "me": ("int", 0), "of": ("int", 1)}

    def init(self):
        self.queue, self.left = [], INF

    def ta(self):
        return self.left

    def output(self):
        return {"out": [self.queue[0]]}

    def internal(self):
        self.queue.pop(0)
        self.left = self.service if self.queue else INF

    def external(self, elapsed, bag):
        if self.queue:
            self.left -= elapsed                 # 처리하던 작업의 남은 시간
        self.queue += [job for job in bag.get("in", []) if job["id"] % self.of == self.me]
        if self.queue and self.left == INF:
            self.left = self.service


class Inspector(Atomic):
    """every 번째 작업마다 하나를 버리고 나머지는 바로 넘긴다."""
    PORTS = {"in": ("Job", "in"), "ok": ("Job", "out")}
    REQUIRED = ("in",)
    PARAMS = {"every": ("int", 3)}

    def init(self):
        self.seen, self.passing = 0, []

    def ta(self):
        return 0.0 if self.passing else INF

    def output(self):
        return {"ok": list(self.passing)}

    def internal(self):
        self.passing = []

    def external(self, elapsed, bag):
        for job in bag.get("in", []):
            self.seen += 1
            if self.seen % self.every:
                self.passing.append(job)


class Sink(Atomic):
    PORTS = {"in": ("Job", "in")}
    REQUIRED = ("in",)

    def init(self):
        self.received = []

    def external(self, elapsed, bag):
        self.received += [(self.now, job["id"]) for job in bag.get("in", [])]


LIBRARY = {m.name: m for m in (module_of(c) for c in (Source, Worker, Inspector, Sink))}
