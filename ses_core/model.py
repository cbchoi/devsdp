"""SES 코어 자료구조 (docs/ses-platform/04_data_structures.md 의 참조 구현).

원칙
- 시뮬레이터 개념을 두지 않는다.
- 참조는 이름 문자열이다. 객체 포인터를 저장하지 않는다.
- 값은 스칼라와 열거형만 허용한다.
- 모든 구조는 불변 값 객체이며 그대로 직렬화된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Union

Value = Union[int, float, str, bool]
Name = str
DefName = str
InstancePath = str


class ScalarType(str, Enum):
    INT = "int"
    FLOAT = "float"
    STR = "str"
    BOOL = "bool"
    ENUM = "enum"


class Direction(str, Enum):
    IN = "in"
    OUT = "out"


class Stereotype(str, Enum):
    ATOMIC = "atomic"
    COUPLED = "coupled"
    ABSTRACT = "abstract"
    FRAME = "frame"


# ---------------------------------------------------------------------------
# 표현식 AST (합 타입)
# ---------------------------------------------------------------------------

class Expr:
    """표현식 노드의 공통 기반. 평가 논리는 ses_ops 에 둔다."""


@dataclass(frozen=True)
class Var(Expr):
    name: Name


@dataclass(frozen=True)
class Const(Expr):
    value: Any


@dataclass(frozen=True)
class Compare(Expr):
    op: str                      # eq, ne, lt, le, gt, ge, in
    left: Expr
    right: Expr


@dataclass(frozen=True)
class And(Expr):
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Or(Expr):
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Not(Expr):
    item: Expr


@dataclass(frozen=True)
class Selected(Expr):
    node: str                    # NodeId. 예: Buffer/policySpec
    choice: Name


@dataclass(frozen=True)
class Call(Expr):
    fn: Name
    args: tuple[Expr, ...] = ()


# ---------------------------------------------------------------------------
# 타입 계층
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Range:
    min: float
    max: float


@dataclass(frozen=True)
class EnumSet:
    values: tuple[Value, ...]


@dataclass(frozen=True)
class Variable:
    name: Name
    type: ScalarType
    default: Optional[Value] = None
    domain: Union[Range, EnumSet, None] = None
    doc: Optional[str] = None


@dataclass(frozen=True)
class PortType:
    name: Name
    fields: Mapping[Name, ScalarType] = field(default_factory=dict)
    doc: Optional[str] = None


@dataclass(frozen=True)
class Port:
    name: Name
    type: Name                   # PortType 이름
    direction: Direction
    doc: Optional[str] = None


@dataclass(frozen=True)
class Attribute:
    name: Name
    type: ScalarType
    default: Optional[Value] = None
    unit: Optional[str] = None
    expr: Optional[Expr] = None
    values: Optional[tuple[Value, ...]] = None
    doc: Optional[str] = None


@dataclass(frozen=True)
class PortRef:
    """정의 수준 결합 끝점. part 가 None 이면 결합 모델 자신의 포트."""
    port: Name
    part: Optional[Name] = None

    @staticmethod
    def parse(text: str) -> "PortRef":
        if "." in text:
            part, port = text.rsplit(".", 1)
            return PortRef(port=port, part=part)
        return PortRef(port=text)

    def __str__(self) -> str:
        return self.port if self.part is None else f"{self.part}.{self.port}"


@dataclass(frozen=True)
class Coupling:
    src: PortRef                 # 저장 형식의 from
    dst: PortRef                 # 저장 형식의 to
    doc: Optional[str] = None


@dataclass(frozen=True)
class PartRef:
    def_name: DefName
    alias: Optional[Name] = None

    @property
    def part_name(self) -> Name:
        return self.alias or self.def_name


@dataclass(frozen=True)
class Aspect:
    name: Name
    parts: tuple[PartRef, ...]
    couplings: tuple[Coupling, ...] = ()
    rule: Optional[Expr] = None
    priority: Optional[int] = None
    doc: Optional[str] = None


@dataclass(frozen=True)
class Fixed:
    n: int


@dataclass(frozen=True)
class VarCard:
    var: Name


@dataclass(frozen=True)
class RangeCard:
    min: int
    max: Optional[int] = None


Cardinality = Union[Fixed, VarCard, RangeCard]


class PatternKind(str, Enum):
    FAN_OUT_FAN_IN = "fan_out_fan_in"
    CHAIN = "chain"
    RING = "ring"
    BROADCAST = "broadcast"
    CUSTOM = "custom"


@dataclass(frozen=True)
class CouplingPattern:
    kind: PatternKind
    fan_out: tuple[Coupling, ...] = ()
    fan_in: tuple[Coupling, ...] = ()
    between: tuple[Coupling, ...] = ()
    custom: tuple[Coupling, ...] = ()


@dataclass(frozen=True)
class MultiAspect:
    name: Name
    part: PartRef
    cardinality: Cardinality
    naming: str = "{part}_{i}"
    pattern: Optional[CouplingPattern] = None
    rule: Optional[Expr] = None
    priority: Optional[int] = None
    doc: Optional[str] = None


@dataclass(frozen=True)
class SelectRule:
    when: Expr
    then: DefName
    otherwise: Union[DefName, "SelectRule", None] = None   # 저장 형식의 else


@dataclass(frozen=True)
class Specialization:
    name: Name
    alternatives: tuple[DefName, ...]
    select: Optional[SelectRule] = None
    default: Optional[DefName] = None
    doc: Optional[str] = None


@dataclass(frozen=True)
class EntityDef:
    name: DefName
    root: bool = False
    extends: Optional[DefName] = None
    stereotype: Optional[Stereotype] = None
    ports: Mapping[Name, Port] = field(default_factory=dict)
    attributes: Mapping[Name, Attribute] = field(default_factory=dict)
    aspects: Mapping[Name, Aspect] = field(default_factory=dict)
    multi_aspects: Mapping[Name, MultiAspect] = field(default_factory=dict)
    specializations: Mapping[Name, Specialization] = field(default_factory=dict)
    doc: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_leaf(self) -> bool:
        return not self.aspects and not self.multi_aspects

    @property
    def decomposition_names(self) -> tuple[Name, ...]:
        return tuple(self.aspects) + tuple(self.multi_aspects) + tuple(self.specializations)


@dataclass(frozen=True)
class Constraint:
    name: Name
    when: Optional[Expr] = None
    require: Optional[Expr] = None
    forbid: Optional[Expr] = None
    doc: Optional[str] = None


@dataclass(frozen=True)
class FrameAttachment:
    ref: str
    attach_to: Optional[DefName] = None


@dataclass(frozen=True)
class SesDocument:
    format_version: str
    name: Name
    entities: Mapping[DefName, EntityDef]
    version: Optional[str] = None
    description: Optional[str] = None
    variables: Mapping[Name, Variable] = field(default_factory=dict)
    port_types: Mapping[Name, PortType] = field(default_factory=dict)
    constraints: tuple[Constraint, ...] = ()
    experimental_frames: tuple[FrameAttachment, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def root(self) -> EntityDef:
        roots = [e for e in self.entities.values() if e.root]
        if len(roots) != 1:
            raise ValueError(f"root 엔티티는 정확히 하나여야 한다. 현재 {len(roots)}개")
        return roots[0]

    # 유도 연산 (상속 포함). 저장하지 않는다.
    def ancestors(self, def_name: DefName) -> tuple[DefName, ...]:
        chain: list[DefName] = []
        cur = self.entities[def_name].extends
        while cur is not None:
            if cur in chain:
                raise ValueError(f"extends 순환: {def_name}")
            chain.append(cur)
            cur = self.entities[cur].extends
        return tuple(chain)

    def all_ports(self, def_name: DefName) -> dict[Name, Port]:
        merged: dict[Name, Port] = {}
        for anc in reversed(self.ancestors(def_name)):
            merged.update(self.entities[anc].ports)
        merged.update(self.entities[def_name].ports)
        return merged

    def all_attributes(self, def_name: DefName) -> dict[Name, Attribute]:
        merged: dict[Name, Attribute] = {}
        for anc in reversed(self.ancestors(def_name)):
            merged.update(self.entities[anc].attributes)
        merged.update(self.entities[def_name].attributes)
        return merged

    def contract(self, def_name: DefName) -> "ComponentContract":
        ports = self.all_ports(def_name)
        return ComponentContract(
            def_name=def_name,
            ancestors=self.ancestors(def_name),
            ports={n: ContractPort(n, self.port_types[p.type], p.direction) for n, p in ports.items()},
            parameters={n: ContractParam(n, a.type, a.default, a.unit, a.values)
                        for n, a in self.all_attributes(def_name).items()},
            doc=self.entities[def_name].doc,
        )


# ---------------------------------------------------------------------------
# 결정 계층
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SesRef:
    name: Name
    version: Optional[str] = None


@dataclass(frozen=True)
class AspectChoice:
    at: str                      # InstancePath 또는 NodeId
    choose: Name


@dataclass(frozen=True)
class SpecChoice:
    at: str
    choose: DefName


@dataclass(frozen=True)
class CardinalityChoice:
    at: str
    n: int


@dataclass(frozen=True)
class VarAssign:
    name: Name
    value: Value


Decision = Union[AspectChoice, SpecChoice, CardinalityChoice, VarAssign]


@dataclass(frozen=True)
class Override:
    at: str                      # AttrPath
    value: Value


@dataclass(frozen=True)
class Configuration:
    name: Name
    ses_ref: SesRef
    values: Mapping[Name, Value] = field(default_factory=dict)
    decisions: tuple[Decision, ...] = ()
    overrides: tuple[Override, ...] = ()


# ---------------------------------------------------------------------------
# 기록 계층
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionPoint:
    kind: str                    # variable, aspect, specialization, cardinality
    path: str
    options: tuple[Any, ...]


@dataclass(frozen=True)
class TraceStep:
    seq: int
    point: DecisionPoint
    decision: Decision
    strategy: Name
    reason: str


@dataclass(frozen=True)
class PruningTrace:
    ses_ref: SesRef
    config_ref: Name
    steps: tuple[TraceStep, ...]
    hash: str


# ---------------------------------------------------------------------------
# 인스턴스 계층
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstanceNode:
    path: InstancePath
    name: Name
    declared_def: DefName
    resolved_def: DefName
    via: tuple[Name, ...] = ()
    decomposition: Optional[Name] = None
    values: Mapping[Name, Value] = field(default_factory=dict)
    children: tuple["InstanceNode", ...] = ()
    couplings: tuple[Coupling, ...] = ()

    @property
    def is_leaf(self) -> bool:
        return self.decomposition is None


@dataclass(frozen=True)
class PES:
    ses_ref: SesRef
    config_ref: Name
    trace_hash: str
    root: InstanceNode


# ---------------------------------------------------------------------------
# 경계 계층: FPES 와 ComponentContract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LeafInstance:
    path: InstancePath
    def_name: DefName
    values: Mapping[Name, Value] = field(default_factory=dict)


@dataclass(frozen=True)
class Endpoint:
    path: InstancePath
    port: Name


@dataclass(frozen=True)
class ResolvedCoupling:
    src: Endpoint
    dst: Endpoint


@dataclass(frozen=True)
class ChildPort:
    child: Name
    port: Name


@dataclass(frozen=True)
class ExternalInputCoupling:
    from_port: Name
    to: ChildPort


@dataclass(frozen=True)
class ExternalOutputCoupling:
    src: ChildPort
    to_port: Name


@dataclass(frozen=True)
class InternalCoupling:
    src: ChildPort
    dst: ChildPort


@dataclass(frozen=True)
class CoupledNode:
    path: InstancePath
    children: tuple[Name, ...]
    ports: Mapping[Name, Port] = field(default_factory=dict)
    eic: tuple[ExternalInputCoupling, ...] = ()
    eoc: tuple[ExternalOutputCoupling, ...] = ()
    ic: tuple[InternalCoupling, ...] = ()


@dataclass(frozen=True)
class FPES:
    ses_ref: SesRef
    config_ref: Name
    trace_hash: str
    instances: tuple[LeafInstance, ...]
    couplings: tuple[ResolvedCoupling, ...]
    hierarchy: tuple[CoupledNode, ...] = ()


@dataclass(frozen=True)
class ContractPort:
    name: Name
    type: PortType               # 펼친 포트 타입
    direction: Direction


@dataclass(frozen=True)
class ContractParam:
    name: Name
    type: ScalarType
    default: Optional[Value] = None
    unit: Optional[str] = None
    values: Optional[tuple[Value, ...]] = None


@dataclass(frozen=True)
class ComponentContract:
    """리프 정의의 시뮬레이터 독립적 계약. 모델베이스 구현체가 만족해야 하는 전부."""
    def_name: DefName
    ancestors: tuple[DefName, ...]
    ports: Mapping[Name, ContractPort]
    parameters: Mapping[Name, ContractParam]
    doc: Optional[str] = None


# ---------------------------------------------------------------------------
# 바인딩 계층
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Implementation:
    """백엔드별 구현체 기술. 코어는 param_map 만 해석하고 extra 는 빌더에 넘긴다."""
    param_map: Mapping[Name, str] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Binding:
    target: Name
    ses_ref: SesRef
    map: Mapping[DefName, Implementation]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    coupled_builder: Optional[Name] = None


__all__ = [n for n in dir() if not n.startswith("_") and n not in {
    "annotations", "dataclass", "field", "Enum", "Any", "Mapping", "Optional", "Sequence", "Union"}]
