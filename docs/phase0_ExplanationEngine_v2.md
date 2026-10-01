# Explanation Engine v2 — Phase 0 실행 기록

**기준일:** 2026-10-01  
**상태:** 진행 중 — Gold Set seed 3편 고정, Production 동작 변경 없음

## 목적

Phase 1 이후 생성 로직을 바꾸기 전에 현재 품질 실패를 재현 가능한 기준선으로 고정한다.

이번 Phase 0은 탐지기나 생성 규칙을 새로 켜는 단계가 아니다. 실제 Production 산출물에서 확인한 결함을 작은 Gold Set으로 보존하고, 이후 Source Gate / Explanation Reasoning / Narration / Visual 변경이 이 결함을 개선하는지 비교할 수 있게 한다.

## Seed Gold Set

1. **논문 — Heel-strike**
   - source: full_body, 약 60,000자
   - output: 67초, 17컷
   - 회귀 anchor: `scope_expansion_exclusivity`
   - 대본이 “인간은 모든 유인원 중 유일하게 …”로 범위를 확장한 사례
   - 추가: 결과·수치가 원리보다 먼저 나오는 설명 순서, spoken register, content-mode warning 미집행

2. **리포트 — 삼성전자 메모리 사이클**
   - source: full_text, 약 11,997자
   - output: 66초, 10컷
   - 회귀 anchor: `reasoning_link_lost_before_visual`
   - 상류 financial reasoning은 풍부하지만 directive/visual 단계로 연결되며 reasoning/claim link가 약해진 사례
   - 추가: report인데 `content_profile=paper_explainer`, explanation bridge 부족

3. **리포트 — NH AI Mid Cycle**
   - source: partial_text, 약 1,072자
   - output: 50초, 12컷
   - 회귀 anchor: `source_depth_overexpanded`
   - 얕은 source를 deep explainer처럼 확장한 사례
   - 추가: evidence 없는 factual hook context, metaphor를 literal observation으로 선언

## 품질 축

Gold Set은 모든 사례에 다음 10개 축을 강제한다.

- source adequacy
- fact fidelity
- reasoning quality
- explanation quality
- script coherence
- narration naturalness
- visual explanatory power
- visual-narration alignment
- pacing
- uncertainty calibration

등급은 `pass | mixed | fail | not_audited`만 사용한다.

## 구현

- `engine/explanation_quality.py`
  - Gold Set schema validation
  - deterministic summary
  - review용 Markdown report
  - 외부 API/DB 호출 없음

- `scripts/explanation_quality_audit.py`
  - checked-in Gold Set을 읽는 read-only CLI
  - `--case`, `--json`
  - 운영 DB write 없음

- `tests/fixtures/explanation_quality_gold_set.json`
  - 감사한 3편의 최소 정보와 finding만 저장
  - 원문 전문/민감 데이터는 저장하지 않음

- `tests/test_explanation_quality.py`
  - 양 도메인 포함
  - 10개 품질 축 존재
  - 핵심 regression anchor 3개 유지
  - deterministic summary 고정

## 현재 Main과의 관계 — 중요한 정정

Heel-strike 산출물은 발행 당시 self-check가 `유일하게` 범위 확장을 통과시켰다.

다만 최신 main의 2026-09-30 변경(#84)은 논문 라인에도 Jev grounding 경고를 연결했고, 저장된 과거 사례를 재감사하면서 바로 이 “인간은 모든 유인원 중 유일하게…” 문장을 원문보다 센 주장으로 잡았다고 기록한다.

따라서 이 Gold Set의 의미는:

> “현재 main에는 이 오류를 잡는 장치가 전혀 없다”

가 아니다.

정확한 의미는:

> **“실제 Production에서 발생했던 end-to-end 품질 실패를 앞으로 모든 개선이 회귀 기준으로 가져간다.”**

이다.

Phase 0에서는 기존 Jev 탐지기를 중복 구현하지 않는다.

## 로컬 격리 검증

Phase 0 신규 모듈/fixture만 분리해 실행:

```text
python -m pytest -q tests/test_explanation_quality.py
4 passed

python -m scripts.explanation_quality_audit --json
cases = 3
findings = 11
P0 = 5
P1 = 6
```

전체 저장소 pytest / web build는 GitHub branch CI로 확인한다. 현재 세션에서는 GitHub repo를 로컬 clone할 네트워크가 없어 전체 저장소 로컬 실행은 미검증이다.

## 남은 Phase 0

- Gold Set을 최근 논문/리포트 각 3~5편 수준으로 확대
- 가능하면 최종 MP4를 직접 재생해 `render_review=direct` 표본 확보
- 결함의 최초 발생 단계(Source / Reasoning / Script / Narration / Visual / Render) 분포 재확인
- 상위 3개 failure class 확정
- 그 결과를 Phase 1 Source Adequacy Gate의 실제 규칙 설계 입력으로 사용

## Phase 0 종료 조건

- 논문·리포트 양쪽의 대표 사례가 포함된다.
- 최소 주요 failure class가 반복 관측되는 표본이 있다.
- Gold Set label이 생성 모델의 자기평가가 아니라 감사 근거로 고정된다.
- 다음 Phase 변경 전후를 같은 fixture/평가 계약으로 비교할 수 있다.
- Production write path는 건드리지 않는다.
