"""정준 SES 문서(SesDocument)와 가지치기 대수(algebra, coupling) 사이의 다리.

- unfold_annotated(doc): 정의 테이블을 뿌리에서 펼쳐 SES 트리, 제약식, 주석
  (포트, 없음 대안, 결합)을 만든다. multi-aspect는 개수별 aspect로 전개하고
  결합 틀을 개수마다 사례화한다. 변수는 뿌리의 specialization으로, 선택 규칙과
  선택 제약은 제약식으로 부호화한다.
- unfold(doc): 주석 없이 SES만 돌려준다.
- pruning_patterns(doc): 접힌 형태의 가지치기 SES를 정의별 높이 2 패턴의
  모음으로 바꾼다. 각 패턴은 그 정의의 모든 출현에 적용된다.

기본값(default)은 변이 공간을 바꾸지 않는 선호이므로 여기서는 다루지 않는다.

우선순위(priority)는 분해 사이의 다툼을 가른다 (docs/ses-platform/18_classic_parity.md). 수가 작을수록 앞선다.
정준 문서의 스키마와 04 문서가 처음부터 정해 둔 약속이다.
- 한 엔티티에 적힌 분해들의 규칙이 함께 참이면 우선순위가 가장 높은 것이 적용된다.
- 엔티티와 고른 대안이 각자 분해를 가지면 병합체 안에서 형제가 된다. 우선순위가 가장 높은 것이
  그 구성요소의 분해가 되고, 밀린 구성원은 "분해 없음"(skeleton.NO_ASPECT)을 고른다.
우선순위가 같거나 없어서 가를 수 없으면 종전과 같다. 규칙은 모순이 되고 병합은 부적격이 된다.

빠진 구성요소 (docs/ses-platform/18_classic_parity.md 5.3절)
- 선택 대수는 골라진 엔티티마다 분해를 하나 고르게 한다. 그대로 두면 없음 대안을 골라 빠진 구성요소도
  분해와 그 아래를 골라야 하고, 그 아래의 선택이 변이를 부풀리며, 거기에 걸린 결정과 규칙이 어긋나면
  족이 빈다. 문헌의 절차는 빠진 구성요소의 아래를 평가하지 않는다.
- 그래서 빠질 수 있는 구성요소의 구성원 가운데 분해를 가진 것에 "빠짐"(skeleton.GONE)을 준다. 구성요소가
  빠지면 그것을 고르고, 빠지지 않았으면 고를 수 없다. 빠진 구성요소의 병합체 안의 대안 선택은 그대로 남는다.
  그 선택으로 구성요소가 빠지기 때문이다.

식 (docs/ses-platform/18_classic_parity.md)
- 규칙과 제약의 원자는 변수에 대한 조건이다. 변수의 범위가 유한하므로 원자가 참이 되는 변수 값의
  조합을 모두 적어 명제식으로 바꾼다. 변수와 상수의 비교, 변수끼리의 비교, 이름으로 등록한 함수의
  호출(call)이 모두 같은 방법으로 처리된다. 함수의 본문은 코드에 있지만 문서에는 이름만 남고,
  분석은 함수의 값의 표만 본다. 함수는 같은 인자에 늘 같은 값을 내야 한다.
- selected 는 선택 제약에서만 쓴다. 가리키는 선택지 노드가 골라졌고 그 선택 지점이 실제로 있는
  구성요소의 것일 때 참이다. 없음이 된 구성요소 아래에서 한 선택은 세지 않는다.

속성의 값 (docs/ses-platform/18_classic_parity.md 4절)
- each 는 복제본마다의 값이다. 가장 가까운 복제본의 번호로 고른다. 펼칠 때 정해진다.
- expr 은 변수, 등록한 함수, 복제본의 번호와 개수(replica)에서 값을 낸다. 변수를 보지 않으면 펼칠 때
  정해지고, 보면 변수 값의 조합마다의 값을 표로 적어 두었다가 변이의 변수 값으로 찾는다.
"""

from __future__ import annotations

import operator
from itertools import product

from . import model as m
from .algebra import (ASP, ENT, SPEC, SES, TRUE, AlgebraError, Tree,
                      f_and, f_imp, f_not, f_or, occurrences, sel)
from .coupling import SELF, Ann, Coupling, PortDecl, validate
from .decisions import family
from .ext_attr import AttrDecl, Attributes
from .ext_text import Text
from .extension import Layered
from .loader import fits, selected_target
from .profile import Domain, Item, Profile
from .skeleton import (GONE, NO_ASPECT, component_of, component_path, components, is_component, live_formula,
                       members, owner, void_formula)

_OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le,
        "gt": operator.gt, "ge": operator.ge, "in": lambda v, c: v in c}
MAX_ROWS = 20000                 # 원자 하나의 표가 가질 수 있는 변수 값 조합의 수
REPLICAS = "#replicas"           # 식을 평가할 때 복제본의 (번호, 개수)들을 바깥에서 안으로 적어 두는 자리


def replica_levels(e) -> set:
    """식이 묻는 복제본의 겹(up)들."""
    if isinstance(e, m.Replica):
        return {e.up}
    out: set = set()
    for x in getattr(e, "items", ()) or ():
        out |= replica_levels(x)
    for attr in ("left", "right", "item"):
        if hasattr(e, attr):
            out |= replica_levels(getattr(e, attr))
    for a in getattr(e, "args", ()) or ():
        out |= replica_levels(a)
    return out


def expr_vars(e) -> set:
    """식에 나오는 변수의 이름들."""
    if isinstance(e, m.Var):
        return {e.name}
    out: set = set()
    for x in getattr(e, "items", ()) or ():
        out |= expr_vars(x)
    for attr in ("left", "right", "item"):
        if hasattr(e, attr):
            out |= expr_vars(getattr(e, attr))
    for a in getattr(e, "args", ()) or ():
        out |= expr_vars(a)
    return out


def evaluate(e, env: dict, functions=None):
    """변수 값 env 에서 식의 값. selected 는 변수만으로 정해지지 않으므로 여기서 다루지 않는다."""
    if isinstance(e, m.Const):
        return e.value
    if isinstance(e, m.Var):
        return env[e.name]
    if isinstance(e, m.Replica):
        stack = env.get(REPLICAS, ())
        if e.up >= len(stack):
            raise AlgebraError(f"복제본이 아닌 곳에서 복제본의 {e.what} 를 물었다 (up={e.up})")
        return stack[-1 - e.up][0 if e.what == "index" else 1]
    if isinstance(e, m.Compare):
        left, right = evaluate(e.left, env, functions), evaluate(e.right, env, functions)
        try:
            return bool(_OPS[e.op](left, right))
        except TypeError:
            raise AlgebraError(f"견줄 수 없는 값이다: {left!r} {e.op} {right!r}")
    if isinstance(e, m.And):
        return all(evaluate(x, env, functions) for x in e.items)
    if isinstance(e, m.Or):
        return any(evaluate(x, env, functions) for x in e.items)
    if isinstance(e, m.Not):
        return not evaluate(e.item, env, functions)
    if isinstance(e, m.Call):
        fn = (functions or {}).get(e.fn)
        if fn is None:
            raise AlgebraError(f"등록되지 않은 함수 {e.fn}")
        args = [evaluate(a, env, functions) for a in e.args]
        try:
            return fn(*args)
        except Exception as err:                 # noqa: BLE001
            raise AlgebraError(f"함수 {e.fn} 가 인자 {args} 에서 실패했다: {err}")
    raise AlgebraError(f"분석 가능 단편 밖의 표현식: {e!r}")


def var_node(name: str) -> str:
    return "$" + name


def _domain(doc: m.SesDocument, name: str) -> list:
    var = doc.variables[name]
    if isinstance(var.domain, m.EnumSet):
        return list(var.domain.values)
    if isinstance(var.domain, m.Range) and var.type == m.ScalarType.INT:
        return list(range(int(var.domain.min), int(var.domain.max) + 1))
    if var.type == m.ScalarType.BOOL:
        return [True, False]
    raise AlgebraError(f"변수 {name} 에 유한 범위가 필요하다")


def variable_domains(doc: m.SesDocument) -> dict:
    """변수 이름에서 가질 수 있는 값의 목록으로. 펼친 나무는 값을 글자로 적으므로,
    결정 집합과 선택 지점 표가 원래 형의 값을 되찾을 때 쓴다."""
    return {name: _domain(doc, name) for name in doc.variables}


def _card_set(doc: m.SesDocument, ma: m.MultiAspect) -> list:
    c = ma.cardinality
    if isinstance(c, m.Fixed):
        return [c.n]
    if isinstance(c, m.VarCard):
        return _domain(doc, c.var)
    if c.max is None:
        raise AlgebraError(f"multi-aspect {ma.name} 의 개수에 상한이 필요하다")
    return list(range(c.min, c.max + 1))


def _replica_name(ma: m.MultiAspect, i: int, n: int) -> str:
    return ma.naming.format(i=i, n=n, part=ma.part.part_name)


def _end(ref: m.PortRef, table: dict) -> tuple:
    who = table.get(ref.part, ref.part) if ref.part is not None else SELF
    return (who, ref.port)


def _plain(couplings) -> tuple:
    return tuple((_end(c.src, {}), _end(c.dst, {})) for c in couplings)


def _instantiate_pattern(ma: m.MultiAspect, names: list) -> tuple:
    """multi-aspect의 결합 틀을 복제본 이름 열에 대해 사례화한다."""
    p = ma.pattern
    if p is None:
        return ()
    out: list = []

    def add(c: m.Coupling, table: dict) -> None:
        out.append((_end(c.src, table), _end(c.dst, table)))

    for c in p.fan_out + p.fan_in + p.custom:
        if "{part}" in (c.src.part, c.dst.part):
            for x in names:
                add(c, {"{part}": x})
        else:
            add(c, {})
    for c in p.first:
        for x in names[:1]:
            add(c, {"{part}": x})
    for c in p.last:
        for x in names[-1:]:
            add(c, {"{part}": x})
    for c in p.between:
        holes = {c.src.part, c.dst.part}
        if holes == {"{i}", "{next}"}:
            for i in range(len(names) - 1):
                add(c, {"{i}": names[i], "{next}": names[i + 1]})
            if p.kind == m.PatternKind.RING and names:
                add(c, {"{i}": names[-1], "{next}": names[0]})
        elif holes == {"{i}", "{j}"}:
            for x in names:
                for y in names:
                    if x != y:
                        add(c, {"{i}": x, "{j}": y})
        else:
            raise AlgebraError(f"{ma.name}: between 결합은 {{i}}와 {{next}} 또는 {{i}}와 {{j}}를 써야 한다")
    return tuple(dict.fromkeys(out))


def above(p, q) -> bool:
    """우선순위 p가 q보다 앞서는가. 수가 작을수록 앞선다. 없는 것은 가장 뒤이고, 없는 것끼리는 가르지 못한다."""
    return p is not None and (q is None or p < q)


class Unfolding:
    """정의 표를 펼쳐 나무, 제약식, 주석을 모으는 일.

    두 가지로 쓴다. 족 전체를 펼칠 때는 rec 이 모든 선택지를 따라 내려간다(_unfold). 결정이 끝난
    변이 하나를 만들 때는 고른 것만 적는다(direct.py). 그때 sigma 는 정해진 변수 값이고, 변수의
    범위는 그 값 하나로 줄어든다. 노드에 주석을 적는 코드는 두 쓰임이 함께 쓴다.
    """

    def __init__(self, doc: m.SesDocument, functions=None, sigma=None) -> None:
        self.doc, self.functions, self.sigma = doc, functions, sigma
        self.root = (doc.root.name,)
        self.kinds: dict = {}
        self.labels: dict = {}
        self.clauses: list = []
        self.ports: dict = {}
        self.void: set = set()
        self.coup: dict = {}
        self.attrs: dict = {}
        self.templates: dict = {}
        self.layouts: dict = {}
        self.items: dict = {}
        self.decomps: dict = {}          # 엔티티 노드에서 그 분해들로: [이름, aspect 노드들, 규칙, 우선순위]
        self.computed: dict = {}         # (정의, 속성, 식이 본 복제본들)에서 그 속성의 선언으로
        self.tree = None
        self.gone = frozenset()

    # 변수와 식 -----------------------------------------------------------

    def domain(self, name: str) -> list:
        if self.sigma is not None:
            return [self.sigma[name]]
        return _domain(self.doc, name)

    def cards(self, ma: m.MultiAspect) -> list:
        c = ma.cardinality
        return self.domain(c.var) if isinstance(c, m.VarCard) else _card_set(self.doc, ma)

    def value(self, name: str, v) -> tuple:
        return self.root + (var_node(name), str(v))

    def attribute(self, def_name: str, a: m.Attribute, replicas: tuple) -> AttrDecl:
        """정의 def_name 의 속성 a 가 이 자리에서 가지는 값. replicas 는 바깥에서 안으로 적은 (번호, 개수)들이다."""
        kind = a.type.value
        if a.each is not None:
            i = replicas[-1][0] if replicas else None
            return AttrDecl(kind, a.each[i] if i is not None and i < len(a.each) else a.default)
        if a.expr is None:
            return AttrDecl(kind, a.default)
        levels = replica_levels(a.expr)
        if levels and max(levels) >= len(replicas):
            raise AlgebraError(f"속성 {def_name}.{a.name} 의 식이 복제본의 번호를 쓰는데, "
                               f"그 정의가 놓인 자리를 감싼 multi-aspect 가 {len(replicas)} 겹뿐이다")
        key = (def_name, a.name, tuple(replicas[-1 - u] for u in sorted(levels)))
        if key in self.computed:
            return self.computed[key]
        names = sorted(expr_vars(a.expr))
        domains = [self.domain(n) for n in names]
        rows = 1
        for d in domains:
            rows *= len(d)
        if rows > MAX_ROWS:
            raise AlgebraError(f"속성 {def_name}.{a.name} 의 표가 너무 크다. 변수 {names} 의 값 조합이 {rows} 가지다")
        table = {}
        for row in product(*domains):
            v = evaluate(a.expr, dict(zip(names, row), **{REPLICAS: replicas}), self.functions)
            if v is not None and (not fits(v, a.type) or (a.values is not None and v not in a.values)):
                raise AlgebraError(f"속성 {def_name}.{a.name} 의 식이 타입 {kind} 에 맞지 않는 값 {v!r} 을 냈다"
                                   + (f" (변수 값 {dict(zip(names, row))})" if names else ""))
            table[row] = v
        if not names:
            decl = AttrDecl(kind, table[()])
        else:
            decl = AttrDecl(kind, None, False, lambda env, names=tuple(names), table=table:
                            table[tuple(env[n] for n in names)])
        self.computed[key] = decl
        return decl

    def table(self, e: m.Expr):
        """변수에 대한 조건 하나를, 그것이 참이 되는 변수 값의 조합들로 적는다."""
        names = sorted(expr_vars(e))
        domains = [self.domain(n) for n in names]
        rows = 1
        for d in domains:
            rows *= len(d)
        if rows > MAX_ROWS:
            raise AlgebraError(f"조건의 표가 너무 크다. 변수 {names} 의 값 조합이 {rows} 가지다: {e!r}")
        return f_or(*(f_and(*(sel(self.value(n, v)) for n, v in zip(names, row)))
                      for row in product(*domains) if evaluate(e, dict(zip(names, row)), self.functions)))

    def tr(self, e: m.Expr, chosen=None):
        """식을 선택 원자의 명제식으로. chosen 은 selected 를 번역하는 함수다 (선택 제약에서만 준다)."""
        if isinstance(e, m.And):
            return f_and(*(self.tr(x, chosen) for x in e.items))
        if isinstance(e, m.Or):
            return f_or(*(self.tr(x, chosen) for x in e.items))
        if isinstance(e, m.Not):
            return f_not(self.tr(e.item, chosen))
        if isinstance(e, m.Selected):
            if chosen is None:
                raise AlgebraError(f"selected 는 선택 제약에서만 쓴다: {e!r}")
            return chosen(e)
        if isinstance(e, (m.Compare, m.Call, m.Var, m.Const)):
            return self.table(e)
        raise AlgebraError(f"분석 가능 단편 밖의 표현식: {e!r}")

    def select(self, rule: m.SelectRule, sp_path: tuple):
        cond = self.tr(rule.when)
        other = rule.otherwise
        if isinstance(other, m.SelectRule):
            rest = self.select(other, sp_path)
        elif other is None:
            rest = TRUE
        else:
            rest = sel(sp_path + (other,))
        return f_and(f_imp(cond, sel(sp_path + (rule.then,))), f_imp(f_not(cond), rest))

    # 노드와 주석 ---------------------------------------------------------

    def entity(self, def_name: str, path: tuple, replicas: tuple = ()) -> m.EntityDef:
        """엔티티 노드 하나와 그 주석(속성, 포트, 없음 표시, 프로파일의 항목, 문서 조립 틀)을 적는다."""
        self.kinds[path] = ENT
        self.labels[path] = def_name                 # 정의 표지: 이름과 별개
        e = self.doc.entities[def_name]
        if e.attributes:
            self.attrs[path] = {n: self.attribute(def_name, a, replicas) for n, a in e.attributes.items()}
        if e.kind is not None or e.fields or e.links:
            self.items[path] = Item(e.kind, dict(e.fields), dict(e.links))
        text = e.metadata.get("text") if e.metadata else None
        if isinstance(text, str):
            self.templates[path] = text
        elif isinstance(text, dict) and "template" in text:
            self.templates[path] = text["template"]
        if e.ports:
            self.ports[path] = {n: PortDecl(p.type, p.direction.value, p.required)
                                for n, p in e.ports.items()}
        if e.stereotype == m.Stereotype.VOID:
            self.void.add(path)
        return e

    @staticmethod
    def _separator(e: m.EntityDef, name: str) -> str:
        text = e.metadata.get("text") if e.metadata else None
        return (text.get("separators", {}) if isinstance(text, dict) else {}).get(name, "")

    def aspect(self, e: m.EntityDef, a: m.Aspect, path: tuple) -> tuple:
        """엔티티 노드 path 아래에 aspect 노드를 적는다. 부분들은 부르는 쪽이 이어서 적는다."""
        a_path = path + (a.name,)
        self.kinds[a_path] = ASP
        self.layouts[a_path] = (tuple(p.part_name for p in a.parts), self._separator(e, a.name))
        if a.couplings:
            self.coup[a_path] = _plain(a.couplings)
        return a_path

    def multi(self, e: m.EntityDef, ma: m.MultiAspect, n: int, path: tuple) -> tuple:
        """multi-aspect 의 개수 n 짜리 전개를 적는다. (aspect 노드, 복제본 이름들)을 돌려준다."""
        a_path = path + (f"{ma.name}[{n}]",)
        self.kinds[a_path] = ASP
        names = [_replica_name(ma, i, n) for i in range(n)]
        self.layouts[a_path] = (tuple(names), self._separator(e, ma.name))
        ks = _instantiate_pattern(ma, names)
        if ks:
            self.coup[a_path] = ks
        return a_path, names

    def rec(self, def_name: str, path: tuple, replicas: tuple = ()) -> None:
        """모든 선택지를 따라 내려가며 펼친다."""
        e = self.entity(def_name, path, replicas)
        for sp in e.specializations.values():
            sp_path = path + (sp.name,)
            self.kinds[sp_path] = SPEC
            for alt in sp.alternatives:
                self.rec(alt, sp_path + (alt,), replicas)
            if sp.select is not None:
                self.clauses.append(f_imp(sel(sp_path), self.select(sp.select, sp_path)))
        for a in e.aspects.values():
            a_path = self.aspect(e, a, path)
            for part in a.parts:
                self.rec(part.def_name, a_path + (part.part_name,), replicas)
            self.decomps.setdefault(path, []).append((a.name, (a_path,), a.rule, a.priority))
        for ma in e.multi_aspects.values():
            self.decomps.setdefault(path, []).append(
                (ma.name, tuple(path + (f"{ma.name}[{n}]",) for n in self.cards(ma)), ma.rule, ma.priority))
            for n in self.cards(ma):
                a_path, names = self.multi(e, ma, n, path)
                for i, name in enumerate(names):
                    self.rec(ma.part.def_name, a_path + (name,), replicas + ((i, n),))
                if isinstance(ma.cardinality, m.VarCard):
                    self.clauses.append(f_imp(sel(a_path), sel(self.value(ma.cardinality.var, n))))

    def variables(self) -> None:
        """변수를 뿌리의 specialization 으로 적는다. 값마다 노드 하나다."""
        for name in self.doc.variables:
            s = self.root + (var_node(name),)
            self.kinds[s] = SPEC
            for v in self.domain(name):
                self.kinds[s + (str(v),)] = ENT
        self.gone = frozenset(self.void)

    # 분해의 규칙과 우선순위 ---------------------------------------------

    def rules(self) -> None:
        """분해의 규칙과 우선순위를 제약식으로 옮기고 나무를 만든다. 밀릴 수 있는 구성원에게 "분해 없음"을,
        빠질 수 있는 구성요소의 구성원에게 "빠짐"을 준다."""
        kinds, labels, decomps, gone = self.kinds, self.labels, self.decomps, self.gone

        def together(y: tuple, z: tuple) -> bool:
            """한 병합체의 두 구성원이 함께 선택될 수 있는가. 같은 specialization의 서로 다른 대안 아래이면 아니다.

            두 경로가 갈라지는 자리의 부모가 specialization 이면 서로 다른 대안이고, 엔티티이면 서로 다른
            specialization 이다. 한쪽이 다른 쪽의 조상이면 함께 골라진다.
            """
            i = 0
            while i < min(len(y), len(z)) and y[i] == z[i]:
                i += 1
            return i == len(y) or i == len(z) or kinds[y[:i]] != SPEC

        plain = Tree(kinds, labels)
        rivals: dict = {}                            # 구성원에서, 함께 선택될 수 있고 분해를 가진 다른 구성원들로
        removable: dict = {}                         # 빠질 수 있는 구성요소의, 분해를 가진 구성원에서 그 구성요소로
        for e in components(plain):
            ms = members(plain, e)
            owners = [y for y in ms if y in decomps]
            voids = [z for z in ms if z in gone]
            for y in owners:
                rivals[y] = [z for z in owners if z != y and together(y, z)]
                if any(above(pb, pa) for z in rivals[y] for *_, pb in decomps[z] for *_, pa in decomps[y]):
                    kinds[y + (NO_ASPECT,)] = ASP
                if any(together(y, z) for z in voids):
                    kinds[y + (GONE,)] = ASP
                    removable[y] = e
        tree = self.tree = Tree(kinds, labels)

        # 빠진 구성요소의 구성원은 분해 대신 "빠짐"을 고른다. 그래서 그 아래는 아무것도 골라지지 않는다.
        # "빠짐"은 빠졌을 때만 고를 수 있다
        for y, e in removable.items():
            removed, marker = void_formula(tree, gone, e), sel(y + (GONE,))
            self.clauses.append(f_imp(f_and(sel(y), removed), marker))
            self.clauses.append(f_imp(marker, removed))

        def one_of(nodes):
            return sel(nodes[0]) if len(nodes) == 1 else f_or(*(sel(n) for n in nodes))

        # 분해의 규칙과 우선순위는 살아 있는 구성요소에서만 적용된다. 없음이 된 구성요소나 그 아래의 것은 만들어지지
        # 않으므로 거기서 두 규칙이 함께 참이 되어도 변이를 지우지 않는다. 고전 절차도 그런 곳은 평가하지 않는다
        for y, mine in decomps.items():
            alive = f_and(sel(y), live_formula(tree, gone, component_of(tree, y)))
            out = y + (NO_ASPECT,)
            pushed = sel(out) if out in tree.nodes else None
            ruled = [(d, self.tr(d[2])) for d in mine if d[2] is not None]

            def beaten(d):
                """같은 엔티티에서 우선순위가 더 높은 분해의 규칙이 참이다."""
                return [f for other, f in ruled if other is not d and above(other[3], d[3])]

            for d, holds_ in ruled:                  # 규칙이 참이면 그 분해를 고른다. 더 앞선 규칙이 참이면 물러선다
                guard = [alive, holds_] + [f_not(f) for f in beaten(d)] + ([f_not(pushed)] if pushed is not None else [])
                self.clauses.append(f_imp(f_and(*guard), one_of(d[1])))
            for d in mine:                           # 다른 구성원의 더 앞선 분해와 함께 고를 수 없다
                for z in rivals.get(y, ()):
                    for other in decomps[z]:
                        if above(other[3], d[3]):
                            self.clauses.append(f_imp(alive, f_not(f_and(one_of(d[1]), one_of(other[1])))))
            if pushed is not None:                   # 밀려나려면, 고를 수 있었던 분해가 실제로 밀려야 한다
                no_rule = f_not(f_or(*(f for _, f in ruled)))
                reasons = []
                for d in mine:
                    mine_ok = f_or(no_rule, *([f_and(next(f for o, f in ruled if o is d), *(f_not(f) for f in beaten(d)))]
                                              if d[2] is not None else []))
                    winners = [one_of(other[1]) for z in rivals[y] for other in decomps[z] if above(other[3], d[3])]
                    if winners:
                        reasons.append(f_and(mine_ok, f_or(*winners)))
                self.clauses.append(f_imp(f_and(alive, pushed), f_or(*reasons)))

    # 선택에 대한 제약 ---------------------------------------------------

    def chosen(self, e: m.Selected):
        """selected: 가리키는 선택지 노드가 골라졌고, 그 선택 지점이 실제로 있는 구성요소의 것이다."""
        tree, gone, doc = self.tree, self.gone, self.doc
        if e.path is None:
            def_name, _, group = e.node.partition("/")
            hosts = [(y, def_name) for y in occurrences(tree, def_name)]
        else:
            group, want = e.node, tuple(e.path)
            hosts = [(y, tree.label(y)) for q in tree.kinds
                     if tree.kind(q) == ENT and is_component(tree, q) and component_path(tree, q) == want
                     for y in members(tree, q)]
        options, found = [], False
        for y, def_name in hosts:
            kind, choice = selected_target(doc, e, def_name, group)
            if kind is None:
                continue                             # 이 구성원에는 그 선택 지점이 없다
            found = True
            c = component_of(tree, y)
            # 대안을 고르는 일은 그 구성요소가 놓일 자리가 살아 있으면 일어난다. 그 선택으로 구성요소가
            # 없음이 되어도 선택은 한 것이다. 분해를 고르는 일은 구성요소 자신이 살아 있어야 일어난다
            reached = TRUE if len(c) == 1 else live_formula(tree, gone, owner(tree, c[:-1]))
            if kind == "spec":
                options.append(f_and(sel(y + (group, str(choice))), reached))
            elif kind == "count":
                a = y + (f"{group}[{choice}]",)
                if a in tree.nodes:
                    options.append(f_and(sel(a), live_formula(tree, gone, c)))
            elif kind == "aspect":
                options += [f_and(sel(a), live_formula(tree, gone, c))
                            for a in tree.aspects(y) if family(a[-1]) == choice]
        if self.sigma is not None:
            return f_or(*options)                    # 결정된 변이 하나에서는 가리키는 곳이 없어도 거짓일 뿐이다
        if not hosts:
            raise AlgebraError(f"selected 가 가리키는 곳이 없다: {'/'.join(e.path) if e.path else e.node}")
        if not found:
            raise AlgebraError(f"selected 가 가리키는 선택지가 구성요소 {'/'.join(e.path)} 에 없다: "
                               f"{group or '분해'}={e.choice}")
        return f_or(*options)

    def constraints(self) -> None:
        for c in self.doc.constraints:
            body = f_and(*([self.tr(c.require, self.chosen)] if c.require is not None else []),
                         *([f_not(self.tr(c.forbid, self.chosen))] if c.forbid is not None else []))
            self.clauses.append(f_imp(self.tr(c.when, self.chosen), body) if c.when is not None else body)

    def result(self) -> dict:
        ann = Ann(self.ports, frozenset(self.void), self.coup)
        validate(self.tree, ann)
        typed = {name: {str(v): v for v in self.domain(name)} for name in self.doc.variables}
        return {"ses": SES(self.tree, f_and(*self.clauses)), "ann": ann, "attrs": self.attrs, "typed": typed,
                "labels": {p: self.labels[p] for p in self.attrs},
                "templates": self.templates, "layouts": self.layouts, "items": self.items}


def _unfold(doc: m.SesDocument, functions=None) -> dict:
    u = Unfolding(doc, functions)
    u.rec(doc.root.name, u.root)
    u.variables()
    u.rules()
    u.constraints()
    return u.result()


def reachable(doc: m.SesDocument) -> list:
    """뿌리에서 닿는 정의들. 펼친 나무에 나타나는 정의는 이것들뿐이다."""
    seen, stack = {}, [doc.root.name]
    while stack:
        name = stack.pop()
        if name in seen or name not in doc.entities:
            continue
        e = seen[name] = doc.entities[name]
        stack += [p.def_name for a in e.aspects.values() for p in a.parts]
        stack += [ma.part.def_name for ma in e.multi_aspects.values()]
        stack += [alt for sp in e.specializations.values() for alt in sp.alternatives]
    return list(seen.values())


def extensions_of(doc: m.SesDocument) -> set:
    """족 전체를 펼쳤을 때 얹힐 확장의 이름들. 펼치지 않고 문서만 보고 정한다.

    변이 하나만 만든 나무에는 주석이 하나도 없는 확장이 있을 수 있다. 그때도 족과 같은 확장을 얹어야
    해석의 모양이 같다.
    """
    out = set()
    for e in reachable(doc):
        if e.ports or any(a.couplings for a in e.aspects.values()):
            out.add("devs")
        for ma in e.multi_aspects.values():
            c = ma.cardinality
            top = c.n if isinstance(c, m.Fixed) else max(_domain(doc, c.var)) if isinstance(c, m.VarCard) \
                else (c.max if c.max is not None else max(c.min, 2))
            n = min(top, 2)                          # 복제본이 둘이면 결합 틀의 모든 항이 결합을 낸다
            if _instantiate_pattern(ma, [_replica_name(ma, i, n) for i in range(n)]):
                out.add("devs")
        if e.attributes:
            out.add("attr")
        text = e.metadata.get("text") if e.metadata else None
        if isinstance(text, str) or (isinstance(text, dict) and "template" in text):
            out.add("text")
        if e.kind is not None or e.fields or e.links:
            out.add("domain")
    if doc.profile is not None:
        out.add("domain")
    return out


def layered(doc: m.SesDocument, u: dict, profile: Profile = None, present=()) -> Layered:
    """펼친 결과에 정준 문서가 담은 확장들을 얹는다. present 는 주석이 없어도 얹을 확장의 이름들이다."""
    ann = u["ann"]
    exts = []
    if ann.ports or ann.coup or "devs" in present:
        exts.append(Coupling(ann.ports, ann.coup))
    if u["attrs"] or "attr" in present:
        exts.append(Attributes(u["attrs"], u["typed"], u["labels"]))
    if u["templates"] or "text" in present:
        exts.append(Text(u["templates"], u["layouts"]))
    if doc.profile is not None or u["items"] or "domain" in present:
        if profile is None:
            raise AlgebraError(f"문서가 프로파일 {doc.profile} 을 따른다. 프로파일을 함께 주어야 한다")
        if doc.profile is not None and doc.profile != profile.name:
            raise AlgebraError(f"문서의 프로파일은 {doc.profile} 인데 {profile.name} 이 주어졌다")
        exts.append(Domain(profile, u["items"]))
    return Layered(u["ses"], ann.void, tuple(exts))


def unfold_annotated(doc: m.SesDocument, functions=None) -> tuple:
    """SES와 결합 주석(포트, 없음 대안, 결합). functions 는 이름에서 등록한 함수로 가는 사전이다."""
    u = _unfold(doc, functions)
    return u["ses"], u["ann"]


def unfold(doc: m.SesDocument, functions=None) -> SES:
    return _unfold(doc, functions)["ses"]


def unfold_layered(doc: m.SesDocument, profile: Profile = None, functions=None) -> Layered:
    """정준 문서가 담은 확장들을 얹은 것.

    포트와 결합(DEVS), 속성(Attr)은 정준 YAML의 내장 열쇠에서, 문서 조립 틀(Text)은
    엔티티의 metadata.text 에서 읽는다. 문서가 프로파일을 따르면(profile 열쇠)
    kind, fields, links 를 그 프로파일로 해석하는 범용 확장(Domain)을 얹는다.
    쓰이지 않는 확장은 얹지 않는다. functions 는 식의 call 이 부르는 함수들이다.
    """
    return layered(doc, _unfold(doc, functions), profile)


def pruning_patterns(doc: m.SesDocument) -> list:
    """접힌 형태의 가지치기 SES를 정의별 패턴으로 바꾼다.

    가지치기 SES의 포트와 결합은 연산에 참여하지 않으므로 읽지 않는다.
    """
    if doc.variables or doc.constraints:
        raise AlgebraError("접힌 가지치기 SES의 변수와 제약은 아직 지원하지 않는다")
    out = []
    for name, e in doc.entities.items():
        kinds: dict = {(name,): ENT}
        for sp in e.specializations.values():
            if sp.select is not None:
                raise AlgebraError("접힌 가지치기 SES의 선택 규칙은 아직 지원하지 않는다")
            kinds[(name, sp.name)] = SPEC
            for alt in sp.alternatives:
                kinds[(name, sp.name, alt)] = ENT
        for a in e.aspects.values():
            kinds[(name, a.name)] = ASP
        for ma in e.multi_aspects.values():
            for n in _card_set(doc, ma):
                kinds[(name, f"{ma.name}[{n}]")] = ASP
        if e.aspects or e.multi_aspects:
            kinds[(name, GONE)] = ASP                # 분해를 남기는 패턴도 빠짐은 남긴다. 사람이 고르는 것이 아니다
        if len(kinds) > 1:
            out.append(SES(Tree(kinds)))
    return out
