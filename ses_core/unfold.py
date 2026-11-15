"""정준 SES 문서(SesDocument)와 가지치기 대수(algebra, coupling) 사이의 다리.

- unfold_annotated(doc): 정의 테이블을 뿌리에서 펼쳐 SES 트리, 제약식, 주석
  (포트, 없음 대안, 결합)을 만든다. multi-aspect는 개수별 aspect로 전개하고
  결합 틀을 개수마다 사례화한다. 변수는 뿌리의 specialization으로, 선택 규칙과
  선택 제약은 제약식으로 부호화한다.
- unfold(doc): 주석 없이 SES만 돌려준다.
- pruning_patterns(doc): 접힌 형태의 가지치기 SES를 정의별 높이 2 패턴의
  모음으로 바꾼다. 각 패턴은 그 정의의 모든 출현에 적용된다.

기본값(default)과 우선순위(priority)는 변이 공간을 바꾸지 않는 선호이므로
여기서는 다루지 않는다.

식 (docs/ses-platform/18_classic_parity.md)
- 규칙과 제약의 원자는 변수에 대한 조건이다. 변수의 범위가 유한하므로 원자가 참이 되는 변수 값의
  조합을 모두 적어 명제식으로 바꾼다. 변수와 상수의 비교, 변수끼리의 비교, 이름으로 등록한 함수의
  호출(call)이 모두 같은 방법으로 처리된다. 함수의 본문은 코드에 있지만 문서에는 이름만 남고,
  분석은 함수의 값의 표만 본다. 함수는 같은 인자에 늘 같은 값을 내야 한다.
- selected 는 선택 제약에서만 쓴다. 가리키는 선택지 노드가 골라졌고 그 선택 지점이 실제로 있는
  구성요소의 것일 때 참이다. 없음이 된 구성요소 아래에서 한 선택은 세지 않는다.
"""

from __future__ import annotations

import operator
from itertools import product

from . import model as m
from .algebra import (ASP, ENT, SPEC, SES, TRUE, AlgebraError, Tree,
                      f_and, f_imp, f_not, f_or, occurrences, sel)
from .coupling import SELF, Ann, Coupling, PortDecl, validate
from .decisions import component_path, family
from .ext_attr import AttrDecl, Attributes
from .ext_text import Text
from .extension import Layered
from .loader import selected_target
from .profile import Domain, Item, Profile
from .skeleton import component_of, is_component, live_formula, members, owner

_OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le,
        "gt": operator.gt, "ge": operator.ge, "in": lambda v, c: v in c}
MAX_ROWS = 20000                 # 원자 하나의 표가 가질 수 있는 변수 값 조합의 수


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


def _unfold(doc: m.SesDocument, functions=None) -> dict:
    root = (doc.root.name,)
    kinds: dict = {}
    labels: dict = {}
    clauses: list = []
    ports: dict = {}
    void: set = set()
    coup: dict = {}
    attrs: dict = {}
    templates: dict = {}
    layouts: dict = {}
    items: dict = {}
    aspect_rules: list = []                          # (엔티티 노드, aspect 노드, 규칙). 나무가 다 만들어진 뒤에 번역한다

    def value(name: str, v) -> tuple:
        return root + (var_node(name), str(v))

    def table(e: m.Expr):
        """변수에 대한 조건 하나를, 그것이 참이 되는 변수 값의 조합들로 적는다."""
        names = sorted(expr_vars(e))
        domains = [_domain(doc, n) for n in names]
        rows = 1
        for d in domains:
            rows *= len(d)
        if rows > MAX_ROWS:
            raise AlgebraError(f"조건의 표가 너무 크다. 변수 {names} 의 값 조합이 {rows} 가지다: {e!r}")
        return f_or(*(f_and(*(sel(value(n, v)) for n, v in zip(names, row)))
                      for row in product(*domains) if evaluate(e, dict(zip(names, row)), functions)))

    def tr(e: m.Expr, chosen=None):
        """식을 선택 원자의 명제식으로. chosen 은 selected 를 번역하는 함수다 (선택 제약에서만 준다)."""
        if isinstance(e, m.And):
            return f_and(*(tr(x, chosen) for x in e.items))
        if isinstance(e, m.Or):
            return f_or(*(tr(x, chosen) for x in e.items))
        if isinstance(e, m.Not):
            return f_not(tr(e.item, chosen))
        if isinstance(e, m.Selected):
            if chosen is None:
                raise AlgebraError(f"selected 는 선택 제약에서만 쓴다: {e!r}")
            return chosen(e)
        if isinstance(e, (m.Compare, m.Call, m.Var, m.Const)):
            return table(e)
        raise AlgebraError(f"분석 가능 단편 밖의 표현식: {e!r}")

    def select(rule: m.SelectRule, sp_path: tuple):
        cond = tr(rule.when)
        other = rule.otherwise
        if isinstance(other, m.SelectRule):
            rest = select(other, sp_path)
        elif other is None:
            rest = TRUE
        else:
            rest = sel(sp_path + (other,))
        return f_and(f_imp(cond, sel(sp_path + (rule.then,))), f_imp(f_not(cond), rest))

    def rec(def_name: str, path: tuple) -> None:
        kinds[path] = ENT
        labels[path] = def_name                      # 정의 표지: 이름과 별개
        e = doc.entities[def_name]
        if e.attributes:
            attrs[path] = {n: AttrDecl(a.type.value, a.default) for n, a in e.attributes.items()}
        if e.kind is not None or e.fields or e.links:
            items[path] = Item(e.kind, dict(e.fields), dict(e.links))
        text = e.metadata.get("text") if e.metadata else None
        if isinstance(text, str):
            templates[path] = text
        elif isinstance(text, dict) and "template" in text:
            templates[path] = text["template"]
        seps = text.get("separators", {}) if isinstance(text, dict) else {}
        if e.ports:
            ports[path] = {n: PortDecl(p.type, p.direction.value, p.required)
                           for n, p in e.ports.items()}
        if e.stereotype == m.Stereotype.VOID:
            void.add(path)
        for sp in e.specializations.values():
            sp_path = path + (sp.name,)
            kinds[sp_path] = SPEC
            for alt in sp.alternatives:
                rec(alt, sp_path + (alt,))
            if sp.select is not None:
                clauses.append(f_imp(sel(sp_path), select(sp.select, sp_path)))
        for a in e.aspects.values():
            a_path = path + (a.name,)
            kinds[a_path] = ASP
            for part in a.parts:
                rec(part.def_name, a_path + (part.part_name,))
            layouts[a_path] = (tuple(p.part_name for p in a.parts), seps.get(a.name, ""))
            if a.couplings:
                coup[a_path] = _plain(a.couplings)
            if a.rule is not None:
                aspect_rules.append((path, a_path, a.rule))
        for ma in e.multi_aspects.values():
            for n in _card_set(doc, ma):
                a_path = path + (f"{ma.name}[{n}]",)
                kinds[a_path] = ASP
                names = [_replica_name(ma, i, n) for i in range(n)]
                for name in names:
                    rec(ma.part.def_name, a_path + (name,))
                layouts[a_path] = (tuple(names), seps.get(ma.name, ""))
                ks = _instantiate_pattern(ma, names)
                if ks:
                    coup[a_path] = ks
                if isinstance(ma.cardinality, m.VarCard):
                    clauses.append(f_imp(sel(a_path), sel(value(ma.cardinality.var, n))))

    rec(doc.root.name, root)
    for name in doc.variables:
        s = root + (var_node(name),)
        kinds[s] = SPEC
        for v in _domain(doc, name):
            kinds[s + (str(v),)] = ENT
    tree = Tree(kinds, labels)
    gone = frozenset(void)
    # 분해의 규칙은 살아 있는 구성요소에서만 적용된다. 없음이 된 구성요소나 그 아래의 것은 만들어지지 않으므로
    # 거기서 두 규칙이 함께 참이 되어도 변이를 지우지 않는다. 고전 절차도 그런 곳의 규칙은 평가하지 않는다
    for y, a_path, rule in aspect_rules:
        alive = live_formula(tree, gone, component_of(tree, y))
        clauses.append(f_imp(f_and(sel(y), alive, tr(rule)), sel(a_path)))

    def chosen(e: m.Selected):
        """selected: 가리키는 선택지 노드가 골라졌고, 그 선택 지점이 실제로 있는 구성요소의 것이다."""
        if e.path is None:
            def_name, _, group = e.node.partition("/")
            hosts = [(y, def_name) for y in occurrences(tree, def_name)]
        else:
            group, want = e.node, tuple(e.path)
            hosts = [(y, tree.label(y)) for q in tree.nodes
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
        if not hosts:
            raise AlgebraError(f"selected 가 가리키는 곳이 없다: {'/'.join(e.path) if e.path else e.node}")
        if not found:
            raise AlgebraError(f"selected 가 가리키는 선택지가 구성요소 {'/'.join(e.path)} 에 없다: "
                               f"{group or '분해'}={e.choice}")
        return f_or(*options)

    for c in doc.constraints:
        body = f_and(*([tr(c.require, chosen)] if c.require is not None else []),
                     *([f_not(tr(c.forbid, chosen))] if c.forbid is not None else []))
        clauses.append(f_imp(tr(c.when, chosen), body) if c.when is not None else body)
    ann = Ann(ports, frozenset(void), coup)
    validate(tree, ann)
    return {"ses": SES(tree, f_and(*clauses)), "ann": ann, "attrs": attrs,
            "templates": templates, "layouts": layouts, "items": items}


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
    u = _unfold(doc, functions)
    ann = u["ann"]
    exts = []
    if ann.ports or ann.coup:
        exts.append(Coupling(ann.ports, ann.coup))
    if u["attrs"]:
        exts.append(Attributes(u["attrs"]))
    if u["templates"]:
        exts.append(Text(u["templates"], u["layouts"]))
    if doc.profile is not None or u["items"]:
        if profile is None:
            raise AlgebraError(f"문서가 프로파일 {doc.profile} 을 따른다. 프로파일을 함께 주어야 한다")
        if doc.profile is not None and doc.profile != profile.name:
            raise AlgebraError(f"문서의 프로파일은 {doc.profile} 인데 {profile.name} 이 주어졌다")
        exts.append(Domain(profile, u["items"]))
    return Layered(u["ses"], ann.void, tuple(exts))


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
        if len(kinds) > 1:
            out.append(SES(Tree(kinds)))
    return out
