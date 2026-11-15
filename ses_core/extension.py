"""SES 핵 위의 확장 계약 (docs/ses-platform/11_ses_core_and_extensions.md).

확장 X는 핵이 정한 뼈대 위에 분야별 내용을 얹는다. X가 내놓는 것은 넷이다.
- 주석: 엔티티 노드와 aspect 노드에 붙는 분야별 자료.
- 병합: 병합체 구성원들의 주석을 구성요소 하나의 주석으로 합치는 규칙.
- 검사: 구성요소 하나와 그 분해, 살아 있는 자식만 보는 국소 조건.
- 해석: 뼈대에 대한 구조 재귀로 분야의 산출물을 만든다.

확장은 View만 받는다. 선택되지 않은 노드나 바깥의 나무를 볼 수 없으므로
적격성은 변이 자체의 성질이 되고, 핵의 정리(보존, 적격 핵, 합성)가 모든
확장에 대해 성립한다.

주석은 변이의 변수 값에 달려 있을 수 있다(given). 변수 값은 변이가 고른 것이고 변이만으로
정해지므로 위의 성질은 그대로다 (docs/ses-platform/18_classic_parity.md 4절).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .algebra import ENT, SES, Tree, f_and, sem
from .algebra import prune as _prune
from .skeleton import Comp, assignment, core_psi, core_violations, skeleton


@dataclass(frozen=True)
class View:
    """확장이 보는 구성요소 하나."""
    comp: Comp
    ann: Any                          # 병합된 주석
    conflicts: tuple                  # 병합 충돌 메시지
    aspect_ann: Any                   # 선택된 분해의 주석 (분해가 정확히 하나일 때)
    children: Mapping[str, "View"]    # 살아 있는 자식
    absent: tuple                     # 없음이 된 부분의 이름

    @property
    def path(self) -> tuple:
        return self.comp.path

    @property
    def name(self) -> str:
        return self.comp.name


class Extension:
    """확장 X의 기반 클래스. 하위 클래스가 필요한 메서드를 채운다."""

    name = "x"

    def given(self, env: Mapping) -> "Extension":
        """변이의 변수 값이 env 일 때의 확장. env 는 변수 이름에서 값 노드의 이름으로 가는 사전이다.

        주석이 변수 값에 달려 있지 않은 확장은 자신을 돌려준다.
        """
        return self

    def entity(self, path: tuple) -> Any:
        """엔티티 노드의 주석. 없으면 None."""
        return None

    def aspect(self, path: tuple) -> Any:
        """aspect 노드의 주석. 없으면 None."""
        return None

    def merge(self, tree: Tree, items: list) -> tuple:
        """병합체의 주석을 만든다. items는 (구성원 경로, 주석)의 목록.

        (병합된 주석, 충돌 메시지 목록)을 돌려준다. 구성원 사이의 조상 관계
        (경로의 접두사)만 써야 하며 목록의 순서에 의존하면 안 된다.
        """
        if len(items) == 1:
            return items[0][1], []
        return items[0][1], ["병합 규칙이 정의되지 않았다"]

    def check(self, view: View) -> list:
        """국소 검사. (부호, 메시지)의 목록."""
        return []

    def check_tree(self, root: View) -> list:
        """뼈대 전체에 대한 검사. (부호, 경로, 메시지)의 목록.

        구성요소 하나의 시야로 적을 수 없는 조건(나무를 가로지르는 관계, 합계)을
        위한 자리다. 뼈대만 받으므로 적격성은 여전히 변이 자체의 성질이다.
        """
        return []

    def interpret(self, view: View, children: Mapping[str, Any]) -> Any:
        """해석. children은 살아 있는 자식들의 해석 결과."""
        return None

    def psi(self, tree: Tree, void: frozenset):
        """문법적 특성식(선택). 없으면 None을 돌려주고 틀이 술어 제약을 쓴다."""
        return None


@dataclass(frozen=True)
class Layered:
    """SES와 확장들: SES + X1 + ... + Xk."""
    ses: SES
    void: frozenset = frozenset()
    extensions: tuple = ()

    def plus(self, *exts: Extension) -> "Layered":
        return Layered(self.ses, self.void, self.extensions + tuple(exts))

    def only(self, *names: str) -> "Layered":
        return Layered(self.ses, self.void, tuple(x for x in self.extensions if x.name in names))


def view(ext: Extension, T: Tree, comp: Comp) -> View:
    items = [(y, ext.entity(y)) for y in comp.members]
    items = [(y, a) for y, a in items if a is not None]
    ann, conflicts = ext.merge(T, items) if items else (None, [])
    aspect_ann = ext.aspect(comp.aspect) if comp.aspect is not None else None
    return View(comp, ann, tuple(conflicts), aspect_ann,
                {n: view(ext, T, c) for n, c in comp.parts.items()}, comp.absent)


def violations(L: Layered, V: frozenset) -> list:
    """변이 V의 위반 목록: (계층 이름, 부호, 경로, 메시지)."""
    T = L.ses.tree
    out = [("core", code, path, msg) for code, path, msg in core_violations(T, L.void, V)]
    sk = skeleton(T, L.void, V)
    if sk is None:
        return out

    def walk(ext: Extension, v: View) -> None:
        for msg in v.conflicts:
            out.append((ext.name, "M", v.path, msg))
        for code, msg in ext.check(v):
            out.append((ext.name, code, v.path, msg))
        for child in v.children.values():
            walk(ext, child)

    env = assignment(T, V)
    for ext in (x.given(env) for x in L.extensions):
        root = view(ext, T, sk)
        walk(ext, root)
        out.extend((ext.name, code, path, msg) for code, path, msg in ext.check_tree(root))
    return out


def wellformed(L: Layered, V: frozenset) -> bool:
    return not violations(L, V)


def family_wellformed(L: Layered) -> bool:
    return all(wellformed(L, V) for V in sem(L.ses))


def ill_formed(L: Layered) -> list:
    return [(V, vs) for V in sem(L.ses) for vs in [violations(L, V)] if vs]


def interpret(L: Layered, V: frozenset) -> Optional[dict]:
    """변이 V의 해석: 확장 이름에서 그 확장의 산출물로."""
    T = L.ses.tree
    sk = skeleton(T, L.void, V)
    if sk is None:
        return None

    def go(ext: Extension, v: View):
        return ext.interpret(v, {n: go(ext, c) for n, c in v.children.items()})

    env = assignment(T, V)
    return {ext.name: go(ext, view(ext, T, sk)) for ext in (x.given(env) for x in L.extensions)}


def wf_pattern(L: Layered, syntactic: bool = True) -> SES:
    """적격성 가지치기 SES. 확장이 특성식을 주면 그것을, 아니면 술어 제약을 쓴다."""
    T = L.ses.tree
    parts = [core_psi(T, L.void)]
    for ext in L.extensions:
        f = ext.psi(T, L.void) if syntactic else None
        if f is None:
            single = Layered(SES(T), L.void, (ext,))
            f = ("pred", lambda V, single=single: wellformed(single, V))
        parts.append(f)
    return SES(Tree({T.root: ENT}), f_and(*parts))


def prune(L: Layered, *patterns: SES) -> Optional[Layered]:
    R = _prune(L.ses, *patterns)
    return None if R is None else Layered(R, L.void, L.extensions)


def wf_core(L: Layered, syntactic: bool = True) -> Optional[Layered]:
    """적격 핵: 모든 확장에 대해 적격인 변이만 남긴 가장 큰 가지치기."""
    return prune(L, wf_pattern(L, syntactic))
