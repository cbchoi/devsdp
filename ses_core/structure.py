"""계층 구조: 실행기가 받는 것 (docs/ses-platform/14_executors.md 2절).

변이 V의 실현 모델 R(V)는 포트를 가진 구성요소의 계층과 그 사이의 결합이다. 이 모듈은
그 구조를 SES와 떼어 놓고 다룬다. 실행기(DEVS 시뮬레이터, 하드웨어 조립)는 이 구조만
받으므로, 실행기에 대한 정리는 여기의 성질에서 나온다.

구조의 표현은 결합 확장(coupling.py)의 해석이 내는 것과 같은 중첩 사전이다.
    {"ports": {이름: (타입, 방향)}, "required": [이름], "children": {이름: 구조},
     "eic": [(자기 포트, (자식, 포트))], "eoc": [((자식, 포트), 자기 포트)],
     "ic": [((자식, 포트), (자식, 포트))]}
자식이 없으면 원자다. 구성요소는 뿌리에서부터의 자식 이름 열(경로)로, 포트의 자리는
(경로, 포트 이름)으로 가리킨다. 뿌리의 경로는 빈 열이다.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Optional

IN, OUT = "in", "out"


class StructureError(ValueError):
    pass


def node(ports: Optional[Mapping] = None, children: Optional[Mapping] = None, eic=(), eoc=(), ic=(),
         required=(), **extra) -> dict:
    out = {"ports": dict(ports or {}), "required": sorted(required), "children": dict(children or {}),
           "eic": list(eic), "eoc": list(eoc), "ic": list(ic)}
    out.update(extra)
    return out


def is_atom(n: dict) -> bool:
    return not n["children"]


def walk(n: dict, path: tuple = ()):
    """(경로, 구성요소)를 위에서 아래로."""
    yield path, n
    for name, child in n["children"].items():
        yield from walk(child, path + (name,))


def subtree(n: dict, path: tuple) -> dict:
    for name in path:
        n = n["children"][name]
    return n


def atoms(n: dict) -> list:
    return [p for p, c in walk(n) if is_atom(c)]


def height(n: dict) -> int:
    return 0 if is_atom(n) else 1 + max(height(c) for c in n["children"].values())


def copy(n: dict) -> dict:
    out = dict(n)
    out["ports"] = dict(n["ports"])
    out["required"] = list(n.get("required", ()))
    out["children"] = {k: copy(c) for k, c in n["children"].items()}
    for key in ("eic", "eoc", "ic"):
        out[key] = list(n[key])
    return out


def canon(n: dict) -> tuple:
    """같은 구조이면 같은 값. 집합에 넣거나 비교할 때 쓴다. 뿌리의 이름은 구조에 들지 않는다."""
    return (tuple(sorted(n["ports"].items())), tuple(sorted(n.get("required", ()))),
            tuple((k, canon(c)) for k, c in sorted(n["children"].items())),
            tuple(sorted(set(n["eic"]))), tuple(sorted(set(n["eoc"]))), tuple(sorted(set(n["ic"]))))


# ---------------------------------------------------------------------------
# 구조의 적격성: 결합의 끝점이 있고, 방향과 타입이 맞는다 (08 문서의 C1에서 C3)
# ---------------------------------------------------------------------------

def violations(n: dict, no_self_loop: bool = False) -> list:
    out = []
    for path, c in walk(n):
        kids = c["children"]

        def decl(who, port):
            owner = c if who is None else kids.get(who)
            return None if owner is None else owner["ports"].get(port)

        triples = [(None, sp, ch, cp, (IN, IN)) for sp, (ch, cp) in c["eic"]] + \
                  [(ch, cp, None, sp, (OUT, OUT)) for (ch, cp), sp in c["eoc"]] + \
                  [(a, ap, b, bp, (OUT, IN)) for (a, ap), (b, bp) in c["ic"]]
        for sw, sp, dw, dp, want in triples:
            sd, dd = decl(sw, sp), decl(dw, dp)
            label = f"{sw or 'self'}.{sp} 에서 {dw or 'self'}.{dp}"
            if sd is None or dd is None:
                out.append(("C1", path, f"{label}: 포트가 없다"))
                continue
            if (sd[1], dd[1]) != want or (no_self_loop and sw is not None and sw == dw):
                out.append(("C2", path, f"{label}: 방향이 맞지 않다"))
            if sd[0] != dd[0]:
                out.append(("C3", path, f"{label}: 타입이 다르다"))
    return out


def one_step_undriven(n: dict) -> list:
    """08 문서의 C4: 필수 포트에 한 걸음 안에서 들어오는 결합이 없는 곳. (경로, 포트)의 목록."""
    out = []
    for path, c in walk(n):
        if is_atom(c):
            continue
        into = {(ch, cp) for _, (ch, cp) in c["eic"]} | {dst for _, dst in c["ic"]}
        up = {sp for _, sp in c["eoc"]}
        for name, child in c["children"].items():
            for p in child.get("required", ()):
                if child["ports"][p][1] == IN and (name, p) not in into:
                    out.append((path + (name,), p))
        for p in c.get("required", ()):
            if c["ports"][p][1] == OUT and p not in up:
                out.append((path, p))
    return out


# ---------------------------------------------------------------------------
# 한 걸음 관계와 평탄화 (정의 24, 25. 정리 17)
# ---------------------------------------------------------------------------

def steps(n: dict) -> set:
    """결합이 정하는 한 걸음 관계: (출발 자리, 도착 자리)의 집합."""
    out = set()
    for path, c in walk(n):
        for sp, (ch, cp) in c["eic"]:
            out.add(((path, sp), (path + (ch,), cp)))
        for (ch, cp), sp in c["eoc"]:
            out.add(((path + (ch,), cp), (path, sp)))
        for (a, ap), (b, bp) in c["ic"]:
            out.add(((path + (a,), ap), (path + (b,), bp)))
    return out


def sources(n: dict) -> list:
    """원천: 원자의 출력 자리와 뿌리의 입력 자리."""
    out = [((), p) for p, (_, d) in n["ports"].items() if d == IN]
    out += [(path, p) for path, c in walk(n) if is_atom(c) and path
            for p, (_, d) in c["ports"].items() if d == OUT]
    if is_atom(n):
        out += [((), p) for p, (_, d) in n["ports"].items() if d == OUT]
    return out


def sinks(n: dict) -> set:
    """수신처: 원자의 입력 자리와 뿌리의 출력 자리."""
    out = {((), p) for p, (_, d) in n["ports"].items() if d == OUT}
    out |= {(path, p) for path, c in walk(n) if is_atom(c) and path
            for p, (_, d) in c["ports"].items() if d == IN}
    return out


def flatten(n: dict) -> Counter:
    """평탄화: 원천에서 수신처로 가는 길의 수. (원천, 수신처)에서 길의 개수로.

    결합 모델의 경계를 모두 풀어 원자에서 원자로(또는 뿌리의 포트로) 가는 연결만 남긴다.
    길이 둘이면 메시지가 두 번 전달되므로 개수를 센다. 연결이 있는지만 볼 때는 열쇠만 쓴다.
    """
    succ: dict = {}
    for a, b in steps(n):
        succ.setdefault(a, []).append(b)
    targets = sinks(n)
    memo: dict = {}
    active: set = set()

    def reach(p) -> Counter:
        if p in memo:
            return memo[p]
        if p in active:
            raise StructureError(f"결합이 순환한다: {p}")
        active.add(p)
        acc: Counter = Counter()
        for q in succ.get(p, ()):
            if q in targets:
                acc[q] += 1
            for t, k in reach(q).items():
                acc[t] += k
        active.discard(p)
        memo[p] = acc
        return acc

    out: Counter = Counter()
    for s in sources(n):
        for t, k in reach(s).items():
            out[(s, t)] += k
    return out


def grounded(n: dict) -> set:
    """원천에서 닿는 자리들 (원천 자신을 포함). 정의 27."""
    succ: dict = {}
    for a, b in steps(n):
        succ.setdefault(a, []).append(b)
    seen = set(sources(n))
    stack = list(seen)
    while stack:
        for q in succ.get(stack.pop(), ()):
            if q not in seen:
                seen.add(q)
                stack.append(q)
    return seen


def ungrounded(n: dict) -> list:
    """조건 C5의 위반: 필수 포트인데 어떤 원천에서도 닿지 않는 자리. (경로, 포트)의 목록."""
    ok = grounded(n)
    return [(path, p) for path, c in walk(n) for p in c.get("required", ()) if (path, p) not in ok]


# ---------------------------------------------------------------------------
# 절단, 몫, 치환 (정의 26)
# ---------------------------------------------------------------------------

def as_atom(c: dict) -> dict:
    out = {k: v for k, v in c.items() if k not in ("children", "eic", "eoc", "ic")}
    out["ports"] = dict(c["ports"])
    out["required"] = list(c.get("required", ()))
    out.update(children={}, eic=[], eoc=[], ic=[])
    return out


def is_cut(n: dict, cut: Iterable) -> bool:
    """절단: 서로 조상 관계가 아니고, 모든 원자를 덮으며, 뿌리를 담지 않는 구성요소의 집합."""
    cut = set(cut)
    if () in cut:
        return False
    for a in cut:
        for b in cut:
            if a != b and b[:len(a)] == a:
                return False
    return all(any(p[:len(c)] == c for c in cut) for p in atoms(n))


def quotient(n: dict, cut: Iterable) -> dict:
    """몫 N/F: 절단의 구성요소를 같은 인터페이스의 원자로 바꾼 구조."""
    cut = set(cut)

    def rec(c: dict, path: tuple) -> dict:
        if path in cut:
            return as_atom(c)
        out = copy(c)
        out["children"] = {name: rec(child, path + (name,)) for name, child in c["children"].items()}
        return out

    return rec(n, ())


def replace(n: dict, path: tuple, m: dict) -> dict:
    """치환 N[c := M]: 경로의 구성요소를 다른 구조로 바꾼다."""
    if not path:
        return copy(m)
    out = copy(n)
    cur = out
    for name in path[:-1]:
        cur = cur["children"][name]
    cur["children"][path[-1]] = copy(m)
    return out


def compose_flat(n: dict, cut: Iterable) -> Counter:
    """정리 17의 우변: 몫의 평탄화와 절단 안쪽의 평탄화를 이어 붙인 것."""
    cut = sorted(set(cut))
    total: Counter = Counter()
    outs: dict = {}                     # 절단 구성요소의 출력 자리에서 {안쪽 원천: 길의 수}로
    ins: dict = {}                      # 절단 구성요소의 입력 자리에서 {안쪽 수신처: 길의 수}로
    for c in cut:
        sub = subtree(n, c)
        if is_atom(sub):
            continue
        for ((sp, s), (tp, t)), k in flatten(sub).items():
            if sp and tp:               # 둘 다 안쪽의 원자: 꼭짓점이 안쪽에 있는 연결
                total[((c + sp, s), (c + tp, t))] += k
            elif sp:                    # 안쪽 원자의 출력에서 c의 출력 포트로
                outs.setdefault((c, t), Counter())[(c + sp, s)] += k
            elif tp:                    # c의 입력 포트에서 안쪽 원자의 입력으로
                ins.setdefault((c, s), Counter())[(c + tp, t)] += k
    for (s, t), k in flatten(quotient(n, cut)).items():
        for s2, a in (outs.get(s, {}) if s[0] in cut and not is_atom(subtree(n, s[0])) else {s: 1}).items():
            for t2, b in (ins.get(t, {}) if t[0] in cut and not is_atom(subtree(n, t[0])) else {t: 1}).items():
                total[(s2, t2)] += k * a * b
    return total


# ---------------------------------------------------------------------------
# 위임 완전성과 재구성 (정리 21의 (d), 정리 20)
# ---------------------------------------------------------------------------

def from_flat(tree: dict, conns: Iterable) -> dict:
    """주어진 계층 위에서, 원자 사이의 연결들을 정확히 평탄화로 가지는 구조를 만든다.

    연결 하나마다 두 끝의 가장 가까운 공통 조상까지 경계를 넘을 때마다 새 포트를 하나씩
    더한다. 포트를 연결마다 따로 두므로 다른 연결과 섞이지 않는다. 연결의 끝은 원자의
    포트이거나 뿌리의 포트다.
    """
    out = copy(tree)
    for k, ((a, ap), (b, bp)) in enumerate(conns):
        src, dst = subtree(out, a), subtree(out, b)
        typ = (src if a else out)["ports"][ap][0]
        if (dst if b else out)["ports"][bp][0] != typ:
            raise StructureError(f"타입이 다른 연결: {a}.{ap} 에서 {b}.{bp}")
        lca = 0
        if a and b:
            while lca < min(len(a), len(b)) - 1 and a[lca] == b[lca]:
                lca += 1
        apex = (a[:lca] if a else ()) if a and b else ()
        fresh = f"d{k}"
        up_port = ap                                   # 출발 쪽: 원자에서 꼭짓점의 자식까지 올라간다
        for i in range(len(a), len(apex) + 1, -1):
            parent = subtree(out, a[:i - 1])
            parent["ports"][fresh] = (typ, OUT)
            parent["eoc"].append(((a[i - 1], up_port), fresh))
            up_port = fresh
        down_port = bp                                 # 도착 쪽: 원자에서 꼭짓점의 자식까지 거슬러 올라가며 만든다
        for i in range(len(b), len(apex) + 1, -1):
            parent = subtree(out, b[:i - 1])
            parent["ports"][fresh + "i"] = (typ, IN)
            parent["eic"].append((fresh + "i", (b[i - 1], down_port)))
            down_port = fresh + "i"
        top = subtree(out, apex)
        if a and b:
            top["ic"].append(((a[len(apex)], up_port), (b[len(apex)], down_port)))
        elif not a:                                    # 뿌리의 입력에서 내려간다
            top["eic"].append((ap, (b[0], down_port)))
        else:                                          # 뿌리의 출력으로 올라간다
            top["eoc"].append(((a[0], up_port), bp))
    return out


def regroup(n: dict, group_of: Mapping) -> tuple:
    """평탄화된 연결을 유지한 채 원자를 묶음별로 다시 계층화한다. (구조, 이음매)를 돌려준다.

    묶음은 실행기에 대응한다. 묶음 하나가 결합 모델 하나가 되고, 묶음을 넘는 연결(이음매)만
    뿌리의 내부 결합으로 남는다. 원자의 새 경로는 (묶음 이름, 옛 경로를 이은 이름)이다.
    """
    def key(path: tuple) -> tuple:
        return (group_of[path], "/".join(path)) if path else ()

    tree = node(n["ports"], required=n.get("required", ()))
    for path in atoms(n):
        if not path:
            raise StructureError("원자 하나뿐인 구조는 묶을 것이 없다")
        g = tree["children"].setdefault(group_of[path], node())
        g["children"]["/".join(path)] = as_atom(subtree(n, path))
    conns = sorted(((key(s), sp), (key(t), tp)) for ((s, sp), (t, tp)) in flatten(n))
    seam = [c for c in conns if c[0][0] and c[1][0] and c[0][0][0] != c[1][0][0]]
    return from_flat(tree, conns), seam
