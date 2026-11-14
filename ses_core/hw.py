"""하드웨어 실행기: SES에 하드웨어 모듈을 붙이면 임베디드 시스템의 배선표와 부품표가 된다
(docs/ses-platform/14_executors.md 5절).

SES의 포트 타입은 실행기와 무관한 낱말이다(측정값, 전원). 이 실행기는 타입마다 물리적인
규약을 정한다. 규약은 평탄화된 연결 위의 조건이며 실행기의 고유한 적격성이 된다.

| 규약 | 뜻 | 위반 부호 |
|---|---|---|
| max_out, max_in | 출력 하나, 입력 하나에 이을 수 있는 상대의 수 (일대일 연결) | H1 |
| unique | 같은 선에 달린 상대들은 이 매개변수의 값이 서로 달라야 한다 (버스 주소) | H2 |
| load, capacity | 공급 쪽의 용량이 받는 쪽 부하의 합보다 작지 않아야 한다 (전원) | H3 |

산출물은 부품표(bom), 배선표(nets), 설정(config)이다. 하드웨어는 계층이 없으므로 평탄화된
연결을 그대로 쓴다.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from . import structure as st
from .executor import Executor


def ref(path: tuple) -> str:
    return "/".join(path)


class HwExecutor(Executor):
    name = "hw"

    def __init__(self, rules: Mapping[str, Mapping]) -> None:
        self.rules = dict(rules)                 # 포트 타입에서 규약으로

    def conventions(self) -> list:
        return [self.check]

    def check(self, plan: dict) -> list:
        out = []
        by_src, by_dst = defaultdict(set), defaultdict(set)
        for s, t in st.flatten(plan):
            by_src[s].add(t)
            by_dst[t].add(s)

        def comp(pt):
            return st.subtree(plan, pt[0])

        def param(pt, name):
            return comp(pt).get("params", {}).get(name)

        for end, table, limit in (("출력", by_src, "max_out"), ("입력", by_dst, "max_in")):
            for pt, others in sorted(table.items()):
                rule = self.rules.get(comp(pt)["ports"][pt[1]][0], {})
                bus = rule.get("bus", comp(pt)["ports"][pt[1]][0])
                if rule.get(limit) is not None and len(others) > rule[limit]:
                    out.append(("H1", pt[0], f"{pt[1]}: {bus} {end} 하나에 {len(others)}곳이 이어졌다. "
                                              f"많아야 {rule[limit]}곳이다"))
                if rule.get("unique"):
                    seen = defaultdict(list)
                    for o in sorted(others):
                        seen[param(o, rule["unique"])].append(ref(o[0]))
                    for value, who in sorted(seen.items(), key=lambda kv: repr(kv[0])):
                        if value is not None and len(who) > 1:      # 설명은 변이마다 달라지지 않게 적는다
                            out.append(("H2", pt[0], f"{pt[1]}: {bus} 에 {rule['unique']} 가 {value} 인 "
                                                      f"장치가 둘 이상 달렸다"))
        for pt, others in sorted(by_src.items()):
            rule = self.rules.get(comp(pt)["ports"][pt[1]][0], {})
            if rule.get("load"):
                capacity = param(pt, rule.get("capacity"))
                total = sum(param(o, rule["load"]) or 0 for o in others)
                if capacity is not None and total > capacity:
                    out.append(("H3", pt[0], f"{pt[1]}: 이어진 부하의 합이 용량 {capacity} 을 넘는다"))
        return out

    def build(self, plan: dict, library: Mapping) -> dict:
        parts = [(p, st.subtree(plan, p)) for p in st.atoms(plan)]
        nets = sorted((s, t) for s, t in st.flatten(plan))

        def end(pt) -> str:
            return f"{ref(pt[0])}.{pt[1]}" if pt[0] else pt[1]

        def bus(pt) -> tuple:
            typ = (st.subtree(plan, pt[0]) if pt[0] else plan)["ports"][pt[1]][0]
            return typ, self.rules.get(typ, {}).get("bus", typ)

        return {
            "interface": dict(plan["ports"]),
            "bom": [{"ref": ref(p), "module": c["module"], "ports": dict(c["ports"]),
                     "part": (library[c["module"]].body or {}).get("part")} for p, c in parts],
            "nets": [dict(zip(("from", "to", "type", "bus"), (end(s), end(t)) + bus(s))) for s, t in nets],
            "config": {ref(p): dict(c["params"]) for p, c in parts if c["params"]},
        }

    def observe(self, artifact: dict) -> dict:
        """배선표에서 구조를 다시 읽는다. 계층이 없으므로 한 층짜리 구조가 된다."""
        def point(text: str) -> tuple:
            who, _, port = text.rpartition(".")
            return (who or None, port)

        eic, eoc, ic = [], [], []
        for n in artifact["nets"]:
            (a, ap), (b, bp) = point(n["from"]), point(n["to"])
            if a is None:
                eic.append((ap, (b, bp)))
            elif b is None:
                eoc.append(((a, ap), bp))
            else:
                ic.append(((a, ap), (b, bp)))
        return st.node(artifact["interface"], {e["ref"]: st.node(e["ports"]) for e in artifact["bom"]},
                       eic, eoc, ic)


def load_rules(d: dict) -> dict:
    """라이브러리 파일의 conventions 절."""
    return {typ: dict(rule) for typ, rule in (d.get("conventions") or {}).items()}
