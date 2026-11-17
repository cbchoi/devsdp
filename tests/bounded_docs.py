"""작은 SES 문서를 빠짐없이 내는 열거기. 열한 묶음이고 저마다 적힌 차원들의 곱 전체다.

무작위가 아니다. 순서가 고정되어 있으므로 문서 하나는 (묶음, 번호)로 정해진다. 한도는 이 파일의 상수다.
theory.md 의 독립된 검토(작은 문서의 전수 검사)에서 만든 것을 저장소로 옮겼다. 검사는 bounded_check.py 가 한다.

공통으로 쓰는 것
  변수        v: 정수 1..2,  w: 불  (F9 는 n: 정수 {0, 2} 도,  F10 은 u: 정수 1..2 도).
              문서가 쓰는 변수만 선언한다.
  규칙        v1: v == 1,  v2: v == 2,  w: w == true,  nw: w == false
  우선순위    없음, 1, 2
  분해의 종류 asp1 (aspect, 부분 하나), asp2 (aspect, 부분 둘), ma1 / ma2 (multi-aspect, 개수 1 / 2),
              ma02 (multi-aspect, 범위 0..2), mav (multi-aspect, 개수 = 변수 v)
  병합체      정의 X 가 specialization s 로 대안 A 와 B 를 가진다 (A, B 는 X 를 extends 한다).
              둘째 specialization t 는 대안 C 와 D 를 가지고 X 나 A 에 놓인다.
  놓는 자리   root: X 가 뿌리다.   asp: 뿌리 Top 이 aspect top = [X] 를 가진다.
              ma02: Top 이 X 의 multi-aspect top 을 범위 0..2 로 가진다 (복제본 X_0, X_1).
  부분        묶음이 달리 말하지 않으면 분해마다 새 잎 정의다.

묶음
  F1  두 주인      X 와 A 가 aspect 를 0..2 개씩 가진다. aspect 마다 (우선순위 x 규칙{없음,v1,v2}).
                   B 는 {보통, 없음, 우선순위 없음/1/2 의 aspect 하나}.                    55*55*5 = 15125
  F2  세 주인      X 는 aspect 0..1 개, A 와 C 는 1..2 개. aspect 마다 (우선순위 x 규칙{없음,v1}).
                   t 는 X 또는 A 에 놓인다. B 와 D 는 보통.                              7*27*27*2 = 10206
  F3  종류         X 는 {분해 없음, (asp1|asp2|ma02|mav) x 우선순위{없음,1}}. A, B 는 {보통, 없음,
                   (asp1|asp2|ma1|ma2|ma02|mav) x 우선순위{없음,1,2}}. 놓는 자리 셋.      9*20*20*3 = 10800
  F4  둘째 묶음    A, B, C, D 는 {보통, 없음, asp1 우선순위 1, ma02}. X 는 {없음, asp1, asp1 우선순위 1,
                   ma1 우선순위 2}. t 는 (X, "t"), (A, "t"), 또는 (A, 뿌리의 것과 같은 이름 "s").
                   놓는 자리는 root 또는 asp. 없음인 A 가 t 를 가지는 것은 문서가 아니다 (W2).   5120
  F5  규칙         s 의 선택 규칙 (v 와 w 로 여섯 꼴) x X (36: 없음, 규칙을 가진 aspect 하나, 또는 aspect 와
                   mav multi-aspect 가 모두 규칙을 가지고 우선순위가 세 꼴) x A (8) x B (4).  6*36*8*4 = 6912
  F6  부분         X 가 병합체 P 로 분해된다 (일곱 가지) x P (작은 병합체 20 가지) x X 자신의 specialization
                   (네 가지) x X 의 분해의 규칙 {없음, v1}.                                7*20*4*2 = 1120
  F7  제약         바탕 문서 11개 x 그 문서의 원자(변수, 정의 수준과 경로 수준의 selected)로 만든 크기 0..2 의
                   제약 집합 전부. 제약 하나의 꼴: require a, forbid a, when a require b, when a forbid b,
                   when not a require b, require any[a,b], forbid all[a,b]. 둘이면 require a / forbid a.  5465
  F8  원자         병합체 378개 (X: asp1 또는 ma02 우선순위 2. A, B, C, D 는 {보통, 없음, asp1 우선순위 1}.
                   t 는 F4 와 같다) x 놓는 자리 {root, ma02} x {제약 없음, forbid a}. a 는 그 문서가 내는
                   selected 원자 전부다. 정의 수준(닿는 정의마다 대안, 분해, 개수)과 경로 수준(자리 X (root),
                   또는 Top 과 Top/X_1 (ma02)). 구조 756개, 문서 15768개.
  F9  드문 모양    s 의 대안 셋 A, B, N 이 {보통, 없음, asp1 우선순위 1} x X 는 {없음, 부분 없는 aspect, asp1,
                   부분이 대안 B 자신인 aspect, 개수 0 의 multi-aspect, n 이 {0, 2} 인 multi-aspect} x
                   선택 규칙 {없음, v1 이면 N 아니면 A, v1 이면 N} x 세 단계의 사슬 A.t, C.u, E 에서
                   E 의 aspect {없음, 우선순위 없음, 우선순위 1}. W2 가 막는 조합은 뺀다.          1071
  F10 식           X 가 규칙을 가진 aspect 둘을 가진다. 규칙은 v, u, w 위의 식 여덟 가지 (not, all, any, in,
                   변수끼리 견주기, 늘 참, 늘 거짓) x 우선순위 세 꼴 x s 의 선택 규칙 {없음, 여덟 식 e 마다
                   e 이면 A 아니면 B}.                                                    8*8*3*9 = 1728
  F11 함께 쓰기    C 가 X.s 의 대안이면서 A.t 의 대안이다 (A 는 X.s 의 다른 대안). X, A, C 의 aspect 의
                   우선순위 {없음,1,2} x D {보통, 없음} x {제약 없음, C 에 대한 selected 여섯 가운데 하나를
                   forbid}. 놓는 자리는 ma02.                                             3*3*3*2*7 = 378

합계: 문서 73693개.

쓰는 법
  python tests/bounded_docs.py                 묶음마다의 크기
  python tests/bounded_docs.py F3 1234         문서 F3/1234 를 JSON 으로
"""

from __future__ import annotations

import json
import sys
from itertools import combinations, combinations_with_replacement, product

RULES = {
    None: None,
    "v1": {"var": "v", "eq": 1},
    "v2": {"var": "v", "eq": 2},
    "w": {"var": "w", "eq": True},
    "nw": {"var": "w", "eq": False},
}
VARIABLES = {"v": {"type": "int", "range": [1, 2]}, "w": {"type": "bool"},
             "u": {"type": "int", "range": [1, 2]}, "n": {"type": "int", "values": [0, 2]}}
CARD = {"ma0": 0, "ma1": 1, "ma2": 2, "ma02": {"min": 0, "max": 2}, "mav": {"var": "v"}, "man": {"var": "n"}}


def _vars_of(x, out: set) -> None:
    if isinstance(x, dict):
        if "var" in x and isinstance(x["var"], str):
            out.add(x["var"])
        for v in x.values():
            _vars_of(v, out)
    elif isinstance(x, list):
        for v in x:
            _vars_of(v, out)


class Builder:
    """정의를 모은다. 다 만든 문서가 쓰는 변수만 선언한다."""

    def __init__(self, root: str = "X") -> None:
        self.ents: dict = {}
        self.constraints: list = []
        self.root = root

    def ent(self, name: str, **body) -> dict:
        self.ents.setdefault(name, {}).update(body)
        return self.ents[name]

    def dec(self, owner: str, name: str, kind: str, pri=None, rule=None, parts=None) -> None:
        """owner 에 분해를 더한다. parts 는 부분의 목록이다 (정의의 이름, 또는 {"def": ..., "alias": ...}).
        주지 않으면 분해의 이름을 딴 새 잎 정의다."""
        body: dict = {}
        if kind in ("asp0", "asp1", "asp2"):
            n = int(kind[3])
            if parts is None:
                parts = [f"L{name}{i}" for i in range(n)]
            for p in parts:
                self.ent(p if isinstance(p, str) else p["def"])
            body["parts"] = list(parts)
            self.ent(owner).setdefault("aspects", {})[name] = body
        else:
            part = parts[0] if parts else f"L{name}"
            self.ent(part)
            body["part"] = part
            body["cardinality"] = CARD[kind]
            self.ent(owner).setdefault("multi_aspects", {})[name] = body
        if pri is not None:
            body["priority"] = pri
        if rule is not None:
            body["rule"] = RULES[rule] if isinstance(rule, str) else rule

    def spec(self, owner: str, name: str, alts: list, select=None) -> None:
        sp: dict = {"alternatives": list(alts)}
        if select is not None:
            sp["select"] = select
        self.ent(owner).setdefault("specializations", {})[name] = sp
        for a in alts:
            self.ent(a).setdefault("extends", owner)

    def void(self, name: str) -> None:
        self.ent(name)["stereotype"] = "void"

    def embed(self, how: str, inner: str = "X") -> None:
        """root: inner 가 뿌리다.  asp / ma02: 그 위에 뿌리 Top 을 둔다."""
        if how == "root":
            self.root = inner
        elif how == "asp":
            self.root = "Top"
            self.ent("Top", aspects={"top": {"parts": [inner]}})
        elif how == "ma02":
            self.root = "Top"
            self.ent("Top", multi_aspects={"top": {"part": inner, "cardinality": {"min": 0, "max": 2}}})
        else:
            raise ValueError(how)

    def done(self) -> dict:
        self.ents[self.root]["root"] = True
        used: set = set()
        _vars_of(self.ents, used)
        _vars_of(self.constraints, used)
        d: dict = {"ses": "1.0", "name": self.root}
        if used:
            d["variables"] = {n: VARIABLES[n] for n in VARIABLES if n in used}
        d["entities"] = self.ents
        if self.constraints:
            d["constraints"] = self.constraints
        return d


def alt(b: Builder, name: str, what) -> None:
    """대안 하나: 'plain', 'void', 또는 (종류, 우선순위) / (종류, 우선순위, 규칙)."""
    b.ent(name)
    if what == "plain":
        return
    if what == "void":
        b.void(name)
        return
    kind, pri = what[0], what[1]
    rule = what[2] if len(what) > 2 else None
    b.dec(name, name.lower() + ("a" if kind.startswith("asp") else "m"), kind, pri, rule)


# ---------------------------------------------------------------------------
# F1. 두 주인
# ---------------------------------------------------------------------------

OPT9 = [(pri, rule) for pri in (None, 1, 2) for rule in (None, "v1", "v2")]
SETS55 = [()] + [(o,) for o in OPT9] + list(combinations_with_replacement(OPT9, 2))
B5 = ["plain", "void", ("asp1", None), ("asp1", 1), ("asp1", 2)]


def f1():
    for xs, as_, bw in product(SETS55, SETS55, B5):
        b = Builder()
        b.ent("X")
        for i, (pri, rule) in enumerate(xs):
            b.dec("X", f"xa{i}", "asp1", pri, rule)
        b.spec("X", "s", ["A", "B"])
        for i, (pri, rule) in enumerate(as_):
            b.dec("A", f"aa{i}", "asp1", pri, rule)
        alt(b, "B", bw)
        yield b.done()


# ---------------------------------------------------------------------------
# F2. 세 주인
# ---------------------------------------------------------------------------

OPT6 = [(pri, rule) for pri in (None, 1, 2) for rule in (None, "v1")]
SETS27 = [(o,) for o in OPT6] + list(combinations_with_replacement(OPT6, 2))
SETS7 = [()] + [(o,) for o in OPT6]


def f2():
    for xs, as_, cs, where in product(SETS7, SETS27, SETS27, ("X", "A")):
        b = Builder()
        b.ent("X")
        for i, (pri, rule) in enumerate(xs):
            b.dec("X", f"xa{i}", "asp1", pri, rule)
        b.spec("X", "s", ["A", "B"])
        for i, (pri, rule) in enumerate(as_):
            b.dec("A", f"aa{i}", "asp1", pri, rule)
        b.spec(where, "t", ["C", "D"])
        for i, (pri, rule) in enumerate(cs):
            b.dec("C", f"ca{i}", "asp1", pri, rule)
        yield b.done()


# ---------------------------------------------------------------------------
# F3. 대안의 종류
# ---------------------------------------------------------------------------

X9 = [None] + [(k, p) for k in ("asp1", "asp2", "ma02", "mav") for p in (None, 1)]
ALT20 = ["plain", "void"] + [(k, p) for k in ("asp1", "asp2", "ma1", "ma2", "ma02", "mav") for p in (None, 1, 2)]


def f3():
    for xd, aw, bw, how in product(X9, ALT20, ALT20, ("root", "asp", "ma02")):
        b = Builder()
        b.ent("X")
        if xd is not None:
            b.dec("X", "xa" if xd[0].startswith("asp") else "xm", xd[0], xd[1])
        b.spec("X", "s", ["A", "B"])
        alt(b, "A", aw)
        alt(b, "B", bw)
        b.embed(how)
        yield b.done()


# ---------------------------------------------------------------------------
# F4. 둘째 specialization, 없음 대안
# ---------------------------------------------------------------------------

K4 = ["plain", "void", ("asp1", 1), ("ma02", None)]
X4 = [None, ("asp1", None), ("asp1", 1), ("ma1", 2)]
T3 = [("X", "t"), ("A", "t"), ("A", "s")]


def f4():
    for xd, aw, bw, cw, dw, (where, tname), how in product(X4, K4, K4, K4, K4, T3, ("root", "asp")):
        if where == "A" and aw == "void":
            continue                                         # W2: 없음 대안은 specialization 을 가지지 않는다
        b = Builder()
        b.ent("X")
        if xd is not None:
            b.dec("X", "xa" if xd[0].startswith("asp") else "xm", xd[0], xd[1])
        b.spec("X", "s", ["A", "B"])
        alt(b, "A", aw)
        alt(b, "B", bw)
        b.spec(where, tname, ["C", "D"])
        alt(b, "C", cw)
        alt(b, "D", dw)
        b.embed(how)
        yield b.done()


# ---------------------------------------------------------------------------
# F5. v 와 w 위의 분해의 규칙과 선택 규칙
# ---------------------------------------------------------------------------

SEL6 = [
    None,
    {"when": RULES["v1"], "then": "A", "else": "B"},
    {"when": RULES["v1"], "then": "A"},
    {"when": RULES["w"], "then": "B", "else": "A"},
    {"when": RULES["w"], "then": "B"},
    {"when": RULES["v1"], "then": "A", "else": {"when": RULES["w"], "then": "B"}},
]
X36 = [None] + [("one", pri, rule) for rule in (None, "v1", "w", "nw") for pri in (None, 1)] + \
      [("two", pris, r1, r2) for pris in ((None, None), (1, 1), (1, 2))
       for r1 in ("v1", "v2", "w") for r2 in ("v1", "v2", "w")]
A8 = ["plain", "void"] + [("asp1", pri, rule) for rule in (None, "v1", "w") for pri in (None, 1)]
B4 = ["plain", "void", ("asp1", 1), ("asp1", None, "w")]


def f5():
    for select, xd, aw, bw in product(SEL6, X36, A8, B4):
        b = Builder()
        b.ent("X")
        if xd is not None and xd[0] == "one":
            b.dec("X", "xa", "asp1", xd[1], xd[2])
        elif xd is not None:
            b.dec("X", "xa", "asp1", xd[1][0], xd[2])
            b.dec("X", "xm", "mav", xd[1][1], xd[3])
        b.spec("X", "s", ["A", "B"], select)
        alt(b, "A", aw)
        alt(b, "B", bw)
        yield b.done()


# ---------------------------------------------------------------------------
# F6. 부분이 작은 병합체인 것
# ---------------------------------------------------------------------------

def part_cluster(b: Builder, kind) -> None:
    """정의 P 를 스무 모양 가운데 하나로 만든다."""
    b.ent("P")
    name = kind[0] if isinstance(kind, tuple) else kind
    if name == "leaf":
        return
    if name in ("PV", "PVV"):                                # 없어도 되는 부분. PVV 는 분해도 가진다
        b.spec("P", "k", ["P1", "P0"])
        b.void("P0")
        if name == "PVV":
            b.dec("P", "pa", "asp1")
    elif name == "PD":                                       # 대안 하나가 분해를 가진다
        b.spec("P", "k", ["P1", "P2"])
        b.dec("P2", "qa", "asp1")
    elif name == "PO":                                       # 바탕과 대안이 모두 분해를 가진다
        b.dec("P", "pa", "asp1", kind[1])
        b.spec("P", "k", ["P1", "P2"])
        b.dec("P2", "qa", "asp1", kind[2])
    elif name in ("PS", "PSn"):                              # 부분 안의 선택 규칙
        rule = {"when": RULES["v1"], "then": "P1", "else": "P2"} if name == "PS" else \
               {"when": RULES["v1"], "then": "P2"}
        b.spec("P", "k", ["P1", "P2"], rule)
        b.dec("P2", "qa", "asp1")
    elif name == "PM":
        b.dec("P", "pm", "ma02")
    elif name == "PMV":
        b.dec("P", "pm", "mav")
    elif name == "PR":                                       # 규칙을 가진 aspect 둘. 함께 참이 되지 않는다
        b.dec("P", "pa", "asp1", None, "v1")
        b.dec("P", "pb", "asp1", None, "v2")
    elif name == "PRT":                                      # 규칙을 가진 aspect 둘. v = 1 에서 함께 참이다
        b.dec("P", "pa", "asp1", None, "v1")
        b.dec("P", "pb", "asp1", None, "v1")
    elif name == "PK":                                       # specialization 둘. 하나는 없음 대안을 가진다
        b.spec("P", "k", ["P1", "P0"])
        b.void("P0")
        b.spec("P", "j", ["P3", "P4"])
        b.dec("P4", "ra", "asp1")
    else:
        raise ValueError(kind)


P20 = ["leaf", "PV", "PVV", "PD"] + [("PO", p, q) for p in (None, 1, 2) for q in (None, 1, 2)] + \
      ["PS", "PSn", "PM", "PMV", "PR", "PRT", "PK"]
XP7 = ["asp1", "twice", "asp2", "ma1", "ma2", "ma02", "mav"]
XS4 = [None, "void", "asp", "ma"]


def f6():
    for how, pk, xs, rule in product(XP7, P20, XS4, (None, "v1")):
        b = Builder()
        b.ent("X")
        part_cluster(b, pk)
        if how == "twice":                                   # 같은 정의를 두 자리에
            b.dec("X", "xa", "asp2", None, rule, [{"def": "P", "alias": "p1"}, {"def": "P", "alias": "p2"}])
        elif how == "asp2":
            b.dec("X", "xa", "asp2", None, rule, ["P", "Lx"])
        elif how == "asp1":
            b.dec("X", "xa", "asp1", None, rule, ["P"])
        else:
            b.dec("X", "xm", how, None, rule, ["P"])
        if xs == "void":
            b.spec("X", "s", ["A", "B"])
            b.void("B")
        elif xs == "asp":                                    # 대안도 P 로 분해되고 그것이 앞선다
            b.spec("X", "s", ["A", "B"])
            b.dec("A", "aa", "asp1", 1, None, ["P"])
        elif xs == "ma":
            b.spec("X", "s", ["A", "B"])
            b.dec("A", "am", "ma02", 1, None, ["P"])
        yield b.done()


# ---------------------------------------------------------------------------
# F7. 제약
# ---------------------------------------------------------------------------

def sel(text: str) -> dict:
    return {"selected": text}


def at(path: list, **what) -> dict:
    return {"selected": dict({"path": list(path)}, **what)}


def base_twice():
    """없어도 되는 같은 병합체가 한 aspect 의 두 자리에 있다."""
    b = Builder()
    b.dec("X", "xa", "asp2", None, None, [{"def": "P", "alias": "p1"}, {"def": "P", "alias": "p2"}])
    b.spec("P", "k", ["P1", "P0"])
    b.void("P0")
    b.dec("P1", "qa", "asp1")
    atoms = [sel("P/k=P1"), sel("P/k=P0"), sel("P1=qa"), sel("X=xa"),
             at(["X", "p1"], specialization="k", alternative="P1"),
             at(["X", "p2"], specialization="k", alternative="P0"),
             at(["X", "p2"], aspect="qa")]
    return b, atoms


def base_pool():
    """병합체의 복제본. 개수 0..2."""
    b = Builder()
    b.dec("X", "xm", "ma02", None, None, ["P"])
    b.spec("P", "k", ["P1", "P2"])
    b.dec("P2", "qa", "asp1")
    atoms = [sel("X/xm=0"), sel("X/xm=2"), sel("X=xm"), sel("P/k=P2"), sel("P2=qa"),
             at(["X"], multi_aspect="xm", count=1),
             at(["X", "P_0"], specialization="k", alternative="P2"),
             at(["X", "P_1"], specialization="k", alternative="P1"),
             at(["X", "P_1"], aspect="qa")]
    return b, atoms


def base_contest():
    """뿌리 아래의 병합체에서 바탕과 대안이 같은 자리(우선순위 없음)의 분해를 가진다. 대안에 따라 분해를
    정할 수 없거나 빠진다."""
    b = Builder()
    b.dec("X", "xa", "asp1")
    b.dec("X", "xb", "asp1", 1, "v1")
    b.spec("X", "s", ["A", "B", "N"])
    b.dec("A", "aa", "asp1")
    b.void("N")
    b.embed("asp")
    atoms = [RULES["v1"], sel("X/s=A"), sel("X/s=N"), sel("X=xa"), sel("A=aa"), sel("X=xb"),
             at(["Top", "X"], specialization="s", alternative="B"),
             at(["Top", "X"], aspect="xa"),
             at(["Top", "X"], aspect="aa"),
             at(["Top"], aspect="top")]
    return b, atoms


def base_vars():
    """변수로 정하는 개수, 규칙을 가진 분해, 선택 규칙."""
    b = Builder()
    b.dec("X", "xa", "asp1", None, "w", ["P"])
    b.dec("X", "xm", "mav", None, None, ["P"])
    b.spec("P", "k", ["P1", "P2"], {"when": RULES["v1"], "then": "P1"})
    b.dec("P2", "qa", "asp1")
    atoms = [RULES["v1"], RULES["w"], sel("X/xm=1"), sel("X/xm=2"), sel("X=xm"), sel("X=xa"), sel("P/k=P2"),
             at(["X"], multi_aspect="xm", count=2),
             at(["X", "P_1"], specialization="k", alternative="P2"),
             at(["X", "P"], specialization="k", alternative="P1")]
    return b, atoms


def base_gone():
    """빠진 구성요소 안에서 한 대안의 선택도 한 선택이다 (정의 5)."""
    b = Builder()
    b.dec("X", "xa", "asp1")
    b.spec("X", "s", ["A", "B"])
    b.void("B")
    b.spec("X", "t", ["C", "D"])
    b.dec("C", "ca", "asp1", 1)
    b.embed("ma02")
    atoms = [sel("X/s=B"), sel("X/t=C"), sel("X/t=D"), sel("X=xa"), sel("C=ca"), sel("Top/top=2"),
             at(["Top", "X_0"], specialization="t", alternative="C"),
             at(["Top", "X_1"], specialization="s", alternative="B"),
             at(["Top", "X_0"], aspect="ca"),
             at(["Top"], multi_aspect="top", count=1)]
    return b, atoms


def base_nested():
    """세 단계. 아래 자리는 위에서 어떤 것을 골랐을 때만 있다."""
    b = Builder()
    b.dec("X", "xa", "asp1", None, None, ["P"])
    b.spec("X", "s", ["A", "B"])
    b.void("B")
    b.spec("P", "k", ["P1", "P2"])
    b.dec("P1", "qa", "asp1", None, None, ["Q"])
    b.spec("Q", "j", ["Q1", "Q0"])
    b.void("Q0")
    b.embed("asp")
    atoms = [sel("X/s=A"), sel("P/k=P1"), sel("Q/j=Q0"), sel("P1=qa"),
             at(["Top", "X"], specialization="s", alternative="B"),
             at(["Top", "X", "P"], specialization="k", alternative="P2"),
             at(["Top", "X", "P"], aspect="qa"),
             at(["Top", "X", "P", "Q"], specialization="j", alternative="Q1")]
    return b, atoms


def base_names():
    """한 병합체의 서로 다른 구성원이 같은 이름을 쓴다 (W4 는 한 정의 안에서만 이름이 다르기를 요구한다)."""
    b = Builder()
    b.dec("X", "a", "asp1", 1)
    b.dec("X", "m", "ma02", 2)
    b.spec("X", "s", ["A", "B"])
    b.dec("A", "a", "asp1", 2)
    b.spec("A", "s", ["C", "D"])
    b.dec("C", "m", "ma1", 1)
    atoms = [sel("X=a"), sel("A=a"), sel("X/s=A"), sel("A/s=C"), sel("C/m=1"), sel("X/m=1"),
             at(["X"], aspect="a"),
             at(["X"], aspect="m"),
             at(["X"], specialization="s", alternative="C"),
             at(["X"], multi_aspect="m", count=1)]
    return b, atoms


def base_stuck():
    """한 대안에서 분해를 정할 수 없는 부분과, 그 둘레의 선택에 대한 제약."""
    b = Builder()
    b.dec("X", "xa", "asp2", None, None, ["P", "Lx"])
    b.dec("P", "pa", "asp1", 1)
    b.spec("P", "k", ["P1", "P2", "P0"])
    b.dec("P1", "qa", "asp1", 1)
    b.dec("P2", "qb", "asp1", 2)
    b.void("P0")
    atoms = [sel("P/k=P1"), sel("P/k=P2"), sel("P/k=P0"), sel("P=pa"), sel("P1=qa"), sel("P2=qb"),
             at(["X", "P"], aspect="pa"),
             at(["X", "P"], specialization="k", alternative="P1"),
             at(["X"], aspect="xa")]
    return b, atoms


def base_mixed():
    """multi-aspect 와 대안의 aspect 가 겨룬다. 복제본의 이름이 개수 사이에서 같다."""
    b = Builder()
    b.dec("X", "xm", "ma02", 2, None, ["P"])
    b.spec("X", "s", ["A", "B"], {"when": RULES["w"], "then": "B"})
    b.dec("A", "aa", "asp1", 1, "v1", [{"def": "P", "alias": "P_0"}])
    b.spec("P", "k", ["P1", "P0"])
    b.void("P0")
    atoms = [RULES["v1"], RULES["w"], sel("X=xm"), sel("A=aa"), sel("X/xm=1"), sel("P/k=P0"), sel("X/s=A"),
             at(["X", "P_0"], specialization="k", alternative="P1"),
             at(["X", "P_1"], specialization="k", alternative="P0"),
             at(["X"], aspect="aa")]
    return b, atoms


def base_cross():
    """한 구성원에서는 specialization 이고 다른 구성원에서는 분해인 이름."""
    b = Builder()
    b.spec("X", "s", ["A", "B"])
    b.spec("X", "m", ["C", "D"])
    b.dec("A", "s", "ma02", 1)
    b.dec("A", "m", "asp1", 1, "v1")
    b.dec("C", "ca", "asp1", 2)
    atoms = [RULES["v1"], sel("X/s=A"), sel("A/s=1"), sel("A=s"), sel("A=m"), sel("X/m=C"),
             at(["X"], specialization="s", alternative="A"),
             at(["X"], multi_aspect="s", count=2),
             at(["X"], aspect="s"),
             at(["X"], aspect="m"),
             at(["X"], specialization="m", alternative="C")]
    return b, atoms


def base_place():
    """한 자리에 두 정의. aspect xa 와 xb 가 부분을 모두 p 라 부르고, 그 정의는 서로 다르며 둘 다
    specialization k 를 가진다."""
    b = Builder()
    b.dec("X", "xa", "asp1", None, None, [{"def": "P", "alias": "p"}])
    b.dec("X", "xb", "asp1", None, None, [{"def": "Q", "alias": "p"}])
    b.spec("P", "k", ["P1", "P2"])
    b.spec("Q", "k", ["Q1", "Q0"])
    b.void("Q0")
    b.dec("Q1", "qa", "asp1")
    atoms = [sel("P/k=P1"), sel("Q/k=Q0"), sel("X=xa"), sel("Q1=qa"),
             at(["X", "p"], specialization="k", alternative="P1"),
             at(["X", "p"], specialization="k", alternative="Q1"),
             at(["X", "p"], aspect="qa"),
             at(["X"], aspect="xb")]
    return b, atoms


BASES = [base_twice, base_pool, base_contest, base_vars, base_gone, base_nested, base_names, base_stuck, base_mixed,
         base_cross, base_place]


def constraint_sets(atoms: list):
    """적힌 꼴의, 크기 0..2 의 제약 집합 전부."""
    yield []
    for a in atoms:
        yield [{"name": "c0", "require": a}]
        yield [{"name": "c0", "forbid": a}]
    for a, b in product(atoms, repeat=2):
        if a is b:
            continue
        yield [{"name": "c0", "when": a, "require": b}]
        yield [{"name": "c0", "when": a, "forbid": b}]
        yield [{"name": "c0", "when": {"not": a}, "require": b}]
    for a, b in combinations(atoms, 2):
        yield [{"name": "c0", "require": {"any": [a, b]}}]
        yield [{"name": "c0", "forbid": {"all": [a, b]}}]
    simple = [(key, a) for a in atoms for key in ("require", "forbid")]
    for (k1, a), (k2, b) in combinations(simple, 2):
        yield [{"name": "c0", k1: a}, {"name": "c1", k2: b}]


def f7():
    for base in BASES:
        _, atoms = base()
        for cs in constraint_sets(atoms):
            b, _ = base()
            b.constraints = json.loads(json.dumps(cs))
            yield b.done()


# ---------------------------------------------------------------------------
# F8. 문서가 내는 selected 원자를 하나씩
# ---------------------------------------------------------------------------

K3 = ["plain", "void", ("asp1", 1)]
X2 = [("asp1", None), ("ma02", 2)]


def _counts(card) -> list:
    if isinstance(card, int):
        return [card]
    if "var" in card:
        v = VARIABLES[card["var"]]
        return list(v["values"]) if "values" in v else list(range(v["range"][0], v["range"][1] + 1))
    return list(range(card["min"], card["max"] + 1))


def _merged(ents: dict, name: str) -> list:
    """name 에서 시작하는 구성요소에 합쳐질 수 있는 정의들 (name 이 첫째)."""
    out = [name]
    for sp in (ents[name].get("specializations") or {}).values():
        for a in sp["alternatives"]:
            out += _merged(ents, a)
    return out


def atoms_of(d: dict, places: list) -> list:
    """문서가 내는 selected 원자 전부. 정의 수준은 뿌리에서 닿는 정의마다, 경로 수준은 주어진 자리마다다.
    places 는 (구성요소 경로, 그 자리의 정의)의 목록이다."""
    ents = d["entities"]
    root = next(n for n, e in ents.items() if e.get("root"))
    seen, stack = [], [root]
    while stack:                                             # 닿는 정의들. 순서는 고정이다
        n = stack.pop(0)
        if n in seen:
            continue
        seen.append(n)
        e = ents[n]
        stack += [a for sp in (e.get("specializations") or {}).values() for a in sp["alternatives"]]
        stack += [p if isinstance(p, str) else p["def"] for a in (e.get("aspects") or {}).values() for p in a["parts"]]
        stack += [ma["part"] for ma in (e.get("multi_aspects") or {}).values()]
    out = []
    for n in seen:
        e = ents[n]
        for sname, sp in (e.get("specializations") or {}).items():
            out += [sel(f"{n}/{sname}={a}") for a in sp["alternatives"]]
        for x in list(e.get("aspects") or {}) + list(e.get("multi_aspects") or {}):
            out.append(sel(f"{n}={x}"))
        for x, ma in (e.get("multi_aspects") or {}).items():
            out += [sel(f"{n}/{x}={k}") for k in _counts(ma["cardinality"])]
    for path, name in places:
        got = []                                             # 두 구성원의 같은 이름은 원자 하나다
        for y in _merged(ents, name):
            e = ents[y]
            for sname, sp in (e.get("specializations") or {}).items():
                got += [("specialization", sname, "alternative", a) for a in sp["alternatives"]]
            for x in list(e.get("aspects") or {}) + list(e.get("multi_aspects") or {}):
                got.append(("aspect", x))
            for x, ma in (e.get("multi_aspects") or {}).items():
                got += [("multi_aspect", x, "count", k) for k in _counts(ma["cardinality"])]
        for g in dict.fromkeys(got):
            out.append(at(path, **({g[0]: g[1]} if len(g) == 2 else {g[0]: g[1], g[2]: g[3]})))
    return out


def f8_structures():
    for xd, aw, bw, cw, dw, (where, tname), how in product(X2, K3, K3, K3, K3, T3, ("root", "ma02")):
        if where == "A" and aw == "void":
            continue
        def make():
            b = Builder()
            b.ent("X")
            b.dec("X", "xa" if xd[0].startswith("asp") else "xm", xd[0], xd[1])
            b.spec("X", "s", ["A", "B"])
            alt(b, "A", aw)
            alt(b, "B", bw)
            b.spec(where, tname, ["C", "D"])
            alt(b, "C", cw)
            alt(b, "D", dw)
            b.embed(how)
            return b
        places = [(["X"], "X")] if how == "root" else [(["Top"], "Top"), (["Top", "X_1"], "X")]
        yield make, places


def f8():
    for make, places in f8_structures():
        yield make().done()
        for a in atoms_of(make().done(), places):
            b = make()
            b.constraints = [{"name": "c0", "forbid": a}]
            yield b.done()


# ---------------------------------------------------------------------------
# F9. 드문 모양
# ---------------------------------------------------------------------------

X6 = [None, "asp0", "aspL", "aspB", "ma0", "man"]
SEL3 = [None, {"when": RULES["v1"], "then": "N", "else": "A"}, {"when": RULES["v1"], "then": "N"}]
DEEP3 = [None, ("yes", None), ("yes", 1)]


def f9():
    for aw, bw, nw, xd, select, deep in product(K3, K3, K3, X6, SEL3, DEEP3):
        if xd == "aspB" and bw == "void":
            continue                                         # W2: 없음 대안은 부분이 아니다
        if deep is not None and aw == "void":
            continue                                         # W2: 없음 대안은 specialization 을 가지지 않는다
        b = Builder()
        b.ent("X")
        if xd == "asp0":
            b.dec("X", "xa", "asp0")
        elif xd == "aspL":
            b.dec("X", "xa", "asp1")
        elif xd == "aspB":
            b.dec("X", "xa", "asp1", None, None, ["B"])
        elif xd in ("ma0", "man"):
            b.dec("X", "xm", xd)
        b.spec("X", "s", ["A", "B", "N"], select)
        alt(b, "A", aw)
        alt(b, "B", bw)
        alt(b, "N", nw)
        if deep is not None:
            b.spec("A", "t", ["C", "D"])
            b.spec("C", "u", ["E", "F"])
            b.dec("E", "ea", "asp1", deep[1])
        yield b.done()


# ---------------------------------------------------------------------------
# F10. 규칙의 식
# ---------------------------------------------------------------------------

EXPR8 = [
    RULES["v1"],
    {"not": RULES["v1"]},
    {"all": [RULES["v1"], RULES["w"]]},
    {"any": [RULES["v2"], RULES["nw"]]},
    {"var": "v", "lt": {"var": "u"}},
    {"var": "v", "in": [2]},
    {"all": []},
    {"any": []},
]


def f10():
    for r1, r2, pris, when in product(EXPR8, EXPR8, ((None, None), (1, 1), (1, 2)), [None] + EXPR8):
        b = Builder()
        b.dec("X", "xa", "asp1", pris[0], json.loads(json.dumps(r1)))
        b.dec("X", "xb", "asp1", pris[1], json.loads(json.dumps(r2)))
        b.spec("X", "s", ["A", "B"],
               None if when is None else {"when": json.loads(json.dumps(when)), "then": "A", "else": "B"})
        b.dec("A", "aa", "asp1", 1)
        yield b.done()


# ---------------------------------------------------------------------------
# F11. 한 정의가 두 깊이에서 대안인 것
# ---------------------------------------------------------------------------

CON7 = [None, "C=ca", "A/t=C", "X/s=C", ("specialization", "t", "C"), ("specialization", "s", "C"), ("aspect", "ca")]


def f11():
    for px, pa, pc, void_d, con in product((None, 1, 2), (None, 1, 2), (None, 1, 2), (False, True), CON7):
        b = Builder()
        b.dec("X", "xa", "asp1", px)
        b.spec("X", "s", ["A", "C"])                         # C 를 바로
        b.dec("A", "aa", "asp1", pa)
        b.spec("A", "t", ["C", "D"])                         # 그리고 A 아래에도 (C 는 A 를, A 는 X 를 extends 한다)
        b.ent("C")["extends"] = "A"
        b.dec("C", "ca", "asp1", pc)
        if void_d:
            b.void("D")
        b.embed("ma02")
        if isinstance(con, str):
            b.constraints = [{"name": "c0", "forbid": sel(con)}]
        elif con is not None and con[0] == "specialization":
            b.constraints = [{"name": "c0", "forbid": at(["Top", "X_1"], specialization=con[1], alternative=con[2])}]
        elif con is not None:
            b.constraints = [{"name": "c0", "forbid": at(["Top", "X_1"], aspect=con[1])}]
        yield b.done()


FAMILIES = {"F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5, "F6": f6, "F7": f7, "F8": f8, "F9": f9, "F10": f10,
            "F11": f11}


def documents(families=None):
    """(묶음, 번호, 문서)를 고정된 순서로."""
    for name in families or FAMILIES:
        for i, d in enumerate(FAMILIES[name]()):
            yield name, i, d


def document(family: str, index: int) -> dict:
    for i, d in enumerate(FAMILIES[family]()):
        if i == index:
            return d
    raise IndexError(f"{family}/{index}")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        print(json.dumps(document(sys.argv[1], int(sys.argv[2])), ensure_ascii=False, indent=1))
    else:
        total = 0
        for name, gen in FAMILIES.items():
            n = sum(1 for _ in gen())
            total += n
            print(f"{name}: {n}")
        print(f"합계: {total}")
