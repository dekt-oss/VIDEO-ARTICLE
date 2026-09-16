-- 유튜브 쇼츠 성과 스냅샷 (P-V3 승인 이탈) — docs/deviation-youtube-analytics.md
-- engine.analytics 워커가 YouTube Data API(영상 목록/길이) + Analytics API(지표)로 최근 N일
-- 쇼츠 성과를 끌어와 일 단위 스냅샷으로 쌓는다. 대시보드 /analytics 가 읽는다(읽기 전용 흐름).
-- 업로드 큐(upload_requests, 0015)와 무관 — 이건 조회이고 저건 발행이다.
--
-- 멱등: (video_id, snapshot_date) unique upsert → 같은 날 재실행하면 최신 지표로 갱신.
-- 시계열: snapshot_date 를 PK 에 포함해 날짜별 성과 추이를 남긴다(추후 성장 곡선용).

create table if not exists youtube_analytics (
  id                          uuid primary key default gen_random_uuid(),
  video_id                    text not null,               -- 유튜브 영상 id
  lang                        text default 'ko',           -- 'ko' | 'en' (언어별 채널)
  snapshot_date               date not null,               -- 이 스냅샷을 뜬 날(채널 타임존)
  title                       text,
  published_at                timestamptz,                 -- 영상 게시 시각
  duration_sec                int default 0,
  views                       bigint default 0,
  estimated_minutes_watched   numeric default 0,
  average_view_duration_sec   numeric default 0,           -- 평균 시청 시간(초)
  average_view_percentage     numeric default 0,           -- 평균 시청 지속률(%)
  likes                       bigint default 0,
  comments                    bigint default 0,
  shares                      bigint default 0,
  subscribers_gained          bigint default 0,
  impressions                 bigint default 0,            -- 노출수(요청 지표에 따라 0일 수 있음)
  ctr_percent                 numeric,                     -- 노출 클릭률(%) = views/impressions, 없으면 null
  collected_at                timestamptz default now()
);

-- 멱등 키: 한 영상의 하루치 성과는 1행(재실행 시 갱신).
create unique index if not exists youtube_analytics_video_day
  on youtube_analytics (video_id, snapshot_date);
-- 대시보드 조회: 최근 스냅샷 + 게시 최신순.
create index if not exists youtube_analytics_snapshot_idx
  on youtube_analytics (snapshot_date desc, published_at desc);

-- 공개 접근 정책(0007/0009/0015 와 동일). 엔진 워커는 service_role 로 동작하므로 정책과 무관.
alter table youtube_analytics enable row level security;
drop policy if exists youtube_analytics_public_all on youtube_analytics;
create policy youtube_analytics_public_all on youtube_analytics
  for all to anon, authenticated using (true) with check (true);
