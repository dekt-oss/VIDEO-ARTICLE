-- 유튜브 자동 업로드 큐 (P-V2 승인 이탈) — docs/deviation-youtube-upload.md
-- ⑥ 렌더 결과(render_jobs.status='done', output_url=mp4)에서 사람이 "유튜브 업로드" 버튼을 누르면
-- upload_requests 에 요청 행이 쌓이고, GitHub Actions 워커(engine.publish)가 폴링해 YouTube Data API
-- videos.insert 로 업로드한다. render_jobs 패턴을 그대로 미러링(원자적 클레임 + 상태 전이 + 폴러).
--
-- 결정(사용자 승인): 트리거=대시보드 버튼, 기본 공개=비공개(private), KO/EN=언어별 다른 채널.
-- ★ 렌더 잡과 달리 워커가 죽어도 자동 재큐(watchdog)하지 않는다 — 업로드는 되돌리기 어려운 외부
--   행위라 재큐가 채널에 중복 영상을 만들 위험이 있다. 'processing' 방치 잡은 사람이 수동 재시도한다.

create table if not exists upload_requests (
  id               uuid primary key default gen_random_uuid(),
  render_job_id    uuid references render_jobs(id) on delete cascade,
  paper_id         uuid references papers(id) on delete set null,
  lang             text default 'ko',        -- 'ko' | 'en' (언어별 채널)
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
create index if not exists upload_requests_status_idx on upload_requests (status, requested_at);
create index if not exists upload_requests_job_idx on upload_requests (render_job_id);

-- 한 렌더 잡(=한 언어 mp4)은 활성 업로드(대기/처리중/완료) 1건만 — 중복 업로드로 채널에 같은
-- 영상이 두 번 올라가는 것을 DB 레벨에서 막는다. 실패('error')는 재시도 가능(유니크 대상에서 제외).
create unique index if not exists upload_requests_job_active
  on upload_requests (render_job_id)
  where status in ('queued', 'processing', 'done');

-- 공개 접근 정책(0007/0009 와 동일). 엔진 워커는 service_role 로 동작하므로 정책과 무관.
alter table upload_requests enable row level security;
drop policy if exists upload_requests_public_all on upload_requests;
create policy upload_requests_public_all on upload_requests
  for all to anon, authenticated using (true) with check (true);
