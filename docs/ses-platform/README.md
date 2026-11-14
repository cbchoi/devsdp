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
| 12_generic_and_specific.md | 범용성과 특수성을 나눈 형식: 네 층(핵, 범용 장치, 도메인 프로파일, 도메인 문서), 세 분야(커리큘럼, RFP, 논문의 논리 구성) 적용 결과 |
| 13_editor_data_model.md | 편집기를 고려한 자료구조: 세 모형, 편집 모델(요소, 참조, 원시 연산과 역연산), 정준 문서와의 왕복, 주소와 곁자료, 진단, 결정 집합과 선택 지점 표, 프로파일의 표시 정보, 검증 상태, 한계와 결정이 필요한 것 |
| 14_executors.md | 실행기를 붙이는 SES: 구조와 평탄화, 끝에서 끝까지의 구동, 모듈과 바인딩과 계획, 실현의 유일성, 실행 가능 핵, 실행기 사이의 대응, 표현 완전성과 한계, 고전 SES/MB의 포섭, DEVS와 하드웨어 두 실행기의 사례 |
| schema/profile.schema.json | 도메인 프로파일의 JSON Schema 초안 |
| schema/binding.schema.json | 바인딩과 모듈 라이브러리의 JSON Schema 초안 |
| schema/decisions.schema.json | 결정 집합의 JSON Schema 초안 |
| schema/edit.schema.json | 편집 모델의 스냅숏과 변경 이력(ses-edit/1)의 JSON Schema 초안 |
| domains/ | 세 분야의 프로파일과 예시 도메인 문서 |
| examples/processing_system.decisions.yaml | 결정 집합 예시 (변수 값과 선택 지점에 대한 결정) |
| examples/processing_system.pruning.ses.yaml | 가지치기 SES 예시 (대상 SES와 같은 스키마) |
| references.md | 검토 문헌 링크 목록 (열람 상태 표기) |
| schema/ses.schema.json | 정준 YAML/JSON 표현의 JSON Schema 초안 |
| examples/processing_system.ses.yaml | 처리 시스템 예시 SES (타입 수준) |
| examples/processing_system.config.yaml | 가지치기 구성 예시 (04 문서의 옛 형식. 어떤 코드도 읽지 않는다. 13 문서의 결정 집합이 대신한다) |
| examples/processing_system.binding.pyevsim.yaml | pyevsim 바인딩 예시 (04 문서의 옛 초안 형식. 어떤 코드도 읽지 않는다) |
| examples/processing_system.binding.devs.yaml | 처리 시스템에 DEVS 실행기를 붙이는 바인딩. 모델베이스는 저장소 루트의 examples/processing_mb.py |
| examples/sensor_node.ses.yaml | 센서 노드 예시 SES. 실행기 둘을 붙인다 |
| examples/sensor_node.binding.devs.yaml, sensor_node.binding.hw.yaml, sensor_node.hwlib.yaml | 센서 노드의 DEVS 바인딩, 하드웨어 바인딩, 하드웨어 모듈 라이브러리 |

예시 SES는 스키마로 검증했다. 검증 방법:

```bash
python -c "import json, yaml, jsonschema; s=json.load(open('docs/ses-platform/schema/ses.schema.json')); d=yaml.safe_load(open('docs/ses-platform/examples/processing_system.ses.yaml')); jsonschema.Draft202012Validator(s).validate(d); print('valid')"
```

읽는 순서는 01, 02, 03, 04이다. 03의 6절이 구조 표현의, 04가 자료구조의 핵심이다. 편집기를 만들 때는 13을 먼저 읽는다. 13은 04의 자료구조 가운데 편집에 쓰는 부분을 다시 정한 것이다. 실행기(시뮬레이터, 하드웨어)를 붙일 때는 14를 읽는다. 14는 04의 경계 계층과 바인딩 계층을 다시 정하고 정리로 뒷받침한 것이다.

04의 자료구조를 그대로 옮긴 Python 참조 정의가 저장소 루트의 ses_core 패키지(model.py, loader.py)에 있다. 예시 SES 를 적재하고 무결성 검사를 확인하는 테스트는 tests/test_loader.py 이며 다음으로 실행한다.

```bash
pip install pyyaml pytest
python -m pytest -q tests
```
