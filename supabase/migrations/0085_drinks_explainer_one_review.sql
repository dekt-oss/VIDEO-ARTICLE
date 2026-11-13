-- 주류 — 설명형 검수 한 번에 (2026-11-13). docs/deviation-drinks-explainer-one-review.md
--
-- 무엇이 — 왜: 자동 검사를 통과한 설명형 영상은 사람 검수가 세 번(과정 검수 → 품질 검수 6항목 → 최종 파일 승인) 따로 있었다.
--   앞의 둘은 '제작' 칸에, 마지막은 '검수' 칸에 있어서 결정 바가 '검수' 칸으로 보내면 버튼이 없었다(운영자 캡처 2026-11-13, 청주·탁주).
--   운영자 지시: 흐름이 거슬리지 않게 쭉 이어지게. → 영상 바로 아래 한 번의 [검수하고 승인]이 세 기록을 한 트랜잭션으로 남긴다.
-- 바뀌지 않는 것: 세 단계의 규칙·순서·체크 항목(각 함수를 그대로 부른다 — 하나라도 거부하면 전부 되돌린다). 불합격 경로도 그대로.
-- 되돌리기: drop function drinks_explainer_approve_all(jsonb);

create or replace function drinks_explainer_approve_all(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid := drinks_uuid(p, 'plan_revision_id'); e drink_explainer_episodes; r drink_output_reviews; ck jsonb := p -> 'checks';
begin
  select * into e from drink_explainer_episodes where plan_revision_id = v_plan for update;
  if not found then perform drinks_fail('not_found', '설명형 편을 찾지 못했습니다'); end if;
  if e.state not in ('auto_qa_pass', 'process_review_pass', 'quality_review_pass') then
    perform drinks_fail('invalid_state', '자동 검사를 통과하고 아직 승인 전인 편만 검수합니다(' || e.state || ')');
  end if;
  select * into r from drink_output_reviews where plan_revision_id = v_plan and status in ('pending', 'changes_requested')
    order by created_at desc limit 1;
  if not found then perform drinks_fail('not_found', '검수할 최종 파일 묶음이 없습니다'); end if;
  if e.state = 'auto_qa_pass' then
    perform drinks_explainer_review(jsonb_build_object('plan_revision_id', v_plan, 'stage', 'process', 'outcome', 'pass', 'checks', ck));
  end if;
  if e.state in ('auto_qa_pass', 'process_review_pass') then
    perform drinks_explainer_review(jsonb_build_object('plan_revision_id', v_plan, 'stage', 'quality', 'outcome', 'pass', 'checks', ck));
  end if;
  return drinks_output_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'approve',
    'checklist', ck, 'reviewer', 'operator', 'reason', drinks_text(p, 'reason')));
end $$;

revoke all on function drinks_explainer_approve_all(jsonb) from public, anon, authenticated;
grant execute on function drinks_explainer_approve_all(jsonb) to service_role;
