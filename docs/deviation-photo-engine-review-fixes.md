# 편차 기록 — 실사형 지시서·렌더 엔진 리뷰 반영 (2026-08-29)

입력: 외부 리뷰(`docs/리뷰요청_지시서렌더엔진_v1.md` 에 대한 회신). 우선순위 1~7.

---

## 1. 역할별 모델이 Batch 에서 무시되던 것

**무엇이 문제였나.** 실시간 생성은 `visual_role=MECHANISM` 이면 `gemini-3-pro-image` 를 쓰는데,
Batch 제출은 전 컷을 `config.IMAGE_MODEL`(flash) 하나로 보냈다. **기본 모드가 batch** 이므로
(`IMAGE_GENERATION_MODE=batch`) 3D 도해는 사실상 항상 flash 로 생성돼 캐시에 굳었다.
모델 상향(8/28)이 화면에 도달한 적이 없다는 뜻이다.

**고친 방식.** Batch 엔드포인트가 `{model}:batchGenerateContent` 로 모델별로 갈리므로,
컷을 **실제 모델별로 묶어 잡을 나눠 제출**한다(`image.group_batch_requests`).
`submit_batch(model=...)` 는 기본값 없는 필수 인자다 — 기본값을 두면 같은 버그가 조용히 돌아온다.

## 2. 생성 사양의 단일 출처 (`engine/generation_spec.py`)

여섯 소비자가 각자 판단하던 것을 하나로 모았다.

| 소비자 | 이전 | 이후 |
|---|---|---|
| 이미지 제공자 호출 | 역할별 모델 ✅ | `image_spec()` |
| Batch 제출 | `config.IMAGE_MODEL` ❌ | `image_spec(generation_mode="batch")` |
| 예상 비용(`compute_cost_plan`) | 전 컷 한 모델 ❌ | 컷마다 실제 모델 |
| 비용 원장(성공·실패·폴백) | `config.IMAGE_MODEL` ❌ | `spec.model` / `spec.unit_type` |
| 이미지 캐시 키 | 모델·역할 없음 ❌ | `spec.cache_fields()` |
| 예산 가드 | 위 값 신뢰 | 같은 값 |

`ImageSpec` 필드: provider · model · visual_role · generation_mode · unit_type · unit_price_usd ·
aspect_ratio · output_resolution · style_version.
`VideoSpec` 은 여기에 clip_sec · resolution · **start_asset_hash** 를 더한다.

`IMAGE_OUTPUT_RESOLUTION="provider_default"` 는 **우리가 해상도를 지정하지 않는다는 사실**을
값으로 적어 둔 것이다(단가표가 "기본값 1K/2K" 가정 위에 서 있다는 미검증 항목을 캐시·원장에 남긴다).

## 3. 캐시 키를 산출 결정 요인과 맞춤

- `assemble.content_hash` — 이미지용. 생성 사양이 들어간다.
- `assemble.clip_content_hash` — **신설**. 클립은 이미지와 다른 함수를 쓴다. Veo 모델·요청 티어·
  **시작 에셋 논리 해시**가 들어간다.
- I2V 연쇄: `chain["clip_key"]` 를 다음 컷의 `start_asset_key` 로 넘긴다. 앞 컷이 바뀌면 뒤 컷의
  키가 따라 바뀐다 — 예전에는 앞이 바뀌어도 뒤가 옛 클립을 그대로 썼다.
- **언어는 여전히 어느 키에도 없다**(KO/EN 에셋·클립 공유 유지).

**⚠ 의도적 캐시 무효화.** 이 변경으로 **기존 `render_assets` 캐시는 전량 미스**가 된다.
호환을 택하지 않은 이유: 조건부로 키를 넣으면 "어떤 컷은 모델이 키에 있고 어떤 컷은 없는"
상태가 되어 지금 고친 버그를 다시 만든다. 이미 끝난 영상은 mp4 로 남아 깨지지 않고,
**재렌더할 때만** 다시 생성된다(그때 이미지 재생성 비용이 든다).

## 4·5. 실사형 화면 계약의 결정론적 게이트 (`engine/photo_contract.py`)

차단: 빈 훅 · 역할 누락 · 차트/축/라벨/화면숫자 요구 · 숫자 나레이션↔오버레이 누락 ·
컷 수 부족 · 도해 부재 · **도해 구조 누락** · 장식적 도해(근거 2개 겹칠 때).
경고: 역할 비율 · 영상 컷 수 · 영상 컷 비연속 · 과길이 컷 · 장식 의심(근거 1개).

**MECHANISM 을 enum 에서 구조로.** `mechanism{subject, components[2+], relationship,
initial_state, transformation, final_state, highlighted_element, claim_ids}` 를 컷 필드로 받고,
LLM 은 구조를 먼저 채운 뒤 `visual_prompt` 를 파생시킨다. 구조가 없으면 승인이 막힌다.

사유 코드는 Python 정본, 웹은 미러. **웹은 편집으로 깨질 수 있는 항목만 재계산**하고
판단이 섞이는 항목은 재계산하지 않는다(오탐이 두 배가 된다). 이 분리를 CI 가 양방향으로 고정한다.

## 6. 결정론적 컷 골격 (`engine/cut_skeleton.py`)

컷 수를 **대본 scenes 개수에서 떼어냈다.** 문장 경계와 목표 길이로 코드가 칸을 만들고, LLM 은
칸을 시각 표현으로 채운다. 긴 문장은 쉼표·연결어미 경계에서 쪼개고, 자를 곳이 없으면 그대로 둔다
(글자수로 억지로 자르면 말이 끊긴다). 지시서 단계는 **제거하지 않았다** — typed manifest 로 유지한다.

## 7. 제한적 재생성

계약 위반 → 구조화된 처방을 되먹여 **1회만** 재생성 → **같은 코드 검사를 다시** 실행.
두 번째도 위반이면 자동 승인 금지(사람 검수). 되먹임이 새로 만든 위반은 `new_violations` 로 남는다.
모델의 "고쳤다" 선언은 신뢰하지 않는다.

## 8. Edge → 큐 전용

Edge `generate-directive` 는 이제 **요청 검증 + 큐 적재만** 한다(1,254줄 → 106줄).
프롬프트·enum·정규화의 TypeScript 복제가 사라졌다. 생성은 Python 워커가 독점한다.

요청 행에 `lease_expires_at · heartbeat_at · attempt_count · last_error · worker_id`(0043).
임대 만료 → 자동 재큐, 시도 상한 초과 → error 확정. `draft.yml` 에 지시서 워커 스텝을 추가했다.

## 9. T2V

**하지 않았다**(리뷰 지시대로). 기존 I2V 경로는 그대로다. 같은 지시서로 나중에 비교할 수 있게
`VideoSpec.start_asset_hash` 가 "시작 이미지 없음"(빈 문자열)도 표현할 수 있게 열어 뒀다.

---

## 되돌리는 법

```
IMAGE_MODEL_MECHANISM=gemini-2.5-flash-image   # 역할 상향 취소(캐시도 함께 갈린다)
PROMPT_CONTRACT_VERSION=<옛 값>                 # 캐시 키를 옛 계약으로 되돌린다
DIRECTIVE_CONTRACT_RETRY=false                  # 재생성 끄기
CUT_SKELETON_ENABLED=false                      # 컷 골격 끄기
```
게이트 자체를 끄는 스위치는 **두지 않았다.** 끌 수 있게 하면 오탐이 났을 때 끄는 쪽이 빨라지고,
그러면 게이트가 있으나 마나가 된다. 임계값(`PHOTO_*`)으로 조인다.

## 미검증

- 라이브 Gemini/Veo 호출 · 실제 과금 · 실제 영상 품질 — **확인하지 않았다.**
- 마이그레이션 0043 미적용 · 엣지 함수 미배포.
- 배포 순서 주의: **0043 적용 → 워커 배포 → 엣지 배포.** 엣지를 먼저 배포하면 큐에만 쌓이고
  아무도 처리하지 않는다(워커가 없으면 지시서가 생성되지 않는다).
