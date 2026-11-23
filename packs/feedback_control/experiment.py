"""피드백 제어 사례의 실험 제어 (Folkerts et al. (2019)의 2.4절을 옮긴 것).

문헌의 실험 제어는 SES 변수 feedforward 를 정해 가지치기하고, 평탄화하고, 모델을 만들고, 시뮬레이션한다.
먼저 피드포워드가 없는 구조에서 PID 제어기의 설정 여럿을 살피고, 목표에 닿지 못하면 피드포워드가 있는
구조로 다시 살핀다. 목표는 외란이 들어온 뒤 정착 시간 15초 미만, 최대 벗어남 5% 미만이다.

여기서는 같은 일을 이 플랫폼의 길로 한다.
- 가지치기와 평탄화: 결정 집합(변수 feedforward)으로 변이 하나를 직접 만든다(ses_core/direct.py).
- PID 제어기의 설정: 결정 집합의 속성 재정의(set)로 k 와 Ti 를 바꾼다.
- 모델 만들기와 실행: 실행기를 붙여 계획을 만들고 참조 시뮬레이터로 돌린다.

문헌의 매개변수 범위 k=[1,5], Ti=[1,0.5] 는 값의 목록으로 읽었고 그 곱(설정 넷)을 살핀다. 내 판단이다.
"벗어남"은 외란의 높이에 대한 제어량의 가장 큰 벗어남으로, "정착 시간"은 벗어남이 5% 안으로 들어와
머물기까지의 시간으로 읽었다. 이것도 내 판단이다.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))           # 저장소 안에서 설치 없이 돌릴 때

from ses_core import direct, load_ses  # noqa: E402
from ses_core import pack as P  # noqa: E402
from ses_core import executor as X  # noqa: E402
from ses_core.decisions import DecisionSet, Override  # noqa: E402
from ses_core.devs import DevsExecutor, simulate  # noqa: E402

PACK = P.load(HERE)
mb = P.module(PACK)                          # 이 묶음의 모델 베이스
K, TI = (1.0, 5.0), (1.0, 0.5)               # 문헌의 PARAMVARY1, PARAMVARY2
SETTLE, OVERSHOOT = 15.0, 0.05               # 문헌의 목표
UNTIL = 60.0


def configuration(feedforward: int, k: float, ti: float) -> DecisionSet:
    return DecisionSet(variables={"feedforward": (feedforward,)},
                       set=(Override("k", k, at="ctrlPIDSys"), Override("Ti", ti, at="ctrlPIDSys")))


def run(feedforward: int, k: float, ti: float, doc=None, binding=None) -> dict:
    """설정 하나를 만들고 돌린다. 제어량의 응답과 목표에 닿았는지를 돌려준다."""
    doc = doc or load_ses(PACK.path(PACK.document))
    binding = binding or X.load_binding(PACK.path(PACK.binding))
    built = direct.build(doc, configuration(feedforward, k, ti))
    L, ext = X.attach(built.layered, DevsExecutor(), binding, mb.LIBRARY)
    if not X.executable(L, ext, built.variant):
        raise RuntimeError(f"만들 수 없는 설정이다: feedforward={feedforward}, k={k}, Ti={ti}")
    start = X.plan(L, ext, built.variant)["children"]["sourceDist"]["params"]["start"]
    log = simulate(X.realize(L, ext, DevsExecutor(), built.variant), UNTIL, max_steps=10 ** 6)
    ys = mb.response(log, ("addDist",))
    peak, settle = mb.quality(ys, start, OVERSHOOT)
    return {"feedforward": feedforward, "k": k, "Ti": ti, "peak": peak, "settle": settle,
            "met": peak < OVERSHOOT and settle < SETTLE, "response": ys}


def study() -> tuple:
    """문헌의 실험 과정. (살핀 설정들의 결과, 목표에 닿은 설정들)을 돌려준다."""
    doc = load_ses(PACK.path(PACK.document))
    binding = X.load_binding(PACK.path(PACK.binding))
    tried = []
    for feedforward in (0, 1):               # 피드포워드가 없는 구조부터
        results = [run(feedforward, k, ti, doc, binding) for k in K for ti in TI]
        tried += results
        good = [r for r in results if r["met"]]
        if good:
            return tried, good
    return tried, []


def main() -> None:
    tried, good = study()
    print("feedforward    k     Ti   최대 벗어남   정착 시간   목표")
    for r in tried:
        print(f"{r['feedforward']:>11} {r['k']:>4} {r['Ti']:>6} {r['peak']:>12.4f} {r['settle']:>10.3f}   "
              f"{'닿음' if r['met'] else '못 닿음'}")
    print("결과:", [(r["feedforward"], r["k"], r["Ti"]) for r in good] or "목표에 닿은 설정이 없다")


if __name__ == "__main__":
    main()
