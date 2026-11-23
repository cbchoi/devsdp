"""변이 검사. 구현을 일부러 틀리게 고친 사본에서 시험이 실패하는지 본다.

시험이 그 코드를 실제로 지키고 있는지를 재는 도구다. 변이마다 원본의 글 한 곳을 틀린 글로 바꾸고
시험을 돌린다. 시험이 실패하면 잡힌 것이고, 통과하면 살아남은 것이다. 살아남은 변이는 시험의 빈 곳이거나
결과가 같은 변형이다.

쓰는 법
  python tools/mutate.py              tools/mutants.py 의 모든 변이
  python tools/mutate.py F U3         이름이 그 글자로 시작하는 변이만
  python tools/mutate.py --dry        바꿀 글이 원본에 정확히 한 번 있는지만 본다
  python tools/mutate.py --list       변이의 이름과 설명

작업 나무는 건드리지 않는다. 저장소를 임시 디렉터리에 한 번 베끼고 거기서 고치고 되돌린다.
빠른 시험 묶음에서 살아남은 변이는 전체 시험으로 다시 본다. 살아남은 변이가 있으면 종료 코드 1 이다.
변이 목록에서 "결과가 같은 변형"이라고 적어 둔 것은 살아남아도 세지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mutants import FAST, FULL, MUTANTS  # noqa: E402


def check(root: str) -> int:
    """바꿀 글이 원본에 정확히 한 번씩 있는가. 어긋난 변이의 수."""
    bad = 0
    labels = [name.split()[0] for name, *_ in MUTANTS]
    for label in sorted({x for x in labels if labels.count(x) > 1}):
        print(f"{label}: 같은 이름의 변이가 {labels.count(label)}개 있다. 이름으로 골라 돌릴 수 없다")
        bad += 1
    for name, file, old, new, _ in MUTANTS:
        text = open(os.path.join(root, file), encoding="utf-8").read()
        if text.count(old) != 1 or old == new:
            print(f"{name}: {file} 에 바꿀 글이 {text.count(old)}번 있다")
            bad += 1
    return bad


def run(work: str, targets: list, limit: int) -> tuple:
    """(통과했는가, 마지막 줄)."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *targets],
                           cwd=work, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        return False, "시간 초과 (잡힌 것으로 센다)"
    lines = [x for x in r.stdout.strip().splitlines() if x.strip()]
    failed = next((x for x in lines if x.startswith("FAILED") or x.startswith("ERROR")), "")
    return r.returncode == 0, (failed or (lines[-1] if lines else ""))[:160]


def main(argv: list) -> int:
    if argv == ["--list"]:
        for name, file, _, _, same in MUTANTS:
            print(f"{name}  [{file}]" + (f"  (결과가 같은 변형: {same})" if same else ""))
        return 0
    bad = check(ROOT)
    print(f"변이 {len(MUTANTS)}개, 맞지 않는 것 {bad}개")
    if argv == ["--dry"] or bad:
        return 1 if bad else 0
    chosen = [m for m in MUTANTS if not argv or any(m[0].startswith(a) for a in argv)]
    work = tempfile.mkdtemp(prefix="ses-mutate-")
    shutil.copytree(ROOT, os.path.join(work, "repo"), ignore=shutil.ignore_patterns(".git", "__pycache__", "reference",
                                                                                   ".pytest_cache", "*.pdf"))
    repo = os.path.join(work, "repo")
    survived = 0
    try:
        ok, tail = run(repo, FULL, 1800)
        if not ok:
            print("고치지 않은 사본에서 시험이 실패한다:", tail)
            return 2
        for name, file, old, new, same in chosen:
            path = os.path.join(repo, file)
            original = open(path, encoding="utf-8").read()
            open(path, "w", encoding="utf-8").write(original.replace(old, new))
            started = time.time()
            try:
                ok, tail = run(repo, FAST, 900)
                where = "빠른 묶음"
                if ok:
                    ok, tail = run(repo, FULL, 1800)
                    where = "전체"
            finally:
                open(path, "w", encoding="utf-8").write(original)
            verdict = "살아남음" if ok else f"잡힘({where})"
            if ok and same:
                verdict = f"살아남음. 결과가 같은 변형: {same}"
            elif ok:
                survived += 1
            print(f"{name}: {verdict}  {int(time.time() - started)}초  {'' if ok else tail}", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"합계 {len(chosen)}개, 잡히지 않은 것 {survived}개")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
