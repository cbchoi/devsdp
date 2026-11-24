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

속성 값의 재정의(set)는 선택이 아니다. 변이를 줄이지 않고, 만들어지는 구성요소의 속성 값을 바꾼다.
- at: 그 정의가 준 값을 바꾼다. 그 정의가 구성원인 모든 구성요소에 미치고, 병합 규칙을 그대로 따른다.
- path: 그 구성요소의 값을 바꾼다. 구성원들이 준 값보다 앞선다. 복제본마다 다른 값을 줄 때 쓴다.

결정은 원래의 SES를 기준으로 해석한다. 결정이 남기려는 선택지가 원래의 SES에 없으면
낡은 결정으로 보고한다. 편집기의 상태는 (SES, 결정 집합)이고 가지치기된 SES는 그때마다
다시 계산하는 파생물이다. 이미 가지치기된 SES에 결정을 덧붙여 적용하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional

from .algebra import (ENT, SPEC, SES, AlgebraError, Tree, determinate, interior,
                      occurrences, prune, reduce, restrict)
from .skeleton import GONE, NO_ASPECT, component_path, is_component, members, real_aspects  # noqa: F401

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
class Override:
    """속성 값의 재정의 하나. at(정의)과 path(구성요소 경로) 가운데 하나로 가리킨다."""
    attribute: str
    value: Any
    at: Optional[str] = None
    path: Optional[tuple] = None

    @property
    def key(self) -> tuple:
        """같은 곳의 같은 속성을 가리키는 재정의는 열쇠가 같다."""
        where = ("at", self.at) if self.at is not None else ("path", self.path)
        return ("set",) + where + (self.attribute,)

    def problems(self) -> list:
        """형식의 문제. 대상 SES와 무관하게 판정된다."""
        out = []
        if (self.at is None) == (self.path is None):
            out.append("at 과 path 가운데 정확히 하나가 있어야 한다")
        if not isinstance(self.attribute, str) or not self.attribute:
            out.append("attribute 에 속성의 이름이 있어야 한다")
        if self.value is None or isinstance(self.value, (list, tuple, dict)):
            out.append("value 는 값 하나여야 한다")
        return out

    def to_dict(self) -> dict:
        d: dict = {}
        if self.at is not None:
            d["at"] = self.at
        if self.path is not None:
            d["path"] = list(self.path)
        d["attribute"] = self.attribute
        d["value"] = self.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "Override":
        return Override(d.get("attribute"), d.get("value"), d.get("at"),
                        tuple(d["path"]) if d.get("path") is not None else None)


@dataclass(frozen=True)
class DecisionSet:
    name: Optional[str] = None
    target: Optional[str] = None                                   # 대상 SES 문서의 이름
    variables: Mapping[str, tuple] = field(default_factory=dict)   # 변수에서 남길 값들로
    choose: tuple = ()
    set: tuple = ()                                                # 속성 값의 재정의들

    def decide(self, choice: Choice) -> "DecisionSet":
        """결정을 더한다. 같은 선택 지점의 결정이 있으면 바꾼다."""
        rest = tuple(c for c in self.choose if c.key != choice.key)
        return replace(self, choose=rest + (choice,))

    def undecide(self, key: tuple) -> "DecisionSet":
        """결정이나 재정의 하나를 뺀다."""
        return replace(self, choose=tuple(c for c in self.choose if c.key != key),
                       set=tuple(o for o in self.set if o.key != key))

    def override(self, o: Override) -> "DecisionSet":
        """속성 값의 재정의를 더한다. 같은 곳의 같은 속성에 대한 것이 있으면 바꾼다."""
        return replace(self, set=tuple(x for x in self.set if x.key != o.key) + (o,))

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
        if what == "attribute":                # 정의 수준의 재정의만 고친다. 경로 수준의 것은 problems가 알려 준다
            return replace(self, set=tuple(replace(o, attribute=new) if o.at == owner and o.attribute == old else o
                                           for o in self.set))
        overrides = self.set
        if what == "entity":
            overrides = tuple(replace(o, at=new if o.at == old else o.at,
                                      path=sub(o.path) if o.path is not None else None) for o in self.set)
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
        return replace(self, choose=tuple(out), set=overrides,
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
        if self.set:
            d["set"] = [o.to_dict() for o in self.set]
        return d

    @staticmethod
    def from_dict(d: dict) -> "DecisionSet":
        return DecisionSet(d.get("name"), d.get("target"),
                           {k: _tuple(v) for k, v in (d.get("variables") or {}).items()},
                           tuple(Choice.from_dict(c) for c in d.get("choose") or ()),
                           tuple(Override.from_dict(o) for o in d.get("set") or ()))


class DecisionError(ValueError):
    """결정 집합의 파일이 형식에 맞지 않다. 어디가 틀렸는지를 적는다."""


_FILE_KEYS = {"decisions", "name", "target", "variables", "choose", "set"}
_CHOICE_KEYS = {"at", "path", "node", "aspect", "specialization", "alternative", "multi_aspect", "count"}
_SET_KEYS = {"at", "path", "attribute", "value"}
_MEANT = {"variable": "variables", "vars": "variables", "chose": "choose", "choice": "choose", "choices": "choose",
          "sets": "set", "override": "set", "overrides": "set", "alternatives": "alternative", "spec": "specialization",
          "multi-aspect": "multi_aspect", "multiaspect": "multi_aspect", "attr": "attribute", "val": "value"}


def check_file(d) -> None:
    """파일에서 읽은 결정 집합의 모양을 본다. 틀리면 DecisionError 를 낸다.

    모르는 항목을 조용히 넘기지 않는다. variables 를 variable 로 적으면 결정이 없는 것처럼 읽혀서,
    틀린 곳과 먼 곳에서 "결정이 모자라다"고 나온다. 스키마(schema/decisions.schema.json)의 항목과 같다.
    """
    def known(x, keys, where) -> None:
        if not isinstance(x, dict):
            raise DecisionError(f"{where}: 이름과 값의 표로 적어야 한다. 적힌 것은 {x!r} 다")
        for key in sorted(map(str, set(x) - keys)):
            meant = _MEANT.get(key)
            raise DecisionError(f"{where}: 모르는 항목 {key} 가 있다. " + (f"{meant} 를 뜻했는가. " if meant else "")
                                + f"쓸 수 있는 것은 {sorted(keys)} 다")

    if d is None:
        raise DecisionError('파일이 비어 있다. decisions: "1.0" 으로 시작하고 target 에 문서의 이름을 적는다')
    known(d, _FILE_KEYS, "결정 집합")
    if d.get("variables") is not None and not isinstance(d["variables"], dict):
        raise DecisionError("variables: 변수 이름에서 값으로 가는 표로 적는다. 예: variables: {n: 3}")
    for key, keys in (("choose", _CHOICE_KEYS), ("set", _SET_KEYS)):
        items = d.get(key)
        if items is None:
            continue
        if not isinstance(items, list):
            raise DecisionError(f"{key}: 목록으로 적는다. 항목마다 - 로 시작한다")
        for i, item in enumerate(items):
            known(item, keys, f"{key}[{i}]")
            for where in ("path", "node"):
                if item.get(where) is not None and not isinstance(item[where], list):
                    raise DecisionError(f"{key}[{i}].{where}: 이름의 목록으로 적는다. 예: [뿌리, 부분]")
            for where in ("at", "specialization", "multi_aspect", "attribute"):
                if item.get(where) is not None and not isinstance(item[where], str):
                    raise DecisionError(f"{key}[{i}].{where}: 이름 하나를 글로 적는다. 적힌 것은 {item[where]!r} 다")
    for name in ("name", "target"):
        if d.get(name) is not None and not isinstance(d[name], str):
            raise DecisionError(f"{name}: 글로 적는다. 적힌 것은 {d[name]!r} 다")


def load_decisions(path: str) -> DecisionSet:
    from . import safeyaml
    try:
        d = safeyaml.load(path)
    except safeyaml.YamlError as e:
        raise DecisionError(str(e)) from None
    check_file(d)
    try:
        return DecisionSet.from_dict(d)
    except (TypeError, ValueError, AttributeError, LookupError) as e:       # 모양이 틀린 곳을 미리 다 막지는 못했다
        raise DecisionError(f"모양이 틀렸다. {type(e).__name__}: {e}") from None


_CHANGE_KEYS = {"variables", "choose", "set"}


def overlaid(ds: Optional[DecisionSet], change) -> DecisionSet:
    """결정 집합 위에 고친 것(change)을 얹는다. 실험에서 사례 하나의 값을 바꿔 가며 돌릴 때 쓴다.

    change 는 결정 집합 파일의 variables, choose, set 과 같은 모양의 표다. 같은 변수, 같은 선택 지점, 같은 곳의
    같은 속성에 대한 것이 이미 있으면 바꾸고 없으면 더한다. 모양이 틀리면 DecisionError 다.
    """
    if not isinstance(change, dict):
        raise DecisionError(f"고칠 것은 variables, choose, set 을 가진 표로 준다. 받은 것은 {change!r} 다")
    extra = sorted(map(str, set(change) - _CHANGE_KEYS))
    if extra:
        raise DecisionError(f"고칠 것에 모르는 항목 {extra[0]} 가 있다. 쓸 수 있는 것은 {sorted(_CHANGE_KEYS)} 다")
    check_file(dict(change))
    try:
        more = DecisionSet.from_dict(change)
    except (TypeError, ValueError, AttributeError, LookupError) as e:
        raise DecisionError(f"모양이 틀렸다. {type(e).__name__}: {e}") from None
    out = ds or DecisionSet()
    for name, values in more.variables.items():
        out = out.assign(name, *values)
    for c in more.choose:
        out = out.decide(c)
    for o in more.set:
        out = out.override(o)
    return out


# ---------------------------------------------------------------------------
# 가지치기 SES로의 번역
# ---------------------------------------------------------------------------

def owners(T: Tree, c) -> list:
    """결정이나 재정의가 가리키는 엔티티 노드들."""
    if c.at is not None:
        # 변수의 값의 노드는 정의가 놓인 곳이 아니다. 그 노드의 표지는 $ 로 시작하는 변수의 이름이다
        return [] if str(c.at).startswith(VAR_PREFIX) else occurrences(T, c.at)
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
            mine = [a for a in T.aspects(y) if a[-1] != GONE]   # 빠졌다는 표시는 결정이 고르는 것이 아니다. 늘 남긴다
            keeps = any(family(a[-1]) in want for a in mine)
            for a in mine:
                touched = True
                if family(a[-1]) in want:
                    found.add(family(a[-1]))
                elif a[-1] == NO_ASPECT and not keeps:
                    pass                               # 이 구성원에는 남길 분해가 없다. 우선순위에 밀려날 수 있게 둔다
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
    return out + [(c.key, _no_variable(c)) for c in ds.choose]


def _no_variable(c: Choice) -> Choice:
    """선택의 결정이 변수를 specialization 인 것처럼 가리키면, 없는 선택 지점을 가리킨 것으로 만든다.

    변수는 펼친 나무에서 뿌리의 specialization 으로 적혀 있을 뿐이다. 변수의 값은 결정 집합의 variables 로 정한다.
    """
    if c.specialization is not None and str(c.specialization).startswith(VAR_PREFIX):
        return replace(c, specialization="")
    return c


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
# 속성 값의 재정의
# ---------------------------------------------------------------------------

def _override_problem(T: Tree, decls: Mapping, o: Override) -> Optional[str]:
    """재정의 하나가 대상에 맞지 않는 까닭. 맞으면 None."""
    bad = o.problems()
    if bad:
        return "; ".join(bad)
    ys = owners(T, o)
    if not ys:
        return "재정의가 가리키는 곳이 대상에 없다"
    found = [decls[y][o.attribute] for y in ys if o.attribute in (decls.get(y) or {})]
    if not found:
        where = f"정의 {o.at}" if o.at is not None else f"구성요소 {'/'.join(o.path)}"
        return f"{where} 에 속성 {o.attribute} 가 없다"
    for d in found:
        if not _fits(o.value, d.type):
            return f"값 {o.value!r} 이 속성 {o.attribute} 의 타입 {d.type} 에 맞지 않다"
    return None


def _fits(value, type_: str) -> bool:
    from . import model as m
    from .loader import fits
    try:
        return fits(value, m.ScalarType(type_))
    except ValueError:
        return True                            # 문서 밖에서 만든 선언의 타입은 판정하지 않는다


def _attr_extension(L):
    return next((x for x in L.extensions if x.name == "attr"), None)


def override_problems(L, ds: DecisionSet) -> list:
    """대상에 맞지 않는 재정의: (열쇠, 설명)의 목록. L은 속성 확장이 얹힌 SES다."""
    attr = _attr_extension(L)
    decls = attr.decls if attr is not None else {}
    out = []
    for o in ds.set:
        why = _override_problem(L.ses.tree, decls, o)
        if why is not None:
            out.append((o.key, why))
    return out


def with_overrides(L, ds: DecisionSet, skip_invalid: bool = False):
    """결정 집합의 속성 재정의를 얹은 것. 변이의 집합은 바뀌지 않는다.

    그 뒤에 붙이는 실행기(executor.attach)와 해석이 재정의된 값을 본다. 대상에 맞지 않는 재정의가 있으면
    AlgebraError를 낸다. skip_invalid이면 그런 것을 빼고 얹는다.
    """
    if not ds.set:
        return L
    bad = dict(override_problems(L, ds))
    if bad and not skip_invalid:
        key, why = next(iter(bad.items()))
        raise AlgebraError(f"{'/'.join('/'.join(x) if isinstance(x, tuple) else str(x) for x in key)}: {why}")
    attr = _attr_extension(L)
    if attr is None:
        return L
    good = [o for o in ds.set if o.key not in bad]
    by_def = {(o.at, o.attribute): o.value for o in good if o.at is not None}
    by_path = {(tuple(o.path), o.attribute): o.value for o in good if o.path is not None}
    T = L.ses.tree
    new = attr.overridden(by_def, by_path, {p: T.label(p) for p in attr.decls})
    return type(L)(L.ses, L.void, tuple(new if x is attr else x for x in L.extensions))


def decide(L, ds: DecisionSet, skip_invalid: bool = False):
    """결정 집합 전체를 적용한 것: 선택으로 가지치기하고 속성 재정의를 얹는다. 남는 변이가 없으면 None.

    재정의도 선택에 대한 결정처럼 원래의 SES를 기준으로 해석한다. 같은 결정 집합의 선택이 지운 곳을
    가리키는 재정의는 낡은 것이 아니다. 그 변이들에서 쓰이지 않을 뿐이다.
    """
    over = with_overrides(L, ds, skip_invalid)
    R = apply(L.ses, ds, skip_invalid)
    return None if R is None else type(L)(R, over.void, over.extensions)


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
            for a in real_aspects(T, q):               # 밀려났다는 표시는 사람이 고르는 선택지가 아니다
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


def choices_on_definitions(doc, ds: Optional[DecisionSet] = None, functions=None) -> list:
    """결정 집합을 적용한 뒤의 선택 지점 표를 정의 표 위에서 구한다. 나무를 펼치지 않고 변이를 열거하지 않는다.

    choices 와 같은 표를 같은 순서로 낸다(theory.md 정리 9 와 따름정리 9.2). 펼친 나무의 노드를 가리킨
    결정(node)이 있으면 AlgebraError 를 낸다. 그때는 choices 를 쓴다.
    """
    from . import folded
    fam = folded.analyze(doc, functions, ds if ds is not None else DecisionSet())
    return [ChoicePoint(owner, kind, group, options) for owner, kind, group, options in folded.choice_rows(doc, fam)]


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
            if not asps or next(a for a in asps if a in V)[-1] == GONE:
                continue                               # 빠진 구성요소. 대안의 선택이 이미 정한다
            asps = tuple(a for a in asps if a[-1] != GONE)
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
