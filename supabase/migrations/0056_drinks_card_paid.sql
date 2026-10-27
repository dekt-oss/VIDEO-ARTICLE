-- 주류 공장 — 사진형 카드뉴스의 유료 그림 허용 (2026-10-27, 운영자 승인). docs/deviation-drinks-production.md "사진형 카드"
--
-- 채널은 카드 우선이고 릴스는 같은 슬라이드를 무료로 엮는 것이라 "카드는 영상 그림을 재사용" 이라는 0054 의 전제가 더는 맞지 않는다.
-- 사진형 카드(plan.layout = 'photo' 또는 plan.template_version = 'card-photo-v1')는 쪽마다 4:5 배경 그림을 직접 산다
-- (engine/drinks_paid.card_image_item — 항목 이름 'page-NN-photo', 실사 단가).
--
-- 바뀌는 것(다른 검사는 0054 와 같다 — 열린 결재·기간·상한·종류·제작안 전용):
--   drinks_is_photo_plan      새 도우미. 엔진 is_photo_plan 과 같은 판정.
--   drinks_request_render     유료 허용 조건: 영상, 또는 사진형 카드. 오류 문구 갱신.
--   drinks_estimate_render    사진형 카드의 image_prompt 있는 쪽(출처 장 제외)을 실사 단가로 센다. 반환에 'pages' 배열을 더한다 —
--                             'scenes' 는 그대로(영상), images·bought·total_usd 는 두 가지를 합친다.
--   drinks_validate_plan      카드 쪽의 image_prompt·kicker·category·photo_shift 와 제작안의 layout·caption 을 버리지 않는다.
--                             (0054 까지는 pages 를 role·heading·body·graphic_spec·claim_ids 만 남겨 사진형 필드가 저장 때 사라졌다.)
--
-- ★ 이 파일은 아직 어떤 DB 에도 적용하지 않는다(0050~0055 와 함께 나중에 한꺼번에 나간다).
-- 되돌리기: 이 파일의 세 함수를 0054 정의(drinks_request_render·drinks_estimate_render·drinks_validate_plan)로 다시 만들고
--          drinks_is_photo_plan 을 drop 한다.

-- 사진형 카드 제작안인가 — engine/drinks_cards_photo.is_photo_plan 과 같다(layout == photo 또는 template_version == card-photo-v1).
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

-- 0054 재정의: 사진형 카드 필드를 버리지 않는다(나머지 검사는 0054 와 같다).
create or replace function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql as $$
declare
  core text[] := drinks_text_array(p_review.brief -> 'selected_claim_ids');
  all_claims text[] := array(select x ->> 'claim_id' from jsonb_array_elements(p_review.evidence_pack -> 'claims') x);
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; out jsonb := '[]'; i int := 0; cids text[]; cid text; v_role text; v_kind text; n int;
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
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'narration', drinks_text(el, 'narration'), 'visual_role', v_role, 'content_kind', v_kind,
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
        -- 0056: 사진형 카드 쪽 필드(engine/drinks_cards_photo.py) — 있는 것만 붙여 글자 카드 제작안의 저장 모양은 그대로다.
        --   영어 그림 지시문은 유료 주문서에 쓰이고 화면에 나가는 글이 아니다.
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
  -- 0056: layout·caption 을 보존한다(엔진이 layout 으로 사진형을 고르고 build_caption 이 caption 을 읽는다).
  return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
    'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1'))
    || jsonb_strip_nulls(jsonb_build_object('layout', drinks_text(p_plan, 'layout'),
      'caption', case when jsonb_typeof(p_plan -> 'caption') = 'object' then p_plan -> 'caption' end));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한 — 0054·0055 와 같다(service_role 만). 다시 만든 함수가 기본 권한으로 돌아가지 않게 다시 못 박는다.
-- ─────────────────────────────────────────────────────────────

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
