-- 생성 요청 큐에 lease·heartbeat·재시도 흔적 (2026-08-29 리뷰 §8)
--
-- 무엇을 푸는가: 요청이 **영구 processing** 으로 남는다. 실측(2026-08-28 13:07) —
--   Edge Function 이 202 를 돌려준 뒤 EdgeRuntime.waitUntil 안에서 생성을 계속하다가
--   47초 만에 isolate 가 shutdown 됐다. catch 가 실행되지 않으니 상태를 error 로 바꾸지도
--   못했고, 요청은 processing 인 채로 남아 화면이 "생성 중"에서 멈췄다. 아무도 다시 집지 않는다.
--
-- 고치는 방식: 요청을 **임대(lease)** 로 잡는다. 워커가 집을 때 만료 시각을 찍고 살아 있는 동안
--   heartbeat 를 갱신한다. 만료된 processing 행은 다른 워커가 되집어 간다(자동 재큐).
--   시도 횟수가 상한을 넘으면 error 로 확정한다 — 무한 재시도로 돈을 태우지 않기 위해서다.
--
-- ★ 컬럼만 늘린다. 기존 status 값(queued/processing/done/error)과 인덱스는 그대로다 —
--   옛 행과 옛 코드가 그대로 동작해야 한다(NULL lease = 만료된 것으로 본다).

alter table directive_requests
  add column if not exists lease_expires_at timestamptz,
  add column if not exists heartbeat_at     timestamptz,
  add column if not exists attempt_count    int default 0,
  add column if not exists last_error       text,
  add column if not exists worker_id        text;

alter table report_directive_requests
  add column if not exists lease_expires_at timestamptz,
  add column if not exists heartbeat_at     timestamptz,
  add column if not exists attempt_count    int default 0,
  add column if not exists last_error       text,
  add column if not exists worker_id        text;

-- 만료 임대를 빨리 찾기 위한 인덱스. "processing 인데 lease 가 지났다" 가 재큐 대상이다.
create index if not exists directive_requests_lease_idx
  on directive_requests (status, lease_expires_at);
create index if not exists report_directive_requests_lease_idx
  on report_directive_requests (status, lease_expires_at);

comment on column directive_requests.lease_expires_at is
  '워커 임대 만료 시각. 지난 processing 행은 다른 워커가 되집어 간다(engine/db.requeue_stale_directive_requests). '
  'NULL 이면 임대 없이 processing 이 된 옛 행 — 역시 재큐 대상이다.';
comment on column directive_requests.attempt_count is
  '시도 횟수. 상한(config.REQUEST_MAX_ATTEMPTS)을 넘으면 재큐하지 않고 error 로 확정한다 — '
  '무한 재시도는 유료 호출을 무한히 태운다.';
