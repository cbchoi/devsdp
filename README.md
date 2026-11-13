# devsdp

SES(System Entity Structure) 공통 플랫폼 설계 자료와 구현을 위한 저장소다.

- docs/ses-platform/ : 연구 검토, 플랫폼 구상, 객체지향 연계 개선 방안과 구조 표현, 시뮬레이터 독립 자료구조 제안, 스키마 초안, 예시
- ses_core/ : 자료구조의 Python 참조 정의, 정준 YAML 적재기, 가지치기 대수와 족 수준 적격성 참조 구현(algebra.py, coupling.py, unfold.py)
- tests/ : 예시 SES 적재와 무결성 검사 테스트, 가지치기 대수와 족 수준 적격성 정리의 무작위 검증
