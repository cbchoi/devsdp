# SES 공통 플랫폼 설계 문서

System Entity Structure(SES, 시스템 엔티티 구조)를 연구와 개발에서 공통으로 쓰기 위한 플랫폼 설계 자료다.

| 문서 | 내용 |
|---|---|
| 01_research_review.md | SES 최신 연구 검토(2016 ~ 2026), 기존 도구 소스 분석, 플랫폼 시사점 |
| 02_platform_concept.md | 목표, 요구사항, 계층 아키텍처, 데이터 흐름, 아티팩트 분리, 백엔드 전략, LLM 연계, 로드맵 |
| 03_oo_design_and_representation.md | 객체지향과 설계 패턴 연계 개선 방안, 메타모델, 작성 패턴 카탈로그, 정준 표현(YAML, DSL, Python API, PES, FPES) |
| 04_data_structures.md | 시뮬레이터 독립적 자료구조 제안: 식별자 체계, 7개 계층(타입, 결정, 기록, 인스턴스, 경계, 바인딩), 시뮬레이터별 대응표 |
| 05_research_directions.md | 학술적 확장 가능 요소 평가: 기여가 아닌 것, 연구 후보 8개, 우선순위, 확인 필요 사항 |
| 06_core_concept.md | 연구의 핵심 개념 제안: SES의 의미를 절차에서 제약으로, 정의 4개, 파생 개선점, 반증 가능한 주장, 예상 반론 |
| 07_pruning_algebra.md | 가지치기 대수: 가지치기 관계, 가지치기 SES, 가지치기 연산, 정리 6개와 명제 1개, 예제, 검증 상태 |
| 08_coupling_wellformedness.md | 결합을 가진 가지치기 대수와 족 수준 적격성: 변이 적격성, 특성식, 적격 핵, 정적 규율, 결합 틀의 절단 정리 |
| 09_review.md | 전체 검토: 재현된 결함, 이론과 검증의 빈 곳, 연구 주장의 빈 곳, 정합성, 우선순위 권고 |
| 10_theory_extensions.md | 새로운 이론으로 확장할 여지: 후보 9개의 핵심 추측, 선행 연구 위험, 비교와 권고 |
| 11_ses_core_and_extensions.md | SES 핵과 확장(SES + X)의 정의: 핵의 두 층, 확장 계약, 모든 확장이 물려받는 정리, 세 사례(DEVS, 속성, 문서 조립) |
| examples/processing_system.pruning.ses.yaml | 가지치기 SES 예시 (대상 SES와 같은 스키마) |
| references.md | 검토 문헌 링크 목록 (열람 상태 표기) |
| schema/ses.schema.json | 정준 YAML/JSON 표현의 JSON Schema 초안 |
| examples/processing_system.ses.yaml | 처리 시스템 예시 SES (타입 수준) |
| examples/processing_system.config.yaml | 가지치기 구성 예시 |
| examples/processing_system.binding.pyevsim.yaml | pyevsim 바인딩 예시 |

예시 SES는 스키마로 검증했다. 검증 방법:

```bash
python -c "import json, yaml, jsonschema; s=json.load(open('docs/ses-platform/schema/ses.schema.json')); d=yaml.safe_load(open('docs/ses-platform/examples/processing_system.ses.yaml')); jsonschema.Draft202012Validator(s).validate(d); print('valid')"
```

읽는 순서는 01, 02, 03, 04이다. 03의 6절이 구조 표현의, 04가 자료구조의 핵심이다.

04의 자료구조를 그대로 옮긴 Python 참조 정의가 저장소 루트의 ses_core 패키지(model.py, loader.py)에 있다. 예시 SES 를 적재하고 무결성 검사를 확인하는 테스트는 tests/test_loader.py 이며 다음으로 실행한다.

```bash
pip install pyyaml pytest
python -m pytest -q tests
```
