-- 주류 스튜디오 흐름 단순화(2026-11-17). docs/계획_주류흐름단순화_2026-11-17.md
--
-- 운영자: "수정해야 되는 경우는 그냥 바로 수정하거나 수정 방향을 입력할 수 있게" · "막힌 이유 보여줘서 어쩌자는거야".
-- 바뀌는 것 넷:
--   1. drinks_studio_edit_scene — 장면(카드는 페이지) 글 한 칸을 바로 고친다. 0원(모델을 부르지 않는다).
--      · 작성 중 초안: 그 자리에서 고친다(drink_plans_guard 가 version·input_hash 를 다시 잰다).
--      · 승인된 초안(지시서 단계): 새 작성 중 초안을 만든다. 옛 승인본·지시서는 기록으로 남는다. 돈을 쓰기 시작한 편이면 막는다.
--      근거에 없는 숫자 검사는 지금처럼 승인 때(drinks_studio_approve_draft) 돈다.
--   2. drinks_explainer_request_plan — provider 기본값 omni → clay(스튜디오 기본과 같게). 지시서가 아직 없는 편은 방식을 바꿀 수 있다.
--      계기: 옛 화면으로 승인한 '막걸리…' 편이 provider 없이 omni 로 만들어져 omni 전용 검사(hook_text_overflow)에 걸렸다.
--   3. drink_explainer_episodes_guard — 위 2 를 위해 plan_draft·지시서 없음일 때만 provider 변경을 허용(돈 0원 상태).
--   4. drinks_studio_status — last 에 해결안(result.rescue)을 싣는다. 스튜디오 막힘 화면이 [해결안 적용] 한 번을 보이게.
-- 되돌리기: drop function drinks_studio_edit_scene(jsonb), drinks_plan_visual_claims(uuid); 그리고 0067 의 drinks_explainer_request_plan·
--           drink_explainer_episodes_guard·drinks_explainer_job_context,
--           0077 의 drinks_studio_status 를 다시 실행한다.

-- ─────────────────────────────────────────────────────────────
-- 1. 장면 글 바로 고치기
-- ─────────────────────────────────────────────────────────────
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
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then
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

-- ─────────────────────────────────────────────────────────────
-- 2·3. 만드는 방식: 기본 사진클레이, 지시서 전(0원)에는 바꿀 수 있다
-- ─────────────────────────────────────────────────────────────
create or replace function drink_explainer_episodes_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '편 기록은 삭제할 수 없습니다'); end if;
  if new.plan_revision_id <> old.plan_revision_id or new.topic_id <> old.topic_id then
    perform drinks_fail('immutable', '편의 제작안은 바꿀 수 없습니다');
  end if;
  -- 0087: 지시서가 없는 첫 상태(plan_draft)는 아무것도 사지 않았다 — 만드는 방식을 바꿔도 된다.
  if new.provider <> old.provider and not (old.state = 'plan_draft' and new.state = 'plan_draft' and old.directive is null and new.directive is null) then
    perform drinks_fail('immutable', '지시서를 만든 뒤에는 만드는 방식을 바꿀 수 없습니다');
  end if;
  if old.directive is not null and new.directive is distinct from old.directive then
    perform drinks_fail('immutable', '장면별 지시서는 바꿀 수 없습니다 — 대본이 바뀌면 새 제작안입니다');
  end if;
  if new.state <> old.state and not drinks_explainer_can_transition(old.state, new.state) then
    perform drinks_fail('invalid_state', '편 상태를 ' || old.state || ' 에서 ' || new.state || ' 로 바꿀 수 없습니다');
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;

create or replace function drinks_explainer_request_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; e drink_explainer_episodes; v_provider text := drinks_text(p, 'provider');
begin
  -- 잠금 순서 topic → plan(0050 규칙, drinks_studio_edit_scene 과 같다). 옛 함수는 plan 을 먼저 잠가 교착 여지가 있었다(코덱스 리뷰).
  perform drinks_lock_topic((select x.topic_id from drink_plan_revisions x where x.id = drinks_uuid(p, 'plan_revision_id')), null, false);
  pl := drinks_explainer_lock_plan(p);
  insert into drink_explainer_episodes (plan_revision_id, topic_id, provider)
    values (pl.id, pl.topic_id, coalesce(v_provider, 'clay'))
    on conflict (plan_revision_id) do nothing;
  select * into e from drink_explainer_episodes where plan_revision_id = pl.id for update;
  if e.state <> 'plan_draft' then perform drinks_fail('invalid_state', '지시서가 이미 있습니다(' || e.state || ')'); end if;
  if v_provider is not null and v_provider <> e.provider then
    -- 지시서 작업이 이미 돌고 있으면 바꾸지 않는다 — 워커가 옛 방식으로 지시서를 저장할 수 있다.
    if exists (select 1 from drink_production_jobs j where j.plan_revision_id = pl.id and j.renderer = 'explainer_plan' and j.status in ('queued','running')) then
      perform drinks_fail('job_running', '지시서를 만드는 중이라 지금은 방식을 바꿀 수 없습니다 — 끝난 뒤에 다시 누르세요');
    end if;
    update drink_explainer_episodes set provider = v_provider, last_code = null, last_message = null where plan_revision_id = pl.id;
  end if;
  return drinks_explainer_enqueue(pl, 'explainer_plan', null);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 2-1. 시각 주장표: 장면 글만 고쳐 만든 새 초안은 표의 주인(visual_from — 개발 요청 결과가 있는 초안)의 표를 쓴다(그림 지시는 그대로라서).
--      표는 개발 요청 결과에만 있다(0067). 사람이 고친 새 초안에는 결과가 없어 지시서가 visual_claims_missing 으로 멈췄다(코덱스 리뷰).
--      편집 때 주인을 한 번에 적어 두므로 몇 번을 고쳐도 한 단계로 찾는다.
--      대사만 바뀌므로 표의 claim_ids·장면 수가 같은지는 워커의 plan_problems(대본·시각 주장 코드 검사)가 다시 본다.
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_plan_visual_claims(p_plan uuid) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select r.result -> 'visual_claims'
    from (select p_plan as plan_id, 0 as pri
          union all
          select (x.detail ->> 'visual_from')::uuid, 1 from drink_workflow_events x
            where x.entity_type = 'plan' and x.entity_id = p_plan and x.action = 'plan_created'
              and x.detail ->> 'via' = 'studio_edit_scene' and x.detail ? 'visual_from') c
    join drink_develop_requests r on r.result_plan_revision_id = c.plan_id and r.kind = 'plan' and r.status = 'succeeded'
    order by c.pri, r.created_at desc limit 1
$$;

create or replace function drinks_explainer_job_context(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid := drinks_uuid(p, 'plan_revision_id'); v_ap uuid := drinks_uuid(p, 'approval_id', false); a drink_spend_approvals;
begin
  select * into a from drink_spend_approvals where id = v_ap;
  return drinks_explainer_status(jsonb_build_object('plan_revision_id', v_plan)) || jsonb_build_object(
    'approval', case when a.id is null then null else drinks_spend_view(a) end,
    'visual_claims', drinks_plan_visual_claims(v_plan));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 4. 스튜디오 상태에 해결안
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_studio_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare s jsonb := drinks_studio_status_0076(p); v_rescue jsonb;
begin
  if s ? 'plans' and jsonb_typeof(s -> 'plans') = 'array' then
    s := jsonb_set(s, '{plans}', coalesce((select jsonb_agg(x || jsonb_build_object('estimate', drinks_studio_card_estimate((x ->> 'plan_revision_id')::uuid)) order by o)
      from jsonb_array_elements(s -> 'plans') with ordinality e(x, o)), '[]'::jsonb));
  end if;
  if jsonb_typeof(s -> 'last') = 'object' then
    select q.result -> 'rescue' into v_rescue from drink_develop_requests q where q.id = (s -> 'last' ->> 'request_id')::uuid and q.status = 'blocked';
    if v_rescue is not null and jsonb_typeof(v_rescue) = 'object' then s := jsonb_set(s, '{last,rescue}', v_rescue); end if;
  end if;
  return s;
end $$;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_%' or p.proname like 'drink\_%')
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
  end loop;
end $$;
