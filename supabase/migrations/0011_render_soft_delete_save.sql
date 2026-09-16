-- 렌더 결과 관리(저장/삭제/휴지통). render_jobs 에 nullable 타임스탬프 2개를 더한다.
-- 상태값(queued→done) 대신 타임스탬프를 쓰는 이유: 감사 로그 겸용, null 기본값이라 기존 행·엔진
-- insert 무변경, status 상태머신을 건드리지 않는다. deleted_at/saved_at 은 독립(보관 렌더도 삭제 가능).
alter table render_jobs add column if not exists deleted_at timestamptz;  -- 휴지통(soft delete)
alter table render_jobs add column if not exists saved_at   timestamptz;  -- 보관(keep/pin)

create index if not exists render_jobs_deleted_idx on render_jobs (deleted_at);
create index if not exists render_jobs_saved_idx   on render_jobs (saved_at);

-- render_jobs RLS: 기존 render_jobs_public_all(0009) 이 새 컬럼을 그대로 커버한다 — 정책 변경 불필요.

-- 영구삭제 시 Storage 의 mp4 객체까지 지우려면 anon 에게 renders 버킷 DELETE 권한이 필요하다.
-- 대시보드는 anon 키 전용(service_role 은 엔진 전용)이고, 데이터가 비민감(논문 영상)이라
-- 0007/0009 의 "전체 공개" 기조와 일치시킨다. 파괴적 액션은 UI 확인 모달로만 방지한다.
drop policy if exists renders_public_delete on storage.objects;
create policy renders_public_delete on storage.objects
  for delete to anon, authenticated using (bucket_id = 'renders');
