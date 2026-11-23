"""도메인 프로파일과 범용 장치 (docs/ses-platform/12_generic_and_specific.md).

분야의 낱말은 프로파일에만 있다. 이 모듈은 어느 분야의 낱말도 담지 않고,
프로파일이 선언한 것을 다섯 가지 범용 장치로 해석한다.

- 유형: 엔티티가 그 분야에서 무엇인가 (단원, 요구사항, 주장).
- 필드: 유형마다 가지는 값과 그 타입.
- 포함 규칙: 어떤 유형이 어떤 유형을 부분으로 가질 수 있는가.
- 관계: 엔티티 사이의 유형 있는 방향 관계 (선수, 추적, 지지).
- 규칙: 포괄(유형마다 관계가 몇 개 있어야 하는가)과 수량(필드의 합이나 개수의 범위).

Domain은 확장 계약(extension.py)을 지키는 확장 하나다. 따라서 어떤 프로파일로
정의한 분야든 핵의 정리(보존, 적격 핵, 합성)가 그대로 성립한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .algebra import AlgebraError
from .extension import Extension, View

_TYPES = {"int": (int,), "float": (int, float), "str": (str,), "bool": (bool,), "enum": (str, int)}


# title과 ui는 편집기를 위한 것이다. title은 화면에 보일 이름, ui는 편집기가 해석하는
# 자유로운 힌트(아이콘, 색, 입력 방식, 단위)다. 핵과 검사는 둘을 읽지 않는다.
# 분야에 따라 달라지는 표시 방식도 분야의 낱말이므로 프로파일에 둔다.

@dataclass(frozen=True)
class FieldSpec:
    type: str
    required: bool = False
    values: tuple = ()
    default: Any = None
    doc: Optional[str] = None
    title: Optional[str] = None
    ui: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KindSpec:
    name: str
    fields: Mapping[str, FieldSpec] = field(default_factory=dict)
    contains: Optional[tuple] = None        # None이면 제한 없음
    doc: Optional[str] = None
    title: Optional[str] = None
    ui: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LinkSpec:
    name: str
    src: tuple = ()                          # 출발 유형. 비어 있으면 제한 없음
    dst: tuple = ()                          # 도착 유형
    acyclic: bool = False
    target_required: bool = False            # 출발이 있으면 대상도 있어야 하는가
    doc: Optional[str] = None
    title: Optional[str] = None
    ui: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    name: str
    form: str                                # "coverage" 또는 "measure"
    each: Optional[str] = None               # coverage: 대상 유형
    incoming: Mapping[str, tuple] = field(default_factory=dict)   # 관계 유형에서 (최소, 최대)로
    outgoing: Mapping[str, tuple] = field(default_factory=dict)
    at: Optional[str] = None                 # measure: 합을 내는 자리의 유형. 없으면 뿌리
    op: str = "sum"                          # sum 또는 count
    field: Optional[str] = None
    over: tuple = ()
    min: Optional[float] = None
    max: Optional[float] = None
    equals: Optional[float] = None


@dataclass(frozen=True)
class Profile:
    name: str
    kinds: Mapping[str, KindSpec]
    links: Mapping[str, LinkSpec] = field(default_factory=dict)
    rules: tuple = ()
    description: Optional[str] = None

    def palette(self, kind: Optional[str]) -> dict:
        """유형 kind의 엔티티를 편집할 때 편집기가 내놓을 것.

        fields는 입력 폼의 항목, parts는 부분으로 둘 수 있는 유형, links_out과 links_in은
        이 유형에서 나가거나 이 유형으로 들어올 수 있는 관계다. 검사(Domain.check)가
        받아들이는 것과 같아야 한다. 모르는 유형이면 제한 없는 팔레트를 준다.
        """
        spec = self.kinds.get(kind)
        return {
            "fields": dict(spec.fields) if spec is not None else {},
            "parts": list(self.kinds) if spec is None or spec.contains is None else list(spec.contains),
            "links_out": [l.name for l in self.links.values() if not l.src or kind in l.src],
            "links_in": [l.name for l in self.links.values() if not l.dst or kind in l.dst],
        }


@dataclass(frozen=True)
class Item:
    """엔티티 노드에 붙는 프로파일 주석."""
    kind: Optional[str] = None
    fields: Mapping[str, Any] = field(default_factory=dict)
    links: Mapping[str, tuple] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 프로파일 적재
# ---------------------------------------------------------------------------

def _bounds(x) -> tuple:
    if isinstance(x, int):
        return (x, None)
    return (x.get("min", 0), x.get("max"))


def load_profile_dict(d: dict) -> Profile:
    kinds = {}
    for name, k in (d.get("kinds") or {}).items():
        k = k or {}
        fields = {f: FieldSpec(spec["type"], bool(spec.get("required", False)),
                               tuple(spec.get("values", ())), spec.get("default"), spec.get("doc"),
                               spec.get("title"), dict(spec.get("ui") or {}))
                  for f, spec in (k.get("fields") or {}).items()}
        kinds[name] = KindSpec(name, fields, tuple(k["contains"]) if "contains" in k else None,
                               k.get("doc"), k.get("title"), dict(k.get("ui") or {}))
    links = {name: LinkSpec(name, tuple(l.get("from", ())), tuple(l.get("to", ())),
                            bool(l.get("acyclic", False)), l.get("target", "optional") == "required",
                            l.get("doc"), l.get("title"), dict(l.get("ui") or {}))
             for name, l in ((n, v or {}) for n, v in (d.get("links") or {}).items())}
    rules = []
    for r in d.get("rules", []):
        if "each" in r:
            rules.append(Rule(r["name"], "coverage", each=r["each"],
                              incoming={k: _bounds(v) for k, v in (r.get("incoming") or {}).items()},
                              outgoing={k: _bounds(v) for k, v in (r.get("outgoing") or {}).items()}))
        elif "sum" in r or "count" in r:
            op = "sum" if "sum" in r else "count"
            body = r[op]
            rules.append(Rule(r["name"], "measure", at=r.get("at"), op=op,
                              field=body.get("field"), over=tuple(body.get("over", ())),
                              min=r.get("min"), max=r.get("max"), equals=r.get("equals")))
        else:
            raise AlgebraError(f"규칙 {r.get('name')}: each, sum, count 가운데 하나가 필요하다")
    prof = Profile(d["name"], kinds, links, tuple(rules), d.get("description"))
    _validate(prof)
    return prof


def load_profile(path: str) -> Profile:
    import yaml
    with open(path, encoding="utf-8") as f:
        return load_profile_dict(yaml.safe_load(f))


def _validate(p: Profile) -> None:
    errors = []

    def kind(k, where):
        if k not in p.kinds:
            errors.append(f"{where}: 정의되지 않은 유형 {k}")

    for k in p.kinds.values():
        for c in k.contains or ():
            kind(c, f"kinds.{k.name}.contains")
        for f, spec in k.fields.items():
            if spec.type not in _TYPES:
                errors.append(f"kinds.{k.name}.fields.{f}: 알 수 없는 타입 {spec.type}")
            if spec.type == "enum" and not spec.values:
                errors.append(f"kinds.{k.name}.fields.{f}: enum에는 values가 필요하다")
    for l in p.links.values():
        for k in l.src + l.dst:
            kind(k, f"links.{l.name}")
    for r in p.rules:
        if r.form == "coverage":
            kind(r.each, f"rules.{r.name}.each")
            for lt in list(r.incoming) + list(r.outgoing):
                if lt not in p.links:
                    errors.append(f"rules.{r.name}: 정의되지 않은 관계 {lt}")
        else:
            if r.at is not None:
                kind(r.at, f"rules.{r.name}.at")
            for k in r.over:
                kind(k, f"rules.{r.name}.over")
            if r.op == "sum" and not r.field:
                errors.append(f"rules.{r.name}: sum에는 field가 필요하다")
    if errors:
        raise AlgebraError("프로파일 오류:\n  " + "\n  ".join(errors))


# ---------------------------------------------------------------------------
# 범용 확장: 프로파일로 매개변수화된다
# ---------------------------------------------------------------------------

class Domain(Extension):
    """프로파일이 선언한 유형, 필드, 포함 규칙, 관계, 규칙을 검사하고 해석한다."""

    def __init__(self, profile: Profile, items: Mapping):
        self.profile = profile
        self.items = items                   # 엔티티 경로에서 Item으로
        self.name = profile.name

    def entity(self, path):
        return self.items.get(path)

    # 병합: 유형은 하나여야 하고, 필드는 더 구체적인 구성원이 덮으며, 관계는 합친다
    def merge(self, tree, items):
        conflicts = []
        kinds = sorted({it.kind for _, it in items if it.kind})
        if len(kinds) > 1:
            conflicts.append(f"병합체 구성원의 유형이 다르다: {kinds}")
        by_name: dict = {}
        for path, it in items:
            for name, value in it.fields.items():
                by_name.setdefault(name, []).append((path, value))
        fields = {}
        for name, setters in by_name.items():
            top = [(p, v) for p, v in setters
                   if not any(q != p and q[:len(p)] == p for q, _ in setters)]
            if len({repr(v) for _, v in top}) > 1:
                conflicts.append(f"필드 {name} 에 서로 다른 대안이 다른 값을 준다")
            fields[name] = top[0][1]
        links: dict = {}
        for _, it in items:
            for lt, targets in it.links.items():
                links.setdefault(lt, set()).update(targets)
        return Item(kinds[0] if kinds else None, fields,
                    {lt: tuple(sorted(ts)) for lt, ts in links.items()}), conflicts

    def _value(self, it: Item, name: str, spec: FieldSpec):
        return it.fields.get(name, spec.default)

    # 국소 검사: 유형, 필드, 포함 규칙
    def check(self, v: View) -> list:
        it = v.ann
        if it is None:
            return []
        out = []
        if it.kind is None:
            if it.fields:
                out.append(("T0", "유형이 없는 엔티티가 필드를 가진다"))
            return out
        spec = self.profile.kinds.get(it.kind)
        if spec is None:
            return [("T1", f"프로파일에 없는 유형 {it.kind}")]
        for name, value in it.fields.items():
            f = spec.fields.get(name)
            if f is None:
                out.append(("F1", f"유형 {it.kind} 에 없는 필드 {name}"))
            elif not isinstance(value, _TYPES[f.type]) or \
                    (f.type != "bool" and isinstance(value, bool)):
                out.append(("F3", f"필드 {name} 의 값 {value!r} 이 타입 {f.type} 이 아니다"))
            elif f.type == "enum" and value not in f.values:
                out.append(("F3", f"필드 {name} 의 값 {value!r} 이 허용 값이 아니다"))
        for name, f in spec.fields.items():
            if f.required and self._value(it, name, f) is None:
                out.append(("F2", f"필수 필드 {name} 에 값이 없다"))
        if spec.contains is not None:
            for n, child in v.children.items():
                ck = child.ann.kind if child.ann is not None else None
                if ck is not None and ck not in spec.contains:
                    out.append(("T2", f"유형 {it.kind} 은 유형 {ck} 인 {n} 을 부분으로 가질 수 없다"))
        return out

    # 뼈대 전체 검사: 관계와 규칙
    def _nodes(self, root: View) -> list:
        out, stack = [], [root]
        while stack:
            v = stack.pop()
            out.append(v)
            stack.extend(v.children.values())
        return out

    def _edges(self, nodes: list, out: Optional[list] = None) -> dict:
        """관계 유형에서 (출발, 도착) 쌍의 목록으로. out이 주어지면 위반을 적는다."""
        index: dict = {}
        for v in nodes:
            for label in v.comp.labels:
                index.setdefault(label, []).append(v)
        edges: dict = {}
        for v in nodes:
            it = v.ann
            if it is None:
                continue
            for lt, targets in it.links.items():
                spec = self.profile.links.get(lt)
                if spec is None:
                    if out is not None:
                        out.append(("L0", v.path, f"프로파일에 없는 관계 {lt}"))
                    continue
                if spec.src and it.kind not in spec.src and out is not None:
                    out.append(("L2", v.path, f"유형 {it.kind} 은 관계 {lt} 의 출발이 될 수 없다"))
                for t in targets:
                    found = index.get(t, [])
                    if not found:
                        if spec.target_required and out is not None:
                            out.append(("L1", v.path, f"관계 {lt} 의 대상 {t} 이 이 변이에 없다"))
                        continue
                    for u in found:
                        uk = u.ann.kind if u.ann is not None else None
                        if spec.dst and uk not in spec.dst and out is not None:
                            out.append(("L2", v.path, f"관계 {lt} 의 대상 {t} 의 유형이 맞지 않다"))
                        edges.setdefault(lt, []).append((v, u))
        return edges

    def check_tree(self, root: View) -> list:
        out: list = []
        nodes = self._nodes(root)
        edges = self._edges(nodes, out)
        for lt, spec in self.profile.links.items():          # 비순환
            if spec.acyclic and lt in edges:
                node = _find_cycle([(a.path, b.path) for a, b in edges[lt]])
                if node is not None:
                    out.append(("L3", node, f"관계 {lt} 에 순환이 있다"))
        for r in self.profile.rules:
            if r.form == "coverage":
                for v in nodes:
                    if v.ann is None or v.ann.kind != r.each:
                        continue
                    for lt, (lo, hi) in r.incoming.items():
                        n = sum(1 for _, b in edges.get(lt, []) if b is v)
                        if n < lo or (hi is not None and n > hi):
                            out.append(("R1", v.path, f"{r.name}: 들어오는 관계 {lt} 이 {n}개다"))
                    for lt, (lo, hi) in r.outgoing.items():
                        n = sum(1 for a, _ in edges.get(lt, []) if a is v)
                        if n < lo or (hi is not None and n > hi):
                            out.append(("R1", v.path, f"{r.name}: 나가는 관계 {lt} 이 {n}개다"))
            else:
                scopes = [root] if r.at is None else \
                    [v for v in nodes if v.ann is not None and v.ann.kind == r.at]
                for s in scopes:
                    total = self._measure(r, s)
                    bad = (r.min is not None and total < r.min) or \
                        (r.max is not None and total > r.max) or \
                        (r.equals is not None and total != r.equals)
                    if bad:
                        want = ", ".join(f"{word} {x}" for word, x in (("최소", r.min), ("최대", r.max), ("정확히", r.equals))
                                         if x is not None)
                        out.append(("R2", s.path, f"{r.name}: 값이 {total} 이다. 규칙은 {want} 이다"))
        return out

    def _measure(self, r: Rule, scope: View):
        total = 0
        for v in self._nodes(scope):
            it = v.ann
            if it is None or it.kind not in r.over:
                continue
            if r.op == "count":
                total += 1
            else:
                spec = self.profile.kinds[it.kind].fields.get(r.field) \
                    if it.kind in self.profile.kinds else None
                value = it.fields.get(r.field, spec.default if spec else None)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    total += value
        return total

    # 해석: 분야 중립의 구조화된 산출물
    def interpret(self, v: View, children):
        it = v.ann or Item()
        spec = self.profile.kinds.get(it.kind) if it.kind else None
        fields = dict(it.fields)
        if spec is not None:
            for name, f in spec.fields.items():
                if name not in fields and f.default is not None:
                    fields[name] = f.default
        totals = {r.name: self._measure(r, v) for r in self.profile.rules
                  if r.form == "measure" and (r.at == it.kind or (r.at is None and len(v.path) == 1))}
        node = {"name": v.name, "def": v.comp.labels[-1], "kind": it.kind, "fields": fields,
                "links": {lt: list(ts) for lt, ts in it.links.items()}, "children": dict(children)}
        if totals:
            node["totals"] = totals
        return node


def _find_cycle(pairs: list):
    graph: dict = {}
    for a, b in pairs:
        graph.setdefault(a, []).append(b)
    state: dict = {}

    def visit(n):
        state[n] = 1
        for m in graph.get(n, []):
            if state.get(m) == 1 or (state.get(m) is None and visit(m)):
                return True
        state[n] = 2
        return False

    for n in sorted(graph):
        if state.get(n) is None and visit(n):
            return n
    return None
