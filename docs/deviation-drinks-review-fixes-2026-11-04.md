# 편차 기록 — 릴스 3형식 독립 리뷰 후속 수정 (2026-11-04)

리뷰 기준 커밋 `03de16b`(브랜치 `claude/drinks-reels-verify-stage`). 리뷰는 참고 자료였고, 지적마다 최신 코드에서 **재현 시험을 먼저 만들고** 고쳤다.
"재현"은 고치기 전 코드에서 그 시험이 실패했다는 뜻이다(커밋마다 고치기 전 파일로 되돌려 돌려 봤다).

운영 DB·운영 화면·실제 공급자·인스타 앱은 **보지 않았다.** 새 마이그레이션 `0071` 은 파일만 있다.

## 판정 요약

| # | 리뷰 지적 | 판정 | 원인(한 줄) | 고친 곳 | 시험 |
|---|---|---|---|---|---|
| R1 | 시작 그림 숨은 재시도·잘못된 해제 | 맞음·재현 | 유료 그림이 재시도 데코레이터 경로를 타서 접수 뒤 타임아웃에 POST 4회, 원장은 해제 | `engine/providers/image.py::gemini_image_once`, `engine/drinks_paid.py::buy/_generate` | `tests/test_drinks_paid.py` (고치기 전 10건 실패) |
| R1 곁가지 | 대본 LLM 원장 | 맞음(같은 형태) | 응답 전에 끊긴 호출을 사용량 0 이라고 해제 | `engine/drinks_develop.py::Ledger` | `test_timed_out_model_call_is_settled_at_estimate_not_released` |
| R2 | Apify+분석 $0.02 합산 | 맞음·재현 | Apify 에 상한 전체를 주고 분석비를 위에 얹음, 사용량 모름 = 예상액 | `engine/drinks_meme_refine.py::split_budget/refine`, 0071 C(월 상한 트리거) | `tests/test_drinks_meme_refine.py` (고치기 전 12건 실패), `test_r2_month_guard_rechecks_on_insert` |
| R3 | 근거 철회 후 밈 게시 | 맞음·재현 | `drinks_pub_block` 이 밈은 상태만 보고 근거 유효성은 안 봄 | 0071 B | `test_r3_*` (0071 없이 실패) |
| R4 | 고아 가잡기·종결 정산 누락 | 맞음·재현(A·B 둘 다) | 시도 행에 hold_id 를 generating 때야 적음 / sweep 이 종결 시도는 안 봄 | 0071 A, `drinks_paid.buy_clip_attempt` | `test_r4*` (0071 없이 실패) |
| R5 | 요청 ID 유실·조회 예외 | 맞음·재현 | 해석 실패를 `ExplainerProviderError` 만 잡아 `ValueError` 가 ID 없이 샘 | `engine/providers/video.py`, `scripts/explainer_lookup.py` | `tests/test_drinks_explainer_queue.py` R5 묶음 |
| R6 | 새벽 예약 ↔ 크론 | 맞음(코드로 확인) | 크론 07:00~23:30, 예약은 아무 시각 | 0071 D, `config.DRINKS_PUBLISH_WINDOW`, `web/lib/drinks/publishWindow.ts` | `test_publish_window_*`, `publishWindow.test.ts` |
| R7 | 편집 뒤 카드 글 검사 누락 | 맞음(코드로 확인) | 화면 글 검사가 생성 때만, 렌더 직전엔 없음 | `engine/drinks_script_check.py::check_card_texts`, `engine/drinks_produce.py` | `tests/test_drinks_card_text_check.py` |
| R8 | 남의 영상 삭제 실패 오보고 | 맞음·재현 | `rmtree(ignore_errors)` 뒤 무조건 '지움' 목록에 넣음 | `engine/drinks_meme_refine.py::_rmtree/sweep_tmp`, `--clean-tmp`, `drinks-apify.yml` | R8 묶음 |
| R9 | 공급자 다운로드 URL | 맞음(코드로 확인) | 응답이 준 주소를 그대로 GET, Omni 는 인증 헤더 + 리다이렉트 허용 | `engine/drinks_fetch.py::check_provider_url/pinned_client`, video·refine | R9 묶음 |
| R10 | S3 잔액 올림 | 맞음·재현 | `ceil_cents(8.90 − 2.2111)` = 6.69 → 합 8.9011 | `scripts/explainer_stages.py::floor_cents/s3_scope` | R10 묶음 |

## 결정과 버린 대안

- **R1 — 재시도를 원장 아래로 옮기지 않고 없앴다.** 유료 그림 한 장의 재시도는 사람이 결과를 본 뒤 새 시도로 하는 편이 안전하다(같은 항목 재구매는 DB `hold_in_progress` 가 막는다). 논문 공장의 `_gemini_image` 재시도는 결재 원장이 없어 그대로 뒀다.
- **R1 — "안 보냄"의 기준:** 연결 전 실패(ConnectError·ConnectTimeout·PoolTimeout)·키 없음·HTTP 4xx(429 포함). 그 밖(읽기/쓰기 타임아웃·끊김·5xx·200 뒤 해석·저장 실패)은 전부 "모름"이다. 모름이면 가잡기를 남기고 운영자가 `drinks_close_orphan_hold` 로 billed/void 를 정한다.
- **R2 — 분석 1편 예약액은 예상액($0.003)이다.** 공급자 쪽에 분석 1편의 하드 상한이 없어서(사고 토큰 포함) 허용된 마지막 호출이 예약액보다 비싸면 그만큼 넘을 수 있다. 그 금액은 숨기지 않고 `over_cap_usd` 로 남는다(`test_overrun_of_the_last_allowed_call_is_recorded_with_a_warning`). 예약액을 "최대 가능액"으로 올리면 3편 분석이 $0.02 안에 들지 않아 기획이 바뀐다 — 운영자 결정 사항으로 남겼다.
- **R4 — 정산을 시도 기록 함수 안으로 합치지 않고, sweep 이 복구하게 했다.** 워커의 기존 호출 순서·가짜 RPC 시험을 그대로 두면서 리뷰의 완료 기준(각 경계에서 끊겨도 sweep·운영자 닫기로 복구, 이중 정산 없음)을 만족한다. 고아 가잡기는 **자동 해제하지 않는다.**
- **R6 — 크론을 넓히지 않고 예약 시각을 좁혔다.** 24시간 크론은 빈 실행 비용 때문에 낮춘 이력이 있어(`docs/deviation-cron-cost.md`) 운영자 결정으로 남겼다. 리허설은 메모리 DB 에서만 창을 넓힌다(밤에 돌려도 시계 때문에 깨지지 않게). 창 자체는 별도 시험이 본다.
- **R7 — 막는 자리는 렌더 직전이다.** 저장·승인 단계(SQL)에 같은 규칙을 옮기지는 않았다 — 렌더가 파일을 하나도 만들지 않으면 검수·게시로 갈 산출물이 없다. 승인 화면에서 미리 알려 주는 것은 하지 않았다(후속).

## 알고 있는 한계 (미검증 포함)

- `config.DRINKS_APIFY_VIDEO_HOSTS`(인스타 영상 CDN `.cdninstagram.com`·`.fbcdn.net`)는 실제 Apify 응답으로 확인한 값이 아니다(미검증). 다르면 다운로드가 안전하게 거절되고 분석 0회로 끝난다.
- PGlite 는 연결이 하나라 **진짜 동시 실행**은 시험하지 못했다. 동시성은 잠금(advisory lock·for update)·고유 색인·상태 검사로 막히는지 순서대로 확인했다. 실제 Postgres 두 연결 시험(`supabase/tests/drinks_concurrency.pg.mjs` 방식)은 돌리지 않았다(미검증).
- 웹 DB 시험(`web/lib/drinks/*.db.test.ts`)은 여전히 0050~0069 범위만 올린다. 0071 은 파이썬 PGlite 시험(`tests/test_drinks_review_fixes.py`·리허설)이 본다.
- 권고 문장 검사(`_ADVICE`)는 "~두세요" 같은 끝맺음을 아직 못 잡는다(R7 시험을 쓰다 발견, 이번 범위 밖).
- 실제 공급자·청구·운영 DB·RLS·화면·인스타 앱·정시 게시는 보지 않았다.

## 되돌리기

커밋 단위로 되돌린다(R1 `25b8a1e`, R2·R3·R4·R6 `51faed9`, R5·R9 `1336e01`, R8 `d5d44de`, R7 `6366ca8`, R10 `3cc712b`). 0071 은 운영에 적용하지 않았으므로 파일을 지우면 된다 — 적용 뒤라면 0071 머리말의 되돌리기를 따른다.
