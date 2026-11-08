-- 주류 공장 — 사진형 카드뉴스 복구 + 스튜디오 연결 (2026-11-08). docs/deviation-drinks-card-photo-restore.md
--
-- 사건: 운영자가 2026-10-27 승인한 사진형 카드(card-photo-v1 — 사진 전면·[핵심어] 금색 제목·출처 장 팔로우 안내)는
--   PR 126 으로 올라갔지만 그 PR 이 PR 125 브랜치 위에 쌓여 있었고, 10-28 PR 125 머지 뒤 브랜치가 지워지면서 GitHub 가
--   PR 126 을 **자동으로 닫았다**(머지 아님). 그 뒤 만든 카드 엔진(0065)·스튜디오(0076)는 글자 카드(card-v1)만 알았다.
--   그 PR 의 0056_drinks_card_paid.sql 은 번호가 다른 파일(0056_drinks_function_search_path)에 밀려 적용된 적이 없다.
--
-- 이 파일:
--   ① 0056 의 세 함수를 지금 정의 위에 다시 얹는다 — drinks_is_photo_plan(새), drinks_estimate_render·drinks_request_render(0054 이후
--      바뀐 적 없음 — 0056 본문 그대로), drinks_validate_plan(0065 정의 + 사진형 칸 보존: image_prompt·kicker·category·photo_shift·layout·caption).
--   ② drinks_studio_generate(0076) — 사진형 초안이면 화면이 보여 준 금액(approve_usd)으로 그 초안 전용 결재(1일, 그림만)를 열고 유료 렌더.
--      금액이 없거나 지금 예상보다 작으면 spend_confirm_required 로 멈춘다(아무것도 사지 않는다). 이미 산 그림은 예상에서 0 으로 빠진다.
--      확정된 소재의 새 초안(draft)은 drinks_plan_action 으로 제출·승인한다(검사 그대로).
--   ③ drinks_studio_rewrite(0076) — 확정된 카드 초안이면 같은 승인 근거로 새 초안 요청(옛 확정·제작물은 새 초안이 확정될 때까지 그대로).
--   ④ drinks_studio_status — 0076 정의를 drinks_studio_status_0076 으로 옮기고, 초안마다 사진 예상 금액(estimate)을 붙인다.
--
-- 되돌리기: 0054 의 drinks_estimate_render·drinks_request_render, 0065 의 drinks_validate_plan, 0076 의 drinks_studio_generate·
--   drinks_studio_rewrite 를 다시 실행하고, drinks_studio_status 를 지운 뒤 drinks_studio_status_0076 을 원래 이름으로 되돌린다.
--   엔진은 DRINKS_CARD_LAYOUT=text 로 글자 카드에 돌아간다.


create or replace function drinks_is_photo_plan(p_plan jsonb) returns boolean language sql immutable as $$
  select coalesce(p_plan ->> 'layout' = 'photo' or p_plan ->> 'template_version' = 'card-photo-v1', false)
$$;

-- 이 제작안을 유료로 한 번 렌더할 때 새로 드는 예상 금액(그림만). 정리 카드는 로컬로 그리므로 0.
-- 이 제작안 버전으로 이미 산 그림도 0 — 승인된 제작안은 바뀌지 않으므로 같은 그림을 다시 쓴다(engine/drinks_paid.py).
--   영상: 항목 이름 'scene-NN-역할' 은 engine/drinks_paid.image_item 과 같아야 한다.
--   사진형 카드(0056): 항목 이름 'page-NN-photo' 는 engine/drinks_paid.card_image_item 과 같아야 하고, 단가는 실사(price_image_reality) —
--     엔진도 같은 값(config.DRINKS_PAID_PRICES["image_reality"] = 실사 모델 정가)을 쓴다. 대상은 출처 장이 아니고 image_prompt 가
--     비지 않은 쪽(엔진 build_card_image_items 와 같다). tests/test_drinks_paid.py 가 엔진과 대조한다.
--   반환: scenes(영상, 0054 와 같은 꼴) · pages(사진형 카드: position·role=쪽 역할·kind='photo'·usd·bought·price_usd) ·
--         images·bought·total_usd(둘을 합친 값). 영상 제작안은 pages 가 빈 배열이다.
--   시험 스크립트로(제작 작업 없이) 산 그림은 여기서 모른다 — 그만큼 예상이 실제보다 크게(안전한 쪽으로) 나온다.
create or replace function drinks_estimate_render(p_plan uuid) returns jsonb language sql stable as $$
  with sc as (
    select (e.ord)::int as position, coalesce(nullif(e.s ->> 'visual_role', ''), 'reality') as role
    from drink_plan_revisions pl, jsonb_array_elements(coalesce(pl.plan_json -> 'scenes', '[]')) with ordinality e(s, ord)
    where pl.id = p_plan and pl.format = 'video'
  ), priced as (
    select position, role,
      exists (select 1 from drink_spend_holds h join drink_production_jobs j on j.id = h.job_id
        where j.plan_revision_id = p_plan and h.status = 'settled'
          and h.item_key = 'scene-' || lpad(sc.position::text, 2, '0') || '-' || sc.role) as bought,
      case role when 'text_card' then 0
        when 'mechanism' then (drinks_spend_limits() ->> 'price_image_mechanism')::numeric
        else (drinks_spend_limits() ->> 'price_image_reality')::numeric end as price
    from sc
  ), est as (
    select position, role, bought, price, case when bought then 0 else price end as usd from priced
  ), pg as (
    select coalesce((e.s ->> 'position')::int, e.ord::int) as position, coalesce(nullif(e.s ->> 'role', ''), 'explain') as role
    from drink_plan_revisions pl, jsonb_array_elements(coalesce(pl.plan_json -> 'pages', '[]')) with ordinality e(s, ord)
    where pl.id = p_plan and pl.format = 'carousel' and drinks_is_photo_plan(pl.plan_json)
      and coalesce(e.s ->> 'role', '') <> 'source'
      and nullif(btrim(coalesce(e.s ->> 'image_prompt', ''), E' \t\r\n'), '') is not null
  ), pg_priced as (
    select position, role,
      exists (select 1 from drink_spend_holds h join drink_production_jobs j on j.id = h.job_id
        where j.plan_revision_id = p_plan and h.status = 'settled'
          and h.item_key = 'page-' || lpad(pg.position::text, 2, '0') || '-photo') as bought,
      (drinks_spend_limits() ->> 'price_image_reality')::numeric as price
    from pg
  ), pg_est as (
    select position, role, bought, price, case when bought then 0 else price end as usd from pg_priced
  )
  select jsonb_build_object(
    'scenes', coalesce((select jsonb_agg(jsonb_build_object('position', position, 'role', role, 'usd', usd,
        'bought', bought, 'price_usd', price) order by position) from est), '[]'),
    'pages', coalesce((select jsonb_agg(jsonb_build_object('position', position, 'role', role, 'kind', 'photo', 'usd', usd,
        'bought', bought, 'price_usd', price) order by position) from pg_est), '[]'),
    'images', (select count(*) from est where usd > 0) + (select count(*) from pg_est where usd > 0),
    'bought', (select count(*) from est where bought) + (select count(*) from pg_est where bought),
    'total_usd', coalesce((select sum(usd) from est), 0) + coalesce((select sum(usd) from pg_est), 0))
$$;

-- 0054 재정의: 유료 렌더 허용 조건에 사진형 카드를 더한다(나머지 검사는 0054 와 같다).
create or replace function drinks_request_render(p jsonb) returns jsonb language plpgsql as $$
declare pl drink_plan_revisions; rv drink_topic_reviews; j drink_production_jobs; v_block text; v_input text;
  v_attempt int; prev drink_production_jobs; v_paid boolean := coalesce((p ->> 'paid')::boolean, false);
  ap drink_spend_approvals; v_est jsonb; v_view jsonb;
begin
  perform drinks_reap_prod_jobs();
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  v_block := drinks_plan_renderable(pl.id);
  if v_block is not null then
    perform drinks_fail(case v_block when 'not_found' then 'not_found' else 'not_renderable' end,
      case v_block when 'not_found' then '제작안을 찾지 못했습니다'
        when 'plan_not_approved' then '승인된 제작안만 렌더합니다'
        when 'plan_blocked' then '차단된 제작안입니다(근거 철회·권리 변경)'
        else '이 제작안이 쓴 근거를 지금은 쓸 수 없습니다' end);
  end if;
  if v_paid then
    -- 0056: 영상, 또는 사진형 카드(layout=photo / template_version=card-photo-v1)만 유료. 글자 카드(card-v1)는 살 그림이 없다.
    if not (pl.format = 'video' or (pl.format = 'carousel' and drinks_is_photo_plan(pl.plan_json))) then
      perform drinks_fail('paid_disabled', '유료 생성은 영상 또는 사진형 카드뉴스(layout=photo) 제작안에만 씁니다');
    end if;
    if drinks_uuid(p, 'spend_approval_id', false) is null then
      perform drinks_fail('paid_disabled', '유료 렌더는 결재가 있어야 합니다 — 결재 금액 안에서만 그림을 삽니다');
    end if;
    select * into ap from drink_spend_approvals where id = drinks_uuid(p, 'spend_approval_id') for share;
    if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
    if ap.status <> 'open' or ap.expires_at <= now() then perform drinks_fail('approval_closed', '열린 결재가 아닙니다'); end if;
    if not ('image' = any(ap.allowed_kinds)) then perform drinks_fail('kind_not_approved', '이 결재는 그림 생성을 허용하지 않습니다'); end if;
    if ap.plan_revision_id is distinct from pl.id then
      perform drinks_fail('ownership', '렌더 결재는 그 제작안 전용이어야 합니다');
    end if;
    -- 발주 전 예상 금액 > 남은 금액이면 큐에 넣지 않는다. 실제로 막는 것은 호출마다의 가잡기(drinks_hold_spend)다.
    v_est := drinks_estimate_render(pl.id);
    v_view := drinks_spend_view(ap);
    if (v_est ->> 'total_usd')::numeric > (v_view ->> 'remaining_usd')::numeric then
      perform drinks_fail('budget_insufficient', '예상 $' || (v_est ->> 'total_usd') || ' 가 남은 결재 금액 $' || (v_view ->> 'remaining_usd') || ' 보다 큽니다',
        jsonb_build_object('estimate', v_est, 'approval', v_view));
    end if;
  end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_input := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|' ||
    (drinks_production_limits() ->> 'renderer_version') || '|' || case when v_paid then 'paid|' || ap.id::text else 'local' end, 'UTF8')), 'hex');
  select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
    and status in ('queued','running');
  if found then
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);   -- 중복 요청은 같은 작업
  end if;
  if drinks_uuid(p, 'retry_of', false) is not null then
    select * into prev from drink_production_jobs where id = drinks_uuid(p, 'retry_of') and plan_revision_id = pl.id;
    if not found or prev.status not in ('failed','canceled') then
      perform drinks_fail('invalid_state', '실패·취소된 같은 제작안의 작업만 재시도합니다');
    end if;
  end if;
  v_attempt := 1 + (select count(*) from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input);
  begin
    insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, retry_of, input_hash, plan_hash,
      review_hash, renderer, renderer_version, requested_by, spend_approval_id)
    values (pl.topic_id, pl.id, pl.format, v_attempt, prev.id, v_input, pl.approved_hash, rv.approved_hash,
      case when v_paid then 'paid' else 'local' end, drinks_production_limits() ->> 'renderer_version', 'operator', ap.id)
    returning * into j;
  exception when unique_violation then
    select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
      and status in ('queued','running');
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);
  end;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', pl.format, 'attempt_no', j.attempt_no, 'renderer', j.renderer, 'spend_approval_id', ap.id,
      'estimate_usd', v_est -> 'total_usd'));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', false, 'attempt_no', j.attempt_no,
    'renderer', j.renderer, 'estimate', v_est);
end $$;

create or replace function drinks_estimate_render(p_plan uuid) returns jsonb language sql stable as $$
  with sc as (
    select (e.ord)::int as position, coalesce(nullif(e.s ->> 'visual_role', ''), 'reality') as role
    from drink_plan_revisions pl, jsonb_array_elements(coalesce(pl.plan_json -> 'scenes', '[]')) with ordinality e(s, ord)
    where pl.id = p_plan and pl.format = 'video'
  ), priced as (
    select position, role,
      exists (select 1 from drink_spend_holds h join drink_production_jobs j on j.id = h.job_id
        where j.plan_revision_id = p_plan and h.status = 'settled'
          and h.item_key = 'scene-' || lpad(sc.position::text, 2, '0') || '-' || sc.role) as bought,
      case role when 'text_card' then 0
        when 'mechanism' then (drinks_spend_limits() ->> 'price_image_mechanism')::numeric
        else (drinks_spend_limits() ->> 'price_image_reality')::numeric end as price
    from sc
  ), est as (
    select position, role, bought, price, case when bought then 0 else price end as usd from priced
  ), pg as (
    select coalesce((e.s ->> 'position')::int, e.ord::int) as position, coalesce(nullif(e.s ->> 'role', ''), 'explain') as role
    from drink_plan_revisions pl, jsonb_array_elements(coalesce(pl.plan_json -> 'pages', '[]')) with ordinality e(s, ord)
    where pl.id = p_plan and pl.format = 'carousel' and drinks_is_photo_plan(pl.plan_json)
      and coalesce(e.s ->> 'role', '') <> 'source'
      and nullif(btrim(coalesce(e.s ->> 'image_prompt', ''), E' \t\r\n'), '') is not null
  ), pg_priced as (
    select position, role,
      exists (select 1 from drink_spend_holds h join drink_production_jobs j on j.id = h.job_id
        where j.plan_revision_id = p_plan and h.status = 'settled'
          and h.item_key = 'page-' || lpad(pg.position::text, 2, '0') || '-photo') as bought,
      (drinks_spend_limits() ->> 'price_image_reality')::numeric as price
    from pg
  ), pg_est as (
    select position, role, bought, price, case when bought then 0 else price end as usd from pg_priced
  )
  select jsonb_build_object(
    'scenes', coalesce((select jsonb_agg(jsonb_build_object('position', position, 'role', role, 'usd', usd,
        'bought', bought, 'price_usd', price) order by position) from est), '[]'),
    'pages', coalesce((select jsonb_agg(jsonb_build_object('position', position, 'role', role, 'kind', 'photo', 'usd', usd,
        'bought', bought, 'price_usd', price) order by position) from pg_est), '[]'),
    'images', (select count(*) from est where usd > 0) + (select count(*) from pg_est where usd > 0),
    'bought', (select count(*) from est where bought) + (select count(*) from pg_est where bought),
    'total_usd', coalesce((select sum(usd) from est), 0) + coalesce((select sum(usd) from pg_est), 0))
$$;

-- 0054 재정의: 유료 렌더 허용 조건에 사진형 카드를 더한다(나머지 검사는 0054 와 같다).
create or replace function drinks_request_render(p jsonb) returns jsonb language plpgsql as $$
declare pl drink_plan_revisions; rv drink_topic_reviews; j drink_production_jobs; v_block text; v_input text;
  v_attempt int; prev drink_production_jobs; v_paid boolean := coalesce((p ->> 'paid')::boolean, false);
  ap drink_spend_approvals; v_est jsonb; v_view jsonb;
begin
  perform drinks_reap_prod_jobs();
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  v_block := drinks_plan_renderable(pl.id);
  if v_block is not null then
    perform drinks_fail(case v_block when 'not_found' then 'not_found' else 'not_renderable' end,
      case v_block when 'not_found' then '제작안을 찾지 못했습니다'
        when 'plan_not_approved' then '승인된 제작안만 렌더합니다'
        when 'plan_blocked' then '차단된 제작안입니다(근거 철회·권리 변경)'
        else '이 제작안이 쓴 근거를 지금은 쓸 수 없습니다' end);
  end if;
  if v_paid then
    -- 0056: 영상, 또는 사진형 카드(layout=photo / template_version=card-photo-v1)만 유료. 글자 카드(card-v1)는 살 그림이 없다.
    if not (pl.format = 'video' or (pl.format = 'carousel' and drinks_is_photo_plan(pl.plan_json))) then
      perform drinks_fail('paid_disabled', '유료 생성은 영상 또는 사진형 카드뉴스(layout=photo) 제작안에만 씁니다');
    end if;
    if drinks_uuid(p, 'spend_approval_id', false) is null then
      perform drinks_fail('paid_disabled', '유료 렌더는 결재가 있어야 합니다 — 결재 금액 안에서만 그림을 삽니다');
    end if;
    select * into ap from drink_spend_approvals where id = drinks_uuid(p, 'spend_approval_id') for share;
    if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
    if ap.status <> 'open' or ap.expires_at <= now() then perform drinks_fail('approval_closed', '열린 결재가 아닙니다'); end if;
    if not ('image' = any(ap.allowed_kinds)) then perform drinks_fail('kind_not_approved', '이 결재는 그림 생성을 허용하지 않습니다'); end if;
    if ap.plan_revision_id is distinct from pl.id then
      perform drinks_fail('ownership', '렌더 결재는 그 제작안 전용이어야 합니다');
    end if;
    -- 발주 전 예상 금액 > 남은 금액이면 큐에 넣지 않는다. 실제로 막는 것은 호출마다의 가잡기(drinks_hold_spend)다.
    v_est := drinks_estimate_render(pl.id);
    v_view := drinks_spend_view(ap);
    if (v_est ->> 'total_usd')::numeric > (v_view ->> 'remaining_usd')::numeric then
      perform drinks_fail('budget_insufficient', '예상 $' || (v_est ->> 'total_usd') || ' 가 남은 결재 금액 $' || (v_view ->> 'remaining_usd') || ' 보다 큽니다',
        jsonb_build_object('estimate', v_est, 'approval', v_view));
    end if;
  end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_input := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|' ||
    (drinks_production_limits() ->> 'renderer_version') || '|' || case when v_paid then 'paid|' || ap.id::text else 'local' end, 'UTF8')), 'hex');
  select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
    and status in ('queued','running');
  if found then
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);   -- 중복 요청은 같은 작업
  end if;
  if drinks_uuid(p, 'retry_of', false) is not null then
    select * into prev from drink_production_jobs where id = drinks_uuid(p, 'retry_of') and plan_revision_id = pl.id;
    if not found or prev.status not in ('failed','canceled') then
      perform drinks_fail('invalid_state', '실패·취소된 같은 제작안의 작업만 재시도합니다');
    end if;
  end if;
  v_attempt := 1 + (select count(*) from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input);
  begin
    insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, retry_of, input_hash, plan_hash,
      review_hash, renderer, renderer_version, requested_by, spend_approval_id)
    values (pl.topic_id, pl.id, pl.format, v_attempt, prev.id, v_input, pl.approved_hash, rv.approved_hash,
      case when v_paid then 'paid' else 'local' end, drinks_production_limits() ->> 'renderer_version', 'operator', ap.id)
    returning * into j;
  exception when unique_violation then
    select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
      and status in ('queued','running');
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);
  end;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', pl.format, 'attempt_no', j.attempt_no, 'renderer', j.renderer, 'spend_approval_id', ap.id,
      'estimate_usd', v_est -> 'total_usd'));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', false, 'attempt_no', j.attempt_no,
    'renderer', j.renderer, 'estimate', v_est);
end $$;

create or replace function drinks_request_render(p jsonb) returns jsonb language plpgsql as $$
declare pl drink_plan_revisions; rv drink_topic_reviews; j drink_production_jobs; v_block text; v_input text;
  v_attempt int; prev drink_production_jobs; v_paid boolean := coalesce((p ->> 'paid')::boolean, false);
  ap drink_spend_approvals; v_est jsonb; v_view jsonb;
begin
  perform drinks_reap_prod_jobs();
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  v_block := drinks_plan_renderable(pl.id);
  if v_block is not null then
    perform drinks_fail(case v_block when 'not_found' then 'not_found' else 'not_renderable' end,
      case v_block when 'not_found' then '제작안을 찾지 못했습니다'
        when 'plan_not_approved' then '승인된 제작안만 렌더합니다'
        when 'plan_blocked' then '차단된 제작안입니다(근거 철회·권리 변경)'
        else '이 제작안이 쓴 근거를 지금은 쓸 수 없습니다' end);
  end if;
  if v_paid then
    -- 0056: 영상, 또는 사진형 카드(layout=photo / template_version=card-photo-v1)만 유료. 글자 카드(card-v1)는 살 그림이 없다.
    if not (pl.format = 'video' or (pl.format = 'carousel' and drinks_is_photo_plan(pl.plan_json))) then
      perform drinks_fail('paid_disabled', '유료 생성은 영상 또는 사진형 카드뉴스(layout=photo) 제작안에만 씁니다');
    end if;
    if drinks_uuid(p, 'spend_approval_id', false) is null then
      perform drinks_fail('paid_disabled', '유료 렌더는 결재가 있어야 합니다 — 결재 금액 안에서만 그림을 삽니다');
    end if;
    select * into ap from drink_spend_approvals where id = drinks_uuid(p, 'spend_approval_id') for share;
    if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
    if ap.status <> 'open' or ap.expires_at <= now() then perform drinks_fail('approval_closed', '열린 결재가 아닙니다'); end if;
    if not ('image' = any(ap.allowed_kinds)) then perform drinks_fail('kind_not_approved', '이 결재는 그림 생성을 허용하지 않습니다'); end if;
    if ap.plan_revision_id is distinct from pl.id then
      perform drinks_fail('ownership', '렌더 결재는 그 제작안 전용이어야 합니다');
    end if;
    -- 발주 전 예상 금액 > 남은 금액이면 큐에 넣지 않는다. 실제로 막는 것은 호출마다의 가잡기(drinks_hold_spend)다.
    v_est := drinks_estimate_render(pl.id);
    v_view := drinks_spend_view(ap);
    if (v_est ->> 'total_usd')::numeric > (v_view ->> 'remaining_usd')::numeric then
      perform drinks_fail('budget_insufficient', '예상 $' || (v_est ->> 'total_usd') || ' 가 남은 결재 금액 $' || (v_view ->> 'remaining_usd') || ' 보다 큽니다',
        jsonb_build_object('estimate', v_est, 'approval', v_view));
    end if;
  end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_input := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|' ||
    (drinks_production_limits() ->> 'renderer_version') || '|' || case when v_paid then 'paid|' || ap.id::text else 'local' end, 'UTF8')), 'hex');
  select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
    and status in ('queued','running');
  if found then
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);   -- 중복 요청은 같은 작업
  end if;
  if drinks_uuid(p, 'retry_of', false) is not null then
    select * into prev from drink_production_jobs where id = drinks_uuid(p, 'retry_of') and plan_revision_id = pl.id;
    if not found or prev.status not in ('failed','canceled') then
      perform drinks_fail('invalid_state', '실패·취소된 같은 제작안의 작업만 재시도합니다');
    end if;
  end if;
  v_attempt := 1 + (select count(*) from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input);
  begin
    insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, retry_of, input_hash, plan_hash,
      review_hash, renderer, renderer_version, requested_by, spend_approval_id)
    values (pl.topic_id, pl.id, pl.format, v_attempt, prev.id, v_input, pl.approved_hash, rv.approved_hash,
      case when v_paid then 'paid' else 'local' end, drinks_production_limits() ->> 'renderer_version', 'operator', ap.id)
    returning * into j;
  exception when unique_violation then
    select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
      and status in ('queued','running');
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);
  end;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', pl.format, 'attempt_no', j.attempt_no, 'renderer', j.renderer, 'spend_approval_id', ap.id,
      'estimate_usd', v_est -> 'total_usd'));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', false, 'attempt_no', j.attempt_no,
    'renderer', j.renderer, 'estimate', v_est);
end $$;

create or replace function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  core text[] := drinks_text_array(p_review.brief -> 'selected_claim_ids');
  all_claims text[] := array(select x ->> 'claim_id' from jsonb_array_elements(p_review.evidence_pack -> 'claims') x);
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; out jsonb := '[]'; i int := 0; cids text[]; cid text; v_role text; v_kind text; n int;
  v_reel jsonb := p_plan -> 'reel'; lim jsonb := drinks_card_reel_limits(); v_hook text; v_share text; v_extra jsonb;
begin
  if p_plan is null or jsonb_typeof(p_plan -> k) is distinct from 'array' then
    perform drinks_fail('invalid_plan', case k when 'scenes' then '영상 제작안에는 장면(scenes) 배열이 필요합니다'
      else '카드뉴스 제작안에는 페이지(pages) 배열이 필요합니다' end);
  end if;
  n := jsonb_array_length(p_plan -> k);
  if n = 0 then perform drinks_fail('invalid_plan', '장면·페이지가 하나 이상 있어야 합니다'); end if;
  if n > 40 then perform drinks_fail('invalid_plan', '장면·페이지는 40개까지입니다'); end if;
  for el in select * from jsonb_array_elements(p_plan -> k) loop
    i := i + 1;
    if jsonb_typeof(el) <> 'object' then perform drinks_fail('invalid_plan', i || '번 항목 형식이 잘못됐습니다'); end if;
    if el ? 'claim_ids' and jsonb_typeof(el -> 'claim_ids') not in ('array','null') then
      perform drinks_fail('invalid_plan', i || '번 항목 claim_ids 는 배열이어야 합니다');
    end if;
    cids := drinks_text_array(el -> 'claim_ids');
    foreach cid in array cids loop
      if not cid = any(all_claims) then
        perform drinks_fail('plan_claim_unknown', i || '번 항목의 ' || cid || ' 는 이 근거 버전에 없는 주장입니다');
      end if;
      if not cid = any(core) then
        perform drinks_fail('plan_claim_not_core', i || '번 항목이 승인 근거의 핵심 주장이 아닌 ' || cid || ' 를 씁니다');
      end if;
    end loop;
    if p_format = 'video' then
      if drinks_text(el, 'narration') is null then perform drinks_fail('invalid_plan', i || '번 장면에 나레이션이 없습니다'); end if;
      v_role := coalesce(drinks_text(el, 'visual_role'), 'reality');
      if v_role not in ('reality','mechanism','text_card','other') then
        perform drinks_fail('invalid_plan', i || '번 장면의 화면 역할이 잘못됐습니다');
      end if;
      v_kind := coalesce(drinks_text(el, 'content_kind'), 'fact');
      if v_kind not in ('fact','transition') then
        perform drinks_fail('invalid_plan', i || '번 장면 내용 종류는 사실 설명(fact) 또는 도입·전환·마무리(transition)입니다');
      end if;
      if el ? 'timing_sec' and el -> 'timing_sec' <> 'null'::jsonb
          and (jsonb_typeof(el -> 'timing_sec') <> 'number' or (el ->> 'timing_sec')::numeric <= 0
               or (el ->> 'timing_sec')::numeric > 60) then
        perform drinks_fail('invalid_plan', i || '번 장면 길이는 0초 초과 60초 이하 숫자여야 합니다');
      end if;
      -- 0057: card_page = 같은 소재 카드뉴스의 N 번째 페이지를 이 장면의 그림으로(1~20 정수)
      if el ? 'card_page' and el -> 'card_page' <> 'null'::jsonb
          and (jsonb_typeof(el -> 'card_page') <> 'number' or (el ->> 'card_page')::numeric <> trunc((el ->> 'card_page')::numeric)
               or (el ->> 'card_page')::numeric < 1 or (el ->> 'card_page')::numeric > 20) then
        perform drinks_fail('invalid_plan', i || '번 장면 card_page 는 1 이상 20 이하 정수여야 합니다');
      end if;
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'narration', drinks_text(el, 'narration'), 'visual_role', v_role, 'content_kind', v_kind,
        'card_page', case when jsonb_typeof(el -> 'card_page') = 'number' then (el ->> 'card_page')::int end,
        'explanation', drinks_text(el, 'explanation'), 'claim_ids', to_jsonb(cids),
        'timing_sec', case when jsonb_typeof(el -> 'timing_sec') = 'number' then el -> 'timing_sec' end,
        'continuity', drinks_text(el, 'continuity'), 'overlays', drinks_text(el, 'overlays'),
        -- 0054: 유료 그림 주문에 쓰는 영어 지시문(그림·움직임). 화면에 나가는 글이 아니다 — 사실 주장은 나레이션·근거가 진다.
        'visual_prompt', left(drinks_text(el, 'visual_prompt'), 1500), 'motion_prompt', left(drinks_text(el, 'motion_prompt'), 600),
        -- 엔진 실사형 화면 계약(2026-10-27): 이 장면이 답하는 질문·연출·도해 구조. engine/drinks_screen.py 가 읽는다.
        'answers_ko', left(drinks_text(el, 'answers_ko'), 300), 'staging_ko', left(drinks_text(el, 'staging_ko'), 600),
        'mechanism', case when jsonb_typeof(el -> 'mechanism') = 'object' and length((el -> 'mechanism')::text) <= 4000
                         then el -> 'mechanism' end));
    else
      if el ? 'position' and el -> 'position' <> 'null'::jsonb and el ->> 'position' <> i::text then
        perform drinks_fail('invalid_plan', '페이지 순서는 1부터 빈칸·중복 없이 이어져야 합니다(' || i || '번째)');
      end if;
      v_role := drinks_text(el, 'role');
      if v_role is null or v_role not in ('cover','explain','compare','checklist','source') then
        perform drinks_fail('invalid_plan', i || '번 페이지 역할이 잘못됐습니다');
      end if;
      if drinks_text(el, 'heading') is null then perform drinks_fail('invalid_plan', i || '번 페이지 제목이 없습니다'); end if;
      if el ? 'photo_shift' and el -> 'photo_shift' <> 'null'::jsonb
          and (jsonb_typeof(el -> 'photo_shift') <> 'number' or abs((el ->> 'photo_shift')::numeric) > 2000) then
        perform drinks_fail('invalid_plan', i || '번 페이지 photo_shift 는 -2000~2000 사이 숫자여야 합니다');
      end if;
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'role', v_role, 'heading', drinks_text(el, 'heading'),
        'body', drinks_text(el, 'body'), 'graphic_spec', drinks_text(el, 'graphic_spec'),
        'claim_ids', to_jsonb(cids))
        -- 0077(=0056): 사진형 카드 쪽 필드 — 있는 것만 붙여 글자 카드 제작안의 저장 모양(입력 해시)은 그대로다.
        || jsonb_strip_nulls(jsonb_build_object(
        'image_prompt', left(drinks_text(el, 'image_prompt'), 1500), 'kicker', left(drinks_text(el, 'kicker'), 80),
        'category', left(drinks_text(el, 'category'), 80),
        'photo_shift', case when jsonb_typeof(el -> 'photo_shift') = 'number' then el -> 'photo_shift' end)));
    end if;
  end loop;
  if p_format = 'video' then
    return jsonb_build_object('scenes', out, 'notes', drinks_text(p_plan, 'notes'));
  end if;
  if p_plan ? 'caption' and p_plan -> 'caption' <> 'null'::jsonb
      and (jsonb_typeof(p_plan -> 'caption') <> 'object' or length((p_plan -> 'caption')::text) > 8000) then
    perform drinks_fail('invalid_plan', '캡션(caption)은 8000자 이하 객체여야 합니다');
  end if;
  if drinks_text(p_plan, 'layout') is not null and drinks_text(p_plan, 'layout') not in ('photo') then
    perform drinks_fail('invalid_plan', '카드 배치(layout)는 photo 만 있습니다(비우면 글자 카드)');
  end if;
  -- 0077(=0056): layout·caption 을 보존한다(엔진이 layout 으로 사진형을 고르고 build_caption 이 caption 을 읽는다). 없으면 예전과 같은 모양.
  v_extra := jsonb_strip_nulls(jsonb_build_object('layout', drinks_text(p_plan, 'layout'),
    'caption', case when jsonb_typeof(p_plan -> 'caption') = 'object' then p_plan -> 'caption' end));
  -- 0065: 카드뉴스 릴스 묶음. 없으면 옛 제작안과 똑같다(입력 해시도 같다).
  if v_reel is null or jsonb_typeof(v_reel) = 'null' then
    return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
      'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1')) || v_extra;
  end if;
  if jsonb_typeof(v_reel) <> 'object' then perform drinks_fail('invalid_plan', '릴스 묶음(reel) 형식이 잘못됐습니다'); end if;
  v_hook := drinks_text(v_reel, 'hook_title');
  v_share := drinks_text(v_reel, 'share_line');
  if v_hook is null or length(v_hook) > (lim ->> 'hook_max')::int then
    perform drinks_fail('invalid_plan', '릴스 첫 페이지 훅 제목은 1~' || (lim ->> 'hook_max') || '자입니다');
  end if;
  if v_share is null or length(v_share) > (lim ->> 'share_max')::int then
    perform drinks_fail('invalid_plan', '릴스 마지막 페이지 저장/보내기 한 줄은 1~' || (lim ->> 'share_max') || '자입니다');
  end if;
  if n < (lim ->> 'min_pages')::int or n > (lim ->> 'max_pages')::int then
    perform drinks_fail('invalid_plan', '릴스로 만드는 카드는 ' || (lim ->> 'min_pages') || '~' || (lim ->> 'max_pages') || '장입니다(페이지당 2.5~4초, 15~30초)');
  end if;
  return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
    'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1'),
    'reel', jsonb_build_object('hook_title', v_hook, 'share_line', v_share)) || v_extra;
end $$;

create or replace function drinks_studio_generate(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; pk drink_topic_format_picks; v_ap jsonb; v_render jsonb; v_nums jsonb;
  j drink_production_jobs; v_retry uuid := drinks_uuid(p, 'retry_of', false); d drink_deliverables; v_est jsonb; v_ok numeric;
  ap drink_spend_approvals; v_words text;
begin
  if coalesce(drinks_text(p, 'format_intent'), '') <> 'card' then
    perform drinks_fail('format_not_supported', '이 화면에서 끝까지 만드는 형식은 카드뉴스뿐입니다');
  end if;
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  if pr.format <> 'carousel' then perform drinks_fail('format_not_supported', '카드뉴스 초안이 아닙니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pk from drink_topic_format_picks where topic_id = t.id and format_intent = 'card';
  if not found then perform drinks_fail('format_not_selected', '카드뉴스로 고른 소재가 아닙니다'); end if;
  if pk.approved_at is null then
    select * into r from drink_topic_reviews where id = pr.topic_review_id;
    v_nums := drinks_studio_unverified_numbers(pr.plan_json, r);
    if jsonb_array_length(v_nums) > 0 then
      perform drinks_fail('numbers_unverified', '근거 인용에 없는 숫자가 초안에 있습니다(' || (select string_agg(x, ', ') from jsonb_array_elements_text(v_nums) x)
        || ') — 고치거나 지운 뒤 생성하세요', v_nums);
    end if;
    v_ap := drinks_approve_content(jsonb_build_object('topic_id', t.id, 'expected_topic_version', drinks_int(p, 'expected_topic_version'),
      'review_id', r.id, 'expected_review_version', drinks_int(p, 'expected_review_version'),
      'plan_revision_id', pr.id, 'expected_plan_version', drinks_int(p, 'expected_plan_version'), 'format_intent', 'card',
      'note', '스튜디오 [콘텐츠 생성] — 운영자가 초안을 읽고 확정',
      -- 5축 점수는 참고값(0076 §4) — 65점 기준 아래여도 운영자가 직접 골라 확정한 것이므로 그 사실을 예외 사유로 기록한다(빈칸으로 우회하지 않는다).
      'score_exception_reason', '스튜디오에서 운영자가 소재를 직접 골라 초안을 확정함(점수는 참고값, 0076)',
      'format_exceptions',
      jsonb_build_object('carousel', '운영자가 스튜디오에서 카드뉴스를 직접 골랐습니다')));
    select * into pr from drink_plan_revisions where id = pr.id;
  elsif pr.plan_status = 'draft' then
    -- 0077: 이미 확정된 소재의 새 초안(예: 사진형으로 다시 쓴 것). 옛 승인 그대로, 이 초안만 제출·승인한다(drinks_plan_action — 검사 그대로).
    select * into d from drink_deliverables where id = pr.deliverable_id;
    if d.current_revision_id is distinct from pr.id or pr.blocked_at is not null then
      perform drinks_fail('invalid_state', '최신 카드뉴스 초안이 아닙니다 — 새로 불러오세요');
    end if;
    select * into r from drink_topic_reviews where id = pr.topic_review_id;
    v_nums := drinks_studio_unverified_numbers(pr.plan_json, r);
    if jsonb_array_length(v_nums) > 0 then
      perform drinks_fail('numbers_unverified', '근거 인용에 없는 숫자가 초안에 있습니다(' || (select string_agg(x, ', ') from jsonb_array_elements_text(v_nums) x)
        || ') — 고치거나 지운 뒤 생성하세요', v_nums);
    end if;
    if pr.version <> coalesce(drinks_int(p, 'expected_plan_version', false), pr.version) then
      perform drinks_fail('version_conflict', '초안이 다른 곳에서 바뀌었습니다 — 새로 불러오세요');
    end if;
    perform drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'submit'));
    select * into pr from drink_plan_revisions where id = pr.id;
    v_ap := drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'approve',
      'reason', '스튜디오 [콘텐츠 생성] — 운영자가 새 초안을 읽고 확정'));
    select * into pr from drink_plan_revisions where id = pr.id;
  elsif pr.plan_status <> 'approved' then
    perform drinks_fail('invalid_state', '이 소재의 카드뉴스는 다른 초안으로 이미 확정됐습니다 — 새로 불러오세요');
  end if;
  if v_retry is null then
    select * into j from drink_production_jobs where plan_revision_id = pr.id and status in ('queued','running','succeeded') order by created_at desc limit 1;
    if found then
      return jsonb_build_object('topic_id', t.id, 'plan_revision_id', pr.id, 'approved', v_ap is not null, 'approve', v_ap,
        'render', jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true), 'existing', true);
    end if;
  end if;
  if drinks_is_photo_plan(pr.plan_json) then
    -- 0077: 사진형 카드는 쪽마다 배경 사진을 산다. 화면이 보여 준 금액(approve_usd)이 지금 예상 이상일 때만 — 그 클릭이 이 금액의 결재다.
    v_est := drinks_estimate_render(pr.id);
    v_ok := drinks_text(p, 'approve_usd')::numeric;   -- 없으면 null → 아래에서 멈춘다
    if v_ok is null or v_ok + 0.0001 < (v_est ->> 'total_usd')::numeric then
      perform drinks_fail('spend_confirm_required', '배경 사진 ' || (v_est ->> 'images') || '장 $' || (v_est ->> 'total_usd')
        || ' — 화면에서 금액을 확인하고 다시 누르세요', v_est);
    end if;
    select * into ap from drink_spend_approvals where plan_revision_id = pr.id and status = 'open' and expires_at > now()
      and 'image' = any(allowed_kinds) order by created_at desc limit 1;
    if not found or (drinks_spend_view(ap) ->> 'remaining_usd')::numeric < (v_est ->> 'total_usd')::numeric then
      v_words := coalesce(drinks_text(p, 'approver_words'), '스튜디오 [콘텐츠 생성] — 사진형 카드 배경 사진 ' || (v_est ->> 'images') || '장 $'
        || (v_est ->> 'total_usd') || ' 확인 후 생성');
      perform drinks_open_spend_approval(jsonb_build_object('cap_usd', greatest(v_ok, 0.01), 'days', 1, 'allowed_kinds', jsonb_build_array('image'),
        'plan_revision_id', pr.id, 'stage', 'studio_card_photo', 'purpose', '사진형 카드 배경 사진', 'approver_words', v_words));
      select * into ap from drink_spend_approvals where plan_revision_id = pr.id and status = 'open' order by created_at desc limit 1;
    end if;
    v_render := drinks_request_render(jsonb_strip_nulls(jsonb_build_object('plan_revision_id', pr.id, 'retry_of', v_retry,
      'paid', true, 'spend_approval_id', ap.id)));
  else
    v_render := drinks_request_render(jsonb_strip_nulls(jsonb_build_object('plan_revision_id', pr.id, 'retry_of', v_retry)));
  end if;
  return jsonb_build_object('topic_id', t.id, 'plan_revision_id', pr.id, 'approved', v_ap is not null, 'approve', v_ap, 'render', v_render,
    'existing', coalesce((v_render ->> 'existing')::boolean, false));
end $$;

create or replace function drinks_studio_rewrite(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_ins text := btrim(coalesce(drinks_text(p, 'instruction'), ''));
  v_budget uuid; bs jsonb;
begin
  perform drinks_reap_develop();
  if length(v_ins) < 2 or length(v_ins) > 500 then perform drinks_fail('invalid_input', '수정 방향을 2~500자로 적어 주세요'); end if;
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pr from drink_plan_revisions where id = pr.id for update;
  if pr.version <> drinks_int(p, 'expected_version') then perform drinks_fail('version_conflict', '초안이 다른 곳에서 바뀌었습니다 — 새로 불러오세요'); end if;
  if pr.format = 'carousel' and pr.plan_status = 'approved' and pr.blocked_at is null then
    -- 0077: 확정된 초안 → 같은 승인 근거로 새 초안 한 벌(옛 확정·제작물은 그대로). 작성 중인 새 초안이 이미 있으면 그것을 고친다.
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
      values (t.id, 'plan', t.approved_review_id, v_budget, false, 'card', v_ins) returning * into q;
    perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
      jsonb_build_object('kind', 'plan', 'budget_id', v_budget, 'review_id', t.approved_review_id, 'draft_evidence', false, 'format_intent', 'card',
        'new_draft_of_approved', pr.id));
    return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
  end if;
  if pr.format <> 'carousel' or pr.plan_status <> 'draft' or pr.blocked_at is not null or not pr.drafted_from_unapproved then
    perform drinks_fail('invalid_state', '고칠 수 있는 카드뉴스 초안이 아닙니다');
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
    values (t.id, 'plan', r.id, v_budget, true, 'card', v_ins, pr.id, pr.version) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', 'plan', 'budget_id', v_budget, 'review_id', r.id, 'draft_evidence', true, 'format_intent', 'card', 'rewrite_of', pr.id));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

-- ④ 스튜디오 상태 — 0076 정의는 그대로 두고(이름만 옮김) 초안마다 사진 예상 금액을 붙인다.
do $$
begin
  if to_regprocedure('public.drinks_studio_status_0076(jsonb)') is null then
    alter function drinks_studio_status(jsonb) rename to drinks_studio_status_0076;
  end if;
end $$;

-- 사진형이 아니면 0원·0장(글자 카드는 살 것이 없다).
create or replace function drinks_studio_card_estimate(p_plan uuid) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select case when drinks_is_photo_plan(pl.plan_json)
    then drinks_estimate_render(pl.id) || jsonb_build_object('photo', true)
    else jsonb_build_object('photo', false, 'images', 0, 'bought', 0, 'total_usd', 0) end
  from drink_plan_revisions pl where pl.id = p_plan
$$;

create or replace function drinks_studio_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare s jsonb := drinks_studio_status_0076(p);
begin
  if s ? 'plans' and jsonb_typeof(s -> 'plans') = 'array' then
    s := jsonb_set(s, '{plans}', coalesce((select jsonb_agg(x || jsonb_build_object('estimate', drinks_studio_card_estimate((x ->> 'plan_revision_id')::uuid)) order by o)
      from jsonb_array_elements(s -> 'plans') with ordinality e(x, o)), '[]'::jsonb));
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
