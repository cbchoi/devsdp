"""시뮬레이터 독립적 SES 코어의 Python 참조 구현.

모듈
- model, loader: 정준 문서의 자료구조와 적재기. 엄격하다.
- algebra, skeleton: 핵. 선택 대수와 구성 구조.
- extension, coupling, ext_attr, ext_text, profile: 확장 계약과 확장들.
- unfold: 정준 문서에서 분석 모델(펼친 나무)로.
- edit, decisions, diagnose: 편집기를 위한 자료구조. 편집 모델, 결정 집합, 진단.
- structure, executor, devs, hw, classic: 실행기를 붙이는 자리. 구조와 평탄화, 바인딩과 계획,
  DEVS 참조 실행기, 하드웨어 실행기, 고전 SES/MB의 절차적 의미.
- pyevsim_executor: pyevsim 실행기. pyevsim이 설치되어 있어야 가져올 수 있다.
- cevsim_executor, cevsim_bridge: cevsim 실행기와 C++ 다리. 조립하려면 cevsim의 소스와 C++ 컴파일러가 있어야 한다.

이 패키지의 최상위에서는 정준 문서의 자료구조와 적재기만 내보낸다.
나머지는 모듈 이름으로 가져온다.
"""

from .model import *  # noqa: F401,F403
from .loader import load_ses, load_ses_dict, LoadError  # noqa: F401
