# SES 최신 연구 검토와 공통 플랫폼 시사점

작성일: 2026-11-03. 원문 확인 갱신: 2026-11-04

## 0. 검토 범위와 방법

- 대상: System Entity Structure(SES, 시스템 엔티티 구조) 및 SES/MB(SES와 Model Base, 모델베이스) 관련 연구. 2018년 이후를 중심으로 하되, 플랫폼 설계에 직접 영향을 주는 고전 문헌은 포함했다.
- 방법: 1차 검토(11월 3일)는 웹 검색 요약과 GitHub 공개 소스(SESToPy, SESMoPy, SESTools) 열람으로 수행했다. 2차 검토(11월 4일)는 저장소 reference 디렉터리에 넣어 둔 논문 13편의 원문 전체를 읽고 1차 검토의 초록 수준 기술을 교정했다.
- 원문을 읽은 13편: Zeigler (2023), Capocchi, Zeigler, Santucci (2025), Xie et al. (2023), Lee, Bae, Paik (2021), Folkerts, Pawletta, Durak (2023), Deatcu et al. (2019), Folkerts et al. (2019), Folkerts et al. (2021), Carreira-Munich et al. (2024), Vasa et al. (2026), Zhang et al. (2025), Chen et al. (2026), Lektauers et al. (2026).
- 여전히 원문을 읽지 못한 것: Deatcu et al. (2018) 설계 패턴 원 논문(2019 SNE 판으로 대체), Folkerts et al. (2020) 반응형 가지치기, eUDEVS, WSN-SES/MB, EFSUT, Schmidt et al. (2016). 이 항목은 [미열람]으로 표기했다.

## 1. 연구 흐름 요약

| 흐름 | 주체 | 대표 산출물 | 시기 | 플랫폼 관련도 |
|---|---|---|---|---|
| 이론 확장 | Zeigler (Arizona, RTSync), Capocchi, Santucci (Corsica) | MetaSES, IoCT 개발 방법론 | 2023 ~ 2025 | 높음 (클래스와 인스턴스 구분, 설계 시점 변이 정리) |
| 공학적 확장과 도구 | Pawletta, Deatcu, Folkerts (Wismar), Durak (DLR) | eSES/MB 인프라, SESToPy 계열 Python 도구, SES 작성 패턴 14개, 반응형 가지치기, 복제 인덱스 확장 | 2016 ~ 2023 | 매우 높음 (가장 구체적인 선행 구현) |
| MBSE 연계 | Xie, Zhang 외 (Beihang) | SES-X, X-SEM | 2023 ~ 2024 | 중간 (2단계 가지치기, 수동) |
| 국내 응용 | ETRI, KNU, 국방 분야 | GO-DEVS, WSN-SES/MB, 전차 취약성 분석 | 2015 ~ 2021 | 중간 (결합 그래프 저장과 질의, SES 확장 요청) |
| LLM 기반 DEVS 생성 | Castro (UBA), Sarjoughian (ASU), Zhang (Beihang), Li (Tsinghua) | DEVS Copilot, PDEVS statechart 검증, X 언어 생성, DEVS-Gen | 2024 ~ 2026 | 높음 (SES를 쓰지 않음. 공백이자 기회) |
| 인접 기술 | Lektauers (Riga) 외 | SMDL(YAML) 기반 DEVS DevOps, SysML v2 변이 모델링 | 2021 ~ 2026 | 중간 (출력 형식과 수명주기 참고) |

## 2. 흐름별 상세

### 2.1 이론 확장: Zeigler 계열

Zeigler (2023), "Extending the Hierarchy of System Specifications and Morphisms with SES Abstraction", Information 14(1):22. 단독 저자. [원문 확인]
- MetaSES의 정의: "SES의 구성요소와 결합을 메타 수준에서 추상화한 것. DEVS 모델의 클래스를 구성요소로 인식하고, 클래스 사이의 포트 대 포트 결합을 고수준으로 기술한다"(4쪽). 형식 정의는 부록 A.1(18쪽)에만 있다. MetaSES G = (Nodes, Edges), Nodes는 클래스 집합, 간선은 (A, (op, ip), B) 형태로 클래스 A의 출력 포트 op에서 클래스 B의 입력 포트 ip로의 결합이다. 여기서 자유 유향그래프 FG(각 클래스의 인스턴스 사이 전체 결합)를 생성하고, FG에서 결합 DEVS N(FG)를 유도한다.
- 3단계 절차(6쪽): 클래스와 메시지 타입 정의, 자유 유향그래프(제약 없는 SES가 생성하는 전체 결합) 생성, 제약(인덱싱, 결합 제한) 부과로 "변환 가능한 SES"를 얻어 MS4 Me가 DEVS 결합 모델로 변환. 클래스는 SES의 multi-aspect로 대응된다(16쪽).
- 시스템 명세 계층은 0에서 6까지 7단계로 제시되며(3쪽 표 1), SES와 MetaSES는 6단계(Network of Systems)에 놓인다. 사상(morphism)은 고전적 수준별 시스템 사상만 다룬다. SES와 SES 사이의 사상(정제, 준동형, 추상화 대응)은 정의되지 않는다. 가장 가까운 서술은 "MetaSES가 생성한 유향그래프와 제약 없는 SES가 생성한 유향그래프 사이의 그래프 사상"(5쪽)이며, 이는 생성 결과 그래프 사이의 관계이지 SES 사이의 관계가 아니다.
- 클래스와 인스턴스의 구분은 비형식적으로 존재한다. MetaSES 노드는 클래스, 변환 가능한 SES는 인덱스가 붙은 인스턴스(AN_q, EPU_{x,i})를 담는다(5쪽, 13쪽). 부록은 클래스별 해시 집합으로 인스턴스 id를 생성한다.
- 가지치기는 형식화되지 않는다(단어 자체가 없고 제약 부과가 그 역할을 한다). 실험 프레임은 모델 저장소의 적용 가능성 관계로 한 번 언급된다(16쪽). 디지털 트윈 언급은 없다. 도구는 MS4 Me.
- 열린 문제(15 ~ 17쪽): 다해상도 모델링과 MetaSES의 결합, 저장소의 기저와 집약(base and lumped) 쌍을 위한 자료구조, MetaSES에서 multi-aspect로의 대응을 설계 공간 탐색에 활용, 메타모델링 기반 코드 생성.
- 시사점: 플랫폼의 정의 테이블(클래스)과 PES(인덱스 인스턴스) 분리는 MetaSES와 일치한다. SES 사이 사상은 미정의 영역이다.

Capocchi, Zeigler, Santucci (2025), "Simulation-Based Development of Internet of Cyber-Things Using DEVS", Computers 14(7):258. [원문 확인]
- 설계, 시뮬레이션, 구현의 3단계 방법론. 모델 연속성은 추상 실행 커널을 실시간 커널(RT-DEVS)로 교체하고 엔진을 이식하는 방식으로 달성한다(5 ~ 6쪽, 18쪽 표 3).
- SES의 역할은 "모델 변이를 조직하고 자동 구성을 지원"(3쪽)하는 설계 시점 역할이다. 군집(swarm) 사례에서 중앙집중과 분산 분해를 대안 aspect로 보인다(13 ~ 14쪽). 저자 자신의 SES 도구는 명시되지 않으며 시뮬레이터는 DEVSimPy다.
- 동적 구조: DS-DEVS는 SES와 독립적으로 쓰인다. 실행 중 변경은 "사전 정의된 구조 변경 규칙과 시스템 목표에 따라" 모델 내부에서 일어난다(12쪽). PES나 SES를 실행 중에 참조하여 재구성을 유도하는 부분은 없다.
- LLM, 디지털 트윈 언급 없음. 실험 프레임은 그림의 라벨로만 등장한다.
- 시사점: SES 주도의 실행 중 재구성은 아직 아무도 하지 않았다.

Risco-Martín, Mittal, de la Cruz, Zeigler, eUDEVS (2009 논문, arXiv 2407.08281로 2024 재게시). [미열람, 초록 수준]
- SES를 UML과 DEVS를 잇는 온톨로지로 쓰며, SES로 생성한 모델에 행위 명세가 없다는 점을 명시한다.

EFSUT(Experimental Frame-System Under Test) 관련 논문 (2026, 저자 미확인). [미열람, 출처 불확실]
- 질문마다 실험 프레임을 유도하고 SES가 대안 구성을 생성한다고 소개된다. 참고 수준으로만 둔다.

### 2.2 공학적 확장과 도구: Wismar와 DLR

Deatcu, Folkerts, Pawletta, Durak (2019), "How to Define SES Trees for Variability Modeling", SNE 29(3):117-126. [원문 확인]
- 공리 여섯 가지(118 ~ 119쪽): alternating mode, strict hierarchy, uniformity, valid brothers, attached variables, inheritance.
- 확장 요소 정의(119 ~ 120쪽): SESvar(SES 인터페이스를 이루는 전역 변수), 의미 조건(SESvar 값 범위 제한, 가지치기 전에 검사), specrule(specialization에서 자식 선택), aspectrule(aspect 또는 multi-aspect 형제 가운데 선택), 선택 제약(트리의 다른 곳에서 내려진 결정에 따른 교차 선택), priority(같은 수준 서술 노드 형제의 고유 번호), numRep(multi-aspect 복제 수), mb 속성(리프 전용 모델베이스 참조), couplings(엔티티와 포트 이름 쌍), SESfcn(가지치기 중 평가되는 절차적 지식, 암묵 변수 parent와 children 사용 가능).
- 작성 패턴 14개(120 ~ 125쪽): (1) aspect 노드(필수 합성), (2) multi-aspect 노드(numRep은 SESvar, 결합은 SESfcn, 다중집합 파라미터), (3) specialization 형제(두 XOR의 AND, 평가 순서가 상속 속성에 영향), (4) specialization 노드(XOR), (5) aspect 형제(aspectrule로 정확히 하나 선택), (6) multi-aspect 형제, (7) aspect와 multi-aspect 형제, (8) 선택적 구성요소(specialization 아래 NONE 리프), (9) OR 구성요소(NONE을 가진 specialization들을 자식으로 둔 aspect, 전부 NONE은 무효), (10) 한 경로에 두 specialization(속성 상속), (11) specialization 뒤의 aspect, (12) specialization과 aspect 형제(priority 필요), (13) 한 경로에 여러 multi-aspect(이름 변경과 가변 결합), (14) 선택 제약(require, exclude, 의미 조건).
- 규칙은 비형식 표기(specrule = {VAR == '1' then b; VAR == '2' then c})와 MATLAB 식 의사코드로만 적힌다. 언어는 정의되지 않는다. "가지치기 알고리즘의 형식 정의는 향후 과제의 핵심"(125쪽).
- 시사점: 14개 패턴은 플랫폼의 적합성 테스트 묶음으로 그대로 쓸 수 있다. 규칙 언어와 평가 순서 의미론은 비어 있다.

Folkerts, Deatcu, Pawletta, Hartmann (2019), "Python-based eSES/MB Framework", SNE 29(4):207-215. [원문 확인]
- 파이프라인(212쪽): 실험 제어(EC)가 SESvar를 정하고, SESToPy가 가지치기하여 PES JSON을 만들고, 평탄화하여 FPES를 만들며, SESMoPy가 모델을 생성하고, SESEuPy가 시뮬레이터를 감싸 실행한다.
- SES는 "JSON 구조로 저장"(211쪽)된다고만 적혀 있고 노드별 스키마는 없다. 리프의 mb 속성(mb = 'MB/PID')과 파라미터 속성(k, Ti, Td)으로 모델베이스를 참조한다. 실험 파라미터 범위와 시뮬레이터 지정은 expMethod, simMethod 엔티티의 속성에 들어간다(211쪽). 결합은 Python SESfcn으로 만든다.
- 백엔드: MATLAB/Simulink, Dymola, OpenModelica, MATLAB용 PDEVS 툴박스, DEVSimPy(209쪽).
- 한계: 신호 흐름 모델만 지원, 물리 모델링과 FMI는 개발 중, EC는 수작업 스크립트, 프로토타입.

Folkerts, Pawletta, Deatcu (2021), "Model Generation for Multiple Simulators Using SES/MB and FMI", ARGESIM Report 59:13-20. [원문 확인]
- 모델베이스는 OpenModelica 라이브러리(MB.mo)와 FMU 폴더다. SESMoPy가 FMU를 OpenModelica로 들여와 FPES대로 조립하고 시뮬레이터 독립적인 "모델 FMU"로 내보낸다(15쪽, 19쪽). FMI는 모델 교환만 지원하고 공동 시뮬레이션은 다루지 않는다(15쪽).
- 실험 프레임은 분리되지 않는다. simMethod와 expMethod가 시스템 하위 트리 옆의 엔티티로 들어간다(17쪽 그림 4).
- 한계: OpenModelica가 필수 허브, Simulink는 들여오기 지시만 생성.

Folkerts, Pawletta, Durak (2023), "An Extension for the Specification and Automated Selection of System Variants Based on the SES Using a Problem from Process Industry", SNE 33(1):17-25. [원문 확인]
- 확장의 실체: 새 노드 종류는 없다. (a) multi-aspect 뒤의 엔티티에 암묵 관리되는 밑줄 속성(_generatingEntity)을 두고 가지치기가 복제 인덱스를 배정하여, 같은 경로의 후속 specialization과 multi-aspect를 복제본마다 다르게 결정한다(20쪽). (b) SESfcn에서 PARENT와 CHILDREN 암묵 변수를 쓴다. (c) numRep과 specrule 결과를 SESvar와 밑줄 속성으로 계산하는 SESfcn. (d) 복제 후 multi-aspect를 aspect로 바꾸고 결합을 SESfcn으로 재계산. PES에서는 uniformity 공리가 명시적으로 완화된다(22 ~ 23쪽).
- 자동 선택의 방식: 탐색이나 솔버가 아니라 결정적 규칙 평가다. "본 논문은 자동, 목표 지향으로 정확히 하나의 변이를 선택하는 가지치기에 집중한다. 이를 위해 노드 속성에 가지치기 정보를 둔 SES 확장을 쓴다"(18쪽). 목표 지향성은 EC에서 SESvar 값을 실험 명세에 따라 정하는 데서 온다(19쪽). 사용자는 가지치기 전에 SESvar 네 개를 모두 배정해야 한다(21쪽).
- 형식화: 없음. "일반 프레임워크는 구체적 알고리즘을 정의하지 않는다"(17쪽). 4단계 수작업 유도 예(21 ~ 22쪽)와 중간 PES 개념만 있다. 가지치기 기록이나 재현성 개념은 없다. 변이 개수도 "지수적으로 증가"라고만 적는다.
- 평가(22쪽): "경로에 multi-aspect가 많아질수록 SESfcn의 복잡도가 크게 증가한다."
- 시사점: 복제 인덱스 속성과 중간 PES 단계는 플랫폼의 InstancePath와 naming 템플릿이 같은 문제를 더 단순하게 푼다. 솔버 기반 자동 분석과 가지치기 형식화는 완전히 비어 있다.

Deatcu et al. (2018) 설계 패턴 원 논문, Folkerts et al. (2020) 반응형 가지치기. [미열람]
- 2020 논문의 가지치기 분류(대화형, 자동, 열거형, 선택형)는 2023 논문 18쪽에서 재인용된 것으로 확인했다. 반응형의 세부는 미확인이다.

DLR SESTools (GitHub). Java, XML, XPath 선택 제약. 공리 여섯 가지와 가지치기 4단계를 README에 명시.

### 2.3 MBSE 연계: SES-X

Xie, Zhang, Li, Gu, Chen (2023), "SES-X: A MBSE Methodology Based on SES/MB and X Language", Information 14(1):23. [원문 확인]
- 단계(4 ~ 8쪽): 분석(요구, 유스케이스, 아키텍처), 아키텍처 분해(재귀), 아키텍처 가지치기(요구와 유스케이스 노드 제거, 기능 검증용 트리), 물리 모델링(원자 엔티티에 물리 모델 부착, 결과는 가능한 구조 집합인 SES), 물리 모델 가지치기(엔티티마다 specialization 하나 선택), 시뮬레이션 검증(X 언어 모델로 변환, XLab 실행).
- 두 수준의 가지치기는 모두 수동이다. 1수준은 "현재 모델러가 수행하며 자동화 알고리즘은 향후 연구"(6쪽). 규칙 언어, 제약 언어, 솔버가 없다.
- SES 표현은 고전 트리 그림뿐이다. XML, 텍스트 문법, X 언어 구문은 없다. 결합은 분해 간선에 포트 쌍 집합으로 주석된다(12 ~ 13쪽). 변수, 제약, 선택 함수는 도입되지 않는다.
- 모델베이스는 X 언어 모델(연속, 이산, 에이전트, 함수 클래스와 결합 클래스)이며 리프와 모델은 이름 대응으로만 연결된다(11쪽).
- 사례(9 ~ 13쪽): 자동차 = 프레임과 타이어(5개 원자 모듈). "합성이 한 수준뿐이라 엔티티마다 specialization이 하나"(11쪽)이므로 사실상 변이가 하나다.
- 한계(14쪽): "SES-X 프로세스는 아직 X 언어 구문 수준으로 코드화되지 않았다."
- 시사점: 검증용 가지치기와 실행용 가지치기를 단계로 나누는 발상만 가져온다. 형식 문법, 규칙 기반 가지치기, 모델베이스 조회는 플랫폼이 새로 제공해야 한다.

### 2.4 국내 응용

Lee, Bae, Paik (2021), "GO-DEVS", Sensors 21(20):6771. [원문 확인]
- DEVS 모델을 계층마다 블록 단위 (G, M)으로 분해한다(6 ~ 7쪽). M은 블록 id, 부모 블록 id, 부모 노드 id, 루트 노드 id, 입출력 포트. G는 다중 그래프로 노드는 하위 구성요소와 블록 루트 노드, 간선은 결합이며 루트에서 비루트는 EIC, 비루트에서 루트는 EOC, 비루트 사이는 IC다. 온톨로지는 공통 이벤트 분류 체계(EventName(ValueType) 트리)로 포트와 이벤트 이름을 통일한다.
- 질의(7 ~ 9쪽): IO 질의는 입출력 포트 명세로 모델을 찾으며, 정의 3은 질의 이벤트마다 분류 체계상 같거나 조상인 이벤트가 모델에 있으면 포함으로 본다. 구조 질의는 블록 문장(id, 부모, 직접 "/"와 간접 "//" 위상 관계, 그래프 패턴, 루트)의 집합이며 블록 내 매칭은 라벨 없는 부분그래프 동형(Ullmann)이다. 원자 모델 내부는 질의하지 않는다.
- SES 비판 원문(2쪽): "SES는 같은 수준 구성요소 사이의 관계를 고려하지 않는데, 이 관계는 그래프 패턴을 보인다." 결론(18쪽): "SES와 우리 접근을 체계적으로 통합해야 한다. 예를 들어 내부 구조를 추가하여 SES를 확장하고, 확장된 SES 데이터를 저장하고 질의하는 프레임워크를 개발할 수 있다."
- 구현: MariaDB 10.5, SQL 번역(알고리즘 1 ~ 3), 조상 검사는 전이 폐포 테이블 또는 XML 구간 번호. 합성 데이터 3만 개 모델, 질의 14개. 구조 질의는 3만 모델에서 약 6초. 복잡도 분석 없음.
- 시사점: 블록 단위 그래프 분해(수준마다 EIC, EOC, IC 간선 유형)와 분류 체계 기반 IO 호환 정의는 플랫폼의 FPES hierarchy와 PortType 설계에 그대로 대응한다. GO-DEVS가 요청한 "결합 구조를 가진 SES의 저장과 질의"는 플랫폼이 채울 공백이다.

WSN-SES/MB (Sensors 2021), 전차 취약성 분석 (2015), 미국 특허 11922102와 12265763, Cheon, Kim (2008). [미열람, 1차 검토 내용 유지]

### 2.5 LLM 기반 DEVS 모델 생성 (SES 미사용)

네 편 모두 원문을 확인했으며, SES, 가지치기, 변이성, feature model, 제품 라인에 대한 언급이 전혀 없다. 모두 기술 하나에서 모델 하나를 생성한다.

Carreira-Munich, Paz-Marcolla, Castro (2024), "DEVS Copilot", WSC 2024:2785-2796. [원문 확인]
- GPT-4 호출 두 번. 개념 명세자(자연어에서 반구조 개념 명세)와 형식 명세자(개념 명세에서 TOML 기반 DSL, 시스템 프롬프트에 BNF 포함). 파서가 PythonPDEVS 코드를 만든다(4 ~ 6쪽). 구조와 행위는 개념 명세 안에서 함께 생성되며 구조 우선 단계는 없다.
- 검증은 "현재 직접 육안 검사이며 추가 검사기는 없다"(8쪽). 결과 분류는 수용, 복구 가능(구문 오류), 오류(논리 오류). 조명 제어 시스템 7개, 정제 라운드 0 ~ 3회, 기준선 없음(9쪽 표 1).
- 향후: 오류 메시지를 내는 파서로 문법 적합성 자동 반복, LTS와 LTL 속성 자동 검증(11쪽).

Vasa, Sarjoughian, Yellig (2026), "LLM-based Framework for Generating and Verifying Parallel DEVS Statecharts", arXiv 2608.14956. [원문 확인]
- 원자 모델 하나의 자연어 기술에서 "사실"(외부, 내부, 출력 전이의 자연어 문장, JSON)을 뽑고, 행위 조건을 명제 논리로 번역하여 z3로 충족 가능성과 함의(entailment)를 검사하고, 함의되지 않은 조건을 수정 프롬프트로 되돌려 반복한 뒤, EBNF 문법으로 statechart를 생성한다(8 ~ 12쪽). "결합 모델 명세는 제외"(3쪽).
- 평가: 시스템 14개, LLM 8종, UPPAAL 교착과 도달성 검사, 전문가 점수. 검증 전후 비교에서 교착 시스템 수 감소(17쪽 표 6).
- 한계: 명제 논리는 시간을 다루지 못하고, 결합과 계층 모델 검증이 없다(18 ~ 19쪽).
- 시사점: "생성, 검사, 미충족 제약 피드백, 재생성" 루프는 SES 적합성 위반을 피드백 신호로 쓰는 설계에 그대로 재사용할 수 있다.

Zhang, Zhang, Niyato, Ren, Gu, Chen, Laili, Cai, Bruzzone (2025), "GenAI for Simulation Model in Model-Based Systems Engineering", arXiv 2503.06422. [원문 확인]
- 제품 설계 문서에서 X 언어 모델을 생성한다. NER-BERT로 문장을 걸러 내고, 결합 클래스(구성과 연결)를 먼저 생성하며("하향식 생성의 순방향 설계 원칙에 따라 결합 클래스 모델을 원자 클래스 모델보다 먼저 구성해야 한다", 5쪽), 원자 포트를 결합 모델의 연결에서 알고리즘으로 유도한 뒤(알고리즘 1, 7쪽), 미세 조정한 CodeQwen1.5-7B가 행위 코드를 채운다.
- 제약은 템플릿과 BNF이며 일관성은 사후 점수(이름, 포트, 함수의 수준 간 일치)로 측정한다. 항공기 전기 시스템 사례. 제안 방법 0.81 ~ 0.87 대 직접 프롬프트 0.16 ~ 0.24(12쪽 표 7).
- 시사점: 세 편 가운데 SES 사고방식에 가장 가깝다(구조 먼저, 포트는 결합에서 유도). 그러나 구조는 문서 하나에서 추출한 고정 구조이며 대안 선택과 가지치기가 없다.

Chen, Zhuang, Li, Li (2026), "Specification-Driven Generation and Evaluation of Discrete-Event World Models via the DEVS Formalism", arXiv 2603.03784. [원문 확인]
- 자연어 명세(운영 명세와 행위 명세)에서 xDEVS Python 패키지를 생성한다. 1단계 구조 계획(전역 골격, 결합 노드의 EIC, IC, EOC와 자식 포트 계약을 하향식으로 정제), 2단계 행위 합성(노드마다 별도 파일, 요약기가 구현된 인터페이스를 뽑아 부모가 실제 포트 이름으로 생성). 구조와 행위가 분리되어 있고 구조가 먼저 고정된다(6 ~ 8쪽).
- 중간 산출물은 Pydantic JSON(Skeleton, PlanTree, ModelPlan)이며 포트 타입, EIC/IC/EOC 문자열, 초기 인자를 담는다(17 ~ 18쪽). 검증은 트레이스 기반(운영 점수와 행위 점수). Cadmium 예제 7개 벤치마크. GPT-5.2 행위 점수 0.87(11쪽 표 2).
- 시사점: PlanTree는 사실상 FPES와 같은 평탄 구조이며, 트레이스 기반 적합성 지표는 백엔드 독립적인 생성 모델 수락 검사로 쓸 수 있다. 변이 공간은 없고 선언적 교환 형식도 없다.

### 2.6 인접 기술

Lektauers, Linkevičs, Mosāns, Fokina, Gulbe (2026), "A Model-Centric DevOps Architecture for DEVS-Based Digital Twin Simulation Services", arXiv 2609.11122. [원문 확인]
- SMDL(Simulation Model Definition Language, YAML): name, version, time_unit, models 목록. 이산 사건 모델은 variables, entities(분포 속성), blocks(source, processor, queue, gate, sink 등 사전 구축 클래스를 태그로 지정하고 to:로 연결). 추상 메타모델(그림 1)에는 Model, AtomicModel, CoupledModel, Port, Coupling(EIC, IC, EOC), Parameter가 있지만 구현된 구체 스키마는 "포트를 암묵적으로 두고" 문서 간 합성을 지원하지 않는다(6쪽). SemVer 버전 관리, 불변 아티팩트 레지스트리, 적재 시 구문, 구조, 정적 의미(참조 무결성, 결선 폐쇄, 고유 이름, 파라미터 범위) 검사(11쪽, 12쪽 표 2 결함 주입).
- FMI 어댑터와 HELICS 브로커는 아키텍처로만 기술되고 사례에서는 쓰이지 않는다(25쪽). multiPDEVS 엔진은 Java이며 비공개(26쪽).
- 변이성 없음. 실험은 고정 구조의 파라미터 스윕이다. 사례의 복제 수(링크 74,508개)는 코드 빌더가 만든다.
- 사례: 리가 버스 22번 노선, 원자 모델 115,294개, 24시간 모의 106초.
- 시사점: SMDL은 플랫폼의 FPES에서 생성할 출력 형식 후보이며, 3계층 검증 분류와 결함 주입 표는 정준 SES 검증의 본보기다. 변이성은 전혀 다루지 않는다.

SysML v2 변이 모델링과 feature model: 1차 검토 내용 유지. SES와의 공식 비교 문헌은 확인되지 않았다.

## 3. 기존 도구의 구조 분석 (SESToPy 소스 기준)

공개 소스를 직접 읽고 확인한 사실이다. 2019 SNE 논문 원문도 이를 뒷받침한다(JSON 구조의 스키마 없음, 규칙은 Python 함수).

| 항목 | SESToPy의 구현 | 평가 |
|---|---|---|
| 노드 클래스 | Node를 상속한 EntityNode, AspectNode, MaspectNode, SpecNode, DescriptiveNode. 트리 조작 메서드가 Node에 있고 Qt 표시 속성(색, 굵기)이 같은 클래스에 섞여 있다. | 도메인 모델과 GUI 모델이 분리되지 않았다. |
| 규칙 표현 | aspect 규칙, specialization 규칙, 속성 식, 의미 조건, 우선순위, 복제 개수, 결합 조건이 모두 Python 식 문자열이며 실행 시 평가(eval)한다. PATH 같은 특수 변수를 정규식으로 찾아 치환한다. | 안전성, 정적 검증, 다른 언어 백엔드로의 이식이 불가능하다. |
| 저장 형식 | "SES JSON Version 1"이라는 헤더 뒤에 줄 단위로 JSON 배열을 이어 붙인 형식. 노드는 위치 인덱스로 의미가 정해지는 리스트. 파일 머리말에 "수동 편집 금지"를 명시. | 사람이 읽거나 diff할 수 없고 스키마가 없다. |
| 모델베이스 연결 | 리프 엔티티의 속성 중 이름이 "mb"인 것의 값(문자열)으로 모델베이스 요소를 가리킨다. | 바인딩이 SES 본문에 섞여 있어 백엔드 교체 시 SES를 수정해야 한다. |
| 가지치기 | Prune 클래스 하나에 1,300줄. 선택 제약은 가지치기에서 무시된다고 README에 기록. | 전략 교체와 단위 테스트가 어렵다. |
| 되돌리기 | 미구현 (README). | 대화형 가지치기의 필수 기능이 빠져 있다. |
| uniformity 처리 | 같은 이름의 노드가 서로 다른 uid를 갖도록 복제한다. 2023 논문은 PES에서 uniformity를 명시적으로 완화한다. | 참조 의미론이 아니라 복사 의미론이라 일관성 유지 비용이 크다. |

## 4. 공통 플랫폼 구상에 주는 시사점

| 번호 | 시사점 | 근거 (원문 확인) | 플랫폼 반영 |
|---|---|---|---|
| 1 | 열린 정준 표현 형식이 없다 | SESToPy JSON에 스키마 없음(2019), SES-X는 그림뿐(2023), MS4 Me 전용 | JSON Schema로 검증되는 YAML/JSON 정준 표현 |
| 2 | 규칙을 코드 문자열로 두면 안 된다 | Deatcu 2019는 언어를 정의하지 않음, Folkerts 2023의 SESfcn 복잡도 급증 | 선언적 표현식 AST, 이름으로 등록한 함수 |
| 3 | 구조와 행위의 계약이 필요하다 | Zhang 2025와 Chen 2026이 포트를 결합에서 유도하고 인터페이스를 요약하여 일관성 확보 | 엔티티 포트와 타입, 바인딩 파일 분리, ComponentContract |
| 4 | 가지치기는 전략의 집합이며 형식화가 비어 있다 | Folkerts 2023 "구체적 알고리즘을 정의하지 않는다", Deatcu 2019 "형식 정의는 향후 과제" | 가지치기 파이프라인, 전략, 결정 기록 |
| 5 | 결합은 1급 그래프여야 한다 | GO-DEVS의 명시적 SES 확장 요청 | aspect의 결합 그래프, 패턴, 질의 |
| 6 | 클래스와 인스턴스를 구분해야 한다 | MetaSES의 클래스 노드와 인덱스 인스턴스, Folkerts 2023의 복제 인덱스 속성 | 정의 테이블과 PES 분리, InstancePath |
| 7 | 실행 시점과 연결되어야 한다 | Capocchi 2025에서 DS-DEVS가 SES와 독립 | 재가지치기 이벤트 인터페이스, PES 차분 |
| 8 | LLM 생성의 제약과 검증기로서 SES | 네 편 모두 SES 미사용, 모델 하나 생성, Vasa 2026의 피드백 루프 | 정준 표현을 구조화 출력 스키마로, 공리 검증기와 위반 피드백 |
| 9 | 다중 백엔드 생성 | Folkerts 2021의 모델 FMU 허브, Lektauers 2026의 SMDL | 백엔드별 빌더, FPES 중간 표현, SMDL 출력 후보 |
| 10 | 작성 패턴이 필요하다 | Deatcu 2019의 14개 패턴 | 패턴 카탈로그와 적합성 테스트, 린트 |
| 11 | 생성 모델의 수락 검사 | Chen 2026의 트레이스 기반 운영 점수와 행위 점수, Lektauers 2026의 3계층 적재 검증 | 백엔드 독립 수락 테스트와 결함 주입 표 |

## 5. 솔직한 평가

- SES 연구는 소수 그룹이 주도하며 2023년 이후 새 논문이 드물다. 가장 최근의 SES 전용 논문(Folkerts 2023)조차 알고리즘 형식화를 하지 않았고, 저자들이 그 공백을 명시했다. 도구는 연구용 프로토타입이고 유지보수가 멈춰 있다.
- 현재 모멘텀은 LLM 기반 DEVS 생성에 있고 네 편 모두 SES를 모른다. 가장 가까운 Zhang (2025)과 Chen (2026)도 구조 하나를 고정하여 생성한다. "변이 공간을 먼저 생성하고 검증한 뒤 가지치기"는 아무도 하지 않았다.
- GO-DEVS는 SES에 같은 수준 결합 구조를 추가하고 저장과 질의 프레임워크를 만들라고 2021년에 요청했지만, 그 뒤 수행한 연구가 확인되지 않는다.
- 편집기 GUI를 먼저 만드는 순서는 피해야 한다. 코어 라이브러리, 정준 표현, CLI, 백엔드 빌더 순으로 가고 시각화는 읽기 전용 뷰어로 시작한다.

## 참고 문헌

references.md에 링크와 열람 상태를 둔다.

- Zeigler, B. P. (2023). Extending the Hierarchy of System Specifications and Morphisms with SES Abstraction. Information, 14(1), 22.
- Capocchi, L., Zeigler, B. P., Santucci, J.-F. (2025). Simulation-Based Development of Internet of Cyber-Things Using DEVS. Computers, 14(7), 258.
- Risco-Martín, J. L., Mittal, S., de la Cruz, J. M., Zeigler, B. P. (2009). eUDEVS. Simulation, 85(11-12). arXiv:2407.08281 (2024 재게시).
- Pawletta, T. et al. (2016). Extended Variability Modeling Using System Entity Structure Ontology within MATLAB/Simulink. SpringSim.
- Schmidt, A., Durak, U., Pawletta, T. (2016). Model-based testing methodology using system entity structures for MATLAB/Simulink models. Simulation, 92(8).
- Deatcu, C., Folkerts, H., Pawletta, T., Durak, U. (2018). Design Patterns for Variability Modeling Using SES Ontology. Mod4Sim, SpringSim.
- Deatcu, C., Folkerts, H., Pawletta, T., Durak, U. (2019). How to Define SES Trees for Variability Modeling. SNE, 29(3), 117-126.
- Folkerts, H., Deatcu, C., Pawletta, T., Hartmann, S. (2019). Python-based eSES/MB Framework. SNE, 29(4), 207-215.
- Folkerts, H., Pawletta, T., Deatcu, C., Zeigler, B. (2020). Automated, Reactive Pruning of System Entity Structures for Simulation Engineering. SpringSim.
- Folkerts, H., Pawletta, T., Deatcu, C. (2021). Model Generation for Multiple Simulators Using SES/MB and FMI. ARGESIM Report 59, 13-20.
- Folkerts, H., Pawletta, T., Durak, U. (2023). An Extension for the Specification and Automated Selection of System Variants Based on the SES Using a Problem from Process Industry. SNE, 33(1), 17-25.
- Xie, K., Zhang, L., Li, X., Gu, P., Chen, Z. (2023). SES-X: A MBSE Methodology Based on SES/MB and X Language. Information, 14(1), 23.
- Lee, C.-H., Bae, J. W., Paik, E. (2021). GO-DEVS. Sensors, 21(20), 6771.
- Carreira-Munich, T., Paz-Marcolla, V., Castro, R. (2024). DEVS Copilot. Winter Simulation Conference 2024, 2785-2796.
- Vasa, V. K., Sarjoughian, H. S., Yellig, E. J. (2026). LLM-based Framework for Generating and Verifying Parallel DEVS Statecharts. arXiv:2608.14956.
- Zhang, L. et al. (2025). GenAI for Simulation Model in Model-Based Systems Engineering. arXiv:2503.06422.
- Chen, Z., Zhuang, H., Li, Z., Li, C. (2026). Specification-Driven Generation and Evaluation of Discrete-Event World Models via the DEVS Formalism. arXiv:2603.03784.
- Lektauers, A. et al. (2026). A Model-Centric DevOps Architecture for DEVS-Based Digital Twin Simulation Services. arXiv:2609.11122.
- Zeigler, B. P., Sarjoughian, H. S. (2013). Guide to Modeling and Simulation of Systems of Systems. Springer.
- GitHub: hendrikfolkerts/sestopy, sesmopy, seseupy, sesecpy. aeronautical-informatics/SESTools.
