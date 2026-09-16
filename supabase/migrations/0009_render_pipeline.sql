-- 영상화 파이프라인 (P-V0~P-V1) — docs/deviation-render-pipeline.md
-- ④ 초안(drafts) 이후: 버전별 컷 지시서 → 승인 → 렌더 잡 → 에셋 캐시.
-- 렌더된 mp4·에셋은 용량이 커서 Storage(renders 버킷) URL 만 DB 에 저장한다.

-- ⑤ 컷별 제작 지시서(사람이 승인하는 중심 산출물 + 렌더 엔진 입력). 명세 §4.
create table if not exists directives (
  id            uuid primary key default gen_random_uuid(),
  paper_id      uuid references papers(id) on delete cascade,
  version_type  text,                  -- 'comic' | 'image_sequence' | 'animation'
  header        jsonb,                 -- aspect_ratio, global_style, bgm, total_estimated_sec
  cuts          jsonb,                 -- 컷 배열(명세 §4 스키마)
  status        text default 'draft',  -- 'draft' | 'approved' | 'rendering' | 'rendered' | 'failed'
  created_at    timestamptz default now(),
  approved_at   timestamptz
);
create index if not exists directives_paper_idx on directives (paper_id, created_at desc);

-- 지시서 생성 트리거 큐(draft_requests 패턴). 대시보드가 요청 행을 쓰고 엣지함수/워커가 소비.
create table if not exists directive_requests (
  id           uuid primary key default gen_random_uuid(),
  paper_id     uuid references papers(id) on delete cascade,
  version_type text,
  status       text default 'queued',  -- 'queued' | 'processing' | 'done' | 'error'
  error        text,
  requested_at timestamptz default now(),
  updated_at   timestamptz default now()
);
create index if not exists directive_requests_status_idx on directive_requests (status, requested_at);

-- 렌더 잡 큐(P-V1). GitHub Actions/로컬 워커가 render_jobs 를 폴링해 mp4 를 만든다.
create table if not exists render_jobs (
  id            uuid primary key default gen_random_uuid(),
  directive_id  uuid references directives(id) on delete cascade,
  status        text default 'queued', -- 'queued' | 'assets' | 'tts' | 'assembling' | 'done' | 'failed'
  progress      int default 0,         -- 0~100
  cost_estimate numeric default 0,     -- 누적 비용(예산 가드용)
  output_url    text,                  -- 렌더된 mp4 (Storage URL)
  error_log     text,
  created_at    timestamptz default now(),
  finished_at   timestamptz
);
create index if not exists render_jobs_status_idx on render_jobs (status, created_at);

-- 컷별 생성 에셋 캐시(멱등성). content_hash 로 재렌더 시 변경 컷만 재생성.
create table if not exists render_assets (
  id            uuid primary key default gen_random_uuid(),
  directive_id  uuid references directives(id) on delete cascade,
  cut_no        int,
  asset_type    text,                  -- 'image' | 'clip' | 'audio'
  asset_url     text,
  content_hash  text,                  -- 컷 내용 해시(visual_prompt+version+style) — 캐시 키
  meta          jsonb,
  created_at    timestamptz default now(),
  unique (directive_id, cut_no, asset_type)
);
create index if not exists render_assets_hash_idx on render_assets (content_hash);

-- Storage 버킷 'renders' (저장소 최초의 스토리지 사용 — deviation 기록). 공개 읽기(대시보드 미리보기).
-- 워커는 service_role 로 업로드(RLS 우회). public=true 라 URL 로 바로 재생 가능.
insert into storage.buckets (id, name, public)
values ('renders', 'renders', true)
on conflict (id) do nothing;

-- 공개 접근 정책 (로그인 제거 0007 과 동일). 네 테이블 모두 anon/authenticated 읽기·쓰기.
-- 엔진/엣지함수는 service_role 로 동작하므로 정책과 무관.
do $$
declare t text;
begin
  foreach t in array array['directives','directive_requests','render_jobs','render_assets']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists %I_public_all on %I', t, t);
    execute format(
      'create policy %I_public_all on %I for all to anon, authenticated using (true) with check (true)',
      t, t);
  end loop;
end $$;
