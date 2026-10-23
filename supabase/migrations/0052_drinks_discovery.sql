-- 주류 공장 B 보완 — 커뮤니티·SNS 소재 발견(2026-10-22). docs/deviation-drinks-discovery.md
--
-- 0051(B단계) 위에 쌓는다. "소재 발견 자료"는 **사실 근거가 아니다** — 사람들이 무엇을 궁금해하는지의 신호다.
-- 그래서 출처 스냅샷(drink_source_snapshots, 근거용)과 다른 표에 둔다. 소재로 올릴 때만 스냅샷(URL만, metadata_only)으로
-- 연결되고, A단계 규칙상 metadata_only 는 근거가 될 수 없다(승인 차단). 근거는 공식·전문 자료를 따로 확보해 붙인다.
--
--   drink_discovery_items         발견 자료 1건(플랫폼·채널·제목·확보한 요약·게시 시각·확보 범위·권리 확인 상태)
--   drink_discovery_observations  공개 지표 관측(append-only). 제공된 지표만 저장 — 미제공은 키 자체가 없다(0 으로 채우지 않음)
--   drink_discovery_candidates    규칙으로 묶은 소재 후보(provisional, 기준 discovery-v1). 승인·편성과 무관
--   drink_candidate_items         후보 ↔ 발견 자료(자료 하나는 후보 하나에만 — 같은 자료로 후보를 부풀리지 않음)
--
-- 수집원(drink_sources)에 purpose(evidence|discovery)·platform·method 'api' 를 더한다. API 수집원의 주소·허용 호스트는
-- 입력이 아니라 아래 커넥터 목록(drinks_discovery_connector)에서 정해진다.
--
-- 되돌리기: 표 4개와 이 파일의 함수를 drop 하고, drink_sources·drink_collection_items 의 추가 칸·체크를 0051 정의로 되돌린다.

-- ─────────────────────────────────────────────────────────────
-- 커넥터 목록(코드 고정) — 공식 API 만. 키가 필요한 것은 워커가 키 없으면 검증 실행을 실패시킨다(api_key_missing)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_discovery_connector(p_platform text) returns jsonb language sql immutable as $$
  select case p_platform
    when 'stackexchange' then jsonb_build_object('entry', 'https://api.stackexchange.com/2.3/questions',
      'api_hosts', jsonb_build_array('api.stackexchange.com'), 'item_hosts', jsonb_build_array('alcohol.stackexchange.com'),
      'needs_key', false, 'coverage', 'title_summary', 'license', 'CC BY-SA 4.0(작성자·링크 표기)')
    when 'youtube' then jsonb_build_object('entry', 'https://www.googleapis.com/youtube/v3/search',
      'api_hosts', jsonb_build_array('www.googleapis.com'), 'item_hosts', jsonb_build_array('www.youtube.com'),
      'needs_key', true, 'coverage', 'title_summary_comments', 'license', 'YouTube API 서비스 약관 — 메타데이터·링크만 보관')
    when 'naver' then jsonb_build_object('entry', 'https://naverapihub.apigw.ntruss.com/search/v1/cafearticle',
      'api_hosts', jsonb_build_array('naverapihub.apigw.ntruss.com'),
      'item_hosts', jsonb_build_array('cafe.naver.com', 'blog.naver.com', 'm.blog.naver.com'),
      'needs_key', true, 'coverage', 'title_summary', 'license', '네이버 검색 API 약관 — 검색 결과 요약만(회원 전용 본문 아님)')
    else null end
$$;

-- ─────────────────────────────────────────────────────────────
-- 수집원 확장
-- ─────────────────────────────────────────────────────────────

alter table drink_sources add column if not exists purpose text not null default 'evidence'
  check (purpose in ('evidence','discovery'));
alter table drink_sources add column if not exists platform text
  check (platform is null or platform in ('stackexchange','youtube','naver'));
alter table drink_sources add column if not exists item_hosts text[] not null default '{}'
  check (cardinality(item_hosts) <= 5);
alter table drink_sources drop constraint if exists drink_sources_method_check;
alter table drink_sources drop constraint if exists drink_sources_method_ck;
alter table drink_sources add constraint drink_sources_method_ck
  check (method in ('manual_url','approved_page','listing','feed','api'));
alter table drink_sources drop constraint if exists drink_sources_api_ck;
alter table drink_sources add constraint drink_sources_api_ck
  check ((method = 'api') = (platform is not null) and (method <> 'api' or purpose = 'discovery'));

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_discovery_items (
  id                  uuid primary key default gen_random_uuid(),
  platform            text not null check (platform in
                        ('stackexchange','youtube','naver_cafe','naver_blog','instagram','reddit','community','web')),
  canonical_url       text not null check (canonical_url ~ '^https?://'),
  external_id         text,
  source_id           uuid references drink_sources(id),          -- 수동 등록이면 null
  first_run_id        uuid references drink_collection_runs(id),
  channel_name        text check (channel_name is null or length(channel_name) <= 200),   -- 채널·커뮤니티·카페 이름
  title               text check (title is null or length(title) <= 500),
  summary             text check (summary is null or length(summary) <= 2000),      -- 확보한 요약(원문 전문 아님)
  summary_hash        text,                                       -- 같은 글 전재(보도자료) 판별용
  posted_at           timestamptz,                                -- 확인 가능한 게시 시각. 모르면 null
  discovered_at       timestamptz not null default now(),
  coverage            text not null check (coverage in
                        ('link_only','title_only','title_summary','title_summary_comments')),
  collection_status   text not null check (collection_status in ('collected','manual')),
  rights_status       text not null default 'unknown' check (rights_status in
                        ('unknown','link_and_summary_ok','restricted')),
  rights_note         text,
  questions           text[] not null default '{}' check (cardinality(questions) <= 10),   -- 원문에서 뽑은 질문 문장(번역 안 함)
  signals             text[] not null default '{}' check (signals <@ array['question','debate','misconception','selection',
                        'storage','new_product','event']::text[]),
  operator_note       text check (operator_note is null or length(operator_note) <= 1000),
  origin_group        text,                                       -- 운영자가 정한 원출처 묶음
  latest_metrics      jsonb check (latest_metrics is null or jsonb_typeof(latest_metrics) = 'object'),
  metrics_observed_at timestamptz,
  created_by          text not null check (created_by in ('collector','operator')),
  version             int not null default 1,
  updated_at          timestamptz not null default now(),
  check ((collection_status = 'manual') = (created_by = 'operator')),
  check (collection_status = 'manual' or source_id is not null),
  check ((latest_metrics is null) = (metrics_observed_at is null))
);
create unique index if not exists drink_discovery_url_uq on drink_discovery_items (canonical_url);
create index if not exists drink_discovery_hash_idx on drink_discovery_items (summary_hash);
create index if not exists drink_discovery_time_idx on drink_discovery_items (discovered_at desc);

create table if not exists drink_discovery_observations (
  id           bigint generated always as identity primary key,
  item_id      uuid not null references drink_discovery_items(id),
  run_id       uuid references drink_collection_runs(id),
  observed_at  timestamptz not null default now(),
  metrics      jsonb not null check (jsonb_typeof(metrics) = 'object')
);
create index if not exists drink_disc_obs_item_idx on drink_discovery_observations (item_id, id desc);

create table if not exists drink_discovery_candidates (
  id                  uuid primary key default gen_random_uuid(),
  status              text not null default 'suggested' check (status in ('suggested','dismissed','promoted','merged')),
  key_question        text not null check (length(btrim(key_question)) between 1 and 500),  -- 원문 질문(번역 안 함)
  reader_value        text,
  discovery_path      text,
  signals             text[] not null default '{}',
  interest            jsonb not null default '{}',   -- 독립 채널 수·플랫폼별 지표(합산하지 않음)
  first_scene         text,
  fit_video           smallint check (fit_video between 0 and 4),
  fit_carousel        smallint check (fit_carousel between 0 and 4),
  facts_to_check      text[] not null default '{}',
  duplicate_topic_ids uuid[] not null default '{}',
  provisional_score   numeric(5,2),
  rubric              text not null default 'discovery-v1',
  score_reason        text,
  promoted_topic_id   uuid references drink_topics(id),
  merged_into         uuid references drink_discovery_candidates(id),
  decision_reason     text,
  version             int not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  check (status <> 'promoted' or promoted_topic_id is not null),
  check (status <> 'merged' or (merged_into is not null and merged_into <> id)),
  check (status <> 'dismissed' or decision_reason is not null)
);

create table if not exists drink_candidate_items (
  item_id      uuid primary key references drink_discovery_items(id),   -- 자료 하나는 후보 하나에만
  candidate_id uuid not null references drink_discovery_candidates(id),
  added_at     timestamptz not null default now()
);
create index if not exists drink_candidate_items_cand_idx on drink_candidate_items (candidate_id);

-- 실행 문서 기록이 발견 자료도 가리킬 수 있게(본문 스냅샷 대신).
alter table drink_collection_items add column if not exists discovery_item_id uuid references drink_discovery_items(id);
alter table drink_collection_items drop constraint if exists drink_collection_items_check;
alter table drink_collection_items drop constraint if exists drink_items_target_ck;
alter table drink_collection_items add constraint drink_items_target_ck
  check (status not in ('new','changed') or snapshot_id is not null or discovery_item_id is not null);

-- ─────────────────────────────────────────────────────────────
-- 트리거
-- ─────────────────────────────────────────────────────────────

drop trigger if exists drink_disc_obs_append_only on drink_discovery_observations;
create trigger drink_disc_obs_append_only before update or delete on drink_discovery_observations
  for each row execute function drink_append_only_guard();

create or replace function drink_discovery_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '발견 자료·후보는 삭제할 수 없습니다(기각·보관을 쓰세요)'); end if;
  if tg_op = 'UPDATE' then
    new.version := old.version + 1;
    new.updated_at := now();
  end if;
  return new;
end $$;
drop trigger if exists drink_discovery_items_guard on drink_discovery_items;
create trigger drink_discovery_items_guard before update or delete on drink_discovery_items
  for each row execute function drink_discovery_guard();
drop trigger if exists drink_discovery_cand_guard on drink_discovery_candidates;
create trigger drink_discovery_cand_guard before update or delete on drink_discovery_candidates
  for each row execute function drink_discovery_guard();

create or replace function drink_candidate_items_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '후보 연결은 지울 수 없습니다(병합은 옮기기로)'); end if;
  return new;
end $$;
drop trigger if exists drink_candidate_items_guard on drink_candidate_items;
create trigger drink_candidate_items_guard before delete on drink_candidate_items
  for each row execute function drink_candidate_items_guard();

-- ─────────────────────────────────────────────────────────────
-- 헬퍼
-- ─────────────────────────────────────────────────────────────

-- 제공된 공개 지표만 남긴다: 알려진 키 + 0 이상의 정수. 없는 지표는 키가 없다(0 으로 만들지 않음).
create or replace function drinks_clean_metrics(m jsonb) returns jsonb language sql immutable as $$
  select coalesce(jsonb_object_agg(k, (m ->> k)::bigint), '{}'::jsonb)
  from jsonb_object_keys(coalesce(case when jsonb_typeof(m) = 'object' then m end, '{}'::jsonb)) k
  where k in ('views','likes','comments','answers','score','favorites')
    and jsonb_typeof(m -> k) = 'number' and (m ->> k) ~ case when k = 'score' then '^-?[0-9]+$' else '^[0-9]+$' end
$$;

create or replace function drinks_discovery_platform_ok(p text) returns boolean language sql immutable as $$
  select p in ('stackexchange','youtube','naver_cafe','naver_blog','instagram','reddit','community','web')
$$;

-- ─────────────────────────────────────────────────────────────
-- 수집원 등록: 발견용 API 수집원(주소·허용 호스트는 커넥터 목록이 정한다)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_register_discovery_source(p jsonb) returns jsonb language plpgsql as $$
declare
  c jsonb := drinks_discovery_connector(drinks_text(p, 'platform')); s drink_sources; cats text[];
  q text[] := drinks_text_array(p -> 'queries');
begin
  if c is null then perform drinks_fail('invalid_input', '지원하는 발견 채널(stackexchange·youtube·naver)을 고르세요'); end if;
  if drinks_text(p, 'name') is null then perform drinks_fail('invalid_input', '이름을 입력하세요'); end if;
  cats := drinks_text_array(p -> 'categories');
  if cardinality(cats) = 0 or not cats <@ array['sake','traditional','whisky'] then
    perform drinks_fail('invalid_input', '주종은 사케·전통주·위스키 중에서 고르세요');
  end if;
  if cardinality(q) = 0 or cardinality(q) > 10 or exists (select 1 from unnest(q) x where length(x) > 100) then
    perform drinks_fail('invalid_input', '검색어·태그를 1~10개(각 100자 이하) 넣으세요');
  end if;
  if drinks_text(p, 'platform') = 'youtube' and cardinality(q) > 3 then
    -- search.list 1회 = 쿼터 100. 실행마다 쓰지 못하는 검색어가 남으면 매번 '다 못 봤음'이 된다(검토 지적).
    perform drinks_fail('invalid_input', '유튜브 검색어는 수집원 하나에 3개까지입니다 — 나머지는 다른 수집원으로 등록하세요');
  end if;
  insert into drink_sources (name, home_url, publisher, language, categories, source_kind, method, entry_urls, allowed_hosts,
    parser_config, terms_status, terms_note, terms_url, terms_checked_at, rights_default, request_interval_sec,
    max_items_per_run, max_bodies_per_run, purpose, platform, item_hosts)
  -- 대표 주소 = 커넥터 주소 + 검색어 묶음 지문. 같은 채널·같은 검색어 묶음만 중복으로 막는다(주종별로 따로 둘 수 있게).
  values (drinks_text(p, 'name'), (c ->> 'entry') || '#q=' || left(md5(array_to_string(array(select x from unnest(q) x order by 1), '|')), 12),
    drinks_text(p, 'publisher'), coalesce(drinks_text(p, 'language'), 'en'), cats,
    'community', 'api', array[c ->> 'entry'], array(select jsonb_array_elements_text(c -> 'api_hosts')),
    jsonb_build_object('queries', to_jsonb(q), 'site', coalesce(drinks_text(p, 'site'), 'alcohol')),
    'unverified', c ->> 'license', null, null, 'unknown',
    greatest(coalesce(drinks_int(p, 'request_interval_sec', false), 3), 3),
    least(coalesce(drinks_int(p, 'max_items_per_run', false), 50), 100), 0,
    'discovery', drinks_text(p, 'platform'), array(select jsonb_array_elements_text(c -> 'item_hosts')))
  returning * into s;
  perform drinks_log_source(s.id, 'source', s.id, 'source_registered', null, s.state, null,
    jsonb_build_object('purpose', 'discovery', 'platform', s.platform));
  return jsonb_build_object('source_id', s.id, 'state', s.state, 'version', s.version,
    'needs_key', (c ->> 'needs_key')::boolean);
exception when unique_violation then
  perform drinks_fail('duplicate_source', '같은 채널 수집원이 이미 있습니다 — 검색어는 그 수집원에 추가하세요');
  return null;
end $$;

-- 워커가 받는 실행 정보에 발견 수집원 칸을 더한다(0051 정의 대체).
create or replace function drinks_run_payload(r drink_collection_runs, s drink_sources) returns jsonb
language sql stable as $$
  select jsonb_build_object('run_id', r.id, 'lease_token', r.lease_token, 'lease_expires_at', r.lease_expires_at,
    'mode', r.mode, 'retry_urls', to_jsonb(r.retry_urls), 'cursor_from', r.cursor_from, 'limits', r.limits,
    'source', jsonb_build_object('id', s.id, 'name', s.name, 'method', s.method, 'entry_urls', to_jsonb(s.entry_urls),
      'allowed_hosts', to_jsonb(s.allowed_hosts), 'parser_config', s.parser_config, 'parser_version', s.parser_version,
      'language', s.language, 'publisher', s.publisher, 'purpose', s.purpose, 'platform', s.platform,
      'item_hosts', to_jsonb(s.item_hosts)))
$$;

-- ─────────────────────────────────────────────────────────────
-- 워커: 발견 자료 1건 기록(drinks_collect_item 의 발견판). 같은 실행·같은 URL 은 한 번.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_collect_discovery(p jsonb) returns jsonb language plpgsql as $$
declare
  r drink_collection_runs; s drink_sources; it jsonb := p -> 'item';
  v_url text := drinks_text(it, 'canonical_url'); v_status text := drinks_text(it, 'status');
  v_summary text := left(drinks_text(it, 'summary'), 2000); v_hash text; d drink_discovery_items;
  v_final text; v_metrics jsonb; v_id bigint; v_platform text := drinks_text(it, 'platform');
  v_questions text[]; v_signals text[];
begin
  r := drinks_lock_run(p);
  select * into s from drink_sources where id = r.source_id;
  if s.purpose <> 'discovery' then perform drinks_fail('invalid_state', '발견용 수집원이 아닙니다'); end if;
  if it is null or jsonb_typeof(it) <> 'object' then perform drinks_fail('invalid_input', '자료 형식이 잘못됐습니다'); end if;
  if v_url is null or not drinks_entry_url_ok(v_url) or not (drinks_url_host(v_url) = any(s.item_hosts)) then
    perform drinks_fail('host_not_allowed', '이 채널의 자료 주소가 아닙니다');
  end if;
  if coalesce(v_status, '') not in ('fetched','skipped','failed') then perform drinks_fail('invalid_input', '자료 결과 값이 잘못됐습니다'); end if;
  if v_status in ('skipped','failed') and drinks_text(it, 'error_code') is null then
    perform drinks_fail('invalid_input', '건너뜀·실패에는 오류 코드가 필요합니다');
  end if;
  if r.item_count >= (r.limits ->> 'max_items')::int then
    perform drinks_fail('limit_exceeded', '이 실행의 자료 상한(' || (r.limits ->> 'max_items') || '건)에 닿았습니다');
  end if;
  if exists (select 1 from drink_collection_items i where i.run_id = r.id and i.canonical_url = v_url) then
    return jsonb_build_object('duplicate_in_run', true);
  end if;
  if v_status = 'fetched' and r.mode = 'validate' then
    -- 검증 실행: 자료가 실제로 오는지만 기록한다(발견 자료를 만들지 않음). 확보한 글자 수 = 제목+요약.
    v_final := 'checked';
  elsif v_status = 'fetched' then
    if not drinks_discovery_platform_ok(v_platform) then perform drinks_fail('invalid_input', '플랫폼 값이 잘못됐습니다'); end if;
    v_hash := drinks_body_hash(coalesce(v_summary, drinks_text(it, 'title')));
    v_metrics := drinks_clean_metrics(it -> 'metrics');
    v_questions := array(select left(x, 300) from unnest(drinks_text_array(it -> 'questions')) x limit 10);
    v_signals := array(select x from unnest(drinks_text_array(it -> 'signals')) x
      where x = any(array['question','debate','misconception','selection','storage','new_product','event']));
    select * into d from drink_discovery_items where canonical_url = v_url for update;
    if not found then
      insert into drink_discovery_items (platform, canonical_url, external_id, source_id, first_run_id, channel_name, title,
        summary, summary_hash, posted_at, coverage, collection_status, rights_status, rights_note, questions, signals,
        latest_metrics, metrics_observed_at, created_by)
      values (v_platform, v_url, drinks_text(it, 'external_id'), s.id, r.id, left(drinks_text(it, 'channel_name'), 200),
        left(drinks_text(it, 'title'), 500), v_summary, v_hash, (drinks_text(it, 'posted_at'))::timestamptz,
        coalesce(drinks_text(it, 'coverage'), 'title_only'), 'collected', 'unknown', s.terms_note, v_questions, v_signals,
        case when v_metrics = '{}' then null else v_metrics end, case when v_metrics = '{}' then null else now() end, 'collector')
      on conflict (canonical_url) do nothing
      returning * into d;
      v_final := case when d.id is null then 'unchanged' else 'new' end;
      if d.id is null then select * into d from drink_discovery_items where canonical_url = v_url; end if;
    else
      v_final := case when d.summary_hash is distinct from v_hash then 'changed' else 'unchanged' end;
      update drink_discovery_items set title = coalesce(left(drinks_text(it, 'title'), 500), title),
        summary = coalesce(v_summary, summary), summary_hash = v_hash,
        questions = case when cardinality(v_questions) > 0 then v_questions else questions end,
        signals = case when cardinality(v_signals) > 0 then v_signals else signals end,
        latest_metrics = case when v_metrics = '{}' then latest_metrics else v_metrics end,
        metrics_observed_at = case when v_metrics = '{}' then metrics_observed_at else now() end
        where id = d.id returning * into d;
    end if;
    if v_metrics <> '{}' then
      insert into drink_discovery_observations (item_id, run_id, metrics) values (d.id, r.id, v_metrics);
    end if;
  else
    v_final := v_status;
  end if;
  insert into drink_collection_items (run_id, source_id, canonical_url, url_raw, status, http_status, error_code, error_message,
    title, summary, published_at, discovery_item_id, body_chars)
  values (r.id, s.id, v_url, v_url, v_final, drinks_int(it, 'http_status', false), drinks_text(it, 'error_code'),
    left(drinks_text(it, 'error_message'), 1000), left(drinks_text(it, 'title'), 500), left(v_summary, 2000),
    (drinks_text(it, 'posted_at'))::timestamptz::date, d.id,
    case when v_final = 'checked' then length(coalesce(drinks_text(it, 'title'), '') || coalesce(v_summary, '')) end)
  on conflict (run_id, canonical_url) do nothing returning id into v_id;
  if v_id is null then return jsonb_build_object('duplicate_in_run', true); end if;
  update drink_collection_runs set item_count = item_count + 1,
    new_count = new_count + (case when v_final = 'new' then 1 else 0 end),
    changed_count = changed_count + (case when v_final = 'changed' then 1 else 0 end),
    unchanged_count = unchanged_count + (case when v_final = 'unchanged' then 1 else 0 end),
    skipped_count = skipped_count + (case when v_final = 'skipped' then 1 else 0 end),
    failed_count = failed_count + (case when v_final = 'failed' then 1 else 0 end),
    heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => drinks_limit('lease_sec'))
    where id = r.id;
  return jsonb_build_object('item_id', v_id, 'status', v_final, 'discovery_item_id', d.id);
end $$;

-- 워커: 아직 후보에 묶이지 않은 발견 자료 + 열린 후보(규칙 묶기 입력). 읽기만.
create or replace function drinks_discovery_backlog(p jsonb) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'items', coalesce((select jsonb_agg(jsonb_build_object('id', d.id, 'platform', d.platform, 'channel_name', d.channel_name,
        'title', d.title, 'summary', left(d.summary, 600), 'summary_hash', d.summary_hash, 'origin_group', d.origin_group,
        'questions', to_jsonb(d.questions), 'signals', to_jsonb(d.signals), 'latest_metrics', d.latest_metrics,
        'posted_at', d.posted_at, 'canonical_url', d.canonical_url) order by d.discovered_at)
      from (select * from drink_discovery_items x where not exists (select 1 from drink_candidate_items ci where ci.item_id = x.id)
        order by x.discovered_at limit 500) d), '[]'),
    'candidates', coalesce((select jsonb_agg(jsonb_build_object('id', c.id, 'key_question', c.key_question, 'version', c.version,
        'items', coalesce((select jsonb_agg(jsonb_build_object('id', d.id, 'platform', d.platform, 'channel_name', d.channel_name,
            'title', d.title, 'summary', left(d.summary, 600), 'summary_hash', d.summary_hash, 'origin_group', d.origin_group,
            'questions', to_jsonb(d.questions), 'signals', to_jsonb(d.signals), 'latest_metrics', d.latest_metrics,
            'canonical_url', d.canonical_url))
          from drink_candidate_items ci join drink_discovery_items d on d.id = ci.item_id where ci.candidate_id = c.id), '[]')))
      from drink_discovery_candidates c where c.status = 'suggested'), '[]'),
    'topics', coalesce((select jsonb_agg(jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question))
      from drink_topics t where t.status not in ('duplicate','rejected')), '[]'))
$$;

-- 워커(규칙): 후보 만들기 또는 열린 후보에 자료 더하기. 이미 다른 후보에 묶인 자료는 거부(부풀리기 방지).
create or replace function drinks_suggest_candidate(p jsonb) returns jsonb language plpgsql as $$
declare
  ids uuid[] := array(select (x)::uuid from jsonb_array_elements_text(coalesce(p -> 'item_ids', '[]')) x);
  c drink_discovery_candidates; v_target uuid := drinks_uuid(p, 'candidate_id', false); n int;
begin
  if cardinality(ids) = 0 and v_target is null then perform drinks_fail('invalid_input', '자료가 없습니다'); end if;
  perform 1 from drink_discovery_items where id = any(ids) order by id for update;
  get diagnostics n = row_count;
  if n <> cardinality(ids) then perform drinks_fail('not_found', '없는 자료가 섞여 있습니다'); end if;
  if cardinality(ids) > 0 and exists (select 1 from drink_candidate_items where item_id = any(ids)) then
    return jsonb_build_object('skipped', 'already_assigned');
  end if;
  if v_target is not null then
    select * into c from drink_discovery_candidates where id = v_target for update;
    if not found or c.status <> 'suggested' then return jsonb_build_object('skipped', 'candidate_closed'); end if;
    -- 카드는 후보의 **자료 전체**로 다시 계산한 값이어야 한다(워커가 그렇게 보낸다 — 새 묶음만으로 덮지 않게).
    update drink_discovery_candidates set interest = coalesce(p -> 'interest', interest),
      signals = coalesce(drinks_text_array(p -> 'signals'), signals), provisional_score = coalesce((p ->> 'provisional_score')::numeric, provisional_score),
      score_reason = coalesce(drinks_text(p, 'score_reason'), score_reason),
      facts_to_check = case when p ? 'facts_to_check' then drinks_text_array(p -> 'facts_to_check') else facts_to_check end,
      fit_video = coalesce(drinks_int(p, 'fit_video', false), fit_video), fit_carousel = coalesce(drinks_int(p, 'fit_carousel', false), fit_carousel),
      duplicate_topic_ids = case when p ? 'duplicate_topic_ids' then array(select (x)::uuid from jsonb_array_elements_text(p -> 'duplicate_topic_ids') x
        where exists (select 1 from drink_topics t where t.id = (x)::uuid)) else duplicate_topic_ids end
      where id = c.id returning * into c;
    if cardinality(ids) = 0 then return jsonb_build_object('candidate_id', c.id, 'added', 0, 'refreshed', true); end if;
  else
    insert into drink_discovery_candidates (key_question, reader_value, discovery_path, signals, interest, first_scene, fit_video,
      fit_carousel, facts_to_check, duplicate_topic_ids, provisional_score, rubric, score_reason)
    values (left(drinks_text(p, 'key_question'), 500), drinks_text(p, 'reader_value'), drinks_text(p, 'discovery_path'),
      drinks_text_array(p -> 'signals'), coalesce(p -> 'interest', '{}'), drinks_text(p, 'first_scene'),
      drinks_int(p, 'fit_video', false), drinks_int(p, 'fit_carousel', false), drinks_text_array(p -> 'facts_to_check'),
      array(select (x)::uuid from jsonb_array_elements_text(coalesce(p -> 'duplicate_topic_ids', '[]')) x
        where exists (select 1 from drink_topics t where t.id = (x)::uuid)),
      (p ->> 'provisional_score')::numeric, coalesce(drinks_text(p, 'rubric'), 'discovery-v1'), drinks_text(p, 'score_reason'))
    returning * into c;
  end if;
  insert into drink_candidate_items (item_id, candidate_id) select x, c.id from unnest(ids) x;
  return jsonb_build_object('candidate_id', c.id, 'added', cardinality(ids));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 운영자 동작
-- ─────────────────────────────────────────────────────────────

-- 수동 발견 자료: 어떤 채널이든 URL + 짧은 메모. 서버는 URL 을 열지 않는다(제목·요약은 운영자가 쓴 것만).
create or replace function drinks_add_discovery(p jsonb) returns jsonb language plpgsql as $$
declare d drink_discovery_items; v_url text := drinks_text(p, 'canonical_url'); v_platform text := drinks_text(p, 'platform');
  v_existing boolean := false;
begin
  if v_url is null or v_url !~ '^https?://[^\s/]+' then perform drinks_fail('invalid_input', 'http(s) 주소를 넣으세요'); end if;
  if not coalesce(drinks_discovery_platform_ok(v_platform), false) then perform drinks_fail('invalid_input', '플랫폼을 고르세요'); end if;
  select * into d from drink_discovery_items where canonical_url = v_url;
  if found then
    v_existing := true;
  else
    insert into drink_discovery_items (platform, canonical_url, channel_name, title, summary, summary_hash, posted_at, coverage,
      collection_status, operator_note, questions, created_by)
    values (v_platform, v_url, left(drinks_text(p, 'channel_name'), 200), left(drinks_text(p, 'title'), 500),
      left(drinks_text(p, 'summary'), 2000), drinks_body_hash(coalesce(drinks_text(p, 'summary'), drinks_text(p, 'title'))),
      (drinks_text(p, 'posted_at'))::timestamptz,
      case when drinks_text(p, 'summary') is not null then 'title_summary' when drinks_text(p, 'title') is not null then 'title_only'
        else 'link_only' end,
      'manual', left(drinks_text(p, 'note'), 1000),
      case when drinks_text(p, 'question') is not null then array[left(drinks_text(p, 'question'), 300)] else '{}' end, 'operator')
    on conflict (canonical_url) do nothing returning * into d;
    if d.id is null then select * into d from drink_discovery_items where canonical_url = v_url; v_existing := true; end if;
  end if;
  return jsonb_build_object('discovery_item_id', d.id, 'existing', v_existing);
end $$;

-- 후보 → 소재(사람이 한국어 제목·질문을 쓴다). 발견 자료는 URL만(metadata_only) 질문·인기 신호로 붙는다 — 근거가 아니다.
create or replace function drinks_promote_candidate(p jsonb) returns jsonb language plpgsql as $$
declare c drink_discovery_candidates; r jsonb; it record; links jsonb := '[]'; v_topic uuid;
begin
  select * into c from drink_discovery_candidates where id = drinks_uuid(p, 'candidate_id') for update;
  if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from c.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  if c.status <> 'suggested' then perform drinks_fail('invalid_state', '열린 후보만 소재로 올릴 수 있습니다'); end if;
  v_topic := drinks_uuid(p, 'topic_id', false);
  if v_topic is null then
    r := drinks_create_topic(jsonb_build_object('title', drinks_text(p, 'title'), 'question', drinks_text(p, 'question'),
      'categories', p -> 'categories', 'lane', coalesce(drinks_text(p, 'lane'), 'reader_question'),
      'reader_value', coalesce(drinks_text(p, 'reader_value'), c.reader_value), 'target_subject', drinks_text(p, 'target_subject'),
      'angle', drinks_text(p, 'angle'), 'confirm_not_duplicate', coalesce(p -> 'confirm_not_duplicate', 'false'::jsonb)));
    v_topic := (r ->> 'topic_id')::uuid;
  else
    -- 기존 소재에 신호로 더하기(병합 결정은 운영자). 중복·제외 처리된 소재에는 붙이지 않는다.
    if (drinks_lock_topic(v_topic, null, false)).status in ('duplicate','rejected') then
      perform drinks_fail('invalid_state', '중복·제외 처리된 소재에는 붙일 수 없습니다');
    end if;
  end if;
  for it in select d.* from drink_candidate_items ci join drink_discovery_items d on d.id = ci.item_id
      where ci.candidate_id = c.id order by d.discovered_at loop
    links := links || jsonb_build_array(drinks_add_source_internal(v_topic, jsonb_strip_nulls(jsonb_build_object(
      'canonical_url', it.canonical_url, 'url_raw', it.canonical_url, 'title', it.title, 'publisher', it.channel_name,
      'source_kind', case when it.platform in ('stackexchange','reddit','naver_cafe','community') then 'community' else 'media' end,
      'role', 'discovery', 'relation_note', '소재 발견 자료(' || it.platform || ')'))));
  end loop;
  update drink_discovery_candidates set status = 'promoted', promoted_topic_id = v_topic,
    decision_reason = drinks_text(p, 'reason') where id = c.id;
  perform drinks_log(v_topic, 'topic', v_topic, 'discovery_promoted', null, null, c.id::text, drinks_text(p, 'reason'),
    jsonb_build_object('candidate_id', c.id, 'rubric', c.rubric, 'provisional_score', c.provisional_score, 'links', jsonb_array_length(links)));
  return jsonb_build_object('topic_id', v_topic, 'linked', jsonb_array_length(links), 'created', r is not null);
end $$;

create or replace function drinks_candidate_action(p jsonb) returns jsonb language plpgsql as $$
declare c drink_discovery_candidates; t drink_discovery_candidates; v_action text := drinks_text(p, 'action');
begin
  select * into c from drink_discovery_candidates where id = drinks_uuid(p, 'candidate_id') for update;
  if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from c.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  if v_action = 'dismiss' then
    if c.status <> 'suggested' then perform drinks_fail('invalid_state', '열린 후보만 기각합니다'); end if;
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '기각 사유를 적으세요'); end if;
    update drink_discovery_candidates set status = 'dismissed', decision_reason = drinks_text(p, 'reason') where id = c.id returning * into c;
  elsif v_action = 'reopen' then
    if c.status <> 'dismissed' then perform drinks_fail('invalid_state', '기각한 후보만 다시 엽니다'); end if;
    update drink_discovery_candidates set status = 'suggested', decision_reason = null where id = c.id returning * into c;
  elsif v_action = 'merge' then
    if c.status <> 'suggested' then perform drinks_fail('invalid_state', '열린 후보만 병합합니다'); end if;
    select * into t from drink_discovery_candidates where id = drinks_uuid(p, 'into_candidate_id') for update;
    if not found or t.status <> 'suggested' or t.id = c.id then perform drinks_fail('invalid_input', '합칠 대상이 열린 다른 후보여야 합니다'); end if;
    update drink_candidate_items set candidate_id = t.id where candidate_id = c.id;
    update drink_discovery_candidates set status = 'merged', merged_into = t.id, decision_reason = drinks_text(p, 'reason') where id = c.id
      returning * into c;
  elsif v_action = 'edit' then
    if c.status <> 'suggested' then perform drinks_fail('invalid_state', '열린 후보만 고칩니다'); end if;
    update drink_discovery_candidates set key_question = coalesce(left(drinks_text(p, 'key_question'), 500), key_question),
      reader_value = coalesce(drinks_text(p, 'reader_value'), reader_value),
      facts_to_check = case when p ? 'facts_to_check' then drinks_text_array(p -> 'facts_to_check') else facts_to_check end
      where id = c.id returning * into c;
  else
    perform drinks_fail('invalid_input', '알 수 없는 후보 동작입니다');
  end if;
  return jsonb_build_object('candidate_id', c.id, 'status', c.status, 'version', c.version);
end $$;

-- 원출처 묶음(운영자): 같은 보도자료 전재 등을 하나로 센다. 자동으로 묶지 않는다.
create or replace function drinks_set_discovery_origin(p jsonb) returns jsonb language plpgsql as $$
declare d drink_discovery_items;
begin
  select * into d from drink_discovery_items where id = drinks_uuid(p, 'discovery_item_id') for update;
  if not found then perform drinks_fail('not_found', '자료를 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from d.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  update drink_discovery_items set
    origin_group = case when p ? 'origin_group' then drinks_text(p, 'origin_group') else origin_group end,
    rights_status = coalesce(drinks_text(p, 'rights_status'), rights_status), rights_note = coalesce(drinks_text(p, 'rights_note'), rights_note)
    where id = d.id returning * into d;
  return jsonb_build_object('discovery_item_id', d.id, 'origin_group', d.origin_group, 'version', d.version);
end $$;

-- 실행 끝(0051 정의 대체): 발견 수집원의 '받은 데까지 전진'만 더했다. 나머지 판정은 0051 과 같다.
create or replace function drinks_finish_run(p jsonb) returns jsonb language plpgsql as $$
declare
  r drink_collection_runs; s drink_sources; v_fatal text := drinks_text(p, 'error_code');
  v_aborted boolean := coalesce((p ->> 'aborted')::boolean, false); v_ok int; v_status text; v_to timestamptz;
  -- 워커가 알려 주는 "다 못 본 것": 문서·본문 상한에 걸려 처음 보는 글을 못 가져옴, 승인 밖 호스트로 빠진 글.
  v_incomplete int := greatest(coalesce(drinks_int(p, 'incomplete_count', false), 0), 0);
  v_offhost int := greatest(coalesce(drinks_int(p, 'offhost_count', false), 0), 0);
  v_parsed int := drinks_int(p, 'parsed_count', false);
  -- 발견 수집원: 오래된 것부터(시간 오름차순) 받은 경우 "여기까지는 빠짐없이 봤다"는 시각. 상한에 걸려도 그만큼은 전진한다.
  v_advance timestamptz := (drinks_text(p, 'advance_to'))::timestamptz;
begin
  r := drinks_lock_run(p);
  select * into s from drink_sources where id = r.source_id for update;
  v_ok := r.item_count - r.failed_count - r.skipped_count;
  if v_aborted then v_status := 'aborted';
  elsif v_fatal is not null and r.item_count = 0 then v_status := 'failed';
  -- 목록·피드를 받았는데 링크·글을 하나도 못 찾음 = 사이트 개편 의심. "정상 0건"이 아니다.
  elsif r.mode <> 'retry' and s.method in ('listing','feed') and v_parsed = 0 then
    v_status := 'failed'; v_fatal := 'no_candidates';
  elsif r.item_count = 0 and v_offhost > 0 then v_status := 'failed'; v_fatal := 'host_not_allowed';
  elsif r.item_count > 0 and v_ok = 0 and r.failed_count = 0 then v_status := 'failed'; v_fatal := 'all_skipped';
  elsif r.failed_count > 0 and v_ok + r.skipped_count > 0 then v_status := 'partial';
  elsif r.failed_count > 0 then v_status := 'failed';
  elsif v_fatal is not null then v_status := 'partial';
  elsif v_incomplete + v_offhost > 0 then
    v_status := 'partial'; v_fatal := case when v_incomplete > 0 then 'limit_reached' else 'host_not_allowed' end;
  elsif r.item_count = 0 then v_status := 'empty';
  else v_status := 'succeeded';
  end if;
  -- 검증 실행은 문서가 하나도 없으면 "검증 성공"이 아니다 — 본문을 실제로 뽑아 봐야 한다.
  if r.mode = 'validate' and v_status in ('succeeded','empty')
      and not exists (select 1 from drink_collection_items i where i.run_id = r.id and i.status = 'checked'
        and coalesce(i.body_chars, 0) > 0) then
    v_status := 'failed'; v_fatal := coalesce(v_fatal, 'no_body_extracted');
  end if;
  if r.mode = 'collect' and v_status in ('succeeded','empty') then v_to := r.started_at; end if;
  -- 상한(limit_reached)만으로 부분 성공인 발견 실행은 받은 데까지 워처마크를 옮긴다 — 안 옮기면 매번 같은 첫 묶음만 받고
  -- 영원히 부분 성공이다(검토 지적). 실패 문서가 있으면 옮기지 않는다.
  if r.mode = 'collect' and s.purpose = 'discovery' and v_status = 'partial' and v_fatal = 'limit_reached'
      and r.failed_count = 0 and v_advance is not null then
    v_to := least(v_advance, r.started_at);
  end if;
  update drink_collection_runs set status = v_status, finished_at = now(), lease_token = null, cursor_to = v_to,
    listed_count = greatest(listed_count, coalesce(drinks_int(p, 'listed_count', false), 0)),
    request_count = greatest(request_count, coalesce(drinks_int(p, 'request_count', false), 0)),
    error_code = coalesce(v_fatal, case when v_status = 'partial' then 'some_items_failed' end),
    error_message = left(coalesce(drinks_text(p, 'error_message'),
      case when v_fatal = 'limit_reached' then '상한에 걸려 처음 보는 글 ' || v_incomplete || '건을 다 가져오지 못했습니다 — 다음 실행이 이어서 가져옵니다(워처마크 그대로)'
        when v_fatal = 'no_candidates' then '목록·피드에서 글 링크를 하나도 찾지 못했습니다 — 사이트 개편 여부를 확인하세요'
        when v_fatal = 'all_skipped' then '모든 문서를 건너뛰었습니다(robots.txt 등) — 아무것도 수집하지 못했습니다'
        when v_fatal = 'host_not_allowed' then '승인 밖 호스트로 이어진 글 ' || v_offhost || '건을 가져오지 않았습니다'
        when v_status = 'partial' then r.failed_count || '건 실패 — [실패분 재시도]로 다시 가져올 수 있습니다' end), 2000)
    where id = r.id returning * into r;
  if r.mode = 'validate' then
    update drink_sources set last_validation_run_id = r.id where id = s.id;
  end if;
  if v_to is not null then
    -- 워처마크는 앞으로만 간다(늦게 끝난 옛 실행이 되돌리지 못하게).
    update drink_sources set watermark_at = greatest(coalesce(watermark_at, v_to), v_to), last_success_run_id = r.id
      where id = s.id;
  end if;
  perform drinks_log_source(s.id, 'run', r.id, 'run_finished', 'running', r.status, r.error_code,
    jsonb_build_object('items', r.item_count, 'failed', r.failed_count, 'new', r.new_count, 'changed', r.changed_count,
      'watermark_advanced', v_to is not null), 'worker');
  return jsonb_build_object('run_id', r.id, 'status', r.status, 'watermark_advanced', v_to is not null);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한
-- ─────────────────────────────────────────────────────────────

alter table drink_discovery_items enable row level security;
alter table drink_discovery_observations enable row level security;
alter table drink_discovery_candidates enable row level security;
alter table drink_candidate_items enable row level security;

revoke all on table drink_discovery_items, drink_discovery_observations, drink_discovery_candidates, drink_candidate_items
  from anon, authenticated;
revoke all on sequence drink_discovery_observations_id_seq from anon, authenticated;
grant select, insert, update on table drink_discovery_items, drink_discovery_observations, drink_discovery_candidates,
  drink_candidate_items to service_role;
grant usage on sequence drink_discovery_observations_id_seq to service_role;

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
