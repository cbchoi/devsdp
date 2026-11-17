"""결합의 족 수준 검사를 정의 표 위에서 한다. 변이를 열거하지 않는다.

결합 확장의 검사(coupling.Coupling.check, C1에서 C4)와 포트의 병합 충돌(M)은 국소적이다. 구성요소 하나에
대한 판정은 그 구성요소의 병합체, 고른 분해, 그리고 부분마다의 "인터페이스"로만 정해진다. 부분의 인터페이스는
그 부분이 빠졌는가와, 빠지지 않았다면 그 병합체의 합쳐진 포트다. 부분의 아래에서 무엇을 골랐는가는 관여하지 않는다.

그래서 모든 변이를 보는 대신 다음을 본다. 변수 값마다, 뿌리에서 닿는 구성요소의 정의마다, 그 정의의 병합체와
고를 수 있는 분해와 부분들의 인터페이스의 모든 조합. 부분들은 서로 독립으로 고르므로(선택 제약이 없으면) 그런
조합은 모두 어떤 변이에 나타나고, 변이에 나타나는 조합은 모두 여기서 본다. 그러므로 위반의 집합이 열거한 것과 같다.

multi-aspect 의 복제본이 많을 때는 절단 정리(08 문서의 정리 13)를 쓴다. 개수 3 이상은 개수 3으로 대표한다.

한계
- 선택 제약(selected)이 있으면 여기서 본 조합 가운데 제약이 막는 것이 있을 수 있다. 그때 결과는 "있을 수 있는 위반"이다.
- 뼈대 전체를 보는 검사(끝에서 끝까지의 구동 C5, 실행기의 검사)와 다른 확장(속성, 문서 조립, 프로파일)은 보지 않는다.
- 위반이 있는 변이의 수는 세지 않는다. 어떤 위반이 어디서 생기는지만 낸다.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from . import model as m
from .coupling import Coupling, PortDecl
from .extension import View
from .folded import Semantics, replica_name, selected_atoms
from .skeleton import Comp
from .unfold import _instantiate_pattern, _plain

CUT = 3                     # 절단 정리: 개수 3 이상은 3으로 대표한다


@dataclass(frozen=True)
class Finding:
    code: str               # M, C1, C2, C3, C4
    definition: str         # 그 구성요소의 정의
    message: str
    assignment: tuple       # 그것이 생기는 변수 값 하나. (이름, 값)들
    members: tuple          # 그때의 병합체
    decomposition: str      # 그때 고른 분해. 병합 충돌이면 빈 글자
    count: object = None    # multi-aspect 이면 본 개수. CUT 이면 3 이상을 대표한다


def _ports(e: m.EntityDef) -> dict:
    return {n: PortDecl(p.type, p.direction.value, p.required) for n, p in e.ports.items()}


def _leaf(name: str, ann) -> View:
    return View(Comp(("part", name), (), (), (), {}, ()), ann, (), None, {}, ())


def check(doc: m.SesDocument, functions=None) -> tuple:
    """(위반들, 선택 제약이 있어 "있을 수 있는 위반"인가)."""
    sem = Semantics(doc, functions)
    ext = Coupling({}, {})
    early = [c for c in doc.constraints if not any(selected_atoms(x) for x in (c.when, c.require, c.forbid))]
    constrained = len(early) < len(doc.constraints)
    found: dict = {}
    merged: dict = {}                 # 병합체(구성원의 이름들)에서 (합쳐진 포트, 충돌들)로. 변수 값과 무관하다
    judged: dict = {}                 # 국소 구성에서 검사 결과로. 변수 값과 무관하다

    def interface(names: tuple) -> tuple:
        if names not in merged:
            items = [((y,), _ports(doc.entities[y])) for y in names if doc.entities[y].ports]
            merged[names] = ext.merge(None, items) if items else (None, [])
        return merged[names]

    def options(d: str, sigma: dict, memo: dict) -> list:
        """정의 d 의 부분이 가질 수 있는 인터페이스들. None 은 빠진 것이다. 같은 것은 한 번만 든다."""
        if d not in memo:
            out, seen = [], set()
            for mu in sem.members(d, sigma):
                ann = None if sem.removed(mu) else (interface(tuple(mu.names()))[0] or {})
                key = "gone" if ann is None else repr(sorted(ann.items()))
                if key not in seen:
                    seen.add(key)
                    out.append((key, ann))
            memo[d] = out
        return memo[d]

    def judge(d: str, names: tuple, y: str, x, n, kids: tuple) -> list:
        """국소 구성 하나의 위반들. kids 는 부분마다의 (이름, 인터페이스의 열쇠, 합쳐진 포트)다."""
        key = (d, names, y, x.name, n, tuple((name, k) for name, k, _ in kids))
        if key not in judged:
            absent = tuple(name for name, _, ann in kids if ann is None)
            children = {name: _leaf(name, ann) for name, _, ann in kids if ann is not None}
            couplings = _plain(x.couplings) if isinstance(x, m.Aspect) else \
                _instantiate_pattern(x, [name for name, _, _ in kids])
            comp = Comp((d,), (), names, ((d, x.name),), {name: v.comp for name, v in children.items()}, absent)
            ann, _ = interface(names)
            judged[key] = ext.check(View(comp, ann, (), couplings, children, absent))
        return judged[key]

    for sigma in sem.assignments():
        if not all(sem.satisfied(c, sigma, set()) for c in early):
            continue
        where = tuple(sigma.items())
        memo: dict = {}
        seen, stack = set(), [sem.root]
        while stack:                                           # 이 변수 값에서 뿌리에서 닿는 구성요소의 정의들
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            for mu in sem.members(d, sigma):
                if sem.removed(mu):
                    continue
                names = tuple(mu.names())
                for msg in interface(names)[1]:
                    found.setdefault(("M", d, msg), Finding("M", d, msg, where, names, ""))
                owners = sem.owners(mu)
                if not owners:
                    continue
                for y, x in sem.outcomes(owners, sigma)[0]:
                    if isinstance(x, m.Aspect):
                        cases = [(None, [(p.part_name, p.def_name) for p in x.parts])]
                    else:
                        counts = sem.counts(x, sigma)
                        small = sorted({n for n in counts if n < CUT} | ({CUT} if any(n >= CUT for n in counts) else set()))
                        cases = [(n, [(replica_name(x, i, n), x.part.def_name) for i in range(n)]) for n in small]
                    for n, parts in cases:
                        stack += [child for _, child in parts]
                        for combo in product(*(options(child, sigma, memo) for _, child in parts)):
                            kids = tuple((name, k, ann) for (name, _), (k, ann) in zip(parts, combo))
                            for code, msg in judge(d, names, y, x, n, kids):
                                found.setdefault((code, d, msg), Finding(code, d, msg, where, names, x.name, n))
    return list(found.values()), constrained
