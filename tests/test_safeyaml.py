"""YAML 파일을 읽는 일 (ses_core/safeyaml.py).

별칭(&, *)으로 부풀린 파일과 자기 자신을 가리키는 파일은 읽은 값을 돌아보는 코드를 멈추게 한다. 읽은 뒤에 펼친
크기를 세어 거부한다. 문서, 결정 집합, 바인딩, 프로파일, 묶음의 선언과 기록이 모두 이 길로 읽힌다.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from ses_core import safeyaml  # noqa: E402
from ses_core import executor, load_ses, pack, profile  # noqa: E402
from ses_core.decisions import DecisionError, load_decisions  # noqa: E402
from ses_core.loader import LoadError  # noqa: E402

BOMB = "a: &a [x,x,x,x,x,x,x,x,x,x]\n" + "".join(
    f"{c}: &{c} [{','.join(['*' + p] * 10)}]\n" for p, c in zip("abcdefgh", "bcdefghi"))


def test_the_unfolded_size_counts_shared_values_every_time():
    shared = [1, 2, 3]
    assert safeyaml.unfolded_size(5) == 1 and safeyaml.unfolded_size([]) == 1
    assert safeyaml.unfolded_size(shared) == 4                           # 목록 하나와 값 셋
    assert safeyaml.unfolded_size({"a": shared, "b": shared}) == 11      # 사전 하나, 열쇠 둘, 목록이 두 번
    assert safeyaml.unfolded_size(safeyaml.load_text("a: &a [1, 2]\nb: *a\nc: *a\n")) == 13
    with pytest.raises(safeyaml.YamlError, match="값 10개 넘게 부풀린다"):
        safeyaml.unfolded_size({"a": shared, "b": shared}, limit=10)
    assert safeyaml.unfolded_size({"a": shared, "b": shared}, limit=11) == 11


def test_a_file_blown_up_by_aliases_is_refused_quickly():
    """아홉 줄이 십억 개의 값으로 펼쳐진다. 세는 일은 적힌 값의 수에 비례하므로 바로 끝난다."""
    with pytest.raises(safeyaml.YamlError, match="별칭\\(&, \\*\\)이 파일을 값 1000000개 넘게 부풀린다"):
        safeyaml.load_text(BOMB)
    small = "a: &a [x,x]\nb: [*a,*a,*a]\n"
    assert safeyaml.load_text(small) == {"a": ["x", "x"], "b": [["x", "x"]] * 3}


def test_a_file_that_points_at_itself_is_refused():
    for text in ("a: &a [*a]\n", "&a {k: *a}\n", "a: &a {b: &b [*a, *b]}\n"):
        with pytest.raises(safeyaml.YamlError, match="자기 자신을 가리키는 별칭"):
            safeyaml.load_text(text)


def test_what_is_not_text_and_what_is_not_yaml(tmp_path):
    for name, raw, word in (("a.yaml", b"\xff\xfe\x00bad", "UTF-8 로 적힌 글이 아니다"),
                            ("b.yaml", b"a: 1\x00\n", "NUL 문자"),
                            ("c.yaml", b"a: [1, 2\n", "YAML 문법이 틀렸다. 2번째 줄 1번째 칸"),
                            ("d.yaml", b"a: 2026-13-45\n", "YAML 문법이 틀렸다"),
                            ("e.yaml", b"[" * 5000, "YAML 문법이 틀렸다")):
        path = tmp_path / name
        path.write_bytes(raw)
        with pytest.raises(safeyaml.YamlError, match=word):
            safeyaml.load(str(path))
    with pytest.raises(OSError):
        safeyaml.load(str(tmp_path / "none.yaml"))
    (tmp_path / "ok.yaml").write_text("이름: 값\n", encoding="utf-8")
    assert safeyaml.load(str(tmp_path / "ok.yaml")) == {"이름": "값"}


def test_every_reader_of_the_platform_goes_this_way(tmp_path):
    """문서, 결정 집합, 바인딩, 프로파일, 묶음의 선언. 어느 것도 부풀린 파일 앞에서 멈추지 않는다."""
    path = tmp_path / "bomb.yaml"
    path.write_text(BOMB, encoding="utf-8")
    with pytest.raises(LoadError, match="부풀린다"):
        load_ses(str(path))
    with pytest.raises(DecisionError, match="부풀린다"):
        load_decisions(str(path))
    with pytest.raises(executor.BindingError, match="부풀린다"):
        executor.load_binding(str(path))
    with pytest.raises(Exception, match="부풀린다"):
        profile.load_profile(str(path))
    (tmp_path / "pack.yaml").write_text(BOMB, encoding="utf-8")
    with pytest.raises(pack.PackError, match="부풀린다"):
        pack.load(str(tmp_path))
