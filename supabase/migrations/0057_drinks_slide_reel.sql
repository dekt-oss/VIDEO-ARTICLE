-- 주류 슬라이드 릴스 — 카드뉴스 페이지를 영상 장면 그림으로 (2026-10-28). docs/deviation-drinks-production.md "릴스 2차 묶음"
--
-- 영상 제작안의 장면이 card_page: N 을 가지면, 같은 소재의 가장 최근 **승인된** 카드뉴스 묶음의 N 번째 페이지가 그 장면의 그림이 된다
-- (워커가 합성 — 0원, LLM 없음). 이 파일이 하는 일은 둘뿐이다:
--   1) drinks_validate_plan  : 장면의 card_page(1~20 정수)를 보존한다. 범위를 벗어나면 invalid_plan.
--   2) drinks_start_render   : 작업 JSON 에 card_pages [{position, storage_key, mime}] 를 싣는다. 없으면 [].
--                              "승인 + 지금도 사용 가능(drink_output_validity.currently_usable) + 철회 안 됨" 인 카드 묶음 중 가장 최근 것.
--
-- ★ 두 함수 모두 0054 정의를 그대로 복사하고 위 부분만 더했다. create or replace 는 함수 설정(proconfig)을 초기화하므로
--   0056 의 search_path 고정(public, pg_temp)을 정의 안에 다시 적었다. 권한(grant)은 create or replace 가 유지한다.
-- 되돌리기: 0054 의 drinks_start_render·drinks_validate_plan 정의를 다시 실행하고(그다음 0056 의 반복문도 한 번 더),
--          저장된 제작안의 card_page 는 무시되므로(워커가 card_pages 를 못 받음) 그대로 둬도 해가 없다.

create or replace function drinks_start_render(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare j drink_production_jobs; pl drink_plan_revisions; rv drink_topic_reviews; t drink_topics; v_block text; v_reaped int;
  ap drink_spend_approvals; v_card_manifest uuid; v_cards jsonb;
begin
  v_reaped := drinks_reap_prod_jobs();
  loop
    select * into j from drink_production_jobs where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    -- 대기 중에 근거가 철회·만료됐거나 제작안이 차단됐으면 돌리지 않는다(비용을 쓰기 전에 멈춘다).
    v_block := drinks_plan_renderable(j.plan_revision_id);
    select * into pl from drink_plan_revisions where id = j.plan_revision_id;
    if v_block is null and pl.approved_hash is distinct from j.plan_hash then v_block := 'plan_changed'; end if;
    -- 유료 작업은 결재가 지금도 열려 있어야 시작한다(대기 중에 결재가 닫히면 돈을 쓰지 않는다).
    if v_block is null and j.renderer = 'paid' then
      select * into ap from drink_spend_approvals where id = j.spend_approval_id;
      if ap.status <> 'open' or ap.expires_at <= now() then v_block := 'approval_closed'; end if;
    end if;
    if v_block is not null then
      update drink_production_jobs set status = 'canceled', finished_at = now(), error_code = v_block,
        error_message = '대기 중에 제작안·근거·결재가 바뀌어 렌더하지 않았습니다(' || v_block || ')' where id = j.id;
      continue;
    end if;
    update drink_production_jobs set status = 'running', lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => (drinks_production_limits() ->> 'lease_sec')::int),
      heartbeat_at = now(), started_at = now(), worker_id = coalesce(drinks_text(p, 'worker_id'), 'worker')
      where id = j.id returning * into j;
    select * into rv from drink_topic_reviews where id = pl.topic_review_id;
    select * into t from drink_topics where id = j.topic_id;
    -- 슬라이드 릴스(0057): 같은 소재의 가장 최근 '승인되고 지금도 쓸 수 있는' 카드뉴스 묶음의 페이지. 영상 작업에만 싣는다.
    v_cards := '[]'::jsonb;
    if j.format = 'video' then
      select m.id into v_card_manifest
        from drink_asset_manifests m
        join drink_output_reviews r on r.manifest_id = m.id
        join drink_output_validity v on v.review_id = r.id
        join drink_plan_revisions cp on cp.id = m.plan_revision_id
       where m.format = 'carousel' and cp.topic_id = j.topic_id and r.status = 'approved' and r.revoked_at is null
         and v.currently_usable
       order by r.reviewed_at desc nulls last, m.created_at desc limit 1;
      if v_card_manifest is not null then
        v_cards := coalesce((select jsonb_agg(jsonb_build_object('position', ma.position, 'storage_key', a.storage_key, 'mime', a.mime)
            order by ma.position)
          from drink_manifest_assets ma join drink_media_assets a on a.id = ma.asset_id
          where ma.manifest_id = v_card_manifest and ma.role = 'page' and a.state = 'stored'), '[]'::jsonb);
      end if;
    end if;
    return jsonb_build_object('reaped', v_reaped, 'job', jsonb_build_object(
      'job_id', j.id, 'lease_token', j.lease_token, 'format', j.format, 'attempt_no', j.attempt_no, 'input_hash', j.input_hash,
      'renderer', j.renderer, 'spend_approval_id', j.spend_approval_id,
      'renderer_version', j.renderer_version, 'plan_revision_id', pl.id, 'plan', pl.plan_json, 'revision_no', pl.revision_no,
      'card_pages', v_cards,
      'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'categories', to_jsonb(t.categories)),
      'brief', rv.brief, 'claims', rv.evidence_pack -> 'claims',
      'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher,
          'url', s.canonical_url, 'published_at', s.published_at))
        from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
          from jsonb_array_elements(rv.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]')));
  end loop;
end $$;

-- 0054 재정의 + card_page 보존(나머지 검사는 0054 와 같다).
create or replace function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql set search_path = public, pg_temp as $$
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
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'role', v_role, 'heading', drinks_text(el, 'heading'),
        'body', drinks_text(el, 'body'), 'graphic_spec', drinks_text(el, 'graphic_spec'),
        'claim_ids', to_jsonb(cids)));
    end if;
  end loop;
  if p_format = 'video' then
    return jsonb_build_object('scenes', out, 'notes', drinks_text(p_plan, 'notes'));
  end if;
  return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
    'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1'));
end $$;
