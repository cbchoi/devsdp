"""결정 집합: 가지치기를 자료로 적은 것, 선택 지점 표, 증거
(docs/ses-platform/13_editor_data_model.md).
"""

import collections
import os
import random
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import rand_document  # noqa: E402
from test_algebra import rand_formula, rand_tree  # noqa: E402

from ses_core import load_ses, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core.algebra import ASP, ENT, SPEC, SES, AlgebraError, Tree, is_pes, prune, reduce, sem, variants  # noqa: E402
from ses_core.decisions import (  # noqa: E402
    Choice, ChoicePoint, DecisionSet, apply, choice_table, choices, component_path, excluded,
    family, load_decisions, patterns, problems, split_count, witness)
from ses_core.extension import wf_core  # noqa: E402
from ses_core.profile import load_profile  # noqa: E402
from ses_core.skeleton import members  # noqa: E402
from ses_core.unfold import pruning_patterns, unfold, unfold_layered, variable_domains  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform")
EXAMPLES = os.path.join(ROOT, "examples")
DOMAINS = os.path.join(ROOT, "domains")


def processing():
    return unfold(load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml")))


def curriculum():
    doc = load_ses(os.path.join(DOMAINS, "curriculum_intro_programming.ses.yaml"))
    return doc, unfold_layered(doc, load_profile(os.path.join(DOMAINS, "curriculum.profile.yaml")))


def var_set(S):
    return set(sem(S)) if S is not None else set()


def names(S):
    return {n[-1] for n in S.tree.nodes}


# ---------------------------------------------------------------------------
# 예제: 결정 집합은 가지치기 SES 파일과 같은 일을 한다
# ---------------------------------------------------------------------------

def test_decision_set_equals_the_pruning_ses_file():
    S = processing()
    pruning = load_ses(os.path.join(EXAMPLES, "processing_system.pruning.ses.yaml"))
    by_file = prune(S, *pruning_patterns(pruning))
    ds = DecisionSet(choose=(
        Choice(at="Buffer", specialization="policySpec", alternative=("PriorityBuffer",)),
        Choice(at="ServerPool", multi_aspect="serversMAsp", count=(4,))))
    by_decisions = apply(S, ds)
    assert by_decisions.tree.nodes == by_file.tree.nodes
    assert var_set(by_decisions) == var_set(by_file)
    assert is_pes(by_decisions)


def test_variable_values_alone_select_the_structure():
    """문헌에서 가지치기의 표준 인터페이스는 변수 값이다. 09 문서의 결함 1.3."""
    S = processing()
    R = apply(S, DecisionSet(variables={"policy": ("priority",), "num_servers": (4,)}))
    assert is_pes(R)
    assert "PriorityBuffer" in names(R) and "FifoBuffer" not in names(R)
    assert {"server_0", "server_3"} <= names(R) and "server_4" not in names(R)
    # 선택 제약: 우선순위 정책은 서버가 2대 이상일 때만 허용된다
    assert apply(S, DecisionSet(variables={"policy": ("priority",), "num_servers": (1,)})) is None
    # 값을 여럿 남기면 부분 가지치기다
    R = apply(S, DecisionSet(variables={"num_servers": (2, 3)}))
    assert len(sem(R)) == 4


def test_example_decision_file():
    doc = load_ses(os.path.join(EXAMPLES, "processing_system.ses.yaml"))
    ds = load_decisions(os.path.join(EXAMPLES, "processing_system.decisions.yaml"))
    assert ds.target == doc.name
    S = unfold(doc)
    assert problems(S, ds) == []
    R = apply(S, ds)
    assert is_pes(R)
    by_file = prune(S, *pruning_patterns(load_ses(os.path.join(EXAMPLES, "processing_system.pruning.ses.yaml"))))
    assert R.tree.nodes == by_file.tree.nodes
    assert DecisionSet.from_dict(yaml.safe_load(yaml.safe_dump(ds.to_dict(), allow_unicode=True))) == ds


POOL = {
    "ses": "1.0", "name": "Pool",
    "entities": {
        "Pool": {"root": True, "multi_aspects": {"servers": {"part": "Server", "cardinality": {"min": 2, "max": 3},
                                                             "naming": "server_{i}"}}},
        "Server": {"specializations": {"kind": {"alternatives": ["Fast", "Slow"]}}},
        "Fast": {"extends": "Server"},
        "Slow": {"extends": "Server"},
    },
}


def test_replicas_can_be_decided_one_by_one():
    S = unfold(load_ses_dict(POOL))
    assert len(sem(S)) == 4 + 8
    two = Choice(at="Pool", multi_aspect="servers", count=(2,))
    fast0 = Choice(path=("Pool", "server_0"), specialization="kind", alternative=("Fast",))
    slow1 = Choice(path=("Pool", "server_1"), specialization="kind", alternative=("Slow",))
    R = apply(S, DecisionSet(choose=(two, fast0, slow1)))
    assert is_pes(R)
    assert ("Pool", "servers[2]", "server_0", "kind", "Fast") in R.tree.nodes
    assert ("Pool", "servers[2]", "server_1", "kind", "Slow") in R.tree.nodes
    # 경로 수준의 결정은 개수와 무관하게 그 이름의 복제본에 적용된다
    R = apply(S, DecisionSet(choose=(fast0, slow1)))
    assert len(sem(R)) == 1 + 2
    # 정의 수준의 결정은 모든 복제본에 적용된다
    all_fast = Choice(at="Server", specialization="kind", alternative=("Fast",))
    assert len(sem(apply(S, DecisionSet(choose=(all_fast,))))) == 2
    # 두 수준의 결정은 모두 적용된다. 덮어쓰지 않으며 모순이면 남는 것이 없다
    assert apply(S, DecisionSet(choose=(all_fast, slow1))) is None


def test_decisions_form_a_set():
    ds = DecisionSet()
    a = Choice(at="Server", specialization="kind", alternative=("Fast",))
    b = Choice(at="Server", specialization="kind", alternative=("Slow",))
    c = Choice(at="Pool", multi_aspect="servers", count=(2,))
    ds = ds.decide(a).decide(c)
    assert ds.choose == (a, c)
    ds = ds.decide(b)                                      # 같은 선택 지점의 결정은 바뀐다
    assert ds.choose == (c, b)
    assert ds.undecide(c.key).choose == (b,)               # 되돌리기는 결정 하나를 빼는 일이다
    ds = ds.assign("n", 2, 3)
    assert ds.variables == {"n": (2, 3)}
    assert ds.assign("n").variables == {}
    assert ds.to_dict() == {"decisions": "1.0", "variables": {"n": [2, 3]}, "choose": [
        {"at": "Pool", "multi_aspect": "servers", "count": 2},
        {"at": "Server", "specialization": "kind", "alternative": "Slow"}]}
    assert DecisionSet.from_dict(ds.to_dict()) == ds


def test_malformed_and_stale_decisions_are_reported():
    S = unfold(load_ses_dict(POOL))
    stale = [
        Choice(at="Nowhere", specialization="kind", alternative=("Fast",)),          # 없는 정의
        Choice(at="Server", specialization="type", alternative=("Fast",)),           # 없는 선택 지점
        Choice(at="Server", specialization="kind", alternative=("Medium",)),         # 없는 선택지
        Choice(at="Pool", multi_aspect="servers", count=(9,)),
        Choice(at="Pool", aspect=("layout",)),
        Choice(path=("Pool", "server_7"), specialization="kind", alternative=("Fast",)),
        Choice(node=("Pool", "servers[2]"), aspect=("x",)),                         # 엔티티가 아닌 노드
        Choice(at="Server", path=("Pool",), specialization="kind", alternative=("Fast",)),   # 주소가 둘
        Choice(at="Server", specialization="kind"),                                  # 남길 것이 없다
        Choice(at="Server"),                                                         # 내용이 없다
    ]
    good = Choice(at="Server", specialization="kind", alternative=("Fast",))
    ds = DecisionSet(variables={"missing": (1,)}, choose=tuple(stale) + (good,))
    found = problems(S, ds)
    assert [key for key, _ in found] == [("variable", "missing")] + [c.key for c in stale]
    with pytest.raises(AlgebraError):
        apply(S, ds)
    assert var_set(apply(S, ds, skip_invalid=True)) == var_set(apply(S, DecisionSet(choose=(good,))))
    assert all(c.problems() for c in stale[-3:]) and not good.problems()


# ---------------------------------------------------------------------------
# 무작위 문서: 번역이 선언한 뜻과 같고 순서와 무관하다
# ---------------------------------------------------------------------------

def selection_points(T):
    """(엔티티 노드, 결정의 내용에 쓸 낱말들)의 목록."""
    out = []
    for q in T.kinds:
        if T.kind(q) == SPEC and not q[-1].startswith("$"):
            kids = [c[-1] for c in T.children(q)]
            if len(kids) > 1:
                out.append((q[:-1], "specialization", q[-1], kids))
        elif T.kind(q) == ENT:
            fams = list(dict.fromkeys(family(a[-1]) for a in T.aspects(q)))
            if len(fams) > 1:
                out.append((q, "aspect", "", fams))
            for fam in fams:
                counts = [split_count(a[-1])[1] for a in T.aspects(q) if family(a[-1]) == fam]
                if len(counts) > 1:
                    out.append((q, "multi_aspect", fam, counts))
    return out


def rand_choice(rng, T, level=None):
    points = selection_points(T)
    if not points:
        return None
    y, kind, group, options = rng.choice(points)
    keep = tuple(rng.sample(options, rng.randint(1, max(1, len(options) - 1))))
    what = {"specialization": dict(specialization=group, alternative=keep),
            "multi_aspect": dict(multi_aspect=group, count=keep),
            "aspect": dict(aspect=keep)}[kind]
    level = level or rng.choice(["at", "at", "path", "node"])
    where = {"at": dict(at=T.label(y)), "path": dict(path=component_path(T, y)), "node": dict(node=y)}[level]
    return Choice(**where, **what)


def rand_decisions(rng, S):
    T = S.tree
    ds = DecisionSet()
    for _ in range(rng.randint(1, 4)):
        c = rand_choice(rng, T)
        if c is not None:
            ds = ds.decide(c)
    for q in T.specs(T.root):
        if q[-1].startswith("$") and rng.random() < 0.5:
            values = [c[-1] for c in T.children(q)]
            ds = ds.assign(q[-1][1:], *rng.sample(values, rng.randint(1, len(values))))
    return ds


def entries(T, ds):
    out = [Choice(node=T.root, specialization="$" + k, alternative=tuple(str(v) for v in vs))
           for k, vs in ds.variables.items()]
    return out + list(ds.choose)


STATS: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(300))
def test_decisions_mean_what_they_exclude_in_any_order(seed):
    rng = random.Random(seed)
    S = unfold(load_ses_dict(rand_document(rng)))
    T = S.tree
    ds = rand_decisions(rng, S)
    assert problems(S, ds) == []
    banned = set().union(*(excluded(T, c) for c in entries(T, ds))) if entries(T, ds) else set()
    expected = {V for V in sem(S) if not (banned & V)}      # 뜻: 배제한 선택지를 고르지 않는 변이
    R = apply(S, ds)
    assert var_set(R) == expected
    if R is not None:
        assert R.tree.nodes == frozenset().union(*expected)  # 축약되어 있다
    shuffled = list(ds.choose)
    rng.shuffle(shuffled)
    assert var_set(apply(S, DecisionSet(variables=dict(reversed(list(ds.variables.items()))),
                                        choose=tuple(shuffled)))) == expected
    # 결정은 원래의 SES를 기준으로 가지치기 SES로 번역된다. 번역된 것을 하나씩 차례로,
    # 어떤 순서로 적용해도 같다 (07 문서의 정리 5).
    translated = patterns(S, ds)
    rng.shuffle(translated)
    one_by_one = S
    for P in translated:
        one_by_one = prune(one_by_one, P) if one_by_one is not None else None
    assert var_set(one_by_one) == expected
    STATS["empty" if R is None else "partial" if len(expected) < len(sem(S)) else "no_effect"] += 1
    for c in ds.choose:
        STATS[c.key[0]] += 1


def test_decision_sample_is_not_vacuous():
    if not STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert STATS["partial"] >= 150 and STATS["empty"] >= 5, STATS
    assert min(STATS["at"], STATS["path"], STATS["node"]) >= 80, STATS


@pytest.mark.parametrize("seed", range(200))
def test_definition_level_decision_is_a_folded_pruning_ses(seed):
    """at 으로 적은 결정은 접힌 형태의 가지치기 SES(높이 2의 패턴)와 같은 결과를 낸다."""
    rng = random.Random(seed)
    c = None
    while c is None:                                        # 선택 지점이 있는 문서가 나올 때까지
        S = unfold(load_ses_dict(rand_document(rng)))
        T = S.tree
        c = rand_choice(rng, T, level="at")
    kinds = {(c.at,): ENT}
    occurrence = next(q for q in T.kinds if T.kind(q) == ENT and T.label(q) == c.at)
    if c.specialization is not None:
        kinds[(c.at, c.specialization)] = SPEC
        for alt in c.alternative:
            kinds[(c.at, c.specialization, alt)] = ENT
    else:
        for a in T.aspects(occurrence):
            fam, n = split_count(a[-1])
            keep = fam in c.aspect if c.aspect else (fam != c.multi_aspect or n in c.count)
            if keep:
                kinds[(c.at, a[-1])] = ASP
    folded = SES(Tree(kinds))
    assert var_set(apply(S, DecisionSet(choose=(c,)))) == var_set(prune(S, folded))


# ---------------------------------------------------------------------------
# 증거: 변이 하나를 정확히 재현한다
# ---------------------------------------------------------------------------

WITNESS: collections.Counter = collections.Counter()


def check_witness(S, V, domains=None):
    T = S.tree
    w = witness(T, V, domains)
    assert problems(S, w) == []
    R = apply(S, w)
    again = DecisionSet.from_dict(yaml.safe_load(yaml.safe_dump(w.to_dict(), allow_unicode=True)))
    assert again == w                                       # 파일로 적었다 읽어도 같다
    for c in w.choose:
        WITNESS[c.key[0]] += 1
    return w, R


@pytest.mark.parametrize("seed", range(200))
def test_witness_reproduces_exactly_its_variant(seed):
    rng = random.Random(seed)
    doc = load_ses_dict(rand_document(rng))
    S = unfold(doc)
    T = S.tree
    good = sem(S)
    for V in rng.sample(good, min(8, len(good))):
        w, R = check_witness(S, V, variable_domains(doc))
        assert R is not None and R.tree.nodes == V and is_pes(R)
    bad = [V for V in variants(T) if V not in set(good)]    # 제약을 어기는 선택은 남지 않는다
    for V in rng.sample(bad, min(3, len(bad))):
        w, R = check_witness(S, V)
        assert R is None
        assert sem(apply(SES(T), w)) == [V]


@pytest.mark.parametrize("seed", range(100))
def test_witness_on_trees_without_shared_definitions(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    S = SES(T, rand_formula(rng, T))
    for V in rng.sample(variants(T), min(6, len(variants(T)))):
        w, R = check_witness(S, V)
        assert all(c.at is not None for c in w.choose)      # 이름이 모두 다르면 정의 수준으로 충분하다
        if V in set(sem(S)):
            assert R.tree.nodes == V
        else:
            assert R is None


def test_witness_falls_back_to_narrower_addresses():
    # 병합체의 두 구성원이 같은 이름의 부분을 가지고, 그 부분이 서로 다르게 고른 변이.
    # 정의 수준으로도 구성요소 경로로도 적을 수 없으므로 노드로 적는다.
    kinds = {("r",): ENT, ("r", "a"): ASP, ("r", "a", "x"): ENT, ("r", "a", "x", "k"): SPEC,
             ("r", "a", "x", "k", "p"): ENT, ("r", "a", "x", "k", "q"): ENT,
             ("r", "s"): SPEC, ("r", "s", "b"): ENT, ("r", "s", "b", "c"): ASP,
             ("r", "s", "b", "c", "x"): ENT, ("r", "s", "b", "c", "x", "k"): SPEC,
             ("r", "s", "b", "c", "x", "k", "p"): ENT, ("r", "s", "b", "c", "x", "k", "q"): ENT}
    T = Tree(kinds)
    S = SES(T)
    assert len(variants(T)) == 4
    levels = collections.Counter()
    for V in variants(T):
        w, R = check_witness(S, V)
        assert R.tree.nodes == V
        levels.update(c.key[0] for c in w.choose)
    assert levels["node"] == 4 and levels["at"] == 2        # 둘이 같게 고른 변이는 정의 수준 하나로 적힌다
    # 복제본이 서로 다르게 고르면 구성요소 경로로 적는다
    S = unfold(load_ses_dict(POOL))
    V = next(V for V in sem(S) if ("Pool", "servers[2]", "server_0", "kind", "Fast") in V
             and ("Pool", "servers[2]", "server_1", "kind", "Slow") in V)
    w, R = check_witness(S, V)
    assert R.tree.nodes == V
    assert w.to_dict()["choose"] == [
        {"at": "Pool", "multi_aspect": "servers", "count": 2},
        {"path": ["Pool", "server_0"], "specialization": "kind", "alternative": "Fast"},
        {"path": ["Pool", "server_1"], "specialization": "kind", "alternative": "Slow"}]


def test_witness_sample_is_not_vacuous():
    if not WITNESS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert WITNESS["at"] >= 500 and WITNESS["path"] >= 100 and WITNESS["node"] >= 4, WITNESS


def test_witness_gives_variable_values_their_type():
    doc, L = curriculum()
    S = L.ses
    V = next(V for V in sem(S) if any(n[-1] == "실습들[2]" for n in V) and any(n[-1] == "웹트랙" for n in V)
             and any(n[-1] == "심화미개설" for n in V))
    w = witness(S.tree, V, variable_domains(doc))
    assert w.to_dict() == {"decisions": "1.0", "variables": {"실습주수": 2}, "choose": [
        {"at": "심화알고리즘", "specialization": "개설여부", "alternative": "심화미개설"},
        {"at": "응용영역", "aspect": "웹트랙"},
        {"at": "실습영역", "multi_aspect": "실습들", "count": 2}]}
    assert apply(S, w).tree.nodes == V
    assert witness(S.tree, V).variables == {"실습주수": ("2",)}       # 표가 없으면 나무에 적힌 글자


# ---------------------------------------------------------------------------
# 선택 지점 표
# ---------------------------------------------------------------------------

def test_choice_table_of_the_curriculum():
    doc, L = curriculum()
    S = L.ses
    domains = variable_domains(doc)
    table = choices(S, domains=domains)
    assert [(p.owner, p.kind, p.group, p.options) for p in table] == [
        ("실습주수", "variable", "", ((1, True), (2, True), (3, True))),
        ("심화알고리즘", "alternative", "개설여부", (("심화개설", True), ("심화미개설", True))),
        ("응용영역", "aspect", "", (("자료처리트랙", True), ("웹트랙", True))),
        ("실습영역", "count", "실습들", ((1, True), (2, True), (3, True)))]
    assert not any(p.decided for p in table)

    ds = DecisionSet().pick(table[2], "웹트랙").pick(table[0], 2)
    table = choices(S, ds, domains)
    assert table[2].remaining == ("웹트랙",) and table[2].decided
    assert table[0].remaining == (2,)
    assert table[3].remaining == (2,)                      # 개수는 변수를 따라 정해진다
    assert not table[1].decided
    assert len(sem(apply(S, ds))) == 2
    assert ds.pick(table[2]).choose == ()                  # 선택지 없이 고르면 결정을 푼다

    core = wf_core(L)                                      # 적격 핵에서 죽은 선택지
    table = choice_table(S, core.ses, domains)
    assert table[1].options == (("심화개설", True), ("심화미개설", False))
    assert table[3].options == ((1, True), (2, True), (3, False))
    assert table[0].options == ((1, True), (2, True), (3, False))
    assert all(not p.active for p in choice_table(S, None))


@pytest.mark.parametrize("seed", range(150))
def test_choice_table_marks_what_remains(seed):
    rng = random.Random(seed)
    doc = load_ses_dict(rand_document(rng))
    S = unfold(doc)
    T = S.tree
    ds = rand_decisions(rng, S) if rng.random() < 0.7 else DecisionSet()
    R = apply(S, ds)
    left = var_set(R)
    table = choice_table(S, R, variable_domains(doc))
    seen = set()
    for p in table:
        assert len(p.options) > 1
        for option, alive in p.options:
            if p.kind == "variable":
                nodes = [T.root + ("$" + p.owner, str(option))]
            elif p.kind == "alternative":
                nodes = [q + (p.group, option) for q in T.kinds if T.kind(q) == ENT and T.label(q) == p.owner]
            else:
                nodes = [a for q in T.kinds if T.kind(q) == ENT and T.label(q) == p.owner
                         for a in T.aspects(q)
                         if (family(a[-1]) == option if p.kind == "aspect"
                             else split_count(a[-1]) == (p.group, option))]
            nodes = [n for n in nodes if n in T.nodes]
            assert nodes
            assert alive == any(n in V for V in left for n in nodes)    # 남았다 = 남은 변이가 어디선가 고른다
            seen.update(nodes)
        # 표의 한 줄에서 남은 선택지 하나를 고르면 그 줄은 그것으로 정해진다
        if p.remaining and rng.random() < 0.3:
            option = rng.choice(p.remaining)
            after = choice_table(S, apply(S, ds.pick(p, option)), variable_domains(doc))
            same = next(x for x in after if (x.owner, x.kind, x.group) == (p.owner, p.kind, p.group))
            assert set(same.remaining) <= {option}
    # 선택지가 둘 이상인 선택 지점은 빠짐없이 표에 있다
    for y, kind, group, options in selection_points(T):
        row = {"specialization": "alternative", "multi_aspect": "count", "aspect": "aspect"}[kind]
        assert any((p.owner, p.kind, p.group) == (T.label(y), row, group) for p in table)


# ---------------------------------------------------------------------------
# 문서의 이름이 바뀌면 결정 집합이 따라간다
# ---------------------------------------------------------------------------

def test_decision_set_follows_renames_in_the_document():
    path = os.path.join(DOMAINS, "curriculum_intro_programming.ses.yaml")
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    ds = DecisionSet(target="프로그래밍입문", variables={"실습주수": (2,)}, choose=(
        Choice(at="응용영역", aspect=("웹트랙",)),
        Choice(at="심화알고리즘", specialization="개설여부", alternative=("심화개설",)),
        Choice(at="실습영역", multi_aspect="실습들", count=(2,)),
        Choice(path=("프로그래밍입문", "기초영역", "심화알고리즘"), specialization="개설여부",
               alternative=("심화개설",))))
    before = apply(unfold(load_ses_dict(d)), ds)
    assert is_pes(before)

    m = E.from_dict(d)
    ed = E.Editor(m)
    plan = [(m.entity("응용영역"), "응용"), (m.by_name("aspect", "웹트랙")[0], "웹"),
            (m.by_name("specialization", "개설여부")[0], "개설"), (m.entity("심화개설"), "개설함"),
            (m.by_name("variable", "실습주수")[0], "주수"), (m.by_name("multi_aspect", "실습들")[0], "반복"),
            (m.entity("프로그래밍입문"), "입문"), (m.entity("기초영역"), "기초")]
    stale = 0
    for id, new in plan:
        r = ed.rename(id, new)
        ds = ds.renamed(r.type, r.old, r.new, r.owner)
        stale += bool(problems(unfold(load_ses_dict(E.to_dict(m))), ds))
    after_doc = unfold(load_ses_dict(E.to_dict(m)))
    assert ds.target == "입문" and ds.variables == {"주수": (2,)}
    assert ds.choose[0] == Choice(at="응용", aspect=("웹",))
    assert ds.choose[1] == Choice(at="심화알고리즘", specialization="개설", alternative=("개설함",))
    assert ds.choose[2] == Choice(at="실습영역", multi_aspect="반복", count=(2,))
    # 경로 수준의 결정은 엔티티 이름만 따라간다. specialization 이름은 낡은 채로 남고 보고된다
    assert ds.choose[3].path == ("입문", "기초", "심화알고리즘") and ds.choose[3].specialization == "개설여부"
    assert [key for key, _ in problems(after_doc, ds)] == [ds.choose[3].key]
    assert stale == 6                                       # 세 번째 이름 바꾸기부터 낡은 결정이 하나 있다
    after = apply(after_doc, ds, skip_invalid=True)
    assert is_pes(after) and len(after.tree.nodes) == len(before.tree.nodes)
