# Explanation Engine v2 Phase 6 — Spoken Narration

## 결론

Phase 6는 `narrative-plan-v1`을 짧은 한국어 구어체 초안으로 바꾸는 shadow-only 계약이다.
현재 Production의 Paper/Report 대본 생성 결과에는 연결하지 않았다. 모델은 문장만 쓸 수 있고,
`narration_id`, reasoning/evidence/raw-ref, prerequisite knowledge ref, causal/uncertainty/attribution
메타데이터는 검증된 Narrative Plan에서 코드가 주입한다.

`DRAFT_ACCEPTED`는 Phase 6의 결정론적 검사만 통과했다는 뜻이다. 문장별 의미 함의가 원문과
일치하거나 발행 가능한 상태라는 뜻이 아니다. `qa.semantic_entailment`는 항상 `NOT_CHECKED`이며,
그 판정은 Phase 7의 책임이다.

## 현재 문제와 Phase 6의 경계

기존 Production 경로는 Fact Sheet에서 곧바로 대본과 시각 지시를 만들기 때문에, reasoning과
화면 사이의 의미 연결이 약해지거나 범위·인과·귀속이 강화되어도 최종 단계에서 추적하기 어렵다.
Phase 3–5는 Evidence Pack → Explanation IR → prerequisite resolution → Narrative Plan을 만들었다.
Phase 6는 이 검증된 계획만 보고 spoken draft를 만들며, 원문 전문이나 임의 Fact Sheet 필드를
다시 읽지 않는다.

```
Evidence Pack
  → Explanation IR
  → Prerequisite Resolution
  → Narrative Plan
  → Spoken Narration draft (Phase 6, shadow only)
```

## 입력과 출력 계약

입력은 다음 네 계약이며 Phase 6 경계에서 모두 다시 검증한다.

- `evidence-pack-v1`
- `explanation-ir-v1`
- `prerequisite-resolution-v1`
- `narrative-plan-v1`

`planning_status=READY`만 모델 호출 대상이다. `BLOCKED_PREREQUISITE`와
`BLOCKED_NO_REASONING`은 호출 전에 `BLOCKED_UPSTREAM`으로 반환한다.

출력 계약은 `spoken-narration-v1`이다.

- `DRAFT_ACCEPTED`: 결정론적 Phase 6 guard 통과
- `REJECTED_DRAFT`: 모델 payload/coverage/semantic guard 실패
- `BLOCKED_UPSTREAM`: 상류 plan이 READY가 아니어서 호출하지 않음

모델 입력에는 질문·thesis·ordered beat·content point·해결된 prerequisite explanation과
guardrail·causal/uncertainty/attribution/transition 메타데이터만 들어간다. evidence ID, raw ref,
원문 전문, 기존 Production 대본과 directive는 모델에 전달하지 않는다.

## 결정론적 차단과 경고

다음은 draft를 `REJECTED_DRAFT`로 만든다.

- beat 누락·중복·순서 변경·unknown ID·빈 문장
- 숫자의 부호 또는 붙은 단위·통화의 변경·삭제·추가(공백 종류 차이는 정규화)
- `모든`, `유일`, `항상`, `절대`, `오직`, `최초`, `전부`, `완전히`, `반드시`의 신규 추가
- association 표현을 determination/direct-cause 표현으로 강화
- 범위 단서 각각의 제거와 불확실성·연관·부정 의미 갈래 제거/추가
- 연관·부정 문구를 남겨 둔 채 determination/direct-cause 표현을 추가하는 우회
- `broker_projection`을 단정형으로 변경
- Report beat의 증권사 귀속 제거
- 승인된 핵심 질문 뒤에 근거 없는 사실 단정을 붙인 hook
- factual beat의 reasoning/evidence/knowledge trace 소실

다음은 경고이며 Phase 6에서 차단하거나 의미 정합성을 증명하지 않는다.

- 60자를 넘는 문장
- 핵심 질문 반복
- 한 beat에 과도한 숫자
- 설명되지 않은 영문 약어
- 보고서식·논문식 문체 휴리스틱

## Spoken polish

Polish는 accepted first draft만 받는 독립 단계다. 각 beat에서 기존
`engine.script_polish.rejection_reason()`을 먼저 적용하고, Phase 6 전체 draft guard도 다시
통과해야 한다. 어느 하나라도 실패하면 그 beat의 accepted 문장을 그대로 유지하고
`polish.rejected`에 이유를 기록한다. 입력 artifact는 변경하지 않는다.

기존 Production `engine/script_polish.py`의 동작은 변경하지 않았다.

## Gold Set shadow 결과

결정론적 fixture 결과는 다음과 같다.

| Case | Phase 6 상태 | 의미 |
|---|---|---|
| Personality GWAS | `DRAFT_ACCEPTED` | prerequisite와 association guard를 유지한 deterministic payload |
| Heel strike | `BLOCKED_UPSTREAM` | 필수 prerequisite 미해결, 모델 호출 0회 |
| Retinotopic remapping | `BLOCKED_UPSTREAM` | 필수 prerequisite 미해결, 모델 호출 0회 |
| Samsung report | `BLOCKED_UPSTREAM` | 필수 prerequisite 미해결, 모델 호출 0회 |
| NH Mid Cycle | `BLOCKED_UPSTREAM` | shallow source 확장 방지, 모델 호출 0회 |
| Shipbuilding report | `BLOCKED_UPSTREAM` | opportunity/current-state 전환 방지, 모델 호출 0회 |

이 결과는 기존 영상보다 최종 품질이 좋아졌다는 뜻이 아니다. 비교기는 `semantic_entailment`와
`final_directive_quality`를 항상 `not_measured`로 보고하며 개선 백분율을 만들지 않는다.

## Production과 비용 경계

이번 Phase에서는 다음을 하지 않았다.

- `engine/scriptgen.py`, `engine/report_scriptgen.py`, Production prompt 수정
- Supabase/DB migration 또는 artifact 저장
- directive/approval/render/publish 연결
- 실제 Gold Set 재생성, 외부 모델 또는 유료 API 호출
- Production shallow-source 신규 1편의 source → draft → directive → approval 실사

모든 자동 테스트는 고정 payload 또는 injected caller를 사용한다.

Phase 6 경계는 상류 plan을 동일 IR/resolution에서 다시 만든 canonical plan과 대조한다. 따라서
필수 SETUP beat를 삭제·재번호화한 plan도 모델 호출 전에 거부한다. Artifact validator는 저장된
QA 결과를 신뢰하지 않고 현재 문장에서 guard·warning·metric을 다시 계산하며, READY plan과
`BLOCKED_UPSTREAM` 같은 status 불일치도 거부한다.

## 비교 가능 시점

- Phase 7: Source/Evidence와 최종 narration의 clause-level semantic fidelity 비교
- Phase 9: reasoning ID가 Visual Stage/Mutation까지 이어진 뒤 legacy directive와 V2 directive 비교
- Phase 11: 실제 rendered output 비교
- Phase 13–14: 통합 publish gate와 실제 A/B 지표

## Rollback

`engine/spoken_narration.py`, `engine/spoken_narration_shadow_compare.py`, 관련 테스트·문서를
제거하면 된다. 저장 데이터와 Production wiring이 없으므로 데이터 rollback은 필요 없다.
