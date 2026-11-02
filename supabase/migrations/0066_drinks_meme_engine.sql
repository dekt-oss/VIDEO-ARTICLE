-- 주류 공장 - 밈형 제작 엔진 (2026-11-02). docs/deviation-drinks-meme-engine.md
-- 기획: docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md §4-3·§5, docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md §5·§6-5·§7.
--
-- ★ 파일만 있다. 운영 적용은 따로 결재받는다. 0063·0064 가 먼저 적용돼 있어야 한다.
--
-- 무엇: 밈 카드([쓰자])나 밈으로 고른 소재 → 제작안 초안 → 사람 승인 → 로컬 제작 → 게시 대기.
--   drink_meme_drafts       제작안 한 벌과 상태. 승인 때 내용 지문을 고정한다.
--   drink_meme_events       상태 변화 기록(지울 수 없다).
--   drink_develop_holds     칸 하나를 더한다(meme_draft_id). 글 초안 LLM 도 같은 결재 잔액에서 잡히게 하려고.
-- 왜 여기서 막나:
--   · 박자 맞춤(sync_required)은 표 제약으로 게시 대기(publish_waiting)에 들어갈 수 없다. 워커가 무엇을 보내든 DB 가 manual_audio 로 정한다.
--   · 음주 조장·미성년·과음 미화 낱말은 승인에서 막힌다(규칙은 engine/config.py DRINKS_MEME_UNSAFE_RULES 와 같아야 한다 - tests/test_drinks_meme.py 가 대조).
--   · 정보가 들어간 밈은 승인된 근거 버전과 그 안의 주장 ID 가 없으면 승인되지 않는다(근거 없으면 멈춤).
--   · 남의 영상·게시물 주소는 제작안에 저장 자체가 거부된다. 장면 칸은 우리 권리의 파일(drink_media_assets)만 가리킨다.
-- 하지 않는 것:
--   · 게시 요청(drink_publication_requests)을 만들지 않는다. 게시 대기까지가 끝이다. 게시 워커 연결은 다음 결재 대상이다.
--   · 돈이 나가는 함수는 글 초안의 가잡기(drinks_meme_hold)뿐이고, 결재가 없으면 budget_missing 으로 거부된다. 반응 장면 구매는 없다.
--   · [쓰자](drinks_ig_card_decide)와 [이걸로](drinks_pick_topic)는 고치지 않는다. 제작안은 별도 동작으로 만든다.
-- 영향: 표 추가 + drink_develop_holds 칸 추가(request_id 만 null 허용, 기존 행 변화 없음).
-- 되돌리기:
--   drop view if exists drink_meme_board;
--   delete from drink_develop_holds where meme_draft_id is not null;  -- 트리거가 막으면 먼저 트리거를 내린다. 밈 글 초안 지출 기록이 사라진다
--   alter table drink_develop_holds drop constraint drink_develop_holds_owner_ck, drop column meme_draft_id, alter column request_id set not null;
--   do $$ declare f record; begin for f in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--     where n.nspname = 'public' and (p.proname like 'drinks\_meme\_%' or p.proname = 'drink_meme_drafts_guard') loop execute format('drop function %s cascade', f.sig); end loop; end $$;
--   drop table if exists drink_meme_events, drink_meme_drafts;
--   버킷의 drinks/memes/ 아래 파일은 따로 지운다.

-- ─────────────────────────────────────────────────────────────
-- 상수 (engine/config.py DRINKS_MEME_* 와 같아야 한다)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_meme_limits() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object('min_ms', 6000, 'max_ms', 15000, 'beat_min_ms', 500, 'beat_max_ms', 8000, 'max_beats', 6, 'text_max_chars', 60,
    'text_max_usd_per_draft', 0.02, 'text_max_calls_per_draft', 3, 'lease_sec', 900)
$$;

create or replace function drinks_meme_unsafe_rules() returns table (code text, label text, pattern text)
language sql immutable set search_path = public, pg_temp as $$
  values
    ('meme_encourages_drinking', '음주 조장', '(원\s*샷|한\s*잔\s*더|한\s*병\s*더|더\s*마셔|마셔\s*라|마시자|달리자|부어라|벌주|취하자|먹고\s*죽|오늘은\s*마신다)'),
    ('meme_minor', '미성년', '(미성년|고등학생|중학생|초등학생|고딩|중딩|초딩|교복|수능|청소년|학교\s*끝나고)'),
    ('meme_overdrinking', '과음 미화', '(필름\s*(이\s*)?끊|꽐라|만취|폭음|폭탄주|주량\s*자랑|토할\s*때까지|기억\s*(이\s*)?안\s*나|인사불성|해장술|술고래|말술|[0-9]+\s*병\s*(은\s*)?(기본|마셨|깠))'),
    ('meme_drunk_driving', '음주운전', '(음주\s*운전|술\s*마시고\s*운전|한\s*잔만\s*하고\s*운전)'),
    ('meme_pregnancy', '임신 중 음주', '(임산부|임신\s*중)')
$$;

create or replace function drinks_meme_info_pattern() returns text language sql immutable set search_path = public, pg_temp as $$
  select '([0-9]+\s*(%|퍼센트|도|ml|밀리|리터|칼로리|kcal|년산|배)|연구|논문|과학적|칼로리|숙취\s*해소|건강에|몸에\s*(좋|나쁘)|효과가|법적으로|법으로|법령|세금|주세)'::text
$$;

create or replace function drinks_meme_foreign_pattern() returns text language sql immutable set search_path = public, pg_temp as $$
  select '(instagram\.com|cdninstagram|fbcdn|tiktok|youtube\.com|youtu\.be|media_url|permalink)'::text
$$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_meme_drafts (
  id                 uuid primary key default gen_random_uuid(),
  card_id            uuid references drink_ig_cards(id),
  topic_id           uuid references drink_topics(id),
  status             text not null default 'draft' check (status in ('text_requested','text_running','draft','approved','rendering',
                       'publish_waiting','manual_audio','posted_manual','stopped','failed','rejected')),
  spec               jsonb not null default '{}' check (jsonb_typeof(spec) = 'object' and length(spec::text) <= 20000),
  sync_grade         text check (sync_grade is null or sync_grade in ('sync_free','sync_required')),
  frame_hint         text check (frame_hint is null or frame_hint in ('top_text','full_title')),   -- 글 초안 요청 때만 쓴다
  evidence_review_id uuid references drink_topic_reviews(id),
  budget_id          uuid references drink_develop_budgets(id),
  approved_digest    text,
  approved_by        text,
  approved_at        timestamptz,
  lease_token        uuid,
  lease_expires_at   timestamptz,
  worker_id          text,
  files              jsonb not null default '[]' check (jsonb_typeof(files) = 'array'),
  qa                 jsonb not null default '{}' check (jsonb_typeof(qa) = 'object'),
  safety             jsonb not null default '{}' check (jsonb_typeof(safety) = 'object'),
  guide              text check (guide is null or length(guide) <= 4000),
  error_code         text check (error_code is null or length(error_code) <= 60),
  error_message      text check (error_message is null or length(error_message) <= 2000),
  external_url       text check (external_url is null or external_url ~ '^https://(www\.)?instagram\.com/'),   -- 운영자가 앱에서 올린 우리 게시물
  version            int not null default 1,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint drink_meme_owner_ck check ((card_id is null) <> (topic_id is null)),
  -- ★ 박자 맞춤은 게시 대기에 들어갈 수 없다. 앱에서 붙이는 경로(manual_audio) 말고는 길이 없다.
  constraint drink_meme_sync_gate_ck check (status <> 'publish_waiting' or sync_grade = 'sync_free'),
  constraint drink_meme_manual_ck check (status not in ('manual_audio','posted_manual') or sync_grade = 'sync_required'),
  constraint drink_meme_sync_spec_ck check (sync_grade is not distinct from (spec ->> 'sync_grade')),
  constraint drink_meme_output_ck check (status not in ('publish_waiting','manual_audio','posted_manual') or jsonb_array_length(files) > 0),
  constraint drink_meme_guide_ck check (status <> 'manual_audio' or guide is not null),
  constraint drink_meme_posted_ck check (status <> 'posted_manual' or external_url is not null),
  constraint drink_meme_approved_ck check (status not in ('approved','rendering','publish_waiting','manual_audio','posted_manual')
    or (approved_at is not null and approved_digest is not null)),
  constraint drink_meme_lease_ck check (status not in ('rendering','text_running') or lease_token is not null)
);
-- 카드·소재 하나에 살아 있는 제작안은 하나.
create unique index if not exists drink_meme_one_live_card_uq on drink_meme_drafts (card_id) where card_id is not null and status not in ('rejected','stopped','failed','posted_manual');
create unique index if not exists drink_meme_one_live_topic_uq on drink_meme_drafts (topic_id) where topic_id is not null and status not in ('rejected','stopped','failed','posted_manual');
create index if not exists drink_meme_status_idx on drink_meme_drafts (status, approved_at);

create table if not exists drink_meme_events (
  id          bigint generated always as identity primary key,
  draft_id    uuid not null references drink_meme_drafts(id),
  action      text not null,
  from_status text,
  to_status   text,
  actor       text not null default 'operator',
  note        text check (note is null or length(note) <= 2000),
  created_at  timestamptz not null default now()
);
create index if not exists drink_meme_events_draft_idx on drink_meme_events (draft_id, id);
drop trigger if exists drink_meme_events_append_only on drink_meme_events;
create trigger drink_meme_events_append_only before update or delete on drink_meme_events
  for each row execute function drink_append_only_guard();

-- 글 초안 LLM 도 개발 결재(drink_develop_budgets) 잔액에서 잡힌다. 결재 뷰가 이 표를 세므로 따로 세지 않는다.
alter table drink_develop_holds add column if not exists meme_draft_id uuid references drink_meme_drafts(id);
alter table drink_develop_holds alter column request_id drop not null;
alter table drink_develop_holds drop constraint if exists drink_develop_holds_owner_ck;
alter table drink_develop_holds add constraint drink_develop_holds_owner_ck check (request_id is not null or meme_draft_id is not null);
create index if not exists drink_develop_holds_meme_idx on drink_develop_holds (meme_draft_id) where meme_draft_id is not null;

-- 승인된 뒤에는 내용이 안 바뀐다. 지우지 않는다. 게시 대기·앱 부착은 제작 중에서만 들어간다.
create or replace function drink_meme_drafts_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '제작안 기록은 지우지 않습니다 — 버리기로 닫으세요'); end if;
  if new.status in ('publish_waiting','manual_audio') and old.status <> new.status and old.status <> 'rendering' then
    perform drinks_fail('invalid_transition', '제작이 끝난 것만 게시 대기·앱 부착으로 갑니다');
  end if;
  if new.spec is distinct from old.spec and old.status not in ('draft','text_requested','text_running') then
    perform drinks_fail('immutable', '승인·제작에 들어간 제작안은 고칠 수 없습니다 — 다시 초안으로 되돌리세요');
  end if;
  new.updated_at := now();
  new.version := old.version + 1;
  return new;
end $$;
drop trigger if exists drink_meme_drafts_guard on drink_meme_drafts;
create trigger drink_meme_drafts_guard before update or delete on drink_meme_drafts
  for each row execute function drink_meme_drafts_guard();

-- ─────────────────────────────────────────────────────────────
-- 규칙
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_meme_log(p_id uuid, p_action text, p_from text, p_to text, p_note text default null, p_actor text default 'operator')
returns void language sql set search_path = public, pg_temp as $$
  insert into drink_meme_events (draft_id, action, from_status, to_status, actor, note) values (p_id, p_action, p_from, p_to, p_actor, left(p_note, 2000))
$$;

create or replace function drinks_meme_digest(p_spec jsonb, p_review uuid) returns text language sql immutable set search_path = public, pg_temp as $$
  select encode(sha256(convert_to(concat_ws('|', 'drinks-meme-v1', p_spec::text, coalesce(p_review::text, '')), 'UTF8')), 'hex')
$$;

create or replace function drinks_meme_card_sync_required(p_card uuid) returns boolean language sql stable set search_path = public, pg_temp as $$
  select coalesce((select f.value ~* '(필수|맞춰|맞춤|required)' from drink_ig_card_fields f where f.card_id = p_card and f.field = 'music_sync'), false)
$$;

-- 승인을 막는 이유 목록. engine/drinks_meme.py check_safety 와 같은 규칙이고, 워커가 제작 직전에 숫자·양·권고까지 다시 잰다.
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
  if v_grade is null or v_grade not in ('sync_free','sync_required') or v_mode is null or v_mode not in ('none','ambient_local','ig_audio','app_manual') then
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
  if v_grade = 'sync_free' and p_card is not null and drinks_meme_card_sync_required(p_card) then
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

-- ─────────────────────────────────────────────────────────────
-- 운영자 동작
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_meme_lock(p jsonb) returns drink_meme_drafts language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_expected int := drinks_int(p, 'expected_version', false);
begin
  select * into d from drink_meme_drafts where id = drinks_uuid(p, 'draft_id') for update;
  if not found then perform drinks_fail('not_found', '제작안을 찾지 못했습니다'); end if;
  if v_expected is not null and v_expected <> d.version then
    perform drinks_fail('version_conflict', '다른 곳에서 바뀌었습니다 - 화면을 새로 불러오세요');
  end if;
  return d;
end $$;

-- 제작안을 낼 수 있는 대상인가. 카드는 [쓰자] + 정밀 틀(기획 v2 §5·§6-5), 소재는 [이걸로]에서 밈으로 고른 것.
create or replace function drinks_meme_check_owner(p_card uuid, p_topic uuid) returns void language plpgsql stable set search_path = public, pg_temp as $$
declare c drink_ig_cards;
begin
  if (p_card is null) = (p_topic is null) then perform drinks_fail('invalid_input', '밈 카드 또는 소재 중 하나를 지정하세요'); end if;
  if p_card is not null then
    select * into c from drink_ig_cards where id = p_card;
    if not found then perform drinks_fail('not_found', '카드를 찾지 못했습니다'); end if;
    if c.decision is distinct from 'use' then perform drinks_fail('invalid_state', '[쓰자]로 고른 카드만 제작안을 만듭니다'); end if;
    if drinks_ig_card_precision(p_card) <> 'precise' then
      perform drinks_fail('card_not_precise', '참고 카드입니다 - 원본 릴스를 보고 비트 수·컷 길이·반전 시점을 넣으면 정밀 틀이 됩니다');
    end if;
  elsif not exists (select 1 from drink_topic_picks pk where pk.topic_id = p_topic and pk.format_intent = 'meme') then
    perform drinks_fail('invalid_state', '밈형으로 고른 소재가 아닙니다');
  end if;
end $$;

create or replace function drinks_meme_save_draft(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_spec jsonb := p -> 'spec'; v_review uuid := drinks_uuid(p, 'evidence_review_id', false);
  v_card uuid := drinks_uuid(p, 'card_id', false); v_topic uuid := drinks_uuid(p, 'topic_id', false); v_before text;
begin
  if v_spec is null or jsonb_typeof(v_spec) <> 'object' then perform drinks_fail('invalid_input', '제작안 내용이 없습니다'); end if;
  if v_spec::text ~* drinks_meme_foreign_pattern() then
    perform drinks_fail('meme_foreign_media', '남의 영상·게시물 주소는 제작안에 넣지 않습니다');
  end if;
  if p ? 'draft_id' and drinks_text(p, 'draft_id') is not null then
    d := drinks_meme_lock(p);
    if d.status <> 'draft' then perform drinks_fail('invalid_state', '초안 상태에서만 고칩니다 - 먼저 초안으로 되돌리세요'); end if;
    v_before := d.status;
    update drink_meme_drafts set spec = v_spec, sync_grade = v_spec ->> 'sync_grade', evidence_review_id = v_review, error_code = null, error_message = null
      where id = d.id returning * into d;
  else
    perform drinks_meme_check_owner(v_card, v_topic);
    begin
      insert into drink_meme_drafts (card_id, topic_id, spec, sync_grade, evidence_review_id)
        values (v_card, v_topic, v_spec, v_spec ->> 'sync_grade', v_review) returning * into d;
    exception when unique_violation then
      perform drinks_fail('draft_exists', '이 카드·소재에 이미 진행 중인 제작안이 있습니다');
    end;
  end if;
  perform drinks_meme_log(d.id, 'saved', v_before, d.status);
  return jsonb_build_object('draft_id', d.id, 'status', d.status, 'version', d.version, 'blockers', drinks_meme_blockers(d.spec, d.evidence_review_id, d.card_id));
end $$;

-- 글 초안 요청. 큐에 넣을 뿐이고, 모델 호출은 워커가 결재 안에서만 한다.
create or replace function drinks_meme_request_text(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_card uuid := drinks_uuid(p, 'card_id', false); v_topic uuid := drinks_uuid(p, 'topic_id', false);
  v_budget uuid := drinks_uuid(p, 'budget_id', false); b drink_develop_budgets; v_frame text := drinks_text(p, 'frame');
begin
  if v_budget is null then perform drinks_fail('budget_missing', '글 초안을 모델로 쓰려면 열린 개발 결재가 있어야 합니다 - 없으면 직접 쓰세요'); end if;
  select * into b from drink_develop_budgets where id = v_budget;
  if not found or b.status <> 'open' or b.expires_at <= now() then perform drinks_fail('approval_closed', '닫혔거나 기간이 지난 결재입니다'); end if;
  if v_frame is null or v_frame not in ('top_text','full_title') then perform drinks_fail('invalid_input', '화면 틀을 고르세요'); end if;
  perform drinks_meme_check_owner(v_card, v_topic);
  begin
    insert into drink_meme_drafts (card_id, topic_id, status, budget_id, frame_hint) values (v_card, v_topic, 'text_requested', v_budget, v_frame) returning * into d;
  exception when unique_violation then
    perform drinks_fail('draft_exists', '이 카드·소재에 이미 진행 중인 제작안이 있습니다');
  end;
  perform drinks_meme_log(d.id, 'text_requested', null, d.status);
  return jsonb_build_object('draft_id', d.id, 'status', d.status, 'version', d.version);
end $$;

create or replace function drinks_meme_draft_action(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_action text := drinks_text(p, 'action'); v_before text; v_block jsonb; v_url text;
begin
  perform drinks_meme_reap();
  d := drinks_meme_lock(p);
  v_before := d.status;
  if v_action = 'approve' then
    if d.status <> 'draft' then perform drinks_fail('invalid_state', '초안만 승인합니다'); end if;
    v_block := drinks_meme_blockers(d.spec, d.evidence_review_id, d.card_id);
    if jsonb_array_length(v_block) > 0 then
      perform drinks_fail(coalesce(
        (select b ->> 'code' from jsonb_array_elements(v_block) b where b ->> 'code' <> 'meme_invalid' limit 1), 'meme_invalid'),
        (select string_agg(b ->> 'message', ' / ') from jsonb_array_elements(v_block) b), jsonb_build_object('blockers', v_block));
    end if;
    update drink_meme_drafts set status = 'approved', approved_digest = drinks_meme_digest(spec, evidence_review_id), approved_by = 'operator', approved_at = now(),
      error_code = null, error_message = null where id = d.id returning * into d;
  elsif v_action = 'reopen' then
    if d.status not in ('approved','stopped','failed','publish_waiting','manual_audio') then perform drinks_fail('invalid_state', '이 상태는 초안으로 되돌리지 않습니다'); end if;
    if exists (select 1 from drink_meme_drafts x where x.id <> d.id and x.status not in ('rejected','stopped','failed','posted_manual')
        and (x.card_id = d.card_id or x.topic_id = d.topic_id)) then
      perform drinks_fail('draft_exists', '이 카드·소재에 이미 진행 중인 다른 제작안이 있습니다');
    end if;
    update drink_meme_drafts set status = 'draft', approved_digest = null, approved_by = null, approved_at = null, files = '[]', guide = null, qa = '{}', safety = '{}',
      lease_token = null, lease_expires_at = null where id = d.id returning * into d;
  elsif v_action = 'reject' then
    if d.status not in ('draft','approved','stopped','failed','publish_waiting','manual_audio') then perform drinks_fail('invalid_state', '이 상태는 버릴 수 없습니다'); end if;
    update drink_meme_drafts set status = 'rejected', error_message = left(drinks_text(p, 'reason'), 2000) where id = d.id returning * into d;
  elsif v_action = 'manual_posted' then
    -- 앱에서 음원을 붙여 올린 뒤 운영자가 링크를 남긴다(기획 v2 §5). 서버는 이 주소를 열지 않는다.
    if d.status <> 'manual_audio' then perform drinks_fail('invalid_state', '앱 부착 대기 중인 것만 등록합니다'); end if;
    v_url := drinks_text(p, 'url');
    if v_url is null or v_url !~ '^https://(www\.)?instagram\.com/' then perform drinks_fail('invalid_input', '인스타 게시물 주소를 넣으세요'); end if;
    update drink_meme_drafts set status = 'posted_manual', external_url = v_url where id = d.id returning * into d;
  else
    perform drinks_fail('invalid_input', '알 수 없는 동작입니다');
  end if;
  perform drinks_meme_log(d.id, v_action, v_before, d.status, drinks_text(p, 'reason'));
  return jsonb_build_object('draft_id', d.id, 'status', d.status, 'version', d.version);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 전용 — 승인 함수를 부르지 않는다. 사람 승인을 대신하지 않는다
-- ─────────────────────────────────────────────────────────────

-- 임대가 끝난 작업을 닫는다. 잡아 둔 글 초안 지출은 해제한다(호출이 성공했는지 모르면 예상액을 확정해 잔액을 지킨다).
create or replace function drinks_meme_reap() returns int language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_n int := 0;
begin
  for d in select * from drink_meme_drafts where status in ('rendering','text_running') and lease_expires_at < now() for update skip locked loop
    update drink_develop_holds set status = 'settled', actual_usd = est_usd, settled_at = now(), note = '워커가 사라져 예상액으로 확정' where meme_draft_id = d.id and status = 'held';
    update drink_meme_drafts set status = 'failed', error_code = 'worker_lost', error_message = '워커가 끝내지 못했습니다 - 초안으로 되돌려 다시 승인하세요', lease_token = null, lease_expires_at = null
      where id = d.id;
    perform drinks_meme_log(d.id, 'reaped', d.status, 'failed', null, 'worker');
    v_n := v_n + 1;
  end loop;
  return v_n;
end $$;

create or replace function drinks_meme_card_json(p_card uuid) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('id', c.id, 'name', c.name, 'structure', c.structure, 'audio_id', c.audio_id,
    'fields', coalesce((select jsonb_object_agg(f.field, jsonb_build_object('value', f.value, 'evidence', f.evidence, 'confidence', f.confidence))
      from drink_ig_card_fields f where f.card_id = c.id), '{}'::jsonb))
  from drink_ig_cards c where c.id = p_card
$$;

create or replace function drinks_meme_claim(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_kind text := coalesce(drinks_text(p, 'kind'), 'render'); v_block jsonb; v_reaped int; v_token uuid := gen_random_uuid();
  v_until timestamptz := now() + make_interval(secs => (drinks_meme_limits() ->> 'lease_sec')::int); rv drink_topic_reviews; t drink_topics; v_asset jsonb;
begin
  v_reaped := drinks_meme_reap();
  if v_kind = 'text' then
    select * into d from drink_meme_drafts where status = 'text_requested' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    update drink_meme_drafts set status = 'text_running', lease_token = v_token, lease_expires_at = v_until, worker_id = drinks_text(p, 'worker_id') where id = d.id returning * into d;
    perform drinks_meme_log(d.id, 'text_started', 'text_requested', d.status, null, 'worker');
    select * into t from drink_topics where id = d.topic_id;
    return jsonb_build_object('reaped', v_reaped, 'job', jsonb_build_object('draft_id', d.id, 'lease_token', d.lease_token, 'frame', d.frame_hint,
      'card', drinks_meme_card_json(d.card_id),
      'topic', case when d.topic_id is null then null else jsonb_build_object('title', t.title, 'question', t.question) end));
  elsif v_kind <> 'render' then
    perform drinks_fail('invalid_input', 'kind 는 render·text 입니다');
  end if;
  loop
    select * into d from drink_meme_drafts where status = 'approved' order by approved_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    -- 승인한 내용 그대로인가, 지금도 규칙을 지키나(근거가 취소됐을 수 있다).
    v_block := drinks_meme_blockers(d.spec, d.evidence_review_id, d.card_id);
    if d.approved_digest is distinct from drinks_meme_digest(d.spec, d.evidence_review_id) or jsonb_array_length(v_block) > 0 then
      update drink_meme_drafts set status = 'stopped',
        error_code = case when jsonb_array_length(v_block) > 0 then v_block -> 0 ->> 'code' else 'digest_changed' end,
        error_message = coalesce((select string_agg(b ->> 'message', ' / ') from jsonb_array_elements(v_block) b), '승인 뒤 내용이 바뀌었습니다') where id = d.id;
      perform drinks_meme_log(d.id, 'claim_stopped', 'approved', 'stopped', null, 'worker');
      continue;
    end if;
    update drink_meme_drafts set status = 'rendering', lease_token = v_token, lease_expires_at = v_until, worker_id = drinks_text(p, 'worker_id') where id = d.id returning * into d;
    perform drinks_meme_log(d.id, 'render_started', 'approved', d.status, null, 'worker');
    select * into rv from drink_topic_reviews where id = d.evidence_review_id;
    if d.spec -> 'scene' ->> 'source' = 'bought_reaction' then
      select jsonb_build_object('storage_key', a.storage_key, 'sha256', a.sha256, 'rights', a.rights, 'provenance', a.provenance) into v_asset
        from drink_media_assets a where a.id = (d.spec -> 'scene' ->> 'asset_id')::uuid;
    end if;
    return jsonb_build_object('reaped', v_reaped, 'job', jsonb_build_object('draft_id', d.id, 'lease_token', d.lease_token, 'spec', d.spec,
      'card', case when d.card_id is null then null else drinks_meme_card_json(d.card_id) end,
      'hooks', coalesce((select jsonb_agg(h) from (
          select f.value as h from drink_ig_card_fields f where f.card_id = d.card_id and f.field in ('cover_text','caption_hook')
          union all
          select m.caption_hook from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id where e.card_id = d.card_id and m.caption_hook is not null) x), '[]'),
      'claims', coalesce(rv.evidence_pack -> 'claims', '[]'),
      'sources', case when rv.id is null then '[]'::jsonb else coalesce((select jsonb_agg(jsonb_build_object('title', s.title, 'publisher', s.publisher, 'url', s.canonical_url))
        from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
          from jsonb_array_elements(rv.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]') end,
      'scene_asset', v_asset));
  end loop;
end $$;

create or replace function drinks_meme_lock_lease(p jsonb, p_status text) returns drink_meme_drafts language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts;
begin
  select * into d from drink_meme_drafts where id = drinks_uuid(p, 'draft_id') for update;
  if not found or d.status <> p_status or d.lease_token is distinct from drinks_uuid(p, 'lease_token') then
    perform drinks_fail('lease_lost', '이 작업의 임대를 잃었습니다');
  end if;
  return d;
end $$;

-- 제작 끝. ★ 어디로 갈지는 워커가 아니라 DB 가 등급으로 정한다.
create or replace function drinks_meme_finish(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_out text := drinks_text(p, 'outcome'); v_files jsonb := coalesce(p -> 'files', '[]'); v_next text; v_guide text := left(drinks_text(p, 'guide'), 4000); f jsonb;
begin
  d := drinks_meme_lock_lease(p, 'rendering');
  if v_out = 'rendered' then
    if not exists (select 1 from jsonb_array_elements(v_files) x where x ->> 'role' = 'final_video') then
      perform drinks_fail('invalid_manifest', '완성 영상이 없습니다');
    end if;
    for f in select * from jsonb_array_elements(v_files) loop
      if coalesce(f ->> 'storage_key', '') !~ '^(drinks/memes/|local:drinks/memes/)' or coalesce(f ->> 'sha256', '') !~ '^[0-9a-f]{64}$' then
        perform drinks_fail('invalid_manifest', '파일 기록이 규칙에 맞지 않습니다');
      end if;
    end loop;
    v_next := case when d.sync_grade = 'sync_free' and d.spec -> 'audio' ->> 'mode' <> 'app_manual' then 'publish_waiting' else 'manual_audio' end;
    if v_next = 'manual_audio' and v_guide is null then perform drinks_fail('invalid_manifest', '앱 부착 안내가 없습니다'); end if;
    update drink_meme_drafts set status = v_next, files = v_files, guide = v_guide, qa = coalesce(p -> 'qa', '{}'), safety = coalesce(p -> 'safety', '{}'),
      lease_token = null, lease_expires_at = null, error_code = null, error_message = null where id = d.id returning * into d;
  elsif v_out in ('stopped','failed') then
    update drink_meme_drafts set status = v_out, qa = coalesce(p -> 'qa', '{}'), safety = coalesce(p -> 'safety', '{}'), lease_token = null, lease_expires_at = null,
      error_code = left(drinks_text(p, 'error_code'), 60), error_message = left(drinks_text(p, 'error_message'), 2000) where id = d.id returning * into d;
  else
    perform drinks_fail('invalid_input', 'outcome 은 rendered·stopped·failed 입니다');
  end if;
  perform drinks_meme_log(d.id, 'render_' || v_out, 'rendering', d.status, d.error_code, 'worker');
  return jsonb_build_object('draft_id', d.id, 'status', d.status, 'version', d.version);
end $$;

-- 글 초안 호출 전 가잡기. 결재 잔액·기간·초안 1건 상한을 잰다. 확정·해제는 drinks_develop_settle 을 그대로 쓴다.
create or replace function drinks_meme_hold(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; b drink_develop_budgets; h drink_develop_holds; v_est numeric := drinks_num(p, 'est_usd'); v_used numeric; v_n int; s jsonb; v_lim jsonb := drinks_meme_limits();
begin
  d := drinks_meme_lock_lease(p, 'text_running');
  if v_est <= 0 then perform drinks_fail('invalid_input', '예상 금액은 0 보다 커야 합니다'); end if;
  if d.budget_id is null then perform drinks_fail('budget_missing', '결재가 없는 요청은 모델을 부를 수 없습니다'); end if;
  select * into b from drink_develop_budgets where id = d.budget_id for update;
  if b.status <> 'open' then perform drinks_fail('approval_closed', '닫힌 결재로는 쓸 수 없습니다'); end if;
  if b.expires_at <= now() then perform drinks_fail('approval_expired', '결재 기간이 지났습니다'); end if;
  select coalesce(sum(case when status = 'held' then est_usd else actual_usd end) filter (where status in ('held','settled')), 0), count(*)
    into v_used, v_n from drink_develop_holds where meme_draft_id = d.id;
  if v_n >= (v_lim ->> 'text_max_calls_per_draft')::int then perform drinks_fail('hold_limit', '이 초안의 모델 호출이 ' || v_n || '번입니다 - 멈춥니다'); end if;
  if v_used + v_est > (v_lim ->> 'text_max_usd_per_draft')::numeric then perform drinks_fail('request_cap_exceeded', '초안 1건 상한을 넘습니다'); end if;
  s := drinks_develop_budget_json(b.id);
  if (s ->> 'remaining_usd')::numeric < v_est then perform drinks_fail('budget_exceeded', '결재 금액을 넘습니다'); end if;
  insert into drink_develop_holds (meme_draft_id, budget_id, model, est_usd, note) values (d.id, b.id, drinks_text(p, 'model'), v_est, '밈 글 초안') returning * into h;
  return jsonb_build_object('hold_id', h.id, 'remaining_usd', (s ->> 'remaining_usd')::numeric - v_est);
end $$;

-- 글 초안 끝. 초안 상태로만 간다 - 승인은 사람이 한다.
create or replace function drinks_meme_finish_text(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v_out text := drinks_text(p, 'outcome'); v_spec jsonb := p -> 'spec';
begin
  d := drinks_meme_lock_lease(p, 'text_running');
  if v_out = 'ok' then
    if v_spec is null or jsonb_typeof(v_spec) <> 'object' or v_spec::text ~* drinks_meme_foreign_pattern() then
      perform drinks_fail('invalid_input', '글 초안이 규칙에 맞지 않습니다');
    end if;
    update drink_meme_drafts set status = 'draft', spec = v_spec, sync_grade = v_spec ->> 'sync_grade', lease_token = null, lease_expires_at = null where id = d.id returning * into d;
  elsif v_out in ('stopped','failed') then
    update drink_meme_drafts set status = v_out, lease_token = null, lease_expires_at = null, error_code = left(drinks_text(p, 'error_code'), 60),
      error_message = left(drinks_text(p, 'error_message'), 2000) where id = d.id returning * into d;
  else
    perform drinks_fail('invalid_input', 'outcome 은 ok·stopped·failed 입니다');
  end if;
  perform drinks_meme_log(d.id, 'text_' || v_out, 'text_running', d.status, d.error_code, 'worker');
  return jsonb_build_object('draft_id', d.id, 'status', d.status, 'version', d.version);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 화면용 보기 · 권한
-- ─────────────────────────────────────────────────────────────

create or replace view drink_meme_board with (security_invoker = true) as
select d.id, d.card_id, d.topic_id, d.status, d.spec, d.sync_grade, d.evidence_review_id, d.approved_at, d.files, d.qa, d.safety, d.guide,
  d.error_code, d.error_message, d.external_url, d.version, d.created_at, d.updated_at,
  coalesce(c.name, t.title) as owner_name,
  drinks_meme_blockers(d.spec, d.evidence_review_id, d.card_id) as blockers
from drink_meme_drafts d
left join drink_ig_cards c on c.id = d.card_id
left join drink_topics t on t.id = d.topic_id;

alter table drink_meme_drafts enable row level security;
alter table drink_meme_events enable row level security;
revoke all on table drink_meme_drafts, drink_meme_events, drink_meme_board from anon, authenticated;
grant select, insert, update on table drink_meme_drafts, drink_meme_events to service_role;
grant select on table drink_meme_board to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname like 'drinks\_meme\_%'
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
  end loop;
end $$;
