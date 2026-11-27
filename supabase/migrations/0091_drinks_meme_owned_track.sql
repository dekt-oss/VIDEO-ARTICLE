-- 0091 주류 밈: 우리 음원 박자 구움(owned_track) — docs/plans/2026-11-26-hyperframes-engine.md S3 · docs/deviation-drinks-meme-owned-track.md
--
-- 무엇이 바뀌나
--   · 음원 방식에 'owned_track' 추가. 영상에 우리 권리 음원(assets/music/ledger.json)을 박자에 맞춰 구워 넣는다(engine/hf_render.py).
--   · 앱에서 음원을 맞춰 붙일 필요가 없으므로 등급은 박자 무관(sync_free) — 기존 게시 대기·발행 경로를 그대로 탄다.
--     박자 맞춤(sync_required)·앱 부착(app_manual)·표 제약(drink_meme_sync_gate_ck)은 그대로다.
--   · '박자 맞춤 카드는 박자 무관으로 승인 안 됨' 규칙은 owned_track 이면 비켜 간다(박자를 우리가 맞췄으므로).
--   · owned_track 은 ① 위쪽 글 틀(top_text) + 글 배경(text_bg)만 — 하이퍼프레임 템플릿이 그 틀 하나다.
--   · 승인 지문(drinks_meme_digest)은 spec 전체를 묶으므로 음원 이름(track)도 지문에 들어간다. 음원 파일 자체의 무결성은
--     워커가 렌더 직전 ledger 의 sha256 과 대조한다.
--
-- 되돌리기
--   0066 의 drinks_meme_blockers 정의를 다시 적용한다(이 파일 함수만 바뀐다. 표·제약·다른 함수는 그대로).
--   이미 owned_track 으로 승인된 초안은 그 뒤 저장·승인에서 '소리 등급·음원 방식을 고르세요'로 막힌다 — 초안으로 되돌려 소리를 다시 고른다.
--   이미 만든 파일·게시 기록은 지우지 않는다.

create or replace function drinks_meme_blockers(p_spec jsonb, p_review uuid, p_card uuid) returns jsonb
language plpgsql stable set search_path = public, pg_temp as $$
declare
  v_lim jsonb := drinks_meme_limits(); v_out jsonb := '[]'; v_beats jsonb := coalesce(p_spec -> 'beats', '[]'); b jsonb; v_total bigint := 0;
  v_max int := (v_lim ->> 'text_max_chars')::int; v_text text; v_top text := btrim(coalesce(p_spec ->> 'top_line', '')); r record; v_hit text;
  v_mode text := p_spec -> 'audio' ->> 'mode'; v_grade text := p_spec ->> 'sync_grade'; v_scene text := p_spec -> 'scene' ->> 'source';
  v_info boolean := coalesce((p_spec ->> 'contains_info')::boolean, false); v_ids jsonb := coalesce(p_spec -> 'claim_ids', '[]');
  v_rev drink_topic_reviews; v_ms numeric; v_asset uuid; v_bad text;
begin
  if coalesce(p_spec ->> 'frame', '') not in ('top_text','full_title') then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '화면 틀을 고르세요');
  end if;
  if v_top = '' or length(v_top) > v_max then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '윗줄·제목은 1~' || v_max || '자입니다');
  end if;
  if jsonb_typeof(v_beats) <> 'array' or jsonb_array_length(v_beats) < 1 or jsonb_array_length(v_beats) > (v_lim ->> 'max_beats')::int then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '비트는 1~' || (v_lim ->> 'max_beats') || '개입니다');
    v_beats := '[]';
  end if;
  v_text := v_top || E'\n' || coalesce(p_spec ->> 'caption', '');
  for b in select * from jsonb_array_elements(v_beats) loop
    if length(btrim(coalesce(b ->> 'text', ''))) not between 1 and v_max then
      v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '비트 글은 1~' || v_max || '자입니다');
    end if;
    v_text := v_text || E'\n' || coalesce(b ->> 'text', '');
    v_ms := case when jsonb_typeof(b -> 'ms') = 'number' then (b ->> 'ms')::numeric end;
    if v_ms is null or v_ms <> trunc(v_ms) or v_ms not between (v_lim ->> 'beat_min_ms')::int and (v_lim ->> 'beat_max_ms')::int then
      v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '비트 길이가 범위 밖입니다');
    else
      v_total := v_total + v_ms::bigint;
    end if;
  end loop;
  if v_total not between (v_lim ->> 'min_ms')::int and (v_lim ->> 'max_ms')::int then
    v_out := v_out || jsonb_build_object('code', 'meme_duration', 'message', '길이는 6~15초입니다(지금 ' || round(v_total / 1000.0, 1) || '초)');
  end if;
  if v_grade is null or v_grade not in ('sync_free','sync_required') or v_mode is null or v_mode not in ('none','ambient_local','ig_audio','app_manual','owned_track') then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '소리 등급·음원 방식을 고르세요');
  end if;
  if v_grade = 'sync_required' and (v_mode is distinct from 'app_manual' or btrim(coalesce(p_spec -> 'audio' ->> 'title', '')) = ''
      or jsonb_typeof(p_spec -> 'audio' -> 'start_hint_sec') is distinct from 'number') then
    v_out := v_out || jsonb_build_object('code', 'meme_sync_blocked', 'message', '박자 맞춤은 앱에서 붙일 음원 이름과 시작 지점(초)이 있어야 합니다');
  end if;
  if v_grade = 'sync_free' and v_mode = 'app_manual' then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '앱에서 붙이는 음원은 박자 맞춤 등급에서만 씁니다');
  end if;
  if v_mode = 'ig_audio' and btrim(coalesce(p_spec -> 'audio' ->> 'audio_id', '')) = '' then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '인스타 음원을 쓰려면 음원 ID 가 있어야 합니다');
  end if;
  if v_mode = 'owned_track' and btrim(coalesce(p_spec -> 'audio' ->> 'track', '')) = '' then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '우리 음원 이름(track)이 없습니다');
  end if;
  if v_mode = 'owned_track' and (coalesce(p_spec ->> 'frame', '') <> 'top_text' or v_scene is distinct from 'text_bg') then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '우리 음원 박자 영상은 ① 위쪽 글 틀 + 글 배경으로만 만듭니다');
  end if;
  -- 0091: 우리 음원을 박자에 맞춰 구운 밈은 앱에서 붙일 필요가 없다 → 박자 맞춤 카드여도 박자 무관 등급으로 승인된다
  if v_grade = 'sync_free' and v_mode is distinct from 'owned_track' and p_card is not null and drinks_meme_card_sync_required(p_card) then
    v_out := v_out || jsonb_build_object('code', 'meme_sync_blocked', 'message', '이 카드는 박자에 맞춰야 성립한다고 적혀 있습니다 - 박자 맞춤으로 두거나 카드 칸을 고치세요');
  end if;
  if v_scene is null or v_scene not in ('text_bg','bought_reaction') then
    v_out := v_out || jsonb_build_object('code', 'meme_invalid', 'message', '장면은 글+배경 또는 우리가 산 반응 장면입니다');
  elsif v_scene = 'bought_reaction' then
    begin
      v_asset := (p_spec -> 'scene' ->> 'asset_id')::uuid;
    exception when others then
      v_asset := null;
    end;
    if v_asset is null or not exists (select 1 from drink_media_assets a where a.id = v_asset and a.state = 'stored' and a.rights in ('generated_paid','own','licensed')) then
      v_out := v_out || jsonb_build_object('code', 'meme_foreign_media', 'message', '장면 칸은 우리 권리의 파일만 받습니다');
    elsif coalesce(p_spec ->> 'caption', '') !~ 'AI 생성' then
      v_out := v_out || jsonb_build_object('code', 'meme_ai_label_missing', 'message', '산 장면을 쓰면 캡션에 AI 생성 영상 한 줄을 넣습니다');
    end if;
  end if;
  for r in select * from drinks_meme_unsafe_rules() loop
    v_hit := substring(v_text from '(?i)' || r.pattern);
    if v_hit is not null then
      v_out := v_out || jsonb_build_object('code', r.code, 'message', r.label || ' - ''' || v_hit || ''' 는 쓰지 않습니다');
    end if;
  end loop;
  if v_text ~* drinks_meme_info_pattern() and not v_info then
    v_out := v_out || jsonb_build_object('code', 'meme_info_undeclared', 'message', '정보로 읽히는 말이 있습니다 - 정보 포함으로 표시하고 근거를 붙이거나 말을 바꾸세요');
  end if;
  if v_info then
    select * into v_rev from drink_topic_reviews where id = p_review;
    if not found or v_rev.status <> 'approved' or v_rev.revoked_at is not null then
      v_out := v_out || jsonb_build_object('code', 'meme_evidence_missing', 'message', '정보가 들어간 밈인데 승인된 근거 버전이 없습니다 - 멈춥니다');
    elsif jsonb_typeof(v_ids) <> 'array' or jsonb_array_length(v_ids) = 0 then
      v_out := v_out || jsonb_build_object('code', 'meme_evidence_missing', 'message', '정보가 들어간 밈인데 근거 주장을 고르지 않았습니다 - 멈춥니다');
    else
      select string_agg(i, ', ') into v_bad from jsonb_array_elements_text(v_ids) i
        where not exists (select 1 from jsonb_array_elements(v_rev.evidence_pack -> 'claims') c where c ->> 'claim_id' = i);
      if v_bad is not null then
        v_out := v_out || jsonb_build_object('code', 'meme_evidence_missing', 'message', '승인된 근거에 없는 주장입니다: ' || v_bad);
      end if;
    end if;
  end if;
  return v_out;
end $$;
