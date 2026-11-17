"""작은 문서의 전수 검사를 모든 코어로 돌린다 (tests/bounded_docs.py 의 문서마다 tests/bounded_check.py).

쓰는 법
  python tools/bounded.py                       모든 묶음, 모든 코어. 4 코어에서 5분쯤
  python tools/bounded.py F1 F7                 일부 묶음
  python tools/bounded.py --jobs 2 --limit 500  묶음마다 앞의 500개만 (빨리 보는 용도)
  python tools/bounded.py --out 디렉터리        summary.json 과 failures.jsonl 을 그 디렉터리에 적는다

문서는 고정된 순서로 나오므로 결과는 일꾼의 수와 무관하다. 검사가 하나라도 실패하면 종료 코드 1 이다.
실패한 문서는 (묶음, 번호)로 적힌다. python tests/bounded_docs.py F3 1234 로 그 문서를 볼 수 있다.
"""

from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bounded_docs  # noqa: E402


def work(job: tuple) -> tuple:
    import bounded_check
    family, start, stop, step = job
    stats: collections.Counter = collections.Counter()
    failures, largest = [], 0
    for i, d in enumerate(bounded_docs.FAMILIES[family]()):
        if i < start or i >= stop or (i - start) % step:
            continue
        try:
            st, fails = bounded_check.check_document(d)
        except Exception as e:                               # noqa: BLE001
            st, fails = collections.Counter(), [("crash", f"{type(e).__name__}: {e}")]
        stats.update(st)
        largest = max(largest, st.get("variants", 0))
        failures += [{"family": family, "index": i, "check": check, "message": msg} for check, msg in fails]
    return family, stats, largest, failures


def main() -> int:
    ap = argparse.ArgumentParser(description="작은 문서의 전수 검사")
    ap.add_argument("families", nargs="*", default=list(bounded_docs.FAMILIES))
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    sizes = {f: sum(1 for _ in bounded_docs.FAMILIES[f]()) for f in args.families}
    jobs = []
    for f in args.families:
        stop = min(sizes[f], args.limit) if args.limit else sizes[f]
        jobs += [(f, k, stop, args.jobs * 4) for k in range(args.jobs * 4)]       # 서로 엇갈린 조각들
    started = time.time()
    per_family: dict = {f: collections.Counter() for f in args.families}
    largest: dict = {f: 0 for f in args.families}
    failures: list = []
    with multiprocessing.Pool(args.jobs) as pool:
        for family, stats, most, fails in pool.imap_unordered(work, jobs):
            per_family[family].update(stats)
            largest[family] = max(largest[family], most)
            failures += fails
    failures.sort(key=lambda x: (x["family"], x["index"], x["check"]))
    total: collections.Counter = collections.Counter()
    for f in args.families:
        total.update(per_family[f])
    summary = {"families": {f: dict(sorted(per_family[f].items()), max_variants=largest[f]) for f in args.families},
               "total": dict(sorted(total.items()), max_variants=max(largest.values(), default=0)),
               "sizes": sizes, "limit": args.limit, "failures": len(failures),
               "failures_by_check": dict(collections.Counter(f"{x['family']}:{x['check']}" for x in failures))}
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1, sort_keys=True)
        with open(os.path.join(args.out, "failures.jsonl"), "w", encoding="utf-8") as f:
            for x in failures:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    for fam in args.families:
        s = per_family[fam]
        print(f"{fam}: 문서 {s['documents']} 변이 {s['variants']} 핵 적격 {s['wf_variants']} 부적격 {s['ill_variants']} "
              f"고전 절차의 모델 {s['classic_models']} 실패한 문서 {s['failed_documents']}")
    print(f"합계: 문서 {total['documents']} 변이 {total['variants']} 핵 적격 {total['wf_variants']} "
          f"부적격 {total['ill_variants']} 병합체 {total['clusters']} 실패 {len(failures)} "
          f"({time.time() - started:.0f}초)")
    for x in failures[:20]:
        print(f"  {x['family']}/{x['index']} {x['check']}: {x['message'][:200]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
