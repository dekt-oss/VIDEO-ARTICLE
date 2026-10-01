# Explanation Engine v2 — Phase 0 실행 기록

**기준일:** 2026-10-01  
**상태:** 1차 Baseline 완료 — 논문 3편 + 리포트 3편 Gold Set 고정, Production 동작 변경 없음

## 목적

Phase 1 이후 생성 로직을 바꾸기 전에 현재 품질 실패를 재현 가능한 기준선으로 고정한다.

이번 Phase 0은 탐지기나 생성 규칙을 새로 켜는 단계가 아니다. 실제 Production 산출물에서 확인한 결함을 Gold Set으로 보존하고, 이후 Source Gate / Explanation Reasoning / Narration / Visual 변경이 이 결함을 개선하는지 같은 기준으로 비교한다.

## Gold Set — 6편

### 논문 3편

1. **Heel-strike mechanics**
   - source: `full_body`, 약 60,000자
   - output: 67초, 17컷
   - 대표 anchor: `scope_expansion_exclusivity`
   - 원문은 African apes도 heel-strike할 수 있다고 하는데 대본은 “인간은 모든 유인원 중 유일하게”로 확대

2. **Retinotopic remapping in deaf adults**
   - source: `full_body`, 약 60,000자
   - render QA signal: 약 58.37초
   - 대표 anchor: `cross_sensory_transfer_invented`
   - 시각계 내부의 peripheral↔central representation 재분배를 “청각에 쓰이던 자원을 시각으로 옮겼다”로 강화
   - 저장 draft는 `approval_blocked=true` / `series_split_required`였으나 block 이후 published 행 생성도 확인

3. **Personality GWAS**
   - source: `full_body`, 약 60,000자
   - merged render 기준 약 84.86초, 13컷
   - 대표 anchor: `association_to_determination_hook`
   - “personality와 연관된 1,260개 변이”를 “성격을 결정하는 유전자 1,260개”로 강화
   - actual Render QA가 전반부 video cut 7/7을 거의 정지로 판정(motion median 약 0.0008, 기록된 발행 benchmark 0.0117)

### 리포트 3편

4. **삼성전자 — 메모리 사이클 / 목표주가**
   - source: `full_text`, 약 11,997자
   - output: 66초, 10컷
   - 대표 anchor: `reasoning_link_lost_before_visual`
   - R01~R04 financial reasoning은 풍부하지만 Directive로 내려가며 claim/reasoning 연결 약화
   - report인데 `content_profile=paper_explainer`인 routing 이상도 확인

5. **NH — AI 투자 / Mid Cycle**
   - source: `partial_text`, 약 1,072자
   - output: 50초, 12컷
   - 대표 anchor: `source_depth_overexpanded`
   - 얕은 source를 deep explainer처럼 확장
   - evidence 없는 factual hook context와 metaphor/literal semantics 혼재

6. **SK — 리레이팅의 조건: 데이터센터 & 함정**
   - source: `full_text`, 약 11,911자
   - output: 64초, 10컷
   - 대표 anchor: `unsupported_replacement_claim`
   - 원문은 글로벌 함정 건조 역량 부족 + 국내 조선사의 수주 pipeline을 말하지만 Directive는 “한국 특수선 도크가 해외 건조 설비를 대체하고 있다”고 강화
   - R01~R04 `reasoning_id`는 남지만 10개 컷의 `claim_ids/claim_refs`가 비어 cross-stage link 문제가 재현

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

## 1차 Failure 분포

6편에서 수동 감사한 finding:

```text
cases = 6
findings = 23

domain
  paper  = 3
  report = 3

severity
  P0 = 11
  P1 = 12

first failure / observed stage
  script    = 10
  reasoning = 6
  visual    = 4
  narration = 1
  source    = 1
  render    = 1
```

이 분포를 최종 통계로 과대해석하지 않는다. 의도적으로 문제가 보이는 최근 Production 사례를 Gold Set으로 잡은 소표본이다.

다만 **Renderer 하나가 주 병목이라는 가설은 이 표본에서 지지되지 않는다.**

반복적으로 보이는 상위 failure class는 현재:

1. **Semantic Fidelity / Script Calibration**
   - association → determination
   - peripheral representation → “시야가 넓어진다”
   - possibility/pipeline → already replacing
   - scope/qualifier 강화

2. **Explanation Reasoning**
   - 연구 결과·숫자 나열이 원리보다 먼저 나옴
   - prerequisite 개념 설명 부족
   - 풍부한 reasoning을 최종 1분 요약으로 지나치게 압축

3. **Reasoning → Visual 계약 소실**
   - 상류 reasoning_id/claim이 하류 stage에서 끊김
   - 관련 이미지는 있으나 설명하는 화면이 아닌 경우 반복

Source adequacy와 Renderer도 실제 결함이 있으나 이번 6편에서는 위 세 클래스보다 발생 빈도가 낮았다.

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
  - 감사한 6편의 최소 정보와 finding만 저장
  - 원문 전문/민감 데이터는 저장하지 않음

- `tests/test_explanation_quality.py`
  - 논문 3 / 리포트 3 고정
  - 10개 품질 축 존재
  - 대표 regression anchor 6개 유지
  - deterministic failure 분포 고정

## 최신 main과의 관계 — 중요한 정정

Gold Set은 “현재 main에 보호장치가 없다”는 뜻이 아니다.

예를 들어 Heel-strike 오류는 발행 당시 self-check가 `유일하게` 범위 확장을 통과시켰지만, 최신 main의 2026-09-30 변경(#84)은 논문 라인에도 Jev grounding 경고를 연결했고 같은 과거 문장을 원문보다 센 주장으로 탐지했다고 기록한다.

Retinotopic의 “청각 자원을 시각으로 옮겼다”, SK의 “한국 도크가 해외 설비를 대체한다”도 최신 Jev 감사에서 원문을 넘는 사례로 확인됐다.

따라서 Phase 0은 기존 Jev 탐지기를 중복 구현하지 않는다.

Gold Set의 목적은:

> **실제 Production에서 발생한 end-to-end 실패를 이후 모든 개선이 회귀 기준으로 가져가는 것**

이다.

## 검증

신규 Phase 0 모듈을 격리 실행한 초기 3편 버전:

```text
python -m pytest -q tests/test_explanation_quality.py
4 passed
```

이후 Gold Set을 6편으로 확장했고 branch test expectation도 6편/23 findings로 갱신했다.

전체 저장소 pytest / web build는 PR CI로 확인한다. 현재 세션에서는 GitHub repo를 로컬 clone할 네트워크/DNS가 없어 전체 저장소 로컬 실행은 미검증이다.

## Render 직접 검수 한계

Production의 `render_jobs.qa`가 저장한 실제 frame/audio QA signal은 감사에 사용했다.

예:
- Personality 영상: video cut 7/7 almost-static warning
- Retinotopic: frame decodable / audio / duration QA

그러나 현재 실행 환경의 외부 DNS 제한 때문에 public Storage MP4를 직접 다운로드하지 못했다.

따라서 사람이 픽셀·음성을 직접 재생한 검수는 아직 **미검증**이다. Gold Set의 `render_review`는 그 사실을 숨기지 않는다.

## Phase 0 판정

**1차 Baseline 목표는 달성했다.**

- 논문/리포트 각 3편
- 서로 다른 failure class 고정
- Production write path 변경 없음
- deterministic fixture/test 생성
- 다음 Phase에서 같은 계약으로 전후 비교 가능

Phase 0을 완전히 닫기 전에 가능하면 MP4 direct review 표본을 추가한다. 다만 이는 Phase 1 Source Adequacy Gate 설계의 blocker는 아니다.

## 다음 단계

Phase 1에서는 곧바로 LLM prompt를 바꾸지 않는다.

먼저 현재 `source_depth / source_chars / source provenance`가 draft mode, duration, story complexity, mechanism 허용 여부에 실제로 어떻게 소비되는지 execution path를 추적한 뒤 **Source Adequacy Gate**의 최소 규칙을 설계한다.

Phase 1 구현은 별도 PR 또는 이 Draft PR의 Phase 0 승인 후 시작한다.
