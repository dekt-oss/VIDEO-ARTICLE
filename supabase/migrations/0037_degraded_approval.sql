-- 0037 — degraded 렌더 결과의 사람 승인 표식 (작업지시서 영상엔진품질 v3 §8-2·§8-3).
--
-- 무엇이 필요한가: §8-3 이 상태를 `draft → rendering → qa_pending → done | degraded | failed`
-- 로 정의하고, **done 은 critical QA 전부 PASS 일 때만**이라고 못박았다. important 요소가
-- 빠진 영상은 `degraded` 로 떨어지고 사람이 보고 승인해야 발행할 수 있다.
--
-- ★ 왜 status 를 'done' 으로 덮지 않고 컬럼을 새로 두는가: 덮으면 "무엇을 승인했는지"가
--   사라진다. 결함이 있는 채로 나간 영상과 처음부터 깨끗했던 영상이 기록상 구분되지 않으면,
--   나중에 "왜 이 편만 반응이 나빴나"를 물을 때 답할 자료가 없다. 승인은 판정을 지우는 것이
--   아니라 **판정 위에 사람의 결정을 얹는 것**이다.
--
-- ★★ 상태 어휘(qa_pending·degraded) 자체는 DDL 이 필요 없다 — status 컬럼에 CHECK 제약이
--    한 곳도 없어 새 값이 그냥 써진다. 어휘 정본은 engine/config.py 의 RENDER_STATUS_* 와
--    그 쌍둥이 web/lib/renderStatus.ts 이고, 둘이 갈리면 tests/test_schema_parity.py 가 잡는다.
--    여기서는 주석만 현행화한다.

alter table render_jobs
  add column if not exists degraded_approved_at timestamptz;

alter table report_render_jobs
  add column if not exists degraded_approved_at timestamptz;

comment on column render_jobs.degraded_approved_at is
  'degraded(중요 요소 누락) 영상을 사람이 확인하고 발행을 승인한 시각. null 이면 미승인 — 업로드가 막힌다';
comment on column report_render_jobs.degraded_approved_at is
  'degraded(중요 요소 누락) 영상을 사람이 확인하고 발행을 승인한 시각. null 이면 미승인 — 업로드가 막힌다';

-- 상태 어휘 주석 현행화(값 제약은 없다 — 위 ★★ 참조).
comment on column render_jobs.status is
  'queued | assets | tts | assembling | qa_pending | degraded | done | failed. '
  'qa_pending·degraded 는 **사람 대기** 상태라 watchdog 이 재큐하지 않는다(engine/db.py)';
comment on column report_render_jobs.status is
  'queued | assets | tts | assembling | qa_pending | degraded | done | failed. '
  'qa_pending·degraded 는 **사람 대기** 상태라 watchdog 이 재큐하지 않는다(engine/report_db.py)';
