# Explanation Engine v2 — Phase 5 Narrative Planner

**기준일:** 2026-10-02
**기준 main:** `e03282d4c6a9f2af14cb70889ff4cd9b0285d067`

## 결정

Phase 5는 `Evidence Pack + Explanation IR + prerequisite-resolution-v1`을 읽어 설명 순서만 정하는
shadow layer다. Production 대본·지시서·렌더 경로는 변경하지 않는다.

```text
Evidence Pack ───────────────┬→ Explanation IR ─┐
                             │                   ├→ narrative-plan-v1
Prerequisite Resolver → prerequisite resolution┘
```

## 최소 계약

- 영상 하나에 `core_question` 하나만 유지한다.
- `scope_action=NARROW_SCOPE`이면 계획을 만들지 않고
  `planning_status=BLOCKED_PREREQUISITE`로 닫는다.
- evidence-backed reasoning unit이 없으면 질문만 있는 이야기를 만들지 않고
  `planning_status=BLOCKED_NO_REASONING`으로 닫는다.
- 해결된 필수 선행개념은 첫 evidence/reasoning beat보다 앞에 둔다.
- Hook은 `core_question`만 사용하며 새로운 사실 주장을 만들지 않는다.
- 설명 beat의 문구는 IR unit 또는 prerequisite explanation을 그대로 참조한다.
- 모든 reasoning beat는 `reasoning_ids`, `evidence_ids`, `raw_refs`를 보존한다.
- Planner 진입 시 IR과 prerequisite resolution을 Evidence Pack 원장과 다시 검증한다.
- `semantic_entailment=false`를 다시 해석하거나 causal strength를 강화하지 않는다.

## 출력 형태

`narrative-plan-v1`은 `planning_status`, `core_question`, `thesis`, `beats`,
`excluded_reasoning_ids`, `warnings`, `source`를 가진다. Beat stage는
`HOOK|SETUP|CONFLICT|EXPLANATION|EVIDENCE|PAYOFF|BOUNDARY`만 허용한다.
같은 stage의 연속 IR unit은 한 beat로 묶을 수 있지만 원래 chain 순서는 바꾸지 않는다.

## 말로 읽을 숫자 배정 (2026-10-04)

각 beat 에 `number_delivery = {spoken_numbers, screen_facts}` 를 둔다. 대본 재료(`content_points`)는
그대로 두고(위 계약), **어느 숫자를 말하고 어느 문장을 화면 카드로 보낼지만** 정한다.

- 예산: 영상 전체 `MAX_SPOKEN_NUMBERS`(2). 시점 표현(2026년·3분기·3Q26E)과 이름 속 숫자(HBM4·A100)는 세지 않는다.
- 우선순위: ① thesis 와 같은 문장 ② `result`·`payoff` 역할 ③ 나머지 — 각각 이야기 순서. 한 단위의 숫자는
  전부 말하거나 전부 화면으로(범위를 반쪽만 읽지 않는다).
- 고르지 못한 단위는 `screen_facts`(원문 문장 + 숫자)로 가고 Phase 10 컷에 실린다.
- `validate()` 가 같은 규칙으로 다시 계산해 다르면 `number_delivery_invalid`.

배경: 종전에는 숫자를 전부 대본 재료로 넘겨 Phase 6(숫자 변경 금지)과 Phase 8(2개 상한)이 동시에 만족될 수
없었다(파일럿 16·15개). 숫자 계약은 `engine/spoken_numbers.py` 한 자리다(2026-10-04, Phase 12 파일럿 후속).

## 기존 4막과 관계

기존 `engine/narrative.py`의 4막은 대본 형식으로 유지한다. 새 planner는 그보다 앞에서
무슨 논리를 어떤 순서로 지불할지 정한다. 따라서 이번 단계에서 기존 prompt나 scene
normalizer를 수정하지 않는다.

## Shadow 비교

동일 Gold Set에서 다음만 판정한다.

- one-core-question 유지
- prerequisite-before-complexity
- IR chain coverage 및 stable ref 보존
- unresolved prerequisite fail-closed
- shallow-source IR 상한 보존

spoken narration, directive, render, retention은 `not_measured`다. 단일 개선률은 만들지 않는다.

### Gold Set 결과

| Case | Phase 5 status | 확인된 변화 |
|---|---|---|
| Personality GWAS | `READY` | 두 prerequisite를 reasoning보다 먼저 배치하고 association guardrail 및 trace를 보존 |
| Heel strike | `BLOCKED_PREREQUISITE` | exclusivity 오류가 해결됐다고 주장하지 않고 story 생성 차단 |
| Retinotopic remapping | `BLOCKED_PREREQUISITE` | cross-sensory mechanism 오류가 해결됐다고 주장하지 않고 story 생성 차단 |
| Samsung report | `BLOCKED_PREREQUISITE` | memory-cycle 개념 미해결 상태에서 story 확장 차단 |
| NH Mid Cycle | `BLOCKED_PREREQUISITE` | BRIEF IR 상한을 보존하고 미해결 개념 확장 차단 |
| Shipbuilding | `BLOCKED_PREREQUISITE` | opportunity를 현재 사실로 바꾸지 않고 story 생성 차단 |

이는 최종 영상 품질 점수가 아니다. 현재 측정 가능한 개선은 safe ordering, stable trace,
fail-closed planning뿐이다.

## Fable Review와 조치

1. 초기 validator가 content/ref만 검사하고 causal level, uncertainty, attribution,
   transition relation 변조를 놓쳤다. 모든 semantic metadata를 IR과 exact-match하도록 보강했다.
2. reasoning unit이 0개여도 질문 하나짜리 plan이 나왔다. `BLOCKED_NO_REASONING`을 추가했다.
3. Planner가 Evidence Pack을 받지 않아 변조된 evidence/raw ref를 원장과 대조할 수 없었다.
   Evidence Pack을 필수 입력으로 바꾸고 Phase 3/4 validator를 진입 시 다시 실행한다.
4. 차단된 case에도 one-core-question 개선을 표시했다. story 미생성 상태는 `not_applicable`로 낮췄다.
5. legacy case의 domain/shape를 검증하지 않아 다른 도메인 finding을 잘못 비교할 수 있었다.
   comparator가 case ID, domain, findings shape를 먼저 검증하도록 보강했다.

## 검증

- Phase 5 targeted: 13 passed
- adjacent Explanation Engine: 79 passed
- full Python: 2562 passed, 22 skipped
- Web Node: 152 passed
- TypeScript `tsc --noEmit --incremental false`: passed
- lint: passed, no warnings/errors
- production build: passed, 39 static pages

## Rollback

Phase 5 신규 모듈·테스트·fixture·문서를 제거하면 된다. DB와 Production 데이터 변경은 없다.
