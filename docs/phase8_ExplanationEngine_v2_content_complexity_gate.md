# Explanation Engine v2 Phase 8 — Content Complexity Gate

## 결론

Phase 8은 `semantic-fidelity-v1`을 통과한 대본과 기존 `content_plan`을 읽고,
경고를 실제 후속 행동과 Visual Planner 제약으로 바꾸는 `content-complexity-gate-v1`
Shadow 계약이다. 현재 Production 대본·지시서·승인·렌더·발행 경로에는 연결하지 않았다.

`READY`는 Phase 9 Visual Planner가 이 Gate의 제약을 소비해도 된다는 뜻이다.
최종 지시서나 렌더 영상의 품질이 개선됐다는 뜻은 아니다.

## 현재 문제

기존 경로는 `series_split`, `too_many_spoken_numbers` 같은 경고를 저장하고도 한 편의
영상으로 계속 진행할 수 있었다. 반대로 과거 `series_split_required`를 곧바로 승인 차단으로
올렸을 때에는 독립 주장이 아닌 여러 `main_result`까지 세어 정상 초안 10건을 모두 막았다.

따라서 Phase 8은 다음 원칙을 사용한다.

- 경고만 남기고 계속 진행하지 않는다.
- `series_split`은 분할 행동이 기본이며, 사유가 있는 명시적 override만 허용한다.
- 숫자 과다는 override할 수 없고 대본 재생성을 요구한다.
- Source Adequacy의 길이·content mode 상한을 다시 적용한다.
- 근거 있는 mechanism reasoning ID가 없으면 후속 Visual Planner가 mechanism 장면을
  만들지 못하도록 한다.
- 의미 QA를 통과하지 못한 대본에서는 복잡도 행동을 만들지 않는다.

## 입력과 출력

입력:

- 기존 normalized `content_plan`
- `spoken-narration-v1`
- `semantic-fidelity-v1`
- `narrative-plan-v1`
- `explanation-ir-v1`
- `prerequisite-resolution-v1`
- `evidence-pack-v1`
- 선택적 `series_split` override

`content_plan`과 override는 현재 Shadow 호출자가 전달하는 입력이다. Phase 13 Production
wiring 전에는 운영자 인증이나 저장 이벤트와 연결돼 있지 않다. Production에서는 브라우저가
보낸 임의 JSON을 직접 받지 않고, 정본 draft에 저장된 normalized plan과 인증된 운영자
override 이벤트만 읽어야 한다.

출력 상태:

- `READY`: 필요한 행동이 없고 Phase 9가 제약을 소비할 수 있음
- `ACTION_REQUIRED`: 분할·대본 재생성·길이 축소 중 하나 이상이 필요함
- `BLOCKED_UPSTREAM`: Phase 7 의미 QA가 통과하지 않아 Phase 8을 평가하지 않음

## 행동 규칙

| 신호 | Phase 8 행동 |
|---|---|
| `selected_mode=series_split` | `SPLIT_SERIES`; `approved=true`와 비어 있지 않은 사유가 있는 override만 해제 |
| 전체 발화 숫자 `MAX_SPOKEN_NUMBERS` 초과 | `REGENERATE_NARRATION`; override 불가 |
| Source mode 또는 목표 길이가 Source Adequacy 상한 초과 | `DOWNGRADE_LENGTH` |
| 의미 QA 미통과 | `BLOCKED_UPSTREAM`; 복잡도 행동과 Visual 제약 소비 금지 |
| mechanism reasoning ID 없음 | `mechanism_visual_allowed=false` |

Gate는 저장된 `gate_status`, 행동 목록, 제약, override 결과를 신뢰하지 않는다.
`validate()`가 같은 입력으로 정본 결과를 다시 계산하고 다른 저장 결과를
`gate_not_canonical`로 거절한다. Evidence Pack과 IR의 `source_mode`를 함께 위조해도
Source Adequacy 정책표와 다르면 거절한다.

예외 하나(2026-10-04, Phase 11 리뷰 후속): 출처 메타가 없는 레거시 Fact Sheet 는 Phase 2 가
모드를 추정하지 않고 `source_mode=""` 로 둔다(Phase 2 §8). 이때 깊이는 `none` 이므로 정책도 가장
보수적인 `none` 행이 적용된다 — 이 조합만 불일치로 보지 않는다. 다른 깊이에서 빈 모드는 계속
거절한다. 이 소스 검사는 `source_errors(pack, ir)` 로 분리돼 있어 Shadow 실행이 유료 모델 호출
전에 먼저 돌린다.

## Gold Set Shadow 결과

Phase 7에서 안전하게 차단·거절된 여섯 사례는 Phase 8에서도 전부
`BLOCKED_UPSTREAM`이며, 안전하지 않은 대본으로부터 분할·시각화 행동을 만들지 않는다.

- Heel strike: `BLOCKED_UPSTREAM`
- Retinotopic remapping: `BLOCKED_UPSTREAM`
- Personality GWAS: Phase 7 `REJECTED` → Phase 8 `BLOCKED_UPSTREAM`
- Samsung report: `BLOCKED_UPSTREAM`
- NH Mid Cycle: `BLOCKED_UPSTREAM`; 저장된 `series_split` 신호도 평가하지 않음
- Shipbuilding report: `BLOCKED_UPSTREAM`

별도 합성 회귀에서는 과거 `content_mode_warning_not_enforced` 사례에
`SPLIT_SERIES → ACTION_REQUIRED`가 생성되는지 확인한다. 이 비교는 계약 행동만 증명한다.
기존 지시서보다 좋은 지시서나 영상이 생성됐다는 비율은 계산하지 않는다.

## 변경 경계

- `engine/content_complexity_gate.py`: 행동·제약 정본과 validation
- `engine/content_complexity_shadow_compare.py`: Gold Set 계약 비교
- `tests/test_content_complexity_gate.py`: Paper/Report, 우회, 위조, Gold 회귀

DB migration과 Production wiring은 없다. 기존 `engine/content_mode.py`의 Production
승인 정책도 이번 Phase에서는 바꾸지 않는다. Phase 9는 `READY` 결과만 받고
`mechanism_reasoning_ids`, Source 상한, 행동 상태를 반드시 소비해야 한다.

## 검증 경계

확인하는 것:

- 경고가 실제 구조화 행동으로 변환되는가
- `series_split` override에 명시적 사유가 필요한가
- 숫자 과다를 override로 우회할 수 없는가
- Source 정책과 저장 artifact를 함께 위조해도 거절되는가
- mechanism 근거가 없을 때 Visual Planner 제약이 생기는가
- unsafe upstream에서 Phase 8 행동이 생기지 않는가

미검증:

- Production 운영자 override의 인증·감사 로그
- 실제 모델 대본 재생성 성공률과 비용
- 실제 Source fetch 또는 길이 축소 실행
- 기존 지시서와 V2 지시서 품질 비교
- 렌더 영상과 publish/A-B 결과

## Rollback

Phase 8 신규 모듈 두 개, 테스트, 이 문서를 제거하면 된다. Production wiring, DB 저장,
migration이 없으므로 운영 데이터 rollback은 필요 없다.

## Fable Review

구현이 틀렸다고 가정하고 evidence trace, 우회 가능성, unsafe upstream 격리를 다시
검토했다.

- `BLOCKED_UPSTREAM` 결과가 mechanism ID를 노출하던 문제를 발견해, 해당 상태에서는
  `mechanism_visual_allowed=false`와 빈 ID 목록만 반환하도록 수정했다.
- Shadow comparator가 contract version만 확인하고 잘못된 status/action shape를 받을 수
  있던 문제를 발견해, 허용 상태와 action 필수 필드를 검증하도록 수정했다.
- 잘못된 domain이 `KeyError`를 낸다는 가설은 재현되지 않았다. 기존 Evidence Pack
  validation이 구조화된 `evidence_pack_invalid:domain_invalid` 오류를 반환함을 확인했다.

## 로컬 검증 결과

- Phase 8 targeted: `12 passed`
- Phase 2~8 adjacent regression: `162 passed`
- 전체 Python: `2656 passed, 22 skipped`
- Web Node: `141 passed, 0 failed` (기존 module type 경고는 남아 있음)
- TypeScript `tsc --noEmit`: 통과
- ESLint: 오류·경고 없음 (Next.js lint deprecation 안내만 출력)
- Next.js production build: 통과, static page 39개 생성
- staged diff whitespace 검사: 커밋 직전 수행

첫 lint 실행은 외부 worktree의 `.next/cache/eslint` 쓰기 권한 문제로 실패했고,
동일 명령을 권한이 있는 환경에서 다시 실행해 통과했다. 이는 lint 규칙 실패가 아니다.

## 다음 단계

Phase 9에서 기존 Beat/Resolved Visual Plan/Stage/Mutation 구조를 재사용하고 다음 trace를
끝까지 연결한다.

`Explanation step → claim/evidence → reasoning_id → stage_id → mutation`

Phase 9는 `ACTION_REQUIRED` 또는 `BLOCKED_UPSTREAM` Gate를 받으면 Visual Plan을 만들지
않아야 하며, `mechanism_visual_allowed=false`일 때 mechanism Stage를 생성해서는 안 된다.
