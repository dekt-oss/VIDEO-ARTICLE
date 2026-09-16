-- report_drafts.video_flow 누락 복구 (작업지시서 영상엔진품질 v3 — P1 적대적 리뷰)
--
-- 무엇이 문제였나: `engine/report_draft.generate_report_draft` 는 `video_flow`(logline·beats)를
--   반환 dict 에 담는데 `report_drafts` 에 그 컬럼이 없었다. `report_db.upsert_report_draft` 가
--   dict 를 그대로 PostgREST 로 보내므로 워커가 `42703 column does not exist` 로 죽는다.
--
-- ★ 얼마나 오래 깨져 있었나: 0019 에서 테이블을 만들 때부터다. 논문 라인은 `0006_video_flow.sql`
--   이 `drafts.video_flow` 를 추가했는데 리포트 미러(0019)에는 그 컬럼이 빠졌다.
--   실측(2026-08-02): `report_drafts` 21행 중 `fact_sheet ? 'number_facts'` 인 행 **0건**.
--   즉 파이썬 워커 산출물이 한 번도 저장된 적이 없고, 21행은 전부 Edge Function 이 만들었다.
--   그래서 이 결함이 눈에 띄지 않았다 — 워커는 백업 경로였고 아무도 성공을 확인하지 않았다.
--
-- ★ 재발 방지: `tests/test_schema_parity.py` 가 반환 dict 키 ↔ 마이그레이션 컬럼을 대조한다.
--   그 테스트가 있었으면 이 결함은 애초에 CI 에서 걸렸다.

alter table report_drafts add column if not exists video_flow jsonb;

comment on column report_drafts.video_flow is
  '대본 흐름(logline·total_duration_sec·beats). 논문 drafts.video_flow(0006) 의 리포트 미러 — '
  '0019 에서 누락돼 워커 upsert 가 계속 실패했다.';
