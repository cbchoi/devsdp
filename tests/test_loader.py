"""예시 SES 를 적재하여 자료구조와 무결성 검사를 확인한다."""

import copy
import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ses_core import load_ses, load_ses_dict, LoadError  # noqa: E402
from ses_core import model as m  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform",
                       "examples", "processing_system.ses.yaml")


@pytest.fixture
def raw():
    with open(EXAMPLE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_load_example():
    doc = load_ses(EXAMPLE)
    assert doc.root.name == "ProcessingSystem"
    assert set(doc.entities) == {"ProcessingSystem", "Generator", "Buffer", "FifoBuffer",
                                 "PriorityBuffer", "ServerPool", "Server", "Collector"}
    assert doc.entities["Generator"].is_leaf
    assert not doc.entities["ServerPool"].is_leaf


def test_inheritance_and_contract():
    doc = load_ses(EXAMPLE)
    assert doc.ancestors("PriorityBuffer") == ("Buffer",)
    ports = doc.all_ports("PriorityBuffer")
    assert set(ports) == {"in", "ack", "out"}
    c = doc.contract("PriorityBuffer")
    assert set(c.parameters) == {"capacity", "levels"}
    assert c.ports["in"].type.fields["priority"] == m.ScalarType.INT
    assert c.ports["out"].direction == m.Direction.OUT


def test_expression_ast():
    doc = load_ses(EXAMPLE)
    sel = doc.entities["Buffer"].specializations["policySpec"].select
    assert isinstance(sel.when, m.Compare)
    assert sel.when == m.Compare("eq", m.Var("policy"), m.Const("fifo"))
    assert sel.then == "FifoBuffer" and sel.otherwise == "PriorityBuffer"
    cons = doc.constraints[0]
    assert cons.require == m.Compare("ge", m.Var("num_servers"), m.Const(2))


def test_multi_aspect_pattern():
    doc = load_ses(EXAMPLE)
    ma = doc.entities["ServerPool"].multi_aspects["serversMAsp"]
    assert ma.cardinality == m.VarCard("num_servers")
    assert ma.pattern.kind == m.PatternKind.FAN_OUT_FAN_IN
    assert str(ma.pattern.fan_out[0].dst) == "{part}.in"


def test_dangling_reference_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["entities"]["ProcessingSystem"]["aspects"]["pipelineDec"]["parts"].append("Ghost")
    with pytest.raises(LoadError, match="Ghost"):
        load_ses_dict(bad)


def test_port_type_mismatch_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["entities"]["ProcessingSystem"]["aspects"]["pipelineDec"]["couplings"].append(
        {"from": "ServerPool.done", "to": "Collector.in"})   # Ack 에서 Job 으로
    with pytest.raises(LoadError, match="포트 타입이 다르다"):
        load_ses_dict(bad)


def test_specialization_must_extend_parent(raw):
    bad = copy.deepcopy(raw)
    del bad["entities"]["FifoBuffer"]["extends"]
    with pytest.raises(LoadError, match="extends 하지 않는다"):
        load_ses_dict(bad)


def test_strict_hierarchy_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["entities"]["Server"]["aspects"] = {"selfDec": {"parts": ["ServerPool"]}}
    del bad["entities"]["Server"]["stereotype"]
    with pytest.raises(LoadError, match="strict hierarchy"):
        load_ses_dict(bad)


def test_two_roots_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["entities"]["Collector"]["root"] = True
    with pytest.raises(LoadError, match="root"):
        load_ses_dict(bad)


@pytest.mark.parametrize("card,var", [
    ({"min": 1, "max": 0}, None), ({"min": -1, "max": 2}, None), (-2, None), ({"min": 1.5}, None),
    ({"var": "v"}, {"type": "enum", "values": ["a", "b"]}), ({"var": "v"}, {"type": "int", "range": [-1, 2]}),
    ({"var": "v"}, {"type": "bool"}),
])
def test_counts_must_be_non_negative_integers_and_ranges_not_empty(raw, card, var):
    """개수는 0 이상의 정수다. 빈 범위(min 이 max 보다 큼)를 받으면 펼친 나무는 그 분해를 없는 것으로 보고 고전 절차는
    구성요소를 만들지 못해 두 뜻이 갈렸다(18 문서 8절). 적재할 때 막는다."""
    bad = copy.deepcopy(raw)
    bad["entities"]["ServerPool"]["multi_aspects"]["serversMAsp"]["cardinality"] = card
    if var is not None:
        bad["variables"]["v"] = var
    with pytest.raises(LoadError, match="개수"):
        load_ses_dict(bad)


def test_valid_counts_are_accepted(raw):
    for card in (0, {"min": 0, "max": 0}, {"min": 2}, {"min": 1, "max": 3}):
        d = copy.deepcopy(raw)
        d["entities"]["ServerPool"]["multi_aspects"]["serversMAsp"]["cardinality"] = card
        load_ses_dict(d)


@pytest.mark.parametrize("name", ["~", "-"])
def test_marker_names_are_reserved(raw, name):
    """펼침은 밀려난 구성원과 빠진 구성요소에 표시 노드를 붙인다. 그 이름은 문서의 분해나 specialization 에 쓸 수 없다."""
    bad = copy.deepcopy(raw)
    bad["entities"]["Generator"]["aspects"] = {name: {"parts": ["Collector"]}}
    del bad["entities"]["Generator"]["stereotype"]
    with pytest.raises(LoadError, match="쓸 수 없다"):
        load_ses_dict(bad)


def test_a_definition_cannot_be_merged_twice_into_one_component():
    """한 엔티티의 두 specialization 이 같은 정의에 닿으면 그 정의가 병합체에 두 번 든다. 대수는 그것을 분해 둘로
    보아 합칠 수 없다고 하고 고전 절차는 하나로 보아 만든다(18 문서 7절). 적재할 때 막는다."""
    def doc(entities):
        return {"ses": "1.0", "name": "R", "entities": entities}

    direct_twice = doc({"R": {"root": True, "specializations": {"s": {"alternatives": ["A"]}, "t": {"alternatives": ["A"]}}},
                        "A": {"extends": "R", "aspects": {"aa": {"parts": ["P"]}}}, "P": {}})
    with pytest.raises(LoadError, match=r"R: specialization s 와 t 가 같은 정의 \['A'\] 에 닿는다"):
        load_ses_dict(direct_twice)
    # 대안은 바탕을 extends 해야 하므로, 한 정의가 두 곳의 대안이 되려면 extends 의 사슬이 둘을 모두 지나야 한다
    nested_twice = doc({"R": {"root": True, "specializations": {"s": {"alternatives": ["A", "B"]}, "t": {"alternatives": ["C"]}}},
                        "A": {"extends": "R"}, "B": {"extends": "C", "specializations": {"u": {"alternatives": ["D"]}}},
                        "C": {"extends": "R", "specializations": {"w": {"alternatives": ["D", "E"]}}},
                        "D": {"extends": "B"}, "E": {"extends": "C"}})
    with pytest.raises(LoadError, match=r"R: specialization s 와 t 가 같은 정의 \['D'\] 에 닿는다"):
        load_ses_dict(nested_twice)
    # 한 specialization 의 대안들이 같은 정의에 닿는 것은 괜찮다. 대안은 하나만 골라진다
    same_spec = doc({"R": {"root": True, "specializations": {"s": {"alternatives": ["B", "C"]}}},
                     "B": {"extends": "C", "specializations": {"u": {"alternatives": ["D"]}}},
                     "C": {"extends": "R", "specializations": {"w": {"alternatives": ["D"]}}},
                     "D": {"extends": "B"}})
    load_ses_dict(same_spec)
    # 서로 다른 구성요소가 같은 정의를 대안으로 쓰는 것도 괜찮다
    two_parts = doc({"R": {"root": True, "aspects": {"d": {"parts": ["X", "Y"]}}},
                     "X": {"extends": "Y", "specializations": {"s": {"alternatives": ["A"]}}},
                     "Y": {"specializations": {"t": {"alternatives": ["A"]}}}, "A": {"extends": "X"}})
    load_ses_dict(two_parts)


@pytest.mark.parametrize("bad", ["$s", "m[2]", "a/b", "1st", "has space", ""])
def test_names_are_identifiers(bad):
    """이름은 글자, 숫자, 밑줄이다. 펼친 나무가 변수($), 개수([n]), 주소(/)에 쓰는 글자가 이름에 들면
    정의 표 위의 뜻과 펼친 나무가 어긋난다 (theory.md 의 W4). 스키마의 identifier 와 같은 규칙이다."""
    def doc(entities, variables=None):
        d = {"ses": "1.0", "name": "R", "entities": entities}
        return dict(d, variables=variables) if variables else d

    cases = [doc({"R": {"root": True, "specializations": {bad: {"alternatives": ["A"]}}}, "A": {"extends": "R"}}),
             doc({"R": {"root": True, "aspects": {bad: {"parts": ["A"]}}}, "A": {}}),
             doc({"R": {"root": True, "multi_aspects": {bad: {"part": "A", "cardinality": 2}}}, "A": {}}),
             doc({"R": {"root": True, "aspects": {"d": {"parts": [{"def": "A", "alias": bad}]}}}, "A": {}}),
             doc({"R": {"root": True, "aspects": {"d": {"parts": [bad]}}}, bad: {}}),
             doc({"R": {"root": True}}, {bad: {"type": "int", "range": [1, 2]}})]
    for d in cases:
        with pytest.raises(LoadError, match="쓸 수 없다"):
            load_ses_dict(d)
    load_ses_dict(doc({"R": {"root": True, "aspects": {"분해_1": {"parts": [{"def": "A", "alias": "첫째"}]}}}, "A": {}}))


def test_values_of_a_variable_are_written_differently():
    """변수의 값은 글자로 적어 구별한다. 1 과 "1" 처럼 적으면 같은 두 값은 펼친 나무에서 한 노드가 된다 (theory.md 의 W5)."""
    def doc(values):
        return {"ses": "1.0", "name": "R", "variables": {"v": {"type": "enum", "values": values}},
                "entities": {"R": {"root": True}}}

    for values in ([1, "1"], ["a", "a"], [True, "True"]):
        with pytest.raises(LoadError, match="글자로 적으면 같다"):
            load_ses_dict(doc(values))
    load_ses_dict(doc([1, 2, "a"]))
