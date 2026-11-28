-- Preserve Jjeri guards if later migrations redefine drinks_request_render,
-- drinks_validate_plan, or drinks_register_asset. Check the live registry before numbering.
-- Candidate migration. Assign a migration number after checking the remote registry.
-- Rehearse against the local Postgres schema through 0091 before applying it elsewhere.
begin;

alter table drink_production_jobs drop constraint drink_production_jobs_renderer_check;
alter table drink_production_jobs add constraint drink_production_jobs_renderer_check
  check (renderer in ('local','paid','explainer_plan','explainer_buy','explainer_render','jjeri_class','jjeri_anatomy'));
alter table drink_publication_requests drop constraint drink_pub_format_ck;
alter table drink_publication_requests add constraint drink_pub_format_ck
  check (content_format in ('card','explainer','meme','jjeri_class','jjeri_anatomy'));

-- Keep the approved directive inside plan_json so the existing plan hash and review lifecycle cover it.
alter function drinks_validate_plan(text, jsonb, drink_topic_reviews) rename to drinks_validate_plan_before_jjeri;
create function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_base jsonb := drinks_validate_plan_before_jjeri(p_format, p_plan, p_review);
  v_episode jsonb := p_plan -> 'jjeri_class';
  v_anatomy jsonb := p_plan -> 'jjeri_anatomy';
  v_limits jsonb;
begin
  if v_anatomy is not null then
    if p_format <> 'video' or jsonb_typeof(v_anatomy) is distinct from 'object'
        or v_anatomy ->> 'format' is distinct from 'jjeri_anatomy'
        or v_anatomy -> 'version' is distinct from '1'::jsonb
        or jsonb_typeof(v_anatomy -> 'text_claim_ids') is distinct from 'object'
        or jsonb_typeof(v_anatomy -> 'worlds') is distinct from 'array'
        or octet_length(v_anatomy::text) > 65536 then
      perform drinks_fail('jjeri_directive_invalid', '영상 제작안에 유효한 술 해부 지시서를 넣어 주세요');
    end if;
    if jsonb_array_length(v_anatomy -> 'worlds') not between 2 and 5 then
      perform drinks_fail('jjeri_directive_invalid', '등록된 2~5개 세계의 술 해부 지시서가 필요합니다');
    end if;
    v_base := v_base || jsonb_build_object('jjeri_anatomy', v_anatomy);
  end if;
  if v_episode is null then return v_base; end if;
  v_limits := drinks_jjeri_render_status('{}'::jsonb);
  if p_format <> 'video' or jsonb_typeof(v_episode) is distinct from 'object'
      or v_episode ->> 'format' is distinct from 'jjeri_class'
      or v_episode -> 'version' is distinct from '1'::jsonb
      or jsonb_typeof(v_episode -> 'text_claim_ids') is distinct from 'object'
      or jsonb_typeof(v_episode -> 'scenes') is distinct from 'array'
      or octet_length(v_episode::text) > (v_limits ->> 'max_bytes')::int then
    perform drinks_fail('jjeri_directive_invalid', '영상 제작안에 유효한 째리의 술 수업 지시서를 넣어 주세요');
  end if;
  if jsonb_array_length(v_episode -> 'scenes')
       not between (v_limits ->> 'scene_min')::int and (v_limits ->> 'scene_max')::int then
    perform drinks_fail('jjeri_directive_invalid', format('째리의 술 수업은 %s~%s장면입니다',
      v_limits ->> 'scene_min', v_limits ->> 'scene_max'));
  end if;
  return v_base || jsonb_build_object('jjeri_class', v_episode);
end $$;

alter function drinks_request_render(jsonb) rename to drinks_request_render_before_jjeri;
create function drinks_request_render(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_existing uuid := drinks_uuid(p, 'retry_of', false);
begin
  if p ? 'renderer' then
    perform drinks_fail('invalid_input', '제작 형식에 맞는 렌더 요청을 사용하세요');
  end if;
  if v_existing is not null and exists (select 1 from drink_production_jobs where id = v_existing and renderer in ('jjeri_class','jjeri_anatomy')) then
    perform drinks_fail('invalid_state', '째리의 술 수업 형식을 선택한 뒤 재시도해 주세요');
  end if;
  return drinks_request_render_before_jjeri(p);
end $$;

-- Own the enqueue transaction here, independent of upgrades to drinks_request_render.
create function drinks_request_jjeri_format(p jsonb, v_renderer text) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  pl drink_plan_revisions; rv drink_topic_reviews; j drink_production_jobs; prev drink_production_jobs;
  v_existing uuid := drinks_uuid(p, 'retry_of', false);
  v_version text := case v_renderer when 'jjeri_class' then 'jjeri-class-v1' when 'jjeri_anatomy' then 'jjeri-anatomy-v1' end;
  v_hash text;
  v_attempt int;
begin
  if v_version is null or p ? 'renderer' then
    perform drinks_fail('invalid_input', '째리 모션 요청에 렌더러를 따로 지정할 수 없습니다');
  end if;
  if coalesce((p ->> 'paid')::boolean, false) or p ->> 'spend_approval_id' is not null then
    perform drinks_fail('paid_disabled', '째리 모션은 무료 렌더만 지원합니다');
  end if;

  perform drinks_reap_prod_jobs();
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  if not found then perform drinks_fail('not_found', '제작안을 찾지 못했습니다'); end if;
  if drinks_plan_renderable(pl.id) is not null then
    perform drinks_fail('not_renderable', '승인되고 근거가 유효한 제작안만 렌더합니다');
  end if;
  if pl.format <> 'video' or coalesce(pl.plan_json -> v_renderer ->> 'format', '') <> v_renderer then
    perform drinks_fail('jjeri_directive_missing', '승인된 제작안에 째리 모션 지시서가 없습니다');
  end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_hash := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|' || v_version, 'UTF8')), 'hex');

  if v_existing is not null then
    select * into prev from drink_production_jobs where id = v_existing and plan_revision_id = pl.id
      and renderer = v_renderer and input_hash = v_hash and status in ('failed','canceled');
    if not found then perform drinks_fail('invalid_state', '같은 입력으로 실패·취소된 째리 모션만 재시도합니다'); end if;
  end if;
  select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_hash
    and status in ('queued','running');
  if found then return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true, 'renderer', j.renderer); end if;
  v_attempt := 1 + (select count(*) from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_hash);
  insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, retry_of, input_hash,
      plan_hash, review_hash, renderer, renderer_version, requested_by)
    values (pl.topic_id, pl.id, pl.format, v_attempt, prev.id, v_hash, pl.approved_hash, rv.approved_hash,
      v_renderer, v_version, 'operator') returning * into j;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', pl.format, 'attempt_no', j.attempt_no, 'renderer', j.renderer));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', false, 'attempt_no', j.attempt_no, 'renderer', j.renderer);
end $$;


create function drinks_request_jjeri_render(p jsonb) returns jsonb language sql set search_path = public, pg_temp as $$
  select drinks_request_jjeri_format(p, 'jjeri_class')
$$;

create function drinks_request_jjeri_anatomy_render(p jsonb) returns jsonb language sql set search_path = public, pg_temp as $$
  select drinks_request_jjeri_format(p, 'jjeri_anatomy')
$$;

-- The server uses this read-only capability to keep older databases and rollback safe.
create function drinks_jjeri_render_status(p jsonb) returns jsonb
language sql stable set search_path = public, pg_temp as $$
  -- Keep these persistence bounds in sync with JJERI_* (PGlite contract test).
  select jsonb_build_object('ready', to_regprocedure('public.drinks_request_jjeri_render(jsonb)') is not null,
    'scene_min', 8, 'scene_max', 14, 'max_bytes', 65536)
    || case when p -> 'include_anatomy' = 'true'::jsonb
       then jsonb_build_object('anatomy_ready', to_regprocedure('public.drinks_request_jjeri_anatomy_render(jsonb)') is not null)
       else '{}'::jsonb end
$$;

-- Animation is a supported alternative for an approved video.
create or replace function drink_prod_jobs_explainer_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.retry_of is not null and exists (
    select 1 from drink_production_jobs previous where previous.id = new.retry_of
      and previous.renderer is distinct from new.renderer
      and (previous.renderer in ('jjeri_class','jjeri_anatomy') or new.renderer in ('jjeri_class','jjeri_anatomy'))
  ) then
    perform drinks_fail('invalid_state', '째리의 술 수업은 같은 형식으로만 재시도할 수 있습니다');
  end if;
  if new.renderer in ('jjeri_class','jjeri_anatomy') then
    if new.format <> 'video' or new.spend_approval_id is not null or not exists (
      select 1 from drink_plan_revisions pl where pl.id = new.plan_revision_id
        and pl.format = 'video' and pl.plan_json -> new.renderer ->> 'format' = new.renderer
    ) then
      perform drinks_fail('jjeri_directive_missing', '승인된 영상 제작안에 째리의 술 수업 지시서가 필요합니다');
    end if;
  elsif new.renderer like 'explainer\_%' then
    if not drinks_plan_is_explainer(new.plan_revision_id) then
      perform drinks_fail('not_renderable', '설명형으로 고른 소재의 영상 제작안이 아닙니다');
    end if;
  elsif drinks_plan_is_explainer(new.plan_revision_id) then
    perform drinks_fail('not_renderable', '설명형은 전부 영상이어야 해서 옛 그림 나열식으로 만들지 않습니다 — 설명형 제작으로 진행하세요');
  end if;
  return new;
end $$;

-- Set the type on insert so the existing immutability guard and returned row agree.
create function drink_pub_jjeri_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare old_format text := new.content_format;
begin
  if tg_op = 'INSERT' then
    select j.renderer into new.content_format
      from drink_manifest_assets ma
      join drink_media_assets a on a.id = ma.asset_id
      join drink_production_jobs j on j.id = a.job_id
      where ma.manifest_id = new.manifest_id and ma.role = 'final_video' and j.renderer in ('jjeri_class','jjeri_anatomy')
      limit 1;
    if not found then new.content_format := old_format; end if;
  elsif new.content_format in ('jjeri_class','jjeri_anatomy') and new.status is distinct from old.status
      and new.status in ('awaiting_approval', 'approved', 'scheduled', 'publishing') then
    perform drinks_fail('jjeri_owner_review_required', '째리의 술 수업은 소유자 최종 판정 대기 중입니다');
  end if;
  return new;
end $$;
create trigger drink_pub_jjeri_guard before insert or update on drink_publication_requests
  for each row execute function drink_pub_jjeri_guard();

-- Check for cancellation or invalid evidence under the registration transaction's lease lock.
alter function drinks_register_asset(jsonb) rename to drinks_register_asset_before_jjeri;
create function drinks_register_asset(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare j drink_production_jobs := drinks_lock_prod_job(p);
begin
  if j.renderer in ('jjeri_class','jjeri_anatomy') and (j.cancel_requested or drinks_plan_renderable(j.plan_revision_id) is not null) then
    perform drinks_fail('jjeri_render_canceled', '작업이 취소됐거나 승인 근거를 지금 쓸 수 없습니다');
  end if;
  return drinks_register_asset_before_jjeri(p);
end $$;

-- Workers without the renderer capability never claim that format.
create or replace function drinks_start_render(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare j drink_production_jobs; pl drink_plan_revisions; rv drink_topic_reviews; t drink_topics; v_block text; v_reaped int;
  ap drink_spend_approvals; v_card_manifest uuid; v_cards jsonb;
begin
  v_reaped := drinks_reap_prod_jobs();
  loop
    select * into j from drink_production_jobs where status = 'queued'
      and (renderer <> 'jjeri_class' or p -> 'allow_jjeri_class' = 'true'::jsonb)
      and (renderer <> 'jjeri_anatomy' or p -> 'allow_jjeri_anatomy' = 'true'::jsonb)
      order by created_at, id limit 1 for update skip locked;
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

revoke all on function drinks_validate_plan(text, jsonb, drink_topic_reviews),
  drinks_request_render(jsonb), drinks_request_jjeri_render(jsonb), drinks_request_jjeri_anatomy_render(jsonb),
  drinks_request_jjeri_format(jsonb,text), drinks_jjeri_render_status(jsonb),
  drinks_register_asset(jsonb), drink_pub_jjeri_guard() from public, anon, authenticated;
grant execute on function drinks_validate_plan(text, jsonb, drink_topic_reviews),
  drinks_request_render(jsonb), drinks_request_jjeri_render(jsonb), drinks_request_jjeri_anatomy_render(jsonb),
  drinks_request_jjeri_format(jsonb,text), drinks_jjeri_render_status(jsonb),
  drinks_register_asset(jsonb), drink_pub_jjeri_guard() to service_role;

commit;
