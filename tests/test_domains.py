"""범용 장치와 도메인 프로파일: 세 분야(커리큘럼, RFP, 논문의 논리 구성)를
분야별 코드 없이 선언만으로 다루는지 확인한다 (docs/ses-platform/12_generic_and_specific.md).
"""

import copy
import json
import os
import random
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from test_algebra import rand_formula, rand_pattern, rand_selection, rand_tree  # noqa: E402
from test_extension import rand_attrs, rand_void, same  # noqa: E402

from ses_core import LoadError, load_ses, load_ses_dict  # noqa: E402
from ses_core.algebra import ASP, ENT, SPEC, SES, AlgebraError, restrict, sem, variants  # noqa: E402
from ses_core.algebra import prune as prune_ses  # noqa: E402
from ses_core.extension import (  # noqa: E402
    Layered, family_wellformed, ill_formed, interpret, prune, violations, wellformed, wf_core)
from ses_core.profile import Domain, Item, load_profile, load_profile_dict  # noqa: E402
from ses_core.unfold import pruning_patterns, unfold_layered  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "ses-platform")
DOMAINS = os.path.join(ROOT, "domains")
CASES = {
    "curriculum": "curriculum_intro_programming",
    "rfp": "rfp_lms",
    "paper": "paper_pruning_algebra",
}


def raw(name):
    with open(os.path.join(DOMAINS, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def layered(profile_name, ses_dict=None, profile_dict=None):
    prof = load_profile_dict(profile_dict or raw(profile_name + ".profile.yaml"))
    doc = load_ses_dict(ses_dict or raw(CASES[profile_name] + ".ses.yaml"))
    return unfold_layered(doc, prof)


def codes(L):
    out = {}
    for V, vs in ill_formed(L):
        for _, code, path, _ in vs:
            out[code] = out.get(code, 0) + 1
    return out


def selected(V, name):
    return any(n[-1] == name for n in V)


# ---------------------------------------------------------------------------
# 형식: 세 분야의 프로파일과 문서가 두 스키마를 통과한다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(CASES))
def test_documents_conform_to_schemas(name):
    jsonschema = pytest.importorskip("jsonschema")
    with open(os.path.join(ROOT, "schema", "profile.schema.json"), encoding="utf-8") as f:
        profile_schema = json.load(f)
    with open(os.path.join(ROOT, "schema", "ses.schema.json"), encoding="utf-8") as f:
        ses_schema = json.load(f)
    jsonschema.Draft202012Validator(profile_schema).validate(raw(name + ".profile.yaml"))
    jsonschema.Draft202012Validator(ses_schema).validate(raw(CASES[name] + ".ses.yaml"))


@pytest.mark.parametrize("name", sorted(CASES))
def test_only_the_profile_extension_is_used(name):
    L = layered(name)
    assert [x.name for x in L.extensions] == [name]         # 분야별 코드 없음
    assert isinstance(L.extensions[0], Domain)


# ---------------------------------------------------------------------------
# 학습 커리큘럼
# ---------------------------------------------------------------------------

def test_curriculum_family_analysis():
    L = layered("curriculum")
    vs = sem(L.ses)
    assert len(vs) == 12                                    # 트랙 2, 심화 개설 2, 실습 주수 3
    good = [V for V in vs if wellformed(L, V)]
    assert len(good) == 4
    assert codes(L) == {"R1": 6, "R2": 2}
    for V in vs:
        ok = selected(V, "심화개설") and not selected(V, "실습들[3]")
        assert wellformed(L, V) == ok
    core = wf_core(L)                                       # 적격 핵: 심화 단원이 사실상 필수
    assert len(sem(core.ses)) == 4
    assert not any(n[-1] == "심화미개설" for n in core.ses.tree.nodes)
    assert not any(n[-1] == "실습들[3]" for n in core.ses.tree.nodes)


def test_curriculum_interpretation_is_a_syllabus():
    L = layered("curriculum")
    V = next(v for v in sem(L.ses) if wellformed(L, v) and selected(v, "웹트랙")
             and selected(v, "실습들[2]"))
    out = interpret(L, V)["curriculum"]
    assert out["kind"] == "과정" and out["totals"] == {"총시수": 45, "평가비중합": 100}
    area = out["children"]["응용영역"]["children"]
    assert sorted(area) == ["웹기초", "웹프로젝트"]
    assert area["웹프로젝트"]["fields"] == {"시수": 9, "수준": "기초"}     # 기본값이 채워진다
    assert area["웹프로젝트"]["links"] == {"달성": ["LO3"], "선수": ["웹기초"]}
    deep = out["children"]["기초영역"]["children"]["심화알고리즘"]
    assert deep["def"] == "심화개설" and deep["fields"]["수준"] == "심화"
    assert sorted(out["children"]["실습영역"]["children"]) == ["실습_0", "실습_1"]


def test_curriculum_pruning_ses_selects_a_track():
    """가지치기 SES로 트랙을 고른다. 분야가 달라도 가지치기는 핵의 연산 그대로다."""
    L = layered("curriculum")
    web = pruning_patterns(load_ses_dict({"ses": "1.0", "name": "p", "entities": {
        "프로그래밍입문": {"root": True},
        "응용영역": {"aspects": {"웹트랙": {"parts": ["웹기초"]}}},
        "웹기초": {}}}))
    R = prune(wf_core(L), *web)
    assert len(sem(R.ses)) == 2 and family_wellformed(R)
    assert all(selected(V, "웹프로젝트") for V in sem(R.ses))


def test_curriculum_prerequisite_cycle_and_missing_prerequisite():
    bad = raw(CASES["curriculum"] + ".ses.yaml")
    bad["entities"]["변수와자료형"]["links"]["선수"] = ["함수"]          # 순환
    L = layered("curriculum", bad)
    assert "L3" in codes(L)
    bad2 = raw(CASES["curriculum"] + ".ses.yaml")
    bad2["entities"]["함수"]["links"]["선수"] = ["심화알고리즘"]         # 선택 단원을 선수로
    L2 = layered("curriculum", bad2)
    missing = [V for V, vs in ill_formed(L2) if any(c == "L1" for _, c, _, _ in vs)]
    assert missing and all(selected(V, "심화미개설") for V in missing)


# ---------------------------------------------------------------------------
# 제안요청서
# ---------------------------------------------------------------------------

def test_rfp_family_analysis():
    L = layered("rfp")
    vs = sem(L.ses)
    assert len(vs) == 8 and codes(L) == {"L1": 4, "R1": 4}
    for V in vs:
        ok = selected(V, "운영포함") and selected(V, "성능요구제외")
        assert wellformed(L, V) == ok
    core = wf_core(L)
    assert len(sem(core.ses)) == 2                          # 보안 수준만 고를 수 있다
    out = interpret(core, sem(core.ses)[0])["rfp"]
    assert out["totals"] == {"배점합": 100}


def test_rfp_scores_must_sum_to_one_hundred():
    bad = raw(CASES["rfp"] + ".ses.yaml")
    bad["entities"]["가격평가"]["fields"]["배점"] = 20
    L = layered("rfp", bad)
    assert codes(L)["R2"] == 8                              # 모든 변이에서 배점 합이 90
    assert wf_core(L) is None                               # 적격한 변이가 하나도 없다


def test_rfp_required_target_moves_the_obligation():
    """성능 요구사항에 평가항목을 붙이면 그 선택지가 살아나고, 의무가 반대쪽으로 옮겨 간다."""
    fixed = raw(CASES["rfp"] + ".ses.yaml")
    fixed["entities"]["기술평가"]["links"]["평가대상"].append("동시접속")
    L = layered("rfp", fixed)
    # 평가대상은 대상이 필수인 관계이므로 이번에는 성능 요구를 뺀 변이가 부적격이 된다
    good = [V for V in sem(L.ses) if wellformed(L, V)]
    assert len(good) == 2 and all(selected(V, "성능요구포함") for V in good)


# ---------------------------------------------------------------------------
# 논문의 논리 구성
# ---------------------------------------------------------------------------

def test_paper_family_analysis():
    L = layered("paper")
    vs = sem(L.ses)
    assert len(vs) == 8
    good = [V for V in vs if wellformed(L, V)]
    assert len(good) == 2
    plans = {(selected(V, "C3포함"), selected(V, "성능실험"), selected(V, "E4포함")) for V in good}
    assert plans == {(False, False, False), (True, True, False)}
    # 주장 C3을 넣으려면 성능 실험이 필요하고, 추가 증명 E4는 어느 구성안에도 들어가지 못한다
    core = wf_core(L)
    assert not any(n[-1] == "E4포함" for n in core.ses.tree.nodes)


def test_paper_page_budget_decides_what_fits():
    relaxed = raw("paper.profile.yaml")
    for r in relaxed["rules"]:
        if r["name"] == "분량":
            r["max"] = 14
    L = layered("paper", profile_dict=relaxed)
    good = [V for V in sem(L.ses) if wellformed(L, V)]
    assert len(good) == 4                                   # 분량 제한을 풀면 구성안이 늘어난다


# ---------------------------------------------------------------------------
# 프로파일이 잡는 것들
# ---------------------------------------------------------------------------

def test_profile_checks_kinds_fields_and_containment():
    base = raw(CASES["rfp"] + ".ses.yaml")

    def found(mutate):
        d = copy.deepcopy(base)
        mutate(d["entities"])
        return set(codes(layered("rfp", d)))

    assert "T1" in found(lambda e: e["로그인"].update(kind="요구"))                 # 없는 유형
    assert "F1" in found(lambda e: e["로그인"]["fields"].update(담당="팀"))          # 없는 필드
    assert "F2" in found(lambda e: e["로그인"]["fields"].pop("번호"))                # 필수 필드 누락
    assert "F3" in found(lambda e: e["로그인"]["fields"].update(구분="기타"))        # 허용 값 아님
    assert "F3" in found(lambda e: e["기술평가"]["fields"].update(배점="육십"))      # 타입 다름
    assert "T2" in found(lambda e: e["개발과업"]["aspects"]["요구사항목록"]["parts"].append("가격평가"))
    assert "L2" in found(lambda e: e["로그인"].update(links={"평가대상": ["강의관리"]}))


def test_loader_rejects_link_to_undefined_entity():
    d = raw(CASES["rfp"] + ".ses.yaml")
    d["entities"]["기술평가"]["links"]["평가대상"].append("없는요구사항")
    with pytest.raises(LoadError, match="없는요구사항"):
        load_ses_dict(d)


def test_profile_is_validated():
    p = raw("rfp.profile.yaml")
    p["links"]["평가대상"]["to"] = ["요구"]
    with pytest.raises(AlgebraError, match="정의되지 않은 유형"):
        load_profile_dict(p)
    with pytest.raises(AlgebraError, match="프로파일"):
        unfold_layered(load_ses_dict(raw(CASES["rfp"] + ".ses.yaml")), None)
    with pytest.raises(AlgebraError, match="프로파일"):
        layered("rfp", raw(CASES["paper"] + ".ses.yaml"))


def test_field_conflict_between_sibling_alternatives():
    d = raw(CASES["paper"] + ".ses.yaml")
    d["entities"]["E3"]["specializations"]["검토"] = {"alternatives": ["내부검토", "외부검토"]}
    d["entities"]["내부검토"] = {"extends": "E3"}
    d["entities"]["외부검토"] = {"extends": "E3", "fields": {"분량": 1}}
    L = layered("paper", d)
    bad = [V for V, vs in ill_formed(L) if any(c == "M" for _, c, _, _ in vs)]
    assert bad and all(selected(V, "외부검토") for V in bad)     # 두 대안이 분량을 다르게 준다


# ---------------------------------------------------------------------------
# 핵의 정리는 어떤 프로파일에서도 성립한다 (11 문서의 정리 14 ~ 16)
# ---------------------------------------------------------------------------

def rand_profile(rng):
    kinds = {}
    names = ["a", "b", "c"]
    for k in names:
        spec = {"fields": {"w": {"type": "int", "required": rng.random() < 0.15}}}
        if rng.random() < 0.2:
            spec["contains"] = rng.sample(names, rng.randint(1, 3))
        kinds[k] = spec
    links = {
        "r": {"acyclic": rng.random() < 0.6,
              "target": "required" if rng.random() < 0.5 else "optional"},
        "s": {"from": rng.sample(names, rng.randint(2, 3)), "to": rng.sample(names, rng.randint(2, 3))},
    }
    rules = []
    if rng.random() < 0.5:
        rules.append({"name": "cover", "each": rng.choice(names),
                      rng.choice(["incoming", "outgoing"]): {rng.choice(["r", "s"]): 1}})
    if rng.random() < 0.5:
        rules.append({"name": "total", "sum": {"field": "w", "over": names},
                      "max": rng.randint(6, 20)})
    if rng.random() < 0.3:
        rules.append({"name": "howmany", "at": rng.choice(names),
                      "count": {"over": names}, "min": 1, "max": rng.randint(1, 4)})
    return load_profile_dict({"profile": "1.0", "name": "domain", "kinds": kinds,
                              "links": links, "rules": rules})


def rand_domain(seed):
    rng = random.Random(seed)
    T = rand_tree(rng)
    void = rand_void(rng, T)
    ents = sorted(e for e in T.nodes if T.kind(e) == ENT and e not in void)
    labels = [e[-1] for e in ents]
    items = {}
    for e in ents:
        if rng.random() < 0.2:
            continue
        fields = {"w": rng.randint(1, 4)} if rng.random() < 0.7 else {}
        links = {}
        for lt in ("r", "s"):
            if rng.random() < 0.2:
                links[lt] = tuple(rng.sample(labels, min(len(labels), rng.randint(1, 2))))
        items[e] = Item(rng.choice(["a", "b", "c"]) if rng.random() < 0.9 else None, fields, links)
    L = Layered(SES(T, rand_formula(rng, T)), void, (Domain(rand_profile(rng), items),))
    return rng, L


@pytest.mark.parametrize("seed", range(300))
def test_core_theorems_hold_for_any_profile(seed):
    rng, L = rand_domain(seed)
    T = L.ses.tree
    K = rand_selection(rng, T)
    sub = Layered(SES(restrict(T, K)), L.void, L.extensions)
    for V in variants(sub.ses.tree)[:30]:                          # 내재성
        assert violations(sub, V) == violations(L, V)
        assert interpret(sub, V) == interpret(L, V)
    good = {V for V in sem(L.ses) if wellformed(L, V)}
    core = wf_core(L)                                              # 적격 핵
    assert (set(sem(core.ses)) if core is not None else set()) == good
    P = SES(rand_pattern(rng, T, extras=True), rand_formula(rng, T))
    if core is not None:
        assert same(wf_core(core), core)
        R = prune(core, P)
        if R is not None:
            assert family_wellformed(R)                            # 보존
    lp = prune(L, P)                                               # 가지치기와 교환
    assert same(wf_core(lp) if lp is not None else None,
                prune(core, P) if core is not None else None)
    attrs = rand_attrs(rng, T, L.void)                             # 다른 확장과의 합성
    joint = wf_core(L.plus(attrs))
    step = wf_core(Layered(core.ses, L.void, (attrs,))) if core is not None else None
    assert same(joint, Layered(step.ses, L.void, L.extensions + (attrs,)) if step else None)


def test_random_profile_sample_is_not_vacuous():
    fw = mixed = none = 0
    seen = set()
    for seed in range(300):
        _, L = rand_domain(seed)
        vs = sem(L.ses)
        good = sum(wellformed(L, V) for V in vs)
        fw += bool(vs) and good == len(vs)
        mixed += 0 < good < len(vs)
        none += bool(vs) and good == 0
        for V in vs[:10]:
            seen |= {c for _, c, _, _ in violations(L, V)}
    assert fw >= 10 and mixed >= 60 and none >= 30
    assert {"F2", "T2", "L1", "L2", "L3", "M", "R1", "R2"} <= seen
