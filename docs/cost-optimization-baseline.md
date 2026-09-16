# 숏츠 렌더 비용 최적화 — Baseline & 경로 판정 (PC0)

> 기준 명세: `개발명세서(최종 v3) — 숏츠 렌더 비용 최적화` (2026-07-16).
> 이 문서는 **수정 전 현황 스냅샷**이자 명세 §4(PC0)의 **경량 vs 무거운 경로 판정** 기록이다.
> 실제 코드를 읽고 내린 판정이며, 이후 PC1~PC4 착수의 게이트다.

---

## 0. 결론 (두괄식)

- **경로 = 경량(lightweight).** 렌더 워커는 `workflow_dispatch` + 15분 안전망 cron 으로 도는
  **단일 배치 프로세스**이고, `concurrency: render-worker` 로 **직렬화**(병렬 워커 없음)되며 **웹훅·상시
  서버·외부 이벤트 트리거가 없다**. 명세 §4.2 세 질문 모두 "예" → 경량 경로 확정.
- **작업 D(언어 독립 공유 에셋)는 사실상 이미 구현됨.** 이미지·Veo 클립은 `content_hash(cut, header)`
  키(언어 무관)로 캐시되어 KO 렌더가 만든 에셋을 EN 렌더가 재사용한다. → D 는 **"구조 검증 + 캐시키
  보강 + 원장 분리"로 축소**(명세 §15 리스크 2 경로).
- **가장 큰 실질 갭 = 작업 C(비용 원장).** 현재 비용은 잡당 누적 `float` 한 개(`render_jobs.cost_estimate`)
  뿐이고 **호출별 원장·예상/실제 구분·단가 스냅샷이 없다.** → 절감이 진짜였는지 **측정 자체가 불가능**한
  상태. C 가 최우선 실작업.
- **작업 A(이미지 Batch)** 미구현(현재 Realtime 단건). **작업 B(영상 캡)** 부분 구현(단일 예산 캡만,
  media_policy enum·이중 캡·Preflight 없음).

---

## 1. 현재 파이프라인 구조 (읽은 코드 기준)

| 관심사 | 현재 구현 | 파일 |
|---|---|---|
| 렌더 오케스트레이션 | `poll_once → process_job(job, directive, lang)` 큐 소비 | `engine/render.py` |
| 이미지 생성 | Gemini nano banana **Realtime 단건**, 레이트리밋 6s | `engine/providers/image.py` |
| 영상 생성 | Veo 3.1 **Lite** I2V(스틸 첫 프레임→모션), 비동기 폴링 | `engine/providers/video.py` |
| 애니 클립 | Manim 파라미터 템플릿(무료·결정론) | `engine/manim_templates.py` |
| TTS | Edge TTS(무료), 언어별 보이스 | `engine/providers/tts.py` |
| 에셋 캐시 | `render_assets(directive_id, cut_no, asset_type)` + `content_hash` | `supabase/migrations/0009_*.sql` |
| 비용 | 잡당 누적 `float` → `render_jobs.cost_estimate` **1행** | `engine/render.py:294` |

### 실행 형태 (경로 판정 근거 — §4.2)
1. **단일 프로세스, 한 번 실행:** `.github/workflows/render.yml` 이 `workflow_dispatch`(대시보드 버튼) +
   `schedule: */15`(안전망)으로 `python -m engine.render`(=`poll_once`) 를 돌린다. 상시 워커 아님.
2. **KO·EN 순차:** 언어별로 **별도 render_job** 이 큐에 쌓이고, 워커는 `poll_once` 루프에서 **직렬 처리**한다.
   코드상 병렬 실행 경로 없음.
3. **상시 서버/웹훅 없음:** `concurrency: group: render-worker, cancel-in-progress: false` 로 워커가
   직렬화된다. 큐 테이블(`render_jobs`)은 있으나 소비는 배치 폴링이고 웹훅·락·상시 워커가 없다.

→ **셋 다 "예" → 순차 배치 스크립트 → 경량 경로.** (명세 §4.2 표의 좌측을 채택.)

---

## 2. 경량 경로 채택 결과 (무거운 장치는 도입 안 함)

| 항목 | 채택(경량) | 도입 안 함(무거운) |
|---|---|---|
| Batch 완료 감지 | **폴링 루프** | ~~Webhook + 보정 Poller~~ |
| 중복/동시성 | `unique(...)` + READY 재사용 + `batch_payload_hash` 대조 | ~~advisory lock · 재시작 복구~~ |
| 가격 이력 | **원장 행 단가 스냅샷 컬럼**(`unit_price_usd`, `price_verified_at`) | ~~`pricing_versions` 테이블~~ |
| 상태 | **경량 6단계**(기존 render_jobs 상태 흐름 유지) | ~~12단계 확장~~ |

기존 `render_jobs.status`(queued→assets→tts→assembling→done/failed)가 이미 경량 6단계에 대응하므로
새 상태머신을 만들지 않는다.

---

## 3. 작업별 현황 & 재범위

### D — 언어 독립 공유 에셋 → **거의 완료 (검증·보강으로 축소)**
- `content_hash` payload = `{version_type, visual_type, scene_kind, visual_prompt, global_style, effects}`
  → **narration/subtitle/locale 미포함**. `test_render_cache.py` 가 "나레이션 변경이 해시를 안 바꾼다"를 이미 검증.
- `_gen_still`/`_gen_veo_clip` 은 `directive_id + cut_no + asset_type` 로 캐시 조회 → **locale 을 키에 넣지 않음.**
- **남은 보강:** (a) 캐시키에 `model_id/resolution/visual_version` 미포함(§5.6) — 현재 단일 모델이라 실해는
  없으나 모델 교체 시 캐시 오염 위험 → 보강 대상. (b) KO→EN 재렌더 시 유료 API **0회** 를 못 박는 통합
  테스트 부재(§5.7 DoD) → 추가. (c) burn-in 금지 프롬프트 제약(§5.3)은 이미지 프롬프트에 `no on-screen
  text` 만 있고 §5.3 전체 목록(no numbers/labels/watermarks 등)보다 약함 → 강화.
  - ⚠️ **Manim 코드 클립(kinetic_typography/data_viz)은 언어별 텍스트를 화면에 굽는다** → 언어별 재렌더.
    이는 명세 §5.3 취지와 상충하나 Manim 은 무료·결정론적이라 재렌더 비용이 무시할 만함(기존 DV11 결정).
    값비싼 이미지(comic/broll)·Veo 클립만 진짜 언어 공유. 이 구분은 유지한다.

### C — 비용 원장 → **완료(PC2)**
- `generation_attempts`(호출 1건=1행, `engine/cost.py` + `0016_*.sql`) + `unit_price_usd`/`price_verified_at`
  스냅샷 + 공유비는 생성 1회만 기록(§6.3 중복 계상 방지). `Decimal` 비용.

### A — 이미지 Batch → **완료(PC3) + 라이브 배선(사용자 승인, 2026-07-16)**
- `engine/providers/image.py`(`build_batch_requests`/`submit_batch`/`poll_batch`/`fetch_batch_results`)
  + `engine/image_batch.py`(제출/폴링 오케스트레이션) + `0017_image_batch_jobs.sql`.
- 설계: render.py 의 Realtime 경로는 **무수정**. Batch 는 지시서 승인 후 미캐시 컷을 미리 채우는
  "pre-warm" 레이어 — `_gen_still` 이 이미 캐시 우선이라 Batch 가 먼저 도착하면 자동으로 반값(원장에
  `generation_mode=batch`/`unit_type=image_batch` 기록), 늦으면 기존 Realtime 폴백이 그대로 동작
  (회귀 없음).
- **`IMAGE_GENERATION_MODE` 기본값 `batch`로 전환(사용자 명시 승인) + `render.yml`에 배선 완료.**
  render 워커 cron/dispatch 가 돌 때마다 `python -m engine.image_batch` 가 먼저 실행돼 (1) 최근 승인된
  지시서 중 미캐시 컷을 Batch 로 제출하고 (2) 대기 중인 Batch 잡을 폴링해 완료분을 캐시에 적재한다.
  자동 제출(`submit_for_approved`)은 `IMAGE_GENERATION_MODE=="batch"` **AND**
  `IMAGE_PROVIDER=="gemini"` 일 때만 동작(이중 게이트) — CLI 로 특정 지시서를 지정하는
  `submit_for_directive` 는 검증용 강제 실행이라 이 게이트를 안 탄다.
- ⚠️ **여전히 라이브 키로 실제 검증되지 않음** — 이미지 모델(`gemini-2.5-flash-image`)의 Batch 지원
  여부가 공식 문서에 명시돼 있지 않다(최신 예시는 `gemini-3-pro-image-preview` 등). 계약이 틀리면
  `poll_batch`/`fetch_batch_results` 가 예외를 던지고, `image_batch.py` 는 그 예외를 컷/잡 단위로
  삼켜 로그만 남긴다 — **render.py 의 렌더 자체는 막히지 않는다**(그 컷은 캐시가 안 채워진 채로 남고
  render.py 가 평소처럼 Realtime 로 생성). 문제가 보이면 `IMAGE_GENERATION_MODE=realtime`(env/repo
  variable)으로 즉시 롤백 가능.
- ⚠️ **첫 렌더는 대개 절감이 없다.** 지시서 승인 즉시 대시보드가 렌더를 트리거하므로(`triggerRender`),
  방금 승인한 지시서는 Batch 가 끝나기 전에 Realtime 이 이미 채울 가능성이 높다(Batch 는 분~시간
  단위). 절감은 주로 **재렌더**(2번째 언어, 편집 후 재시도)에서 실현된다.

### B — 영상 이중 캡 → **완료(PC4)**
- `media_policy` enum + `VIDEO_MAX_GENERATED_SEC_PER_TOPIC`(8초)/`VIDEO_MAX_COST_USD_PER_TOPIC`($0.40)
  + Preflight(`directive.py:preflight_video_budget`, 지시서 정규화 시점 = 렌더/과금 이전 강등) +
  Veo "생성됐으나 산출물 무효" 실패의 실효 비용 원장 반영(`VeoBilledRejection`).

---

## 4. 비용 Baseline (단가·구조 스냅샷)

> **주의:** 명세 §4.4 가 요구하는 실측 지표(주제당 요청/성공/채택 수, 재생성 수, 사용초, P50/P95, 실패율,
> 실제 편당 비용)는 **호출별 원장이 없어 현재 산출 불가**. 이 자체가 작업 C 의 필요성을 증명한다.
> 아래는 **config 단가 + 10패널 모델 시나리오**(명세 §10)에 근거한 이론 baseline이며, 실측 baseline 은
> PC2(원장) 도입 후 7주제로 채운다.

### 4.1 현재 단가 (config)
| 항목 | 단가 | 출처 |
|---|---:|---|
| 이미지(nano banana, Realtime) | $0.039/장 | `GEMINI_IMAGE_COST_USD` |
| 이미지(Batch) — **미도입** | $0.0195/장(목표) | 명세 §2.1 |
| 영상(Veo Lite 720p) | $0.05/초 | `VEO_COST_PER_SEC_USD` |
| 편당 예산 캡 | $1.2 | `RENDER_BUDGET_CAP_USD` |
| TTS(Edge) | $0(무료) | `TTS_PROVIDER=edge` |

### 4.2 편당 이론 비용 (현재 = "D 적용 + Realtime 이미지", 10패널 가정)
- 이미지 10장 × $0.039 = **$0.390** (KO·EN 공유 1벌 — D 덕분에 20장 아님)
- 영상: Veo Lite 4초 클립 최대 4개 × ($0.05×4) = 최대 **$0.80** (선택적)
- → 영상 없는 편: **~$0.39** / 영상 4클립 편: **~$1.19** (현행 캡 $1.2 에 근접 → 캡 상향 이력이 이 때문).

### 4.3 목표 (D 유지 + A 도입 후)
- 이미지 Batch 전환: $0.390 → **$0.195** (편당 이미지비 50%↓, 언어별 실시간 20장 대비 ~75%↓ — 명세 §10).
- 영상은 §8 이중 캡으로 통제(넣는 만큼 그대로 가산).

---

## 5. 착수 시 확정할 값 (명세 §2, §15)

- **Veo Fast 단가 $0.10 vs $0.15 충돌**, **Lite 무음 $0.03** 존재 여부 → 공식 가격표로 확정(config 상수라
  아키텍처 무영향). 현재 config 는 Fast=$0.10 주석, Lite=$0.05.
- **Gemini Batch JSONL 매핑 필드 = `key`**(OpenAI식 `custom_id` 아님) — A 구현 시 준수.
- 이미지 **입력 토큰 비용**도 원장에 반영(출력 이미지비만으로 총비용 계산 금지 — §2.1).

---

## 6. 구현 순서 (이 문서 이후)

```
PC1 작업 D 검증·보강 (캐시키 + 통합테스트 + burn-in 프롬프트)   ✅ 완료
PC2 작업 C 경량 원장 + Preflight                              ✅ 완료 — 최대 실질 갭·측정 기반
PC3 작업 A 이미지 Batch(폴링) + 라이브 배선                    ✅ 완료 — 라이브 키 검증만 남음
PC4 작업 B 영상 정책·이중 캡                                   ✅ 완료
```
A·B·C·D 를 하나의 대규모 변경으로 묶지 않는다(명세 §12.5). PC 단계별 독립 커밋(이 저장소 git log 참조).

## 5. 남은 실작업 (라이브 키 검증만 — 코드/배선은 완료)

1. **첫 실제 렌더에서 관찰:** `render.yml` 이 돌 때 새로 추가된 "Image Batch 제출·폴링" 스텝의 로그를
   본다. `image_batch: 자동 제출 N건` 이 찍히면 제출 성공. 다음 폴(15분 주기 또는 다음 대시보드 트리거)
   에서 `image_batch 완료: job=... 성공=X 실패=Y` 로 실제 응답 구조 검증 여부가 드러난다.
2. **계약이 다르면:** `poll_batch`/`fetch_batch_results`(`engine/providers/image.py`)만 실제 응답에
   맞춰 고친다 — `image_batch.py` 오케스트레이션·캐시·원장 로직은 무관해 영향 없음.
3. **문제가 심하면 즉시 롤백:** GitHub repo variable `IMAGE_GENERATION_MODE=realtime` 로 설정(코드
   변경·재배포 불필요, 다음 워크플로 실행부터 적용).

---

*본 Baseline 은 코드를 읽고 내린 판정이다. 실측 지표(P50/P95·실패율·실효 편당비용)는 원장(PC2) 도입 후
7주제 측정으로 이 문서에 갱신한다. 가격은 2026-07 기준, 착수 시 공식 문서 우선.*
