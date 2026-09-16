-- 리포트 팩토리 PF1 — 초안 + 컴플라이언스 게이트 (docs/deviation-report-factory.md, 명세 §5)
--
-- 논문 P1(drafts/draft_requests + published)을 report_* 로 미러링 + 신규 compliance 컬럼.
-- 원문 전문은 저장하지 않는다(저작권 안전장치, 명세 §2) — fact_sheet 는 추출 사실만.

create extension if not exists "pgcrypto";

create table if not exists report_drafts (            -- PF1 산출물
  report_id       uuid primary key references reports(id) on delete cascade,
  fact_sheet      jsonb,                 -- 추출된 검증가능 사실(금융 필드)
  script_md       text,                  -- 숏폼 대본
  scenes          jsonb,                 -- 씬별 나레이션+비주얼 프롬프트 (PV 재사용 대비)
  self_check      jsonb,                 -- 문장별 근거 매핑(자기검증)
  compliance      jsonb,                 -- 🆕 컴플라이언스 게이트 결과 (rule_flags/llm_verdict/hallucination_flags/blocked)
  upload_title_ko text,
  upload_title_en text,
  created_at      timestamptz default now()
);

-- PF1 트리거 큐 (대시보드가 요청 행을 쓰고 엔진/엣지가 소비)
create table if not exists report_draft_requests (
  id           uuid primary key default gen_random_uuid(),
  report_id    uuid references reports(id) on delete cascade,
  status       text default 'queued',    -- 'queued' | 'processing' | 'done' | 'error'
  error        text,
  requested_at timestamptz default now(),
  updated_at   timestamptz default now()
);
create index if not exists report_draft_requests_status_idx
  on report_draft_requests (status, requested_at);

create table if not exists report_published (         -- 발행 이력
  report_id    uuid primary key references reports(id) on delete cascade,
  final_script text,
  platforms    jsonb,
  published_at timestamptz default now()
);

-- ─── RLS: 논문 P1 과 동일한 공개 자세(0007·0013 패턴) ───
alter table report_drafts enable row level security;
alter table report_draft_requests enable row level security;
alter table report_published enable row level security;

-- report_drafts: anon 조회 + 인라인 편집(update). insert/delete 는 service_role(엔진)만.
drop policy if exists report_drafts_public_select on report_drafts;
create policy report_drafts_public_select on report_drafts
  for select to anon, authenticated using (true);
drop policy if exists report_drafts_public_update on report_drafts;
create policy report_drafts_public_update on report_drafts
  for update to anon, authenticated using (true) with check (true);

-- 사람이 읽고 쓰는 테이블: report_draft_requests/report_published → anon 전체 권한.
do $$
declare t text;
begin
  foreach t in array array['report_draft_requests','report_published'] loop
    execute format($f$
      drop policy if exists %1$s_public_all on %1$s;
      create policy %1$s_public_all on %1$s
        for all to anon, authenticated
        using (true) with check (true);
    $f$, t);
  end loop;
end $$;
