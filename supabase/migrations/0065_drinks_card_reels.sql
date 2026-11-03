-- 주류 카드뉴스 형식 엔진 (2026-11-02). docs/deviation-drinks-card-reels.md, 총괄계획 §4-2·§6 3단계, 기획 v2 §4·§7-3.
--
-- ★ 파일만 만든다. 운영 DB 적용은 따로 결재받는다.
--
-- 무엇이 바뀌나 — 왜
--   A. 카드뉴스도 내용 승인 한 번으로 간다. 0064 는 카드뉴스 대본 자동 작성이 없어 근거에서 card_plan_not_built 로 멈췄다.
--      [이걸로]에서 카드를 고르면 근거 초안 → 카드 제작안 초안(carousel)을 이어 만들고, [승인] 한 번이 근거·편성·카드 제작안을 승인한다.
--      승인 금액은 받지 않는다 — 카드 렌더는 0원이라 결재할 금액이 없다.
--   B. 한 제작안에서 카드뉴스와 릴스를 같이 낸다. 제작안에 reel 묶음(훅 제목·저장/보내기 한 줄)이 있으면 파일 묶음에 세로 영상 1개 + 표지 1개가 더 들어간다.
--      발행 요청은 post_type 으로 carousel·reel 을 고른다(같은 묶음, 같은 검수 한 번).
--   C. 음원 전달 계약(기획 v2 §7-3). 발행 요청에 audio 묶음을 저장하고 승인 지문에 넣는다. 승인 뒤 바꾸면 승인이 풀린다.
--      카드뉴스 릴스는 음원 필수다(mode='none' 불가). 음원을 못 붙이면 음원 없이 올리지 않고 멈춘다(paused, pause_code='audio_failed').
--
-- 안전 장치 — 약해지는 것이 없다
--   · 승인 전 카드 제작안도 draft 로만 존재한다. drink_plans_guard·drinks_plan_action·drinks_plan_renderable 을 고치지 않았다.
--   · 표시 없는 대본 요청은 그대로 review_not_approved 이고 영상 전용이다.
--   · 근거가 바뀌면 카드 제작안도 차단된다(drink_review_evidence_edited 는 형식을 가리지 않는다). 저장 때 값 대조, 승인 직전 값 대조도 같다.
--   · 개발 결재가 없으면 모델을 부르지 않는다. 워커는 승인·제출·편성 함수를 부르지 않는다.
--   · 설명형의 금액 검사·옛 렌더 차단(explainer_engine_not_wired)은 그대로다.
--   · 옛 행의 승인 지문은 그대로다 — audio 가 없으면 지문 계산이 0055 와 글자 하나까지 같다.
--
-- 기획과 다르게 정한 것(근거는 docs)
--   · 상태 audio_failed 를 새로 만들지 않고 paused + pause_code='audio_failed' 로 둔다. 멈춤·재개·취소 경로와 화면이 이미 있다.
--   · needs_reconfirm 도 새 상태가 아니라 awaiting_approval + pause_code='needs_reconfirm' 이다(이 칸은 예약 때 지워진다).
--   · verified_available_at 은 audio 묶음 안이 아니라 칸(audio_verified_at)이다. 묶음에 넣으면 재확인할 때마다 승인 지문이 바뀐다.
--
-- 되돌리기:
--   1. 0064 의 drinks_request_develop·drinks_start_develop·drinks_develop_save_plan·drinks_develop_chain_next·drinks_pick_topic·drinks_approve_content,
--      0057 의 drinks_validate_plan, 0053 의 drinks_output_review_action·drinks_finish_render,
--      0055 의 drinks_pub_transition_ok·drink_publications_guard·drinks_pub_digest·drinks_pub_block·drinks_create_publication·drinks_claim_publication·
--      drinks_publication_step·drinks_publish_board 를 다시 실행한다(그다음 0056 의 반복문도 한 번 더).
--   2. drop function drinks_set_publication_audio(jsonb); drop function drinks_pub_audio_clean(jsonb, text, drink_social_accounts, uuid);
--      drop function drinks_pub_audio_required(uuid, text); drop function drinks_format_required(jsonb, text); drop function drinks_card_reel_limits();
--   3. alter table drink_publication_requests drop column audio, drop column audio_verified_at;
--      alter table drink_plan_revisions drop constraint drink_plans_draft_flag_ck; 0064 의 제약을 다시 건다(승인 전 카드 제작안 행이 없을 때만 된다).
--   이미 만든 카드 묶음의 영상·표지 파일은 그대로 남고, 발행 요청의 음원 칸만 사라진다.

-- ─────────────────────────────────────────────────────────────
-- 표·칸
-- ─────────────────────────────────────────────────────────────

alter table drink_plan_revisions drop constraint if exists drink_plans_draft_flag_ck;
alter table drink_plan_revisions add constraint drink_plans_draft_flag_ck
  check (not drafted_from_unapproved or (format in ('video','carousel') and evidence_content_hash is not null));

alter table drink_publication_requests add column if not exists audio jsonb;                -- 기획 v2 §7-3 음원 묶음. null = 고르지 않음
alter table drink_publication_requests add column if not exists audio_verified_at timestamptz;   -- 게시 직전 재조회가 통과한 시각(지문 밖)
alter table drink_publication_requests drop constraint if exists drink_pub_audio_shape_ck;
alter table drink_publication_requests add constraint drink_pub_audio_shape_ck
  check (audio is null or (jsonb_typeof(audio) = 'object' and audio ->> 'mode' in ('ig_audio','licensed_mix','none')));

-- ─────────────────────────────────────────────────────────────
-- 규칙 함수
-- ─────────────────────────────────────────────────────────────

-- engine/config.py DRINKS_CARD_REEL_* 와 같아야 한다(tests/test_drinks_card_reel.py 가 대조).
create or replace function drinks_card_reel_limits() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object('min_pages', 4, 'max_pages', 12, 'hook_max', 40, 'share_max', 60)
$$;

-- 이 형식의 필수 주장. 비어 있으면 다른 형식의 목록, 그것도 없으면 핵심 주장 앞 3개(engine/config.py DRINKS_DEVELOP_REQUIRED_CLAIMS). 워커의 코드 검사와 같은 규칙이다.
create or replace function drinks_format_required(p_brief jsonb, p_format text) returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select coalesce(
    (select v from (select p_brief -> 'required_claims' -> p_format as v) a where jsonb_typeof(v) = 'array' and jsonb_array_length(v) > 0),
    (select v from (select p_brief -> 'required_claims' -> case p_format when 'video' then 'carousel' else 'video' end as v) b where jsonb_typeof(v) = 'array' and jsonb_array_length(v) > 0),
    (select coalesce(jsonb_agg(x order by o), '[]'::jsonb) from jsonb_array_elements(coalesce(p_brief -> 'selected_claim_ids', '[]'::jsonb)) with ordinality e(x, o) where o <= 3))
$$;

-- 음원이 필수인 게시인가: 카드 묶음을 릴스로 올리는 것(기획 v2 §7-3). 설명형 릴스는 나레이션이 있어 고르지 않아도 된다.
create or replace function drinks_pub_audio_required(p_manifest uuid, p_post_type text) returns boolean language sql stable set search_path = public, pg_temp as $$
  select p_post_type = 'reel' and coalesce((select format = 'carousel' from drink_asset_manifests where id = p_manifest), false)
$$;

-- 화면이 보낸 음원 선택 → 저장할 묶음. 제목·가수는 화면 값을 믿지 않고 고른 순간의 음원 표에서 복사한다. 값을 대신 채우지 않는다(볼륨·박자 등급은 화면이 정해 보낸다).
create or replace function drinks_pub_audio_clean(p_audio jsonb, p_type text, p_acc drink_social_accounts, p_manifest uuid)
returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_mode text; v_id text; v_sync text; a drink_ig_audio; v_av numeric; v_vv numeric; v_req boolean := drinks_pub_audio_required(p_manifest, p_type);
begin
  if p_audio is null or jsonb_typeof(p_audio) = 'null' then
    if v_req then perform drinks_fail('audio_required', '카드뉴스 릴스는 음원이 필수입니다'); end if;
    return null;
  end if;
  if jsonb_typeof(p_audio) <> 'object' then perform drinks_fail('invalid_input', '음원 설정 형식이 잘못됐습니다'); end if;
  if p_type <> 'reel' then perform drinks_fail('audio_not_for_carousel', '캐러셀에는 음원을 붙일 수 없습니다(문서에 없음) — 릴스로 올리세요'); end if;
  v_mode := drinks_text(p_audio, 'mode');
  if v_mode is null or v_mode not in ('ig_audio','licensed_mix','none') then perform drinks_fail('invalid_input', '음원 방식을 고르세요'); end if;
  if v_mode = 'none' then
    if v_req then perform drinks_fail('audio_required', '카드뉴스 릴스는 음원 없이 올리지 않습니다'); end if;
    return jsonb_build_object('mode', 'none', 'selected_by', 'operator', 'selected_at', now());
  end if;
  v_sync := drinks_text(p_audio, 'sync_grade');
  if v_sync is null or v_sync not in ('sync_free','sync_required') then perform drinks_fail('invalid_input', '박자 등급(sync_free·sync_required)을 고르세요'); end if;
  if v_mode = 'licensed_mix' then
    -- 렌더에 라이선스 음악을 까는 경로는 아직 없다. 조용히 무음 릴스가 나가지 않게 파일 기록으로 막는다.
    if not exists (select 1 from drink_manifest_assets ma join drink_media_assets x on x.id = ma.asset_id
        where ma.manifest_id = p_manifest and ma.role = 'final_video' and x.provenance ->> 'audio_mix' = 'licensed') then
      perform drinks_fail('licensed_mix_not_rendered', '이 영상에는 라이선스 음악이 깔려 있지 않습니다 — 인스타 음원을 고르세요');
    end if;
    return jsonb_build_object('mode', 'licensed_mix', 'sync_grade', v_sync, 'selected_by', 'operator', 'selected_at', now());
  end if;
  -- ig_audio: 음원을 붙이는 게시는 Facebook 로그인 연결로만 보낸다(기획 v2 §7-3 4번). 가짜 계정은 시험용이다.
  if p_acc.connection not in ('facebook_login','fake') then
    perform drinks_fail('audio_connection_unsupported', '인스타 음원은 Facebook 로그인 연결 계정으로만 붙입니다 — 이 계정은 ' || p_acc.connection || ' 입니다');
  end if;
  v_id := drinks_text(p_audio, 'audio_id');
  if v_id is null then perform drinks_fail('invalid_input', '음원을 고르세요'); end if;
  select * into a from drink_ig_audio where audio_id = v_id;
  if not found then perform drinks_fail('audio_not_found', '수집된 음원 목록에 없는 음원입니다'); end if;
  v_av := drinks_num(p_audio, 'audio_volume');
  v_vv := drinks_num(p_audio, 'video_volume');
  if v_av <> trunc(v_av) or v_av < 1 or v_av > 100 or v_vv <> trunc(v_vv) or v_vv < 1 or v_vv > 100 then
    perform drinks_fail('invalid_input', '음원·영상 볼륨은 1~100 정수입니다');
  end if;
  return jsonb_build_object('mode', 'ig_audio', 'audio_id', a.audio_id, 'audio_type', a.audio_type, 'title_snapshot', a.title,
    'artist_snapshot', a.display_artist, 'audio_volume', v_av::int, 'video_volume', v_vv::int, 'sync_grade', v_sync,
    'selected_by', 'operator', 'selected_at', now());
end $$;

-- 승인 지문: 음원이 있으면 묶음을 더한다. 없으면 0055 계산과 글자 하나까지 같다 — 이미 승인된 요청이 풀리지 않는다.
-- 고른 사람·시각은 뺀다(같은 음원을 다시 골라도 지문은 같다).
create or replace function drinks_pub_digest(r drink_publication_requests) returns text language sql stable set search_path = public, pg_temp as $$
  select encode(sha256(convert_to(concat_ws('|', 'drinks-pub-v1', r.manifest_id::text, r.manifest_hash, r.account_id::text,
    r.target_external_account_id, r.post_type, r.caption, coalesce(r.cover_asset_id::text, ''),
    coalesce(to_char(r.publish_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''))
    || case when r.audio is null then '' else '|audio:' || (r.audio - 'selected_by' - 'selected_at')::text end, 'UTF8')), 'hex')
$$;

create or replace function drinks_pub_block(p_id uuid) returns text language sql stable set search_path = public, pg_temp as $$
  select case
    when r.id is null then 'not_found'
    when r.approval_digest is distinct from drinks_pub_digest(r) then 'digest_changed'
    when not coalesce((select v.currently_usable from drink_output_validity v where v.review_id = r.output_review_id), false)
      then 'output_not_usable'
    when a.status = 'reauth_required' then 'account_reauth'
    when a.status <> 'active' then 'account_not_active'
    when not a.publish_enabled then 'publish_disabled'
    when a.external_account_id <> r.target_external_account_id then 'account_mismatch'
    -- 0065 음원: 필수인데 없음 / Facebook 로그인이 아닌 연결 / 박자를 맞춰야 해서 자동 게시 대상이 아님(시작 위치를 못 정한다, §7-2)
    when drinks_pub_audio_required(r.manifest_id, r.post_type) and coalesce(r.audio ->> 'mode', 'none') = 'none' then 'audio_missing'
    when r.audio ->> 'mode' = 'ig_audio' and a.connection not in ('facebook_login','fake') then 'audio_connection_unsupported'
    when r.audio ->> 'mode' = 'ig_audio' and r.audio ->> 'sync_grade' is distinct from 'sync_free' then 'audio_sync_required'
    else null end
  from (select 1) x left join drink_publication_requests r on r.id = p_id
    left join drink_social_accounts a on a.id = r.account_id
$$;

create or replace function drinks_pub_transition_ok(a text, b text) returns boolean language sql immutable set search_path = public, pg_temp as $$
  select a = b or (a, b) in (
    ('draft','awaiting_approval'), ('draft','canceled'),
    ('awaiting_approval','draft'), ('awaiting_approval','approved'), ('awaiting_approval','canceled'),
    ('approved','scheduled'), ('approved','paused'), ('approved','canceled'),
    ('scheduled','publishing'), ('scheduled','paused'), ('scheduled','canceled'),
    ('paused','scheduled'), ('paused','awaiting_approval'), ('paused','canceled'),
    ('publishing','published'), ('publishing','failed'), ('publishing','unknown'), ('publishing','paused'),
    ('publishing','canceled'),
    ('unknown','published'), ('unknown','failed'), ('unknown','canceled'),
    ('failed','scheduled'),
    -- 0065: 음원을 바꾸면 승인이 풀린다(drinks_set_publication_audio).
    ('approved','awaiting_approval'), ('scheduled','awaiting_approval'), ('failed','awaiting_approval'))
$$;

-- ─────────────────────────────────────────────────────────────
-- A. 카드뉴스 이어 만들기·한 번 승인 (0064 정의 + 카드뉴스)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_request_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_kind text := drinks_text(p, 'kind');
  v_budget uuid := drinks_uuid(p, 'budget_id', false); v_review uuid := drinks_uuid(p, 'review_id', false); bs jsonb;
  v_draft boolean := coalesce(p -> 'draft_evidence' = 'true'::jsonb, false);
  v_chain boolean := coalesce(p -> 'chain' = 'true'::jsonb, false);
  v_stop jsonb; v_intent text; v_fmt text;
begin
  if v_kind is null or v_kind not in ('evidence','plan') then perform drinks_fail('invalid_input', '종류는 evidence 또는 plan 입니다'); end if;
  if v_draft and v_kind <> 'plan' then perform drinks_fail('invalid_input', '승인 전 근거 표시는 대본 초안 요청에만 씁니다'); end if;
  if v_chain and v_kind <> 'evidence' then perform drinks_fail('invalid_input', '이어 만들기 표시는 근거 초안 요청에만 씁니다'); end if;
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  select * into q from drink_develop_requests where topic_id = t.id and kind = v_kind and status in ('queued','running');
  if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
  if v_budget is not null then
    bs := drinks_develop_budget_json(v_budget);
    if bs is null then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
    if bs ->> 'status' <> 'open' then perform drinks_fail('approval_closed', '닫힌 결재입니다'); end if;
    if (bs ->> 'expired')::boolean then perform drinks_fail('approval_expired', '결재 기간이 지났습니다 — 새로 결재받으세요'); end if;
    if (bs ->> 'remaining_usd')::numeric <= 0 then perform drinks_fail('budget_exceeded', '결재 금액을 모두 썼습니다'); end if;
  end if;
  if v_kind = 'evidence' then
    if t.status not in ('researching','ready','selected') then
      perform drinks_fail('invalid_state', '조사 후보로 고른 소재만 근거 초안을 만들 수 있습니다');
    end if;
    if exists (select 1 from drink_topic_reviews where topic_id = t.id and status = 'draft') then
      perform drinks_fail('draft_exists', '작성 중인 근거 버전이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
    if exists (select 1 from drink_topic_reviews where id = t.current_review_id and status = 'in_review') then
      perform drinks_fail('review_in_progress', '검토 중인 버전이 있습니다 — 승인하거나 변경 요청한 뒤 요청하세요');
    end if;
    v_review := null;
  elsif v_draft then
    -- 승인 전 근거로 대본 초안: 결재 필수, 설명형·카드뉴스로 고른 소재의 작업 중 근거만.
    if v_budget is null then perform drinks_fail('budget_missing', '결재(예산)가 없어 대본을 만들 수 없습니다 — 개발 결재를 열고 다시 요청하세요'); end if;
    if t.status <> 'researching' then perform drinks_fail('invalid_state', '근거를 작성 중인 소재에서만 승인 전 대본 초안을 만듭니다'); end if;
    select format_intent into v_intent from drink_topic_picks where topic_id = t.id;
    v_fmt := drinks_intent_format(v_intent);
    if v_fmt is null then
      perform drinks_fail('format_not_selected', '설명형·카드뉴스로 고른 소재만 승인 전 근거로 대본을 만듭니다');
    end if;
    select * into r from drink_topic_reviews where id = t.current_review_id;
    if not found or r.status <> 'draft' then
      perform drinks_fail('review_not_draft', '작성 중인 근거 버전이 없습니다 — 근거 초안을 먼저 만드세요');
    end if;
    if v_review is not null and v_review <> r.id then perform drinks_fail('review_not_current', '작업 중인 근거 버전으로만 만듭니다'); end if;
    v_review := r.id;
    v_stop := drinks_chain_stop_blockers(r.id);
    if jsonb_array_length(v_stop) > 0 then
      perform drinks_fail('evidence_not_usable', '근거에 고칠 곳이 있어 대본을 만들지 않았습니다 — 주장·인용을 먼저 고치세요', v_stop);
    end if;
    -- 옛 근거 버전을 가리키던 초안은 승인될 수 없다 — 새 대본의 자리를 비운다.
    update drink_plan_revisions set blocked_at = now(), blocked_reason = 'evidence_edited: 더 새로운 근거 버전이 있습니다'
      where topic_id = t.id and format = v_fmt and drafted_from_unapproved and plan_status = 'draft' and blocked_at is null
        and topic_review_id <> r.id;
    if exists (select 1 from drink_deliverables d join drink_plan_revisions pr on pr.deliverable_id = d.id
        where d.topic_id = t.id and d.format = v_fmt and pr.plan_status = 'draft' and pr.blocked_at is null) then
      perform drinks_fail('draft_exists', '이 근거로 만든 대본이 이미 있습니다');
    end if;
  else
    v_review := coalesce(v_review, t.approved_review_id);
    if v_review is null then perform drinks_fail('review_not_approved', '승인된 근거 버전이 있어야 제작안 초안을 만들 수 있습니다'); end if;
    select * into r from drink_topic_reviews where id = v_review;
    if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다'); end if;
    if r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then
      perform drinks_fail('review_not_approved', '승인되고 지금도 유효한 근거 버전으로만 제작안 초안을 만들 수 있습니다');
    end if;
    if t.status <> 'selected' or not 'video' = any(t.selected_formats) then
      perform drinks_fail('format_not_selected', '영상으로 편성된 소재만 제작안 초안을 만들 수 있습니다');
    end if;
    if exists (select 1 from drink_deliverables d join drink_plan_revisions pr on pr.deliverable_id = d.id
        where d.topic_id = t.id and d.format = 'video' and pr.plan_status = 'draft' and pr.blocked_at is null) then
      perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
  end if;
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id, chain, draft_evidence)
    values (t.id, v_kind, v_review, v_budget, v_chain, v_draft) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', v_kind, 'budget_id', v_budget, 'review_id', v_review, 'chain', v_chain, 'draft_evidence', v_draft));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

create or replace function drinks_start_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; v_reaped int; v_block text; v_budget jsonb; v_job jsonb; v_intent text;
begin
  v_reaped := drinks_reap_develop();
  loop
    select * into q from drink_develop_requests where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    select * into t from drink_topics where id = q.topic_id;
    select format_intent into v_intent from drink_topic_picks where topic_id = q.topic_id;
    v_block := null;
    if q.kind = 'evidence' then
      if t.status not in ('researching','ready','selected') then v_block := 'topic_state_changed'; end if;
    else
      select * into r from drink_topic_reviews where id = q.review_id;
      if q.draft_evidence then
        if t.status <> 'researching' then v_block := 'topic_state_changed';
        elsif r.status <> 'draft' or r.id is distinct from t.current_review_id then v_block := 'review_changed';
        elsif drinks_intent_format(v_intent) is null then v_block := 'format_not_selected'; end if;
      elsif r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then v_block := 'review_not_approved';
      elsif t.status <> 'selected' or not 'video' = any(t.selected_formats) then v_block := 'format_not_selected'; end if;
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

create or replace function drinks_develop_save_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_res jsonb; v_dver int; t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions;
  v_plan jsonb; v_no int; v_hash text; v_take text := left(drinks_text(p, 'core_takeaway_draft'), 300); v_fmt text; v_req jsonb;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'plan' then perform drinks_fail('invalid_state', '제작안 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  if not q.draft_evidence then
    select dv.version into v_dver from drink_deliverables dv where dv.topic_id = q.topic_id and dv.format = 'video' for update;
    v_res := drinks_save_plan(jsonb_build_object('topic_id', q.topic_id, 'format', 'video', 'topic_review_id', q.review_id,
      'plan_json', p -> 'plan_json') || case when v_dver is null then '{}'::jsonb
                                         else jsonb_build_object('expected_deliverable_version', v_dver) end);
    update drink_develop_requests set result_plan_revision_id = (v_res ->> 'revision_id')::uuid, step = 'plan_saved' where id = q.id;
    return v_res;
  end if;
  t := drinks_lock_topic(q.topic_id, null, false);
  select * into r from drink_topic_reviews where id = q.review_id for update;
  if t.status <> 'researching' or r.status <> 'draft' or t.current_review_id is distinct from r.id then
    perform drinks_fail('review_changed', '대본을 쓰는 사이 근거·소재 상태가 바뀌었습니다 — 저장하지 않습니다');
  end if;
  v_hash := drinks_evidence_content_hash(r.evidence_pack, r.brief);
  if q.evidence_hash is distinct from v_hash then
    perform drinks_fail('review_changed', '대본을 쓰는 사이 근거가 바뀌었습니다 — 바뀐 근거로 다시 만들어야 합니다');
  end if;
  v_fmt := drinks_intent_format((select format_intent from drink_topic_picks where topic_id = t.id));
  if v_fmt is null then
    perform drinks_fail('format_not_selected', '설명형·카드뉴스로 고른 소재가 아닙니다');
  end if;
  v_plan := drinks_validate_plan(v_fmt, p -> 'plan_json', r);
  -- 다른 형식으로 만든 근거면 이 형식의 필수 주장이 비어 있다 — 편성(drinks_select)이 막히기 전에 채운다. 형식을 바꾼 편의 옛 초안은 트리거가 차단한다.
  if cardinality(drinks_text_array(r.brief -> 'required_claims' -> v_fmt)) = 0 then
    v_req := drinks_format_required(r.brief, v_fmt);
    update drink_topic_reviews set brief = jsonb_set(jsonb_set(brief, '{required_claims}',
        coalesce(brief -> 'required_claims', '{}'::jsonb) || jsonb_build_object(v_fmt, v_req)), '{proposed_formats}', jsonb_build_array(v_fmt))
      where id = r.id returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    -- 트리거가 '쓰는 중인 요청'에 건 취소를 푼다 — 이 요청의 결과를 지금 저장하는 중이다.
    update drink_develop_requests set cancel_requested = false where id = q.id;
    v_hash := drinks_evidence_content_hash(r.evidence_pack, r.brief);
  end if;
  select * into d from drink_deliverables where topic_id = t.id and format = v_fmt and locale = 'ko' for update;
  if not found then
    insert into drink_deliverables (topic_id, format) values (t.id, v_fmt) returning * into d;
    perform drinks_log(t.id, 'deliverable', d.id, 'deliverable_created', null, null, v_fmt, null);
  end if;
  if exists (select 1 from drink_plan_revisions where deliverable_id = d.id and plan_status = 'draft' and blocked_at is null) then
    perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다');
  end if;
  if v_take is not null and drinks_text(r.brief, 'core_takeaway') is null then
    update drink_topic_reviews set brief = jsonb_set(brief, '{core_takeaway}', to_jsonb(v_take)) where id = r.id returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    perform drinks_log(t.id, 'review', r.id, 'core_takeaway_prefilled', 'draft', 'draft', r.input_hash, null, jsonb_build_object('request_id', q.id));
  end if;
  select coalesce(max(revision_no), 0) + 1 into v_no from drink_plan_revisions where deliverable_id = d.id;
  insert into drink_plan_revisions (deliverable_id, topic_id, format, revision_no, topic_review_id, plan_json, aspect_ratio,
      drafted_from_unapproved, evidence_content_hash)
    values (d.id, t.id, v_fmt, v_no, r.id, v_plan, case v_fmt when 'video' then '9:16' else '4:5' end, true, v_hash) returning * into pr;
  update drink_deliverables set current_revision_id = pr.id where id = d.id;
  update drink_develop_requests set result_plan_revision_id = pr.id, step = 'plan_saved' where id = q.id;
  perform drinks_log(t.id, 'plan', pr.id, 'plan_created', null, 'draft', pr.input_hash, null,
    jsonb_build_object('format', v_fmt, 'revision_no', v_no, 'topic_review_id', r.id, 'drafted_from_unapproved', true));
  return jsonb_build_object('revision_id', pr.id, 'deliverable_id', d.id, 'revision_no', pr.revision_no, 'version', pr.version,
    'input_hash', pr.input_hash, 'coverage', drinks_plan_coverage(v_fmt, pr.plan_json, r), 'drafted_from_unapproved', true);
end $$;

create or replace function drinks_develop_chain_next(q drink_develop_requests) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_intent text; v_stop jsonb; v_res jsonb;
begin
  select format_intent into v_intent from drink_topic_picks where topic_id = q.topic_id;
  if drinks_intent_format(v_intent) is null then
    return jsonb_build_object('queued', false, 'code', 'format_not_selected', 'message', '설명형·카드뉴스로 고른 소재가 아니라 대본을 이어 만들지 않았습니다');
  end if;
  if q.budget_id is null then
    return jsonb_build_object('queued', false, 'code', 'budget_missing', 'message', '개발 결재가 없어 대본을 만들지 않았습니다');
  end if;
  v_stop := drinks_chain_stop_blockers(q.result_review_id);
  if jsonb_array_length(v_stop) > 0 then
    return jsonb_build_object('queued', false, 'code', 'evidence_not_usable', 'blockers', v_stop, 'message',
      '근거에 고칠 곳이 있어 대본을 만들지 않았습니다 — 돈을 쓰기 전에 멈췄습니다. 주장·인용을 고친 뒤 대본을 다시 요청하세요');
  end if;
  begin
    v_res := drinks_request_develop(jsonb_build_object('topic_id', q.topic_id, 'kind', 'plan', 'budget_id', q.budget_id, 'draft_evidence', true));
    return jsonb_build_object('queued', true, 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
  exception when raise_exception then
    if sqlerrm not like 'drinks:%' then raise; end if;
    return jsonb_build_object('queued', false, 'code', split_part(sqlerrm, ':', 2), 'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
  end;
end $$;

create or replace function drinks_pick_topic(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_format text := drinks_text(p, 'format'); v_cand uuid := drinks_uuid(p, 'candidate_id', false); v_topic uuid := drinks_uuid(p, 'topic_id', false);
  v_week date := drinks_date(p, 'editorial_week'); v_budget uuid := drinks_uuid(p, 'budget_id', false);
  c drink_discovery_candidates; t drink_topics; r drink_topic_reviews; v_res jsonb; v_chain jsonb; v_created boolean := false; v_fits jsonb;
  v_prev text; v_fmt text := drinks_intent_format(v_format); v_old uuid;
begin
  if v_format is null or v_format not in ('explainer','card','meme') then perform drinks_fail('invalid_input', '형식(설명형·카드뉴스·밈형)을 고르세요'); end if;
  if v_week is null then perform drinks_fail('invalid_input', '편성 주차를 고르세요'); end if;
  v_week := v_week - (extract(isodow from v_week)::int - 1);
  if (v_cand is null) = (v_topic is null) then perform drinks_fail('invalid_input', '후보 또는 소재 중 하나를 지정하세요'); end if;
  if v_cand is not null then
    select * into c from drink_discovery_candidates where id = v_cand;
    if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
    if c.provisional_score is null then
      perform drinks_fail('scores_incomplete', '이 후보에는 임시 점수가 없습니다 — 소재로 올린 뒤 경량 평가를 먼저 하세요');
    end if;
    v_res := drinks_promote_candidate(p - 'topic_id');
    v_topic := (v_res ->> 'topic_id')::uuid;
    v_created := true;
    t := drinks_lock_topic(v_topic, null, false);
    v_fits := jsonb_strip_nulls(jsonb_build_object('fit_video', c.fit_video, 'fit_carousel', c.fit_carousel));
    update drink_topics set status = 'triaged', provisional_score = c.provisional_score, provisional_rubric = c.rubric,
      provisional_scores = case when v_fits = '{}'::jsonb then null else v_fits end,
      triage_reason = c.score_reason
      where id = t.id returning * into t;
    perform drinks_log(t.id, 'topic', t.id, 'triaged', 'inbox', t.status, c.rubric, '후보 임시 점수를 옮김',
      jsonb_build_object('candidate_id', c.id, 'score', c.provisional_score));
  else
    t := drinks_lock_topic(v_topic, drinks_int(p, 'expected_version', false), false);
  end if;
  if t.status = 'triaged' then
    perform drinks_topic_action(jsonb_build_object('topic_id', t.id, 'expected_version', t.version, 'action', 'start_research'));
    t := drinks_lock_topic(t.id, null, false);
  end if;
  if t.status = 'inbox' then
    perform drinks_fail('invalid_state', '경량 평가를 먼저 하세요(요약 탭)');
  elsif t.status in ('ready','selected') then
    perform drinks_fail('invalid_state', '이미 근거가 승인된 소재입니다 — 기존 공통 기획·제작안 탭에서 이어 가세요');
  elsif t.status <> 'researching' then
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재입니다 — 다시 연 뒤에 고르세요');
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if found and r.status = 'in_review' then
    perform drinks_fail('review_in_progress', '검토 중인 근거 버전이 있습니다 — 공통 기획 탭에서 승인하거나 변경 요청한 뒤 고르세요');
  end if;
  select format_intent into v_prev from drink_topic_picks where topic_id = t.id;
  -- 형식을 바꾸면 옛 형식으로 쓰던 대본 요청을 거둔다. 그대로 두면 워커가 새 형식으로 읽어 다른 틀의 대본을 쓴다.
  if v_prev is distinct from v_format then
    for v_old in select id from drink_develop_requests where topic_id = t.id and kind = 'plan' and draft_evidence and status in ('queued','running') loop
      perform drinks_cancel_develop(jsonb_build_object('request_id', v_old));
    end loop;
  end if;
  insert into drink_topic_picks (topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id)
    values (t.id, v_format, drinks_text(p, 'recommended_format'), left(drinks_text(p, 'recommended_reason'), 500), v_week, v_budget, v_cand)
    on conflict (topic_id) do update set format_intent = excluded.format_intent, recommended_format = excluded.recommended_format,
      recommended_reason = excluded.recommended_reason, editorial_week = excluded.editorial_week, budget_id = excluded.budget_id,
      candidate_id = coalesce(drink_topic_picks.candidate_id, excluded.candidate_id), approved_at = null, approved_amount_usd = null;
  perform drinks_log(t.id, 'topic', t.id, 'format_picked', t.status, t.status, v_format, null,
    jsonb_build_object('format_intent', v_format, 'maps_to', drinks_intent_format(v_format), 'recommended_format', drinks_text(p, 'recommended_format'),
      'editorial_week', v_week, 'budget_id', v_budget, 'candidate_id', v_cand));
  if v_format = 'meme' then
    v_chain := jsonb_build_object('queued', false, 'code', 'meme_board', 'message',
      '밈형은 근거·대본을 만들지 않습니다. 형식만 적어 두었고, 제작은 밈 보드에서 이어집니다(밈 제작 엔진은 아직 없습니다)');
  elsif r.id is not null and r.status = 'draft' then
    if exists (select 1 from drink_plan_revisions pl where pl.topic_review_id = r.id and pl.format = v_fmt and pl.plan_status = 'draft' and pl.blocked_at is null) then
      v_chain := jsonb_build_object('queued', false, 'code', 'already_drafted', 'message', '이 근거로 만든 대본이 이미 있습니다');
    else
      v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true)));
      v_chain := jsonb_build_object('queued', true, 'kind', 'plan', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
    end if;
  else
    v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', true)));
    v_chain := jsonb_build_object('queued', true, 'kind', 'evidence', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
  end if;
  return jsonb_build_object('topic_id', t.id, 'created', v_created, 'status', t.status, 'format_intent', v_format,
    'maps_to', drinks_intent_format(v_format), 'editorial_week', v_week, 'chain', v_chain);
end $$;

create or replace function drinks_approve_content(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions; pk drink_topic_picks;
  v_amount numeric; v_note text := drinks_text(p, 'note'); v_id uuid; v_hash text; v_sel jsonb; v_planned jsonb;
begin
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_topic_version'));
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
  select * into pk from drink_topic_picks where topic_id = t.id for update;
  if not found then perform drinks_fail('format_not_selected', '[이걸로]로 형식을 고른 소재만 한 번에 승인합니다 — 기존 탭을 쓰세요'); end if;
  if drinks_intent_format(pk.format_intent) is null or pr.format <> drinks_intent_format(pk.format_intent) then
    perform drinks_fail('format_not_selected', '고른 형식의 제작안이 아닙니다 — 형식을 다시 고르거나 그 형식의 대본을 만드세요');
  end if;
  if t.status <> 'researching' then
    perform drinks_fail('invalid_state', '근거를 작성 중인 소재만 한 번에 승인합니다 — 기존 탭을 쓰세요');
  end if;
  if t.current_review_id is distinct from r.id then perform drinks_fail('review_not_current', '최신 근거 버전이 아닙니다'); end if;
  if r.status not in ('draft','in_review') then perform drinks_fail('invalid_state', '이미 결정된 근거 버전입니다 — 기존 탭을 쓰세요'); end if;
  if not pr.drafted_from_unapproved or pr.plan_status <> 'draft' then
    perform drinks_fail('invalid_state', '승인 전 근거로 만든 작성 중 대본만 한 번에 승인합니다');
  end if;
  if d.current_revision_id is distinct from pr.id then perform drinks_fail('plan_not_current', '최신 대본이 아닙니다'); end if;
  if pr.blocked_at is not null then
    perform drinks_fail('plan_blocked', '이 대본을 만든 뒤 근거가 바뀌었습니다 — 이 근거로 대본을 다시 만들어야 승인할 수 있습니다');
  end if;
  -- ★ 대본이 기댄 근거가 바로 지금 승인하는 근거인가. 트리거가 차단하지만, 승인 직전에 값으로 한 번 더 잰다.
  if pr.topic_review_id is distinct from r.id
      or pr.evidence_content_hash is distinct from drinks_evidence_content_hash(r.evidence_pack, r.brief) then
    perform drinks_fail('plan_stale', '대본이 지금 근거 내용으로 만들어진 것이 아닙니다 — 이 근거로 대본을 다시 만드세요');
  end if;
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', '초안을 만드는 중입니다 — 끝난 뒤에 승인하세요');
  end if;
  -- 승인 금액: 기록만 한다. 결재를 열지 않는다. 상한은 유료 결재 1건 상한(0054)과 같다. 카드뉴스는 로컬 렌더 0원이라 금액을 받지 않는다.
  if pr.format = 'video' then
    v_amount := drinks_num(p, 'approved_amount_usd');
    if v_amount <= 0 or v_amount > (drinks_spend_limits() ->> 'max_cap_usd')::numeric then
      perform drinks_fail('invalid_input', '승인 금액은 0 보다 크고 $' || (drinks_spend_limits() ->> 'max_cap_usd') || ' 이하여야 합니다');
    end if;
  end if;

  -- 1) 근거: 작성 중 → 검토 → 승인. drinks_review_action 이 필수 조건(support_review·핵심 메시지·점수·인용·사용 조건)을 다시 잰다.
  if r.status = 'draft' then
    perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'submit'));
    select * into r from drink_topic_reviews where id = r.id;
  end if;
  perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'approve', 'reason', v_note));
  select * into r from drink_topic_reviews where id = r.id;
  -- 2) 편성: [이걸로] 때 고른 주차·형식. drinks_select 가 65점 기준·형식 적합성·필수 주장을 다시 잰다.
  select * into t from drink_topics where id = t.id;
  v_sel := drinks_select(jsonb_build_object('topic_id', t.id, 'expected_version', t.version, 'review_id', r.id,
    'review_input_hash', r.approved_hash, 'formats', jsonb_build_array(pr.format), 'editorial_week', to_char(pk.editorial_week, 'YYYY-MM-DD'),
    'score_exception_reason', drinks_text(p, 'score_exception_reason'), 'format_exceptions', coalesce(p -> 'format_exceptions', '{}'::jsonb)));
  -- 3) 대본: 사람이 채운 칸이 근거 해시에 들어갔으니 제작안 해시를 승인된 근거 기준으로 다시 잰다(본문은 그대로) → 제출 → 승인.
  update drink_plan_revisions set updated_at = now() where id = pr.id returning * into pr;
  perform drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'submit'));
  select * into pr from drink_plan_revisions where id = pr.id;
  v_planned := drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'approve', 'reason', v_note));
  select * into pr from drink_plan_revisions where id = pr.id;

  update drink_topic_picks set approved_at = now(), approved_amount_usd = v_amount where topic_id = t.id;
  select * into t from drink_topics where id = t.id;
  perform drinks_log(t.id, 'topic', t.id, 'content_approved', 'researching', t.status, pr.id::text, v_note,
    jsonb_build_object('review_id', r.id, 'review_hash', r.approved_hash, 'plan_revision_id', pr.id, 'plan_hash', pr.approved_hash,
      'format_intent', pk.format_intent, 'approved_amount_usd', v_amount, 'spend_approval_opened', false));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version, 'review_id', r.id, 'review_status', r.status,
    'plan_revision_id', pr.id, 'plan_status', pr.plan_status, 'selected_formats', v_sel -> 'selected_formats',
    'editorial_week', v_sel -> 'editorial_week', 'approved_amount_usd', v_amount, 'coverage', v_planned -> 'coverage');
end $$;

-- ─────────────────────────────────────────────────────────────
-- B. 제작안의 릴스 묶음·파일 묶음 규칙 (0057·0053 정의 + 릴스)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  core text[] := drinks_text_array(p_review.brief -> 'selected_claim_ids');
  all_claims text[] := array(select x ->> 'claim_id' from jsonb_array_elements(p_review.evidence_pack -> 'claims') x);
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; out jsonb := '[]'; i int := 0; cids text[]; cid text; v_role text; v_kind text; n int;
  v_reel jsonb := p_plan -> 'reel'; lim jsonb := drinks_card_reel_limits(); v_hook text; v_share text;
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
  -- 0065: 카드뉴스 릴스 묶음. 없으면 옛 제작안과 똑같다(입력 해시도 같다).
  if v_reel is null or jsonb_typeof(v_reel) = 'null' then
    return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
      'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1'));
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
    'reel', jsonb_build_object('hook_title', v_hook, 'share_line', v_share));
end $$;

create or replace function drinks_output_review_action(p jsonb) returns jsonb language plpgsql as $$
declare r drink_output_reviews; v_action text := drinks_text(p, 'action'); v_block text; ck jsonb := p -> 'checklist';
  k text; required text[];
begin
  select * into r from drink_output_reviews where id = drinks_uuid(p, 'review_id') for update;
  if not found then perform drinks_fail('not_found', '검수 기록을 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from r.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  if r.status not in ('pending','changes_requested') and v_action <> 'revoke' then
    perform drinks_fail('invalid_state', '검수 대기 중인 묶음만 판정합니다');
  end if;
  if v_action = 'approve' then
    -- 권리 철회·근거 무효화는 제작안 행을 바꾼다(blocked_at). 그 행을 먼저 잠가 진행 중인 철회를 기다린 뒤 다시 잰다 —
    -- 아니면 아직 커밋 안 된 철회를 못 보고 승인이 통과한다(실제 Postgres 경합 ⑭).
    perform 1 from drink_plan_revisions where id = r.plan_revision_id for share;
    v_block := drinks_plan_renderable(r.plan_revision_id);
    if v_block is not null then
      update drink_output_reviews set status = 'blocked', reason = '승인 시점 재검사: ' || v_block where id = r.id returning * into r;
      return jsonb_build_object('review_id', r.id, 'status', r.status, 'blocked_by', v_block);
    end if;
    required := case (select format from drink_asset_manifests where id = r.manifest_id)
      when 'video' then array['scene_types_labeled','no_real_product_implied','claims_match_evidence','audio_subtitles_ok','vertical_ok']
      else array['page_order_ok','no_text_overflow','claims_match_evidence','source_page_ok'] end;
    -- 0065: 같은 묶음에 릴스가 들었으면 사람이 영상도 본다.
    if exists (select 1 from drink_manifest_assets ma join drink_asset_manifests m on m.id = ma.manifest_id
        where ma.manifest_id = r.manifest_id and ma.role = 'final_video' and m.format = 'carousel') then
      required := required || array['reel_motion_ok','reel_hook_share_ok'];
    end if;
    if ck is null or jsonb_typeof(ck) <> 'object' then perform drinks_fail('invalid_input', '검수 체크리스트가 필요합니다'); end if;
    foreach k in array required loop
      if coalesce((ck ->> k)::boolean, false) is not true then
        perform drinks_fail('checklist_incomplete', '확인하지 않은 검수 항목이 있습니다: ' || k, to_jsonb(required));
      end if;
    end loop;
    update drink_output_reviews set status = 'approved', checklist = ck, reviewer = coalesce(drinks_text(p, 'reviewer'), 'operator'),
      reviewed_at = now(), reason = drinks_text(p, 'reason') where id = r.id returning * into r;
  elsif v_action = 'request_changes' then
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '고칠 점을 적으세요'); end if;
    update drink_output_reviews set status = 'changes_requested', reason = drinks_text(p, 'reason'), checklist = ck,
      reviewed_at = now() where id = r.id returning * into r;
  elsif v_action = 'revoke' then
    if r.status <> 'approved' then perform drinks_fail('invalid_state', '승인된 검수만 철회합니다'); end if;
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '철회 사유를 적으세요'); end if;
    update drink_output_reviews set status = 'blocked', revoked_at = now(), reason = drinks_text(p, 'reason')
      where id = r.id returning * into r;
  else
    perform drinks_fail('invalid_input', '알 수 없는 검수 동작입니다');
  end if;
  perform drinks_log((select topic_id from drink_plan_revisions where id = r.plan_revision_id), 'plan', r.plan_revision_id,
    'output_review_' || v_action, null, r.status, r.manifest_id::text, r.reason);
  return jsonb_build_object('review_id', r.id, 'status', r.status, 'version', r.version);
end $$;

create or replace function drinks_finish_render(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs; m drink_asset_manifests; el jsonb; v_hash text; v_block text; v_review drink_output_reviews;
  n_final int; n_cover int; n_pages int; max_pos int; v_want_reel int;
begin
  j := drinks_lock_prod_job(p);
  if drinks_text(p, 'outcome') = 'failed' or j.cancel_requested then
    update drink_production_jobs set status = case when j.cancel_requested then 'canceled' else 'failed' end, finished_at = now(),
      lease_token = null, error_code = coalesce(drinks_text(p, 'error_code'), case when j.cancel_requested then 'canceled' end),
      error_message = left(drinks_text(p, 'error_message'), 2000) where id = j.id returning * into j;
    return jsonb_build_object('job_id', j.id, 'status', j.status);
  end if;
  if jsonb_typeof(p -> 'assets') is distinct from 'array' or jsonb_array_length(p -> 'assets') = 0 then
    perform drinks_fail('invalid_input', '묶음에 들어갈 파일이 없습니다');
  end if;
  -- 파일은 이 작업이 등록한 것만. 역할·순서 규칙을 DB 가 잰다.
  if exists (select 1 from jsonb_array_elements(p -> 'assets') e where not exists (select 1 from drink_media_assets a
      where a.id = (e ->> 'asset_id')::uuid and a.job_id = j.id and a.state = 'stored')) then
    perform drinks_fail('ownership', '이 작업이 등록하지 않은 파일이 묶음에 있습니다');
  end if;
  select count(*) filter (where e ->> 'role' = 'final_video'), count(*) filter (where e ->> 'role' = 'cover'),
    count(*) filter (where e ->> 'role' = 'page'), max(((e ->> 'position')::int)) filter (where e ->> 'role' = 'page')
    into n_final, n_cover, n_pages, max_pos from jsonb_array_elements(p -> 'assets') e;
  if j.format = 'video' and (n_final <> 1 or n_cover <> 1 or n_pages <> 0) then
    perform drinks_fail('invalid_manifest', '영상 묶음은 최종 영상 1개와 커버 1개여야 합니다');
  end if;
  -- 0065: 제작안에 릴스 묶음이 있으면 카드 묶음에 영상 1개 + 표지 1개가 함께 든다. 없으면 옛 규칙 그대로(영상 0개).
  select case when plan_json ? 'reel' then 1 else 0 end into v_want_reel from drink_plan_revisions where id = j.plan_revision_id;
  if j.format = 'carousel' and (n_final <> v_want_reel or (v_want_reel = 1 and n_cover <> 1)) then
    perform drinks_fail('invalid_manifest', '릴스 묶음이 있는 카드 제작안은 영상 1개·표지 1개가, 없는 제작안은 영상 0개가 들어야 합니다');
  end if;
  if j.format = 'carousel' and (n_pages = 0 or max_pos <> n_pages
      or (select count(distinct (e ->> 'position')::int) from jsonb_array_elements(p -> 'assets') e where e ->> 'role' = 'page') <> n_pages
      or n_pages <> jsonb_array_length(coalesce((select plan_json -> 'pages' from drink_plan_revisions where id = j.plan_revision_id), '[]'))) then
    perform drinks_fail('invalid_manifest', '카드 묶음은 제작안 페이지 수만큼 1부터 빈칸·중복 없이 이어져야 합니다');
  end if;
  v_hash := encode(sha256(convert_to(j.input_hash || '|' || (select string_agg((e ->> 'role') || ':' || (e ->> 'position') || ':' ||
      (select a.sha256 from drink_media_assets a where a.id = (e ->> 'asset_id')::uuid), ',' order by e ->> 'role', ((e ->> 'position')::int))
    from jsonb_array_elements(p -> 'assets') e), 'UTF8')), 'hex');
  select * into m from drink_asset_manifests where plan_revision_id = j.plan_revision_id and manifest_hash = v_hash;
  if not found then
    insert into drink_asset_manifests (plan_revision_id, job_id, format, manifest_hash, input_hash)
      values (j.plan_revision_id, j.id, j.format, v_hash, j.input_hash) returning * into m;
    insert into drink_manifest_assets (manifest_id, asset_id, role, position)
      select m.id, (e ->> 'asset_id')::uuid, e ->> 'role', coalesce((e ->> 'position')::int, 1) from jsonb_array_elements(p -> 'assets') e;
  end if;
  v_block := drinks_plan_renderable(j.plan_revision_id);
  insert into drink_output_reviews (manifest_id, plan_revision_id, status, qa_summary, reason)
    values (m.id, j.plan_revision_id, case when v_block is null then 'pending' else 'blocked' end,
      coalesce(case when jsonb_typeof(p -> 'qa') = 'object' then p -> 'qa' end, '{}'),
      case when v_block is not null then '렌더 중 근거·제작안이 무효가 됨(' || v_block || ') — 파일·비용은 보존' end)
    on conflict (manifest_id) do nothing returning * into v_review;
  update drink_production_jobs set status = 'succeeded', finished_at = now(), lease_token = null, result_manifest_id = m.id
    where id = j.id returning * into j;
  perform drinks_log(j.topic_id, 'plan', j.plan_revision_id, 'render_finished', 'running', 'succeeded', m.id::text, v_block,
    jsonb_build_object('format', j.format, 'manifest_hash', v_hash, 'review', coalesce(v_review.status, 'existing')));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'manifest_id', m.id, 'manifest_hash', v_hash,
    'review_status', coalesce(v_review.status, (select status from drink_output_reviews where manifest_id = m.id)));
end $$;

-- ─────────────────────────────────────────────────────────────
-- C. 음원 계약 (0055 정의 + audio)
-- ─────────────────────────────────────────────────────────────

create or replace function drink_publications_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '발행 요청은 삭제할 수 없습니다(취소로 표시)'); end if;
  if old.status <> 'draft' and (new.manifest_id, new.manifest_hash, new.account_id, new.target_external_account_id,
      new.post_type, new.caption, new.cover_asset_id, new.publish_at, new.plan_revision_id, new.output_review_id)
      is distinct from (old.manifest_id, old.manifest_hash, old.account_id, old.target_external_account_id,
      old.post_type, old.caption, old.cover_asset_id, old.publish_at, old.plan_revision_id, old.output_review_id) then
    perform drinks_fail('immutable', '작성 중이 아닌 발행 요청의 내용은 바꿀 수 없습니다 — 취소하고 새로 만드세요');
  end if;
  -- 0065: 작성 중 요청을 취소하면 표 제약(status='draft' 또는 지문 있음)에 걸려 취소가 안 됐다(0055 결함). 음원이 없어 보류할 때 이 길이 필요하다.
  if new.status = 'canceled' and new.approval_digest is null then new.approval_digest := drinks_pub_digest(new); end if;
  -- 0065: 음원은 작성 중이거나, 승인을 풀면서만 바뀐다(drinks_set_publication_audio).
  if old.status <> 'draft' and new.audio is distinct from old.audio and not (new.status = 'awaiting_approval' and new.approved_at is null) then
    perform drinks_fail('immutable', '승인을 풀지 않고 음원을 바꿀 수 없습니다');
  end if;
  if new.status = 'awaiting_approval' and old.status <> 'awaiting_approval' and drinks_pub_audio_required(new.manifest_id, new.post_type)
      and coalesce(new.audio ->> 'mode', 'none') = 'none' then
    perform drinks_fail('audio_required', '카드뉴스 릴스는 음원이 필수입니다 — 음원을 고른 뒤 승인 요청하세요');
  end if;
  if old.status = 'published' and new.status = 'published' and (new.external_post_id is distinct from old.external_post_id) then
    perform drinks_fail('immutable', '게시된 요청의 외부 게시물 ID 는 바꿀 수 없습니다');
  end if;
  if not drinks_pub_transition_ok(old.status, new.status) then
    perform drinks_fail('invalid_transition', '발행 요청 ' || old.status || ' → ' || new.status || ' 는 허용되지 않습니다');
  end if;
  if old.status in ('published','canceled') and to_jsonb(new) - array['reconcile_state','external_url','version','updated_at']
      is distinct from to_jsonb(old) - array['reconcile_state','external_url','version','updated_at'] then
    perform drinks_fail('immutable', '끝난 발행 요청은 바꿀 수 없습니다');
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;

create or replace function drinks_create_publication(p jsonb) returns jsonb language plpgsql as $$
declare o drink_output_reviews; m drink_asset_manifests; pl drink_plan_revisions; a drink_social_accounts;
  r drink_publication_requests; v_type text; v_cover uuid; v_pages int; v_want text := drinks_text(p, 'post_type'); v_audio jsonb;
begin
  select * into o from drink_output_reviews where id = drinks_uuid(p, 'output_review_id');
  if not found then perform drinks_fail('not_found', '검수 기록을 찾지 못했습니다'); end if;
  if not coalesce((select currently_usable from drink_output_validity where review_id = o.id), false) then
    perform drinks_fail('output_not_usable', '검수 승인된(그리고 지금도 근거가 유효한) 파일 묶음만 발행합니다');
  end if;
  select * into m from drink_asset_manifests where id = o.manifest_id;
  select * into pl from drink_plan_revisions where id = o.plan_revision_id;
  select * into a from drink_social_accounts where id = drinks_uuid(p, 'account_id');
  if not found then perform drinks_fail('not_found', '계정을 고르세요(기본 계정은 없습니다)'); end if;
  if a.status = 'disabled' then perform drinks_fail('invalid_state', '사용 중지된 계정입니다'); end if;
  v_type := case m.format when 'carousel' then 'carousel' else 'reel' end;
  -- 0065: 카드 묶음에 영상이 들었으면 같은 묶음을 릴스로도 올린다.
  if v_want is not null and v_want <> v_type then
    if not (v_want = 'reel' and m.format = 'carousel' and exists (select 1 from drink_manifest_assets where manifest_id = m.id and role = 'final_video')) then
      perform drinks_fail('invalid_input', '이 파일 묶음은 ' || v_want || ' 로 올릴 수 없습니다');
    end if;
    v_type := v_want;
  end if;
  if not coalesce(a.capabilities -> 'post_types' ? v_type, false) then
    perform drinks_fail('capability_missing', '이 계정은 ' || v_type || ' 게시가 확인되지 않았습니다(계정 기능 목록)');
  end if;
  if v_type = 'carousel' then
    select count(*) into v_pages from drink_manifest_assets where manifest_id = m.id and role = 'page';
    if v_pages < 2 or v_pages > drinks_pub_limit(a, 'carousel_max_items') then
      perform drinks_fail('capability_missing', '캐러셀은 2~' || drinks_pub_limit(a, 'carousel_max_items') || '장이어야 합니다(지금 '
        || v_pages || '장)');
    end if;
  else
    select asset_id into v_cover from drink_manifest_assets where manifest_id = m.id and role = 'cover';
  end if;
  perform drinks_check_caption(coalesce(p ->> 'caption', ''), a);
  -- 음원은 여기서 고르지 않아도 된다(작성 중). 승인 요청 때 필수 여부를 잰다.
  if p -> 'audio' is not null and jsonb_typeof(p -> 'audio') <> 'null' then
    v_audio := drinks_pub_audio_clean(p -> 'audio', v_type, a, m.id);
  end if;
  begin
    insert into drink_publication_requests (topic_id, plan_revision_id, output_review_id, manifest_id, manifest_hash, post_type,
      account_id, target_external_account_id, caption, cover_asset_id, publish_at, audio)
    values (pl.topic_id, pl.id, o.id, m.id, m.manifest_hash, v_type, a.id, a.external_account_id, coalesce(p ->> 'caption', ''),
      v_cover, (drinks_text(p, 'publish_at'))::timestamptz, v_audio)
    returning * into r;
  exception when unique_violation then
    perform drinks_fail('duplicate_publication', '이 제작안·계정·형식에는 이미 살아 있는(또는 게시된) 발행 요청이 있습니다');
  end;
  perform drinks_pub_log(r, 'created', null, null);
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'post_type', r.post_type, 'audio', r.audio);
end $$;

create or replace function drinks_claim_publication(p jsonb) returns jsonb language plpgsql as $$
declare r drink_publication_requests; a drink_social_accounts; v_block text; v_reaped int; v_paused int := 0;
  v_grace int := (drinks_publish_limits() ->> 'late_grace_sec')::int; att drink_publication_attempts; pl drink_plan_revisions;
  rv drink_topic_reviews;
begin
  v_reaped := drinks_reap_publications();
  loop
    select * into r from drink_publication_requests where status = 'scheduled' and publish_at <= now()
      order by publish_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('request', null, 'reaped', v_reaped, 'paused', v_paused); end if;
    v_block := drinks_pub_block(r.id);
    if v_block is null and r.cancel_requested then v_block := 'cancel_requested'; end if;
    if v_block is null and r.publish_at < now() - make_interval(secs => v_grace) then v_block := 'late'; end if;
    if v_block is not null then
      update drink_publication_requests set status = 'paused', pause_code = v_block,
        pause_reason = case v_block when 'late' then '예약 시각보다 2시간 넘게 늦어 게시하지 않았습니다 — 새 시각으로 다시 승인받으세요'
          else '게시 직전 재확인에서 막혔습니다: ' || v_block end where id = r.id returning * into r;
      perform drinks_pub_log(r, 'claim_paused', 'scheduled', v_block, '{}', 'worker');
      v_paused := v_paused + 1;
      continue;
    end if;
    select * into a from drink_social_accounts where id = r.account_id;
    update drink_publication_requests set status = 'publishing', lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => (drinks_publish_limits() ->> 'lease_sec')::int),
      attempt_count = attempt_count + 1, error_code = null, error_message = null
      where id = r.id returning * into r;
    insert into drink_publication_attempts (request_id, attempt_no, target_external_account_id, provider, lease_token)
      values (r.id, r.attempt_count, r.target_external_account_id,
        case a.connection when 'fake' then 'fake' else 'instagram_graph' end, r.lease_token)
      returning * into att;
    perform drinks_pub_log(r, 'claimed', 'scheduled', null, jsonb_build_object('attempt_no', att.attempt_no), 'worker');
    select * into pl from drink_plan_revisions where id = r.plan_revision_id;
    select * into rv from drink_topic_reviews where id = pl.topic_review_id;
    return jsonb_build_object('reaped', v_reaped, 'paused', v_paused, 'request', jsonb_build_object(
      'request_id', r.id, 'lease_token', r.lease_token, 'attempt_id', att.id, 'attempt_no', att.attempt_no,
      'post_type', r.post_type, 'caption', r.caption, 'publish_at', r.publish_at,
      'audio', r.audio, 'audio_required', drinks_pub_audio_required(r.manifest_id, r.post_type),
      'account', jsonb_build_object('account_id', a.id, 'connection', a.connection, 'external_account_id', a.external_account_id,
        'credential_ref', a.credential_ref, 'capabilities', a.capabilities),
      'files', coalesce((select jsonb_agg(jsonb_build_object('role', ma.role, 'position', ma.position, 'asset_id', x.id,
          'storage_key', x.storage_key, 'sha256', x.sha256, 'mime', x.mime, 'width', x.width, 'height', x.height)
          order by ma.role, ma.position)
        from drink_manifest_assets ma join drink_media_assets x on x.id = ma.asset_id where ma.manifest_id = r.manifest_id), '[]'),
      'claims', rv.evidence_pack -> 'claims',
      'sources', coalesce((select jsonb_agg(jsonb_build_object('title', s.title, 'publisher', s.publisher, 'url', s.canonical_url))
        from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
          from jsonb_array_elements(rv.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]')));
  end loop;
end $$;

create or replace function drinks_publication_step(p jsonb) returns jsonb language plpgsql as $$
declare r drink_publication_requests; v_stage text := drinks_text(p, 'stage'); v_block text;
begin
  r := drinks_lock_pub_lease(p);
  if v_stage not in ('audio_verified','containers_created','containers_ready','before_publish','publish_called') then
    perform drinks_fail('invalid_input', '알 수 없는 발행 단계입니다');
  end if;
  update drink_publication_requests set lease_expires_at = now() + make_interval(secs => (drinks_publish_limits() ->> 'lease_sec')::int)
    where id = r.id returning * into r;
  -- 0065: 게시 직전 음원 재조회가 통과한 시각. 승인 지문 밖의 칸이다.
  if v_stage = 'audio_verified' then
    update drink_publication_requests set audio_verified_at = now() where id = r.id;
    return jsonb_build_object('proceed', true);
  end if;
  if v_stage <> 'before_publish' then
    update drink_publication_attempts set stage = v_stage,
      provider_container_ids = case when jsonb_typeof(p -> 'container_ids') = 'array' then p -> 'container_ids'
        else provider_container_ids end,
      response_code = coalesce(drinks_text(p, 'response_code'), response_code)
      where request_id = r.id and lease_token = r.lease_token;
    return jsonb_build_object('proceed', true);
  end if;
  v_block := drinks_pub_block(r.id);
  if v_block is null and r.cancel_requested then v_block := 'cancel_requested'; end if;
  return jsonb_build_object('proceed', v_block is null, 'block', v_block);
end $$;

create or replace function drinks_publish_board(p jsonb) returns jsonb language plpgsql as $$
declare v_lim int := 300;
begin
  perform drinks_reap_publications();   -- 끊긴 '게시 중'을 화면을 열 때도 unknown 으로 정리한다(버튼이 옛 상태를 보지 않게)
  return jsonb_build_object(
    'limits', drinks_publish_limits(),
    'accounts', coalesce((select jsonb_agg(jsonb_build_object('id', a.id, 'platform', a.platform, 'external_account_id',
        a.external_account_id, 'display_name', a.display_name, 'account_type', a.account_type, 'connection', a.connection,
        'capabilities', a.capabilities, 'status', a.status, 'status_reason', a.status_reason, 'publish_enabled', a.publish_enabled,
        'credential_ref', a.credential_ref, 'verified_at', a.verified_at, 'verified_username', a.verified_username,
        'version', a.version) order by a.created_at) from drink_social_accounts a), '[]'),
    'requests', coalesce((select jsonb_agg(x order by x ->> 'updated_at' desc) from (
        select jsonb_build_object('id', r.id, 'topic_id', r.topic_id, 'topic_title', t.title, 'categories', to_jsonb(t.categories),
          'plan_revision_id', r.plan_revision_id, 'post_type', r.post_type, 'account_id', r.account_id,
          'target_external_account_id', r.target_external_account_id, 'caption', r.caption, 'publish_at', r.publish_at,
          'display_timezone', r.display_timezone, 'status', r.status, 'approval_digest', r.approval_digest,
          'current_digest', drinks_pub_digest(r), 'block', case when r.status in ('approved','scheduled','paused','awaiting_approval')
            then drinks_pub_block(r.id) end, 'approved_at', r.approved_at, 'pause_code', r.pause_code, 'pause_reason', r.pause_reason,
          'cancel_requested', r.cancel_requested, 'external_post_id', r.external_post_id, 'external_url', r.external_url,
          'reconcile_state', r.reconcile_state, 'attempt_count', r.attempt_count, 'error_code', r.error_code,
          'error_message', r.error_message, 'published_at', r.published_at, 'version', r.version, 'updated_at', r.updated_at,
          'audio', r.audio, 'audio_verified_at', r.audio_verified_at, 'audio_required', drinks_pub_audio_required(r.manifest_id, r.post_type),
          'files', (select jsonb_agg(jsonb_build_object('role', ma.role, 'position', ma.position, 'storage_key', a.storage_key,
              'width', a.width, 'height', a.height, 'state', a.state) order by ma.role, ma.position)
            from drink_manifest_assets ma join drink_media_assets a on a.id = ma.asset_id where ma.manifest_id = r.manifest_id)) x
        from drink_publication_requests r join drink_topics t on t.id = r.topic_id
        order by r.updated_at desc limit v_lim) q), '[]'),
    'requests_truncated', (select count(*) > v_lim from drink_publication_requests),
    -- 발행안을 만들 수 있는 것: 지금도 쓸 수 있는 검수 승인 묶음 중 살아 있는 요청이 없는 것
    'ready_outputs', coalesce((select jsonb_agg(jsonb_build_object('output_review_id', v.review_id, 'manifest_id', v.manifest_id,
        'plan_revision_id', v.plan_revision_id, 'format', m.format, 'topic_title', t.title, 'reviewed_at', o.reviewed_at,
        'pages', (select count(*) from drink_manifest_assets ma where ma.manifest_id = v.manifest_id and ma.role = 'page'),
        -- 0065: 이 묶음으로 아직 만들 수 있는 게시 형식. 카드 묶음에 영상이 들었으면 둘 다다.
        'post_types', k.post_types)
        order by o.reviewed_at desc)
      from drink_output_validity v join drink_output_reviews o on o.id = v.review_id
      join drink_asset_manifests m on m.id = v.manifest_id join drink_plan_revisions pl on pl.id = v.plan_revision_id
      join drink_topics t on t.id = pl.topic_id
      cross join lateral (select coalesce(jsonb_agg(ty), '[]'::jsonb) as post_types from unnest(case m.format when 'video' then array['reel']
            else case when exists (select 1 from drink_manifest_assets ma where ma.manifest_id = v.manifest_id and ma.role = 'final_video')
              then array['carousel','reel'] else array['carousel'] end end) ty
          where not exists (select 1 from drink_publication_requests r where r.output_review_id = v.review_id and r.post_type = ty
            and r.status not in ('canceled','failed'))) k
      where v.currently_usable and jsonb_array_length(k.post_types) > 0), '[]'),
    -- 0065: 고를 수 있는 음원(가장 최근 수집일의 목록, 인스타가 준 순서). 트렌드 수집이 없으면 빈 목록이다.
    'audio_options', coalesce((select jsonb_agg(jsonb_build_object('audio_id', x.audio_id, 'audio_type', x.audio_type, 'title', x.title,
        'display_artist', x.display_artist, 'duration_ms', x.duration_ms, 'preview_url', x.preview_url, 'list_position', x.list_position)
        order by x.list_position nulls last)
      from (select * from drink_ig_audio_latest order by list_position nulls last limit 50) x), '[]'),
    -- 추천 게시 시간대: 지금 전략의 slot 가중치(자동으로 넣지 않는다 — 발행안 작성 때 참고로만)
    'slot_weights', (select weights -> 'slot' from drink_strategy_versions where status = 'active'));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 음원 고르기·바꾸기 (운영자) — 승인 뒤 바꾸면 승인이 풀린다(기획 v2 §7-3 3번). 게시 중·끝난 요청은 못 바꾼다.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_set_publication_audio(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_publication_requests; a drink_social_accounts; v_audio jsonb; v_before text;
begin
  perform drinks_reap_publications();
  r := drinks_lock_publication(p);
  v_before := r.status;
  if r.status not in ('draft','awaiting_approval','approved','scheduled','paused','failed') then
    perform drinks_fail('invalid_state', '게시 중이거나 끝난 발행 요청의 음원은 바꿀 수 없습니다');
  end if;
  select * into a from drink_social_accounts where id = r.account_id;
  v_audio := drinks_pub_audio_clean(p -> 'audio', r.post_type, a, r.manifest_id);
  if r.status = 'draft' then
    update drink_publication_requests set audio = v_audio where id = r.id returning * into r;
  else
    update drink_publication_requests set audio = v_audio, audio_verified_at = null, status = 'awaiting_approval', approved_at = null, approved_by = null,
      pause_code = 'needs_reconfirm', pause_reason = '음원이 바뀌어 다시 승인해야 합니다', error_code = null, error_message = null
      where id = r.id returning * into r;
    update drink_publication_requests set approval_digest = drinks_pub_digest(r) where id = r.id returning * into r;
  end if;
  perform drinks_pub_log(r, 'audio_set', v_before, null, jsonb_build_object('mode', v_audio ->> 'mode', 'audio_id', v_audio ->> 'audio_id',
    'sync_grade', v_audio ->> 'sync_grade', 'needs_reconfirm', v_before <> 'draft'));
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'approval_digest', r.approval_digest, 'audio', r.audio);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: anon·authenticated 에 아무것도 주지 않는다)
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
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;

-- 확인(적용 후):
--   select has_function_privilege('anon', 'public.drinks_set_publication_audio(jsonb)', 'EXECUTE');   → false
--   select drinks_pub_digest(r) = r.approval_digest from drink_publication_requests r where r.audio is null and r.approval_digest is not null;   → 전부 true(옛 승인 지문이 그대로)
