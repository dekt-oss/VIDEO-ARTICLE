-- 주류 공장 - Apify 밈 틀 정밀화 · 월 상한 · 손으로 만드는 밈 카드 (2026-11-02). docs/deviation-drinks-stage3-4.md
-- 기획: docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md §3(결정 1), docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md §6-1·§6-5·§6-7, docs/검토_Apify도입_2026-11-01.md §8.
--
-- ★ 파일만 있다. 운영 적용은 따로 결재받는다. 0063·0066 이 먼저 적용돼 있어야 한다. 0069 는 다른 작업이 쓴다 — 이 작업의 마이그레이션은 이 파일 하나다.
--
-- 무엇:
--   drink_apify_requests     [쓰자]([이걸로]) 클릭 1회 = Apify 실행 승인 1회. 실행 상한(meme_refine $0.02 · explainer_reference $0.05)과 월 상한($3)을 DB 가 센다.
--                            넘으면 apify_budget_exhausted 로 거부하고 요청을 만들지 않는다. 결과 칸(results)에는 길이·재생 수·음원 ID·상태만 남는다 —
--                            영상·음성 주소가 들어오면 저장 자체가 거부된다(검토 §8 "영상 주소는 저장하지 않는다").
--   drinks_ig_card_use_refine 카드 [쓰자] + 정밀화 요청을 한 트랜잭션으로. 이미 정밀 틀이면 요청을 만들지 않는다(돈을 안 쓴다).
--   drinks_apify_finish      워커가 분석 결과를 카드 칸(drink_ig_card_fields, 근거 video)에 옮긴다. 운영자가 직접 넣은 칸은 덮지 않는다(0063 과 같은 규칙).
--   drinks_ig_create_manual_card 정상 관측일 전에도 운영자가 비트 수·컷 길이·반전 시점을 넣어 정밀 틀 카드를 손으로 만든다(기획 v2 §6-5 두 번째 길).
--                            0063 의 카드 만들기는 정상 관측일이 아니면 거부하므로, 그 전에는 제작으로 갈 카드가 하나도 없었다.
-- 하지 않는 것:
--   · 매일 돌지 않는다. 요청은 클릭으로만 생긴다(T4 는 정상 관측일 계산에 들어가지 않는다 - 0063 drink_ig_trend_runs 에도 적지 않는다).
--   · [이걸로] 쪽(explainer_reference)은 상한·칸만 둔다. 요청을 만드는 화면 동작은 아직 없다.
--   · 남의 영상 파일을 우리 저장소에 넣지 않는다. 워커가 분석 뒤 지우고(engine/drinks_meme_refine.py), DB 에는 메타만 온다.
-- 영향: 표 추가만. 기존 표·함수는 건드리지 않는다(drinks_ig_card_decide 도 그대로 — 새 함수가 그것을 부른다).
-- 되돌리기:
--   drop view if exists drink_apify_board, drink_apify_month_state;
--   do $$ declare f record; begin for f in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--     where n.nspname = 'public' and (p.proname like 'drinks\_apify\_%' or p.proname in ('drinks_ig_card_use_refine','drinks_ig_create_manual_card')) loop
--     execute format('drop function %s cascade', f.sig); end loop; end $$;
--   drop table if exists drink_apify_requests;
--   손으로 만든 카드(merge_key 가 manual: 으로 시작)는 drink_ig_cards 에 남는다. 지우려면 그 행과 칸·제작안을 함께 지운다.

-- ─────────────────────────────────────────────────────────────
-- 상수 (engine/config.py DRINKS_APIFY_* 와 같아야 한다)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_apify_limits() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object('month_cap_usd', 3.00, 'run_cap_usd', jsonb_build_object('meme_refine', 0.02, 'explainer_reference', 0.05),
    'max_reels', 3, 'lease_sec', 900, 'reel_usd', 0.0026, 'start_usd', 0.001, 'analysis_est_usd', 0.003)
$$;

-- 영상·음성 주소가 들어 있으면 저장하지 않는다. 결과·분석 칸 둘 다 이 검사를 받는다.
create or replace function drinks_apify_media_url_pattern() returns text language sql immutable set search_path = public, pg_temp as $$
  select '(cdninstagram|fbcdn|videoUrl|video_url|audioUrl|audio_url|download_url|"url"\s*:\s*"https?://)'::text
$$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_apify_requests (
  id               uuid primary key default gen_random_uuid(),
  kind             text not null check (kind in ('meme_refine','explainer_reference')),
  card_id          uuid references drink_ig_cards(id),
  topic_id         uuid references drink_topics(id),
  status           text not null default 'queued' check (status in ('queued','running','done','partial','failed','stopped')),
  cap_usd          numeric(8,4) not null check (cap_usd > 0),
  est_usd          numeric(8,4) not null check (est_usd >= 0),
  actual_usd       numeric(8,4) check (actual_usd is null or actual_usd >= 0),
  month_key        date not null,                       -- 서울 기준 그 달의 1일. 월 상한은 이 값으로 센다
  input_count      int not null default 0 check (input_count >= 0),
  run_id           text check (run_id is null or length(run_id) <= 100),
  results          jsonb not null default '[]' check (jsonb_typeof(results) = 'array'),
  analysis         jsonb not null default '{}' check (jsonb_typeof(analysis) = 'object'),
  fields_written   jsonb not null default '[]' check (jsonb_typeof(fields_written) = 'array'),
  error_code       text check (error_code is null or length(error_code) <= 60),
  error_message    text check (error_message is null or length(error_message) <= 2000),
  lease_token      uuid,
  lease_expires_at timestamptz,
  worker_id        text,
  requested_by     text not null default 'operator',
  created_at       timestamptz not null default now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  constraint drink_apify_owner_ck check ((card_id is null) <> (topic_id is null)),
  constraint drink_apify_kind_owner_ck check ((kind = 'meme_refine' and card_id is not null) or (kind = 'explainer_reference' and topic_id is not null)),
  constraint drink_apify_lease_ck check (status <> 'running' or lease_token is not null),
  constraint drink_apify_finished_ck check (status in ('queued','running') or finished_at is not null),
  -- 저장 자체가 거부된다: 영상·음성 주소.
  constraint drink_apify_no_media_url_ck check (results::text !~* drinks_apify_media_url_pattern() and analysis::text !~* drinks_apify_media_url_pattern())
);
-- 카드·소재 하나에 살아 있는 요청은 하나.
create unique index if not exists drink_apify_one_live_card_uq on drink_apify_requests (card_id) where card_id is not null and status in ('queued','running');
create unique index if not exists drink_apify_one_live_topic_uq on drink_apify_requests (topic_id) where topic_id is not null and status in ('queued','running');
create index if not exists drink_apify_month_idx on drink_apify_requests (month_key, status);

-- ─────────────────────────────────────────────────────────────
-- 월 상한 계산
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_apify_month_key(p_at timestamptz default now()) returns date language sql stable set search_path = public, pg_temp as $$
  select date_trunc('month', (p_at at time zone 'Asia/Seoul'))::date
$$;

-- 이달 쓴 돈: 끝난 요청은 실제 금액, 끝나지 않은 요청은 상한(아직 얼마가 될지 모르니 상한으로 잡아 둔다).
create or replace function drinks_apify_month_spent(p_month date) returns numeric language sql stable set search_path = public, pg_temp as $$
  select coalesce(sum(case when r.status in ('queued','running') then r.cap_usd else coalesce(r.actual_usd, r.est_usd) end), 0)
  from drink_apify_requests r where r.month_key = p_month
$$;

create or replace function drinks_apify_month_json(p_month date default null) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('month_key', m, 'month_cap_usd', (drinks_apify_limits() ->> 'month_cap_usd')::numeric,
    'spent_usd', drinks_apify_month_spent(m), 'remaining_usd', (drinks_apify_limits() ->> 'month_cap_usd')::numeric - drinks_apify_month_spent(m),
    'requests', (select count(*) from drink_apify_requests r where r.month_key = m),
    'run_cap_usd', drinks_apify_limits() -> 'run_cap_usd')
  from (select coalesce(p_month, drinks_apify_month_key())) x(m)
$$;

create or replace view drink_apify_month_state with (security_invoker = true) as
select (drinks_apify_month_json()) as state;

-- ─────────────────────────────────────────────────────────────
-- 운영자 동작
-- ─────────────────────────────────────────────────────────────

-- 요청 만들기. 클릭 1회 = 실행 1회 승인(기획 v2 §6-1). 월 상한을 넘으면 만들지 않는다.
create or replace function drinks_apify_request(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_kind text := drinks_text(p, 'kind'); v_card uuid := drinks_uuid(p, 'card_id', false); v_topic uuid := drinks_uuid(p, 'topic_id', false);
  v_lim jsonb := drinks_apify_limits(); v_cap numeric; v_month date := drinks_apify_month_key(); v_spent numeric; r drink_apify_requests; c drink_ig_cards; v_n int;
begin
  if v_kind is null or v_kind not in ('meme_refine','explainer_reference') then perform drinks_fail('invalid_input', '요청 종류가 잘못됐습니다'); end if;
  v_cap := (v_lim -> 'run_cap_usd' ->> v_kind)::numeric;
  if v_kind = 'meme_refine' then
    if v_card is null then perform drinks_fail('invalid_input', '카드를 지정하세요'); end if;
    select * into c from drink_ig_cards where id = v_card;
    if not found then perform drinks_fail('not_found', '카드를 찾지 못했습니다'); end if;
    if c.decision is distinct from 'use' then perform drinks_fail('invalid_state', '[쓰자]로 고른 카드만 정밀화합니다'); end if;
    select count(*) into v_n from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id where e.card_id = v_card and m.permalink is not null;
    if v_n = 0 then perform drinks_fail('no_reels', '이 카드에는 공식 API 로 받은 릴스 주소가 없어 분석할 영상이 없습니다 — 칸을 직접 넣으세요'); end if;
  else
    if v_topic is null then perform drinks_fail('invalid_input', '소재를 지정하세요'); end if;
    if not exists (select 1 from drink_topics where id = v_topic) then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  end if;
  v_spent := drinks_apify_month_spent(v_month);
  if v_spent + v_cap > (v_lim ->> 'month_cap_usd')::numeric then
    perform drinks_fail('apify_budget_exhausted', '이달 Apify 상한 $' || (v_lim ->> 'month_cap_usd') || ' 에 닿았습니다(쓴 돈 $' || round(v_spent, 3) || ') — 다음 달까지 실행하지 않습니다',
      jsonb_build_object('month', drinks_apify_month_json(v_month)));
  end if;
  begin
    insert into drink_apify_requests (kind, card_id, topic_id, cap_usd, est_usd, month_key, requested_by)
      values (v_kind, v_card, v_topic, v_cap, v_cap, v_month, coalesce(drinks_text(p, 'requested_by'), 'operator')) returning * into r;
  exception when unique_violation then
    perform drinks_fail('request_exists', '이 카드·소재에 이미 진행 중인 정밀화 요청이 있습니다');
  end;
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'cap_usd', r.cap_usd, 'month', drinks_apify_month_json(v_month), 'queued', true);
end $$;

-- [쓰자] + 정밀화 요청. 결정은 0063 함수가 그대로 기록한다. 이미 정밀 틀이면 요청을 만들지 않는다(돈을 쓸 이유가 없다).
-- 요청이 막혀도(월 상한·릴스 없음) [쓰자] 결정은 남는다 — 막힌 이유를 돌려주고, 운영자는 칸을 직접 넣어 정밀 틀로 만들 수 있다.
create or replace function drinks_ig_card_use_refine(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_id uuid := drinks_uuid(p, 'card_id'); v_dec jsonb; v_req jsonb; v_code text; v_msg text;
begin
  v_dec := drinks_ig_card_decide(jsonb_build_object('card_id', v_id, 'decision', 'use', 'note', drinks_text(p, 'note')));
  if v_dec ->> 'precision' = 'precise' then
    return v_dec || jsonb_build_object('refine', jsonb_build_object('queued', false, 'code', 'already_precise', 'message', '이미 정밀 틀이라 Apify 를 부르지 않습니다(0원)'));
  end if;
  begin
    v_req := drinks_apify_request(jsonb_build_object('kind', 'meme_refine', 'card_id', v_id));
  exception when others then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ '^drinks:' then raise; end if;
    v_code := split_part(v_msg, ':', 2);
    return v_dec || jsonb_build_object('refine', jsonb_build_object('queued', false, 'code', v_code, 'message', substring(v_msg from length('drinks:' || v_code || ':') + 1)));
  end;
  return v_dec || jsonb_build_object('refine', v_req);
end $$;

-- 손으로 만드는 정밀 틀 카드(정상 관측일 전 제작 경로). 비트 수·컷 길이·반전 시점 셋이 다 있어야 만든다.
create or replace function drinks_ig_create_manual_card(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_name text := left(drinks_text(p, 'name'), 300); v_structure text := drinks_text(p, 'structure'); v_id uuid; v_fields jsonb := coalesce(p -> 'fields', '{}'::jsonb);
  k text; v_val text; v_sync text;
begin
  if v_name is null then perform drinks_fail('invalid_input', '밈 이름을 적으세요'); end if;
  if v_structure is not null and v_structure not in ('pov','before_after','twist','list','reaction') then
    perform drinks_fail('invalid_input', '구조는 POV·전후·반전·리스트·반응 중 하나입니다');
  end if;
  if jsonb_typeof(v_fields) <> 'object' then perform drinks_fail('invalid_input', 'fields 는 객체여야 합니다'); end if;
  foreach k in array array['beat_count','cut_lengths','twist_at'] loop
    if drinks_text(v_fields, k) is null then perform drinks_fail('invalid_input', '비트 수·컷 길이·반전 시점을 모두 적어야 정밀 틀입니다(' || k || ')'); end if;
  end loop;
  if drinks_text(v_fields, 'beat_count') !~ '^[0-9]{1,2}$' then perform drinks_fail('invalid_input', '비트 수는 숫자입니다'); end if;
  if drinks_text(v_fields, 'cut_lengths') !~ '^\s*[0-9]+(\.[0-9]+)?(\s*[,/·]\s*[0-9]+(\.[0-9]+)?)*\s*$' then
    perform drinks_fail('invalid_input', '컷 길이는 초 단위 숫자 목록입니다(예: 3,3,4)');
  end if;
  if drinks_text(v_fields, 'cover_text') is not null and drinks_text(v_fields, 'cover_text') ~* drinks_meme_foreign_pattern() then
    perform drinks_fail('meme_foreign_media', '남의 게시물 주소는 칸에 넣지 않습니다');
  end if;
  insert into drink_ig_cards (merge_key, kind, name, structure, first_seen_on, last_signal_on, decision, decided_at, decision_note)
    values ('manual:' || gen_random_uuid()::text, 'structure_hook', v_name, v_structure, current_date, null, 'use', now(), left(coalesce(drinks_text(p, 'note'), '운영자가 직접 만든 카드'), 500))
    returning id into v_id;
  for k in select * from jsonb_object_keys(v_fields) loop
    v_val := left(drinks_text(v_fields, k), 1000);
    if v_val is null or k not in ('structure','cover_text','caption_hook','audio_type','beat_count','cut_lengths','twist_at','first_1_5s','music_sync') then continue; end if;
    insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values (v_id, k, v_val, 'operator', 'high');
  end loop;
  if v_structure is not null then
    insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values (v_id, 'structure', v_structure, 'operator', 'high')
      on conflict (card_id, field) do update set value = excluded.value, evidence = 'operator', confidence = 'high', set_at = now();
  end if;
  v_sync := drinks_text(v_fields, 'music_sync');
  return jsonb_build_object('card_id', v_id, 'precision', drinks_ig_card_precision(v_id), 'sync_required', drinks_meme_card_sync_required(v_id),
    'manual', true);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 전용
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_apify_reap() returns int language plpgsql set search_path = public, pg_temp as $$
declare r drink_apify_requests; v_n int := 0;
begin
  for r in select * from drink_apify_requests where status = 'running' and lease_expires_at < now() for update skip locked loop
    -- 워커가 사라졌다. 얼마가 나갔는지 모르니 상한을 실제 금액으로 적어 월 상한을 지킨다.
    update drink_apify_requests set status = 'failed', error_code = 'worker_lost', error_message = '워커가 끝내지 못했습니다 — 금액은 상한으로 적었습니다',
      actual_usd = cap_usd, lease_token = null, lease_expires_at = null, finished_at = now() where id = r.id;
    v_n := v_n + 1;
  end loop;
  return v_n;
end $$;

create or replace function drinks_apify_claim(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_apify_requests; v_reaped int; v_token uuid := gen_random_uuid(); v_lim jsonb := drinks_apify_limits(); v_card jsonb; v_reels jsonb; v_hooks jsonb;
begin
  v_reaped := drinks_apify_reap();
  select * into r from drink_apify_requests where status = 'queued' and kind = coalesce(drinks_text(p, 'kind'), 'meme_refine')
    order by created_at, id limit 1 for update skip locked;
  if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
  -- 월 상한을 다시 본다(요청이 쌓인 사이 다른 실행이 돈을 썼을 수 있다). 이 요청 자신의 상한은 이미 spent 에 들어 있다.
  if drinks_apify_month_spent(r.month_key) > (v_lim ->> 'month_cap_usd')::numeric then
    update drink_apify_requests set status = 'stopped', error_code = 'apify_budget_exhausted', error_message = '이달 상한에 닿아 실행하지 않았습니다', actual_usd = 0, finished_at = now() where id = r.id;
    return jsonb_build_object('job', null, 'reaped', v_reaped, 'stopped', r.id);
  end if;
  update drink_apify_requests set status = 'running', lease_token = v_token, lease_expires_at = now() + make_interval(secs => (v_lim ->> 'lease_sec')::int),
    worker_id = drinks_text(p, 'worker_id'), started_at = now() where id = r.id returning * into r;
  if r.card_id is not null then
    v_card := drinks_meme_card_json(r.card_id);
    -- 공식 API 가 이미 고른 릴스만 보낸다(기획 v2 §6-1). 조회수 높은 순, 상한 3개.
    select coalesce(jsonb_agg(jsonb_build_object('media_id', x.media_id, 'username', x.username, 'permalink', x.permalink, 'view_count', x.view_count)), '[]') into v_reels
      from (select e.media_id, m.username, m.permalink,
              (select o.view_count from drink_ig_media_observations o where o.media_id = e.media_id order by o.observed_on desc limit 1) as view_count
            from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id
            where e.card_id = r.card_id and m.permalink is not null
            order by 4 desc nulls last, e.media_id limit (v_lim ->> 'max_reels')::int) x;
    select coalesce(jsonb_agg(h), '[]') into v_hooks from (
      select f.value as h from drink_ig_card_fields f where f.card_id = r.card_id and f.field in ('cover_text','caption_hook')
      union all
      select m.caption_hook from drink_ig_card_examples e join drink_ig_media m on m.media_id = e.media_id where e.card_id = r.card_id and m.caption_hook is not null) x;
  end if;
  return jsonb_build_object('reaped', v_reaped, 'job', jsonb_build_object('request_id', r.id, 'lease_token', r.lease_token, 'kind', r.kind,
    'cap_usd', r.cap_usd, 'card', v_card, 'reels', coalesce(v_reels, '[]'), 'hooks', coalesce(v_hooks, '[]'),
    'month', drinks_apify_month_json(r.month_key), 'limits', v_lim));
end $$;

create or replace function drinks_apify_lock_lease(p jsonb) returns drink_apify_requests language plpgsql set search_path = public, pg_temp as $$
declare r drink_apify_requests;
begin
  select * into r from drink_apify_requests where id = drinks_uuid(p, 'request_id') for update;
  if not found or r.status <> 'running' or r.lease_token is distinct from drinks_uuid(p, 'lease_token') then
    perform drinks_fail('lease_lost', '이 작업의 임대를 잃었습니다');
  end if;
  return r;
end $$;

-- 끝. 결과(메타만)·실제 금액·분석 칸을 적고, 영상 근거 칸을 카드에 옮긴다. 운영자 입력 칸은 덮지 않는다.
create or replace function drinks_apify_finish(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  r drink_apify_requests; v_out text := drinks_text(p, 'outcome'); v_results jsonb := coalesce(p -> 'results', '[]'); v_analysis jsonb := coalesce(p -> 'analysis', '{}');
  v_fields jsonb := coalesce(p -> 'fields', '[]'); it jsonb; v_written jsonb := '[]'; v_actual numeric; v_n int;
begin
  r := drinks_apify_lock_lease(p);
  if v_out is null or v_out not in ('done','partial','failed','stopped') then perform drinks_fail('invalid_input', 'outcome 은 done·partial·failed·stopped 입니다'); end if;
  if jsonb_typeof(v_results) <> 'array' or jsonb_typeof(v_analysis) <> 'object' or jsonb_typeof(v_fields) <> 'array' then
    perform drinks_fail('invalid_input', 'results 는 배열, analysis 는 객체, fields 는 배열이어야 합니다');
  end if;
  if v_results::text ~* drinks_apify_media_url_pattern() or v_analysis::text ~* drinks_apify_media_url_pattern() then
    perform drinks_fail('media_url_rejected', '영상·음성 주소는 저장하지 않습니다 — 메타만 보내세요');
  end if;
  begin
    v_actual := nullif(btrim(p ->> 'actual_usd'), '')::numeric;
  exception when others then
    perform drinks_fail('invalid_input', 'actual_usd 는 숫자여야 합니다');
  end;
  if v_actual is null then v_actual := case when v_out = 'stopped' then 0 else r.cap_usd end; end if;   -- 모르면 상한으로 적는다(월 상한을 지킨다)
  if v_out in ('done','partial') and r.card_id is not null then
    for it in select * from jsonb_array_elements(v_fields) loop
      if drinks_text(it, 'field') not in ('structure','cover_text','caption_hook','audio_type','beat_count','cut_lengths','twist_at','first_1_5s','music_sync') then
        perform drinks_fail('invalid_input', '없는 칸입니다: ' || coalesce(drinks_text(it, 'field'), '(없음)'));
      end if;
      if drinks_text(it, 'evidence') <> 'video' then perform drinks_fail('invalid_input', '정밀화는 영상 근거(video)로만 칸을 채웁니다'); end if;
      if drinks_text(it, 'value') is null then continue; end if;
      insert into drink_ig_card_fields (card_id, field, value, evidence, confidence)
        values (r.card_id, drinks_text(it, 'field'), left(drinks_text(it, 'value'), 1000), 'video', coalesce(drinks_text(it, 'confidence'), 'low'))
        on conflict (card_id, field) do update set value = excluded.value, evidence = 'video', confidence = excluded.confidence, set_at = now()
        where drink_ig_card_fields.evidence <> 'operator';
      get diagnostics v_n = row_count;
      if v_n > 0 then v_written := v_written || to_jsonb(drinks_text(it, 'field')); end if;
      if drinks_text(it, 'field') = 'structure' and v_n > 0 and drinks_text(it, 'value') in ('pov','before_after','twist','list','reaction') then
        update drink_ig_cards set structure = drinks_text(it, 'value') where id = r.card_id and structure is null;
      end if;
    end loop;
  end if;
  update drink_apify_requests set status = v_out, results = v_results, analysis = v_analysis, fields_written = v_written, actual_usd = v_actual,
    run_id = left(drinks_text(p, 'run_id'), 100), input_count = coalesce(drinks_int(p, 'input_count', false), input_count),
    error_code = left(drinks_text(p, 'error_code'), 60), error_message = left(drinks_text(p, 'error_message'), 2000),
    lease_token = null, lease_expires_at = null, finished_at = now() where id = r.id returning * into r;
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'actual_usd', r.actual_usd, 'fields_written', r.fields_written,
    'precision', case when r.card_id is null then null else drinks_ig_card_precision(r.card_id) end, 'month', drinks_apify_month_json(r.month_key));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 화면용 보기 · 권한
-- ─────────────────────────────────────────────────────────────

create or replace view drink_apify_board with (security_invoker = true) as
select r.id, r.kind, r.card_id, r.topic_id, r.status, r.cap_usd, r.est_usd, r.actual_usd, r.month_key, r.input_count, r.run_id, r.results, r.analysis,
  r.fields_written, r.error_code, r.error_message, r.created_at, r.started_at, r.finished_at,
  coalesce(c.name, t.title) as owner_name,
  case when r.card_id is null then null else drinks_ig_card_precision(r.card_id) end as precision
from drink_apify_requests r
left join drink_ig_cards c on c.id = r.card_id
left join drink_topics t on t.id = r.topic_id;

alter table drink_apify_requests enable row level security;
revoke all on table drink_apify_requests, drink_apify_board, drink_apify_month_state from anon, authenticated;
grant select, insert, update on table drink_apify_requests to service_role;
grant select on table drink_apify_board, drink_apify_month_state to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_apify\_%' or p.proname in ('drinks_ig_card_use_refine','drinks_ig_create_manual_card'))
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
  end loop;
end $$;
