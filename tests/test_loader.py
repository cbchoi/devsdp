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
