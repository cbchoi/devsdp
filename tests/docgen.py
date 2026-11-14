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
        for j in range(rng.choice([0, 0, 0, 0, 1, 1, 2])):     # 같은 엔티티에 multi-aspect가 둘일 수 있다
            card = rng.choice([2, {"min": 1, "max": 2}] + ([{"var": rng.choice(list(variables))}] if variables else []))
            body.setdefault("multi_aspects", {})[f"m{j}"] = {"part": rng.choice(names[i + 1:]), "cardinality": card}
        if rng.random() < 0.45:
            alts = []
            for j in range(rng.randint(2, 3)):
                alt = f"{n}_x{j}"
                alts.append(alt)
                extra[alt] = {"extends": n}
                if i > 0 and j > 0 and rng.random() < 0.3:
                    extra[alt]["stereotype"] = "void"
                elif rng.random() < 0.3:                    # 대안이 자기 분해를 가진다. 둘이면 선택 지점이 된다
                    extra[alt]["aspects"] = {f"b{j}{x}": {"parts": parts_from(i, rng.randint(1, 2))}
                                             for x in range(rng.choice([1, 1, 2]))}
                elif rng.random() < 0.15:                   # 대안 안의 specialization
                    inner = [f"{alt}_y{x}" for x in range(2)]
                    for sub in inner:
                        extra[sub] = {"extends": alt}
                    extra[alt]["specializations"] = {"t0": {"alternatives": inner}}
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


# ---------------------------------------------------------------------------
# 포트, 결합, 속성을 가진 문서와 무작위 바인딩 (실행기 시험용)
# ---------------------------------------------------------------------------

def _system_attempt(rng: random.Random) -> dict:
    """구조 문서에 포트와 결합을 입힌다. 모든 엔티티가 입력 i와 출력 o를 가지므로 사슬로 이을 수 있다."""
    d = _attempt(rng)
    ents = d["entities"]
    d["port_types"] = {"T": {}, "U": {}}
    for name, body in ents.items():
        if body.get("stereotype") == "void":
            continue
        if "extends" not in body:                           # 대안은 바탕의 포트를 물려받는다
            body["ports"] = {"i": {"type": "T", "direction": "in"}, "o": {"type": "T", "direction": "out"}}
            if rng.random() < 0.5:
                body["ports"]["i"]["required"] = True
            if rng.random() < 0.25:
                body["ports"]["o"]["required"] = True
        elif rng.random() < 0.3:                            # 대안이 포트를 더한다
            body["ports"] = {"z": {"type": "U", "direction": rng.choice(["in", "out"])}}
            if body["ports"]["z"]["direction"] == "in" and rng.random() < 0.3:
                body["ports"]["z"]["required"] = True
        if rng.random() < 0.6:
            body["attributes"] = {"w": {"type": "int", "default": rng.randint(1, 9)}}
        for a in (body.get("aspects") or {}).values():
            names = [p if isinstance(p, str) else p["alias"] for p in a["parts"]]
            chain = [("i", f"{names[0]}.i")] + [(f"{x}.o", f"{y}.i") for x, y in zip(names, names[1:])] + \
                    [(f"{names[-1]}.o", "o")]
            ks = [k for k in chain if rng.random() < 0.85]
            for _ in range(rng.choice([0, 0, 1])):          # 사슬 밖의 내부 결합
                ks.append((f"{rng.choice(names)}.o", f"{rng.choice(names)}.i"))
            if ks:
                a["couplings"] = [{"from": s, "to": t} for s, t in dict.fromkeys(ks)]
        for ma in (body.get("multi_aspects") or {}).values():
            if rng.random() < 0.5:
                ma["couplings"] = {"pattern": "fan_out_fan_in",
                                   "fan_out": [{"from": "i", "to": "{part}.i"}],
                                   "fan_in": [{"from": "{part}.o", "to": "o"}]}
            else:
                ma["couplings"] = {"pattern": "chain",
                                   "first": [{"from": "i", "to": "{part}.i"}],
                                   "between": [{"from": "{i}.o", "to": "{next}.i"}],
                                   "last": [{"from": "{part}.o", "to": "o"}]}
    return d


def rand_system_document(rng: random.Random, lo: int = 2, hi: int = 120) -> dict:
    """포트, 결합, 속성을 가지고 적재기를 통과하는 무작위 문서."""
    while True:
        d = _system_attempt(rng)
        try:
            n = count_variants(unfold(load_ses_dict(d)).tree)
        except (LoadError, AlgebraError):
            continue
        if lo <= n <= hi:
            return d


def static_ports(d: dict, name: str) -> dict:
    """정의의 포트: extends로 물려받은 것과 자신의 것."""
    body = d["entities"][name]
    out = static_ports(d, body["extends"]) if "extends" in body else {}
    out.update({p: (x["type"], x["direction"]) for p, x in (body.get("ports") or {}).items()})
    return out


def rand_binding(rng: random.Random, d: dict, executor: str = "x") -> tuple:
    """무작위 바인딩과 그 모듈 라이브러리. (바인딩 사전, 모듈 선언의 사전)을 돌려준다.

    잎 정의는 대개 묶고, 분해를 가진 정의는 가끔 통째로 묶고(검은 상자), 대안에 따로 묶기도
    한다. 모듈의 인터페이스는 대개 정의와 맞지만 가끔 어긋나게 만든다.
    """
    ents = d["entities"]
    entries, modules = {}, {}
    for name, body in ents.items():
        if body.get("stereotype") == "void":
            continue
        composite = bool(body.get("aspects") or body.get("multi_aspects"))
        chance = 0.12 if composite else (0.45 if "extends" in body else 0.8)
        if rng.random() >= chance:
            continue
        ports = dict(static_ports(d, name))
        if rng.random() < 0.08 and ports:                   # 어긋난 인터페이스
            p = rng.choice(sorted(ports))
            ports[p] = (ports[p][0], "in" if ports[p][1] == "out" else "out")
        params = {"w": ("int", 0) if rng.random() < 0.6 else ("int",)}
        if rng.random() < 0.08:
            params["q"] = ("int",)                          # SES에 없는 매개변수
        required = [p for p, (_, direction) in ports.items() if direction == "in" and rng.random() < 0.3]
        modules[f"M_{name}"] = {"ports": ports, "required": required, "params": params}
        entries[name] = {"module": f"M_{name}"}
    return {"binding": "1.0", "executor": executor, "target": d["name"], "map": entries}, modules
