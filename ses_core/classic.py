"""고전 SES/MB의 절차적 의미 (docs/ses-platform/14_executors.md 7절).

문헌의 도구는 가지치기를 절차로 한다. 변수 값을 정하고, 뿌리에서 아래로 내려가며
specialization의 대안과 aspect를 고르고, 고른 대안을 엔티티에 합치고(inheritance),
남은 나무에서 결합 모델을 조립한다. 이 모듈은 그 절차를 정의 표 위에 그대로 적은 것이다.

펼친 나무, 선택 대수, 뼈대, 확장 계약 가운데 어느 것도 쓰지 않는다. 그래서 대수의 길
(펼치기, 변이 열거, 해석)이 낸 결과와 대조하면 두 의미가 같은지를 독립적으로 확인할 수
있다 (정리 22). multi-aspect의 결합 틀을 개수에 맞게 펼치는 일만 unfold의 함수를 빌린다.

속성의 값도 여기서 따로 정한다 (docs/ses-platform/18_classic_parity.md 4절). 구조를 조립한 뒤
위에서 아래로 내려가며, 합쳐진 정의들 가운데 자식(고른 대안)의 값으로 부모의 값을 덮는다.

문헌에는 이 절차의 형식 정의가 없다. 여기 적은 것은 문헌의 서술을 따른 한 가지 정식화다.
"""

from __future__ import annotations

from itertools import product
from typing import Optional

from . import model as m
from .loader import selected_target
from .unfold import _OPS, _domain, _instantiate_pattern, _replica_name


def _value(e: m.Expr, sigma: dict, functions, replicas: tuple = ()):
    """값으로 쓰는 식: 상수, 변수, 등록한 함수의 호출, 복제본의 번호와 개수.

    replicas 는 그 자리를 감싼 복제본들의 (번호, 개수)를 바깥에서 안으로 적은 것이다.
    """
    if isinstance(e, m.Const):
        return e.value
    if isinstance(e, m.Var):
        return sigma[e.name]
    if isinstance(e, m.Call):
        return functions[e.fn](*(_value(a, sigma, functions, replicas) for a in e.args))
    if isinstance(e, m.Replica):
        i, n = replicas[len(replicas) - 1 - e.up]
        return i if e.what == "index" else n
    return _eval(e, sigma, functions, replicas=replicas)


def _eval(e: Optional[m.Expr], sigma: dict, functions=None, picks=None, doc=None, replicas: tuple = ()) -> bool:
    """규칙과 제약의 식을 변수 값 sigma 에서 평가한다. picks 는 조립하면서 한 선택들이다(selected 용)."""
    if e is None:
        return True
    if isinstance(e, m.Compare):
        return bool(_OPS[e.op](_value(e.left, sigma, functions, replicas), _value(e.right, sigma, functions, replicas)))
    if isinstance(e, m.And):
        return all(_eval(x, sigma, functions, picks, doc, replicas) for x in e.items)
    if isinstance(e, m.Or):
        return any(_eval(x, sigma, functions, picks, doc, replicas) for x in e.items)
    if isinstance(e, m.Not):
        return not _eval(e.item, sigma, functions, picks, doc, replicas)
    if isinstance(e, (m.Call, m.Var, m.Const, m.Replica)):
        return bool(_value(e, sigma, functions, replicas))
    if isinstance(e, m.Selected) and picks is not None and e.path is None:
        def_name, _, group = e.node.partition("/")
        kind, choice = selected_target(doc, e, def_name, group)
        return (kind, def_name, group, choice) in picks
    raise ValueError(f"절차적 의미가 다루지 않는 식: {e!r}")


def _above(p, q) -> bool:
    """우선순위 p가 q보다 앞서는가. 수가 작을수록 앞선다. 없는 것은 가장 뒤이고, 없는 것끼리는 가르지 못한다."""
    return p is not None and (q is None or p < q)


def _mentions_selected(e) -> bool:
    if isinstance(e, m.Selected):
        return True
    kids = list(getattr(e, "items", ()) or ()) + [getattr(e, a) for a in ("left", "right", "item") if hasattr(e, a)]
    return any(_mentions_selected(x) for x in kids)


def _allowed(sp: m.Specialization, sigma: dict, functions=None) -> list:
    """선택 규칙이 정하는 대안. 규칙이 정하지 않으면 모든 대안 가운데 고른다."""
    rule = sp.select
    while rule is not None:
        if _eval(rule.when, sigma, functions):
            return [rule.then]
        if isinstance(rule.otherwise, m.SelectRule):
            rule = rule.otherwise
        elif rule.otherwise is None:
            break
        else:
            return [rule.otherwise]
    return list(sp.alternatives)


def _own_value(a: m.Attribute, sigma: dict, functions, replicas: tuple):
    """정의가 그 속성에 주는 값. 주지 않으면 None."""
    if a.each is not None:
        i = replicas[-1][0] if replicas else None
        return a.each[i] if i is not None and i < len(a.each) else a.default
    if a.expr is not None:
        return _value(a.expr, sigma, functions, replicas)
    return a.default


def _inherit(doc, cluster: tuple, sigma: dict, functions, replicas: tuple, by_def: dict) -> tuple:
    """합쳐진 정의들의 속성. 자식(고른 대안)의 값이 부모의 값을 덮는다 (inheritance 공리).

    cluster 는 (정의, 그 정의의 specialization마다 고른 대안의 cluster 들)이다.
    (값, 타입, 타입이 어긋난 이름들, 서로 다른 대안이 다른 값을 준 이름들)을 돌려준다.
    """
    def_name, kids = cluster
    values, types, bad_type, bad_value = {}, {}, set(), set()
    for a in doc.entities[def_name].attributes.values():
        types[a.name] = a.type
        v = by_def[(def_name, a.name)] if (def_name, a.name) in by_def else _own_value(a, sigma, functions, replicas)
        if v is not None:
            values[a.name] = v
    below: dict = {}
    for kid in kids:
        kv, kt, kbt, kbv = _inherit(doc, kid, sigma, functions, replicas, by_def)
        bad_type |= kbt
        bad_value |= kbv
        for name, t in kt.items():
            if types.setdefault(name, t) != t:
                bad_type.add(name)
        for name, v in kv.items():
            if name in below and repr(below[name]) != repr(v):
                bad_value.add(name)                           # 평가 순서로 정하지 않는다. 합칠 수 없다
            below[name] = v
    values.update(below)
    return values, types, bad_type, bad_value


def _with_attributes(doc, node: dict, sigma: dict, functions, path: tuple, replicas: tuple,
                     by_def: dict, by_path: dict) -> dict:
    """조립한 구조에 속성 값을 붙인다. 구조는 정의마다 한 번 만들어 여러 자리에서 함께 쓰므로 새로 적는다."""
    values, types, bad_type, bad_value = _inherit(doc, node["cluster"], sigma, functions, replicas, by_def)
    for name in types:
        if (path, name) in by_path:                           # 구성요소에 직접 준 값이 구성원들의 값을 대신한다
            values[name] = by_path[(path, name)]
            bad_value.discard(name)
    kids = {name: _with_attributes(doc, c, sigma, functions, path + (name,),
                                   replicas + ((node["replicas"][name],) if name in node["replicas"] else ()),
                                   by_def, by_path)
            for name, c in node["children"].items()}
    return dict(node, children=kids, attrs={name: values.get(name) for name in types},
                attr_clash=sorted(bad_type | bad_value))


def decompositions(owners: list, sigma: dict, functions=None) -> list:
    """병합체의 구성원들 가운데 그 구성요소의 분해가 될 수 있는 (정의, 분해)들.

    owners 는 분해(aspect 나 multi-aspect)를 가진 구성원의 정의들이다. 구성원마다 규칙이 허락하는
    분해를 구하고, 병합으로 형제가 된 분해들 가운데 우선순위가 가장 높은 것만 남긴다. 다른 구성원은
    모두 밀려야 한다. 가르지 못하면 아무것도 남지 않는다.
    """
    allowed, real = {}, {}
    for e in owners:
        fams = list(e.aspects.values()) + list(e.multi_aspects.values())
        forced = [a for a in fams if a.rule is not None and _eval(a.rule, sigma, functions)]
        if not forced:
            allowed[e.name] = real[e.name] = fams             # 참인 규칙이 없으면 어느 것이나 고를 수 있다
            continue
        top = [a for a in forced if not any(_above(b.priority, a.priority) for b in forced)]
        allowed[e.name] = top                                 # 우선순위가 가장 높은 것. 가르지 못하면 여럿이다
        real[e.name] = top if len(top) == 1 else []           # 두 규칙이 서로 다른 분해를 요구하면 고를 수 없다
    return [(e, a) for e in owners for a in real[e.name]
            if all(any(_above(a.priority, b.priority) for b in allowed[z.name]) for z in owners if z is not e)]


def enumerate_classic(doc: m.SesDocument, functions=None, overrides=()) -> list:
    """절차적 가지치기와 조립으로 얻는 (변수 값, 구조)의 목록.

    구조는 결합 확장의 해석과 같은 모양의 중첩 사전이고, 구성요소마다 합쳐진 정의들의 이름
    (labels), 속성의 값(attrs), 값을 합칠 수 없는 속성의 이름(attr_clash)이 더 붙는다. 합칠 수
    없는 경우(같은 이름의 포트를 다르게 선언, 엔티티와 고른 대안이 각자 분해를 가지는데 우선순위로
    가를 수 없음)와 뿌리가 없음이 되는 경우는 내놓지 않는다. 속성을 합칠 수 없는 구조는 내놓되 표시한다.

    변수만 보는 제약은 조립하기 전에 검사한다. 선택에 대한 제약(selected)은 조립하면서 한 선택들을
    모아 두었다가 조립한 뒤에 검사한다. functions 는 식의 call 이 부르는 함수들이다.
    overrides 는 속성 값의 재정의들이다. ("at", 정의, 속성, 값) 또는 ("path", 구성요소 경로, 속성, 값).
    """
    by_def = {(where, name): v for kind, where, name, v in overrides if kind == "at"}
    by_path = {(tuple(where), name): v for kind, where, name, v in overrides if kind == "path"}
    names = list(doc.variables)
    late = [c for c in doc.constraints if any(x is not None and _mentions_selected(x) for x in (c.when, c.require, c.forbid))]
    early = [c for c in doc.constraints if c not in late]

    def satisfied(c, sigma, picks=None) -> bool:
        if not _eval(c.when, sigma, functions, picks, doc):
            return True
        return (c.require is None or _eval(c.require, sigma, functions, picks, doc)) \
            and (c.forbid is None or not _eval(c.forbid, sigma, functions, picks, doc))

    out = []
    for values in product(*(_domain(doc, n) for n in names)):
        sigma = dict(zip(names, values))
        if not all(satisfied(c, sigma) for c in early):
            continue
        memo: dict = {}
        for s, picks in _build(doc, doc.root.name, sigma, memo, functions):
            if s is not None and all(satisfied(c, sigma, picks) for c in late):
                out.append((sigma, _with_attributes(doc, s, sigma, functions, (doc.root.name,), (), by_def, by_path)))
    return out


def counts_of(ma: m.MultiAspect, sigma: dict) -> list:
    """변수 값이 sigma 일 때 그 multi-aspect 가 가질 수 있는 복제본의 수."""
    card = ma.cardinality
    if isinstance(card, m.Fixed):
        return [card.n]
    if isinstance(card, m.VarCard):
        return [sigma[card.var]]
    return list(range(card.min, card.max + 1))


def _clusters(doc, def_name: str, sigma: dict, functions=None) -> list:
    """엔티티에서 시작해 specialization마다 대안을 하나씩 골라 합쳐지는 정의들의 목록들.

    목록마다 그때 한 선택들 (spec, 정의, specialization, 대안)과, 누가 누구의 대안인지를 적은 나무
    (정의, 고른 대안들의 나무)가 함께 온다.
    """
    options = []
    for sp in doc.entities[def_name].specializations.values():
        options.append([(ms, picks | {("spec", def_name, sp.name, alt)}, tree)
                        for alt in _allowed(sp, sigma, functions)
                        for ms, picks, tree in _clusters(doc, alt, sigma, functions)])
    return [([def_name] + [x for ms, _, _ in combo for x in ms], frozenset().union(*(p for _, p, _ in combo)),
             (def_name, tuple(t for _, _, t in combo)))
            for combo in product(*options)]


def _build(doc, def_name: str, sigma: dict, memo: dict, functions=None) -> list:
    """정의 하나에서 만들어질 수 있는 구성요소들과, 그것을 만들며 한 선택들. None은 없음(빠지는 구성요소)이다."""
    if def_name in memo:
        return memo[def_name]
    results: list = []
    for members, chosen, cluster in _clusters(doc, def_name, sigma, functions):
        ents = [doc.entities[x] for x in members]
        if any(e.stereotype == m.Stereotype.VOID for e in ents):
            results.append((None, chosen))                    # 빠진다. 대안을 고른 것까지는 한 선택이다
            continue
        ports: dict = {}
        required: set = set()
        clash = False
        for e in ents:                                        # inheritance: 포트를 합친다
            for p in e.ports.values():
                decl = (p.type, p.direction.value)
                clash = clash or ports.setdefault(p.name, decl) != decl
                if p.required:
                    required.add(p.name)
        owners = [e for e in ents if e.aspects or e.multi_aspects]
        if clash:
            continue                                          # 합칠 수 없다
        base = {"labels": sorted(members), "ports": ports, "required": sorted(required), "cluster": cluster,
                "replicas": {}}
        if not owners:
            results.append((dict(base, children={}, eic=[], eoc=[], ic=[]), chosen))
            continue
        choices = []                                          # (부분의 (이름, 정의) 목록, 결합, 이때 한 선택, 복제본의 번호)
        for e, a in decompositions(owners, sigma, functions):
            if isinstance(a, m.Aspect):
                ks = [((c.src.part, c.src.port), (c.dst.part, c.dst.port)) for c in a.couplings]
                choices.append(([(p.part_name, p.def_name) for p in a.parts], ks,
                                {("aspect", e.name, "", a.name)}, {}))
                continue
            for n in counts_of(a, sigma):
                replicas = [_replica_name(a, i, n) for i in range(n)]
                choices.append(([(r, a.part.def_name) for r in replicas], list(_instantiate_pattern(a, replicas)),
                                {("aspect", e.name, "", a.name), ("count", e.name, a.name, n)},
                                {r: (i, n) for i, r in enumerate(replicas)}))
        for parts, ks, mine, numbered in choices:
            for combo in product(*(_build(doc, d, sigma, memo, functions) for _, d in parts)):
                kids = {name: c for (name, _), (c, _) in zip(parts, combo) if c is not None}
                node = dict(base, children=kids, eic=[], eoc=[], ic=[], replicas=numbered)
                for (sw, sp), (dw, dp) in dict.fromkeys(ks):  # 빠진 부분을 가리키는 결합은 버린다. 같은 결합은 하나다
                    if (sw is not None and sw not in kids) or (dw is not None and dw not in kids):
                        continue
                    if sw is None:
                        node["eic"].append((sp, (dw, dp)))
                    elif dw is None:
                        node["eoc"].append(((sw, sp), dp))
                    else:
                        node["ic"].append(((sw, sp), (dw, dp)))
                results.append((node, chosen | mine | frozenset().union(*(p for _, p in combo))))
    memo[def_name] = results
    return results
