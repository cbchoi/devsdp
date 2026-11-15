"""진단: 문서의 문제를 예외가 아니라 자료로 보고한다 (docs/ses-platform/13_editor_data_model.md).

편집기는 틀린 문서를 열어 둔 채로 일한다. 그래서 검사는 실패하지 않고 진단의 목록을
돌려준다. 진단은 글자가 아니라 편집 모델의 요소를 가리킨다.

진단은 두 범위로 나뉜다.
- 문서 범위(check_document): 변이를 세지 않고 알 수 있는 것. 끊어진 참조, 뿌리의 수,
  이름, extends, 프로파일에 맞지 않는 유형과 필드. 고칠 때마다 바로 계산할 수 있다.
- 족 범위(analyze): 변이를 열거해야 알 수 있는 것. 어떤 선택 아래에서 무엇이 깨지는가.
  펼친 나무의 위반을 문서의 요소로 되돌리고, 요소마다 모아 해당 변이의 수, 그 가운데
  하나를 재현하는 결정 집합(증거), 문제를 일으키기에 충분한 결정들(원인)을 붙인다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .algebra import ENT, SES, AlgebraError, count_variants, reduce, restrict, sem
from .decisions import (ChoicePoint, DecisionSet, _variable_choice, choice_table, excluded, family,
                        witness)
from .edit import IDENTIFIER, EditError, Model, Ref, TYPES, to_dict
from .extension import Layered, violations
from .profile import _TYPES, Profile
from .skeleton import members

_STEREOTYPES = ("atomic", "coupled", "abstract", "frame", "void")
_SCOPE = ("aspects", "multi_aspects", "specializations")
PROFILE_CODES = ("T1", "F1", "F3", "L0", "L2", "T2")        # 문서 범위에서도 판정하는 프로파일 위반


@dataclass(frozen=True)
class Diagnostic:
    severity: str                       # error, warning, info
    code: str
    message: str
    element: Optional[str] = None       # 편집 모델의 요소 식별자
    address: Optional[str] = None       # 그 요소의 주소. 파일에 남길 때 쓴다
    path: tuple = ()                    # 요소 안의 속성 경로. 예: ("fields", "시수")
    related: tuple = ()                 # 관련된 다른 요소
    scope: str = "document"             # document 또는 family
    layer: Optional[str] = None         # 족 범위 위반의 계층: core 또는 확장 이름
    blocking: bool = False              # 이 문제가 있으면 변이 분석을 할 수 없다
    affected: Optional[tuple] = None    # (해당 변이 수, 전체 변이 수)
    witness: Optional[dict] = None      # 문제가 생기는 변이 하나를 재현하는 결정 집합
    cause: Optional[dict] = None        # 이 결정들을 따르는 변이는 모두 이 문제를 가진다
    cause_covers: Optional[int] = None  # 원인을 따르는 변이의 수. affected와 같으면 원인이 전부를 설명한다
    data: Optional[Mapping] = None      # 부호마다 정해진 구조화된 세부. 빠른 고침이 쓴다


@dataclass
class Analysis:
    diagnostics: list
    variants: Optional[int] = None      # 제약을 만족하는 변이의 수
    wellformed: Optional[int] = None    # 그 가운데 적격인 변이의 수
    layered: Optional[Layered] = None   # 분석 모델. 선택 지점 표와 가지치기에 다시 쓴다
    domains: dict = field(default_factory=dict)
    table: list = field(default_factory=list)       # 적격 핵을 기준으로 한 선택 지점 표

    @property
    def errors(self) -> list:
        return [d for d in self.diagnostics if d.severity == "error"]

    def of(self, code: str) -> list:
        return [d for d in self.diagnostics if d.code == code]


# ---------------------------------------------------------------------------
# 문서 범위
# ---------------------------------------------------------------------------

def _hashable(x) -> bool:
    try:
        hash(x)
        return True
    except TypeError:
        return False


def _vars(expr):
    """식 안에서 변수 이름이 적힌 곳."""
    if isinstance(expr, dict):
        if "var" in expr:
            yield expr["var"]
        for v in expr.values():
            yield from _vars(v)
    elif isinstance(expr, list):
        for v in expr:
            yield from _vars(v)


def _select_names(rule):
    """선택 규칙의 then과 else에 적힌 대안 이름."""
    while isinstance(rule, dict):
        if "then" in rule:
            yield rule["then"]
        other = rule.get("else")
        if isinstance(other, dict):
            rule = other
        else:
            if "else" in rule:
                yield other
            return


def effective_kind(m: Model, entity_id: str) -> Optional[str]:
    """엔티티의 유형. 자신에게 없으면 extends를 따라 올라가 찾는다."""
    seen = set()
    cur = entity_id
    while cur is not None and cur not in seen:
        seen.add(cur)
        el = m.elements[cur]
        if el.props.get("kind") is not None:
            return el.props["kind"]
        ref = el.props.get("extends")
        cur = ref.target if isinstance(ref, Ref) else None
    return None


def _ancestors(m: Model, entity_id: str) -> tuple:
    """extends 사슬. (조상들, 순환이 있는가)."""
    out, cur = [], entity_id
    while True:
        ref = m.elements[cur].props.get("extends")
        cur = ref.target if isinstance(ref, Ref) else None
        if cur is None:
            return out, False
        if cur == entity_id or cur in out:
            return out, True
        out.append(cur)


def _ports_of(m: Model, entity_id: str) -> dict:
    """엔티티의 포트: extends로 물려받은 것과 자신의 것."""
    merged: dict = {}
    for eid in list(reversed(_ancestors(m, entity_id)[0])) + [entity_id]:
        ports = m.elements[eid].props.get("ports")
        if isinstance(ports, dict):
            merged.update(ports)
    return merged


def _uses(m: Model, entity_id: str) -> list:
    """(쓰는 자리의 요소, 쓰이는 엔티티)의 목록: 부분, 복제 대상, 대안."""
    out = []
    for a in m.kids(entity_id, "aspects"):
        for p in m.kids(a.id, "parts"):
            out.append((p.id, m.resolved(p.props.get("def"))))
    for ma in m.kids(entity_id, "multi_aspects"):
        out.append((ma.id, m.resolved(ma.props.get("part"))))
    for sp in m.kids(entity_id, "specializations"):
        for alt in m.kids(sp.id, "alternatives"):
            out.append((alt.id, m.resolved(alt.props.get("def"))))
    return [(site, el.id) for site, el in out if el is not None]


def check_document(m: Model, profile: Optional[Profile] = None, unused: bool = True) -> list:
    """변이를 세지 않고 알 수 있는 문제. 어떤 상태의 문서에도 예외 없이 답한다."""
    out: list = []
    if m.root is None:
        return [Diagnostic("error", "ROOT", "문서가 없다", blocking=True)]

    def add(severity, code, element, message, path=(), related=(), blocking=None, data=None) -> None:
        out.append(Diagnostic(severity, code, message, element, m.address(element), tuple(path),
                              tuple(related),
                              blocking=(severity == "error") if blocking is None else blocking, data=data))

    def check_names(elements, what) -> None:
        seen: dict = {}
        for el in elements:
            name = el.props.get("name")
            if not isinstance(name, str) or not IDENTIFIER.match(name):
                add("error", "NAME", el.id, f"{what} 이름 {name!r} 이 식별자 규칙에 맞지 않는다", ("name",))
            if _hashable(name):
                seen.setdefault(name, []).append(el.id)
        for name, ids in seen.items():
            for i in ids[1:]:
                add("error", "DUP", i, f"{what} 이름 {name!r} 이 겹친다", ("name",), ids[:1])

    def check_ref(el, prop, what) -> bool:
        ref = el.props.get(prop)
        if isinstance(ref, Ref) and ref.target is None:
            add("error", "REF", el.id, f"{what} {ref.name!r} 이 정의되어 있지 않다", (prop,),
                data={"name": ref.name})
            return False
        return isinstance(ref, Ref)

    doc = m.get(m.root)
    entities = m.kids(doc.id, "entities")
    variables = m.kids(doc.id, "variables")
    var_names = {v.props.get("name") for v in variables if _hashable(v.props.get("name"))}
    if "ses" not in doc.props:
        add("error", "SHAPE", doc.id, "문서에 형식 판 번호(ses)가 없다", ("ses",))
    if not isinstance(doc.props.get("name"), str):
        add("error", "SHAPE", doc.id, "문서에 이름(name)이 없다", ("name",))
    check_names(entities, "엔티티")
    check_names(variables, "변수")

    def check_vars(el, prop, expr) -> None:
        for name in _vars(expr):
            if not _hashable(name) or name not in var_names:
                add("error", "VAR", el.id, f"정의되지 않은 변수 {name!r}", (prop,), data={"name": name})

    def check_couplings(holder, owner, couplings, parts: dict, path: tuple) -> None:
        """결합의 끝점이 가리키는 부분과 포트가 있는가. 포트의 방향과 타입은 적재기가 본다.

        포트와 결합은 요소가 아니라 속성이어서 이름으로 이어져 있다. 부분을 옮기거나
        포트 이름을 바꾸면 여기서 끊어진 곳이 드러난다.
        """
        if not isinstance(couplings, list):
            return
        own = _ports_of(m, owner.id)
        for i, c in enumerate(couplings):
            for end in ("from", "to"):
                text = c.get(end) if isinstance(c, dict) else None
                where = path + (i, end)
                if not isinstance(text, str):
                    add("error", "COUP", holder.id, "결합의 끝점이 없다", where)
                    continue
                part, _, port = text.rpartition(".")
                if not part:
                    if port not in own:
                        add("error", "COUP", holder.id, f"자신의 포트 {port} 가 없다", where,
                            data={"port": port})
                elif part not in parts:
                    add("error", "COUP", holder.id, f"결합이 가리키는 부분 {part} 가 없다", where,
                        data={"part": part, "port": port})
                elif parts[part] is not None and port not in _ports_of(m, parts[part].id):
                    add("error", "COUP", holder.id, f"부분 {part} 에 포트 {port} 가 없다", where,
                        [parts[part].id], data={"part": part, "port": port})

    for v in variables:
        spec = v.props.get("spec")
        if not isinstance(spec, dict) or "type" not in spec:
            add("error", "SHAPE", v.id, "변수에 type 이 없다", ("spec",))
    for i, c in enumerate(doc.props.get("constraints") or []
                          if isinstance(doc.props.get("constraints"), list) else []):
        check_vars(doc, "constraints", c)

    roots = [e for e in entities if e.props.get("root")]
    if not roots:
        add("error", "ROOT", doc.id, "뿌리 엔티티가 없다. 엔티티 하나에 root 를 표시해야 한다")
    for e in roots[1:] if len(roots) > 1 else []:
        add("error", "ROOT", e.id, "뿌리 엔티티가 둘 이상이다", ("root",), [roots[0].id])

    void = {e.id for e in entities if e.props.get("stereotype") == "void"}
    for e in entities:
        name = e.props.get("name")
        stereotype = e.props.get("stereotype")
        if "stereotype" in e.props and stereotype not in _STEREOTYPES:
            add("error", "SHAPE", e.id, f"알 수 없는 stereotype {stereotype!r}", ("stereotype",))
        scope = [x for r in _SCOPE for x in m.kids(e.id, r)]
        check_names(scope, f"{name} 의 분해와 specialization")

        if check_ref(e, "extends", "extends 의 대상"):
            _, cyclic = _ancestors(m, e.id)
            if cyclic:
                add("error", "EXT", e.id, "extends 가 순환한다", ("extends",))

        for a in m.kids(e.id, "aspects"):
            parts = m.kids(a.id, "parts")
            if not parts:
                add("warning", "MISS", a.id, "부분이 없는 aspect")
            labels: dict = {}
            for p in parts:
                if check_ref(p, "def", "부분의 정의"):
                    if p.props["def"].target in void:
                        add("error", "VOID", p.id, "없음 대안은 부분이 될 수 없다", ("def",))
                label = m.label(p.id)
                if _hashable(label):
                    labels.setdefault(label, []).append(p.id)
            for label, ids in labels.items():
                for i in ids[1:]:
                    add("error", "DUP", i, f"부분 이름 {label!r} 이 겹친다. 별칭이 필요하다", (), ids[:1])
            check_vars(a, "rule", a.props.get("rule"))
            check_couplings(a, e, a.props.get("couplings"),
                            {label: m.resolved(m.get(ids[0]).props.get("def")) for label, ids in labels.items()},
                            ("couplings",))

        for ma in m.kids(e.id, "multi_aspects"):
            if "part" not in ma.props:
                add("error", "MISS", ma.id, "복제할 부분이 없다", ("part",))
            elif check_ref(ma, "part", "복제할 부분의 정의") and ma.props["part"].target in void:
                add("error", "VOID", ma.id, "없음 대안은 부분이 될 수 없다", ("part",))
            card = ma.props.get("cardinality")
            if "cardinality" not in ma.props:
                add("error", "MISS", ma.id, "개수가 없다", ("cardinality",))
            elif isinstance(card, bool) or not (isinstance(card, int) or (
                    isinstance(card, dict) and ("var" in card or "min" in card))):
                add("error", "SHAPE", ma.id, "개수는 정수, {var}, {min, max} 가운데 하나다", ("cardinality",))
            check_vars(ma, "cardinality", card)
            check_vars(ma, "rule", ma.props.get("rule"))
            pattern = ma.props.get("couplings")
            if isinstance(pattern, dict):                   # 결합 틀. 복제본은 {part} 또는 별칭으로 가리킨다
                replica = {ma.props.get("alias") or "{part}": m.resolved(ma.props.get("part"))}
                for key in ("fan_out", "fan_in", "custom", "first", "last"):
                    check_couplings(ma, e, pattern.get(key), replica, ("couplings", key))

        for sp in m.kids(e.id, "specializations"):
            alts = m.kids(sp.id, "alternatives")
            if not alts:
                add("error", "MISS", sp.id, "대안이 없는 specialization. 이 엔티티는 어떤 변이에도 나타날 수 없다")
            alt_names: dict = {}
            for alt in alts:
                if check_ref(alt, "def", "대안의 정의"):
                    target = alt.props["def"].target
                    chain, cyclic = _ancestors(m, target)
                    if e.id not in chain and not cyclic:
                        add("error", "EXT", alt.id,
                            f"대안 {m.label(alt.id)} 이 {name} 을 extends 하지 않는다", (), [target])
                label = m.label(alt.id)
                if _hashable(label):
                    alt_names.setdefault(label, []).append(alt.id)
            for label, ids in alt_names.items():
                for i in ids[1:]:
                    add("error", "DUP", i, f"대안 {label!r} 이 겹친다", (), ids[:1])
            if check_ref(sp, "default", "기본 대안"):
                if m.ref_name(sp.props["default"]) not in alt_names:
                    add("error", "SPEC", sp.id, f"기본값 {m.ref_name(sp.props['default'])} 은 대안이 아니다",
                        ("default",))
            select = sp.props.get("select")
            for chosen in _select_names(select):
                if not _hashable(chosen) or chosen not in alt_names:
                    add("error", "SPEC", sp.id, f"선택 규칙의 {chosen!r} 은 대안이 아니다", ("select",))
            rule = select
            while isinstance(rule, dict):
                check_vars(sp, "select", rule.get("when"))
                rule = rule.get("else")

        for l in m.kids(e.id, "links"):
            check_ref(l, "target", "관계의 대상")

        decomposed = bool(scope)
        if stereotype == "atomic" and decomposed:
            add("error", "ATOMIC", e.id, "atomic 인데 분해를 가진다", ("stereotype",))
        if e.id in void:
            if (decomposed or e.props.get("ports") or e.props.get("attributes")
                    or e.props.get("fields") or m.kids(e.id, "links")):
                add("error", "VOID", e.id, "없음 대안은 포트, 속성, 필드, 관계, 분해를 가질 수 없다")
            if e.props.get("root"):
                add("error", "VOID", e.id, "없음 대안은 뿌리가 될 수 없다", ("root",))

    if len(roots) == 1:
        root = roots[0].id
        reached: set = set()

        def walk(eid: str, trail: tuple) -> None:           # strict hierarchy: 경로에서 같은 정의의 반복
            reached.add(eid)                                # 한 번 다 본 정의는 다시 보지 않는다
            for site, target in _uses(m, eid):
                if target in trail + (eid,):
                    chain = "/".join(str(m.elements[x].props.get("name")) for x in trail + (eid, target))
                    add("error", "CYCLE", site, f"정의가 자기 자신을 포함한다: {chain}", (), [target])
                elif target not in reached:
                    walk(target, trail + (eid,))

        try:
            walk(root, ())
        except RecursionError:
            add("error", "DEPTH", doc.id, "포함 관계가 너무 깊어 검사하지 못했다")
        if unused:
            based = set(reached)
            for eid in reached:
                based.update(_ancestors(m, eid)[0])
            for e in entities:
                if e.id not in based:
                    add("warning", "UNUSED", e.id, "뿌리에서 닿지 않는 엔티티")

    if profile is not None:
        _check_profile(m, profile, entities, add)
    elif doc.props.get("profile") is not None:
        add("error", "PROFILE", doc.id,
            f"문서가 프로파일 {doc.props['profile']!r} 을 따른다. 프로파일을 함께 주어야 분석할 수 있다", ("profile",))
    elif any(e.props.get("kind") is not None or e.props.get("fields") or m.kids(e.id, "links")
             for e in entities):
        add("error", "PROFILE", doc.id,
            "분야의 내용(kind, fields, links)이 있는데 문서가 따르는 프로파일이 없다", ("profile",))
    return out


def _check_profile(m: Model, profile: Profile, entities: list, add) -> None:
    """프로파일에 맞지 않는 것 가운데 정의만 보고 알 수 있는 것. 변이 분석을 막지 않는다."""
    doc = m.get(m.root)
    declared = doc.props.get("profile")
    if declared is not None and declared != profile.name:
        add("error", "PROFILE", doc.id,
            f"문서의 프로파일은 {declared!r} 인데 {profile.name!r} 이 주어졌다", ("profile",))
        return
    for e in entities:
        own = e.props.get("kind")
        fields = e.props.get("fields")
        if own is not None and not isinstance(own, str):
            add("error", "SHAPE", e.id, f"유형은 이름이어야 한다: {own!r}", ("kind",))
            continue
        if "fields" in e.props and not isinstance(fields, dict):
            add("error", "SHAPE", e.id, "fields 는 필드 이름에서 값으로 가는 사상이어야 한다", ("fields",))
            continue
        if own is not None and own not in profile.kinds:
            add("error", "T1", e.id, f"프로파일에 없는 유형 {own!r}", ("kind",), blocking=False)
        kind = effective_kind(m, e.id)
        spec = profile.kinds.get(kind) if isinstance(kind, str) else None
        if spec is not None and isinstance(fields, dict):
            for fname, value in fields.items():
                f = spec.fields.get(fname)
                if f is None:
                    add("error", "F1", e.id, f"유형 {kind} 에 없는 필드 {fname}", ("fields", fname), blocking=False)
                elif (not isinstance(value, _TYPES[f.type])
                      or (f.type != "bool" and isinstance(value, bool))):
                    add("error", "F3", e.id, f"필드 {fname} 의 값 {value!r} 이 타입 {f.type} 이 아니다",
                        ("fields", fname), blocking=False)
                elif f.type == "enum" and value not in f.values:
                    add("error", "F3", e.id, f"필드 {fname} 의 값 {value!r} 이 허용 값 {list(f.values)} 에 없다",
                        ("fields", fname), blocking=False)
        for l in m.kids(e.id, "links"):
            ltype = l.props.get("type")
            if not isinstance(ltype, str):
                add("error", "SHAPE", l.id, f"관계의 유형은 이름이어야 한다: {ltype!r}", ("type",))
                continue
            lspec = profile.links.get(ltype)
            if lspec is None:
                add("error", "L0", l.id, f"프로파일에 없는 관계 {ltype!r}", ("type",), blocking=False)
                continue
            if lspec.src and kind is not None and kind not in lspec.src:
                add("error", "L2", l.id, f"유형 {kind} 은 관계 {ltype} 의 출발이 될 수 없다", (), blocking=False)
            target = m.resolved(l.props.get("target"))
            tkind = effective_kind(m, target.id) if target is not None else None
            if lspec.dst and tkind is not None and tkind not in lspec.dst:
                add("error", "L2", l.id, f"관계 {ltype} 의 대상 {m.label(target.id)} 의 유형 {tkind} 이 맞지 않다",
                    ("target",), [target.id], blocking=False)
        if spec is not None and spec.contains is not None:
            for site, target in _uses(m, e.id):
                if m.elements[site].type == "alternative":
                    continue
                ckind = effective_kind(m, target)
                if ckind is not None and ckind not in spec.contains:
                    add("error", "T2", site,
                        f"유형 {kind} 은 유형 {ckind} 인 {m.label(site)} 을 부분으로 가질 수 없다", (), [target],
                        blocking=False)


# ---------------------------------------------------------------------------
# 펼친 나무의 크기
# ---------------------------------------------------------------------------

def unfolded_size(m: Model, cap: int = 10 ** 12) -> int:
    """정의 표를 뿌리에서 펼쳤을 때의 노드 수. 펼치지 않고 센다.

    같은 정의를 여러 곳에서 쓰면 펼친 나무는 문서보다 지수적으로 크다. 두 부분이 같은
    정의를 쓰는 층이 40개면 노드는 2의 40제곱을 넘는다. 분석을 시작하기 전에 크기를
    알아야 편집기가 멈추지 않는다. 막는 오류가 없는 문서에서만 뜻이 있다. cap을 넘으면
    cap을 돌려준다.
    """
    doc = m.get(m.root)
    domains: dict = {}
    for v in m.kids(doc.id, "variables"):
        spec = v.props.get("spec")
        name = v.props.get("name")
        if not isinstance(spec, dict) or not _hashable(name):
            continue
        r = spec.get("range")
        if isinstance(spec.get("values"), list):
            domains[name] = list(spec["values"])
        elif isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r):
            domains[name] = list(range(r[0], r[1] + 1))
        elif spec.get("type") == "bool":
            domains[name] = [True, False]

    def counts(card) -> list:
        if isinstance(card, int) and not isinstance(card, bool):
            return [card]
        if isinstance(card, dict):
            if "var" in card:
                return [n for n in domains.get(card["var"], []) if isinstance(n, int)] \
                    if _hashable(card["var"]) else []
            lo, hi = card.get("min"), card.get("max")
            if isinstance(lo, int) and isinstance(hi, int):
                return list(range(lo, hi + 1))
        return []

    memo: dict = {}

    def size(eid: str, trail: tuple) -> int:
        if eid in memo:
            return memo[eid]
        if eid in trail:
            return cap
        deeper = trail + (eid,)
        total = 1
        for a in m.kids(eid, "aspects"):
            total += 1 + sum(size(t.id, deeper) for p in m.kids(a.id, "parts")
                             for t in [m.resolved(p.props.get("def"))] if t is not None)
        for ma in m.kids(eid, "multi_aspects"):
            t = m.resolved(ma.props.get("part"))
            each = size(t.id, deeper) if t is not None else 0
            total += sum(1 + n * each for n in counts(ma.props.get("cardinality")))
        for sp in m.kids(eid, "specializations"):
            total += 1 + sum(size(t.id, deeper) for o in m.kids(sp.id, "alternatives")
                             for t in [m.resolved(o.props.get("def"))] if t is not None)
        memo[eid] = min(total, cap)
        return memo[eid]

    roots = [e.id for e in m.kids(doc.id, "entities") if e.props.get("root")]
    if not roots:
        return 0
    return min(size(roots[0], ()) + sum(1 + len(d) for d in domains.values()), cap)


# ---------------------------------------------------------------------------
# 펼친 나무에서 문서의 요소로
# ---------------------------------------------------------------------------

def provenance(m: Model, T, path: tuple, by_name: Optional[Mapping] = None) -> tuple:
    """펼친 나무의 엔티티 노드를 문서의 요소로: (정의 엔티티, 그것을 쓴 자리).

    정의 표지가 정의 엔티티를 정한다. 쓴 자리는 부모 노드의 이름과 그 아래에서의 이름으로
    찾는다: aspect의 부분, multi-aspect, specialization의 대안. 뿌리에는 쓴 자리가 없다.
    by_name은 엔티티 이름에서 식별자로 가는 표이며 여러 번 부를 때 넘겨 준다.
    """
    find = by_name.get if by_name is not None else m.entity
    entity = find(T.label(path))
    usage = None
    if len(path) >= 3 and T.kind(path[:-1]) != ENT:
        holder = find(T.label(path[:-2]))
        if holder is not None:
            name = family(path[-2])
            for a in m.kids(holder, "aspects"):
                if a.props.get("name") == name:
                    usage = next((p.id for p in m.kids(a.id, "parts") if m.label(p.id) == path[-1]), None)
            for ma in m.kids(holder, "multi_aspects"):
                if ma.props.get("name") == name:
                    usage = ma.id
            for sp in m.kids(holder, "specializations"):
                if sp.props.get("name") == name:
                    usage = next((o.id for o in m.kids(sp.id, "alternatives") if m.label(o.id) == path[-1]), None)
    return entity, usage


def _option_element(m: Model, point: ChoicePoint, option) -> tuple:
    """선택 지점 표의 선택지를 문서의 요소로: (요소, 속성 경로)."""
    if point.kind == "variable":
        found = m.by_name("variable", point.owner)
        return (found[0] if found else None), ("spec",)
    owner = m.entity(point.owner)
    if owner is None:
        return None, ()
    if point.kind == "alternative":
        for sp in m.kids(owner, "specializations"):
            if sp.props.get("name") == point.group:
                return next((o.id for o in m.kids(sp.id, "alternatives") if m.label(o.id) == option), sp.id), ()
    if point.kind == "count":
        for ma in m.kids(owner, "multi_aspects"):
            if ma.props.get("name") == point.group:
                return ma.id, ("cardinality",)
    for x in m.kids(owner, "aspects") + m.kids(owner, "multi_aspects"):
        if x.props.get("name") == option:
            return x.id, ()
    return owner, ()


# ---------------------------------------------------------------------------
# 족 범위
# ---------------------------------------------------------------------------

def _decision_entries(T, w: DecisionSet) -> list:
    """증거의 결정들을 하나씩: (변수 이름 또는 None, Choice)."""
    return [(name, _variable_choice(T, name, values)) for name, values in w.variables.items()] + \
           [(None, c) for c in w.choose]


def _cause(T, vs: list, hit: set, w: DecisionSet) -> tuple:
    """증거에서 빼도 되는 결정을 뺀 것. 남은 결정을 따르는 변이는 모두 hit에 든다.

    탐욕적으로 줄이므로 더 뺄 수 없는 원인이지 가장 작은 원인은 아니다.
    """
    entries = _decision_entries(T, w)
    banned = [excluded(T, c) for _, c in entries]

    def following(keep) -> list:
        return [V for V in vs if all(not (banned[i] & V) for i in keep)]

    keep = list(range(len(entries)))
    # 나중에 적힌 결정부터 빼 본다. 변수 값과 위쪽의 결정이 원인으로 남는다.
    for i in reversed(range(len(entries))):
        trial = [j for j in keep if j != i]
        if all(V in hit for V in following(trial)):
            keep = trial
    cause = DecisionSet(variables={entries[i][0]: w.variables[entries[i][0]]
                                   for i in keep if entries[i][0] is not None},
                        choose=tuple(entries[i][1] for i in keep if entries[i][0] is None))
    return cause, len(following(keep))


def analyze(m: Model, profile: Optional[Profile] = None, max_variants: int = 5000,
            unused: bool = True, max_nodes: int = 200000, attach=None, functions=None) -> Analysis:
    """문서 범위와 족 범위의 진단을 모두 낸다. 어떤 상태의 문서에도 예외 없이 답한다.

    max_nodes는 펼친 나무의 노드 수 한도, max_variants는 구조상 변이 수의 한도다.
    어느 쪽이든 넘으면 변이 분석을 하지 않고 LIMIT로 알린다.
    attach는 분석 모델에 확장을 더 얹는 함수다. 실행기를 붙이면(executor.attach) 그 실행기로
    만들 수 없는 변이가 다른 위반과 같은 방식으로 진단된다.
    functions는 식의 call 이 부르는 함수들이다. 등록되지 않은 함수를 부르면 ANALYZE로 알린다.
    """
    from . import loader, unfold                        # 지연 임포트: 순환을 피한다

    diags = check_document(m, profile, unused)
    result = Analysis(diags)
    doc_id = m.root

    def stop(severity, code, message) -> Analysis:
        diags.append(Diagnostic(severity, code, message, doc_id,
                                m.address(doc_id) if doc_id is not None else None,
                                blocking=severity == "error"))
        return result

    if any(d.blocking for d in diags):
        return stop("info", "SKIP", "문서에 오류가 있어 변이 분석을 하지 않았다")
    try:
        nodes = unfolded_size(m, max_nodes + 1)
    except RecursionError:
        nodes = max_nodes + 1
    if nodes > max_nodes:
        return stop("info", "LIMIT", f"펼친 나무의 노드가 한도 {max_nodes}개를 넘어 변이 분석을 하지 않았다")
    try:
        d = to_dict(m)
        doc = loader.load_ses_dict(d)
    except loader.LoadError as e:
        lines = str(e).split("\n")
        for line in lines[1:] or lines:                  # 첫 줄은 건수. 한 줄짜리 오류는 그 줄이 내용이다
            line = line.strip()
            head = re.match(r"[A-Za-z0-9_가-힣]+", line)
            target = m.entity(head.group(0)) if head else None
            diags.append(Diagnostic("error", "LOAD", line, target or doc_id,
                                    m.address(target or doc_id), blocking=True))
        return result
    except Exception as e:                              # 모양이 스키마와 다른 문서. 적재기는 엄격하다
        return stop("error", "LOAD", f"문서를 분석 모델로 옮길 수 없다: {type(e).__name__}: {e}")
    try:
        L = unfold.unfold_layered(doc, profile, functions)
        if attach is not None:
            L = attach(L)
        domains = unfold.variable_domains(doc)
        total = count_variants(L.ses.tree)
    except AlgebraError as e:
        return stop("error", "ANALYZE", f"변이 공간을 만들 수 없다: {e}")
    except Exception as e:                              # 분석이 편집기를 멈추게 하지 않는다
        return stop("error", "ANALYZE", f"변이 공간을 만들다가 실패했다: {type(e).__name__}: {e}")
    result.layered, result.domains = L, domains
    if total > max_variants:
        return stop("info", "LIMIT", f"구조상 변이가 {total}개로 한도 {max_variants}개를 넘어 열거하지 않았다")
    try:
        return _family(m, L, domains, result)
    except Exception as e:
        return stop("error", "ANALYZE", f"변이를 분석하다가 실패했다: {type(e).__name__}: {e}")


def _family(m: Model, L: Layered, domains: dict, result: Analysis) -> Analysis:
    diags = result.diagnostics
    doc_id = m.root

    def stop(severity, code, message) -> Analysis:
        diags.append(Diagnostic(severity, code, message, doc_id, m.address(doc_id),
                                scope="family", blocking=False))
        return result

    S, T = L.ses, L.ses.tree
    vs = sem(S)
    result.variants = len(vs)
    if not vs:
        result.wellformed = 0
        return stop("error", "EMPTY", "제약을 만족하는 변이가 없다")

    # 문서 범위에서 이미 보고한 프로파일 위반은 족 범위에서 되풀이하지 않는다
    static = {(d.code, m.entity_of(d.element)) for d in diags if d.code in PROFILE_CODES}
    by_name = {e.props.get("name"): e.id for e in reversed(m.of_type("entity"))}
    groups: dict = {}                                    # (계층, 부호, 요소, 메시지)에서 변이들로
    good = []
    for V in vs:
        found = violations(L, V)
        if not found:
            good.append(V)
        for layer, code, path, msg in found:
            entity, usage = provenance(m, T, path, by_name)
            if code in PROFILE_CODES and any(
                    (code, by_name.get(T.label(y))) in static for y in members(T, path) if y in V):
                continue
            g = groups.setdefault((layer, code, entity, msg), {"variants": [], "usage": usage})
            if not g["variants"] or g["variants"][-1] is not V:
                g["variants"].append(V)
    result.wellformed = len(good)

    for (layer, code, entity, msg), g in groups.items():
        hit = g["variants"]
        w = witness(T, hit[0], domains)
        cause, covers = _cause(T, vs, set(hit), w)
        diags.append(Diagnostic(
            "error", code, msg, entity or doc_id, m.address(entity or doc_id),
            related=(g["usage"],) if g["usage"] is not None else (), scope="family", layer=layer,
            affected=(len(hit), len(vs)), witness=w.to_dict(), cause=cause.to_dict(), cause_covers=covers))

    if not good:
        result.table = choice_table(S, None, domains)
        return stop("error", "NOWF", f"변이 {len(vs)}개 가운데 적격인 것이 없다")

    # 죽은 선택지: 어떤 변이에도, 또는 어떤 적격 변이에도 나타나지 않는 선택지
    base = choice_table(S, reduce(S), domains)
    core = choice_table(S, SES(restrict(T, frozenset().union(*good))), domains)
    result.table = core
    present = frozenset().union(*good)
    for p_all, p_core in zip(base, core):
        pushed = False
        if not p_core.active:
            # 이 지점 자체가 적격 변이에 없다. 위쪽 선택지가 보고된다. 다만 엔티티는 나타나는데 그 분해가 하나도
            # 나타나지 않는다면, 다른 구성원의 분해에 우선순위로 늘 밀리는 것이다 (18 문서)
            pushed = p_core.kind == "aspect" and any(T.kind(q) == ENT and T.label(q) == p_core.owner for q in present)
            if not pushed:
                continue
        for (option, in_any), (_, in_good) in zip(p_all.options, p_core.options):
            if in_good:
                continue
            element, path = _option_element(m, p_core, option)
            where = f"{p_core.owner} 의 {p_core.group or '분해'}" if p_core.kind != "variable" \
                else f"변수 {p_core.owner}"
            why = "적격인 변이에 나타나지 않는다" if in_any else "제약 때문에 어떤 변이에도 나타나지 않는다"
            if pushed:
                why = "다른 구성원의 분해에 우선순위로 밀려 적격인 변이에 나타나지 않는다"
            diags.append(Diagnostic("warning", "DEAD", f"{where} 에서 선택지 {option} 은 {why}",
                                    element or doc_id, m.address(element or doc_id), path, scope="family",
                                    data={"owner": p_core.owner, "kind": p_core.kind, "group": p_core.group,
                                          "option": option, "in_some_variant": in_any}))
    return result
