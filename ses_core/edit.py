"""편집 모델: 편집기를 위한 문서 자료구조 (docs/ses-platform/13_editor_data_model.md).

정준 문서(YAML, 이름으로 찾음, 엄격함)와 달리 편집 모델은 다음을 만족한다.
- 요소마다 이름과 별개의 식별자를 가진다. 참조는 식별자로 한다. 이름을 바꿔도
  참조가 끊기지 않는다.
- 불완전하거나 틀린 상태를 그대로 담는다. 끊어진 참조, 뿌리 없음이 표현된다.
  의미상의 문제는 예외가 아니라 진단으로 보고한다 (diagnose.py).
- 순서를 보존한다.
- 모든 변경은 자료로 된 원시 연산 네 가지(넣기, 빼기, 바꾸기, 옮기기)로 이루어지고
  각 연산은 역연산을 가진다. 되돌리기, 다시 하기, 변경 이력이 여기서 나온다.
정준 문서와는 손실 없이 오간다 (from_dict, to_dict).

이 모듈은 언어 중립적인 자료구조의 참조 구현이다. 요소 저장소와 연산은 JSON으로
직렬화된다 (snapshot, op_to_json).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


class EditError(ValueError):
    """잘못된 편집 연산. 저장소의 구조 불변식을 깨는 연산이나 충돌하는 연산."""


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"

    def __deepcopy__(self, memo):
        return self


MISSING = _Missing()        # 속성이나 열쇠가 없음을 뜻하는 표지


@dataclass(frozen=True)
class Ref:
    """다른 요소에 대한 참조.

    target이 있으면 연결된 참조이고 이름은 대상의 현재 이름에서 읽는다.
    target이 없으면 끊어진 참조이고 name이 사용자가 적은 이름이다.
    """
    target: Optional[str] = None
    name: Any = None


def _same(a, b) -> bool:
    """두 값이 같은가. JSON의 값 구분을 따른다: 1과 True, 1과 1.0은 다르다.

    사상은 열쇠의 순서까지 같아야 같다. 순서는 편집기에 보이는 내용이다.
    """
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    return a == b


def _norm(v):
    """저장소에 넣을 값의 사본. 튜플은 목록으로 바꾼다(JSON에 튜플이 없다)."""
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


@dataclass(frozen=True)
class TypeSpec:
    prefix: str
    named: bool                       # name 속성을 가지는가
    refs: Mapping[str, str]           # 참조 속성에서 대상 요소 유형으로
    roles: Mapping[str, tuple]        # 자식 역할에서 허용되는 요소 유형으로


# 요소 유형의 등록부. 편집 모델 자체의 스키마다.
# 요소로 두는 기준: 다른 곳에서 가리킬 수 있거나, 자식을 가지거나, 개별로 골라 옮기는 것.
# 그 밖의 내용(필드 값, 포트, 결합, 식)은 요소의 JSON 속성이며 경로로 고친다.
TYPES: Mapping[str, TypeSpec] = {
    "document": TypeSpec("d", True, {}, {"variables": ("variable",), "entities": ("entity",)}),
    "variable": TypeSpec("v", True, {}, {}),
    "entity": TypeSpec("e", True, {"extends": "entity"},
                       {"links": ("link",), "aspects": ("aspect",),
                        "multi_aspects": ("multi_aspect",), "specializations": ("specialization",)}),
    "aspect": TypeSpec("a", True, {}, {"parts": ("part",)}),
    "part": TypeSpec("p", False, {"def": "entity"}, {}),
    "multi_aspect": TypeSpec("m", True, {"part": "entity"}, {}),
    "specialization": TypeSpec("s", True, {"default": "entity"}, {"alternatives": ("alternative",)}),
    "alternative": TypeSpec("o", False, {"def": "entity"}, {}),
    "link": TypeSpec("l", False, {"target": "entity"}, {}),
}

# 같은 이름을 가질 수 없는 범위. 엔티티 안의 aspect, multi-aspect, specialization은
# 한 범위를 이룬다 (valid brothers).
_SIBLING_SCOPE = ("aspects", "multi_aspects", "specializations")


@dataclass
class Element:
    id: str
    type: str
    parent: Optional[str]
    role: Optional[str]
    props: dict
    children: dict
    rev: int = 0


# ---------------------------------------------------------------------------
# 원시 연산: 자료로 된 변경
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Insert:
    """자식이 없는 요소를 넣는다."""
    id: str
    type: str
    parent: Optional[str]
    role: Optional[str]
    index: int
    props: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Remove:
    """자식이 없는 요소를 뺀다."""
    id: str


@dataclass(frozen=True)
class Set:
    """속성의 값을 바꾼다. path의 첫 요소는 속성 이름, 나머지는 그 안의 열쇠나 위치다.

    old는 지금 값이어야 한다. 다르면 충돌이다. 없는 열쇠는 MISSING으로 적는다.
    at은 사상에 새 열쇠를 넣을 자리다(없으면 맨 끝). 열쇠를 지우는 연산의 역연산이
    이것으로 원래 자리를 되살린다. 열쇠의 순서는 편집기에 보이는 내용이다.
    목록에서는 있는 항목을 바꾸거나, 끝에 붙이거나, 마지막 항목을 지울 수 있다.
    """
    id: str
    path: tuple
    old: Any
    new: Any
    at: Optional[int] = None


@dataclass(frozen=True)
class Move:
    """요소를 다른 부모나 다른 자리로 옮긴다. index는 빼낸 뒤의 목록 기준이다."""
    id: str
    parent: str
    role: str
    index: int


def _is_index(key) -> bool:
    return isinstance(key, int) and not isinstance(key, bool)


def _get_in(container, path):
    cur = container
    for key in path:
        if isinstance(cur, dict):
            if key not in cur:
                return MISSING
            cur = cur[key]
        elif isinstance(cur, list):
            if not _is_index(key) or not 0 <= key < len(cur):
                return MISSING
            cur = cur[key]
        else:
            return MISSING
    return cur


def _locate(container, path):
    """path의 마지막 열쇠가 놓일 그릇을 찾는다."""
    cur = container
    for key in path[:-1]:
        nxt = _get_in(cur, (key,))
        if nxt is MISSING:
            raise EditError(f"경로 {path} 의 중간 {key!r} 이 없다")
        cur = nxt
    last = path[-1]
    if isinstance(cur, dict):
        try:
            hash(last)
        except TypeError:
            raise EditError(f"열쇠가 될 수 없는 값: {last!r}") from None
    elif isinstance(cur, list):
        if not _is_index(last):
            raise EditError(f"목록의 위치는 정수여야 한다: {last!r}")
    else:
        raise EditError(f"경로 {path} 는 값을 담을 수 없는 곳을 가리킨다")
    return cur, last


def _set_in(container, path, value, at: Optional[int] = None) -> Optional[int]:
    """값을 넣거나 바꾸거나 지운다. 사상에서 열쇠를 지웠으면 그 열쇠가 있던 자리를 돌려준다."""
    cur, last = _locate(container, path)
    if isinstance(cur, dict):
        if value is MISSING:
            if last not in cur:
                return None
            where = list(cur).index(last)
            del cur[last]
            return where
        if last in cur or at is None or at >= len(cur):
            cur[last] = value
        else:
            if at < 0:
                raise EditError(f"자리 {at} 가 범위를 벗어났다")
            items = list(cur.items())
            items.insert(at, (last, value))
            cur.clear()
            cur.update(items)
        return None
    if value is MISSING:
        if last != len(cur) - 1:
            raise EditError("목록에서는 마지막 항목만 지울 수 있다")
        cur.pop()
    elif last == len(cur):
        cur.append(value)
    elif 0 <= last < len(cur):
        cur[last] = value
    else:
        raise EditError(f"목록 위치 {last} 가 범위를 벗어났다")
    return None


class Model:
    """요소 저장소. 식별자에서 요소로 가는 평평한 표와 부모 자식 관계로 이루어진다."""

    def __init__(self) -> None:
        self.elements: dict = {}
        self.root: Optional[str] = None
        self.revision = 0
        self._counter = 0
        self._incoming: dict = {}        # 대상 식별자에서 {(가진 요소, 속성 이름)}으로
        self.import_issues: list = []    # 읽을 때 담지 못한 곳: (위치, 설명)

    # 기본 조회 -----------------------------------------------------------

    def new_id(self, type: str) -> str:
        self._counter += 1
        return f"{TYPES[type].prefix}{self._counter}"

    def get(self, id: str) -> Element:
        try:
            return self.elements[id]
        except KeyError:
            raise EditError(f"요소 {id} 가 없다") from None

    def kids(self, id: str, role: Optional[str] = None) -> list:
        el = self.get(id)
        roles = [role] if role is not None else list(el.children)
        return [self.elements[c] for r in roles for c in el.children.get(r, [])]

    def of_type(self, type: str) -> list:
        """그 유형의 요소 전체. 문서 순서(깊이 우선)."""
        out = []

        def walk(id):
            el = self.elements[id]
            if el.type == type:
                out.append(el)
            for r in el.children:
                for c in el.children[r]:
                    walk(c)

        if self.root is not None:
            walk(self.root)
        return out

    def all(self) -> list:
        out = []

        def walk(id):
            el = self.elements[id]
            out.append(el)
            for r in el.children:
                for c in el.children[r]:
                    walk(c)

        if self.root is not None:
            walk(self.root)
        return out

    # 원시 연산의 적용 ------------------------------------------------------

    def _touch(self, *ids) -> None:
        self.revision += 1
        for i in ids:
            if i is not None and i in self.elements:
                self.elements[i].rev = self.revision

    def _check_ref(self, holder_id: str, holder_type: str, prop: str, value) -> None:
        """참조 속성의 값은 Ref여야 하고, 연결된 참조의 대상은 맞는 유형으로 있어야 한다."""
        if not isinstance(value, Ref):
            raise EditError(f"{holder_type} 의 {prop} 은 참조여야 한다: {value!r}")
        if value.target is None or value.target == holder_id:
            return
        target = self.elements.get(value.target)
        if target is None:
            raise EditError(f"참조의 대상 {value.target} 이 없다")
        if target.type != TYPES[holder_type].refs[prop]:
            raise EditError(f"{holder_type} 의 {prop} 은 {target.type} 을 가리킬 수 없다")

    def _index(self, holder_id: str, prop: str, value, add: bool) -> None:
        if isinstance(value, Ref) and value.target is not None:
            if add:
                self._incoming.setdefault(value.target, set()).add((holder_id, prop))
            else:
                self._incoming.get(value.target, set()).discard((holder_id, prop))

    def apply(self, op):
        """연산을 적용하고 역연산을 돌려준다. 실패하면 저장소는 바뀌지 않는다."""
        if isinstance(op, Insert):
            if op.id in self.elements:
                raise EditError(f"요소 {op.id} 가 이미 있다")
            spec = TYPES.get(op.type)
            if spec is None:
                raise EditError(f"알 수 없는 요소 유형 {op.type}")
            props = _norm(dict(op.props))
            for prop in spec.refs:
                if prop in props:
                    self._check_ref(op.id, op.type, prop, props[prop])
            if op.parent is None:
                if op.type != "document" or self.root is not None:
                    raise EditError("부모 없는 요소는 문서 하나뿐이다")
            else:
                parent = self.get(op.parent)
                allowed = TYPES[parent.type].roles.get(op.role)
                if allowed is None or op.type not in allowed:
                    raise EditError(f"{parent.type} 의 {op.role} 에 {op.type} 을 둘 수 없다")
                siblings = parent.children[op.role]
                if not 0 <= op.index <= len(siblings):
                    raise EditError(f"위치 {op.index} 가 범위를 벗어났다")
                siblings.insert(op.index, op.id)
            self.elements[op.id] = Element(op.id, op.type, op.parent, op.role, props,
                                           {r: [] for r in spec.roles})
            for prop in spec.refs:
                self._index(op.id, prop, props.get(prop), True)
            if op.parent is None:
                self.root = op.id
            num = op.id[len(spec.prefix):]
            if num.isdigit():
                self._counter = max(self._counter, int(num))
            self._touch(op.id, op.parent)
            return Remove(op.id)

        if isinstance(op, Remove):
            el = self.get(op.id)
            if any(el.children[r] for r in el.children):
                raise EditError(f"요소 {op.id} 에 자식이 남아 있다")
            if any(holder != op.id for holder, _ in self._incoming.get(op.id, ())):
                raise EditError(f"요소 {op.id} 를 가리키는 참조가 남아 있다")
            index = 0
            if el.parent is not None:
                siblings = self.elements[el.parent].children[el.role]
                index = siblings.index(op.id)
                siblings.pop(index)
            else:
                self.root = None
            for prop in TYPES[el.type].refs:
                self._index(op.id, prop, el.props.get(prop), False)
            self._incoming.pop(op.id, None)
            del self.elements[op.id]
            self._touch(el.parent)
            return Insert(op.id, el.type, el.parent, el.role, index, _norm(el.props))

        if isinstance(op, Set):
            el = self.get(op.id)
            if not op.path:
                raise EditError("빈 경로")
            current = _get_in(el.props, op.path)
            if not _same(current, op.old):
                raise EditError(f"충돌: {op.id} 의 {op.path} 는 {current!r} 인데 {op.old!r} 를 기대했다")
            new = _norm(op.new)
            is_ref = op.path[0] in TYPES[el.type].refs
            if is_ref:
                if len(op.path) != 1:
                    raise EditError("참조 속성의 안쪽은 고칠 수 없다")
                if new is not MISSING:
                    self._check_ref(op.id, el.type, op.path[0], new)
            where = _set_in(el.props, op.path, new, op.at)
            if is_ref:
                self._index(op.id, op.path[0], current, False)
                self._index(op.id, op.path[0], new, True)
            self._touch(op.id)
            return Set(op.id, op.path, _norm(op.new), _norm(current), where)

        if isinstance(op, Move):
            el = self.get(op.id)
            if el.parent is None:
                raise EditError("문서는 옮길 수 없다")
            target = self.get(op.parent)
            allowed = TYPES[target.type].roles.get(op.role)
            if allowed is None or el.type not in allowed:
                raise EditError(f"{target.type} 의 {op.role} 에 {el.type} 을 둘 수 없다")
            cur = op.parent
            while cur is not None:                       # 자기 자손 아래로 옮길 수 없다
                if cur == op.id:
                    raise EditError("요소를 자기 자손 아래로 옮길 수 없다")
                cur = self.elements[cur].parent
            old_parent, old_role = el.parent, el.role
            siblings = self.elements[old_parent].children[old_role]
            old_index = siblings.index(op.id)
            siblings.pop(old_index)
            dest = target.children[op.role]
            if not 0 <= op.index <= len(dest):
                siblings.insert(old_index, op.id)
                raise EditError(f"위치 {op.index} 가 범위를 벗어났다")
            dest.insert(op.index, op.id)
            el.parent, el.role = op.parent, op.role
            self._touch(op.id, old_parent, op.parent)
            return Move(op.id, old_parent, old_role, old_index)

        raise EditError(f"알 수 없는 연산 {op!r}")

    # 이름과 주소 ----------------------------------------------------------

    def ref_name(self, ref: Optional[Ref]) -> Optional[str]:
        """참조가 가리키는 이름. 연결되어 있으면 대상의 현재 이름."""
        if ref is None or ref is MISSING:
            return None
        if ref.target is not None and ref.target in self.elements:
            return self.elements[ref.target].props.get("name")
        return ref.name

    def resolved(self, ref) -> Optional[Element]:
        if isinstance(ref, Ref) and ref.target is not None:
            return self.elements.get(ref.target)
        return None

    def label(self, id: str) -> str:
        """요소를 사람에게 보일 이름."""
        el = self.get(id)
        if TYPES[el.type].named:
            return str(el.props.get("name", ""))
        if el.type == "part":
            return el.props.get("alias") or self.ref_name(el.props.get("def")) or "?"
        if el.type == "alternative":
            return self.ref_name(el.props.get("def")) or "?"
        if el.type == "link":
            return f"{el.props.get('type', '?')}:{self.ref_name(el.props.get('target')) or '?'}"
        return el.id

    def address(self, id: str) -> str:
        """요소의 주소: 뿌리에서부터 역할과 이름을 이은 것.

        주소는 파일에 남기는 식별 수단이다(표시 정보, 주석, 진단). 형제 사이에
        같은 이름이 있으면 순번을 붙인다.
        """
        parts = []
        cur = self.get(id)
        while cur.parent is not None:
            parent = self.elements[cur.parent]
            name = self.label(cur.id)
            same = [c for c in parent.children[cur.role] if self.label(c) == name]
            seg = f"{cur.role}/{name}"
            if len(same) > 1:
                seg += f"#{same.index(cur.id)}"
            parts.append(seg)
            cur = parent
        return "/".join(reversed(parts))

    def addresses(self) -> dict:
        return {el.id: self.address(el.id) for el in self.all()}

    def find(self, address: str) -> Optional[str]:
        """주소로 요소를 찾는다."""
        if address == "":
            return self.root
        for el in self.all():
            if self.address(el.id) == address:
                return el.id
        return None

    def by_name(self, type: str, name: str) -> list:
        return [el.id for el in self.of_type(type) if el.props.get("name") == name]

    def entity(self, name: str) -> Optional[str]:
        found = self.by_name("entity", name)
        return found[0] if found else None

    def entity_of(self, id: str) -> Optional[str]:
        """요소가 속한 엔티티."""
        cur = self.elements.get(id)
        while cur is not None and cur.type != "entity":
            cur = self.elements.get(cur.parent) if cur.parent else None
        return cur.id if cur is not None else None

    # 참조 ---------------------------------------------------------------

    def refs_to(self, id: str) -> list:
        """이 요소를 가리키는 (요소 식별자, 속성 이름)의 목록. 역참조 색인에서 읽는다."""
        return sorted(self._incoming.get(id, ()))

    def scan_refs(self) -> dict:
        """참조 속성을 모두 훑어 만든 역참조 표. 색인의 정의이며 검사에 쓴다."""
        out: dict = {}
        for el in self.elements.values():
            for prop in TYPES[el.type].refs:
                ref = el.props.get(prop)
                if isinstance(ref, Ref) and ref.target is not None:
                    out.setdefault(ref.target, set()).add((el.id, prop))
        return out

    def check_invariants(self) -> list:
        """저장소의 구조 불변식을 처음부터 검사한다. 위반의 설명 목록을 돌려준다.

        원시 연산은 이 불변식을 지킨다. 바깥에서 받은 스냅숏을 읽을 때와 시험에서 쓴다.
        """
        out: list = []
        tops = [e.id for e in self.elements.values() if e.parent is None]
        if self.root is None:
            if self.elements:
                out.append("뿌리가 없는데 요소가 있다")
            return out
        if tops != [self.root] or self.elements[self.root].type != "document":
            out.append("부모 없는 요소는 문서 하나여야 한다")
        seen: set = set()

        def walk(id) -> None:
            if id in seen:
                out.append(f"{id} 가 두 번 나타난다")
                return
            seen.add(id)
            el = self.elements[id]
            spec = TYPES.get(el.type)
            if spec is None:
                out.append(f"{id} 의 유형 {el.type} 을 알 수 없다")
                return
            if set(el.children) != set(spec.roles):
                out.append(f"{id} 의 자식 역할이 유형과 맞지 않는다")
            for role, kids in el.children.items():
                for c in kids:
                    child = self.elements.get(c)
                    if child is None:
                        out.append(f"{id} 의 자식 {c} 가 없다")
                        continue
                    if child.parent != id or child.role != role:
                        out.append(f"{c} 의 부모 기록이 {id}/{role} 과 맞지 않는다")
                    if child.type not in spec.roles.get(role, ()):
                        out.append(f"{el.type} 의 {role} 에 {child.type} 이 있다")
                    walk(c)
            for prop in spec.refs:
                if prop in el.props:
                    try:
                        self._check_ref(id, el.type, prop, el.props[prop])
                    except EditError as e:
                        out.append(f"{id}: {e}")

        walk(self.root)
        if seen != set(self.elements):
            out.append("뿌리에서 닿지 않는 요소가 있다")
        scan = self.scan_refs()
        index = {k: v for k, v in self._incoming.items() if v}
        if scan != index:
            out.append("역참조 색인이 참조 속성과 맞지 않는다")
        return out

    def users(self, entity_id: str) -> set:
        """이 엔티티를 부분, 대안, 복제 대상으로 쓰는 엔티티들."""
        out = set()
        for eid, prop in self.refs_to(entity_id):
            el = self.elements[eid]
            if el.type in ("part", "alternative", "multi_aspect"):
                owner = self.entity_of(eid)
                if owner is not None:
                    out.add(owner)
        return out

    def dependents(self, entity_ids) -> set:
        """주어진 엔티티가 바뀌면 다시 분석해야 하는 엔티티들 (자신 포함)."""
        seen = set(entity_ids)
        stack = list(entity_ids)
        while stack:
            for u in self.users(stack.pop()):
                if u not in seen:
                    seen.add(u)
                    stack.append(u)
        return seen

    def changed_entities(self, since: int) -> set:
        """개정 번호 since 뒤에 바뀐 요소가 속한 엔티티들."""
        out = set()
        for el in self.all():
            if el.rev > since:
                owner = self.entity_of(el.id)
                if owner is not None:
                    out.add(owner)
        return out

    # 스냅숏 -------------------------------------------------------------

    def snapshot(self) -> dict:
        """언어 중립적인 JSON 형태의 저장소 전체."""
        return {"format": "ses-edit/1", "root": self.root,
                "elements": {el.id: {"type": el.type, "parent": el.parent, "role": el.role,
                                     "props": _encode(el.props),
                                     "children": {r: list(c) for r, c in el.children.items()}}
                             for el in self.all()}}            # 문서 순서. 편집 이력과 무관하다

    @staticmethod
    def from_snapshot(snap: dict) -> "Model":
        """스냅숏에서 저장소를 되살린다. 구조 불변식을 어긴 스냅숏은 거부한다."""
        if snap.get("format") != "ses-edit/1":
            raise EditError(f"알 수 없는 스냅숏 형식 {snap.get('format')!r}")
        m = Model()
        for id, e in snap["elements"].items():
            m.elements[id] = Element(id, e["type"], e["parent"], e["role"], _decode(e["props"]),
                                     {r: list(c) for r, c in e["children"].items()})
            digits = "".join(ch for ch in id if ch.isdigit())
            if digits:
                m._counter = max(m._counter, int(digits))
        m.root = snap["root"]
        m._incoming = m.scan_refs()
        problems = m.check_invariants()
        if problems:
            raise EditError("스냅숏이 구조 불변식을 어긴다: " + "; ".join(problems[:5]))
        return m


# ---------------------------------------------------------------------------
# JSON 부호화: 참조와 MISSING 표지
# ---------------------------------------------------------------------------

def _encode(v):
    if isinstance(v, Ref):
        return {"$ref": v.target, "name": v.name}
    if v is MISSING:
        return {"$missing": True}
    if isinstance(v, dict):
        return {k: _encode(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_encode(x) for x in v]
    return v


def _decode(v):
    if isinstance(v, dict):
        if set(v) == {"$ref", "name"}:
            return Ref(v["$ref"], v["name"])
        if v == {"$missing": True}:
            return MISSING
        return {k: _decode(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_decode(x) for x in v]
    return v


def op_to_json(op) -> dict:
    if isinstance(op, Insert):
        return {"op": "insert", "id": op.id, "type": op.type, "parent": op.parent,
                "role": op.role, "index": op.index, "props": _encode(dict(op.props))}
    if isinstance(op, Remove):
        return {"op": "remove", "id": op.id}
    if isinstance(op, Set):
        out = {"op": "set", "id": op.id, "path": list(op.path),
               "old": _encode(op.old), "new": _encode(op.new)}
        if op.at is not None:
            out["at"] = op.at
        return out
    if isinstance(op, Move):
        return {"op": "move", "id": op.id, "parent": op.parent, "role": op.role, "index": op.index}
    raise EditError(f"알 수 없는 연산 {op!r}")


def op_from_json(d: dict):
    kind = d["op"]
    if kind == "insert":
        return Insert(d["id"], d["type"], d["parent"], d["role"], d["index"], _decode(d["props"]))
    if kind == "remove":
        return Remove(d["id"])
    if kind == "set":
        return Set(d["id"], tuple(d["path"]), _decode(d["old"]), _decode(d["new"]), d.get("at"))
    if kind == "move":
        return Move(d["id"], d["parent"], d["role"], d["index"])
    raise EditError(f"알 수 없는 연산 {kind}")


# ---------------------------------------------------------------------------
# 이력: 거래, 되돌리기, 다시 하기
# ---------------------------------------------------------------------------

class History:
    """연산을 거래 단위로 묶어 되돌리고 다시 한다. log는 적용된 연산의 기록이다."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self.undo_stack: list = []       # (이름, [(연산, 역연산)])
        self.redo_stack: list = []
        self._open: Optional[list] = None
        self._label: Optional[str] = None
        self._depth = 0

    @contextmanager
    def transaction(self, label: str):
        """거래 하나. 안에서 예외가 나면 그 거래의 연산을 모두 되돌린다."""
        outer = self._depth > 0
        if not outer:
            self._open, self._label = [], label
        self._depth += 1
        try:
            yield
        except BaseException:
            self._depth -= 1
            if not outer:
                for _, inv in reversed(self._open):
                    self.model.apply(inv)
                self._open = None
            raise
        self._depth -= 1
        if not outer:
            if self._open:
                self.undo_stack.append((self._label, self._open))
                self.redo_stack.clear()
            self._open = None

    def apply(self, op):
        if self._depth == 0:
            with self.transaction(type(op).__name__):
                return self.apply(op)
        inverse = self.model.apply(op)
        self._open.append((op, inverse))
        return inverse

    def undo(self) -> Optional[str]:
        if not self.undo_stack:
            return None
        label, ops = self.undo_stack.pop()
        redo = []
        for op, inverse in reversed(ops):
            redo.append((inverse, self.model.apply(inverse)))
        self.redo_stack.append((label, redo))
        return label

    def redo(self) -> Optional[str]:
        if not self.redo_stack:
            return None
        label, ops = self.redo_stack.pop()
        undo = []
        for op, inverse in reversed(ops):
            undo.append((inverse, self.model.apply(inverse)))
        self.undo_stack.append((label, undo))
        return label

    def log(self) -> list:
        """지금까지의 거래를 JSON으로. 다른 저장소에 차례로 적용하면 같은 상태가 된다."""
        return [{"label": label, "ops": [op_to_json(op) for op, _ in ops]}
                for label, ops in self.undo_stack]


# ---------------------------------------------------------------------------
# 정준 문서와의 왕복
# ---------------------------------------------------------------------------

# 정준 순서: 정준 문서에 열쇠를 쓰는 순서. 저장한 파일이 편집 이력과 무관하게 정해지도록 고정한다.
_DOC_HEAD = ("ses", "name", "version", "description", "profile")
_DOC_TAIL = ("constraints", "experimental_frames", "metadata")
_DOC_KEYS = _DOC_HEAD + ("port_types",) + _DOC_TAIL
_ENTITY_PLAIN = ("root", "kind", "fields", "ports", "attributes", "stereotype", "doc", "metadata")
_ENTITY_KEYS = _ENTITY_PLAIN + ("extends", "links", "aspects", "multi_aspects", "specializations")
_ASPECT_PLAIN = ("couplings", "rule", "priority", "doc")
_MULTI_PLAIN = ("cardinality", "naming", "couplings", "rule", "priority", "doc")
_SPEC_PLAIN = ("select", "doc")


def from_dict(d) -> Model:
    """정준 문서(YAML을 읽은 사전)를 편집 모델로.

    의미상의 문제(끊어진 이름, 뿌리 없음, 빠진 열쇠)로 실패하지 않는다. 그런 문서도
    그대로 담는다. 모양이 틀려 담을 수 없는 곳(사상 자리에 목록 등)은 건너뛰고
    import_issues에 적는다. 조용히 버리는 것은 없다.
    """
    m = Model()
    issues = m.import_issues

    def mapping(x, where) -> dict:
        if x is None:
            return {}
        if isinstance(x, dict):
            return x
        issues.append((where, f"사상이어야 하는데 {type(x).__name__} 이다. 읽지 않았다"))
        return {}

    def sequence(x, where) -> list:
        if x is None:
            return []
        if isinstance(x, list):
            return x
        issues.append((where, f"목록이어야 하는데 {type(x).__name__} 이다. 읽지 않았다"))
        return []

    def insert(type, parent, role, props) -> str:
        id = m.new_id(type)
        index = len(m.elements[parent].children[role]) if parent is not None else 0
        m.apply(Insert(id, type, parent, role, index, props))
        return id

    def plain(body, keys, known) -> dict:
        p = {k: body[k] for k in keys if k in body}
        extra = {k: v for k, v in body.items() if k not in known}
        if extra:
            p["extra"] = extra
        return p

    d = mapping(d, "")
    doc = insert("document", None, None, plain(d, _DOC_KEYS, _DOC_KEYS + ("variables", "entities")))

    for name, spec in mapping(d.get("variables"), "variables").items():
        insert("variable", doc, "variables", {"name": name, "spec": spec})

    ids: dict = {}
    bodies: dict = {}
    for name, body in mapping(d.get("entities"), "entities").items():
        body = mapping(body, f"entities/{name}")
        ids[name] = insert("entity", doc, "entities",
                           dict(name=name, **plain(body, _ENTITY_PLAIN, _ENTITY_KEYS)))
        bodies[name] = body

    def ref(name) -> Ref:
        try:
            if name in ids:
                return Ref(ids[name], None)
        except TypeError:                       # 사전의 열쇠가 될 수 없는 값
            pass
        return Ref(None, name)

    def part_props(x, prop) -> dict:
        if not isinstance(x, dict):
            return {prop: ref(x)}
        p = {prop: ref(x.get("def"))}
        if x.get("alias") is not None:
            p["alias"] = x["alias"]
        extra = {k: v for k, v in x.items() if k not in ("def", "alias")}
        if extra:
            p["part_extra"] = extra
        return p

    for name, body in bodies.items():
        eid = ids[name]
        where = f"entities/{name}"
        if "extends" in body:
            m.apply(Set(eid, ("extends",), MISSING, ref(body["extends"])))
        for ltype, targets in mapping(body.get("links"), f"{where}/links").items():
            for t in sequence(targets, f"{where}/links/{ltype}"):
                insert("link", eid, "links", {"type": ltype, "target": ref(t)})
        for aname, a in mapping(body.get("aspects"), f"{where}/aspects").items():
            a = mapping(a, f"{where}/aspects/{aname}")
            aid = insert("aspect", eid, "aspects",
                         dict(name=aname, **plain(a, _ASPECT_PLAIN, _ASPECT_PLAIN + ("parts",))))
            for part in sequence(a.get("parts"), f"{where}/aspects/{aname}/parts"):
                insert("part", aid, "parts", part_props(part, "def"))
        for mname, ma in mapping(body.get("multi_aspects"), f"{where}/multi_aspects").items():
            ma = mapping(ma, f"{where}/multi_aspects/{mname}")
            p = dict(name=mname, **plain(ma, _MULTI_PLAIN, _MULTI_PLAIN + ("part",)))
            if "part" in ma:
                p.update(part_props(ma["part"], "part"))
            insert("multi_aspect", eid, "multi_aspects", p)
        for sname, sp in mapping(body.get("specializations"), f"{where}/specializations").items():
            sp = mapping(sp, f"{where}/specializations/{sname}")
            p = dict(name=sname, **plain(sp, _SPEC_PLAIN, _SPEC_PLAIN + ("alternatives", "default")))
            if "default" in sp:
                p["default"] = ref(sp["default"])
            sid = insert("specialization", eid, "specializations", p)
            for alt in sequence(sp.get("alternatives"), f"{where}/specializations/{sname}/alternatives"):
                insert("alternative", sid, "alternatives", {"def": ref(alt)})
    m.revision = 0
    for el in m.elements.values():
        el.rev = 0
    return m


def to_dict(m: Model) -> dict:
    """편집 모델을 정준 문서로. 열쇠는 정준 순서로 쓴다.

    정준 문서는 이름으로 찾는 형식이다. 이름이 없거나 겹치는 요소가 있으면 담을 수
    없으므로 실패한다. 그런 상태는 스냅숏으로 저장한다. 끊어진 참조는 적힌 이름
    그대로 나간다.
    """
    if m.root is None:
        raise EditError("문서가 없다")
    doc = m.get(m.root)
    out: dict = {}

    def put(target, source, keys) -> None:
        for k in keys:
            if k in source:
                target[k] = _norm(source[k])

    def named(elements, what) -> dict:
        result = {}
        for el in elements:
            name = el.props.get("name")
            try:
                clash = name in result
            except TypeError:
                raise EditError(f"{what} 이름 {name!r} 은 정준 문서의 열쇠가 될 수 없다") from None
            if name is None or name == "":
                raise EditError(f"이름 없는 {what} 은 정준 문서로 쓸 수 없다")
            if clash:
                raise EditError(f"{what} 이름 {name!r} 이 겹쳐 정준 문서로 쓸 수 없다")
            result[name] = el
        return result

    def part_out(el, prop):
        name = m.ref_name(el.props.get(prop))
        extra = el.props.get("part_extra")
        if el.props.get("alias") is None and not extra:
            return name
        body = {"def": name}
        if el.props.get("alias") is not None:
            body["alias"] = el.props["alias"]
        body.update(_norm(extra or {}))
        return body

    put(out, doc.props, _DOC_HEAD)
    variables = named(m.kids(doc.id, "variables"), "변수")
    if variables:
        out["variables"] = {n: _norm(el.props.get("spec", {})) for n, el in variables.items()}
    put(out, doc.props, ("port_types",))

    entities = {}
    for name, el in named(m.kids(doc.id, "entities"), "엔티티").items():
        body: dict = {}
        put(body, el.props, ("root", "kind"))
        if "extends" in el.props:
            body["extends"] = m.ref_name(el.props["extends"])
        put(body, el.props, ("fields",))
        links: dict = {}
        for l in m.kids(el.id, "links"):
            try:
                links.setdefault(l.props.get("type"), []).append(m.ref_name(l.props.get("target")))
            except TypeError:
                raise EditError(f"{name} 의 관계 유형 {l.props.get('type')!r} 은 열쇠가 될 수 없다") from None
        if links:
            body["links"] = links
        put(body, el.props, ("ports", "attributes", "stereotype", "doc"))
        scope = named(m.kids(el.id, "aspects"), f"{name} 의 aspect")
        if scope:
            body["aspects"] = {}
            for aname, a in scope.items():
                ab: dict = {"parts": [part_out(p, "def") for p in m.kids(a.id, "parts")]}
                put(ab, a.props, _ASPECT_PLAIN)
                ab.update(_norm(a.props.get("extra", {})))
                body["aspects"][aname] = ab
        scope = named(m.kids(el.id, "multi_aspects"), f"{name} 의 multi-aspect")
        if scope:
            body["multi_aspects"] = {}
            for mname, ma in scope.items():
                mb: dict = {}
                if "part" in ma.props:
                    mb["part"] = part_out(ma, "part")
                put(mb, ma.props, _MULTI_PLAIN)
                mb.update(_norm(ma.props.get("extra", {})))
                body["multi_aspects"][mname] = mb
        scope = named(m.kids(el.id, "specializations"), f"{name} 의 specialization")
        if scope:
            body["specializations"] = {}
            for sname, sp in scope.items():
                sb: dict = {"alternatives": [m.ref_name(o.props.get("def"))
                                             for o in m.kids(sp.id, "alternatives")]}
                put(sb, sp.props, ("select",))
                if "default" in sp.props:
                    sb["default"] = m.ref_name(sp.props["default"])
                put(sb, sp.props, ("doc",))
                sb.update(_norm(sp.props.get("extra", {})))
                body["specializations"][sname] = sb
        put(body, el.props, ("metadata",))
        body.update(_norm(el.props.get("extra", {})))
        entities[name] = body
    out["entities"] = entities
    put(out, doc.props, _DOC_TAIL)
    out.update(_norm(doc.props.get("extra", {})))
    return out


def load(path: str) -> Model:
    import yaml
    with open(path, encoding="utf-8") as f:
        return from_dict(yaml.safe_load(f))


def dump(m: Model) -> str:
    import yaml
    return yaml.safe_dump(to_dict(m), allow_unicode=True, sort_keys=False)


def new_document(name: str, profile: Optional[str] = None) -> Model:
    d = {"ses": "1.0", "name": name, "entities": {}}
    if profile is not None:
        d["profile"] = profile
    return from_dict(d)


# ---------------------------------------------------------------------------
# 명령: SES의 뜻을 아는 편집. 원시 연산의 거래로 풀린다
# ---------------------------------------------------------------------------

def _rewrite(obj, fn):
    """JSON 값을 돌며 fn이 None이 아닌 값을 돌려주는 곳을 그 값으로 바꾼 사본."""
    replaced = fn(obj)
    if replaced is not None:
        return replaced
    if isinstance(obj, dict):
        return {k: _rewrite(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite(v, fn) for v in obj]
    return obj


@dataclass(frozen=True)
class Renamed:
    """이름 바꾸기의 결과. 이름으로 적힌 바깥 자료(결정 집합, 표시 정보, 주석)를
    따라 고치는 데 쓴다."""
    type: str                          # entity, variable, aspect, multi_aspect, specialization
    old: Any
    new: str
    owner: Optional[str]               # aspect, multi-aspect, specialization의 소유 엔티티 이름
    addresses: Mapping[str, str]       # 옛 주소에서 새 주소로


class Editor:
    """편집 세션. 저장소와 이력을 가지고 명령을 제공한다.

    명령은 SES의 뜻을 아는 편집이다. 원시 연산의 거래 하나로 풀리므로 한 번에
    되돌려진다. 명령은 이름의 유일성처럼 저장소가 강제하지 않는 규칙을 지킨다.
    """

    def __init__(self, model: Model) -> None:
        self.model = model
        self.history = History(model)

    # 도우미 --------------------------------------------------------------

    def _insert(self, type, parent, role, props, index=None) -> str:
        id = self.model.new_id(type)
        if index is None:
            index = len(self.model.get(parent).children[role])
        self.history.apply(Insert(id, type, parent, role, index, props))
        return id

    def set(self, id: str, path, value) -> None:
        """속성의 값을 바꾼다. 값이 같으면 아무 일도 하지 않는다. MISSING이면 지운다."""
        path = (path,) if isinstance(path, str) else tuple(path)
        old = _get_in(self.model.get(id).props, path)
        if not _same(old, value):
            self.history.apply(Set(id, path, _norm(old), value))

    def _check_name(self, type: str, parent: str, name: str, skip: Optional[str] = None) -> None:
        if not isinstance(name, str) or not name:
            raise EditError("이름이 비어 있다")
        m = self.model
        if type in ("entity", "variable"):
            others = m.of_type(type)
        else:
            others = [el for r in _SIBLING_SCOPE for el in m.kids(parent, r)]
        if any(el.id != skip and el.props.get("name") == name for el in others):
            raise EditError(f"이름 {name!r} 이 이미 쓰이고 있다")

    def undo(self):
        return self.history.undo()

    def redo(self):
        return self.history.redo()

    # 엔티티 --------------------------------------------------------------

    def add_entity(self, name: str, kind: Optional[str] = None, root: bool = False, **props) -> str:
        self._check_name("entity", self.model.root, name)
        p = {"name": name}
        if kind is not None:
            p["kind"] = kind
        if root:
            p["root"] = True
        p.update(props)
        with self.history.transaction(f"엔티티 {name} 추가"):
            return self._insert("entity", self.model.root, "entities", p)

    def add_variable(self, name: str, spec: dict) -> str:
        self._check_name("variable", self.model.root, name)
        with self.history.transaction(f"변수 {name} 추가"):
            return self._insert("variable", self.model.root, "variables", {"name": name, "spec": spec})

    def rename(self, id: str, new: str) -> Optional[Renamed]:
        """이름을 바꾼다.

        참조는 식별자로 이어져 있어 고칠 것이 없다. 이름이 글자로 적힌 곳(선택 규칙의
        then과 else, 결합의 끝점, 식의 변수 이름, 실험 프레임의 붙는 곳, 문서 조립의
        구분자 표)은 같은 거래에서 함께 고친다.
        """
        m = self.model
        el = m.get(id)
        if not TYPES[el.type].named or el.type == "document":
            raise EditError(f"{el.type} 의 이름은 이 명령으로 바꾸지 않는다")
        old = el.props.get("name")
        if old == new:
            return None
        self._check_name(el.type, el.parent, new, skip=id)
        before = m.addresses()
        with self.history.transaction(f"{old} 의 이름을 {new} 로"):
            self.set(id, "name", new)
            if el.type == "entity":
                self._rewrite_entity_mentions(id, old, new)
            elif el.type == "variable":
                self._rewrite_variable_mentions(old, new)
            elif el.type == "aspect":
                self._rewrite_separator_key(el.parent, old, new)
        after = m.addresses()
        owner = m.get(el.parent).props.get("name") if el.type not in ("entity", "variable") else None
        return Renamed(el.type, old, new, owner,
                       {before[i]: after[i] for i in before if i in after and before[i] != after[i]})

    def _rewrite_endpoints(self, aspect_id: str, old, new) -> None:
        """aspect의 결합에서 부분 이름 old로 적힌 끝점을 new로 고친다."""
        couplings = self.model.get(aspect_id).props.get("couplings")
        if not isinstance(couplings, list) or not isinstance(old, str) or not isinstance(new, str):
            return
        out = []
        for c in couplings:
            if isinstance(c, dict):
                c = dict(c)
                for key in ("from", "to"):
                    v = c.get(key)
                    if isinstance(v, str) and v.startswith(old + "."):
                        c[key] = new + v[len(old):]
            out.append(c)
        self.set(aspect_id, "couplings", out)

    def _rewrite_entity_mentions(self, id: str, old, new: str) -> None:
        m = self.model
        for eid, prop in m.refs_to(id):
            el = m.get(eid)
            if el.type == "alternative":                 # 선택 규칙의 then, else
                spec = m.get(el.parent)
                select = spec.props.get("select")
                if select is not None:
                    def fix(obj):
                        if isinstance(obj, dict) and ("then" in obj or "else" in obj):
                            out = {k: (v if k in ("then", "else") and not isinstance(v, dict)
                                       else _rewrite(v, fix)) for k, v in obj.items()}
                            for key in ("then", "else"):
                                if key in out and _same(out[key], old):
                                    out[key] = new
                            return out
                        return None
                    self.set(spec.id, "select", _rewrite(select, fix))
            elif el.type == "part" and el.props.get("alias") is None:   # 결합의 끝점
                self._rewrite_endpoints(el.parent, old, new)
        doc = m.get(m.root)                               # 실험 프레임이 붙는 곳
        frames = doc.props.get("experimental_frames")
        if isinstance(frames, list):
            self.set(doc.id, "experimental_frames",
                     [dict(f, attach_to=new) if isinstance(f, dict) and _same(f.get("attach_to"), old)
                      else f for f in frames])

    def _rewrite_variable_mentions(self, old, new: str) -> None:
        def fix(obj):
            if isinstance(obj, dict) and "var" in obj and _same(obj["var"], old):
                return {k: (new if k == "var" else _rewrite(v, fix)) for k, v in obj.items()}
            return None

        for el in self.model.all():
            for key in ("rule", "select", "cardinality", "constraints"):
                if el.props.get(key) is not None:
                    self.set(el.id, key, _rewrite(el.props[key], fix))
            attrs = el.props.get("attributes")
            if isinstance(attrs, dict):                   # 속성의 유도식
                self.set(el.id, "attributes",
                         {k: (dict(a, expr=_rewrite(a["expr"], fix))
                              if isinstance(a, dict) and "expr" in a else a)
                          for k, a in attrs.items()})

    def _rewrite_separator_key(self, entity_id: str, old, new: str) -> None:
        """문서 조립 확장의 구분자 표는 aspect 이름을 열쇠로 쓴다."""
        seps = _get_in(self.model.get(entity_id).props, ("metadata", "text", "separators"))
        if isinstance(seps, dict) and old in seps:
            self.set(entity_id, ("metadata", "text", "separators"),
                     {(new if k == old else k): v for k, v in seps.items()})

    def set_alias(self, part_id: str, alias: Optional[str]) -> None:
        """부분의 별칭을 정하거나 없앤다. 그 부분 이름으로 적힌 결합의 끝점을 함께 고친다."""
        m = self.model
        el = m.get(part_id)
        if el.type != "part":
            raise EditError("별칭은 aspect의 부분에 붙인다")
        old_name = m.label(part_id)
        with self.history.transaction("별칭 바꾸기"):
            self.set(part_id, "alias", alias if alias is not None else MISSING)
            self._rewrite_endpoints(el.parent, old_name, m.label(part_id))

    def remove(self, id: str, cascade: bool = False) -> None:
        """요소와 그 아래를 지운다.

        이 요소를 가리키던 참조는 끊어진 참조로 남긴다(이름은 유지). cascade이면
        가리키던 부분, 대안, 관계를 함께 지운다.
        """
        m = self.model
        el = m.get(id)
        if el.type == "document":
            raise EditError("문서는 지울 수 없다")
        name = m.label(id)
        with self.history.transaction(f"{name} 삭제"):
            doomed = []

            def collect(i):
                for child in m.kids(i):
                    collect(child.id)
                doomed.append(i)

            collect(id)
            inside = set(doomed)
            for target in doomed:
                for eid, prop in m.refs_to(target):
                    if eid in inside:
                        continue
                    holder = m.get(eid)
                    if cascade and holder.type in ("part", "alternative", "link"):
                        self.history.apply(Remove(eid))
                    else:
                        self.set(eid, prop, Ref(None, m.get(target).props.get("name")))
            for i in doomed:
                self.history.apply(Remove(i))

    def set_root(self, entity_id: str) -> None:
        """이 엔티티를 뿌리로 정한다. 다른 엔티티의 뿌리 표시는 지운다."""
        m = self.model
        if m.get(entity_id).type != "entity":
            raise EditError("뿌리는 엔티티여야 한다")
        with self.history.transaction("뿌리 지정"):
            for el in m.of_type("entity"):
                if el.id != entity_id and "root" in el.props:
                    self.set(el.id, "root", MISSING)
            self.set(entity_id, "root", True)

    def duplicate(self, entity_id: str, new_name: str) -> str:
        """엔티티 정의를 그 아래의 구조와 함께 복사한다. 사본의 참조는 원본과 같은 대상을 가리킨다."""
        m = self.model
        src = m.get(entity_id)
        if src.type != "entity":
            raise EditError("엔티티만 복제한다")
        self._check_name("entity", m.root, new_name)
        with self.history.transaction(f"{src.props.get('name')} 복제"):
            def clone(el, parent, role) -> str:
                props = _norm(el.props)
                if el.id == entity_id:
                    props["name"] = new_name
                    props.pop("root", None)
                new_id = self._insert(el.type, parent, role, props)
                for r, kids in el.children.items():
                    for c in list(kids):
                        clone(m.get(c), new_id, r)
                return new_id

            return clone(src, m.root, "entities")

    # 구조 ---------------------------------------------------------------

    def add_aspect(self, entity_id: str, name: str) -> str:
        self._check_name("aspect", entity_id, name)
        with self.history.transaction(f"aspect {name} 추가"):
            return self._insert("aspect", entity_id, "aspects", {"name": name})

    def add_part(self, aspect_id: str, def_id: str, alias: Optional[str] = None,
                 index: Optional[int] = None) -> str:
        p = {"def": Ref(def_id, None)}
        if alias is not None:
            p["alias"] = alias
        with self.history.transaction("부분 추가"):
            return self._insert("part", aspect_id, "parts", p, index)

    def add_multi_aspect(self, entity_id: str, name: str, def_id: str, cardinality,
                         naming: Optional[str] = None) -> str:
        self._check_name("multi_aspect", entity_id, name)
        p = {"name": name, "part": Ref(def_id, None), "cardinality": cardinality}
        if naming is not None:
            p["naming"] = naming
        with self.history.transaction(f"multi-aspect {name} 추가"):
            return self._insert("multi_aspect", entity_id, "multi_aspects", p)

    def add_specialization(self, entity_id: str, name: str) -> str:
        self._check_name("specialization", entity_id, name)
        with self.history.transaction(f"specialization {name} 추가"):
            return self._insert("specialization", entity_id, "specializations", {"name": name})

    def add_alternative(self, spec_id: str, def_id: str, set_extends: bool = True) -> str:
        """대안을 더한다. 대안이 될 엔티티가 아직 누구도 extends 하지 않으면 소유 엔티티를
        extends 하게 한다."""
        m = self.model
        with self.history.transaction("대안 추가"):
            alt = self._insert("alternative", spec_id, "alternatives", {"def": Ref(def_id, None)})
            owner = m.entity_of(spec_id)
            target = m.get(def_id)
            if set_extends and "extends" not in target.props and owner != def_id:
                self.set(def_id, "extends", Ref(owner, None))
            return alt

    def make_optional(self, entity_id: str, spec_name: str = "포함여부",
                      present: Optional[str] = None, absent: Optional[str] = None) -> tuple:
        """엔티티를 선택 사항으로 만든다: 있음 대안과 없음 대안을 가진 specialization을 더한다."""
        name = self.model.get(entity_id).props["name"]
        present = present or f"{name}_포함"
        absent = absent or f"{name}_제외"
        with self.history.transaction(f"{name} 을 선택 사항으로"):
            sid = self.add_specialization(entity_id, spec_name)
            yes = self.add_entity(present)
            no = self.add_entity(absent, stereotype="void")
            self.add_alternative(sid, yes)
            self.add_alternative(sid, no)
            return sid, yes, no

    def move(self, id: str, parent: str, role: Optional[str] = None, index: Optional[int] = None) -> None:
        """요소를 다른 부모로 옮긴다. index가 없으면 맨 끝."""
        el = self.model.get(id)
        role = role or el.role
        if index is None:
            dest = self.model.get(parent).children[role]
            index = len(dest) - (1 if el.parent == parent and el.role == role else 0)
        if TYPES[el.type].named and (el.parent != parent):
            self._check_name(el.type, parent, el.props.get("name"), skip=id)
        self.history.apply(Move(id, parent, role, index))

    def reorder(self, id: str, index: int) -> None:
        el = self.model.get(id)
        self.history.apply(Move(id, el.parent, el.role, index))

    # 분야의 내용 ----------------------------------------------------------

    def set_kind(self, entity_id: str, kind: Optional[str]) -> None:
        self.set(entity_id, "kind", kind if kind is not None else MISSING)

    def set_field(self, entity_id: str, name: str, value) -> None:
        el = self.model.get(entity_id)
        with self.history.transaction(f"필드 {name}"):
            if not isinstance(el.props.get("fields"), dict):
                self.set(entity_id, "fields", {name: value})
            else:
                self.set(entity_id, ("fields", name), value)

    def remove_field(self, entity_id: str, name: str) -> None:
        self.set(entity_id, ("fields", name), MISSING)

    def add_link(self, entity_id: str, type: str, target_id: str) -> str:
        with self.history.transaction(f"관계 {type} 추가"):
            return self._insert("link", entity_id, "links", {"type": type, "target": Ref(target_id, None)})

    def relink(self, id: str, prop: str, target_id: Optional[str]) -> None:
        """참조 속성을 다른 대상으로 잇는다. 끊어진 참조를 고칠 때 쓴다."""
        if prop not in TYPES[self.model.get(id).type].refs:
            raise EditError(f"{prop} 은 참조 속성이 아니다")
        self.set(id, prop, Ref(target_id, None) if target_id is not None else MISSING)

    def reconnect(self) -> int:
        """끊어진 참조 가운데 그 이름의 엔티티가 지금 있는 것을 다시 잇는다."""
        m = self.model
        count = 0
        with self.history.transaction("끊어진 참조 다시 잇기"):
            for el in m.all():
                for prop in TYPES[el.type].refs:
                    ref = el.props.get(prop)
                    if isinstance(ref, Ref) and ref.target is None and ref.name is not None:
                        target = m.entity(ref.name)
                        if target is not None:
                            self.set(el.id, prop, Ref(target, None))
                            count += 1
        return count
