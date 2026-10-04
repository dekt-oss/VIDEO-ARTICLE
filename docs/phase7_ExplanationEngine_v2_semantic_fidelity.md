# Explanation Engine v2 Phase 7 — Semantic Fidelity QA

## 결론

Phase 7은 `spoken-narration-v1`의 모든 문장을 의미 절 단위로 Evidence Pack과
Explanation IR에 대조하는 shadow-only 품질 계약이다. 작성 모델과 분리된 critic이 의미
판정을 제안하고, 코드는 절 누락·재배열, 근거 세탁, 범위·인과·수식어·귀속 손실, 근거 없는
사실형 hook을 결정론적으로 차단한다.

현재 Paper/Report Production 대본, directive, approval, render, publish 경로에는 연결하지
않았다. `PASSED`는 Phase 7의 제한된 입력과 고정 계약 안에서 critic 판정과 결정론적 검증을
통과했다는 뜻일 뿐, 최종 지시서나 영상 품질이 개선됐다는 뜻이 아니다.

## 현재 문제와 선택한 구조

기존 self-check는 source quote가 존재한다는 사실을 claim 전체의 의미 보증처럼 취급하거나,
hook을 예외 처리해 association을 determination으로 강화한 문장을 놓칠 수 있었다. Phase 7은
의미 판정과 무결성 검증을 분리한다.

```text
Evidence Pack + Explanation IR + Prerequisite Resolution + Narrative Plan
  → Spoken Narration
  → independent semantic critic
  → deterministic clause/trace/support validation
  → semantic-fidelity-v1 (shadow only)
```

critic은 의미 판단만 수행한다. `clause_id`, beat/reasoning/concept/raw ref, aggregate status,
metrics는 코드가 정본 artifact에서 다시 만든다. writer와 critic은 호출 목적과 prompt가
분리되지만 같은 self-check 모델 설정을 사용할 수 있으므로 독립성 수준은 `separate_call`이다.

## 입력, 상태, 출력 계약

Phase 7 경계는 다음 다섯 입력을 다시 검증한다.

- `evidence-pack-v1`
- `explanation-ir-v1`
- `prerequisite-resolution-v1`
- `narrative-plan-v1`과 canonical 재구성 결과
- `spoken-narration-v1`과 현재 Phase 6 guard 재계산 결과

출력은 `semantic-fidelity-v1`이다.

- `PASSED`: 모든 사실 절이 적격 근거에 의해 entailed이고 수사 절 예외가 유효함
- `REJECTED`: 의미 실패 또는 결정론적 의미 guard 실패
- `BLOCKED_UPSTREAM`: Phase 6가 narration을 만들기 전에 차단됨; critic 0회
- `REJECTED_UPSTREAM`: Phase 6 draft가 거부됨; critic 0회
- `CRITIC_ERROR`: 호출 실패, payload/coverage/reference 계약 실패; 의미 통과로 승격하지 않음

## critic 입력 경계와 근거 적격성

critic은 각 beat가 소유한 narration, reasoning unit, prerequisite concept, Evidence Pack
항목만 받는다. 원문 전문, 무관한 Fact Sheet 항목, Production script/directive는 받지 않는다.

`verification_state=SUPPORTED`만으로는 사실 절을 통과시킬 수 없다. 다음 중 하나가 있어야 한다.

- 직접 인용 source span
- 값과 필요한 unit/period가 검증된 structured number
- 상류 `verification_scope.semantic_entailment=true`

`UNSUPPORTED`와 `STALE` evidence는 positive support가 될 수 없다. quote-presence만 true이고
source span이나 semantic entailment가 없는 항목도 positive support로 인정하지 않는다.
SETUP beat는 canonical prerequisite concept와 knowledge ref가 함께 있을 때만 evidence ID 없는
설명을 허용한다.

## clause coverage와 fail-closed 규칙

critic이 반환한 ordered clause span에서 공백만 정규화한 뒤 원문 문장을 정확히 한 번 완전히
덮는지 확인한다. 문장부호·숫자 부호·소수점·단위는 의미를 바꿀 수 있어 정확히 보존한다. 절
생략, 역순, 중복, 추가는 `CRITIC_ERROR`다. critic이 다른 beat의
evidence를 인용하거나 unknown ID를 만들면 역시 `CRITIC_ERROR`다.

다음 finding은 서로 구분해 보존한다.

- `contradiction`
- `scope_expansion`
- `causal_upgrade`
- `missing_qualifier`
- `unsupported_background`
- `attribution_loss`
- `unsupported_factual_hook`

수사적 예외는 HOOK의 순수한 핵심 질문에만 적용된다. 사실 주장이 섞였거나 evidence를 인용한
수사 절, HOOK 밖의 수사 절은 통과하지 않는다.
"순수한 핵심 질문"의 판정은 Phase 6 과 같은 `spoken_narration.hook_matches_core_question` 이다 — 내용은
글자 그대로, 문장 끝 어미만 말투 변형 허용(2026-10-04 정정, 이전에는 공백만 무시한 완전 일치였다).

## Gold Set shadow 결과

고정 fixture와 고정 critic payload의 결과는 다음과 같다.

| Case | Phase 7 상태 | critic 호출 | 계약상 의미 |
|---|---|---:|---|
| Heel strike | `BLOCKED_UPSTREAM` | 0 | 필수 prerequisite 미해결 상태 보존 |
| Retinotopic remapping | `BLOCKED_UPSTREAM` | 0 | 원문 밖 cross-sensory 설명 생성 전 차단 |
| Personality GWAS | `REJECTED` | 1 | quote-presence만 있고 적격 support surface가 없어 fail-closed |
| Samsung report | `BLOCKED_UPSTREAM` | 0 | 상류 reasoning/claim link 불충분 상태 보존 |
| NH Mid Cycle | `BLOCKED_UPSTREAM` | 0 | shallow source 과확장 전 차단 |
| Shipbuilding report | `BLOCKED_UPSTREAM` | 0 | opportunity를 current replacement로 바꾸기 전 차단 |

별도 합성 회귀는 `scope_expansion`, `causal_upgrade`, `missing_qualifier`,
`attribution_loss`가 각 축에서 `failed`로 남는지 확인한다. 이는 고정 payload에 대한 계약 검증이다.
실제 critic의 recall/precision이나 기존 Production 지시서 대비 품질 향상을 증명하지 않는다.

비교기는 `clause_coverage`, `stable_trace`, `semantic_entailment`, `scope_calibration`,
`causal_calibration`, `qualifier_preservation`, `attribution_preservation`, `hook_grounding`을
보고한다. `final_directive_quality`는 항상 `not_measured`이며 개선 백분율을 만들지 않는다.

## Production, 비용, 검증 경계

이번 Phase에서는 다음을 하지 않았다.

- `engine/scriptgen.py`, `engine/report_scriptgen.py`, directive/approval 경로 수정
- Supabase/DB migration 또는 Phase 7 artifact 저장
- 실제 외부 critic 모델 호출이나 유료 API 사용
- Gold Set 실제 재생성, 신규 Production source → draft → directive → approval 실사
- legacy directive와 V2 directive의 실제 명세서 비교
- render/publish 연결 또는 최종 영상 비교

자동 테스트는 injected caller와 고정 payload를 사용한다. 따라서 외부 모델의 실제 의미 판정
정확도와 비용·지연·재시도 동작은 미검증이다.

## 실제 명세서 비교 가능 시점

Phase 7부터 narration 단위 의미·trace 계약 비교는 가능하다. 실제 지시서 비교는 Phase 9에서
reasoning ID가 Visual Stage/Mutation과 Shot Directive까지 유지된 후가 적절하다. rendered
output 비교는 Phase 11 이후, publish gate와 실제 A/B는 Phase 13–14 범위다.

## Rollback

`engine/semantic_fidelity.py`, `engine/semantic_fidelity_shadow_compare.py`, 관련 테스트와 이 문서를
제거하면 된다. Production wiring과 저장 migration이 없으므로 데이터 rollback은 필요 없다.
