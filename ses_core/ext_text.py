"""확장 사례: 문서 조립 (SES + Text).

시뮬레이션과 무관한 분야의 예다. 엔티티는 문서의 조각이고, aspect는 조각들의
배열이며, specialization은 조각의 대체 문안이다. 변이 하나가 문서 하나가 된다.

주석
- 엔티티: 틀 문자열. {이름}은 그 이름의 부분으로, {*}는 살아 있는 모든 부분을
  분해가 정한 순서와 구분자로 이은 것으로 치환된다.
- aspect: (부분 순서, 구분자).

병합: 가장 구체적인 구성원의 틀을 쓴다. 서로 조상 관계가 아닌 두 구성원이 틀을
주면 충돌이다.
검사: 틀이 가리키는 이름은 그 구성요소의 부분이어야 한다. 없음이 된 부분은 빈
문자열로 치환되지만, 필수라고 표시한 자리({!이름})가 없음이면 위반이다.
"""

from __future__ import annotations

import re
from typing import Mapping

from .extension import Extension, View

_SLOT = re.compile(r"\{(!?)([A-Za-z_][A-Za-z0-9_]*|\*)\}")


class Text(Extension):
    name = "text"

    def __init__(self, templates: Mapping, layouts: Mapping = None):
        self.templates = templates           # 엔티티 경로에서 틀 문자열로
        self.layouts = layouts or {}         # aspect 경로에서 (순서, 구분자) 로

    def entity(self, path):
        return self.templates.get(path)

    def aspect(self, path):
        return self.layouts.get(path)

    def merge(self, tree, items):
        top = [(p, t) for p, t in items
               if not any(q != p and q[:len(p)] == p for q, _ in items)]
        conflicts = ["서로 다른 대안이 각각 틀을 준다"] if len({t for _, t in top}) > 1 else []
        return top[0][1], conflicts

    def _template(self, v: View) -> str:
        return v.ann if v.ann is not None else ("{*}" if v.children or v.absent else "")

    def check(self, v: View) -> list:
        out = []
        known = set(v.children) | set(v.absent)
        for must, name in _SLOT.findall(self._template(v)):
            if name == "*":
                continue
            if name not in known:
                out.append(("X1", f"틀이 가리키는 부분 {name} 이 없다"))
            elif must and name in v.absent:
                out.append(("X2", f"필수 자리 {name} 이 없음이다"))
        return out

    def interpret(self, v: View, children):
        order, sep = v.aspect_ann or (sorted(children), "")
        order = [n for n in order if n in children] + sorted(n for n in children if n not in order)

        def fill(m):
            name = m.group(2)
            if name == "*":
                return sep.join(children[n] for n in order)
            return children.get(name, "")

        return _SLOT.sub(fill, self._template(v))
