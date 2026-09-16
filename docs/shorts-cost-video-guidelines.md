# 숏츠 비용·영상 제작 공통 지침 (양 라인 공통)

> **적용 범위:** 이 저장소의 논문 숏츠 라인 **그리고** 신규 주제 숏츠 자동화 라인 — **둘 다 동일 적용**.
> 세부가 다른 경우만 각 라인에서 별도 지시한다. 근거 명세: `개발명세서(최종 v3) — 숏츠 렌더 비용 최적화`,
> 현황·판정: `docs/cost-optimization-baseline.md`.

이 문서는 "왜"가 아니라 **어느 라인이든 지켜야 하는 규칙**을 모은다. 값은 전부 `engine/config.py` 상수라
라인별로 env 로 조정하되, 아래 **불변식(invariant)**은 라인이 달라도 깨지 않는다.

---

## 원칙 요약 (절감 크기 순: D → A → B, 측정 = C)

1. **D 언어 독립 공유 에셋 — 최우선.** 시각 에셋(이미지·영상)은 **언어 무관 1벌만** 생성해 공유한다.
   언어는 TTS·자막·타임라인만 분기. 언어가 늘어도 이미지·영상비는 **안 는다.**
2. **A 이미지 Batch.** 대량 패널은 Batch API 로 장당 표준가의 ~50%. 검수 단건만 Realtime.
3. **B 영상 = 선택 투자.** 영상은 기본 자산이 아니다. 저가 티어(Veo Lite) + 선택적 사용 + **초수·금액 이중 캡.**
4. **C 비용 원장.** 모든 외부 생성 호출을 호출별로 기록해 절감이 진짜였는지 실측한다.

---

## 불변식 (라인 무관 — 절대 깨지 않는다)

### I1. 공유 시각 에셋에 언어 텍스트를 굽지 않는다 (Burn-in 금지)
- 이미지·영상 프롬프트에 `config.BURN_IN_NEGATIVE_PROMPT`(no text/captions/labels/**numbers**/
  watermarks 등)를 **항상** 붙인다. 자막·제목·차트 라벨·수치·연구자명·UI 문구는 화면에 굽지 않는다.
- 텍스트는 **언어별 레이어(ASS 자막 / MoviePy·SVG 오버레이)로 합성**한다. 언어별로 장면 전체를 이미지
  모델로 재생성하지 않는다.
- 이유: KO 이미지에 한글이 박히면 EN 이 재사용 못 해 이중 생성 → D 가 깨진다.
- 예외: 코드 기반 클립(Manim kinetic_typography/data_viz)은 화면에 텍스트를 굽지만 **무료·결정론적**이라
  언어별 재렌더 비용이 무시할 만함. 값비싼 이미지(comic/broll)·Veo 클립만 진짜 언어 공유 대상.

### I2. 에셋 생성 함수는 locale 을 받지 않는다
- 이미지·영상 생성/캐시 조회는 언어 인자가 없어야 한다(구조적으로 언어 독립). 캐시 키는 비주얼만:
  `content_hash(cut, header)` — **narration/subtitle/locale/voice/timeline 포함 금지.**
- TTS·자막·타임라인·렌더만 locale 을 받는다.

### I3. 공유비는 원장에 1회만 기록한다 (이중 계상 금지)
- 시각 에셋비는 **생성이 일어난 1회만** `generation_attempts` 에 기록한다(캐시 재사용은 기록 안 함).
  KO·EN 이 같은 이미지를 쓰면 이미지비는 원장에 **한 번**. → 원장 합계 = 실제 총지출.
- 언어별 성과 분석이 필요하면 관리회계상 50:50 등으로 **배분**하되 원장은 재기록하지 않는다.

### I4. 영상은 이중 캡을 통과해야만 생성한다
- **초수 캡 + 금액 캡** 둘 다(`VIDEO_MAX_GENERATED_SEC_PER_TOPIC`/`VIDEO_MAX_COST_USD_PER_TOPIC`). 초수만
  제한하면 티어 상향 시 비용 통제가 안 된다.
- **Preflight = 지시서 생성 시점**(렌더/유료 API 호출 이전)에 캡을 적용한다. 캡을 넘는 컷은 애초에
  Veo 를 호출하지 않도록 `motion_source` 를 스틸로 강등한다(사후 예산가드가 아니라 사전 차단).
- `media_policy` enum(`image_only`/`image_preferred`/`video_allowed`/`video_required`)으로 라인별
  영상 사용 태도를 결정한다. `video_required` 는 캡을 넘어도 최우선 1개는 강제 유지(사람 개입 큐가
  없는 경량 경로의 대체 — 로그로 표시).
- 영상 공유: 한/영이 **같은 클립**을 쓰므로 언어 수와 무관하게 **1회만** 생성.
- **미채택 비용도 원장에 포함:** Veo 생성이 완료(과금 유력)됐으나 다운로드/검증에 실패해 못 쓰는
  경우도 실효 비용으로 기록한다(`billed_units` 로 명시 — 실패해도 과금분은 남긴다).

### I5. 비용은 Decimal, 단가는 config
- 비용 계산·합산은 `Decimal`(부동소수 드리프트 금지). 단가는 코드에 박지 말고 `config.PRICING` 에서
  읽어 원장 행에 스냅샷. Preview 모델 가격·ID 변동은 config 로 흡수(아키텍처 무영향).

---

## config 노브 (라인별 조정 가능, 불변식은 유지)

| 노브 | 의미 | 기본 |
|---|---|---:|
| `BURN_IN_NEGATIVE_PROMPT` | 공유 에셋 화면 텍스트 금지 제약(I1) | 고정 문구 |
| `PRICING` | 모델별 단가표(원장 스냅샷, I5) | §2.3 표 |
| `LANGUAGES` / `DEFAULT_LANG` | 산출 언어 | `("ko","en")` / `ko` |
| `IMAGE_MODEL` / `IMAGE_PROVIDER` | 이미지 모델·제공자 | nano banana / placeholder |
| `IMAGE_GENERATION_MODE` | 이미지 Realtime/Batch 전환(I3 절감의 실행 스위치). `render.yml` 배선 완료 — 문제 시 repo variable 로 즉시 롤백 | `batch`(사용자 승인, 2026-07-16) |
| `VEO_MODEL` | 영상 티어(Lite/Fast/Standard) | Lite |
| `VEO_CLIP_SEC` / `VEO_MAX_CLIPS_PER_DRAFT` | 클립 길이·편당 클립 개수 상한(레거시 보조 가드) | 4초 / 4개 |
| `VIDEO_MAX_GENERATED_SEC_PER_TOPIC` / `VIDEO_MAX_COST_USD_PER_TOPIC` | **주제당 이중 캡**(I4, Preflight) | 8초 / $0.40 |
| `DEFAULT_MEDIA_POLICY` | 영상 사용 정책 기본값(I4) | `image_preferred` |
| `RENDER_BUDGET_CAP_USD` | 편당(이미지+영상+TTS 합산) 금액 백스톱 | $1.2 |

> **주의:** Veo Fast 단가는 소스 간 $0.10 vs $0.15 충돌, Lite 무음 $0.03 존재 여부 미확정 →
> 착수 시 공식 가격표로 확정(config 라 코드 무영향). 이미지 **입력 토큰 비용**도 원장에 반영.

---

## 신규 주제 라인 착수 체크리스트 (이 지침을 그 라인에 적용할 때)
- [ ] 이미지/영상 생성 함수가 `lang`/`locale` 을 받지 않는가? (I2)
- [ ] 캐시 키에 narration/subtitle/locale 이 없는가? (I2)
- [ ] 프롬프트에 `BURN_IN_NEGATIVE_PROMPT` 가 붙는가? (I1)
- [ ] 한 언어 재렌더 시 시각 에셋 생성 호출 0 인가? (D DoD §5.7)
- [ ] 모든 외부 생성 호출이 원장에 기록되고 공유비는 1회만인가? (I3)
- [ ] 영상이 초수·금액 이중 캡을 통과해야만 생성되는가? (I4)
- [ ] 단가가 `config.PRICING` 에서 오고 비용이 `Decimal` 인가? (I5)

세부가 다른 부분(예: 신규 라인 고유의 씬 구성·화풍·플랫폼)은 각 라인에서 별도 지시한다.
