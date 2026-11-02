-- 주류 공장 - 인스타 트렌드 보드·밈 보드 (2026-11-02). docs/deviation-drinks-ig-trend-board.md
-- 기획: docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md §6, 총괄 계획 §2·§4-3·§5.
--
-- 이 파일은 **파일만** 있다. 운영 적용은 운영자 결재 대상이다(기획 v2 §10-6).
-- 하는 일(전부 새 객체 - 기존 표·함수는 건드리지 않는다. 0059 의 drink_trend_* 는 다른 기능이다):
--   1) drink_ig_trend_runs        : 수집원별·날짜별 실행 상태 5종(ok·ok_empty·partial·failed·not_run). §6-2
--   2) drink_ig_token_checks      : 토큰 만료 기록(V-T1). 토큰 값은 어디에도 저장하지 않는다.
--   3) drink_ig_watch_accounts    : 관찰 계정(후보 → 운영자 체크 → 활성). 첫 관측일이 backfill 기준이다. §6-3·§6-8
--   4) drink_ig_audio·_observations : 인기 음원과 그날의 목록 자리. §6-4
--   5) drink_ig_media·_observations : 릴스 1건 1행(미디어 ID로 합침), 날짜별 마지막 값, 나이 구간. §6-3
--      ★ 남의 영상 파일·영상 주소를 넣을 칸이 없다. 남는 것은 링크·수치·표지 주소·캡션 첫 줄뿐이다(§6-7).
--      ★ view_count 는 없으면 null 이다. 0 으로 채우지 않는다(§6-3).
--   6) drink_ig_cards·_card_examples·_card_fields : 밈 카드, 예시, 필드별 근거+확신도. §6-5·§6-6
--      ★ 영상 전용 칸(비트 수·컷 길이·반전 시점·첫 1.5초·음악 동기화)은 근거가 video·operator 가 아니면 저장이 거부된다.
--   7) drink_ig_links             : 운영자 링크(T3). 서버는 이 주소를 열지 않는다 - 공식 API 로 그 계정을 찾아 맞춘다.
--   8) 워커 전용 함수·운영자 함수·보기 2개.
-- T4(Apify)는 상태 어휘 자리만 있다. 기록 함수가 받지 않고, 연결된 코드도 없다(§6-1 클릭 승인 미연결).
-- 권한: 0059 방향 그대로 - 공개 역할(anon·authenticated)은 표·보기·함수 모두 접근 불가, service_role 만.
-- 문턱 0.8·7·80 은 engine/config.py 의 DRINKS_IG_* 와 같아야 한다(tests/test_drinks_ig_trends.py 가 대조).
-- 영향: 추가만 한다. 기존 데이터 변화 없음.
-- 되돌리기:
--   drop view if exists drink_ig_board_cards, drink_ig_audio_latest;
--   do $$ declare f record; begin for f in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--     where n.nspname = 'public' and p.proname like 'drinks\_ig\_%' loop execute format('drop function %s', f.sig); end loop; end $$;
--   drop table if exists drink_ig_card_fields, drink_ig_card_examples, drink_ig_cards, drink_ig_links, drink_ig_media_observations,
--     drink_ig_media, drink_ig_audio_observations, drink_ig_audio, drink_ig_watch_accounts, drink_ig_token_checks, drink_ig_trend_runs;

-- ─────────────────────────────────────────────────────────────
-- 실행 상태 (수집원 × 날짜 한 줄)
-- ─────────────────────────────────────────────────────────────
create table if not exists drink_ig_trend_runs (
  source            text not null check (source in ('t1','t2','t3','t4')),   -- t4 는 자리만(기록 함수가 거부한다)
  observed_on       date not null,                                           -- config.TIMEZONE 기준 날짜
  status            text not null check (status in ('ok','ok_empty','partial','failed','not_run')),
  attempted         int  not null default 0 check (attempted >= 0),          -- t1=쪽 수, t2=계정 수, t3=링크 수
  succeeded         int  not null default 0 check (succeeded >= 0),
  items             int  not null default 0 check (items >= 0),              -- 받은 결과 수(음원·릴스)
  failure_reasons   jsonb not null default '{}'::jsonb,                      -- 실패 사유별 수 {"token_expired": 1}
  excluded_no_views int  check (excluded_no_views is null or excluded_no_views >= 0),   -- view_count 없어 판정에서 뺀 수(t2·t3)
  detail            jsonb not null default '{}'::jsonb,
  finished_at       timestamptz not null default now(),
  primary key (source, observed_on),
  constraint drink_ig_runs_counts_ck check (succeeded <= attempted),
  -- 상태와 숫자가 어긋나면 저장되지 않는다. "성공인데 0건"과 "실패"가 섞이지 않게.
  constraint drink_ig_runs_status_ck check (
    case status
      when 'ok'       then succeeded = attempted and items > 0
      when 'ok_empty' then succeeded = attempted and items = 0
      when 'partial'  then succeeded > 0 and succeeded < attempted
      when 'failed'   then succeeded = 0 and items = 0
      when 'not_run'  then attempted = 0 and succeeded = 0 and items = 0
    end)
);
create index if not exists drink_ig_runs_day_idx on drink_ig_trend_runs (observed_on desc);

create table if not exists drink_ig_token_checks (
  checked_on             date primary key,
  checked_at             timestamptz not null default now(),
  status                 text not null check (status in ('ok','expired','missing','unavailable')),
  expires_at             timestamptz,      -- null: 만료 없음 또는 못 읽음(status 로 구분)
  data_access_expires_at timestamptz,
  error_code             text check (error_code is null or length(error_code) <= 60)
);

-- ─────────────────────────────────────────────────────────────
-- 관찰 계정
-- ─────────────────────────────────────────────────────────────
create table if not exists drink_ig_watch_accounts (
  username          text primary key check (username ~ '^[a-z0-9._]{1,30}$'),
  status            text not null default 'candidate' check (status in ('candidate','active','paused')),
  kind              text not null default 'meme' check (kind in ('meme','drinks','explainer','other')),
  origin            text not null default 'operator' check (origin in ('doc_measured','operator')),
  note              text check (note is null or length(note) <= 500),
  first_observed_on date,                 -- 이번 활성화 이후 첫 성공 관측일. 이 날 처음 본 릴스가 backfill 이다.
  last_ok_on        date,
  last_error_code   text check (last_error_code is null or length(last_error_code) <= 60),
  last_error_on     date,
  followers_count   bigint check (followers_count is null or followers_count >= 0),
  activated_at      timestamptz,
  created_at        timestamptz not null default now()
);

-- 문서에 실측 기록이 있는 계정만 후보로 넣는다. 이름을 추측하지 않는다. 활성화는 운영자만 한다.
insert into drink_ig_watch_accounts (username, status, kind, origin, note) values
  ('9gag',         'candidate', 'meme',      'doc_measured', '공식 API 조회 확인, 인기 릴스 길이 가운데값 10초(검토_Apify §6 시험 2)'),
  ('pubity',       'candidate', 'meme',      'doc_measured', '공식 API 조회 확인, 가운데값 29초(검토_Apify §6 시험 2)'),
  ('memezar',      'candidate', 'meme',      'doc_measured', '공식 API 조회 확인, 가운데값 52초(검토_Apify §6 시험 2)'),
  ('daquan',       'candidate', 'meme',      'doc_measured', '공식 API 조회 확인, 가운데값 11초(검토_Apify §6 시험 2)'),
  ('ladbible',     'candidate', 'meme',      'doc_measured', '공식 API 조회 확인. Apify 는 연령 제한으로 6/6 막힘(검토_Apify §6 시험 2)'),
  ('masterofmalt', 'candidate', 'drinks',    'doc_measured', '공식 API 조회 확인(검토_Apify §1). 술 계정'),
  ('winefolly',    'candidate', 'drinks',    'doc_measured', '검토_Apify §0·§1 조사 대상. 술 계정'),
  ('vinepair',     'candidate', 'drinks',    'doc_measured', '검토_Apify §0·§1 조사 대상. 술 계정'),
  ('zackdfilms',   'candidate', 'explainer', 'doc_measured', '검토_Apify §1 조사 대상. 3D 도해 설명형 — 밈 계정 아님'),
  ('natgeo',       'candidate', 'explainer', 'doc_measured', '검토_Apify §2 공식 API 조회 기록. 설명형 — 밈 계정 아님')
on conflict (username) do nothing;

-- ─────────────────────────────────────────────────────────────
-- 음원 (T1)
-- ─────────────────────────────────────────────────────────────
create table if not exists drink_ig_audio (
  audio_id      text primary key check (length(audio_id) between 1 and 100),
  audio_type    text not null check (audio_type in ('music','original_sound')),
  title         text check (title is null or length(title) <= 300),
  display_artist text check (display_artist is null or length(display_artist) <= 300),
  ig_username   text check (ig_username is null or length(ig_username) <= 100),
  duration_ms   int check (duration_ms is null or duration_ms >= 0),
  preview_url   text check (preview_url is null or preview_url ~ '^https://'),   -- 만료될 수 있는 미리듣기 링크. 음원 파일은 받지 않는다.
  first_seen_on date not null,
  last_seen_on  date not null
);

create table if not exists drink_ig_audio_observations (
  audio_id      text not null references drink_ig_audio(audio_id) on delete cascade,
  observed_on   date not null,
  list_position int  not null check (list_position >= 1),   -- '인스타가 우리 계정에 준 추천 순서' 안의 자리 (§6-4)
  rising_reason text check (rising_reason is null or rising_reason in ('new','three_days')),
  primary key (audio_id, observed_on)
);
create index if not exists drink_ig_audio_obs_day_idx on drink_ig_audio_observations (observed_on desc);

-- ─────────────────────────────────────────────────────────────
-- 릴스 (T2·T3) - 미디어 ID 하나에 한 행, 날짜별 관측은 마지막 값만
-- ─────────────────────────────────────────────────────────────
create table if not exists drink_ig_media (
  media_id      text primary key check (length(media_id) between 1 and 100),
  username      text not null check (username ~ '^[a-z0-9._]{1,30}$'),
  permalink     text check (permalink is null or permalink ~ '^https://'),
  posted_at     timestamptz,
  caption_hook  text check (caption_hook is null or length(caption_hook) <= 200),   -- 캡션 첫 줄만. 캡션 전문은 저장하지 않는다.
  media_audio_type text check (media_audio_type is null or length(media_audio_type) <= 60),
  cover_url     text check (cover_url is null or cover_url ~ '^https://'),          -- 만료되는 표지 주소
  has_video_url boolean not null default false,   -- API 가 영상 주소를 줬는지만 기록한다. 주소 자체는 저장하지 않는다.
  is_backfill   boolean not null default false,   -- 관찰 계정을 추가한 날 처음 본 릴스. 새 예시 신호에 넣지 않는다(§6-3).
  sources       text[] not null default '{}',
  first_seen_on date not null,
  last_seen_on  date not null
);
create index if not exists drink_ig_media_user_idx on drink_ig_media (username);

create table if not exists drink_ig_media_observations (
  media_id        text not null references drink_ig_media(media_id) on delete cascade,
  observed_on     date not null,
  observed_at     timestamptz not null default now(),
  view_count      bigint check (view_count is null or view_count >= 0),      -- 없으면 null. 기본값·0 채움 금지.
  like_count      bigint check (like_count is null or like_count >= 0),
  comments_count  bigint check (comments_count is null or comments_count >= 0),
  age_hours       numeric,
  age_bucket      text check (age_bucket is null or age_bucket in ('h0_24','h24_72','d3_7','d7_plus')),
  baseline_views  numeric,
  view_multiple   numeric,
  trend_flag      text not null check (trend_flag in ('rising','normal','insufficient_sample','no_views','no_age')),
  primary key (media_id, observed_on)
);
create index if not exists drink_ig_media_obs_day_idx on drink_ig_media_observations (observed_on desc);

-- ─────────────────────────────────────────────────────────────
-- 밈 카드
-- ─────────────────────────────────────────────────────────────
create table if not exists drink_ig_cards (
  id                uuid primary key default gen_random_uuid(),
  merge_key         text not null unique check (length(merge_key) between 1 and 300),
  kind              text not null check (kind in ('audio','challenge','structure_hook','single_reel')),
  name              text not null check (length(name) between 1 and 300),
  audio_id          text,            -- 같은 음원이라도 구조가 다르면 다른 카드다. 연결은 이 값으로 표시한다(§6-6).
  challenge_name    text check (challenge_name is null or length(challenge_name) <= 300),
  structure         text check (structure is null or structure in ('pov','before_after','twist','list','reaction')),
  state             text not null default 'new' check (state in ('new','rising','peak','cooled')),
  first_seen_on     date not null,
  last_signal_on    date,
  last_evaluated_on date,            -- 이 날짜까지 수명을 셌다. 같은 날 다시 돌아도 두 번 세지 않는다.
  state_changed_on  date,
  quiet_normal_days int not null default 0 check (quiet_normal_days >= 0),   -- 정상 관측일만 센다
  increase_streak   int not null default 0 check (increase_streak >= 0),
  archived_on       date,            -- 식음 → 자동 보관
  decision          text check (decision is null or decision in ('use','pass','later')),
  decided_at        timestamptz,
  decision_note     text check (decision_note is null or length(decision_note) <= 500),
  created_at        timestamptz not null default now(),
  constraint drink_ig_cards_decision_ck check ((decision is null) = (decided_at is null)),
  constraint drink_ig_cards_archive_ck check (archived_on is null or state = 'cooled')
);
create index if not exists drink_ig_cards_state_idx on drink_ig_cards (state, first_seen_on desc);

create table if not exists drink_ig_card_examples (
  card_id         uuid not null references drink_ig_cards(id) on delete cascade,
  media_id        text not null references drink_ig_media(media_id) on delete cascade,
  added_on        date not null,
  origin          text not null check (origin in ('rising_reel','operator_link')),
  view_multiple   numeric,
  primary key (card_id, media_id),
  constraint drink_ig_card_examples_media_uq unique (media_id)    -- 릴스 하나는 카드 하나에만
);
create index if not exists drink_ig_card_examples_card_idx on drink_ig_card_examples (card_id, added_on);

-- §6-5: 값마다 근거와 확신도. 값이 없으면 행이 없다(= null).
create table if not exists drink_ig_card_fields (
  card_id    uuid not null references drink_ig_cards(id) on delete cascade,
  field      text not null check (field in ('structure','cover_text','caption_hook','audio_type',
                                            'beat_count','cut_lengths','twist_at','first_1_5s','music_sync')),
  value      text not null check (length(value) between 1 and 1000),
  evidence   text not null check (evidence in ('video','cover','caption','api_metrics','operator')),
  confidence text not null check (confidence in ('high','low')),
  set_at     timestamptz not null default now(),
  primary key (card_id, field),
  -- 표지·캡션으로는 알 수 없는 칸. 모델을 믿지 않고 저장에서 막는다.
  constraint drink_ig_card_fields_video_only_ck check (
    field not in ('beat_count','cut_lengths','twist_at','first_1_5s','music_sync') or evidence in ('video','operator'))
);

-- ─────────────────────────────────────────────────────────────
-- 운영자 링크 (T3)
-- ─────────────────────────────────────────────────────────────
create table if not exists drink_ig_links (
  id            uuid primary key default gen_random_uuid(),
  canonical_url text not null unique check (canonical_url ~ '^https://(www\.)?instagram\.com/'),
  shortcode     text not null check (shortcode ~ '^[A-Za-z0-9_-]{5,40}$'),
  username      text not null check (username ~ '^[a-z0-9._]{1,30}$'),
  note          text check (note is null or length(note) <= 500),
  status        text not null default 'pending' check (status in ('pending','resolved','not_found','account_unavailable','failed')),
  attempts      int not null default 0 check (attempts >= 0),
  media_id      text references drink_ig_media(media_id) on delete set null,
  error_code    text check (error_code is null or length(error_code) <= 60),
  created_at    timestamptz not null default now(),
  resolved_on   date
);
create index if not exists drink_ig_links_status_idx on drink_ig_links (status, created_at);

-- ─────────────────────────────────────────────────────────────
-- 공용 계산
-- ─────────────────────────────────────────────────────────────

-- 정상 관측일(§6-2) = T1 이 ok 이고, T2 계정 성공률이 80% 이상인 날. 활성 계정이 0개면 성공률을 말할 수 없어 정상이 아니다.
create or replace function drinks_ig_is_normal_day(d date) returns boolean
language sql stable set search_path = public, pg_temp as $$
  select coalesce((select status = 'ok' from drink_ig_trend_runs where source = 't1' and observed_on = d), false)
     and coalesce((select attempted > 0 and succeeded::numeric / attempted >= 0.8
                   from drink_ig_trend_runs where source = 't2' and observed_on = d), false)
$$;

-- 정밀 틀 승격(§6-5): 비트 수·컷 길이·반전 시점이 video 근거 또는 운영자 입력으로 다 채워졌을 때만. 나머지는 참고 카드다.
create or replace function drinks_ig_card_precision(c uuid) returns text
language sql stable set search_path = public, pg_temp as $$
  select case when (select count(*) from drink_ig_card_fields f
                    where f.card_id = c and f.field in ('beat_count','cut_lengths','twist_at') and f.evidence in ('video','operator')) = 3
              then 'precise' else 'reference' end
$$;

create or replace function drinks_ig_bigint(p jsonb, k text) returns bigint
language plpgsql set search_path = public, pg_temp as $$
declare v text := nullif(btrim(p ->> k), '');
begin
  if v is null then return null; end if;   -- 없으면 null 그대로. 0 으로 바꾸지 않는다.
  if v !~ '^[0-9]{1,18}$' then perform drinks_fail('invalid_input', k || ' 는 0 이상의 정수여야 합니다'); end if;
  return v::bigint;
end $$;

create or replace function drinks_ig_day(p jsonb) returns date
language plpgsql set search_path = public, pg_temp as $$
declare d date := drinks_date(p, 'observed_on');
begin
  if d is null then perform drinks_fail('invalid_input', 'observed_on 이 필요합니다'); end if;
  return d;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 전용 함수
-- ─────────────────────────────────────────────────────────────

-- 실행 기록. not_run 은 빈 날짜 채우기라 이미 있는 기록을 덮지 않는다. 나머지는 같은 날 다시 돌면 마지막 값으로 바뀐다.
create or replace function drinks_ig_record_run(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_source text := drinks_text(p, 'source'); v_status text := drinks_text(p, 'status'); v_day date := drinks_ig_day(p);
  v_att int := coalesce(drinks_int(p, 'attempted', false), 0); v_suc int := coalesce(drinks_int(p, 'succeeded', false), 0);
  v_items int := coalesce(drinks_int(p, 'items', false), 0); v_excl int := drinks_int(p, 'excluded_no_views', false);
  v_reasons jsonb := coalesce(p -> 'failure_reasons', '{}'::jsonb); v_detail jsonb := coalesce(p -> 'detail', '{}'::jsonb);
  v_written int;
begin
  if v_source is null or v_source not in ('t1','t2','t3') then
    perform drinks_fail('invalid_input', 'source 는 t1·t2·t3 중 하나입니다(t4 는 연결되지 않았습니다)');
  end if;
  if v_status is null or v_status not in ('ok','ok_empty','partial','failed','not_run') then
    perform drinks_fail('invalid_input', 'status 가 잘못됐습니다');
  end if;
  if jsonb_typeof(v_reasons) <> 'object' or jsonb_typeof(v_detail) <> 'object' then
    perform drinks_fail('invalid_input', 'failure_reasons·detail 은 객체여야 합니다');
  end if;
  begin
    if v_status = 'not_run' then
      insert into drink_ig_trend_runs (source, observed_on, status) values (v_source, v_day, 'not_run')
        on conflict (source, observed_on) do nothing;
    else
      insert into drink_ig_trend_runs (source, observed_on, status, attempted, succeeded, items, failure_reasons, excluded_no_views, detail, finished_at)
      values (v_source, v_day, v_status, v_att, v_suc, v_items, v_reasons, v_excl, v_detail, now())
      on conflict (source, observed_on) do update set status = excluded.status, attempted = excluded.attempted, succeeded = excluded.succeeded,
        items = excluded.items, failure_reasons = excluded.failure_reasons, excluded_no_views = excluded.excluded_no_views,
        detail = excluded.detail, finished_at = now();
    end if;
  exception when check_violation then
    perform drinks_fail('invalid_input', '상태와 숫자가 맞지 않습니다');
  end;
  get diagnostics v_written = row_count;
  return jsonb_build_object('written', v_written > 0, 'normal_day', drinks_ig_is_normal_day(v_day));
end $$;

create or replace function drinks_ig_record_token_check(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare v_day date := drinks_ig_day(p); v_status text := drinks_text(p, 'status'); v_exp timestamptz; v_data timestamptz;
begin
  if v_status is null or v_status not in ('ok','expired','missing','unavailable') then
    perform drinks_fail('invalid_input', 'status 가 잘못됐습니다');
  end if;
  begin
    v_exp := nullif(btrim(p ->> 'expires_at'), '')::timestamptz;
    v_data := nullif(btrim(p ->> 'data_access_expires_at'), '')::timestamptz;
  exception when others then
    perform drinks_fail('invalid_input', '만료 시각 형식이 잘못됐습니다');
  end;
  insert into drink_ig_token_checks (checked_on, checked_at, status, expires_at, data_access_expires_at, error_code)
  values (v_day, now(), v_status, v_exp, v_data, left(drinks_text(p, 'error_code'), 60))
  on conflict (checked_on) do update set checked_at = now(), status = excluded.status, expires_at = excluded.expires_at,
    data_access_expires_at = excluded.data_access_expires_at, error_code = excluded.error_code;
  return jsonb_build_object('checked_on', v_day, 'status', v_status);
end $$;

-- 워커가 하루 시작에 읽는 것. 한 행(jsonb)이라 PostgREST 1,000행 상한에 잘리지 않는다.
create or replace function drinks_ig_worker_state(p jsonb) returns jsonb
language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'accounts', coalesce((select jsonb_agg(jsonb_build_object('username', a.username, 'first_observed_on', a.first_observed_on) order by a.username)
      from drink_ig_watch_accounts a where a.status = 'active'), '[]'::jsonb),
    'last_run_on', (select max(r.observed_on) from drink_ig_trend_runs r where r.source in ('t1','t2','t3')),
    'runs', coalesce((select jsonb_agg(jsonb_build_object('source', r.source, 'observed_on', r.observed_on, 'status', r.status,
        'attempted', r.attempted, 'succeeded', r.succeeded) order by r.observed_on, r.source)
      from drink_ig_trend_runs r where r.observed_on >= current_date - 60 and r.source in ('t1','t2','t3')), '[]'::jsonb),
    'audio_first_seen', coalesce((select jsonb_object_agg(au.audio_id, au.first_seen_on) from drink_ig_audio au), '{}'::jsonb),
    'audio_recent', coalesce((select jsonb_agg(jsonb_build_object('audio_id', o.audio_id, 'observed_on', o.observed_on))
      from drink_ig_audio_observations o where o.observed_on >= current_date - 14), '[]'::jsonb),
    'pending_links', coalesce((select jsonb_agg(jsonb_build_object('link_id', l.id, 'shortcode', l.shortcode, 'username', l.username, 'attempts', l.attempts) order by l.created_at, l.id)
      from (select * from drink_ig_links where status = 'pending' order by created_at, id
            limit least(greatest(coalesce(drinks_int(p, 'link_limit', false), 20), 1), 200)) l), '[]'::jsonb),
    -- 찾았지만 아직 카드에 안 붙은 운영자 링크. 카드는 정상 관측일에만 만들기 때문에 다음 정상일에 붙는다.
    'unattached_links', coalesce((select jsonb_agg(jsonb_build_object('link_id', l.id, 'media_id', l.media_id, 'username', m.username,
        'caption_hook', m.caption_hook) order by l.created_at, l.id)
      from drink_ig_links l join drink_ig_media m on m.media_id = l.media_id
      where l.status = 'resolved' and not exists (select 1 from drink_ig_card_examples e where e.media_id = l.media_id)), '[]'::jsonb),
    'cards', coalesce((select jsonb_agg(jsonb_build_object('card_id', c.id, 'merge_key', c.merge_key, 'kind', c.kind, 'state', c.state,
        'first_seen_on', c.first_seen_on, 'last_evaluated_on', c.last_evaluated_on, 'quiet_normal_days', c.quiet_normal_days,
        'increase_streak', c.increase_streak, 'audio_id', c.audio_id, 'structure', c.structure,
        'caption_hook', (select f.value from drink_ig_card_fields f where f.card_id = c.id and f.field = 'caption_hook'),
        'examples_today', (select count(*) from drink_ig_card_examples e where e.card_id = c.id and e.added_on = drinks_date(p, 'observed_on'))) order by c.id)
      from drink_ig_cards c), '[]'::jsonb),
    'attached_media', coalesce((select jsonb_agg(e.media_id) from drink_ig_card_examples e), '[]'::jsonb))
$$;

-- 음원 관측 한 묶음(같은 트랜잭션). 같은 날 다시 오면 마지막 값.
create or replace function drinks_ig_record_audio(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare v_day date := drinks_ig_day(p); it jsonb; n int := 0; v_id text; v_preview text;
begin
  if jsonb_typeof(p -> 'items') <> 'array' then perform drinks_fail('invalid_input', 'items 는 배열이어야 합니다'); end if;
  for it in select * from jsonb_array_elements(p -> 'items') loop
    v_id := drinks_text(it, 'audio_id');
    if v_id is null then perform drinks_fail('invalid_input', 'audio_id 가 필요합니다'); end if;
    v_preview := drinks_text(it, 'preview_url');
    if v_preview is not null and v_preview !~ '^https://' then v_preview := null; end if;
    begin
      insert into drink_ig_audio (audio_id, audio_type, title, display_artist, ig_username, duration_ms, preview_url, first_seen_on, last_seen_on)
      values (v_id, drinks_text(it, 'audio_type'), left(drinks_text(it, 'title'), 300), left(drinks_text(it, 'display_artist'), 300),
        left(drinks_text(it, 'ig_username'), 100), drinks_int(it, 'duration_ms', false), v_preview, v_day, v_day)
      on conflict (audio_id) do update set title = coalesce(excluded.title, drink_ig_audio.title),
        display_artist = coalesce(excluded.display_artist, drink_ig_audio.display_artist),
        ig_username = coalesce(excluded.ig_username, drink_ig_audio.ig_username),
        duration_ms = coalesce(excluded.duration_ms, drink_ig_audio.duration_ms),
        preview_url = coalesce(excluded.preview_url, drink_ig_audio.preview_url),
        first_seen_on = least(drink_ig_audio.first_seen_on, excluded.first_seen_on),
        last_seen_on = greatest(drink_ig_audio.last_seen_on, excluded.last_seen_on);
      insert into drink_ig_audio_observations (audio_id, observed_on, list_position, rising_reason)
      values (v_id, v_day, drinks_int(it, 'list_position'), drinks_text(it, 'rising_reason'))
      on conflict (audio_id, observed_on) do update set list_position = excluded.list_position, rising_reason = excluded.rising_reason;
    exception when check_violation or not_null_violation then
      perform drinks_fail('invalid_input', '음원 값이 잘못됐습니다');
    end;
    n := n + 1;
  end loop;
  return jsonb_build_object('recorded', n);
end $$;

-- 기준선용 과거 관측: 계정·나이 구간별로 릴스 1건 1값(그 구간의 가장 최근 값). 조회수 없는 관측은 뺀다.
create or replace function drinks_ig_baseline_rows(p jsonb) returns jsonb
language sql stable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(jsonb_build_object('username', x.username, 'media_id', x.media_id, 'age_bucket', x.age_bucket, 'view_count', x.view_count)), '[]'::jsonb)
  from (
    select distinct on (o.media_id, o.age_bucket) m.username, o.media_id, o.age_bucket, o.view_count
    from drink_ig_media_observations o join drink_ig_media m on m.media_id = o.media_id
    where o.view_count is not null and o.age_bucket is not null
      and o.observed_on >= coalesce(drinks_date(p, 'since'), current_date - 60)
      and m.username = any(drinks_text_array(p -> 'usernames'))
    order by o.media_id, o.age_bucket, o.observed_on desc
  ) x
$$;

-- 한 계정(또는 링크)의 릴스 관측 묶음. is_backfill 은 처음 적힌 값을 지킨다.
create or replace function drinks_ig_record_media(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_day date := drinks_ig_day(p); v_user text := lower(drinks_text(p, 'username')); v_source text := drinks_text(p, 'source');
  it jsonb; n int := 0; v_id text; v_posted timestamptz; v_perma text; v_cover text;
begin
  if v_user is null or v_user !~ '^[a-z0-9._]{1,30}$' then perform drinks_fail('invalid_input', 'username 이 잘못됐습니다'); end if;
  if v_source is null or v_source not in ('t2','t3') then perform drinks_fail('invalid_input', 'source 는 t2·t3 중 하나입니다'); end if;
  if jsonb_typeof(p -> 'items') <> 'array' then perform drinks_fail('invalid_input', 'items 는 배열이어야 합니다'); end if;
  for it in select * from jsonb_array_elements(p -> 'items') loop
    v_id := drinks_text(it, 'media_id');
    if v_id is null then perform drinks_fail('invalid_input', 'media_id 가 필요합니다'); end if;
    begin
      v_posted := nullif(btrim(it ->> 'posted_at'), '')::timestamptz;
    exception when others then
      perform drinks_fail('invalid_input', 'posted_at 형식이 잘못됐습니다');
    end;
    v_perma := drinks_text(it, 'permalink');
    if v_perma is not null and v_perma !~ '^https://' then v_perma := null; end if;
    v_cover := drinks_text(it, 'cover_url');
    if v_cover is not null and v_cover !~ '^https://' then v_cover := null; end if;
    begin
      insert into drink_ig_media (media_id, username, permalink, posted_at, caption_hook, media_audio_type, cover_url, has_video_url, is_backfill, sources, first_seen_on, last_seen_on)
      values (v_id, v_user, v_perma, v_posted, left(drinks_text(it, 'caption_hook'), 200), left(drinks_text(it, 'media_audio_type'), 60), v_cover,
        coalesce((it ->> 'has_video_url')::boolean, false), coalesce((it ->> 'is_backfill')::boolean, false), array[v_source], v_day, v_day)
      on conflict (media_id) do update set permalink = coalesce(excluded.permalink, drink_ig_media.permalink),
        posted_at = coalesce(excluded.posted_at, drink_ig_media.posted_at),
        caption_hook = coalesce(excluded.caption_hook, drink_ig_media.caption_hook),
        media_audio_type = coalesce(excluded.media_audio_type, drink_ig_media.media_audio_type),
        cover_url = coalesce(excluded.cover_url, drink_ig_media.cover_url),
        has_video_url = drink_ig_media.has_video_url or excluded.has_video_url,
        sources = (select array_agg(distinct s order by s) from unnest(drink_ig_media.sources || excluded.sources) s),
        first_seen_on = least(drink_ig_media.first_seen_on, excluded.first_seen_on),
        last_seen_on = greatest(drink_ig_media.last_seen_on, excluded.last_seen_on);
      -- 같은 날 같은 릴스는 마지막 값만. 뒤 값의 조회수가 없으면 null 로 남는다(앞 값을 끌어 쓰지 않는다).
      insert into drink_ig_media_observations (media_id, observed_on, observed_at, view_count, like_count, comments_count, age_hours, age_bucket, baseline_views, view_multiple, trend_flag)
      values (v_id, v_day, now(), drinks_ig_bigint(it, 'view_count'), drinks_ig_bigint(it, 'like_count'), drinks_ig_bigint(it, 'comments_count'),
        nullif(btrim(it ->> 'age_hours'), '')::numeric, drinks_text(it, 'age_bucket'),
        nullif(btrim(it ->> 'baseline_views'), '')::numeric, nullif(btrim(it ->> 'view_multiple'), '')::numeric, drinks_text(it, 'trend_flag'))
      on conflict (media_id, observed_on) do update set observed_at = now(), view_count = excluded.view_count, like_count = excluded.like_count,
        comments_count = excluded.comments_count, age_hours = excluded.age_hours, age_bucket = excluded.age_bucket,
        baseline_views = excluded.baseline_views, view_multiple = excluded.view_multiple, trend_flag = excluded.trend_flag;
    exception when check_violation or not_null_violation or invalid_text_representation then
      perform drinks_fail('invalid_input', '릴스 값이 잘못됐습니다');
    end;
    n := n + 1;
  end loop;
  return jsonb_build_object('recorded', n);
end $$;

-- 계정 관측 결과. 첫 성공 날짜를 남긴다(backfill 기준). 목록에 없는 계정(T3)은 아무 일도 없다.
create or replace function drinks_ig_mark_account(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare v_day date := drinks_ig_day(p); v_user text := lower(drinks_text(p, 'username')); v_ok boolean := coalesce((p ->> 'ok')::boolean, false); v_n int;
begin
  if v_user is null then perform drinks_fail('invalid_input', 'username 이 필요합니다'); end if;
  if v_ok then
    update drink_ig_watch_accounts set first_observed_on = coalesce(first_observed_on, v_day), last_ok_on = v_day,
      last_error_code = null, last_error_on = null, followers_count = coalesce(drinks_ig_bigint(p, 'followers_count'), followers_count)
      where username = v_user;
  else
    update drink_ig_watch_accounts set last_error_code = left(drinks_text(p, 'error_code'), 60), last_error_on = v_day where username = v_user;
  end if;
  get diagnostics v_n = row_count;
  return jsonb_build_object('updated', v_n > 0);
end $$;

create or replace function drinks_ig_finish_link(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare v_id uuid := drinks_uuid(p, 'link_id'); v_status text := drinks_text(p, 'status'); v_n int;
begin
  if v_status is null or v_status not in ('pending','resolved','not_found','account_unavailable','failed') then
    perform drinks_fail('invalid_input', 'status 가 잘못됐습니다');
  end if;
  update drink_ig_links set status = v_status, attempts = attempts + 1, media_id = coalesce(drinks_text(p, 'media_id'), media_id),
    error_code = left(drinks_text(p, 'error_code'), 60), resolved_on = case when v_status = 'pending' then resolved_on else drinks_date(p, 'observed_on') end
    where id = v_id;
  get diagnostics v_n = row_count;
  if v_n = 0 then perform drinks_fail('not_found', '링크를 찾지 못했습니다'); end if;
  return jsonb_build_object('link_id', v_id, 'status', v_status);
end $$;

-- 카드 만들기·예시 붙이기. ★ 정상 관측일이 아니면 거부한다 - 실패한 날에 카드가 바뀌지 않게 DB 가 막는다(§6-6).
-- 돌려주는 수는 '그날 붙은 예시'로 센다. 도중에 죽고 다시 돌아도 신호가 사라지지 않게.
create or replace function drinks_ig_upsert_card(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_day date := drinks_ig_day(p); v_key text := drinks_text(p, 'merge_key'); v_id uuid; v_created boolean := false; it jsonb;
  v_new_ex int; v_new_acc int;
begin
  if v_key is null then perform drinks_fail('invalid_input', 'merge_key 가 필요합니다'); end if;
  if not drinks_ig_is_normal_day(v_day) then
    perform drinks_fail('not_normal_day', '정상 관측일이 아니라 카드를 바꾸지 않습니다');
  end if;
  begin
    insert into drink_ig_cards (merge_key, kind, name, audio_id, challenge_name, structure, first_seen_on, last_signal_on)
    values (v_key, drinks_text(p, 'kind'), left(drinks_text(p, 'name'), 300), drinks_text(p, 'audio_id'), left(drinks_text(p, 'challenge_name'), 300),
      drinks_text(p, 'structure'), v_day, v_day)
    on conflict (merge_key) do nothing returning id into v_id;
    v_created := v_id is not null;
    if not v_created then select id into v_id from drink_ig_cards where merge_key = v_key; end if;
    for it in select * from jsonb_array_elements(coalesce(p -> 'examples', '[]'::jsonb)) loop
      insert into drink_ig_card_examples (card_id, media_id, added_on, origin, view_multiple)
      values (v_id, drinks_text(it, 'media_id'), v_day, drinks_text(it, 'origin'), nullif(btrim(it ->> 'view_multiple'), '')::numeric)
      on conflict do nothing;
    end loop;
    -- 값이 없는 칸은 행을 만들지 않는다(= null). 운영자가 직접 넣은 값은 덮지 않는다.
    for it in select * from jsonb_array_elements(coalesce(p -> 'fields', '[]'::jsonb)) loop
      insert into drink_ig_card_fields (card_id, field, value, evidence, confidence)
      values (v_id, drinks_text(it, 'field'), left(drinks_text(it, 'value'), 1000), drinks_text(it, 'evidence'), drinks_text(it, 'confidence'))
      on conflict (card_id, field) do update set value = excluded.value, evidence = excluded.evidence, confidence = excluded.confidence, set_at = now()
        where drink_ig_card_fields.evidence <> 'operator';
    end loop;
  exception when check_violation or not_null_violation or foreign_key_violation then
    perform drinks_fail('invalid_input', '카드 값이 잘못됐습니다');
  end;
  select count(*) into v_new_ex from drink_ig_card_examples where card_id = v_id and added_on = v_day;
  select count(distinct m.username) into v_new_acc
    from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id
    where e.card_id = v_id and e.added_on = v_day
      and not exists (select 1 from drink_ig_card_examples e2 join drink_ig_media m2 on m2.media_id = e2.media_id
                      where e2.card_id = v_id and e2.added_on < v_day and m2.username = m.username);
  if v_new_ex > 0 then update drink_ig_cards set last_signal_on = v_day where id = v_id; end if;
  return jsonb_build_object('card_id', v_id, 'created', v_created, 'new_examples', v_new_ex, 'new_accounts', v_new_acc);
end $$;

-- 수명 반영 한 묶음(같은 트랜잭션). ★ 정상 관측일이 아니면 통째로 거부한다. 이미 센 날은 건너뛴다(같은 날 재실행).
create or replace function drinks_ig_apply_lifecycle(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_day date := drinks_ig_day(p); it jsonb; v_state text; v_quiet int; v_streak int; v_applied int := 0; v_skipped int := 0; v_n int;
begin
  if not drinks_ig_is_normal_day(v_day) then
    perform drinks_fail('not_normal_day', '정상 관측일이 아니라 수명을 세지 않습니다');
  end if;
  for it in select * from jsonb_array_elements(coalesce(p -> 'cards', '[]'::jsonb)) loop
    v_state := drinks_text(it, 'state');
    v_quiet := coalesce(drinks_int(it, 'quiet_normal_days', false), 0);
    v_streak := coalesce(drinks_int(it, 'increase_streak', false), 0);
    if v_state is null or v_state not in ('new','rising','peak','cooled') then perform drinks_fail('invalid_input', 'state 가 잘못됐습니다'); end if;
    if v_state = 'cooled' and v_quiet < 7 then
      perform drinks_fail('invalid_input', '정상 관측일 7일 동안 새 예시가 없어야 식음입니다');
    end if;
    update drink_ig_cards c set
      state_changed_on = case when c.state <> v_state then v_day else c.state_changed_on end,
      state = v_state, quiet_normal_days = v_quiet, increase_streak = v_streak, last_evaluated_on = v_day,
      archived_on = case when v_state = 'cooled' then coalesce(c.archived_on, v_day) else null end
      where c.id = drinks_uuid(it, 'card_id') and (c.last_evaluated_on is null or c.last_evaluated_on < v_day);
    get diagnostics v_n = row_count;
    if v_n > 0 then v_applied := v_applied + 1; else v_skipped := v_skipped + 1; end if;
  end loop;
  return jsonb_build_object('applied', v_applied, 'skipped', v_skipped);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 운영자 함수 (POST /api/drinks 운영자 게이트 뒤에서만 불린다)
-- ─────────────────────────────────────────────────────────────

-- 관찰 계정: add(후보로 넣기) / activate(체크) / pause(빼기). 다시 켜면 그날 처음 본 릴스를 다시 backfill 로 본다.
create or replace function drinks_ig_watch_action(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_user text := lower(ltrim(coalesce(drinks_text(p, 'username'), ''), '@')); v_action text := drinks_text(p, 'action');
  v_kind text := coalesce(drinks_text(p, 'kind'), 'meme'); v_n int; v_status text;
begin
  if v_user !~ '^[a-z0-9._]{1,30}$' then perform drinks_fail('invalid_input', '인스타 계정 이름이 잘못됐습니다'); end if;
  if v_action = 'add' then
    if v_kind not in ('meme','drinks','explainer','other') then perform drinks_fail('invalid_input', '계정 종류가 잘못됐습니다'); end if;
    insert into drink_ig_watch_accounts (username, status, kind, origin, note)
    values (v_user, 'candidate', v_kind, 'operator', left(drinks_text(p, 'note'), 500))
    on conflict (username) do nothing;
  elsif v_action = 'activate' then
    if (select count(*) from drink_ig_watch_accounts where status = 'active' and username <> v_user) >= 80 then
      perform drinks_fail('active_limit', '관찰 계정은 80개까지입니다');
    end if;
    update drink_ig_watch_accounts set status = 'active', activated_at = now(),
      first_observed_on = case when status = 'active' then first_observed_on else null end
      where username = v_user;
    get diagnostics v_n = row_count;
    if v_n = 0 then perform drinks_fail('not_found', '목록에 없는 계정입니다 - 먼저 후보로 넣으세요'); end if;
  elsif v_action = 'pause' then
    update drink_ig_watch_accounts set status = 'paused' where username = v_user;
    get diagnostics v_n = row_count;
    if v_n = 0 then perform drinks_fail('not_found', '목록에 없는 계정입니다'); end if;
  else
    perform drinks_fail('invalid_input', 'action 은 add·activate·pause 중 하나입니다');
  end if;
  select status into v_status from drink_ig_watch_accounts where username = v_user;
  return jsonb_build_object('username', v_user, 'status', v_status);
end $$;

-- 운영자 링크(T3). 서버는 이 주소를 열지 않는다. 같은 주소는 한 건.
create or replace function drinks_ig_add_link(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_url text := drinks_text(p, 'canonical_url'); v_code text := drinks_text(p, 'shortcode');
  v_user text := lower(ltrim(coalesce(drinks_text(p, 'username'), ''), '@')); v_id uuid; v_existing boolean := false;
begin
  if v_url is null or v_url !~ '^https://(www\.)?instagram\.com/' then perform drinks_fail('invalid_input', '인스타그램 릴스 주소를 넣으세요'); end if;
  if v_code is null or v_code !~ '^[A-Za-z0-9_-]{5,40}$' then perform drinks_fail('invalid_input', '릴스 주소에서 릴스 코드를 찾지 못했습니다'); end if;
  if v_user !~ '^[a-z0-9._]{1,30}$' then perform drinks_fail('invalid_input', '계정 이름을 적으세요(주소에 없는 경우가 많습니다)'); end if;
  insert into drink_ig_links (canonical_url, shortcode, username, note)
  values (v_url, v_code, v_user, left(drinks_text(p, 'note'), 500))
  on conflict (canonical_url) do nothing returning id into v_id;
  if v_id is null then
    v_existing := true;
    select id into v_id from drink_ig_links where canonical_url = v_url;
  end if;
  return jsonb_build_object('link_id', v_id, 'existing', v_existing);
end $$;

-- [쓰자]/[넘기기]/[나중에]. ★ 결정만 기록한다. 분석·구매·발행을 시작하는 길이 없다.
create or replace function drinks_ig_card_decide(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare v_id uuid := drinks_uuid(p, 'card_id'); v_decision text := drinks_text(p, 'decision'); v_n int;
begin
  if v_decision is null or v_decision not in ('use','pass','later') then
    perform drinks_fail('invalid_input', 'decision 은 use·pass·later 중 하나입니다');
  end if;
  update drink_ig_cards set decision = v_decision, decided_at = now(), decision_note = left(drinks_text(p, 'note'), 500) where id = v_id;
  get diagnostics v_n = row_count;
  if v_n = 0 then perform drinks_fail('not_found', '카드를 찾지 못했습니다'); end if;
  return jsonb_build_object('card_id', v_id, 'decision', v_decision, 'precision', drinks_ig_card_precision(v_id));
end $$;

-- 운영자가 원본 릴스를 보고 칸을 직접 채운다(§6-5 정밀 틀 승격의 두 번째 길). 값을 비우면 지운다.
create or replace function drinks_ig_set_card_field(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare v_id uuid := drinks_uuid(p, 'card_id'); v_field text := drinks_text(p, 'field'); v_value text := left(drinks_text(p, 'value'), 1000);
begin
  if not exists (select 1 from drink_ig_cards where id = v_id) then perform drinks_fail('not_found', '카드를 찾지 못했습니다'); end if;
  if v_field is null or v_field not in ('structure','cover_text','caption_hook','audio_type','beat_count','cut_lengths','twist_at','first_1_5s','music_sync') then
    perform drinks_fail('invalid_input', '없는 칸입니다');
  end if;
  if v_field = 'structure' and v_value is not null and v_value not in ('pov','before_after','twist','list','reaction') then
    perform drinks_fail('invalid_input', '구조는 POV·전후·반전·리스트·반응 중 하나입니다');
  end if;
  if v_value is null then
    delete from drink_ig_card_fields where card_id = v_id and field = v_field;
  else
    insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values (v_id, v_field, v_value, 'operator', 'high')
    on conflict (card_id, field) do update set value = excluded.value, evidence = 'operator', confidence = 'high', set_at = now();
  end if;
  if v_field = 'structure' then update drink_ig_cards set structure = v_value where id = v_id; end if;
  return jsonb_build_object('card_id', v_id, 'field', v_field, 'precision', drinks_ig_card_precision(v_id));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 읽기 보기
-- ─────────────────────────────────────────────────────────────

-- 가장 최근에 관측한 날의 음원 목록. 자리는 그 날 '인스타가 우리 계정에 준 추천 순서' 안의 자리다.
create or replace view drink_ig_audio_latest with (security_invoker = true) as
select a.audio_id, a.audio_type, a.title, a.display_artist, a.ig_username, a.duration_ms, a.preview_url, a.first_seen_on,
  o.observed_on, o.list_position, o.rising_reason
from drink_ig_audio_observations o join drink_ig_audio a on a.audio_id = o.audio_id
where o.observed_on = (select max(observed_on) from drink_ig_audio_observations);

create or replace view drink_ig_board_cards with (security_invoker = true) as
select c.id, c.merge_key, c.kind, c.name, c.audio_id, c.challenge_name, c.structure, c.state, c.first_seen_on, c.last_signal_on,
  c.last_evaluated_on, c.state_changed_on, c.quiet_normal_days, c.increase_streak, c.archived_on, c.decision, c.decided_at, c.decision_note,
  drinks_ig_card_precision(c.id) as precision,
  (select count(*) from drink_ig_card_examples e where e.card_id = c.id) as examples_count,
  (select count(distinct m.username) from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id where e.card_id = c.id) as accounts_count,
  (select max(e.view_multiple) from drink_ig_card_examples e where e.card_id = c.id) as max_multiple,
  -- 같은 음원을 쓰는 다른 카드 수(연결 표시만, §6-6)
  (select count(*) from drink_ig_cards c2 where c2.audio_id = c.audio_id and c2.id <> c.id) as same_audio_cards,
  coalesce((select jsonb_agg(x order by (x ->> 'view_count')::bigint desc nulls last) from (
     select jsonb_build_object('media_id', e.media_id, 'username', m.username, 'permalink', m.permalink, 'origin', e.origin,
       'view_multiple', e.view_multiple, 'hook', m.caption_hook,
       'view_count', (select o.view_count from drink_ig_media_observations o where o.media_id = e.media_id order by o.observed_on desc limit 1)) as x
     from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id
     where e.card_id = c.id
     order by (select o.view_count from drink_ig_media_observations o where o.media_id = e.media_id order by o.observed_on desc limit 1) desc nulls last, e.media_id
     limit 3) t), '[]'::jsonb) as examples,
  coalesce((select jsonb_object_agg(f.field, jsonb_build_object('value', f.value, 'evidence', f.evidence, 'confidence', f.confidence))
     from drink_ig_card_fields f where f.card_id = c.id), '{}'::jsonb) as fields,
  (select o.list_position from drink_ig_audio_observations o where o.audio_id = c.audio_id order by o.observed_on desc limit 1) as audio_position,
  (select o.observed_on from drink_ig_audio_observations o where o.audio_id = c.audio_id order by o.observed_on desc limit 1) as audio_position_on
from drink_ig_cards c;

-- ─────────────────────────────────────────────────────────────
-- 권한 - 0059 방향 그대로. 공개 역할 접근 없음, 정책 없음(RLS 전면 차단), service_role 만
-- ─────────────────────────────────────────────────────────────
alter table drink_ig_trend_runs enable row level security;
alter table drink_ig_token_checks enable row level security;
alter table drink_ig_watch_accounts enable row level security;
alter table drink_ig_audio enable row level security;
alter table drink_ig_audio_observations enable row level security;
alter table drink_ig_media enable row level security;
alter table drink_ig_media_observations enable row level security;
alter table drink_ig_cards enable row level security;
alter table drink_ig_card_examples enable row level security;
alter table drink_ig_card_fields enable row level security;
alter table drink_ig_links enable row level security;

revoke all on table drink_ig_trend_runs, drink_ig_token_checks, drink_ig_watch_accounts, drink_ig_audio, drink_ig_audio_observations,
  drink_ig_media, drink_ig_media_observations, drink_ig_cards, drink_ig_card_examples, drink_ig_card_fields, drink_ig_links,
  drink_ig_audio_latest, drink_ig_board_cards from anon, authenticated;
grant select, insert, update on table drink_ig_trend_runs, drink_ig_token_checks, drink_ig_watch_accounts, drink_ig_audio, drink_ig_audio_observations,
  drink_ig_media, drink_ig_media_observations, drink_ig_cards, drink_ig_card_examples, drink_ig_links to service_role;
grant select, insert, update, delete on table drink_ig_card_fields to service_role;
grant select on table drink_ig_audio_latest, drink_ig_board_cards to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname like 'drinks\_ig\_%'
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
  end loop;
end $$;
