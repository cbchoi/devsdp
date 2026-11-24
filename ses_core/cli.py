"""명령줄 도구 ses (docs/ses-platform/18_classic_parity.md 6절).

    ses check    문서 [--functions 모듈:이름] [--profile 파일] [--max-variants N]
    ses choices  문서 [--decisions 파일] [--functions 모듈:이름]
    ses variants 문서 [--decisions 파일] [--limit N] [--max-variants N] [--functions 모듈:이름]
    ses build    문서 --decisions 파일 [--defaults] [--depth N] [--functions 모듈:이름]
    ses plan     문서 --decisions 파일 --binding 파일 --library 모듈:이름 [--json] [...]
    ses run      문서 --decisions 파일 --binding 파일 --library 모듈:이름 --until 시각 [--log N] [...]
    ses pack new   디렉터리 [--name 이름] [--template minimal|full]
    ses pack check 디렉터리 [--record] [--executors devs,pyevsim,cevsim]
    ses pack show  디렉터리
    ses pack run   디렉터리 사례 [--until 시각] [--log N]
    ses ops        [--tools]
    ses call       연산 [--args JSON | --args-file 파일] [--root 디렉터리] [--pretty] [--out 파일]

check 는 문서와 변이 공간 전체를 진단한다(편집기의 진단과 같다). choices 와 variants 는 결정 집합을
적용한 족에서 남은 선택지와 변이를 보인다.

choices 는 족을 펼치지 않는다. 남은 변이의 수와 선택 지점 표를 정의 표 위에서 구한다(theory.md 7절).
복제본이 많은 족에서도 답한다. 결정이 펼친 나무의 노드를 가리킬 때(node)만 족을 펼친다. variants 는
변이를 늘어놓으므로 족을 펼치되, 남은 변이의 수를 먼저 세어 한도를 넘으면 펼치지 않고 멈춘다.

choices 는 선택의 핵만 본다. 속성의 식, 결합의 틀, 포트는 보지 않는다. 그래서 족을 펼치면 거부될
문서(등록하지 않은 함수를 부르는 속성 등)에도 답한다. 문서 전체의 검사는 check 가 한다.
변수 값의 조합은 결정과 변수 하나만 보는 제약으로 줄인 뒤에 돌아본다. 그 수가 --max-assignments
(기본 200,000)를 넘으면 멈춘다.

build, plan, run 은 결정이 끝난 변이 하나를 위에서 아래로 만든다(ses_core/direct.py). 족을 펼치지
않으므로 큰 모델에 쓴다. plan 은 실행기를 붙여 계획을 만들고, run 은 그 계획을 참조 시뮬레이터(devs)로 돌린다.

pack 은 분야 묶음을 다룬다(ses_core/pack.py, docs/ses-platform/20_packs.md). 묶음은 문서, 모델 베이스, 바인딩,
사례를 한 디렉터리에 담은 것이다. new 는 돌아가는 가장 작은 묶음을 만들고, check 는 묶음이 플랫폼의 계약을
지키는지 본다.

ops 와 call 은 에이전트가 부르는 연산이다(ses_core/ops.py, docs/ses-platform/21_agent_operations.md). ops 는 연산의
목록을 JSON 으로 내고, call 은 연산 하나를 불러 결과의 봉투를 JSON 한 줄로 낸다. 한글은 \\u 꼴로 적는다.
call 의 종료 코드는 봉투의 ok 가 참이면 0, 거짓이면 1 이다. 없는 옵션처럼 명령의 쓰임새가 틀리면 2 다.

모듈:이름 은 파이썬 모듈 안의 사전을 가리킨다. 문서의 식이 부르는 함수들(--functions)과 실행기의 모듈
라이브러리(--library)다. 모듈은 지금 디렉터리에서도 찾는다.

종료 코드: 0 성공, 1 문서나 결정의 오류 또는 실행 가능하지 않음, 2 사용법 오류, 3 결정이 모자람.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import sys
from typing import Optional

OK, FAILED, USAGE, UNDECIDED = 0, 1, 2, 3
MAX_ASSIGNMENTS = 200000        # 정의 표 위의 계산이 돌아보는 변수 값의 조합의 한도


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
    quiet, sys.dont_write_bytecode = sys.dont_write_bytecode, True       # 쓰는 사람의 디렉터리에 캐시를 남기지 않는다
    try:
        obj = importlib.import_module(module)
        for part in attr.split("."):
            obj = getattr(obj, part)
    except (ImportError, AttributeError) as e:
        raise Stop(FAILED, f"{what} {spec} 를 찾을 수 없다: {e}. 모듈은 지금 디렉터리에서 찾는다. 다른 디렉터리의 것이면 그 "
                           "디렉터리에서 치거나 점으로 이은 경로로 적는다")
    except Exception as e:                                   # noqa: BLE001  쓰는 사람의 모듈이 실리다가 낸 것
        raise Stop(FAILED, f"{what} {spec} 를 실을 수 없다: {type(e).__name__}: {e}")
    finally:
        sys.dont_write_bytecode = quiet
    return obj


def _document(path: str):
    from .loader import LoadError, load_ses
    try:
        return load_ses(path)
    except LoadError as e:
        raise Stop(FAILED, f"문서를 적재할 수 없다. {e}")
    except OSError as e:
        raise Stop(FAILED, f"문서를 읽을 수 없다: {e}")


def _short(options) -> str:
    """선택지의 목록을 적는다. 이어진 정수가 길게 늘어서면 처음과 끝과 개수만 적는다."""
    xs = list(options)
    ints = all(isinstance(x, int) and not isinstance(x, bool) for x in xs)
    if len(xs) > 12 and ints and xs == list(range(xs[0], xs[0] + len(xs))):
        return f"[{xs[0]} ... {xs[-1]}] ({len(xs)}개)"
    if len(xs) > 40:
        return "[" + ", ".join(repr(x) for x in xs[:20]) + f", ... ] ({len(xs)}개)"
    return str(xs)


def _decisions(path: Optional[str]):
    from .decisions import DecisionError, DecisionSet, load_decisions
    if path is None:
        return DecisionSet()
    try:
        return load_decisions(path)
    except OSError as e:
        raise Stop(FAILED, f"결정 집합을 읽을 수 없다: {e}")
    except DecisionError as e:
        raise Stop(FAILED, f"결정 집합의 모양이 틀렸다. {e}")
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise Stop(FAILED, f"결정 집합의 모양이 틀렸다: {type(e).__name__}: {e}")
    except Exception as e:                                   # noqa: BLE001  YAML 의 문법 오류 등
        if type(e).__module__.split(".")[0] != "yaml":
            raise
        raise Stop(FAILED, f"결정 집합을 읽을 수 없다: {str(e).splitlines()[0]}")


def _build(args, out):
    from . import direct
    from .algebra import AlgebraError
    from .profile import load_profile
    doc = _document(args.document)
    ds = _decisions(args.decisions)
    functions = _resolve(args.functions, "--functions")
    try:
        profile = load_profile(args.profile) if getattr(args, "profile", None) else None
    except Exception as e:                                   # noqa: BLE001
        raise Stop(FAILED, f"프로파일을 읽을 수 없다: {type(e).__name__}: {e}")
    try:
        built = direct.build(doc, ds, profile=profile, functions=functions, use_defaults=args.defaults, infer=True)
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
    from . import edit, safeyaml
    from .diagnose import analyze, where_it_happens
    from .profile import load_profile
    try:
        m = edit.load(args.document)
    except OSError as e:
        raise Stop(FAILED, f"문서를 읽을 수 없다: {e}")
    except safeyaml.YamlError as e:
        raise Stop(FAILED, f"문서를 읽을 수 없다. {e}")
    try:
        profile = load_profile(args.profile) if args.profile else None
    except Exception as e:                                   # noqa: BLE001
        raise Stop(FAILED, f"프로파일을 읽을 수 없다: {type(e).__name__}: {e}")
    a = analyze(m, profile, max_variants=args.max_variants, functions=_resolve(args.functions, "--functions"))
    for d in a.diagnostics:
        print(f"{d.severity} {d.code} {d.address or '-'}: {d.message}{where_it_happens(d)}", file=out)
    if a.variants is None and a.core is not None:
        print(f"변이 {_count(a.core.variants)}개, 그 가운데 핵 적격 {_count(a.core.wellformed)}개 "
              "(열거하지 않고 정의 표 위에서 셌다. 확장은 결합의 국소 검사만 했다)", file=out)
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


def _count(n: int) -> str:
    """수를 적는다. 서른 자리가 넘으면 앞의 몇 자리와 자릿수만 적는다. 아주 큰 수는 글로 다 옮길 수도 없다."""
    if n < 10 ** 30:
        return str(n)
    k = int((n.bit_length() - 1) * 0.30102999566398120)      # 자릿수에서 1 을 뺀 것의 어림
    while n >= 10 ** (k + 1):
        k += 1
    lead = str(n // 10 ** (k - 5))
    return f"약 {lead[0]}.{lead[1:]}e+{k} ({k + 1}자리)"


def _on_definitions(args):
    """문서, 결정 집합, 그리고 결정을 적용한 족을 정의 표 위에서 분석한 것. 나무를 펼치지 않는다.

    결정이 펼친 나무의 노드를 가리키면(node) 분석의 자리에 None 을 낸다. 그때는 부르는 쪽이 족을 펼친다.
    """
    from . import folded
    from .algebra import AlgebraError
    doc = _document(args.document)
    ds = _decisions(args.decisions)
    try:
        if any(c.node is not None for c in ds.choose):
            return doc, ds, None
        return doc, ds, folded.analyze(doc, _resolve(args.functions, "--functions"), ds,
                                       max_assignments=args.max_assignments)
    except folded.TooManyAssignments as e:
        raise Stop(FAILED, f"돌아볼 변수 값의 조합이 {_count(e.count)}가지로 한도 {args.max_assignments}가지를 넘는다. "
                           "변수의 값을 결정으로 줄이거나 --max-assignments 로 한도를 올린다")
    except AlgebraError as e:
        raise Stop(FAILED, f"변이 공간을 만들 수 없다. {e}")
    except (AttributeError, TypeError) as e:
        raise Stop(FAILED, f"결정 집합의 모양이 틀렸다: {type(e).__name__}: {e}")


def _print_table(points, out, single: bool = False) -> None:
    """선택 지점의 표. 줄은 정의마다 하나다. single 은 남은 변이가 하나라는 뜻이다. 그때 한 줄에 여럿이 남았으면
    그 정의가 놓인 자리마다 다른 것이 정해진 것이고, 더 정할 것은 없다."""
    for p in points:
        everything = [o for o, _ in p.options]
        where = f"{p.owner} {p.kind}" + (f" {p.group}" if p.group else "")
        state = "정해짐" if p.decided else ("남은 것 없음" if not p.active else "자리마다 정해짐" if single else "열림")
        print(f"{where}: {state}. 남은 선택지 {_short(p.remaining)} / 전체 {_short(everything)}", file=out)


def cmd_choices(args, out) -> int:
    from . import direct, folded
    from .algebra import count_variants, sem
    from .decisions import ChoicePoint, choice_table
    doc, ds, fam = _on_definitions(args)
    if fam is not None:                                      # 정의 표 위에서. 족을 펼치지 않는다
        if not fam.variants:
            print("남은 변이가 없다", file=out)
            why = direct.why_none(doc, ds, _resolve(args.functions, "--functions"))
            if why:
                print(f"어긋난 곳: {why}", file=out)
            return FAILED
        print(f"남은 변이 {_count(fam.variants)}개", file=out)
        _print_table([ChoicePoint(*row) for row in folded.choice_rows(doc, fam)], out, single=fam.variants == 1)
        if doc.profile:                                      # 이 표는 선택의 핵만 본다. 프로파일의 규칙이 지우는 변이도 센다
            print(f"문서가 프로파일 {doc.profile} 을 가리킨다. 이 표는 프로파일의 규칙을 보지 않았다. ses check --profile 로 본다",
                  file=out)
        return OK
    doc, S, pruned, domains = _family(args)
    if pruned is None:
        print("남은 변이가 없다", file=out)
        return FAILED
    n = count_variants(pruned.tree)
    print(f"남은 변이 {len(sem(pruned))}개" if n <= args.max_variants else
          f"구조상 남은 변이 {n}개 (한도 {args.max_variants}개를 넘어 제약은 세지 않았다)", file=out)
    _print_table(choice_table(S, pruned, domains), out)
    return OK


def cmd_variants(args, out) -> int:
    from .algebra import count_variants, sem
    from .decisions import witness
    doc, ds, fam = _on_definitions(args)
    if fam is not None:                                      # 펼치기 전에 센다. 한도를 넘으면 펼치지 않는다
        if not fam.variants:
            print("남은 변이가 없다", file=out)
            return FAILED
        if fam.variants > args.max_variants:
            raise Stop(FAILED, f"변이가 {_count(fam.variants)}개로 한도 {args.max_variants}개를 넘어 열거하지 않는다")
    doc, S, pruned, domains = _family(args)
    if pruned is None:
        print("남은 변이가 없다", file=out)
        return FAILED
    n = count_variants(pruned.tree)
    if fam is None and n > args.max_variants:                # 정확한 수를 모를 때만 구조상의 수로 멈춘다
        raise Stop(FAILED, f"구조상 변이가 {n}개로 한도 {args.max_variants}개를 넘어 열거하지 않는다")
    variants = sem(pruned)
    print(f"변이 {len(variants)}개" + (f". 앞의 {args.limit}개만 보인다. --limit 로 늘린다" if len(variants) > args.limit else ""),
          file=out)
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
    values = None
    if args.attributes:                                      # 속성의 값. 식과 결정 집합의 재정의를 거친 것이다
        from .extension import interpret
        values = (interpret(L, built.variant) or {}).get("attr")

    def show(c, depth: int, attr) -> None:
        counts["components"] += 1
        if args.depth is None or depth <= args.depth:
            labels = ", ".join(c.labels)
            given = ""
            if attr is not None and attr.get("params"):
                given = " " + json.dumps(attr["params"], ensure_ascii=False, default=str)
            print("  " * depth + (c.name if labels == c.name else f"{c.name}: {labels}") + given, file=out)
            for name in c.absent:
                print("  " * (depth + 1) + f"{name}: 없음", file=out)
        for name, child in c.parts.items():
            show(child, depth + 1, (attr or {}).get("children", {}).get(name) if attr is not None else None)

    show(sk, 0, values)
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
    except X.BindingError as e:
        raise Stop(FAILED, f"바인딩의 모양이 틀렸다. {e}")
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
    try:
        model = X.realize(L, ext, executor, built.variant)   # 모델의 init 이 여기서 돈다
        log = simulate(model, args.until, max_steps=args.max_steps)
    except Exception as e:                                   # noqa: BLE001  모델의 코드가 낸 것은 무엇이든 한 줄로 알린다
        raise Stop(FAILED, f"시뮬레이션이 멈췄다: {e}" if isinstance(e, RuntimeError) else
                           f"시뮬레이션이 멈췄다: {type(e).__name__}: {e}")
    for t, path, port, value in log[:args.log]:
        print(f"{t} {'/'.join(path)}.{port} {json.dumps(value, ensure_ascii=False, default=str)}", file=out)
    print(f"출력 사건 {len(log)}개" + (f", 마지막 시각 {log[-1][0]}" if log else ""), file=out)
    return OK


# ---------------------------------------------------------------------------
# 분야 묶음
# ---------------------------------------------------------------------------

def _report(report, out) -> None:
    pack = report.pack
    for f in report.findings:
        print(f"{f.severity} {f.code} {f.where}: {f.message}", file=out)
    if pack is None:
        return
    if report.family is not None:
        print(f"문서 {pack.document}: 변이 {_count(report.family[0])}개, 그 가운데 적격 {_count(report.family[1])}개", file=out)
    for name, info in report.cases.items():
        parts = []
        if "atoms" in info:
            parts.append(f"원자 구성요소 {info['atoms']}개, 연결 {info['links']}개")
        elif "components" in info:                           # 모델 베이스가 없는 묶음. 구조까지 만든다
            parts.append(f"구성요소 {info['components']}개")
        if "structure" in info:
            parts.append(f"구조의 지문 {info['structure']}")
        if "events" in info:
            parts.append(f"사건 {info['events']}개, 지문 {info['digest']}")
        if "executors" in info:
            parts.append("실행기 " + ", ".join(f"{k} {v}" for k, v in info["executors"].items()))
        print(f"사례 {name}: " + (". ".join(parts) if parts else "만들지 못했다"), file=out)


def cmd_pack_new(args, out) -> int:
    from . import pack as P
    try:
        written = P.scaffold(args.directory, args.name, args.template)
    except P.PackError as e:
        raise Stop(FAILED, str(e))
    for path in written:
        print(f"만들었다: {os.path.relpath(path)}", file=out)
    report = P.check(args.directory, record=True)
    print(f"검사하고 기록을 적었다: {os.path.relpath(os.path.join(args.directory, P.RECORDS))}", file=out)
    _report(report, out)
    print(f"다음: {os.path.join(args.directory, 'pack.yaml')} 의 설명을 읽고, 문서와 모델 베이스를 자기 분야의 것으로 바꾼다. "
          f"바꿀 때마다 ses pack check {args.directory} 로 본다", file=out)
    return OK if report.ok else FAILED


def cmd_pack_check(args, out) -> int:
    from . import pack as P
    wanted = tuple(x for x in args.executors.split(",") if x) if args.executors else None
    report = P.check(args.directory, record=args.record, executors=wanted)
    _report(report, out)
    errors = len(report.errors)
    warnings = sum(f.severity == "warning" for f in report.findings)
    print(f"묶음 {report.pack.name if report.pack else os.path.basename(os.path.abspath(args.directory))}: "
          + ("통과" if not errors else f"오류 {errors}건") + (f", 경고 {warnings}건" if warnings else ""), file=out)
    return OK if not errors else FAILED


def cmd_pack_show(args, out) -> int:
    from . import pack as P
    try:
        pack = P.load(args.directory)
    except P.PackError as e:
        raise Stop(FAILED, str(e))
    print(f"묶음 {pack.name}" + (f": {pack.title}" if pack.title else ""), file=out)
    print(f"문서 {pack.document}" + (f", 프로파일 {pack.profile}" if pack.profile else ""), file=out)
    if pack.model_file:
        print(f"모델 베이스 {pack.model_file}" + (f" (모듈 {pack.library})" if pack.library else "")
              + (f" (함수 {pack.functions})" if pack.functions else ""), file=out)
    if pack.binding:
        print(f"바인딩 {pack.binding}. 실행기 {', '.join(pack.executors)}", file=out)
    for c in pack.cases:
        print(f"사례 {c.name}: " + (c.decisions or "결정 없음") + (f", 시각 {c.until} 까지" if c.until is not None else ""),
              file=out)
    stem = os.path.splitext(pack.model_file)[0].replace(os.sep, ".") if pack.model_file else None
    fn = f" --functions {stem}:{pack.functions}" if pack.functions else ""
    prof = f" --profile {pack.profile}" if pack.profile else ""
    print("이 디렉터리 안에서 쓰는 명령:", file=out)
    print(f"  ses check {pack.document}{fn}{prof}", file=out)
    print(f"  ses choices {pack.document}{fn}", file=out)
    for c in pack.cases:
        if c.decisions:
            print(f"  ses choices {pack.document}{fn} --decisions {c.decisions}", file=out)
            print(f"  ses build {pack.document}{fn}{prof} --decisions {c.decisions} --attributes", file=out)
            if pack.binding:
                print(f"  ses plan {pack.document}{fn}{prof} --decisions {c.decisions} --binding {pack.binding} "
                      f"--library {stem}:{pack.library}", file=out)
    return OK


def cmd_pack_run(args, out) -> int:
    from . import pack as P
    try:
        log, sigma, atoms = P.run(args.directory, args.case, args.until)
    except P.PackError as e:
        raise Stop(FAILED, str(e))
    for t, path, port, value in log[:args.log]:
        print(f"{t} {'/'.join(path)}.{port} {json.dumps(value, ensure_ascii=False, default=str)}", file=out)
    print(f"변수 값 {sigma}. 원자 구성요소 {atoms}개. 출력 사건 {len(log)}개"
          + (f", 마지막 시각 {log[-1][0]}" if log else ""), file=out)
    return OK


# ---------------------------------------------------------------------------
# 에이전트가 부르는 연산
# ---------------------------------------------------------------------------

def cmd_ops(args, out) -> int:
    from . import ops
    json.dump(ops.tools() if args.tools else ops.manifest(), out, ensure_ascii=False, indent=1)
    print(file=out)
    return OK


def cmd_call(args, out) -> int:
    """연산 하나를 부르고 봉투를 낸다. 봉투는 ASCII 로만 적은 JSON 한 줄이다.

    한글과 줄바꿈 문자는 \\u 꼴로 적는다. 그래서 받는 쪽의 글자 인코딩이 무엇이든, 줄을 어떻게 나누든 봉투가
    깨지지 않는다. --pretty 는 사람이 보라고 여러 줄로, 한글을 그대로 적는다. --out 은 봉투를 파일에 적는다.
    묶음의 코드가 표준 출력을 어지럽혀도 파일은 온전하다.
    """
    from . import ops

    def refused(message: str) -> dict:
        return {"op": str(args.operation)[:80], "version": ops.VERSION, "ok": False, "result": None, "output": "",
                "findings": [{"severity": "error", "code": "A0", "where": str(args.operation)[:80], "message": message,
                              "kind": "input", "data": {}, "next": ops.NEXT["input"]}]}

    env = None
    text = args.args
    if args.args is not None and args.args_file is not None:
        env = refused("--args 와 --args-file 가운데 하나만 준다")
    elif args.args_file is not None:
        try:
            if args.args_file == "-":
                text = sys.stdin.read()
            else:
                with open(args.args_file, encoding="utf-8") as f:
                    text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            env = refused(f"입력 파일을 읽을 수 없다: {e}")
    if env is None:
        try:
            given = json.loads(text) if text is not None and text.strip() else {}
        except (ValueError, RecursionError) as e:            # JSON 이 아니거나, 너무 깊거나, 수가 너무 크다
            env = refused(f"입력이 JSON 이 아니다: {type(e).__name__}: {str(e)[:200]}")
        else:
            env = ops.call(args.operation, given, root=args.root)
    try:
        line = json.dumps(env, ensure_ascii=not args.pretty, indent=1 if args.pretty else None, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as e:     # 봉투를 글로 옮기지 못했다. 도구의 결함이다
        env = {"op": str(args.operation)[:80], "version": ops.VERSION, "ok": False, "result": None, "output": "",
               "findings": [{"severity": "error", "code": "A9", "where": str(args.operation)[:80],
                             "message": f"도구의 결함이다. 봉투를 JSON 으로 옮기지 못했다: {type(e).__name__}"}]}
        line = json.dumps(env, ensure_ascii=True)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            raise Stop(USAGE, f"--out 의 파일에 쓸 수 없다: {e}")
    try:
        print(line, file=out)
    except UnicodeEncodeError:                               # --pretty 인데 받는 쪽이 한글을 적지 못한다
        print(json.dumps(env, ensure_ascii=True, indent=1), file=out)
    except ValueError:                                       # 묶음의 코드가 표준 출력을 닫았다
        with contextlib.suppress(OSError):
            os.write(1, (line + "\n").encode("utf-8"))
    return OK if env["ok"] else FAILED


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ses", description="SES 문서와 분야 묶음을 검사하고, 변이를 고르고, 만들고, 돌린다")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, decisions_required=False):
        p.add_argument("document", help="정준 SES 문서(YAML)")
        p.add_argument("--functions", help="문서의 식이 부르는 함수들의 사전. 모듈:이름")
        p.add_argument("--decisions", required=decisions_required, help="결정 집합(YAML)")
        return p

    pk = sub.add_parser("pack", help="분야 묶음: 만들고, 검사하고, 사례를 돌린다").add_subparsers(dest="pack_command",
                                                                                             required=True)
    c = pk.add_parser("new", help="돌아가는 가장 작은 묶음을 새 디렉터리에 만든다")
    c.add_argument("directory")
    c.add_argument("--name", help="묶음의 이름. 주지 않으면 디렉터리의 이름")
    c.add_argument("--template", choices=["minimal", "full"], default="minimal",
                   help="뼈대의 종류. full 은 변수, 없음 대안, 복제, 사례마다 다른 값을 모두 쓰는 본보기다")
    c.set_defaults(run=cmd_pack_new)
    c = pk.add_parser("check", help="묶음이 플랫폼의 계약을 지키는지 본다")
    c.add_argument("directory")
    c.add_argument("--record", action="store_true", help="사례의 기록을 records.yaml 에 적는다")
    c.add_argument("--executors", help="실행기 사이의 일치를 볼 실행기들. 쉼표로 가른다. 주지 않으면 쓸 수 있는 것 전부")
    c.set_defaults(run=cmd_pack_check)
    c = pk.add_parser("show", help="묶음에 든 것과, 그 안에서 쓰는 명령을 보인다")
    c.add_argument("directory")
    c.set_defaults(run=cmd_pack_show)
    c = pk.add_parser("run", help="사례 하나를 참조 시뮬레이터로 돌려 출력 사건을 보인다")
    c.add_argument("directory")
    c.add_argument("case")
    c.add_argument("--until", type=float, help="돌릴 시각. 주지 않으면 선언에 적힌 시각")
    c.add_argument("--log", type=int, default=20, help="보일 사건의 수")
    c.set_defaults(run=cmd_pack_run)

    c = sub.add_parser("ops", help="에이전트가 부르는 연산의 목록을 JSON 으로 낸다")
    c.add_argument("--tools", action="store_true", help="도구 정의(name, description, input_schema)의 목록만 낸다")
    c.set_defaults(run=cmd_ops)
    c = sub.add_parser("call", help="연산 하나를 부르고 결과의 봉투를 JSON 한 줄로 낸다")
    c.add_argument("operation", help="연산의 이름. ses ops 가 알려 준다")
    c.add_argument("--args", help="입력. JSON 객체의 글")
    c.add_argument("--args-file", help="입력이 든 JSON 파일. - 이면 표준 입력")
    c.add_argument("--root", help="작업 자리. 연산은 이 안의 디렉터리만 다룬다. 주지 않으면 지금 디렉터리")
    c.add_argument("--pretty", action="store_true", help="여러 줄로, 한글을 그대로 적어 낸다. 사람이 볼 때 쓴다")
    c.add_argument("--out", help="봉투를 이 파일에도 적는다. 표준 출력이 어지럽혀져도 파일은 온전하다")
    c.set_defaults(run=cmd_call)

    c = sub.add_parser("check", help="문서와 변이 공간 전체를 진단한다")
    c.add_argument("document")
    c.add_argument("--functions")
    c.add_argument("--profile", help="도메인 프로파일(YAML)")
    c.add_argument("--max-variants", type=int, default=5000)
    c.set_defaults(run=cmd_check)

    c = common(sub.add_parser("choices", help="결정 집합을 적용한 뒤 남은 선택지"))
    c.add_argument("--max-variants", type=int, default=5000,
                   help="결정이 펼친 나무의 노드를 가리켜 족을 펼칠 때만 쓴다")
    c.add_argument("--max-assignments", type=int, default=MAX_ASSIGNMENTS,
                   help="돌아볼 변수 값의 조합의 한도")
    c.set_defaults(run=cmd_choices)

    c = common(sub.add_parser("variants", help="결정 집합을 적용한 뒤 남은 변이와 그것을 재현하는 결정"))
    c.add_argument("--limit", type=int, default=10)
    c.add_argument("--max-variants", type=int, default=5000)
    c.add_argument("--max-assignments", type=int, default=MAX_ASSIGNMENTS,
                   help="돌아볼 변수 값의 조합의 한도")
    c.set_defaults(run=cmd_variants)

    for name, help_, run in (("build", "결정이 끝난 변이 하나를 만든다", cmd_build),
                             ("plan", "변이 하나를 만들고 실행기의 계획을 낸다", cmd_plan),
                             ("run", "변이 하나를 만들고 참조 시뮬레이터로 돌린다", cmd_run)):
        c = common(sub.add_parser(name, help=help_), decisions_required=True)
        c.add_argument("--defaults", action="store_true", help="정해지지 않은 변수와 대안에 문서의 기본값을 쓴다")
        c.add_argument("--profile", help="도메인 프로파일(YAML). 문서가 프로파일을 따르면 함께 준다")
        if name == "build":
            c.add_argument("--depth", type=int, help="이 깊이까지만 보인다")
            c.add_argument("--attributes", action="store_true", help="구성요소마다 속성의 값을 함께 보인다")
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
        code = args.run(args, out)
        out.flush()
        return code
    except Stop as e:
        print(str(e), file=out)
        return e.code
    except BrokenPipeError:                                  # 출력을 받던 쪽이 먼저 닫았다(| head). 조용히 끝낸다
        with contextlib.suppress(Exception):
            sys.stdout = open(os.devnull, "w")
        return OK


if __name__ == "__main__":
    raise SystemExit(main())
