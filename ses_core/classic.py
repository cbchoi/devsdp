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
from .unfold import _OPS, _domain, _instantiate_pattern, _replica_name


def _eval(e: Optional[m.Expr], sigma: dict) -> bool:
    if e is None:
        return True
    if isinstance(e, m.Compare):
        return bool(_OPS[e.op](sigma[e.left.name], e.right.value))
    if isinstance(e, m.And):
        return all(_eval(x, sigma) for x in e.items)
    if isinstance(e, m.Or):
        return any(_eval(x, sigma) for x in e.items)
    if isinstance(e, m.Not):
        return not _eval(e.item, sigma)
    raise ValueError(f"절차적 의미가 다루지 않는 식: {e!r}")


def _allowed(sp: m.Specialization, sigma: dict) -> list:
    """선택 규칙이 정하는 대안. 규칙이 정하지 않으면 모든 대안 가운데 고른다."""
    rule = sp.select
    while rule is not None:
        if _eval(rule.when, sigma):
            return [rule.then]
        if isinstance(rule.otherwise, m.SelectRule):
            rule = rule.otherwise
        elif rule.otherwise is None:
            break
        else:
            return [rule.otherwise]
    return list(sp.alternatives)


def enumerate_classic(doc: m.SesDocument) -> list:
    """절차적 가지치기와 조립으로 얻는 (변수 값, 구조)의 목록.

    구조는 결합 확장의 해석과 같은 모양의 중첩 사전이고, 구성요소마다 합쳐진 정의들의 이름
    (labels)이 더 붙는다. 합칠 수 없는 경우(같은 이름의 포트를 다르게 선언, 엔티티와 고른
    대안이 각자 분해를 가짐)와 뿌리가 없음이 되는 경우는 내놓지 않는다.
    """
    names = list(doc.variables)
    out = []
    for values in product(*(_domain(doc, n) for n in names)):
        sigma = dict(zip(names, values))
        ok = True
        for c in doc.constraints:
            if _eval(c.when, sigma):
                ok = ok and (c.require is None or _eval(c.require, sigma)) \
                    and (c.forbid is None or not _eval(c.forbid, sigma))
        if not ok:
            continue
        memo: dict = {}
        out += [(sigma, s) for s in _build(doc, doc.root.name, sigma, memo) if s is not None]
    return out


def _clusters(doc, def_name: str, sigma: dict) -> list:
    """엔티티에서 시작해 specialization마다 대안을 하나씩 골라 합쳐지는 정의들의 목록들."""
    options = []
    for sp in doc.entities[def_name].specializations.values():
        options.append([ms for alt in _allowed(sp, sigma) for ms in _clusters(doc, alt, sigma)])
    return [[def_name] + [x for part in combo for x in part] for combo in product(*options)]


def _build(doc, def_name: str, sigma: dict, memo: dict) -> list:
    """정의 하나에서 만들어질 수 있는 구성요소들. None은 없음(빠지는 구성요소)이다."""
    if def_name in memo:
        return memo[def_name]
    results: list = []
    for members in _clusters(doc, def_name, sigma):
        ents = [doc.entities[x] for x in members]
        if any(e.stereotype == m.Stereotype.VOID for e in ents):
            results.append(None)
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
        if clash or len(owners) > 1:
            continue                                          # 합칠 수 없다
        base = {"labels": sorted(members), "ports": ports, "required": sorted(required)}
        if not owners:
            results.append(dict(base, children={}, eic=[], eoc=[], ic=[]))
            continue
        e = owners[0]
        forced = [a for a in e.aspects.values() if a.rule is not None and _eval(a.rule, sigma)]
        if len(forced) > 1:
            continue                                          # 두 규칙이 서로 다른 aspect를 요구한다
        choices = []                                          # (부분의 (이름, 정의) 목록, 결합)
        for a in e.aspects.values():
            if forced and a is not forced[0]:
                continue
            ks = [((c.src.part, c.src.port), (c.dst.part, c.dst.port)) for c in a.couplings]
            choices.append(([(p.part_name, p.def_name) for p in a.parts], ks))
        for ma in ([] if forced else e.multi_aspects.values()):
            card = ma.cardinality
            counts = [card.n] if isinstance(card, m.Fixed) else [sigma[card.var]] \
                if isinstance(card, m.VarCard) else range(card.min, card.max + 1)
            for n in counts:
                replicas = [_replica_name(ma, i, n) for i in range(n)]
                choices.append(([(r, ma.part.def_name) for r in replicas],
                                list(_instantiate_pattern(ma, replicas))))
        for parts, ks in choices:
            for combo in product(*(_build(doc, d, sigma, memo) for _, d in parts)):
                kids = {name: c for (name, _), c in zip(parts, combo) if c is not None}
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
                results.append(node)
    memo[def_name] = results
    return results
