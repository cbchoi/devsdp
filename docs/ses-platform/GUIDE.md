# 처음 오는 연구자를 위한 안내서

작성일: 2026-11-23. 이 안내서의 3절에서 6절의 걸음은 `tests/test_guide.py`가 그대로 돌린다. 적힌 출력이 실제와 달라지면 그 시험이 실패한다.

## 0. 이 안내서가 하는 일

한 시간쯤 따라 하면 자기 분야를 올릴 묶음 하나를 손에 쥔다. 묶음은 디렉터리 하나이고 네 가지가 든다.

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

`ses`라는 명령이 생긴다. 다른 시뮬레이션 엔진은 없어도 된다. 참조 시뮬레이터가 들어 있다. pyevsim과 cevsim에서도 돌려 보려면 7절을 본다.

## 2. 첫 묶음을 만든다

빈 자리에서 다음을 친다. `mylab` 자리에 자기 묶음의 이름을 쓴다. 이름은 글자, 숫자, 밑줄로 쓴다.

```bash
ses pack new mylab
```

여섯 파일이 생기고 바로 검사까지 한다. 끝의 몇 줄은 이렇다.

```text
문서 mylab.ses.yaml: 변이 2개, 그 가운데 적격 2개
사례 fast: 원자 구성요소 3개, 연결 2개. 사건 19개, 지문 253f991d865d276f. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
사례 slow: 원자 구성요소 3개, 연결 2개. 사건 16개, 지문 a1eec6a2077ace65. 실행기 devs 기준, pyevsim 건너뜀, cevsim 건너뜀
```

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

변이가 하나로 정해지면 조립할 수 있다.

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

`Worker: Worker, Slow`는 그 자리에 Worker와 Slow가 합쳐졌다는 뜻이다. 대안을 고르면 그 대안의 정의가 엔티티에 합쳐진다. 포트와 속성도 합쳐진다.

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

줄마다 시각, 낸 구성요소와 포트, 값이다. 원천이 2마다 작업을 내고 빠른 처리기가 1 뒤에 내보낸다.

## 5. 검사를 돌린다

고칠 때마다 이것을 돌린다.

```bash
ses pack check .
```

마지막 줄이 `묶음 mylab: 통과`이면 된다. 검사가 보는 것은 여덟 가지다.

| 부호 | 보는 것 | 흔한 까닭 |
|---|---|---|
| P0 | 선언(pack.yaml) | 없는 파일, 잘못 적은 항목 |
| P1 | 문서 | 잘못 적은 항목, 없는 정의를 가리킴, 이름이 겹침 |
| P2 | 모델 베이스 | 파이썬 오류, 포트의 선언이 틀림, 시간 전진이 시간 단위의 정수배가 아님 |
| P3 | 바인딩 | 문서에 없는 정의나 없는 모델을 적음 |
| P4 | 사례의 결정 | 없는 선택지를 적음, 결정이 모자라 구조가 하나로 정해지지 않음 |
| P5 | 조립과 실행 가능성 | 묶이지 않은 구성요소, 모델과 문서의 포트가 다름, 구동되지 않는 필수 입력 |
| P6 | 실행과 기록 | 돌다가 멈춤, 두 번 돌린 기록이 다름, 적어 둔 기록과 다름 |
| P7 | 실행기 사이의 일치 | 다른 엔진에서 기록이 다름 |

## 6. 자기 분야로 바꾼다

세 걸음을 따라 하면 무엇을 어디서 고치는지 알게 된다. 그다음에 이름과 내용을 자기 분야의 것으로 바꾼다.

### 걸음 1. 대안을 하나 더한다

처리기의 셋째 대안 Careful을 더한다. 네 군데를 고친다.

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
info P6 careful: 적어 둔 기록이 없다. ses pack check --record 로 적는다
문서 mylab.ses.yaml: 변이 3개, 그 가운데 적격 3개
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

기록의 지문은 누가 어디서 돌려도 같다. 모델을 고쳤는데 뜻하지 않게 결과가 달라지면 검사가 잡는다.

### 이제 자기 분야로

정의의 이름, 포트, 속성, 모델을 자기 분야의 것으로 바꾼다. 순서는 문서, 모델 베이스, 바인딩, 사례다. 한 군데 고칠 때마다 검사한다.

## 7. 다른 엔진에서도 돌린다

모델을 2절의 틀대로 쓰면(공통 모델 기반) 같은 모델 베이스가 세 엔진에서 같은 기록을 낸다. 검사가 그것을 확인한다.

```bash
pip install pyevsim
ses pack check .
```

사례의 줄이 `pyevsim 같다`로 바뀐다. cevsim은 소스를 받아 둔 자리를 환경 변수로 준다. C++ 컴파일러(g++)가 있어야 한다.

```bash
CEVSIM_HOME=/path/to/cevsim ses pack check .
```

## 8. 모델을 쓸 때 지킬 것

넷이다. 어기면 검사가 잡는다.

1. 난수는 씨앗을 매개변수로 받아 모델 안에서 만든다. `random.Random(self.seed)`를 `init`에서 만든다. 전역 난수를 쓰면 기록이 재현되지 않는다(P6).
2. 시각은 `self.now`만 쓴다. 벽시계를 쓰지 않는다(P6).
3. 받은 값을 고치지 않는다. 고쳐야 하면 복사해서 고친다. 엔진마다 값을 넘기는 방식이 달라 기록이 달라진다(P7).
4. 시간 전진은 바인딩의 `time_unit`의 정수배다. 0.5 간격이 필요하면 `time_unit`을 0.5로 적는다(P2, P5).

## 9. 족이 커질 때

같은 부분이 여러 개이고 그 수가 변하면 복제(multi-aspect)를 쓴다. `packs/wsn`이 그 사례다. 센서가 1개에서 1,000개이고 변이는 9,000개다.

```bash
ses choices packs/wsn/wsn.ses.yaml --functions packs.wsn.model_base:FUNCTIONS
```

변이를 하나씩 만들어 보지 않고 세므로 1초 안에 답한다. 고를 것이 많을 때는 결정 집합으로 좁혀 가며 `choices`로 남은 것을 본다.

부분이 있을 수도 없을 수도 있으면 "없음 대안"을 쓴다. `packs/feedback_control`이 그 사례다. 피드포워드 제어기가 있는 구조와 없는 구조가 한 문서에 있다. 부분이 빠지면 그 부분으로 가는 결합도 빠지므로, 남은 부분의 필수 입력이 구동되는지를 `check`가 본다.

## 10. 묶음을 나눠 쓴다

묶음은 디렉터리째 주고받는다. 자기 저장소에 두어도 되고 이 저장소의 `packs/` 아래에 두어도 된다. `records.yaml`도 함께 둔다. 받은 사람이 `ses pack check`를 돌려 통과하면 같은 결과를 얻은 것이다.

## 11. 더 읽을 것

| 알고 싶은 것 | 읽을 것 |
|---|---|
| 묶음의 계약 전체 | `20_packs.md` |
| 문서가 정확히 무엇을 뜻하는가 | `theory.md` |
| 문서의 형식 | `schema/ses.schema.json`, `04_data_structures.md` |
| 결정 집합 | `13_editor_data_model.md`의 7절, `theory.md`의 7절 |
| 실행기를 붙이는 법 | `14_executors.md`, `15_pyevsim_executor.md`, `16_cevsim_executor.md` |
| 시간 단위 | `17_time_unit.md` |
| 분야의 어휘와 규칙(프로파일) | `12_generic_and_specific.md`, `domains/` |
| 무엇이 정해졌고 무엇이 남았는가 | `ROADMAP.md` |

## 12. 아직 안 되는 것

- 뜻에 대한 결정 둘이 열려 있다. 분해가 여럿인 정의에 우선순위를 쓰는 문서와, 자리를 가리켜 분해를 정하는 결정 집합은 뜻이 바뀔 수 있다. 처음에는 둘 다 쓰지 않기를 권한다. `ROADMAP.md`의 정해야 할 것 1과 4다.
- 검사는 구조가 그 분야에 맞는지, 모델의 행동이 옳은지를 보지 않는다. 형식에 맞고, 조립되고, 재현된다는 것까지다.
- 에이전트가 부르는 연산과 평가의 틀은 아직 없다.
- 문서는 한국어뿐이다.
