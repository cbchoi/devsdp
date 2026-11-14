# devsdp

SES(System Entity Structure) 공통 플랫폼 설계 자료와 구현을 위한 저장소다.

- docs/ses-platform/ : 연구 검토, 플랫폼 구상, 객체지향 연계 개선 방안과 구조 표현, 시뮬레이터 독립 자료구조 제안, 스키마 초안, 예시, 분야별 프로파일과 예시(domains/)
- ses_core/ : 자료구조의 Python 참조 정의, 정준 YAML 적재기, 핵(algebra.py 선택 대수, skeleton.py 구성 구조), 확장 계약(extension.py)과 확장 사례(coupling.py, ext_attr.py, ext_text.py), 도메인 프로파일과 범용 장치(profile.py), 정준 문서와의 연결(unfold.py), 편집기를 위한 자료구조(edit.py 편집 모델, decisions.py 결정 집합, diagnose.py 진단)
- tests/ : 예시 SES 적재와 무결성 검사 테스트, 가지치기 대수와 족 수준 적격성 정리, 확장 계약의 공통 정리의 무작위 검증, 편집 모델과 결정 집합과 진단의 무작위 검증(test_edit.py, test_decisions.py, test_diagnose.py)
