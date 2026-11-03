"""시뮬레이터 독립적 SES 코어 자료구조의 Python 참조 정의.

이 패키지는 자료구조(model)와 정준 YAML 적재기(loader)만 담는다.
가지치기, 평탄화, 모델 생성 논리는 포함하지 않는다.
"""

from .model import *  # noqa: F401,F403
from .loader import load_ses, load_ses_dict, LoadError  # noqa: F401
