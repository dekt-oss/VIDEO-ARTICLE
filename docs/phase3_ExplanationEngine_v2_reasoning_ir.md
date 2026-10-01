# Explanation Engine v2 — Phase 3 Reasoning IR

**기준일:** 2026-10-01  
**기준 커밋:** `f52f587ebe24b63586ca7dd5904ddc35492b8d94`  
**선행:** Phase 0 Gold Set, Phase 1 Source Adequacy, Phase 2 Common Evidence Pack

## 1. 목표

Phase 3는 대본을 다시 쓰거나 Production 생성 경로를 바꾸지 않는다. 기존 Fact Sheet를
읽기 전용으로 투영한 Evidence Pack을 도메인별 Reasoning Adapter가 읽고, 다음 단계가
공통으로 소비할 최소 Explanation IR을 shadow output으로 만든다.

```text
Paper Fact Sheet ─→ Evidence Pack ─→ Paper Reasoning Adapter ─┐
                                                               ├─→ Explanation IR
Report Fact Sheet ─→ Evidence Pack ─→ Report Reasoning Adapter ┘
                                      ↑
                              existing report_reasoning
```

성공 기준은 설명 문장의 자연스러움이 아니라 다음 계약의 기계적 보장이다.

- 한 영상은 하나의 `core_question`만 가진다.
- 모든 Reasoning Unit은 Evidence Pack의 `evidence_id`로 돌아간다.
- `raw_ref`는 모델 입력을 신뢰하지 않고 Evidence Pack에서 코드가 다시 만든다.
- 근거의 인과 강도, 불확실성, 귀속, 범위를 강화하지 않는다.
- Phase 1 source policy보다 깊은 논증을 만들지 않는다.
- 기존 script/directive/render 결과는 바뀌지 않는다.

## 2. 범위

### 포함

- `explanation-ir-v1` 최소 스키마
- 공통 순수 정규화·검증
- Paper Adapter
- 기존 `report_reasoning.py` 결과를 재사용하는 Report Adapter
- 결정론적 ID와 chain
- Phase 0 대표 실패 여섯 건의 shadow regression
- Paper/Report 각 최소 세 fixture
- 사용법과 계약 문서

### 제외

- 기존 `scriptgen.py`, `report_scriptgen.py`, directive, render 경로 연결
- 새로운 LLM 호출 또는 prompt 변경
- DB migration과 IR 저장
- Narration, Visual Beat, Shot Directive 생성
- Production 생성·배포·유료 재생성
- 기존 Report reasoning schema의 교체

## 3. Architecture 선택

공통 Core와 도메인 Adapter를 분리한다.

### 3.1 Common IR Core

`engine/explanation_ir.py`는 다음만 담당한다.

- 계약 상수와 허용 enum
- Evidence Pack index 생성
- 모델/Adapter 출력의 정규화
- 코드 기반 `XR01`, `XR02` ID 부여
- dangling evidence 제거
- Evidence Pack 기반 `raw_refs` 재구성
- validation과 warning 산출
- 입력 불변성과 deterministic output 보장

도메인 의미를 추론하지 않으며 네트워크, DB, LLM을 호출하지 않는다.

### 3.2 Paper Reasoning Adapter

`engine/paper_reasoning_adapter.py`는 Paper Evidence Pack만 읽는다.

- `claim_type`을 최소 IR role로 매핑한다.
- `causal_strength`, `uncertainty`, `limitations`를 그대로 운반한다.
- prerequisite가 필요하면 Evidence Pack에 존재하는 항목만 사용한다.
- `association_only`를 cause/mechanism/determination으로 올리지 않는다.
- `semantic_entailment=false`인 claim은 인과 승격이 불가능하도록 보수적으로 표시한다.
- `UNSUPPORTED`와 `STALE` evidence는 positive reasoning unit의 근거가 될 수 없다.

이 Adapter는 새로운 과학 지식을 합성하지 않는다.

### 3.3 Report Reasoning Adapter

`engine/report_reasoning_adapter.py`는 기존 `report_reasoning.py`의 정규화된 unit을
버리지 않고 Explanation IR로 변환한다.

- 기존 `R01#step` 순서를 보존한다.
- `fact_ids`를 `report:<fact_id>` Evidence Pack ID로 변환한다.
- qualitative claim, opinion, risk는 Evidence Pack에 존재할 때만 참조한다.
- broker attribution과 projection/estimate 성격을 보존한다.
- 기존 Source Adequacy의 reasoning unit/step 상한을 다시 넘지 않는다.
- source quote만 있고 Evidence Pack item으로 추적할 수 없는 단계는 조용히 승인하지 않고
  warning과 함께 제외한다.

## 4. 최소 IR 계약

```yaml
contract_version: explanation-ir-v1
domain: paper|report
content_id: string
core_question: string
thesis: string
reasoning_units:
  - reasoning_id: XR01
    role: phenomenon|prerequisite|cause|mechanism|bridge|result|limitation|risk|payoff
    text: string
    evidence_ids: [string]
    raw_refs: [string]
    causal_level: string
    uncertainty: string
    attribution: string
    transition_relation: string
explanation_chain: [XR01, XR02]
warnings: [string]
source:
  source_depth: string
  source_mode: string
```

필드는 Phase 4가 실제로 소비할 최소값만 둔다. Visual Beat, camera, narration 필드는
Phase 3에 추가하지 않는다.

## 5. 정규화 계약

### 5.1 ID와 참조

- 입력의 `reasoning_id`는 폐기하고 배열 순서대로 `XR01…`을 부여한다.
- `evidence_ids`는 Evidence Pack 전체에서 실제 존재하는 ID만 남긴다.
- `raw_refs` 입력값은 폐기하고 남은 evidence item의 `raw_ref`에서 재구성한다.
- evidence가 하나도 남지 않은 positive unit은 제거하고 warning을 남긴다.
- `explanation_chain`은 살아남은 unit 순서에서 코드가 재구성한다.

### 5.2 Evidence 상태

- `UNSUPPORTED`, `STALE`: positive reasoning 근거로 사용 금지
- `SUPPORTED`: `verification_scope`가 확인한 항목만 신뢰
- `UNVERIFIABLE_AT_CURRENT_DEPTH`, `NOT_CHECKED`: 사용 시 상태를 보존하고 warning 부여
- `semantic_entailment=false`: claim 전체의 의미가 입증됐다고 간주하지 않음

limitation/risk unit은 부정적·제약 정보를 보존하는 용도이므로 해당 evidence의 의미를
뒤집지 않는 범위에서 유지할 수 있다.

### 5.3 Semantic calibration

- Paper의 `causal_strength=association_only`는 IR에서도 그대로 유지한다.
- projection, speculation, author interpretation은 certainty를 올리지 않는다.
- Report의 opinion과 전망은 broker attribution 없는 객관적 사실로 변환하지 않는다.
- qualifier/limitation은 같은 evidence item의 구조화 필드에서 보존한다.

### 5.4 Source Adequacy

- Report는 기존 `source_adequacy.reasoning_limits()`와 이미 정규화된 unit/step 결과를 재사용한다.
- Paper는 새로운 수치 상한을 발명하지 않는다. Evidence Pack에 존재하는 claim을 넘는 bridge나
  mechanism을 합성하지 않는 방식으로 얕은 source의 확장을 막는다.
- `BRIEF_EXPLAINER`, `SUMMARY_ONLY`에서 검증되지 않은 배경지식을 채워 넣지 않는다.

## 6. Core Question과 Thesis

Phase 3는 문학적인 질문 생성기가 아니다.

- Adapter 입력에 명시된 단일 질문/명제가 있으면 정규화해 사용한다.
- 여러 질문 배열은 허용하지 않는다.
- 비어 있으면 domain의 핵심 evidence 한 항목을 기반으로 결정론적 최소 문장을 만든다.
- 만들어진 질문과 thesis는 reasoning unit보다 강한 인과나 확실성을 주장할 수 없다.
- 자연스러운 spoken narration과 story refinement는 Phase 4 이후 책임이다.

## 7. Gold Set Shadow Regression

fixture는 실제 Production 실패 유형을 최소 입력으로 재현한다.

### Paper

1. Heel strike: African apes 가능 범위를 보존하고 인간의 exclusivity를 만들지 않는다.
2. Retinotopic remapping: visual representation 변화에서 cross-sensory transfer를 만들지 않는다.
3. Personality GWAS: association을 determination으로 올리지 않는다.

### Report

1. Samsung: 기존 financial reasoning ID가 IR evidence trace로 이어진다.
2. NH Mid Cycle: `partial_text` source의 unit/step 상한을 넘지 않는다.
3. Shipbuilding: pipeline/opportunity를 현재 확정 replacement로 바꾸지 않고 broker attribution을 보존한다.

fixture는 외부 LLM이나 DB 없이 같은 입력에서 byte-equivalent JSON shape를 만든다.

## 8. 오류 처리

- Evidence Pack 자체가 invalid하면 IR 생성은 실패하고 validation error를 반환한다.
- dangling evidence는 제거하고 warning을 남긴다.
- evidence가 사라져 빈 positive unit이 되면 unit도 제거한다.
- domain 불일치, 잘못된 contract version, 중복 ID, 빈 core question은 validation error다.
- 검증 불가와 검증 실패를 같은 상태로 합치지 않는다.

## 9. 변경 경계

첫 Phase 3 PR은 새 모듈·테스트·fixture·문서만 추가하는 것을 원칙으로 한다.
기존 파일 변경이 불가피하면 import/export 수준으로 제한하고 이유를 PR에 기록한다.
`scriptgen.py`, `report_scriptgen.py`, directive, render, web, Supabase는 변경하지 않는다.

## 10. 검증

- targeted Explanation IR tests
- 기존 Evidence Pack / report reasoning regressions
- full Python pytest
- web node tests
- TypeScript typecheck
- lint
- 가능한 build/runtime smoke
- `git diff --check`
- 적대적 Fable Review:
  - evidence 없는 reasoning
  - scope expansion
  - qualifier drop
  - association → causation
  - projection → current fact
  - broker opinion → objective fact
  - author interpretation → proven mechanism
  - stale/unsupported evidence reuse
  - shallow source overexpansion
  - ID/ref loss

## 11. Rollback

Production 경로에 연결하지 않으므로 rollback은 Phase 3 신규 파일과 문서 제거만으로 끝난다.
DB, 저장 JSON, 기존 script 결과에는 복구 작업이 없다.
