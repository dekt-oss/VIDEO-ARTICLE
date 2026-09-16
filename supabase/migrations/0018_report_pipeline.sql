-- 리포트 팩토리 (PF0) — 두 번째 "공장" 스키마 (docs/deviation-report-factory.md, 명세 §4)
--
-- 논문 공장(papers/scores/daily_batch/decisions)을 report_* 로 미러링한다.
-- ★ 병렬 테이블(디스크리미네이터 컬럼 아님): 기존 스키마가 전부 paper_id PK/FK 로 묶여 있고
--   대시보드가 JS 조인으로 읽으므로, 공유 테이블에 kind 컬럼을 두면 FK 정체성이 깨지고
--   모든 기존 쿼리에 필터를 더해야 하며 공개 RLS 에서 공장 간 데이터가 섞인다.
--   report_* 병렬 테이블이 두 공장을 완전 격리하고 미러를 기계적으로 만든다.
-- 원문 전문(raw_content)은 저장하지 않는다 — summary 요약만(저작권 안전장치, 명세 §2).

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ARIA 신호에서 온 후보 (원문 전문 저장 최소화)
create table if not exists reports (
  id             uuid primary key default gen_random_uuid(),
  external_id    text unique,          -- 'aria_signal:{id}' / 'aria_research:{id}' (중복제거 키)
  source         text,                 -- 'aria_signal' | 'aria_research'
  ticker         text,                 -- 종목코드 (있으면)
  company        text,                 -- 종목/테마명
  theme          text,                 -- ARIA 테마
  broker         text,                 -- 증권사/채널명 (출처)
  analyst        text,                 -- 애널리스트 (출처)
  title          text,
  summary        text,                 -- 핵심요약 (원문 전문 아님)
  target_price   numeric,              -- broker_targets 목표가
  opinion        text,                 -- 투자의견 (매수/중립 등, 사실 인용용)
  report_url     text,                 -- 원문 링크 (본문은 여기 두고 안 옮김)
  aria_priority  numeric,              -- ARIA 신호 강도 (정렬 보정용)
  signal_level   text,                 -- HIGH | MID | LOW
  is_risk        boolean default false,-- ARIA 위험 신호 (안전도 채점 보조)
  matched_keywords jsonb,              -- ARIA 매칭 근거
  macro_context  text,                 -- list_briefings 맥락 한 줄
  collected_at   timestamptz default now()
);
create index if not exists reports_collected_at_idx on reports (collected_at desc);
create index if not exists reports_ticker_idx on reports (ticker);

-- 4축 경량 채점(명세 §3): 시의성/이해가능성/스토리성/안전도 + 정렬 지수(코드 계산).
create table if not exists report_scores (
  report_id        uuid primary key references reports(id) on delete cascade,
  timeliness       int,                -- ① 시의성/관심도
  explainability   int,                -- ② 이해 가능성
  story            int,                -- ③ 스토리성/의외성
  safety           int,                -- ④ 컴플라이언스 안전도(높을수록 안전)
  interest_index   numeric,            -- 관심 지수(코드 계산)
  story_index      numeric,            -- 스토리 지수(코드 계산)
  safety_index     numeric,            -- 안전 지수(코드 계산)
  title_ko         text,               -- 대시보드 표시용 한글 제목
  one_liner_ko     text,
  one_liner_en     text,
  angle            text,               -- 대중용 핵심 앵글 한 줄
  risk_note        text,               -- 컴플라이언스/편향 관점 주의점
  model            text,
  scored_at        timestamptz default now()
);

create table if not exists report_daily_batch (      -- 그날의 상위 후보
  batch_date date,
  report_id  uuid references reports(id) on delete cascade,
  rank       int,
  sort_mode  text,                      -- 'interest' | 'story' | 'safety'
  primary key (batch_date, report_id)
);
create index if not exists report_daily_batch_date_idx on report_daily_batch (batch_date desc);

create table if not exists report_decisions (         -- 사람의 낙점/탈락
  report_id  uuid primary key references reports(id) on delete cascade,
  status     text,                      -- 'shortlisted' | 'picked' | 'rejected'
  note       text,
  decided_at timestamptz default now()
);

-- ─── RLS: 논문 공장과 동일한 공개(anon) 자세(0007_public_access.sql 패턴) ───
-- 엔진은 계속 service_role 로 RLS 를 우회한다(변경 없음).
alter table reports enable row level security;
alter table report_scores enable row level security;
alter table report_daily_batch enable row level security;
alter table report_decisions enable row level security;

-- 읽기 전용(엔진이 쓰고 사람은 봄): reports/report_scores/report_daily_batch → anon 조회 허용.
do $$
declare t text;
begin
  foreach t in array array['reports','report_scores','report_daily_batch'] loop
    execute format($f$
      drop policy if exists %1$s_public_select on %1$s;
      create policy %1$s_public_select on %1$s
        for select to anon, authenticated using (true);
    $f$, t);
  end loop;
end $$;

-- 사람이 읽고 쓰는 테이블: report_decisions → anon 전체 권한(로그인 없이 낙점).
do $$
declare t text;
begin
  foreach t in array array['report_decisions'] loop
    execute format($f$
      drop policy if exists %1$s_public_all on %1$s;
      create policy %1$s_public_all on %1$s
        for all to anon, authenticated
        using (true) with check (true);
    $f$, t);
  end loop;
end $$;
