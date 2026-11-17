"""진단: 예외 대신 요소를 가리키는 자료로 보고한다
(docs/ses-platform/13_editor_data_model.md).
"""

import collections
import json
import os
import random
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from docgen import rand_document  # noqa: E402
from test_edit import CURRICULUM, DOCS, PLAIN, PROCESSING, damage, ident, rand_command, raw  # noqa: E402

from ses_core import load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core.algebra import reduce, sem  # noqa: E402
from ses_core.decisions import DecisionSet, apply, choice_table, family, split_count  # noqa: E402
from ses_core.diagnose import (  # noqa: E402
    PROFILE_CODES, analyze, check_document, effective_kind, provenance, unfolded_size)
from ses_core.edit import MISSING, EditError, Editor, Insert, Ref, Set  # noqa: E402
from ses_core.extension import violations  # noqa: E402
from ses_core.profile import load_profile  # noqa: E402
from ses_core.skeleton import MARKERS, skeleton  # noqa: E402
from ses_core.unfold import unfold_layered, variable_domains  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform")


def profile_of(d):
    if d.get("profile"):
        return load_profile(os.path.join(ROOT, "domains", d["profile"] + ".profile.yaml"))
    return None


def open_doc(path):
    d = raw(path)
    m = E.from_dict(d)
    return m, Editor(m), profile_of(d)


def summary(a):
    """족 범위의 오류: (부호, 주소, 해당 변이 수, 원인)."""
    return [(d.code, d.address, d.affected, {k: v for k, v in d.cause.items() if k != "decisions"},
             d.cause_covers)
            for d in a.diagnostics if d.scope == "family" and d.severity == "error"]


def dead(a):
    return [(d.address, d.path, d.data["option"]) for d in a.of("DEAD")]


def at(owner, **what):
    return dict(at=owner, **what)


# ---------------------------------------------------------------------------
# 저장소의 문서
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", DOCS, ids=ident)
def test_repository_documents_have_no_document_errors(path):
    m, _, profile = open_doc(path)
    found = check_document(m, profile)
    assert [d for d in found if d.severity == "error"] == []
    pruning = path.endswith(".pruning.ses.yaml")            # 가지치기 SES의 정의는 패턴이라 뿌리에서 닿지 않는다
    assert {d.code for d in found} == ({"UNUSED"} if pruning else set())
    assert check_document(m, profile, unused=False) == []


def test_curriculum_diagnostics_name_elements_extent_and_cause():
    m, _, profile = open_doc(CURRICULUM)
    a = analyze(m, profile)
    assert (a.variants, a.wellformed) == (12, 4)
    lack = "성취기준은 다뤄지고 평가된다: 들어오는 관계 달성 이 0개다"
    assert [d.message for d in a.errors] == [lack, "총시수: 값이 48 이다"]
    assert summary(a) == [
        ("R1", "entities/LO4", (6, 12),
         {"choose": [at("심화알고리즘", specialization="개설여부", alternative="심화미개설")]}, 6),
        ("R2", "entities/프로그래밍입문", (2, 12),
         {"variables": {"실습주수": 3},
          "choose": [at("심화알고리즘", specialization="개설여부", alternative="심화개설")]}, 2)]
    first = a.errors[0]
    assert first.layer == "curriculum" and m.get(first.element).props["name"] == "LO4"
    assert [m.address(r) for r in first.related] == ["entities/프로그래밍입문/aspects/구성/parts/LO4"]
    assert first.witness == {"decisions": "1.0", "variables": {"실습주수": 1}, "choose": [
        at("심화알고리즘", specialization="개설여부", alternative="심화미개설"),
        at("응용영역", aspect="자료처리트랙"),
        at("실습영역", multi_aspect="실습들", count=1)]}
    assert dead(a) == [
        ("variables/실습주수", ("spec",), 3),
        ("entities/심화알고리즘/specializations/개설여부/alternatives/심화미개설", (), "심화미개설"),
        ("entities/실습영역/multi_aspects/실습들", ("cardinality",), 3)]
    assert [p.remaining for p in a.table] == [(1, 2), ("심화개설",), ("자료처리트랙", "웹트랙"), (1, 2)]


def test_rfp_and_paper_diagnostics():
    m, _, profile = open_doc(os.path.join(ROOT, "domains", "rfp_lms.ses.yaml"))
    a = analyze(m, profile)
    assert (a.variants, a.wellformed) == (8, 2)
    assert summary(a) == [
        ("R1", "entities/동시접속", (4, 8),
         {"choose": [at("동시접속", specialization="포함여부", alternative="성능요구포함")]}, 4),
        ("L1", "entities/운영평가", (4, 8),
         {"choose": [at("운영과업", specialization="운영범위", alternative="운영제외")]}, 4)]
    assert [x[2] for x in dead(a)] == ["성능요구포함", "운영제외"]

    m, _, profile = open_doc(os.path.join(ROOT, "domains", "paper_pruning_algebra.ses.yaml"))
    a = analyze(m, profile)
    assert (a.variants, a.wellformed) == (8, 2)
    assert [(code, address, affected) for code, address, affected, _, _ in summary(a)] == [
        ("R2", "entities/가지치기대수논문", (2, 8)), ("R1", "entities/C3", (1, 8)),
        ("R2", "entities/가지치기대수논문", (2, 8)), ("R1", "entities/E4", (2, 8)), ("R1", "entities/E3", (2, 8))]
    assert [x[2] for x in dead(a)] == ["E4포함"]


def test_processing_system_is_clean():
    m, _, _ = open_doc(PROCESSING)
    a = analyze(m)
    assert a.diagnostics == [] and (a.variants, a.wellformed) == (15, 15)
    assert [(p.owner, p.kind, len(p.options)) for p in a.table] == [
        ("num_servers", "variable", 8), ("policy", "variable", 2),
        ("Buffer", "alternative", 2), ("ServerPool", "count", 8)]


# ---------------------------------------------------------------------------
# 틀린 문서: 진단이 요소를 가리킨다
# ---------------------------------------------------------------------------

def strict_tools_reject(m) -> bool:
    """엄격한 도구(정준 문서 쓰기, 적재기, 스키마) 가운데 하나라도 이 상태를 거부하는가."""
    jsonschema = pytest.importorskip("jsonschema")
    try:
        d = E.to_dict(m)
    except EditError:
        return True
    try:
        load_ses_dict(d)
    except Exception:
        return True
    with open(os.path.join(ROOT, "schema", "ses.schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    return bool(list(jsonschema.Draft202012Validator(schema).iter_errors(d)))


def ent(m, name):
    return m.entity(name)


def named(m, type, name):
    return m.by_name(type, name)[0]


def _two_roots(m, ed):
    ed.set(ent(m, "Server"), "root", True)


def _bad_name(m, ed):
    m.apply(Set(ent(m, "Server"), ("name",), "Server", "서 버"))


def _duplicate(m, ed):
    m.apply(Insert(m.new_id("entity"), "entity", m.root, "entities", 0, {"name": "Server"}))


def _extends_cycle(m, ed):
    ed.set(ent(m, "Buffer"), "extends", Ref(ent(m, "FifoBuffer"), None))


def _foreign_alternative(m, ed):
    ed.add_alternative(named(m, "specialization", "policySpec"), ent(m, "Collector"), set_extends=False)


def _self_part(m, ed):
    ed.add_part(named(m, "aspect", "pipelineDec"), ent(m, "ProcessingSystem"))


def _no_alternatives(m, ed):
    for alt in list(m.kids(named(m, "specialization", "policySpec"), "alternatives")):
        ed.remove(alt.id)


def _drop_part(m, ed):
    ed.remove(next(p.id for p in m.of_type("part") if m.label(p.id) == "Collector"))


def _rename_port(entity, old, new):
    def change(m, ed):
        ports = m.get(ent(m, entity)).props["ports"]
        ed.set(ent(m, entity), "ports", {(new if k == old else k): v for k, v in ports.items()})
    return change


BROKEN = {
    "뿌리 없음": (lambda m, ed: ed.set(ent(m, "ProcessingSystem"), "root", MISSING),
              "ROOT", "", ()),
    "뿌리 둘": (_two_roots, "ROOT", "entities/Server", ("root",)),
    "끊어진 부분": (lambda m, ed: ed.remove(ent(m, "Collector")),
               "REF", "entities/ProcessingSystem/aspects/pipelineDec/parts/Collector", ("def",)),
    "끊어진 복제 대상": (lambda m, ed: ed.remove(ent(m, "Server")),
                  "REF", "entities/ServerPool/multi_aspects/serversMAsp", ("part",)),
    "규칙에 맞지 않는 이름": (_bad_name, "NAME", "entities/서 버", ("name",)),
    "겹치는 이름": (_duplicate, "DUP", "entities/Server#1", ("name",)),
    "extends 순환": (_extends_cycle, "EXT", "entities/Buffer", ("extends",)),
    "소유자를 extends 하지 않는 대안": (_foreign_alternative, "EXT",
                             "entities/Buffer/specializations/policySpec/alternatives/Collector", ()),
    "대안이 아닌 기본값": (lambda m, ed: ed.set(named(m, "specialization", "policySpec"), "default",
                                        Ref(ent(m, "Server"), None)),
                   "SPEC", "entities/Buffer/specializations/policySpec", ("default",)),
    "선택 규칙이 고르는 것이 대안이 아님": (lambda m, ed: ed.set(named(m, "specialization", "policySpec"),
                                                  ("select", "then"), "Server"),
                             "SPEC", "entities/Buffer/specializations/policySpec", ("select",)),
    "개수의 변수가 없음": (lambda m, ed: ed.set(named(m, "multi_aspect", "serversMAsp"), "cardinality",
                                        {"var": "nope"}),
                   "VAR", "entities/ServerPool/multi_aspects/serversMAsp", ("cardinality",)),
    "지운 변수를 쓰는 선택 규칙": (lambda m, ed: ed.remove(named(m, "variable", "policy")),
                       "VAR", "entities/Buffer/specializations/policySpec", ("select",)),
    "지운 변수를 쓰는 제약": (lambda m, ed: ed.remove(named(m, "variable", "policy")),
                    "VAR", "", ("constraints",)),
    "없음 대안이 부분": (lambda m, ed: ed.set(ent(m, "Collector"), "stereotype", "void"),
                  "VOID", "entities/ProcessingSystem/aspects/pipelineDec/parts/Collector", ("def",)),
    "내용을 가진 없음 대안": (lambda m, ed: ed.set(ent(m, "Collector"), "stereotype", "void"),
                     "VOID", "entities/Collector", ()),
    "분해를 가진 atomic": (lambda m, ed: ed.set(ent(m, "ServerPool"), "stereotype", "atomic"),
                      "ATOMIC", "entities/ServerPool", ("stereotype",)),
    "자기 자신을 포함": (_self_part, "CYCLE",
                  "entities/ProcessingSystem/aspects/pipelineDec/parts/ProcessingSystem", ()),
    "복제 대상이 없음": (lambda m, ed: ed.set(named(m, "multi_aspect", "serversMAsp"), "part", MISSING),
                  "MISS", "entities/ServerPool/multi_aspects/serversMAsp", ("part",)),
    "대안이 없는 specialization": (_no_alternatives, "MISS", "entities/Buffer/specializations/policySpec", ()),
    "모르는 stereotype": (lambda m, ed: ed.set(ent(m, "Server"), "stereotype", "bogus"),
                       "SHAPE", "entities/Server", ("stereotype",)),
    "type 없는 변수": (lambda m, ed: ed.set(named(m, "variable", "policy"), "spec", {"values": ["a"]}),
                   "SHAPE", "variables/policy", ("spec",)),
    # 포트와 결합은 이름으로 이어진 속성이다. 끊어지면 결합의 자리까지 짚는다
    "결합이 가리키는 부분이 빠짐": (_drop_part, "COUP", "entities/ProcessingSystem/aspects/pipelineDec",
                         ("couplings", 2, "to")),
    "부분의 포트 이름이 바뀜": (_rename_port("Buffer", "in", "input"), "COUP",
                       "entities/ProcessingSystem/aspects/pipelineDec", ("couplings", 0, "to")),
    "자신의 포트 이름이 바뀜": (_rename_port("ServerPool", "done", "finished"), "COUP",
                       "entities/ServerPool/multi_aspects/serversMAsp", ("couplings", "fan_in", 1, "to")),
    "복제본의 포트 이름이 바뀜": (_rename_port("Server", "out", "result"), "COUP",
                        "entities/ServerPool/multi_aspects/serversMAsp", ("couplings", "fan_in", 0, "from")),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_document_is_diagnosed_at_the_element(case):
    change, code, address, path = BROKEN[case]
    m, ed, _ = open_doc(PROCESSING)
    assert analyze(m).diagnostics == []
    change(m, ed)
    found = check_document(m)
    hits = [d for d in found if (d.code, d.address, d.path) == (code, address, path)]
    assert len(hits) == 1, [(d.code, d.address, d.path) for d in found]
    d = hits[0]
    assert d.severity == "error" and d.blocking and d.scope == "document"
    assert m.find(d.address) == d.element                  # 주소로 요소를 다시 찾는다
    assert strict_tools_reject(m)                          # 엄격한 도구도 이 상태를 거부한다
    a = analyze(m)                                         # 분석은 멈추지 않고, 변이 분석만 건너뛴다
    assert a.variants is None and [x.code for x in a.diagnostics][-1] == "SKIP"
    while ed.undo() is not None:                           # 되돌리면 진단도 사라진다
        pass
    if not ed.history.redo_stack:                          # 원시 연산으로 직접 바꾼 경우는 되돌릴 이력이 없다
        return
    assert analyze(m).diagnostics == []


def test_unreachable_entity_is_a_warning_and_does_not_block():
    m, ed, _ = open_doc(PROCESSING)
    orphan = ed.add_entity("Orphan")
    a = analyze(m)
    assert [(d.severity, d.code, d.element, d.blocking) for d in a.diagnostics] == [
        ("warning", "UNUSED", orphan, False)]
    assert a.variants == 15
    ed.add_entity("Base")                                  # extends 로만 쓰이는 바탕은 쓰이는 것으로 본다
    ed.set(ent(m, "Server"), "extends", Ref(ent(m, "Base"), None))
    assert [d.element for d in analyze(m).of("UNUSED")] == [orphan]


def test_incomplete_document_gets_diagnostics_not_exceptions():
    m = E.from_dict({})                                    # 빈 문서
    assert [(d.code, d.path) for d in analyze(m).diagnostics] == [
        ("SHAPE", ("ses",)), ("SHAPE", ("name",)), ("ROOT", ()), ("SKIP", ())]
    m = E.new_document("새문서")
    ed = Editor(m)
    a = ed.add_entity("A", root=True)
    asp = ed.add_aspect(a, "구성")
    codes = [d.code for d in analyze(m).diagnostics]
    assert codes == ["MISS"]                                # 부분이 없는 aspect는 경고다. 분석은 된다
    assert analyze(m).variants == 1
    sp = ed.add_specialization(a, "종류")
    assert [d.code for d in analyze(m).errors] == ["MISS"]  # 대안이 없으면 A는 나타날 수 없다
    b = ed.add_entity("B")
    ed.add_alternative(sp, b)
    ed.add_alternative(sp, ed.add_entity("C"))
    ed.add_part(asp, ed.add_entity("D"))
    a2 = analyze(m)
    assert a2.errors == [] and a2.variants == 2


# ---------------------------------------------------------------------------
# 프로파일: 정의만 보고 알 수 있는 것은 문서 범위에서 바로 알린다
# ---------------------------------------------------------------------------

def _kind(m, ed):
    ed.set_kind(ent(m, "함수"), "차시")


def _wrong_source(m, ed):
    ed.add_link(ent(m, "LO1"), "선수", ent(m, "함수"))


def _wrong_target(m, ed):
    ed.add_link(ent(m, "함수"), "선수", ent(m, "LO1"))


def _containment(m, ed):
    ed.add_part(named(m, "aspect", "단원구성"), ent(m, "중간평가"))


PROFILE_CASES = {
    "모르는 유형": (_kind, "T1", "entities/함수", ("kind",)),
    "유형에 없는 필드": (lambda m, ed: ed.set_field(ent(m, "함수"), "난이도", 3),
                  "F1", "entities/함수", ("fields", "난이도")),
    "타입이 다른 값": (lambda m, ed: ed.set_field(ent(m, "함수"), "시수", "여섯"),
                 "F3", "entities/함수", ("fields", "시수")),
    "허용 값이 아닌 값": (lambda m, ed: ed.set_field(ent(m, "심화알고리즘"), "수준", "최상"),
                   "F3", "entities/심화알고리즘", ("fields", "수준")),
    "extends 로 물려받은 유형": (lambda m, ed: ed.set_field(ent(m, "심화개설"), "시수", "x"),
                         "F3", "entities/심화개설", ("fields", "시수")),
    "모르는 관계": (lambda m, ed: ed.add_link(ent(m, "함수"), "참고", ent(m, "LO1")),
               "L0", "entities/함수/links/참고:LO1", ("type",)),
    "출발이 될 수 없는 유형": (_wrong_source, "L2", "entities/LO1/links/선수:함수", ()),
    "도착이 될 수 없는 유형": (_wrong_target, "L2", "entities/함수/links/선수:LO1", ("target",)),
    "담을 수 없는 부분": (_containment, "T2", "entities/기초영역/aspects/단원구성/parts/중간평가", ()),
}


@pytest.mark.parametrize("case", sorted(PROFILE_CASES))
def test_profile_violation_is_reported_in_the_document_scope(case):
    change, code, address, path = PROFILE_CASES[case]
    m, ed, profile = open_doc(CURRICULUM)
    change(m, ed)
    found = check_document(m, profile)
    hits = [d for d in found if (d.code, d.address, d.path) == (code, address, path)]
    assert len(hits) == 1, [(d.code, d.address, d.path) for d in found]
    assert hits[0].severity == "error" and not hits[0].blocking
    assert code in PROFILE_CODES

    # 변이의 뜻과 어긋나지 않는다: 그 정의가 살아 있는 변이는 같은 부호의 위반을 가진다
    L = unfold_layered(load_ses_dict(E.to_dict(m)), profile)
    owner = m.get(m.entity_of(hits[0].element)).props["name"]
    alive = [V for V in sem(L.ses) if owner in live_labels(L, V)]
    assert alive
    assert all(any(c == code for _, c, _, _ in violations(L, V)) for V in alive)

    # 변이 분석은 계속되고, 문서 범위에서 알린 것을 되풀이하지 않는다
    a = analyze(m, profile)
    assert a.variants == 12
    again = [d for d in a.diagnostics if d.scope == "family" and d.code == code]
    assert again == []
    assert any(d.scope == "family" for d in a.diagnostics)  # 다른 족 범위 진단은 그대로 나온다


def live_labels(L, V) -> set:
    """변이 V의 뼈대에 살아 있는 구성요소들의 정의 표지. 없음 대안을 고른 구성요소는 빠진다."""
    out: set = set()
    stack = [skeleton(L.ses.tree, L.void, V)]
    while stack:
        comp = stack.pop()
        if comp is not None:
            out.update(comp.labels)
            stack.extend(comp.parts.values())
    return out


def test_profile_must_match_the_document():
    m, _, profile = open_doc(CURRICULUM)
    other = load_profile(os.path.join(ROOT, "domains", "rfp.profile.yaml"))
    for prof in (None, other):
        a = analyze(m, prof)
        assert [(d.code, d.address, d.path, d.blocking) for d in a.errors] == [
            ("PROFILE", "", ("profile",), True)]
        assert a.variants is None


def test_effective_kind_follows_extends():
    m, _, _ = open_doc(CURRICULUM)
    assert effective_kind(m, ent(m, "심화개설")) == "단원"
    assert effective_kind(m, ent(m, "함수")) == "단원"
    m.apply(Set(ent(m, "심화알고리즘"), ("extends",), MISSING, Ref(ent(m, "심화개설"), None)))
    m.apply(Set(ent(m, "심화알고리즘"), ("kind",), "단원", MISSING))
    assert effective_kind(m, ent(m, "심화개설")) is None      # 순환해도 멈춘다


# ---------------------------------------------------------------------------
# 펼친 나무에서 문서의 요소로
# ---------------------------------------------------------------------------

def test_provenance_maps_tree_nodes_to_elements():
    m, _, profile = open_doc(CURRICULUM)
    T = unfold_layered(load_ses_dict(E.to_dict(m)), profile).ses.tree
    where = lambda p: tuple(m.address(x) if x else None for x in provenance(m, T, p))    # noqa: E731
    assert where(("프로그래밍입문",)) == ("entities/프로그래밍입문", None)
    assert where(("프로그래밍입문", "구성", "LO4")) == (
        "entities/LO4", "entities/프로그래밍입문/aspects/구성/parts/LO4")
    assert where(("프로그래밍입문", "구성", "실습영역", "실습들[2]", "실습_1")) == (
        "entities/실습", "entities/실습영역/multi_aspects/실습들")
    assert where(("프로그래밍입문", "구성", "기초영역", "단원구성", "심화알고리즘", "개설여부", "심화미개설")) == (
        "entities/심화미개설", "entities/심화알고리즘/specializations/개설여부/alternatives/심화미개설")
    for node in T.kinds:                                    # 모든 엔티티 노드가 요소로 돌아간다
        if T.kind(node) == "ent" and not node[-2:-1] == ("$실습주수",):
            entity, usage = provenance(m, T, node)
            assert entity is not None and (usage is not None) == (len(node) > 1)


# ---------------------------------------------------------------------------
# 무작위 문서: 족 범위의 진단이 직접 열거한 것과 같다
# ---------------------------------------------------------------------------

FAMILY: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(200))
def test_family_diagnostics_agree_with_direct_enumeration(seed):
    d = rand_document(random.Random(seed))
    m = E.from_dict(d)
    a = analyze(m)
    L = unfold_layered(load_ses_dict(d))
    S, T = L.ses, L.ses.tree
    vs = sem(S)
    table: dict = {}
    good = []
    for V in vs:
        found = violations(L, V)
        if not found:
            good.append(V)
        for layer, code, path, msg in found:
            table.setdefault((layer, code, m.entity(T.label(path)), msg), set()).add(V)
    assert (a.variants, a.wellformed) == (len(vs), len(good))
    assert [x for x in a.diagnostics if x.scope == "document"] == check_document(m)
    assert not [x for x in a.diagnostics if x.blocking]

    family_errors = [x for x in a.diagnostics if x.scope == "family" and x.severity == "error"
                     and x.code != "NOWF"]
    assert {(x.layer, x.code, x.element, x.message): x.affected for x in family_errors} == \
        {key: (len(hit), len(vs)) for key, hit in table.items()}
    for x in family_errors:
        hit = table[(x.layer, x.code, x.element, x.message)]
        assert m.find(x.address) == x.element
        W = apply(S, DecisionSet.from_dict(x.witness))       # 증거는 문제가 있는 변이 하나를 재현한다
        assert len(sem(W)) == 1 and sem(W)[0] in hit
        cause = DecisionSet.from_dict(x.cause)
        follows = sem(apply(S, cause))                       # 원인을 따르는 변이는 모두 문제를 가진다
        assert follows and set(follows) <= hit and len(follows) == x.cause_covers
        entries = [("v", k) for k in cause.variables] + [("c", c) for c in cause.choose]
        for kind, e in entries:                              # 원인에서 더 뺄 것이 없다
            smaller = cause.assign(e) if kind == "v" else cause.undecide(e.key)
            assert not set(sem(apply(S, smaller))) <= hit
        FAMILY["errors"] += 1
        FAMILY["cause_explains_all"] += x.cause_covers == x.affected[0]
        FAMILY["cause_shorter_than_witness"] += len(entries) < len(x.witness.get("choose", [])) + \
            len(x.witness.get("variables", {}))

    if not good:
        assert [x.code for x in a.diagnostics][-1] == "NOWF"
        FAMILY["nowf"] += 1
        return
    # 죽은 선택지: 적격 변이가 고르지 않는 선택지. 그 선택 지점이 적격 변이에 나타날 때만 알린다
    core_nodes = frozenset().union(*good)
    every = choice_table(S, reduce(S), variable_domains(load_ses_dict(d)))
    expected = set()
    for p in every:
        def lives(option, nodes):
            if p.kind == "variable":
                return (T.root[0], "$" + p.owner, str(option)) in nodes
            for q in T.kinds:
                if T.kind(q) != "ent" or T.label(q) != p.owner:
                    continue
                if p.kind == "alternative" and q + (p.group, option) in nodes:
                    return True
                if p.kind != "alternative" and any(
                        a in nodes and (family(a[-1]) == option if p.kind == "aspect"
                                        else split_count(a[-1]) == (p.group, option)) for a in T.aspects(q)):
                    return True
            return False
        if any(lives(o, core_nodes) for o, _ in p.options):
            expected |= {(p.owner, p.kind, p.group, o) for o, _ in p.options if not lives(o, core_nodes)}
    got = {(x.data["owner"], x.data["kind"], x.data["group"], x.data["option"]) for x in a.of("DEAD")}
    assert got == expected
    for x in a.of("DEAD"):
        assert m.find(x.address) == x.element and x.severity == "warning"
    FAMILY["dead"] += len(got)
    FAMILY["clean"] += not family_errors


def test_family_sample_is_not_vacuous():
    if not FAMILY:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert FAMILY["errors"] >= 50 and FAMILY["dead"] >= 60 and FAMILY["clean"] >= 80, FAMILY
    assert FAMILY["cause_shorter_than_witness"] >= 40 and FAMILY["cause_explains_all"] >= 30, FAMILY


@pytest.mark.parametrize("seed", range(200))
def test_core_analysis_beyond_the_limit_agrees_with_enumeration(seed):
    """한도를 넘으면 변이를 열거하지 않고 정의 표 위에서 핵을 분석한다 (theory.md 4절). 같은 문서를 한도 안에서
    열거해 분석한 것과 견준다. 변이 수, 적격 변이 수, 핵의 위반이 생기는 요소, 죽은 선택지가 같다.

    표본의 문서에는 포트와 속성이 없어 확장의 위반이 없다. 그래서 적격이 곧 핵 적격이다."""
    d = rand_document(random.Random(seed))
    m = E.from_dict(d)
    full, core = analyze(m), analyze(m, max_variants=0)
    assert core.variants is None and core.of("LIMIT") and core.core is not None
    assert (core.core.variants, core.core.wellformed) == (full.variants, full.wellformed)

    def errors(a):
        return {(x.code, x.element) for x in a.diagnostics if x.scope == "family" and x.severity == "error"}

    def dead_options(a):
        return {(x.element, json.dumps(x.data, sort_keys=True, default=str)) for x in a.of("DEAD")}

    assert errors(core) == errors(full)
    assert dead_options(core) == dead_options(full)
    for x in core.of("K1"):                                  # 맞서는 분해와 변수 값의 예를 적는다
        assert "맞서는 분해" in x.message and x.data["owners"] and m.find(x.address) == x.element
    FAMILY["core_errors"] += len(errors(core))
    FAMILY["core_dead"] += len(core.of("DEAD"))
    FAMILY["core_docs"] += 1


@pytest.mark.parametrize("seed", range(120))
def test_core_analysis_beyond_the_limit_agrees_on_priorities_and_constraints(seed):
    """우선순위, 분해의 규칙, 선택 제약을 가진 문서에서도 두 분석이 같다. 다른 구성원의 분해에 늘 밀리는 분해를
    죽은 선택지로 알리는 것도 같다. 포트와 결합은 떼어 확장의 위반이 없게 했다."""
    from test_folded import stripped
    from test_parity import prioritized
    d = stripped(prioritized(seed)[0])
    functions = prioritized(seed)[2]
    m = E.from_dict(d)
    full, core = analyze(m, functions=functions), analyze(m, max_variants=0, functions=functions)
    if full.variants is None:                                # 문서 범위의 오류가 있으면 두 분석 모두 하지 않는다
        assert core.core is None
        return
    assert (core.core.variants, core.core.wellformed) == (full.variants, full.wellformed)
    assert {(x.code, x.element) for x in core.errors} == {(x.code, x.element) for x in full.errors}
    assert {(x.element, x.message.replace("핵 적격", "적격"), json.dumps(x.data, sort_keys=True, default=str))
            for x in core.of("DEAD")} == \
        {(x.element, x.message, json.dumps(x.data, sort_keys=True, default=str)) for x in full.of("DEAD")}
    FAMILY["prio_docs"] += 1
    FAMILY["prio_pushed_dead"] += sum("밀려" in x.message for x in core.of("DEAD"))
    FAMILY["prio_k1"] += len(core.of("K1"))


def test_core_analysis_reports_a_removable_root_and_scales():
    """뿌리가 빠지는 변이(K0)를 알리고, 변이를 열거할 수 없는 크기에서도 답한다."""
    d = {"ses": "1.0", "name": "R",
         "entities": {"R": {"root": True, "specializations": {"s": {"alternatives": ["A", "Gone"]}},
                            "multi_aspects": {"m": {"part": "Leaf", "cardinality": {"min": 1, "max": 300}}}},
                      "A": {"extends": "R"}, "Gone": {"extends": "R", "stereotype": "void"},
                      "Leaf": {"specializations": {"k": {"alternatives": ["K0", "K1", "K2"]}}},
                      "K0": {"extends": "Leaf"}, "K1": {"extends": "Leaf"}, "K2": {"extends": "Leaf"}},
         "constraints": [{"name": "c", "forbid": {"selected": "Leaf/k=K2"}}]}
    a = analyze(E.from_dict(d))
    assert a.variants is None and a.of("LIMIT")
    assert a.core.variants == sum(2 ** n for n in range(1, 301)) + 1 and a.core.wellformed == a.core.variants - 1
    assert [x.code for x in a.errors] == ["K0"]
    # 뿌리의 대안 Gone 은 변이에는 나타나지만 적격인 변이에는 없다. K2 는 제약 때문에 어디에도 없다
    assert [(x.data["owner"], x.data["option"], x.data["in_some_variant"]) for x in a.of("DEAD")] == \
        [("R", "Gone", True), ("Leaf", "K2", False)]


def test_core_sample_is_not_vacuous():
    if not FAMILY["core_docs"]:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert FAMILY["core_docs"] == 200 and FAMILY["core_errors"] >= 40 and FAMILY["core_dead"] >= 60, FAMILY
    assert FAMILY["prio_docs"] >= 80 and FAMILY["prio_pushed_dead"] >= 10 and FAMILY["prio_k1"] >= 20, FAMILY


def test_limits_and_empty_families():
    m, ed, _ = open_doc(PROCESSING)
    a = analyze(m, max_variants=10)
    assert [(d.severity, d.code) for d in a.diagnostics] == [("info", "LIMIT")]
    assert a.variants is None and a.layered is not None
    assert (a.core.variants, a.core.wellformed) == (15, 15)      # 열거하지 않고 센 핵의 수
    doc = m.get(m.root)
    ed.set(doc.id, "constraints", [{"name": "불가능", "require": {"var": "num_servers", "gt": 99}}])
    a = analyze(m)
    assert [(d.severity, d.code) for d in a.diagnostics] == [("error", "EMPTY")]
    assert (a.variants, a.wellformed) == (0, 0)


def test_no_wellformed_variant_is_reported_once():
    d = {"ses": "1.0", "name": "R", "entities": {
        "R": {"root": True, "aspects": {"a": {"parts": ["X"]}},
              "specializations": {"s": {"alternatives": ["R1"]}}},
        "R1": {"extends": "R", "aspects": {"b": {"parts": ["X"]}}},
        "X": {}}}
    a = analyze(E.from_dict(d))
    assert (a.variants, a.wellformed) == (1, 0)
    assert [(x.code, x.address, x.affected) for x in a.errors] == [("K1", "entities/R", (1, 1)), ("NOWF", "", None)]
    assert a.errors[0].cause == {"decisions": "1.0"}        # 모든 변이에서 생기므로 원인이 되는 결정이 없다
    assert all(not p.active for p in a.table)


# ---------------------------------------------------------------------------
# 견고성: 어떤 상태의 문서에도 예외 없이 답한다
# ---------------------------------------------------------------------------

ROBUST: collections.Counter = collections.Counter()


def check_analysis(m, profile):
    a = analyze(m, profile, max_variants=400)
    for d in a.diagnostics:
        assert d.severity in ("error", "warning", "info")
        if d.element is not None:
            assert d.element in m.elements and m.find(d.address) == d.element
        assert all(r in m.elements for r in d.related)
    failed = bool(a.of("LOAD") or a.of("ANALYZE"))          # 엄격한 경로가 받지 못한 문서. 진단으로 보고되었다
    blocking = any(d.blocking for d in a.diagnostics)
    if not failed:
        assert (a.variants is None) == (blocking or bool(a.of("LIMIT")))
    if a.variants is not None and not failed:               # 분석이 되었다면 엄격한 경로와 같은 답이다
        L = unfold_layered(load_ses_dict(E.to_dict(m)), profile)
        assert a.variants == len(sem(L.ses))
    ROBUST["analyzed" if a.variants is not None and not failed else "blocked"] += 1
    for d in a.diagnostics:
        ROBUST[d.code] += 1
    return a


@pytest.mark.parametrize("seed", range(250))
def test_analysis_never_raises_on_damaged_documents(seed):
    rng = random.Random(seed)
    d = damage(rng, raw(DOCS[seed % len(DOCS)]))
    m = E.from_dict(d)
    profile = profile_of(raw(DOCS[seed % len(DOCS)]))
    check_analysis(m, profile)


@pytest.mark.parametrize("seed", range(100))
def test_analysis_never_raises_during_editing(seed):
    rng = random.Random(500 + seed)
    path = DOCS[seed % len(DOCS)]
    m, ed, profile = open_doc(path)
    for step in range(25):
        try:
            rand_command(rng, ed)
        except EditError:
            pass
        if step % 5 == 4:
            check_analysis(m, profile)
    while ed.undo() is not None:
        pass
    a = check_analysis(m, profile)                          # 처음으로 돌아가면 진단도 처음과 같다
    assert a.diagnostics == analyze(open_doc(path)[0], profile, max_variants=400).diagnostics


@pytest.mark.parametrize("seed", range(20 * len(DOCS)))          # 문서마다 편집 세션 20개
def test_no_diagnostics_means_the_strict_tools_accept(seed):
    """문서 범위의 진단이 하나도 없으면 정준 문서로 쓸 수 있고, 적재기와 스키마가 받아들인다."""
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(ROOT, "schema", "ses.schema.json"), encoding="utf-8") as f:
        validator = jsonschema.Draft202012Validator(json.load(f))
    rng = random.Random(3000 + seed)
    m, ed, profile = open_doc(DOCS[seed % len(DOCS)])
    for _ in range(12):
        try:
            rand_command(rng, ed)
        except EditError:
            pass
        found = [d for d in check_document(m, profile) if d.code != "UNUSED"]
        if found:
            ROBUST["with_diagnostics"] += 1
            continue
        d = E.to_dict(m)
        load_ses_dict(d)
        assert list(validator.iter_errors(d)) == []
        ROBUST["clean"] += 1


def test_robustness_sample_is_not_vacuous():
    if not ROBUST:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert ROBUST["analyzed"] >= 150 and ROBUST["blocked"] >= 250, ROBUST
    assert ROBUST["clean"] >= 150 and ROBUST["with_diagnostics"] >= 500, ROBUST
    for code in ("REF", "ROOT", "MISS", "DUP", "VAR", "EXT", "UNUSED", "LOAD", "SKIP"):
        assert ROBUST[code] >= 5, (code, ROBUST)


# ---------------------------------------------------------------------------
# 팔레트: 편집기가 내놓는 것과 검사가 받아들이는 것이 같다
# ---------------------------------------------------------------------------

def test_palette_carries_the_display_hints():
    profile = load_profile(os.path.join(ROOT, "domains", "curriculum.profile.yaml"))
    unit = profile.kinds["단원"]
    assert (unit.title, unit.ui) == ("단원", {"icon": "book", "color": "#4477aa"})
    assert profile.kinds["영역"].title is None and profile.kinds["영역"].ui == {}
    pal = profile.palette("단원")
    assert list(pal["fields"]) == ["시수", "수준"]
    assert pal["fields"]["시수"].title == "수업 시수"
    assert pal["fields"]["시수"].ui == {"unit": "시간", "widget": "number", "min": 1}
    assert profile.links["선수"].title == "선수 단원" and profile.links["선수"].ui == {"line": "dashed"}
    assert profile.palette("과정")["parts"] == ["영역", "성취기준", "평가"]
    assert profile.palette("단원")["links_out"] == ["선수", "달성"]
    assert profile.palette("성취기준")["links_in"] == ["달성", "평가함"]
    assert profile.palette(None)["parts"] == list(profile.kinds)


@pytest.mark.parametrize("name", ["curriculum", "rfp", "paper"])
def test_palette_agrees_with_the_checks(name):
    profile = load_profile(os.path.join(ROOT, "domains", name + ".profile.yaml"))
    kinds = list(profile.kinds)
    checked = collections.Counter()
    for parent in kinds:                                    # 포함: 팔레트에 있는 유형만 오류 없이 담긴다
        for child in kinds:
            m = E.new_document("문서", profile=name)
            ed = Editor(m)
            p = ed.add_entity("부모", kind=parent, root=True)
            c = ed.add_entity("자식", kind=child)
            ed.add_part(ed.add_aspect(p, "구성"), c)
            flagged = any(d.code == "T2" for d in check_document(m, profile))
            assert flagged == (child not in profile.palette(parent)["parts"])
            checked["T2" if flagged else "ok"] += 1
    for link in profile.links:                              # 관계: 양쪽 팔레트에 모두 있어야 한다
        for src in kinds:
            for dst in kinds:
                m = E.new_document("문서", profile=name)
                ed = Editor(m)
                a = ed.add_entity("출발", kind=src, root=True)
                b = ed.add_entity("도착", kind=dst)
                ed.add_link(a, link, b)
                flagged = any(d.code == "L2" for d in check_document(m, profile))
                offered = link in profile.palette(src)["links_out"] and link in profile.palette(dst)["links_in"]
                assert flagged == (not offered)
                checked["L2" if flagged else "ok"] += 1
    for kind in kinds:                                      # 필드: 폼에 있는 필드만 받아들여진다
        m = E.new_document("문서", profile=name)
        ed = Editor(m)
        e = ed.add_entity("하나", kind=kind, root=True)
        ed.set_field(e, "폼에없는필드", 1)
        for fname in profile.palette(kind)["fields"]:
            ed.set_field(e, fname, None)
        found = check_document(m, profile)
        assert [d.path for d in found if d.code == "F1"] == [("fields", "폼에없는필드")]
    assert checked["T2"] >= 1 and checked["L2"] >= 10 and checked["ok"] >= 10


def test_coupling_check_sees_inherited_ports():
    m, ed, _ = open_doc(PROCESSING)
    part = next(p.id for p in m.of_type("part") if m.label(p.id) == "Buffer")
    with ed.history.transaction("대안을 직접 부분으로"):       # Buffer 자리에 그 대안을 같은 이름으로 둔다
        ed.relink(part, "def", ent(m, "FifoBuffer"))
        ed.set_alias(part, "Buffer")
    assert check_document(m, unused=False) == []            # 포트는 Buffer에서 물려받은 것이다
    load_ses_dict(E.to_dict(m))
    ports = m.get(ent(m, "Buffer")).props["ports"]
    ed.set(ent(m, "Buffer"), "ports", {k: v for k, v in ports.items() if k != "ack"})
    found = [(d.code, d.path, d.data) for d in check_document(m, unused=False)]
    assert found == [("COUP", ("couplings", 3, "to"), {"part": "Buffer", "port": "ack"})]


def test_shared_definitions_do_not_blow_up_the_hierarchy_check():
    """같은 정의를 여러 곳에서 쓰는 깊은 문서에서도 문서 범위 검사가 금방 끝난다."""
    import time
    depth = 40                                              # 경로의 수는 2의 40제곱이다
    entities = {"L0": {"root": True}}
    for i in range(depth):
        entities[f"L{i}"].update({"aspects": {"a": {"parts": [f"L{i + 1}", {"def": f"L{i + 1}", "alias": "again"}]}}})
        entities[f"L{i + 1}"] = {}
    m = E.from_dict({"ses": "1.0", "name": "L0", "entities": entities})
    started = time.time()
    assert check_document(m) == []
    assert time.time() - started < 5
    # 펼친 나무는 3 곱하기 2의 40제곱쯤 된다. 펼치지 않고 세고, 분석은 시작하지 않는다
    assert unfolded_size(m, cap=10 ** 15) == 3 * 2 ** depth - 2
    assert unfolded_size(m, cap=1000) == 1000                 # 상한을 넘으면 상한을 돌려준다
    a = analyze(m)
    assert [(d.severity, d.code) for d in a.diagnostics] == [("info", "LIMIT")] and a.variants is None
    assert time.time() - started < 5
    m.apply(Insert("p900", "part", m.by_name("aspect", "a")[-1], "parts", 0, {"def": Ref(m.entity("L3"), None)}))
    found = check_document(m)
    assert [(d.code, d.element) for d in found] == [("CYCLE", "p900")]
    assert "L3/" in found[0].message and found[0].message.endswith("/L3")


SIZE: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(150))
def test_unfolded_size_is_counted_without_unfolding(seed):
    if seed < len(PLAIN):
        d = raw(PLAIN[seed])
    else:
        d = rand_document(random.Random(seed))
    L = unfold_layered(load_ses_dict(d), profile_of(d))
    markers = [n for n in L.ses.tree.nodes if n[-1] in MARKERS]          # 어림은 펼침이 붙인 표시를 세지 않는다
    assert unfolded_size(E.from_dict(d)) == len(L.ses.tree.nodes) - len(markers)
    SIZE["docs_with_markers"] += bool(markers)


def test_size_sample_is_not_vacuous():
    if not SIZE:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert SIZE["docs_with_markers"] >= 10, SIZE


def test_very_deep_document_gets_a_diagnostic_not_a_crash():
    depth = 3000
    entities = {"L0": {"root": True}}
    for i in range(depth):
        entities[f"L{i}"].update({"aspects": {"a": {"parts": [f"L{i + 1}"]}}})
        entities[f"L{i + 1}"] = {}
    m = E.from_dict({"ses": "1.0", "name": "L0", "entities": entities})
    a = analyze(m)
    assert [d.code for d in a.diagnostics if d.code != "UNUSED"] == ["DEPTH", "SKIP"]


def test_undo_is_refused_inside_a_transaction():
    m, ed, _ = open_doc(PROCESSING)
    ed.add_entity("X")
    with ed.history.transaction("묶음"):
        ed.add_entity("Y")
        with pytest.raises(EditError):
            ed.undo()
    assert ed.undo() == "묶음" and m.entity("Y") is None and m.entity("X") is not None
