"""무작위 정준 문서 생성기. 여러 시험이 함께 쓴다.

정의 표를 층으로 만든다. 엔티티는 자기보다 뒤의 엔티티만 부분으로 쓰므로 strict
hierarchy가 지켜진다. 같은 정의가 여러 곳에서 쓰이고(표지의 반복), 복제본과 별칭,
대안의 분해, 없음 대안, 변수와 선택 규칙이 섞인다.
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ses_core import LoadError, load_ses_dict  # noqa: E402
from ses_core.algebra import AlgebraError, count_variants  # noqa: E402
from ses_core.unfold import unfold  # noqa: E402


def _attempt(rng: random.Random) -> dict:
    k = rng.randint(4, 7)
    names = [f"E{i}" for i in range(k)]
    variables = {}
    for v in range(rng.choice([0, 0, 1, 2])):
        variables[f"v{v}"] = {"type": "int", "range": [1, rng.choice([2, 3])]}
    entities: dict = {n: {} for n in names}
    entities[names[0]]["root"] = True
    extra: dict = {}

    def parts_from(i: int, count: int) -> list:
        pool = names[i + 1:]
        out, used = [], set()
        for _ in range(count):
            d = rng.choice(pool)
            if d in used or rng.random() < 0.15:
                alias = f"{d.lower()}_{len(out)}"
                out.append({"def": d, "alias": alias})
            else:
                out.append(d)
            used.add(d)
        return out

    for i, n in enumerate(names[:-1]):
        body = entities[n]
        if i > 0 and rng.random() < 0.35:
            continue                                        # 잎
        aspects = {}
        for a in range(rng.choice([0, 1, 1, 2])):
            aspects[f"a{a}"] = {"parts": parts_from(i, rng.randint(1, 3))}
        if aspects:
            body["aspects"] = aspects
        if rng.random() < 0.3:
            card = rng.choice([2, {"min": 1, "max": 2}] + ([{"var": rng.choice(list(variables))}] if variables else []))
            body["multi_aspects"] = {"m0": {"part": rng.choice(names[i + 1:]), "cardinality": card}}
        if rng.random() < 0.45:
            alts = []
            for j in range(rng.randint(2, 3)):
                alt = f"{n}_x{j}"
                alts.append(alt)
                extra[alt] = {"extends": n}
                if i > 0 and j > 0 and rng.random() < 0.3:
                    extra[alt]["stereotype"] = "void"
                elif rng.random() < 0.25:
                    extra[alt]["aspects"] = {f"b{j}": {"parts": parts_from(i, rng.randint(1, 2))}}
            sp = {"alternatives": alts}
            if variables and len(alts) == 2 and rng.random() < 0.4:
                sp["select"] = {"when": {"var": rng.choice(list(variables)), "eq": 1},
                                "then": alts[0], "else": alts[1]}
            body["specializations"] = {"s0": sp}
    entities.update(extra)
    d = {"ses": "1.0", "name": names[0]}
    if variables:
        d["variables"] = variables
    d["entities"] = entities
    return d


def rand_document(rng: random.Random, lo: int = 2, hi: int = 200) -> dict:
    """적재기를 통과하고 변이 수가 lo 이상 hi 이하인 무작위 문서."""
    while True:
        d = _attempt(rng)
        try:
            n = count_variants(unfold(load_ses_dict(d)).tree)
        except (LoadError, AlgebraError):
            continue
        if lo <= n <= hi:
            return d
