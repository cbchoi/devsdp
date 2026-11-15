"""고전 SES/MB의 절차적 의미 (docs/ses-platform/14_executors.md 7절).

문헌의 도구는 가지치기를 절차로 한다. 변수 값을 정하고, 뿌리에서 아래로 내려가며
specialization의 대안과 aspect를 고르고, 고른 대안을 엔티티에 합치고(inheritance),
남은 나무에서 결합 모델을 조립한다. 이 모듈은 그 절차를 정의 표 위에 그대로 적은 것이다.

펼친 나무, 선택 대수, 뼈대, 확장 계약 가운데 어느 것도 쓰지 않는다. 그래서 대수의 길
(펼치기, 변이 열거, 해석)이 낸 결과와 대조하면 두 의미가 같은지를 독립적으로 확인할 수
있다 (정리 22). multi-aspect의 결합 틀을 개수에 맞게 펼치는 일만 unfold의 함수를 빌린다.

문헌에는 이 절차의 형식 정의가 없다. 여기 적은 것은 문헌의 서술을 따른 한 가지 정식화다.
"""

from __future__ import annotations

from itertools import product
from typing import Optional

from . import model as m
from .loader import selected_target
from .unfold import _OPS, _domain, _instantiate_pattern, _replica_name


def _value(e: m.Expr, sigma: dict, functions):
    """값으로 쓰는 식: 상수, 변수, 등록한 함수의 호출."""
    if isinstance(e, m.Const):
        return e.value
    if isinstance(e, m.Var):
        return sigma[e.name]
    if isinstance(e, m.Call):
        return functions[e.fn](*(_value(a, sigma, functions) for a in e.args))
    return _eval(e, sigma, functions)


def _eval(e: Optional[m.Expr], sigma: dict, functions=None, picks=None, doc=None) -> bool:
    """규칙과 제약의 식을 변수 값 sigma 에서 평가한다. picks 는 조립하면서 한 선택들이다(selected 용)."""
    if e is None:
        return True
    if isinstance(e, m.Compare):
        return bool(_OPS[e.op](_value(e.left, sigma, functions), _value(e.right, sigma, functions)))
    if isinstance(e, m.And):
        return all(_eval(x, sigma, functions, picks, doc) for x in e.items)
    if isinstance(e, m.Or):
        return any(_eval(x, sigma, functions, picks, doc) for x in e.items)
    if isinstance(e, m.Not):
        return not _eval(e.item, sigma, functions, picks, doc)
    if isinstance(e, (m.Call, m.Var, m.Const)):
        return bool(_value(e, sigma, functions))
    if isinstance(e, m.Selected) and picks is not None and e.path is None:
        def_name, _, group = e.node.partition("/")
        kind, choice = selected_target(doc, e, def_name, group)
        return (kind, def_name, group, choice) in picks
    raise ValueError(f"절차적 의미가 다루지 않는 식: {e!r}")


def _above(p, q) -> bool:
    """우선순위 p가 q보다 앞서는가. 수가 클수록 앞선다. 없는 것은 가장 뒤이고, 없는 것끼리는 가르지 못한다."""
    return p is not None and (q is None or p > q)


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


def enumerate_classic(doc: m.SesDocument, functions=None) -> list:
    """절차적 가지치기와 조립으로 얻는 (변수 값, 구조)의 목록.

    구조는 결합 확장의 해석과 같은 모양의 중첩 사전이고, 구성요소마다 합쳐진 정의들의 이름
    (labels)이 더 붙는다. 합칠 수 없는 경우(같은 이름의 포트를 다르게 선언, 엔티티와 고른
    대안이 각자 분해를 가지는데 우선순위로 가를 수 없음)와 뿌리가 없음이 되는 경우는 내놓지 않는다.

    변수만 보는 제약은 조립하기 전에 검사한다. 선택에 대한 제약(selected)은 조립하면서 한 선택들을
    모아 두었다가 조립한 뒤에 검사한다. functions 는 식의 call 이 부르는 함수들이다.
    """
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
                out.append((sigma, s))
    return out


def _clusters(doc, def_name: str, sigma: dict, functions=None) -> list:
    """엔티티에서 시작해 specialization마다 대안을 하나씩 골라 합쳐지는 정의들의 목록들.

    목록마다 그때 한 선택들 (spec, 정의, specialization, 대안)이 함께 온다.
    """
    options = []
    for sp in doc.entities[def_name].specializations.values():
        options.append([(ms, picks | {("spec", def_name, sp.name, alt)})
                        for alt in _allowed(sp, sigma, functions) for ms, picks in _clusters(doc, alt, sigma, functions)])
    return [([def_name] + [x for ms, _ in combo for x in ms], frozenset().union(*(p for _, p in combo)))
            for combo in product(*options)]


def _build(doc, def_name: str, sigma: dict, memo: dict, functions=None) -> list:
    """정의 하나에서 만들어질 수 있는 구성요소들과, 그것을 만들며 한 선택들. None은 없음(빠지는 구성요소)이다."""
    if def_name in memo:
        return memo[def_name]
    results: list = []
    for members, chosen in _clusters(doc, def_name, sigma, functions):
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
        base = {"labels": sorted(members), "ports": ports, "required": sorted(required)}
        if not owners:
            results.append((dict(base, children={}, eic=[], eoc=[], ic=[]), chosen))
            continue
        # 구성원마다, 규칙이 허락하는 분해들과 그 가운데 실제로 고를 수 있는 것들
        allowed, real = {}, {}
        for e in owners:
            fams = list(e.aspects.values()) + list(e.multi_aspects.values())
            forced = [a for a in fams if a.rule is not None and _eval(a.rule, sigma, functions)]
            if not forced:
                allowed[e.name] = real[e.name] = fams         # 참인 규칙이 없으면 어느 것이나 고를 수 있다
                continue
            top = [a for a in forced if not any(_above(b.priority, a.priority) for b in forced)]
            allowed[e.name] = top                             # 우선순위가 가장 높은 것. 가르지 못하면 여럿이다
            real[e.name] = top if len(top) == 1 else []       # 두 규칙이 서로 다른 분해를 요구하면 고를 수 없다
        choices = []                                          # (부분의 (이름, 정의) 목록, 결합, 이때 한 선택)
        for e in owners:
            for a in real[e.name]:
                # 병합으로 형제가 된 분해들 가운데 우선순위가 가장 높은 것이 구성요소의 분해다.
                # 다른 구성원은 모두 밀려야 한다. 가르지 못하면 합칠 수 없다
                if not all(any(_above(a.priority, b.priority) for b in allowed[z.name]) for z in owners if z is not e):
                    continue
                if isinstance(a, m.Aspect):
                    ks = [((c.src.part, c.src.port), (c.dst.part, c.dst.port)) for c in a.couplings]
                    choices.append(([(p.part_name, p.def_name) for p in a.parts], ks, {("aspect", e.name, "", a.name)}))
                    continue
                card = a.cardinality
                counts = [card.n] if isinstance(card, m.Fixed) else [sigma[card.var]] \
                    if isinstance(card, m.VarCard) else range(card.min, card.max + 1)
                for n in counts:
                    replicas = [_replica_name(a, i, n) for i in range(n)]
                    choices.append(([(r, a.part.def_name) for r in replicas], list(_instantiate_pattern(a, replicas)),
                                    {("aspect", e.name, "", a.name), ("count", e.name, a.name, n)}))
        for parts, ks, mine in choices:
            for combo in product(*(_build(doc, d, sigma, memo, functions) for _, d in parts)):
                kids = {name: c for (name, _), (c, _) in zip(parts, combo) if c is not None}
                node = dict(base, children=kids, eic=[], eoc=[], ic=[])
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
