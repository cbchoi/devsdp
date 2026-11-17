"""명령줄 도구 ses (docs/ses-platform/18_classic_parity.md 6절).

    ses check    문서 [--functions 모듈:이름] [--profile 파일] [--max-variants N]
    ses choices  문서 [--decisions 파일] [--functions 모듈:이름]
    ses variants 문서 [--decisions 파일] [--limit N] [--functions 모듈:이름]
    ses build    문서 --decisions 파일 [--defaults] [--depth N] [--functions 모듈:이름]
    ses plan     문서 --decisions 파일 --binding 파일 --library 모듈:이름 [--json] [...]
    ses run      문서 --decisions 파일 --binding 파일 --library 모듈:이름 --until 시각 [--log N] [...]

check 는 문서와 변이 공간 전체를 진단한다(편집기의 진단과 같다). choices 와 variants 는 결정 집합을
적용한 족에서 남은 선택지와 변이를 보인다. 이 셋은 족 전체를 펼친다.

build, plan, run 은 결정이 끝난 변이 하나를 위에서 아래로 만든다(ses_core/direct.py). 족을 펼치지
않으므로 큰 모델에 쓴다. plan 은 실행기를 붙여 계획을 만들고, run 은 그 계획을 참조 시뮬레이터(devs)로 돌린다.

모듈:이름 은 파이썬 모듈 안의 사전을 가리킨다. 문서의 식이 부르는 함수들(--functions)과 실행기의 모듈
라이브러리(--library)다. 모듈은 지금 디렉터리에서도 찾는다.

종료 코드: 0 성공, 1 문서나 결정의 오류 또는 실행 가능하지 않음, 2 사용법 오류, 3 결정이 모자람.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Optional

OK, FAILED, USAGE, UNDECIDED = 0, 1, 2, 3


class Stop(Exception):
    """명령을 멈추고 종료 코드와 함께 알린다."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _resolve(spec: Optional[str], what: str):
    """'모듈:이름' 이 가리키는 객체."""
    if spec is None:
        return None
    module, _, attr = spec.partition(":")
    if not module or not attr:
        raise Stop(FAILED, f"{what} 는 '모듈:이름' 꼴이어야 한다: {spec}")
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    try:
        obj = importlib.import_module(module)
        for part in attr.split("."):
            obj = getattr(obj, part)
    except (ImportError, AttributeError) as e:
        raise Stop(FAILED, f"{what} {spec} 를 찾을 수 없다: {e}")
    return obj


def _document(path: str):
    from .loader import LoadError, load_ses
    try:
        return load_ses(path)
    except LoadError as e:
        raise Stop(FAILED, f"문서를 적재할 수 없다. {e}")
    except OSError as e:
        raise Stop(FAILED, f"문서를 읽을 수 없다: {e}")


def _decisions(path: Optional[str]):
    from .decisions import DecisionSet, load_decisions
    if path is None:
        return DecisionSet()
    try:
        return load_decisions(path)
    except OSError as e:
        raise Stop(FAILED, f"결정 집합을 읽을 수 없다: {e}")
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise Stop(FAILED, f"결정 집합의 모양이 틀렸다: {type(e).__name__}: {e}")


def _build(args, out):
    from . import direct
    from .algebra import AlgebraError
    doc = _document(args.document)
    ds = _decisions(args.decisions)
    functions = _resolve(args.functions, "--functions")
    try:
        built = direct.build(doc, ds, functions=functions, use_defaults=args.defaults)
    except direct.Undecided as e:
        raise Stop(UNDECIDED, f"결정이 모자라다. {e}")
    except direct.Contradiction as e:
        raise Stop(FAILED, f"만들 수 없다. {e}")
    except AlgebraError as e:
        raise Stop(FAILED, f"결정 집합이 문서에 맞지 않다. {e}")
    if built.unused:
        print("쓰이지 않은 결정: " + "; ".join("/".join(map(_text, key)) for key in built.unused), file=out)
    return doc, built


def _text(x) -> str:
    return "/".join(map(str, x)) if isinstance(x, tuple) else str(x)


# ---------------------------------------------------------------------------
# 족 전체를 펼치는 명령
# ---------------------------------------------------------------------------

def cmd_check(args, out) -> int:
    from . import edit
    from .diagnose import analyze
    from .profile import load_profile
    try:
        m = edit.load(args.document)
    except OSError as e:
        raise Stop(FAILED, f"문서를 읽을 수 없다: {e}")
    profile = load_profile(args.profile) if args.profile else None
    a = analyze(m, profile, max_variants=args.max_variants, functions=_resolve(args.functions, "--functions"))
    for d in a.diagnostics:
        print(f"{d.severity} {d.code} {d.address or '-'}: {d.message}", file=out)
    if a.variants is None and a.core is not None:
        print(f"변이 {a.core.variants}개, 그 가운데 핵 적격 {a.core.wellformed}개 "
              "(열거하지 않고 정의 표 위에서 셌다. 결합과 속성 같은 확장의 검사는 하지 않았다)", file=out)
    elif a.variants is None:
        print("변이 분석을 하지 않았다", file=out)
    else:
        print(f"변이 {a.variants}개, 그 가운데 적격 {a.wellformed}개", file=out)
    return FAILED if a.errors else OK


def _family(args):
    from .algebra import AlgebraError
    from .decisions import apply
    from .unfold import unfold, variable_domains
    doc = _document(args.document)
    try:
        S = unfold(doc, _resolve(args.functions, "--functions"))
        pruned = apply(S, _decisions(args.decisions))
    except AlgebraError as e:
        raise Stop(FAILED, f"변이 공간을 만들 수 없다. {e}")
    return doc, S, pruned, variable_domains(doc)


def cmd_choices(args, out) -> int:
    from .algebra import count_variants, sem
    from .decisions import choice_table
    doc, S, pruned, domains = _family(args)
    if pruned is None:
        print("남은 변이가 없다", file=out)
        return FAILED
    n = count_variants(pruned.tree)
    print(f"남은 변이 {len(sem(pruned))}개" if n <= args.max_variants else
          f"구조상 남은 변이 {n}개 (한도 {args.max_variants}개를 넘어 제약은 세지 않았다)", file=out)
    for p in choice_table(S, pruned, domains):
        everything = [o for o, _ in p.options]
        where = f"{p.owner} {p.kind}" + (f" {p.group}" if p.group else "")
        state = "정해짐" if p.decided else ("남은 것 없음" if not p.active else "열림")
        print(f"{where}: {state}. 남은 선택지 {list(p.remaining)} / 전체 {everything}", file=out)
    return OK


def cmd_variants(args, out) -> int:
    from .algebra import count_variants, sem
    from .decisions import witness
    doc, S, pruned, domains = _family(args)
    if pruned is None:
        print("남은 변이가 없다", file=out)
        return FAILED
    n = count_variants(pruned.tree)
    if n > args.max_variants:
        raise Stop(FAILED, f"구조상 변이가 {n}개로 한도 {args.max_variants}개를 넘어 열거하지 않는다")
    variants = sem(pruned)
    print(f"변이 {len(variants)}개", file=out)
    for V in variants[:args.limit]:
        ds = witness(S.tree, V, domains).to_dict()      # 그 변이를 정확히 재현하는 결정 집합
        ds.pop("decisions", None)
        print(json.dumps(ds, ensure_ascii=False, default=str), file=out)
    return OK


# ---------------------------------------------------------------------------
# 변이 하나를 만드는 명령
# ---------------------------------------------------------------------------

def cmd_build(args, out) -> int:
    from .skeleton import skeleton
    doc, built = _build(args, out)
    L = built.layered
    sk = skeleton(L.ses.tree, L.void, built.variant)
    if sk is None:
        raise Stop(FAILED, "뿌리가 없음 대안을 골랐다. 만들 구조가 없다 (K0)")
    counts = {"components": 0}

    def show(c, depth: int) -> None:
        counts["components"] += 1
        if args.depth is None or depth <= args.depth:
            labels = ", ".join(c.labels)
            print("  " * depth + (c.name if labels == c.name else f"{c.name}: {labels}"), file=out)
            for name in c.absent:
                print("  " * (depth + 1) + f"{name}: 없음", file=out)
        for child in c.parts.values():
            show(child, depth + 1)

    show(sk, 0)
    print(f"변수 값 {built.sigma}. 구성요소 {counts['components']}개, 노드 {len(built.variant)}개", file=out)
    return OK


def _executor(name: str):
    """바인딩이 적은 실행기. 참조 시뮬레이터(devs) 밖의 것은 이름만 가진 실행기로 계획을 만든다.

    그 실행기만의 조건(하드웨어의 배선 규약, pyevsim 과 cevsim 의 규약)은 이 도구에서 보지 않는다.
    """
    from .devs import DevsExecutor
    from .executor import Executor
    if name == "devs":
        return DevsExecutor()

    class Named(Executor):
        pass
    Named.name = name
    return Named()


def _planned(args, out):
    from . import executor as X
    from .algebra import ENT
    from .extension import violations
    from .skeleton import component_path
    doc, built = _build(args, out)
    try:
        binding = X.load_binding(args.binding)
    except OSError as e:
        raise Stop(FAILED, f"바인딩을 읽을 수 없다: {e}")
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise Stop(FAILED, f"바인딩의 모양이 틀렸다: {type(e).__name__}: {e}")
    library = _resolve(args.library, "--library")
    executor = _executor(binding.executor)
    L, ext = X.attach(built.layered, executor, binding, library)
    found = violations(X.alone(L, ext), built.variant)
    if found:
        T = L.ses.tree
        for layer, code, path, msg in found:                 # 나무의 경로 대신 구성요소 경로로 보인다
            where = component_path(T, path) if T.kinds.get(path) == ENT else path
            print(f"{layer} {code} {'/'.join(map(str, where))}: {msg}", file=out)
        raise Stop(FAILED, f"이 변이는 실행기 {binding.executor} 로 만들 수 없다. 위반 {len(found)}건")
    return built, L, ext, executor


def cmd_plan(args, out) -> int:
    from . import executor as X
    from . import structure as st
    built, L, ext, _ = _planned(args, out)
    p = X.plan(L, ext, built.variant)
    if args.json:
        json.dump(p, out, ensure_ascii=False, indent=1, default=str)
        print(file=out)
        return OK
    atoms = X.frontier(p)
    links = sum(st.flatten(p).values())
    for path in atoms:
        node = st.subtree(p, path)
        print(f"{'/'.join(path) or '(뿌리)'}: {node.get('module')} {json.dumps(node.get('params') or {}, ensure_ascii=False)}",
              file=out)
    print(f"원자 구성요소 {len(atoms)}개, 원자 사이의 연결 {links}개", file=out)
    return OK


def cmd_run(args, out) -> int:
    from . import executor as X
    from .devs import DevsExecutor, simulate
    built, L, ext, executor = _planned(args, out)
    if not isinstance(executor, DevsExecutor):
        raise Stop(FAILED, f"run 은 참조 시뮬레이터(devs)만 돌린다. 바인딩의 실행기는 {ext.binding.executor} 다")
    model = X.realize(L, ext, executor, built.variant)
    try:
        log = simulate(model, args.until, max_steps=args.max_steps)
    except RuntimeError as e:
        raise Stop(FAILED, f"시뮬레이션이 멈췄다: {e}")
    for t, path, port, value in log[:args.log]:
        print(f"{t} {'/'.join(path)}.{port} {json.dumps(value, ensure_ascii=False, default=str)}", file=out)
    print(f"출력 사건 {len(log)}개" + (f", 마지막 시각 {log[-1][0]}" if log else ""), file=out)
    return OK


# ---------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ses", description="SES 문서를 검사하고, 변이를 고르고, 만들고, 돌린다")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, decisions_required=False):
        p.add_argument("document", help="정준 SES 문서(YAML)")
        p.add_argument("--functions", help="문서의 식이 부르는 함수들의 사전. 모듈:이름")
        p.add_argument("--decisions", required=decisions_required, help="결정 집합(YAML)")
        return p

    c = sub.add_parser("check", help="문서와 변이 공간 전체를 진단한다")
    c.add_argument("document")
    c.add_argument("--functions")
    c.add_argument("--profile", help="도메인 프로파일(YAML)")
    c.add_argument("--max-variants", type=int, default=5000)
    c.set_defaults(run=cmd_check)

    c = common(sub.add_parser("choices", help="결정 집합을 적용한 뒤 남은 선택지"))
    c.add_argument("--max-variants", type=int, default=5000)
    c.set_defaults(run=cmd_choices)

    c = common(sub.add_parser("variants", help="결정 집합을 적용한 뒤 남은 변이와 그것을 재현하는 결정"))
    c.add_argument("--limit", type=int, default=10)
    c.add_argument("--max-variants", type=int, default=5000)
    c.set_defaults(run=cmd_variants)

    for name, help_, run in (("build", "결정이 끝난 변이 하나를 만든다", cmd_build),
                             ("plan", "변이 하나를 만들고 실행기의 계획을 낸다", cmd_plan),
                             ("run", "변이 하나를 만들고 참조 시뮬레이터로 돌린다", cmd_run)):
        c = common(sub.add_parser(name, help=help_), decisions_required=True)
        c.add_argument("--defaults", action="store_true", help="정해지지 않은 변수와 대안에 문서의 기본값을 쓴다")
        if name == "build":
            c.add_argument("--depth", type=int, help="이 깊이까지만 보인다")
        else:
            c.add_argument("--binding", required=True, help="바인딩(YAML)")
            c.add_argument("--library", required=True, help="모듈 라이브러리의 사전. 모듈:이름")
        if name == "plan":
            c.add_argument("--json", action="store_true", help="계획 전체를 JSON 으로 낸다")
        if name == "run":
            c.add_argument("--until", type=float, required=True, help="이 시각까지 돌린다")
            c.add_argument("--log", type=int, default=20, help="앞에서부터 보일 출력 사건의 수")
            c.add_argument("--max-steps", type=int, default=1000000)
        c.set_defaults(run=run)
    return ap


def main(argv=None, out=None) -> int:
    out = out or sys.stdout
    args = parser().parse_args(argv)
    try:
        return args.run(args, out)
    except Stop as e:
        print(str(e), file=out)
        return e.code


if __name__ == "__main__":
    raise SystemExit(main())
