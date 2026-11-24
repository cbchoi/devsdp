"""YAML 파일을 읽는다. 별칭으로 부풀린 문서와 자기 자신을 가리키는 문서를 거부한다.

YAML 의 별칭(&이름 으로 붙이고 *이름 으로 가리킨다)은 같은 값을 여러 번 가리킨다. 몇 줄의 파일이 수억 개의
값으로 펼쳐질 수 있고, 자기 자신을 가리키게 적을 수도 있다. 읽은 값을 돌아보는 코드는 그 앞에서 끝나지 않거나
기억을 다 쓴다. 그래서 읽은 뒤에 펼친 크기를 세어 한도를 넘으면 거부한다. 세는 일은 적힌 값의 수에 비례한다.
같은 값은 한 번만 센다.

문서, 결정 집합, 바인딩, 프로파일, 묶음의 선언과 기록을 모두 이 함수로 읽는다. 에이전트가 쓴 파일을 받는
자리이므로 어떤 파일도 도구를 멈추게 해서는 안 된다(docs/ses-platform/21_agent_operations.md).
"""

from __future__ import annotations

from typing import Any

LIMIT = 1000000                 # 별칭을 펼친 값의 수의 한도


class YamlError(ValueError):
    """파일을 YAML 로 읽을 수 없다. 어디가 틀렸는지를 적는다."""


def unfolded_size(x: Any, limit: int = LIMIT) -> int:
    """별칭을 모두 펼쳤을 때의 값의 수. 한도를 넘거나 자기 자신을 가리키면 YamlError 다."""
    memo: dict = {}
    active: set = set()

    def go(v) -> int:
        if not isinstance(v, (dict, list, tuple)):
            return 1
        key = id(v)
        if key in memo:
            return memo[key]
        if key in active:
            raise YamlError("자기 자신을 가리키는 별칭이 있다. 값이 끝없이 펼쳐진다")
        active.add(key)
        n = 1
        for child in (list(v.keys()) + list(v.values()) if isinstance(v, dict) else v):
            n += go(child)
            if n > limit:
                raise YamlError(f"별칭(&, *)이 파일을 값 {limit}개 넘게 부풀린다. 별칭을 쓰지 않고 적는다")
        active.discard(key)
        memo[key] = n
        return n

    try:
        return go(x)
    except RecursionError:
        raise YamlError("값이 너무 깊이 겹쳐 있다") from None


def load_text(text: str) -> Any:
    """글을 YAML 로 읽는다."""
    import yaml  # 지연 임포트. 코어 자료구조 자체는 yaml 에 의존하지 않는다
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"{mark.line + 1}번째 줄 {mark.column + 1}번째 칸: " if mark is not None else ""
        raise YamlError(f"YAML 문법이 틀렸다. {where}{getattr(e, 'problem', None) or str(e).splitlines()[0]}") from None
    except RecursionError:
        raise YamlError("YAML 문법이 틀렸다. 값이 너무 깊이 겹쳐 있다") from None
    except (ValueError, OverflowError) as e:                 # 날짜나 수로 읽으려다 실패한 글
        raise YamlError(f"YAML 문법이 틀렸다. {type(e).__name__}: {e}") from None
    unfolded_size(d)
    return d


def load(path: str) -> Any:
    """파일을 YAML 로 읽는다. 파일을 열 수 없으면 OSError, 읽을 수 없는 내용이면 YamlError 다."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise YamlError("UTF-8 로 적힌 글이 아니다. 파일을 UTF-8 로 저장한다") from None
    if "\x00" in text:
        raise YamlError("글이 아닌 것이 들어 있다(NUL 문자)")
    return load_text(text)
