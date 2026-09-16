-- 리포트 공장 일자별 확인 체크 — 논문 batch_review(0008)의 report_* 미러.
-- 리포트 홈(/finance)이 이 표를 기준으로 "가장 오래된 미확인 배치일"부터 보여준다.
create table if not exists report_batch_review (
  batch_date  date primary key,
  reviewed_at timestamptz not null default now()
);

comment on table report_batch_review is '운영자가 확인 완료한 리포트 배치일. 존재하면 확인됨.';

-- 논문 batch_review 와 동일하게 공개 접근(로그인 제거 정책 계승).
alter table report_batch_review enable row level security;
drop policy if exists report_batch_review_public_all on report_batch_review;
create policy report_batch_review_public_all on report_batch_review
  for all to anon, authenticated
  using (true) with check (true);
