-- 이미지 Batch 잡 추적 (작업 A, 명세 §7). 지시서 승인 후 대량 패널을 Gemini Batch API 로 제출하고
-- 폴링으로 수거한다(경량 경로 — 웹훅 없음, PC0 판정). 결과는 기존 render_assets 캐시에 적재되므로
-- render.py 의 Realtime 경로는 변경 없이 캐시 히트로 자동 절감을 본다.
--
-- rollback: drop table if exists image_batch_jobs;

create table if not exists image_batch_jobs (
  id               uuid primary key default gen_random_uuid(),
  directive_id     uuid references directives(id) on delete cascade,
  provider_job_id  text,                    -- Gemini batch 리소스명("batches/xxxx")
  payload_hash     text,                    -- 제출 페이로드 해시(중복 제출 방지, §7.3)
  status           text default 'submitted', -- submitted | running | succeeded | failed
  request_count    int default 0,
  succeeded_count  int default 0,
  failed_count     int default 0,
  error            text,
  created_at       timestamptz default now(),
  polled_at        timestamptz,
  completed_at     timestamptz,
  unique (directive_id, payload_hash)
);
create index if not exists image_batch_jobs_status_idx on image_batch_jobs (status, created_at);

alter table image_batch_jobs enable row level security;
drop policy if exists image_batch_jobs_public_all on image_batch_jobs;
create policy image_batch_jobs_public_all on image_batch_jobs
  for all to anon, authenticated using (true) with check (true);
