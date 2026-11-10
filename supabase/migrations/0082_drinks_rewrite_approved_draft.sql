-- 코멘트 재생성: 승인된 근거로 만든 작성 중 초안도 고칠 수 있게 (2026-11-10). docs/deviation-drinks-evidence-answers-question.md
--
-- 계기: 버번 소재의 근거를 다시 만들어 승인한 뒤 새 릴스 초안에 코멘트를 달자 '고칠 수 있는 초안이 아닙니다'로 막혔다.
--   종전 함수는 (가) 확정된 초안 (나) 승인 전 근거로 만든 초안 두 경우만 받았다. (다) 승인된 근거로 만든 작성 중 초안을 더한다.
-- 바뀌는 것: drinks_studio_rewrite 에 분기 하나. 나머지 본문은 0078 그대로.
-- 되돌리기: 0078 의 drinks_studio_rewrite 를 다시 실행한다.

create or replace function drinks_studio_rewrite(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_ins text := btrim(coalesce(drinks_text(p, 'instruction'), ''));
  v_budget uuid; bs jsonb; v_intent text;
begin
  perform drinks_reap_develop();
  if length(v_ins) < 2 or length(v_ins) > 500 then perform drinks_fail('invalid_input', '수정 방향을 2~500자로 적어 주세요'); end if;
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pr from drink_plan_revisions where id = pr.id for update;
  if pr.version <> drinks_int(p, 'expected_version') then perform drinks_fail('version_conflict', '초안이 다른 곳에서 바뀌었습니다 — 새로 불러오세요'); end if;
  v_intent := case pr.format when 'carousel' then 'card' when 'video' then 'explainer' end;
  if v_intent is null then perform drinks_fail('invalid_state', '다시 만들 수 있는 초안이 아닙니다'); end if;
  if pr.plan_status = 'approved' and pr.blocked_at is null then
    -- 확정된 초안 → 같은 승인 근거로 새 초안 한 벌(옛 확정·제작물은 그대로). 작성 중인 새 초안이 이미 있으면 그것을 고친다.
    if exists (select 1 from drink_plan_revisions x where x.deliverable_id = pr.deliverable_id and x.plan_status = 'draft' and x.blocked_at is null) then
      perform drinks_fail('draft_exists', '이미 새 초안이 있습니다 — 새로 불러와 그 초안을 고치세요');
    end if;
    if t.status not in ('ready','selected') or not drinks_approval_valid(t.approved_review_id) then
      perform drinks_fail('review_changed', '확정 근거가 지금은 유효하지 않습니다 — 새로 불러오세요');
    end if;
    select * into q from drink_develop_requests where topic_id = t.id and status in ('queued','running') limit 1;
    if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
    bs := drinks_develop_budget_json(v_budget);
    if bs ->> 'status' <> 'open' or (bs ->> 'expired')::boolean or (bs ->> 'remaining_usd')::numeric <= 0 then
      perform drinks_fail('budget_exceeded', '이번 주 AI 초안 한도를 모두 썼습니다');
    end if;
    insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent, instruction)
      values (t.id, 'plan', t.approved_review_id, v_budget, false, v_intent, v_ins) returning * into q;
    perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
      jsonb_build_object('kind', 'plan', 'budget_id', v_budget, 'review_id', t.approved_review_id, 'draft_evidence', false, 'format_intent', v_intent,
        'new_draft_of_approved', pr.id));
    return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
  end if;
  if pr.plan_status = 'draft' and pr.blocked_at is null and not pr.drafted_from_unapproved then
    -- 0082: 승인된 근거로 만든 작성 중 초안(형식을 뒤에 더했거나 근거를 다시 만든 뒤)을 코멘트대로 고친다.
    --   종전엔 이 경우가 빠져 화면 코멘트가 '고칠 수 있는 초안이 아닙니다'로 막혔다(2026-11-10 버번).
    --   워커는 supersedes 로 옛 초안을 막고(drinks_develop_save_rewrite) 같은 승인 근거로 새 초안을 넣는다.
    if t.status not in ('ready','selected') or not drinks_approval_valid(t.approved_review_id) or pr.topic_review_id is distinct from t.approved_review_id then
      perform drinks_fail('review_changed', '초안이 기대던 근거가 바뀌었습니다 — 새로 불러오세요');
    end if;
    select * into q from drink_develop_requests where topic_id = t.id and status in ('queued','running') limit 1;
    if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
    bs := drinks_develop_budget_json(v_budget);
    if bs ->> 'status' <> 'open' or (bs ->> 'expired')::boolean or (bs ->> 'remaining_usd')::numeric <= 0 then
      perform drinks_fail('budget_exceeded', '이번 주 AI 초안 한도를 모두 썼습니다');
    end if;
    insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent, instruction, supersedes_plan_id, supersedes_plan_version)
      values (t.id, 'plan', t.approved_review_id, v_budget, false, v_intent, v_ins, pr.id, pr.version) returning * into q;
    perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
      jsonb_build_object('kind', 'plan', 'budget_id', v_budget, 'review_id', t.approved_review_id, 'draft_evidence', false, 'format_intent', v_intent, 'rewrite_of', pr.id));
    return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
  end if;
  if pr.plan_status <> 'draft' or pr.blocked_at is not null or not pr.drafted_from_unapproved then
    perform drinks_fail('invalid_state', '고칠 수 있는 초안이 아닙니다');
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if t.status <> 'researching' or r.id is distinct from pr.topic_review_id or r.status <> 'draft' then
    perform drinks_fail('review_changed', '초안이 기대던 근거가 바뀌었습니다 — 새로 불러오세요');
  end if;
  select * into q from drink_develop_requests where topic_id = t.id and status in ('queued','running') limit 1;
  if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
  v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  bs := drinks_develop_budget_json(v_budget);
  if bs ->> 'status' <> 'open' or (bs ->> 'expired')::boolean or (bs ->> 'remaining_usd')::numeric <= 0 then
    perform drinks_fail('budget_exceeded', '이번 주 AI 초안 한도를 모두 썼습니다');
  end if;
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent, instruction, supersedes_plan_id, supersedes_plan_version)
    values (t.id, 'plan', r.id, v_budget, true, v_intent, v_ins, pr.id, pr.version) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', 'plan', 'budget_id', v_budget, 'review_id', r.id, 'draft_evidence', true, 'format_intent', v_intent, 'rewrite_of', pr.id));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;
