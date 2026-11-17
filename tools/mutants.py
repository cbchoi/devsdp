"""변이 목록 (tools/mutate.py 가 읽는다).

변이 하나는 (이름, 파일, 원본의 글, 틀린 글, 결과가 같은 변형이면 그 까닭)이다. 원본의 글은 파일에 정확히
한 번 있어야 한다. 코드를 고치면 이 목록도 고친다. `python tools/mutate.py --dry` 가 어긋난 것을 알려 준다.

대상은 의미의 핵이다. 정의 표 위의 의미(folded.py), 그 표현인 펼침의 규칙(unfold.py), 뼈대(skeleton.py),
문서의 조건(loader.py). docs/ses-platform/theory.md 의 정의와 정리마다 그것을 틀리게 하는 변이를 둔다.
"""

FO, UN, SK, LO = "ses_core/folded.py", "ses_core/unfold.py", "ses_core/skeleton.py", "ses_core/loader.py"

# 빠른 묶음: 의미의 핵을 직접 보는 시험. 여기서 살아남으면 전체를 돌린다
FAST = ["tests/test_folded.py", "tests/test_loader.py", "tests/test_parity.py", "tests/test_diagnose.py"]
FULL = ["tests"]


def m(name, file, old, new, same=None):
    return (name, file, old, new, same)


MUTANTS = [
    # 정의 1. 우선순위의 순서 ------------------------------------------------
    m("F1 우선순위의 방향을 뒤집음", FO, "    return p is not None and (q is None or p < q)",
      "    return p is not None and (q is None or p > q)"),
    m("F2 없는 우선순위가 가장 앞섬", FO, "    return p is not None and (q is None or p < q)",
      "    return q is not None and (p is None or p < q)"),
    # 정의 2. 병합체 --------------------------------------------------------
    m("F3 없음 대안이 있어도 빠지지 않음", FO,
      "        return any(self.doc.entities[y].stereotype == m.Stereotype.VOID for y in mu.names())",
      "        return False"),
    # 정의 3. 요구, Dec, Amb -------------------------------------------------
    m("F4 참인 규칙의 분해를 우선순위로 거르지 않음", FO,
      "        return [[x for x in forced if not any(above(w.priority, x.priority) for w in forced)]]",
      "        return [forced]",
      "밀린 분해는 요구에 남아 있어도 결과를 바꾸지 않는다. 그것보다 앞선 분해가 같은 요구에 있으므로 홀로 가장 앞선 것도, "
      "가장 앞선 자리에서 맞서는 것도 될 수 없다"),
    m("F5 홀로 가장 앞선 것 대신 밀리지 않은 것을 결과로 봄", FO,
      "            first = [(y, x) for y, x in pool if all(above(x.priority, w.priority) for _, w in pool if w is not x)]",
      "            first = [(y, x) for y, x in pool if not any(above(w.priority, x.priority) for _, w in pool if w is not x)]"),
    # 정의 4. 구성요소 선택 --------------------------------------------------
    m("F6 정할 수 없는 조합이 있어도 stuck 을 두지 않음", FO,
      "            if ambiguous:\n                out.append(Comp(mu, STUCK))",
      "            if ambiguous and not dec:\n                out.append(Comp(mu, STUCK))"),
    # 정의 6. 핵 적격 --------------------------------------------------------
    m("F7 뿌리가 빠져도 적격으로 봄", FO,
      "        return kappa.state != GONE and all(c.state != STUCK for _, c in kappa.walk((self.root,)))",
      "        return all(c.state != STUCK for _, c in kappa.walk((self.root,)))"),
    # 정의 7. 경로 수준의 selected -------------------------------------------
    m("F8 경로 수준의 selected 가 자리를 보지 않음", FO,
      "                if pos != want:\n                    continue",
      "                if False:\n                    continue"),
    # 정리 5. 표현 -----------------------------------------------------------
    m("F9 빠진 구성요소의 구성원이 빠짐 대신 분해 없음을 고름", FO,
      "                    out.add(at + (\"-\",))", "                    out.add(at + (\"~\",))"),
    # 정리 3. 열거하지 않는 계산 ----------------------------------------------
    m("F10 뿌리가 빠진 것을 부적격으로 세지 않음", FO,
      "                body = self.ill(ROOT_GONE) if len(pos) == 1 else self.one     # 뿌리가 빠지면 부적격이다",
      "                body = self.one"),
    m("F11 정할 수 없는 조합을 세지 않음", FO,
      "                body = self.ill((\"stuck\", d, tuple(sorted(owners)))) if ambiguous else {}",
      "                body = self.ill((\"stuck\", d, tuple(sorted(owners)))) if ambiguous and not dec else {}"),
    m("F12 따로 센 복제본을 거듭제곱에서 빼지 않음", FO,
      "                            inner = p_mul(inner, p_pow(one, n - len(special), self.one))",
      "                            inner = p_mul(inner, p_pow(one, n, self.one))"),
    m("F13 경로 수준의 selected 를 모든 자리에서 본 것으로 셈", FO,
      "        for a in self.by_path.get(pos, ()):",
      "        for a in [x for xs in self.by_path.values() for x in xs]:"),
    m("F14 따로 세야 하는 자리도 정의마다 한 번만 셈", FO,
      "        shared = pos not in self.focus               # 이 자리 아래를 따로 묻는 제약이 없으면 정의마다 한 번만 센다",
      "        shared = True"),
    m("F15 부적격 변이를 적격으로 셈", FO, "sum(n for seen, n, _ in terms if ILL not in seen)", "sum(n for seen, n, _ in terms)"),
    # 족 수준의 분석 ----------------------------------------------------------
    m("A1 부적격 변이에서 일어난 일을 적격 변이의 것으로 셈", FO,
      "            else:\n                wellformed += n\n                live_wf |= events",
      "            else:\n                wellformed += n\n            if True:\n                live_wf |= events"),
    m("A2 분해를 내지 않은 주인을 적지 않음", FO,
      "                    pushed = [(\"pushed\", z) for z in owners if z != y] if self.live else ()",
      "                    pushed = ()"),
    m("A3 변이가 있는 변수 값을 적지 않음", FO,
      "                for name, v in sigma.items():\n                    values[name][1].add(v)",
      "                pass"),
    m("A4 분해를 정할 수 없는 곳의 예를 적지 않음", FO,
      "                    if e == ROOT_GONE or e[0] == \"stuck\":", "                    if e == ROOT_GONE:"),
    m("D1 한도를 넘었을 때의 죽은 선택지: 밀림을 보지 않음", "ses_core/diagnose.py",
      "            pushed = kind == \"aspect\" and (\"pushed\", owner) in fam.live_wf", "            pushed = False"),
    m("D2 한도를 넘었을 때의 죽은 선택지: 선택지가 하나인 지점도 알림", "ses_core/diagnose.py",
      "        if len(options) < 2:\n            continue\n        if kind == \"variable\":",
      "        if kind == \"variable\":"),
    m("D3 한도를 넘었을 때 분해를 정할 수 없는 곳을 알리지 않음", "ses_core/diagnose.py",
      "        add(\"error\", \"K1\", f\"{name} 의 병합체에서", "        (lambda *a: None)(\"error\", \"K1\", f\"{name} 의 병합체에서"),

    # 정의 9. 표시 노드 ------------------------------------------------------
    m("U1 자기 규칙끼리 다투는 구성원에 분해 없음을 주지 않음", UN,
      "                if rivals[y] or any(tied(a, b) for i, a in enumerate(ruled) for b in ruled[i + 1:]):",
      "                if rivals[y]:"),
    m("U2 다른 주인과 함께 골라지는 구성원에 분해 없음을 주지 않음", UN,
      "                if rivals[y] or any(tied(a, b) for i, a in enumerate(ruled) for b in ruled[i + 1:]):",
      "                if any(tied(a, b) for i, a in enumerate(ruled) for b in ruled[i + 1:]):"),
    m("U3 빠짐 표시를 만들지 않음", UN, "                if any(together(y, z) for z in voids):", "                if False:"),
    m("U4 한 specialization 의 대안끼리도 함께 골라진다고 봄", UN,
      "            return i == len(y) or i == len(z) or kinds[y[:i]] != SPEC", "            return True"),
    # 정의 10. 식 -------------------------------------------------------------
    m("U5 (G1) 빠지면 빠짐을 고르게 하지 않음", UN,
      "            self.clauses.append(f_imp(f_and(sel(y), removed), marker))", "            pass"),
    m("U6 (G2) 빠지지 않아도 빠짐을 고를 수 있음", UN, "            self.clauses.append(f_imp(marker, removed))", "            pass"),
    m("U7 (C1) 고른 분해가 Dec 에 드는지 보지 않음", UN,
      "                    self.clauses.append(f_imp(one_of(d[1]), wins[y, i]))       # 고른 분해는 Dec 에 든 것이다",
      "                    pass"),
    m("U8 (C3) 분해를 둘 고를 수 있음", UN,
      "                        self.clauses.append(f_not(f_and(real[y], real[z])))", "                        pass"),
    m("U9 (C2) 정할 수 있어도 아무도 분해를 내지 않을 수 있음", UN,
      "            self.clauses.append(f_imp(nobody, f_or(*ambiguous)))", "            pass"),
    m("U10 wins: 다른 주인의 요구를 보지 않음", UN,
      "                    conds = [sel(y), alone(y, i)]\n                    for z in rivals[y]:",
      "                    conds = [sel(y), alone(y, i)]\n                    for z in ():"),
    m("U11 wins: 요구의 전부가 아니어도 이김", UN, "                    conds = [sel(y), alone(y, i)]",
      "                    conds = [sel(y), demanded(y, i)]"),
    m("U12 top: 더 앞선 참인 규칙에 물러서지 않음", UN,
      "                                                if j != i and above(mine[j][3], mine[i][3]))) for i in forced}",
      "                                                if False)) for i in forced}"),
    m("U13 amb: 한 주인의 요구에 둘인 경우를 보지 않음", UN,
      "                tie = f_or(*(f_and(sel(y), two[y]) for y in owners),\n", "                tie = f_or(\n"),
    m("U14 amb: 두 주인의 요구에 하나씩인 경우를 보지 않음", UN,
      "                             for z in owners[i + 1:] if z in rivals[y]))", "                             for z in ()))"),
    m("U15 amb: 더 앞선 분해가 없어야 한다는 조건을 보지 않음", UN,
      "                ambiguous.append(f_and(tie, *(f_imp(sel(y), behind[y]) for y in owners)))",
      "                ambiguous.append(tie)"),

    # 뼈대와 핵 적격 ----------------------------------------------------------
    m("K1 정할 수 없음을 골라지지 않은 노드로 판정 (가지치기에서 달라진다)", SK,
      "        stuck = not asps and any(y + (NO_ASPECT,) in V for y in ms)",
      "        stuck = not asps and any(real_aspects(T, y) for y in ms)"),
    m("K2 정할 수 없는 구성요소를 위반으로 알리지 않음", SK, "        if c.stuck:", "        if False:"),
    m("K3 핵의 특성식이 정할 수 없음을 보지 않음", SK,
      "            clauses.append(f_imp(f_and(le, f_or(*(sel(n) for n in none))), f_or(*(sel(a) for _, a in asps))))",
      "            pass"),

    # 문서의 조건 -------------------------------------------------------------
    m("L1 (W4) 이름의 글자를 보지 않음", LO, "            if x not in MARKERS and not _IDENTIFIER.match(str(x)):",
      "            if False:"),
    m("L2 (W4) 변수 이름의 글자를 보지 않음", LO, "        if not _IDENTIFIER.match(str(vname)):", "        if False:"),
    m("L3 (W5) 글자로 적으면 같은 값을 받음", LO,
      "            twice = sorted({w for w in written if written.count(w) > 1})\n            if twice:",
      "            twice = sorted({w for w in written if written.count(w) > 1})\n            if False:"),
]
