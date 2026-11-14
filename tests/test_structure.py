"""계층 구조의 성질: 평탄화, 절단, 치환, 끝에서 끝까지의 구동, 표현 완전성
(docs/ses-platform/14_executors.md 의 정리 17, 20, 21과 명제).
"""

import collections
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ses_core import load_ses_dict  # noqa: E402
from ses_core import structure as st  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.extension import interpret, violations as layer_violations  # noqa: E402
from ses_core.structure import IN, OUT, node  # noqa: E402
from ses_core.unfold import unfold_layered  # noqa: E402

TYPES = ["A", "B"]


def rand_structure(rng, depth=3, top=True) -> dict:
    """무작위 적격 구조. 결합은 방향과 타입이 맞는 것만 고른다."""
    ports = {f"p{i}": (rng.choice(TYPES), rng.choice([IN, OUT])) for i in range(rng.randint(1, 4))}
    required = [p for p in ports if rng.random() < 0.3]
    if depth == 0 or (not top and rng.random() < 0.3):
        return node(ports, required=required)
    kids = {f"c{i}": rand_structure(rng, depth - 1, False) for i in range(rng.randint(1, 3))}
    eic = [(sp, (ch, cp)) for sp, (t, d) in ports.items() if d == IN
           for ch, c in kids.items() for cp, (t2, d2) in c["ports"].items() if d2 == IN and t2 == t]
    eoc = [((ch, cp), sp) for sp, (t, d) in ports.items() if d == OUT
           for ch, c in kids.items() for cp, (t2, d2) in c["ports"].items() if d2 == OUT and t2 == t]
    ic = [((a, ap), (b, bp)) for a, ca in kids.items() for ap, (t, d) in ca["ports"].items() if d == OUT
          for b, cb in kids.items() for bp, (t2, d2) in cb["ports"].items() if d2 == IN and t2 == t]
    pick = lambda xs: [x for x in xs if rng.random() < 0.45]                 # noqa: E731
    return node(ports, kids, pick(eic), pick(eoc), pick(ic), required)


def rand_cut(rng, n) -> list:
    out = []

    def go(c, path):
        if st.is_atom(c) or rng.random() < 0.4:
            out.append(path)
        else:
            for name, child in c["children"].items():
                go(child, path + (name,))

    for name, child in n["children"].items():
        go(child, (name,))
    return out


def all_paths(n) -> list:
    """한 걸음 관계의 길을 원천마다 모두 따라가 본다. 평탄화의 정의를 그대로 옮긴 것이다."""
    succ = collections.defaultdict(list)
    for a, b in st.steps(n):
        succ[a].append(b)
    found = []

    def go(trail):
        for q in succ[trail[-1]]:
            assert q not in trail                            # 순환이 없다
            go(trail + [q])
        if len(trail) > 1:
            found.append(trail)

    for s in st.sources(n):
        go([s])
    return found


def kind_of(n, a, b) -> str:
    """한 걸음의 종류: 올라감(외부 출력 결합), 건너감(내부 결합), 내려감(외부 입력 결합)."""
    if len(b[0]) < len(a[0]):
        return "U"
    return "D" if len(b[0]) > len(a[0]) else "I"


STATS: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(300))
def test_paths_have_the_shape_up_across_down(seed):
    """보조정리: 모든 길은 올라감 몇 번, 건너감 많아야 한 번, 내려감 몇 번의 꼴이다."""
    n = rand_structure(random.Random(seed))
    assert st.violations(n) == []
    h = st.height(n)
    targets = st.sinks(n)
    count = collections.Counter()
    for trail in all_paths(n):
        shape = "".join(kind_of(n, a, b) for a, b in zip(trail, trail[1:]))
        assert shape.lstrip("U").lstrip("I").strip("D") == "" and shape.count("I") <= 1, shape
        assert len(shape) <= 2 * h + 1
        if trail[-1] in targets:
            count[(trail[0], trail[-1])] += 1
    assert st.flatten(n) == count                            # 평탄화는 원천에서 수신처로 가는 길의 수다
    STATS["connections"] += len(count)
    STATS["multi_path"] += sum(1 for k in count.values() if k > 1)


@pytest.mark.parametrize("seed", range(300))
def test_theorem17_flattening_is_compositional(seed):
    rng = random.Random(seed)
    n = rand_structure(rng)
    whole = st.flatten(n)
    for _ in range(3):
        cut = rand_cut(rng, n)
        assert st.is_cut(n, cut)
        assert st.compose_flat(n, cut) == whole              # 몫과 안쪽을 이어 붙이면 전체와 같다
        STATS["cuts"] += 1
        STATS["proper_cuts"] += any(not st.is_atom(st.subtree(n, c)) for c in cut)
    # 따름정리: 뿌리의 자식에서 자르면 계층을 한 층씩 조립하는 계산이 된다
    assert st.compose_flat(n, [(name,) for name in n["children"]]) == whole
    # 모든 원자에서 자르면 몫이 자기 자신이다
    assert st.canon(st.quotient(n, st.atoms(n))) == st.canon(n)


@pytest.mark.parametrize("seed", range(200))
def test_substitution_leaves_the_outside_unchanged(seed):
    """따름정리: 인터페이스가 같은 것으로 바꾸면 바깥의 적격성과 바깥에서 본 연결이 그대로다."""
    rng = random.Random(seed)
    n = rand_structure(rng)
    targets = [p for p, c in st.walk(n) if p]
    c = rng.choice(targets)
    old = st.subtree(n, c)
    new = rand_structure(rng, depth=2, top=not st.is_atom(old) or rng.random() < 0.5)
    new["ports"], new["required"] = dict(old["ports"]), list(old["required"])
    for key in ("eic", "eoc"):                               # 새 안쪽의 결합은 옛 인터페이스에 맞는 것만 남긴다
        new[key] = []
    if not st.is_atom(new):
        for name, child in new["children"].items():
            for cp, (t, d) in child["ports"].items():
                for sp, (t2, d2) in new["ports"].items():
                    if (t, d) == (t2, d2) and rng.random() < 0.5:
                        new[key_for(d)].append(((sp, (name, cp)) if d == IN else ((name, cp), sp)))
    m = st.replace(n, c, new)
    assert st.violations(m) == []
    cut = [c] + [a for a in st.atoms(m) if a[:len(c)] != c]
    assert st.is_cut(m, cut)
    old_cut = [c] + [a for a in st.atoms(n) if a[:len(c)] != c]
    assert st.canon(st.quotient(m, cut)) == st.canon(st.quotient(n, old_cut))
    assert st.flatten(st.quotient(m, cut)) == st.flatten(st.quotient(n, old_cut))
    outside = lambda x: {k: v for k, v in st.flatten(x).items()             # noqa: E731
                         if k[0][0][:len(c)] != c and k[1][0][:len(c)] != c}
    assert outside(m) == outside(n)                          # 바깥의 원자 사이 연결은 안쪽과 무관하다


def key_for(direction):
    return "eic" if direction == IN else "eoc"


# ---------------------------------------------------------------------------
# 끝에서 끝까지의 구동 (조건 C5)
# ---------------------------------------------------------------------------

def dangling_example():
    """08 문서의 C4는 통과하지만 원자의 필수 입력에 아무것도 닿지 않는 구조."""
    leaf = node({"x": ("A", IN)}, required=["x"])
    box = node({"i": ("A", IN)}, {"L": leaf}, eic=[("i", ("L", "x"))])          # i는 필수가 아니다
    src = node({"o": ("A", OUT)})
    return node({}, {"A": src, "Box": box})                                     # A.o를 Box.i에 잇지 않았다


def test_one_step_condition_does_not_give_end_to_end_drive():
    n = dangling_example()
    assert st.violations(n) == [] and st.one_step_undriven(n) == []            # C1에서 C4는 모두 통과한다
    assert st.ungrounded(n) == [(("Box", "L"), "x")]                           # 그러나 L.x에는 원천이 없다
    assert st.flatten(n) == {}
    fixed = st.copy(n)
    fixed["ic"].append((("A", "o"), ("Box", "i")))
    assert st.ungrounded(fixed) == [] and st.flatten(fixed) == {((("A",), "o"), (("Box", "L"), "x")): 1}


@pytest.mark.parametrize("seed", range(300))
def test_c5_implies_c4_and_is_strictly_stronger(seed):
    n = rand_structure(random.Random(seed))
    c4, c5 = set(st.one_step_undriven(n)), set(st.ungrounded(n))
    assert c4 <= c5                                          # C5를 어기지 않으면 C4도 어기지 않는다
    reached = {t for _, t in st.flatten(n)}
    for path, c in st.walk(n):                               # 원자의 필수 입력: 구동된다 = 평탄화의 수신처다
        if st.is_atom(c) and path:
            for p in c["required"]:
                if c["ports"][p][1] == IN:
                    assert ((path, p) in c5) == ((path, p) not in reached)
    STATS["c4_ok"] += not c4
    STATS["c4_ok_c5_bad"] += (not c4) and bool(c5)
    STATS["c5_ok"] += not c5


# ---------------------------------------------------------------------------
# 위임 완전성과 재구성
# ---------------------------------------------------------------------------

def rand_bare_tree(rng, depth=3, top=True) -> dict:
    if depth == 0 or (not top and rng.random() < 0.35):
        return node({f"p{i}": (rng.choice(TYPES), rng.choice([IN, OUT])) for i in range(rng.randint(1, 3))})
    return node({}, {f"c{i}": rand_bare_tree(rng, depth - 1, False) for i in range(rng.randint(1, 3))})


@pytest.mark.parametrize("seed", range(300))
def test_delegation_completeness(seed):
    """정리 21 (d): 계층을 넘는 어떤 연결 집합도 위임 포트를 더해 그 계층 위에 정확히 표현된다."""
    rng = random.Random(seed)
    tree = rand_bare_tree(rng)
    tree["ports"] = {"rin": ("A", IN), "rout": ("B", OUT)}
    outs = [(p, x) for p in st.atoms(tree) for x, (t, d) in st.subtree(tree, p)["ports"].items() if d == OUT]
    ins = [(p, x) for p in st.atoms(tree) for x, (t, d) in st.subtree(tree, p)["ports"].items() if d == IN]
    typ = lambda pt: (st.subtree(tree, pt[0]) if pt[0] else tree)["ports"][pt[1]][0]      # noqa: E731
    cands = [(s, t) for s in outs + [((), "rin")] for t in ins + [((), "rout")]
             if typ(s) == typ(t) and (s[0] or t[0]) and not (not s[0] and not t[0])]
    conns = rng.sample(cands, min(len(cands), rng.randint(0, 6)))
    n = st.from_flat(tree, conns)
    assert st.violations(n) == []
    assert st.flatten(n) == collections.Counter(conns)       # 정확히 그 연결들이고 섞임이 없다
    added = sum(len(c["ports"]) for p, c in st.walk(n)) - sum(len(c["ports"]) for p, c in st.walk(tree))
    crossings = 0
    for (a, _), (b, _) in conns:                             # 넘는 경계 하나마다 포트 하나
        if a and b:
            k = 0
            while k < min(len(a), len(b)) - 1 and a[k] == b[k]:
                k += 1
            crossings += (len(a) - k - 1) + (len(b) - k - 1)
        else:
            crossings += len(a or b) - 1
    assert added == crossings
    STATS["delegated"] += len(conns)
    STATS["delegation_ports"] += added


@pytest.mark.parametrize("seed", range(200))
def test_theorem20_regrouping_keeps_the_flat_connections(seed):
    """원자를 실행기별 묶음으로 다시 계층화해도 평탄화된 연결은 같고, 묶음을 넘는 연결이 이음매다."""
    rng = random.Random(seed)
    n = rand_structure(rng)
    if st.is_atom(n):
        pytest.skip("원자 하나뿐인 구조")
    group_of = {a: rng.choice(["devs", "hw", "sw"]) for a in st.atoms(n)}
    w, seam = st.regroup(n, group_of)
    assert st.violations(w) == [] and st.height(w) <= 2
    rename = lambda p: (group_of[p], "/".join(p)) if p else ()                # noqa: E731
    expected = {((rename(s), sp), (rename(t), tp)) for ((s, sp), (t, tp)) in st.flatten(n)}
    assert set(st.flatten(w)) == expected
    assert set(seam) == {c for c in expected if c[0][0] and c[1][0] and c[0][0][0] != c[1][0][0]}
    assert len(w["ic"]) == len(seam)                         # 뿌리의 내부 결합이 정확히 이음매다
    for g, comp in w["children"].items():                    # 묶음 하나는 그 실행기가 혼자 만들 수 있는 구조다
        inner = st.flatten(comp)
        assert {(s, t) for (s, t) in inner if s[0] and t[0]} == \
            {((s[0][1:], s[1]), (t[0][1:], t[1])) for (s, t) in expected
             if s[0] and t[0] and s[0][0] == t[0][0] == g}
    STATS["seams"] += len(seam)


# ---------------------------------------------------------------------------
# 표현 완전성: 구조의 유한한 족은 모두 어떤 SES의 변이들이다 (정리 21의 (a)에서 (c))
# ---------------------------------------------------------------------------

def document_of(structs: list) -> dict:
    """증명의 구성: 뿌리의 specialization이 구조를 고르고, 대안마다 그 구조를 그대로 적는다."""
    entities = {"Sys": {"root": True,
                        "specializations": {"which": {"alternatives": [f"Sys_{i}" for i in range(len(structs))]}}}}

    def define(name, n, extends=None):
        body = {}
        if extends:
            body["extends"] = extends
        if n["ports"]:
            body["ports"] = {p: dict(type=t, direction=d, **({"required": True} if p in n["required"] else {}))
                             for p, (t, d) in n["ports"].items()}
        if n["children"]:
            parts = []
            for cname, child in n["children"].items():
                define(f"{name}__{cname}", child)
                parts.append({"def": f"{name}__{cname}", "alias": cname})
            couplings = [{"from": sp, "to": f"{ch}.{cp}"} for sp, (ch, cp) in n["eic"]] + \
                        [{"from": f"{ch}.{cp}", "to": sp} for (ch, cp), sp in n["eoc"]] + \
                        [{"from": f"{a}.{ap}", "to": f"{b}.{bp}"} for (a, ap), (b, bp) in n["ic"]]
            body["aspects"] = {"a": dict(parts=parts, **({"couplings": couplings} if couplings else {}))}
        entities[name] = body

    for i, n in enumerate(structs):
        define(f"Sys_{i}", n, extends="Sys")
    return {"ses": "1.0", "name": "Sys", "port_types": {t: {} for t in TYPES}, "entities": entities}


@pytest.mark.parametrize("seed", range(200))
def test_theorem21_every_finite_family_of_structures_is_an_ses(seed):
    rng = random.Random(seed)
    family = [rand_structure(rng, depth=2, top=rng.random() < 0.8) for _ in range(rng.randint(1, 4))]
    L = unfold_layered(load_ses_dict(document_of(family)))
    variants = sem(L.ses)
    realized = [interpret(L, V)["devs"] for V in variants]
    assert len(variants) == len(family)                      # 대안 하나가 변이 하나다
    assert {st.canon(r) for r in realized} == {st.canon(n) for n in family}
    for V, r in zip(variants, realized):                     # (a) 실현 모델은 적격 구조다
        assert st.violations(r) == []
        codes = {code for _, code, _, _ in layer_violations(L, V)}
        assert codes <= {"C4"}                               # 족의 구조가 C4를 어길 때만 변이가 부적격이다
        assert ("C4" in codes) == bool(st.one_step_undriven(r))
    STATS["families"] += 1
    STATS["members"] += len(family)


def test_structure_samples_are_not_vacuous():
    if not STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["connections"] >= 1000 and STATS["multi_path"] >= 20, STATS
    assert STATS["proper_cuts"] >= 500, STATS
    assert STATS["c4_ok_c5_bad"] >= 5 and STATS["c5_ok"] >= 30, STATS
    assert STATS["delegated"] >= 500 and STATS["delegation_ports"] >= 500 and STATS["seams"] >= 200, STATS
    assert STATS["members"] >= 400, STATS
