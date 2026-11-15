"""확장 사례: 속성 (SES + Attr).

attached variables 공리와 inheritance 공리의 "무엇이 상속되는가"를 맡는다.
핵은 병합체(누가 누구와 합쳐지는가)만 정하고, 값이 어떻게 합쳐지는지는 이 확장이 정한다.

병합 규칙
- 같은 이름의 속성은 같은 타입이어야 한다.
- 더 구체적인 구성원(대안)이 준 값이 덜 구체적인 구성원(부모)의 값을 덮는다.
- 서로 조상 관계가 아닌 두 구성원(한 엔티티의 서로 다른 specialization에서 온 대안)이
  같은 속성에 다른 값을 주면 충돌이다. 평가 순서로 해소하지 않는다.

값이 정해지는 길 (docs/ses-platform/18_classic_parity.md 4절)
- 정의가 주는 값. 상수이거나, 복제본마다의 값이거나, 변수와 등록한 함수에서 정해지는 값이다.
  변수를 보는 값은 변이의 변수 값이 정해져야 값이 된다. given(env)가 그 일을 한다.
- 결정 집합의 재정의. 정의 수준의 것은 그 정의가 준 값을 바꾸고(그래서 병합 규칙을 그대로 따른다),
  구성요소 수준의 것은 병합한 뒤의 값을 바꾼다(그래서 값의 충돌도 정리한다).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from .extension import Extension, View
from .skeleton import component_path


@dataclass(frozen=True)
class AttrDecl:
    type: str
    value: Any = None
    required: bool = False
    compute: Optional[Callable] = None      # 변수 값(이름에서 값으로)을 받아 값을 내는 함수. 있으면 value 대신 쓴다

    def under(self, env: Mapping) -> "AttrDecl":
        """변수 값이 env 일 때의 선언."""
        return self if self.compute is None else AttrDecl(self.type, self.compute(env), self.required)


def combine(items: list) -> tuple:
    """병합체 구성원들의 속성 선언을 합친다. items는 (구성원 경로, {이름: AttrDecl})의 목록이다.

    ({이름: AttrDecl}, 타입이 어긋난 이름들, 값이 어긋난 이름들)을 돌려준다.
    """
    by_name: dict = {}
    for path, decls in items:
        for name, d in decls.items():
            by_name.setdefault(name, []).append((path, d))
    merged, types, values = {}, set(), set()
    for name, lst in by_name.items():
        if len({d.type for _, d in lst}) > 1:
            types.add(name)
        setters = [(p, d) for p, d in lst if d.value is not None]
        # 다른 설정자의 조상이 아닌 설정자만 남긴다 (가장 구체적인 것들)
        top = [(p, d) for p, d in setters
               if not any(q != p and q[:len(p)] == p for q, _ in setters)]
        if len({repr(d.value) for _, d in top}) > 1:
            values.add(name)
        merged[name] = AttrDecl(lst[0][1].type, top[0][1].value if top else None,
                                any(d.required for _, d in lst))
    return merged, types, values


class Attributes(Extension):
    name = "attr"

    def __init__(self, decls: Mapping, typed: Optional[Mapping] = None, labels: Optional[Mapping] = None,
                 by_def: Optional[Mapping] = None, by_path: Optional[Mapping] = None,
                 env: Optional[Mapping] = None) -> None:
        self.decls = decls               # 엔티티 경로에서 {속성 이름: AttrDecl} 로
        self.typed = typed or {}         # 변수 이름에서 {값 노드의 이름: 원래 형의 값} 으로
        self.labels = labels or {}       # 엔티티 경로에서 정의 이름으로 (정의 수준의 재정의가 쓴다)
        self.by_def = by_def or {}       # (정의 이름, 속성 이름)에서 재정의한 값으로
        self.by_path = by_path or {}     # (구성요소 경로, 속성 이름)에서 재정의한 값으로
        self.env = env                   # 변수 값. 변이가 정해져야 안다
        self.dynamic = any(d.compute is not None for ds in decls.values() for d in ds.values())

    def given(self, env: Mapping) -> "Attributes":
        """변수 값이 env 일 때의 확장. env 는 변수 이름에서 값 노드의 이름으로 가는 사전이다."""
        if not self.dynamic:
            return self
        out = copy.copy(self)                # 변이마다 불린다. 선언들을 다시 훑지 않는다
        out.env = {n: self.typed[n][s] for n, s in env.items() if n in self.typed and s in self.typed[n]}
        return out

    def overridden(self, by_def: Mapping, by_path: Mapping, labels: Optional[Mapping] = None) -> "Attributes":
        """결정 집합의 재정의를 얹은 확장. labels 는 엔티티 경로에서 정의 이름으로 가는 표다."""
        out = copy.copy(self)
        out.labels, out.by_def, out.by_path = labels or self.labels, dict(by_def), dict(by_path)
        return out

    def entity(self, path):
        decls = self.decls.get(path)
        if not decls:
            return None
        if self.dynamic and self.env is not None:
            decls = {n: d.under(self.env) for n, d in decls.items()}
        if self.by_def:
            label = self.labels.get(path)
            decls = {n: (AttrDecl(d.type, self.by_def[(label, n)], d.required) if (label, n) in self.by_def else d)
                     for n, d in decls.items()}
        return decls

    def combine(self, tree, items: list) -> tuple:
        """병합과 구성요소 수준의 재정의. items는 (구성원 경로, entity가 낸 선언들)의 목록이다."""
        merged, types, values = combine(items)
        if self.by_path and items:
            where = component_path(tree, items[0][0])
            for name, d in list(merged.items()):
                if (where, name) in self.by_path:
                    merged[name] = AttrDecl(d.type, self.by_path[(where, name)], d.required)
                    values.discard(name)                # 구성요소에 직접 준 값이 구성원들의 값을 대신한다
        return merged, types, values

    def merge(self, tree, items):
        merged, types, values = self.combine(tree, items)
        conflicts = []
        for name in merged:
            if name in types:
                conflicts.append(f"속성 {name} 의 타입이 구성원마다 다르다")
            if name in values:
                conflicts.append(f"속성 {name} 에 서로 다른 대안이 다른 값을 준다")
        return merged, conflicts

    def check(self, v: View) -> list:
        return [("A1", f"필수 속성 {n} 에 값이 없다")
                for n, d in (v.ann or {}).items() if d.required and d.value is None]

    def interpret(self, v: View, children):
        return {"def": v.comp.labels[-1],
                "params": {n: d.value for n, d in (v.ann or {}).items()},
                "children": dict(children)}
