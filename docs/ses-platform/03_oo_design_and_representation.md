# 객체지향과 설계 패턴을 연계한 SES 개선 방안과 구조 표현

작성일: 2026-11-03

이 문서는 SES(System Entity Structure, 시스템 엔티티 구조)를 객체지향(Object-Oriented, OO) 개념과 소프트웨어 설계 패턴에 대응시켜 개선하고, 공통 플랫폼이 사용할 구조 표현을 제안한다. 예시 파일은 examples 디렉터리, 스키마 초안은 schema 디렉터리에 있다.

## 1. SES 개념과 객체지향 개념의 대응

| SES 개념 | 의미 | 객체지향 대응 | 비고 |
|---|---|---|---|
| entity | 실세계 대상 또는 모델 구성요소 | 클래스(정의)와 객체(인스턴스) | SES 본래 표기는 둘을 구분하지 않는다. 플랫폼은 구분한다 |
| aspect | 분해(decomposition). 부분들의 조합 하나 | 합성(has-a). 생성자 또는 조립 코드 하나 | 형제 aspect는 서로 다른 분해 방식 |
| multi-aspect | 같은 종류 부분의 집합 | 컬렉션 타입 (List[T]) 과 개수 제약 | 복제본은 동일 정의의 인스턴스 |
| specialization | 분류(taxonomy). 대안 가운데 하나 | 상속(is-a), 추상 클래스와 구체 클래스 | inheritance 공리가 속성 상속을 뜻한다 |
| attached variables | 엔티티에 붙는 속성 | 필드, 생성자 인자 | 값은 가지치기 시점에 결정된다 |
| coupling | aspect 내부 부분 사이의 포트 연결 | 객체 간 참조 그래프, 인터페이스 연결 | 트리가 아닌 그래프다 |
| port | 입출력 지점 | 인터페이스 메서드 또는 타입이 있는 채널 | 선행 도구 대부분이 타입을 두지 않는다 |
| SESvar, SESfunction | 전역 변수와 유도 값 | 설정 객체와 순수 함수 | 코드 문자열이 아니어야 한다 |
| aspect 규칙, specialization 규칙 | 선택 조건 | 명세(Specification) 객체 | 평가 가능하고 직렬화 가능해야 한다 |
| selection constraint | 경로를 가로지르는 제약 | 불변식(invariant) | 가지치기 전후에 검사 |
| uniformity 공리 | 같은 이름은 같은 구조 | 참조 의미론. 정의는 하나, 사용은 여럿 | 복사 대신 참조 |
| strict hierarchy 공리 | 경로 위에 같은 이름 금지 | 재귀 합성 금지 | 재귀 구조는 명시적 깊이 제한으로 별도 처리 |
| alternating mode 공리 | entity와 aspect/spec이 번갈아 나타남 | 클래스와 관계가 교대로 | 메타모델의 타입 시스템으로 강제 |
| valid brothers 공리 | 형제는 이름이 다름 | 네임스페이스 내 고유 이름 | 스키마 검증으로 강제 |
| pruning | 변이 공간에서 하나의 구조 선택 | 설정(configuration) 적용과 의존성 해결 | 결정의 열(sequence)로 기록 |
| PES | 가지치기 결과 | 객체 그래프 명세 | 인스턴스 수준 |
| FPES | 평탄화된 PES | 조립 스크립트 입력 | 리프 인스턴스와 결합 목록 |
| model base | 실행 가능한 구성요소 저장소 | 클래스 라이브러리, 패키지 | 바인딩으로 연결 |

## 2. 개선 방안

각 항목은 문제, 제안, 적용 패턴, 효과로 적는다.

### 2.1 정의와 사용의 분리 (타입과 인스턴스)

- 문제: 고전 SES와 SESToPy는 트리의 각 노드를 독립 객체로 복사한다. uniformity 공리를 만족시키려고 같은 이름의 하위 트리를 다시 복사하고 uid를 달리 준다. 큰 트리에서 일관성 유지 비용이 크다.
- 제안: 엔티티 정의(EntityDef)를 이름으로 한 번만 두는 정의 테이블을 만들고, aspect의 parts와 specialization의 alternatives는 정의를 참조(EntityRef)한다. 트리는 참조를 따라가며 펼쳐지는 뷰(view)가 된다. MetaSES의 "클래스에 속하는 다수 구성요소"와 같은 발상이다.
- 적용 패턴: Flyweight(공유 정의), Composite(펼쳐진 트리 뷰).
- 효과: uniformity 공리가 구조적으로 보장된다. 정의 하나를 바꾸면 모든 사용처가 바뀐다. 파일이 짧아지고 diff가 읽힌다.

### 2.2 specialization을 상속으로

- 문제: specialization 대안은 부모 엔티티의 속성과 포트를 반복 기술한다. 선택적 구성요소를 표현하려고 "없음"을 뜻하는 가짜 대안을 임의로 만든다.
- 제안: 대안 엔티티는 extends로 부모를 지정하고 포트와 속성을 상속한다(inheritance 공리의 구현). 추상 엔티티(stereotype abstract)는 가지치기 결과에 남을 수 없다. 선택적 구성요소는 Null Object 패턴으로 표준화한다. 즉 포트는 같지만 행위가 없는 NullX 엔티티를 플랫폼이 자동 생성하고, 평탄화 단계에서 결합을 제거한다.
- 적용 패턴: Inheritance, Abstract Class, Null Object, Liskov 치환 원칙(대안은 부모의 포트 계약을 좁히지 못한다).
- 효과: 대안 추가 비용이 줄고, 바인딩 검증 시 부모 계약으로 모든 대안을 한 번에 검사할 수 있다.

### 2.3 aspect를 합성으로, multi-aspect를 컬렉션으로

- 문제: multi-aspect의 복제 개수와 복제본 사이 결합을 도구마다 다르게 다룬다. SESToPy는 복제 개수를 문자열 식으로 두고 가지치기 중 PATH 변수로 밑줄 이름을 접근한다.
- 제안: multi-aspect는 part(정의 참조), cardinality(상수, 변수, 범위), naming 템플릿, coupling pattern을 갖는 컬렉션 타입으로 본다. 복제는 Prototype 패턴으로 정의에서 인스턴스를 찍어내고, 패턴(fan_out_fan_in, chain, ring, broadcast)이 결합을 생성한다.
- 적용 패턴: Composite, Prototype, Builder(결합 패턴 생성기).
- 효과: WSN-SES/MB 같은 대규모 복제 사례를 선언 몇 줄로 기술한다. 복제본 사이 결합이 규칙이 아니라 패턴 이름으로 남아 읽기 쉽다.

### 2.4 결합을 1급 그래프로

- 문제: 결합은 트리 노드의 부속 데이터이며 질의나 검증 대상이 아니다. GO-DEVS는 같은 수준 관계를 SES가 다루지 못한다고 비판했다.
- 제안: 포트에 타입과 방향을 두고, aspect는 CouplingGraph 객체를 갖는다. 그래프는 포트 타입 일치, 방향 일치, 미연결 포트, 순환을 검증한다. 구조 질의(어떤 엔티티가 Job 타입을 소비하는가)와 IO 질의(입출력 포트 시그니처로 엔티티 찾기)를 제공한다.
- 적용 패턴: Interface(포트 계약), Mediator(aspect가 부분 사이 연결을 소유), Graph 표현.
- 효과: 모델베이스 검색, 결합 오류의 조기 발견, 시각화에서 트리와 그래프를 함께 보여줄 수 있다.

### 2.5 규칙과 제약을 객체로

- 문제: 규칙이 eval되는 Python 문자열이다. 안전하지 않고, C++ 백엔드나 다른 언어로 옮길 수 없으며, 정적 검사가 불가능하다.
- 제안: 작은 선언적 표현식 AST(var, eq, ne, ge, gt, le, lt, in, all, any, not, selected, call)를 정의한다. 복잡한 논리는 이름으로 등록한 함수(call)로 호출하고 함수 본문은 플러그인 코드에 둔다. 규칙은 Specification 객체로서 평가(evaluate), 설명(explain), 직렬화(to_dict)를 제공한다.
- 적용 패턴: Interpreter(AST 평가), Specification(조합 가능한 조건), Registry(이름으로 함수 등록), Strategy(함수 본문 교체).
- 효과: 규칙이 데이터로 남아 검증과 diff가 가능하다. 같은 규칙을 Python과 C++에서 평가할 수 있다. 선택 제약을 가지치기가 무시하는 SESToPy의 결함이 구조적으로 사라진다.

### 2.6 가지치기를 파이프라인과 전략으로

- 문제: 가지치기가 하나의 큰 함수이며 대화형, 자동, 열거형, 선택형, 반응형 방식을 분리할 수 없다. 되돌리기가 없다.
- 제안: 가지치기를 결정 지점(DecisionPoint) 열거, 전략에 의한 결정(Decision), 적용, 검증의 네 단계로 고정한 템플릿으로 만든다. 결정 지점 종류는 변수 배정, aspect 선택, specialization 선택, cardinality 결정의 네 가지다. 전략은 책임 연쇄로 순서대로 시도한다. 명시 결정(구성 파일), 규칙 평가, 기본값, 대화형 질의, 탐색 알고리즘(열거형, 목표 지향 선택형)의 순이다. 각 결정은 Command 객체이며 undo를 갖고 결정 기록(trace)에 쌓인다. 반응형 가지치기는 실험 결과 Observer가 특정 결정을 무효화하고 그 지점부터 다시 실행하는 방식으로 구현한다.
- 적용 패턴: Template Method, Strategy, Chain of Responsibility, Command, Memento, Observer.
- 효과: 다섯 가지 가지치기 방식이 전략 조합으로 표현된다. 결정 기록으로 재현, 비교, 설명이 가능하다. SES-X의 2단계 가지치기는 전략 목록을 두 번 다르게 구성하는 것으로 표현된다.

### 2.7 모델 생성을 추상 팩토리로

- 문제: 모델 빌더가 시뮬레이터별 코드로 흩어져 있고 SES 본문에 모델베이스 참조(mb 속성)가 섞여 있다.
- 제안: FPES를 공통 중간 표현으로 고정한다. 바인딩 파일이 엔티티 정의를 백엔드 구현체에 매핑하고, ModelBuilder 추상 팩토리가 백엔드마다 구현된다. 빌더는 생성 전에 계약(포트 이름과 타입, 생성자 인자)을 구현체의 메타데이터와 대조한다.
- 적용 패턴: Abstract Factory, Builder, Adapter(구현체 메타데이터 추출), Dependency Injection(바인딩).
- 효과: 같은 SES와 구성에서 pyevsim, evsimpp, FMI 모델을 생성한다. SES는 백엔드를 모른다.

### 2.8 횡단 연산을 방문자로

- 문제: 검증, 평탄화, 렌더링, 내보내기가 각각 트리 순회 코드를 중복한다.
- 제안: 노드 클래스는 accept만 제공하고, 연산은 Visitor로 구현한다. 공리 검증기, 린트, 평탄화, 시각화, 외부 형식 변환기가 모두 방문자다.
- 적용 패턴: Visitor.
- 효과: 노드 종류가 고정되어 있어 Visitor가 적합하다. 새 연산 추가가 코어 변경 없이 가능하다.

### 2.9 확장 지점을 메타데이터와 플러그인으로

- 문제: 도메인별 부가 정보(비용, 신뢰도, 시각화 힌트)를 넣으려면 노드 클래스를 고쳐야 한다.
- 제안: 모든 노드에 metadata 네임스페이스를 두고 코어는 해석하지 않는다. 플러그인은 엔트리 포인트로 함수, 결합 패턴, 빌더, 변환기, 린트 규칙을 등록한다.
- 적용 패턴: Decorator(주석 부착), Plugin Registry, Open-Closed 원칙.
- 효과: 코어가 작고 안정된다.

### 2.10 실험 프레임을 SES로

- 문제: 실험 프레임(generator, acceptor, transducer)이 코드에 묻혀 재사용되지 않는다.
- 제안: 실험 프레임을 별도 SES로 쓰고(stereotype frame), 시스템 SES의 루트와 합성하는 연산을 둔다. 합성은 두 트리를 새 루트 아래 두 aspect로 두고 결합을 추가하는 방식이다.
- 적용 패턴: Composite, Facade(합성 연산).
- 효과: 같은 시스템 SES에 여러 실험 프레임을 붙여 실험 계열을 만든다. EFSUT 관련 논의의 "질문마다 프레임" 개념과 맞는다.

## 3. 메타모델

핵심 클래스 (L0 코어)

| 클래스 | 역할 | 주요 필드 |
|---|---|---|
| SES | 하나의 변이 공간 문서 | name, version, variables, port_types, entities(정의 테이블), constraints, root |
| Variable | SES 변수 | name, type, default, range 또는 values |
| PortType | 메시지 타입 | name, fields |
| EntityDef | 엔티티 정의 | name, ports, attributes, parent(extends), aspects, multi_aspects, specializations, stereotype, metadata |
| Port | 포트 | name, type(PortType 참조), direction |
| Attribute | 속성 | name, type, default, unit, expr |
| Aspect | 분해 | name, parts(EntityRef 목록), couplings(CouplingGraph), rule, priority |
| MultiAspect | 컬렉션 분해. Aspect 상속 | part(EntityRef), cardinality, naming, pattern |
| Specialization | 분류 | name, alternatives(EntityRef 목록), select(SelectRule), default |
| EntityRef | 정의 참조 | name, 선택적 alias |
| CouplingGraph | 결합 그래프 | edges(Coupling 목록), 검증 메서드 |
| Coupling | 결합 한 개 | from(포트 경로), to(포트 경로) |
| Expr | 표현식 AST 기반 클래스 | evaluate(env), explain(), to_dict() |
| Constraint | 선택 제약 | name, when, require, forbid |

연산 클래스 (L1)

| 클래스 | 역할 |
|---|---|
| Visitor | 트리 순회 인터페이스 |
| AxiomValidator | 여섯 공리 검사 |
| Linter | 작성 패턴 검사 |
| DecisionPoint | 가지치기 결정 지점 |
| Decision | Command. apply, undo, explain |
| PruningStrategy | 결정 지점에 대한 결정 생성 |
| Pruner | 템플릿. 결정 지점 열거, 전략 연쇄, 적용, 검증 |
| PruningTrace | 결정 기록 |
| PES | 가지치기 결과. 인스턴스 트리 |
| Flattener | PES를 FPES로 |
| FPES | 리프 인스턴스 목록, 속성 값, 결합 목록 |
| Merger, Differ, Query | 병합, 차이, 질의 |

생성 클래스 (L3)

| 클래스 | 역할 |
|---|---|
| Binding | 엔티티 정의에서 구현체로의 매핑 |
| ComponentContract | 포트와 생성자 인자 계약 |
| ModelBuilder | 추상 팩토리. build(fpes, binding) |
| PyevsimBuilder, EvsimppBuilder, FmiBuilder | 백엔드 구현 |

관계 요약
- SES는 EntityDef를 이름으로 소유한다. EntityDef는 Aspect, MultiAspect, Specialization을 소유한다. Aspect와 Specialization은 EntityRef로 EntityDef를 참조한다. 이 참조 때문에 메타모델은 트리가 아니라 방향 그래프이며, strict hierarchy 공리는 "펼친 경로 위에 같은 정의가 두 번 나오지 않음"으로 검사한다.
- PES는 SES의 정의를 참조하는 인스턴스 노드 트리다. 인스턴스 노드는 정의 참조, 인스턴스 이름, 확정된 속성 값, 선택된 aspect 또는 대안을 갖는다.

## 4. 설계 패턴 적용표

| 패턴 | 적용 위치 | 해결하는 문제 |
|---|---|---|
| Composite | 펼쳐진 SES 트리, PES | 계층 순회 |
| Flyweight | EntityDef 정의 테이블 | uniformity, 중복 제거 |
| Prototype | multi-aspect 복제 | 정의에서 인스턴스 생성 |
| Null Object | 선택적 구성요소 | 가짜 대안 제거 |
| Interpreter | Expr AST | eval 제거 |
| Specification | 규칙과 제약 | 조합과 설명 |
| Registry | SES 함수, 결합 패턴, 빌더, 변환기 | 플러그인 등록 |
| Strategy | 가지치기 전략, 결합 패턴, 함수 본문 | 방식 교체 |
| Template Method | Pruner | 고정된 가지치기 절차 |
| Chain of Responsibility | 전략 연쇄, 린트 규칙 연쇄 | 우선순위 있는 결정 |
| Command, Memento | Decision, PruningTrace | 되돌리기, 재현, 설명 |
| Observer | 반응형 가지치기 | 실험 결과에 따른 재가지치기 |
| Visitor | 검증, 린트, 평탄화, 렌더링, 변환 | 연산 추가 |
| Abstract Factory, Builder | ModelBuilder | 다중 백엔드 |
| Adapter | 구현체 메타데이터 추출, 외부 형식 변환 | 이질 환경 연결 |
| Mediator | Aspect의 CouplingGraph | 부분 사이 연결 소유 |
| Facade | SES 합성, CLI 진입점 | 단순한 외부 API |
| Decorator | metadata 네임스페이스 | 코어 수정 없는 주석 |

## 5. SES 작성 패턴 카탈로그

Deatcu et al. (2018, 2019)의 패턴을 플랫폼 표현으로 다시 쓰고 객체지향 패턴과 연결했다. 린트 규칙의 근거가 된다.

| 번호 | 패턴 | 의도 | 플랫폼 표현 | 연결 OO 패턴 |
|---|---|---|---|---|
| P1 | 필수 구성요소 | 항상 포함되는 부분 | aspect 하나에 parts로 나열 | 합성 |
| P2 | 필수 집합 | 같은 종류가 여러 개 | multi_aspect와 cardinality | 컬렉션 |
| P3 | 대안 선택 | 여러 구현 중 하나 | specialization과 extends | 상속, Strategy |
| P4 | 선택적 구성요소 | 있을 수도 없을 수도 | specialization에 Null 대안 자동 생성 | Null Object |
| P5 | 대안 분해 | 분해 방식 자체가 여러 개 | 형제 aspect와 priority 또는 rule | Builder 교체 |
| P6 | 변수 의존 선택 | 변수 값에 따라 구조 결정 | select의 when, rule | Specification |
| P7 | 교차 제약 | 멀리 떨어진 선택 사이 의존 | constraints의 when, require, forbid | 불변식 |
| P8 | 공유 하위 구조 | 같은 구조를 여러 곳에서 | 정의 테이블 참조 | Flyweight |
| P9 | 복제본 결합 패턴 | 복제본 사이와 외부 연결 | pattern fan_out_fan_in, chain, ring, broadcast | Builder |
| P10 | 유도 속성 | 변수에서 계산되는 값 | attribute의 expr | 순수 함수 |
| P11 | 실험 프레임 결합 | 시스템과 프레임 분리 | experimental_frames와 합성 연산 | Facade |
| P12 | 계층 추상화 | 추상 엔티티로 계약만 정의 | stereotype abstract와 extends | 추상 클래스 |

린트 예: specialization의 대안이 부모의 포트를 삭제하면 위반(P3, Liskov). multi_aspect에 결합 패턴이 없고 외부 포트가 있으면 경고(P9). 같은 하위 구조를 두 정의로 중복 기술하면 경고(P8).

Deatcu et al. (2019) 원문의 패턴 14개와의 대응 (2026-11-04 원문 확인 후 추가). 원문 패턴은 플랫폼의 적합성 테스트 묶음으로 쓴다.

| 원문 패턴 | 플랫폼 패턴 | 플랫폼에서 달라지는 점 |
|---|---|---|
| 1 aspect 노드 | P1 | 동일 |
| 2 multi-aspect 노드 | P2, P9 | numRep은 cardinality, 결합 SESfcn은 coupling pattern 선언으로 대체 |
| 3 specialization 형제 | P3 | 평가 순서를 결정 기록에 남겨 상속 속성 충돌을 보고 |
| 4 specialization 노드 | P3 | 동일 |
| 5, 6, 7 aspect, multi-aspect 형제 | P5 | aspectrule 대신 rule과 priority |
| 8 선택적 구성요소(NONE 리프) | P4 | NONE을 사용자가 만들지 않고 플랫폼이 Null 대안을 생성 |
| 9 OR 구성요소 | P4와 P7의 조합 | 전부 NONE 금지를 constraint로 표현 |
| 10 한 경로에 두 specialization | P3, P12 | extends 사슬로 상속을 명시 |
| 11 specialization 뒤의 aspect | P3, P1 | 동일 |
| 12 specialization과 aspect 형제 | P5 | priority |
| 13 한 경로에 여러 multi-aspect | P2, P9 | 이름 변경은 naming 템플릿, 가변 결합은 pattern |
| 14 선택 제약과 의미 조건 | P7 | require, forbid, 변수 domain |

## 6. 구조 표현

### 6.1 정준 YAML 표현

설계 원칙
- 타입 수준(SES), 결정(configuration), 바인딩(binding)을 세 파일로 분리한다. 예시는 examples 디렉터리의 processing_system 세 파일이다.
- 엔티티는 entities 아래 이름을 키로 한 번만 정의한다. parts와 alternatives는 이름으로 참조한다.
- 규칙과 제약은 표현식 AST(JSON 객체)로 쓴다. 코드 문자열은 없다.
- 결합은 "part.port" 문자열 두 개로 쓰고, multi-aspect에서는 {part}, {i}, {next}, {prev} 자리표시자를 쓴다.
- metadata 키는 어디에나 둘 수 있고 코어는 해석하지 않는다.
- JSON Schema(schema/ses.schema.json)로 구조를 검증한다. 공리와 참조 무결성은 스키마로 표현할 수 없으므로 코어 검증기가 맡는다.

예시 핵심 부분 (전체는 examples/processing_system.ses.yaml)

```yaml
entities:
  Buffer:
    ports:
      in: {type: Job, direction: in}
      out: {type: Job, direction: out}
    specializations:
      policySpec:
        alternatives: [FifoBuffer, PriorityBuffer]
        select:
          when: {var: policy, eq: fifo}
          then: FifoBuffer
          else: PriorityBuffer
  ServerPool:
    multi_aspects:
      serversMAsp:
        part: Server
        cardinality: {var: num_servers}
        naming: "server_{i}"
        couplings:
          pattern: fan_out_fan_in
          fan_out: [{from: in, to: "{part}.in"}]
          fan_in: [{from: "{part}.out", to: out}]
```

### 6.2 텍스트 DSL 스케치

사람이 빠르게 쓰고 LLM이 생성하기 쉬운 표면 문법이다. 파서는 이 문법을 정준 YAML과 같은 객체 모델로 변환한다. 의미는 YAML과 1 대 1이며, 새로운 개념을 추가하지 않는다.

```
ses ProcessingSystem version 0.1.0

var num_servers: int = 2 in [1, 8]
var policy: enum(fifo, priority) = fifo

porttype Job { id: int, priority: int, created_at: float }
porttype Ack { job_id: int }

entity ProcessingSystem root {
  aspect pipelineDec {
    parts Generator, Buffer, ServerPool, Collector
    couple Generator.out to Buffer.in
    couple Buffer.out to ServerPool.in
    couple ServerPool.out to Collector.in
    couple ServerPool.done to Buffer.ack
  }
}

entity Generator atomic {
  port out: Job out
  attr interarrival: float = 1.0 [s]
}

entity Buffer {
  port in: Job in
  port ack: Ack in
  port out: Job out
  attr capacity: int = 100
  spec policySpec {
    alternatives FifoBuffer, PriorityBuffer
    select FifoBuffer when policy == fifo else PriorityBuffer
  }
}

entity FifoBuffer extends Buffer atomic
entity PriorityBuffer extends Buffer atomic { attr levels: int = 3 }

entity ServerPool {
  port in: Job in
  port out: Job out
  port done: Ack out
  maspect serversMAsp of Server times num_servers as "server_{i}" {
    pattern fan_out_fan_in
    fan_out in to {part}.in
    fan_in {part}.out to out
    fan_in {part}.done to done
  }
}

entity Server atomic {
  port in: Job in
  port out: Job out
  port done: Ack out
  attr service_time: float = 2.0 [s]
}

entity Collector atomic {
  port in: Job in
  attr log_path: str = "results/jobs.csv"
}

constraint priority_needs_pool
  when policy == priority require num_servers >= 2
```

문법 요점
- 블록 머리는 "종류 이름 수식어"이며 중괄호 본문은 선택이다.
- 식은 var, 상수, 비교, and, or, not, 함수 호출만 허용한다. 파서가 AST로 바꾸고 그 외 구문은 거부한다.
- 결합은 couple A.p to B.q 한 형식만 둔다.

### 6.3 Python API 스케치

코어 클래스의 골격이다. 반환 타입은 주석으로 적었다.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class Node(ABC):
    name: str

    def accept(self, visitor, ctx=None):
        # 각 하위 클래스가 visitor.visit_<kind>(self, ctx)를 호출한다
        ...


@dataclass
class EntityRef:
    name: str
    alias: str | None = None


@dataclass
class Port:
    name: str
    type: str          # PortType 이름
    direction: str     # "in" 또는 "out"


@dataclass
class Attribute:
    name: str
    type: str
    default: object = None
    unit: str | None = None
    expr: "Expr | None" = None


@dataclass
class Aspect(Node):
    name: str
    parts: list[EntityRef]
    couplings: "CouplingGraph"
    rule: "Expr | None" = None
    priority: int | None = None


@dataclass
class MultiAspect(Aspect):
    part: EntityRef = None
    cardinality: "Cardinality" = None
    naming: str = "{part}_{i}"
    pattern: "CouplingPattern | None" = None


@dataclass
class Specialization(Node):
    name: str
    alternatives: list[EntityRef]
    select: "SelectRule | None" = None
    default: EntityRef | None = None


@dataclass
class EntityDef(Node):
    name: str
    ports: dict[str, Port] = field(default_factory=dict)
    attributes: dict[str, Attribute] = field(default_factory=dict)
    parent: str | None = None            # extends
    aspects: dict[str, Aspect] = field(default_factory=dict)
    multi_aspects: dict[str, MultiAspect] = field(default_factory=dict)
    specializations: dict[str, Specialization] = field(default_factory=dict)
    stereotype: str | None = None
    metadata: dict = field(default_factory=dict)

    def all_ports(self, ses):
        # 상속을 따라 부모 포트를 합친 사전을 돌려준다 (inheritance 공리)
        ...


@dataclass
class SES:
    name: str
    version: str
    variables: dict[str, "Variable"]
    port_types: dict[str, "PortType"]
    entities: dict[str, EntityDef]
    constraints: list["Constraint"]
    root: str

    def resolve(self, ref: EntityRef):
        return self.entities[ref.name]

    def validate(self):
        # AxiomValidator를 실행하고 위반 목록을 돌려준다
        ...


class Expr(ABC):
    @abstractmethod
    def evaluate(self, env):
        ...

    @abstractmethod
    def explain(self):
        ...

    @abstractmethod
    def to_dict(self):
        ...


class Visitor(ABC):
    def visit_entity(self, node, ctx): ...
    def visit_aspect(self, node, ctx): ...
    def visit_multi_aspect(self, node, ctx): ...
    def visit_specialization(self, node, ctx): ...
```

가지치기 골격

```python
@dataclass
class DecisionPoint:
    kind: str            # "variable", "aspect", "specialization", "cardinality"
    path: str            # 펼친 트리 경로. 예: "ProcessingSystem/Buffer/policySpec"
    options: list        # 선택 가능한 후보


class Decision(ABC):
    point: DecisionPoint
    reason: str          # 어떤 전략이 왜 골랐는지

    @abstractmethod
    def apply(self, pes): ...

    @abstractmethod
    def undo(self, pes): ...


class PruningStrategy(ABC):
    @abstractmethod
    def decide(self, point, env):
        # Decision 또는 None. None이면 다음 전략으로 넘어간다
        ...


class Pruner:
    def __init__(self, strategies: list[PruningStrategy]):
        self.strategies = strategies

    def prune(self, ses, config):
        # returns (PES, PruningTrace)
        pes = PES.from_root(ses)
        trace = PruningTrace()
        env = Env(ses, config)
        for point in self.enumerate_points(ses, pes, env):
            decision = self.first_decision(point, env)
            decision.apply(pes)
            trace.append(decision)
            self.check_constraints(ses, pes, env, partial=True)
        self.check_constraints(ses, pes, env, partial=False)
        return pes, trace
```

전략 조합으로 가지치기 방식을 표현한다.

| 방식 | 전략 목록 |
|---|---|
| 자동 | ExplicitDecision, RuleEvaluation, DefaultValue |
| 대화형 | ExplicitDecision, RuleEvaluation, InteractivePrompt |
| 열거형 | Enumerate (모든 결정 지점에서 분기하여 PES 집합 생성) |
| 선택형(목표 지향) | ExplicitDecision, RuleEvaluation, ObjectiveSearch |
| 반응형 | 자동 전략에 더하여 ResultObserver가 결정을 무효화하고 재실행 |

### 6.4 공리 검증 규칙

| 공리 | 검사 방법 | 위반 시 메시지 |
|---|---|---|
| uniformity | 정의 테이블 구조상 자동 보장. 가져오기(SESToPy 등)에서는 같은 이름의 노드 구조가 다르면 보고 | "같은 이름 X가 다른 구조로 두 번 정의됨" |
| strict hierarchy | 펼친 경로를 따라가며 같은 정의가 두 번 나오면 위반 | "경로 P에서 X가 재귀적으로 나타남" |
| alternating mode | 메타모델 타입이 강제. EntityDef 아래에는 aspect, multi_aspect, specialization만, 그 아래에는 EntityRef만 | 스키마 오류 |
| valid brothers | 같은 EntityDef 안의 aspect, multi_aspect, specialization 이름 고유. 같은 aspect의 parts 이름(또는 alias) 고유 | "형제 이름 충돌 X" |
| attached variables | 속성 이름은 EntityDef 안에서 고유. 상속받은 속성과 충돌하면 재정의로 간주하고 타입이 같아야 함 | "속성 a의 타입이 부모와 다름" |
| inheritance | extends 대상이 존재하고 순환이 없음. 대안의 포트가 부모 포트를 포함 | "X가 부모 포트 p를 제거함" |

추가 검사: 결합의 포트 존재와 타입 일치, 방향 일치(out에서 in으로, 외부 in에서 내부 in으로, 내부 out에서 외부 out으로), 변수 참조 존재, 루트 유일성, 추상 엔티티가 리프로 남지 않음.

### 6.5 PES와 FPES 표현

PES (인스턴스 트리)

```yaml
pes: "1.0"
ses: {name: ProcessingSystem, version: "0.1.0"}
configuration: priority_4servers
trace_hash: "sha256:..."
root:
  def: ProcessingSystem
  name: ProcessingSystem
  aspect: pipelineDec
  children:
    - {def: Generator, name: Generator, values: {interarrival: 0.5, seed: 0}}
    - {def: PriorityBuffer, name: Buffer, via: policySpec, values: {capacity: 100, levels: 3}}
    - def: ServerPool
      name: ServerPool
      multi_aspect: serversMAsp
      cardinality: 4
      children:
        - {def: Server, name: server_0, values: {service_time: 1.5}}
        - {def: Server, name: server_1, values: {service_time: 2.0}}
        - {def: Server, name: server_2, values: {service_time: 2.0}}
        - {def: Server, name: server_3, values: {service_time: 2.0}}
    - {def: Collector, name: Collector, values: {log_path: "results/jobs.csv"}}
```

FPES (평탄화 결과. 빌더 입력)

```yaml
fpes: "1.0"
instances:
  - {path: ProcessingSystem/Generator, def: Generator, values: {interarrival: 0.5, seed: 0}}
  - {path: ProcessingSystem/Buffer, def: PriorityBuffer, values: {capacity: 100, levels: 3}}
  - {path: ProcessingSystem/ServerPool/server_0, def: Server, values: {service_time: 1.5}}
  - {path: ProcessingSystem/ServerPool/server_1, def: Server, values: {service_time: 2.0}}
  - {path: ProcessingSystem/ServerPool/server_2, def: Server, values: {service_time: 2.0}}
  - {path: ProcessingSystem/ServerPool/server_3, def: Server, values: {service_time: 2.0}}
  - {path: ProcessingSystem/Collector, def: Collector, values: {log_path: "results/jobs.csv"}}
couplings:
  - {from: ProcessingSystem/Generator.out, to: ProcessingSystem/Buffer.in}
  - {from: ProcessingSystem/Buffer.out, to: ProcessingSystem/ServerPool/server_0.in}
  - {from: ProcessingSystem/Buffer.out, to: ProcessingSystem/ServerPool/server_1.in}
  - {from: ProcessingSystem/Buffer.out, to: ProcessingSystem/ServerPool/server_2.in}
  - {from: ProcessingSystem/Buffer.out, to: ProcessingSystem/ServerPool/server_3.in}
  - {from: ProcessingSystem/ServerPool/server_0.out, to: ProcessingSystem/Collector.in}
  - {from: ProcessingSystem/ServerPool/server_0.done, to: ProcessingSystem/Buffer.ack}
hierarchy:
  - {path: ProcessingSystem, kind: coupled, children: [Generator, Buffer, ServerPool, Collector]}
  - {path: ProcessingSystem/ServerPool, kind: coupled, children: [server_0, server_1, server_2, server_3]}
```

평탄화는 결합 모델 경계를 지우고 리프 사이 결합으로 바꾼다. hierarchy 항목은 백엔드가 결합 모델 계층을 보존하고 싶을 때 쓰는 선택 정보다. pyevsim과 evsimpp는 계층을 보존하는 쪽이 자연스러우므로 빌더는 hierarchy를 우선 사용하고, 평탄 결합만 받는 백엔드(일부 FMI 도구)는 couplings를 쓴다.

## 7. SysML v2와 feature model 대응

| 플랫폼 개념 | SysML v2 | feature model |
|---|---|---|
| EntityDef | part def | feature (추상) |
| EntityRef in aspect | part usage | mandatory feature |
| specialization | variation과 variant (part def 아래 variant 선언) | alternative (xor) group |
| Null 대안 | 선택적 usage (multiplicity 0..1) | optional feature |
| multi_aspect와 cardinality | part usage multiplicity [n] | cardinality-based feature |
| constraint | constraint usage, assert | cross-tree constraint |
| coupling | connection usage, interface def | 대응 없음 |
| 변수와 select | attribute와 variant 선택 조건 | attribute, feature attribute |

SysML v2로 내보내기는 구조와 변이는 가능하나 가지치기 규칙은 제약으로만 표현된다. feature model로 내보내기는 결합 정보를 잃는다. 두 변환 모두 단방향이며, 가져오기는 손실이 있다는 점을 전제로 설계해야 한다.

## 8. 미해결 쟁점

1. 재귀 구조: strict hierarchy 공리는 재귀 합성을 막는다. 트리형 네트워크처럼 재귀가 자연스러운 도메인은 깊이 제한이 있는 명시적 펼침으로 다루어야 하는데, 표현 방법을 아직 정하지 않았다.
2. 동적 구조: 실행 중 재가지치기를 Observer로 두었지만, 실행 중인 모델의 상태를 보존하며 구조를 바꾸는 문제(DS-DEVS 수준)는 백엔드 의존적이다. 초기 단계에서는 "중단, 재생성, 재시작"으로 제한한다.
3. 표현식 언어의 범위: 선언적 AST가 산술 연산을 포함하지 않는다. 유도 속성(P10)에 산술이 필요하면 call로 등록 함수를 쓰거나 AST에 산술 노드를 추가해야 한다. 추가하면 C++ 평가기도 같이 커진다.
4. 바인딩 계약 검증의 깊이: 생성자 인자 이름과 포트 이름 대조는 가능하지만, 구현체가 실제로 그 포트에서 그 타입의 메시지를 내보내는지는 정적으로 검사할 수 없다. 런타임 검증 훅이 필요하다.
5. 가져오기 범위: SESToPy의 eval 문자열 규칙은 AST로 자동 변환할 수 없는 경우가 많다. 변환기는 단순 비교 식만 바꾸고 나머지는 call로 감싸 사람이 손보게 한다.
