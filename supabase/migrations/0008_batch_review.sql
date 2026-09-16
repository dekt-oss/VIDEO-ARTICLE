-- 일자별 확인 체크(운영자 요청): 배치 날짜마다 "사람이 검토했는지"를 기록.
-- 메인 화면은 이 표를 기준으로 "가장 오래된 미확인 배치일"부터 보여준다.
create table if not exists batch_review (
  batch_date  date primary key,
  reviewed_at timestamptz not null default now()
);

comment on table batch_review is '운영자가 확인 완료한 배치일. 존재하면 확인됨.';

-- 로그인 제거(0007)와 동일하게 공개 접근.
alter table batch_review enable row level security;
drop policy if exists batch_review_public_all on batch_review;
create policy batch_review_public_all on batch_review
  for all to anon, authenticated
  using (true) with check (true);
