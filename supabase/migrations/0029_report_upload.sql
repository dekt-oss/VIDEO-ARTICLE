-- 리포트 공장 유튜브 업로드 큐 — 논문 upload_requests(0015)의 report_* 미러.
-- ⑥ 리포트 렌더 결과(report_render_jobs.status='done', output_url=mp4)에서 사람이 "유튜브 업로드"
-- 버튼을 누르면 report_upload_requests 에 요청이 쌓이고, GitHub Actions 워커(engine.report_publish)가
-- 폴링해 videos.insert 로 업로드한다. 논문 파이프라인 그대로.
--
-- 결정(사용자): 트리거=버튼, 기본 공개=비공개(private), 채널=별도 금융 채널(KO만).
-- ★ 논문과 동일: watchdog 자동 재큐 없음(업로드는 되돌리기 어려운 외부 행위 — 중복 방지).

create table if not exists report_upload_requests (
  id               uuid primary key default gen_random_uuid(),
  render_job_id    uuid references report_render_jobs(id) on delete cascade,
  report_id        uuid references reports(id) on delete set null,
  lang             text default 'ko',        -- 리포트는 KO 채널(별도 금융 채널)
  privacy_status   text default 'private',   -- 'private' | 'unlisted' | 'public'
  status           text default 'queued',    -- 'queued' | 'processing' | 'done' | 'error'
  progress         int default 0,
  youtube_video_id text,
  youtube_url      text,
  error            text,
  requested_at     timestamptz default now(),
  updated_at       timestamptz default now(),
  finished_at      timestamptz
);
create index if not exists report_upload_requests_status_idx on report_upload_requests (status, requested_at);
create index if not exists report_upload_requests_job_idx on report_upload_requests (render_job_id);

-- 한 렌더 잡은 활성 업로드(대기/처리중/완료) 1건만 — 중복 업로드 차단. 실패는 재시도 가능.
create unique index if not exists report_upload_requests_job_active
  on report_upload_requests (render_job_id)
  where status in ('queued', 'processing', 'done');

alter table report_upload_requests enable row level security;
drop policy if exists report_upload_requests_public_all on report_upload_requests;
create policy report_upload_requests_public_all on report_upload_requests
  for all to anon, authenticated using (true) with check (true);
