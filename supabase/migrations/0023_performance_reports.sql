-- 성과 리포트 (P-V3 하이브리드 분석) — docs/deviation-youtube-analytics.md
-- engine.perf_report 가 규칙(코드)으로 근거 지표(facts)를 뽑고 LLM 이 문장화한 결과를 저장한다.
-- 대시보드 /analytics/report 가 최신 행을 읽어 '잘된점 / 잘못된점 / 개선방향'으로 렌더한다.
--
-- went_well/went_bad/improvements 는 문장 배열(jsonb). facts 는 규칙 단계 산출 근거(감사·재현용).
-- 멱등: (period_type, period_start, lang) unique upsert → 같은 기간 재생성 시 최신 분석으로 갱신.

create table if not exists performance_reports (
  id             uuid primary key default gen_random_uuid(),
  period_type    text not null,            -- 'weekly' | 'monthly' | 'overall'
  period_start   date not null,            -- 기간 시작일(주=월요일, 월=1일, overall=창 시작)
  period_end     date,                     -- 기간 종료일
  lang           text default 'ko',        -- 'ko' | 'en' (언어별 채널)
  went_well      jsonb default '[]'::jsonb,  -- 잘된점 문장 배열
  went_bad       jsonb default '[]'::jsonb,  -- 잘못된점 문장 배열
  improvements   jsonb default '[]'::jsonb,  -- 개선방향 문장 배열
  facts          jsonb default '{}'::jsonb,  -- 규칙 단계 근거 지표(LLM 입력 = 감사용)
  generated_at   timestamptz default now()
);

-- 멱등 키: 한 기간·채널 = 1행(재생성 시 갱신).
create unique index if not exists performance_reports_period_key
  on performance_reports (period_type, period_start, lang);
-- 대시보드 조회: 최신 생성 우선.
create index if not exists performance_reports_generated_idx
  on performance_reports (generated_at desc);

-- 공개 접근 정책(0007/0009/0015/0021/0022 와 동일). 엔진 워커는 service_role 로 동작.
alter table performance_reports enable row level security;
drop policy if exists performance_reports_public_all on performance_reports;
create policy performance_reports_public_all on performance_reports
  for all to anon, authenticated using (true) with check (true);
