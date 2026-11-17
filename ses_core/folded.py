"""접힌 형태 위의 의미 (docs/ses-platform/theory.md 2절과 3절).

정준 문서의 뜻을 정의 표 위에서 직접 정한다. 나무로 펼치지 않는다. 표시 노드도 없다.

- 변수 값 sigma 는 변수마다 값 하나다.
- 병합체 선택 Member: 정의 하나에서 시작해 specialization 마다 대안을 하나씩 골라 합친 것 (정의 2).
- 병합체의 분해 (정의 3): 분해를 가진 구성원마다 요구를 하나 낸다. 참인 규칙이 없으면 자기 분해 가운데
  하나를 고르고, 있으면 규칙이 남긴 것 전부가 요구다. 낸 요구들 가운데 우선순위가 홀로 가장 앞선 분해가
  그 병합체의 분해다. 그런 것이 없으면 분해를 정할 수 없다. Dec 는 그렇게 정해질 수 있는 분해들이고,
  Amb 는 정할 수 없게 되는 요구의 조합이 있다는 뜻이다.
- 구성요소 선택 Comp (정의 4): 병합체와, 그 병합체가 빠졌는지(gone), 분해가 없는지(atom), 분해 하나를
  골랐는지(split)와 그 부분들의 구성요소 선택, 또는 분해를 정할 수 없는지(stuck).
- 변이: 제약을 만족하는 (sigma, 뿌리의 구성요소 선택) (정의 6).
- 핵 적격: 뿌리가 빠지지 않았고 어디에도 stuck 이 없다.

이 모듈은 둘을 담는다.
- Semantics: 정의를 그대로 옮긴 열거. 지수 시간이다. 정리의 대조와 작은 문서에 쓴다.
- evaluate: 변이를 열거하지 않고 정의 표 위에서 값을 구하는 계산 (정리 3). 변이 수와 적격 변이 수를
  큰 문서에서도 낸다.

unfold.py 의 펼침은 이 의미의 한 표현이다. 변이마다 펼친 나무의 노드 집합이 하나씩 대응한다
(nodes, 정리 5). 그 대응은 tests/test_folded.py 가 무작위 문서에서 확인한다.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from itertools import product
from typing import Iterator, Optional

from . import model as m
from .algebra import AlgebraError
from .loader import selected_target

GONE, ATOM, STUCK, SPLIT = "gone", "atom", "stuck", "split"

_OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le,
        "gt": operator.gt, "ge": operator.ge, "in": lambda v, c: v in c}


# ---------------------------------------------------------------------------
# 정의 2, 4. 선택 나무
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Member:
    """병합체 선택. 정의 하나와, 그 정의의 specialization 마다 고른 대안의 병합체 선택."""
    name: str
    picks: tuple = ()                 # ((specialization 이름, Member), ...). 정의에 적힌 순서

    def members(self) -> Iterator["Member"]:
        yield self
        for _, sub in self.picks:
            yield from sub.members()

    def names(self) -> list:
        return [x.name for x in self.members()]


@dataclass(frozen=True)
class Comp:
    """구성요소 선택."""
    member: Member
    state: str                        # GONE, ATOM, STUCK, SPLIT
    owner: Optional[str] = None       # 분해를 낸 구성원의 정의
    dec: Optional[str] = None         # 고른 분해의 이름 (aspect 나 multi-aspect)
    count: Optional[int] = None       # multi-aspect 이면 복제본의 수
    parts: tuple = ()                 # ((부분 이름, Comp), ...). 분해에 적힌 순서

    def walk(self, pos: tuple) -> Iterator[tuple]:
        """(구성요소 경로, 구성요소 선택)들. pos 는 이 구성요소의 경로다."""
        yield pos, self
        for name, c in self.parts:
            yield from c.walk(pos + (name,))


# ---------------------------------------------------------------------------
# 식
# ---------------------------------------------------------------------------

def above(p, q) -> bool:
    """우선순위 p 가 q 보다 앞서는가. 수가 작을수록 앞선다. 없는 것은 가장 뒤이고 없는 것끼리는 가르지 못한다."""
    return p is not None and (q is None or p < q)


def value(e: m.Expr, sigma: dict, functions=None):
    """변수만 보는 식의 값."""
    if isinstance(e, m.Const):
        return e.value
    if isinstance(e, m.Var):
        return sigma[e.name]
    if isinstance(e, m.Compare):
        left, right = value(e.left, sigma, functions), value(e.right, sigma, functions)
        try:
            return bool(_OPS[e.op](left, right))
        except TypeError:
            raise AlgebraError(f"견줄 수 없는 값이다: {left!r} {e.op} {right!r}")
    if isinstance(e, m.And):
        return all(value(x, sigma, functions) for x in e.items)
    if isinstance(e, m.Or):
        return any(value(x, sigma, functions) for x in e.items)
    if isinstance(e, m.Not):
        return not value(e.item, sigma, functions)
    if isinstance(e, m.Call):
        fn = (functions or {}).get(e.fn)
        if fn is None:
            raise AlgebraError(f"등록되지 않은 함수 {e.fn}")
        args = [value(a, sigma, functions) for a in e.args]
        try:
            return fn(*args)
        except Exception as err:                 # noqa: BLE001
            raise AlgebraError(f"함수 {e.fn} 가 인자 {args} 에서 실패했다: {err}")
    raise AlgebraError(f"변수만 보는 식이 아니다: {e!r}")


def selected_atoms(e) -> list:
    """식에 나오는 selected 들."""
    if e is None:
        return []
    if isinstance(e, m.Selected):
        return [e]
    out: list = []
    for x in getattr(e, "items", ()) or ():
        out += selected_atoms(x)
    for attr in ("left", "right", "item"):
        if hasattr(e, attr):
            out += selected_atoms(getattr(e, attr))
    return out


def domain(doc: m.SesDocument, name: str) -> list:
    var = doc.variables[name]
    if isinstance(var.domain, m.EnumSet):
        return list(var.domain.values)
    if isinstance(var.domain, m.Range) and var.type == m.ScalarType.INT:
        return list(range(int(var.domain.min), int(var.domain.max) + 1))
    if var.type == m.ScalarType.BOOL:
        return [True, False]
    raise AlgebraError(f"변수 {name} 에 유한 범위가 필요하다")


def decompositions(e: m.EntityDef) -> list:
    """정의에 적힌 분해들. aspect 가 먼저, multi-aspect 가 뒤다."""
    return list(e.aspects.values()) + list(e.multi_aspects.values())


def replica_name(ma: m.MultiAspect, i: int, n: int) -> str:
    return ma.naming.format(i=i, n=n, part=ma.part.part_name)


# ---------------------------------------------------------------------------
# 정의를 그대로 옮긴 의미
# ---------------------------------------------------------------------------

MAX_ROWS = 20000                 # 조건 하나를 미리 평가해 보는 변수 값 조합의 수. 넘으면 미리 보지 않는다


def reach(doc: m.SesDocument, d: str) -> list:
    """d 와, d 의 specialization 들의 대안에서 다시 닿는 정의들. d 가 놓인 자리의 병합체에 들 수 있는 정의들이다."""
    out, stack = [], [d]
    while stack:
        y = stack.pop()
        if y in out:
            continue
        out.append(y)
        stack += [alt for sp in doc.entities[y].specializations.values() for alt in sp.alternatives]
    return out


def all_counts(doc: m.SesDocument, ma: m.MultiAspect) -> list:
    """어떤 변수 값에서든 그 multi-aspect 가 가질 수 있는 개수들."""
    card = ma.cardinality
    if isinstance(card, m.Fixed):
        return [card.n]
    if isinstance(card, m.VarCard):
        return domain(doc, card.var)
    return [] if card.max is None else list(range(card.min, card.max + 1))


def occurring(doc: m.SesDocument) -> list:
    """어떤 선택에든 놓일 수 있는 정의들. 펼친 나무 T(D)에 엔티티 노드로 나타나는 정의와 같다.

    뿌리에서 대안, aspect 의 부분, 그리고 개수가 0 보다 클 수 있는 multi-aspect 의 부분을 따라 닿는 정의다.
    개수가 늘 0 인 multi-aspect 의 부분은 쓰이기는 하나 어디에도 놓이지 않는다.
    """
    seen, stack = set(), [doc.root.name]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        e = doc.entities[name]
        stack += [alt for sp in e.specializations.values() for alt in sp.alternatives]
        stack += [p.def_name for a in e.aspects.values() for p in a.parts]
        stack += [ma.part.def_name for ma in e.multi_aspects.values() if any(n > 0 for n in all_counts(doc, ma))]
    return [name for name in doc.entities if name in seen]


def possible_members(doc: m.SesDocument, path: tuple) -> list:
    """구성요소 경로 path 에 놓일 수 있는 구성원의 정의들. 그 자리가 어떤 선택에도 없으면 빈 목록이다."""
    if not path or path[0] != doc.root.name:
        return []
    comps = [doc.root.name]
    for name in path[1:]:
        nxt: list = []
        for c in comps:
            for y in reach(doc, c):
                e = doc.entities[y]
                nxt += [p.def_name for a in e.aspects.values() for p in a.parts if p.part_name == name]
                for ma in e.multi_aspects.values():
                    counts = all_counts(doc, ma)
                    tops = counts if "{n}" in ma.naming else counts and [max(counts)]
                    if any(name == replica_name(ma, i, n) for n in tops for i in range(n)):
                        nxt.append(ma.part.def_name)
        comps = list(dict.fromkeys(nxt))
    return list(dict.fromkeys(y for c in comps for y in reach(doc, c)))


def conditions(e) -> list:
    """식에서 변수만 보는 조건들. 그리고, 또는, 아니다, selected 를 벗긴 나머지다."""
    if e is None or isinstance(e, m.Selected):
        return []
    if isinstance(e, (m.And, m.Or)):
        return [c for x in e.items for c in conditions(x)]
    if isinstance(e, m.Not):
        return conditions(e.item)
    return [e]


def variables_of(e) -> list:
    if isinstance(e, m.Var):
        return [e.name]
    out: list = []
    for x in list(getattr(e, "items", ()) or ()) + list(getattr(e, "args", ()) or ()):
        out += variables_of(x)
    for attr in ("left", "right", "item"):
        if hasattr(e, attr):
            out += variables_of(getattr(e, attr))
    return list(dict.fromkeys(out))


def validate(doc: m.SesDocument, functions=None) -> None:
    """뜻을 정할 수 있는 문서인가. 아니면 AlgebraError 를 낸다. 적재기가 보지 못하는 두 가지다.

    - 조건은 변수의 모든 값에서 값이 있어야 한다. 견줄 수 없는 값을 견주거나, 등록하지 않은 함수를 부르거나,
      함수가 실패하면 안 된다. 그리고나 또는으로 묶여 있어 평가가 닿지 않는 조건도 본다.
    - 제약의 selected 는 어떤 선택에든 있을 수 있는 곳을 가리켜야 한다. 가리키는 곳이 없는 것은 잘못 적은 것이다.
      정의 수준이면 그 정의가 어디엔가 놓일 수 있어야 하고(occurring), 경로 수준이면 그 자리가 있을 수 있고
      거기 놓일 수 있는 구성원 가운데 그 선택 지점을 가진 것이 있어야 한다.
    펼침(unfold.py)도 같은 문서를 거부한다.
    """
    exprs = [x for c in doc.constraints for x in (c.when, c.require, c.forbid)]
    for name in reachable(doc):
        e = doc.entities[name]
        exprs += [x.rule for x in decompositions(e)]
        for sp in e.specializations.values():
            rule = sp.select
            while rule is not None:
                exprs.append(rule.when)
                rule = rule.otherwise if isinstance(rule.otherwise, m.SelectRule) else None
    for cond in (c for e in exprs for c in conditions(e)):
        names = variables_of(cond)
        domains = [domain(doc, n) for n in names]
        rows = 1
        for d in domains:
            rows *= len(d)
        if rows <= MAX_ROWS:
            for row in product(*domains):
                value(cond, dict(zip(names, row)), functions)
    placed = set(occurring(doc))
    for c in doc.constraints:
        for x in (c.when, c.require, c.forbid):
            for a in selected_atoms(x):
                if a.path is None:
                    d = a.node.partition("/")[0]
                    if d not in placed:
                        raise AlgebraError(f"selected 가 가리키는 곳이 없다: {a.node}")
                    continue
                hosts = possible_members(doc, tuple(a.path))
                if not hosts:
                    raise AlgebraError(f"selected 가 가리키는 곳이 없다: {'/'.join(a.path)}")
                if all(selected_target(doc, a, y, a.node)[0] is None for y in hosts):
                    raise AlgebraError(f"selected 가 가리키는 선택지가 구성요소 {'/'.join(a.path)} 에 없다: "
                                       f"{a.node or '분해'}={a.choice}")


class Semantics:
    """정준 문서의 뜻. 정의 2에서 7을 그대로 옮겼다."""

    def __init__(self, doc: m.SesDocument, functions=None) -> None:
        validate(doc, functions)
        self.doc, self.functions = doc, functions
        self.root = doc.root.name
        self.names = list(doc.variables)

    # 변수 --------------------------------------------------------------

    def assignments(self) -> Iterator[dict]:
        for values in product(*(domain(self.doc, n) for n in self.names)):
            yield dict(zip(self.names, values))

    # 정의 2. 병합체 선택 -------------------------------------------------

    def alternatives(self, sp: m.Specialization, sigma: dict) -> list:
        """선택 규칙이 정하는 대안. 규칙이 정하지 않으면 모든 대안이다."""
        rule = sp.select
        while rule is not None:
            if value(rule.when, sigma, self.functions):
                return [rule.then]
            if isinstance(rule.otherwise, m.SelectRule):
                rule = rule.otherwise
            elif rule.otherwise is None:
                break
            else:
                return [rule.otherwise]
        return list(sp.alternatives)

    def members(self, d: str, sigma: dict) -> list:
        ent = self.doc.entities[d]
        options = [[(sp.name, sub) for alt in self.alternatives(sp, sigma) for sub in self.members(alt, sigma)]
                   for sp in ent.specializations.values()]
        return [Member(d, tuple(combo)) for combo in product(*options)]

    def removed(self, mu: Member) -> bool:
        return any(self.doc.entities[y].stereotype == m.Stereotype.VOID for y in mu.names())

    def owners(self, mu: Member) -> list:
        return [y for y in mu.names() if decompositions(self.doc.entities[y])]

    # 정의 3. 병합체의 분해 -----------------------------------------------

    def demands(self, y: str, sigma: dict) -> list:
        """구성원 y 가 낼 수 있는 요구들. 요구는 분해들의 묶음이다.

        참인 규칙이 없으면 자기 분해 가운데 하나를 고른다(요구가 분해마다 하나씩이다). 참인 규칙이 있으면
        고를 것이 없다. 규칙이 참인 분해 전부가 요구 하나다.
        """
        fams = decompositions(self.doc.entities[y])
        forced = [x for x in fams if x.rule is not None and value(x.rule, sigma, self.functions)]
        return [forced] if forced else [[x] for x in fams]

    def outcomes(self, owners: list, sigma: dict) -> tuple:
        """(Dec, Amb). 구성원들이 낸 요구의 조합마다, 다른 모든 분해보다 우선순위가 앞선 분해가 있으면 그것이
        그 병합체의 분해다. Dec 는 그렇게 정해질 수 있는 (구성원, 분해)들이고, Amb 는 그런 분해가 없는
        조합이 하나라도 있는가이다."""
        dec, ambiguous = [], False
        for combo in product(*(self.demands(y, sigma) for y in owners)):
            pool = [(y, x) for y, group in zip(owners, combo) for x in group]
            first = [(y, x) for y, x in pool if all(above(x.priority, w.priority) for _, w in pool if w is not x)]
            if not first:
                ambiguous = True
            elif first[0] not in dec:
                dec.append(first[0])
        order = {y: i for i, y in enumerate(owners)}
        dec.sort(key=lambda yx: (order[yx[0]], decompositions(self.doc.entities[yx[0]]).index(yx[1])))
        return dec, ambiguous

    def admissible(self, owners: list, sigma: dict) -> list:
        """Dec: 그 병합체의 분해가 될 수 있는 (구성원, 분해)들."""
        return self.outcomes(owners, sigma)[0]

    def outcomes_closed(self, owners: list, sigma: dict) -> tuple:
        """(Dec, Amb) 를 정리 2의 닫힌 꼴로 구한다. 요구의 조합을 늘어놓지 않으므로 주인의 수에 다항 시간이다.

        outcomes 와 같은 값을 낸다. outcomes 는 정의 3을 그대로 옮긴 것이고 이것은 계산에 쓰는 것이다.
        """
        fams = {y: decompositions(self.doc.entities[y]) for y in owners}
        top: dict = {}                               # 참인 규칙이 있는 주인에서, 그 규칙들의 분해 가운데 밀리지 않은 것들로
        for y in owners:
            forced = [x for x in fams[y] if x.rule is not None and value(x.rule, sigma, self.functions)]
            if forced:
                top[y] = [x for x in forced if not any(above(w.priority, x.priority) for w in forced)]
        allowed = {y: top.get(y, fams[y]) for y in owners}                               # A_y
        alone = {y: (top[y] if len(top[y]) == 1 else []) if y in top else fams[y] for y in owners}   # R_y
        dec = [(y, x) for y in owners for x in alone[y]
               if all(any(above(x.priority, w.priority) for w in allowed[z]) for z in owners if z != y)]
        ambiguous = False
        for c in {x.priority for y in owners for x in allowed[y]}:                        # 자리마다 (정리 2의 (c))
            if not all(any(not above(w.priority, c) for w in allowed[z]) for z in owners):
                continue                             # 어떤 주인은 c 보다 앞선 분해를 낼 수밖에 없다
            here = [y for y in owners if any(w.priority == c for w in allowed[y])]
            if len(here) >= 2 or any(y in top and len(top[y]) >= 2 and top[y][0].priority == c for y in owners):
                ambiguous = True
                break
        return dec, ambiguous

    def ties(self, owners: list, sigma: dict) -> list:
        """결과가 없는 요구의 조합 하나에서 맞서는 것들: (구성원, 분해)들. 그런 조합이 없으면 빈 목록."""
        for combo in product(*(self.demands(y, sigma) for y in owners)):
            pool = [(y, x) for y, group in zip(owners, combo) for x in group]
            if not any(all(above(x.priority, w.priority) for _, w in pool if w is not x) for _, x in pool):
                return [(y, x) for y, x in pool if not any(above(w.priority, x.priority) for _, w in pool)]
        return []

    def counts(self, ma: m.MultiAspect, sigma: dict) -> list:
        card = ma.cardinality
        if isinstance(card, m.Fixed):
            return [card.n]
        if isinstance(card, m.VarCard):
            return [sigma[card.var]]
        if card.max is None:
            raise AlgebraError(f"multi-aspect {ma.name} 의 개수에 상한이 필요하다")
        return list(range(card.min, card.max + 1))

    # 정의 4. 구성요소 선택 -----------------------------------------------

    def selections(self, d: str, sigma: dict, memo: Optional[dict] = None) -> list:
        memo = {} if memo is None else memo
        if d in memo:
            return memo[d]
        out: list = []
        for mu in self.members(d, sigma):
            if self.removed(mu):
                out.append(Comp(mu, GONE))
                continue
            owners = self.owners(mu)
            if not owners:
                out.append(Comp(mu, ATOM))
                continue
            dec, ambiguous = self.outcomes(owners, sigma)
            if ambiguous:
                out.append(Comp(mu, STUCK))                    # 분해를 정할 수 없는 요구의 조합이 있다
            for y, x in dec:
                if isinstance(x, m.Aspect):
                    names = [p.part_name for p in x.parts]
                    for combo in product(*(self.selections(p.def_name, sigma, memo) for p in x.parts)):
                        out.append(Comp(mu, SPLIT, y, x.name, None, tuple(zip(names, combo))))
                    continue
                below = self.selections(x.part.def_name, sigma, memo)
                for n in self.counts(x, sigma):
                    names = [replica_name(x, i, n) for i in range(n)]
                    for combo in product(below, repeat=n):
                        out.append(Comp(mu, SPLIT, y, x.name, n, tuple(zip(names, combo))))
        memo[d] = out
        return out

    # 정의 5. 한 선택들 ---------------------------------------------------

    def choices(self, kappa: Comp) -> set:
        """(구성요소 경로, 종류, 정의, 묶음, 선택지)들. 종류는 spec, aspect, count 다.

        대안을 고른 것은 빠진 구성요소에서도 한 선택이다. 분해와 개수는 분해를 고른 구성요소에만 있다.
        """
        out = set()
        for pos, c in kappa.walk((self.root,)):
            for mem in c.member.members():
                for s, sub in mem.picks:
                    out.add((pos, "spec", mem.name, s, sub.name))
            if c.state == SPLIT:
                out.add((pos, "aspect", c.owner, "", c.dec))
                if c.count is not None:
                    out.add((pos, "count", c.owner, c.dec, c.count))
        return out

    # 정의 6, 7. 제약과 변이 -----------------------------------------------

    def holds(self, e: Optional[m.Expr], sigma: dict, made: set) -> bool:
        """제약의 식. made 는 choices 가 낸 것이다."""
        if e is None:
            return True
        if isinstance(e, m.And):
            return all(self.holds(x, sigma, made) for x in e.items)
        if isinstance(e, m.Or):
            return any(self.holds(x, sigma, made) for x in e.items)
        if isinstance(e, m.Not):
            return not self.holds(e.item, sigma, made)
        if isinstance(e, m.Selected):
            if e.path is None:
                d, _, group = e.node.partition("/")
                kind, choice = selected_target(self.doc, e, d, group)
                return any(k == kind and y == d and g == group and c == choice for _, k, y, g, c in made)
            want = tuple(e.path)
            for pos, k, y, g, c in made:
                if pos != want:
                    continue
                kind, choice = selected_target(self.doc, e, y, e.node)
                if kind is not None and k == kind and (g, c) == ((e.node, choice) if kind != "aspect" else ("", choice)):
                    return True
            return False
        return bool(value(e, sigma, self.functions))

    def satisfied(self, c: m.Constraint, sigma: dict, made: set) -> bool:
        if not self.holds(c.when, sigma, made):
            return True
        return (c.require is None or self.holds(c.require, sigma, made)) \
            and (c.forbid is None or not self.holds(c.forbid, sigma, made))

    def variants(self) -> Iterator[tuple]:
        """Var(D): 제약을 만족하는 (변수 값, 뿌리의 구성요소 선택)."""
        late = [c for c in self.doc.constraints
                if any(selected_atoms(x) for x in (c.when, c.require, c.forbid))]
        early = [c for c in self.doc.constraints if c not in late]
        for sigma in self.assignments():
            if not all(self.satisfied(c, sigma, set()) for c in early):
                continue
            for kappa in self.selections(self.root, sigma):
                if not late or all(self.satisfied(c, sigma, self.choices(kappa)) for c in late):
                    yield sigma, kappa

    def well_formed(self, kappa: Comp) -> bool:
        """핵 적격: 뿌리가 빠지지 않았고 분해를 정할 수 없는 구성요소가 없다."""
        return kappa.state != GONE and all(c.state != STUCK for _, c in kappa.walk((self.root,)))

    # 정리 5. 펼친 나무에서의 표현 -------------------------------------------

    def nodes(self, sigma: dict, kappa: Comp) -> frozenset:
        """그 변이가 펼친 나무에서 고르는 노드들.

        병합체의 구성원 가운데 분해를 가진 것은 저마다 하나를 고른다. 분해를 낸 구성원은 그 분해를,
        빠진 구성요소의 구성원은 "빠짐"(-)을, 나머지는 "분해 없음"(~)을 고른다.
        """
        out = set()
        for name, v in sigma.items():
            out |= {(self.root, "$" + name), (self.root, "$" + name, str(v))}

        def member(mu: Member, at: tuple, c: Comp) -> None:
            out.add(at)
            ent = self.doc.entities[mu.name]
            if decompositions(ent):
                if c.state == GONE:
                    out.add(at + ("-",))
                elif c.state == SPLIT and c.owner == mu.name:
                    a = at + (c.dec if c.count is None else f"{c.dec}[{c.count}]",)
                    out.add(a)
                    for part, sub in c.parts:
                        comp(sub, a + (part,))
                else:
                    out.add(at + ("~",))
            for s, sub in mu.picks:
                out.add(at + (s,))
                member(sub, at + (s, sub.name), c)

        def comp(c: Comp, at: tuple) -> None:
            member(c.member, at, c)

        comp(kappa, (self.root,))
        return frozenset(out)

    # 정의 8. 실현 구조 ---------------------------------------------------

    def shape(self, kappa: Comp):
        """핵 적격인 변이의 구조 (정의 8): (합쳐진 정의들, 고른 분해, 부분들).

        고른 분해는 (그것을 낸 구성원, 분해의 이름)이고, 분해가 없는 구성요소에서는 None 이다.
        부분들은 적힌 순서의 (이름, 그 부분의 구조)다. 빠진 부분은 이름만 남고 구조의 자리에 None 이 온다.
        빠진 부분의 이름을 남기는 까닭은 결합이 그것을 보기 때문이다. 개수 2 에서 둘째 복제본이 빠진 것과
        개수 1 은 살아 있는 부분이 같아도 결합이 다르다. multi-aspect 의 개수는 부분의 수다.
        """
        if kappa.state == GONE:
            return None
        kids = tuple((name, self.shape(c)) for name, c in kappa.parts)
        chosen = (kappa.owner, kappa.dec) if kappa.state == SPLIT else None
        return tuple(sorted(kappa.member.names())), chosen, kids


def live_shape(shape):
    """구조에서 고른 분해의 이름과 빠진 부분을 잊은 것: (합쳐진 정의들, 살아 있는 부분들).

    문헌의 절차가 내는 구조에는 그 둘이 없다. 그것과 견줄 때 쓴다.
    """
    names, _, kids = shape
    return names, tuple((name, live_shape(k)) for name, k in kids if k is not None)


# ---------------------------------------------------------------------------
# 정리 3. 열거하지 않는 계산
#
# 값은 "본 것들의 집합에서 (개수, 일어난 일들)로 가는 사전"이다. 본 것은 제약이 묻는 선택(selected)과,
# 부적격을 뜻하는 표지 ILL 이다. 개수는 본 것이 정확히 그 집합인 구성요소 선택의 수이고, 일어난 일들은
# 그 선택들 가운데 하나에서라도 일어난 일(대안, 분해, 개수의 선택과 부적격의 원인)의 집합이다.
# 두 값의 곱은 본 것의 합집합끼리 개수를 곱하고 일을 합친 것이고, 합은 개수를 더하고 일을 합친 것이다.
# 개수가 0 인 항은 두지 않는다. 이것은 교환 반환을 이루고(theory.md 4절), 변이의 집합에 대한 합이
# 이 반환에서 정의 표 위의 식으로 계산된다. 일을 따라가지 않을 때는 일의 자리에 None 을 둔다.
# ---------------------------------------------------------------------------

ILL = ("ill",)
ROOT_GONE = ("root-gone",)
ONE = {frozenset(): (1, None)}                 # 일을 따라가지 않는 계산의 1
ONE_LIVE = {frozenset(): (1, frozenset())}     # 일을 따라가는 계산의 1


def c_add(a: tuple, b: tuple) -> tuple:
    return a[0] + b[0], (None if a[1] is None else a[1] | b[1])


def c_mul(a: tuple, b: tuple) -> tuple:
    return a[0] * b[0], (None if a[1] is None else a[1] | b[1])


def p_add(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = c_add(out[k], v) if k in out else v
    return out


def p_mul(a: dict, b: dict) -> dict:
    if a is ONE or a is ONE_LIVE:
        return b
    if b is ONE or b is ONE_LIVE:
        return a
    out: dict = {}
    for ka, va in a.items():
        for kb, vb in b.items():
            k = ka | kb
            v = c_mul(va, vb)
            out[k] = c_add(out[k], v) if k in out else v
    return out


def p_pow(a: dict, n: int, one: dict) -> dict:
    out, base = one, a
    while n:
        if n & 1:
            out = p_mul(out, base)
        n >>= 1
        if n:
            base = p_mul(base, base)
    return out


def p_seen(a: dict, atoms=(), events=()) -> dict:
    """모든 항이 atoms 를 보았고 그 선택들에서 events 가 일어났다고 적는다."""
    atoms, events = frozenset(atoms), frozenset(events)
    if not atoms and not events:
        return a
    out: dict = {}
    for k, (n, live) in a.items():
        v = (n, None if live is None else live | events)
        out[k | atoms] = c_add(out[k | atoms], v) if (k | atoms) in out else v
    return out


class Evaluator:
    """정의 표 위에서 변이에 대한 합을 구한다. 변이를 열거하지 않는다.

    live 가 참이면 변이들에서 일어난 일(어떤 선택지가 쓰였는가, 어디서 분해를 정할 수 없는가)도 함께 모은다.
    """

    def __init__(self, doc: m.SesDocument, functions=None, live: bool = False) -> None:
        self.sem = Semantics(doc, functions)
        self.doc = doc
        self.one = ONE_LIVE if live else ONE
        self.live = live
        self.late = [c for c in doc.constraints if any(selected_atoms(x) for x in (c.when, c.require, c.forbid))]
        self.early = [c for c in doc.constraints if c not in self.late]
        atoms = [a for c in self.late for x in (c.when, c.require, c.forbid) for a in selected_atoms(x)]
        self.by_def: dict = {}                    # (종류, 정의, 묶음, 선택지)에서 그것을 묻는 selected 들로
        self.by_path: dict = {}                   # 구성요소 경로에서 그 자리를 묻는 selected 들로
        for a in atoms:
            if a.path is None:
                d, _, group = a.node.partition("/")
                kind, choice = selected_target(doc, a, d, group)
                self.by_def.setdefault((kind, d, group if kind != "aspect" else "", choice), set()).add(a)
            else:
                self.by_path.setdefault(tuple(a.path), set()).add(a)
        self.focus = {q[:i] for q in self.by_path for i in range(1, len(q) + 1)}   # 따로 계산해야 하는 자리들
        self.below: dict = {}                     # 따로 계산해야 하는 자리에서, 그 바로 아래의 그런 자리의 이름들로
        for q in self.focus:
            if len(q) > 1:
                self.below.setdefault(q[:-1], set()).add(q[-1])

    # 한 선택이 보게 하는 것 ------------------------------------------------

    def seen(self, pos: tuple, kind: str, d: str, group: str, choice) -> frozenset:
        out = set(self.by_def.get((kind, d, group, choice), ()))
        for a in self.by_path.get(pos, ()):
            k, c = selected_target(self.doc, a, d, a.node)
            if k is not None and k == kind and (group, choice) == ((a.node, c) if k != "aspect" else ("", c)):
                out.add(a)
        return frozenset(out)

    def mark(self, p: dict, pos: tuple, kind: str, d: str, group: str, choice) -> dict:
        """그 선택을 한 항들에, 제약이 묻는 것과 일어난 일을 적는다."""
        return p_seen(p, self.seen(pos, kind, d, group, choice), [(kind, d, group, choice)] if self.live else ())

    def ill(self, event: tuple) -> dict:
        return {frozenset([ILL]): (1, frozenset([event]) if self.live else None)}

    # 병합체: (빠졌는가, 분해를 가진 구성원들)에서 값으로 --------------------------

    def cluster(self, d: str, pos: tuple, sigma: dict, memo: dict) -> dict:
        # 대안의 선택이 보게 하는 것은 그 자리를 가리키는 selected 가 있을 때만 자리에 달려 있다
        key = ("cluster", d, pos if pos in self.by_path else None)
        if key not in memo:
            memo[key] = self._cluster(d, pos, sigma, memo)
        return memo[key]

    def _cluster(self, d: str, pos: tuple, sigma: dict, memo: dict) -> dict:
        ent = self.doc.entities[d]
        sig = (ent.stereotype == m.Stereotype.VOID, frozenset([d]) if decompositions(ent) else frozenset())
        acc = {sig: self.one}
        for sp in ent.specializations.values():
            options: dict = {}
            for alt in self.sem.alternatives(sp, sigma):
                for s, p in self.cluster(alt, pos, sigma, memo).items():
                    q = self.mark(p, pos, "spec", d, sp.name, alt)
                    options[s] = p_add(options[s], q) if s in options else q
            nxt: dict = {}
            for (g1, o1), p1 in acc.items():
                for (g2, o2), p2 in options.items():
                    key = (g1 or g2, o1 | o2)
                    q = p_mul(p1, p2)
                    nxt[key] = p_add(nxt[key], q) if key in nxt else q
            acc = nxt
        return acc

    # 구성요소 ----------------------------------------------------------------

    def comp(self, d: str, pos: tuple, sigma: dict, memo: dict) -> dict:
        # 이 자리 아래를 따로 묻는 제약이 없으면 정의마다 한 번만 센다. 있으면 자리마다 한 번 센다
        key = (d, pos) if pos in self.focus else d
        if key not in memo:
            memo[key] = self._comp(d, pos, sigma, memo)
        return memo[key]

    def decided(self, owners: frozenset, sigma: dict, memo: dict) -> tuple:
        key = ("dec", owners)
        if key not in memo:
            memo[key] = self.sem.outcomes_closed(sorted(owners), sigma)
        return memo[key]

    def _comp(self, d: str, pos: tuple, sigma: dict, memo: dict) -> dict:
        total: dict = {}
        for (gone, owners), p in self.cluster(d, pos, sigma, memo).items():
            if gone:
                body = self.ill(ROOT_GONE) if len(pos) == 1 else self.one     # 뿌리가 빠지면 부적격이다
            elif not owners:
                body = self.one
            else:
                dec, ambiguous = self.decided(owners, sigma, memo)
                body = self.ill(("stuck", d, tuple(sorted(owners)))) if ambiguous else {}   # 분해를 정할 수 없는 조합이 있다
                for y, x in dec:
                    pushed = [("pushed", z) for z in owners if z != y] if self.live else ()   # 분해를 내지 않은 주인들
                    if isinstance(x, m.Aspect):
                        inner = self.one
                        for part in x.parts:
                            inner = p_mul(inner, self.comp(part.def_name, pos + (part.part_name,), sigma, memo))
                        body = p_add(body, p_seen(self.mark(inner, pos, "aspect", y, "", x.name), (), pushed))
                        continue
                    # 복제본들은 서로 같다. 따로 세야 하는 자리의 복제본만 하나씩 세고 나머지는 거듭제곱한다.
                    # 그런 자리가 없으면 복제본의 이름을 만들지도 않는다. 개수가 이어지면 앞의 거듭제곱을 이어 쓴다
                    watched = self.below.get(pos, ())
                    one = self.comp(x.part.def_name, pos + ("",), sigma, memo) if not watched else None
                    power, at = self.one, 0
                    for n in sorted(self.sem.counts(x, sigma)):
                        if watched:
                            names = [replica_name(x, i, n) for i in range(n)]
                            special = [nm for nm in names if nm in watched]
                            inner = self.one
                            for nm in special:
                                inner = p_mul(inner, self.comp(x.part.def_name, pos + (nm,), sigma, memo))
                            if len(special) < n:
                                plain = next(nm for nm in names if nm not in watched)
                                rest = self.comp(x.part.def_name, pos + (plain,), sigma, memo)
                                inner = p_mul(inner, p_pow(rest, n - len(special), self.one))
                        else:
                            power, at = p_mul(power, p_pow(one, n - at, self.one)), n
                            inner = power
                        inner = self.mark(inner, pos, "count", y, x.name, n)
                        body = p_add(body, p_seen(self.mark(inner, pos, "aspect", y, "", x.name), (), pushed))
            q = p_mul(p, body)
            total = p_add(total, q) if total else q
        return total

    # 뿌리 --------------------------------------------------------------------

    def roots(self):
        """제약(변수만 보는 것)을 통과한 변수 값마다, 제약을 만족하는 항들: (변수 값, [(본 것, 개수, 일들)])."""
        sem = self.sem
        for sigma in sem.assignments():
            if not all(sem.satisfied(c, sigma, set()) for c in self.early):
                continue
            yield sigma, [(seen, n, live) for seen, (n, live) in self.comp(sem.root, (sem.root,), sigma, {}).items()
                          if all(self._satisfied(c, sigma, seen) for c in self.late)]

    def per_assignment(self):
        """(변수 값, 변이 수, 적격 변이 수)들. 제약을 어기는 변이는 세지 않는다."""
        for sigma, terms in self.roots():
            yield sigma, sum(n for _, n, _ in terms), sum(n for seen, n, _ in terms if ILL not in seen)

    def _satisfied(self, c: m.Constraint, sigma: dict, seen: frozenset) -> bool:
        def holds(e) -> bool:
            if e is None:
                return True
            if isinstance(e, m.And):
                return all(holds(x) for x in e.items)
            if isinstance(e, m.Or):
                return any(holds(x) for x in e.items)
            if isinstance(e, m.Not):
                return not holds(e.item)
            if isinstance(e, m.Selected):
                return e in seen
            return bool(value(e, sigma, self.sem.functions))

        if not holds(c.when):
            return True
        return (c.require is None or holds(c.require)) and (c.forbid is None or not holds(c.forbid))

    def count(self) -> tuple:
        """(변이 수, 적격 변이 수)."""
        total = wf = 0
        for _, n, w in self.per_assignment():
            total += n
            wf += w
        return total, wf


def count(doc: m.SesDocument, functions=None) -> tuple:
    """(변이 수, 핵 적격 변이 수). 변이를 열거하지 않는다."""
    return Evaluator(doc, functions).count()


# ---------------------------------------------------------------------------
# 족 수준의 분석 (핵). 변이를 열거하지 않는다
# ---------------------------------------------------------------------------

def reachable(doc: m.SesDocument) -> list:
    """뿌리에서 쓰임 관계로 닿는 정의들. 문서에 적힌 순서."""
    seen, stack = set(), [doc.root.name]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        e = doc.entities[name]
        stack += [p.def_name for a in e.aspects.values() for p in a.parts]
        stack += [ma.part.def_name for ma in e.multi_aspects.values()]
        stack += [alt for sp in e.specializations.values() for alt in sp.alternatives]
    return [name for name in doc.entities if name in seen]


def points(doc: m.SesDocument) -> list:
    """문서가 적은 선택 지점들: (종류, 정의 또는 변수, 묶음, 선택지들). 뿌리에서 닿는 정의의 것만.

    종류는 variable, spec, aspect, count 다. 선택지가 하나뿐인 것도 든다.
    """
    out = [("variable", name, "", tuple(domain(doc, name))) for name in doc.variables]
    for name in reachable(doc):
        e = doc.entities[name]
        for sp in e.specializations.values():
            out.append(("spec", name, sp.name, tuple(sp.alternatives)))
        if decompositions(e):
            out.append(("aspect", name, "", tuple(x.name for x in decompositions(e))))
        for ma in e.multi_aspects.values():
            card = ma.cardinality
            counts = [card.n] if isinstance(card, m.Fixed) else domain(doc, card.var) if isinstance(card, m.VarCard) \
                else [] if card.max is None else list(range(card.min, card.max + 1))
            out.append(("count", name, ma.name, tuple(counts)))
    return out


def declared(doc: m.SesDocument) -> list:
    """문서가 적은 선택지들: (종류, 정의, 묶음, 선택지). 변수의 값은 들지 않는다."""
    return [(kind, owner, group, option) for kind, owner, group, options in points(doc) if kind != "variable"
            for option in options]


@dataclass
class Family:
    """문서의 족에 대해 정의 표 위에서 구한 것."""
    assignments: int                  # 변수만 보는 제약을 통과한 변수 값의 수
    variants: int                     # 변이의 수
    wellformed: int                   # 핵 적격인 변이의 수
    live: frozenset                   # 어떤 변이에서 일어난 일들
    live_wf: frozenset                # 어떤 핵 적격 변이에서 일어난 일들
    values: dict                      # 변수 이름에서 (변이가 있는 값들, 핵 적격 변이가 있는 값들)로
    examples: dict                    # 부적격의 원인(ROOT_GONE 또는 ("stuck", 정의, 주인들))에서 그것이 일어난 변수 값 하나로

    def dead(self, doc: m.SesDocument) -> list:
        """핵 적격인 변이에 나타나지 않는 선택지: (종류, 정의, 묶음, 선택지, 어떤 변이에는 나타나는가)."""
        out = [c + (c in self.live,) for c in declared(doc) if c not in self.live_wf]
        for name in doc.variables:
            some, good = self.values.get(name, (set(), set()))
            out += [("variable", name, "", v, v in some) for v in domain(doc, name) if v not in good]
        return out


def analyze(doc: m.SesDocument, functions=None) -> Family:
    """변이 수, 핵 적격 변이 수, 살아 있는 선택지, 분해를 정할 수 없는 곳. 변이를 열거하지 않는다."""
    ev = Evaluator(doc, functions, live=True)
    assignments = variants = wellformed = 0
    live, live_wf = set(), set()
    values = {name: (set(), set()) for name in doc.variables}
    examples: dict = {}
    for sigma, terms in ev.roots():
        assignments += 1
        for seen, n, events in terms:
            variants += n
            live |= events
            for name, v in sigma.items():
                values[name][0].add(v)
            if ILL in seen:
                for e in events:
                    if e == ROOT_GONE or e[0] == "stuck":
                        examples.setdefault(e, dict(sigma))
            else:
                wellformed += n
                live_wf |= events
                for name, v in sigma.items():
                    values[name][1].add(v)
    return Family(assignments, variants, wellformed, frozenset(live), frozenset(live_wf), values, examples)
