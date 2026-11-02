-- 주류 공장 5단계 — 게시 연결·성과 루프 (2026-11-02). docs/deviation-drinks-stage5-publish-loop.md
-- 기획: docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md §5·§6 5단계, docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md §3-4·§7,
--       docs/계획_주류순환_발행성과전략_2026-10-27.md.
--
-- ★ 파일만 만든다. 운영 DB 적용은 따로 결재받는다. 0055·0058·0065·0066·0067 이 먼저 적용돼 있어야 한다.
--
-- 무엇이 바뀌나 — 왜
--   A. 밈형이 게시 요청 표(0055 drink_publication_requests)에 들어간다. 밈은 제작안·검수 묶음이 없어 그 표에 못 들어갔다(0066 머리말).
--      → 세 칸(plan_revision_id·output_review_id·manifest_id)을 비울 수 있게 하고 meme_draft_id 를 더한다. 둘 중 하나만 채운다(표 제약).
--      → drinks_create_meme_publication: 게시 대기(publish_waiting) 제작안만, 박자 무관(sync_free)만. DB·워커가 각각 다시 잰다.
--      → 게시가 끝나면 제작안이 'published' 가 된다(상태 하나 추가). 박자 맞춤은 여전히 manual_audio 에서 끝난다.
--   B. 설명형은 캡션에 'AI 생성 영상' 한 줄이 없으면 발행안을 만들 수도, 승인 요청할 수도, 게시할 수도 없다(기획 v2 §3-4).
--      산 장면을 쓴 밈도 같다(0066 의 'AI 생성' 규칙을 캡션까지 이어 간다).
--   C. 게시 요청에 content_format(card·explainer·meme)이 붙고, 성과·전략이 그 형식으로 묶인다(전략 차원 'format').
--      0058 의 5-인자 가점 함수를 6-인자로 바꾼다(형식 의도 가점). 옛 가중치에 format 칸이 없으면 가점 0.
--   D. 같은 인스타 계정을 Facebook 로그인 연결로 한 번 더 등록할 수 있다(고유키에 연결 방식을 더한다). 음원 릴스는 Facebook
--      로그인 연결로만 올라가는데(0065) 운영 계정은 Instagram 로그인이라 둘째 행이 필요하다. 토큰은 계정별 비밀 이름이다.
--
-- 안전 장치 — 약해지는 것이 없다
--   · 밈 게시 요청도 승인 지문(제작안 승인 지문 포함)·계정 발행 스위치·예약 시각·2시간 지연·취소 재확인을 그대로 탄다.
--   · 박자 맞춤 밈은 세 겹으로 막힌다: 표 제약(0066) + drinks_pub_block('meme_not_publishable') + 워커 assert_auto_publishable.
--   · 옛 행의 승인 지문은 그대로다 — meme_draft_id 가 없으면 지문 계산이 0065 와 글자 하나까지 같다.
--   · 공개 역할(anon·authenticated)에 아무것도 주지 않는다. 새 함수는 service_role 만 부른다.
--
-- 되돌리기:
--   1. 0065 의 drinks_pub_digest·drinks_pub_block·drink_publications_guard·drinks_create_publication·drinks_claim_publication·drinks_publish_board,
--      0055 의 drinks_pub_log·drinks_update_publication·drinks_finish_publication·drinks_reconcile_publication·drinks_metrics_due·drinks_analytics_board,
--      0058 의 drinks_strategy_inputs·drinks_save_strategy_proposal·drinks_strategy_rank 를 다시 실행한다(그다음 0056 의 반복문도 한 번 더).
--      drop function drinks_strategy_lift(jsonb, text[], text, text[], text, text); 후 0058 의 5-인자 drinks_strategy_lift 를 다시 만든다.
--   2. drop function drinks_create_meme_publication(jsonb); drop function drinks_pub_needs_audio(drink_publication_requests);
--      drop function drinks_pub_ai_label_missing(drink_publication_requests); drop function drinks_ai_label_text(); drop function drinks_pub_after_published(drink_publication_requests);
--   3. 밈 게시 요청 행이 없을 때만: alter table drink_publication_requests drop column meme_draft_id, drop column content_format;
--      세 칸을 not null 로 되돌린다. drink_meme_drafts 의 상태 제약에서 'published' 를 뺀다(그 상태의 행이 없을 때만).
--   4. drop index drink_social_accounts_ext_conn_uq; create unique index drink_social_accounts_ext_uq on drink_social_accounts (platform, external_account_id);
--      (Facebook 로그인 둘째 행이 있으면 먼저 disabled 로 두고 지운다 — 계정 행은 지울 수 없다).

-- ─────────────────────────────────────────────────────────────
-- 상수
-- ─────────────────────────────────────────────────────────────

-- engine/config.py DRINKS_AI_LABEL_TEXT 와 같아야 한다(tests/test_drinks_stage5_publish_loop.py 가 대조).
create or replace function drinks_ai_label_text() returns text language sql immutable set search_path = public, pg_temp as $$
  select 'AI 생성 영상'::text
$$;

-- ─────────────────────────────────────────────────────────────
-- 표·칸
-- ─────────────────────────────────────────────────────────────

-- A. 밈은 제작안·검수 묶음이 없다. 세 칸을 비울 수 있게 하고 meme_draft_id 로 출처를 잇는다.
alter table drink_publication_requests alter column topic_id drop not null;
alter table drink_publication_requests alter column plan_revision_id drop not null;
alter table drink_publication_requests alter column output_review_id drop not null;
alter table drink_publication_requests alter column manifest_id drop not null;
alter table drink_publication_requests alter column manifest_hash drop not null;
alter table drink_publication_requests add column if not exists content_format text not null default 'card';
alter table drink_publication_requests add column if not exists meme_draft_id uuid references drink_meme_drafts(id);
alter table drink_publication_requests drop constraint if exists drink_pub_format_ck;
alter table drink_publication_requests add constraint drink_pub_format_ck check (content_format in ('card','explainer','meme'));
alter table drink_publication_requests drop constraint if exists drink_pub_origin_ck;
alter table drink_publication_requests add constraint drink_pub_origin_ck check ((meme_draft_id is not null) = (content_format = 'meme'));
-- 출처는 둘 중 하나다: 제작안·검수·묶음 셋 다 있거나(카드·설명형), 밈 제작안 하나만 있거나.
alter table drink_publication_requests drop constraint if exists drink_pub_source_ck;
alter table drink_publication_requests add constraint drink_pub_source_ck check (
  case when meme_draft_id is null
    then plan_revision_id is not null and output_review_id is not null and manifest_id is not null and manifest_hash is not null
    else plan_revision_id is null and output_review_id is null and manifest_id is null and manifest_hash is null and cover_asset_id is null end);
alter table drink_publication_requests drop constraint if exists drink_pub_meme_reel_ck;
alter table drink_publication_requests add constraint drink_pub_meme_reel_ck check (meme_draft_id is null or post_type = 'reel');
-- 밈 제작안 하나에 살아 있는(또는 게시된) 요청은 계정마다 하나.
create unique index if not exists drink_pub_one_live_meme_uq on drink_publication_requests (meme_draft_id, account_id)
  where meme_draft_id is not null and status not in ('canceled','failed');
create index if not exists drink_pub_format_idx on drink_publication_requests (content_format, status);

-- 기존 행의 형식: 설명형으로 고른 소재의 영상 제작안이면 explainer, 나머지는 card. 끝난 요청도 바꿔야 하므로 가드를 잠깐 내린다(내용·상태는 그대로다).
alter table drink_publication_requests disable trigger drink_publications_guard;
update drink_publication_requests set content_format = 'explainer'
  where meme_draft_id is null and content_format = 'card' and drinks_plan_is_explainer(plan_revision_id);
alter table drink_publication_requests enable trigger drink_publications_guard;

-- 밈 제작안: 게시가 끝나면 'published'. 게시 대기(sync_free)에서만 들어간다.
alter table drink_meme_drafts drop constraint if exists drink_meme_drafts_status_check;
alter table drink_meme_drafts add constraint drink_meme_drafts_status_check check (status in ('text_requested','text_running','draft','approved','rendering',
  'publish_waiting','manual_audio','posted_manual','published','stopped','failed','rejected'));
alter table drink_meme_drafts drop constraint if exists drink_meme_sync_gate_ck;
alter table drink_meme_drafts add constraint drink_meme_sync_gate_ck check (status not in ('publish_waiting','published') or sync_grade = 'sync_free');
alter table drink_meme_drafts drop constraint if exists drink_meme_output_ck;
alter table drink_meme_drafts add constraint drink_meme_output_ck check (status not in ('publish_waiting','manual_audio','posted_manual','published') or jsonb_array_length(files) > 0);
alter table drink_meme_drafts drop constraint if exists drink_meme_approved_ck;
alter table drink_meme_drafts add constraint drink_meme_approved_ck check (status not in ('approved','rendering','publish_waiting','manual_audio','posted_manual','published')
  or (approved_at is not null and approved_digest is not null));

create or replace function drink_meme_drafts_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '제작안 기록은 지우지 않습니다 — 버리기로 닫으세요'); end if;
  if new.status in ('publish_waiting','manual_audio') and old.status <> new.status and old.status <> 'rendering' then
    perform drinks_fail('invalid_transition', '제작이 끝난 것만 게시 대기·앱 부착으로 갑니다');
  end if;
  -- 0068: 게시됨은 게시 대기에서만. 게시 워커가 게시 요청을 닫을 때만 들어온다(drinks_pub_after_published).
  if new.status = 'published' and old.status <> 'publish_waiting' then
    perform drinks_fail('invalid_transition', '게시 대기 중인 제작안만 게시됨으로 갑니다');
  end if;
  if old.status = 'published' and new.status <> 'published' then
    perform drinks_fail('immutable', '게시된 제작안은 되돌리지 않습니다');
  end if;
  if new.spec is distinct from old.spec and old.status not in ('draft','text_requested','text_running') then
    perform drinks_fail('immutable', '승인·제작에 들어간 제작안은 고칠 수 없습니다 — 다시 초안으로 되돌리세요');
  end if;
  new.updated_at := now();
  new.version := old.version + 1;
  return new;
end $$;

-- D. 같은 인스타 계정을 다른 연결 방식으로 한 번 더 등록할 수 있다(Instagram 로그인 행 + Facebook 로그인 행).
drop index if exists drink_social_accounts_ext_uq;
create unique index if not exists drink_social_accounts_ext_conn_uq on drink_social_accounts (platform, external_account_id, connection);

-- ─────────────────────────────────────────────────────────────
-- 규칙 함수
-- ─────────────────────────────────────────────────────────────

-- 음원이 필수인 게시인가: 카드 묶음 릴스(0065) 또는 음원을 게시 때 붙이기로 한 밈(spec.audio.mode = ig_audio).
create or replace function drinks_pub_needs_audio(r drink_publication_requests) returns boolean language sql stable set search_path = public, pg_temp as $$
  select case when r.meme_draft_id is null then drinks_pub_audio_required(r.manifest_id, r.post_type)
    else coalesce((select d.spec -> 'audio' ->> 'mode' = 'ig_audio' from drink_meme_drafts d where d.id = r.meme_draft_id), false) end
$$;

-- 'AI 생성 영상' 한 줄이 빠졌나: 설명형은 항상, 밈은 산 장면을 썼을 때(기획 v2 §3-4, 0066 meme_ai_label_missing).
create or replace function drinks_pub_ai_label_missing(r drink_publication_requests) returns boolean language sql stable set search_path = public, pg_temp as $$
  select case
    when r.content_format = 'explainer' then position(drinks_ai_label_text() in coalesce(r.caption, '')) = 0
    when r.content_format = 'meme' then coalesce((select d.spec -> 'scene' ->> 'source' = 'bought_reaction' from drink_meme_drafts d where d.id = r.meme_draft_id), false)
      and position('AI 생성' in coalesce(r.caption, '')) = 0
    else false end
$$;

-- 승인 지문: 0065 계산 + 밈이면 제작안 id 와 제작안 승인 지문. meme_draft_id 가 없으면 0065 와 글자 하나까지 같다.
create or replace function drinks_pub_digest(r drink_publication_requests) returns text language sql stable set search_path = public, pg_temp as $$
  select encode(sha256(convert_to(concat_ws('|', 'drinks-pub-v1', r.manifest_id::text, r.manifest_hash, r.account_id::text,
    r.target_external_account_id, r.post_type, r.caption, coalesce(r.cover_asset_id::text, ''),
    coalesce(to_char(r.publish_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''))
    || case when r.audio is null then '' else '|audio:' || (r.audio - 'selected_by' - 'selected_at')::text end
    || case when r.meme_draft_id is null then '' else '|meme:' || r.meme_draft_id::text || ':'
         || coalesce((select d.approved_digest from drink_meme_drafts d where d.id = r.meme_draft_id), '') end, 'UTF8')), 'hex')
$$;

create or replace function drinks_pub_block(p_id uuid) returns text language sql stable set search_path = public, pg_temp as $$
  select case
    when r.id is null then 'not_found'
    when r.approval_digest is distinct from drinks_pub_digest(r) then 'digest_changed'
    when r.meme_draft_id is null and not coalesce((select v.currently_usable from drink_output_validity v where v.review_id = r.output_review_id), false)
      then 'output_not_usable'
    -- 0068 밈: 게시 대기 상태 그대로이고, 박자 무관이며, 앱에서 붙이는 음원이 아니어야 한다. 되돌리거나 버렸으면 게시하지 않는다.
    when r.meme_draft_id is not null and not exists (select 1 from drink_meme_drafts d where d.id = r.meme_draft_id and d.status = 'publish_waiting'
        and d.sync_grade = 'sync_free' and coalesce(d.spec -> 'audio' ->> 'mode', '') <> 'app_manual') then 'meme_not_publishable'
    when drinks_pub_ai_label_missing(r) then 'ai_label_missing'
    when a.status = 'reauth_required' then 'account_reauth'
    when a.status <> 'active' then 'account_not_active'
    when not a.publish_enabled then 'publish_disabled'
    when a.external_account_id <> r.target_external_account_id then 'account_mismatch'
    -- 0065 음원: 필수인데 없음 / Facebook 로그인이 아닌 연결 / 박자를 맞춰야 해서 자동 게시 대상이 아님(시작 위치를 못 정한다, §7-2)
    when drinks_pub_needs_audio(r) and coalesce(r.audio ->> 'mode', 'none') = 'none' then 'audio_missing'
    when r.audio ->> 'mode' = 'ig_audio' and a.connection not in ('facebook_login','fake') then 'audio_connection_unsupported'
    when r.audio ->> 'mode' = 'ig_audio' and r.audio ->> 'sync_grade' is distinct from 'sync_free' then 'audio_sync_required'
    -- 0068 밈: 제작안이 정한 음원과 다른 음원을 붙이지 않는다
    when r.meme_draft_id is not null and r.audio ->> 'mode' = 'ig_audio'
      and r.audio ->> 'audio_id' is distinct from (select d.spec -> 'audio' ->> 'audio_id' from drink_meme_drafts d where d.id = r.meme_draft_id) then 'audio_mismatch'
    else null end
  from (select 1) x left join drink_publication_requests r on r.id = p_id
    left join drink_social_accounts a on a.id = r.account_id
$$;

-- 기록: 밈은 제작안 행(deliverable)에, 나머지는 플랜에 남는다. topic_id 는 밈 카드에서 온 것이면 비어 있다.
create or replace function drinks_pub_log(r drink_publication_requests, p_action text, p_before text, p_reason text,
  p_detail jsonb default '{}', p_actor text default 'operator') returns void language sql set search_path = public, pg_temp as $$
  insert into drink_workflow_events (topic_id, entity_type, entity_id, action, actor, before_status, after_status, version_ref,
    reason, detail)
  values (r.topic_id, case when r.meme_draft_id is null then 'plan' else 'deliverable' end, coalesce(r.plan_revision_id, r.meme_draft_id),
    'publication_' || p_action, p_actor, p_before, r.status, r.id::text, p_reason,
    coalesce(p_detail, '{}') || jsonb_build_object('post_type', r.post_type, 'account_id', r.account_id, 'content_format', r.content_format));
$$;

-- 게시가 확정된 뒤 출처 쪽에 남길 것: 밈 제작안을 'published' 로. 인스타 주소 모양이면 주소도 적는다(0066 의 주소 규칙 그대로).
create or replace function drinks_pub_after_published(r drink_publication_requests) returns void language plpgsql set search_path = public, pg_temp as $$
begin
  if r.meme_draft_id is not null then
    update drink_meme_drafts set status = 'published',
      external_url = case when r.external_url ~ '^https://(www\.)?instagram\.com/' then r.external_url else external_url end
      where id = r.meme_draft_id and status = 'publish_waiting';
    perform drinks_meme_log(r.meme_draft_id, 'published', 'publish_waiting', 'published', r.external_post_id, 'worker');
  end if;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 가드 (0065 정의 + 음원 필수 판정·AI 표기)
-- ─────────────────────────────────────────────────────────────

create or replace function drink_publications_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '발행 요청은 삭제할 수 없습니다(취소로 표시)'); end if;
  if old.status <> 'draft' and (new.manifest_id, new.manifest_hash, new.account_id, new.target_external_account_id,
      new.post_type, new.caption, new.cover_asset_id, new.publish_at, new.plan_revision_id, new.output_review_id, new.meme_draft_id, new.content_format)
      is distinct from (old.manifest_id, old.manifest_hash, old.account_id, old.target_external_account_id,
      old.post_type, old.caption, old.cover_asset_id, old.publish_at, old.plan_revision_id, old.output_review_id, old.meme_draft_id, old.content_format) then
    perform drinks_fail('immutable', '작성 중이 아닌 발행 요청의 내용은 바꿀 수 없습니다 — 취소하고 새로 만드세요');
  end if;
  if new.meme_draft_id is distinct from old.meme_draft_id or new.content_format <> old.content_format then
    perform drinks_fail('immutable', '발행 요청의 출처·형식은 바꿀 수 없습니다');
  end if;
  -- 0065: 작성 중 요청을 취소하면 표 제약(status='draft' 또는 지문 있음)에 걸려 취소가 안 됐다(0055 결함). 음원이 없어 보류할 때 이 길이 필요하다.
  if new.status = 'canceled' and new.approval_digest is null then new.approval_digest := drinks_pub_digest(new); end if;
  -- 0065: 음원은 작성 중이거나, 승인을 풀면서만 바뀐다(drinks_set_publication_audio).
  if old.status <> 'draft' and new.audio is distinct from old.audio and not (new.status = 'awaiting_approval' and new.approved_at is null) then
    perform drinks_fail('immutable', '승인을 풀지 않고 음원을 바꿀 수 없습니다');
  end if;
  if new.status = 'awaiting_approval' and old.status <> 'awaiting_approval' then
    if drinks_pub_needs_audio(new) and coalesce(new.audio ->> 'mode', 'none') = 'none' then
      perform drinks_fail('audio_required', '이 릴스는 음원이 필수입니다 — 음원을 고른 뒤 승인 요청하세요');
    end if;
    -- 0068: 설명형(산 장면 밈)은 'AI 생성 영상' 한 줄이 없으면 승인 요청 자체가 안 된다
    if drinks_pub_ai_label_missing(new) then
      perform drinks_fail('ai_label_missing', '캡션에 ''' || drinks_ai_label_text() || ''' 한 줄이 있어야 합니다(기획 v2 §3-4)');
    end if;
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

-- ─────────────────────────────────────────────────────────────
-- 운영자 RPC — 발행안 작성 (0065 정의 + content_format + AI 표기)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_create_publication(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare o drink_output_reviews; m drink_asset_manifests; pl drink_plan_revisions; a drink_social_accounts;
  r drink_publication_requests; v_type text; v_cover uuid; v_pages int; v_want text := drinks_text(p, 'post_type'); v_audio jsonb; v_fmt text;
  v_caption text := coalesce(p ->> 'caption', '');
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
  perform drinks_check_caption(v_caption, a);
  -- 0068: 형식. 설명형 영상은 'AI 생성 영상' 한 줄이 필수다 — 작성 때부터 받지 않는다(승인·게시 직전에도 다시 잰다).
  v_fmt := case when drinks_plan_is_explainer(pl.id) then 'explainer' else 'card' end;
  if v_fmt = 'explainer' and position(drinks_ai_label_text() in v_caption) = 0 then
    perform drinks_fail('ai_label_missing', '설명형 릴스 캡션에는 ''' || drinks_ai_label_text() || ''' 한 줄이 있어야 합니다(기획 v2 §3-4)');
  end if;
  -- 음원은 여기서 고르지 않아도 된다(작성 중). 승인 요청 때 필수 여부를 잰다.
  if p -> 'audio' is not null and jsonb_typeof(p -> 'audio') <> 'null' then
    v_audio := drinks_pub_audio_clean(p -> 'audio', v_type, a, m.id);
  end if;
  begin
    insert into drink_publication_requests (topic_id, plan_revision_id, output_review_id, manifest_id, manifest_hash, post_type,
      account_id, target_external_account_id, caption, cover_asset_id, publish_at, audio, content_format)
    values (pl.topic_id, pl.id, o.id, m.id, m.manifest_hash, v_type, a.id, a.external_account_id, v_caption,
      v_cover, (drinks_text(p, 'publish_at'))::timestamptz, v_audio, v_fmt)
    returning * into r;
  exception when unique_violation then
    perform drinks_fail('duplicate_publication', '이 제작안·계정·형식에는 이미 살아 있는(또는 게시된) 발행 요청이 있습니다');
  end;
  perform drinks_pub_log(r, 'created', null, null);
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'post_type', r.post_type, 'audio', r.audio,
    'content_format', r.content_format);
end $$;

-- 밈 발행안: 게시 대기(publish_waiting) 제작안 하나 + 계정 하나. 캡션을 안 주면 제작안의 캡션을 쓴다(사람이 승인한 글이다).
-- 박자 맞춤(manual_audio)은 여기 들어오지 못한다 — 0066 표 제약이 publish_waiting 을 막고, 여기서도 다시 잰다.
create or replace function drinks_create_meme_publication(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; a drink_social_accounts; r drink_publication_requests; v_caption text; v_audio jsonb; v_mode text;
begin
  select * into d from drink_meme_drafts where id = drinks_uuid(p, 'draft_id');
  if not found then perform drinks_fail('not_found', '밈 제작안을 찾지 못했습니다'); end if;
  if d.status <> 'publish_waiting' then
    perform drinks_fail('invalid_state', case d.status when 'manual_audio' then '박자에 맞춰야 하는 밈은 자동 게시하지 않습니다 — 앱에서 음원을 붙여 올리세요'
      when 'published' then '이미 게시된 제작안입니다' else '게시 대기 중인 제작안만 발행안을 만듭니다(지금 ' || d.status || ')' end);
  end if;
  v_mode := coalesce(d.spec -> 'audio' ->> 'mode', '');
  if d.sync_grade is distinct from 'sync_free' or v_mode = 'app_manual' then
    perform drinks_fail('meme_sync_blocked', '박자에 맞춰야 하는 밈은 자동 게시하지 않습니다');
  end if;
  if not exists (select 1 from jsonb_array_elements(d.files) f where f ->> 'role' = 'final_video') then
    perform drinks_fail('invalid_state', '완성 영상 파일이 없습니다');
  end if;
  select * into a from drink_social_accounts where id = drinks_uuid(p, 'account_id');
  if not found then perform drinks_fail('not_found', '계정을 고르세요(기본 계정은 없습니다)'); end if;
  if a.status = 'disabled' then perform drinks_fail('invalid_state', '사용 중지된 계정입니다'); end if;
  if not coalesce(a.capabilities -> 'post_types' ? 'reel', false) then
    perform drinks_fail('capability_missing', '이 계정은 reel 게시가 확인되지 않았습니다(계정 기능 목록)');
  end if;
  v_caption := coalesce(nullif(p ->> 'caption', ''), d.spec ->> 'caption', '');
  perform drinks_check_caption(v_caption, a);
  if d.spec -> 'scene' ->> 'source' = 'bought_reaction' and position('AI 생성' in v_caption) = 0 then
    perform drinks_fail('ai_label_missing', '산 장면을 쓴 밈의 캡션에는 ''' || drinks_ai_label_text() || ''' 한 줄이 있어야 합니다');
  end if;
  if p -> 'audio' is not null and jsonb_typeof(p -> 'audio') <> 'null' then
    v_audio := drinks_pub_audio_clean(p -> 'audio', 'reel', a, null);
  end if;
  -- 제작안이 "게시 때 인스타 음원을 붙인다"고 정했으면 그 음원이어야 한다. 아니면 영상에 든 소리(분위기 음원·무음) 그대로다.
  if v_mode = 'ig_audio' and v_audio is not null and (v_audio ->> 'mode' <> 'ig_audio' or v_audio ->> 'audio_id' is distinct from d.spec -> 'audio' ->> 'audio_id') then
    perform drinks_fail('audio_mismatch', '제작안이 정한 음원(' || coalesce(d.spec -> 'audio' ->> 'audio_id', '?') || ')과 다른 음원입니다');
  end if;
  if v_mode <> 'ig_audio' and v_audio is not null and v_audio ->> 'mode' <> 'none' then
    perform drinks_fail('invalid_input', '이 밈은 영상에 소리가 들어 있어 게시 때 음원을 따로 붙이지 않습니다');
  end if;
  begin
    insert into drink_publication_requests (topic_id, meme_draft_id, content_format, post_type, account_id, target_external_account_id, caption, publish_at, audio)
    values (d.topic_id, d.id, 'meme', 'reel', a.id, a.external_account_id, v_caption, (drinks_text(p, 'publish_at'))::timestamptz, v_audio)
    returning * into r;
  exception when unique_violation then
    perform drinks_fail('duplicate_publication', '이 밈 제작안·계정에는 이미 살아 있는(또는 게시된) 발행 요청이 있습니다');
  end;
  perform drinks_pub_log(r, 'created', null, null, jsonb_build_object('meme_draft_id', d.id));
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'post_type', r.post_type, 'audio', r.audio,
    'content_format', r.content_format, 'caption', r.caption);
end $$;

create or replace function drinks_update_publication(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_publication_requests; a drink_social_accounts;
begin
  r := drinks_lock_publication(p);
  if r.status <> 'draft' then perform drinks_fail('invalid_state', '작성 중인 발행안만 고칩니다 — 취소하고 새로 만드세요'); end if;
  select * into a from drink_social_accounts where id = r.account_id;
  if p ? 'caption' then perform drinks_check_caption(coalesce(p ->> 'caption', ''), a); end if;
  update drink_publication_requests set
    caption = case when p ? 'caption' then coalesce(p ->> 'caption', '') else caption end,
    publish_at = case when p ? 'publish_at' then (drinks_text(p, 'publish_at'))::timestamptz else publish_at end
    where id = r.id returning * into r;
  -- 0068: 설명형(산 장면 밈)의 'AI 생성 영상' 한 줄은 고치면서도 빠질 수 없다
  if p ? 'caption' and drinks_pub_ai_label_missing(r) then
    perform drinks_fail('ai_label_missing', '캡션에 ''' || drinks_ai_label_text() || ''' 한 줄이 있어야 합니다(기획 v2 §3-4)');
  end if;
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 RPC — 발행 (0065 정의 + 밈 파일·근거, content_format)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_claim_publication(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_publication_requests; a drink_social_accounts; v_block text; v_reaped int; v_paused int := 0;
  v_grace int := (drinks_publish_limits() ->> 'late_grace_sec')::int; att drink_publication_attempts; rv drink_topic_reviews;
  d drink_meme_drafts; v_review uuid; v_files jsonb;
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
    if r.meme_draft_id is null then
      select topic_review_id into v_review from drink_plan_revisions where id = r.plan_revision_id;
      v_files := coalesce((select jsonb_agg(jsonb_build_object('role', ma.role, 'position', ma.position, 'asset_id', x.id,
          'storage_key', x.storage_key, 'sha256', x.sha256, 'mime', x.mime, 'width', x.width, 'height', x.height)
          order by ma.role, ma.position)
        from drink_manifest_assets ma join drink_media_assets x on x.id = ma.asset_id where ma.manifest_id = r.manifest_id), '[]');
    else
      -- 0068 밈: 파일은 제작안 행에 있다(drinks/memes/…). 근거는 정보 밈일 때만 있다 — 농담의 캡션은 근거 없이 검사된다(숫자·양·권고면 멈춘다).
      select * into d from drink_meme_drafts where id = r.meme_draft_id;
      v_review := d.evidence_review_id;
      v_files := coalesce((select jsonb_agg(jsonb_build_object('role', f ->> 'role', 'position', 1, 'asset_id', null,
          'storage_key', f ->> 'storage_key', 'sha256', f ->> 'sha256', 'mime', f ->> 'mime', 'width', (f ->> 'width')::int, 'height', (f ->> 'height')::int)
          order by f ->> 'role')
        from jsonb_array_elements(d.files) f where f ->> 'role' in ('final_video','cover')), '[]');
    end if;
    select * into rv from drink_topic_reviews where id = v_review;
    return jsonb_build_object('reaped', v_reaped, 'paused', v_paused, 'request', jsonb_build_object(
      'request_id', r.id, 'lease_token', r.lease_token, 'attempt_id', att.id, 'attempt_no', att.attempt_no,
      'post_type', r.post_type, 'caption', r.caption, 'publish_at', r.publish_at,
      'content_format', r.content_format, 'meme_draft_id', r.meme_draft_id, 'meme_spec', case when d.id is null then null else d.spec end,
      'audio', r.audio, 'audio_required', drinks_pub_needs_audio(r),
      'account', jsonb_build_object('account_id', a.id, 'connection', a.connection, 'external_account_id', a.external_account_id,
        'credential_ref', a.credential_ref, 'capabilities', a.capabilities),
      'files', v_files,
      'claims', coalesce(rv.evidence_pack -> 'claims', '[]'::jsonb),
      'sources', case when rv.id is null then '[]'::jsonb else coalesce((select jsonb_agg(jsonb_build_object('title', s.title, 'publisher', s.publisher, 'url', s.canonical_url))
        from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
          from jsonb_array_elements(rv.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]') end));
  end loop;
end $$;

-- 시도 끝(0055 정의 + 밈 제작안 '게시됨'). published 는 외부 게시물 ID 와 그 게시물의 계정 ID 가 대상과 같을 때만.
create or replace function drinks_finish_publication(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_publication_requests; v_out text := drinks_text(p, 'outcome'); v_stage text; v_before text;
begin
  r := drinks_lock_pub_lease(p);
  v_before := r.status;
  select stage into v_stage from drink_publication_attempts where request_id = r.id and lease_token = r.lease_token;
  if v_out = 'published' then
    if drinks_text(p, 'external_post_id') is null then perform drinks_fail('invalid_input', '외부 게시물 ID 가 없습니다'); end if;
    if drinks_text(p, 'owner_account_id') is distinct from r.target_external_account_id then
      update drink_publication_requests set status = 'unknown', lease_token = null, error_code = 'owner_mismatch',
        error_message = '게시물의 계정이 대상과 다르게 보고됐습니다 — 확인이 필요합니다', external_post_id = drinks_text(p, 'external_post_id')
        where id = r.id returning * into r;
      v_out := 'unknown';
    else
      update drink_publication_requests set status = 'published', lease_token = null, external_post_id = drinks_text(p, 'external_post_id'),
        external_url = drinks_text(p, 'external_url'), published_at = now(),
        reconcile_state = case when drinks_text(p, 'external_url') is null then 'url_pending'
          when cancel_requested then 'cancel_not_applied' else 'none' end
        where id = r.id returning * into r;
      perform drinks_pub_after_published(r);
    end if;
  elsif v_out = 'failed' then
    if v_stage = 'publish_called' then
      perform drinks_fail('invalid_input', '게시 호출 뒤의 오류는 실패로 확정할 수 없습니다 — unknown 으로 보내세요');
    end if;
    update drink_publication_requests set status = 'failed', lease_token = null, error_code = drinks_text(p, 'error_code'),
      error_message = left(drinks_text(p, 'error_message'), 2000) where id = r.id returning * into r;
  elsif v_out = 'unknown' then
    update drink_publication_requests set status = 'unknown', lease_token = null, error_code = drinks_text(p, 'error_code'),
      error_message = left(coalesce(drinks_text(p, 'error_message'), '게시 여부를 모릅니다'), 2000) where id = r.id returning * into r;
  elsif v_out in ('paused','canceled') then
    if v_stage = 'publish_called' then
      perform drinks_fail('invalid_input', '게시 호출 뒤에는 멈추거나 취소할 수 없습니다 — unknown 으로 보내세요');
    end if;
    if v_out = 'paused' then
      update drink_publication_requests set status = 'paused', lease_token = null,
        pause_code = coalesce(drinks_text(p, 'error_code'), 'worker_paused'),
        pause_reason = left(coalesce(drinks_text(p, 'error_message'), '워커가 게시 전에 멈췄습니다'), 2000) where id = r.id returning * into r;
    else
      update drink_publication_requests set status = 'canceled', lease_token = null,
        error_message = '게시 직전 취소 확인 — 외부 게시 호출 전에 멈췄습니다' where id = r.id returning * into r;
    end if;
  else
    perform drinks_fail('invalid_input', '알 수 없는 발행 결과입니다');
  end if;
  update drink_publication_attempts set stage = case v_out when 'published' then 'confirmed' else v_out end, finished_at = now(),
    external_post_id = drinks_text(p, 'external_post_id'), response_code = coalesce(drinks_text(p, 'response_code'), response_code),
    error_code = drinks_text(p, 'error_code'), error_message = left(drinks_text(p, 'error_message'), 2000)
    where request_id = r.id and finished_at is null;
  perform drinks_pub_log(r, 'finished', v_before, drinks_text(p, 'error_code'), jsonb_build_object('outcome', v_out), 'worker');
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'external_post_id', r.external_post_id);
end $$;

-- 조회 대조 결과(0055 정의 + 밈 제작안 '게시됨').
create or replace function drinks_reconcile_publication(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_publication_requests;
begin
  r := drinks_lock_publication(p, false);
  if r.status <> 'unknown' then perform drinks_fail('invalid_state', '게시 여부 불명인 요청만 대조합니다'); end if;
  if coalesce((p ->> 'found')::boolean, false) then
    if drinks_text(p, 'owner_account_id') is distinct from r.target_external_account_id or drinks_text(p, 'external_post_id') is null then
      perform drinks_fail('invalid_input', '찾은 게시물의 ID·계정이 확인돼야 정정합니다');
    end if;
    update drink_publication_requests set status = 'published', external_post_id = drinks_text(p, 'external_post_id'),
      external_url = drinks_text(p, 'external_url'), published_at = coalesce((drinks_text(p, 'published_at'))::timestamptz, now()),
      approved_at = coalesce(approved_at, now()),
      reconcile_state = case when cancel_requested then 'cancel_not_applied' else 'reconciled' end, error_code = null,
      error_message = null where id = r.id returning * into r;
    perform drinks_pub_after_published(r);
  elsif coalesce((p ->> 'confirmed_not_published')::boolean, false) then
    update drink_publication_requests set status = case when cancel_requested then 'canceled' else 'failed' end,
      error_code = 'not_published', error_message = '조회 대조: 게시되지 않았음을 확인했습니다' where id = r.id returning * into r;
  else
    return jsonb_build_object('request_id', r.id, 'status', r.status, 'note', '아직 판단할 수 없습니다 — unknown 유지');
  end if;
  perform drinks_pub_log(r, 'reconciled', 'unknown', null, jsonb_build_object('found', p -> 'found'), 'worker');
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'reconcile_state', r.reconcile_state);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 RPC — 성과 (0055 정의 + content_format). 형식별로 모이는 것은 요청 행의 칸이다 — 스냅샷 표는 바뀌지 않는다.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_metrics_due(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(x order by x ->> 'published_at'), '[]') from (
    select jsonb_build_object('request_id', r.id, 'external_post_id', r.external_post_id, 'post_type', r.post_type, 'content_format', r.content_format,
      'published_at', r.published_at, 'bucket', drinks_metric_bucket(extract(epoch from now() - r.published_at)::numeric / 3600),
      'account', jsonb_build_object('account_id', a.id, 'connection', a.connection, 'external_account_id', a.external_account_id,
        'credential_ref', a.credential_ref)) x
    from drink_publication_requests r join drink_social_accounts a on a.id = r.account_id
    where r.status = 'published'
      and r.published_at > now() - make_interval(days => (drinks_publish_limits() ->> 'metric_window_days')::int)
      and drinks_metric_bucket(extract(epoch from now() - r.published_at)::numeric / 3600) <> 'off_window'
      and not exists (select 1 from drink_post_metric_snapshots s where s.request_id = r.id and s.fetch_status <> 'failed'
        and s.age_bucket = drinks_metric_bucket(extract(epoch from now() - r.published_at)::numeric / 3600))
    limit coalesce(drinks_int(p, 'limit', false), 50)) q
$$;

-- ─────────────────────────────────────────────────────────────
-- 전략 (0058 정의 + 차원 'format'). 밈 카드에서 온 게시물은 소재가 없어 주종·갈래·질문 유형이 비어 있다 — 그 묶음에서만 빠진다.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_strategy_inputs(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'active', (select jsonb_build_object('id', v.id, 'label', v.label, 'weights', v.weights) from drink_strategy_versions v
      where v.status = 'active'),
    'limits', drinks_publish_limits(),
    'posts', coalesce((select jsonb_agg(jsonb_build_object('request_id', r.id, 'categories', coalesce(to_jsonb(t.categories), '[]'::jsonb),
        'lane', t.lane, 'question_kind', t.question_kind, 'post_type', r.post_type, 'format', r.content_format, 'slot', drinks_time_slot(r.published_at),
        'values', s.metric_values, 'unavailable', s.unavailable) order by r.published_at)
      from drink_publication_requests r left join drink_topics t on t.id = r.topic_id
      join drink_post_metric_snapshots s on s.request_id = r.id and s.fetch_status <> 'failed'
        and s.age_bucket = drinks_publish_limits() ->> 'strategy_bucket'
      where r.status = 'published'), '[]'))
$$;

create or replace function drinks_save_strategy_proposal(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v drink_strategy_versions; x drink_strategy_proposals; w jsonb := p -> 'weights'; d text; k text;
  v_cap numeric := (drinks_publish_limits() ->> 'strategy_max_lift')::numeric;
begin
  select * into v from drink_strategy_versions where status = 'active';
  if v.id is distinct from drinks_uuid(p, 'base_version_id') then
    perform drinks_fail('stale_strategy', '계산 중에 전략이 바뀌었습니다 — 다시 계산하세요');
  end if;
  if jsonb_typeof(w) <> 'object' then perform drinks_fail('invalid_input', '가중치 형식이 잘못됐습니다'); end if;
  for d in select jsonb_object_keys(w) loop
    if d not in ('category','post_type','lane','slot','question_kind','format') or jsonb_typeof(w -> d) <> 'object' then
      perform drinks_fail('invalid_input', '알 수 없는 가중치 묶음: ' || d);
    end if;
    for k in select jsonb_object_keys(w -> d) loop
      if jsonb_typeof(w -> d -> k) <> 'number' or abs((w -> d ->> k)::numeric) > v_cap then
        perform drinks_fail('invalid_input', '가중치는 ±' || v_cap || ' 안의 숫자여야 합니다: ' || d || '.' || k);
      end if;
      if d = 'format' and k not in ('card','explainer','meme') then
        perform drinks_fail('invalid_input', '알 수 없는 형식 가중치: ' || k);
      end if;
    end loop;
  end loop;
  update drink_strategy_proposals set status = 'superseded' where status = 'proposed';
  insert into drink_strategy_proposals (base_version_id, weights, basis, sample_total, sufficient, summary_ko)
    values (v.id, w, coalesce(p -> 'basis', '{}'), coalesce(drinks_int(p, 'sample_total', false), 0),
      coalesce((p ->> 'sufficient')::boolean, false), left(drinks_text(p, 'summary_ko'), 4000))
    returning * into x;
  return jsonb_build_object('proposal_id', x.id, 'status', x.status, 'sufficient', x.sufficient);
end $$;

-- 전략 가점: 주종(여럿이면 평균)·갈래·질문 유형·더 잘 맞는 형식·고른 콘텐츠 형식의 가중치를 더해 임시 점수에 곱한다(0.5~1.5배).
-- 인자가 하나 늘었으므로(콘텐츠 형식) 옛 5-인자 함수는 지운다 — 둘이 남으면 호출이 모호해진다(0058 과 같은 이유).
drop function if exists drinks_strategy_lift(jsonb, text[], text, text[], text);
create or replace function drinks_strategy_lift(w jsonb, p_cats text[], p_lane text, p_post_types text[],
  p_kind text default 'general', p_format text default null) returns numeric
language sql immutable set search_path = public, pg_temp as $$
  select greatest(-0.5, least(0.5,
      coalesce((select avg(coalesce((w -> 'category' ->> c)::numeric, 0)) from unnest(p_cats) c), 0)
    + coalesce((w -> 'lane' ->> p_lane)::numeric, 0)
    + coalesce((w -> 'question_kind' ->> p_kind)::numeric, 0)
    + coalesce((w -> 'format' ->> p_format)::numeric, 0)
    + coalesce((select max(coalesce((w -> 'post_type' ->> t)::numeric, 0)) from unnest(p_post_types) t), 0)))
$$;

create or replace function drinks_strategy_rank(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  with v as (select * from drink_strategy_versions where status = 'active')
  select jsonb_build_object('strategy', (select label from v), 'weights', (select weights from v), 'topics', coalesce(jsonb_agg(x
    order by (x ->> 'adjusted_score')::numeric desc nulls last, x ->> 'title'), '[]'))
  from (select jsonb_build_object('topic_id', t.id, 'title', t.title, 'status', t.status, 'categories', to_jsonb(t.categories),
      'lane', t.lane, 'question_kind', t.question_kind, 'provisional_score', t.provisional_score, 'format_intent', pk.format_intent,
      'lift', drinks_strategy_lift((select weights from v), t.categories, t.lane, array_remove(array[
        case when coalesce((t.provisional_scores ->> 'fit_carousel')::int, 0) >= 2 then 'carousel' end,
        case when coalesce((t.provisional_scores ->> 'fit_video')::int, 0) >= 2 then 'reel' end], null), t.question_kind, pk.format_intent),
      'adjusted_score', round(t.provisional_score * (1 + drinks_strategy_lift((select weights from v), t.categories, t.lane,
        array_remove(array[
          case when coalesce((t.provisional_scores ->> 'fit_carousel')::int, 0) >= 2 then 'carousel' end,
          case when coalesce((t.provisional_scores ->> 'fit_video')::int, 0) >= 2 then 'reel' end], null), t.question_kind, pk.format_intent)), 2)) x
    from drink_topics t left join drink_topic_picks pk on pk.topic_id = t.id
    where t.status in ('triaged','researching','ready')
    limit coalesce(drinks_int(p, 'limit', false), 200)) q
$$;

-- ─────────────────────────────────────────────────────────────
-- 화면 조회 (0065·0055 정의 + 밈·형식). 소재가 없는 밈 요청은 카드 이름을 제목으로 쓴다.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_publish_board(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
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
        select jsonb_build_object('id', r.id, 'topic_id', r.topic_id, 'topic_title', coalesce(t.title, c.name, '(밈 제작안)'),
          'categories', coalesce(to_jsonb(t.categories), '[]'::jsonb),
          'plan_revision_id', r.plan_revision_id, 'post_type', r.post_type, 'account_id', r.account_id,
          'content_format', r.content_format, 'meme_draft_id', r.meme_draft_id,
          'target_external_account_id', r.target_external_account_id, 'caption', r.caption, 'publish_at', r.publish_at,
          'display_timezone', r.display_timezone, 'status', r.status, 'approval_digest', r.approval_digest,
          'current_digest', drinks_pub_digest(r), 'block', case when r.status in ('approved','scheduled','paused','awaiting_approval')
            then drinks_pub_block(r.id) end, 'approved_at', r.approved_at, 'pause_code', r.pause_code, 'pause_reason', r.pause_reason,
          'cancel_requested', r.cancel_requested, 'external_post_id', r.external_post_id, 'external_url', r.external_url,
          'reconcile_state', r.reconcile_state, 'attempt_count', r.attempt_count, 'error_code', r.error_code,
          'error_message', r.error_message, 'published_at', r.published_at, 'version', r.version, 'updated_at', r.updated_at,
          'audio', r.audio, 'audio_verified_at', r.audio_verified_at, 'audio_required', drinks_pub_needs_audio(r),
          'files', case when r.meme_draft_id is null then
              (select jsonb_agg(jsonb_build_object('role', ma.role, 'position', ma.position, 'storage_key', a.storage_key,
                  'width', a.width, 'height', a.height, 'state', a.state) order by ma.role, ma.position)
                from drink_manifest_assets ma join drink_media_assets a on a.id = ma.asset_id where ma.manifest_id = r.manifest_id)
            else (select jsonb_agg(jsonb_build_object('role', f ->> 'role', 'position', 1, 'storage_key', f ->> 'storage_key',
                  'width', (f ->> 'width')::int, 'height', (f ->> 'height')::int, 'state', 'stored') order by f ->> 'role')
                from jsonb_array_elements(d.files) f where f ->> 'role' in ('final_video','cover')) end) x
        from drink_publication_requests r left join drink_topics t on t.id = r.topic_id
        left join drink_meme_drafts d on d.id = r.meme_draft_id left join drink_ig_cards c on c.id = d.card_id
        order by r.updated_at desc limit v_lim) q), '[]'),
    'requests_truncated', (select count(*) > v_lim from drink_publication_requests),
    -- 발행안을 만들 수 있는 것: 지금도 쓸 수 있는 검수 승인 묶음 중 살아 있는 요청이 없는 것
    'ready_outputs', coalesce((select jsonb_agg(jsonb_build_object('output_review_id', v.review_id, 'manifest_id', v.manifest_id,
        'plan_revision_id', v.plan_revision_id, 'format', m.format, 'topic_title', t.title, 'reviewed_at', o.reviewed_at,
        'content_format', case when drinks_plan_is_explainer(pl.id) then 'explainer' else 'card' end,
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
    -- 0068: 게시 대기 중인 밈 제작안(박자 무관만 여기 온다 — 박자 맞춤은 manual_audio 라 목록에 없다) 중 살아 있는 요청이 없는 것
    'ready_memes', coalesce((select jsonb_agg(jsonb_build_object('draft_id', d.id, 'owner_name', coalesce(c.name, t.title, '(밈 제작안)'),
        'card_id', d.card_id, 'topic_id', d.topic_id, 'frame', d.spec ->> 'frame', 'top_line', d.spec ->> 'top_line', 'caption', d.spec ->> 'caption',
        'audio_mode', d.spec -> 'audio' ->> 'mode', 'audio_id', d.spec -> 'audio' ->> 'audio_id', 'bought_scene', d.spec -> 'scene' ->> 'source' = 'bought_reaction',
        'duration_ms', (select (f ->> 'duration_ms')::int from jsonb_array_elements(d.files) f where f ->> 'role' = 'final_video' limit 1),
        'approved_at', d.approved_at, 'updated_at', d.updated_at) order by d.updated_at desc)
      from drink_meme_drafts d left join drink_ig_cards c on c.id = d.card_id left join drink_topics t on t.id = d.topic_id
      where d.status = 'publish_waiting' and d.sync_grade = 'sync_free' and coalesce(d.spec -> 'audio' ->> 'mode', '') <> 'app_manual'
        and not exists (select 1 from drink_publication_requests r where r.meme_draft_id = d.id and r.status not in ('canceled','failed'))), '[]'),
    -- 0065: 고를 수 있는 음원(가장 최근 수집일의 목록, 인스타가 준 순서). 트렌드 수집이 없으면 빈 목록이다.
    'audio_options', coalesce((select jsonb_agg(jsonb_build_object('audio_id', x.audio_id, 'audio_type', x.audio_type, 'title', x.title,
        'display_artist', x.display_artist, 'duration_ms', x.duration_ms, 'preview_url', x.preview_url, 'list_position', x.list_position)
        order by x.list_position nulls last)
      from (select * from drink_ig_audio_latest order by list_position nulls last limit 50) x), '[]'),
    -- 추천 게시 시간대: 지금 전략의 slot 가중치(자동으로 넣지 않는다 — 발행안 작성 때 참고로만)
    'slot_weights', (select weights -> 'slot' from drink_strategy_versions where status = 'active'),
    'ai_label_text', drinks_ai_label_text());
end $$;

create or replace function drinks_analytics_board(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'limits', drinks_publish_limits(),
    'accounts', (select count(*) from drink_social_accounts),
    'active_accounts', (select count(*) from drink_social_accounts where status = 'active'),
    -- 실제(가짜 아님) 연결 확인 계정 수 — 0 이면 화면이 '미연결'을 띄운다(시험 계정 숫자를 실제 성과로 보이지 않게)
    'real_active_accounts', (select count(*) from drink_social_accounts where status = 'active' and connection <> 'fake'),
    'posts', coalesce((select jsonb_agg(x order by x ->> 'published_at' desc) from (
        select jsonb_build_object('request_id', r.id, 'topic_title', coalesce(t.title, c.name, '(밈 제작안)'), 'categories', coalesce(to_jsonb(t.categories), '[]'::jsonb),
          'lane', t.lane, 'post_type', r.post_type, 'format', r.content_format, 'account', a.display_name, 'is_test', a.connection = 'fake',
          'external_url', r.external_url, 'published_at', r.published_at,
          'slot', drinks_time_slot(r.published_at),
          'snapshots', coalesce((select jsonb_agg(jsonb_build_object('bucket', s.age_bucket, 'hours', s.hours_since_publish,
              'values', s.metric_values, 'unavailable', s.unavailable, 'status', s.fetch_status, 'error_code', s.error_code,
              'observed_at', s.observed_at) order by s.observed_at) from drink_post_metric_snapshots s where s.request_id = r.id), '[]')) x
        from drink_publication_requests r left join drink_topics t on t.id = r.topic_id join drink_social_accounts a on a.id = r.account_id
        left join drink_meme_drafts d on d.id = r.meme_draft_id left join drink_ig_cards c on c.id = d.card_id
        where r.status = 'published' order by r.published_at desc limit 300) q), '[]'),
    'posts_truncated', (select count(*) > 300 from drink_publication_requests where status = 'published'),
    -- 0068: 형식별 묶음 — 비교 칸(72h) 스냅샷이 있는 게시물 수. 화면이 "어느 형식이 몇 편 쌓였나"를 바로 본다.
    'format_counts', coalesce((select jsonb_object_agg(f, n) from (
        select r.content_format f, count(*) n from drink_publication_requests r where r.status = 'published' group by r.content_format) z), '{}'::jsonb),
    'active_strategy', (select jsonb_build_object('id', v.id, 'label', v.label, 'weights', v.weights, 'created_at', v.created_at)
      from drink_strategy_versions v where v.status = 'active'),
    'proposals', coalesce((select jsonb_agg(jsonb_build_object('id', x.id, 'status', x.status, 'weights', x.weights, 'basis', x.basis,
        'sample_total', x.sample_total, 'sufficient', x.sufficient, 'summary_ko', x.summary_ko, 'created_at', x.created_at,
        'decided_at', x.decided_at, 'reason', x.reason, 'base_version_id', x.base_version_id) order by x.created_at desc)
      from (select * from drink_strategy_proposals order by created_at desc limit 10) x), '[]'),
    'rank', drinks_strategy_rank(jsonb_build_object('limit', 200)))
$$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: anon·authenticated 에 아무것도 주지 않는다) + 검색 경로 고정(0056)
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
--   select has_function_privilege('anon', 'public.drinks_create_meme_publication(jsonb)', 'EXECUTE');   → false
--   select drinks_pub_digest(r) = r.approval_digest from drink_publication_requests r where r.meme_draft_id is null and r.approval_digest is not null;   → 전부 true(옛 승인 지문이 그대로)
--   select content_format, count(*) from drink_publication_requests group by 1;   → 기존 행은 card(설명형 소재면 explainer)
