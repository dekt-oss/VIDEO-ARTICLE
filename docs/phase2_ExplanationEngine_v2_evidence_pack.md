# Explanation Engine v2 — Phase 2 Common Evidence Pack

**기준일:** 2026-10-01  
**선행:** Phase 0 Gold Set, Phase 1 Source Adequacy  
**목적:** 논문과 리포트의 서로 다른 근거 원장을 복제하지 않고, 다음 Explanation Reasoning 단계가 공통 인터페이스로 읽게 한다.

---

## 1. 결론

완전한 공통 Fact Sheet를 새로 만들지 않는다.

현재 정본은 이미 다르며 각각 강점이 있다.

### 논문

`claims`가 구조화되어 있다.

- claim_id
- claim_kind
- claim_ko
- population / sample / design
- effect
- causal_strength
- source_quote
- evidence_grade
- validation

### 리포트

정성 주장과 수치 원장이 분리돼 있다.

- `what`
- `basis`
- `risks`
- `opinion`
- `number_facts`

특히 `number_facts`는 값·단위·기간·귀속·원문 quote·validation이 강하다.

둘을 하나의 새 저장 구조로 복사하면:

```text
Paper Fact Sheet
Report Fact Sheet
Common Fact Sheet   ← 세 번째 정본
```

이 되어 drift 위험만 늘어난다.

따라서 Phase 2는:

> **기존 Fact Sheet → 읽기 전용 Evidence Pack**

Adapter만 제공한다.

정본은 기존 Fact Sheet다.

---

## 2. 구현

정본:

```text
engine/evidence_pack.py
```

공통 출력:

```yaml
contract_version: evidence-pack-v1
domain:
content_id:

source:
  source_depth:
  source_chars:
  source_mode:
  provider:
  attribution:

claims:
  - evidence_id:
    raw_ref:
    text:
    claim_type:
    domain_role:
    causal_strength:
    evidence_grade:
    verification_state:
    source_refs:
    uncertainty:
    limitations:
    attribution:
    domain_fields:

numbers:
  - evidence_id:
    raw_ref:
    value:
    unit:
    period:
    metric:
    scope:
    basis:
    attribution:
    display:
    comparator:
    interpretation:
    verification_state:
    validation:
    source_refs:

risks:
limitations:
background_context:
```

---

## 3. 가장 중요한 규칙 — raw_ref

공통 Pack의 모든 Evidence item은 원래 Fact Sheet 위치를 가리킨다.

예:

```text
paper:C01
raw_ref = claims:C01

report:num_target_price
raw_ref = number_facts:num_target_price

report:basis:01
raw_ref = basis[0]
```

이유:

> Explanation Engine이 어떤 문장을 만들었을 때 최종적으로 “어느 원장 항목에서 왔나”를 다시 추적할 수 있어야 한다.

Evidence Pack을 수정해도 원본 Fact Sheet는 바뀌지 않는다.

---

## 4. 검증 상태를 억지로 통일하지 않는다

공통 enum:

```text
SUPPORTED
UNSUPPORTED
UNVERIFIABLE_AT_CURRENT_DEPTH
NOT_CHECKED
STALE
```

### 논문 Claim

현재 `paper_evidence` validation을 그대로 반영한다.

계약 버전이 오래된 validation은 `STALE`이다.
예전 판정을 최신 사실처럼 재사용하지 않는다.

### 리포트 number_fact

원래 `validation`을 보존한다.

```text
number_match
unit_match
period_match
quote_supports_claim
```

그리고 quote/value 대조 상태로 공통 verification_state를 제공한다.

예:

```text
quote_supports_claim=true
number_match=true
period_match=false
```

이면 quote/value는 `SUPPORTED`로 두고
`period_match=false` 자체도 별도 validation 필드에 그대로 남긴다.

즉 하나의 Boolean으로 모든 검증 의미를 뭉개지 않는다.

---

## 5. 리포트 정성 문장은 NOT_CHECKED

현재 리포트의:

```text
what
basis
opinion
risks
```

는 항목별 source quote가 없다.

따라서 Evidence Pack이 임의로:

```text
SUPPORTED
```

라고 붙이면 안 된다.

공통 Adapter는 이들을:

```text
verification_state = NOT_CHECKED
```

로 둔다.

이는 결함을 숨기는 것이 아니라 현재 원장의 실제 상태를 정확히 표현한다.

향후 Phase 3/7에서 정성 주장에도 원문 quote 대조가 필요하다고 판단되면
정본 Fact Sheet 쪽 계약을 강화해야 한다.

Adapter가 없는 근거를 만들어서는 안 된다.

---

## 6. Claim Type을 과도하게 통일하지 않는다

논문:

```text
main_result
mechanism
author_interpretation
...
```

은 원래 claim_kind를 보존한다.

리포트 정성 항목은 구조적 출처를 보존한다.

```text
what    → reported_claim
basis   → reported_reason
opinion → broker_opinion
```

그리고 `domain_role`에 원래 필드명을 남긴다.

현재 정보만으로 basis 문장을:

```text
actual
forecast
scenario
```

중 하나라고 자동 분류하지 않는다.

그것은 Phase 3의 Domain Reasoning Adapter가 Evidence와 원문을 바탕으로 판단할 일이다.

---

## 7. 숫자 처리

### 리포트

`number_facts`의 구조를 거의 그대로 보존한다.

- value
- unit_norm
- period
- metric
- scope
- basis
- attribution
- comparator
- source_refs
- validation

### 논문

현재 top-level `numbers`는 문자열 요약이다.

Phase 2 Adapter에서 이를 억지로 숫자 파싱하지 않는다.

```text
value = null
display = 원문 문자열
verification_state = NOT_CHECKED
```

로 둔다.

실제 구조화된 효과 크기는 Paper Claim의 `effect_size/effect_unit`에 이미 있으므로
그 원장을 사용한다.

---

## 8. Source Adequacy와 연결

Phase 1 정책이 있으면 Evidence Pack의 source에 그대로 노출한다.

```text
source_depth
source_chars
source_mode
```

하지만 레거시 콘텐츠에 정책이 없으면 새 Adapter가 임의로 FULL/BRIEF를 추정하지 않는다.

---

## 9. 이번 Phase에서 하지 않는 것

- DB migration
- Fact Sheet schema 교체
- 기존 Fact Sheet에 Evidence Pack 저장
- Paper/Report 원장 복제
- LLM 호출
- Explanation Reasoning 생성
- 대본 변경
- Renderer 변경

즉 Phase 2 자체는 Production 영상 결과를 바꾸지 않는다.

다음 Phase의 Explanation Engine이 읽을 **공통 입력 계약**을 만든다.

---

## 10. 회귀 테스트

`tests/test_evidence_pack.py`

고정 항목:

1. Paper Claim Ledger 1:1 projection
2. Paper evidence verification 보존
3. 오래된 paper validation → STALE
4. Report qualitative claim → NOT_CHECKED
5. Report number validation 원형 보존
6. Number mismatch → UNSUPPORTED
7. Paper limitation / Report risk 의미 분리
8. Pack 수정이 원본 Fact Sheet를 변경하지 않음
9. 모든 Evidence item이 raw_ref 보유
10. 레거시 source metadata에 없는 의미를 새로 만들지 않음

---

## 11. Phase 3가 이 Pack을 소비하는 방식

다음 Phase의 Domain Adapter는 원본 Fact Sheet를 직접 제각각 읽지 않는다.

```text
Paper Fact Sheet ─┐
                  ├→ Evidence Pack → Paper Reasoning Adapter ─┐
Report Fact Sheet ─┘                                          │
                                                             ↓
                                                     Explanation IR
```

단, Domain Adapter가 정말 필요한 원본 도메인 필드는
`domain_fields/raw_ref`를 통해 추적 가능하다.

---

## 12. 완료 기준

- [x] 공통 Evidence Pack 계약 정의
- [x] Paper Adapter
- [x] Report Adapter
- [x] source/verification semantics 보존
- [x] raw_ref 역추적
- [x] 원본 불변성 테스트
- [x] 잘못된 공통화 방지 테스트
- [ ] 전체 Python CI
- [ ] 기존 Phase 1 CI 선행 통과
- [ ] Production 저장 샘플 projection 실측

마지막 세 항목은 검증 후 완료 판정한다.
