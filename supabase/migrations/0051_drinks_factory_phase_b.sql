-- 주류 공장 B단계 — 수집원 등록부·수집 실행 기록·수집 문서 → 소재 후보 (2026-10-22)
--
-- 명세: docs/주류공장_구조명세_v1_2026-10-21.md §5·§13-B. 구현 결정: docs/deviation-drinks-phase-b.md
-- 0050(A단계) 위에 쌓는다. 0050 은 고치지 않는다.
--
-- 무엇을 만드나:
--   drink_sources            수집원 등록부. proposed → validated → active, paused / retired.
--                            **자동 활성화 없음** — 상태는 운영자 동작(drinks_source_action)으로만 바뀐다.
--   drink_collection_runs    수집원 하나의 실행 1회. 시작·끝·건수·오류·재시도 범위.
--                            정상 0건(empty) / 성공 / 부분 성공(partial) / 실패 / 실행 중단(aborted) 을 가른다.
--   drink_collection_items   실행 안의 문서 1건 결과(새 스냅샷·바뀐 본문·변화 없음·제목만·건너뜀·실패).
--   drink_source_snapshots   ← capture_method 'collected' + 어느 수집원·실행에서 왔는지(0050 확장)
--   drink_topics             ← 경량 평가 사유·조사 필요 사항(triage_reason, research_needs)
--
-- 지키는 것:
--   · 워처마크는 **성공(succeeded·empty)한 수집 실행만** 올린다. 부분 성공·실패·중단은 그대로 둔다.
--   · 수집원 하나에 대기·실행 중인 실행은 하나뿐(부분 고유 인덱스). 같은 실행에서 같은 URL 은 한 번(고유 키).
--   · 실행 임대(lease) 가 끝난 실행은 다음 워커가 'aborted(lease_expired)' 로 닫는다 — running 에 멈춰 있지 않다.
--   · 실행 1회 상한(문서 100·본문 20)과 하루 실행 수 상한, 활성 수집원 수 상한(12)은 DB 가 막는다.
--   · 수집 본문은 신뢰하지 않는 데이터다 — 저장만 하고, 승인·편성·근거 판정은 A단계 규칙(사람)을 그대로 탄다.
--   · 신규 표·함수는 anon/authenticated 에 아무 권한도 주지 않는다.
--
-- 되돌리기: 아래 표 3개와 이 파일의 drinks_* 함수를 drop 하고, 0050 의 drink_snapshots_guard·drinks_triage·
--   drink_workflow_events 체크를 0050 정의로 되돌린 뒤 drink_source_snapshots·drink_topics 의 추가 칸을 drop 한다.

-- ─────────────────────────────────────────────────────────────
-- 상한 — engine/config.py 의 DRINKS_* 와 같은 값이어야 한다(tests/test_drinks_phase_b.py 가 대조)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_collect_limits() returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'max_active_sources', 12,     -- 동시에 active 인 수집원 수
    'max_items_ceiling', 100,     -- 실행 1회 문서(메타데이터) 상한 — 수집원 설정은 이 값 이하만
    'max_bodies_ceiling', 20,     -- 실행 1회 본문 수집 상한
    'runs_per_day', 4,            -- 수집원 하나의 24시간 실행 수(예약 1 + 수동 재시도 여유)
    'lease_sec', 900,             -- 실행 임대 시간. 하트비트가 연장한다
    'queued_ttl_hours', 24,       -- 이보다 오래 대기한 실행은 중단 처리
    'min_interval_sec', 3         -- 요청 간 최소 간격(수집원 설정의 하한)
  )
$$;

create or replace function drinks_limit(k text) returns int language sql immutable as $$
  select (drinks_collect_limits() ->> k)::int
$$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_sources (
  id                    uuid primary key default gen_random_uuid(),
  name                  text not null check (length(btrim(name)) between 1 and 120),
  home_url              text not null check (home_url ~ '^https://'),
  publisher             text,
  language              text not null check (language ~ '^[a-z]{2}$'),
  categories            text[] not null check (cardinality(categories) between 1 and 3
                          and categories <@ array['sake','traditional','whisky']::text[]),
  source_kind           text not null default 'official' check (source_kind in
                          ('official','expert','manufacturer','importer','media','retailer','community','reader','other')),
  -- manual_url: 수집하지 않는다(사람이 URL 을 등록할 때 쓰는 출처 기록) / approved_page: 승인한 고정 페이지 목록 /
  -- listing: 승인한 목록 페이지 1개에서 같은 경로 아래 글 링크를 따라간다 / feed: 확인된 RSS·Atom 피드
  method                text not null check (method in ('manual_url','approved_page','listing','feed')),
  entry_urls            text[] not null default '{}' check (cardinality(entry_urls) <= 20),
  allowed_hosts         text[] not null default '{}' check (cardinality(allowed_hosts) <= 5),
  parser_config         jsonb not null default '{}' check (jsonb_typeof(parser_config) = 'object'),
  parser_version        text not null default 'drinks-html-v1',
  terms_status          text not null default 'unverified' check (terms_status in ('unverified','verified','restricted')),
  terms_note            text,
  terms_url             text check (terms_url is null or terms_url ~ '^https?://'),
  terms_checked_at      date,
  robots_note           text,
  rights_default        text not null default 'unknown' check (rights_default in
                          ('unknown','quote_ok','summary_only','restricted')),
  request_interval_sec  int not null default 5 check (request_interval_sec between 3 and 120),
  max_items_per_run     int not null default 100 check (max_items_per_run between 1 and 100),
  max_bodies_per_run    int not null default 20 check (max_bodies_per_run between 0 and 20),
  state                 text not null default 'proposed' check (state in ('proposed','validated','active','paused','retired')),
  state_reason          text,
  watermark_at          timestamptz,              -- 마지막으로 **완전히 성공한** 수집 실행의 시작 시각
  last_success_run_id   uuid,
  last_validation_run_id uuid,
  version               int not null default 1,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  check (method = 'manual_url' or (cardinality(entry_urls) >= 1 and cardinality(allowed_hosts) >= 1)),
  check (method <> 'listing' or cardinality(entry_urls) = 1),
  check (method <> 'feed' or cardinality(entry_urls) = 1),
  check (state <> 'active' or (terms_status = 'verified' and method <> 'manual_url'))
);
create unique index if not exists drink_sources_home_uq on drink_sources (home_url, method) where state <> 'retired';

create table if not exists drink_collection_runs (
  id               uuid primary key default gen_random_uuid(),
  source_id        uuid not null references drink_sources(id),
  mode             text not null check (mode in ('collect','validate','retry')),
  retry_of         uuid references drink_collection_runs(id),
  retry_urls       text[] not null default '{}' check (cardinality(retry_urls) <= 100),
  requested_by     text not null check (requested_by in ('operator','schedule')),
  scheduled_for    date,                            -- 예약 실행의 날짜(TIMEZONE 기준). 같은 날 두 번 예약 안 됨
  status           text not null default 'queued' check (status in
                     ('queued','running','succeeded','empty','partial','failed','aborted')),
  lease_token      uuid,
  lease_expires_at timestamptz,
  heartbeat_at     timestamptz,
  worker_id        text,
  started_at       timestamptz,
  finished_at      timestamptz,
  limits           jsonb,                           -- 시작 시점의 상한(수집원 설정을 복사) — 나중에 설정이 바뀌어도 기록 유지
  cursor_from      timestamptz,                     -- 시작 시점 워처마크
  cursor_to        timestamptz,                     -- 성공 시 새 워처마크(=started_at). 실패·부분이면 null
  listed_count     int not null default 0,
  item_count       int not null default 0,
  body_count       int not null default 0,
  new_count        int not null default 0,
  changed_count    int not null default 0,
  unchanged_count  int not null default 0,
  metadata_count   int not null default 0,
  skipped_count    int not null default 0,
  failed_count     int not null default 0,
  request_count    int not null default 0,
  error_code       text,
  error_message    text check (error_message is null or length(error_message) <= 2000),
  created_at       timestamptz not null default now(),
  check ((mode = 'retry') = (retry_of is not null)),
  check (mode = 'retry' or cardinality(retry_urls) = 0),
  check ((requested_by = 'schedule') = (scheduled_for is not null)),
  check (status not in ('running') or (lease_token is not null and started_at is not null)),
  check (status in ('queued','running') or finished_at is not null)
);
create unique index if not exists drink_runs_one_active_uq on drink_collection_runs (source_id)
  where status in ('queued','running');
create unique index if not exists drink_runs_one_schedule_uq on drink_collection_runs (source_id, scheduled_for)
  where scheduled_for is not null;
create index if not exists drink_runs_source_idx on drink_collection_runs (source_id, created_at desc);
create index if not exists drink_runs_status_idx on drink_collection_runs (status, created_at);

create table if not exists drink_collection_items (
  id               bigint generated always as identity primary key,
  run_id           uuid not null references drink_collection_runs(id),
  source_id        uuid not null references drink_sources(id),
  canonical_url    text not null check (canonical_url ~ '^https?://'),
  url_raw          text,
  status           text not null check (status in
                     ('new','changed','unchanged','metadata_only','skipped','failed','checked')),
  http_status      int,
  error_code       text,
  error_message    text check (error_message is null or length(error_message) <= 1000),
  title            text check (title is null or length(title) <= 500),
  summary          text check (summary is null or length(summary) <= 2000),
  published_at     date,
  body_chars       int,
  snapshot_id      uuid references drink_source_snapshots(id),
  same_body_count  int not null default 0,
  attempt          int not null default 1 check (attempt between 1 and 3),
  created_at       timestamptz not null default now(),
  unique (run_id, canonical_url),
  check (status not in ('new','changed') or snapshot_id is not null),
  check (status <> 'failed' or error_code is not null),
  check (status <> 'skipped' or error_code is not null)
);
create index if not exists drink_items_source_idx on drink_collection_items (source_id, id desc);
create index if not exists drink_items_snapshot_idx on drink_collection_items (snapshot_id);

-- ─────────────────────────────────────────────────────────────
-- 0050 확장: 수집된 스냅샷의 출처 · 경량 평가 사유 · 수집원/실행 이력
-- ─────────────────────────────────────────────────────────────

alter table drink_source_snapshots add column if not exists collected_source_id uuid references drink_sources(id);
alter table drink_source_snapshots add column if not exists collected_run_id uuid references drink_collection_runs(id);
alter table drink_source_snapshots drop constraint if exists drink_source_snapshots_capture_method_check;
alter table drink_source_snapshots drop constraint if exists drink_snapshots_capture_ck;
alter table drink_source_snapshots add constraint drink_snapshots_capture_ck check (
  (capture_method = 'manual' and collected_run_id is null and collected_source_id is null)
  or (capture_method = 'collected' and collected_run_id is not null and collected_source_id is not null
      and canonical_url is not null));

alter table drink_topics add column if not exists triage_reason text check (triage_reason is null or length(triage_reason) <= 1000);
alter table drink_topics add column if not exists research_needs text check (research_needs is null or length(research_needs) <= 2000);

alter table drink_workflow_events drop constraint if exists drink_workflow_events_entity_type_check;
alter table drink_workflow_events drop constraint if exists drink_events_entity_ck;
alter table drink_workflow_events add constraint drink_events_entity_ck
  check (entity_type in ('topic','snapshot','review','deliverable','plan','source','run'));

-- 스냅샷 입력: 수집 함수가 거래 안에서 'drinks.capture' 를 켠 경우에만 collected 로 남는다.
-- 그 밖의 입력(수동 등록·직접 INSERT)은 0050 처럼 manual 로 강제하고 수집 출처 칸을 비운다.
create or replace function drink_snapshots_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'INSERT' then
    if new.body_text is not null and btrim(new.body_text) = '' then new.body_text := null; end if;
    if new.body_text is null then new.depth := 'metadata_only';
    elsif new.depth is null or new.depth = 'metadata_only' then new.depth := 'excerpt'; end if;
    new.content_hash := drinks_body_hash(new.body_text);
    if coalesce(current_setting('drinks.capture', true), '') = 'collected' then
      new.capture_method := 'collected';
    else
      new.capture_method := 'manual';
      new.collected_source_id := null;
      new.collected_run_id := null;
    end if;
    return new;
  elsif tg_op = 'UPDATE' then
    if (to_jsonb(new) - 'origin_group') is distinct from (to_jsonb(old) - 'origin_group') then
      perform drinks_fail('immutable', '출처 스냅샷은 수정할 수 없습니다 — 정보 정정·재확인은 기록으로 남기세요');
    end if;
    return new;
  end if;
  perform drinks_fail('immutable', '출처 스냅샷은 삭제할 수 없습니다');
  return null;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 불변·전이 트리거
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_source_transition_ok(a text, b text) returns boolean
language sql immutable as $$
  select a = b or (a, b) in (
    ('proposed','validated'), ('proposed','retired'),
    ('validated','active'), ('validated','proposed'), ('validated','retired'),
    ('active','paused'), ('active','retired'),
    ('paused','active'), ('paused','validated'), ('paused','retired'))
$$;

create or replace function drink_sources_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '수집원은 삭제할 수 없습니다(종료를 쓰세요)'); end if;
  if tg_op = 'INSERT' then
    if new.state <> 'proposed' then
      perform drinks_fail('invalid_state', '수집원은 제안(proposed) 상태로만 등록됩니다 — 자동 활성화는 없습니다');
    end if;
    return new;
  end if;
  if old.state = 'retired' and to_jsonb(new) is distinct from to_jsonb(old) then
    perform drinks_fail('immutable', '종료한 수집원은 바꿀 수 없습니다');
  end if;
  if not drinks_source_transition_ok(old.state, new.state) then
    perform drinks_fail('invalid_transition', old.state || ' → ' || new.state || ' 전이는 허용되지 않습니다');
  end if;
  -- 활성화는 함수를 우회한 직접 UPDATE 로도 조건을 넘지 못한다.
  if new.state = 'active' and old.state <> 'active' then
    if new.terms_status <> 'verified' then
      perform drinks_fail('terms_unverified', '이용 조건을 확인(verified)한 수집원만 활성화할 수 있습니다');
    end if;
    -- "가장 최근에 끝난" 검증 실행이 성공이어야 한다 — 옛 성공 뒤에 실패한 검증이 있으면 막는다.
    if coalesce((select r.status from drink_collection_runs r where r.source_id = new.id and r.mode = 'validate'
        and r.status not in ('queued','running') order by r.finished_at desc, r.created_at desc limit 1), '') <> 'succeeded' then
      perform drinks_fail('not_validated', '가장 최근 검증 실행이 성공한 수집원만 활성화할 수 있습니다');
    end if;
    -- 두 활성화가 동시에 11개를 세고 둘 다 통과하지 않게 활성화끼리 줄을 세운다.
    perform pg_advisory_xact_lock(hashtext('drink_sources_activate'));
    if (select count(*) from drink_sources s where s.state = 'active' and s.id <> new.id) >= drinks_limit('max_active_sources') then
      perform drinks_fail('active_limit', '활성 수집원은 ' || drinks_limit('max_active_sources') || '개까지입니다');
    end if;
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists drink_sources_guard on drink_sources;
create trigger drink_sources_guard before insert or update or delete on drink_sources
  for each row execute function drink_sources_guard();

-- 끝난 실행은 고칠 수 없다. 상태 전이는 queued → running → (종료) 또는 queued → aborted 만.
create or replace function drink_runs_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '실행 기록은 삭제할 수 없습니다'); end if;
  if tg_op = 'UPDATE' then
    if old.status not in ('queued','running') then
      perform drinks_fail('immutable', '끝난 실행 기록은 바꿀 수 없습니다');
    end if;
    if (old.status, new.status) not in (('queued','queued'), ('queued','running'), ('queued','aborted'),
        ('running','running'), ('running','succeeded'), ('running','empty'), ('running','partial'),
        ('running','failed'), ('running','aborted')) then
      perform drinks_fail('invalid_transition', '실행 상태 ' || old.status || ' → ' || new.status || ' 는 허용되지 않습니다');
    end if;
    if new.source_id <> old.source_id or new.mode <> old.mode or new.retry_of is distinct from old.retry_of
        or new.retry_urls <> old.retry_urls or new.requested_by <> old.requested_by then
      perform drinks_fail('immutable', '실행의 대상·종류는 바꿀 수 없습니다');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_runs_guard on drink_collection_runs;
create trigger drink_runs_guard before update or delete on drink_collection_runs
  for each row execute function drink_runs_guard();

drop trigger if exists drink_items_append_only on drink_collection_items;
create trigger drink_items_append_only before update or delete on drink_collection_items
  for each row execute function drink_append_only_guard();

-- ─────────────────────────────────────────────────────────────
-- 헬퍼
-- ─────────────────────────────────────────────────────────────

-- 수집원 등록부의 URL·호스트 검사. 공개 https 만, 계정 정보·포트·IP 리터럴·내부 이름 금지.
-- (실제 요청 경로의 검사 — DNS 해석 결과·리다이렉트·응답 크기 — 는 engine/drinks_fetch.py 가 한다.)
create or replace function drinks_host_ok(h text) returns boolean language sql immutable as $$
  select h ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'
    and h !~ '^[0-9.]+$'
    and h !~ '(^|\.)(localhost|local|internal|lan|home|corp|intranet)$'
$$;

create or replace function drinks_url_host(u text) returns text language sql immutable as $$
  select lower(substring(u from '^https://([^/:?#@]+)(/|$|\?)'))
$$;

create or replace function drinks_entry_url_ok(u text) returns boolean language sql immutable as $$
  select u ~ '^https://[^/:?#@\s]+(/[^\s]*)?$' and drinks_host_ok(drinks_url_host(u))
$$;

create or replace function drinks_log_source(p_source uuid, p_type text, p_id uuid, p_action text,
  p_before text, p_after text, p_reason text, p_detail jsonb default '{}', p_actor text default 'operator')
returns void language sql as $$
  insert into drink_workflow_events (topic_id, entity_type, entity_id, action, actor, before_status, after_status,
    version_ref, reason, detail)
  values (null, p_type, p_id, p_action, p_actor, p_before, p_after, p_source::text, p_reason, coalesce(p_detail, '{}'));
$$;

create or replace function drinks_lock_source(p_id uuid, p_expected int) returns drink_sources
language plpgsql as $$
declare s drink_sources;
begin
  if p_id is null then perform drinks_fail('invalid_input', 'source_id 가 필요합니다'); end if;
  select * into s from drink_sources where id = p_id for update;
  if not found then perform drinks_fail('not_found', '수집원을 찾지 못했습니다'); end if;
  if p_expected is not null and s.version <> p_expected then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요',
      jsonb_build_object('current_version', s.version));
  end if;
  return s;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 수집원 RPC (운영자 화면 → 라우트 → service_role)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_register_source(p jsonb) returns jsonb language plpgsql as $$
declare
  s drink_sources; v_method text := drinks_text(p, 'method'); urls text[]; hosts text[]; u text; cats text[];
begin
  if drinks_text(p, 'name') is null then perform drinks_fail('invalid_input', '수집원 이름을 입력하세요'); end if;
  if not coalesce(drinks_entry_url_ok(drinks_text(p, 'home_url')), false) then
    perform drinks_fail('invalid_input', '대표 주소는 공개 https:// 주소여야 합니다(IP·내부 주소·포트·계정 정보 금지)');
  end if;
  if coalesce(v_method, '') not in ('manual_url','approved_page','listing','feed') then
    perform drinks_fail('invalid_input', '수집 방법을 고르세요');
  end if;
  if coalesce(drinks_text(p, 'language'), '') !~ '^[a-z]{2}$' then
    perform drinks_fail('invalid_input', '언어 코드는 두 글자(ko·ja·en)로 넣으세요');
  end if;
  cats := drinks_text_array(p -> 'categories');
  if cardinality(cats) = 0 or not cats <@ array['sake','traditional','whisky'] then
    perform drinks_fail('invalid_input', '주종은 사케·전통주·위스키 중에서 고르세요');
  end if;
  if drinks_text(p, 'terms_status') = 'verified' and (drinks_text(p, 'terms_note') is null or drinks_date(p, 'terms_checked_at') is null) then
    perform drinks_fail('invalid_input', '이용 조건을 확인됨으로 등록하려면 요지와 확인일을 적으세요');
  end if;
  urls := drinks_text_array(p -> 'entry_urls');
  if v_method = 'manual_url' then urls := '{}'; end if;
  foreach u in array urls loop
    if not drinks_entry_url_ok(u) then
      perform drinks_fail('invalid_input', '수집 주소는 공개 https:// 주소여야 합니다: ' || u);
    end if;
  end loop;
  -- 허용 호스트는 수집 주소에서만 만든다(입력으로 넓힐 수 없다). 리다이렉트도 이 호스트 밖으로 못 나간다.
  hosts := array(select distinct drinks_url_host(x) from unnest(urls) x order by 1);
  begin
    insert into drink_sources (name, home_url, publisher, language, categories, source_kind, method, entry_urls,
      allowed_hosts, parser_config, terms_status, terms_note, terms_url, terms_checked_at, robots_note, rights_default,
      request_interval_sec, max_items_per_run, max_bodies_per_run)
    values (drinks_text(p, 'name'), drinks_text(p, 'home_url'), drinks_text(p, 'publisher'), drinks_text(p, 'language'), cats,
      coalesce(drinks_text(p, 'source_kind'), 'official'), v_method, urls, hosts,
      coalesce(case when jsonb_typeof(p -> 'parser_config') = 'object' then p -> 'parser_config' end, '{}'),
      coalesce(drinks_text(p, 'terms_status'), 'unverified'), drinks_text(p, 'terms_note'), drinks_text(p, 'terms_url'),
      drinks_date(p, 'terms_checked_at'), drinks_text(p, 'robots_note'), coalesce(drinks_text(p, 'rights_default'), 'unknown'),
      coalesce(drinks_int(p, 'request_interval_sec', false), 5),
      coalesce(drinks_int(p, 'max_items_per_run', false), drinks_limit('max_items_ceiling')),
      coalesce(drinks_int(p, 'max_bodies_per_run', false), drinks_limit('max_bodies_ceiling')))
    returning * into s;
  exception when unique_violation then
    perform drinks_fail('duplicate_source', '같은 주소·방법의 수집원이 이미 있습니다');
  end;
  perform drinks_log_source(s.id, 'source', s.id, 'source_registered', null, s.state, null,
    jsonb_build_object('method', s.method, 'terms_status', s.terms_status));
  return jsonb_build_object('source_id', s.id, 'state', s.state, 'version', s.version);
end $$;

-- 수집원 상태·설정 동작. 전부 운영자 동작이다 — 워커는 이 함수를 부르지 않는다.
create or replace function drinks_source_action(p jsonb) returns jsonb language plpgsql as $$
declare
  s drink_sources; v_action text := drinks_text(p, 'action'); v_reason text := drinks_text(p, 'reason');
  v_before text; v_terms text;
begin
  perform drinks_reap_runs();  -- 임대가 끝난 실행이 [종료]·상태 변경을 막고 있지 않게 먼저 닫는다
  s := drinks_lock_source(drinks_uuid(p, 'source_id'), drinks_int(p, 'expected_version'));
  v_before := s.state;
  if v_action = 'validate' then
    if s.state <> 'proposed' then perform drinks_fail('invalid_state', '제안 상태에서만 검증 완료로 바꿀 수 있습니다'); end if;
    if s.method = 'manual_url' then perform drinks_fail('invalid_state', '수동 등록 출처는 수집하지 않으므로 검증할 것이 없습니다'); end if;
    if s.terms_status = 'restricted' then perform drinks_fail('terms_restricted', '이용 조건이 수집을 막는 출처입니다'); end if;
    if coalesce((select r.status from drink_collection_runs r where r.id = s.last_validation_run_id), '') <> 'succeeded' then
      perform drinks_fail('not_validated', '가장 최근 검증 실행이 성공해야 합니다 — 먼저 [검증 실행]을 돌리세요');
    end if;
    update drink_sources set state = 'validated', state_reason = v_reason where id = s.id returning * into s;
  elsif v_action = 'activate' then
    if s.state not in ('validated','paused') then
      perform drinks_fail('invalid_state', '검증 완료·일시 중지 상태에서만 활성화할 수 있습니다');
    end if;
    update drink_sources set state = 'active', state_reason = v_reason where id = s.id returning * into s;
  elsif v_action = 'pause' then
    if s.state <> 'active' then perform drinks_fail('invalid_state', '활성 수집원만 일시 중지할 수 있습니다'); end if;
    if v_reason is null then perform drinks_fail('invalid_input', '일시 중지 사유를 적으세요'); end if;
    update drink_sources set state = 'paused', state_reason = v_reason where id = s.id returning * into s;
  elsif v_action = 'retire' then
    if s.state = 'retired' then perform drinks_fail('invalid_state', '이미 종료했습니다'); end if;
    if v_reason is null then perform drinks_fail('invalid_input', '종료 사유를 적으세요'); end if;
    if exists (select 1 from drink_collection_runs r where r.source_id = s.id and r.status in ('queued','running')) then
      perform drinks_fail('run_in_progress', '진행 중인 실행이 끝난 뒤 종료하세요');
    end if;
    update drink_sources set state = 'retired', state_reason = v_reason where id = s.id returning * into s;
  elsif v_action = 'update_terms' then
    v_terms := drinks_text(p, 'terms_status');
    if coalesce(v_terms, '') not in ('unverified','verified','restricted') then
      perform drinks_fail('invalid_input', '이용 조건 상태를 고르세요');
    end if;
    if v_terms = 'verified' and (drinks_text(p, 'terms_note') is null or drinks_date(p, 'terms_checked_at') is null) then
      perform drinks_fail('invalid_input', '확인한 이용 조건 요지와 확인일을 적으세요');
    end if;
    -- 조건이 확인됨에서 내려가면 수집을 멈춘다(활성 → 일시 중지). 다시 켜는 것은 사람이 한다.
    update drink_sources set terms_status = v_terms, terms_note = coalesce(drinks_text(p, 'terms_note'), terms_note),
      terms_url = coalesce(drinks_text(p, 'terms_url'), terms_url),
      terms_checked_at = coalesce(drinks_date(p, 'terms_checked_at'), terms_checked_at),
      rights_default = coalesce(drinks_text(p, 'rights_default'), rights_default),
      state = case when state = 'active' and v_terms <> 'verified' then 'paused' else state end,
      state_reason = case when state = 'active' and v_terms <> 'verified' then '이용 조건 재확인 필요' else state_reason end
      where id = s.id returning * into s;
  elsif v_action = 'update_limits' then
    update drink_sources set
      request_interval_sec = coalesce(drinks_int(p, 'request_interval_sec', false), request_interval_sec),
      max_items_per_run = coalesce(drinks_int(p, 'max_items_per_run', false), max_items_per_run),
      max_bodies_per_run = coalesce(drinks_int(p, 'max_bodies_per_run', false), max_bodies_per_run)
      where id = s.id returning * into s;
  else
    perform drinks_fail('invalid_input', '알 수 없는 수집원 동작입니다');
  end if;
  perform drinks_log_source(s.id, 'source', s.id, 'source_' || v_action, v_before, s.state, v_reason,
    jsonb_build_object('terms_status', s.terms_status, 'limits', jsonb_build_object('interval', s.request_interval_sec,
      'items', s.max_items_per_run, 'bodies', s.max_bodies_per_run)));
  return jsonb_build_object('source_id', s.id, 'state', s.state, 'version', s.version, 'terms_status', s.terms_status);
end $$;

-- 실행 요청. 운영자(지금 수집·검증·재시도) 또는 예약(하루 1회). 실행 자체는 워커가 drinks_start_run 으로 가져간다.
create or replace function drinks_request_run(p jsonb) returns jsonb language plpgsql as $$
declare
  s drink_sources; v_mode text := coalesce(drinks_text(p, 'mode'), 'collect');
  v_by text := coalesce(drinks_text(p, 'requested_by'), 'operator'); prev drink_collection_runs;
  v_urls text[] := '{}'; r drink_collection_runs; v_day date;
begin
  perform drinks_reap_runs();  -- 워커가 죽어 running 에 남은 실행이 새 요청을 막지 않게
  s := drinks_lock_source(drinks_uuid(p, 'source_id'), null);
  if v_by not in ('operator','schedule') then perform drinks_fail('invalid_input', '요청 주체가 잘못됐습니다'); end if;
  if v_mode not in ('collect','validate','retry') then perform drinks_fail('invalid_input', '실행 종류가 잘못됐습니다'); end if;
  if s.method = 'manual_url' then perform drinks_fail('invalid_state', '수동 등록 출처는 수집하지 않습니다'); end if;
  if v_mode in ('collect','retry') and s.state <> 'active' then
    perform drinks_fail('source_not_active', '활성 수집원만 수집합니다(검증은 [검증 실행]으로)');
  end if;
  if v_mode = 'validate' and s.state not in ('proposed','validated','paused') then
    perform drinks_fail('invalid_state', '제안·검증 완료·일시 중지 상태에서만 검증 실행을 돌립니다');
  end if;
  if v_mode = 'validate' and s.terms_status = 'restricted' then
    perform drinks_fail('terms_restricted', '이용 조건이 수집을 막는 출처입니다');
  end if;
  if v_by = 'schedule' and v_mode <> 'collect' then perform drinks_fail('invalid_input', '예약은 수집 실행만 만듭니다'); end if;
  if v_mode = 'retry' then
    select * into prev from drink_collection_runs where id = drinks_uuid(p, 'retry_of') and source_id = s.id;
    if not found then perform drinks_fail('not_found', '재시도할 실행을 찾지 못했습니다'); end if;
    if prev.status not in ('partial','failed','aborted') or prev.mode = 'validate' then
      perform drinks_fail('invalid_state', '부분 성공·실패·중단된 수집 실행만 재시도합니다');
    end if;
    v_urls := array(select i.canonical_url from drink_collection_items i where i.run_id = prev.id
      and i.status = 'failed' order by i.id limit drinks_limit('max_items_ceiling'));
    if cardinality(v_urls) = 0 and prev.status = 'partial' then
      perform drinks_fail('nothing_to_retry', '실패한 문서가 없습니다');
    end if;
    -- 목록 단계에서 실패한 실행(문서 0건)은 실패 문서가 없으니 처음부터 다시 돈다(retry_urls 비움).
  end if;
  if (select count(*) from drink_collection_runs x where x.source_id = s.id
      and x.created_at > now() - interval '24 hours') >= drinks_limit('runs_per_day') then
    perform drinks_fail('run_limit', '수집원 하나는 24시간에 ' || drinks_limit('runs_per_day') || '번까지 실행합니다');
  end if;
  if v_by = 'schedule' then
    v_day := coalesce(drinks_date(p, 'scheduled_for'), (now() at time zone 'Asia/Seoul')::date);
  end if;
  begin
    insert into drink_collection_runs (source_id, mode, retry_of, retry_urls, requested_by, scheduled_for)
      values (s.id, v_mode, prev.id, v_urls, v_by, v_day) returning * into r;
  exception when unique_violation then
    if v_by = 'schedule' and exists (select 1 from drink_collection_runs x where x.source_id = s.id
        and x.scheduled_for = v_day) then
      return jsonb_build_object('run_id', null, 'skipped', 'already_scheduled');
    end if;
    perform drinks_fail('run_in_progress', '이 수집원은 이미 대기·실행 중인 실행이 있습니다');
  end;
  perform drinks_log_source(s.id, 'run', r.id, 'run_requested', null, r.status, null,
    jsonb_build_object('mode', v_mode, 'requested_by', v_by, 'retry_of', prev.id, 'retry_urls', cardinality(v_urls)),
    case when v_by = 'schedule' then 'schedule' else 'operator' end);
  return jsonb_build_object('run_id', r.id, 'status', r.status, 'mode', r.mode, 'retry_urls', cardinality(v_urls));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 RPC (engine/drinks_collect.py)
-- ─────────────────────────────────────────────────────────────

-- 임대가 끝난 실행·오래 대기한 실행을 닫는다. 어느 워커든 시작할 때 먼저 부른다.
create or replace function drinks_reap_runs() returns int language plpgsql as $$
declare n int := 0; r record;
begin
  for r in select id, status from drink_collection_runs
      where (status = 'running' and lease_expires_at < now())
         or (status = 'queued' and created_at < now() - make_interval(hours => drinks_limit('queued_ttl_hours')))
      order by id for update skip locked loop
    update drink_collection_runs set status = 'aborted', finished_at = now(), lease_token = null,
      error_code = case when r.status = 'running' then 'lease_expired' else 'queue_expired' end,
      error_message = case when r.status = 'running' then '워커 응답이 끊겨 실행을 중단 처리했습니다(임대 만료)'
        else '대기 시간이 지나 실행하지 않았습니다' end
      where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

create or replace function drinks_run_payload(r drink_collection_runs, s drink_sources) returns jsonb
language sql stable as $$
  select jsonb_build_object('run_id', r.id, 'lease_token', r.lease_token, 'lease_expires_at', r.lease_expires_at,
    'mode', r.mode, 'retry_urls', to_jsonb(r.retry_urls), 'cursor_from', r.cursor_from, 'limits', r.limits,
    'source', jsonb_build_object('id', s.id, 'name', s.name, 'method', s.method, 'entry_urls', to_jsonb(s.entry_urls),
      'allowed_hosts', to_jsonb(s.allowed_hosts), 'parser_config', s.parser_config, 'parser_version', s.parser_version,
      'language', s.language, 'publisher', s.publisher))
$$;

create or replace function drinks_start_run(p jsonb) returns jsonb language plpgsql as $$
declare r drink_collection_runs; s drink_sources; v_reaped int; v_worker text := coalesce(drinks_text(p, 'worker_id'), 'worker');
begin
  v_reaped := drinks_reap_runs();
  loop
    select * into r from drink_collection_runs where status = 'queued' order by created_at, id
      limit 1 for update skip locked;
    if not found then return jsonb_build_object('run', null, 'reaped', v_reaped); end if;
    select * into s from drink_sources where id = r.source_id for update;
    -- 대기 중에 수집원이 멈췄거나 종료됐으면 돌리지 않는다.
    if (r.mode in ('collect','retry') and s.state <> 'active')
        or (r.mode = 'validate' and s.state not in ('proposed','validated','paused'))
        or (r.mode = 'validate' and s.terms_status = 'restricted') then
      update drink_collection_runs set status = 'aborted', finished_at = now(), error_code = 'source_not_runnable',
        error_message = '대기 중에 수집원 상태가 바뀌어 실행하지 않았습니다(' || s.state || ')' where id = r.id;
      continue;
    end if;
    update drink_collection_runs set status = 'running', lease_token = gen_random_uuid(), worker_id = v_worker,
      started_at = now(), heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => drinks_limit('lease_sec')),
      cursor_from = s.watermark_at,
      limits = jsonb_build_object('max_items', s.max_items_per_run, 'max_bodies', s.max_bodies_per_run,
        'interval_sec', greatest(s.request_interval_sec, drinks_limit('min_interval_sec')),
        'max_requests', s.max_items_per_run + s.max_bodies_per_run + 5)
      where id = r.id returning * into r;
    perform drinks_log_source(s.id, 'run', r.id, 'run_started', 'queued', 'running', null,
      jsonb_build_object('worker_id', v_worker), 'worker');
    return jsonb_build_object('run', drinks_run_payload(r, s), 'reaped', v_reaped);
  end loop;
end $$;

create or replace function drinks_lock_run(p jsonb) returns drink_collection_runs language plpgsql as $$
declare r drink_collection_runs;
begin
  select * into r from drink_collection_runs where id = drinks_uuid(p, 'run_id') for update;
  if not found then perform drinks_fail('not_found', '실행을 찾지 못했습니다'); end if;
  if r.status <> 'running' or r.lease_token is distinct from drinks_uuid(p, 'lease_token') then
    perform drinks_fail('lease_lost', '이 실행의 임대를 잃었습니다(다른 워커가 닫았거나 끝났음)');
  end if;
  if r.lease_expires_at < now() then
    perform drinks_fail('lease_lost', '실행 임대가 만료됐습니다');
  end if;
  return r;
end $$;

create or replace function drinks_heartbeat_run(p jsonb) returns jsonb language plpgsql as $$
declare r drink_collection_runs;
begin
  r := drinks_lock_run(p);
  update drink_collection_runs set heartbeat_at = now(),
    lease_expires_at = now() + make_interval(secs => drinks_limit('lease_sec')),
    listed_count = greatest(listed_count, coalesce(drinks_int(p, 'listed_count', false), 0)),
    request_count = greatest(request_count, coalesce(drinks_int(p, 'request_count', false), 0))
    where id = r.id returning * into r;
  return jsonb_build_object('run_id', r.id, 'lease_expires_at', r.lease_expires_at);
end $$;

-- 후보 URL 중 이미 본문 스냅샷이 있는 것. 워커는 처음 보는 글에 본문 예산을 먼저 쓴다.
create or replace function drinks_known_urls(p jsonb) returns jsonb language plpgsql as $$
declare r drink_collection_runs; urls text[] := drinks_text_array(p -> 'urls');
begin
  r := drinks_lock_run(p);
  if cardinality(urls) > 500 then perform drinks_fail('invalid_input', '한 번에 500개까지 묻습니다'); end if;
  return coalesce((select jsonb_agg(distinct x.canonical_url) from drink_source_snapshots x
    where x.canonical_url = any(urls) and x.content_hash is not null), '[]');
end $$;

-- 문서 1건 기록. 본문이 있으면 스냅샷을 만들거나(새 URL·바뀐 본문) 기존 것을 다시 쓴다(같은 URL·같은 본문).
-- 검증 실행은 스냅샷을 만들지 않는다(접근·본문 추출이 되는지만 기록 — 'checked').
create or replace function drinks_collect_item(p jsonb) returns jsonb language plpgsql as $$
declare
  r drink_collection_runs; s drink_sources; it jsonb := p -> 'item';
  v_url text := drinks_text(it, 'canonical_url'); v_body text := drinks_text(it, 'body_text');
  v_status text := drinks_text(it, 'status'); v_hash text; snap drink_source_snapshots; prev drink_source_snapshots;
  v_final text; v_snap uuid; v_same int := 0; v_id bigint; v_chars int;
begin
  r := drinks_lock_run(p);
  select * into s from drink_sources where id = r.source_id;
  if it is null or jsonb_typeof(it) <> 'object' then perform drinks_fail('invalid_input', '문서 형식이 잘못됐습니다'); end if;
  if v_url is null or not drinks_entry_url_ok(v_url) or not (drinks_url_host(v_url) = any(s.allowed_hosts)) then
    perform drinks_fail('host_not_allowed', '수집원에 승인된 호스트 밖의 문서는 기록하지 않습니다');
  end if;
  if coalesce(v_status, '') not in ('fetched','metadata_only','skipped','failed') then
    perform drinks_fail('invalid_input', '문서 결과 값이 잘못됐습니다');
  end if;
  if v_status in ('skipped','failed') and drinks_text(it, 'error_code') is null then
    perform drinks_fail('invalid_input', '건너뜀·실패에는 오류 코드가 필요합니다');
  end if;
  if v_status = 'fetched' and v_body is null then v_status := 'metadata_only'; end if;
  if v_status <> 'fetched' then v_body := null; end if;
  if r.item_count >= (r.limits ->> 'max_items')::int then
    perform drinks_fail('limit_exceeded', '이 실행의 문서 상한(' || (r.limits ->> 'max_items') || '건)에 닿았습니다');
  end if;
  if v_body is not null and r.body_count >= (r.limits ->> 'max_bodies')::int then
    perform drinks_fail('limit_exceeded', '이 실행의 본문 상한(' || (r.limits ->> 'max_bodies') || '건)에 닿았습니다');
  end if;
  if exists (select 1 from drink_collection_items i where i.run_id = r.id and i.canonical_url = v_url) then
    return jsonb_build_object('duplicate_in_run', true);
  end if;
  v_hash := drinks_body_hash(v_body);
  v_chars := case when v_body is not null then length(v_body) end;

  if v_status in ('skipped','failed') then
    v_final := v_status;
  elsif r.mode = 'validate' then
    v_final := 'checked';
  elsif v_body is not null then
    -- 비교 대상은 이 URL 의 **가장 최근 본문**이다(옛 버전과 같아도 최신과 다르면 바뀐 것).
    select * into prev from drink_source_snapshots where canonical_url = v_url and content_hash is not null
      order by created_at desc limit 1;
    select * into snap from drink_source_snapshots where canonical_url = v_url and content_hash = v_hash limit 1;
    if found and prev.id = snap.id then
      v_final := 'unchanged'; v_snap := snap.id;
    elsif found then
      -- A → B → A: 같은 본문 스냅샷이 이미 있어(고유 키) 새로 만들지 않고 그 스냅샷을 가리킨다.
      v_final := 'changed'; v_snap := snap.id;
    else
      if prev.id is null then  -- 본문 버전이 없으면 제목만 있던 스냅샷을 앞 버전으로 이어 둔다(판정은 '새 문서')
        select * into prev from drink_source_snapshots where canonical_url = v_url order by created_at desc limit 1;
      end if;
      perform set_config('drinks.capture', 'collected', true);
      insert into drink_source_snapshots (url_raw, canonical_url, title, publisher, source_kind, depth, body_text,
        original_language, published_at, checked_at, rights_status, usage_terms, supersedes_id,
        collected_source_id, collected_run_id)
      values (drinks_text(it, 'url_raw'), v_url, left(drinks_text(it, 'title'), 500), s.publisher, s.source_kind,
        'full_text', left(v_body, 200000), s.language, drinks_date(it, 'published_at'),
        (now() at time zone 'Asia/Seoul')::date, s.rights_default, s.terms_note, prev.id, s.id, r.id)
      on conflict (canonical_url, content_hash) where canonical_url is not null and content_hash is not null do nothing
      returning * into snap;
      perform set_config('drinks.capture', '', true);
      if snap.id is null then  -- 다른 실행이 같은 순간 같은 본문을 넣었다
        select * into snap from drink_source_snapshots where canonical_url = v_url and content_hash = v_hash limit 1;
        v_final := 'unchanged';
      else
        v_final := case when prev.id is not null and prev.content_hash is not null then 'changed' else 'new' end;
        perform drinks_log_source(s.id, 'snapshot', snap.id, 'snapshot_collected', null, snap.depth, null,
          jsonb_build_object('run_id', r.id, 'dedup', v_final, 'supersedes_id', prev.id), 'worker');
      end if;
      v_snap := snap.id;
    end if;
    -- 다른 URL 의 글자 그대로 같은 본문: 원출처 후보로 알리기만 한다(정책 ②).
    select count(*) into v_same from drink_source_snapshots x where x.content_hash = v_hash and x.canonical_url <> v_url;
  else
    -- 제목·요약만 확인된 문서. 이미 본문 버전이 있으면 그것을 가리키고, 없으면 metadata_only 스냅샷을 하나 둔다.
    select * into snap from drink_source_snapshots where canonical_url = v_url order by created_at desc limit 1;
    if not found then
      perform set_config('drinks.capture', 'collected', true);
      insert into drink_source_snapshots (url_raw, canonical_url, title, publisher, source_kind, depth, body_text,
        original_language, published_at, checked_at, rights_status, usage_terms, collected_source_id, collected_run_id)
      values (drinks_text(it, 'url_raw'), v_url, left(drinks_text(it, 'title'), 500), s.publisher, s.source_kind,
        'metadata_only', null, s.language, drinks_date(it, 'published_at'), (now() at time zone 'Asia/Seoul')::date,
        s.rights_default, s.terms_note, s.id, r.id)
      on conflict (canonical_url) where canonical_url is not null and content_hash is null do nothing
      returning * into snap;
      perform set_config('drinks.capture', '', true);
      if snap.id is null then
        select * into snap from drink_source_snapshots where canonical_url = v_url order by created_at desc limit 1;
      end if;
    end if;
    v_final := 'metadata_only'; v_snap := snap.id;
  end if;

  insert into drink_collection_items (run_id, source_id, canonical_url, url_raw, status, http_status, error_code,
    error_message, title, summary, published_at, body_chars, snapshot_id, same_body_count, attempt)
  values (r.id, s.id, v_url, drinks_text(it, 'url_raw'), v_final, drinks_int(it, 'http_status', false),
    drinks_text(it, 'error_code'), left(drinks_text(it, 'error_message'), 1000), left(drinks_text(it, 'title'), 500),
    left(drinks_text(it, 'summary'), 2000), drinks_date(it, 'published_at'), v_chars, v_snap, v_same,
    least(greatest(coalesce(drinks_int(it, 'attempt', false), 1), 1), 3))
  on conflict (run_id, canonical_url) do nothing
  returning id into v_id;
  if v_id is null then return jsonb_build_object('duplicate_in_run', true); end if;

  update drink_collection_runs set item_count = item_count + 1,
    body_count = body_count + (case when v_body is not null then 1 else 0 end),
    new_count = new_count + (case when v_final = 'new' then 1 else 0 end),
    changed_count = changed_count + (case when v_final = 'changed' then 1 else 0 end),
    unchanged_count = unchanged_count + (case when v_final = 'unchanged' then 1 else 0 end),
    metadata_count = metadata_count + (case when v_final = 'metadata_only' then 1 else 0 end),
    skipped_count = skipped_count + (case when v_final = 'skipped' then 1 else 0 end),
    failed_count = failed_count + (case when v_final = 'failed' then 1 else 0 end),
    heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => drinks_limit('lease_sec'))
    where id = r.id;
  return jsonb_build_object('item_id', v_id, 'status', v_final, 'snapshot_id', v_snap, 'same_body_count', v_same);
end $$;

-- 실행 끝. 상태는 DB 가 기록된 문서로 정한다 — 워커가 "성공"이라고 우겨도 실패 문서가 있으면 부분 성공이다.
--   목록·피드 자체를 못 가져옴(fatal) + 문서 0건 → failed
--   실패 문서 있음 + 성공 문서 있음 → partial / 실패만 → failed
--   워커가 시간·요청 상한으로 멈춤(aborted) → aborted (워처마크 그대로)
--   문서 0건·오류 없음 → empty(정상 0건) / 그 밖 → succeeded
create or replace function drinks_finish_run(p jsonb) returns jsonb language plpgsql as $$
declare
  r drink_collection_runs; s drink_sources; v_fatal text := drinks_text(p, 'error_code');
  v_aborted boolean := coalesce((p ->> 'aborted')::boolean, false); v_ok int; v_status text; v_to timestamptz;
  -- 워커가 알려 주는 "다 못 본 것": 문서·본문 상한에 걸려 처음 보는 글을 못 가져옴, 승인 밖 호스트로 빠진 글.
  v_incomplete int := greatest(coalesce(drinks_int(p, 'incomplete_count', false), 0), 0);
  v_offhost int := greatest(coalesce(drinks_int(p, 'offhost_count', false), 0), 0);
  v_parsed int := drinks_int(p, 'parsed_count', false);
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
-- 수집 문서 → 소재 후보 · 조사 연결 (운영자 동작)
-- ─────────────────────────────────────────────────────────────

-- 이미 있는 스냅샷(수집 문서)을 소재에 연결한다. 0050 의 연결 규칙(역할 승격·이력·같은 본문 후보)을 그대로 탄다.
create or replace function drinks_link_snapshot(p jsonb) returns jsonb language plpgsql as $$
declare t drink_topics; snap drink_source_snapshots;
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  if t.status = 'duplicate' then perform drinks_fail('invalid_state', '중복 처리된 소재에는 출처를 붙일 수 없습니다'); end if;
  select * into snap from drink_source_snapshots where id = drinks_uuid(p, 'snapshot_id');
  if not found then perform drinks_fail('not_found', '문서를 찾지 못했습니다'); end if;
  return drinks_add_source_internal(t.id, jsonb_strip_nulls(jsonb_build_object(
    'canonical_url', snap.canonical_url, 'body_text', snap.body_text,
    'role', coalesce(drinks_text(p, 'role'), 'discovery'), 'relation_note', drinks_text(p, 'relation_note'))));
end $$;

-- 수집 문서에서 소재 후보를 만든다(제목·질문은 사람이 쓴다). 문서는 discovery 로 붙는다 — 근거로 쓰려면
-- 조사 단계에서 사람이 evidence 로 올리고 인용을 대조한다(A단계 규칙). 점수·승인·편성은 건드리지 않는다.
create or replace function drinks_create_topic_from_snapshot(p jsonb) returns jsonb language plpgsql as $$
declare v_snap uuid := drinks_uuid(p, 'snapshot_id'); r jsonb; l jsonb;
begin
  if not exists (select 1 from drink_source_snapshots where id = v_snap) then
    perform drinks_fail('not_found', '문서를 찾지 못했습니다');
  end if;
  r := drinks_create_topic((p - 'snapshot_id') - 'source');
  l := drinks_link_snapshot(jsonb_build_object('topic_id', r ->> 'topic_id', 'snapshot_id', v_snap, 'role', 'discovery',
    'relation_note', '수집 문서에서 등록'));
  return r || jsonb_build_object('source', l);
end $$;

-- 경량 평가: 0050 과 같고, 평가 사유·조사 필요 사항을 함께 저장한다(provisional 점수와 별도 칸).
create or replace function drinks_triage(p jsonb) returns jsonb language plpgsql as $$
declare t drink_topics; sc jsonb; v_score numeric; v_before text;
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_version'));
  v_before := t.status;
  if t.status not in ('inbox','triaged') then
    perform drinks_fail('invalid_state', '경량 평가는 등록·분류 단계에서만 바꿀 수 있습니다(조사 이후는 근거·기획 버전에서 채점)');
  end if;
  sc := drinks_check_scores(p -> 'scores', false);
  v_score := drinks_weighted_score(sc);
  update drink_topics set provisional_scores = sc, provisional_score = v_score,
    provisional_rubric = 'drinks-v1', status = 'triaged',
    triage_reason = coalesce(drinks_text(p, 'reason'), triage_reason),
    research_needs = coalesce(drinks_text(p, 'research_needs'), research_needs)
    where id = t.id returning * into t;
  perform drinks_log(t.id, 'topic', t.id, 'triaged', v_before, t.status, 'drinks-v1', drinks_text(p, 'reason'),
    jsonb_build_object('scores', sc, 'score', v_score, 'research_needs', drinks_text(p, 'research_needs')));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'provisional_score', v_score, 'version', t.version);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한 — 0050 과 같은 방향(anon/authenticated 는 아무것도 못 한다)
-- ─────────────────────────────────────────────────────────────

alter table drink_sources enable row level security;
alter table drink_collection_runs enable row level security;
alter table drink_collection_items enable row level security;

revoke all on table drink_sources, drink_collection_runs, drink_collection_items from anon, authenticated;
revoke all on sequence drink_collection_items_id_seq from anon, authenticated;
grant select, insert, update on table drink_sources, drink_collection_runs, drink_collection_items to service_role;
grant usage on sequence drink_collection_items_id_seq to service_role;

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
