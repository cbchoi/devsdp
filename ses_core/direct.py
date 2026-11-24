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
  미리 정해 주어야 한다. 다만 infer 를 켜면, 결정 집합이 족을 변이 하나로 줄일 때 규칙과 제약이 정한
  나머지를 정의 표 위의 분석으로 찾아 채운다(completed). 선택지 표가 "남은 변이 1개"라고 하는 결정
  집합이 만들어지지 않는 일이 없게 하기 위해서다.
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
from .decisions import Choice, DecisionSet, override_problems, owners, with_overrides
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
    root = doc.root.name

    def rooted(where: str, path) -> None:
        """구성요소 경로는 뿌리에서 시작한다. 그렇지 않은 경로는 어느 변이에도 없다."""
        if path is not None and (not path or path[0] != root):
            raise AlgebraError(f"{where}: 구성요소 경로는 뿌리의 이름 {root} 에서 시작한다. 적힌 것은 {list(path)} 다. "
                               f"계획과 기록은 뿌리를 빼고 보이지만 결정에는 뿌리부터 적는다")

    for name, given in ds.variables.items():            # 변수의 결정. 문서의 탓이 아니라 결정의 탓으로 가려내려고 여기서 본다
        if name not in doc.variables:
            raise AlgebraError(f"variable/{name}: 결정이 가리키는 선택 지점이 대상에 없다. 있는 변수는 {sorted(doc.variables)} 다")
        try:
            domain = _domain(doc, name)
        except AlgebraError:
            continue                                    # 범위가 없는 변수다. 펼칠 때 알린다
        missing = sorted({str(v) for v in given} - {str(v) for v in domain})
        if missing:
            raise AlgebraError(f"variable/{name}: 남기려는 선택지가 대상에 없다: {missing}. 있는 것은 {_few(domain)} 다")
    for c in ds.choose:
        where = "/".join(map(str, c.key))
        bad = c.problems()
        if bad:
            raise AlgebraError(f"{where}: {'; '.join(bad)}")
        rooted(where, c.path)
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
            raise AlgebraError(f"{where}: 남기려는 선택지가 대상에 없다: {missing}. 있는 것은 {_few(have)} 다")
    for o in ds.set:                            # 정의 수준의 재정의는 그 정의가 적은 속성을 바꾼다. 문서만 보고 판정한다
        where = "/".join("/".join(x) if isinstance(x, tuple) else str(x) for x in o.key)
        bad = o.problems()
        if bad:
            raise AlgebraError(f"{where}: {'; '.join(bad)}")
        rooted(where, o.path)
        if o.at is None:
            continue
        e = doc.entities.get(o.at)
        if e is None or o.at not in reach:
            raise AlgebraError(f"{where}: 재정의가 가리키는 곳이 대상에 없다")
        if o.attribute not in e.attributes:
            below = sorted(a for a in _alternatives_under(doc, o.at) if o.attribute in doc.entities[a].attributes)
            raise AlgebraError(f"{where}: 정의 {o.at} 에 속성 {o.attribute} 가 없다. 있는 속성은 {sorted(e.attributes)} 다"
                               + (f". 그 속성은 대안 {below} 가 가진다. 대안의 이름으로 적는다" if below else ""))
        kind = e.attributes[o.attribute].type
        if not fits(o.value, kind):
            raise AlgebraError(f"{where}: 값 {o.value!r} 이 속성 {o.attribute} 의 타입 {kind.value} 에 맞지 않다")


class _Counts:
    """multi-aspect 가 가질 수 있는 개수의 집합. 상한이 없을 수 있어 목록으로 만들지 않는다."""

    def __init__(self, doc: m.SesDocument, ma: m.MultiAspect) -> None:
        self.doc, self.card = doc, ma.cardinality

    def __str__(self) -> str:
        c = self.card
        if isinstance(c, m.Fixed):
            return str([c.n])
        if isinstance(c, m.VarCard):
            return _few(_domain(self.doc, c.var))
        return f"{c.min} 이상" + (f" {c.max} 이하" if c.max is not None else "")

    def __contains__(self, n) -> bool:
        c = self.card
        if not isinstance(n, int) or isinstance(n, bool):
            return False
        if isinstance(c, m.Fixed):
            return n == c.n
        if isinstance(c, m.VarCard):
            return n in _domain(self.doc, c.var)
        return n >= c.min and (c.max is None or n <= c.max)


def _alternatives_under(doc: m.SesDocument, name: str) -> set:
    """정의의 대안들과, 그 대안들의 대안들."""
    out: set = set()
    stack = [name]
    while stack:
        e = doc.entities.get(stack.pop())
        for sp in (e.specializations.values() if e is not None else ()):
            for alt in sp.alternatives:
                if alt not in out:
                    out.add(alt)
                    stack.append(alt)
    return out


def _few(options) -> str:
    """선택지들을 글로. 많으면 앞의 몇 개와 수만 적는다. 개수처럼 목록이 아닌 것은 그대로 적는다."""
    if isinstance(options, _Counts):
        return str(options)
    items = sorted(options, key=str) if isinstance(options, (set, frozenset)) else list(options)
    return str(items) if len(items) <= 12 else f"{items[:12]} 등 {len(items)}개"


def _place(c: Choice) -> str:
    """결정이 어디를 가리켜 적혔는지: at/정의, path/자리, node/노드."""
    kind, where = c.key[0], c.key[1]
    return f"{kind}/{'/'.join(map(str, where)) if isinstance(where, tuple) else where}"


def _clash(here: list, field: str, ruled: list, declared: list) -> str:
    """한 선택 지점에 남는 것이 없는 까닭. 걸린 결정마다 무엇을 남기는지와, 규칙이 남기는 것을 적는다.

    정의로 적은 결정(at)과 자리로 적은 결정(path)은 둘 다 적용된다. 자리의 결정이 정의의 결정을 덮지 않는다.
    그래서 둘이 다른 것을 남기면 그 자리에 남는 것이 없다. 이 글은 그 경우를 바로 알아보게 하려는 것이다.
    """
    kept = ", ".join(f"결정 {_place(c)} 는 {list(getattr(c, field))} 를 남긴다" for c in here)
    if not ruled:
        return "문서의 선택 규칙이 이 변수 값에서 아무것도 남기지 않는다"
    if len(ruled) < len(declared):
        return f"문서의 선택 규칙은 {list(ruled)} 를 남기고, {kept}. 둘이 어긋난다"
    text = f"이 자리에 걸린 결정들이 서로 어긋난다. {kept}"
    if len({c.key[0] for c in here}) > 1:
        text += (". 정의로 적은 결정(at)과 자리로 적은 결정(path)은 둘 다 적용되고 서로 덮지 않는다. 자리마다 다르게 "
                 "하려면 at 의 결정을 지우고 자리마다 path 로 적는다")
    return text


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
                raise AlgebraError(f"variable/{name}: 남기려는 선택지가 대상에 없다: {missing}. 있는 것은 {_few(domain)} 다")
            domain = [v for v in domain if str(v) in want]
        if len(domain) > 1 and use_defaults and var.default in domain:
            domain = [var.default]
        if len(domain) != 1:
            raise Undecided((), "variable", name, domain)
        sigma[name] = domain[0]
    return sigma


def why_none(doc: m.SesDocument, ds: Optional[DecisionSet], functions=None, use_defaults: bool = False) -> str:
    """결정을 따르는 변이가 없을 때, 조립이 처음 막히는 자리와 까닭. 찾지 못하면 빈 글이다.

    족을 센 쪽(folded)은 수만 안다. 어느 자리에서 무엇이 어긋나는지는 변이 하나를 만들어 보는 쪽이 안다.
    """
    try:
        _build(doc, ds, None, functions, use_defaults)
    except Contradiction as e:
        return str(e)
    except Exception:                                            # noqa: BLE001  모자란 것과 그 밖의 것은 까닭이 아니다
        return ""
    return ""


INFER_ASSIGNMENTS = 200000         # 정해진 것을 찾아 줄 때 돌아보는 변수 값의 조합의 한도
INFER_STEPS = 200                  # 자리마다 하나씩 채워 갈 때의 걸음 수의 한도
INFER_OPTIONS = 40                 # 한 선택 지점에서 하나씩 시험해 보는 선택지의 수의 한도


def _family(doc: m.SesDocument, ds: DecisionSet, functions):
    """결정 집합을 따르는 족을 정의 표 위에서 분석한 것. 셀 수 없으면 None."""
    from . import folded
    if any(c.node is not None for c in ds.choose):
        return None
    try:
        return folded.analyze(doc, functions, ds, max_assignments=INFER_ASSIGNMENTS)
    except (folded.TooManyAssignments, AlgebraError, AttributeError, TypeError):
        return None


def _narrowed(doc: m.SesDocument, ds: DecisionSet, fam) -> DecisionSet:
    """족의 선택 지점 표에서 남은 선택지가 하나인 지점을 정의를 가리킨 결정으로 더한다. 족을 바꾸지 않는 것만 더한다.

    변수, 대안, 개수는 놓인 자리마다 반드시 하나를 고르므로, 남은 선택지가 하나이면 모든 남은 변이가 그것을 골랐다.
    분해는 다르다. 병합체에서 밀려난 주인은 분해를 내지 않는다. 표에 분해가 하나만 남았어도 어떤 변이에서는 그
    주인이 아무것도 내지 않았을 수 있다. 그래서 분해의 결정은 남은 변이가 하나일 때만 더한다.
    """
    from . import folded
    for owner, kind, group, options in folded.choice_rows(doc, fam):
        left = [o for o, alive in options if alive]
        if len(left) != 1 or (kind == "aspect" and fam.variants != 1):
            continue                                             # 자리마다 다르게 정해졌다. 정의의 결정으로 적을 수 없다
        if kind == "variable":
            if ds.variables.get(owner) != (left[0],):
                ds = ds.assign(owner, left[0])
            continue
        # 같은 지점에 여럿을 남기는 결정이 이미 있어도 더한다. 열쇠가 같으면 좁힌 것으로 바뀐다
        ds = ds.decide(Choice(at=owner, specialization=group, alternative=(left[0],)) if kind == "alternative" else
                       Choice(at=owner, multi_aspect=group, count=(left[0],)) if kind == "count" else
                       Choice(at=owner, aspect=(left[0],)))
    return ds


def completed(doc: m.SesDocument, ds: Optional[DecisionSet] = None, functions=None) -> Optional[DecisionSet]:
    """결정 집합이 족을 변이 하나로 줄이면, 그 변이에서 정해진 것을 결정으로 더한 결정 집합. 아니면 None.

    남은 변이가 정확히 하나이면 변수 값과, 정의마다 남은 선택지가 하나인 선택 지점은 그 변이가 정한 것이다.
    선택 규칙이나 제약이 정한 것을 사람이 다시 적지 않아도 되게 한다. 족은 정의 표 위에서 센다(theory.md 7절).
    펼친 나무의 노드를 가리킨 결정이 있거나, 돌아볼 변수 값의 조합이 한도를 넘거나, 결정이 문서에 맞지 않으면 None.
    """
    ds = ds or DecisionSet()
    fam = _family(doc, ds, functions)
    if fam is None or fam.variants != 1:
        return None
    return _narrowed(doc, ds, fam)


def _with(ds: DecisionSet, e: "Undecided", option) -> DecisionSet:
    """조립이 물은 그 자리에 선택지 하나를 고른 결정을 더한 결정 집합."""
    if e.kind == "variable":
        return ds.assign(e.group, option)
    path = tuple(e.where)
    return ds.decide(Choice(path=path, specialization=e.group, alternative=(option,)) if e.kind == "alternative" else
                     Choice(path=path, multi_aspect=e.group, count=(option,)) if e.kind == "count" else
                     Choice(path=path, aspect=(option,)))


def build(doc: m.SesDocument, ds: Optional[DecisionSet] = None, profile: Profile = None, functions=None,
          use_defaults: bool = False, infer: bool = False) -> Built:
    """변수 값과 결정 집합이 정하는 변이 하나를 만든다.

    선택지가 둘 이상 남는 선택 지점이 있으면 Undecided, 만들 수 있는 변이가 없으면 Contradiction 을 낸다.
    use_defaults 이면 정해지지 않은 변수와 specialization 에 문서가 적어 둔 기본값(default)을 쓴다.

    infer 이면, 적힌 결정만으로는 선택 지점이 남아도 결정 집합이 족을 변이 하나로 줄일 때 그 변이를 만든다.
    남은 변이가 하나라는 것은 족 전체를 세어야 알 수 있으므로 그때만 정의 표 위의 분석을 한다.
    명령줄 도구와 묶음의 검사는 이것을 켠다. 그래서 선택지 표가 "남은 변이 1개"라고 한 결정 집합은 만들어진다.

    채우는 법은 둘이다. 먼저 선택지 표에서 남은 선택지가 하나인 지점을 정의를 가리킨 결정으로 더한다. 그래도
    조립이 어떤 자리를 물으면(한 정의가 자리마다 다르게 정해진 경우), 그 자리의 선택지를 하나씩 더해 족을 다시
    세고, 변이가 남는 선택지가 하나뿐이면 그것을 그 자리의 결정으로 더하고 이어 간다.

    infer 일 때 조립이 물었는데 결정을 따르는 변이가 없으면 Contradiction 을 낸다. 모자란 것이 아니라 어긋난 것이다.
    변이가 남는 선택지가 둘 이상인 자리에서는 Undecided 를 내되, 그 선택지들만 적는다. 고르면 변이가 없어지는
    선택지는 남은 선택지가 아니다.
    """
    try:
        return _build(doc, ds, profile, functions, use_defaults)
    except Undecided as first:
        if not infer:
            raise
        asked = first
    given = ds or DecisionSet()
    fam = _family(doc, given, functions)
    if fam is None:
        raise asked
    if fam.variants == 0:
        raise Contradiction("결정을 따르는 변이가 없다. 결정들이 서로 어긋나거나 규칙과 제약에 걸린다")
    more = _narrowed(doc, given, fam)                            # 모든 남은 변이가 따르는 결정만 더한다. 족은 그대로다
    budget = INFER_STEPS
    while True:
        try:
            built = _build(doc, more, profile, functions, use_defaults)
            break
        except Undecided as e:
            # 조립이 물은 자리. 선택지마다 그것을 고른 족을 세어, 변이가 남는 선택지만 남긴다
            budget -= len(e.options)
            if len(e.options) > INFER_OPTIONS or budget < 0 or (e.kind == "aspect" and fam.variants != 1):
                raise                                            # 분해는 남은 변이가 하나일 때만 가려낸다 (_narrowed 의 까닭과 같다)
            alive = [o for o in e.options if getattr(_family(doc, _with(more, e, o), functions), "variants", 1)]
            if not alive:
                raise Contradiction("결정을 따르는 변이가 없다. 결정들이 서로 어긋나거나 규칙과 제약에 걸린다")
            if len(alive) > 1:
                raise Undecided(e.where, e.kind, e.group, alive)
            more = _with(more, e, alive[0])                      # 하나만 남는다. 그 자리의 결정으로 더하고 이어 간다
    mine = {c.key for c in given.choose} | {o.key for o in given.set}
    return Built(built.layered, built.variant, built.sigma, built.used,
                 tuple(k for k in built.unused if k in mine))       # 찾아 준 결정이 쓰이지 않았다고 알리지 않는다


def _build(doc: m.SesDocument, ds: Optional[DecisionSet], profile: Profile, functions, use_defaults: bool) -> Built:
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
            ruled = options = _allowed(sp, sigma, functions)     # 선택 규칙이 정하면 그것 하나다
            here = decisions(def_name, path, cp, "specialization", sp.name)
            for c in here:
                options = [x for x in options if x in c.alternative]
            if len(options) > 1 and use_defaults and sp.default in options:
                options = [sp.default]
            if not options:
                raise Contradiction(f"{'/'.join(cp)}: specialization {sp.name} 에 남는 대안이 없다. "
                                    + _clash(here, "alternative", ruled, list(sp.alternatives)))
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
        clashes: list = []
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
            given = counts
            here = decisions(e.name, node[e.name], cp, "multi_aspect", a.name)
            for c in here:
                counts = [n for n in (c.count if counts is None else counts) if n in c.count and n in _Counts(doc, a)]
            if counts is None:
                raise Undecided(cp, "count", a.name, [f"{card.min} 이상"])
            if not counts and here:                              # 개수가 어긋났다. 무엇과 무엇이 어긋났는지를 남긴다
                clashes.append(f"multi-aspect {a.name} 의 개수는 문서와 변수 값으로 {_few(given) if given is not None else _Counts(doc, a)} 인데 "
                               + ", ".join(f"결정 {_place(c)} 는 {list(c.count)} 를 남긴다" for c in here))
            options += [(e, a, n) for n in counts]
        if not options:
            raise Contradiction(f"{'/'.join(cp)}: 남는 분해가 없다. " + ("; ".join(clashes) if clashes else
                                "결정이 분해의 규칙이나 우선순위와 어긋난다"))
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
