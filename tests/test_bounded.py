"""작은 문서의 전수 검사 (docs/ses-platform/theory.md 의 9절).

bounded_docs.py 가 열한 묶음의 작은 문서를 빠짐없이 낸다(73,693개). 문서마다 bounded_check.py 의 검사를 한다.
정리 1 (c), 정리 2, 정리 3, 정리 5, 따름정리 5.1, 정의 9 와 10 의 글과 펼침의 구현, 고전 절차와의 대조다.

전부 돌리면 코어 하나에서 20분쯤 걸린다. 그래서 여기서는 묶음마다 23번째 문서만 본다(3,209개).
전부는 다음 가운데 하나로 돌린다.
  python tools/bounded.py                 모든 코어를 써서 전부. 요약을 적는다
  SES_BOUNDED=all python -m pytest tests/test_bounded.py
무작위 시험(test_folded.py)과 달리 표본이 아니다. 한도 안의 문서는 빠짐없이 본다.
"""

import collections
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import bounded_check  # noqa: E402
import bounded_docs  # noqa: E402

STEP = 1 if os.environ.get("SES_BOUNDED") == "all" else 23
SIZES = {"F1": 15125, "F2": 10206, "F3": 10800, "F4": 5120, "F5": 6912, "F6": 1120, "F7": 5465, "F8": 15768,
         "F9": 1071, "F10": 1728, "F11": 378}
STATS: collections.Counter = collections.Counter()


@pytest.mark.parametrize("family", list(bounded_docs.FAMILIES))
def test_every_document_of_the_family_passes(family):
    failures, n = [], 0
    for i, d in enumerate(bounded_docs.FAMILIES[family]()):
        n += 1
        if i % STEP:
            continue
        stats, fails = bounded_check.check_document(d)
        STATS.update(stats)
        failures += [(family, i, check, msg) for check, msg in fails]
    assert n == SIZES[family]                                # 열거기가 적힌 수만큼 낸다
    assert not failures, failures[:5]


def test_the_enumeration_is_deterministic():
    """같은 (묶음, 번호)는 같은 문서다. 문서를 번호로 가리킬 수 있어야 실패를 다시 볼 수 있다."""
    for family in ("F6", "F9", "F11"):
        first = list(bounded_docs.FAMILIES[family]())
        assert first == list(bounded_docs.FAMILIES[family]())
        assert bounded_docs.document(family, 7) == first[7]
    assert sum(SIZES.values()) == 73693


def test_a_failure_is_reported():
    """검사가 실제로 견준다는 것. 정의 3 을 틀리게 바꾸면 실패가 나온다."""
    from ses_core import folded as F
    d = bounded_docs.document("F1", 200)
    real = F.above
    try:
        F.above = lambda p, q: p is not None and (q is None or p <= q)       # 같은 수도 앞선다고 한다
        broken = sum(bool(bounded_check.check_document(x)[1])
                     for i, x in enumerate(bounded_docs.FAMILIES["F1"]()) if i % 500 == 0)
    finally:
        F.above = real
    assert not bounded_check.check_document(d)[1]
    assert broken >= 5


def test_the_documents_are_not_vacuous():
    """본 문서들이 검사할 거리를 가지고 있다. 앞의 시험들이 모은 수를 본다."""
    if not STATS["documents"]:
        pytest.skip("앞의 시험이 돌지 않았다")
    floor = 1 if STEP == 23 else 23
    assert STATS["documents"] >= 3200 * floor
    assert STATS["rejected_by_loader"] == 0 and STATS["unfold_raised"] == 0
    assert STATS["variants"] >= 20000 * floor and STATS["ill_variants"] >= 5000 * floor
    assert STATS["stuck_components"] >= 4000 * floor and STATS["gone_components"] >= 4000 * floor
    assert STATS["docs_with_dec_and_amb"] >= 500 * floor
    assert STATS["docs_with_selected"] >= 800 * floor and STATS["docs_with_path_selected"] >= 400 * floor
    assert STATS["classic_models"] >= 10000 * floor
    assert STATS["clusters"] >= 15000 * floor
    assert STATS["variants"] == STATS["unfolded_variants"] == STATS["literal_tree_variants"]
