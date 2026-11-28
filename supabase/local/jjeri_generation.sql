-- Candidate; compare the operational registry and rebase the shared start function before numbering.
-- Apply after the separate jjeri_class.sql candidate. Rehearsal basis: main 93ce7882 through 0091.
begin;

alter table drink_develop_requests drop constraint drink_develop_requests_kind_check;
alter table drink_develop_requests add constraint drink_develop_requests_kind_check check (kind in ('evidence','plan','jjeri'));
alter table drink_develop_requests add column jjeri_input jsonb;
alter table drink_develop_requests add constraint drink_develop_jjeri_input_ck check (
  (kind = 'jjeri') = (jjeri_input is not null) and
  (kind <> 'jjeri' or (review_id is not null and budget_id is not null and not draft_evidence and not chain))
);

create table drink_jjeri_approvals (
  request_id uuid primary key references drink_develop_requests(id),
  plan_revision_id uuid not null unique references drink_plan_revisions(id),
  approved_at timestamptz not null default now()
);
alter table drink_jjeri_approvals enable row level security;
revoke all on drink_jjeri_approvals from public, anon, authenticated;
grant select, insert on drink_jjeri_approvals to service_role;

create function drinks_jjeri_input_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.jjeri_input is distinct from old.jjeri_input then
    perform drinks_fail('immutable', '째리 생성 요청의 근거·결재·입력은 바꿀 수 없습니다');
  end if;
  -- Studio auto-recovery must never resend a Jjeri failure as an ordinary plan.
  if new.kind = 'jjeri' and new.status in ('failed','blocked','canceled') and old.status in ('queued','running')
      and new.error_code not like 'jjeri_%' and new.error_code <> 'canceled' then
    new.error_code := 'jjeri_' || new.error_code;
  end if;
  return new;
end $$;
create trigger drinks_jjeri_input_guard before update on drink_develop_requests
  for each row execute function drinks_jjeri_input_guard();

create function drinks_jjeri_current_review(t drink_topics, v_review uuid, v_hash text) returns drink_topic_reviews
language plpgsql stable set search_path = public, pg_temp as $$
declare r drink_topic_reviews;
begin
  select * into r from drink_topic_reviews where id = v_review and topic_id = t.id;
  if not found or t.status not in ('ready','selected') or t.approved_review_id is distinct from r.id
      or r.status <> 'approved' or r.approved_hash is null or r.approved_hash is distinct from v_hash
      or r.input_hash is distinct from v_hash or not drinks_approval_valid(r.id) then
    perform drinks_fail('jjeri_review_changed', '현재 유효한 승인 근거가 바뀌었습니다. 새 근거를 확인한 뒤 다시 요청하세요');
  end if;
  return r;
end $$;

create function drinks_request_jjeri_episode(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  t drink_topics; r drink_topic_reviews; d drink_deliverables; q drink_develop_requests; pr drink_plan_revisions;
  v_budget uuid := drinks_uuid(p, 'budget_id'); b jsonb; v_input jsonb;
  v_lesson text := drinks_text(p, 'lesson');
  v_format text := coalesce(drinks_text(p, 'format'), 'jjeri_class'); v_cap numeric := drinks_num(p, 'max_usd');
  v_retry uuid := drinks_uuid(p, 'retry_of', false);
  v_regenerate uuid := drinks_uuid(p, 'regenerate_of', false);
begin
  if v_retry is not null and v_regenerate is not null then
    perform drinks_fail('invalid_input', '실패 재시도와 새 지시서 생성은 함께 요청할 수 없습니다');
  end if;
  if p -> 'spend_confirmed' is distinct from 'true'::jsonb or v_cap is null or v_cap <= 0
      or v_cap > (drinks_develop_limits() ->> 'max_usd_per_request')::numeric or scale(v_cap) > 4 then
    perform drinks_fail('jjeri_budget_confirmation', '최대 2회 호출과 요청 금액 상한을 확인해 주세요');
  end if;
  if v_format not in ('jjeri_class','jjeri_anatomy') then
    perform drinks_fail('invalid_input', '지원하는 째리 지시서 형식을 선택하세요');
  end if;
  if (v_format = 'jjeri_class' and (v_lesson is null or v_lesson !~ '^[1-9][0-9]{0,2}교시$'))
      or (v_format = 'jjeri_anatomy' and v_lesson is not null) then
    perform drinks_fail('invalid_input', '교시를 1교시에서 999교시 사이로 입력하세요');
  end if;
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  r := drinks_jjeri_current_review(t, drinks_uuid(p, 'review_id'), drinks_text(p, 'review_hash'));
  if cardinality(drinks_text_array(r.brief -> 'required_claims' -> 'video')) = 0 then
    perform drinks_fail('required_claims_missing', '승인된 기획에 영상 필수 주장을 넣어 주세요');
  end if;
  if t.status <> 'selected' or not 'video' = any(t.selected_formats) or t.selected_review_id is distinct from r.id then
    perform drinks_fail('format_not_selected', '현재 승인 근거로 영상을 편성한 뒤 지시서를 요청하세요');
  end if;
  select * into d from drink_deliverables where topic_id = t.id and format = 'video' and locale = 'ko';
  select * into pr from drink_plan_revisions where id = d.current_revision_id;
  v_input := jsonb_build_object('review_hash', r.approved_hash, 'content_hash', drinks_evidence_content_hash(r.evidence_pack, r.brief),
    'topic', t.title, 'lesson', v_lesson, 'max_usd', v_cap, 'deliverable_id', d.id, 'deliverable_version', d.version,
    'current_revision_id', d.current_revision_id, 'current_plan_version', pr.version, 'current_plan_hash', pr.input_hash,
    'retry_of', v_retry) || case when v_format = 'jjeri_anatomy'
      then jsonb_build_object('format', v_format) else '{}'::jsonb end || case when v_regenerate is not null
      then jsonb_build_object('regenerate_of', v_regenerate) else '{}'::jsonb end;
  select * into q from drink_develop_requests where topic_id = t.id and kind = 'jjeri' and status in ('queued','running');
  if found then
    if q.jjeri_input = v_input and q.budget_id = v_budget then
      return drinks_develop_request_json(q) || jsonb_build_object('existing', true);
    end if;
    perform drinks_fail('develop_in_progress', '다른 째리 생성 요청이 진행 중입니다');
  end if;
  -- Approval advances the video revision. A retried submission after approval must still reuse the approved request.
  select rq.* into q from drink_develop_requests rq
    join drink_jjeri_approvals a on a.request_id = rq.id
    where rq.topic_id = t.id and rq.review_id = r.id and rq.budget_id = v_budget
      and coalesce(rq.jjeri_input ->> 'format','jjeri_class') = v_format
      and (rq.jjeri_input ->> 'lesson') is not distinct from v_lesson and (rq.jjeri_input ->> 'max_usd')::numeric = v_cap
      and (rq.jjeri_input ->> 'retry_of')::uuid is not distinct from v_retry
      and (rq.jjeri_input ->> 'regenerate_of')::uuid is not distinct from v_regenerate
    order by rq.created_at desc limit 1;
  if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
  if v_retry is not null then
    perform 1 from drink_develop_requests where id = v_retry and topic_id = t.id and kind = 'jjeri'
      and review_id = r.id and status in ('failed','blocked','canceled')
      and jjeri_input ->> 'review_hash' = r.approved_hash and coalesce(jjeri_input ->> 'format','jjeri_class') = v_format
      and (jjeri_input ->> 'lesson') is not distinct from v_lesson;
    if not found then perform drinks_fail('invalid_state', '같은 승인 근거·형식·교시의 실패 작업만 재시도할 수 있습니다'); end if;
  end if;
  if v_regenerate is not null then
    perform 1 from drink_develop_requests where id = v_regenerate and topic_id = t.id and kind = 'jjeri'
      and review_id = r.id and status = 'succeeded'
      and jjeri_input ->> 'review_hash' = r.approved_hash and coalesce(jjeri_input ->> 'format','jjeri_class') = v_format
      and (jjeri_input ->> 'lesson') is not distinct from v_lesson;
    if not found then perform drinks_fail('invalid_state', '같은 승인 근거·형식·교시의 완료 작업만 새로 생성할 수 있습니다'); end if;
  end if;
  -- Completed double clicks reuse the same request, including failed attempts. A retry is an explicit, new authorization.
  select * into q from drink_develop_requests where topic_id = t.id and kind = 'jjeri'
    and review_id = r.id and budget_id = v_budget and jjeri_input = v_input order by created_at desc limit 1;
  if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
  b := drinks_develop_budget_json(v_budget);
  if b is null or b ->> 'status' is distinct from 'open' or (b ->> 'expired')::boolean
      or (b ->> 'remaining_usd')::numeric < v_cap then
    perform drinks_fail('budget_exceeded', '요청 상한을 감당할 수 있는 유효한 개발 결재를 선택하세요');
  end if;
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id, jjeri_input)
    values (t.id, 'jjeri', r.id, v_budget, v_input) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'jjeri_episode_requested', null, 'queued', q.id::text, null,
    jsonb_build_object('review_id', r.id, 'review_hash', r.approved_hash, 'max_usd', v_cap, 'lesson', v_lesson));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

-- Shared worker claim: old workers omit allow_jjeri and cannot claim these rows.
create or replace function drinks_start_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; v_reaped int; v_block text; v_budget jsonb; v_job jsonb; v_intent text; v_fmt text;
  v_has_picks boolean;
begin
  v_reaped := drinks_reap_develop();
  loop
    select * into q from drink_develop_requests where status = 'queued'
      and (kind <> 'jjeri' or (p -> 'allow_jjeri' = 'true'::jsonb
        and (jjeri_input ->> 'format' is distinct from 'jjeri_anatomy' or p -> 'allow_jjeri_anatomy_generate' = 'true'::jsonb)))
      order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    if q.kind = 'jjeri' then
      update drink_develop_requests set status = 'running', lease_token = gen_random_uuid(),
        lease_expires_at = now() + make_interval(secs => (drinks_develop_limits() ->> 'lease_sec')::int),
        heartbeat_at = now(), started_at = now(), step = 'started',
        worker_id = coalesce(drinks_text(p, 'worker_id'), 'worker') where id = q.id returning * into q;
      return jsonb_build_object('reaped', v_reaped, 'job', jsonb_build_object(
        'request_id', q.id, 'lease_token', q.lease_token, 'kind', q.kind,
        'budget_id', q.budget_id, 'topic', jsonb_build_object('id', q.topic_id, 'title', q.jjeri_input ->> 'topic')));
    end if;
    select * into t from drink_topics where id = q.topic_id;
    -- 요청의 형식 → 없으면(옛 요청) 대표 형식. 형식을 고른 적 없는 옛 소재는 null(워커가 영상으로 읽는다, 0단계 그대로).
    v_intent := coalesce(q.format_intent, drinks_representative_intent(q.topic_id));
    v_has_picks := exists (select 1 from drink_topic_format_picks where topic_id = q.topic_id);
    v_fmt := drinks_intent_format(coalesce(v_intent, 'explainer'));
    v_block := null;
    if q.kind = 'evidence' then
      if t.status not in ('researching','ready','selected') then v_block := 'topic_state_changed'; end if;
    else
      select * into r from drink_topic_reviews where id = q.review_id;
      if q.draft_evidence then
        if t.status <> 'researching' then v_block := 'topic_state_changed';
        elsif r.status <> 'draft' or r.id is distinct from t.current_review_id then v_block := 'review_changed';
        elsif drinks_intent_format(v_intent) is null or not v_has_picks or not drinks_format_picked(q.topic_id, v_intent) then v_block := 'format_not_selected'; end if;
      elsif r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then v_block := 'review_not_approved';
      elsif v_has_picks then
        if t.status not in ('ready','selected') then v_block := 'topic_state_changed';
        elsif drinks_intent_format(v_intent) is null or not drinks_format_picked(q.topic_id, v_intent) then v_block := 'format_not_selected'; end if;
      elsif t.status <> 'selected' or not v_fmt = any(t.selected_formats) then v_block := 'format_not_selected'; end if;
    end if;
    if v_block is not null then
      update drink_develop_requests set status = 'canceled', finished_at = now(), error_code = v_block,
        error_message = '대기 중에 소재·근거 상태가 바뀌어 만들지 않았습니다(' || v_block || ')' where id = q.id;
      continue;
    end if;
    update drink_develop_requests set status = 'running', lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => (drinks_develop_limits() ->> 'lease_sec')::int),
      heartbeat_at = now(), started_at = now(), step = 'started', worker_id = coalesce(drinks_text(p, 'worker_id'), 'worker'),
      evidence_hash = case when q.draft_evidence then drinks_evidence_content_hash(r.evidence_pack, r.brief) end
      where id = q.id returning * into q;
    v_budget := case when q.budget_id is null then null else drinks_develop_budget_json(q.budget_id) end;
    v_job := jsonb_build_object('request_id', q.id, 'lease_token', q.lease_token, 'kind', q.kind, 'budget_id', q.budget_id,
      'budget', v_budget, 'limits', drinks_develop_limits(), 'chain', q.chain, 'draft_evidence', q.draft_evidence, 'format_intent', v_intent,
      'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'categories', to_jsonb(t.categories),
        'status', t.status, 'version', t.version, 'target_subject', t.target_subject, 'angle', t.angle));
    if q.kind = 'plan' then
      v_job := v_job || jsonb_build_object('review', jsonb_build_object('review_id', r.id, 'status', r.status, 'brief', r.brief,
        'core_claim_ids', to_jsonb(drinks_text_array(r.brief -> 'selected_claim_ids')),
        'claims', coalesce((select jsonb_agg(c) from jsonb_array_elements(r.evidence_pack -> 'claims') c
          where c ->> 'claim_id' = any(drinks_text_array(r.brief -> 'selected_claim_ids'))), '[]'),
        'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher,
            'url', s.canonical_url, 'published_at', s.published_at))
          from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
            from jsonb_array_elements(r.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]')));
    end if;
    return jsonb_build_object('reaped', v_reaped, 'job', v_job);
  end loop;
end $$;

create function drinks_jjeri_generation_context(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'jjeri' then perform drinks_fail('invalid_state', '째리 생성 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  select * into t from drink_topics where id = q.topic_id;
  r := drinks_jjeri_current_review(t, q.review_id, q.jjeri_input ->> 'review_hash');
  if q.jjeri_input ->> 'content_hash' is distinct from drinks_evidence_content_hash(r.evidence_pack, r.brief) then
    perform drinks_fail('jjeri_review_changed', '승인 근거의 내용이 바뀌었습니다');
  end if;
  return jsonb_build_object('topic', q.jjeri_input -> 'topic', 'lesson', q.jjeri_input -> 'lesson',
    'format', coalesce(q.jjeri_input ->> 'format','jjeri_class'),
    'required_claim_ids', r.brief -> 'required_claims' -> 'video',
    'evidence', jsonb_build_object('approved', true, 'selected_claim_ids', r.brief -> 'selected_claim_ids',
      'claims', r.evidence_pack -> 'claims',
      'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title,
        'publisher', s.publisher, 'url', s.canonical_url) order by s.id)
        from drink_source_snapshots s where s.id in (
          select (ref ->> 'snapshot_id')::uuid from jsonb_array_elements(r.evidence_pack -> 'claims') c,
            jsonb_array_elements(c -> 'source_refs') ref
          where c ->> 'claim_id' = any(drinks_text_array(r.brief -> 'selected_claim_ids')))), '[]'::jsonb)));
end $$;

-- Existing Ledger uses drinks_develop_hold and settle. Add stricter request authorization at hold insertion.
create function drinks_jjeri_hold_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_calls int; v_committed numeric;
begin
  -- 0066 shares this ledger with meme drafts. The owner check and FKs still validate both references.
  if new.request_id is null then return new; end if;
  select * into q from drink_develop_requests where id = new.request_id;
  if not found or q.kind <> 'jjeri' then return new; end if;
  perform drinks_jjeri_generation_context(jsonb_build_object('request_id', q.id, 'lease_token', q.lease_token));
  select count(*), coalesce(sum(case status when 'held' then est_usd when 'settled' then actual_usd end), 0)
    into v_calls, v_committed from drink_develop_holds where request_id = q.id;
  if v_calls >= 2 then perform drinks_fail('hold_limit', '째리 요청의 2회 모델 호출 한도를 다 썼습니다'); end if;
  if v_committed + new.est_usd > (q.jjeri_input ->> 'max_usd')::numeric then
    perform drinks_fail('request_cap_exceeded', '확인한 째리 요청 금액 상한을 넘습니다');
  end if;
  return new;
end $$;
create trigger drinks_jjeri_hold_guard before insert on drink_develop_holds
  for each row execute function drinks_jjeri_hold_guard();

create function drinks_finish_jjeri_episode(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; v_plan jsonb; v_coverage jsonb; v_format text;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'jjeri' then perform drinks_fail('invalid_state', '째리 생성 요청이 아닙니다'); end if;
  t := drinks_lock_topic(q.topic_id, null, false);
  perform drinks_jjeri_generation_context(p);
  r := drinks_jjeri_current_review(t, q.review_id, q.jjeri_input ->> 'review_hash');
  v_plan := drinks_validate_plan('video', p -> 'plan', r);
  v_format := coalesce(q.jjeri_input ->> 'format','jjeri_class');
  if v_plan -> v_format ->> 'topic' is distinct from q.jjeri_input ->> 'topic'
      or (v_format = 'jjeri_class' and v_plan -> v_format ->> 'episode' is distinct from q.jjeri_input ->> 'lesson') then
    perform drinks_fail('jjeri_directive_invalid', '요청한 형식·주제·교시와 다른 지시서입니다');
  end if;
  v_coverage := drinks_plan_coverage('video', v_plan, r);
  if v_coverage -> 'ok' is distinct from 'true'::jsonb then
    perform drinks_fail('plan_coverage', '지시서 화면과 내레이션에 영상 필수 주장이 모두 전달되어야 합니다', v_coverage);
  end if;
  update drink_develop_requests set status = 'succeeded', step = 'succeeded', finished_at = now(), lease_token = null,
    result = jsonb_build_object('plan', v_plan, 'cost', p -> 'cost') where id = q.id returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'jjeri_episode_generated', 'running', 'succeeded', q.id::text, null, '{}');
  return drinks_develop_request_json(q);
end $$;

create function drinks_approve_jjeri_episode(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; d drink_deliverables;
  pr drink_plan_revisions; v_saved jsonb; v_id uuid; v_note text := drinks_text(p, 'reason');
begin
  if p -> 'review_confirmed' is distinct from 'true'::jsonb then
    perform drinks_fail('jjeri_human_review_required', '원문과 지시서를 대조했는지 확인해 주세요');
  end if;
  select * into q from drink_develop_requests where id = drinks_uuid(p, 'request_id') and kind = 'jjeri';
  if not found or q.status <> 'succeeded' then perform drinks_fail('invalid_state', '생성을 마친 지시서만 승인할 수 있습니다'); end if;
  t := drinks_lock_topic(q.topic_id, null, false);
  r := drinks_jjeri_current_review(t, q.review_id, q.jjeri_input ->> 'review_hash');
  if drinks_evidence_content_hash(r.evidence_pack, r.brief) is distinct from q.jjeri_input ->> 'content_hash' then
    perform drinks_fail('jjeri_review_changed', '생성 이후 승인 근거의 내용이 바뀌었습니다');
  end if;
  if t.status <> 'selected' or not 'video' = any(t.selected_formats) or t.selected_review_id is distinct from r.id then
    perform drinks_fail('format_not_selected', '현재 승인 근거로 영상을 편성한 뒤 지시서를 승인하세요');
  end if;
  select plan_revision_id into v_id from drink_jjeri_approvals where request_id = q.id;
  if found then return jsonb_build_object('revision_id', v_id, 'existing', true); end if;
  select * into d from drink_deliverables where topic_id = t.id and format = 'video' and locale = 'ko' for update;
  select * into pr from drink_plan_revisions where id = d.current_revision_id for update;
  if (d.id, d.version, d.current_revision_id, pr.version, pr.input_hash) is distinct from
      ((q.jjeri_input ->> 'deliverable_id')::uuid, (q.jjeri_input ->> 'deliverable_version')::int,
       (q.jjeri_input ->> 'current_revision_id')::uuid, (q.jjeri_input ->> 'current_plan_version')::int,
       q.jjeri_input ->> 'current_plan_hash') then
    perform drinks_fail('version_conflict', '생성 이후 영상 제작안이 바뀌었습니다. 현재 제작안을 확인하세요');
  end if;
  if pr.plan_status in ('draft','in_review') and pr.blocked_at is null then
    perform drinks_fail('draft_exists', '작성 중이거나 검토 중인 영상 제작안을 먼저 처리하세요');
  end if;
  v_saved := drinks_save_plan(jsonb_build_object('topic_id', t.id, 'topic_review_id', r.id, 'format', 'video',
    'plan_json', q.result -> 'plan', 'expected_deliverable_version', d.version));
  v_id := (v_saved ->> 'revision_id')::uuid;
  select * into pr from drink_plan_revisions where id = v_id;
  if pr.plan_json -> coalesce(q.jjeri_input ->> 'format','jjeri_class') is distinct from
      q.result -> 'plan' -> coalesce(q.jjeri_input ->> 'format','jjeri_class') then
    perform drinks_fail('jjeri_directive_invalid', '저장 경로가 째리 지시서를 보존하지 못했습니다');
  end if;
  perform drinks_plan_action(jsonb_build_object('revision_id', v_id, 'expected_version', pr.version, 'action', 'submit'));
  select * into pr from drink_plan_revisions where id = v_id;
  perform drinks_plan_action(jsonb_build_object('revision_id', v_id, 'expected_version', pr.version, 'action', 'approve',
    'reason', coalesce(v_note, '째리 지시서와 승인 근거를 직접 대조함')));
  insert into drink_jjeri_approvals (request_id, plan_revision_id) values (q.id, v_id);
  return jsonb_build_object('revision_id', v_id, 'existing', false);
end $$;

create function drinks_jjeri_generation_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; r drink_topic_reviews; q drink_develop_requests; d drink_deliverables; pr drink_plan_revisions;
  v_id uuid; v_current boolean;
begin
  perform drinks_reap_develop();
  select * into t from drink_topics where id = drinks_uuid(p, 'topic_id');
  if not found then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  select * into r from drink_topic_reviews where id = t.approved_review_id;
  v_current := coalesce(t.status in ('ready','selected') and r.status = 'approved'
    and r.approved_hash = r.input_hash and drinks_approval_valid(r.id)
    and cardinality(drinks_text_array(r.brief -> 'required_claims' -> 'video')) > 0, false);
  select * into q from drink_develop_requests where topic_id = t.id and kind = 'jjeri' order by created_at desc, id desc limit 1;
  select plan_revision_id into v_id from drink_jjeri_approvals where request_id = q.id;
  select * into d from drink_deliverables where topic_id = t.id and format = 'video' and locale = 'ko';
  select * into pr from drink_plan_revisions where id = d.current_revision_id;
  return jsonb_build_object('current_review', case when v_current then jsonb_build_object('id', r.id, 'hash', r.approved_hash) end,
    'can_request', coalesce(v_current and t.status = 'selected' and 'video' = any(t.selected_formats)
      and t.selected_review_id = r.id, false),
    'max_usd', drinks_develop_limits() -> 'max_usd_per_request', 'max_calls', 2, 'revision_id', v_id,
    'budgets', coalesce((select jsonb_agg(drinks_develop_budget_json(s.budget_id) order by s.created_at desc)
      from drink_develop_budget_state s where s.status = 'open' and not s.expired and s.remaining_usd > 0), '[]'),
    'request_current', coalesce(v_current and q.review_id = r.id
      and q.jjeri_input ->> 'review_hash' = r.approved_hash, false),
    'can_approve', coalesce(v_current and t.status = 'selected' and 'video' = any(t.selected_formats) and t.selected_review_id = r.id
      and q.status = 'succeeded' and q.review_id = r.id and q.jjeri_input ->> 'review_hash' = r.approved_hash and v_id is null
      and not coalesce(pr.plan_status in ('draft','in_review') and pr.blocked_at is null, false)
      and (d.id, d.version, d.current_revision_id, pr.version, pr.input_hash) is not distinct from
        ((q.jjeri_input ->> 'deliverable_id')::uuid, (q.jjeri_input ->> 'deliverable_version')::int,
         (q.jjeri_input ->> 'current_revision_id')::uuid, (q.jjeri_input ->> 'current_plan_version')::int,
         q.jjeri_input ->> 'current_plan_hash'), false),
    'request', case when q.id is not null then drinks_develop_request_json(q) || jsonb_build_object(
      'format', coalesce(q.jjeri_input ->> 'format','jjeri_class'),
      'lesson', q.jjeri_input -> 'lesson', 'max_usd', q.jjeri_input -> 'max_usd') end);
end $$;

-- Keep legacy views on their original request kinds.
create or replace function drinks_develop_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id');
begin
  perform drinks_reap_develop();
  if not exists (select 1 from drink_topics where id = v_topic) then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  return jsonb_build_object('topic_id', v_topic,
    'requests', coalesce((select jsonb_agg(drinks_develop_request_json(x) order by x.created_at desc)
      from drink_develop_requests x where x.id in (select id from drink_develop_requests where topic_id = v_topic and kind <> 'jjeri'
        order by created_at desc limit 10)), '[]'),
    'active', (select drinks_develop_request_json(a) from drink_develop_requests a where a.topic_id = v_topic and a.kind <> 'jjeri' and a.status in ('queued','running')
      order by a.created_at desc limit 1),
    'budgets', coalesce((select jsonb_agg(drinks_develop_budget_json(s.budget_id) order by s.created_at desc)
      from drink_develop_budget_state s where s.status = 'open' and not s.expired), '[]'),
    'pick', (select to_jsonb(k) from drink_topic_picks k where k.topic_id = v_topic),
    'picks', coalesce((select jsonb_agg(to_jsonb(k) order by k.created_at, k.format_intent) from drink_topic_format_picks k where k.topic_id = v_topic), '[]'),
    'limits', drinks_develop_limits());
end $$;

create or replace function drinks_studio_status_0076(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id'); t drink_topics; r drink_topic_reviews;
begin
  perform drinks_reap_develop();
  select * into t from drink_topics where id = v_topic;
  if not found then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  return jsonb_build_object(
    'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'status', t.status, 'version', t.version, 'categories', to_jsonb(t.categories)),
    'picks', coalesce((select jsonb_agg(jsonb_build_object('format_intent', k.format_intent, 'approved_at', k.approved_at, 'recommended_format', k.recommended_format,
        'recommended_reason', k.recommended_reason) order by k.created_at) from drink_topic_format_picks k where k.topic_id = t.id), '[]'::jsonb),
    'active', (select drinks_develop_request_json(a) - 'result' from drink_develop_requests a where a.topic_id = t.id and a.kind <> 'jjeri' and a.status in ('queued','running')
      order by a.created_at desc limit 1),
    'last', (select drinks_develop_request_json(l) - 'result' || jsonb_build_object('result_cost', l.result -> 'cost',
        'factcheck', l.result -> 'factcheck', 'excluded', l.result -> 'excluded', 'has_unsaved', l.result ? 'unsaved_evidence' or l.result ? 'unsaved_plan')
      from drink_develop_requests l where l.topic_id = t.id and l.kind <> 'jjeri' order by l.created_at desc limit 1),
    'recoveries_24h', (select count(*) from drink_develop_requests where topic_id = t.id and recovery_of is not null and created_at > now() - interval '24 hours'),
    'limits', drinks_studio_limits(),
    'review', case when r.id is null then null else jsonb_build_object('review_id', r.id, 'status', r.status, 'version', r.version, 'blank', drinks_review_is_blank(r),
      'core_claim_ids', r.brief -> 'selected_claim_ids', 'core_takeaway', r.brief -> 'core_takeaway', 'claims', r.evidence_pack -> 'claims',
      'readiness', r.readiness) end,
    'plans', coalesce((select jsonb_agg(jsonb_build_object('plan_revision_id', pl.id, 'format', pl.format, 'version', pl.version, 'plan_status', pl.plan_status,
        'blocked', pl.blocked_at is not null, 'blocked_reason', pl.blocked_reason, 'plan_json', pl.plan_json, 'topic_review_id', pl.topic_review_id,
        'current', d.current_revision_id = pl.id, 'updated_at', pl.updated_at,
        'unverified_numbers', drinks_studio_unverified_numbers(pl.plan_json, (select x from drink_topic_reviews x where x.id = pl.topic_review_id)),
        'jobs', coalesce((select jsonb_agg(jsonb_build_object('job_id', j.id, 'status', j.status, 'error_code', j.error_code, 'attempt_no', j.attempt_no,
            'created_at', j.created_at, 'finished_at', j.finished_at) order by j.created_at desc) from drink_production_jobs j where j.plan_revision_id = pl.id), '[]'::jsonb))
      order by pl.created_at desc)
      from drink_plan_revisions pl join drink_deliverables d on d.id = pl.deliverable_id
      where pl.topic_id = t.id and (d.current_revision_id = pl.id or pl.plan_status = 'approved')), '[]'::jsonb),
    'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher, 'url', s.canonical_url,
        'role', ts.role, 'rights_status', drinks_snapshot_meta(s.id) ->> 'rights_status', 'usage_terms', s.usage_terms) order by ts.created_at)
      from drink_topic_sources ts join drink_source_snapshots s on s.id = ts.snapshot_id where ts.topic_id = t.id), '[]'::jsonb));
end $$;

-- Preserve the ordinary studio workflow while Jjeri owns a separate preview and retry path.

-- Replacements use the last local definitions through 0091. Only the request scope changes.

-- 0072
create or replace function drinks_approve_content(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions; pk drink_topic_format_picks;
  v_amount numeric; v_note text := drinks_text(p, 'note'); v_id uuid; v_sel jsonb; v_planned jsonb;
  v_intent text := drinks_text(p, 'format_intent'); v_before text; v_formats text[]; v_week date; v_fresh boolean;
begin
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_topic_version'));
  v_before := t.status;
  v_id := drinks_uuid(p, 'review_id');
  select * into r from drink_topic_reviews where id = v_id for update;
  if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거 버전이 아닙니다'); end if;
  v_id := drinks_uuid(p, 'plan_revision_id');
  select * into pr from drink_plan_revisions where id = v_id;
  if not found or pr.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 제작안이 아닙니다'); end if;
  select * into d from drink_deliverables where id = pr.deliverable_id for update;
  select * into pr from drink_plan_revisions where id = v_id for update;
  if r.version <> drinks_int(p, 'expected_review_version') or pr.version <> drinks_int(p, 'expected_plan_version') then
    perform drinks_fail('version_conflict', '보고 있던 근거·대본이 다른 곳에서 바뀌었습니다 — 화면을 새로 불러와 다시 확인하세요');
  end if;
  -- 어느 형식을 승인하나: 입력 → 없으면 대표 형식(옛 호출).
  v_intent := coalesce(v_intent, drinks_representative_intent(t.id));
  if v_intent is null then perform drinks_fail('format_not_selected', '[이걸로]로 형식을 고른 소재만 한 번에 승인합니다 — 기존 탭을 쓰세요'); end if;
  select * into pk from drink_topic_format_picks where topic_id = t.id and format_intent = v_intent for update;
  if not found then perform drinks_fail('format_not_selected', '[이걸로]로 고르지 않은 형식입니다 — 형식을 먼저 더하세요'); end if;
  if drinks_intent_format(pk.format_intent) is null or pr.format <> drinks_intent_format(pk.format_intent) then
    perform drinks_fail('format_not_selected', '고른 형식의 제작안이 아닙니다 — 형식을 다시 고르거나 그 형식의 대본을 만드세요');
  end if;
  if pk.approved_at is not null then
    perform drinks_fail('invalid_state', '이 형식은 이미 승인됐습니다');
  end if;
  v_fresh := t.status = 'researching';
  if v_fresh then
    -- A. 근거가 아직 승인 전 — 0065 와 같은 검사.
    if t.current_review_id is distinct from r.id then perform drinks_fail('review_not_current', '최신 근거 버전이 아닙니다'); end if;
    if r.status not in ('draft','in_review') then perform drinks_fail('invalid_state', '이미 결정된 근거 버전입니다 — 기존 탭을 쓰세요'); end if;
    if not pr.drafted_from_unapproved or pr.plan_status <> 'draft' then
      perform drinks_fail('invalid_state', '승인 전 근거로 만든 작성 중 대본만 한 번에 승인합니다');
    end if;
  elsif t.status in ('ready','selected') then
    -- B. 다른 형식이 먼저 승인돼 근거는 이미 승인본이다. 그 승인본으로 쓴 작성 중 제작안만.
    if r.id is distinct from t.approved_review_id then perform drinks_fail('review_not_current', '지금 승인된 근거 버전이 아닙니다'); end if;
    if r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then
      perform drinks_fail('review_not_approved', '승인되고 지금도 유효한 근거 버전으로만 제작안을 승인합니다');
    end if;
    if pr.plan_status <> 'draft' then perform drinks_fail('invalid_state', '작성 중인 제작안만 승인합니다'); end if;
  else
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재는 승인할 수 없습니다');
  end if;
  if d.current_revision_id is distinct from pr.id then perform drinks_fail('plan_not_current', '최신 대본이 아닙니다'); end if;
  if pr.blocked_at is not null then
    perform drinks_fail('plan_blocked', '이 대본을 만든 뒤 근거가 바뀌었습니다 — 이 근거로 대본을 다시 만들어야 승인할 수 있습니다');
  end if;
  -- ★ 대본이 기댄 근거가 바로 지금 승인하는(또는 승인된) 근거인가. 트리거가 차단하지만, 승인 직전에 값으로 한 번 더 잰다.
  --   승인된 근거로 쓴 옛 제작안(drinks_save_plan 경로)은 근거 값을 적지 않았다 — 승인본은 내용이 고정이라 버전 일치만 잰다.
  if pr.topic_review_id is distinct from r.id
      or ((pr.drafted_from_unapproved or pr.evidence_content_hash is not null)
          and pr.evidence_content_hash is distinct from drinks_evidence_content_hash(r.evidence_pack, r.brief)) then
    perform drinks_fail('plan_stale', '대본이 지금 근거 내용으로 만들어진 것이 아닙니다 — 이 근거로 대본을 다시 만드세요');
  end if;
  if exists (select 1 from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', '초안을 만드는 중입니다 — 끝난 뒤에 승인하세요');
  end if;
  -- 승인 금액: 기록만 한다. 결재를 열지 않는다. 상한은 유료 결재 1건 상한(0054)과 같다. 카드뉴스는 로컬 렌더 0원이라 금액을 받지 않는다.
  if pr.format = 'video' then
    v_amount := drinks_num(p, 'approved_amount_usd');
    if v_amount <= 0 or v_amount > (drinks_spend_limits() ->> 'max_cap_usd')::numeric then
      perform drinks_fail('invalid_input', '승인 금액은 0 보다 크고 $' || (drinks_spend_limits() ->> 'max_cap_usd') || ' 이하여야 합니다');
    end if;
  end if;

  if v_fresh then
    -- 1) 근거: 작성 중 → 검토 → 승인. drinks_review_action 이 필수 조건(주장별 확인·핵심 메시지·점수·인용·사용 조건)을 다시 잰다.
    if r.status = 'draft' then
      perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'submit'));
      select * into r from drink_topic_reviews where id = r.id;
    end if;
    perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'approve', 'reason', v_note));
    select * into r from drink_topic_reviews where id = r.id;
    v_formats := array[pr.format];
    v_week := pk.editorial_week;
  else
    -- 1') 근거는 이미 승인본. 편성 형식에 이 형식을 더한다(합집합). 편성 주차는 이미 편성됐으면 그대로, 아니면 이 형식의 선택 주차.
    v_formats := coalesce(t.selected_formats, '{}'::text[]);
    if not pr.format = any(v_formats) then v_formats := v_formats || pr.format; end if;
    v_week := case when t.status = 'selected' then t.editorial_week else pk.editorial_week end;
  end if;
  -- 2) 편성. drinks_select 가 65점 기준·형식 적합성·필수 주장을 다시 잰다.
  select * into t from drink_topics where id = t.id;
  v_sel := drinks_select(jsonb_build_object('topic_id', t.id, 'expected_version', t.version, 'review_id', r.id,
    'review_input_hash', r.approved_hash, 'formats', to_jsonb(v_formats), 'editorial_week', to_char(v_week, 'YYYY-MM-DD'),
    'score_exception_reason', drinks_text(p, 'score_exception_reason'), 'format_exceptions', coalesce(p -> 'format_exceptions', '{}'::jsonb)));
  -- 3) 대본: 제작안 해시를 승인된 근거 기준으로 다시 잰다(본문은 그대로) → 제출 → 승인.
  update drink_plan_revisions set updated_at = now() where id = pr.id returning * into pr;
  perform drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'submit'));
  select * into pr from drink_plan_revisions where id = pr.id;
  v_planned := drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'approve', 'reason', v_note));
  select * into pr from drink_plan_revisions where id = pr.id;

  update drink_topic_format_picks set approved_at = now(), approved_amount_usd = v_amount where topic_id = t.id and format_intent = pk.format_intent;
  update drink_topic_picks set approved_at = now(), approved_amount_usd = v_amount where topic_id = t.id and format_intent = pk.format_intent and approved_at is null;
  select * into t from drink_topics where id = t.id;
  perform drinks_log(t.id, 'topic', t.id, 'content_approved', v_before, t.status, pr.id::text, v_note,
    jsonb_build_object('review_id', r.id, 'review_hash', r.approved_hash, 'plan_revision_id', pr.id, 'plan_hash', pr.approved_hash,
      'format_intent', pk.format_intent, 'approved_amount_usd', v_amount, 'spend_approval_opened', false, 'formats', to_jsonb(v_formats)));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version, 'review_id', r.id, 'review_status', r.status,
    'plan_revision_id', pr.id, 'plan_status', pr.plan_status, 'selected_formats', v_sel -> 'selected_formats',
    'editorial_week', v_sel -> 'editorial_week', 'approved_amount_usd', v_amount, 'coverage', v_planned -> 'coverage',
    'format_intent', pk.format_intent, 'spend_approval_opened', false);
end $$;

-- 0076
create or replace function drinks_save_review(p jsonb) returns jsonb language plpgsql as $$
declare
  v_topic uuid := drinks_uuid(p, 'topic_id'); v_review uuid := drinks_uuid(p, 'review_id', false);
  t drink_topics; r drink_topic_reviews; base drink_topic_reviews; v_no int;
  v_pack jsonb; v_brief jsonb; v_scores jsonb;
begin
  -- 0076: 사람 저장은 AI 가 이 소재의 초안을 만드는 중이면 거절한다(화면 잠금에만 기대지 않는다). 워커의 저장(drinks_develop_save_evidence)은
  --       같은 트랜잭션에서 drinks.worker_save=on 을 켜고 부른다 — 그 요청의 임대를 이미 확인한 뒤다.
  perform drinks_reap_develop();
  if coalesce(current_setting('drinks.worker_save', true), '') <> 'on'
      and exists (select 1 from drink_develop_requests where kind in ('evidence','plan') and topic_id = v_topic and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', 'AI 가 이 소재의 초안을 만드는 중입니다 — 끝난 뒤에 저장하세요(지금 저장하면 그 결과와 부딪힙니다)');
  end if;
  if v_review is null then
    t := drinks_lock_topic(v_topic, drinks_int(p, 'expected_topic_version'));
  else
    t := drinks_lock_topic(v_topic, null, false);
  end if;
  if t.status not in ('researching','ready','selected') then
    perform drinks_fail('invalid_state', '조사 후보로 고른 소재만 근거·기획을 작성할 수 있습니다');
  end if;
  if v_review is null then
    if exists (select 1 from drink_topic_reviews where topic_id = t.id and status = 'draft') then
      perform drinks_fail('draft_exists', '작성 중인 버전이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
    -- 검토 중인 버전을 두고 새 버전을 만들면 그 검토가 고아가 된다(승인·변경요청 모두 불가). 먼저 결정하게 한다.
    if exists (select 1 from drink_topic_reviews where id = t.current_review_id and status = 'in_review') then
      perform drinks_fail('review_in_progress', '검토 중인 버전이 있습니다 — 승인하거나 변경 요청한 뒤 새 버전을 만드세요');
    end if;
    if t.current_review_id is not null then
      select * into base from drink_topic_reviews where id = t.current_review_id;
    end if;
    v_pack := drinks_normalize_pack(t.id, coalesce(p -> 'evidence_pack', base.evidence_pack, '{"claims": []}'));
    v_brief := drinks_normalize_brief(coalesce(p -> 'brief', base.brief));
    v_scores := drinks_check_scores(coalesce(p -> 'scores', base.scores), true);
    select coalesce(max(revision_no), 0) + 1 into v_no from drink_topic_reviews where topic_id = t.id;
    insert into drink_topic_reviews (topic_id, revision_no, based_on_review_id, scores, evidence_pack, brief)
      values (t.id, v_no, base.id, v_scores, v_pack, v_brief) returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    update drink_topics set current_review_id = r.id where id = t.id returning * into t;
    perform drinks_log(t.id, 'review', r.id, 'review_created', null, 'draft', r.input_hash, null,
      jsonb_build_object('revision_no', v_no, 'based_on', base.id));
  else
    select * into r from drink_topic_reviews where id = v_review for update;
    if not found or r.topic_id <> t.id then
      perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다');
    end if;
    if r.status <> 'draft' then
      perform drinks_fail('immutable', '검토 중·승인된 버전은 수정할 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    if r.version <> drinks_int(p, 'expected_version') then
      perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 화면을 새로 불러오세요',
        jsonb_build_object('current_version', r.version));
    end if;
    update drink_topic_reviews set
      evidence_pack = drinks_normalize_pack(t.id, coalesce(p -> 'evidence_pack', r.evidence_pack)),
      brief = drinks_normalize_brief(coalesce(p -> 'brief', r.brief)),
      scores = drinks_check_scores(coalesce(p -> 'scores', r.scores), true)
      where id = r.id returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    perform drinks_log(t.id, 'review', r.id, 'review_saved', 'draft', 'draft', r.input_hash, null);
  end if;
  return jsonb_build_object('review_id', r.id, 'revision_no', r.revision_no, 'version', r.version,
    'input_hash', r.input_hash, 'score', r.score, 'readiness', r.readiness);
end $$;

-- 0076
create or replace function drinks_studio_recover_topic(p_topic uuid, p_actor text) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; last drink_develop_requests; r drink_topic_reviews; bs jsonb; v_n int; v_res jsonb; v_budget uuid; v_lim int := (drinks_studio_limits() ->> 'max_recoveries_24h')::int;
begin
  select * into t from drink_topics where id = p_topic for update;
  if not found or t.status <> 'researching' then return null; end if;
  if exists (select 1 from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running')) then return null; end if;
  select * into last from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id order by created_at desc limit 1;
  if not found or last.status <> 'failed' or not drinks_studio_recoverable(last.error_code) then return null; end if;
  select count(*) into v_n from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and recovery_of is not null and created_at > now() - interval '24 hours';
  if v_n >= v_lim then return jsonb_build_object('code', 'recovery_limit', 'recoveries', v_n); end if;
  v_budget := last.budget_id;
  bs := case when v_budget is null then null else drinks_develop_budget_json(v_budget) end;
  -- 원래 결재가 주간 한도(0073)이고 주가 바뀌어 끝났으면(또는 결재 없이 들어간 옛 요청이면) 이번 주 한도로 잇는다(같은 종류의 자동 한도 — 새 결재를 지어내지 않는다).
  if bs is null or ((bs ->> 'expired')::boolean
      and exists (select 1 from drink_develop_budgets b where b.id = v_budget and b.stage like 'weekly:%')) then
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
    bs := drinks_develop_budget_json(v_budget);
  end if;
  if bs is null or bs ->> 'status' <> 'open' or (bs ->> 'expired')::boolean or (bs ->> 'remaining_usd')::numeric <= 0 then
    return jsonb_build_object('code', 'budget_unavailable');
  end if;
  begin
    if last.kind = 'evidence' then
      v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', last.chain));
    else
      select * into r from drink_topic_reviews where id = t.current_review_id;
      if not found or r.status <> 'draft' then return null; end if;
      if last.supersedes_plan_id is not null then
        -- 수정 지시 재시도: 사람이 그 뒤에 초안을 고쳤으면 다시 하지 않는다.
        if not exists (select 1 from drink_plan_revisions where id = last.supersedes_plan_id and plan_status = 'draft' and blocked_at is null
            and version = last.supersedes_plan_version) then return null; end if;
        insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent, instruction, supersedes_plan_id, supersedes_plan_version)
          values (t.id, 'plan', r.id, v_budget, true, last.format_intent, last.instruction, last.supersedes_plan_id, last.supersedes_plan_version)
          returning jsonb_build_object('request_id', id) into v_res;
      else
        v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true,
          'format_intent', last.format_intent));
      end if;
    end if;
  exception when raise_exception then
    if sqlerrm not like 'drinks:%' then raise; end if;
    return jsonb_build_object('code', split_part(sqlerrm, ':', 2), 'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
  end;
  update drink_develop_requests set recovery_of = last.id where id = (v_res ->> 'request_id')::uuid;
  perform drinks_log(t.id, 'topic', t.id, 'develop_recovered', 'failed', 'queued', (v_res ->> 'request_id'), last.error_code,
    jsonb_build_object('recovery_of', last.id, 'kind', last.kind, 'actor', p_actor, 'recoveries_24h', v_n + 1));
  return jsonb_build_object('request_id', v_res ->> 'request_id', 'recovery_of', last.id, 'kind', last.kind);
end $$;

-- 0076
create or replace function drinks_studio_recover_all(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare x record; v_out jsonb := '[]'::jsonb; v_res jsonb;
begin
  perform drinks_reap_develop();
  for x in select distinct on (topic_id) topic_id, status, error_code, finished_at from drink_develop_requests
      where kind in ('evidence','plan') and created_at > now() - interval '1 day' order by topic_id, created_at desc loop
    if x.status = 'failed' and x.finished_at > now() - interval '2 hours' and drinks_studio_recoverable(x.error_code) then
      v_res := drinks_studio_recover_topic(x.topic_id, 'worker');
      if v_res ? 'request_id' then v_out := v_out || jsonb_build_object('topic_id', x.topic_id) || v_res; end if;
    end if;
  end loop;
  return jsonb_build_object('recovered', v_out);
end $$;

-- 0076
create or replace function drinks_studio_prepare(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id', false); v_cand uuid := drinks_uuid(p, 'candidate_id', false);
  v_fmt text := coalesce(drinks_text(p, 'format_intent'), 'card'); c drink_discovery_candidates; t drink_topics; r drink_topic_reviews;
  v_budget uuid; v_week date := (now() at time zone 'Asia/Seoul')::date; v_res jsonb; v_rec jsonb; v_action text := 'none'; last drink_develop_requests;
  v_intent text;
begin
  perform drinks_reap_develop();
  if v_fmt not in ('card','explainer') then perform drinks_fail('invalid_input', '초안 형식은 카드뉴스·설명형 중 하나입니다'); end if;
  v_week := v_week - (extract(isodow from v_week)::int - 1);
  if (v_topic is null) = (v_cand is null) then perform drinks_fail('invalid_input', '후보 또는 소재 중 하나를 지정하세요'); end if;
  if v_cand is not null then
    select * into c from drink_discovery_candidates where id = v_cand;
    if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
    v_topic := c.promoted_topic_id;
  end if;
  if v_topic is null then
    -- 새 후보: 소재로 올리고 형식 하나(추천)를 의도로 적고 근거 요청까지(0072 [이걸로] 그대로). 편성 주차 = 이번 주, 예산 = 이번 주 AI 초안 한도.
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
    v_res := drinks_pick_topic(jsonb_build_object('candidate_id', v_cand, 'expected_version', c.version, 'formats', jsonb_build_array(v_fmt), 'editorial_week', to_char(v_week, 'YYYY-MM-DD'),
      'budget_id', v_budget, 'recommended_format', v_fmt, 'recommended_reason', left(drinks_text(p, 'recommended_reason'), 500),
      'lane', 'reader_question', 'title', coalesce(drinks_text(p, 'title'), c.key_question), 'question', coalesce(drinks_text(p, 'question'), c.key_question))
      || jsonb_strip_nulls(jsonb_build_object('categories', p -> 'categories', 'reader_value', drinks_text(p, 'reader_value'),
        'confirm_not_duplicate', p -> 'confirm_not_duplicate')));
    return jsonb_build_object('topic_id', v_res ->> 'topic_id', 'action', 'picked', 'queued', coalesce((v_res -> 'chain' ->> 'queued')::boolean, false),
      'existing', coalesce((v_res -> 'chain' ->> 'existing')::boolean, false), 'pick', v_res);
  end if;
  t := drinks_lock_topic(v_topic, null, false);
  if exists (select 1 from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running')) then
    return jsonb_build_object('topic_id', t.id, 'action', 'already_running', 'queued', false, 'existing', true);
  end if;
  if exists (select 1 from drink_plan_revisions pl join drink_deliverables d on d.id = pl.deliverable_id
      where pl.topic_id = t.id and d.current_revision_id = pl.id and pl.blocked_at is null and pl.plan_status in ('draft','approved')) then
    return jsonb_build_object('topic_id', t.id, 'action', 'draft_ready', 'queued', false, 'existing', true);
  end if;
  if t.status not in ('triaged','researching','ready','selected') then
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재입니다 — 다른 소재를 고르세요');
  end if;
  v_rec := drinks_studio_recover_topic(t.id, 'studio');
  if v_rec ? 'request_id' then
    return jsonb_build_object('topic_id', t.id, 'action', 'recovered', 'queued', true, 'existing', false, 'recovery', v_rec);
  end if;
  if v_rec ? 'code' then
    return jsonb_build_object('topic_id', t.id, 'action', 'needs_choice', 'queued', false, 'code', v_rec ->> 'code', 'message', v_rec ->> 'message');
  end if;
  select * into last from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id order by created_at desc limit 1;
  if found and last.status in ('blocked','failed') then
    -- 자동으로 다시 하지 않는 실패(자료 부족·검사 실패·예산 등). 같은 실패를 되풀이하지 않는다 — 화면이 이유와 선택지를 보여 준다.
    return jsonb_build_object('topic_id', t.id, 'action', 'stopped', 'queued', false, 'code', last.error_code);
  end if;
  v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  if not exists (select 1 from drink_topic_format_picks where topic_id = t.id and format_intent in ('card','explainer')) then
    v_res := drinks_pick_topic(jsonb_build_object('topic_id', t.id, 'formats', jsonb_build_array(v_fmt), 'editorial_week', to_char(v_week, 'YYYY-MM-DD'),
      'budget_id', v_budget, 'recommended_format', v_fmt));
    return jsonb_build_object('topic_id', t.id, 'action', 'picked', 'queued', coalesce((v_res -> 'chain' ->> 'queued')::boolean, false),
      'existing', coalesce((v_res -> 'chain' ->> 'existing')::boolean, false), 'pick', v_res);
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if t.status = 'researching' and r.id is not null and r.status = 'draft' and not drinks_review_is_blank(r) then
    -- 근거는 있고 초안만 없다(옛 흐름에서 멈춘 소재): 고른 형식의 초안을 이 근거로 만든다.
    select format_intent into v_intent from drink_topic_format_picks where topic_id = t.id and format_intent in ('card','explainer') order by created_at limit 1;
    v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true, 'format_intent', v_intent));
    v_action := 'plan_requested';
  elsif t.status = 'researching' then
    v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', true));
    v_action := 'evidence_requested';
  else
    -- 근거가 이미 승인된 소재(ready/selected)에 카드 초안만 없다: 승인된 근거로 카드 초안을 만든다(0072 일반 대본 요청 그대로).
    v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'format_intent', 'card'));
    v_action := 'plan_requested';
  end if;
  return jsonb_build_object('topic_id', t.id, 'action', v_action, 'queued', true, 'existing', coalesce((v_res ->> 'existing')::boolean, false),
    'request_id', v_res ->> 'request_id');
end $$;

-- 0076
create or replace function drinks_studio_save_draft(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; v_pages jsonb := p -> 'pages'; v_new jsonb; v_out jsonb := '[]'::jsonb;
  el jsonb; i int := 0; ed jsonb; v_plan jsonb;
begin
  perform drinks_reap_develop();
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pr from drink_plan_revisions where id = pr.id for update;
  if pr.format <> 'carousel' then perform drinks_fail('invalid_state', '이 화면에서는 카드뉴스 초안만 고칩니다'); end if;
  if pr.plan_status <> 'draft' or pr.blocked_at is not null then
    perform drinks_fail('immutable', '이미 생성에 쓴(또는 바뀐) 초안입니다 — 고치려면 [초안 수정하기]로 새 초안을 만드세요');
  end if;
  if pr.version <> drinks_int(p, 'expected_version') then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 새로 불러온 뒤 다시 고치세요', jsonb_build_object('current_version', pr.version));
  end if;
  if exists (select 1 from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', 'AI 가 초안을 만드는 중입니다 — 끝난 뒤에 저장하세요');
  end if;
  if jsonb_typeof(v_pages) is distinct from 'array' or jsonb_array_length(v_pages) <> jsonb_array_length(pr.plan_json -> 'pages') then
    perform drinks_fail('invalid_input', '페이지 수는 바꿀 수 없습니다 — 글만 고칩니다');
  end if;
  for el in select * from jsonb_array_elements(pr.plan_json -> 'pages') loop
    i := i + 1;
    ed := v_pages -> (i - 1);
    if jsonb_typeof(ed) <> 'object' then perform drinks_fail('invalid_input', i || '번 페이지 형식이 잘못됐습니다'); end if;
    if (el ->> 'role') <> 'source' and nullif(btrim(coalesce(ed ->> 'heading', '')), '') is null then
      perform drinks_fail('invalid_input', i || '번 페이지 제목이 비었습니다');
    end if;
    if length(coalesce(ed ->> 'heading', '')) > 120 or length(coalesce(ed ->> 'body', '')) > 1200 then
      perform drinks_fail('invalid_input', i || '번 페이지 글이 너무 깁니다');
    end if;
    v_out := v_out || jsonb_build_array(el || jsonb_build_object('heading', btrim(coalesce(ed ->> 'heading', el ->> 'heading')),
      'body', nullif(btrim(coalesce(ed ->> 'body', '')), '')));
  end loop;
  v_new := jsonb_set(pr.plan_json, '{pages}', v_out);
  if jsonb_typeof(p -> 'reel') = 'object' then
    v_new := jsonb_set(v_new, '{reel}', coalesce(pr.plan_json -> 'reel', '{}'::jsonb)
      || jsonb_strip_nulls(jsonb_build_object('hook_title', nullif(btrim(p -> 'reel' ->> 'hook_title'), ''), 'share_line', nullif(btrim(p -> 'reel' ->> 'share_line'), ''))));
  end if;
  select * into r from drink_topic_reviews where id = pr.topic_review_id;
  v_plan := drinks_validate_plan(pr.format, v_new, r);
  if v_plan is not distinct from pr.plan_json then
    return jsonb_build_object('plan_revision_id', pr.id, 'version', pr.version, 'changed', false, 'unverified_numbers', drinks_studio_unverified_numbers(pr.plan_json, r));
  end if;
  update drink_plan_revisions set plan_json = v_plan where id = pr.id returning * into pr;
  perform drinks_log(t.id, 'plan', pr.id, 'studio_draft_saved', 'draft', 'draft', pr.input_hash, null,
    jsonb_build_object('actor', 'operator', 'edited_by', 'human'));
  return jsonb_build_object('plan_revision_id', pr.id, 'version', pr.version, 'changed', true, 'input_hash', pr.input_hash,
    'unverified_numbers', drinks_studio_unverified_numbers(pr.plan_json, r));
end $$;

-- 0082
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
    select * into q from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running') limit 1;
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
    select * into q from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running') limit 1;
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
  select * into q from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running') limit 1;
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

-- 0084
create or replace function drinks_apply_rescue(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_req uuid := drinks_uuid(p, 'request_id'); last drink_develop_requests; t drink_topics; rs jsonb;
  v_q text; v_title text; v_budget uuid; bs jsonb; v_res jsonb;
begin
  select * into last from drink_develop_requests where id = v_req;
  if not found then perform drinks_fail('not_found', '개발 요청을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(last.topic_id, null, false);
  if last.kind <> 'evidence' or last.status <> 'blocked' or not (last.result ? 'rescue') then
    perform drinks_fail('invalid_state', '해결안이 있는 막힌 근거 요청이 아닙니다');
  end if;
  if exists (select 1 from drink_develop_requests x where x.kind in ('evidence','plan') and x.topic_id = t.id and x.created_at > last.created_at) then
    perform drinks_fail('stale_rescue', '이 소재에 더 최근 요청이 있습니다 — 화면을 새로 불러오세요');
  end if;
  rs := last.result -> 'rescue';
  v_q := left(btrim(coalesce(rs ->> 'question', '')), 1000);
  v_title := left(btrim(coalesce(nullif(rs ->> 'title', ''), v_q)), 200);
  if v_q = '' then perform drinks_fail('invalid_state', '해결안에 질문이 없습니다'); end if;
  v_budget := last.budget_id;
  bs := case when v_budget is null then null else drinks_develop_budget_json(v_budget) end;
  -- drinks_studio_recover_topic 과 같은 규칙: 주간 한도가 끝났으면 이번 주 한도로 잇는다(새 결재를 지어내지 않는다).
  if bs is null or ((bs ->> 'expired')::boolean
      and exists (select 1 from drink_develop_budgets b where b.id = v_budget and b.stage like 'weekly:%')) then
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  end if;
  perform drinks_log(t.id, 'topic', t.id, 'rescue_applied', t.question, v_q, last.id::text, coalesce(rs ->> 'kind', 'reframe'),
    jsonb_build_object('old_title', t.title, 'new_title', v_title, 'actor', coalesce(drinks_text(p, 'actor'), 'operator')));
  update drink_topics set question = v_q, title = v_title, version = version + 1 where id = t.id;
  v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', last.chain));
  update drink_develop_requests set recovery_of = last.id where id = (v_res ->> 'request_id')::uuid;
  return v_res || jsonb_build_object('rescued_from', last.id, 'question', v_q, 'title', v_title);
end $$;

-- 0087
create or replace function drinks_studio_edit_scene(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; d drink_deliverables; e drink_explainer_episodes; np drink_plan_revisions;
  v_edits jsonb := p -> 'edits'; ed jsonb; v_n int; v_field text; v_text text;
  v_key text; v_json jsonb; v_plan jsonb; v_no int; v_hash text; v_root uuid; v_log jsonb := '[]'::jsonb;
begin
  -- 한 장면(카드는 한 장)의 칸 여러 개를 한 번에 — 제목만 저장되고 본문은 실패하는 반쪽 저장이 없다(코덱스 리뷰).
  if jsonb_typeof(v_edits) is distinct from 'array' or jsonb_array_length(v_edits) not between 1 and 10 then
    perform drinks_fail('invalid_input', '고칠 글(edits)을 1~10개 보내 주세요');
  end if;
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  -- 잠금 순서: topic → deliverable → plan(0050 규칙). drinks_explainer_request_plan 도 0087 부터 같은 순서다.
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into d from drink_deliverables where id = pr.deliverable_id for update;
  select * into pr from drink_plan_revisions where id = pr.id for update;
  if pr.version <> drinks_int(p, 'expected_version') then perform drinks_fail('version_conflict', '초안이 다른 곳에서 바뀌었습니다 — 새로 불러오세요'); end if;
  if pr.blocked_at is not null then perform drinks_fail('plan_blocked', '더 이상 쓰지 않는 초안입니다 — 새로 불러오세요'); end if;
  if d.current_revision_id is distinct from pr.id then perform drinks_fail('plan_not_current', '최신 초안이 아닙니다 — 새로 불러오세요'); end if;
  if exists (select 1 from drink_develop_requests where kind in ('evidence','plan') and topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_running', '초안을 만드는 중입니다 — 끝난 뒤에 고치세요');
  end if;
  v_key := case pr.format when 'video' then 'scenes' else 'pages' end;
  v_json := pr.plan_json;
  for ed in select * from jsonb_array_elements(v_edits) loop
    v_n := drinks_int(ed, 'n'); v_field := drinks_text(ed, 'field'); v_text := btrim(coalesce(drinks_text(ed, 'text'), ''));
    if pr.format = 'video' and v_field is distinct from 'narration' then perform drinks_fail('invalid_input', '릴스는 장면 대사(narration)만 고칠 수 있습니다'); end if;
    if pr.format = 'carousel' and (v_field is null or v_field not in ('heading','body')) then perform drinks_fail('invalid_input', '카드뉴스는 제목(heading)·본문(body)만 고칠 수 있습니다'); end if;
    if v_n is null or v_n < 1 or v_n > jsonb_array_length(coalesce(pr.plan_json -> v_key, '[]'::jsonb)) then
      perform drinks_fail('invalid_input', '없는 장면 번호입니다');
    end if;
    if length(v_text) < 2 or length(v_text) > 400 then perform drinks_fail('invalid_input', v_n || '번 글은 2~400자로 적어 주세요'); end if;
    v_json := jsonb_set(v_json, array[v_key, (v_n - 1)::text, v_field], to_jsonb(v_text));
    v_log := v_log || jsonb_build_array(jsonb_build_object('n', v_n, 'field', v_field));
  end loop;
  select * into r from drink_topic_reviews where id = pr.topic_review_id;
  v_plan := drinks_validate_plan(pr.format, v_json, r);

  if pr.plan_status = 'draft' then
    update drink_plan_revisions set plan_json = v_plan where id = pr.id returning * into np;
    perform drinks_log(t.id, 'plan', np.id, 'plan_edited', 'draft', 'draft', np.input_hash, null,
      jsonb_build_object('edits', v_log, 'via', 'studio_edit_scene'));
    return jsonb_build_object('plan_revision_id', np.id, 'version', np.version, 'new_draft', false);
  end if;

  if pr.plan_status <> 'approved' then perform drinks_fail('invalid_state', '고칠 수 있는 초안이 아닙니다(' || pr.plan_status || ')'); end if;
  -- 승인된 초안 → 새 작성 중 초안. 돈이 나가기 시작한 편(결재 이후)·제작을 시작한 카드는 막는다 — 산 그림이 글과 어긋난다.
  select * into e from drink_explainer_episodes where plan_revision_id = pr.id;
  if found and e.approval_id is not null then
    perform drinks_fail('already_making', '이미 제작을 시작한 초안입니다 — 고치려면 코멘트로 새 초안을 만드세요');
  end if;
  if exists (select 1 from drink_production_jobs j where j.plan_revision_id = pr.id and j.status in ('queued','running','succeeded')
             and j.renderer <> 'explainer_plan') then
    perform drinks_fail('already_making', '이미 제작을 시작한 초안입니다 — 고치려면 코멘트로 새 초안을 만드세요');
  end if;
  if exists (select 1 from drink_plan_revisions x where x.deliverable_id = d.id and x.plan_status = 'draft' and x.blocked_at is null) then
    perform drinks_fail('draft_exists', '이미 새 초안이 있습니다 — 새로 불러와 그 초안을 고치세요');
  end if;
  if t.status not in ('ready','selected') or not drinks_approval_valid(pr.topic_review_id) then
    perform drinks_fail('review_changed', '초안이 기대던 근거가 지금은 유효하지 않습니다 — 새로 불러오세요');
  end if;
  -- 시각 주장표의 주인(개발 요청 결과가 있는 초안). 고친 초안을 또 고쳐도 한 번에 찾아간다(재귀·깊이 한도 없음).
  select (x.detail ->> 'visual_from')::uuid into v_root from drink_workflow_events x
    where x.entity_type = 'plan' and x.entity_id = pr.id and x.action = 'plan_created' and x.detail ->> 'via' = 'studio_edit_scene' and x.detail ? 'visual_from'
    order by x.id desc limit 1;
  v_root := coalesce(v_root, pr.id);
  v_hash := drinks_evidence_content_hash(r.evidence_pack, r.brief);
  select coalesce(max(revision_no), 0) + 1 into v_no from drink_plan_revisions where deliverable_id = d.id;
  insert into drink_plan_revisions (deliverable_id, topic_id, format, revision_no, topic_review_id, plan_json, aspect_ratio,
      visual_profile, brand_profile_version, drafted_from_unapproved, evidence_content_hash)
    values (d.id, t.id, pr.format, v_no, r.id, v_plan, pr.aspect_ratio, pr.visual_profile, pr.brand_profile_version, false, v_hash)
    returning * into np;
  update drink_deliverables set current_revision_id = np.id where id = d.id;
  -- 옛 승인본은 더 이상 제작에 못 쓴다(다른 탭·옛 주소로 고치기 전 글을 사지 않게). 지우지 않고 기록으로 둔다.
  update drink_plan_revisions set blocked_at = now(), blocked_reason = 'edited: 운영자가 장면을 고쳐 새 초안으로 바뀌었습니다' where id = pr.id;
  perform drinks_log(t.id, 'plan', np.id, 'plan_created', null, 'draft', np.input_hash, null,
    jsonb_build_object('format', np.format, 'revision_no', v_no, 'topic_review_id', r.id, 'edited_from', pr.id, 'visual_from', v_root,
      'edits', v_log, 'via', 'studio_edit_scene'));
  return jsonb_build_object('plan_revision_id', np.id, 'version', np.version, 'new_draft', true, 'edited_from', pr.id);
end $$;

-- 0074's work list tracks only traditional evidence and script requests.
create or replace view drink_work_items with (security_invoker = true) as
with units as (
  select 'topic:' || fp.topic_id::text || ':' || fp.format_intent as unit_id, fp.topic_id, t.title, t.question, t.status as topic_status, t.version as topic_version,
    fp.format_intent, 'topic'::text as source, fp.editorial_week, fp.approved_at as pick_approved_at, fp.approved_amount_usd as pick_amount_usd,
    null::uuid as card_draft_id, fp.updated_at as pick_updated_at, t.current_review_id, t.approved_review_id
  from drink_topic_format_picks fp join drink_topics t on t.id = fp.topic_id
  union all
  select 'meme_card:' || m.id::text, null::uuid, c.name, null::text, null::text, null::int,
    'meme'::text, 'card'::text, null::date, null::timestamptz, null::numeric,
    m.id, m.updated_at, null::uuid, null::uuid
  from drink_meme_drafts m join drink_ig_cards c on c.id = m.card_id
  where m.card_id is not null
)
select u.unit_id, u.topic_id, u.title, u.question, u.topic_status, u.topic_version, u.format_intent, u.source,
  u.editorial_week, u.pick_approved_at, u.pick_amount_usd,
  rv.id as review_id, rv.status as review_status,
  case when rv.id is null or rv.status <> 'approved' then null
       else (rv.revoked_at is null and drinks_approval_valid(rv.id)) end as review_valid, rv.version as review_version,
  dq.kind as develop_kind, dq.status as develop_status, dq.id as develop_request_id, dq.error_code as develop_error_code,
  pl.id as plan_revision_id, pl.plan_status, (pl.id is not null and pl.blocked_at is not null) as plan_blocked, pl.version as plan_version, pl.format as plan_format,
  jb.id as job_id, jb.status as job_status, jb.error_code as job_error_code,
  ep.state as explainer_state,
  orv.id as output_review_id, orv.status as output_review_status, coalesce(ov.currently_usable, false) as output_usable,
  mm.id as meme_draft_id, mm.status as meme_status, mm.sync_grade as meme_sync_grade, mm.external_url as meme_external_url,
  pb.id as pub_request_id, pb.status as pub_status, pb.pause_code as pub_pause_code, pb.publish_at as pub_publish_at, pb.external_url as pub_external_url, pb.version as pub_version,
  coalesce(ep.state = 'unknown_billed', false) or coalesce(pb.status = 'unknown', false)
    or coalesce(dq.status = 'running' and dq.lease_expires_at < now(), false) as unknown_billed,
  (exists (select 1 from drink_develop_holds h where h.status = 'held'
      and ((h.request_id = dq.id and dq.status not in ('queued','running')) or (h.meme_draft_id = mm.id and mm.status not in ('text_running','rendering'))))
   or exists (select 1 from drink_spend_holds h join drink_spend_approvals a on a.id = h.approval_id
      where a.plan_revision_id = pl.id and h.status = 'held'
        and not exists (select 1 from drink_production_jobs j where j.id = h.job_id and j.status = 'running' and j.lease_expires_at > now()))) as orphan_hold,
  greatest(u.pick_updated_at, pl.updated_at, coalesce(dq.finished_at, dq.started_at, dq.created_at), coalesce(jb.finished_at, jb.started_at, jb.created_at),
    ep.updated_at, pb.updated_at, mm.updated_at) as updated_at
from units u
left join lateral (select r.* from drink_topic_reviews r where r.id = coalesce(u.current_review_id, u.approved_review_id)) rv on true
left join lateral (
  select q.* from drink_develop_requests q
  where u.source = 'topic' and u.format_intent in ('explainer','card') and q.topic_id = u.topic_id
    and (q.kind = 'evidence' or (q.kind = 'plan'
      and coalesce(q.format_intent, drinks_representative_intent(u.topic_id)) = u.format_intent))
  order by q.created_at desc limit 1) dq on true
left join lateral (
  select pr.* from drink_deliverables d join drink_plan_revisions pr on pr.id = d.current_revision_id
  where u.source = 'topic' and d.topic_id = u.topic_id and d.format = drinks_intent_format(u.format_intent) and d.locale = 'ko'
  limit 1) pl on true
left join lateral (select j.* from drink_production_jobs j where j.plan_revision_id = pl.id order by j.created_at desc limit 1) jb on true
left join lateral (select e.* from drink_explainer_episodes e where e.plan_revision_id = pl.id) ep on true
left join lateral (select o.* from drink_output_reviews o where o.plan_revision_id = pl.id order by o.created_at desc limit 1) orv on true
left join lateral (select v.currently_usable from drink_output_validity v where v.review_id = orv.id) ov on true
left join lateral (
  select m.* from drink_meme_drafts m
  where (u.source = 'card' and m.id = u.card_draft_id) or (u.source = 'topic' and u.format_intent = 'meme' and m.topic_id = u.topic_id)
  order by (m.status not in ('rejected','stopped','failed','posted_manual')) desc, m.updated_at desc limit 1) mm on true
left join lateral (
  select b.* from drink_publication_requests b
  where (mm.id is not null and b.meme_draft_id = mm.id) or (pl.id is not null and b.plan_revision_id = pl.id)
  order by (b.status in ('published','canceled')) asc, b.created_at desc limit 1) pb on true;

revoke all on function drinks_jjeri_input_guard(), drinks_jjeri_hold_guard(),
  drinks_jjeri_current_review(drink_topics, uuid, text), drinks_request_jjeri_episode(jsonb),
  drinks_jjeri_generation_context(jsonb), drinks_finish_jjeri_episode(jsonb),
  drinks_approve_jjeri_episode(jsonb), drinks_jjeri_generation_status(jsonb) from public, anon, authenticated;
grant execute on function drinks_jjeri_current_review(drink_topics, uuid, text), drinks_request_jjeri_episode(jsonb),
  drinks_jjeri_generation_context(jsonb), drinks_finish_jjeri_episode(jsonb),
  drinks_approve_jjeri_episode(jsonb), drinks_jjeri_generation_status(jsonb) to service_role;

commit;
