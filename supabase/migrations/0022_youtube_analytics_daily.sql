-- 유튜브 채널 날짜별 시계열 (P-V3 성과 리포트) — docs/deviation-youtube-analytics.md
-- engine.analytics 가 YouTube Analytics API(dimensions=day)로 채널 단위 일별 지표를 끌어와 저장한다.
-- youtube_analytics(0021, per-video 롤링 스냅샷)와 달리, 이건 채널 전체를 하루 단위로 쌓은 진짜
-- 시계열 — 대시보드 /analytics/report 가 이걸 읽어 일간/주간/월간으로 집계하고 차트로 그린다.
--
-- 멱등: (lang, day) unique upsert → 재실행하면 최신 지표로 갱신(지표 확정 지연 대비).

create table if not exists youtube_analytics_daily (
  id                          uuid primary key default gen_random_uuid(),
  lang                        text default 'ko',   -- 'ko' | 'en' (언어별 채널)
  day                         date not null,       -- 채널 타임존 기준 날짜
  views                       bigint default 0,
  estimated_minutes_watched   numeric default 0,
  average_view_percentage     numeric default 0,   -- 평균 시청 지속률(%)
  likes                       bigint default 0,
  comments                    bigint default 0,
  shares                      bigint default 0,
  subscribers_gained          bigint default 0,
  collected_at                timestamptz default now()
);

-- 멱등 키: 한 채널의 하루치 = 1행(재실행 시 갱신).
create unique index if not exists youtube_analytics_daily_lang_day
  on youtube_analytics_daily (lang, day);
-- 대시보드 조회: 최근 날짜 우선.
create index if not exists youtube_analytics_daily_day_idx
  on youtube_analytics_daily (day desc);

-- 공개 접근 정책(0007/0009/0015/0021 과 동일). 엔진 워커는 service_role 로 동작하므로 정책과 무관.
alter table youtube_analytics_daily enable row level security;
drop policy if exists youtube_analytics_daily_public_all on youtube_analytics_daily;
create policy youtube_analytics_daily_public_all on youtube_analytics_daily
  for all to anon, authenticated using (true) with check (true);
