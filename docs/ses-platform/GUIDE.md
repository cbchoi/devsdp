# 처음 오는 연구자를 위한 안내서

작성일: 2026-11-23. 이 안내서의 2절에서 7절의 걸음은 `tests/test_guide.py`가 그대로 돌린다. 적힌 출력이 실제와 달라지면 그 시험이 실패한다. 글 상자의 출력은 실제 출력 가운데 몇 줄을 옮긴 것이다. 전부가 아니다.

## 0. 이 안내서가 하는 일

두 시간쯤 따라 하면 자기 분야를 올릴 묶음 하나를 손에 쥔다. 묶음은 디렉터리 하나이고 네 가지가 든다.

| 든 것 | 무엇인가 | 누가 정하는가 |
|---|---|---|
| SES 문서 | 그 분야의 시스템이 가질 수 있는 구조 전부. 구조의 족이다 | 연구자 |
| 모델 베이스 | 구성요소가 무엇을 하는지. 원자 모델들이다 | 연구자 |
| 바인딩 | 문서의 정의를 모델 베이스의 모델에 잇는다 | 연구자 |
| 사례 | 족에서 고른 구조 하나. 결정 집합으로 적는다 | 연구자 |

플랫폼이 하는 일은 이것들이 서로 맞는지를 보고, 고른 구조를 조립해 돌리는 것이다. 연구자마다 분야와 모델은 다르고, 공통인 것은 형식과 검사다.

알아 둘 낱말은 다섯이다.

- 엔티티(entity). 시스템의 구성요소 하나. 문서에서는 "정의"라고 부른다.
- 분해(aspect). 엔티티가 무엇으로 이루어지는가. 부분들과 그 사이의 결합을 적는다.
- 대안(specialization). 엔티티가 무엇 가운데 하나인가. 대안들을 적는다.
- 복제(multi-aspect). 같은 부분이 몇 개 있는가. 개수를 수, 범위, 변수로 적는다.
- 변이. 대안과 개수를 모두 정해서 나온 구조 하나. 문서 하나가 변이 여럿을 뜻한다.

## 1. 설치

파이썬 3.11 이상이 있어야 한다. 저장소를 받은 자리에서 설치한다.

```bash
pip install -e ".[test]"
```

```bash
ses --help
```

`ses`라는 명령이 생긴다. 다른 시뮬레이션 엔진은 없어도 된다. 참조 시뮬레이터가 들어 있다. pyevsim과 cevsim에서도 돌려 보려면 8절을 본다.

## 2. 첫 묶음을 만든다

빈 자리에서 다음을 친다. `mylab` 자리에 자기 묶음의 이름을 쓴다. 이름은 글자, 숫자, 밑줄로 쓴다.

```bash
ses pack new mylab
```

파일 여섯을 만들고, 바로 검사하고, 그 결과를 일곱째 파일 `records.yaml`에 적는다. 출력 가운데 몇 줄은 이렇다.

```text
검사하고 기록을 적었다: mylab/records.yaml
info P7 cevsim: 이 실행기에서는 돌리지 않았다. cevsim 의 소스(환경 변수 CEVSIM_HOME)나 C++ 컴파일러가 없다
문서 mylab.ses.yaml: 변이 2개, 그 가운데 적격 2개
사례 fast: 원자 구성요소 3개, 연결 2개. 사건 19개, 지문 253f991d865d276f. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
사례 slow: 원자 구성요소 3개, 연결 2개. 사건 16개, 지문 a1eec6a2077ace65. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
```

`info P7`로 시작하는 줄은 다른 엔진이 이 컴퓨터에 없다는 알림이다. 오류가 아니다. 검사할 때마다 나온다. pyevsim에 대한 같은 줄도 나온다.

만들어진 것은 작업을 내는 원천, 그것을 처리하는 처리기, 모으는 수집기로 된 줄이다. 처리기는 빠른 것과 느린 것 가운데 하나다. 그래서 변이가 둘이다.

| 파일 | 내용 |
|---|---|
| `pack.yaml` | 묶음의 선언. 무엇이 어디 있는지 |
| `mylab.ses.yaml` | SES 문서 |
| `model_base.py` | 원자 모델 셋(Source, Worker, Sink) |
| `binding.yaml` | 정의를 모델에 잇는다. 시간 단위 |
| `cases/fast.decisions.yaml`, `cases/slow.decisions.yaml` | 사례 둘 |
| `records.yaml` | 사례를 돌린 기록의 요약. 도구가 적는다 |

파일마다 맨 위에 설명이 있다. 지금 한 번씩 열어 읽는다. 십 분이면 된다.

`ses pack new mylab --template full`은 더 큰 묶음을 만든다. 이 안내서의 6절과 7절의 걸음을 끝까지 따라간 상태와 같다. 변수, 규칙, 없음 대안, 복제, 사례마다 다른 값이 모두 들어 있다. 걸음을 따라갈 때는 쓰지 않는다. 걸음을 마친 뒤에 형식의 본보기로 쓰거나, 따라가다 막혔을 때 견주어 본다.

## 3. 문서에 묻는다

묶음 디렉터리로 들어간다.

```bash
cd mylab
ses check mylab.ses.yaml
```

```text
변이 2개, 그 가운데 적격 2개
```

`check`는 문서가 뜻하는 모든 변이를 본다. 모든 변이가 조립되는지, 쓰이지 않는 선택지가 있는지를 알린다.

무엇을 고를 수 있는지는 `choices`가 알린다.

```bash
ses choices mylab.ses.yaml
```

```text
남은 변이 2개
Worker alternative speed: 열림. 남은 선택지 ['Fast', 'Slow'] / 전체 ['Fast', 'Slow']
```

결정 집합을 주면 그 결정을 따르는 변이만 남는다.

```bash
ses choices mylab.ses.yaml --decisions cases/slow.decisions.yaml
```

```text
남은 변이 1개
Worker alternative speed: 정해짐. 남은 선택지 ['Slow'] / 전체 ['Fast', 'Slow']
```

남은 변이가 하나이면 조립할 수 있다.

```bash
ses build mylab.ses.yaml --decisions cases/slow.decisions.yaml
```

```text
Line
  Source
  Worker: Worker, Slow
  Sink
변수 값 {}. 구성요소 4개, 노드 7개
```

`Worker: Worker, Slow`는 그 자리에 Worker와 Slow가 합쳐졌다는 뜻이다. 대안을 고르면 그 대안의 정의가 엔티티에 합쳐진다. 포트와 속성도 합쳐진다. 마지막 줄의 구성요소는 위에 그려진 상자의 수이고(뒤에 나오는 `없음`으로 적힌 줄은 세지 않는다), 노드는 문서의 뜻을 적는 나무의 마디의 수다. 노드의 수는 몰라도 된다.

속성의 값까지 보려면 `--attributes`를 붙인다. 이 묶음에서 쓰는 명령을 경로까지 채워서 보려면 `ses pack show .`를 친다.

## 4. 돌려 본다

```bash
ses pack run . fast --log 4
```

```text
2.0 Source.out {"id": 0}
3.0 Worker.out {"id": 0}
4.0 Source.out {"id": 1}
5.0 Worker.out {"id": 1}
변수 값 {}. 원자 구성요소 3개. 출력 사건 19개, 마지막 시각 20.0
```

줄마다 시각, 낸 구성요소와 포트, 값이다. 원천이 2마다 작업을 내고 빠른 처리기가 1 뒤에 내보낸다. 기록에는 출력 사건만 남는다. 모델 안의 상태는 보이지 않는다. 재고 싶은 값이 있으면 모델이 포트로 내게 한다. 어디에도 이어지지 않은 출력 포트로 내도 기록에 남는다.

기록 전체를 프로그램에서 읽으려면 JSON으로 받는다(11절).

## 5. 검사를 돌린다

고칠 때마다 이것을 돌린다.

```bash
ses pack check .
```

마지막 줄이 `묶음 mylab: 통과`이면 된다. 알리는 줄의 첫 낱말은 error, warning, info 가운데 하나다. 그 뒤에 문서, 사례, 묶음으로 시작하는 요약의 줄이 온다. error가 하나도 없으면 통과다. warning은 통과를 막지 않지만 읽어야 한다. 검사가 보는 것은 여덟 가지다.

| 부호 | 보는 것 | 흔한 까닭 |
|---|---|---|
| P0 | 선언(pack.yaml) | 없는 파일, 잘못 적은 항목 |
| P1 | 문서 | 잘못 적은 항목, 없는 정의를 가리킴, 이름이 겹침 |
| P2 | 모델 베이스 | 파이썬 오류, 포트나 매개변수의 선언이 틀림 |
| P3 | 바인딩 | 문서에 없는 정의나 없는 모델을 적음. target이 문서의 name과 다름 |
| P4 | 사례의 결정 | 없는 선택지를 적음, 결정이 모자라 구조가 하나로 정해지지 않음. target이 문서의 name과 다름 |
| P5 | 조립과 실행 가능성 | 묶이지 않은 구성요소, 모델과 문서의 포트가 다름, 구동되지 않는 필수 입력, 시간 값이 시간 단위의 정수배가 아님 |
| P6 | 실행과 기록 | 모델이 예외를 냄, 두 번 돌린 기록이 다름, 받은 값을 고침, 적어 둔 기록과 다름 |
| P7 | 실행기 사이의 일치 | 다른 엔진에서 기록이 다름 |

## 6. 자기 분야로 바꾼다

네 걸음을 따라 하면 무엇을 어디서 고치는지 알게 된다. 그다음에 이름과 내용을 자기 분야의 것으로 바꾼다.

### 걸음 1. 대안을 하나 더한다

처리기의 셋째 대안 Careful을 더한다. 파일 넷의 다섯 군데를 고친다.

`mylab.ses.yaml`에서 대안의 목록에 이름을 넣는다.

```yaml
        alternatives: [Fast, Careful, Slow]
```

같은 파일에 그 정의를 더한다. Slow 위에 둔다.

```yaml
  Careful:
    extends: Worker
    attributes:
      service: {type: float, default: 2.0}
```

`binding.yaml`의 map에 한 줄을 더한다.

```yaml
  Careful: {module: Worker}
```

사례를 하나 만든다. `cases/careful.decisions.yaml`이다.

```yaml
decisions: "1.0"
name: careful
target: Line

choose:
  - {at: Worker, specialization: speed, alternative: Careful}
```

`pack.yaml`의 cases에 그 사례를 적는다.

```yaml
  - {name: careful, decisions: cases/careful.decisions.yaml, until: 20}
```

검사한다.

```bash
ses pack check .
```

```text
warning P6 careful: 적어 둔 기록이 없다. ses pack check --record 로 적는다
문서 mylab.ses.yaml: 변이 3개, 그 가운데 적격 3개
묶음 mylab: 통과, 경고 1건
```

새 사례의 기록을 적어 둔다.

```bash
ses pack check . --record
```

### 걸음 2. 일부러 틀려 본다

`mylab.ses.yaml`에서 Careful의 `default`를 `value`로 바꾸고 검사한다.

```text
error P1 mylab.ses.yaml: 문서를 적재할 수 없다. Careful: 속성 service: 모르는 항목 value 가 있다. default 를 뜻했는가. 쓸 수 있는 것은 ['default', 'doc', 'each', 'expr', 'type', 'unit', 'values'] 다
묶음 mylab: 오류 1건
```

검사는 어느 정의의 무엇이 틀렸는지를 적는다. `default`로 되돌린다.

### 걸음 3. 원자 모델을 하나 더한다

처리기와 수집기 사이에 검사기를 넣는다. 세 번째 작업마다 하나를 버린다. 세 파일을 고친다.

`mylab.ses.yaml`에서 Line의 분해를 고친다. 부분과 결합이다.

```yaml
        parts: [Source, Worker, Inspector, Sink]
        couplings:
          - {from: Source.out, to: Worker.in}
          - {from: Worker.out, to: Inspector.in}
          - {from: Inspector.ok, to: Sink.in}
```

같은 파일에 정의를 더한다. Sink 위에 둔다.

```yaml
  Inspector:
    ports:
      in: {type: Job, direction: in, required: true}
      ok: {type: Job, direction: out}
    attributes:
      every: {type: int, default: 3, doc: 이 번째 작업마다 하나를 버린다}
```

여기서 검사하면 구조는 맞고 행동이 없다는 것을 알린다.

```text
error P5 fast: 이 변이는 실행 가능하지 않다. exec:devs B1 Line/Inspector: 원자 구성요소 Inspector 에 묶인 모듈이 없다
```

`model_base.py`에 모델을 쓴다. Sink 위에 둔다.

```python
class Inspector(Atomic):
    """every 번째 작업마다 하나를 버리고 나머지는 바로 넘긴다."""
    PORTS = {"in": ("Job", "in"), "ok": ("Job", "out")}
    REQUIRED = ("in",)
    PARAMS = {"every": ("int", 3)}

    def init(self):
        self.seen, self.passing = 0, []

    def ta(self):
        return 0.0 if self.passing else INF

    def output(self):
        return {"ok": list(self.passing)}

    def internal(self):
        self.passing = []

    def external(self, elapsed, bag):
        for job in bag.get("in", []):
            self.seen += 1
            if self.seen % self.every:
                self.passing.append(job)
```

같은 파일 맨 아래의 LIBRARY에 넣는다.

```python
LIBRARY = {m.name: m for m in (module_of(c) for c in (Source, Worker, Inspector, Sink))}
```

`binding.yaml`의 map에 한 줄을 더한다.

```yaml
  Inspector: {module: Inspector}
```

검사한다. 이번에는 기록이 달라졌다고 알린다.

```text
error P6 fast: 기록이 적어 둔 것과 다르다. 적어 둔 것은 사건 19개 (지문 253f991d865d276f), 지금은 25개 (지문 dec6335bffb42167). 뜻한 변화이면 --record 로 다시 적는다
```

뜻한 변화이므로 다시 적는다.

```bash
ses pack check . --record
```

```text
문서 mylab.ses.yaml: 변이 3개, 그 가운데 적격 3개
사례 fast: 원자 구성요소 4개, 연결 3개. 사건 25개, 지문 dec6335bffb42167. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
사례 slow: 원자 구성요소 4개, 연결 3개. 사건 20개, 지문 32fb94ccaaef9791. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
사례 careful: 원자 구성요소 4개, 연결 3개. 사건 25개, 지문 5d577716f47f6822. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
묶음 mylab: 통과
```

기록의 지문은 누가 어디서 돌려도 같다. 모델을 고쳤는데 뜻하지 않게 결과가 달라지면 검사가 잡는다. 뜻하지 않은 변화인데 `--record`로 덮으면 그 검사를 끈 것이다.

### 걸음 4. 사례마다 값을 달리한다

구조는 같고 값만 다른 사례는 결정 집합의 `set`으로 만든다. 문서를 고치지 않는다. 원천이 두 배로 자주 내는 사례 `cases/rush.decisions.yaml`이다.

```yaml
decisions: "1.0"
name: rush
target: Line

choose:
  - {at: Worker, specialization: speed, alternative: Fast}
set:
  - {at: Source, attribute: period, value: 1.0}
```

`pack.yaml`의 cases에 적는다.

```yaml
  - {name: rush, decisions: cases/rush.decisions.yaml, until: 20}
```

값이 모델까지 갔는지는 `plan`으로 본다. 원자 구성요소마다 묶인 모델과 받은 값을 보인다.

```bash
ses plan mylab.ses.yaml --decisions cases/rush.decisions.yaml --binding binding.yaml --library model_base:LIBRARY
```

```text
Source: Source {"period": 1.0}
Worker: Worker {"service": 1.0}
```

`at`은 정의의 이름이다. 그 정의가 놓인 모든 자리에 적용된다. 한 자리만 바꾸려면 `path`로 구성요소의 경로를 적는다. 경로는 뿌리의 이름에서 시작한다. `{path: [Line, Source], attribute: period, value: 1.0}`이다. `plan`과 기록은 뿌리를 빼고 `Source`라고 보이지만 결정에는 뿌리부터 적는다.

`set`을 적을 때 알아 둘 것이 다섯이다.

- 같은 속성을 `at`으로도 `path`로도 적으면 그 자리에서는 `path`로 적은 값이 쓰인다. 걸음 6의 `choose`는 다르다. 거기서는 둘 다 적용된다.
- 속성의 이름을 잘못 적으면 오류다(P4). 그 정의나 그 자리의 구성요소에 있는 속성을 줄이 적는다.
- 대안이 가진 속성은 그 대안의 이름으로 적는다. `{at: Fast, attribute: service, value: 2.0}`이다. 바탕 정의의 이름(Worker)으로 적으면 그 정의에 그 속성이 없다고 나오고, 줄이 어느 대안이 그 속성을 가지는지를 적는다.
- `set`은 문서가 식(`expr`)으로 정한 속성도 바꾼다. 경고가 없다. 걸음 6의 `me`와 `of`처럼 구조에서 정해지는 속성은 `set`에 적지 않는다.
- 이 변이에 없는 자리나 정의를 가리킨 `set`은 오류가 아니다. `warning P4 ...: 쓰이지 않은 결정`으로만 알린다.

문서의 속성은 묶인 모델의 PARAMS에 같은 이름이 있을 때만 모델에 간다. 이름이 다르면 모델은 자기 기본값으로 돈다. 검사가 `warning P5`로 알린다.

기록을 적는다.

```bash
ses pack check . --record
```

### 이제 자기 분야로

정의의 이름, 포트, 속성, 모델을 자기 분야의 것으로 바꾼다. 순서는 문서, 모델 베이스, 바인딩, 사례다. 바꿀 때 자주 걸리는 것이 다섯이다.

- 문서를 통째로 바꾸는 동안에는 `ses check 문서`, `ses choices 문서`, `ses build 문서 --decisions 파일`로 구조부터 맞춘다. 이 셋은 모델 베이스와 바인딩 없이 돈다. `ses pack check .`는 네 파일을 다 바꿀 때까지 P3와 P4의 오류를 낸다. 정상이다. 오류가 줄어드는지를 본다.
- 문서의 `name`을 바꾸면 `binding.yaml`의 `target`과 모든 결정 집합의 `target`도 같은 이름으로 바꾼다.
- 사례의 이름을 바꾸거나 지우면 `records.yaml`에 옛 기록이 남았다는 경고가 나온다. `ses pack check . --record`가 지운다.
- 모델의 PORTS에 적은 포트는 문서의 그 정의의 `ports`에도 적는다. 타입과 방향이 같아야 한다.
- 결정 집합 파일의 `name`은 설명이다. 검사가 견주지 않는다. 사례의 이름은 `pack.yaml`의 cases에 적은 것이다.

## 7. 족을 넓힌다

구조가 달라지는 두 가지 흔한 경우다. 부분이 있을 수도 없을 수도 있는 경우와, 같은 부분이 여러 개인 경우다. 둘 다 변수를 쓴다.

### 걸음 5. 있을 수도 없을 수도 있는 부분

검사기를 뺄 수 있게 한다. 세 가지를 적는다. 변수, 없음 대안, 그리고 검사기가 없을 때의 결합이다. 이 플랫폼에는 조건에 따라 달라지는 결합이 없다. 그래서 분해를 둘로 적고 규칙으로 고른다. 두 분해에 공통인 결합은 두 번 적는다.

`mylab.ses.yaml`의 `entities:` 위에 변수를 둔다.

```yaml
variables:
  inspect: {type: int, range: [0, 1], doc: 검사기를 두는가. 1 이면 둔다}
```

Line의 `aspects`를 둘로 바꾼다. `rule`이 참인 분해가 골라진다.

```yaml
    aspects:
      inspected:                             # 검사기가 있을 때
        rule: {var: inspect, eq: 1}
        parts: [Source, Worker, Inspector, Sink]
        couplings:
          - {from: Source.out, to: Worker.in}
          - {from: Worker.out, to: Inspector.in}
          - {from: Inspector.ok, to: Sink.in}
      direct:                                # 검사기가 없을 때. 처리기에서 바로 수집기로 간다
        rule: {var: inspect, eq: 0}
        parts: [Source, Worker, Inspector, Sink]
        couplings:
          - {from: Source.out, to: Worker.in}
          - {from: Worker.out, to: Sink.in}
```

Inspector의 `attributes` 아래에 대안을 두고 정의 둘을 더한다. `stereotype: void`가 없음 대안이다. 고르면 그 구성요소가 구조에서 빠진다. 없음 대안은 바인딩에 적지 않는다.

```yaml
    specializations:
      presence:
        alternatives: [Present, Absent]
        select: {when: {var: inspect, eq: 1}, then: Present, else: Absent}

  Present:
    extends: Inspector

  Absent:
    extends: Inspector
    stereotype: void
```

검사하면 사례마다 변수의 값을 묻는다.

```text
error P4 fast: 결정이 모자라다. 문서: 변수 inspect이(가) 정해지지 않았다. 남은 선택지: [0, 1]
```

사례 넷의 결정 집합에 변수의 값을 적는다. `target` 줄 아래에 둔다.

```yaml
variables:
  inspect: 1
```

검사기가 없는 사례 `cases/direct.decisions.yaml`을 만든다.

```yaml
decisions: "1.0"
name: direct
target: Line

variables:
  inspect: 0

choose:
  - {at: Worker, specialization: speed, alternative: Fast}
```

`pack.yaml`의 cases에 적는다.

```yaml
  - {name: direct, decisions: cases/direct.decisions.yaml, until: 20}
```

조립해 본다.

```bash
ses build mylab.ses.yaml --decisions cases/direct.decisions.yaml
```

```text
Line
  Inspector: 없음
  Source
  Worker: Worker, Fast
  Sink
변수 값 {'inspect': 0}. 구성요소 4개, 노드 12개
```

기록을 적는다. 사례 direct의 지문은 검사기를 넣기 전의 fast와 같다. 같은 구조이기 때문이다.

```bash
ses pack check . --record
```

```text
문서 mylab.ses.yaml: 변이 6개, 그 가운데 적격 6개
사례 direct: 원자 구성요소 3개, 연결 2개. 사건 19개, 지문 253f991d865d276f. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
```

규칙이 정하는 것은 다시 적지 않아도 된다. 변수의 값만 적으면 분해와 검사기의 대안은 규칙이 정한다. `ses choices`가 "남은 변이 1개"라고 하면 조립된다.

변수의 타입은 int, float, str, bool, enum 이다. 구조를 가르는 변수는 가질 수 있는 값이 유한해야 한다. int 는 `range: [1, 3]`으로 적고, 그 밖의 타입은 `values`로 값을 늘어놓는다. 이름 붙은 값 가운데 하나를 고르는 변수는 `control: {type: enum, values: [fixed, actuated]}`이고 규칙에서 `{var: control, eq: actuated}`로 견준다. bool 은 값을 적지 않는다. 범위가 넓은 값(씨앗, 시간, 용량)은 변수가 아니라 속성으로 두고 걸음 4의 `set`으로 준다. 정수 변수의 범위는 값 100,000개까지다.

변수와 대안에는 기본값을 적을 수 있다. 변수는 `inspect: {type: int, range: [0, 1], default: 1}`, 대안은 specialization 에 `default: Slow`다. 기본값은 사례가 쓰겠다고 할 때만 쓰인다. `pack.yaml`의 그 사례에 `defaults: true`를 적는다. 적지 않으면 기본값이 있어도 `결정이 모자라다`가 나온다. 명령에서는 `ses build 문서 --decisions 파일 --defaults`다.

### 걸음 6. 같은 부분을 여러 개 둔다

처리기를 여러 개 둔다. 그 수는 변수다. 복제된 부분은 그것을 담는 정의를 따로 둔다. 여기서는 Workers다.

변수를 하나 더한다. `inspect` 아래에 둔다.

```yaml
  workers: {type: int, range: [1, 3], doc: 처리기의 수}
```

Line의 두 분해에서 Worker를 Workers로 바꾼다. `parts`의 이름과 결합의 `Worker.in`, `Worker.out`이다. 여섯 군데다.

Worker 위에 Workers를 더한다. 결합에서 복제된 부분은 `{part}`로 적는다. `fan_out`은 들어온 값을 모든 복제본에 주고, `fan_in`은 모든 복제본의 출력을 모은다.

```yaml
  Workers:
    ports:
      in: {type: Job, direction: in, required: true}
      out: {type: Job, direction: out}
    multi_aspects:
      pool:
        part: Worker
        cardinality: {var: workers}
        naming: "w{i}"
        couplings:
          pattern: fan_out_fan_in
          fan_out: [{from: in, to: "{part}.in"}]
          fan_in: [{from: "{part}.out", to: out}]
```

모든 복제본이 모든 작업을 받는다. 한 작업을 한 처리기만 처리하게 하려면 복제본이 자기 번호를 알아야 한다. Worker의 `ports` 아래에 속성 둘을 둔다. 번호는 0부터 센다.

```yaml
    attributes:
      me: {type: int, expr: {replica: index}, doc: 몇 번째 복제본인가}
      of: {type: int, expr: {var: workers}, doc: 복제본이 모두 몇 개인가}
```

`model_base.py`의 Worker가 그 값을 받게 한다. PARAMS를 고친다.

```python
    PARAMS = {"service": ("time", 1.0), "me": ("int", 0), "of": ("int", 1)}
```

`external`에서 자기 몫의 작업만 줄에 세운다. 끝의 세 줄을 이것으로 바꾼다.

```python
        self.queue += [job for job in bag.get("in", []) if job["id"] % self.of == self.me]
        if self.queue and self.left == INF:
            self.left = self.service
```

사례 다섯의 결정 집합의 `variables`에 `workers: 1`을 더한다. 그리고 처리기가 둘인 사례 `cases/pair.decisions.yaml`을 만든다.

```yaml
decisions: "1.0"
name: pair
target: Line

variables:
  inspect: 1
  workers: 2

choose:
  - {at: Worker, specialization: speed, alternative: Slow}
```

`pack.yaml`의 cases에 적는다.

```yaml
  - {name: pair, decisions: cases/pair.decisions.yaml, until: 20}
```

조립해 본다. `at: Worker`로 적은 결정은 모든 복제본에 적용된다.

```bash
ses build mylab.ses.yaml --decisions cases/pair.decisions.yaml
```

```text
Line
  Source
  Workers
    w0: Worker, Slow
    w1: Worker, Slow
  Inspector: Inspector, Present
  Sink
변수 값 {'inspect': 1, 'workers': 2}. 구성요소 7개, 노드 19개
```

검사하면 앞의 사례들의 기록이 달라졌다고 알린다. 처리기의 자리가 `Worker`에서 `Workers/w0`으로 바뀌었기 때문이다. 사건의 수는 같다.

```text
error P6 fast: 기록이 적어 둔 것과 다르다. 적어 둔 것은 사건 25개 (지문 dec6335bffb42167), 지금은 25개 (지문 5abf65cc3adc79d7). 뜻한 변화이면 --record 로 다시 적는다
```

뜻한 변화이므로 다시 적고, 돌려 본다.

```bash
ses pack check . --record
ses pack run . pair --log 4
```

```text
문서 mylab.ses.yaml: 변이 78개, 그 가운데 적격 78개
사례 pair: 원자 구성요소 5개, 연결 5개. 사건 24개, 지문 9f4cf4935bf75bfe. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
묶음 mylab: 통과
2.0 Source.out {"id": 0}
4.0 Source.out {"id": 1}
5.0 Workers/w0.out {"id": 0}
5.0 Inspector.ok {"id": 0}
```

변이가 78개인 것은 복제본마다 대안을 따로 고를 수 있기 때문이다.

복제본마다 다르게 고르려면 자리(`path`)로 적는다. 여기서 한 가지를 알아야 한다. 정의로 적은 결정(`at`)과 자리로 적은 결정(`path`)은 둘 다 적용된다. 자리의 결정이 정의의 결정을 덮지 않는다. 사례 pair의 `at: Worker` 줄을 둔 채 아래 줄을 더하면 변이가 남지 않는다.

```yaml
  - {path: [Line, Workers, w1], specialization: speed, alternative: Fast}
```

```bash
ses choices mylab.ses.yaml --decisions cases/pair.decisions.yaml
```

```text
남은 변이가 없다
어긋난 곳: Line/Workers/w1: specialization speed 에 남는 대안이 없다. 이 자리에 걸린 결정들이 서로 어긋난다. 결정 at/Worker 는 ['Slow'] 를 남긴다, 결정 path/Line/Workers/w1 는 ['Fast'] 를 남긴다. 정의로 적은 결정(at)과 자리로 적은 결정(path)은 둘 다 적용되고 서로 덮지 않는다. 자리마다 다르게 하려면 at 의 결정을 지우고 자리마다 path 로 적는다
```

`at: Worker` 줄을 자리의 줄로 바꾸면 된다. 복제본마다 한 줄씩이다.

```yaml
  - {path: [Line, Workers, w0], specialization: speed, alternative: Slow}
```

```text
남은 변이 1개
Worker alternative speed: 자리마다 정해짐. 남은 선택지 ['Fast', 'Slow'] / 전체 ['Fast', 'Careful', 'Slow']
    w0: Worker, Slow
    w1: Worker, Fast
```

`ses choices`의 표는 정의마다 한 줄이다. 복제본마다 다른 것을 골랐으면 그 줄은 `자리마다 정해짐`이고 남은 선택지에 고른 것들이 모두 보인다. 더 정할 것이 있는지는 맨 윗줄의 남은 변이의 수로 본다. 복제본이 많을 때는 대안에 `default`를 적고 사례에 `defaults: true`를 두면 다른 복제본만 `path`로 적으면 된다. 이 안내서의 나머지는 pair를 처음의 `at: Worker` 한 줄로 되돌린 상태에서 이어진다.

같은 정의를 한 분해에서 두 번 쓰는 것은 복제가 아니다. `parts`에 `{def: Channel, alias: Forward}`처럼 다른 이름을 붙여 적는다. 그렇게 두 번 놓은 정의의 속성 값을 자리마다 다르게 하는 것은 문서에 적을 수 없다. 사례의 `set`에 `path`로 적는다.

부분을 가진 정의가 자기 포트를 가지면, 그 분해의 결합에서 자기 포트는 점 없이 이름만 적는다. `{from: in, to: Queue.in}`, `{from: Queue.out, to: out}`이다. 걸음 6의 Workers가 그렇게 적었다. 결합의 양 끝은 포트 타입이 같아야 한다.

### 대안마다 포트가 다를 때

대안마다 포트가 달라도 된다. 대안만 가진 포트로 결합을 적을 수 있다. 그 대안이 골라지지 않은 변이에서 결합이 살아 있으면 `ses check`가 알린다. 아래는 교차로의 제어기다. 감응식 제어기(Actuated)만 감지기의 신호를 받는 포트 `call`을 가진다. `crossing.ses.yaml`로 적어 본다.

```yaml
ses: "1.0"
name: Crossing

port_types:
  Call: {fields: {lane: int}}

entities:

  Crossing:
    root: true
    aspects:
      main:
        parts: [Detector, Controller]
        couplings:
          - {from: Detector.call, to: Controller.call}

  Controller:
    specializations:
      kind:
        alternatives: [FixedTime, Actuated]

  FixedTime:
    extends: Controller

  Actuated:                                  # 이 대안만 입력 포트 call 을 가진다
    extends: Controller
    ports:
      call: {type: Call, direction: in, required: true}

  Detector:
    ports:
      call: {type: Call, direction: out}
    specializations:
      presence:
        alternatives: [Installed, NoDetector]

  Installed:
    extends: Detector

  NoDetector:                                # 없음 대안. 고르면 감지기가 빠진다
    extends: Detector
    stereotype: void
```

```bash
ses check crossing.ses.yaml
```

```text
error C1 entities/Crossing: Detector.call 에서 Controller.call: 포트가 없다 (변이 4개 가운데 1개. Detector/presence=Installed, Controller/kind=FixedTime 일 때)
error C4 entities/Crossing: Controller.call: 필수 입력 포트에 들어오는 결합이 없다 (변이 4개 가운데 1개. Detector/presence=NoDetector, Controller/kind=Actuated 일 때)
변이 4개, 그 가운데 적격 2개
```

줄의 끝이 어느 변이에서 나는지를 알린다. 고정 주기 제어기에 감지기를 단 변이와, 감응식 제어기에 감지기가 없는 변이다. 둘 다 뜻이 없는 조합이므로 족에서 뺀다. 선택 사이의 조건은 문서의 `constraints`에 적는다. 파일의 끝에 더한다.

```yaml
constraints:
  - name: fixed_time_has_no_detector
    when: {selected: "Controller/kind=FixedTime"}
    require: {selected: "Detector/presence=NoDetector"}
  - name: actuated_needs_detector
    when: {selected: "Controller/kind=Actuated"}
    require: {selected: "Detector/presence=Installed"}
```

```text
변이 2개, 그 가운데 적격 2개
```

`selected`는 `정의/specialization의 이름=대안`으로 적는다. 복제의 개수는 `정의/multi-aspect의 이름=개수`다. `when`이 참인 변이는 `require`도 참이어야 한다. `forbid`는 참이면 안 되는 것을 적는다. 변수를 보는 조건도 같은 자리에 적는다. `when: {selected: "Assessment/kind=Project"}`, `require: {var: weeks, ge: 12}`이다.

알아 둘 것이 셋이다.

- 제약이 정하는 선택은 결정 집합에 다시 적지 않아도 된다. 위의 문서에서 사례가 `{at: Controller, specialization: kind, alternative: Actuated}`만 적으면 감지기는 제약이 정한다.
- 다른 선택 지점이 무엇을 골랐는지(`selected`)는 `constraints`에서만 쓴다. 분해의 `rule`과 대안의 `select`에는 변수만 쓴다.
- 제약을 어기는 조합은 변이의 수에 들지 않는다. 사례가 그런 조합을 고르면 `만들 수 없다. 제약 ... 을 어긴다`가 나온다.

형식의 나머지는 `schema/ses.schema.json`의 constraint에, 뜻은 `04_data_structures.md`의 4.11절에 있다.

## 8. 다른 엔진에서도 돌린다

모델을 2절의 틀대로 쓰면(공통 모델 기반) 같은 모델 베이스가 세 엔진에서 같은 기록을 낸다. 검사가 그것을 확인한다.

```bash
pip install pyevsim
ses pack check .
```

사례의 줄이 `pyevsim 같다`로 바뀐다. cevsim은 소스를 받아 둔 자리를 환경 변수로 준다. C++ 컴파일러(g++)가 있어야 한다.

```bash
CEVSIM_HOME=/path/to/cevsim ses pack check .
```

## 9. 모델을 쓸 때

모델이 채우는 함수는 여섯이다. `model_base.py`의 맨 위에 적혀 있다.

| 함수 | 언제 불리는가 |
|---|---|
| `init(self)` | 만들 때. 처음 상태를 둔다 |
| `ta(self)` | 다음 내부 사건까지 남은 시간. 쉬고 있으면 INF |
| `output(self)` | 내부 사건 직전. 포트 이름에서 값의 목록으로 가는 사전을 낸다 |
| `internal(self)` | 내부 사건 |
| `external(self, elapsed, bag)` | 입력을 받았을 때. `elapsed`는 이 모델의 마지막 전이에서 흐른 시간, `bag`은 포트 이름에서 값의 목록으로 |
| `confluent(self, bag)` | 내부 사건과 입력이 같은 시각에 겹쳤을 때. 적지 않으면 `internal()` 뒤에 `external(0.0, bag)`을 한다 |

`self.now`는 지금 처리하는 사건의 시각이다. `output`, `internal`, `external` 안에서 읽는다.

`output`은 늘 사전을 낸다. 낼 것이 없는 내부 사건에서는 빈 사전 `{}`을 낸다. None 을 내면 오류다. 같은 시각에 온 입력은 `bag`으로 한 번에 받는다. 포트마다 값의 목록이다.

PARAMS의 타입은 bool, int, float, str, time 가운데 하나다. 문서의 속성에는 time이 없다. 시간 값은 문서에 float로 적고 모델에서 time으로 적는다. 기본값이 없는 매개변수 `("int",)`는 문서의 같은 이름의 속성이 값을 주어야 한다.

LIBRARY에 넣은 클래스의 이름이 바인딩에 적는 모듈의 이름이다. 모델끼리 공통의 부모 클래스를 두어도 된다. 부모는 LIBRARY에 넣지 않는다. 하위 클래스는 부모의 PORTS, REQUIRED, PARAMS를 그대로 물려받는다. 하위 클래스에서 PARAMS를 다시 적으면 부모의 것은 사라진다. 더하려면 `PARAMS = {**Parent.PARAMS, "limit": ("int", 3)}`처럼 합쳐 적는다.

대안을 가진 정의는 바인딩에서 대안마다 묶는다. 뼈대의 `Fast: {module: Worker}`, `Slow: {module: Worker}`가 그렇다. 대안마다 행동이 다르면 대안마다 다른 모듈을 적는다. 바탕 정의(Worker)에 묶어도 된다. 그러면 모든 대안이 그 모듈을 쓴다. 바탕과 대안 둘 다에 묶으면 대안의 것이 쓰인다.

지킬 것은 넷이다. 어기면 검사가 잡는다. 사례가 지나간 길에서만 잡는다.

1. 난수는 씨앗을 매개변수로 받아 모델 안에서 만든다. `random.Random(self.seed)`를 `init`에서 만든다. 전역 난수를 쓰면 기록이 재현되지 않는다. 검사는 두 가지로 본다. 모델의 글에서 전역 난수를 찾아 경고하고(P2), 사례를 두 번 돌려 기록이 다르면 오류로 알린다(P6). `random.seed`로 전역 난수에 씨앗을 주는 것도 안 된다. 그것은 두 번 돌려도 같아서 경고로만 드러난다.
2. 시각은 `self.now`만 쓴다. 벽시계를 쓰지 않는다. 이것도 글에서 찾아 경고하고(P2) 기록이 달라지면 오류로 알린다(P6).
3. 받은 값을 고치지 않는다. 낸 값도 낸 뒤에 고치지 않는다. 고쳐야 하면 복사해서 고친다. 엔진마다 값을 넘기는 방식이 달라 기록이 달라진다. 검사는 값을 베껴서 넘기는 방식으로 한 번 더 돌려 견준다(P6).
4. 시간 전진은 바인딩의 `time_unit`의 정수배다. 0.5 간격이 필요하면 `time_unit`을 0.5로 적는다. 매개변수의 값이 어긋나면 P5, 모델 안에서 계산한 값이 어긋나면 P6으로 나온다. 지수분포처럼 연속인 시간은 그대로 쓰지 못한다. `time_unit`을 0.01처럼 작게 적고 뽑은 값을 `max(0.01, round(x, 2))`로 그 단위에 맞춘다.

P2의 경고가 있어도 사례는 그대로 돌리고 기록과 견준다. 경고는 통과를 막지 않지만, 전역 난수와 벽시계의 경고는 고쳐야 하는 것이다.

모델이 예외를 내면 검사가 어느 구성요소의 어느 함수가 언제 어느 줄에서 냈는지를 적는다. 만들 때 `init`에서 난 것도 같다. 다음은 갓 만든 묶음(2절)의 Sink의 `external`에서 없는 열쇠를 읽었을 때의 줄이다.

```text
error P6 fast: 참조 시뮬레이터에서 돌다가 멈췄다: ModelError: Sink 의 external() 이 시각 3.0 에서 예외를 냈다: KeyError: 'idd' (model_base.py 76번째 줄)
```

되먹임 고리는 결합을 그대로 적으면 된다. 고리 안에 시간 전진이 0보다 큰 모델이 하나는 있어야 한다. 없으면 걸음 수의 한도에서 멈춘다. 한도는 사례마다 1,000,000걸음이고 `pack.yaml`의 사례에 `max_steps`로 바꾼다.

포트 타입의 `fields`는 설명이다. 모델이 내는 값과 견주지 않는다.

## 10. 족이 커질 때

`packs/wsn`은 센서가 1개에서 1,000개이고 변이가 9,000개인 사례다. 저장소의 뿌리에서 친다.

```bash
ses choices packs/wsn/wsn.ses.yaml --functions packs.wsn.model_base:FUNCTIONS
```

변이를 하나씩 만들어 보지 않고 세므로 1초 안에 답한다. 고를 것이 많을 때는 결정 집합으로 좁혀 가며 `choices`로 남은 것을 본다.

`packs/feedback_control`은 걸음 5와 같은 모양의 사례다. 피드포워드 제어기가 있는 구조와 없는 구조가 한 문서에 있다. 부분이 빠지면 그 부분으로 가는 결합도 빠지므로, 남은 부분의 필수 입력이 구동되는지를 `check`가 본다.

## 11. 결과를 꺼낸다

사건 기록을 프로그램에서 읽으려면 연산을 부른다. 결과가 JSON 한 줄로 나온다.

```bash
ses call pack_run --args '{"dir": ".", "case": "fast", "limit": 1000}'
```

`result.log`가 사건의 목록이고 `result.events`가 전체의 수다. `limit`은 가장 크게 1,000이다. 넘기면 오류(A0)가 오고 `result`가 null이다. 그래서 결과를 읽기 전에 `ok`를 본다. 사건이 더 많으면 `offset`을 올려 가며 나눠 받는다. 연산의 목록과 입력은 `ses ops`가 낸다. 에이전트에게 묶음을 맡길 때 쓰는 것도 이 연산들이다(`21_agent_operations.md`).

값을 바꿔 가며 여러 번 돌리는 실험은 묶음 안에 파이썬 스크립트로 둔다. `ses_core.pack.run`이 사례 하나를 돌려 사건 기록, 변수 값, 원자 구성요소의 수를 돌려준다. `change`로 사례의 결정 위에 고칠 것을 얹는다. 결정 집합 파일의 `variables`, `choose`, `set`과 같은 모양이다. 같은 변수, 같은 선택 지점, 같은 속성에 대한 것은 바꾸고 없는 것은 더한다. 원천의 간격을 바꿔 가며 검사기를 통과한 작업을 세는 `sweep.py`다. 묶음의 디렉터리에 둔다.

```python
from ses_core import pack as P

for period in (1.0, 2.0, 4.0):
    change = {"set": [{"at": "Source", "attribute": "period", "value": period}]}
    log, variables, atoms = P.run(".", "fast", change=change)
    passed = [value["id"] for t, where, port, value in log if where == ("Inspector",) and port == "ok"]
    print(period, len(log), len(passed))
```

```bash
python sweep.py
```

```text
1.0 52 13
2.0 25 6
4.0 12 3
```

줄마다 간격, 출력 사건의 수, 검사기를 통과한 작업의 수다. 사건 하나는 시각, 구성요소의 경로, 포트, 값의 넷이다. 경로는 뿌리를 뺀 이름들이다. 알아 둘 것이 넷이다.

- 기록에는 출력 사건만 있다. 모델 안의 상태(대기 시간의 합 같은 것)를 꺼내려면 모델이 포트로 내게 한다. 어디에도 결합하지 않은 출력 포트로 내도 기록에 남는다. 그 포트도 문서의 `ports`에 적는다.
- 씨앗을 바꾼 반복도 같은 길이다. 씨앗을 속성으로 두고 `set`으로 바꾼다.
- 이 길은 기록(records.yaml)을 읽지도 적지도 않는다. 검사가 견주는 것은 선언의 사례뿐이다.
- 스크립트는 선언의 `experiments`에 적어 둔다. 문헌의 실험 하나를 옮긴 긴 본보기가 `packs/feedback_control/experiment.py`다.

## 12. 구조만 가진 묶음

시뮬레이션이 아닌 분야는 모델 베이스 없이 올린다. 교육과정, 제안요청서, 논문의 구성이 `domains/`에 본보기로 있다. 선언에서 `model_base`와 `binding`을 지우고 사례에서 `until`을 뺀다. `model_base.py`와 `binding.yaml`도 지운다. 남는 선언은 이렇다.

```yaml
pack: "1.0"
name: mylab
document: mylab.ses.yaml
cases:
  - {name: fast, decisions: cases/fast.decisions.yaml}
  - {name: slow, decisions: cases/slow.decisions.yaml}
```

검사는 문서와 사례의 결정을 본다. 돌릴 것이 없으므로 사례마다 만든 구조의 지문을 `records.yaml`에 적어 두고 견준다. 구성요소, 포트, 결합, 속성의 값이 그 지문에 든다. 모델 베이스가 있는 묶음에서도 `until`이 없는 사례는 이렇게 본다.

돌리던 묶음을 이렇게 바꾼 뒤의 첫 검사는 `error P6 fast: 구조가 적어 둔 것과 다르다`를 낸다. 적어 둔 것이 돌린 기록의 지문이기 때문이다. `ses pack check . --record`로 다시 적는다.

## 13. 묶음을 나눠 쓴다

묶음은 디렉터리째 주고받는다. 자기 저장소에 두어도 되고 이 저장소의 `packs/` 아래에 두어도 된다. `records.yaml`도 함께 둔다. 받은 사람이 `ses pack check`를 돌려 통과하면 같은 결과를 얻은 것이다.

주기 전에 `ses pack check .`의 마지막 줄이 경고 없이 `통과`인지 본다. 기록이 없는 사례는 경고로만 나온다. 기록이 없으면 받은 사람이 같은 결과인지 알 수 없다.

## 14. 더 읽을 것

문서는 저장소의 `docs/ses-platform/` 아래에 있다.

| 알고 싶은 것 | 읽을 것 |
|---|---|
| 묶음의 계약 전체 | `20_packs.md` |
| 에이전트가 부르는 연산 | `21_agent_operations.md` |
| 문서가 정확히 무엇을 뜻하는가 | `theory.md` |
| 문서의 형식 | `schema/ses.schema.json`, `04_data_structures.md` |
| 결정 집합의 형식 | `schema/decisions.schema.json`, `13_editor_data_model.md`의 7절 |
| 실행기를 붙이는 법 | `14_executors.md`, `15_pyevsim_executor.md`, `16_cevsim_executor.md` |
| 시간 단위 | `17_time_unit.md` |
| 분야의 어휘와 규칙(프로파일) | `12_generic_and_specific.md`, `domains/` |
| 무엇이 정해졌고 무엇이 남았는가 | `ROADMAP.md` |

## 15. 아직 안 되는 것

- 뜻에 대한 결정 셋이 열려 있다. 분해가 여럿인 정의에 우선순위를 쓰는 문서와, 자리를 가리켜 분해를 정하는 결정 집합은 뜻이 바뀔 수 있다. 처음에는 둘 다 쓰지 않기를 권한다. 걸음 5처럼 규칙으로 분해를 고르는 것은 해당하지 않는다. `ROADMAP.md`의 정해야 할 것 1과 4다. 셋째는 아래의 extends다.
- 검사는 구조가 그 분야에 맞는지, 모델의 행동이 옳은지를 보지 않는다. 형식에 맞고, 조립되고, 재현된다는 것까지다.
- 조건에 따라 달라지는 결합이 없다. 걸음 5처럼 분해를 둘로 적는다. 있을 수도 없을 수도 있는 부분이 여럿이면 분해의 수가 빠르게 는다.
- 복제된 부분 가운데 하나에만 값을 보내는 결합이 없다. 걸음 6처럼 모델이 자기 몫을 고른다. 빈 서버 하나에만 일을 보내려면 보내는 모델이 값을 복사해 받을 복제본의 번호를 적어 내고, 복제본은 자기 번호(`me`)가 적힌 값만 받는다. 복제본이 비었다는 것은 복제본의 출력을 보내는 모델로 되먹여 알린다.
- `set`으로 준 값이 구조와 맞는지는 보지 않는다. 식으로 정해지는 속성을 `set`으로 바꾸면 구조와 어긋난 값이 모델에 간다.
- `ses choices`는 프로파일의 규칙을 보지 않는다. 프로파일이 지우는 변이도 센다. 문서가 프로파일을 가리키면 그렇다고 한 줄로 알린다.
- 속성의 값은 수, 글, 참과 거짓 하나다. 목록을 값으로 가질 수 없다. 시간에 따른 값의 열 같은 것은 글로 적어 모델이 풀거나 모델 안에 둔다.
- 다른 정의를 extends로 가리키는 정의를 부분으로 직접 놓으면, 가리킨 정의의 포트를 물려받지 않는다. 포트를 그 정의에 다시 적는다. 이 뜻은 바뀔 수 있다(`ROADMAP.md`의 정해야 할 것 5).
- 에이전트가 연산으로 일을 잘하는지를 재는 평가의 틀은 아직 없다.
- 이 안내서를 따라 해 본 것은 연구자의 역할을 맡긴 에이전트 여덟이다(첫 판에 여섯, 고친 판에 둘). 사람은 아직 없다. 에이전트는 문서를 빠짐없이 읽고 지치지 않는다. 사람이 막히는 곳은 다를 수 있다.
- 문서는 한국어뿐이다.
