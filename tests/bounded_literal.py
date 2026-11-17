"""theory.md 의 정의 9 와 10 을 글에서 그대로 옮겨 적은 것.

literal_tree(doc)            T(D) 의 노드의 종류와 표지            (정의 9)
literal_variants(doc)        (T(D), Psi(D)) 의 변이                (5.1절과 정의 10)

ses_core.unfold 와 ses_core.skeleton 을 부르지 않는다. 적재한 문서(model), 우선순위의 순서 above 와 변수에 대한
조건의 평가(folded.py), 그리고 (V1)에서 (V4)를 위한 algebra.variants 만 쓴다. Psi(D) 는 식으로 만들지 않고
노드 집합 위에서 항목마다 평가한다. 구현이 (Phi)에 더 붙이는 "살아 있다"는 조건은 여기에 넣지 않는다
(글은 그 조건이 늘 참이라고 한다). 독립된 검토에서 만든 것을 저장소로 옮겼다. 펼침의 구현과 견주는 데 쓴다.
"""

from __future__ import annotations

from itertools import product

from ses_core import folded as F
from ses_core import model as m
from ses_core.algebra import ASP, ENT, SPEC, Tree, variants

above = F.above


def same_place(p, q) -> bool:
    return not above(p, q) and not above(q, p)


def counts_any_sigma(doc, x) -> list:
    """어떤 sigma 에서 Cnt(x, sigma) 에 드는 n 들."""
    c = x.cardinality
    if isinstance(c, m.Fixed):
        return [c.n]
    if isinstance(c, m.VarCard):
        return list(F.domain(doc, c.var))
    return list(range(c.min, c.max + 1))


def replica(x, i: int, n: int) -> str:
    return x.naming.format(i=i, n=n, part=x.part.part_name)


class Literal:
    def __init__(self, doc, functions=None) -> None:
        self.doc, self.functions = doc, functions
        self.ents = doc.entities
        self.r = doc.root.name
        self.kinds: dict = {}
        self.labels: dict = {}
        self._tree()

    # 정의 9 ---------------------------------------------------------------

    def _ent(self, d: str, u: tuple) -> None:
        self.kinds[u] = ENT
        self.labels[u] = d
        e = self.ents[d]
        for s in e.specializations.values():
            self.kinds[u + (s.name,)] = SPEC
            for a in s.alternatives:
                self._ent(a, u + (s.name, a))
        for x in e.aspects.values():
            self.kinds[u + (x.name,)] = ASP
            for p in x.parts:
                self._ent(p.def_name, u + (x.name, p.part_name))
        for x in e.multi_aspects.values():
            for n in counts_any_sigma(self.doc, x):
                a = u + (f"{x.name}[{n}]",)
                self.kinds[a] = ASP
                for i in range(n):
                    self._ent(x.part.def_name, a + (replica(x, i, n),))

    def decs(self, d: str) -> list:
        e = self.ents[d]
        return list(e.aspects.values()) + list(e.multi_aspects.values())

    def is_void(self, y: tuple) -> bool:
        return self.ents[self.labels[y]].stereotype == m.Stereotype.VOID

    def has_dec(self, y: tuple) -> bool:
        return bool(self.decs(self.labels[y]))

    def member_nodes(self, e: tuple) -> list:
        """e 와, 구성원 노드 y 마다의 y/s/a 꼴의 노드들."""
        out = [e]
        for s in self.ents[self.labels[e]].specializations.values():
            for a in s.alternatives:
                out += self.member_nodes(e + (s.name, a))
        return out

    def together(self, y: tuple, z: tuple) -> bool:
        """한 specialization 노드의 서로 다른 자식 아래에 있지 않다."""
        for i in range(1, min(len(y), len(z))):
            n = y[:i]
            if z[:i] == n and self.kinds[n] == SPEC and y[i] != z[i]:
                return False
        return True

    def _tree(self) -> None:
        self._ent(self.r, (self.r,))
        self.components = [u for u in self.labels if len(u) == 1 or self.kinds[u[:-1]] == ASP]
        self.members = {e: self.member_nodes(e) for e in self.components}
        for e in self.components:
            mem = self.members[e]
            for y in mem:
                if not self.has_dec(y):
                    continue
                if any(self.is_void(z) and self.together(y, z) for z in mem):
                    self.kinds[y + ("-",)] = ASP
                ruled = [x for x in self.decs(self.labels[y]) if x.rule is not None]
                if any(z != y and self.has_dec(z) and self.together(y, z) for z in mem) or \
                        any(same_place(a.priority, b.priority) for i, a in enumerate(ruled) for b in ruled[i + 1:]):
                    self.kinds[y + ("~",)] = ASP
        for x in self.doc.variables:
            self.kinds[(self.r, "$" + x)] = SPEC
            for c in F.domain(self.doc, x):
                self.kinds[(self.r, "$" + x, str(c))] = ENT

    # 정의 10 --------------------------------------------------------------

    def dec_nodes(self, y: tuple, x) -> list:
        if isinstance(x, m.Aspect):
            return [y + (x.name,)]
        return [y + (f"{x.name}[{n}]",) for n in counts_any_sigma(self.doc, x)]

    def select(self, sp, tau: dict):
        """선택 규칙이 tau 에서 내는 것: 대안 하나 또는 None."""
        rule = sp.select
        while rule is not None:
            if F.value(rule.when, tau, self.functions):
                return rule.then
            if isinstance(rule.otherwise, m.SelectRule):
                rule = rule.otherwise
            elif rule.otherwise is None:
                return None
            else:
                return rule.otherwise
        return None

    def demand_sets(self, d: str, tau: dict) -> tuple:
        """정리 2 와 정의 3 의 (A_y, R_y, y 가 낼 수 있는 요구들)."""
        fams = self.decs(d)
        forced = [x for x in fams if x.rule is not None and F.value(x.rule, tau, self.functions)]
        if not forced:
            return fams, fams, [[x] for x in fams]
        top = [x for x in forced if not any(above(w.priority, x.priority) for w in forced if w is not x)]
        return top, (top if len(top) == 1 else []), [top]

    def amb(self, owners: list, tau: dict) -> bool:
        """owners 의 정의들에 대한 정리 2 의 (c)."""
        demands = {d: self.demand_sets(d, tau)[2] for d in owners}
        for c in {x.priority for d in owners for x in self.decs(d)}:
            fine = {d: [g for g in demands[d] if not any(above(x.priority, c) for x in g)] for d in owners}
            if not all(fine.values()):
                continue
            if any(sum(same_place(x.priority, c) for x in g) >= 2 for d in owners for g in fine[d]):
                return True
            if sum(any(same_place(x.priority, c) for g in fine[d] for x in g) for d in owners) >= 2:
                return True
        return False

    def component_path(self, e: tuple) -> tuple:
        """노드의 경로에서 aspect, specialization, 대안의 이름을 뺀 것."""
        out = [e[0]]
        for i in range(1, len(e)):
            if self.kinds[e[:i + 1]] == ENT and self.kinds[e[:i]] == ASP:
                out.append(e[i])
        return tuple(out)

    def pointed(self, e: m.Selected) -> list:
        """selected 가 가리키는 노드들."""
        if e.path is None:
            d, _, group = e.node.partition("/")
            hosts = [u for u, lab in self.labels.items() if lab == d]
        else:
            group = e.node
            hosts = [u for c in self.components if self.component_path(c) == tuple(e.path) for u in self.members[c]]
        out = []
        for u in hosts:
            ent = self.ents[self.labels[u]]
            if not group:
                for x in self.decs(self.labels[u]):
                    if x.name == e.choice:
                        out += self.dec_nodes(u, x)
            elif group in ent.specializations:
                if e.choice in ent.specializations[group].alternatives:
                    out.append(u + (group, e.choice))
            elif group in ent.multi_aspects:
                try:
                    out.append(u + (f"{group}[{int(e.choice)}]",))
                except (TypeError, ValueError):
                    pass
        return out

    def expr(self, e, taus: list, V: frozenset) -> bool:
        if e is None:
            return True
        if isinstance(e, m.And):
            return all(self.expr(x, taus, V) for x in e.items)
        if isinstance(e, m.Or):
            return any(self.expr(x, taus, V) for x in e.items)
        if isinstance(e, m.Not):
            return not self.expr(e.item, taus, V)
        if isinstance(e, m.Selected):
            return any(n in V for n in self.pointed(e))
        return any(F.value(e, tau, self.functions) for tau in taus)            # [g]

    def psi(self, V: frozenset) -> bool:
        doc, r = self.doc, self.r
        names = list(doc.variables)
        # [g]: "g 를 참으로 만드는 어떤 변수 값에 대해, 그 값의 노드들이 골라졌다"
        taus = [dict(zip(names, vals)) for vals in product(*(F.domain(doc, n) for n in names))
                if all((r, "$" + n, str(v)) in V for n, v in zip(names, vals))]

        def cond(test) -> bool:
            return any(test(tau) for tau in taus)

        for u in V:
            k = self.kinds[u]
            if k == SPEC and not u[-1].startswith("$"):                           # (S)
                sp = self.ents[self.labels[u[:-1]]].specializations[u[-1]]
                if sp.select is not None:
                    for a in sp.alternatives:
                        if cond(lambda tau: self.select(sp, tau) == a) and u + (a,) not in V:
                            return False
            if k == ENT and u in self.labels:                                     # (N)
                for x in self.ents[self.labels[u]].multi_aspects.values():
                    if isinstance(x.cardinality, m.VarCard):
                        for n in counts_any_sigma(doc, x):
                            if u + (f"{x.name}[{n}]",) in V and (r, "$" + x.cardinality.var, str(n)) not in V:
                                return False
        for e in self.components:
            mem = self.members[e]
            removed = any(z in V and self.is_void(z) for z in mem)
            owners = [y for y in mem if self.has_dec(y)]
            for y in owners:
                gone = y + ("-",)
                if gone in self.kinds:
                    if y in V and removed and gone not in V:                      # (G1)
                        return False
                    if gone in V and not removed:                                 # (G2)
                        return False
                for x in self.decs(self.labels[y]):                               # (C1)
                    if not any(n in V for n in self.dec_nodes(y, x)):
                        continue
                    wins = y in V and cond(lambda tau: any(x is w for w in self.demand_sets(self.labels[y], tau)[1]))
                    for z in owners:
                        if z != y and self.together(y, z) and z in V:
                            wins = wins and cond(lambda tau: any(above(x.priority, w.priority)
                                                                 for w in self.demand_sets(self.labels[z], tau)[0]))
                    if not wins:
                        return False
            chose = {y: any(n in V for x in self.decs(self.labels[y]) for n in self.dec_nodes(y, x)) for y in owners}
            for i, y in enumerate(owners):                                        # (C3)
                for z in owners[i + 1:]:
                    if self.together(y, z) and chose[y] and chose[z]:
                        return False
            if not removed and any(y in V for y in owners) and not any(chose.values()):   # (C2)
                if not cond(lambda tau: self.amb([self.labels[y] for y in owners if y in V], tau)):
                    return False
        for c in doc.constraints:                                                 # (Phi)
            if not self.expr(c.when, taus, V):
                continue
            if not self.expr(c.require, taus, V) or (c.forbid is not None and self.expr(c.forbid, taus, V)):
                return False
        return True

    def variants(self) -> list:
        T = Tree(dict(self.kinds), dict(self.labels))
        return [V for V in variants(T) if self.psi(V)]


def literal_tree(doc, functions=None) -> tuple:
    lit = Literal(doc, functions)
    return lit.kinds, lit.labels


def literal_variants(doc, functions=None) -> list:
    return Literal(doc, functions).variants()
