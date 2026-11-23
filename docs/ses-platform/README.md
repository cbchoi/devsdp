# SES 공통 플랫폼 설계 문서

System Entity Structure(SES, 시스템 엔티티 구조)를 연구와 개발에서 공통으로 쓰기 위한 플랫폼 설계 자료다.

| 문서 | 내용 |
|---|---|
| theory.md | 규범 문서. SES 문서의 뜻을 정의 표 위에서 정한다. 문서의 조건, 변이, 핵 적격, 구조, 결정의 정의와 정리 아홉(잘 정의됨, 병합체의 분해, 열거하지 않는 계산, 복잡도, 펼친 나무에 의한 표현, 일어난 일의 계산, 결합의 국소 검사, 복제본 수의 절단, 결정의 표현)과 그 증명. 문헌의 도구(SESToPy)와 다른 곳. 다른 문서와 어긋나면 이 문서가 옳다. 9절이 검증 상태(시험, 작은 문서의 전수 검사, 변이 검사, 독립된 검토)를 적는다 |
| ROADMAP.md | 목표(이론을 정립하고 그 이론을 도구로 만든다), 끝났다고 말할 조건, 이정표와 상태, 정해야 할 것 |
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
| 15_pyevsim_executor.md | pyevsim 실행기: 계약과 쓰는 법, pyevsim 1.1.7에서 확인한 엔진의 성질, 공통 모델 기반을 올리는 어댑터와 그 정확성, 참조 시뮬레이터와의 사건 기록 대조, 한계와 결정이 필요한 것 |
| 16_cevsim_executor.md | cevsim 실행기: 계약과 쓰는 법, cevsim의 main(45e7fa9)에서 확인한 엔진의 성질과 앞선 커밋(a9886a6)과의 차이, C++ 엔진과 Python 사이의 다리, 공통 모델 기반을 올리는 방법, 참조 시뮬레이터와의 사건 기록 대조, 한계와 결정이 필요한 것 |
| 17_time_unit.md | 시간 단위: 바인딩에 적는 시간 단위와 눈금으로 세는 시각의 계약, 눈금을 엔진의 시각에 맞추는 방법, 시간 값의 정적 검사(B5), 세 실행기의 기록 대조, 한계와 결정이 필요한 것 |
| 18_classic_parity.md | 전통적인 SES와의 간격 메우기: 선택에 대한 제약(selected), 이름으로 등록한 함수(call), 우선순위, 사례마다 다른 매개변수(속성의 식, 복제본마다의 값, 결정 집합의 속성 재정의), 규모(결정이 끝난 변이를 직접 만드는 길), 도구와 사례(패키지, 명령줄 도구 ses, 문헌 사례 둘의 재현), 빠진 구성요소가 분해를 고르지 않게 한 수정, 작업 중에 찾은 결함, 검증 상태 |
| 19_literature_check.md | 문헌 확인: 07, 08, 11, 14, 10 문서와 theory.md의 주장마다 선행 연구와의 관계. 일곱 분야의 보고와 강한 주장 46건의 재확인. 제품 라인, 반환 파싱, 구성요소 모델 분야에 이미 있는 것과 SES에 고유한 것. 원문 접근의 한계(읽은 것은 19%)와 읽지 못한 문헌. 우리 문서의 잘못과 고칠 말. 문헌의 도구와의 차이 |
| 20_packs.md | 분야 묶음: 연구자가 자기 분야를 올리는 단위. 공통인 것과 연구자의 것의 경계, 모델의 계약(공통 모델 기반으로 정함), 묶음의 선언(pack.yaml), 적합성 검사의 부호 P0에서 P7, 명령 ses pack, 저장소의 묶음 둘, 한계 |
| GUIDE.md | 처음 오는 연구자를 위한 안내서. 설치, 첫 묶음, 문서에 묻기, 돌리기, 검사, 자기 분야로 바꾸기(대안 더하기, 일부러 틀려 보기, 원자 모델 더하기), 다른 엔진, 모델을 쓸 때 지킬 것. 적힌 명령과 출력은 tests/test_guide.py가 실제 도구와 견준다 |
| patches/cevsim_a9886a6_schedule_and_messages.patch | cevsim a9886a6의 두 결함(일정 목록과 메시지 묶음에서 열쇠로 지우기)을 고치는 제안. 그 커밋의 사본에서 확인했다. cevsim의 main(45e7fa9)은 같은 문제를 다른 방법으로 고쳤으므로 main에는 맞지 않는다. 기록으로 둔다 |
| patches/cevsim_45e7fa9_gxx_linux_issue.md | cevsim에 알릴 글(영어). cevsim의 main(45e7fa9)의 자체 시험이 g++ 13.3과 리눅스에서 컴파일되지 않거나 실패하는 곳, 원인 셋, 사본에서 확인한 고치는 길 셋, long double의 폭에 따라 결과가 달라지는 예. cevsim 저장소에는 올리지 않았다 |
| patches/cevsim_45e7fa9_gxx_linux_tests.patch | 위의 글에 딸린 수정 제안. 시험 코드만 고친다(파일 7개, 17줄). 45e7fa9의 사본에서 등록된 시험 24개가 모두 통과하는 것을 확인했다 |
| schema/profile.schema.json | 도메인 프로파일의 JSON Schema 초안 |
| schema/binding.schema.json | 바인딩과 모듈 라이브러리의 JSON Schema 초안 |
| schema/decisions.schema.json | 결정 집합의 JSON Schema 초안 |
| schema/edit.schema.json | 편집 모델의 스냅숏과 변경 이력(ses-edit/1)의 JSON Schema 초안 |
| domains/ | 세 분야의 프로파일과 예시 도메인 문서 |
| examples/processing_system.decisions.yaml | 결정 집합 예시 (변수 값과 선택 지점에 대한 결정) |
| examples/processing_system.decisions.tuned.yaml | 결정 집합 예시 (속성 값의 재정의. 서버마다 다른 서비스 시간) |
| examples/processing_system.pruning.ses.yaml | 가지치기 SES 예시 (대상 SES와 같은 스키마) |
| references.md | 검토 문헌 링크 목록 (열람 상태 표기) |
| schema/ses.schema.json | 정준 YAML/JSON 표현의 JSON Schema 초안 |
| examples/processing_system.ses.yaml | 처리 시스템 예시 SES (타입 수준) |
| examples/processing_system.config.yaml | 가지치기 구성 예시 (04 문서의 옛 형식. 어떤 코드도 읽지 않는다. 13 문서의 결정 집합이 대신한다) |
| examples/processing_system.binding.pyevsim.yaml | 처리 시스템에 pyevsim 실행기를 붙이는 바인딩. 모델베이스는 저장소 루트의 examples/processing_pyevsim.py(pyevsim 모델) 또는 examples/processing_mb.py(공통 모델 기반) |
| examples/processing_system.binding.cevsim.yaml | 처리 시스템에 cevsim 실행기를 붙이는 바인딩. 모델베이스는 저장소 루트의 examples/processing_mb.py(공통 모델 기반) |
| examples/processing_system.binding.devs.yaml | 처리 시스템에 DEVS 실행기를 붙이는 바인딩. 모델베이스는 저장소 루트의 examples/processing_mb.py |
| examples/sensor_node.ses.yaml | 센서 노드 예시 SES. 실행기 둘을 붙인다 |
| examples/sensor_node.binding.devs.yaml, sensor_node.binding.hw.yaml, sensor_node.hwlib.yaml | 센서 노드의 DEVS 바인딩, 하드웨어 바인딩, 하드웨어 모듈 라이브러리 |
| 저장소 루트의 packs/wsn | 분야 묶음. 문헌 사례: 큰 무선 센서 네트워크(Nam, Kim (2021)). 문서, 모델베이스, 바인딩, 사례 둘(센서 9개, 센서 1,000개). 20 문서 |
| 저장소 루트의 packs/feedback_control | 분야 묶음. 문헌 사례: 피드포워드를 켜고 끄는 피드백 제어(Folkerts et al. (2019)). 문서, 모델베이스, 바인딩, 사례 둘, 실험 제어(experiment.py) |

예시 SES는 스키마로 검증했다. 검증 방법:

```bash
python -c "import json, yaml, jsonschema; s=json.load(open('docs/ses-platform/schema/ses.schema.json')); d=yaml.safe_load(open('docs/ses-platform/examples/processing_system.ses.yaml')); jsonschema.Draft202012Validator(s).validate(d); print('valid')"
```

명령줄 도구 ses 로 문서를 검사하고, 변이를 고르고, 만들고, 돌릴 수 있다(18 문서의 6절).

```bash
pip install .
ses check docs/ses-platform/examples/processing_system.ses.yaml
ses run docs/ses-platform/examples/processing_system.ses.yaml --decisions docs/ses-platform/examples/processing_system.decisions.tuned.yaml --binding docs/ses-platform/examples/processing_system.binding.devs.yaml --library examples.processing_mb:LIBRARY --until 20
```

뜻을 알려면 theory.md를 먼저 읽는다. 번호가 붙은 문서는 작업의 기록이고, 그 가운데 설계를 읽는 순서는 01, 02, 03, 04이다. 03의 6절이 구조 표현의, 04가 자료구조의 핵심이다. 편집기를 만들 때는 13을 먼저 읽는다. 13은 04의 자료구조 가운데 편집에 쓰는 부분을 다시 정한 것이다. 실행기(시뮬레이터, 하드웨어)를 붙일 때는 14를 읽는다. 14는 04의 경계 계층과 바인딩 계층을 다시 정하고 정리로 뒷받침한 것이다. pyevsim으로 실행할 때는 15를, cevsim으로 실행할 때는 16을 읽는다. 모델의 시간을 어떻게 적고 실행기들이 어떻게 세는지는 17을 읽는다.

04의 자료구조를 그대로 옮긴 Python 참조 정의가 저장소 루트의 ses_core 패키지(model.py, loader.py)에 있다. 예시 SES 를 적재하고 무결성 검사를 확인하는 테스트는 tests/test_loader.py 이며 다음으로 실행한다.

```bash
pip install pyyaml pytest
python -m pytest -q tests
```
