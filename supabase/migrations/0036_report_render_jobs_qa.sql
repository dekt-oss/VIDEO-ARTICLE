-- 0036 — report_render_jobs.qa: 리포트 라인 렌더 QA 를 남길 자리.
--
-- 왜 필요한가: 논문 라인은 render_jobs.qa 에 발행 전 mp4 실검 결과(끝 검은프레임·무음·
-- 클리핑·길이)를 남기는데, 리포트 라인에는 그 컬럼도 없고 run_qa 호출도 없었다. 그래서
-- 리포트 영상은 **아무 검사도 받지 않고** 나갔다.
--
-- 여기에는 세 가지가 들어간다(v3 §8-1·§9):
--   · run_qa 산출물 — mp4 실검
--   · board_qa    — 컷별 CORE 충전율·프레임 판정. Phase 0 이 실측한 결함(충전율 0.235 가
--                   통과)의 기준값을 정하려면 분포가 쌓여야 하는데, 지금까지 이 값은
--                   계산되고 즉시 버려졌다.
--   · cut_map     — 컷 ↔ 최종 mp4 시간축. "몇 초 지점의 어느 컷이 실패했나"를 물을 수 있게.
--
-- ★ 판정 정책은 이 마이그레이션으로 바뀌지 않는다. 기록만 시작한다 — 충전율 warn→fail
--   승격은 분포를 보고 운영자가 기준값을 정한 뒤다.

alter table report_render_jobs
  add column if not exists qa jsonb;

comment on column report_render_jobs.qa is
  'mp4 실검(run_qa) + board_qa(컷별 충전율·프레임 판정) + cut_map(컷↔시간축). 기록 전용 — 차단하지 않는다';
