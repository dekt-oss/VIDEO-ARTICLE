-- 리포트 팩토리 PF2 — 영상화(지시서 + 렌더) (docs/deviation-report-factory.md)
--
-- 논문 렌더 파이프라인(0009/0011/0012)을 report_* 로 미러. 렌더 엔진은 재사용, 테이블만 격리.
-- render_jobs/render_assets 는 directive_id 로만 묶여 papers FK 가 없지만, 리포트 지시서는
-- report_directives 에 살아야 하므로(paper 테이블 오염 방지) 병렬 테이블 + FK 로 완전 격리한다.
-- 산출 mp4 는 기존 'renders' 버킷의 'report/' 접두 경로(신규 버킷 없음).

create extension if not exists "pgcrypto";

create table if not exists report_directives (
  id            uuid primary key default gen_random_uuid(),
  report_id     uuid references reports(id) on delete cascade,
  version_type  text,                    -- 'comic' (PF2 단일)
  header        jsonb,                   -- aspect_ratio·global_style·hook_*·cta_*·broker·total_estimated_sec
  cuts          jsonb,                   -- 컷별 지시(나레이션·visual_prompt·effects·source_facts…)
  status        text default 'draft',    -- draft|approved|rendering|rendered|failed
  created_at    timestamptz default now(),
  approved_at   timestamptz
);
create index if not exists report_directives_report_idx on report_directives (report_id, created_at desc);

create table if not exists report_directive_requests (
  id           uuid primary key default gen_random_uuid(),
  report_id    uuid references reports(id) on delete cascade,
  version_type text,
  status       text default 'queued',    -- queued|processing|done|error
  error        text,
  requested_at timestamptz default now(),
  updated_at   timestamptz default now()
);
create index if not exists report_directive_requests_status_idx
  on report_directive_requests (status, requested_at);

create table if not exists report_render_jobs (
  id            uuid primary key default gen_random_uuid(),
  directive_id  uuid references report_directives(id) on delete cascade,
  lang          text not null default 'ko',
  status        text default 'queued',    -- queued|assets|tts|assembling|done|failed
  progress      int default 0,
  cost_estimate numeric default 0,
  output_url    text,
  error_log     text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now(),  -- 하트비트(watchdog 재큐 기준)
  finished_at   timestamptz,
  deleted_at    timestamptz,                -- 휴지통(soft delete)
  saved_at      timestamptz                 -- 보관
);
create index if not exists report_render_jobs_status_idx  on report_render_jobs (status, created_at);
create index if not exists report_render_jobs_deleted_idx on report_render_jobs (deleted_at);
create index if not exists report_render_jobs_saved_idx   on report_render_jobs (saved_at);

-- 스키마 패리티용(PF2 v1 미배선 — 워커가 directive_id=None 으로 캐시 미접촉). 후속 배선 대비.
create table if not exists report_render_assets (
  id            uuid primary key default gen_random_uuid(),
  directive_id  uuid references report_directives(id) on delete cascade,
  cut_no        int,
  asset_type    text,
  asset_url     text,
  content_hash  text,
  meta          jsonb,
  created_at    timestamptz default now(),
  unique (directive_id, cut_no, asset_type)
);

-- ─── RLS: 논문 렌더(0009)·PF0/PF1(0018/0019) 공개 자세 그대로 ───
do $$
declare t text;
begin
  foreach t in array array['report_directives','report_directive_requests',
                           'report_render_jobs','report_render_assets']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists %I_public_all on %I', t, t);
    execute format(
      'create policy %I_public_all on %I for all to anon, authenticated using (true) with check (true)',
      t, t);
  end loop;
end $$;
