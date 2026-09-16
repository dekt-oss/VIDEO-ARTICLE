# WORK ORDER — Paper Visual Explanation Engine v3

## 목표

`dekt-oss/VIDEO-ARTICLE`의 현재 논문 영상 파이프라인을 기반으로 **Paper Visual Explanation Engine v3**를 구현한다.

이번 작업의 핵심은 근거 시스템 전체를 다시 만드는 것이 아니다.

**논문의 설명 영상을 독립적인 이미지 컷의 나열에서, 동일한 3D 세계와 지속되는 개체가 단계적으로 변화하는 Visual Mechanism Sequence 중심 구조로 전환한다.**

자동 merge하지 않는다.

---

# 1. 시작 전 Source of Truth 복구

작업 시작 즉시 GitHub/Repository를 Source of Truth로 현재 상태부터 다시 확인한다.

반드시 확인:

- 현재 branch / HEAD
- `AGENTS.md` 존재 여부
- `CLAUDE.md`
- README
- 관련 workflow/CI
- 최신 논문 설명엔진 명세/ADR/deviation 문서
- `engine/directive.py`
- `engine/photo_contract.py`
- `engine/cut_skeleton.py`
- `engine/render.py`
- `engine/render_manifest.py`
- `engine/render_qa.py`
- `engine/generation_spec.py`
- `engine/providers/image.py`
- `engine/providers/video.py`
- `engine/factsheet.py`
- `engine/paper_source.py`
- `engine/selfcheck.py`
- `engine/visual_contract.py`
- 기존 board/component/manim 계층
- 관련 tests

문서에 적혀 있다는 이유만으로 구현됐다고 가정하지 않는다.

현재 코드·runtime path·consumer를 확인하고 **current state와 target state를 분리해 보고한 뒤 구현한다.**

---

# 2. 절대 요구사항

## 2.1 Cut을 삭제하지 않는다

Cut은 계속 다음 용도로 필요하다.

- narration
- subtitle timing
- duration
- rendering timeline

하지만 **Cut을 visual world 생성 단위로 사용하지 않는다.**

상위 계층:

`Visual Sequence`

하위 계층:

`Stage / Cut`

로 확장한다.

---

## 2.2 같은 사람·물체의 재등장을 중복으로 판단하지 않는다

다음은 정상이다.

- 첫 장면 사람이 마지막에 다시 등장
- 동일 실험 참가자가 다음 단계에서 행동 변화
- 같은 토큰이 다른 사람에게 이동
- 같은 테이블에서 다른 실험 상태
- 동일 장치 내부를 다른 단계에서 재노출

차단 대상은:

> 같은 세계/인물/구도/상태가 다시 나오면서 새 정보나 상태 변화가 없는 경우

이다.

---

# 3. Shared Visual Sequence Contract

현재 코드 구조를 확인한 뒤 가장 작은 변경으로 공통 Sequence schema를 도입한다.

새 모듈명은 현 architecture를 보고 최종 결정하되 개념적으로 다음 책임을 분리한다.

- visual sequence model/normalization
- visual sequence contract
- visual router
- sequence metrics

예상 구조 예:

```text
engine/
  visual_sequence.py
  visual_sequence_contract.py
  visual_router.py
```

단, 이미 같은 책임을 수행하는 모듈이 있다면 새 파일을 만들지 말고 기존 모듈을 확장한다.

---

# 4. 최소 Sequence Schema

지시서에 최소 다음 개념을 표현할 수 있어야 한다.

```json
{
  "sequence_id": "SEQ_EXPERIMENT",
  "sequence_role": "MECHANISM_SEQUENCE",
  "world_id": "WORLD_TRUST_GAME",

  "visual_world": {
    "style": "premium_technical_3d",
    "geometry": "clean_realistic_3d",
    "lighting": "soft_top_left",
    "camera_base": "35deg_isometric",
    "identity_lock": true
  },

  "persistent_entities": [
    {
      "entity_id": "PARTICIPANT_A",
      "entity_type": "person",
      "continuity": "locked"
    },
    {
      "entity_id": "TOKEN_SET",
      "entity_type": "object",
      "continuity": "locked"
    }
  ],

  "stages": [
    {
      "stage_id": "S1",
      "cut_refs": [3],
      "operation": "SPLIT",
      "continuity_from": null,
      "state_before": {},
      "state_after": {},
      "observable_change": "participants split into two groups",
      "camera_operation": "DOLLY_IN",
      "claim_ids": []
    }
  ]
}
```

필드명을 그대로 복사하라는 뜻은 아니다.

현재 스키마와 migration/API 소비자를 확인한 뒤 backward-compatible 형태로 설계한다.

---

# 5. Visual Operation enum

최소 다음을 공통 enum으로 지원한다.

### Object / Geometry

- REVEAL
- CUTAWAY
- EXPLODE
- ASSEMBLE
- SPLIT
- MERGE
- TRANSFER
- FLOW
- ACCUMULATE
- TRANSFORM
- ISOLATE
- ZOOM_INTO

### Camera

- ORBIT
- DOLLY_IN
- DOLLY_OUT
- TRACK
- TOP_DOWN
- SECTION_DIVE
- FOLLOW_OBJECT

자유 텍스트만으로 operation을 표현하지 않는다.

---

# 6. Paper Explanation Planner

Paper용 Planner는 논문의 근거를 **시각적으로 설명할 수 있는 explanation beat**로 변환한다.

최소 분류:

- QUESTION
- SCOPE
- EXPERIMENT_SETUP
- INTERVENTION
- MEASUREMENT
- MECHANISM
- RESULT
- COMPARISON
- LIMITATION
- CONCLUSION

중요:

문장 경계와 explanation beat를 동일시하지 않는다.

한 문장이:

> 약물을 투여하고 신뢰 게임을 진행했다.

처럼 두 개 의미를 포함하면 시각적으로는

1. intervention
2. measurement

로 나눌 수 있어야 한다.

---

# 7. Visual Router

각 beat에 무조건 3D를 붙이지 않는다.

## `3D_MECHANISM_SEQUENCE`

다음에 우선:

- 구조
- 이동
- 물리적 관계
- 단계
- 실험 흐름
- 원문에 근거한 mechanism

## `CODE_VIZ`

다음에 우선:

- 정확한 %
- sample size
- 실험군 비교
- 통계 결과
- 정확한 정량 변화

## `REALITY`

다음에 우선:

- 실제 연구 대상
- 실제 장치/현장 자체가 설명 가치가 있는 경우

AI reconstruction이라면 실제 촬영물처럼 오해되지 않도록 내부 메타데이터를 구분한다.

## `OVERLAY`

- 정확한 숫자
- scope
- source
- caveat

---

# 8. Visual World / Persistent Entity

Sequence마다 canonical world를 만든다.

Stage가 넘어가도 가능한 한 다음을 유지한다.

- person identity
- object identity
- material
- spatial layout
- camera axis
- lighting
- scale

Renderer가 reference image 또는 이전 stage 결과를 다음 stage 생성에 사용할 수 있는 구조를 마련한다.

`new_asset`과 `reuse`만으로 표현하지 않는다.

최소 의미 구분:

- NEW_WORLD
- CONTINUE_WORLD
- MUTATE_STATE
- CAMERA_REVEAL
- RETURN_WORLD
- REFERENCE_CONDITIONED_NEW_STATE

---

# 9. Sequence-aware Rendering

현재 이미지/영상 provider의 capability를 먼저 확인한다.

가능한 현재 기술 범위에서:

1. Sequence canonical frame 생성
2. world/entity reference 보존
3. 다음 Stage의 target state 생성
4. I2V가 적합하면 Stage A → B transition 생성
5. B의 final state를 다음 Stage 입력으로 사용
6. Sequence 종료 시에만 필요하면 새로운 world로 전환

완벽한 캐릭터 identity가 provider 한계로 보장되지 않는다면 그 사실을 숨기지 말고 `degraded continuity`로 기록한다.

---

# 10. Pixel duplicate 검사는 보조수단

기존 또는 신규 pixel delta/hash 검사는 유지할 수 있다.

그러나 다음을 절대 동일시하지 않는다.

`pixel difference = semantic progression`

다음 상황은 pixel 변화가 커도 실패다.

- crop만 변경
- tone만 변경
- overlay만 변경
- 동일 포즈/동일 의미

Sequence Contract는 **구조화된 state transition**을 별도로 검사한다.

---

# 11. Sequence Contract / Gate

최소 다음을 코드로 판정한다.

### VSEQ-1 — Sequence completeness

MECHANISM_SEQUENCE라면 의미 있는 Stage가 2개 이상 있어야 한다.

### VSEQ-2 — Progression

연속 Stage는:

`state_before != state_after`

이고 `observable_change`가 존재해야 한다.

### VSEQ-3 — Continuity

`CONTINUE_WORLD / MUTATE_STATE`라면 이전 world/entity 참조가 실제 존재해야 한다.

dangling ref 금지.

### VSEQ-4 — Static repeat

같은 world + 같은 state + 동일 operation 없이 반복되는 Stage는 경고 또는 차단한다.

### VSEQ-5 — Narration ↔ Visual alignment

Stage가 설명하는 claim/evidence beat가 해당 Cut narration과 일치해야 한다.

### VSEQ-6 — Visual factual claim

화면에 추가되는 구조·경로·생리기전 등도 factual claim으로 간주한다.

근거 없는 biological mechanism을 visual prompt가 새로 만들지 못하게 한다.

### VSEQ-7 — Quantitative integrity

정확한 15%를 동전 10개→11~12개 같은 모호한 개수 은유로 대체하지 않는다.

정량값은 code viz/overlay로 분리한다.

---

# 12. Abstract-only 정책 유지

Visual Engine이 좋아진다고 abstract-only 자료에서 더 많은 기전을 상상하면 안 된다.

원문/abstract에 없는:

- 정확한 실험 procedure
- 장비
- 생리학적 전달 경로
- 특정 brain region
- double-blind 여부
- placebo design
- 세부 protocol

등을 3D로 시각화하지 않는다.

“설명할 근거가 부족하다”면 더 일반적인 실험 구조 또는 result visualization으로 router가 후퇴해야 한다.

---

# 13. Golden Sample — 현재 옥시토신 논문

v3 검증용 첫 golden sample로 현재 리뷰한 논문을 사용한다.

목표 영상 구조 예:

## Sequence A — 질문 / 현실

동일 인물과 trust situation.

현실 장면에서 실험 world로 자연스럽게 진입.

## Sequence B — 실험

- 대상 집단
- 그룹 분리
- treatment/comparison
- trust game
- 행동 측정

동일 공간·동일 participant·동일 token system 유지.

원문에 없는 코→뇌 분자 이동은 금지.

## Sequence C — 결과

- +15% result
- prior study enters
- combined analysis
- +16.9% update

15→16.9가 동일 result system의 state progression으로 보여야 한다.

## Sequence D — scope / conclusion

“다른 사람에게 효과가 없다”가 아니라 연구가 확인한 범위를 정확히 보여준다.

필요하면 첫 인물이 새로운 상태로 다시 등장할 수 있다.

이는 중복이 아니라 narrative return이다.

---

# 14. KPI

기존 지표를 모두 삭제할 필요는 없지만 v3 검증에는 다음을 추가한다.

- sequence_count
- avg_stages_per_sequence
- world_reset_rate
- persistent_entity_ratio
- transformation_density
- static_repeat_rate
- mechanism_sequence_coverage
- camera_continuity_rate
- visual_claim_ground_rate

정량 KPI가 실제 영상 품질을 완전히 대신한다고 주장하지 않는다.

최종 Golden QA에는 사람이 보는 visual review가 필요하다.

---

# 15. 테스트

최소 다음 테스트를 추가한다.

### Unit

- Sequence schema normalization
- invalid operation
- dangling continuity ref
- missing entity
- state change 없음
- valid recurrence
- invalid static recurrence
- world reset
- visual router
- claim linkage

### Regression

기존:

- directive
- photo_contract
- shared_assets
- cut_skeleton
- render
- manifest
- QA
- prompt/schema parity

전부 깨지지 않아야 한다.

### Golden

옥시토신 샘플로:

- v2 directive
- v3 directive
- sequence plan
- 가능하면 rendered contact sheet/video

를 비교한다.

단순히 `7 MECHANISM → 8 MECHANISM` 같은 숫자로 성공판정하지 않는다.

---

# 16. 실제 검증

가능하다면 provider를 실제 호출해 적어도 한 번의 end-to-end sample을 만든다.

검증 항목:

- 동일 world 유지
- 인물/개체 continuity
- stage transition
- I2V 연결
- visual/narration alignment
- static repetition 감소
- 비용

Provider 장애로 live render를 못 했다면:

`미검증`

이라고 명확히 보고한다.

Unit test 통과를 실제 영상 품질 검증으로 간주하지 않는다.

---

# 17. Non-goal

이번 P0/P1에서 하지 않는다.

- Blender 전체 도입
- 완전 procedural human animation
- 기존 Fact Sheet 전체 재설계
- UI 전면 재설계
- 모든 기존 영상 버전 교체
- DB 대규모 migration

Blender/procedural 3D는 v3 sequence architecture가 실제로 효과가 있다는 것을 확인한 뒤 별도 ADR/Issue로 검토한다.

---

# 18. 완료 조건

다음이 모두 충족돼야 v3 Paper 작업 완료로 본다.

1. Visual Sequence가 실제 directive/runtime schema에 존재
2. Stage별 state progression이 코드로 검증
3. Persistent Entity/World continuity 표현 가능
4. 동일 인물의 의미 있는 재등장이 허용
5. 의미 없는 static recurrence는 탐지
6. Visual Router가 3D/code/reality/overlay를 구분
7. 논문 visual factual claim이 evidence를 벗어나지 않음
8. 옥시토신 golden sample에서 v3 sequence directive 생성
9. 기존 regression 통과
10. 가능한 runtime render 검증
11. 실제 검증하지 못한 항목 명시

---

# 19. 작업 종료 절차

구현 후:

- test
- lint
- typecheck
- build
- 관련 CI
- 가능한 runtime render

를 실행한다.

그 후 반드시:

> “내 구현이 틀렸다고 가정”

하고 adversarial self-review를 수행한다.

특히 확인:

- 새로운 schema가 실제 renderer에서 소비되는가?
- JSON에만 있고 무시되는 dead field는 없는가?
- prompt에만 적고 gate가 없는 규칙은 없는가?
- continuity가 단순 파일복사로 퇴행하지 않았는가?
- 동일 인물을 과도하게 금지하지 않는가?
- unsupported mechanism이 3D로 더 그럴듯하게 포장되지는 않는가?

별도 branch에서 commit/push 후 Draft PR을 만든다.

자동 merge하지 않는다.

PR 본문에는 반드시:

- current state
- target state
- 주요 diff
- 테스트 결과
- runtime 검증
- golden sample 비교
- 미검증 사항
- 후속 P2

를 기록한다.