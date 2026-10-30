-- 주류 소재 개발 — 제작안 초안 저장이 '이미 결과물이 있는 소재'에서 version_conflict 로 막히던 것 (2026-10-30). docs/deviation-drinks-develop.md
--
-- 운영 실측: 위스키 소재에 앞선 영상 초안(결과물)이 있는 상태에서 새 초안을 저장하자 drinks_save_plan 이
-- "다른 곳에서 먼저 저장됐습니다"(version_conflict)로 거부했다. drinks_save_plan 은 결과물에 현재 제작안이 있으면
-- expected_deliverable_version 을 요구하는데(0050), 0060 의 워커 래퍼가 그 값을 넘기지 않았다. 시험은 늘 결과물이 없는 소재였다.
-- 이 파일은 drinks_develop_save_plan 하나만 다시 정의한다 — 워커는 화면을 보지 않으므로, 저장 직전의 결과물 버전을
-- 그 자리에서 읽어 넘긴다(임대를 가진 워커만 부를 수 있고, 안쪽 검사·잠금은 drinks_save_plan 이 그대로 한다).
-- 되돌리기: 0060 의 drinks_develop_save_plan 정의를 다시 실행한다.

create or replace function drinks_develop_save_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_res jsonb; v_dver int;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'plan' then perform drinks_fail('invalid_state', '제작안 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  select d.version into v_dver from drink_deliverables d where d.topic_id = q.topic_id and d.format = 'video' for update;
  v_res := drinks_save_plan(jsonb_build_object('topic_id', q.topic_id, 'format', 'video', 'topic_review_id', q.review_id,
    'plan_json', p -> 'plan_json') || case when v_dver is null then '{}'::jsonb
                                       else jsonb_build_object('expected_deliverable_version', v_dver) end);
  update drink_develop_requests set result_plan_revision_id = (v_res ->> 'revision_id')::uuid, step = 'plan_saved' where id = q.id;
  return v_res;
end $$;

revoke all on function drinks_develop_save_plan(jsonb) from public, anon, authenticated;
grant execute on function drinks_develop_save_plan(jsonb) to service_role;
