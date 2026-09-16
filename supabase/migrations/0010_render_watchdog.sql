-- 렌더 잡 정체 감지용 하트비트 컬럼(watchdog). 워커가 죽어 진행중 상태로 방치된 잡을
-- updated_at 기준으로 재큐한다(engine/db.py:_reclaim_stale_render_jobs).
alter table render_jobs add column if not exists updated_at timestamptz not null default now();

-- 재큐 조회 성능(정체 잡 스캔).
create index if not exists idx_render_jobs_status_updated on render_jobs (status, updated_at);
