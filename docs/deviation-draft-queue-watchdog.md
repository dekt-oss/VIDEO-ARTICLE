# 편차 기록 — 초안 요청 큐의 정체 회수 (2026-09-17)

> **한 줄:** `draft_requests`·`report_draft_requests` 가 `processing` 으로 멈추면 **영원히**
> 막혔다. 0043 이 바로 그 사고를 고쳤는데 **지시서 큐에만** 붙고 초안 큐는 빠져 있었다.

## 1. 무엇이 문제였나

폴링 워커는 `queued` 만 집는다. 그래서 요청을 집어간 쪽이 중간에 죽으면 그 행은 `processing`
인 채로 남고 **아무도 다시 집지 않는다.** 화면에서는 이렇게 보인다.

- 논문 ④: [초안 생성] 이 "이미 처리 중"으로 막혀 아무 일도 안 일어난다.
- 리포트 ④: `/api/report-generate-draft` 가 **409 "이미 생성 중입니다"** 를 영원히 돌려준다.

운영자가 할 수 있는 일은 SQL 로 `status='queued'` 를 손으로 되돌리는 것뿐이었다
(핸드오프 `docs/핸드오프_작업폴더정리_2026-09-16.md` 남은일 6번).

## 2. 왜 빠져 있었나 — 0043 의 아이러니

`supabase/migrations/0043_request_lease.sql` 머리말이 실측한 사고는 **초안 경로**다.

> 실측(2026-08-28 13:07) — Edge Function 이 202 를 돌려준 뒤 `EdgeRuntime.waitUntil` 안에서
> 생성을 계속하다가 47초 만에 isolate 가 shutdown 됐다. catch 가 실행되지 않으니 상태를
> error 로 바꾸지도 못했고, 요청은 processing 인 채로 남아 화면이 "생성 중"에서 멈췄다.

그 `generate-draft` Edge Function 이 쓰는 테이블이 `draft_requests` 인데, 0043 이 임대 컬럼을
붙인 것은 `directive_requests`·`report_directive_requests` **둘뿐**이다. 고친 곳과 아픈 곳이
어긋나 있었고, 1년 가까이 아무도 눈치채지 못했다.

## 3. 어떻게 고쳤나 — 임대가 아니라 시간

| 선택지 | 판단 |
|---|---|
| 0043 임대를 초안 큐에도 확장 | **버렸다.** 마이그레이션 + Edge Function 2개 수정이 필요하다. Edge 는 하트비트를 못 찍으므로 결국 시간 기준이 되는데, 그러면 컬럼을 늘릴 이유가 없다 |
| `updated_at` 시간 기준 워치독 | **골랐다.** 두 테이블 다 `updated_at` 이 처음부터 있다. 렌더 잡 워치독(`_reclaim_stale_render_jobs`)과 **같은 방식**이고 마이그레이션이 없다 |

### 문턱을 60분으로 잡은 근거

문턱은 **살아 있는 워커의 최대 수명보다 길어야** 한다. 짧으면 정상 동작 중인 워커의 요청을
회수해 같은 초안을 두 번 만든다 — 유료 호출이 두 배가 된다.

워커 수명의 상한은 워크플로의 `timeout-minutes` 다: `draft.yml` 30분, `queues.yml` 45분.
그래서 60분이면 살아 있는 워커와 절대 겹치지 않는다.

★ 지금 워커는 요청을 **한꺼번에 집고**(기본 5건) 자기 차례가 와야 `updated_at` 을 찍는다.
  그래서 뒤쪽 요청은 앞쪽이 끝날 때까지 옛 시각을 달고 있다. 문턱을 줄이려면 **먼저**
  요청마다 하트비트를 찍게 고쳐야 한다. 그 전에 줄이면 안 된다.

### 되살릴 때 새 행을 넣지 않는 이유

웹 라우트가 정체된 행을 발견하면 **그 행을 `queued` 로 되돌린다.** 새 행을 넣으면 엔진
워치독이 나중에 옛 행까지 되살려 같은 초안이 두 번 만들어진다.

## 4. 손댄 곳

| 파일 | 무엇 |
|---|---|
| `engine/config.py` | `REQUEST_STALE_MINUTES = 60` |
| `engine/db.py` | `reclaim_stale_draft_requests()` + `claim_draft_requests` 가 먼저 호출. `update_draft_request` 가 `updated_at` 을 함께 찍는다(안 찍으면 방금 집은 요청을 다른 워커가 뺏는다) |
| `engine/report_db.py` | `claim_report_draft_requests` 가 같은 함수를 `report_draft_requests` 로 호출 |
| `web/lib/requestQueue.ts` | 쌍둥이 상수 + `isStaleProcessing()` |
| `web/app/api/generate-draft`·`report-generate-draft` | 정체 행을 되살린 뒤 진행 |

## 5. 재발 방지

`tests/test_schema_parity.py` 에 셋을 넣었고, 셋 다 변이로 실제로 잡히는지 확인했다.

- `test_request_stale_minutes_matches_between_python_and_ts` — PY/TS 값이 갈리는가
- `test_stale_threshold_outlives_the_worker_job_timeout` — 워크플로의 `timeout-minutes` 를
  **직접 읽어** 비교한다. 주석에 숫자를 적어 두면 워크플로만 늘렸을 때 갈린다
- `test_every_request_queue_has_a_way_out_of_processing` — 큐마다 회수 장치가 있는가,
  그리고 그 함수가 **실제로 폴링 경로에서 불리는가**. 업로드 큐 2개는 "일부러 없음"으로
  명시(중복 발행이 더 나쁘다)

## 6. 되돌리는 법

`claim_draft_requests`·`claim_report_draft_requests` 의 `reclaim_stale_draft_requests` 호출과
웹 라우트의 되살리기 블록을 지우면 종전 동작(영원히 막힘)으로 돌아간다.
`REQUEST_STALE_MINUTES` 는 환경변수로 덮을 수 있다 — 다만 §3 의 하한 근거를 먼저 읽을 것.

## 7. 아직 안 한 것

- **라이브 검증.** 실제로 멈춘 요청을 회수하는 것은 워커가 도는 환경에서만 볼 수 있다.
  지금까지 확인한 것은 로직·배선·쌍둥이 값이다.
- 업로드 큐(`upload_requests`·`report_upload_requests`)는 여전히 회수하지 않는다. 의도된 것이다.
