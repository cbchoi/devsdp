# devsdp

SES(System Entity Structure) 공통 플랫폼 설계 자료와 구현을 위한 저장소다.

- docs/ses-platform/ : 연구 검토, 플랫폼 구상, 객체지향 연계 개선 방안과 구조 표현, 시뮬레이터 독립 자료구조 제안, 스키마 초안, 예시, 분야별 프로파일과 예시(domains/)
- ses_core/ : 자료구조의 Python 참조 정의, 정준 YAML 적재기, 핵(algebra.py 선택 대수, skeleton.py 구성 구조), 확장 계약(extension.py)과 확장 사례(coupling.py, ext_attr.py, ext_text.py), 도메인 프로파일과 범용 장치(profile.py), 정준 문서와의 연결(unfold.py), 편집기를 위한 자료구조(edit.py 편집 모델, decisions.py 결정 집합, diagnose.py 진단), 실행기를 붙이는 자리(structure.py 구조와 평탄화, executor.py 바인딩과 계획, devs.py DEVS 실행기와 참조 시뮬레이터, hw.py 하드웨어 실행기, pyevsim_executor.py pyevsim 실행기, cevsim_executor.py와 cevsim_bridge/ cevsim 실행기와 C++ 다리, classic.py 고전 SES/MB의 절차적 의미), 결정이 끝난 변이를 직접 만드는 길(direct.py), 명령줄 도구(cli.py)
- examples/ : 예시 SES에 붙이는 모델베이스(처리 시스템, 센서 노드의 DEVS 원자 모델. processing_pyevsim.py는 처리 시스템을 pyevsim 모델로 쓴 것), 문헌 사례의 모델베이스(wsn_mb.py 무선 센서 네트워크, feedback_control_mb.py 피드백 제어)와 실험 제어(feedback_control_experiment.py)
- tests/ : 예시 SES 적재와 무결성 검사 테스트, 가지치기 대수와 족 수준 적격성 정리, 확장 계약의 공통 정리의 무작위 검증, 편집 모델과 결정 집합과 진단의 무작위 검증(test_edit.py, test_decisions.py, test_diagnose.py), 구조 이론과 실행기의 무작위 검증(test_structure.py, test_executor.py), pyevsim 실행기와 cevsim 실행기의 충실성과 참조 시뮬레이터와의 사건 기록 대조(test_pyevsim.py, test_cevsim.py), 시간 단위의 계약과 세 실행기의 기록 대조(test_time_unit.py), 전통적인 SES와의 간격 메우기(test_parity.py 선택 제약과 함수와 우선순위, test_params.py 사례마다 다른 매개변수, test_direct.py 변이 하나를 직접 만드는 길, test_cases.py 문헌 사례, test_cli.py 명령줄 도구)

설치와 명령줄 도구. 의존은 PyYAML 하나이고 파이썬 3.11과 3.13에서 시험했다. 설치하면 명령 ses 가 생긴다. 설치하지 않고 python -m ses_core 로도 부른다. 명령과 종료 코드는 docs/ses-platform/18_classic_parity.md 6절에 있다.

```bash
pip install ".[test]"
python -m pytest -q tests
ses check docs/ses-platform/examples/processing_system.ses.yaml
```

pyevsim 실행기(ses_core/pyevsim_executor.py, examples/processing_pyevsim.py, tests/test_pyevsim.py)는 pyevsim이 설치되어 있어야 쓸 수 있다. 1.1.7에서 확인했다. 설치되어 있지 않으면 그 시험은 건너뛴다.

```bash
pip install pyevsim
```

cevsim 실행기(ses_core/cevsim_executor.py, ses_core/cevsim_bridge/, tests/test_cevsim.py)는 cevsim의 소스와 C++ 컴파일러(g++)가 있어야 쓸 수 있다. cevsim을 받아 둔 자리를 환경 변수로 준다. cevsim의 main(45e7fa9)에 맞췄고 C++23을 지원하는 g++가 필요하다. 그보다 앞선 cevsim이거나 없으면 그 시험은 건너뛴다.

```bash
CEVSIM_HOME=/path/to/cevsim python -m pytest -q tests/test_cevsim.py
```
