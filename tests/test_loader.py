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


def test_unknown_keys_are_refused_and_the_table_of_keys_is_the_schema():
    """잘못 적은 항목을 조용히 넘기지 않는다. 속성의 값을 value 로 적으면 값이 없는 속성이 되기 때문이다.

    적재기가 아는 항목의 표(loader.KEYS)는 스키마의 properties 와 같다. 스키마를 고치면 이 시험이 알린다.
    """
    import json
    from ses_core import loader
    with open(os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform", "schema", "ses.schema.json"),
              encoding="utf-8") as f:
        schema = json.load(f)
    defs = schema["$defs"]
    multi = defs["multiAspect"]["properties"]
    of_schema = {
        "document": schema, "variable": defs["variable"], "portType": defs["portType"], "port": defs["port"],
        "attribute": defs["attribute"], "entity": defs["entity"], "aspect": defs["aspect"],
        "multiAspect": defs["multiAspect"], "pattern": multi["couplings"], "specialization": defs["specialization"],
        "selectRule": defs["selectRule"], "coupling": defs["coupling"], "constraint": defs["constraint"],
        "frame": schema["properties"]["experimental_frames"]["items"],
        "partRef": next(x for x in defs["partRef"]["oneOf"] if "properties" in x),
    }
    assert set(of_schema) == set(loader.KEYS)
    for kind, part in of_schema.items():
        assert set(part["properties"]) == loader.KEYS[kind], kind

    def doc(**changes):
        d = {"ses": "1.0", "name": "R", "variables": {"v": {"type": "int", "range": [1, 2]}},
             "entities": {"R": {"root": True, "attributes": {"a": {"type": "int", "default": 1}},
                                "aspects": {"x": {"parts": ["P"]}},
                                "specializations": {"s": {"alternatives": ["A", "B"]}}},
                          "A": {"extends": "R"}, "B": {"extends": "R"}, "P": {}}}
        for path, value in changes.items():
            at = d
            keys = path.split("/")
            for key in keys[:-1]:
                at = at[key]
            at[keys[-1]] = value
        return d

    load_ses_dict(doc())
    for changes, message in [
        ({"entities/R/attributes/a": {"type": "int", "value": 1}}, "R: 속성 a: 모르는 항목 value 가 있다. default 를 뜻했는가"),
        ({"entities/R/aspects/x": {"part": ["P"]}}, "R: aspect x: 모르는 항목 part 가 있다. parts 를 뜻했는가"),
        ({"entities/R/specializations/s": {"alternative": ["A", "B"]}}, "alternatives 를 뜻했는가"),
        ({"entities/R/aspect": {}}, "R: 정의: 모르는 항목 aspect 가 있다. aspects 를 뜻했는가"),
        ({"entities/R/colour": "red"}, "R: 정의: 모르는 항목 colour 가 있다. 쓸 수 있는 것은"),
        ({"variables/v": {"type": "int", "range": [1, 2], "note": "x"}}, "variables.v: 모르는 항목 note"),
        ({"entitys": {}}, "문서: 모르는 항목 entitys"),
        ({"entities/P": None}, "P: 정의: 이름과 값의 표로 적어야 한다"),
        ({"entities/R/attributes/a": 3}, "R: 속성 a: 이름과 값의 표로 적어야 한다"),
        ({"entities/R/attributes/a": {"default": 1}}, "R: 속성 a: type 가 없다"),
        ({"entities/R/aspects/x": {}}, "R: aspect x: parts 가 없다"),
    ]:
        with pytest.raises(LoadError, match=message):
            load_ses_dict(doc(**changes))


def test_values_of_a_variable_are_different_values():
    """글자는 달라도 같은 값으로 읽히는 두 값은 함께 둘 수 없다. 0 과 false, 1 과 true, 1 과 1.0 이 그렇다.

    선택 지점 표는 값으로 줄을 만든다. 그런 값들이 함께 있으면 표가 둘을 구별하지 못한다 (theory.md 의 W5).
    """
    def doc(values):
        return {"ses": "1.0", "name": "R", "variables": {"v": {"type": "enum", "values": values}},
                "entities": {"R": {"root": True}}}

    for values in ([0, False, "a"], [True, 1], [1, 1.0], ["x", 2, 2.0]):
        with pytest.raises(LoadError, match="같은 값으로 읽힌다"):
            load_ses_dict(doc(values))
    for values in ([0, 1, "a"], [True, False], [1, 2.5], ["0", "False"]):
        load_ses_dict(doc(values))


def test_values_of_a_variable_are_written_differently():
    """변수의 값은 글자로 적어 구별한다. 1 과 "1" 처럼 적으면 같은 두 값은 펼친 나무에서 한 노드가 된다 (theory.md 의 W5)."""
    def doc(values):
        return {"ses": "1.0", "name": "R", "variables": {"v": {"type": "enum", "values": values}},
                "entities": {"R": {"root": True}}}

    for values in ([1, "1"], ["a", "a"], [True, "True"]):
        with pytest.raises(LoadError, match="글자로 적으면 같다"):
            load_ses_dict(doc(values))
    load_ses_dict(doc([1, 2, "a"]))


def test_a_cycle_is_found_through_a_shared_definition_and_deep_sharing_is_fast():
    """쓰임 관계의 순환은 여러 곳에서 쓰이는 정의를 거쳐도 찾는다. 같은 정의를 여러 번 쓰는 깊은 문서도 금방 본다."""
    import time
    cyc = {"ses": "1.0", "name": "R",
           "entities": {"R": {"root": True, "aspects": {"d": {"parts": ["X", "Y"]}}},
                        "X": {"aspects": {"d": {"parts": ["S"]}}}, "Y": {"aspects": {"d": {"parts": ["S"]}}},
                        "S": {"aspects": {"d": {"parts": ["T"]}}}, "T": {"aspects": {"d": {"parts": ["Y"]}}}}}
    with pytest.raises(LoadError, match="strict hierarchy 위반"):
        load_ses_dict(cyc)
    depth = 60                                                # 경로의 수는 2의 60제곱이다
    entities = {"L0": {"root": True}}
    for i in range(depth):
        entities[f"L{i}"].update({"aspects": {"a": {"parts": [f"L{i + 1}", {"def": f"L{i + 1}", "alias": "again"}]}}})
        entities[f"L{i + 1}"] = {}
    started = time.time()
    load_ses_dict({"ses": "1.0", "name": "L0", "entities": entities})
    assert time.time() - started < 5


@pytest.mark.parametrize("why,entities,variables", [
    ("두 번 적었다", {"R": {"root": True, "specializations": {"s": {"alternatives": ["A", "A"]}}}, "A": {"extends": "R"}}, None),
    ("대안이 하나도 없다", {"R": {"root": True, "specializations": {"s": {"alternatives": []}}}}, None),
    ("이름의 틀", {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": 2, "naming": "x"}}}, "P": {}}, None),
    ("이름의 틀", {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": 2, "naming": "{part}_{n}"}}}, "P": {}}, None),
    ("이름의 틀", {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": 2, "naming": "{part}/{i}"}}}, "P": {}}, None),
    ("이름의 틀", {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": 2, "naming": "{who}_{i}"}}}, "P": {}}, None),
    ("부분이 될 수 없다", {"R": {"root": True, "multi_aspects": {"m": {"part": "V", "cardinality": 2}}}, "V": {"stereotype": "void"}}, None),
    ("쓸 수 없다", {"R": {"root": True, "aspects": {"a": {"parts": ["~"]}}}, "~": {}}, None),
    ("쓸 수 없다", {"R": {"root": True, "aspects": {"a": {"parts": [{"def": "P", "alias": "-"}]}}}, "P": {}}, None),
    ("값이 하나도 없다", {"R": {"root": True}}, {"v": {"type": "int", "range": [3, 1]}}),
    ("값이 하나도 없다", {"R": {"root": True}}, {"v": {"type": "enum", "values": []}}),
    ("우선순위는 정수", {"R": {"root": True, "aspects": {"a": {"parts": ["P"], "priority": 1.5}}}, "P": {}}, None),
    ("우선순위는 정수", {"R": {"root": True, "aspects": {"a": {"parts": ["P"], "priority": True}}}, "P": {}}, None),
    ("우선순위는 정수", {"R": {"root": True, "multi_aspects": {"m": {"part": "P", "cardinality": 1, "priority": "1"}}}, "P": {}}, None),
])
def test_the_conditions_of_a_document_are_enforced(why, entities, variables):
    """theory.md 의 정의 1과 W1에서 W5가 문서에 요구하는 것을 적재기가 본다. 독립된 검토가 찾은 빈 곳들이다.
    이 문서들에서 정의 표 위의 의미와 펼친 나무가 다른 수를 내거나 한쪽이 실패했다."""
    d = {"ses": "1.0", "name": "R", "entities": entities}
    if variables:
        d["variables"] = variables
    with pytest.raises(LoadError, match=why):
        load_ses_dict(d)


def test_definitions_that_the_root_does_not_reach_are_not_judged_for_cycles():
    """쓰임 관계의 순환은 뿌리에서 닿는 정의들에서만 본다. 닿지 않는 정의는 뜻에 관여하지 않는다 (theory.md 의 W1)."""
    load_ses_dict({"ses": "1.0", "name": "R",
                   "entities": {"R": {"root": True}, "A": {"aspects": {"a": {"parts": ["B"]}}},
                                "B": {"aspects": {"b": {"parts": ["A"]}}}}})


def test_valid_replica_names_and_priorities_are_accepted():
    load_ses_dict({"ses": "1.0", "name": "R",
                   "entities": {"R": {"root": True, "multi_aspects": {
                       "m": {"part": "P", "cardinality": 2, "naming": "unit{i}_of_{n}", "priority": -3},
                       "k": {"part": "P", "cardinality": 1, "priority": 0}}}, "P": {}}})
