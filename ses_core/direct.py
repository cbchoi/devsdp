"""결정이 끝난 변이 하나를 위에서 아래로 만든다 (docs/ses-platform/18_classic_parity.md 5절).

족 전체를 다루는 길(unfold, 변이 열거)은 모든 개수와 모든 선택지를 펼친다. 복제본이 천 개인 모델
하나를 만들려고 1부터 1,000까지의 개수를 모두 펼칠 수는 없다. 문헌의 도구는 가지치기를 절차로
하므로 만드는 모델의 크기에만 묶인다. 이 모듈이 그 길이다.

하는 일
- 변수 값과 결정 집합을 받아 뿌리에서 아래로 내려간다. 선택 지점마다 규칙을 그 변수 값에서 평가하고
  결정을 적용해 선택지를 하나로 줄인다. 고른 것만 적는다.
- 결과는 그 변이 하나만 담은 SES(가지치기된 엔티티 구조, PES)와 확장들이다. 노드의 경로와 주석은 족
  전체를 펼쳤을 때의 것과 같다. 그래서 뼈대, 검사, 해석, 실행기의 계획을 만드는 코드를 그대로 쓴다.

족 전체를 펼치는 길과 다른 점
- 되돌아가지 않는다. 선택지가 둘 이상 남으면 Undecided 로 멈춘다. 제약이 나중에 걸러 낼 선택도
  미리 정해 주어야 한다.
- 합칠 수 없는 구성요소(분해를 가진 정의가 둘 이상 합쳐졌는데 우선순위로 가를 수 없음)는 만들지
  않고 Contradiction 으로 멈춘다. 족 전체를 펼친 길에서는 그런 변이가 있되 핵 부적격(K1)이다.
- 없음이 된 구성요소의 아래는 만들지 않는다. 거기에 대한 결정과 규칙은 평가하지 않는다.
- 구성요소 경로나 노드로 가리킨 결정이 낡았는지는 판정하지 않는다. 쓰이지 않은 결정을 알려 줄 뿐이다.

선택의 규칙(선택 규칙, 분해의 규칙, 우선순위)은 고전 절차(classic.py)의 함수를 함께 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import model as m
from .algebra import ASP, SPEC, AlgebraError, Tree, holds
from .classic import _allowed, counts_of, decompositions
from .decisions import DecisionSet, override_problems, owners, with_overrides
from .extension import Layered
from .loader import fits
from .profile import Profile
from .skeleton import GONE, NO_ASPECT, skeleton
from .unfold import Unfolding, _domain, extensions_of, layered, reachable


class Undecided(AlgebraError):
    """선택 지점에 선택지가 둘 이상 남았다. 결정이 더 필요하다."""

    def __init__(self, where: tuple, kind: str, group: str, options: list) -> None:
        self.where, self.kind, self.group, self.options = tuple(where), kind, group, list(options)
        at = "/".join(where) if where else "문서"
        what = {"variable": f"변수 {group}", "alternative": f"specialization {group} 의 대안",
                "aspect": "분해", "count": f"multi-aspect {group} 의 개수"}[kind]
        super().__init__(f"{at}: {what}이(가) 정해지지 않았다. 남은 선택지: {self.options}")


class Contradiction(AlgebraError):
    """규칙, 결정, 제약이 서로 어긋나 만들 수 있는 변이가 없다."""


@dataclass(frozen=True)
class Built:
    layered: Layered            # 그 변이 하나만 담은 SES와 확장들. 결정 집합의 속성 재정의가 얹혀 있다
    variant: frozenset          # 그 변이. 나무의 모든 노드다
    sigma: dict                 # 변수 값
    used: tuple                 # 만드는 데 쓰인 결정의 열쇠들
    unused: tuple               # 한 번도 쓰이지 않은 결정과 재정의의 열쇠들


def _check(doc: m.SesDocument, ds: DecisionSet) -> None:
    """정의 수준의 결정이 문서에 맞는지 본다. 족 전체를 펼친 나무에서의 판정(decisions.excluded)과 같다."""
    reach = {e.name for e in reachable(doc)}
    for c in ds.choose:
        where = "/".join(map(str, c.key))
        bad = c.problems()
        if bad:
            raise AlgebraError(f"{where}: {'; '.join(bad)}")
        if c.at is None:
            continue
        e = doc.entities.get(c.at)
        if e is None or c.at not in reach:
            raise AlgebraError(f"{where}: 결정이 가리키는 곳이 대상에 없다")
        if c.specialization is not None:
            sp = e.specializations.get(c.specialization)
            have = set(sp.alternatives) if sp is not None else None
            want = set(c.alternative)
        elif c.multi_aspect is not None:
            ma = e.multi_aspects.get(c.multi_aspect)
            have, want = (None if ma is None else _Counts(doc, ma)), set(c.count)
        else:
            have = set(e.aspects) | set(e.multi_aspects) or None
            want = set(c.aspect) - {NO_ASPECT}
        if have is None:
            raise AlgebraError(f"{where}: 결정이 가리키는 선택 지점이 대상에 없다")
        missing = sorted(str(x) for x in want if x not in have)
        if missing:
            raise AlgebraError(f"{where}: 남기려는 선택지가 대상에 없다: {missing}")
    for o in ds.set:                            # 정의 수준의 재정의는 그 정의가 적은 속성을 바꾼다. 문서만 보고 판정한다
        where = "/".join("/".join(x) if isinstance(x, tuple) else str(x) for x in o.key)
        bad = o.problems()
        if bad:
            raise AlgebraError(f"{where}: {'; '.join(bad)}")
        if o.at is None:
            continue
        e = doc.entities.get(o.at)
        if e is None or o.at not in reach:
            raise AlgebraError(f"{where}: 재정의가 가리키는 곳이 대상에 없다")
        if o.attribute not in e.attributes:
            raise AlgebraError(f"{where}: 정의 {o.at} 에 속성 {o.attribute} 가 없다")
        kind = e.attributes[o.attribute].type
        if not fits(o.value, kind):
            raise AlgebraError(f"{where}: 값 {o.value!r} 이 속성 {o.attribute} 의 타입 {kind.value} 에 맞지 않다")


class _Counts:
    """multi-aspect 가 가질 수 있는 개수의 집합. 상한이 없을 수 있어 목록으로 만들지 않는다."""

    def __init__(self, doc: m.SesDocument, ma: m.MultiAspect) -> None:
        self.doc, self.card = doc, ma.cardinality

    def __contains__(self, n) -> bool:
        c = self.card
        if not isinstance(n, int) or isinstance(n, bool):
            return False
        if isinstance(c, m.Fixed):
            return n == c.n
        if isinstance(c, m.VarCard):
            return n in _domain(self.doc, c.var)
        return n >= c.min and (c.max is None or n <= c.max)


def _sigma(doc: m.SesDocument, ds: DecisionSet, use_defaults: bool) -> dict:
    """결정 집합이 정한 변수 값. 값이 하나로 정해지지 않은 변수가 있으면 멈춘다."""
    sigma = {}
    for name in ds.variables:
        if name not in doc.variables:
            raise AlgebraError(f"variable/{name}: 결정이 가리키는 선택 지점이 대상에 없다")
    for name, var in doc.variables.items():
        domain = _domain(doc, name)
        given = ds.variables.get(name)
        if given is not None:
            want = {str(v) for v in given}
            missing = sorted(want - {str(v) for v in domain})
            if missing:
                raise AlgebraError(f"variable/{name}: 남기려는 선택지가 대상에 없다: {missing}")
            domain = [v for v in domain if str(v) in want]
        if len(domain) > 1 and use_defaults and var.default in domain:
            domain = [var.default]
        if len(domain) != 1:
            raise Undecided((), "variable", name, domain)
        sigma[name] = domain[0]
    return sigma


def build(doc: m.SesDocument, ds: Optional[DecisionSet] = None, profile: Profile = None, functions=None,
          use_defaults: bool = False) -> Built:
    """변수 값과 결정 집합이 정하는 변이 하나를 만든다.

    선택지가 둘 이상 남는 선택 지점이 있으면 Undecided, 만들 수 있는 변이가 없으면 Contradiction 을 낸다.
    use_defaults 이면 정해지지 않은 변수와 specialization 에 문서가 적어 둔 기본값(default)을 쓴다.
    """
    ds = ds or DecisionSet()
    _check(doc, ds)
    sigma = _sigma(doc, ds, use_defaults)
    u = Unfolding(doc, functions, sigma)
    by_def: dict = {}
    by_path: dict = {}
    by_node: dict = {}
    for c in ds.choose:
        table, where = ((by_def, c.at) if c.at is not None else
                        (by_path, tuple(c.path)) if c.path is not None else (by_node, tuple(c.node)))
        table.setdefault(where, []).append(c)
    used: dict = {}

    def decisions(def_name: str, path: tuple, cp: tuple, kind: str, group: str = "") -> list:
        """그 엔티티 노드의 그 선택 지점에 걸린 결정들."""
        if not ds.choose:
            return []
        found = [c for c in by_def.get(def_name, []) + by_path.get(cp, []) + by_node.get(path, [])
                 if c.kind == kind and (kind == "aspect" or group == (c.specialization or c.multi_aspect))]
        for c in found:
            used[c.key] = True
        return found

    def cluster(def_name: str, path: tuple, cp: tuple, replicas: tuple) -> list:
        """엔티티와, specialization마다 고른 대안들. 합쳐져 구성요소 하나가 되는 (정의, 노드)의 목록이다."""
        e = u.entity(def_name, path, replicas)
        out = [(e, path)]
        for sp in e.specializations.values():
            options = _allowed(sp, sigma, functions)             # 선택 규칙이 정하면 그것 하나다
            for c in decisions(def_name, path, cp, "specialization", sp.name):
                options = [x for x in options if x in c.alternative]
            if len(options) > 1 and use_defaults and sp.default in options:
                options = [sp.default]
            if not options:
                raise Contradiction(f"{'/'.join(cp)}: specialization {sp.name} 에 남는 대안이 없다. "
                                    "선택 규칙과 결정이 어긋난다")
            if len(options) > 1:
                raise Undecided(cp, "alternative", sp.name, options)
            sp_path = path + (sp.name,)
            u.kinds[sp_path] = SPEC
            out += cluster(options[0], sp_path + (options[0],), cp, replicas)
        return out

    def component(def_name: str, path: tuple, cp: tuple, replicas: tuple) -> None:
        members = cluster(def_name, path, cp, replicas)
        if any(e.stereotype == m.Stereotype.VOID for e, _ in members):
            for e, y in members:                                 # 빠지는 구성요소. 분해 대신 "빠짐"을 고르고 그 아래는 없다
                if e.aspects or e.multi_aspects:
                    u.kinds[y + (GONE,)] = ASP
            return
        owners = [(e, y) for e, y in members if e.aspects or e.multi_aspects]
        if not owners:
            return
        node = {e.name: y for e, y in owners}
        wins, pushable = {}, {}
        for e, y in owners:                                      # 분해에 대한 결정: 남길 분해와, 밀려나도 되는가
            fams = set(e.aspects) | set(e.multi_aspects)
            wins[e.name], pushable[e.name] = fams, True
            for c in decisions(e.name, y, cp, "aspect"):
                want = set(c.aspect)
                wins[e.name] = wins[e.name] & want
                pushable[e.name] = pushable[e.name] and (NO_ASPECT in want or not (want & fams))
        options = []
        candidates = decompositions([e for e, _ in owners], sigma, functions)
        if not candidates:
            raise Contradiction(f"{'/'.join(cp)}: 분해를 하나로 정할 수 없다. 분해를 가진 정의 "
                                f"{[e.name for e, _ in owners]} 의 우선순위나 함께 참인 규칙을 가를 수 없다")
        for e, a in candidates:
            if a.name not in wins[e.name] or not all(pushable[z.name] for z, _ in owners if z is not e):
                continue
            if isinstance(a, m.Aspect):
                options.append((e, a, None))
                continue
            card = a.cardinality
            if isinstance(card, m.RangeCard) and card.max is None:
                counts = None                                    # 상한이 없다. 결정이 개수를 정해야 한다
            else:
                counts = counts_of(a, sigma)
            for c in decisions(e.name, node[e.name], cp, "multi_aspect", a.name):
                counts = [n for n in (c.count if counts is None else counts) if n in c.count and n in _Counts(doc, a)]
            if counts is None:
                raise Undecided(cp, "count", a.name, [f"{card.min} 이상"])
            options += [(e, a, n) for n in counts]
        if not options:
            raise Contradiction(f"{'/'.join(cp)}: 남는 분해가 없다. 결정이 분해의 규칙이나 우선순위와 어긋난다")
        if len(options) > 1:
            names = list(dict.fromkeys(a.name for _, a, _ in options))
            if len(names) > 1:
                raise Undecided(cp, "aspect", "", names)
            raise Undecided(cp, "count", names[0], [n for _, _, n in options])
        e, a, n = options[0]
        y = node[e.name]
        for z, yz in owners:                                     # 밀린 구성원은 "분해 없음"을 고른다
            if z is not e:
                u.kinds[yz + (NO_ASPECT,)] = ASP
        if isinstance(a, m.Aspect):
            a_path = u.aspect(e, a, y)
            for part in a.parts:
                component(part.def_name, a_path + (part.part_name,), cp + (part.part_name,), replicas)
        else:
            a_path, names = u.multi(e, a, n, y)
            for i, name in enumerate(names):
                component(a.part.def_name, a_path + (name,), cp + (name,), replicas + ((i, n),))

    component(doc.root.name, u.root, u.root, ())
    u.variables()
    u.tree = Tree(u.kinds, u.labels)
    start = len(u.clauses)
    u.constraints()
    V = frozenset(u.tree.nodes)
    for c, clause in zip(doc.constraints, u.clauses[start:]):
        if not holds(clause, V):
            raise Contradiction(f"제약 {c.name} 을 어긴다")
    L = layered(doc, u.result(), profile, extensions_of(doc))
    missing = []
    if ds.set:
        # 정의 수준의 것은 위에서 문서로 판정했다. 구성요소 경로로 가리킨 것은 만든 구조에서만 볼 수 있다.
        # 그 구성요소나 속성이 이 변이에 없으면 쓰이지 않은 것으로 알리고, 타입이 맞지 않으면 멈춘다
        for key, why in override_problems(L, ds):
            if "타입" in why:
                raise AlgebraError(f"{'/'.join('/'.join(x) if isinstance(x, tuple) else str(x) for x in key)}: {why}")
            missing.append(key)
        # 빠진 구성요소를 가리킨 재정의도 쓰이지 않은 것이다. 그 구성요소의 노드는 나무에 있지만 만들어지지 않는다
        live: set = set()
        stack = [skeleton(u.tree, L.void, V)]
        while stack:
            comp = stack.pop()
            if comp is not None:
                live.update(comp.members)
                stack += list(comp.parts.values())
        declared = next((x.decls for x in L.extensions if x.name == "attr"), {})
        for o in ds.set:
            if o.key not in missing and not any(y in live and o.attribute in (declared.get(y) or {})
                                                for y in owners(u.tree, o)):
                missing.append(o.key)
        L = with_overrides(L, ds, skip_invalid=True)
    unused = tuple(c.key for c in ds.choose if c.key not in used) + tuple(o.key for o in ds.set if o.key in missing)
    return Built(L, V, sigma, tuple(used), unused)
