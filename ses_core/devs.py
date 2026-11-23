"""DEVS 실행기: 가장 작은 참조 시뮬레이터 (docs/ses-platform/14_executors.md 5절).

SES에 DEVS 실행기를 붙이면 SES/MB가 된다는 것을 실제로 돌려 보이기 위한 것이다.
병렬 DEVS(동시에 일어난 사건을 한꺼번에 처리하고, 입력은 묶음으로 받는다)의 추상
시뮬레이터를 그대로 옮겼다. pyevsim이나 evsimpp를 대신하려는 것이 아니다.

두 가지 방식으로 실행한다.
- 계층 실행: 결합 모델마다 조정자가 있어 자식의 출력을 결합대로 나른다.
- 평탄 실행: 계층을 풀어 원자 모델과 평탄화된 연결만으로 나른다.
두 방식의 사건 기록이 같다는 것이 결합에 대한 닫힘이다. 문헌의 정리이며 여기서는
무작위 구조에서 확인만 한다.

시각은 시간 단위의 눈금으로 센다. 원자 모델의 시간 전진은 시간 단위의 정수배여야 하고, 모델과
기록에 보이는 시각은 눈금의 수에 시간 단위를 곱한 값이다. 실수의 덧셈으로 시각을 쌓지 않으므로
같은 시각인지가 정수의 비교로 정해진다. 다른 실행기(pyevsim, cevsim)도 같은 방법으로 센다.
"""

from __future__ import annotations

from typing import Mapping, Optional

from . import structure as st
from .executor import Executor, last_tick, same_unit, ticks, time_unit

INF = float("inf")


class Atomic:
    """원자 모델. 하위 클래스가 인터페이스(PORTS, REQUIRED, PARAMS)와 네 함수를 채운다."""

    PORTS: Mapping[str, tuple] = {}          # 포트 이름에서 (타입, 방향)으로
    REQUIRED: tuple = ()                     # 구동되어야 하는 입력 포트
    PARAMS: Mapping[str, tuple] = {}         # 매개변수 이름에서 (타입, 기본값)으로. 기본값이 없으면 (타입,)

    def __init__(self, name: str, **params) -> None:
        self.name = name
        self.now = 0.0
        for key, value in params.items():
            setattr(self, key, value)
        self.init()

    def init(self) -> None:
        """초기 상태."""

    def ta(self) -> float:
        """다음 내부 사건까지 남은 시간. 시간 단위의 음이 아닌 정수배이거나 INF여야 한다."""
        return INF

    def output(self) -> dict:
        """내부 사건 직전의 출력: 포트 이름에서 값의 목록으로."""
        return {}

    def internal(self) -> None:
        """내부 전이."""

    def external(self, elapsed: float, bag: dict) -> None:
        """외부 전이. elapsed는 마지막 전이에서 흐른 시간이고 bag은 포트 이름에서 값의 목록으로."""

    def confluent(self, bag: dict) -> None:
        """내부 사건과 입력이 같은 시각에 겹쳤을 때. 기본은 내부 전이 뒤에 외부 전이."""
        self.internal()
        self.external(0.0, bag)


class Coupled:
    """결합 모델: 자식과 세 종류의 결합."""

    def __init__(self, name: str, ports: Mapping, children: Mapping, eic=(), eoc=(), ic=()) -> None:
        self.name, self.ports, self.children = name, dict(ports), dict(children)
        # 결합은 관계다. 같은 결합을 두 번 적어도 메시지는 한 번 간다. 평탄 실행과 같아야 한다
        self.eic, self.eoc, self.ic = list(dict.fromkeys(eic)), list(dict.fromkeys(eoc)), list(dict.fromkeys(ic))


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def _leaves(model, path=()) -> dict:
    if isinstance(model, Coupled):
        out = {}
        for name, child in model.children.items():
            out.update(_leaves(child, path + (name,)))
        return out
    return {path: model}


def _bag(inbox: dict) -> dict:
    """받은 것을 출처의 순서로 늘어놓는다. 계층 실행과 평탄 실행이 같은 순서를 보게 하기 위해서다."""
    return {port: [v for _, v in sorted(items, key=lambda x: x[0])] for port, items in sorted(inbox.items())}


def _fire(atom: Atomic, n: int, unit: float, last: dict, path: tuple, imminent: bool, inbox: dict) -> None:
    """눈금 n에서의 전이. 모델에 주는 시각과 흐른 시간은 눈금의 수에 시간 단위를 곱한 값이다."""
    atom.now = n * unit
    if imminent and inbox:
        atom.confluent(_bag(inbox))
    elif imminent:
        atom.internal()
    elif inbox:
        atom.external((n - last[path]) * unit, _bag(inbox))
    else:
        return
    last[path] = n


def simulate(model, until: float, flat: bool = False, max_steps: int = 100000, unit: Optional[float] = None) -> list:
    """시뮬레이션을 돌리고 원자 모델의 출력 사건을 (시각, 원자의 경로, 포트, 값)의 목록으로 돌려준다.

    unit은 시간 단위다. 주지 않으면 모델에 적힌 것(DevsExecutor가 적는다)을 쓰고, 그것도 없으면 1이다.
    둘 다 있으면 같아야 한다. 시각 until까지 돌린다. 그 시각의 사건도 처리한다. until이 INF이면 사건이 없어질
    때까지 돌린다.
    """
    u = same_unit(unit, getattr(model, "_time_unit", None))
    leaves = _leaves(model)
    who = {p: "/".join(p) or getattr(a, "name", "") for p, a in leaves.items()}
    last = {p: 0 for p in leaves}                         # 마지막으로 전이한 눈금
    due = {p: ticks(who[p], a.ta(), u) for p, a in leaves.items()}      # 다음 내부 사건의 눈금. 쉬고 있으면 None
    end = INF if until == INF else last_tick(until, u)
    routes: dict = {}
    if flat:                                              # 평탄화된 연결: (출발 자리)에서 도착 자리들로
        for (s, t), k in st.flatten(observe(model)).items():
            routes.setdefault(s, []).extend([t] * k)
    log: list = []
    for _ in range(max_steps):
        n = min((d for d in due.values() if d is not None), default=None)
        if n is None or n > end:
            return log
        t = n * u
        imminent = sorted(p for p in leaves if due[p] == n)
        emitted: dict = {}                                # (경로, 포트)에서 값의 목록으로
        for p in imminent:
            leaves[p].now = t
            for port, values in sorted(leaves[p].output().items()):
                if values:                                # 값이 없는 출력은 보내지 않은 것이다. 받는 쪽에 사건이 없다
                    emitted[(p, port)] = list(values)
                    log.extend((t, p, port, v) for v in values)
        inbox: dict = {p: {} for p in leaves}
        if flat:
            for src, values in emitted.items():
                for (dst, dport) in routes.get(src, ()):
                    if dst:                               # 뿌리의 출력 포트로 나가는 것은 받을 원자가 없다
                        inbox[dst].setdefault(dport, []).extend(
                            ((src, i), v) for i, v in enumerate(values))
        else:
            _route(model, (), emitted, inbox)
        for p in leaves:
            if due[p] == n or inbox[p]:
                _fire(leaves[p], n, u, last, p, due[p] == n, inbox[p])
                k = ticks(who[p], leaves[p].ta(), u)
                due[p] = None if k is None else n + k
    raise RuntimeError("시뮬레이션이 정해진 걸음 수 안에 끝나지 않았다")


def _route(model, path: tuple, emitted: dict, inbox: dict) -> dict:
    """계층 실행의 한 걸음: 자식의 출력을 결합대로 나른다. 이 모델이 밖으로 내는 것을 돌려준다.

    값에는 출처(원자의 자리와 묶음 안의 순번)를 달아 둔다. 조정자는 메시지를 위로 올리고(외부
    출력 결합), 옆으로 건네고(내부 결합), 아래로 내린다(외부 입력 결합).
    """
    if not isinstance(model, Coupled):
        return {port: [((src, i), v) for i, v in enumerate(values)]
                for src, values in emitted.items() if src[0] == path for port in [src[1]]}
    outs = {name: _route(child, path + (name,), emitted, inbox) for name, child in model.children.items()}
    for (a, ap), (b, bp) in model.ic:
        _deliver(model.children[b], path + (b,), bp, outs[a].get(ap, ()), inbox)
    mine: dict = {}
    for (child, cp), sp in model.eoc:
        mine.setdefault(sp, []).extend(outs[child].get(cp, ()))
    return mine


def _deliver(model, path: tuple, port: str, items, inbox: dict) -> None:
    if not items:
        return
    if isinstance(model, Coupled):
        for sp, (child, cp) in model.eic:
            if sp == port:
                _deliver(model.children[child], path + (child,), cp, items, inbox)
    else:
        inbox[path].setdefault(port, []).extend(items)


# ---------------------------------------------------------------------------
# 실행기
# ---------------------------------------------------------------------------

def observe(model) -> dict:
    """만들어진 모델에서 구조를 다시 읽는다. 실행기의 충실성을 확인할 때 쓴다."""
    if isinstance(model, Coupled):
        return st.node(model.ports, {n: observe(c) for n, c in model.children.items()},
                       model.eic, model.eoc, model.ic)
    return st.node(getattr(model, "ports", None) or type(model).PORTS)


def module_of(cls, name: str = None):
    """원자 모델 클래스에서 모듈 선언을 만든다."""
    from .executor import Module
    if not (isinstance(cls, type) and issubclass(cls, Atomic)):
        raise TypeError(f"{getattr(cls, '__name__', cls)} 는 공통 모델 기반(ses_core.devs.Atomic 의 하위 클래스)이 아니다")
    return Module(name or cls.__name__, dict(cls.PORTS), tuple(cls.REQUIRED), dict(cls.PARAMS), cls)


class DevsExecutor(Executor):
    """계획을 DEVS 모델로 만든다. 원자 구성요소는 모델베이스의 클래스를, 결합 모델은 계획의 구조를 쓴다.

    시간 단위는 계획에 실려 온 것(바인딩이 적은 것)을 쓴다. time_unit을 주면 그것과 같아야 한다.
    만든 모델에 적어 두고 simulate가 읽는다.
    """

    name = "devs"

    def __init__(self, time_unit: Optional[float] = None) -> None:
        self.time_unit = time_unit

    def build(self, plan: dict, library: Mapping):
        unit = time_unit(plan, self.time_unit)

        def rec(n: dict, path: tuple):
            if st.is_atom(n):
                model = library[n["module"]].body("/".join(path) or n.get("name", ""), **n["params"])
                model.ports = dict(n["ports"])
                return model
            return Coupled(n.get("name", ""), n["ports"],
                           {name: rec(c, path + (name,)) for name, c in n["children"].items()},
                           n["eic"], n["eoc"], n["ic"])

        model = rec(plan, ())
        model._time_unit = unit
        return model

    def observe(self, artifact) -> dict:
        return observe(artifact)
