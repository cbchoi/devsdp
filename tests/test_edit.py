"""편집 모델: 식별자 기반 요소 저장소, 원시 연산과 역연산, 이력, 정준 문서와의 왕복
(docs/ses-platform/13_editor_data_model.md).
"""

import collections
import copy
import glob
import json
import os
import random
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ses_core import LoadError, load_ses_dict  # noqa: E402
from ses_core import edit as E  # noqa: E402
from ses_core.algebra import sem  # noqa: E402
from ses_core.edit import (  # noqa: E402
    MISSING, EditError, Editor, Insert, Model, Move, Ref, Remove, Set, op_from_json, op_to_json)
from ses_core.extension import ill_formed  # noqa: E402
from ses_core.profile import load_profile  # noqa: E402
from ses_core.unfold import unfold_layered  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform")
DOCS = sorted(glob.glob(os.path.join(ROOT, "examples", "*.ses.yaml"))
              + glob.glob(os.path.join(ROOT, "domains", "*.ses.yaml")))
PROCESSING = os.path.join(ROOT, "examples", "processing_system.ses.yaml")
CURRICULUM = os.path.join(ROOT, "domains", "curriculum_intro_programming.ses.yaml")
NAMED = ("entity", "variable", "aspect", "multi_aspect", "specialization")


def raw(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ordered(x) -> str:
    """열쇠의 순서까지 비교하기 위한 문자열."""
    return json.dumps(x, ensure_ascii=False)


def canon(d):
    return E.to_dict(E.from_dict(d))


def state(m) -> str:
    """저장소의 상태. 사상의 열쇠 순서까지 본다."""
    return ordered(m.snapshot())


def ident(path) -> str:
    return os.path.basename(path)


def test_there_are_documents_to_test():
    assert len(DOCS) == 5


# ---------------------------------------------------------------------------
# 정준 문서와의 왕복
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", DOCS, ids=ident)
def test_round_trip_is_exact_for_repository_documents(path):
    d = raw(path)
    m = E.from_dict(d)
    assert m.import_issues == []
    assert m.check_invariants() == []
    assert ordered(E.to_dict(m)) == ordered(d)             # 내용과 열쇠 순서가 모두 같다
    assert ordered(yaml.safe_load(E.dump(m))) == ordered(d)


@pytest.mark.parametrize("path", DOCS, ids=ident)
def test_snapshot_survives_json(path):
    m = E.from_dict(raw(path))
    snap = m.snapshot()
    again = Model.from_snapshot(json.loads(json.dumps(snap, ensure_ascii=False)))
    assert ordered(again.snapshot()) == ordered(snap)
    assert again.check_invariants() == []
    assert ordered(E.to_dict(again)) == ordered(E.to_dict(m))


def test_every_name_is_written_once_and_references_are_identifiers():
    """정준 문서에서 다섯 번 적히는 이름이 편집 모델에서는 한 번만 적힌다."""
    d = raw(CURRICULUM)
    assert ordered(d).count('"함수"') == 5
    m = E.from_dict(d)
    assert ordered(m.snapshot()).count('"함수"') == 1
    assert len(m.refs_to(m.entity("함수"))) == 4


def test_snapshot_that_breaks_the_invariants_is_rejected():
    snap = E.from_dict(raw(PROCESSING)).snapshot()
    broken = copy.deepcopy(snap)
    victim = next(i for i, e in broken["elements"].items() if e["type"] == "part")
    broken["elements"][victim]["parent"] = broken["root"]
    with pytest.raises(EditError):
        Model.from_snapshot(broken)
    broken = copy.deepcopy(snap)
    broken["elements"][victim]["props"]["def"] = {"$ref": "nowhere", "name": None}
    with pytest.raises(EditError):
        Model.from_snapshot(broken)
    with pytest.raises(EditError):
        Model.from_snapshot(dict(snap, format="other"))


# ---------------------------------------------------------------------------
# 불완전하거나 틀린 문서
# ---------------------------------------------------------------------------

INCOMPLETE = [
    {},
    {"ses": "1.0", "name": "x", "entities": {}},
    {"entities": {"A": None}},
    {"entities": {"A": {"aspects": {"a": None}}}},
    {"entities": {"A": {"aspects": {"a": {"parts": ["B", "없는것"]}}}}},
    {"entities": {"A": {"root": True}, "B": {"root": True, "extends": "B"}}},
    {"entities": {"A": {"specializations": {"s": {"alternatives": ["X"], "default": "Y"}}}}},
    {"entities": {"A": {"multi_aspects": {"m": {}}}, "B": {"links": {"선수": ["A", "Z"]}}}},
    {"entities": {"A": {"extends": 3, "aspects": {"a": {"parts": [{"alias": "y"}, 7]}}}}},
]

MISSHAPED = [
    (None, False), ([], True), ("x", True),
    ({"entities": []}, True), ({"variables": 3}, True),
    ({"entities": {"A": 5}}, True),
    ({"entities": {"A": {"aspects": []}}}, True),
    ({"entities": {"A": {"aspects": {"a": {"parts": "B"}}}}}, True),
    ({"entities": {"A": {"links": {"t": "B"}}}}, True),
    ({"entities": {"A": {"specializations": {"s": {"alternatives": {"x": 1}}}}}}, True),
]


@pytest.mark.parametrize("d", INCOMPLETE, ids=range(len(INCOMPLETE)))
def test_incomplete_documents_are_held_as_they_are(d):
    m = E.from_dict(d)                                     # 예외가 없다
    assert m.import_issues == []
    assert m.check_invariants() == []
    c = E.to_dict(m)
    assert ordered(canon(c)) == ordered(c)                 # 저장하고 다시 열어도 같다
    assert not (scalars(d) - scalars(c))                   # 적힌 값이 사라지지 않는다


@pytest.mark.parametrize("d, has_issue", MISSHAPED, ids=range(len(MISSHAPED)))
def test_misshaped_input_is_reported_not_dropped_silently(d, has_issue):
    m = E.from_dict(d)
    assert m.check_invariants() == []
    assert bool(m.import_issues) == has_issue


def scalars(x) -> collections.Counter:
    """문서에 적힌 값들(사상의 값과 목록의 항목). None은 뺀다."""
    out: collections.Counter = collections.Counter()

    def walk(v):
        if isinstance(v, dict):
            for item in v.values():
                walk(item)
        elif isinstance(v, list):
            for item in v:
                walk(item)
        elif v is not None:
            out[(type(v).__name__, v)] += 1

    walk(x)
    return out


JUNK = [None, [], {}, 3, "잡음", [1], {"k": 1}, True, ["x", {"def": "y"}]]


def damage(rng, d):
    """문서의 임의의 자리를 지우거나 엉뚱한 값으로 바꾼다."""
    d = copy.deepcopy(d)
    spots = []

    def walk(v):
        if isinstance(v, dict):
            for k in v:
                spots.append((v, k))
                walk(v[k])
        elif isinstance(v, list):
            for i in range(len(v)):
                spots.append((v, i))
                walk(v[i])

    walk(d)
    for _ in range(rng.randint(1, 3)):
        container, key = rng.choice(spots)
        try:
            if rng.random() < 0.3 and isinstance(container, dict):
                del container[key]
            else:
                container[key] = copy.deepcopy(rng.choice(JUNK))
        except (KeyError, IndexError):
            pass
    return d


@pytest.mark.parametrize("seed", range(300))
def test_import_never_fails_on_damaged_documents(seed):
    rng = random.Random(seed)
    d = damage(rng, raw(DOCS[seed % len(DOCS)]))
    m = E.from_dict(d)                                     # 무엇이 들어와도 예외가 없다
    assert m.check_invariants() == []
    try:
        c = E.to_dict(m)
    except EditError:
        return                                             # 이름이 열쇠가 될 수 없는 상태. 스냅숏으로만 저장된다
    assert ordered(canon(c)) == ordered(c)
    if not m.import_issues:
        assert not (scalars(d) - scalars(c))


def test_damaged_sample_is_not_vacuous():
    issues = clean = 0
    for seed in range(300):
        m = E.from_dict(damage(random.Random(seed), raw(DOCS[seed % len(DOCS)])))
        issues += bool(m.import_issues)
        clean += not m.import_issues
    assert issues >= 30 and clean >= 100


# ---------------------------------------------------------------------------
# 원시 연산: 역연산과 원자성
# ---------------------------------------------------------------------------

def rand_value(rng, m):
    ids = list(m.elements)
    return rng.choice([1, 1.0, True, "글", None, [1, 2], {"a": 1}, {"a": {"b": [3]}},
                       Ref(rng.choice(ids), None), Ref(None, "어딘가"), Ref("없는식별자", None), MISSING])


def rand_path(rng, m, el):
    keys = list(el.props) + list(E.TYPES[el.type].refs) + ["새속성", "fields"]
    path = [rng.choice(keys)]
    cur = el.props.get(path[0])
    while isinstance(cur, (dict, list)) and cur and rng.random() < 0.6:
        key = rng.choice(list(cur)) if isinstance(cur, dict) else rng.randrange(len(cur) + 1)
        path.append(key)
        cur = (cur.get(key) if isinstance(cur, dict)
               else cur[key] if key < len(cur) else None)
    if rng.random() < 0.2:
        path.append("새열쇠")
    return tuple(path)


def rand_op(rng, m):
    ids = list(m.elements)
    kind = rng.choice(["insert", "insert", "remove", "set", "set", "move", "move"])
    if kind == "insert":
        parent = m.get(rng.choice(ids))
        roles = list(E.TYPES[parent.type].roles)
        role = rng.choice(roles + ["없는역할"]) if roles else "없는역할"
        allowed = E.TYPES[parent.type].roles.get(role, ())
        type = rng.choice(list(allowed) * 4 + list(E.TYPES)) if allowed else rng.choice(list(E.TYPES))
        props = {"name": rng.choice(["가", "나", "다"])} if E.TYPES[type].named else {}
        for prop in E.TYPES[type].refs:
            if rng.random() < 0.7:
                props[prop] = rand_value(rng, m)
        id = rng.choice(ids) if rng.random() < 0.05 else m.new_id(type)
        return Insert(id, type, parent.id, role, rng.randint(0, len(parent.children.get(role, [])) + 1), props)
    if kind == "remove":
        return Remove(rng.choice(ids))
    if kind == "set":
        el = m.get(rng.choice(ids))
        path = rand_path(rng, m, el)
        old = E._get_in(el.props, path) if rng.random() < 0.9 else "틀린옛값"
        return Set(el.id, path, old, rand_value(rng, m))
    el = m.get(rng.choice(ids))
    target = m.get(rng.choice(ids))
    roles = list(E.TYPES[target.type].roles)
    role = el.role if el.role in roles and rng.random() < 0.8 else rng.choice(roles + ["없는역할"])
    return Move(el.id, target.id, role, rng.randint(0, len(target.children.get(role, [])) + 1))


def through_json(op):
    return op_from_json(json.loads(json.dumps(op_to_json(op), ensure_ascii=False)))


OP_STATS: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(150))
def test_primitive_operations_are_invertible_and_atomic(seed):
    rng = random.Random(seed)
    m = E.from_dict(raw(DOCS[seed % len(DOCS)]))
    for _ in range(60):
        op = rand_op(rng, m)
        before = state(m)
        try:
            inverse = m.apply(op)
        except EditError:
            assert state(m) == before                  # 실패한 연산은 흔적을 남기지 않는다
            assert m.check_invariants() == []
            OP_STATS[type(op).__name__, "rejected"] += 1
            continue
        after = state(m)
        assert m.check_invariants() == []                  # 구조 불변식과 역참조 색인
        assert through_json(op) == op and through_json(inverse) == inverse
        again = m.apply(inverse)
        assert state(m) == before                      # 역연산은 정확히 되돌린다
        m.apply(through_json(again))
        assert state(m) == after                       # 역연산의 역연산은 원래 연산이다
        OP_STATS[type(op).__name__, "applied"] += 1


def test_primitive_operation_sample_is_not_vacuous():
    if not OP_STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    for kind in ("Insert", "Remove", "Set", "Move"):
        assert OP_STATS[kind, "applied"] >= 100, OP_STATS
        assert OP_STATS[kind, "rejected"] >= 100, OP_STATS


def test_store_keeps_structure_but_not_meaning():
    m = E.from_dict(raw(PROCESSING))
    server, buffer = m.entity("Server"), m.entity("Buffer")
    aspect = m.of_type("aspect")[0].id
    part = m.of_type("part")[0].id
    with pytest.raises(EditError):                         # 유형이 맞지 않는 자리
        m.apply(Insert("x1", "entity", aspect, "parts", 0, {"name": "E"}))
    with pytest.raises(EditError):                         # 없는 대상을 가리키는 참조
        m.apply(Set(part, ("def",), m.get(part).props["def"], Ref("nowhere", None)))
    with pytest.raises(EditError):                         # 엔티티가 아닌 것을 가리키는 참조
        m.apply(Set(part, ("def",), m.get(part).props["def"], Ref(aspect, None)))
    with pytest.raises(EditError):                         # 참조 자리에 글자
        m.apply(Set(part, ("def",), m.get(part).props["def"], "Server"))
    with pytest.raises(EditError):                         # 가리키는 참조가 남은 요소
        m.apply(Remove(server))
    with pytest.raises(EditError):                         # 자식이 남은 요소
        m.apply(Remove(buffer))
    with pytest.raises(EditError):                         # 옛 값이 다르면 충돌
        m.apply(Set(server, ("name",), "Other", "S"))
    # 의미가 틀린 상태는 담는다: 뿌리 둘, 겹치는 이름, 끊어진 참조, 자기 자신을 extends
    m.apply(Set(server, ("root",), MISSING, True))
    m.apply(Insert("e99", "entity", m.root, "entities", 0, {"name": "Buffer"}))
    m.apply(Set(part, ("def",), m.get(part).props["def"], Ref(None, "없는엔티티")))
    m.apply(Set(server, ("extends",), MISSING, Ref(server, None)))
    assert m.check_invariants() == []
    with pytest.raises(EditError):                         # 이름이 겹치면 정준 문서로는 쓸 수 없다
        E.to_dict(m)
    assert state(Model.from_snapshot(m.snapshot())) == state(m)             # 스냅숏으로는 저장된다


def test_values_are_compared_as_json_values():
    m = E.from_dict({"entities": {"A": {"fields": {"x": 1, "y": 0}}}})
    ed = Editor(m)
    a = m.entity("A")
    ed.set(a, ("fields", "x"), True)                       # 1과 True는 다른 값이다
    assert m.get(a).props["fields"]["x"] is True
    ed.set(a, ("fields", "x"), 1.0)
    assert isinstance(m.get(a).props["fields"]["x"], float)
    n = len(ed.history.undo_stack)
    ed.set(a, ("fields", "x"), 1.0)                        # 같은 값이면 아무 일도 없다
    assert len(ed.history.undo_stack) == n
    ed.set(a, "fields", {"y": 0, "x": 1.0})                # 열쇠의 순서도 내용이다
    assert list(m.get(a).props["fields"]) == ["y", "x"]


# ---------------------------------------------------------------------------
# 명령과 이력: 무작위 편집 세션
# ---------------------------------------------------------------------------

POOL = ["가", "나", "다", "라", "마", "Alpha", "Beta", "새_요소"]


def rand_command(rng, ed):
    """무작위 명령 하나. 거절될 수 있다(EditError)."""
    m = ed.model

    def pick(*types):
        xs = [el for t in types for el in m.of_type(t)]
        if not xs:
            raise EditError("고를 요소가 없다")
        return rng.choice(xs).id

    def name():
        existing = [el.props.get("name") for el in m.all() if isinstance(el.props.get("name"), str)]
        return rng.choice(POOL + existing[:6]) + rng.choice(["", "", str(rng.randint(0, 99))])

    c = rng.randrange(22)
    if c == 0:
        ed.add_entity(name(), kind=rng.choice([None, "단원", "영역"]))
    elif c == 1:
        ed.rename(pick(*NAMED), name())
    elif c == 2:
        ed.remove(pick("entity", "aspect", "part", "multi_aspect", "specialization",
                       "alternative", "link", "variable"), cascade=rng.random() < 0.5)
    elif c == 3:
        ed.add_aspect(pick("entity"), name())
    elif c == 4:
        ed.add_part(pick("aspect"), pick("entity"), alias=rng.choice([None, None, name()]))
    elif c == 5:
        ed.add_multi_aspect(pick("entity"), name(), pick("entity"),
                            rng.choice([2, {"min": 1, "max": 3}, {"var": "n"}]))
    elif c == 6:
        ed.add_specialization(pick("entity"), name())
    elif c == 7:
        ed.add_alternative(pick("specialization"), pick("entity"), set_extends=rng.random() < 0.7)
    elif c == 8:
        ed.make_optional(pick("entity"), spec_name=name())
    elif c == 9:
        ed.move(pick("part"), pick("aspect"))
    elif c == 10:
        ed.move(pick("aspect", "multi_aspect", "specialization"), pick("entity"))
    elif c == 11:
        id = pick("entity", "part", "aspect", "alternative", "link")
        el = m.get(id)
        ed.reorder(id, rng.randrange(len(m.get(el.parent).children[el.role])))
    elif c == 12:
        ed.set_kind(pick("entity"), rng.choice([None, "단원", "평가"]))
    elif c == 13:
        ed.set_field(pick("entity"), rng.choice(["시수", "코드", "비중"]), rng.choice([3, "P-9", 40, True]))
    elif c == 14:
        ed.remove_field(pick("entity"), rng.choice(["시수", "코드", "비중"]))
    elif c == 15:
        ed.add_link(pick("entity"), rng.choice(["선수", "달성"]), pick("entity"))
    elif c == 16:
        id = pick("part", "alternative", "link", "multi_aspect")
        prop = next(iter(E.TYPES[m.get(id).type].refs))
        ed.relink(id, prop, pick("entity"))
    elif c == 17:
        ed.set_alias(pick("part"), rng.choice([None, name()]))
    elif c == 18:
        ed.duplicate(pick("entity"), name())
    elif c == 19:
        ed.set_root(pick("entity"))
    elif c == 20:
        ed.add_variable(name(), {"type": "int", "range": [1, 3]})
    else:
        ed.reconnect()


SESSION_STATS: collections.Counter = collections.Counter()


@pytest.mark.parametrize("seed", range(120))
def test_sessions_undo_redo_and_replay(seed):
    rng = random.Random(1000 + seed)
    start = raw(DOCS[seed % len(DOCS)])
    m = E.from_dict(start)
    ed = Editor(m)
    initial = m.snapshot()
    timeline, pos = [state(m)], 0
    for _ in range(40):
        r = rng.random()
        if r < 0.15:
            label = ed.undo()
            assert (label is None) == (pos == 0)
            pos = max(pos - 1, 0)
            SESSION_STATS["undo"] += label is not None
        elif r < 0.25:
            label = ed.redo()
            assert (label is None) == (pos == len(timeline) - 1)
            pos = min(pos + 1, len(timeline) - 1)
            SESSION_STATS["redo"] += label is not None
        else:
            before, depth = state(m), len(ed.history.undo_stack)
            try:
                rand_command(rng, ed)
            except EditError:
                assert state(m) == before              # 거절된 명령은 전체가 되돌려진다
                assert len(ed.history.undo_stack) == depth
                SESSION_STATS["rejected"] += 1
            else:
                if len(ed.history.undo_stack) > depth:     # 명령 하나는 되돌리기 한 단계다
                    assert len(ed.history.undo_stack) == depth + 1
                    timeline = timeline[:pos + 1] + [state(m)]
                    pos += 1
                    SESSION_STATS["applied"] += 1
                else:
                    assert state(m) == before          # 바뀐 것이 없으면 이력에 남지 않는다
                    SESSION_STATS["noop"] += 1
        assert state(m) == timeline[pos]
        assert m.check_invariants() == []

    final = state(m)
    replay = Model.from_snapshot(initial)                  # 변경 이력을 다른 저장소에 재생한다
    for entry in json.loads(json.dumps(ed.history.log(), ensure_ascii=False)):
        for op in entry["ops"]:
            replay.apply(op_from_json(op))
    assert state(replay) == final

    try:                                                   # 저장하고 다시 열어도 같다
        c = E.to_dict(m)
    except EditError:
        SESSION_STATS["unsavable"] += 1
    else:
        reopened = E.from_dict(c)
        assert reopened.import_issues == []
        assert ordered(E.to_dict(reopened)) == ordered(c)
        SESSION_STATS["saved"] += 1

    while ed.undo() is not None:                           # 끝까지 되돌리면 처음과 같다
        pass
    assert state(m) == timeline[0]
    assert ordered(E.to_dict(m)) == ordered(start)
    while ed.redo() is not None:                           # 끝까지 다시 하면 가장 나중 상태다
        pass
    assert state(m) == timeline[-1]


def test_session_sample_is_not_vacuous():
    if not SESSION_STATS:
        pytest.skip("앞의 시험과 함께 실행할 때만 센다")
    assert SESSION_STATS["applied"] >= 1500, SESSION_STATS
    assert SESSION_STATS["rejected"] >= 200, SESSION_STATS
    assert SESSION_STATS["undo"] >= 200 and SESSION_STATS["redo"] >= 50, SESSION_STATS
    assert SESSION_STATS["saved"] >= 80, SESSION_STATS


def test_failed_command_rolls_back_the_whole_transaction():
    m = E.from_dict(raw(CURRICULUM))
    ed = Editor(m)
    ed.add_entity("함수_제외")                              # make_optional이 만들 이름을 먼저 차지한다
    before = state(m)
    with pytest.raises(EditError):
        ed.make_optional(m.entity("함수"))                  # specialization과 엔티티 하나를 만든 뒤 실패한다
    assert state(m) == before
    assert len(ed.history.undo_stack) == 1


# ---------------------------------------------------------------------------
# 이름 바꾸기: 뜻이 보존된다
# ---------------------------------------------------------------------------

def analysis(d):
    """문서의 분석 결과 요약: 변이 수, 적격이 아닌 변이 수, 위반 부호별 건수."""
    doc = load_ses_dict(d)
    profile = None
    if d.get("profile"):
        profile = load_profile(os.path.join(ROOT, "domains", d["profile"] + ".profile.yaml"))
    L = unfold_layered(doc, profile)
    bad = ill_formed(L)
    counts = collections.Counter(code for _, vs in bad for _, code, _, _ in vs)
    return len(sem(L.ses)), len(bad), sorted(counts.items())


@pytest.mark.parametrize("path", DOCS, ids=ident)
def test_renaming_everything_preserves_the_analysis(path):
    d = raw(path)
    expected = analysis(d)
    m = E.from_dict(d)
    ed = Editor(m)
    targets = [el.id for el in m.all() if el.type in NAMED]
    assert targets
    for i, id in enumerate(targets):
        old = m.get(id).props["name"]
        result = ed.rename(id, f"이름_{i}")
        assert (result.type, result.old, result.new) == (m.get(id).type, old, f"이름_{i}")
    renamed = E.to_dict(m)
    assert not (set(_names(d)) & set(_names(renamed)))      # 옛 이름이 하나도 남지 않았다
    assert analysis(renamed) == expected                   # 적재되고, 분석 결과가 같다
    for _ in targets:
        ed.undo()
    assert ordered(E.to_dict(m)) == ordered(d)


def _names(d):
    out = list(d.get("variables") or {})
    for name, body in d["entities"].items():
        out.append(name)
        for key in ("aspects", "multi_aspects", "specializations"):
            out.extend(body.get(key) or {})
    return out


@pytest.mark.parametrize("path", DOCS, ids=ident)
def test_rename_and_back_is_identity(path):
    d = raw(path)
    m = E.from_dict(d)
    ed = Editor(m)
    for el in list(m.all()):
        if el.type in NAMED:
            old = el.props["name"]
            ed.rename(el.id, old + "_임시")
            ed.rename(el.id, old)
    assert ordered(E.to_dict(m)) == ordered(d)


def test_rename_rewrites_names_written_as_text():
    d = raw(PROCESSING)
    d["entities"]["ProcessingSystem"]["metadata"] = {"text": {"separators": {"pipelineDec": "\n"}}}
    m = E.from_dict(d)
    ed = Editor(m)
    ed.rename(m.entity("FifoBuffer"), "Fifo")
    ed.rename(m.entity("Generator"), "Source")
    ed.rename(m.entity("ProcessingSystem"), "Plant")
    ed.rename(m.by_name("variable", "policy")[0], "discipline")
    ed.rename(m.by_name("variable", "num_servers")[0], "servers")
    ed.rename(m.by_name("aspect", "pipelineDec")[0], "pipeline")
    out = E.to_dict(m)
    ents = out["entities"]
    assert ents["Buffer"]["specializations"]["policySpec"]["select"] == {
        "when": {"var": "discipline", "eq": "fifo"}, "then": "Fifo", "else": "PriorityBuffer"}
    assert ents["Plant"]["aspects"]["pipeline"]["couplings"][0] == {"from": "Source.out", "to": "Buffer.in"}
    assert ents["Plant"]["metadata"]["text"]["separators"] == {"pipeline": "\n"}
    assert ents["ServerPool"]["multi_aspects"]["serversMAsp"]["cardinality"] == {"var": "servers"}
    assert out["constraints"][0]["when"] == {"var": "discipline", "eq": "priority"}
    assert out["constraints"][0]["require"] == {"var": "servers", "ge": 2}
    assert out["experimental_frames"][0]["attach_to"] == "Plant"
    load_ses_dict(out)


def test_alias_change_rewrites_coupling_endpoints():
    m = E.from_dict(raw(PROCESSING))
    ed = Editor(m)
    part = next(p.id for p in m.of_type("part") if m.label(p.id) == "Buffer")
    ed.set_alias(part, "queue")
    out = E.to_dict(m)
    asp = out["entities"]["ProcessingSystem"]["aspects"]["pipelineDec"]
    assert {"def": "Buffer", "alias": "queue"} in asp["parts"]
    assert {"from": "Generator.out", "to": "queue.in"} in asp["couplings"]
    assert {"from": "ServerPool.done", "to": "queue.ack"} in asp["couplings"]
    load_ses_dict(out)
    ed.set_alias(part, None)
    assert ordered(E.to_dict(m)) == ordered(raw(PROCESSING))


# ---------------------------------------------------------------------------
# 지우기, 끊어진 참조, 다시 잇기
# ---------------------------------------------------------------------------

def test_remove_leaves_dangling_references_that_keep_the_name():
    d = raw(CURRICULUM)
    m = E.from_dict(d)
    ed = Editor(m)
    target = m.entity("함수")
    holders = m.refs_to(target)
    assert len(holders) == 4
    ed.remove(target)
    assert m.entity("함수") is None and m.refs_to(target) == []
    for holder, prop in holders:
        assert m.get(holder).props[prop] == Ref(None, "함수")      # 이름은 남는다
    saved = E.to_dict(m)
    assert "함수" in saved["entities"]["기초영역"]["aspects"]["단원구성"]["parts"]
    with pytest.raises(LoadError):                                 # 엄격한 적재기는 거부한다
        load_ses_dict(saved)
    again = ed.add_entity("함수", kind="단원")
    assert ed.reconnect() == 4
    assert sorted(m.refs_to(again)) == sorted(holders)
    ed.undo(), ed.undo(), ed.undo()
    assert ordered(E.to_dict(m)) == ordered(d)


def test_cascade_removes_the_uses():
    m = E.from_dict(raw(CURRICULUM))
    ed = Editor(m)
    before = len(m.elements)
    ed.remove(m.entity("함수"), cascade=True)
    out = E.to_dict(m)
    assert '"함수"' not in ordered(out)
    assert before - len(m.elements) == 1 + 2 + 4            # 엔티티, 자신의 관계 둘, 가리키던 부분 하나와 관계 셋
    load_ses_dict(out)
    ed.undo()
    assert ordered(E.to_dict(m)) == ordered(raw(CURRICULUM))


def test_commands_keep_names_unique():
    m = E.from_dict(raw(PROCESSING))
    ed = Editor(m)
    before = state(m)
    with pytest.raises(EditError):
        ed.add_entity("Buffer")
    with pytest.raises(EditError):
        ed.rename(m.entity("Server"), "Buffer")
    with pytest.raises(EditError):
        ed.add_variable("policy", {"type": "int"})
    with pytest.raises(EditError):                         # aspect, multi-aspect, specialization은 한 범위다
        ed.add_aspect(m.entity("ServerPool"), "serversMAsp")
    with pytest.raises(EditError):
        ed.add_entity("")
    assert state(m) == before and ed.history.undo_stack == []


def test_building_a_document_from_nothing():
    m = E.new_document("작은과정", profile="curriculum")
    ed = Editor(m)
    course = ed.add_entity("작은과정", kind="과정", root=True)
    area = ed.add_entity("영역1", kind="영역")
    unit = ed.add_entity("단원1", kind="단원")
    ed.set_field(unit, "시수", 30)
    ed.add_part(ed.add_aspect(course, "구성"), area)
    ed.add_part(ed.add_aspect(area, "단원구성"), unit)
    sid, yes, no = ed.make_optional(unit, "개설여부", "개설", "미개설")
    out = E.to_dict(m)
    assert out["entities"]["단원1"]["specializations"]["개설여부"]["alternatives"] == ["개설", "미개설"]
    assert out["entities"]["미개설"] == {"extends": "단원1", "stereotype": "void"}
    assert analysis(out)[0] == 2                           # 개설과 미개설, 두 변이
    assert len(ed.history.undo_stack) == 9


# ---------------------------------------------------------------------------
# 주소: 파일에 남기는 식별 수단
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", DOCS, ids=ident)
def test_addresses_identify_elements(path):
    m = E.from_dict(raw(path))
    addrs = m.addresses()
    assert len(set(addrs.values())) == len(addrs) == len(m.elements)
    for id, address in addrs.items():
        assert m.find(address) == id


def test_addresses_stay_unique_with_duplicate_names():
    m = E.from_dict(raw(PROCESSING))
    asp = m.of_type("aspect")[0].id
    m.apply(Insert("p90", "part", asp, "parts", 0, {"def": Ref(m.entity("Buffer"), None)}))
    m.apply(Insert("e90", "entity", m.root, "entities", 0, {"name": "Buffer"}))
    addrs = m.addresses()
    assert len(set(addrs.values())) == len(addrs)
    assert addrs["e90"] == "entities/Buffer#0"
    assert all(m.find(a) == i for i, a in addrs.items())


def test_rename_reports_the_address_changes():
    m = E.from_dict(raw(CURRICULUM))
    ed = Editor(m)
    result = ed.rename(m.entity("응용영역"), "응용")
    assert result.addresses["entities/응용영역"] == "entities/응용"
    assert result.addresses["entities/응용영역/aspects/웹트랙/parts/웹기초"] == "entities/응용/aspects/웹트랙/parts/웹기초"
    assert result.addresses["entities/프로그래밍입문/aspects/구성/parts/응용영역"] == \
        "entities/프로그래밍입문/aspects/구성/parts/응용"
    assert all(m.find(new) is not None for new in result.addresses.values())
    result = ed.rename(m.by_name("aspect", "웹트랙")[0], "웹")
    assert (result.type, result.owner) == ("aspect", "응용")
    assert set(result.addresses) == {"entities/응용/aspects/웹트랙", "entities/응용/aspects/웹트랙/parts/웹기초",
                                     "entities/응용/aspects/웹트랙/parts/웹프로젝트"}


# ---------------------------------------------------------------------------
# 변경 추적: 무엇을 다시 분석해야 하는가
# ---------------------------------------------------------------------------

def test_change_tracking_names_the_entities_to_reanalyse():
    m = E.from_dict(raw(CURRICULUM))
    ed = Editor(m)
    name = lambda ids: {m.get(i).props["name"] for i in ids}           # noqa: E731
    rev = m.revision
    assert m.changed_entities(rev) == set()
    ed.set_field(m.entity("웹기초"), "시수", 9)
    assert name(m.changed_entities(rev)) == {"웹기초"}
    assert name(m.dependents(m.changed_entities(rev))) == {"웹기초", "응용영역", "프로그래밍입문"}
    rev = m.revision
    ed.add_part(m.by_name("aspect", "웹트랙")[0], m.entity("실습"))
    assert name(m.changed_entities(rev)) == {"응용영역"}
    assert name(m.users(m.entity("실습"))) == {"응용영역", "실습영역"}
    assert name(m.dependents({m.entity("심화미개설")})) == {"심화미개설", "심화알고리즘", "기초영역", "프로그래밍입문"}
