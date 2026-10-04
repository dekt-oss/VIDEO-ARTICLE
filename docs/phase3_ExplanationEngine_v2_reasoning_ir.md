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
- `UNSUPPORTED`·`STALE`·`NOT_CHECKED` evidence는 positive reasoning unit의 근거가 될 수 없다
  (`NOT_CHECKED` 는 2026-10-05 설계 점검 B 로 추가 — 아래 §정정).

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

- `UNSUPPORTED`, `STALE`, `NOT_CHECKED`: positive reasoning 근거로 사용 금지(제약 역할 limitation·risk 는 예외)
- `SUPPORTED`: `verification_scope`가 확인한 항목만 신뢰
- `UNVERIFIABLE_AT_CURRENT_DEPTH`: 사용 시 상태를 보존하고 warning 부여

**정정(2026-10-05, 설계 점검 B).** 종전에는 `NOT_CHECKED` 도 warning 만 붙이고 근거로 썼다. 그러면 "한 번도
검증 안 된 근거"가 "옛 규칙으로 검증된 근거(`STALE`)"보다 통과가 쉽다 — 안전 쪽으로 거꾸로다. 실데이터에서
retinotopic 논문(`6b2d092a`)의 근거 6/6 이 `NOT_CHECKED` 로 V2 근거가 됐다. 이제 둘 다 막고, 비교 자료에
"Fact Sheet 재검증 필요(상태별 건수)"를 표시한다. 얕은 원문용 `UNVERIFIABLE_AT_CURRENT_DEPTH` 는 그대로다.
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
- Adapter가 Evidence Pack에서 고른 기본 thesis는 원문 항목을 그대로 사용한다.
- 호출자가 질문이나 thesis를 직접 넘기면 텍스트의 semantic entailment를 코드가 증명할 수
  없으므로 `caller_*_semantics_unverified` warning을 남긴다. 이 warning이 있는 값을 자동으로
  Production narration에 승격하면 안 된다.
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

## 12. 구현된 Shadow API

Phase 3의 진입점은 기존 생성 파이프라인이 아니라 명시적인 Python 호출뿐이다.

### Paper

```python
from engine import evidence_pack, paper_reasoning_adapter

pack = evidence_pack.build(paper_fact_sheet, "paper", content_id=paper_id)
ir = paper_reasoning_adapter.build(
    pack,
    core_question="이 연구가 실제로 보여 주는 것은 무엇인가?",
    thesis="Fact Sheet의 세기를 넘지 않는 한 문장",
)
```

Paper Adapter는 `claims`만 positive reasoning으로 사용한다. `what_found`와 `how`에서
투영된 `background_context`는 항목별 semantic verification이 없으므로 prerequisite로
자동 승격하지 않는다. claim에 붙은 limitation은 같은 evidence ID를 가진 별도
`limitation` unit으로 이어진다.

### Report

```python
from engine import evidence_pack, report_reasoning_adapter

pack = evidence_pack.build(report_fact_sheet, "report", content_id=report_id)
ir = report_reasoning_adapter.build(pack, {"units": normalized_report_reasoning_units})
```

Report Adapter는 기존 `report_reasoning.normalize_units()` 이후의 결과를 받는다.
`fact_ids=["num_op"]`는 `evidence_ids=["report:num_op"]`로만 변환된다. 원문 quote만 있고
Evidence Pack ID가 없는 단계는 IR에서 제외된다. `full_text`는 5×5, `partial_text`는
1×3, `summary_only/none`은 0×0이라는 Phase 1 상한을 config 정본에서 다시 읽는다.

## 13. Warning과 Validation

대표 warning:

- `evidence_ref_unknown:<id>`: Evidence Pack에 없는 참조
- `evidence_state_disallowed:<id>:<state>`: unsupported/stale positive 근거
- `semantic_entailment_unverified:<id>`: quote 존재가 claim 의미 전체를 입증하지 않음
- `evidence_not_checked:<id>`: 항목별 검증 미실행
- `evidence_unverifiable:<id>`: 현재 source depth에서 판정 불가
- `report_step_without_evidence_id:<Rxx#step>`: 기존 금융 단계에 Fact Sheet ID가 없음
- `report_attribution_derived:<Rxx#step>:<broker>`: unit 귀속이 비어 Evidence Pack에서 복구
- `report_attribution_corrected:<Rxx#step>:<old>!=<broker>`: stale/cross-report 귀속을 정본으로 보정
- `report_attribution_missing|ambiguous:<Rxx#step>`: broker 귀속을 안전하게 정할 수 없음
- `caller_core_question_semantics_unverified`, `caller_thesis_semantics_unverified`: 호출자 입력의
  의미 강도를 코드가 검증하지 못함
- `source_reasoning_units_capped`, `source_reasoning_steps_capped`: Phase 1 상한 적용

`engine.explanation_ir.validate(ir, pack)`는 contract/domain/core question/ID/chain/evidence/raw
reference를 다시 검사한다. warning은 보존 가능한 불확실성을 나타내고, validation error는
IR 구조를 소비하면 안 된다는 뜻이다.

## 14. 실제 변경 경계

- `engine/explanation_ir.py`: 공통 정규화·검증
- `engine/paper_reasoning_adapter.py`: Paper Claim Ledger Adapter
- `engine/report_reasoning_adapter.py`: 기존 금융 reasoning Adapter
- `tests/test_explanation_ir.py`: 공통·도메인·Gold Set 회귀
- `tests/fixtures/explanation_ir_gold_cases.json`: Paper 3건 + Report 3건

기존 `scriptgen.py`, `report_scriptgen.py`, directive, render, web, Supabase 경로는
변경하지 않았다. 따라서 이 PR만 배포해도 Production output은 Phase 2와 동일하며,
새 IR은 호출자가 명시적으로 Adapter를 호출할 때만 생성된다.

## 15. 검증 결과

2026-10-01 로컬 격리 worktree에서 다음을 실행했다.

- Phase 3 + Evidence Pack + Report Reasoning targeted: `54 passed`
- 전체 Python: `2533 passed, 22 skipped`
- Web Node tests: `150 passed, 0 failed`
- TypeScript `tsc --noEmit --incremental false`: 통과
- Next lint: warning/error 없이 통과 (`next lint` deprecation 안내만 존재)
- Next production build: 39개 static page 생성을 포함해 통과
- `git diff --check`: 통과

전체 pytest의 최초 sandbox 실행은 Windows 임시 디렉터리 권한으로 setup error가 발생했다.
코드 실패와 분리하기 위해 쓰기 가능한 고정 `--basetemp`로 전체 suite를 다시 실행했고 위 최종
결과를 얻었다.

## 16. Fable Review 결과

실패를 전제로 evidence state, source depth, attribution, ID/ref를 다시 공격적으로 확인했고 다음
계약 누락을 보정했다.

1. 정규화 후 IR을 수동 조작하면 `validate()`가 `UNSUPPORTED` positive evidence를 놓치던 문제
2. invalid Evidence Pack을 `validate()`가 명시적 오류로 반환하지 않던 문제
3. `summary_only/none`에서 unit은 0개여도 기존 deep reasoning title이 thesis로 남을 수 있던 문제
4. report reasoning의 `attributed_to`가 비었을 때 Evidence Pack의 broker 귀속을 복구하거나
   missing/ambiguous warning을 내지 않던 문제
5. report reasoning 또는 정규화 후 IR의 broker 귀속이 Evidence Pack과 충돌해도 정본 기준으로
   보정·거부하지 않던 문제

각 항목은 실패하는 회귀 테스트를 먼저 확인한 뒤 수정했다. 보정 후 blocking finding은 없다.
다만 caller가 직접 제공한 core question/thesis의 의미적 타당성은 deterministic code로 검증할 수
없어서 warning으로 표시하며, 실제 Production source→draft→directive→approval 동작과 실제 Gold Set
payload shadow 비교는 이 PR에서 미검증이다.
