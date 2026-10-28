-- 주류 공장 - 질문 신호를 소재와 전략까지 (2026-10-28). docs/deviation-drinks-discovery.md "질문 신호를 소재와 전략까지"
--
-- 문제: 소재 발견 후보에는 질문 유형(signals)·출처 채널·관심 신호(interest)가 있는데, 소재로 올리면 사라진다.
--   그래서 전략 고리(성과 -> 다음 편성)는 주종·갈래·형식·시간대만 배우고 "어떤 질문이 저장을 부르나"는 잴 수 없다.
-- 이 파일이 하는 일:
--   1) drink_topics 에 question_kind(질문 유형)·discovery_platforms(발견 채널)·interest(관심 신호) 칸을 더한다.
--   2) drinks_promote_candidate 가 후보 값을 복사한다(운영자가 고른 질문 유형이 있으면 그것을 우선).
--   3) 수동 등록(drinks_create_topic)이 question_kind 를 받는다(기본 general).
--   4) 전략 묶음(차원)에 question_kind 를 더한다: 입력(drinks_strategy_inputs)·제안 검증·가점(drinks_strategy_lift/rank).
--      문턱(묶음 3편·전체 6편·한 번에 ±0.2·상한 ±0.5)은 그대로다.
--   5) 발견 수집원 설정에 선택 칸 lookback_days(1~3650)를 받는다 - 첫 실행 소급 기간(없으면 전역 365일).
--   6) 바꾼 함수에 검색 경로를 다시 고정한다(0056 과 같은 반복문 - create or replace 는 함수 설정을 지운다).
-- 영향: 기존 소재는 question_kind='general', discovery_platforms='{}', interest=null 이 된다(손실 없음).
--   기존 전략 가중치(strategy-v0 등)에는 question_kind 칸이 없고, 없는 칸은 가점 0 으로 읽힌다.
-- 되돌리기(아래 순서):
--   1. 0055 의 drinks_strategy_inputs·drinks_save_strategy_proposal·drinks_strategy_rank 를 다시 실행하고,
--      drop function drinks_strategy_lift(jsonb, text[], text, text[], text); 후 0055 의 4-인자 drinks_strategy_lift 를 다시 만든다.
--   2. 0050 의 drinks_create_topic, 0052 의 drinks_promote_candidate·drinks_register_discovery_source 를 다시 실행한다.
--   3. drop function drinks_pick_question_kind(text[]);
--      alter table drink_topics drop column question_kind, drop column discovery_platforms, drop column interest;
--   4. 0056 의 반복문을 다시 실행한다.

-- ─────────────────────────────────────────────────────────────
-- 1) 소재 칸
-- ─────────────────────────────────────────────────────────────

alter table drink_topics add column if not exists question_kind text not null default 'general';
alter table drink_topics drop constraint if exists drink_topics_question_kind_ck;
alter table drink_topics add constraint drink_topics_question_kind_ck
  check (question_kind in ('storage','misconception','selection','debate','pairing','howto','general'));
alter table drink_topics add column if not exists discovery_platforms text[] not null default '{}';
alter table drink_topics drop constraint if exists drink_topics_discovery_platforms_ck;
alter table drink_topics add constraint drink_topics_discovery_platforms_ck check (cardinality(discovery_platforms) <= 8);
alter table drink_topics add column if not exists interest jsonb;
alter table drink_topics drop constraint if exists drink_topics_interest_ck;
alter table drink_topics add constraint drink_topics_interest_ck check (interest is null or jsonb_typeof(interest) = 'object');

-- 후보 신호 -> 질문 유형. 여러 신호가 겹치면 고정 우선순위(보관 > 오해 > 논쟁 > 선택). 그 밖의 신호(question·new_product·event)는 general.
-- engine/config.py DRINKS_QUESTION_KIND_PRIORITY 와 같은 순서여야 한다(tests/test_drinks_bootstrap.py 가 대조).
create or replace function drinks_pick_question_kind(p_signals text[]) returns text language sql immutable as $$
  select coalesce((select k from unnest(array['storage','misconception','debate','selection']) with ordinality o(k, n)
    where k = any(coalesce(p_signals, '{}')) order by n limit 1), 'general')
$$;

-- ─────────────────────────────────────────────────────────────
-- 2) 수동 소재 등록: question_kind (0050 정의 대체 - 마지막 칸만 늘었다)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_create_topic(p jsonb) returns jsonb language plpgsql as $$
declare
  t drink_topics; cats text[]; v_key text; dups jsonb; src jsonb; v_kind text := coalesce(drinks_text(p, 'question_kind'), 'general');
  v_platforms text[] := drinks_text_array(p -> 'discovery_platforms');
  v_interest jsonb := case when jsonb_typeof(p -> 'interest') = 'object' and p -> 'interest' <> '{}'::jsonb then p -> 'interest' end;
begin
  if drinks_text(p, 'title') is null or drinks_text(p, 'question') is null then
    perform drinks_fail('invalid_input', '제목과 질문을 입력하세요');
  end if;
  if jsonb_typeof(p -> 'categories') is distinct from 'array' then
    perform drinks_fail('invalid_input', '주종을 하나 이상 고르세요');
  end if;
  cats := drinks_text_array(p -> 'categories');
  if cardinality(cats) = 0 or not cats <@ array['sake','traditional','whisky'] then
    perform drinks_fail('invalid_input', '주종은 사케·전통주·위스키 중에서 고르세요');
  end if;
  if coalesce(drinks_text(p, 'lane'), '') not in ('evergreen','timely','reader_question') then
    perform drinks_fail('invalid_input', '공급 경로(상시 지식·시의성·독자 질문)를 고르세요');
  end if;
  if v_kind not in ('storage','misconception','selection','debate','pairing','howto','general') then
    perform drinks_fail('invalid_input', '질문 유형을 다시 고르세요');
  end if;
  if exists (select 1 from unnest(v_platforms) x where not drinks_discovery_platform_ok(x)) then
    perform drinks_fail('invalid_input', '발견 채널 값이 잘못됐습니다');
  end if;
  v_key := drinks_dedupe_key(cats, drinks_text(p, 'question'), drinks_text(p, 'target_subject'), drinks_text(p, 'angle'));
  select jsonb_agg(jsonb_build_object('id', id, 'title', title, 'status', status, 'version', version) order by created_at)
    into dups from drink_topics where dedupe_key = v_key and status <> 'duplicate';
  -- 중복 의심은 자동 병합하지 않고 사람에게 묻는다(§5.4-3).
  if dups is not null and coalesce(p -> 'confirm_not_duplicate' = 'true'::jsonb, false) is false then
    perform drinks_fail('duplicate_suggested', '같은 주종·질문·대상·각도의 소재가 이미 있습니다', dups);
  end if;
  insert into drink_topics (title, question, reader_value, categories, lane, target_subject, angle, dedupe_key,
    reader_signal_count, question_kind, discovery_platforms, interest)
  values (drinks_text(p, 'title'), drinks_text(p, 'question'), drinks_text(p, 'reader_value'), cats,
    drinks_text(p, 'lane'), drinks_text(p, 'target_subject'), drinks_text(p, 'angle'), v_key,
    greatest(coalesce(drinks_int(p, 'reader_signal_count', false), 0), 0), v_kind,
    v_platforms, v_interest)
  returning * into t;
  perform drinks_log(t.id, 'topic', t.id, 'topic_created', null, t.status, null, null,
    jsonb_build_object('possible_duplicates', coalesce(dups, '[]'), 'question_kind', t.question_kind));
  if p ? 'source' and p -> 'source' <> 'null'::jsonb then
    src := drinks_add_source_internal(t.id, p -> 'source');
  end if;
  return jsonb_build_object('topic_id', t.id, 'source', src, 'possible_duplicates', coalesce(dups, '[]'));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 3) 후보 -> 소재: 질문 유형·발견 채널·관심 신호를 복사한다 (0052 정의 대체)
--    새 소재: 운영자가 질문 유형을 골랐으면 그것, 아니면 후보 신호에서 고정 우선순위로. 채널은 후보 자료들의 플랫폼.
--    기존 소재에 붙이는 경우: 채널은 합치고, 질문 유형은 general 일 때만 채우고, 관심 신호는 비어 있을 때만 채운다
--    (이미 사람이 정한 값을 덮지 않는다. 바꿀 것이 없으면 소재 버전을 올리지 않는다).
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_promote_candidate(p jsonb) returns jsonb language plpgsql as $$
declare c drink_discovery_candidates; r jsonb; it record; links jsonb := '[]'; v_topic uuid;
  v_kind text; v_platforms text[]; v_interest jsonb; tp drink_topics;
begin
  select * into c from drink_discovery_candidates where id = drinks_uuid(p, 'candidate_id') for update;
  if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from c.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  if c.status <> 'suggested' then perform drinks_fail('invalid_state', '열린 후보만 소재로 올릴 수 있습니다'); end if;
  v_kind := coalesce(drinks_text(p, 'question_kind'), drinks_pick_question_kind(c.signals));
  if v_kind not in ('storage','misconception','selection','debate','pairing','howto','general') then
    perform drinks_fail('invalid_input', '질문 유형을 다시 고르세요');
  end if;
  v_platforms := array(select distinct d.platform from drink_candidate_items ci join drink_discovery_items d on d.id = ci.item_id
    where ci.candidate_id = c.id order by 1);
  v_interest := case when c.interest is null or c.interest = '{}'::jsonb then null else c.interest end;
  v_topic := drinks_uuid(p, 'topic_id', false);
  if v_topic is null then
    r := drinks_create_topic(jsonb_build_object('title', drinks_text(p, 'title'), 'question', drinks_text(p, 'question'),
      'categories', p -> 'categories', 'lane', coalesce(drinks_text(p, 'lane'), 'reader_question'),
      'reader_value', coalesce(drinks_text(p, 'reader_value'), c.reader_value), 'target_subject', drinks_text(p, 'target_subject'),
      'angle', drinks_text(p, 'angle'), 'question_kind', v_kind, 'discovery_platforms', to_jsonb(v_platforms),
      'interest', coalesce(v_interest, 'null'::jsonb),
      'confirm_not_duplicate', coalesce(p -> 'confirm_not_duplicate', 'false'::jsonb)));
    v_topic := (r ->> 'topic_id')::uuid;
  else
    -- 기존 소재에 신호로 더하기(병합 결정은 운영자). 중복·제외 처리된 소재에는 붙이지 않는다.
    tp := drinks_lock_topic(v_topic, null, false);
    if tp.status in ('duplicate','rejected') then
      perform drinks_fail('invalid_state', '중복·제외 처리된 소재에는 붙일 수 없습니다');
    end if;
    if not v_platforms <@ tp.discovery_platforms or (tp.question_kind = 'general' and v_kind <> 'general')
        or (tp.interest is null and v_interest is not null) then
      update drink_topics set
        discovery_platforms = array(select distinct x from unnest(tp.discovery_platforms || v_platforms) x order by 1),
        question_kind = case when tp.question_kind = 'general' then v_kind else tp.question_kind end,
        interest = coalesce(tp.interest, v_interest)
        where id = v_topic;
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
    jsonb_build_object('candidate_id', c.id, 'rubric', c.rubric, 'provisional_score', c.provisional_score, 'links', jsonb_array_length(links),
      'question_kind', v_kind, 'platforms', to_jsonb(v_platforms)));
  return jsonb_build_object('topic_id', v_topic, 'linked', jsonb_array_length(links), 'created', r is not null);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 4) 발견 수집원 등록: 선택 칸 lookback_days (0052 정의 대체 - parser_config 에 한 칸 늘었다)
--    첫 실행의 소급 기간. 엔진은 값이 없으면 전역 기본(365일)을 쓴다. 1~3650 정수만.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_register_discovery_source(p jsonb) returns jsonb language plpgsql as $$
declare
  c jsonb := drinks_discovery_connector(drinks_text(p, 'platform')); s drink_sources; cats text[];
  q text[] := drinks_text_array(p -> 'queries'); v_lookback int := drinks_int(p, 'lookback_days', false);
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
  if p ? 'lookback_days' and p -> 'lookback_days' <> 'null'::jsonb and (v_lookback is null or v_lookback < 1 or v_lookback > 3650) then
    perform drinks_fail('invalid_input', '소급 일수는 1~3650 사이의 정수여야 합니다');
  end if;
  insert into drink_sources (name, home_url, publisher, language, categories, source_kind, method, entry_urls, allowed_hosts,
    parser_config, terms_status, terms_note, terms_url, terms_checked_at, rights_default, request_interval_sec,
    max_items_per_run, max_bodies_per_run, purpose, platform, item_hosts)
  -- 대표 주소 = 커넥터 주소 + 검색어 묶음 지문. 같은 채널·같은 검색어 묶음만 중복으로 막는다(주종별로 따로 둘 수 있게).
  values (drinks_text(p, 'name'), (c ->> 'entry') || '#q=' || left(md5(array_to_string(array(select x from unnest(q) x order by 1), '|')), 12),
    drinks_text(p, 'publisher'), coalesce(drinks_text(p, 'language'), 'en'), cats,
    'community', 'api', array[c ->> 'entry'], array(select jsonb_array_elements_text(c -> 'api_hosts')),
    jsonb_build_object('queries', to_jsonb(q), 'site', coalesce(drinks_text(p, 'site'), 'alcohol'))
      || case when v_lookback is not null then jsonb_build_object('lookback_days', v_lookback) else '{}'::jsonb end,
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

-- ─────────────────────────────────────────────────────────────
-- 5) 전략: 묶음에 question_kind 를 더한다 (0055 정의 대체)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_strategy_inputs(p jsonb) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'active', (select jsonb_build_object('id', v.id, 'label', v.label, 'weights', v.weights) from drink_strategy_versions v
      where v.status = 'active'),
    'limits', drinks_publish_limits(),
    'posts', coalesce((select jsonb_agg(jsonb_build_object('request_id', r.id, 'categories', to_jsonb(t.categories),
        'lane', t.lane, 'question_kind', t.question_kind, 'post_type', r.post_type, 'slot', drinks_time_slot(r.published_at),
        'values', s.metric_values, 'unavailable', s.unavailable) order by r.published_at)
      from drink_publication_requests r join drink_topics t on t.id = r.topic_id
      join drink_post_metric_snapshots s on s.request_id = r.id and s.fetch_status <> 'failed'
        and s.age_bucket = drinks_publish_limits() ->> 'strategy_bucket'
      where r.status = 'published'), '[]'))
$$;

create or replace function drinks_save_strategy_proposal(p jsonb) returns jsonb language plpgsql as $$
declare v drink_strategy_versions; x drink_strategy_proposals; w jsonb := p -> 'weights'; d text; k text;
  v_cap numeric := (drinks_publish_limits() ->> 'strategy_max_lift')::numeric;
begin
  select * into v from drink_strategy_versions where status = 'active';
  if v.id is distinct from drinks_uuid(p, 'base_version_id') then
    perform drinks_fail('stale_strategy', '계산 중에 전략이 바뀌었습니다 — 다시 계산하세요');
  end if;
  if jsonb_typeof(w) <> 'object' then perform drinks_fail('invalid_input', '가중치 형식이 잘못됐습니다'); end if;
  for d in select jsonb_object_keys(w) loop
    if d not in ('category','post_type','lane','slot','question_kind') or jsonb_typeof(w -> d) <> 'object' then
      perform drinks_fail('invalid_input', '알 수 없는 가중치 묶음: ' || d);
    end if;
    for k in select jsonb_object_keys(w -> d) loop
      if jsonb_typeof(w -> d -> k) <> 'number' or abs((w -> d ->> k)::numeric) > v_cap then
        perform drinks_fail('invalid_input', '가중치는 ±' || v_cap || ' 안의 숫자여야 합니다: ' || d || '.' || k);
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

-- 전략 가점: 주종(여럿이면 평균)·갈래·질문 유형·더 잘 맞는 형식의 가중치를 더해 임시 점수에 곱한다(0.5~1.5배).
-- 인자가 하나 늘었으므로(질문 유형) 옛 4-인자 함수는 지운다 - 둘이 남으면 호출이 모호해진다.
drop function if exists drinks_strategy_lift(jsonb, text[], text, text[]);
create or replace function drinks_strategy_lift(w jsonb, p_cats text[], p_lane text, p_post_types text[],
  p_kind text default 'general') returns numeric
language sql immutable as $$
  select greatest(-0.5, least(0.5,
      coalesce((select avg(coalesce((w -> 'category' ->> c)::numeric, 0)) from unnest(p_cats) c), 0)
    + coalesce((w -> 'lane' ->> p_lane)::numeric, 0)
    + coalesce((w -> 'question_kind' ->> p_kind)::numeric, 0)
    + coalesce((select max(coalesce((w -> 'post_type' ->> t)::numeric, 0)) from unnest(p_post_types) t), 0)))
$$;

create or replace function drinks_strategy_rank(p jsonb) returns jsonb language sql stable as $$
  with v as (select * from drink_strategy_versions where status = 'active')
  select jsonb_build_object('strategy', (select label from v), 'weights', (select weights from v), 'topics', coalesce(jsonb_agg(x
    order by (x ->> 'adjusted_score')::numeric desc nulls last, x ->> 'title'), '[]'))
  from (select jsonb_build_object('topic_id', t.id, 'title', t.title, 'status', t.status, 'categories', to_jsonb(t.categories),
      'lane', t.lane, 'question_kind', t.question_kind, 'provisional_score', t.provisional_score,
      'lift', drinks_strategy_lift((select weights from v), t.categories, t.lane, array_remove(array[
        case when coalesce((t.provisional_scores ->> 'fit_carousel')::int, 0) >= 2 then 'carousel' end,
        case when coalesce((t.provisional_scores ->> 'fit_video')::int, 0) >= 2 then 'reel' end], null), t.question_kind),
      'adjusted_score', round(t.provisional_score * (1 + drinks_strategy_lift((select weights from v), t.categories, t.lane,
        array_remove(array[
          case when coalesce((t.provisional_scores ->> 'fit_carousel')::int, 0) >= 2 then 'carousel' end,
          case when coalesce((t.provisional_scores ->> 'fit_video')::int, 0) >= 2 then 'reel' end], null), t.question_kind)), 2)) x
    from drink_topics t where t.status in ('triaged','researching','ready')
    limit coalesce(drinks_int(p, 'limit', false), 200)) q
$$;

-- ─────────────────────────────────────────────────────────────
-- 6) 검색 경로 고정 (0056 과 같은 반복문). create or replace 는 함수에 붙은 설정을 지우므로 위에서 바꾼 함수들을 다시 고정한다.
-- ─────────────────────────────────────────────────────────────
do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_%' or p.proname like 'drink\_%')
  loop
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;
