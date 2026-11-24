"""실행기를 붙이는 SES (docs/ses-platform/14_executors.md).

SES는 구조의 족을 정하고, 실행기는 그 구조 하나를 자기 플랫폼의 산출물로 만든다.
DEVS 실행기를 붙이면 시뮬레이션 모델(SES/MB)이, 하드웨어 실행기를 붙이면 배선표와
부품표가 된다. 실행기가 달라져도 SES와 그 위의 이론은 그대로다.

붙이는 자리는 셋이다.
- 모듈 라이브러리: 실행기가 가진 구현 단위들. 인터페이스만 보이고 본체는 불투명하다.
- 바인딩: 정의 이름에서 모듈로 가는 부분 사상. 고전 SES/MB의 모델베이스 참조다.
- 계획: 변이의 실현 모델을 바인딩이 닿는 곳(전선)에서 자른 구조. 실행기는 이것만 받는다.

시간이 있는 실행기는 시간 단위를 함께 받는다. 바인딩이 적어 둔 시간 단위가 계획에 실려 가고,
실행기는 시각을 그 단위의 눈금으로 센다 (ticks, time_unit).

바인딩과 실행 가능성 검사는 확장 계약(extension.py)을 따르는 확장 하나로 구현한다.
그래서 핵의 정리(내재성과 보존, 적격 핵, 합성)가 모든 실행기에 대해 성립한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from . import structure as st
from .algebra import sem
from .coupling import PortDecl
import copy

from .ext_attr import AttrDecl, Attributes, combine
from .extension import Extension, Layered, View, interpret, violations, wf_core

# 매개변수의 타입. time은 시간 값이다. 수이고, 시간 단위의 음이 아닌 정수배이거나 무한이어야 한다
_TYPES = {"int": (int,), "float": (int, float), "str": (str,), "bool": (bool,), "time": (int, float)}


@dataclass(frozen=True)
class Module:
    """모듈: 실행기의 라이브러리에 든 구현 단위.

    SES 쪽에서 보이는 것은 인터페이스(포트, 필수 입력, 매개변수)뿐이다. body는 실행기만
    아는 본체(시뮬레이션 모델의 클래스, 부품 번호)이고 어떤 검사도 들여다보지 않는다.
    매개변수의 선언은 (타입,) 또는 (타입, 기본값)이다. 타입 time은 본체가 시간 전진으로 쓰는 값이라는
    선언이며, 그 값이 시간 단위의 정수배인지를 계획에서 검사한다(B5).
    """
    name: str
    ports: Mapping[str, tuple] = field(default_factory=dict)
    required: tuple = ()
    params: Mapping[str, tuple] = field(default_factory=dict)
    body: Any = None


@dataclass(frozen=True)
class Bind:
    module: str
    params: Mapping[str, str] = field(default_factory=dict)     # 모듈의 매개변수에서 속성 이름으로


@dataclass(frozen=True)
class Binding:
    """정의 이름에서 모듈로 가는 부분 사상. 실행기마다 하나씩 둔다.

    time_unit은 시간 단위다. 모듈들의 시간 전진이 모두 그 정수배라는 선언이며, 실행기는 시각을 그
    단위의 눈금으로 센다. 적지 않으면 1이다. 시간이 없는 실행기(하드웨어)의 바인딩에는 적지 않는다.
    """
    executor: str
    map: Mapping[str, Bind]
    target: Optional[str] = None
    time_unit: Optional[float] = None

    def __post_init__(self) -> None:
        if self.time_unit is not None and not _is_unit(self.time_unit):
            raise ValueError(f"시간 단위 {self.time_unit!r} 는 0보다 큰 유한한 수여야 한다")

    @staticmethod
    def from_dict(d: dict) -> "Binding":
        entries = {name: Bind(e["module"], dict(e.get("params") or {}))
                   for name, e in (d.get("map") or {}).items()}
        return Binding(d["executor"], entries, d.get("target"), d.get("time_unit"))

    def to_dict(self) -> dict:
        out: dict = {"binding": "1.0", "executor": self.executor}
        if self.target is not None:
            out["target"] = self.target
        if self.time_unit is not None:
            out["time_unit"] = self.time_unit
        out["map"] = {name: dict(module=b.module, **({"params": dict(b.params)} if b.params else {}))
                      for name, b in self.map.items()}
        return out


class BindingError(ValueError):
    """바인딩의 파일이 형식에 맞지 않다. 어디가 틀렸는지를 적는다."""


_BINDING_KEYS = {"binding", "executor", "target", "time_unit", "map"}
_BIND_KEYS = {"module", "params"}


def check_binding_file(d) -> None:
    """파일에서 읽은 바인딩의 모양을 본다. 틀리면 BindingError 를 낸다. 모르는 항목을 조용히 넘기지 않는다.

    항목의 표는 스키마(schema/binding.schema.json)의 binding 과 같다. params 를 param 으로 적으면 매개변수의
    이름 바꾸기가 없는 것처럼 읽혀서 값이 모델에 가지 않는다.
    """
    if not isinstance(d, dict):
        raise BindingError('이름과 값의 표로 적어야 한다. binding: "1.0" 으로 시작한다')
    unknown = sorted(map(str, set(d) - _BINDING_KEYS))
    if unknown:
        raise BindingError(f"모르는 항목 {unknown} 가 있다. 쓸 수 있는 것은 {sorted(_BINDING_KEYS)} 다")
    for key in ("executor", "map"):
        if key not in d:
            raise BindingError(f"{key} 가 없다")
    if not isinstance(d["executor"], str):
        raise BindingError(f"executor: 실행기의 이름을 글로 적는다. 적힌 것은 {d['executor']!r} 다")
    if d.get("target") is not None and not isinstance(d["target"], str):
        raise BindingError(f"target: 문서의 이름을 글로 적는다. 적힌 것은 {d['target']!r} 다")
    if not isinstance(d["map"], dict):
        raise BindingError("map: 정의의 이름에서 {module: 모듈의 이름} 으로 가는 표로 적는다")
    for name, e in d["map"].items():
        if not isinstance(e, dict):
            raise BindingError(f"map.{name}: {{module: 모듈의 이름}} 의 모양으로 적는다. 적힌 것은 {e!r} 다")
        unknown = sorted(map(str, set(e) - _BIND_KEYS))
        if unknown:
            raise BindingError(f"map.{name}: 모르는 항목 {unknown} 가 있다. 쓸 수 있는 것은 {sorted(_BIND_KEYS)} 다")
        if not isinstance(e.get("module"), str):
            raise BindingError(f"map.{name}.module: 모듈의 이름을 글로 적는다. 적힌 것은 {e.get('module')!r} 다")
        params = e.get("params")
        if params is not None and not (isinstance(params, dict) and all(isinstance(k, str) and isinstance(v, str)
                                                                         for k, v in params.items())):
            raise BindingError(f"map.{name}.params: 모듈의 매개변수 이름에서 속성 이름으로 가는 표로 적는다")


def load_binding(path: str) -> Binding:
    from . import safeyaml
    try:
        d = safeyaml.load(path)
    except safeyaml.YamlError as e:
        raise BindingError(str(e)) from None
    check_binding_file(d)
    try:
        return Binding.from_dict(d)
    except ValueError as e:                                  # 시간 단위가 틀렸다
        raise BindingError(str(e)) from None


def load_library_dict(d: dict, bodies: Optional[Mapping] = None) -> dict:
    """자료로 적은 모듈 라이브러리. bodies가 있으면 모듈 이름으로 본체를 붙인다."""
    out = {}
    for name, m in (d.get("modules") or {}).items():
        ports = {p: (x["type"], x["direction"]) for p, x in (m.get("ports") or {}).items()}
        params = {p: ((x["type"], x["default"]) if "default" in x else (x["type"],))
                  for p, x in (m.get("params") or {}).items()}
        body = (bodies or {}).get(name, {k: v for k, v in m.items() if k not in ("ports", "required", "params")})
        out[name] = Module(name, ports, tuple(m.get("required") or ()), params, body)
    return out


class OffGrid(ValueError):
    """시간 전진이나 사건 시각이 시간 단위의 정수배가 아니다."""


def _is_unit(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < math.inf


def grid(value: float, unit: float) -> Optional[int]:
    """값이 시간 단위의 몇 배인지. 정수배가 아니면 None이다.

    부동소수점의 끝자리 차이(상대 오차 1e-9)는 정수배로 본다. 참조 시뮬레이터와 모든 실행기가 이 함수
    하나로 판정한다. 그래서 같은 값은 어디서나 같은 눈금이 된다.
    """
    k = value / unit
    if not math.isfinite(k):
        return None
    n = round(k)
    return n if abs(k - n) <= 1e-9 * max(1.0, abs(k)) else None


def ticks(who: str, ta: float, unit: float) -> Optional[int]:
    """시간 전진을 눈금의 수로 바꾼다. 무한이면 None이다. 시간 단위의 정수배가 아니면 OffGrid다."""
    if ta == math.inf:
        return None
    if not ta >= 0:
        raise ValueError(f"{who}: 시간 전진 {ta} 이 음수이거나 수가 아니다")
    n = grid(ta, unit)
    if n is None:
        e = OffGrid(f"{who}: 시간 전진 {ta} 이 시간 단위 {unit} 의 배수가 아니다")
        e.who, e.value, e.unit = who, ta, unit               # 기계가 읽을 자료
        raise e
    return n


def last_tick(until: float, unit: float) -> int:
    """시각 until까지 돌릴 때 처리할 마지막 눈금.

    until이 어떤 눈금의 시각이면(끝자리 차이는 같은 것으로 본다) 그 눈금이고, 아니면 그 앞의 눈금이다.
    """
    n = grid(until, unit)
    return n if n is not None else math.floor(until / unit)


def _off_grid(value, unit: float) -> bool:
    """시간 값이 시간 단위의 음이 아닌 정수배도 무한도 아닌가. 수가 아닌 값은 타입 검사(B4)가 맡는다."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value == math.inf:
        return False
    return not value >= 0 or grid(value, unit) is None


def same_unit(*units) -> float:
    """여러 자리에 적힌 시간 단위가 가리키는 하나의 값. 적히지 않은 자리는 None이다.

    적힌 것이 서로 다르면 오류다. 어디에도 적히지 않았으면 1이다.
    """
    declared = {u for u in units if u is not None}
    if len(declared) > 1:
        raise ValueError(f"시간 단위가 서로 다르다: {sorted(declared)}")
    unit = declared.pop() if declared else 1.0
    if not _is_unit(unit):
        raise ValueError(f"시간 단위 {unit!r} 는 0보다 큰 유한한 수여야 한다")
    return float(unit)


def time_unit(plan: dict, given: Optional[float] = None) -> float:
    """계획을 돌릴 시간 단위.

    바인딩이 적어 둔 시간 단위는 계획의 구성요소에 실려 온다. 실행기를 만들 때 준 값(given)이 있으면
    그것과 같아야 한다. 어디에도 없으면 1이다.
    """
    return same_unit(given, *(c.get("time_unit") for _, c in st.walk(plan)))


class Executor:
    """실행기: 계획을 받아 자기 플랫폼의 산출물을 만든다.

    실행기가 지켜야 하는 것은 충실성 하나다. 만든 산출물에서 구조를 다시 읽으면(observe)
    받은 계획의 구조와 같아야 한다. 구성요소나 연결을 더하거나 빼지 않는다.
    """

    name = "x"

    def conventions(self) -> list:
        """이 플랫폼만의 조건들. 계획을 받아 (부호, 구성요소 경로, 설명)의 목록을 내는 함수들."""
        return []

    def build(self, plan: dict, library: Mapping):
        raise NotImplementedError

    def observe(self, artifact) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class _Merged:
    """병합체 하나의 주석: 인터페이스, 속성 값, 바인딩."""
    ports: Mapping[str, PortDecl]
    port_conflicts: tuple
    attrs: Mapping[str, AttrDecl]
    attr_conflicts: tuple
    bound: bool                          # 구성원 가운데 묶인 것이 있는가
    bind: Optional[Bind]                 # 가장 구체적인 바인딩. 여럿이면 None (모호)
    by: tuple                            # 묶인 구성원들의 정의 이름


class Bound(Extension):
    """실행기와 바인딩을 얹는 확장.

    주석: 엔티티에는 포트 선언, 속성, 그 정의의 바인딩. aspect에는 결합.
    병합: 포트는 합집합, 속성과 바인딩은 더 구체적인 구성원의 것이 이긴다.
    검사: 뼈대를 위에서 아래로 내려가며 전선까지만 본다 (check_tree).
    해석: 계획. 전선에서 자른 구조에 모듈과 매개변수 값을 붙인 것.
    """

    def __init__(self, name: str, label: Callable, ports: Mapping, coup: Mapping, attrs: Optional[Attributes],
                 binding: Binding, library: Mapping, conventions=(), time_unit: Optional[float] = None) -> None:
        self.name = name
        self._label, self.ports, self.coup, self.attrs = label, ports, coup, attrs
        self.binding, self.library, self.conventions = binding, library, tuple(conventions)
        self.unit = same_unit(binding.time_unit, time_unit)  # 바인딩이 적은 것과 실행기에 준 것. 둘 다 없으면 1

    # 주석과 병합 ----------------------------------------------------------

    def given(self, env):
        """속성의 값이 변수 값에 달려 있으면 그 값으로 정한 확장을 돌려준다."""
        attrs = self.attrs.given(env) if self.attrs is not None else None
        if attrs is self.attrs:
            return self
        out = copy.copy(self)
        out.attrs = attrs
        return out

    def entity(self, path):
        return (self.ports.get(path) or {}, (self.attrs.entity(path) if self.attrs is not None else None) or {},
                self.binding.map.get(self._label(path)), self._label(path))

    def aspect(self, path):
        return self.coup.get(path, ())

    def merge(self, tree, items):
        decls: dict = {}
        for path, (ports, _, _, _) in items:
            for p, d in ports.items():
                decls.setdefault(p, []).append(d)
        ports = {p: PortDecl(ds[0].type, ds[0].direction, any(d.required for d in ds))
                 for p, ds in decls.items()}
        port_conflicts = tuple(p for p, ds in decls.items() if len({(d.type, d.direction) for d in ds}) > 1)

        def top(pairs: list) -> list:
            """다른 것의 조상이 아닌 것들: 가장 구체적인 구성원이 준 것."""
            return [(p, x) for p, x in pairs if not any(q != p and q[:len(p)] == p for q, _ in pairs)]

        # 속성은 속성 확장과 같은 규칙으로 합친다. 구성요소 수준의 재정의도 거기서 얹힌다
        declared = [(path, a) for path, (_, a, _, _) in items if a]
        attrs, types, values = (self.attrs.combine(tree, declared) if self.attrs is not None
                                else combine(declared))
        attr_conflicts = [name for name in attrs if name in types or name in values]
        bound = [(path, (b, label)) for path, (_, _, b, label) in items if b is not None]
        best = top(bound)
        return _Merged(ports, port_conflicts, attrs, tuple(attr_conflicts), bool(bound),
                       best[0][1][0] if len(best) == 1 else None,
                       tuple(label for _, (_, label) in bound)), []

    # 계획 ---------------------------------------------------------------

    def _unit(self) -> dict:
        """바인딩이 시간 단위를 적어 두었으면 계획의 구성요소에 싣는다. 실행기가 거기서 읽는다."""
        return {} if self.binding.time_unit is None else {"time_unit": self.binding.time_unit}

    def _kind(self, v: View) -> str:
        if v.ann.bound:
            return "bound"                                   # 전선: 여기서 멈춘다
        if v.comp.is_atomic or (len(v.comp.aspects) == 1 and not v.children):
            return "unbound"                                 # 묶이지 않은 잎. 부분이 모두 빠진 구성요소도 잎이다
        return "composite" if len(v.comp.aspects) == 1 else "broken"

    @staticmethod
    def _which(v: View) -> str:
        """묶을 정의의 이름. 복제본은 이름이 번호로 끝나므로 구성요소의 이름만으로는 무엇을 묶을지 알 수 없다."""
        labels = [x for x in v.comp.labels if x != v.name]
        return f". 바인딩의 map 에 정의 {' 또는 '.join(labels)} 를 적는다" if labels else ""

    def _leaf(self, v: View, found: Optional[list] = None) -> dict:
        """전선의 구성요소(또는 더 내려갈 수 없는 구성요소)를 원자로 적는다."""
        m: _Merged = v.ann
        say = (lambda code, msg: found.append((code, v.path, msg))) if found is not None else (lambda *a: None)
        ports = {p: (d.type, d.direction) for p, d in m.ports.items()}
        required = {p for p, d in m.ports.items() if d.required}
        module, params = None, {}
        kind = self._kind(v)
        for p in m.port_conflicts:
            say("C0", f"포트 {p} 의 선언이 충돌한다")
        if kind == "unbound" and v.comp.is_atomic:
            say("B1", f"원자 구성요소 {v.name} 에 묶인 모듈이 없다" + self._which(v))
        elif kind == "unbound":
            say("B1", f"구성요소 {v.name} 의 부분이 모두 빠졌고 묶인 모듈도 없다")
        elif kind == "bound" and m.bind is None:
            say("B2", f"바인딩이 모호하다. 서로 다른 갈래의 정의 {sorted(set(m.by))} 가 각각 묶여 있다")
        elif kind == "bound" and m.bind.module not in self.library:
            say("B1", f"라이브러리에 모듈 {m.bind.module} 이 없다")
        elif kind == "bound":
            mod: Module = self.library[m.bind.module]
            module = mod.name
            for p, decl in ports.items():
                if mod.ports.get(p) != decl:
                    theirs = mod.ports.get(p)                    # 모듈이 그 포트를 어떻게 선언했는가
                    say("B3", f"모듈 {mod.name} 의 포트 {p} 가 {decl} 이 아니다. "
                        + (f"모듈은 {theirs} 로 선언했다" if theirs is not None else "모듈에 그 포트가 없다"))
            for p in mod.required:
                if p not in ports:
                    say("B3", f"모듈 {mod.name} 의 필수 포트 {p} 가 SES의 인터페이스에 없다")
                else:
                    required.add(p)                          # 모듈이 요구하는 입력은 구동되어야 한다
            for name in m.attr_conflicts:
                if name in {m.bind.params.get(x, x) for x in mod.params}:
                    say("B4", f"속성 {name} 의 값이 구성원마다 다르다")
            for name, decl in mod.params.items():
                attr = m.attrs.get(m.bind.params.get(name, name))
                if attr is not None and attr.value is not None:
                    ok = isinstance(attr.value, _TYPES.get(decl[0], (object,)))
                    if not ok or (decl[0] != "bool" and isinstance(attr.value, bool)):
                        say("B4", f"매개변수 {name} 의 값 {attr.value!r} 이 타입 {decl[0]} 이 아니다")
                    params[name] = attr.value
                elif len(decl) > 1:
                    params[name] = decl[1]
                else:
                    say("B4", f"모듈 {mod.name} 의 매개변수 {name} 에 줄 값이 없다")
                if decl[0] == "time" and name in params and _off_grid(params[name], self.unit):
                    say("B5", f"매개변수 {name} 의 값 {params[name]!r} 이 시간 단위 {self.unit} 의 음이 아닌 정수배가 아니다")
        return st.node(ports, required=required, name=v.name, path=v.path, labels=v.comp.labels,
                       module=module, params=params, **self._unit())

    def _composite(self, v: View, kids: Mapping, found: Optional[list] = None) -> dict:
        m: _Merged = v.ann
        if found is not None:
            for p in m.port_conflicts:
                found.append(("C0", v.path, f"포트 {p} 의 선언이 충돌한다"))
        ports = {p: (d.type, d.direction) for p, d in m.ports.items()}
        dead = set(v.absent)
        eic, eoc, ic = [], [], []
        for (sw, sp), (dw, dp) in v.aspect_ann or ():
            if {sw, dw} & dead:
                continue                                     # 없음이 된 부분을 가리키는 결합은 빠진다
            if sw is None:
                eic.append((sp, (dw, dp)))
            elif dw is None:
                eoc.append(((sw, sp), dp))
            else:
                ic.append(((sw, sp), (dw, dp)))
        return st.node(ports, kids, eic, eoc, ic, [p for p, d in m.ports.items() if d.required],
                       name=v.name, path=v.path, labels=v.comp.labels, module=None, params={}, **self._unit())

    def _plan(self, v: View, found: list) -> dict:
        if self._kind(v) != "composite":
            return self._leaf(v, found)
        return self._composite(v, {n: self._plan(c, found) for n, c in v.children.items()}, found)

    def interpret(self, v: View, children):
        return self._composite(v, children) if self._kind(v) == "composite" else self._leaf(v)

    # 검사 ---------------------------------------------------------------

    def check_tree(self, root: View) -> list:
        found: list = []
        plan = self._plan(root, found)
        where = {p: c["path"] for p, c in st.walk(plan)}     # 구성요소 경로에서 SES 나무의 경로로
        found += [(code, where[p], msg) for code, p, msg in st.violations(plan)]
        if not any(code in ("C1", "C2", "C3") for code, _, _ in found):
            found += [("C5", where[p], f"{port}: 필수 포트에 닿는 원천이 없다") for p, port in st.ungrounded(plan)]
            for rule in self.conventions:
                found += [(code, where[p], msg) for code, p, msg in rule(plan)]
        return found


# ---------------------------------------------------------------------------
# 붙이기와 묻기
# ---------------------------------------------------------------------------

def attach(L: Layered, executor: Executor, binding: Binding, library: Mapping) -> tuple:
    """SES에 실행기를 붙인다. (실행기가 얹힌 Layered, 그 확장)을 돌려준다.

    구조(포트와 결합)와 속성은 L에 이미 얹힌 확장의 것을 그대로 쓴다. 같은 구조에 실행기를
    여럿 붙일 수 있다.
    """
    structure = next((x for x in L.extensions if x.name == "devs"), None)
    attrs = next((x for x in L.extensions if x.name == "attr"), None)
    ext = Bound(f"exec:{executor.name}", L.ses.tree.label,
                structure.ports if structure else {}, structure.coup if structure else {},
                attrs, binding, library, executor.conventions(),
                getattr(executor, "time_unit", None))
    return L.plus(ext), ext


def alone(L: Layered, ext: Bound) -> Layered:
    """그 실행기의 조건만 남긴 것. 실행 가능성은 핵의 적격성과 이 확장의 검사로 정해진다."""
    return Layered(L.ses, L.void, (ext,))


def executable(L: Layered, ext: Bound, V: frozenset) -> bool:
    return not violations(alone(L, ext), V)


def plan(L: Layered, ext: Bound, V: frozenset) -> Optional[dict]:
    """변이 V의 계획. 뿌리가 없음이면 None."""
    out = interpret(alone(L, ext), V)
    return None if out is None else out[ext.name]


def realize(L: Layered, ext: Bound, executor: Executor, V: frozenset):
    """변이 V의 실현: 계획을 실행기에 넘겨 산출물을 만든다. 실행 가능한 변이에서만 뜻이 있다."""
    if not executable(L, ext, V):
        raise ValueError("실행 가능하지 않은 변이는 실현할 수 없다")
    return executor.build(plan(L, ext, V), ext.library)


def exec_core(L: Layered, ext: Bound) -> Optional[Layered]:
    """실행 가능 핵: 이 실행기로 만들 수 있는 변이만 남긴 가장 큰 가지치기."""
    core = wf_core(alone(L, ext), syntactic=False)
    return None if core is None else Layered(core.ses, L.void, L.extensions)


def executable_variants(L: Layered, ext: Bound) -> list:
    return [V for V in sem(L.ses) if executable(L, ext, V)]


def frontier(p: dict) -> list:
    """계획의 전선: 모듈로 만들어질 구성요소들의 경로."""
    return st.atoms(p)


def assign(p: dict, chooser: Callable) -> tuple:
    """전선의 구성요소를 실행기들에 나눈다 (혼합 실현). chooser는 (경로, 구성요소)에서 묶음 이름으로.

    (묶음별로 다시 계층화한 구조, 이음매)를 돌려준다. 이음매는 실행기 사이를 잇는 연결이며
    그 밖의 연결은 한 실행기 안에 있다 (정리 20).
    """
    return st.regroup(p, {a: chooser(a, st.subtree(p, a)) for a in st.atoms(p)})
