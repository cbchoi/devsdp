"""문서 하나에 대한 검사들 (docs/ses-platform/theory.md). 작은 문서의 전수 검사(bounded_docs.py)가 쓴다.

check_document(d) 는 파이썬 사전으로 준 문서 하나에서 다음을 본다.

  (1) 정리 5.  nu 가 Var(D) (folded.Semantics.variants) 에서 (T(D), Psi(D)) 의 변이(unfold.unfold_annotated 와
      algebra.sem) 로 가는 전단사다. 노드 집합으로 견준다. 핵 적격인 것끼리 대응한다(skeleton.core_violations).
      정리가 노드 집합 위에서 말하는 핵 적격(뿌리의 병합체에 없음 대안이 없고, 어느 구성 노드에서도 보조정리 4
      (b) 의 넷째 경우가 아니다)도 같다.
  (2) 정리 3.  folded.Evaluator 가 센 (변이, 핵 적격인 변이)의 수가 변수 값마다 열거한 수와 같고,
      folded.count 가 그 합과 같다.
  (3) 고전 절차.  WVar(D) 위의 (sigma, 구조)의 모음이 classic.enumerate_classic 이 낸 것과 같다. 구조는
      고른 분해의 이름과 빠진 부분을 잊은 것으로 견준다(folded.live_shape). 문서에 경로 수준의 selected 가
      없을 때만 한다(고전 절차는 그것을 읽지 않는다). 포트와 결합은 tests/test_folded.py 처럼 떼어 낸다.
      (3b) 정의 수준의 선택들을 구조에 더해 다시 견준다. 고전 절차가 구조를 만들며 적어 둔 선택과 견준다.
  (4) 따름정리 5.1.  skeleton(T, void, V) 가 살아 있는 자리마다 kappa 와 같다(구성원 노드, 표지, 고른 분해의
      노드, 살아 있는 부분, 빠진 부분, 정할 수 없음의 표시). core_violations 는 뿌리가 빠졌을 때 정확히 K0 을,
      정할 수 없는 자리마다 정확히 K1 을 낸다.
  (5) 정리 1 (c) 와 정리 2 (b) 에서 (e).  뿌리에서 닿는 정의의 병합체마다, 변수 값마다, 정의 3 을 그대로
      계산한 Dec 와 Amb (folded.Semantics.outcomes) 가 정리 2 의 글에서 읽은 닫힌 꼴과 같다. 주인이 있는
      살아 있는 병합체는 Dec 가 비지 않았거나 Amb 다. (d) 와 (e).
  (6) 정의 9 와 10.  unfold.py 가 만든 나무와 변이가, 글에서 옮겨 적은 T(D) 와 (T(D), Psi(D)) 의 변이
      (bounded_literal.py) 와 같다.

(통계, 실패들)을 낸다. 실패는 (검사, 글)의 목록이고 모두 성립하면 비어 있다.
독립된 검토에서 만든 것을 저장소로 옮겼다.
"""

from __future__ import annotations

import collections
import json
import os
import sys
from itertools import product

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ses_core import LoadError, classic, load_ses_dict  # noqa: E402
from ses_core import folded as F  # noqa: E402
from ses_core import model as m  # noqa: E402
from ses_core.algebra import ASP, ENT, AlgebraError, sem  # noqa: E402
from ses_core.skeleton import NO_ASPECT as MARK_NONE  # noqa: E402
from ses_core.skeleton import component_path, core_violations, skeleton  # noqa: E402
from ses_core.unfold import unfold_annotated  # noqa: E402

import bounded_literal  # noqa: E402


def stripped(d: dict) -> dict:
    """포트와 결합을 떼어 낸 문서 (tests/test_folded.py 와 같다)."""
    d = json.loads(json.dumps(d))
    d.pop("port_types", None)
    for body in d["entities"].values():
        body.pop("ports", None)
        for a in list((body.get("aspects") or {}).values()) + list((body.get("multi_aspects") or {}).values()):
            a.pop("couplings", None)
    return d


def classic_shape(n: dict):
    return tuple(n["labels"]), tuple((name, classic_shape(c)) for name, c in n["children"].items())


def classic_with_picks(doc, functions=None):
    """classic.enumerate_classic 과 같되, 절차가 적어 둔 선택을 함께 낸다: (sigma, 구조, 선택들)."""
    names = list(doc.variables)
    late = [c for c in doc.constraints if any(F.selected_atoms(x) for x in (c.when, c.require, c.forbid))]
    early = [c for c in doc.constraints if c not in late]

    def satisfied(c, sigma, picks=None) -> bool:
        if not classic._eval(c.when, sigma, functions, picks, doc):
            return True
        return (c.require is None or classic._eval(c.require, sigma, functions, picks, doc)) \
            and (c.forbid is None or not classic._eval(c.forbid, sigma, functions, picks, doc))

    for values in product(*(F.domain(doc, n) for n in names)):
        sigma = dict(zip(names, values))
        if not all(satisfied(c, sigma) for c in early):
            continue
        for structure, picks in classic._build(doc, doc.root.name, sigma, {}, functions):
            if structure is not None and all(satisfied(c, sigma, picks) for c in late):
                yield sigma, structure, picks


def has_path_selected(doc) -> bool:
    return any(a.path is not None for c in doc.constraints
               for x in (c.when, c.require, c.forbid) for a in F.selected_atoms(x))


def has_selected(doc) -> bool:
    return any(F.selected_atoms(x) for c in doc.constraints for x in (c.when, c.require, c.forbid))


# ---------------------------------------------------------------------------
# 정리 5 의 마지막 문장을 노드 집합에서 바로 읽는다 (skeleton.py 를 쓰지 않는다)
# ---------------------------------------------------------------------------

def wf_by_theorem5(doc, T, V: frozenset) -> bool:
    """뿌리의 병합체에 없음 대안이 없고, 어느 구성 노드에서도 보조정리 4 (b) 의 넷째 경우가 아니다.
    넷째 경우: 빠지지 않았고, 분해를 가진 구성원이 하나 이상 골라졌고, 그것들이 모두 '~' 를 고른다."""
    ents = doc.entities

    def member_nodes(e):
        out, stack = [], [e]
        while stack:
            y = stack.pop()
            out.append(y)
            for s in T.specs(y):
                if len(s) == 2 and s[-1].startswith("$"):
                    continue
                stack += [c for c in T.children(s) if c in V]
        return out

    def is_void(y):
        return ents[T.label(y)].stereotype == m.Stereotype.VOID

    def has_dec(y):
        e = ents[T.label(y)]
        return bool(e.aspects or e.multi_aspects)

    for e in V:
        if T.kind(e) != ENT or not (len(e) == 1 or T.kind(e[:-1]) == ASP):
            continue
        ms = member_nodes(e)
        removed = any(is_void(y) for y in ms)
        if len(e) == 1 and removed:
            return False
        owners = [y for y in ms if has_dec(y)]
        if not removed and owners and all(y + (MARK_NONE,) in V for y in owners):
            return False
    return True


# ---------------------------------------------------------------------------
# 따름정리 5.1: 뼈대와 kappa
# ---------------------------------------------------------------------------

def place_members(mu: F.Member, at: tuple) -> list:
    out = [at]
    for s, sub in mu.picks:
        out += place_members(sub, at + (s, sub.name))
    return out


def owner_node(mu: F.Member, at: tuple, name: str):
    if mu.name == name:
        return at
    for s, sub in mu.picks:
        got = owner_node(sub, at + (s, sub.name), name)
        if got is not None:
            return got
    return None


def compare_skeleton(T, sk, kappa: F.Comp, pos: tuple, problems: list, stuck_at: list) -> None:
    """sk 는 구성요소 경로 pos 에 놓인, 살아 있는 구성요소 kappa 의 뼈대 노드다."""
    here = "/".join(pos)
    if component_path(T, sk.path) != pos:
        problems.append(f"{here}: 뼈대의 경로 {sk.path} 의 구성요소 경로가 {component_path(T, sk.path)} 다")
    want_members = place_members(kappa.member, sk.path)
    if sorted(sk.members) != sorted(want_members) or sk.members[0] != sk.path:
        problems.append(f"{here}: 구성원 노드 {sk.members} != {want_members}")
    if sorted(sk.labels) != sorted(kappa.member.names()):
        problems.append(f"{here}: 표지 {sk.labels} != {kappa.member.names()}")
    if kappa.state == F.SPLIT:
        y = owner_node(kappa.member, sk.path, kappa.owner)
        a = y + (kappa.dec if kappa.count is None else f"{kappa.dec}[{kappa.count}]",)
        if sk.aspects != (a,):
            problems.append(f"{here}: 고른 분해 {sk.aspects} != {(a,)}")
        live = [n for n, c in kappa.parts if c.state != F.GONE]
        gone = [n for n, c in kappa.parts if c.state == F.GONE]
        if list(sk.parts) != live:
            problems.append(f"{here}: 살아 있는 부분 {list(sk.parts)} != {live}")
        if list(sk.absent) != gone:
            problems.append(f"{here}: 빠진 부분 {list(sk.absent)} != {gone}")
        if sk.stuck:
            problems.append(f"{here}: 뼈대는 정할 수 없다고 하는데 kappa 는 split 이다")
        for n, c in kappa.parts:
            if c.state != F.GONE and n in sk.parts:
                compare_skeleton(T, sk.parts[n], c, pos + (n,), problems, stuck_at)
        return
    if sk.aspects or sk.parts or sk.absent:
        problems.append(f"{here}: kappa 는 {kappa.state} 인데 뼈대에 분해나 부분이 있다 {sk.aspects} {list(sk.parts)} {sk.absent}")
    if sk.stuck != (kappa.state == F.STUCK):
        problems.append(f"{here}: 뼈대의 표시는 {sk.stuck} 인데 kappa 는 {kappa.state}")
    if kappa.state == F.STUCK:
        stuck_at.append(sk.path)


# ---------------------------------------------------------------------------
# 정리 2 (b), (c): 글에서 읽은 닫힌 꼴
# ---------------------------------------------------------------------------

def closed_forms(doc, owners: list, sigma: dict, functions=None) -> tuple:
    """(Dec 를 (주인, 분해의 이름)의 집합으로, Amb)."""
    above = F.above

    def same(p, q) -> bool:
        return not above(p, q) and not above(q, p)

    A, R, demands = {}, {}, {}
    for y in owners:
        fams = F.decompositions(doc.entities[y])
        forced = [x for x in fams if x.rule is not None and F.value(x.rule, sigma, functions)]
        top = [x for x in forced if not any(above(w.priority, x.priority) for w in forced if w is not x)]
        if not forced:
            A[y], R[y], demands[y] = fams, fams, [[x] for x in fams]
        else:
            A[y], R[y], demands[y] = top, (top if len(top) == 1 else []), [top]
    dec = {(y, x.name) for y in owners for x in R[y]
           if all(any(above(x.priority, w.priority) for w in A[z]) for z in owners if z != y)}
    amb = False
    for c in {x.priority for y in owners for x in F.decompositions(doc.entities[y])}:
        fine = {y: [g for g in demands[y] if not any(above(x.priority, c) for x in g)] for y in owners}
        if not all(fine.values()):
            continue                                         # 어떤 주인은 c 보다 앞선 것을 낼 수밖에 없다
        twice = any(sum(same(x.priority, c) for x in g) >= 2 for y in owners for g in fine[y])
        holders = [y for y in owners if any(same(x.priority, c) for g in fine[y] for x in g)]
        amb = amb or twice or len(holders) >= 2
    return dec, amb


def check_clusters(doc, s, functions, stats, fail) -> None:
    reach, stack = [], [s.root]
    while stack:
        n = stack.pop()
        if n in reach:
            continue
        reach.append(n)
        e = doc.entities[n]
        stack += [a for sp in e.specializations.values() for a in sp.alternatives]
        stack += [p.def_name for a in e.aspects.values() for p in a.parts]
        stack += [ma.part.def_name for ma in e.multi_aspects.values()]
    for sigma in s.assignments():
        done = set()
        for name in reach:
            for mu in s.members(name, sigma):
                owners = s.owners(mu)
                if s.removed(mu) or not owners or frozenset(owners) in done:
                    continue
                done.add(frozenset(owners))
                dec, amb = s.outcomes(owners, sigma)
                got = {(y, x.name) for y, x in dec}
                want, want_amb = closed_forms(doc, owners, sigma, functions)
                stats["clusters"] += 1
                stats["clusters_dec_and_amb"] += bool(dec) and amb
                stats["clusters_amb_only"] += (not dec) and amb
                where = f"sigma {sigma} 주인 {owners}"
                if not dec and not amb:
                    fail("T1c", f"{where}: Dec 도 Amb 도 아니다")
                if got != want:
                    fail("T2b", f"{where}: Dec {sorted(got)} 닫힌 꼴 {sorted(want)}")
                if amb != want_amb:
                    fail("T2c", f"{where}: Amb {amb} 닫힌 꼴 {want_amb}")
                fams = [x for y in owners for x in F.decompositions(doc.entities[y])]
                if len(owners) == 1 and not any(x.rule is not None and F.value(x.rule, sigma, functions) for x in fams):
                    if amb or len(dec) != len(fams):
                        fail("T2d", f"{where}: Dec {sorted(got)} Amb {amb}")
                pris = [x.priority for x in fams]
                if all(p is not None for p in pris) and len(set(pris)) == len(pris) and amb:
                    fail("T2e", f"{where}: 우선순위 {pris} 가 서로 다른 수인데 Amb 다")


# ---------------------------------------------------------------------------
# 검사들
# ---------------------------------------------------------------------------

def check_document(d: dict, functions=None) -> tuple:
    stats: collections.Counter = collections.Counter()
    fails: list = []

    def fail(check: str, msg: str) -> None:
        fails.append((check, msg))

    try:
        doc = load_ses_dict(d)
    except LoadError as e:
        stats["rejected_by_loader"] += 1
        return stats, [("load", str(e).splitlines()[-1].strip())]
    stats["documents"] += 1
    s = F.Semantics(doc, functions)
    listed = list(s.variants())
    wf_flags = [s.well_formed(kappa) for _, kappa in listed]
    stats["variants"] += len(listed)
    stats["wf_variants"] += sum(wf_flags)
    stats["ill_variants"] += len(listed) - sum(wf_flags)
    stats["docs_with_ill"] += any(not ok for ok in wf_flags)
    stats["docs_empty"] += not listed
    states = collections.Counter(c.state for _, kappa in listed for _, c in kappa.walk((s.root,)))
    stats["stuck_components"] += states[F.STUCK]
    stats["gone_components"] += states[F.GONE]
    stats["docs_with_stuck"] += bool(states[F.STUCK])
    stats["docs_with_gone"] += bool(states[F.GONE])
    stats["docs_with_selected"] += has_selected(doc)
    paths = has_path_selected(doc)
    stats["docs_with_path_selected"] += paths
    stats["assignments"] += sum(1 for _ in s.assignments())
    stats["docs_with_dec_and_amb"] += any(
        amb and dec for sigma in s.assignments() for name in doc.entities
        for mu in s.members(name, sigma) if not s.removed(mu) and s.owners(mu)
        for dec, amb in [s.outcomes(s.owners(mu), sigma)])

    # (1) 정리 5 --------------------------------------------------------------
    try:
        S, ann = unfold_annotated(doc, functions)
    except AlgebraError as e:
        stats["unfold_raised"] += 1
        fail("unfold", f"unfold_annotated 가 AlgebraError 를 냈다: {e}")
        S = None
    if S is not None:
        T = S.tree
        theirs = sem(S)
        mine = [s.nodes(sigma, kappa) for sigma, kappa in listed]
        stats["tree_nodes"] += len(T.nodes)
        stats["unfolded_variants"] += len(theirs)
        if len(set(mine)) != len(mine):
            fail("T5-injective", f"변이 {len(mine)}개가 노드 집합 {len(set(mine))}개를 낸다")
        if len(set(theirs)) != len(theirs):
            fail("T5-tree", "펼친 나무가 같은 변이를 두 번 낸다")
        not_in_tree = [V for V in mine if not V <= T.nodes]
        if not_in_tree:
            fail("T5-nodes", f"nu 가 T(D) 에 없는 노드를 낸다: {sorted(not_in_tree[0] - T.nodes)}")
        if set(mine) != set(theirs):
            only_mine, only_theirs = set(mine) - set(theirs), set(theirs) - set(mine)
            fail("T5-bijection", f"정의 표 {len(mine)} 펼친 나무 {len(theirs)}. 정의 표에만 {len(only_mine)}, "
                                 f"펼친 나무에만 {len(only_theirs)}. 예: "
                                 f"{sorted(next(iter(only_mine or only_theirs)))}")
        wf_mine = {V for V, ok in zip(mine, wf_flags) if ok}
        wf_theirs = {V for V in theirs if not core_violations(T, ann.void, V)}
        if wf_mine != wf_theirs:
            fail("T5-wellformed", f"핵 적격: 정의 표 {len(wf_mine)} 펼친 나무 {len(wf_theirs)}")
        wf_read = {V for V in theirs if wf_by_theorem5(doc, T, V)}
        if wf_read != wf_theirs:
            fail("T5-wellformed-statement", f"정리의 글로 읽은 것 {len(wf_read)} core_violations {len(wf_theirs)}")

        # (6) 글에서 읽은 정의 9 와 10 ------------------------------------------
        lit = bounded_literal.Literal(doc, functions)
        if dict(T.kinds) != lit.kinds:
            extra = sorted(set(T.kinds) - set(lit.kinds))
            missing = sorted(set(lit.kinds) - set(T.kinds))
            fail("D9-tree", f"unfold 에 정의 9 에 없는 {extra[:4]} 가 있고 {missing[:4]} 가 없다")
        elif any(T.label(u) != lab for u, lab in lit.labels.items()):
            fail("D9-labels", "표지가 다르다")
        literal = lit.variants()
        stats["literal_tree_variants"] += len(literal)
        if set(literal) != set(theirs) or len(literal) != len(theirs):
            a, b = set(literal) - set(theirs), set(theirs) - set(literal)
            fail("D10-psi", f"글의 Psi(D) 는 변이 {len(literal)}개, unfold 는 {len(theirs)}개. "
                            f"예: {sorted(next(iter(a or b)))}")

        # (4) 따름정리 5.1 ----------------------------------------------------
        for (sigma, kappa), V, ok in zip(listed, mine, wf_flags):
            if not V <= T.nodes:
                continue
            sk = skeleton(T, ann.void, V)
            cv = core_violations(T, ann.void, V)
            if (not cv) != ok:
                fail("C51-core_violations", f"sigma {sigma}: core_violations {cv} 인데 well_formed 는 {ok}")
            if kappa.state == F.GONE:
                if sk is not None or [c for c, _, _ in cv] != ["K0"]:
                    fail("C51-root-gone", f"sigma {sigma}: 뿌리가 빠졌는데 뼈대 {sk}, 위반 {cv}")
                continue
            if sk is None:
                fail("C51-root-gone", f"sigma {sigma}: 뼈대가 없는데 뿌리는 {kappa.state}")
                continue
            problems, stuck_at = [], []
            compare_skeleton(T, sk, kappa, (s.root,), problems, stuck_at)
            if problems:
                fail("C51-skeleton", f"sigma {sigma}: " + "; ".join(problems[:3]))
            if sorted((c, p) for c, p, _ in cv) != sorted(("K1", p) for p in stuck_at):
                fail("C51-K1", f"sigma {sigma}: 위반 {cv} 인데 정할 수 없는 자리는 {stuck_at}")

    # (2) 정리 3 --------------------------------------------------------------
    by_sigma: dict = {}
    for (sigma, kappa), ok in zip(listed, wf_flags):
        key = tuple(sorted(sigma.items()))
        total, wf = by_sigma.get(key, (0, 0))
        by_sigma[key] = (total + 1, wf + ok)
    try:
        counted = {tuple(sorted(sigma.items())): (total, wf)
                   for sigma, total, wf in F.Evaluator(doc, functions).per_assignment() if total}
        if counted != by_sigma:
            diff = sorted(k for k in set(counted) | set(by_sigma) if counted.get(k) != by_sigma.get(k))
            fail("T3-per-assignment", f"sigma {dict(diff[0])}: Evaluator {counted.get(diff[0])} "
                                      f"열거 {by_sigma.get(diff[0])}")
        totals = (sum(t for t, _ in by_sigma.values()), sum(w for _, w in by_sigma.values()))
        got = F.count(doc, functions)
        if got != totals:
            fail("T3-count", f"count {got} 열거 {totals}")
    except Exception as e:                                   # noqa: BLE001
        fail("T3-raised", f"{type(e).__name__}: {e}")

    # (3) 고전 절차 -----------------------------------------------------------
    if not paths:
        try:
            plain = load_ses_dict(stripped(d))
            sp = F.Semantics(plain, functions)
            mine_models = collections.Counter((tuple(sorted(sigma.items())), F.live_shape(sp.shape(kappa)))
                                              for sigma, kappa in sp.variants() if sp.well_formed(kappa))
            theirs_models = collections.Counter((tuple(sorted(sigma.items())), classic_shape(n))
                                                for sigma, n in classic.enumerate_classic(plain, functions))
            stats["classic_docs"] += 1
            stats["classic_models"] += sum(mine_models.values())
            if mine_models != theirs_models:
                only = (mine_models - theirs_models) + (theirs_models - mine_models)
                fail("classic", f"WVar 의 모델 {sum(mine_models.values())}개, 고전 절차 "
                                f"{sum(theirs_models.values())}개. 예: {next(iter(only))}")
            # (3b) 고전 절차의 구조에는 고른 분해가 없다. 선택도 견준다: (sigma, 구조, 정의 수준의 선택들)을
            # 고전 절차가 구조를 만들며 적어 둔 선택과 견준다.
            mine_made = collections.Counter(
                (tuple(sorted(sigma.items())), F.live_shape(sp.shape(kappa)),
                 frozenset((k, y, g, c) for _, k, y, g, c in sp.choices(kappa)))
                for sigma, kappa in sp.variants() if sp.well_formed(kappa))
            theirs_made = collections.Counter(
                (tuple(sorted(sigma.items())), classic_shape(n), frozenset(picks))
                for sigma, n, picks in classic_with_picks(plain, functions))
            if mine_made != theirs_made:
                only = (mine_made - theirs_made) + (theirs_made - mine_made)
                fail("classic-choices", f"정의 표와 고전 절차가 한 선택이 다르다. 예: {next(iter(only))}")
        except Exception as e:                               # noqa: BLE001
            fail("classic-raised", f"{type(e).__name__}: {e}")

    # (5) 정리 1 (c), 정리 2 (b) 에서 (e) -------------------------------------
    check_clusters(doc, s, functions, stats, fail)

    stats["failed_documents"] += bool(fails)
    return stats, fails


if __name__ == "__main__":
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as f:
            stats, fails = check_document(json.load(f))
        print(path, dict(stats))
        for check, msg in fails:
            print("  실패", check, msg)
