"""확장 사례: 속성 (SES + Attr).

attached variables 공리와 inheritance 공리의 "무엇이 상속되는가"를 맡는다.
핵은 병합체(누가 누구와 합쳐지는가)만 정하고, 값이 어떻게 합쳐지는지는 이 확장이 정한다.

병합 규칙
- 같은 이름의 속성은 같은 타입이어야 한다.
- 더 구체적인 구성원(대안)이 준 값이 덜 구체적인 구성원(부모)의 값을 덮는다.
- 서로 조상 관계가 아닌 두 구성원(한 엔티티의 서로 다른 specialization에서 온 대안)이
  같은 속성에 다른 값을 주면 충돌이다. 평가 순서로 해소하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .extension import Extension, View


@dataclass(frozen=True)
class AttrDecl:
    type: str
    value: Any = None
    required: bool = False


class Attributes(Extension):
    name = "attr"

    def __init__(self, decls: Mapping):
        self.decls = decls               # 엔티티 경로에서 {속성 이름: AttrDecl} 로

    def entity(self, path):
        return self.decls.get(path) or None

    def merge(self, tree, items):
        by_name: dict = {}
        for path, decls in items:
            for name, d in decls.items():
                by_name.setdefault(name, []).append((path, d))
        merged, conflicts = {}, []
        for name, lst in by_name.items():
            if len({d.type for _, d in lst}) > 1:
                conflicts.append(f"속성 {name} 의 타입이 구성원마다 다르다")
            setters = [(p, d) for p, d in lst if d.value is not None]
            # 다른 설정자의 조상이 아닌 설정자만 남긴다 (가장 구체적인 것들)
            top = [(p, d) for p, d in setters
                   if not any(q != p and q[:len(p)] == p for q, _ in setters)]
            if len({repr(d.value) for _, d in top}) > 1:
                conflicts.append(f"속성 {name} 에 서로 다른 대안이 다른 값을 준다")
            merged[name] = AttrDecl(lst[0][1].type, top[0][1].value if top else None,
                                    any(d.required for _, d in lst))
        return merged, conflicts

    def check(self, v: View) -> list:
        return [("A1", f"필수 속성 {n} 에 값이 없다")
                for n, d in (v.ann or {}).items() if d.required and d.value is None]

    def interpret(self, v: View, children):
        return {"def": v.comp.labels[-1],
                "params": {n: d.value for n, d in (v.ann or {}).items()},
                "children": dict(children)}
