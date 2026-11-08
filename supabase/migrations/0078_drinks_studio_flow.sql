-- 0078: 콘텐츠 스튜디오 한 줄 흐름(운영자 2026-11-08) — 초안 코멘트 재생성 → 초안 승인 → 작업 명세서 승인 → 제작 → 검수 → 등록.
-- 근거: docs/deviation-drinks-studio-flow.md
-- ① [코멘트대로 다시 만들기]를 설명형(영상) 초안에도 연다(0077 까지는 카드뉴스만).
-- ② [이 초안 승인] 하나로 근거·대본 승인과 편성을 끝낸다. 제작을 시작하지 않는다 — 돈은 다음 단계(명세서 승인)에서만 나간다.
-- 되돌리기: 0077 의 drinks_studio_rewrite 를 다시 적용하고 drop function drinks_studio_approve_draft(jsonb).

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

-- [이 초안 승인]. 근거의 자격 검사는 drinks_approve_content·drinks_plan_action 이 그대로 잰다 — 운영자에게 근거표를 보이지 않을 뿐 검사를 빼지 않는다.
-- 금액은 기록용(0065 와 같다): 결재를 열지 않고 돈이 나가지 않는다.
create or replace function drinks_studio_approve_draft(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; pk drink_topic_format_picks; d drink_deliverables; v_nums jsonb; v_intent text; v_res jsonb;
begin
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  v_intent := case pr.format when 'carousel' then 'card' when 'video' then 'explainer' end;
  if v_intent is null then perform drinks_fail('format_not_supported', '승인할 수 있는 초안이 아닙니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pk from drink_topic_format_picks where topic_id = t.id and format_intent = v_intent;
  if not found then perform drinks_fail('format_not_selected', '이 형식으로 고른 소재가 아닙니다'); end if;
  select * into r from drink_topic_reviews where id = pr.topic_review_id;
  v_nums := drinks_studio_unverified_numbers(pr.plan_json, r);
  if jsonb_array_length(v_nums) > 0 then
    perform drinks_fail('numbers_unverified', '근거 자료에 없는 숫자가 초안에 있습니다(' || (select string_agg(x, ', ') from jsonb_array_elements_text(v_nums) x)
      || ') — 코멘트로 고쳐 다시 만드세요', v_nums);
  end if;
  if pk.approved_at is null then
    return drinks_approve_content(jsonb_build_object('topic_id', t.id, 'expected_topic_version', t.version,
      'review_id', r.id, 'expected_review_version', r.version,
      'plan_revision_id', pr.id, 'expected_plan_version', drinks_int(p, 'expected_plan_version'), 'format_intent', v_intent,
      'note', '스튜디오 [이 초안 승인] — 운영자가 초안을 읽고 승인, 근거는 자동 검사',
      'approved_amount_usd', case when pr.format = 'video' then (drinks_spend_limits() ->> 'max_cap_usd')::numeric end,
      'score_exception_reason', '스튜디오에서 운영자가 소재를 직접 골라 초안을 승인함(점수는 참고값, 0076)',
      'format_exceptions', jsonb_build_object(pr.format, '운영자가 스튜디오에서 이 형식을 직접 골랐습니다')));
  end if;
  -- 이미 승인된 소재의 새 초안(코멘트로 다시 만든 것): 이 초안만 제출·승인한다.
  select * into d from drink_deliverables where id = pr.deliverable_id;
  if pr.plan_status <> 'draft' or d.current_revision_id is distinct from pr.id or pr.blocked_at is not null then
    perform drinks_fail('invalid_state', '최신 작성 중 초안이 아닙니다 — 새로 불러오세요');
  end if;
  if pr.version <> drinks_int(p, 'expected_plan_version') then
    perform drinks_fail('version_conflict', '초안이 다른 곳에서 바뀌었습니다 — 새로 불러오세요');
  end if;
  perform drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'submit'));
  select * into pr from drink_plan_revisions where id = pr.id;
  v_res := drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'approve',
    'reason', '스튜디오 [이 초안 승인] — 운영자가 새 초안을 읽고 승인'));
  return v_res || jsonb_build_object('topic_id', t.id, 'plan_revision_id', pr.id);
end $$;
