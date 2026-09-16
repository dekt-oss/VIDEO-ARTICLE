-- 0039 — 비용 원장이 리포트 렌더 잡도 받게 한다.
--
-- 무엇이 문제였나: `generation_attempts.render_job_id` 가 **논문** 테이블만 가리킨다
-- (`references render_jobs(id)`). 리포트 렌더는 자기 잡 번호(report_render_jobs.id)를 넣으므로
-- 외래키 위반으로 **모든 기록이 거부**된다. 기록 실패는 삼켜지도록 돼 있어(렌더를 막지 않는다)
-- 아무도 몰랐다.
--
-- 실측(2026-08-20 실사형 C형 시험 렌더): 이미지 7장 + Veo 클립 6개, 실지출 $1.47.
-- 그런데 원장은 **0행**이었다. 로그에만 남았다:
--   violates foreign key constraint "generation_attempts_render_job_id_fkey"
--   Key (render_job_id)=(c47b4bca-…) is not present in table "render_jobs".
--
-- 왜 중요한가: 이 원장이 "이 편이 왜 비쌌나 · 어느 컷이 폴백이었나"를 답하는 유일한 자료다
-- (docs/measure-core-fill 과 같은 계열). 리포트 라인이 통째로 빠져 있으면 비용 분석이 반쪽이다.
--
-- 어떻게 고치나: 외래키를 **떼고** 잡 종류를 함께 적는다. 두 테이블을 한 컬럼이 동시에
-- 가리킬 수는 없으므로(다형 참조), DB 제약 대신 컬럼으로 구분한다.
-- 되돌리기: 아래 rollback 주석 참조.
--
-- rollback:
--   alter table generation_attempts drop column if exists render_job_kind;
--   alter table generation_attempts
--     add constraint generation_attempts_render_job_id_fkey
--     foreign key (render_job_id) references render_jobs(id) on delete set null;

alter table generation_attempts
  drop constraint if exists generation_attempts_render_job_id_fkey;

alter table generation_attempts
  add column if not exists render_job_kind text not null default 'paper';

comment on column generation_attempts.render_job_kind is
  '''paper'' = render_jobs · ''report'' = report_render_jobs. render_job_id 가 어느 테이블을 가리키는지.';

create index if not exists gen_attempts_job_idx
  on generation_attempts (render_job_kind, render_job_id);
