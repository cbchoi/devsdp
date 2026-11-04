# 시뮬레이터 독립적 SES 자료구조 제안

작성일: 2026-11-03

이 문서는 공통 플랫폼의 코어가 보유하는 자료구조를 시뮬레이터와 프로그래밍 언어에 독립적으로 정의한다. 03 문서의 메타모델을 메모리 구조와 직렬화 구조 수준으로 구체화한 것이다. Python 참조 정의는 ses_core/model.py 에 있고, 예시 SES를 적재하여 확인했다.

## 1. 독립성 원칙

| 원칙 | 내용 | 위반 예 |
|---|---|---|
| I1 | 자료구조 어디에도 시뮬레이터 개념(시간 진행, 상태, 이벤트 큐, 스케줄러)을 두지 않는다 | 엔티티에 time_advance 필드를 두는 것 |
| I2 | 구성요소는 이름, 포트, 파라미터 계약으로만 기술한다. 구현체 클래스는 바인딩 계층에만 나타난다 | 엔티티 정의에 Python 클래스 경로를 넣는 것 |
| I3 | 참조는 포인터가 아니라 이름과 경로(문자열)다. 모든 구조가 그대로 직렬화된다 | 노드가 부모 객체를 직접 가리키는 것 |
| I4 | 값은 스칼라(int, float, str, bool)와 그 열거형만 허용한다. 객체 값은 두지 않는다 | 속성 값으로 분포 객체를 넣는 것. 분포는 이름과 스칼라 파라미터로 기술한다 |
| I5 | 시뮬레이터와의 경계는 FPES와 ComponentContract 두 구조다. 빌더는 이 둘만 읽는다 | 빌더가 SES 원문을 읽는 것 |
| I6 | 계층 정보(결합 모델 경계)는 보존하되 선택 사항으로 둔다. 평탄 결합만 받는 백엔드도 같은 FPES를 쓴다 | 계층을 지운 FPES와 보존한 FPES를 따로 두는 것 |
| I7 | 규칙은 데이터(AST)다. 어떤 언어로도 같은 평가 결과를 내야 한다 | 호스트 언어 식 문자열 |

## 2. 식별자와 주소 체계

| 종류 | 형식 | 예 | 용도 |
|---|---|---|---|
| Name | [A-Za-z_][A-Za-z0-9_]* | Buffer | 정의, 포트, 속성, 변수 이름 |
| DefName | Name | PriorityBuffer | 엔티티 정의 식별 (문서 안에서 유일) |
| NodeId | DefName/Name | Buffer/policySpec | 정의 안의 aspect, multi-aspect, specialization 식별 |
| InstancePath | Name(/Name)* | ProcessingSystem/ServerPool/server_0 | PES와 FPES의 인스턴스 식별 |
| PortRef(정의 수준) | part.port 또는 port | Generator.out, in | aspect 안의 결합 끝점. part 없으면 자기 자신(결합 모델 외부 포트) |
| PortRef(인스턴스 수준) | InstancePath.port | ProcessingSystem/Buffer.in | FPES 결합 끝점 |
| AttrPath | InstancePath.attr | ProcessingSystem/Generator.interarrival | 구성 파일의 오버라이드 대상 |
| Template | 자리표시자 포함 문자열 | server_{i}, {part}.in | multi-aspect 복제 시 치환. 허용 자리표시자: {i}, {part}, {next}, {prev}, {n} |

주소는 모두 문자열이다. 메모리 상의 조회 성능은 적재 시 만드는 색인(이름에서 객체로의 사전)으로 해결하고, 색인은 직렬화하지 않는다.

## 3. 자료구조 계층 개관

| 계층 | 구조 | 성격 | 생산자 | 소비자 |
|---|---|---|---|---|
| 타입 | SesDocument | 변이 공간. 사람이 작성 | 모델러, LLM | 검증기, 가지치기 |
| 결정 | Configuration | 변수 값, 명시 결정, 오버라이드 | 실험자 | 가지치기 |
| 기록 | PruningTrace | 결정 열 | 가지치기 | 재현, 설명, 반응형 재가지치기 |
| 인스턴스 | PES | 선택된 구조의 인스턴스 트리 | 가지치기 | 평탄화, 시각화 |
| 경계 | FPES | 리프 인스턴스와 결합 목록 | 평탄화 | 모델 빌더 |
| 경계 | ComponentContract | 리프 정의의 포트와 파라미터 계약 | 코어(SES에서 유도) | 모델 빌더, 모델베이스 작성자, LLM |
| 바인딩 | Binding | 정의에서 구현체로의 매핑 | 개발자 | 모델 빌더 |

타입, 결정, 기록, 인스턴스 계층은 시뮬레이터를 전혀 모른다. 경계 계층은 시뮬레이터를 모르지만 시뮬레이터가 읽도록 설계된다. 바인딩만 특정 백엔드를 안다.

## 4. 타입 계층: SesDocument

표기: 필드 이름, 타입, 필수 여부, 불변식. 타입 표기에서 Map<K, V>는 순서가 보존되는 사전, List<T>는 순서 있는 목록, T? 는 선택 필드다.

### 4.1 SesDocument

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| format_version | str | 예 | 표현 형식 버전. "1.0" |
| name | Name | 예 | 문서 이름 |
| version | str? | | 문서 버전 |
| description | str? | | |
| variables | Map<Name, Variable> | | SES 변수 |
| port_types | Map<Name, PortType> | | 메시지 타입 |
| entities | Map<DefName, EntityDef> | 예 | 정의 테이블 |
| constraints | List<Constraint> | | 선택 제약 |
| experimental_frames | List<FrameAttachment> | | 실험 프레임 참조 |
| metadata | Map<str, Any> | | 코어가 해석하지 않는 확장 영역 |

불변식
- root 가 true 인 EntityDef 가 정확히 하나 있다.
- 모든 EntityRef, extends, 포트 타입 이름, 변수 이름은 문서 안에서 해석된다(댕글링 참조 없음).
- extends 관계에 순환이 없다.
- 펼친 어떤 경로에서도 같은 DefName 이 두 번 나오지 않는다(strict hierarchy).

### 4.2 Variable

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | Name | 예 | |
| type | ScalarType | 예 | int, float, str, bool, enum |
| default | Value? | | |
| domain | Domain? | | Range{min, max} 또는 EnumSet{values} |
| doc | str? | | |

### 4.3 PortType

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | Name | 예 | |
| fields | Map<Name, ScalarType> | | 메시지 필드. 비어 있으면 신호(signal) |

### 4.4 EntityDef

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | DefName | 예 | |
| root | bool | | 기본 false |
| extends | DefName? | | specialization 부모. 포트와 속성을 상속 |
| stereotype | Stereotype? | | atomic, coupled, abstract, frame. 없으면 구조로 추론 |
| ports | Map<Name, Port> | | 자기 선언 포트. 상속 포트는 포함하지 않음 |
| attributes | Map<Name, Attribute> | | 자기 선언 속성 |
| aspects | Map<Name, Aspect> | | |
| multi_aspects | Map<Name, MultiAspect> | | |
| specializations | Map<Name, Specialization> | | |
| metadata | Map<str, Any> | | |

불변식
- aspects, multi_aspects, specializations 의 키는 셋을 합쳐 유일하다(valid brothers).
- 상속 포트와 같은 이름의 포트를 다시 선언하면 타입과 방향이 같아야 한다.
- stereotype 이 atomic 이면 aspects 와 multi_aspects 가 비어 있다.
- stereotype 이 abstract 이면 PES 리프로 남을 수 없다.

유도 연산(저장하지 않음): all_ports(상속 포함), all_attributes(상속 포함), is_leaf(분해가 없음).

### 4.5 Port, Attribute

Port

| 필드 | 타입 | 필수 |
|---|---|---|
| name | Name | 예 |
| type | Name (PortType) | 예 |
| direction | in 또는 out | 예 |

Attribute

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | Name | 예 | |
| type | ScalarType | 예 | |
| default | Value? | | |
| unit | str? | | 단위 문자열. 검증하지 않고 전달만 한다 |
| expr | Expr? | | 변수에서 유도되는 값. default 와 동시 지정 시 expr 우선 |
| values | List<Value>? | | enum 타입의 허용 값 |

### 4.6 Aspect

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | Name | 예 | |
| parts | List<PartRef> | 예 | 구성 부분 |
| couplings | List<Coupling> | | 부분 사이, 부분과 외부 포트 사이 결합 |
| rule | Expr? | | 참이면 이 aspect 선택 |
| priority | int? | | 형제 aspect 사이 자동 선택 순서. 작을수록 우선 |

PartRef

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| def | DefName | 예 | 참조하는 정의 |
| alias | Name? | | 부분 이름. 없으면 def 와 같다. 같은 정의를 두 번 쓰면 alias 가 필요하다 |

불변식: parts 의 부분 이름(alias 또는 def)이 유일하다.

### 4.7 MultiAspect

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | Name | 예 | |
| part | PartRef | 예 | 복제 대상 |
| cardinality | Cardinality | 예 | Fixed{n}, Var{name}, Range{min, max} |
| naming | Template | | 복제본 이름. 기본 "{part}_{i}" |
| pattern | CouplingPattern? | | 복제본 결합 생성 규칙 |
| rule | Expr? | | |
| priority | int? | | |

CouplingPattern

| 필드 | 타입 | 설명 |
|---|---|---|
| kind | fan_out_fan_in, chain, ring, broadcast, custom | |
| fan_out | List<Coupling> | 외부 in 에서 각 복제본으로. {part} 자리표시자 |
| fan_in | List<Coupling> | 각 복제본에서 외부 out 으로 |
| between | List<Coupling> | 복제본 사이. {i}, {next}, {prev} |
| custom | List<Coupling> | kind 가 custom 일 때 전체 목록 |

### 4.8 Specialization

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| name | Name | 예 | |
| alternatives | List<DefName> | 예 | 각 대안은 이 정의를 extends 해야 한다(검증기가 확인) |
| select | SelectRule? | | 조건부 선택 |
| default | DefName? | | 규칙과 명시 결정이 없을 때 |

SelectRule: {when: Expr, then: DefName, else: DefName 또는 SelectRule}. 중첩으로 다중 분기를 표현한다.

### 4.9 Coupling

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| from | PortRef | 예 | 출발. "part.port" 또는 "port"(외부 입력 포트) |
| to | PortRef | 예 | 도착. "part.port" 또는 "port"(외부 출력 포트) |

PortRef 는 저장 시 문자열이고 메모리에서는 {part: Name?, port: Name} 두 필드로 분해한다. part 가 없으면 결합 모델 자신의 포트다.

불변식(검증기): 출발 포트는 부분의 out 또는 자신의 in, 도착 포트는 부분의 in 또는 자신의 out. 양 끝의 PortType 이 같다.

### 4.10 Expr (표현식 AST)

합 타입(sum type)이다. 저장 형식은 한 개의 키로 종류를 구분하는 JSON 객체다.

| 노드 | 필드 | 평가 |
|---|---|---|
| Var | name | 환경에서 변수 값 |
| Const | value | 상수 |
| Compare | op(eq, ne, lt, le, gt, ge, in), left: Expr, right: Expr | 비교 |
| And | items: List<Expr> | 모두 참 |
| Or | items: List<Expr> | 하나 이상 참 |
| Not | item: Expr | 부정 |
| Selected | node: NodeId, choice: Name | 가지치기 중 해당 지점이 그 대안을 골랐는가 |
| Call | fn: Name, args: List<Expr> | 이름으로 등록된 함수 호출 |

저장 형식에서는 {var: x, eq: 3} 처럼 Compare 를 축약한다(스키마 참조). 적재기가 축약형을 위 AST 로 펼친다.

평가 환경(Env): 변수 값 사전, 지금까지의 결정 사전, 함수 레지스트리, 현재 인스턴스 경로, 부모와 자식 인스턴스 참조, 현재 복제 인덱스(multi-aspect 안에서 {i}). 부모와 자식 참조는 Folkerts, Pawletta, Durak (2023)의 SESfcn 암묵 변수 PARENT, CHILDREN과 복제 인덱스 밑줄 속성이 하던 역할을 대신한다.

### 4.11 Constraint

| 필드 | 타입 | 설명 |
|---|---|---|
| name | Name | |
| when | Expr? | 없으면 항상 적용 |
| require | Expr? | when 이 참일 때 반드시 참 |
| forbid | Expr? | when 이 참일 때 반드시 거짓 |

## 5. 결정 계층: Configuration

| 필드 | 타입 | 설명 |
|---|---|---|
| name | Name | 구성 이름 |
| ses_ref | {name, version} | 대상 SES |
| values | Map<Name, Value> | 변수 값 |
| decisions | List<Decision> | 명시 결정 |
| overrides | List<Override> | 속성 값 재정의. {at: AttrPath, value} |

Decision 합 타입

| 종류 | 필드 | 설명 |
|---|---|---|
| AspectChoice | at: InstancePath 또는 NodeId, choose: Name | 형제 aspect 가운데 선택 |
| SpecChoice | at, choose: DefName | 대안 선택 |
| CardinalityChoice | at, n: int | 복제 개수 |
| VarAssign | name, value | values 와 동일. 기록 계층과 형식을 맞추기 위해 둔다 |

at 이 NodeId(정의 수준)이면 그 정의가 나타나는 모든 인스턴스에 적용되고, InstancePath(인스턴스 수준)이면 그 인스턴스에만 적용된다. 둘 다 있으면 인스턴스 수준이 우선한다.

## 6. 기록 계층: PruningTrace

| 필드 | 타입 | 설명 |
|---|---|---|
| ses_ref, config_ref | | |
| steps | List<TraceStep> | 결정 순서 |
| hash | str | steps 의 정규화 직렬화 해시. PES 와 FPES 가 이 값을 가진다 |

TraceStep

| 필드 | 타입 | 설명 |
|---|---|---|
| seq | int | 순번 |
| point | DecisionPoint {kind, path, options} | 결정 지점 |
| decision | Decision | 내려진 결정 |
| strategy | Name | 결정한 전략 이름 |
| reason | str | 사람이 읽는 근거(규칙 설명 등) |

같은 SES, 같은 Configuration, 같은 전략 목록이면 같은 hash 가 나와야 한다(결정성). 반응형 재가지치기는 특정 seq 이후를 버리고 다시 쌓는다.

## 7. 인스턴스 계층: PES

| 필드 | 타입 | 설명 |
|---|---|---|
| ses_ref, config_ref, trace_hash | | |
| root | InstanceNode | |

InstanceNode

| 필드 | 타입 | 설명 |
|---|---|---|
| path | InstancePath | 유일 식별자 |
| name | Name | 부분 이름(복제본은 치환된 이름) |
| declared_def | DefName | aspect 의 parts 에 적힌 정의 |
| resolved_def | DefName | specialization 을 거쳐 확정된 정의. 분류가 없으면 declared_def 와 같다 |
| via | List<Name> | 거친 specialization 이름들(중첩 가능) |
| decomposition | Name? | 선택된 aspect 또는 multi_aspect 이름. 리프면 없음 |
| values | Map<Name, Value> | 확정된 속성 값(상속 포함, 오버라이드 반영) |
| children | List<InstanceNode> | |
| couplings | List<Coupling> | 이 노드의 분해 안에서 확정된 결합(자리표시자 치환 완료). 정의 수준 PortRef 형식 유지 |

PES 는 트리이며 모든 변이성이 사라진 상태다. 규칙, 제약, 변수는 없다. 같은 정의(resolved_def)의 인스턴스가 서로 다른 값과 다른 하위 구조를 가질 수 있다. 즉 uniformity 공리는 타입 계층(정의 테이블)에서만 성립하고 PES 에서는 성립하지 않는다. Folkerts, Pawletta, Durak (2023)이 PES 에서 uniformity 를 완화한 것과 같은 결정이며, 플랫폼은 이를 InstancePath 로 자연스럽게 표현한다.

## 8. 경계 계층: FPES 와 ComponentContract

### 8.1 FPES

| 필드 | 타입 | 설명 |
|---|---|---|
| ses_ref, config_ref, trace_hash | | 출처 |
| instances | List<LeafInstance> | 리프 인스턴스. 실행 구성요소 하나에 대응 |
| couplings | List<ResolvedCoupling> | 리프 사이 결합(결합 모델 경계를 통과한 결과) |
| hierarchy | List<CoupledNode> | 선택. 결합 모델 경계 보존 정보 |

LeafInstance

| 필드 | 타입 | 설명 |
|---|---|---|
| path | InstancePath | |
| def | DefName | resolved_def |
| values | Map<Name, Value> | 파라미터 값 |

ResolvedCoupling: {from: {path, port}, to: {path, port}}. 양 끝 모두 리프다.

CoupledNode

| 필드 | 타입 | 설명 |
|---|---|---|
| path | InstancePath | 결합 모델 인스턴스 |
| children | List<Name> | 직계 자식 이름 |
| ports | Map<Name, Port> | 결합 모델의 외부 포트 |
| eic | List<{from_port, to: {child, port}}> | 외부 입력 결합 |
| eoc | List<{from: {child, port}, to_port}> | 외부 출력 결합 |
| ic | List<{from: {child, port}, to: {child, port}}> | 내부 결합 |

hierarchy 가 있으면 couplings 는 hierarchy 의 eic, eoc, ic 를 리프까지 추적한 결과와 일치해야 한다. 빌더는 둘 중 하나만 쓰면 된다. 계층을 보존하는 DEVS 시뮬레이터는 hierarchy 를, 평탄 조립만 하는 도구는 couplings 를 쓴다.

### 8.2 ComponentContract

SES 에서 유도되는 리프 정의의 계약이다. 모델베이스 작성자와 LLM 이 구현체를 만들 때 보는 유일한 명세다.

| 필드 | 타입 | 설명 |
|---|---|---|
| def | DefName | |
| ancestors | List<DefName> | extends 사슬 |
| ports | Map<Name, {type: PortType(펼침), direction}> | 상속 포함 |
| parameters | Map<Name, {type, default, unit, values}> | 상속 포함 속성 |
| doc | str? | |

계약은 시뮬레이터 개념을 포함하지 않는다. "포트 in 으로 Job 메시지가 들어오고 out 으로 Job 을 내보내며 service_time 파라미터를 받는다"까지가 계약이고, 그것이 DEVS 원자 모델인지 FMU 인지는 바인딩이 정한다.

## 9. 바인딩 계층: Binding

| 필드 | 타입 | 설명 |
|---|---|---|
| target | Name | 백엔드 이름 |
| ses_ref | | |
| defaults | Map<str, Any> | 백엔드별 기본값 |
| map | Map<DefName, Implementation> | |
| coupled_builder | Name? | 결합 모델 생성 방식 |

Implementation 은 백엔드마다 다르다. 코어는 DefName 키와 param_map(계약 파라미터 이름에서 구현체 인자 이름으로의 사전)만 검사하고 나머지는 빌더에 넘긴다. 예: Python 백엔드는 {module, class, ctor_args}, C++ 백엔드는 {header, class, factory}, FMI 는 {fmu_path, parameter_map}.

## 10. 시뮬레이터별 대응

FPES 와 ComponentContract 가 각 시뮬레이터 개념에 어떻게 대응하는지 정리한다. 이 표가 "시뮬레이터 독립"의 근거다.

| 코어 구조 | DEVS (pyevsim, evsimpp, xDEVS) | FMI, SSP | SysML v2 | 그래프 저장소(GO-DEVS 류) |
|---|---|---|---|---|
| LeafInstance | 원자 모델 인스턴스 | FMU 인스턴스 | part usage | 노드 |
| LeafInstance.values | 생성자 인자 또는 초기 상태 파라미터 | 파라미터 값 | attribute 값 | 노드 속성 |
| CoupledNode | 결합 모델 | SSP System | part usage 와 nested parts | 하위 그래프 |
| CoupledNode.eic, eoc, ic | EIC, EOC, IC | SSP Connection | connection usage | 간선 |
| ResolvedCoupling | 평탄 결합 모델의 IC | SSP Connection(평탄) | connection usage | 간선 |
| Port | 입출력 포트 | ScalarVariable 또는 Connector | port usage | 노드 포트 |
| PortType | 메시지 클래스 | 변수 타입 | port def, item def | 포트 타입 라벨 |
| ComponentContract | 원자 모델 클래스 시그니처 | FMU modelDescription | part def | 노드 타입 스키마 |

## 11. 언어 중립 정의와 참조 구현

- 직렬화: 정준 YAML/JSON. 스키마는 schema/ses.schema.json. Configuration, PES, FPES, Binding 스키마는 같은 방식으로 추가한다(1단계 과제).
- 메모리 모델: 각 언어에서 불변 값 객체(Python dataclass frozen, C++ struct const 멤버)로 두고, 조회 색인은 별도 객체에 둔다.
- Python 참조 정의: ses_core/model.py. 자료구조만 있고 가지치기 논리는 없다. ses_core/loader.py 가 정준 YAML 을 적재하고 참조 무결성을 검사한다.
- C++ 대응: 같은 필드 이름의 struct 와 std::map, std::vector, std::optional, std::variant(Expr, Cardinality, Decision)로 옮긴다. JSON 적재는 nlohmann/json 을 가정한다. evsimpp 빌더는 FPES 와 Binding 만 읽으면 되므로 C++ 쪽에는 FPES, ComponentContract, Binding 세 구조만 먼저 구현해도 된다.

## 12. 선택 근거와 대안 비교

| 결정 | 채택 | 대안 | 채택 이유 |
|---|---|---|---|
| 참조 방식 | 이름 문자열 | 객체 포인터 | 직렬화와 언어 독립. 색인으로 성능 보완 |
| 정의와 인스턴스 | 분리(EntityDef 와 InstanceNode) | 단일 노드 클래스 | uniformity 보장, 파일 크기, MetaSES 와 일치 |
| 결합 저장 위치 | aspect 안의 목록 | 문서 전역 간선 목록 | 결합은 분해에 종속된다. 전역 질의는 색인으로 제공 |
| 경계 구조 | FPES 하나에 couplings 와 hierarchy 병행 | 평탄 FPES 와 계층 FPES 분리 | 백엔드가 고르게 하고 변환기를 하나로 유지 |
| 규칙 | AST 객체 | 식 문자열 | 안전성, 다중 언어 평가, 정적 검사 |
| 복제본 결합 | 패턴 객체 | 규칙 코드 | 읽기 쉬움, 대규모 복제 선언화 |
| 값 타입 | 스칼라와 열거형만 | 임의 객체 | 모든 백엔드로 전달 가능 |
