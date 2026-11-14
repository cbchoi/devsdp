"""시뮬레이터 독립적 SES 코어의 Python 참조 구현.

모듈
- model, loader: 정준 문서의 자료구조와 적재기. 엄격하다.
- algebra, skeleton: 핵. 선택 대수와 구성 구조.
- extension, coupling, ext_attr, ext_text, profile: 확장 계약과 확장들.
- unfold: 정준 문서에서 분석 모델(펼친 나무)로.
- edit, decisions, diagnose: 편집기를 위한 자료구조. 편집 모델, 결정 집합, 진단.

이 패키지의 최상위에서는 정준 문서의 자료구조와 적재기만 내보낸다.
나머지는 모듈 이름으로 가져온다.
"""

from .model import *  # noqa: F401,F403
from .loader import load_ses, load_ses_dict, LoadError  # noqa: F401
