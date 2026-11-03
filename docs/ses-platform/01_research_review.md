# SES 최신 연구 검토와 공통 플랫폼 시사점

작성일: 2026-11-03

## 0. 검토 범위와 한계

- 대상: System Entity Structure(SES, 시스템 엔티티 구조) 및 SES/MB(SES와 Model Base, 모델베이스) 관련 연구. 2018년 이후를 중심으로 하되, 플랫폼 설계에 직접 영향을 주는 고전 문헌은 포함했다.
- 방법: 웹 검색 결과(초록, 색인 텍스트)와 GitHub 공개 소스(SESToPy, SESMoPy, SESTools) 직접 열람.
- 한계: 본 작업 환경의 네트워크 정책상 arXiv, MDPI, SNE, ACM, ResearchGate 등 원문 사이트에 접근할 수 없었다. 원문 전체를 확인하지 못한 항목은 [초록 수준]으로 표기했다. 해당 항목의 세부 주장(알고리즘, 평가 결과)은 플랫폼 설계에 인용하기 전에 원문으로 재확인이 필요하다.

## 1. 연구 흐름 요약

| 흐름 | 주체 | 대표 산출물 | 시기 | 플랫폼 관련도 |
|---|---|---|---|---|
| 이론 확장 | Zeigler (Arizona, RTSync) 외 | MetaSES, 시스템 명세 계층과의 통합, IoCT 개발 방법론, eUDEVS(2009 논문의 2024 재게시) | 2023 ~ 2025 | 높음 (타입/인스턴스 구분, 구조와 행위의 분리) |
| 공학적 확장과 도구 | Pawletta, Deatcu, Folkerts (Wismar), Durak (DLR) | eSES/MB 인프라, SESToPy 계열 Python 도구, SES 설계 패턴, 반응형 가지치기 | 2016 ~ 2023 | 매우 높음 (가장 구체적인 선행 구현) |
| MBSE 연계 | Xie, Zhang 외 (Beihang) | SES-X, X-SEM | 2023 ~ 2024 | 중간 (2단계 가지치기, MBSE 수명주기 연결) |
| 국내 응용 | ETRI, KNU, 국방 분야 | WSN-SES/MB, GO-DEVS, 전차 취약성 분석 | 2015 ~ 2021 | 중간 (대규모 모델 생성, 저장과 검색) |
| LLM 기반 DEVS 생성 | Castro (UBA), Sarjoughian (ASU) 외 | DEVS Copilot, PDEVS statechart 생성과 검증 | 2024 ~ 2026 | 높음 (SES를 쓰지 않음. 공백이자 기회) |
| 인접 기술 | 다수 | 선언적 DEVS 기술 언어(YAML), SysML v2 변이 모델링, FMI 기반 다중 시뮬레이터 생성 | 2021 ~ 2026 | 중간 (포맷과 상호운용) |

## 2. 흐름별 상세

### 2.1 이론 확장: Zeigler 계열

Zeigler (2023), "Extending the Hierarchy of System Specifications and Morphisms with SES Abstraction", Information 14(1):22. [초록 수준]
- 시스템 명세 계층(hierarchy of system specifications, 행위 수준에서 구조 수준까지)과 SES를 통합하려는 시도다.
- MetaSES를 제안한다. SES의 구성요소와 결합(coupling)을 메타 수준에서 추상화하여, 지정된 클래스에 속하는 다수의 구성요소로 이루어진 복합 시스템(systems of systems)을 구성하는 계산 프레임워크다.
- 시사점: SES를 "타입 수준" 명세로, 가지치기 결과(PES, Pruned Entity Structure)와 생성된 모델을 "인스턴스 수준"으로 명확히 구분해야 한다. 공통 플랫폼의 메타모델은 엔티티 정의(클래스)와 엔티티 사용(인스턴스)을 분리해야 한다.

Risco-Martín, Mittal, de la Cruz, Zeigler, "eUDEVS: Executable UML with DEVS Theory of Modeling and Simulation", arXiv 2407.08281 (2024년 arXiv 게시. 원 논문은 Simulation 85(11-12), 2009로 파악되며 최신 연구가 아니라 재게시다). [초록 수준]
- SES를 UML과 DEVS를 잇는 온톨로지로 사용한다. SES는 소수의 공리로 규정되는 형식 구조이며, 가지치기로 PES를 얻고 이를 합성 트리를 거쳐 시뮬레이션 모델로 합성한다.
- SES로 생성한 모델에는 행위 명세가 없다는 점을 명시한다. 행위는 별도로(예: 상태차트, DEVS Natural Language) 공급해야 한다.
- 시사점: SES는 구조만 다룬다. 플랫폼은 "구조(SES)"와 "행위(모델베이스 구현체)" 사이의 계약(포트, 타입, 생성자 인자)을 명시적으로 두어야 한다.

"Simulation-Based Development of Internet of Cyber-Things Using DEVS", Computers 14(7):258 (2025, 저자 미확인). [초록 수준]
- SES가 모델 변이(variants)를 조직하고 자동 구성(configuration)을 지원하는 역할로 제시된다. 동적 구조 DEVS(DS-DEVS)로 실행 중 재구성을 다룬다. 모델 연속성(model continuity)을 강조한다.
- 시사점: SES는 설계 시점 도구로 끝나지 않고 실행 시점의 구조 변경과 연결되어야 한다. 가지치기 결과가 실행 중 재구성의 입력이 될 수 있어야 한다.

EFSUT(Experimental Frame-System Under Test) 관련 논문 (2026, 저자 미확인). [초록 수준, 출처 불확실]
- 이해관계자의 질문마다 실험 프레임(experimental frame)을 유도하고, SES가 대안 구성을 생성하는 역할을 맡는다고 소개된다. 디지털 트윈 수명주기의 모델 선택을 다룬다.
- 시사점: 실험 프레임을 SES와 같은 형식으로 기술하고 시스템 SES와 합성하는 기능이 필요하다. 다만 이 항목은 출처 확인이 안 되어 참고 수준으로만 둔다.

### 2.2 공학적 확장과 도구: Wismar와 DLR

이 그룹이 지난 10년간 가장 구체적인 SES 확장과 도구를 냈다. 플랫폼 설계의 직접적인 비교 대상이다.

Pawletta et al. (2016), "Extended Variability Modeling Using System Entity Structure Ontology within MATLAB/Simulink", SpringSim.
- SES 변수(SESvar), SES 함수(SESfunction), aspect 규칙, specialization 규칙, 의미 조건(semantic condition), 선택 제약(selection constraint), 우선순위 속성 등 확장을 도입했다. 이후 모든 도구의 기반이 되었다.

Deatcu et al. (2018), "Design Patterns for Variability Modeling Using SES Ontology", Mod4Sim at SpringSim. Deatcu et al. (2019), "How to Define SES Trees for Variability Modeling", SNE 29(3). [초록 수준]
- SES 트리 설계와 가지치기 계산을 위한 설계 패턴 모음이다. 확인된 패턴 예: 필수 구성요소(mandatory sections) 패턴, multi-aspect를 쓰는 필수 구성요소 패턴, specialization 형제(siblings) 패턴.
- MATLAB 기반 SES 툴박스에서 도출했으며 다른 응용에도 적용하도록 의도했다.
- 시사점: 플랫폼은 "SES 작성 패턴 카탈로그"를 1급 기능으로 가져야 한다. 03 문서에서 이 패턴들을 객체지향 패턴과 연결하여 확장한다.

Folkerts et al. (2019), "Python-based eSES/MB Framework", SNE 29(4). Folkerts et al. (2019), "An Integrated Modeling, Simulation and Experimentation Environment in Python Based on SES/MB and DEVS", SummerSim. Folkerts et al. (2021), "Model Generation for Multiple Simulators Using SES/MB and FMI", SNE 31(1).
- eSES/MB 인프라: SES 모델링 도구(SESToPy), 모델 빌더(SESMoPy), 실행 유닛(SESEuPy), 실험 제어(SESEcPy)로 구성된다. 대상 시뮬레이터는 Simulink, OpenModelica, Dymola이며 FMI(Functional Mock-up Interface)로 모델을 생성한다. DEVS 백엔드로는 DEVSimPy와 연계했다.
- 가지치기 결과 PES를 평탄화(flattening)하여 FPES(Flattened PES)를 만들고, 이를 모델 빌더가 모델베이스와 결합한다.

Folkerts et al. (2020), "Automated, Reactive Pruning of System Entity Structures for Simulation Engineering", SpringSim. [초록 수준]
- 가지치기 방식의 분류: 대화형(interactive), 자동(automated), 열거형(enumerative, 모든 변이 도출), 선택형(selective, 하나의 변이 도출), 반응형(reactive, 실험 결과에 따라 재가지치기).
- 시사점: 가지치기는 단일 알고리즘이 아니라 교체 가능한 전략의 집합이어야 한다.

Folkerts, Pawletta, Durak (2023), "An Extension for the Specification and Automated Selection of System Variants Based on the SES Using a Problem from Process Industry", SNE 33(1). [초록 수준]
- 목표 지향(goal-directed)으로 정확히 하나의 변이를 자동 선택하는 확장을 공정 산업 문제에 적용했다. 이 그룹의 가장 최근 SES 논문이다.

DLR SESTools (Durak 외, GitHub aeronautical-informatics/SESTools).
- Java 기반 SESEditor와 PESEditor. XML 저장, 선택 제약은 XPath로 기술. README에 SES 공리 여섯 가지(uniformity, strict hierarchy, alternating mode, valid brothers, attached variables, inheritance)와 가지치기 4단계(변수 값 배정, aspect 선택, specialization 선택, multi-aspect 개수 지정)를 명시한다.

### 2.3 MBSE 연계: SES-X

Xie, Zhang, Li, Gu, Chen (2023), "SES-X: A MBSE Methodology Based on SES/MB and X Language", Information 14(1):23. [초록 수준]
- SES/MB와 X 언어(Beihang의 M&S 언어)를 결합하여 MBSE(Model-Based Systems Engineering, 모델 기반 시스템 공학) 전 수명주기를 지원한다. 시스템 분석, 아키텍처 분해, 물리 모델링, 시뮬레이션을 다룬다.
- 두 수준의 가지치기를 수행한다. 하나는 모델 검증용, 하나는 시뮬레이션 효율용이다. 자동차 사례를 제시했다. 후속으로 X-SEM(2024, Journal of Manufacturing Systems)이 있다.
- 시사점: 가지치기를 한 번에 끝내지 않고 "단계별 가지치기(staged pruning)"로 설계하면 검증과 실행을 분리할 수 있다. 플랫폼 파이프라인에 반영한다.

### 2.4 국내 응용

- WSN-SES/MB (Sensors 2021, 21(2):430): 대규모 무선 센서 네트워크를 위해 트리 구조, 파라미터, 원자 DEVS 모델을 결합하여 계층적 시뮬레이션 모델을 구성한다. 대규모 multi-aspect 복제 사례다.
- GO-DEVS (Lee, Bae, Paik, Sensors 2021, 21(20):6771, ETRI): 그래프와 온톨로지 표현으로 다수의 DEVS 모델을 저장하고 검색한다. IO 질의와 구조 질의를 지원한다. SES에 대한 비판이 명시되어 있다. SES는 같은 수준 구성요소 사이의 관계(결합 그래프 패턴)를 고려하지 않으며, 내부 구조를 추가하여 SES를 확장하고 이를 저장하고 질의하는 프레임워크를 개발할 수 있다고 제안한다.
- 전차 취약성 분석 (한국시뮬레이션학회 논문지 2015), 사이버 공격 시뮬레이션의 규칙 기반 SES 등 국방 응용이 있다. 2022년 이후 국내 SES 신규 논문은 이번 검색에서 확인되지 않았다.
- 미국 특허 11922102 및 12265763 "Method to integrate diverse components for simulation of complex system": SES 가지치기 GUI에서 DEVS 원자 모델과 결합 모델을 생성하는 환경을 청구한다. SES 트리를 분해, 전문화, multi-aspect 관계로 구성하는 하향식 설계를 기술한다.
- 고전: Cheon, Kim (2008), "DEVS model composition by system entity structure". SESBuilder가 제한된 자연어 입력에서 SES를 정의하고 PES를 XML로 생성한다. 결합 정보도 제한 구문 자연어로 처리한다.
- 시사점: 결합(coupling)을 트리의 부속물이 아니라 질의 가능한 그래프로 다루어야 한다(GO-DEVS 비판 수용). 제한 자연어 입력은 2008년에 이미 시도되었고, 현재는 LLM으로 같은 목표를 훨씬 낮은 비용으로 달성할 수 있다.

### 2.5 LLM 기반 DEVS 모델 생성 (SES 미사용)

- Carreira-Munich, Paz-Marcolla, Castro (2024), "DEVS Copilot", WSC 2024: 자연어 시스템 기술을 대화로 정제하여 DEVS 실행 모델로 변환한다. DEVS를 중간 형식 언어로 쓴다.
- Vasa, Sarjoughian 외 (2025, WSC 2025) 및 arXiv 2608.14956 (2026): PDEVS statechart 문법으로 원자 모델 행위를 생성하고 검증한다.
- arXiv 2503.06422 (2025), "GenAI for Simulation Model in MBSE": 결합(coupled) 클래스 모델을 먼저 하향식으로 만들고 원자 클래스 모델을 생성한다. 구조를 먼저, 행위를 나중에 생성하는 순서가 SES의 하향식 설계와 일치한다.
- arXiv 2603.03784 (2026), "Specification-Driven Generation and Evaluation of Discrete-Event World Models via the DEVS Formalism".
- 공통점: 모두 SES를 쓰지 않는다. 구조 생성의 제약과 검증이 약하며, 변이 공간(variants)을 다루지 않는다.
- 시사점: SES를 LLM 생성의 "스키마이자 검증기"로 쓰는 연구와 도구가 비어 있다. 공통 플랫폼의 차별점으로 삼을 수 있다. 구체적으로는 (1) LLM이 SES 정준 표현(JSON/YAML)을 생성하고, (2) 플랫폼이 공리 검증과 제약 검사를 수행하며, (3) 가지치기와 모델 빌더가 실행 모델을 만든다. 행위 생성은 기존 LLM 연구(statechart 문법)를 모델베이스 구현체 생성에 연결하면 된다.

### 2.6 인접 기술

- arXiv 2609.11122 (2026), "A Model-Centric DevOps Architecture for DEVS-Based Digital Twin Simulation Services": YAML 기반 선언적 DEVS 모델 기술 언어(SMDL)를 제안한다. 사람이 읽을 수 있고 버전 관리가 가능한 형식을 강조하며 FMI 공동 시뮬레이션을 지원한다.
- SysML v2: 변이점(variation point)과 변이(variant)로 변이성을 표준 언어 수준에서 지원한다. SES와 SysML v2 변이 모델링을 직접 대응시킨 연구는 확인되지 않았다.
- 소프트웨어 제품 라인(SPL)의 feature model: SES와 같은 트리 기반 변이 모델이다. SES의 aspect, specialization, multi-aspect와 feature model의 mandatory, optional, alternative, cardinality를 대응시킨 공식 비교 문헌은 확인되지 않았다.
- 시사점: 플랫폼의 정준 표현은 텍스트 기반이고 diff가 가능해야 한다. SysML v2 변이 모델과 feature model로의 변환기를 두면 외부 생태계와 연결된다.

## 3. 기존 도구의 구조 분석 (SESToPy 소스 기준)

공개 소스를 직접 읽고 확인한 사실이다. 공통 플랫폼이 반복하지 말아야 할 점을 중심으로 정리했다.

| 항목 | SESToPy의 구현 | 평가 |
|---|---|---|
| 노드 클래스 | Node를 상속한 EntityNode, AspectNode, MaspectNode, SpecNode, DescriptiveNode. 트리 조작 메서드가 Node에 있고 Qt 표시 속성(색, 굵기)이 같은 클래스에 섞여 있다. | 도메인 모델과 GUI 모델이 분리되지 않았다. |
| 규칙 표현 | aspect 규칙, specialization 규칙, 속성 식, 의미 조건, 우선순위, 복제 개수, 결합 조건이 모두 Python 식 문자열이며 실행 시 평가(eval)한다. PATH 같은 특수 변수를 정규식으로 찾아 치환한다. | 안전성, 정적 검증, 다른 언어 백엔드로의 이식이 불가능하다. |
| 저장 형식 | "SES JSON Version 1"이라는 헤더 뒤에 줄 단위로 JSON 배열을 이어 붙인 형식. 노드는 위치 인덱스로 의미가 정해지는 리스트(예: nd[12]가 깊이, nd[6]이 속성, nd[8]이 결합). 파일 머리말에 "수동 편집 금지"를 명시. | 사람이 읽거나 diff할 수 없고 스키마가 없다. |
| 모델베이스 연결 | 리프 엔티티의 속성 중 이름이 "mb"인 것의 값(문자열)으로 모델베이스 요소를 가리킨다. | 바인딩이 SES 본문에 섞여 있어 백엔드 교체 시 SES를 수정해야 한다. |
| 가지치기 | Prune 클래스 하나에 1,300줄. 경로 목록(paths)을 만들고 노드 종류별로 분기한다. 선택 제약은 가지치기에서 무시된다고 README에 기록. | 전략 교체와 단위 테스트가 어렵다. |
| 되돌리기 | 미구현 (README). | 대화형 가지치기의 필수 기능이 빠져 있다. |
| uniformity 처리 | 같은 이름의 노드가 서로 다른 uid를 갖도록 복제한다. | 참조 의미론이 아니라 복사 의미론이라 일관성 유지 비용이 크다. |

SESTools(DLR)는 Java와 XML을 쓰고 XPath로 선택 제약을 표현한다. 공리 목록과 가지치기 단계를 명문화한 점은 참고할 만하지만, 의존 jar를 수동으로 넣어야 하고 문서가 부족하다.

## 4. 공통 플랫폼 구상에 주는 시사점

| 번호 | 시사점 | 근거 | 플랫폼 반영 |
|---|---|---|---|
| 1 | 열린 정준 표현 형식이 없다 | SESToPy 줄 단위 JSON, SESTools XML, MS4 Me 전용 형식, SES-X 전용 | JSON Schema로 검증되는 YAML/JSON 정준 표현을 정의하고 공개한다 |
| 2 | 규칙을 코드 문자열로 두면 안 된다 | SESToPy의 eval 기반 규칙 | 작은 선언적 표현식 AST를 정의하고, 복잡한 논리는 이름으로 등록한 함수(플러그인)로 뺀다 |
| 3 | 구조와 행위의 계약이 필요하다 | eUDEVS, SESToPy의 mb 속성 | 엔티티에 포트와 타입을 명시하고, 바인딩 파일을 SES와 분리한다 |
| 4 | 가지치기는 전략의 집합이다 | Folkerts 2020의 5가지 방식, SES-X의 2단계 가지치기 | 가지치기 파이프라인과 교체 가능한 전략, 결정 기록(trace) |
| 5 | 결합은 1급 그래프여야 한다 | GO-DEVS의 SES 비판 | aspect에 결합 그래프를 두고 패턴(fan-out, chain, ring)으로 생성하며 질의를 지원한다 |
| 6 | 타입과 인스턴스를 구분해야 한다 | MetaSES | 엔티티 정의 테이블(타입)과 PES(인스턴스)를 분리한다 |
| 7 | 실행 시점과 연결되어야 한다 | IoCT 2025, 반응형 가지치기 | 재가지치기를 이벤트로 트리거하는 인터페이스를 둔다 |
| 8 | LLM 생성의 제약과 검증기로서 SES | 2.5절의 공백 | 정준 표현을 LLM 구조화 출력 스키마로 쓰고 공리 검증기를 제공한다 |
| 9 | 다중 백엔드 생성 | Folkerts FMI, SES-X, 사용자 환경(pyevsim, evsimpp) | 백엔드별 모델 빌더(추상 팩토리)와 공통 FPES 중간 표현 |
| 10 | 작성 패턴이 필요하다 | Deatcu 2018, 2019 | 패턴 카탈로그와 린트(lint) 규칙 |

## 5. 솔직한 평가

- SES 연구는 소수 그룹이 주도하며 2023년 이후 새 논문이 드물다. 도구는 연구용 프로토타입이고 GUI 중심이며 유지보수가 멈춰 있다(SESToPy 마지막 변경 이력 기준). 기존 도구를 가져다 쓰는 선택은 권하지 않는다. 다만 개념(확장 요소, 가지치기 방식, 패턴)은 그대로 흡수해야 한다.
- 현재 모멘텀은 LLM 기반 DEVS 생성에 있고 SES는 그 흐름에서 빠져 있다. 공통 플랫폼이 연구 가치를 가지려면 "SES를 LLM 생성의 스키마와 검증기로 쓴다"는 위치를 선점해야 한다. 플랫폼 자체(편집기, 포맷)는 공학적 기여이지 연구 기여는 아니다.
- 편집기 GUI를 먼저 만드는 순서는 피해야 한다. 선행 도구들이 모두 GUI에 묶여 코어 재사용에 실패했다. 코어 라이브러리, 정준 표현, CLI, 백엔드 빌더 순으로 가고 시각화는 읽기 전용 뷰어로 시작한다.

## 참고 문헌

- Zeigler, B. P. (2023). Extending the Hierarchy of System Specifications and Morphisms with SES Abstraction. Information, 14(1), 22.
- Risco-Martín, J. L., Mittal, S., de la Cruz, J. M., Zeigler, B. P. (2009). eUDEVS: Executable UML with DEVS Theory of Modeling and Simulation. Simulation, 85(11-12). arXiv:2407.08281 (2024 재게시).
- (저자 미확인) (2025). Simulation-Based Development of Internet of Cyber-Things Using DEVS. Computers, 14(7), 258.
- Pawletta, T. et al. (2016). Extended Variability Modeling Using System Entity Structure Ontology within MATLAB/Simulink. SpringSim.
- Schmidt, A., Durak, U., Pawletta, T. (2016). Model-based testing methodology using system entity structures for MATLAB/Simulink models. Simulation, 92(8).
- Deatcu, C., Folkerts, H., Pawletta, T., Durak, U. (2018). Design Patterns for Variability Modeling Using SES Ontology. Mod4Sim, SpringSim.
- Deatcu, C. et al. (2019). How to Define SES Trees for Variability Modeling. SNE, 29(3).
- Folkerts, H., Deatcu, C., Pawletta, T., Hartmann, S. (2019). Python-based eSES/MB Framework. SNE, 29(4), 207-215.
- Folkerts, H., Pawletta, T., Deatcu, C., Zeigler, B. (2020). Automated, Reactive Pruning of System Entity Structures for Simulation Engineering. SpringSim.
- Folkerts, H., Pawletta, T., Deatcu, C. (2021). Model Generation for Multiple Simulators Using SES/MB and FMI. SNE, 31(1), 25-32.
- Folkerts, H., Pawletta, T., Durak, U. (2023). An Extension for the Specification and Automated Selection of System Variants Based on the SES Using a Problem from Process Industry. SNE, 33(1).
- Xie, K., Zhang, L., Li, X., Gu, P., Chen, Z. (2023). SES-X: A MBSE Methodology Based on SES/MB and X Language. Information, 14(1), 23.
- Lee, C.-H., Bae, J. W., Paik, E. (2021). GO-DEVS: Storage and Retrieval System for DEVS Models Using Graph and Ontology Representation. Sensors, 21(20), 6771.
- WSN-SES/MB (2021). System Entity Structure and Model Base Framework for Large-Scale Wireless Sensor Networks. Sensors, 21(2), 430.
- Cheon, S., Kim, T. G. (2008). DEVS model composition by system entity structure. IEEE.
- Carreira-Munich, Paz-Marcolla, Castro (2024). DEVS Copilot. Winter Simulation Conference 2024, 2785-2796.
- arXiv:2608.14956 (2026). LLM-based Framework for Generating and Verifying Parallel DEVS Statecharts.
- arXiv:2503.06422 (2025). GenAI for Simulation Model in Model-Based Systems Engineering.
- arXiv:2609.11122 (2026). A Model-Centric DevOps Architecture for DEVS-Based Digital Twin Simulation Services.
- Zeigler, B. P., Sarjoughian, H. S. (2013). Guide to Modeling and Simulation of Systems of Systems. Springer. (SES 기초와 가지치기 장)
- GitHub: hendrikfolkerts/sestopy, sesmopy, seseupy, sesecpy. aeronautical-informatics/SESTools.
