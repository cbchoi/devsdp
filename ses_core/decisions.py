"""결정 집합: 가지치기를 자료로 적은 것 (docs/ses-platform/13_editor_data_model.md).

편집기에서 변이를 고르는 일은 선택 지점마다 남길 선택지를 정하는 일이다. 그 결정들의
모음이 결정 집합이다. 결정 하나는 가지치기 SES 하나로 번역되고, 가지치기 연산은
순서와 무관하므로(07 문서의 정리 5) 결정 집합은 열이 아니라 집합이다. 결정을 더하고
빼는 순서가 결과에 영향을 주지 않는다. 되돌리기는 결정 하나를 빼는 일이다.

결정이 가리키는 곳은 세 가지 방식으로 적는다. 위에서 아래로 갈수록 좁다.
- at: 정의 이름. 그 정의가 출현하는 모든 곳. 접힌 형태의 가지치기 SES와 같다.
- path: 구성요소 경로(뿌리에서부터 부분 이름들). 그 구성요소의 병합체 전체.
  복제본마다 다르게 고를 때 쓴다.
- node: 펼친 나무의 엔티티 노드 하나. 가장 좁고 언제나 정확하다. 기계가 만든다.

결정의 내용은 세 가지 가운데 하나다.
- aspect: 남길 분해의 이름들 (aspect 이름 또는 multi-aspect 이름).
- multi_aspect와 count: 그 multi-aspect에서 남길 개수들.
- specialization과 alternative: 그 specialization에서 남길 대안들.
변수 값은 결정 집합의 variables에 따로 적는다.

결정은 원래의 SES를 기준으로 해석한다. 결정이 남기려는 선택지가 원래의 SES에 없으면
낡은 결정으로 보고한다. 편집기의 상태는 (SES, 결정 집합)이고 가지치기된 SES는 그때마다
다시 계산하는 파생물이다. 이미 가지치기된 SES에 결정을 덧붙여 적용하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Optional

from .algebra import (ASP, ENT, SPEC, SES, AlgebraError, Tree, determinate, interior,
                      occurrences, prune, reduce, restrict)
from .skeleton import component_of, is_component, members

FALSE = ("or",)
VAR_PREFIX = "$"
_COUNT = re.compile(r"^(.*)\[(\d+)\]$")


def split_count(name) -> tuple:
    """'실습들[2]' 를 ('실습들', 2) 로. multi-aspect의 전개가 아니면 (이름, None)."""
    m = _COUNT.match(name) if isinstance(name, str) else None
    return (m.group(1), int(m.group(2))) if m else (name, None)


def family(name):
    """aspect 노드의 이름에서 문서에 적힌 분해의 이름으로."""
    return split_count(name)[0]


def _tuple(x) -> tuple:
    if x is None:
        return ()
    if isinstance(x, (list, tuple)):
        return tuple(x)
    return (x,)


def _one(xs: tuple):
    return xs[0] if len(xs) == 1 else list(xs)


@dataclass(frozen=True)
class Choice:
    """선택 지점에 대한 결정 하나."""
    at: Optional[str] = None
    path: Optional[tuple] = None
    node: Optional[tuple] = None
    aspect: tuple = ()
    specialization: Optional[str] = None
    alternative: tuple = ()
    multi_aspect: Optional[str] = None
    count: tuple = ()

    @property
    def kind(self) -> str:
        if self.specialization is not None:
            return "specialization"
        return "multi_aspect" if self.multi_aspect is not None else "aspect"

    @property
    def keep(self) -> tuple:
        return {"specialization": self.alternative, "multi_aspect": self.count,
                "aspect": self.aspect}[self.kind]

    @property
    def key(self) -> tuple:
        """같은 선택 지점을 가리키는 결정은 열쇠가 같다."""
        where = (("at", self.at) if self.at is not None else
                 ("path", self.path) if self.path is not None else ("node", self.node))
        group = {"specialization": self.specialization, "multi_aspect": self.multi_aspect,
                 "aspect": ""}[self.kind]
        return where + (self.kind, group)

    def problems(self) -> list:
        """형식의 문제. 대상 SES와 무관하게 판정된다."""
        out = []
        if sum(x is not None for x in (self.at, self.path, self.node)) != 1:
            out.append("at, path, node 가운데 정확히 하나가 있어야 한다")
        kinds = (bool(self.aspect), self.specialization is not None, self.multi_aspect is not None)
        if sum(kinds) != 1:
            out.append("aspect, specialization, multi_aspect 가운데 정확히 하나가 있어야 한다")
        if self.specialization is not None and not self.alternative:
            out.append("specialization 에는 남길 alternative 가 있어야 한다")
        if self.multi_aspect is not None and not self.count:
            out.append("multi_aspect 에는 남길 count 가 있어야 한다")
        if self.specialization is None and self.alternative:
            out.append("alternative 는 specialization 과 함께 쓴다")
        if self.multi_aspect is None and self.count:
            out.append("count 는 multi_aspect 와 함께 쓴다")
        return out

    def to_dict(self) -> dict:
        d: dict = {}
        if self.at is not None:
            d["at"] = self.at
        if self.path is not None:
            d["path"] = list(self.path)
        if self.node is not None:
            d["node"] = list(self.node)
        if self.aspect:
            d["aspect"] = _one(self.aspect)
        if self.specialization is not None:
            d["specialization"] = self.specialization
        if self.specialization is not None or self.alternative:    # 형식이 틀린 결정도 그대로 적는다
            d["alternative"] = _one(self.alternative)
        if self.multi_aspect is not None:
            d["multi_aspect"] = self.multi_aspect
        if self.multi_aspect is not None or self.count:
            d["count"] = _one(self.count)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Choice":
        seq = lambda k: tuple(d[k]) if d.get(k) is not None else None      # noqa: E731
        return Choice(at=d.get("at"), path=seq("path"), node=seq("node"),
                      aspect=_tuple(d.get("aspect")), specialization=d.get("specialization"),
                      alternative=_tuple(d.get("alternative")), multi_aspect=d.get("multi_aspect"),
                      count=_tuple(d.get("count")))


@dataclass(frozen=True)
class DecisionSet:
    name: Optional[str] = None
    target: Optional[str] = None                                   # 대상 SES 문서의 이름
    variables: Mapping[str, tuple] = field(default_factory=dict)   # 변수에서 남길 값들로
    choose: tuple = ()

    def decide(self, choice: Choice) -> "DecisionSet":
        """결정을 더한다. 같은 선택 지점의 결정이 있으면 바꾼다."""
        rest = tuple(c for c in self.choose if c.key != choice.key)
        return replace(self, choose=rest + (choice,))

    def undecide(self, key: tuple) -> "DecisionSet":
        return replace(self, choose=tuple(c for c in self.choose if c.key != key))

    def assign(self, variable: str, *values) -> "DecisionSet":
        """변수가 가질 수 있는 값을 정한다. 값이 없으면 제한을 푼다."""
        vs = dict(self.variables)
        if values:
            vs[variable] = tuple(values)
        else:
            vs.pop(variable, None)
        return replace(self, variables=vs)

    def pick(self, point: "ChoicePoint", *options) -> "DecisionSet":
        """선택 지점 표의 한 줄에서 남길 선택지를 정한다. 정의 수준의 결정이 된다.

        선택지를 주지 않으면 그 지점의 결정을 푼다.
        """
        if point.kind == "variable":
            return self.assign(point.owner, *options)
        if not options:
            kind = {"aspect": "aspect", "count": "multi_aspect", "alternative": "specialization"}[point.kind]
            return self.undecide(("at", point.owner, kind, point.group))
        if point.kind == "aspect":
            return self.decide(Choice(at=point.owner, aspect=tuple(options)))
        if point.kind == "count":
            return self.decide(Choice(at=point.owner, multi_aspect=point.group, count=tuple(options)))
        return self.decide(Choice(at=point.owner, specialization=point.group, alternative=tuple(options)))

    def renamed(self, what: str, old: str, new: str, owner: Optional[str] = None) -> "DecisionSet":
        """문서에서 이름이 바뀌었을 때 결정 집합을 따라 고친다.

        what은 entity, variable, aspect, multi_aspect, specialization. 뒤의 셋은 소유
        엔티티의 이름(owner)이 필요하고 정의 수준의 결정만 고친다. 경로 수준과 노드
        수준의 결정은 나무 없이는 소유자를 알 수 없으므로 엔티티 이름만 고친다.
        고치지 못해 낡은 결정은 problems가 알려 준다.
        """
        sub = lambda xs: tuple(new if x == old else x for x in xs)        # noqa: E731
        if what == "variable":
            return replace(self, variables={(new if k == old else k): v for k, v in self.variables.items()})
        out = []
        for c in self.choose:
            if what == "entity":
                c = replace(c, at=new if c.at == old else c.at, alternative=sub(c.alternative),
                            path=sub(c.path) if c.path is not None else None,
                            node=(tuple(new if i % 2 == 0 and x == old else x for i, x in enumerate(c.node))
                                  if c.node is not None else None))
            elif c.at is not None and c.at == owner:
                if what == "specialization" and c.specialization == old:
                    c = replace(c, specialization=new)
                elif what in ("aspect", "multi_aspect"):
                    c = replace(c, aspect=sub(c.aspect),
                                multi_aspect=new if c.multi_aspect == old else c.multi_aspect)
            out.append(c)
        return replace(self, choose=tuple(out),
                       target=new if what == "entity" and self.target == old else self.target)

    def to_dict(self) -> dict:
        d: dict = {"decisions": "1.0"}
        if self.name is not None:
            d["name"] = self.name
        if self.target is not None:
            d["target"] = self.target
        if self.variables:
            d["variables"] = {k: _one(v) for k, v in self.variables.items()}
        if self.choose:
            d["choose"] = [c.to_dict() for c in self.choose]
        return d

    @staticmethod
    def from_dict(d: dict) -> "DecisionSet":
        return DecisionSet(d.get("name"), d.get("target"),
                           {k: _tuple(v) for k, v in (d.get("variables") or {}).items()},
                           tuple(Choice.from_dict(c) for c in d.get("choose") or ()))


def load_decisions(path: str) -> DecisionSet:
    import yaml
    with open(path, encoding="utf-8") as f:
        return DecisionSet.from_dict(yaml.safe_load(f))


# ---------------------------------------------------------------------------
# 가지치기 SES로의 번역
# ---------------------------------------------------------------------------

def component_path(T: Tree, q: tuple) -> tuple:
    """구성요소 경로: 뿌리에서 그 구성요소까지의 부분 이름들. aspect와 대안의 이름은 빠진다."""
    q = component_of(T, q)
    return (q[0],) + tuple(q[i] for i in range(1, len(q)) if T.kind(q[:i]) == ASP)


def owners(T: Tree, c: Choice) -> list:
    """결정이 가리키는 엔티티 노드들."""
    if c.at is not None:
        return occurrences(T, c.at)
    if c.path is not None:
        want = tuple(c.path)
        return [y for q in T.kinds
                if T.kind(q) == ENT and is_component(T, q) and component_path(T, q) == want
                for y in members(T, q)]
    q = tuple(c.node)
    return [q] if T.kinds.get(q) == ENT else []


def excluded(T: Tree, c: Choice) -> set:
    """결정이 배제하는 선택지 노드. 세 가지 주소 방식에 같은 규칙을 쓴다.

    결정이 가리키는 곳이나 남기려는 선택지가 대상에 없으면 AlgebraError를 낸다.
    낡은 결정을 조용히 넘기지 않기 위해서다.
    """
    bad = c.problems()
    if bad:
        raise AlgebraError("; ".join(bad))
    ys = owners(T, c)
    if not ys:
        raise AlgebraError("결정이 가리키는 곳이 대상에 없다")
    out: set = set()
    found: set = set()
    touched = False
    if c.specialization is not None:
        want = set(c.alternative)
        for y in ys:
            s = y + (c.specialization,)
            if T.kinds.get(s) == SPEC:
                touched = True
                for x in T.children(s):
                    if x[-1] in want:
                        found.add(x[-1])
                    else:
                        out.add(x)
    elif c.multi_aspect is not None:
        want = set(c.count)
        for y in ys:
            for a in T.aspects(y):
                fam, n = split_count(a[-1])
                if fam == c.multi_aspect and n is not None:
                    touched = True
                    if n in want:
                        found.add(n)
                    else:
                        out.add(a)
    else:
        want = set(c.aspect)
        for y in ys:
            for a in T.aspects(y):
                touched = True
                if family(a[-1]) in want:
                    found.add(family(a[-1]))
                else:
                    out.add(a)
    if not touched:
        raise AlgebraError("결정이 가리키는 선택 지점이 대상에 없다")
    if want - found:
        raise AlgebraError(f"남기려는 선택지가 대상에 없다: {sorted(map(str, want - found))}")
    return out


def _pattern(T: Tree, out: set) -> SES:
    """배제할 노드들을 가지치기 SES로. 뿌리에 놓이는 펼친 형태의 패턴이 된다."""
    top = Tree({T.root: ENT}, {T.root: T.label(T.root)})
    if not out:
        return SES(top)
    X = [n for n in T.kinds if not any(n[:i] in out for i in range(1, len(n) + 1))]
    K = interior(T, X)
    if K is None:                              # 이 결정은 어떤 변이도 남기지 않는다
        return SES(top, FALSE)
    return SES(restrict(T, K))


def _variable_choice(T: Tree, name: str, values: tuple) -> Choice:
    return Choice(node=T.root, specialization=VAR_PREFIX + name,
                  alternative=tuple(str(v) for v in values))


def _entries(T: Tree, ds: DecisionSet) -> list:
    """(열쇠, Choice)의 목록. 변수 값도 뿌리의 specialization에 대한 결정으로 본다."""
    out = [(("variable", name), _variable_choice(T, name, values))
           for name, values in ds.variables.items()]
    return out + [(c.key, c) for c in ds.choose]


def problems(S: SES, ds: DecisionSet) -> list:
    """대상에 맞지 않는 결정: (열쇠, 설명)의 목록. 문서가 바뀌어 낡은 결정을 찾는다."""
    T = S.tree
    out = []
    for key, c in _entries(T, ds):
        try:
            excluded(T, c)
        except AlgebraError as e:
            out.append((key, str(e)))
    return out


def patterns(S: SES, ds: DecisionSet, skip_invalid: bool = False) -> list:
    """결정 집합을 가지치기 SES의 모음으로 번역한다."""
    T = S.tree
    if len(occurrences(T, T.label(T.root))) != 1:
        raise AlgebraError("뿌리의 정의가 나무 안에 다시 나타난다. 결정을 뿌리에 놓을 수 없다")
    out = []
    for key, c in _entries(T, ds):
        try:
            out.append(_pattern(T, excluded(T, c)))
        except AlgebraError as e:
            if not skip_invalid:
                raise AlgebraError(f"{'/'.join(map(str, key))}: {e}") from None
    return out


def apply(S: SES, ds: DecisionSet, skip_invalid: bool = False) -> Optional[SES]:
    """S에 결정 집합을 적용한 가지치기된 SES. 남는 변이가 없으면 None."""
    return prune(S, *patterns(S, ds, skip_invalid))


# ---------------------------------------------------------------------------
# 선택 지점 표: 대화형 가지치기 화면의 자료
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChoicePoint:
    """정의 수준의 선택 지점 하나와 그 선택지들의 상태."""
    owner: str               # 정의 이름. 변수이면 변수 이름
    kind: str                # variable, aspect, count, alternative
    group: str               # specialization 이름 또는 multi-aspect 이름. 그 밖에는 빈 문자열
    options: tuple           # (선택지, 남아 있는가). 문서에 적힌 순서

    @property
    def remaining(self) -> tuple:
        return tuple(o for o, alive in self.options if alive)

    @property
    def active(self) -> bool:
        """이 선택 지점이 남은 변이 가운데 어디엔가 나타나는가."""
        return bool(self.remaining)

    @property
    def decided(self) -> bool:
        return len(self.remaining) == 1


def choice_table(S: SES, pruned: Optional[SES], domains: Optional[Mapping] = None) -> list:
    """S의 선택 지점마다 pruned에 남은 선택지를 표시한다.

    선택지가 남아 있다는 것은 pruned의 어떤 변이가 어떤 출현에서 그 선택지를 고른다는
    뜻이다. pruned가 None이면 남은 것이 없다. domains는 변수 이름에서 값의 목록으로
    가는 표이며, 주면 변수의 선택지를 원래 형의 값으로 돌려준다.
    """
    T = S.tree
    live = pruned.tree.nodes if pruned is not None else frozenset()
    variables: dict = {}
    groups: dict = {}

    def mark(table, key, option, node) -> None:
        g = table.setdefault(key, {})
        g[option] = g.get(option, False) or node in live

    for q in T.kinds:                          # 문서에 적은 순서
        k = T.kind(q)
        if k == ENT:
            for a in T.aspects(q):
                fam, n = split_count(a[-1])
                mark(groups, (T.label(q), "aspect", ""), fam, a)
                if n is not None:
                    mark(groups, (T.label(q), "count", fam), n, a)
        elif k == SPEC:
            if len(q) == 2 and q[-1].startswith(VAR_PREFIX):
                name = q[-1][len(VAR_PREFIX):]
                typed = {str(v): v for v in (domains or {}).get(name, ())}
                for c in T.children(q):
                    mark(variables, (name, "variable", ""), typed.get(c[-1], c[-1]), c)
            else:
                for c in T.children(q):
                    mark(groups, (T.label(q[:-1]), "alternative", q[-1]), c[-1], c)
    return [ChoicePoint(o, k, g, tuple(opts.items()))
            for table in (variables, groups)
            for (o, k, g), opts in table.items() if len(opts) > 1]


def choices(S: SES, ds: Optional[DecisionSet] = None, domains: Optional[Mapping] = None) -> list:
    """결정 집합을 적용한 뒤의 선택 지점 표."""
    return choice_table(S, apply(S, ds) if ds is not None else reduce(S), domains)


# ---------------------------------------------------------------------------
# 증거: 변이 하나를 정확히 재현하는 결정 집합
# ---------------------------------------------------------------------------

def witness(T: Tree, V: frozenset, domains: Optional[Mapping] = None) -> DecisionSet:
    """변이 V를 정확히 재현하는 결정 집합.

    진단이 '이 변이에서 문제가 생긴다'를 보일 때 쓴다. 선택지가 둘 이상인 선택
    지점마다 V가 고른 것을 적는다. 읽기 쉽도록 가장 넓은 주소 방식부터 시도한다:
    그 정의의 모든 출현이 V에서 같은 것을 골랐으면 정의 수준으로, 아니면 구성요소
    경로로, 그것도 V와 어긋나면 노드로 적는다.
    """
    V = frozenset(V)
    if not determinate(T, V):
        raise AlgebraError("증거로 삼을 선택이 변이가 아니다")
    variables: dict = {}
    facts: list = []
    for q in T.kinds:
        if q not in V:
            continue
        k = T.kind(q)
        if k == SPEC:
            kids = T.children(q)
            if len(kids) < 2:
                continue
            chosen = next(c[-1] for c in kids if c in V)
            if len(q) == 2 and q[-1].startswith(VAR_PREFIX):
                name = q[-1][len(VAR_PREFIX):]
                typed = {str(v): v for v in (domains or {}).get(name, ())}
                variables[name] = (typed.get(chosen, chosen),)
            else:
                facts.append((q[:-1], dict(specialization=q[-1], alternative=(chosen,))))
        elif k == ENT:
            asps = T.aspects(q)
            if len(asps) < 2:
                continue
            fam, n = split_count(next(a[-1] for a in asps if a in V))
            if any(family(a[-1]) != fam for a in asps):
                facts.append((q, dict(aspect=(fam,))))
            if n is not None and sum(family(a[-1]) == fam for a in asps) > 1:
                facts.append((q, dict(multi_aspect=fam, count=(n,))))

    def faithful(c: Choice) -> bool:
        try:
            return not (excluded(T, c) & V)
        except AlgebraError:
            return False

    choose: list = []
    for y, what in facts:
        for c in (Choice(at=T.label(y), **what), Choice(path=component_path(T, y), **what),
                  Choice(node=y, **what)):
            if faithful(c):
                if c not in choose:
                    choose.append(c)
                break
    return DecisionSet(variables=variables, choose=tuple(choose))
