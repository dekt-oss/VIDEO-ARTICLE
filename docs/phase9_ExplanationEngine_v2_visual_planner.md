# Explanation Engine v2 Phase 9 — Traceable Visual Planner

## 결론

Phase 9는 `content-complexity-gate-v1`이 `READY`인 대본만 받아
`visual-plan-v1`으로 변환하는 Shadow-only Visual Planner다. 각 의미 단위는 다음 ID 사슬을
유지한다.

`Narrative Beat → Narration → Reasoning → Evidence/raw_ref → Visual Stage → Mutation → Shot`

현재 Production `directive.py`, `report_directive.py`, 승인, 렌더, 발행 경로에는 연결하지
않았다. 따라서 이번 Phase가 증명하는 것은 trace와 차단 계약이며, 최종 지시서나 렌더 영상의
미학적 개선은 아니다.

## 현재 문제

기존 Production 지시서는 화면 관련 필드를 풍부하게 갖고 있지만, 상류 reasoning/evidence와
실제 Stage/Mutation의 연결이 끊기는 사례가 있었다. Samsung report에서는 상류 R01~R04가
있어도 directive cut의 claim reference가 비었고, shipbuilding report에서는 reasoning ID가
남아도 claim ID가 비었다. 관련 공장이나 책상 이미지는 만들었지만 “왜”를 화면 변화로 설명하지
못한 사례도 있었다.

Phase 9는 모델로 그럴듯한 장면을 새로 쓰지 않는다. 이미 검증된 의미와 ID를 구조화된 Stage,
Mutation, Shot Directive에 투영한다.

## 입력과 차단 경계

입력:

- 기존 normalized `content_plan`
- `content-complexity-gate-v1`
- `spoken-narration-v1`
- `semantic-fidelity-v1`
- `narrative-plan-v1`
- `explanation-ir-v1`
- `prerequisite-resolution-v1`
- `evidence-pack-v1`

Phase 8 Gate를 현재 입력으로 다시 계산한다. 저장된 Gate의 status, constraints, override가
정본과 다르면 `content_complexity_gate_invalid:gate_not_canonical`로 거절한다.

- `READY`: Visual Stage/Mutation/Shot을 생성한다.
- `ACTION_REQUIRED`: `BLOCKED_GATE`, Visual 결과 0개
- `BLOCKED_UPSTREAM`: `BLOCKED_GATE`, Visual 결과 0개

## 출력 계약

`visual-plan-v1`의 최소 필드:

- `planner_status`: `READY|BLOCKED_GATE`
- `sequences`: 의미상 연속된 stage 묶음
- `visual_beats`: 하나의 의미와 하나의 구조화된 화면 변화
- `stage`: `stage_id`, operation, camera, continuity, mutations
- `shot_directive`: narration/reasoning/evidence/source reference와 의미 기반 transition
- `constraints`: Source Adequacy와 mechanism 허용 범위
- `qa.metrics`: visual beat, traced stage, mechanism stage 수

Visual mode는 `QUESTION`, `PREREQUISITE`, `PHENOMENON`, `SCHEMATIC`, `MECHANISM`,
`DATA`, `RESULT`, `BOUNDARY`로 제한한다. `MECHANISM`은 Phase 8이 허용한 reasoning ID에만
사용한다. Report의 broker attribution, projection causal level, uncertainty도 Stage와 Shot까지
보존한다.

Transition은 임의 효과가 아니라 의미 관계에서 결정한다.

| 의미 관계 | Shot transition |
|---|---|
| `supports` | `GRAPHIC_MATCH` |
| `continues` / process | `OBJECT_FOLLOW` |
| `qualifies` / limitation | `CUTAWAY` |
| whole → part | `PUSH_IN` |
| part → whole / payoff | `PULL_OUT` |
| 그 외 새 질문 | `HARD_CUT` |

새 sequence의 첫 stage는 항상 `NEW_WORLD`다. 기존 Visual Sequence 계약에 맞춰
`MECHANISM_SEQUENCE`는 2개 이상의 stage일 때만 사용한다.

## 실제 Production 명세서 전후 비교

비교 기준은 `tests/fixtures/explanation_quality_gold_set.json`의 2026-10-01 Production
read-only 감사 결과다. 아래 “전”은 실제로 저장된 directive 요약이며, “후”는 동일 case가
Phase 3~8 의미 검증을 거쳐 Phase 9에 도달했을 때의 Shadow 결과다.

| Production case | 전: 실제 directive | 확인된 P0 | 후: V2 Phase 9 |
|---|---:|---|---|
| Heel strike | 67초 · 17컷 | 인간만 heel-strike한다는 범위 확대 | `BLOCKED_GATE`, stage 0 |
| Samsung memory | 66초 · 10컷 | report→paper 오라우팅, reasoning link 소실 | `BLOCKED_GATE`, stage 0 |
| NH Mid Cycle | 50초 · 12컷 | 1,072자 source 과확장, 무근거 hook | `BLOCKED_GATE`, stage 0 |
| Retinotopic remapping | 58.37초 · 9컷 | 청각 자원을 시각으로 옮겼다는 기전 발명 | `BLOCKED_GATE`, stage 0 |
| Personality GWAS | 84.86초 · 13컷 | association→determination | `BLOCKED_GATE`, stage 0 |
| Shipbuilding | 64초 · 10컷 | opportunity→현재 대체 사실, claim link 소실 | `BLOCKED_GATE`, stage 0 |

### 비교 판정

- 실제 과거: 여섯 case 모두 directive가 생성됐고 각 case에 P0 의미/trace 결함이 있었다.
- V2 Shadow: 여섯 case 모두 `PREVENTED_BEFORE_VISUAL`; Visual Beat/Stage/Mutation/Shot 0개다.
- 개선 확인: 문제 의미가 Visual 지시로 승격되는 release 경로를 닫았다.
- 아직 확인 불가: 안전한 새 대본으로 만든 최종 Production 지시서의 화면 설명력과 미학.
- 렌더 비교: 미실행·미검증. `rendered_video_quality=not_measured`다.

Retinotopic 사례의 기존 실측 기록(`docs/핸드오프_기전교육력_2026-09-18.md`)에는 실제
재생성 directive와 4-stage 기전 렌더가 남아 있다. 하지만 그 시각 구조가 풍부하다는 사실은
“청각 자원을 시각으로 이전했다”는 상류 의미 발명을 정당화하지 않는다. Phase 9 결과가
0 stage인 이유는 시각 품질을 포기해서가 아니라, 틀린 기전을 더 정교하게 그리지 않기 위해서다.

## 안전한 입력에서 확인한 구조 변화

결정론적 Paper fixture에서는 2개 Visual Beat가 생성됐다.

1. 질문 `VB01 → VS01 → VM01 → SHOT01`
2. 근거 있는 mechanism `VB02 → XR01 → paper:C01 → claims:C01 → VS02 → VM02 → SHOT02`

Report fixture에서는 broker attribution과 `broker_projection`이 Visual Beat와 Shot Directive까지
동일하게 유지됐다. 이 fixture는 계약 검증용이며 실제 Production 품질 비교로 세지 않는다.

## Fable Review

구현이 틀렸다고 가정하고 비교 정합성, continuity, 기존 Visual Sequence 계약을 공격적으로
검토했다.

1. 다른 case/domain의 plan을 legacy case와 비교할 수 있었다.
   `comparison_identity_mismatch`로 거절하도록 수정했다.
2. 훅과 mechanism이 다른 sequence인데 두 번째를 `CONTINUE_WORLD`로 만들었다.
   각 sequence 첫 stage를 `NEW_WORLD`로 다시 계산하도록 수정했다.
3. 단일 mechanism stage도 `MECHANISM_SEQUENCE`로 분류했다.
   2개 미만이면 `RESULT_SEQUENCE`로 낮춰 기존 계약과 맞췄다.
4. `blocked_from_gate()`가 `READY` Gate도 차단 결과로 바꿀 수 있었다.
   `ACTION_REQUIRED|BLOCKED_UPSTREAM`만 받도록 수정했다.

모든 수정은 실패하는 회귀 테스트를 먼저 추가한 뒤 반영했다.

## 검증 결과

- Phase 9 targeted: `11 passed`
- Phase 2~9 + 기존 Visual Sequence/Stage 인접 회귀: `206 passed`
- 전체 Python: `2667 passed, 22 skipped`
- Web Node: `141 passed, 0 failed` (기존 module type 경고는 남아 있음)
- TypeScript `tsc --noEmit`: 통과
- ESLint: 오류·경고 없음 (Next.js lint deprecation 안내만 출력)
- Next.js production build: 통과, static page 39개 생성

외부 모델, DB, 유료 렌더 호출은 하지 않았다.

## 변경 경계와 rollback

- `engine/visual_planner.py`: 정본 Visual Plan 생성·검증
- `engine/visual_plan_shadow_compare.py`: 실제 Production Gold 전후 비교
- `tests/test_visual_planner.py`: Paper/Report/위조/차단/비교 회귀

DB migration, 외부 모델 호출, asset 선택, Production wiring은 없다. 세 파일과 이 문서를
제거하면 rollback된다.

## 다음 단계

Phase 10은 Phase 9의 추상 Shot Directive를 기존 Production directive schema로 투영하되,
`reasoning_id`, `evidence_id`, `raw_ref`, `stage_id`, `mutation_id`를 잃지 않아야 한다.
그때 안전하게 통과한 실제 source 1편을 재생성하면 기존 지시서와 V2 지시서의 내용·연출을
동일 입력으로 직접 비교할 수 있다. Phase 11 이후에만 실제 rendered output을 비교한다.
