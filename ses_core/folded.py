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

class Semantics:
    """정준 문서의 뜻. 정의 2에서 7을 그대로 옮겼다."""

    def __init__(self, doc: m.SesDocument, functions=None) -> None:
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
        고를 것이 없다. 그 규칙들의 분해 가운데 우선순위에서 밀리지 않은 것 전부가 요구 하나다.
        """
        fams = decompositions(self.doc.entities[y])
        forced = [x for x in fams if x.rule is not None and value(x.rule, sigma, self.functions)]
        if not forced:
            return [[x] for x in fams]
        return [[x for x in forced if not any(above(w.priority, x.priority) for w in forced)]]

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
        """적격 변이의 구조: (합쳐진 정의들, 고른 분해, 살아 있는 부분들의 구조). 빠진 부분은 없다."""
        if kappa.state == GONE:
            return None
        kids = tuple((name, self.shape(c)) for name, c in kappa.parts if c.state != GONE)
        return tuple(sorted(kappa.member.names())), kids


# ---------------------------------------------------------------------------
# 정리 3. 열거하지 않는 계산
#
# 값은 "본 것들의 집합에서 개수로 가는 사전"이다. 본 것은 제약이 묻는 선택(selected)과, 부적격을 뜻하는
# 표지 ILL 이다. 두 값의 곱은 본 것의 합집합끼리 개수를 곱해 더한 것이고, 합은 개수를 더한 것이다.
# 이것은 교환 반환을 이루고, 변이의 집합은 이 반환에서 정의 표 위의 식으로 계산된다.
# ---------------------------------------------------------------------------

ILL = ("ill",)
ONE = {frozenset(): 1}


def p_add(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def p_mul(a: dict, b: dict) -> dict:
    if a is ONE:
        return b
    if b is ONE:
        return a
    out: dict = {}
    for ka, va in a.items():
        for kb, vb in b.items():
            k = ka | kb
            out[k] = out.get(k, 0) + va * vb
    return out


def p_pow(a: dict, n: int) -> dict:
    out, base = ONE, a
    while n:
        if n & 1:
            out = p_mul(out, base)
        n >>= 1
        if n:
            base = p_mul(base, base)
    return out


def p_seen(a: dict, atoms) -> dict:
    """모든 항이 atoms 를 보았다고 적는다."""
    atoms = frozenset(atoms)
    if not atoms:
        return a
    out: dict = {}
    for k, v in a.items():
        out[k | atoms] = out.get(k | atoms, 0) + v
    return out


class Evaluator:
    """정의 표 위에서 변이의 수를 구한다. 변이를 열거하지 않는다."""

    def __init__(self, doc: m.SesDocument, functions=None) -> None:
        self.sem = Semantics(doc, functions)
        self.doc = doc
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

    # 한 선택이 보게 하는 것 ------------------------------------------------

    def seen(self, pos: tuple, kind: str, d: str, group: str, choice) -> frozenset:
        out = set(self.by_def.get((kind, d, group, choice), ()))
        for a in self.by_path.get(pos, ()):
            k, c = selected_target(self.doc, a, d, a.node)
            if k is not None and k == kind and (group, choice) == ((a.node, c) if k != "aspect" else ("", c)):
                out.add(a)
        return frozenset(out)

    # 병합체: (빠졌는가, 분해를 가진 구성원들)에서 값으로 --------------------------

    def cluster(self, d: str, pos: tuple, sigma: dict) -> dict:
        ent = self.doc.entities[d]
        sig = (ent.stereotype == m.Stereotype.VOID, frozenset([d]) if decompositions(ent) else frozenset())
        acc = {sig: ONE}
        for sp in ent.specializations.values():
            options: dict = {}
            for alt in self.sem.alternatives(sp, sigma):
                saw = self.seen(pos, "spec", d, sp.name, alt)
                for s, p in self.cluster(alt, pos, sigma).items():
                    options[s] = p_add(options.get(s, {}), p_seen(p, saw))
            nxt: dict = {}
            for (g1, o1), p1 in acc.items():
                for (g2, o2), p2 in options.items():
                    key = (g1 or g2, o1 | o2)
                    nxt[key] = p_add(nxt.get(key, {}), p_mul(p1, p2))
            acc = nxt
        return acc

    # 구성요소 ----------------------------------------------------------------

    def comp(self, d: str, pos: tuple, sigma: dict, memo: dict) -> dict:
        shared = pos not in self.focus               # 이 자리 아래를 따로 묻는 제약이 없으면 정의마다 한 번만 센다
        if shared and d in memo:
            return memo[d]
        total: dict = {}
        for (gone, owners), p in self.cluster(d, pos, sigma).items():
            if gone:
                body = {frozenset([ILL]): 1} if len(pos) == 1 else ONE     # 뿌리가 빠지면 부적격이다
            elif not owners:
                body = ONE
            else:
                dec, ambiguous = self.sem.outcomes(sorted(owners), sigma)
                body = {frozenset([ILL]): 1} if ambiguous else {}              # 분해를 정할 수 없는 조합이 있다
                if dec:
                    for y, x in dec:
                        saw = self.seen(pos, "aspect", y, "", x.name)
                        if isinstance(x, m.Aspect):
                            inner = ONE
                            for part in x.parts:
                                inner = p_mul(inner, self.comp(part.def_name, pos + (part.part_name,), sigma, memo))
                            body = p_add(body, p_seen(inner, saw))
                            continue
                        for n in self.sem.counts(x, sigma):
                            names = [replica_name(x, i, n) for i in range(n)]
                            special = [nm for nm in names if pos + (nm,) in self.focus]
                            inner = ONE
                            for nm in special:
                                inner = p_mul(inner, self.comp(x.part.def_name, pos + (nm,), sigma, memo))
                            if len(special) < n:                           # 나머지 복제본은 서로 같다
                                plain = next(nm for nm in names if pos + (nm,) not in self.focus)
                                one = self.comp(x.part.def_name, pos + (plain,), sigma, memo)
                                inner = p_mul(inner, p_pow(one, n - len(special)))
                            body = p_add(body, p_seen(inner, saw | self.seen(pos, "count", y, x.name, n)))
            total = p_add(total, p_mul(p, body))
        if shared:
            memo[d] = total
        return total

    # 뿌리 --------------------------------------------------------------------

    def per_assignment(self) -> Iterator[tuple]:
        """(변수 값, 변이 수, 적격 변이 수)들. 제약을 어기는 변이는 세지 않는다."""
        sem = self.sem
        for sigma in sem.assignments():
            if not all(sem.satisfied(c, sigma, set()) for c in self.early):
                continue
            total = wf = 0
            for seen, n in self.comp(sem.root, (sem.root,), sigma, {}).items():
                if all(self._satisfied(c, sigma, seen) for c in self.late):
                    total += n
                    if ILL not in seen:
                        wf += n
            yield sigma, total, wf

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
