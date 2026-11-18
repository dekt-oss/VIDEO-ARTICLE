-- 주류 — 설명형 릴스 캡션의 'AI 생성 영상' 한 줄을 필수에서 뺀다(2026-11-18).
--
-- 운영자: "ai생성내용 왜 필수임? 그냥 바로 올릴 수 있게 열어놔".
-- 0068 은 설명형 캡션에 그 한 줄이 없으면 발행안을 만들지도, 승인·게시하지도 못하게 막았다(기획 v2 §3-4).
-- 영상 자체에는 화면 위쪽에 "생성형 AI 이미지 포함" 표시가 계속 나간다(engine/drinks_clay.draw_layers). 캡션 한 줄만 선택으로 바꾼다.
-- 밈(산 장면을 쓴 것)의 규칙은 그대로다.
-- 바뀌는 것: drinks_pub_ai_label_missing(설명형이면 항상 false), drinks_create_publication(설명형 검사 삭제, 나머지는 0068 그대로).
-- 되돌리기: 0068 의 두 함수를 다시 실행한다.

create or replace function drinks_pub_ai_label_missing(r drink_publication_requests) returns boolean language sql stable set search_path = public, pg_temp as $$
  select case
    when r.content_format = 'meme' then coalesce((select d.spec -> 'scene' ->> 'source' = 'bought_reaction' from drink_meme_drafts d where d.id = r.meme_draft_id), false)
      and position('AI 생성' in coalesce(r.caption, '')) = 0
    else false end
$$;

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
  -- 0088: 형식만 정한다. 설명형 캡션의 'AI 생성 영상' 한 줄은 이제 선택이다(운영자 2026-11-18).
  v_fmt := case when drinks_plan_is_explainer(pl.id) then 'explainer' else 'card' end;
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

revoke all on function drinks_create_publication(jsonb) from public, anon, authenticated;
grant execute on function drinks_create_publication(jsonb) to service_role;
revoke all on function drinks_pub_ai_label_missing(drink_publication_requests) from public, anon, authenticated;
grant execute on function drinks_pub_ai_label_missing(drink_publication_requests) to service_role;
