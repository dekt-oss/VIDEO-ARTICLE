-- 주류 공장 D단계 — 순환 고리: ③ 인스타 발행 · ④ 성과 수집 · ⑤ 전략 제안 (2026-10-27).
-- 결재 문서 docs/계획_주류순환_발행성과전략_2026-10-27.md, 기록 docs/deviation-drinks-publish-loop.md.
--
-- 명세 §7(social_accounts·publication_requests·publication_attempts·post_metric_snapshots)·§8.4·§9.3~9.4·§11·§12.
-- ⑤ 전략은 명세 밖이라 결재 문서에서 정했다: 제안만 만들고 운영자가 [반영]해야 바뀐다.
--
--   drink_social_accounts         게시 대상 계정. 플랫폼+외부 ID 는 생성 후 불변. 토큰은 DB 에 없다(credential_ref = 비밀 이름)
--   drink_publication_requests    발행 요청 1건(§8.4 상태 10개). 승인 지문 = 파일 묶음·계정·외부 ID·형식·캡션·예약시각
--   drink_publication_attempts    워커 시도 1회의 단계·컨테이너 ID·응답 코드(토큰·원문 응답 없음)
--   drink_post_metric_snapshots   성과 스냅샷(append-only). 받은 지표만 키로 — 없는 지표는 0 이 아니라 키 없음
--   drink_strategy_versions       지금 쓰는 편성 가중치(처음엔 중립 strategy-v0)
--   drink_strategy_proposals      성과에서 계산한 제안(표본 수 포함). 운영자 [반영] → 새 전략 버전
--
-- ★ 외부 API 와 DB 사이 정확히-한-번은 보장하지 않는다(§8.4). 고유키·점유·조회 대조로 중복을 줄이고,
--   게시 여부를 모르면 unknown 으로 남긴다. unknown 은 **자동으로 다시 게시하지 않는다** — 조회 대조로만 정리한다.
-- ★ 실제 계정 연결·게시는 이 파일이 켜지 않는다. 계정은 발행 스위치가 꺼진 채(publish_enabled=false) 등록되고,
--   워커가 공급자에게 외부 ID 를 대조한 뒤에야 active 가 된다.
--
-- 되돌리기: 아래 표 6개와 이 파일의 drinks_* 함수를 drop 한다(0050~0054 표는 이 표들을 참조하지 않는다).

create or replace function drinks_publish_limits() returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'lease_sec', 900,             -- 발행 시도 1회 임대. 단계 기록이 연장한다
    'late_grace_sec', 7200,       -- 예약시각보다 2시간 넘게 늦으면 게시하지 않고 paused(§8.4)
    'caption_max', 2200,          -- 공급자 문서 숫자는 계정 capabilities 가 우선한다(§11 — 버전 있는 규칙으로)
    'hashtag_max', 30,
    'carousel_max_items', 10,
    'metric_window_days', 10,     -- 게시 후 이 기간까지만 성과를 모은다
    -- 같은 경과시간 비교(§9.4). 창 안에서 잰 것만 그 칸이다 — 창을 놓치면 'off_window' 로 남기고 비교에서 뺀다(추정 금지).
    'metric_buckets', jsonb_build_array(
      jsonb_build_object('name', '24h', 'from_h', 24, 'to_h', 36),
      jsonb_build_object('name', '72h', 'from_h', 72, 'to_h', 96),
      jsonb_build_object('name', '7d', 'from_h', 168, 'to_h', 216)),
    'strategy_bucket', '72h',     -- 전략은 이 칸만 비교한다
    'strategy_min_group', 3,      -- 한 묶음(예: 위스키) 표본이 이보다 적으면 그 묶음 가중치를 바꾸지 않는다
    'strategy_min_total', 6,      -- 전체 표본이 이보다 적으면 아무 가중치도 바꾸지 않는다(표본 부족 제안)
    'strategy_max_step', 0.2,     -- 제안 1회에 한 가중치가 움직이는 폭
    'strategy_max_lift', 0.5      -- 가중치 절대 상한
  )
$$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_social_accounts (
  id                  uuid primary key default gen_random_uuid(),
  platform            text not null check (platform in ('instagram')),
  external_account_id text not null check (length(btrim(external_account_id)) between 1 and 100),
  display_name        text not null check (length(btrim(display_name)) between 1 and 100),
  account_type        text not null check (account_type in ('business','creator','test')),
  -- 연결 방식(§11): 서로 다른 로그인의 권한명·Page 요구를 섞지 않는다. fake = 시험용 가짜 공급자(외부 호출 0)
  connection          text not null check (connection in ('instagram_login','facebook_login','fake')),
  capabilities        jsonb not null default '{}' check (jsonb_typeof(capabilities) = 'object'),
  status              text not null default 'pending_verification' check (status in
                        ('pending_verification','active','reauth_required','mismatch','disabled')),
  status_reason       text,
  publish_enabled     boolean not null default false,   -- 'Instagram 발행 허용'(§9.5) — 초기 꺼짐
  credential_ref      text check (credential_ref is null or credential_ref ~ '^[A-Z][A-Z0-9_]{2,63}$'),   -- 비밀 이름만
  verified_at         timestamptz,
  verified_username   text,
  version             int not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  -- 가짜 계정과 진짜 계정이 섞이지 않게: fake 연결은 fake_ 로 시작하는 ID 만, 진짜 연결은 그 접두어를 못 쓴다
  check ((connection = 'fake') = (external_account_id like 'fake\_%')),
  check (connection = 'fake' or credential_ref is not null),
  check (not publish_enabled or status = 'active')
);
create unique index if not exists drink_social_accounts_ext_uq on drink_social_accounts (platform, external_account_id);

create table if not exists drink_publication_requests (
  id                          uuid primary key default gen_random_uuid(),
  topic_id                    uuid not null references drink_topics(id),
  plan_revision_id            uuid not null references drink_plan_revisions(id),
  output_review_id            uuid not null references drink_output_reviews(id),
  manifest_id                 uuid not null references drink_asset_manifests(id),
  manifest_hash               text not null,
  post_type                   text not null check (post_type in ('carousel','reel')),
  account_id                  uuid not null references drink_social_accounts(id),
  target_external_account_id  text not null,
  caption                     text not null default '' check (length(caption) <= 5000),
  cover_asset_id              uuid references drink_media_assets(id),
  publish_at                  timestamptz,
  display_timezone            text not null default 'Asia/Seoul',
  status                      text not null default 'draft' check (status in ('draft','awaiting_approval','approved',
                                'scheduled','publishing','published','failed','unknown','paused','canceled')),
  approval_digest             text,     -- awaiting_approval 에 들어갈 때 고정. 승인은 이 값을 본 사람만 한다
  approved_by                 text,
  approved_at                 timestamptz,
  pause_code                  text,
  pause_reason                text,
  cancel_requested            boolean not null default false,
  external_post_id            text,
  external_url                text,
  reconcile_state             text not null default 'none' check (reconcile_state in
                                ('none','url_pending','reconciled','cancel_not_applied')),
  lease_token                 uuid,
  lease_expires_at            timestamptz,
  attempt_count               int not null default 0,
  error_code                  text,
  error_message               text check (error_message is null or length(error_message) <= 2000),
  published_at                timestamptz,
  version                     int not null default 1,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  check (status = 'draft' or approval_digest is not null),
  check (status not in ('approved','scheduled','publishing','published') or approved_at is not null),
  check (status <> 'publishing' or lease_token is not null),
  check (status <> 'published' or (external_post_id is not null and published_at is not null)),
  check (status <> 'paused' or pause_code is not null)
);
-- 같은 제작안·계정·형식에 살아 있는 요청(또는 성공한 요청)은 하나. 취소·확정 실패는 제외(§8.4).
-- unknown 은 제외하지 않는다 — 게시됐을 수 있는 것 옆에 새 요청을 못 만든다.
create unique index if not exists drink_pub_one_live_uq on drink_publication_requests (plan_revision_id, account_id, post_type)
  where status not in ('canceled','failed');
create index if not exists drink_pub_due_idx on drink_publication_requests (status, publish_at);

create table if not exists drink_publication_attempts (
  id                          uuid primary key default gen_random_uuid(),
  request_id                  uuid not null references drink_publication_requests(id),
  attempt_no                  int not null check (attempt_no >= 1),
  target_external_account_id  text not null,
  provider                    text not null check (provider in ('fake','instagram_graph')),
  stage                       text not null default 'claimed' check (stage in ('claimed','containers_created',
                                'containers_ready','publish_called','confirmed','failed','unknown','paused','canceled')),
  lease_token                 uuid not null,
  provider_container_ids      jsonb not null default '[]' check (jsonb_typeof(provider_container_ids) = 'array'),
  response_code               text,
  external_post_id            text,
  error_code                  text,
  error_message               text check (error_message is null or length(error_message) <= 2000),
  started_at                  timestamptz not null default now(),
  finished_at                 timestamptz,
  unique (request_id, attempt_no)
);

create table if not exists drink_post_metric_snapshots (
  id                    bigint generated always as identity primary key,
  request_id            uuid not null references drink_publication_requests(id),
  external_post_id      text not null,
  observed_at           timestamptz not null default now(),
  hours_since_publish   numeric(8,2) not null,
  age_bucket            text not null,       -- 24h / 72h / 7d / off_window (창 밖 — 비교에서 뺀다)
  metric_schema_version text not null,
  metric_values         jsonb not null default '{}' check (jsonb_typeof(metric_values) = 'object'),
  unavailable           jsonb not null default '{}' check (jsonb_typeof(unavailable) = 'object'),  -- 키 → 받지 못한 이유
  fetch_status          text not null check (fetch_status in ('ok','partial','failed')),
  error_code            text,
  unique (request_id, observed_at, metric_schema_version)
);
-- 한 칸에 성공 스냅샷은 하나(재실행해도 같은 칸을 두 번 세지 않는다). 실패는 여러 번 남을 수 있다.
create unique index if not exists drink_metrics_bucket_uq on drink_post_metric_snapshots (request_id, age_bucket, metric_schema_version)
  where age_bucket <> 'off_window' and fetch_status <> 'failed';

create table if not exists drink_strategy_versions (
  id           uuid primary key default gen_random_uuid(),
  label        text not null unique,
  weights      jsonb not null check (jsonb_typeof(weights) = 'object'),
  status       text not null check (status in ('active','retired')),
  proposal_id  uuid,
  created_at   timestamptz not null default now(),
  retired_at   timestamptz
);
create unique index if not exists drink_strategy_one_active_uq on drink_strategy_versions ((true)) where status = 'active';

create table if not exists drink_strategy_proposals (
  id                uuid primary key default gen_random_uuid(),
  base_version_id   uuid not null references drink_strategy_versions(id),
  weights           jsonb not null check (jsonb_typeof(weights) = 'object'),
  basis             jsonb not null check (jsonb_typeof(basis) = 'object'),   -- 묶음별 평균·표본 수·전체 평균
  sample_total      int not null check (sample_total >= 0),
  sufficient        boolean not null,
  summary_ko        text,
  status            text not null default 'proposed' check (status in ('proposed','accepted','rejected','superseded')),
  decided_by        text,
  decided_at        timestamptz,
  reason            text,
  created_at        timestamptz not null default now(),
  check (status <> 'rejected' or reason is not null)
);
alter table drink_strategy_versions drop constraint if exists drink_strategy_versions_proposal_fk;
alter table drink_strategy_versions add constraint drink_strategy_versions_proposal_fk foreign key (proposal_id)
  references drink_strategy_proposals(id);

insert into drink_strategy_versions (label, weights, status)
  select 'strategy-v0', '{"category":{},"post_type":{},"lane":{},"slot":{}}'::jsonb, 'active'
  where not exists (select 1 from drink_strategy_versions);

-- ─────────────────────────────────────────────────────────────
-- 불변·전이 트리거
-- ─────────────────────────────────────────────────────────────

drop trigger if exists drink_metrics_append_only on drink_post_metric_snapshots;
create trigger drink_metrics_append_only before update or delete on drink_post_metric_snapshots
  for each row execute function drink_append_only_guard();

create or replace function drink_accounts_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '계정 기록은 삭제할 수 없습니다(사용 중지로 표시)'); end if;
  if new.platform <> old.platform or new.external_account_id <> old.external_account_id or new.connection <> old.connection then
    perform drinks_fail('immutable', '계정의 플랫폼·외부 ID·연결 방식은 바꿀 수 없습니다 — 다른 계정은 새로 등록하세요');
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists drink_accounts_guard on drink_social_accounts;
create trigger drink_accounts_guard before update or delete on drink_social_accounts
  for each row execute function drink_accounts_guard();

create or replace function drinks_pub_transition_ok(a text, b text) returns boolean language sql immutable as $$
  select a = b or (a, b) in (
    ('draft','awaiting_approval'), ('draft','canceled'),
    ('awaiting_approval','draft'), ('awaiting_approval','approved'), ('awaiting_approval','canceled'),
    ('approved','scheduled'), ('approved','paused'), ('approved','canceled'),
    ('scheduled','publishing'), ('scheduled','paused'), ('scheduled','canceled'),
    ('paused','scheduled'), ('paused','awaiting_approval'), ('paused','canceled'),
    ('publishing','published'), ('publishing','failed'), ('publishing','unknown'), ('publishing','paused'),
    ('publishing','canceled'),
    ('unknown','published'), ('unknown','failed'), ('unknown','canceled'),
    ('failed','scheduled'))
$$;

-- 발행 요청: 내용(payload)은 draft 에서만 바뀐다. 상태는 표에 있는 길로만 간다. 함수를 우회한 UPDATE 도 같다.
create or replace function drink_publications_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '발행 요청은 삭제할 수 없습니다(취소로 표시)'); end if;
  if old.status <> 'draft' and (new.manifest_id, new.manifest_hash, new.account_id, new.target_external_account_id,
      new.post_type, new.caption, new.cover_asset_id, new.publish_at, new.plan_revision_id, new.output_review_id)
      is distinct from (old.manifest_id, old.manifest_hash, old.account_id, old.target_external_account_id,
      old.post_type, old.caption, old.cover_asset_id, old.publish_at, old.plan_revision_id, old.output_review_id) then
    perform drinks_fail('immutable', '작성 중이 아닌 발행 요청의 내용은 바꿀 수 없습니다 — 취소하고 새로 만드세요');
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
drop trigger if exists drink_publications_guard on drink_publication_requests;
create trigger drink_publications_guard before update or delete on drink_publication_requests
  for each row execute function drink_publications_guard();

create or replace function drink_pub_attempts_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '발행 시도 기록은 삭제할 수 없습니다'); end if;
  if old.finished_at is not null then perform drinks_fail('immutable', '끝난 발행 시도는 바꿀 수 없습니다'); end if;
  if new.request_id <> old.request_id or new.attempt_no <> old.attempt_no or new.lease_token <> old.lease_token
      or new.target_external_account_id <> old.target_external_account_id then
    perform drinks_fail('immutable', '발행 시도의 대상은 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_pub_attempts_guard on drink_publication_attempts;
create trigger drink_pub_attempts_guard before update or delete on drink_publication_attempts
  for each row execute function drink_pub_attempts_guard();

create or replace function drink_strategy_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '전략 기록은 삭제할 수 없습니다'); end if;
  if tg_table_name = 'drink_strategy_versions' then
    if new.weights is distinct from old.weights or new.label <> old.label then
      perform drinks_fail('immutable', '전략 버전의 가중치는 바꿀 수 없습니다 — 새 버전을 만드세요');
    end if;
    if old.status = 'retired' and new.status <> 'retired' then
      perform drinks_fail('immutable', '물러난 전략 버전은 다시 켤 수 없습니다 — 그 가중치로 새 제안을 만드세요');
    end if;
  else
    if new.weights is distinct from old.weights or new.basis is distinct from old.basis
        or new.base_version_id <> old.base_version_id then
      perform drinks_fail('immutable', '전략 제안의 내용은 바꿀 수 없습니다');
    end if;
    if old.status <> 'proposed' then perform drinks_fail('immutable', '이미 결정된 제안입니다'); end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_strategy_versions_guard on drink_strategy_versions;
create trigger drink_strategy_versions_guard before update or delete on drink_strategy_versions
  for each row execute function drink_strategy_guard();
drop trigger if exists drink_strategy_proposals_guard on drink_strategy_proposals;
create trigger drink_strategy_proposals_guard before update or delete on drink_strategy_proposals
  for each row execute function drink_strategy_guard();

-- ─────────────────────────────────────────────────────────────
-- 헬퍼
-- ─────────────────────────────────────────────────────────────

-- 승인 지문: 사람이 본 것(파일 묶음·계정·외부 ID·형식·캡션·커버·예약시각) 전부. 하나라도 다르면 다른 지문.
create or replace function drinks_pub_digest(r drink_publication_requests) returns text language sql stable as $$
  select encode(sha256(convert_to(concat_ws('|', 'drinks-pub-v1', r.manifest_id::text, r.manifest_hash, r.account_id::text,
    r.target_external_account_id, r.post_type, r.caption, coalesce(r.cover_asset_id::text, ''),
    coalesce(to_char(r.publish_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), '')), 'UTF8')), 'hex')
$$;

create or replace function drinks_pub_limit(p_acc drink_social_accounts, k text) returns int language sql stable as $$
  select coalesce((p_acc.capabilities ->> k)::int, (drinks_publish_limits() ->> k)::int)
$$;

-- 이 요청을 지금 게시해도 되나: 승인 지문 그대로·결과물 검수 승인이 지금도 유효·계정이 살아 있고 발행 허용·외부 ID 일치.
-- 막히면 이유 코드(왜 paused 로 보내는지)를 돌려준다.
create or replace function drinks_pub_block(p_id uuid) returns text language sql stable as $$
  select case
    when r.id is null then 'not_found'
    when r.approval_digest is distinct from drinks_pub_digest(r) then 'digest_changed'
    when not coalesce((select v.currently_usable from drink_output_validity v where v.review_id = r.output_review_id), false)
      then 'output_not_usable'
    when a.status = 'reauth_required' then 'account_reauth'
    when a.status <> 'active' then 'account_not_active'
    when not a.publish_enabled then 'publish_disabled'
    when a.external_account_id <> r.target_external_account_id then 'account_mismatch'
    else null end
  from (select 1) x left join drink_publication_requests r on r.id = p_id
    left join drink_social_accounts a on a.id = r.account_id
$$;

create or replace function drinks_pub_log(r drink_publication_requests, p_action text, p_before text, p_reason text,
  p_detail jsonb default '{}', p_actor text default 'operator') returns void language sql as $$
  insert into drink_workflow_events (topic_id, entity_type, entity_id, action, actor, before_status, after_status, version_ref,
    reason, detail)
  values (r.topic_id, 'plan', r.plan_revision_id, 'publication_' || p_action, p_actor, p_before, r.status, r.id::text, p_reason,
    coalesce(p_detail, '{}') || jsonb_build_object('post_type', r.post_type, 'account_id', r.account_id));
$$;

create or replace function drinks_lock_publication(p jsonb, p_check_version boolean default true)
returns drink_publication_requests language plpgsql as $$
declare r drink_publication_requests;
begin
  select * into r from drink_publication_requests where id = drinks_uuid(p, 'request_id') for update;
  if not found then perform drinks_fail('not_found', '발행 요청을 찾지 못했습니다'); end if;
  if p_check_version and drinks_int(p, 'expected_version') is distinct from r.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  return r;
end $$;

-- 캡션 형식 검사(내용 검사 — 원문에 없는 숫자·양·권고 — 는 워커가 게시 직전에 코드로 한다).
create or replace function drinks_check_caption(p_caption text, p_acc drink_social_accounts) returns void language plpgsql as $$
begin
  if length(coalesce(p_caption, '')) > drinks_pub_limit(p_acc, 'caption_max') then
    perform drinks_fail('invalid_input', '캡션이 너무 깁니다(' || drinks_pub_limit(p_acc, 'caption_max') || '자 이하)');
  end if;
  if (select count(*) from regexp_matches(coalesce(p_caption, ''), '#[^\s#]+', 'g')) > drinks_pub_limit(p_acc, 'hashtag_max') then
    perform drinks_fail('invalid_input', '해시태그가 너무 많습니다(' || drinks_pub_limit(p_acc, 'hashtag_max') || '개 이하)');
  end if;
end $$;

-- 임대가 끝난 '게시 중'은 unknown 이다 — 외부 게시가 됐을 수도 있다. 실패로 닫거나 다시 줄 세우지 않는다(§8.4).
create or replace function drinks_reap_publications() returns int language plpgsql as $$
declare n int := 0; r record;
begin
  for r in select id from drink_publication_requests where status = 'publishing' and lease_expires_at < now()
      order by id for update skip locked loop
    update drink_publication_attempts set stage = 'unknown', finished_at = now(), error_code = 'lease_expired',
      error_message = '워커 응답이 끊겼습니다 — 게시 여부를 조회로 대조해야 합니다'
      where request_id = r.id and finished_at is null;
    update drink_publication_requests set status = 'unknown', lease_token = null, error_code = 'lease_expired',
      error_message = '워커 응답이 끊겨 게시 여부를 모릅니다 — 자동으로 다시 게시하지 않습니다' where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 운영자 RPC — 계정
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_register_account(p jsonb) returns jsonb language plpgsql as $$
declare a drink_social_accounts; caps jsonb := coalesce(p -> 'capabilities', '{}');
begin
  if jsonb_typeof(caps) <> 'object' then perform drinks_fail('invalid_input', '기능(capabilities) 형식이 잘못됐습니다'); end if;
  if coalesce(drinks_text(p, 'connection'), '') not in ('instagram_login','facebook_login','fake') then
    perform drinks_fail('invalid_input', '연결 방식을 고르세요(Instagram 로그인 / Facebook 로그인)');
  end if;
  if (drinks_text(p, 'connection') = 'fake') <> coalesce(drinks_text(p, 'external_account_id') like 'fake\_%', false) then
    perform drinks_fail('invalid_input', '시험용 가짜 계정은 fake_ 로 시작하는 ID 만, 실제 계정은 그 접두어를 쓸 수 없습니다');
  end if;
  if drinks_text(p, 'connection') <> 'fake' and coalesce(drinks_text(p, 'credential_ref'), '') !~ '^[A-Z][A-Z0-9_]{2,63}$' then
    perform drinks_fail('invalid_input', '토큰을 둔 비밀 이름(대문자·숫자·밑줄)을 적으세요 — 토큰 원문은 넣지 않습니다');
  end if;
  begin
    insert into drink_social_accounts (platform, external_account_id, display_name, account_type, connection, capabilities,
      credential_ref)
    values (coalesce(drinks_text(p, 'platform'), 'instagram'), drinks_text(p, 'external_account_id'), drinks_text(p, 'display_name'),
      coalesce(drinks_text(p, 'account_type'), 'business'), drinks_text(p, 'connection'), caps, drinks_text(p, 'credential_ref'))
    returning * into a;
  exception when unique_violation then
    perform drinks_fail('duplicate_account', '같은 외부 ID 의 계정이 이미 있습니다 — 재인증은 그 계정에서 하세요');
  end;
  return jsonb_build_object('account_id', a.id, 'status', a.status, 'version', a.version);
end $$;

create or replace function drinks_account_action(p jsonb) returns jsonb language plpgsql as $$
declare a drink_social_accounts; v_action text := drinks_text(p, 'action'); n int := 0;
begin
  select * into a from drink_social_accounts where id = drinks_uuid(p, 'account_id') for update;
  if not found then perform drinks_fail('not_found', '계정을 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from a.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  if v_action = 'enable_publish' then
    if a.status <> 'active' then perform drinks_fail('invalid_state', '외부 ID 대조가 끝난(활성) 계정만 발행을 켤 수 있습니다'); end if;
    update drink_social_accounts set publish_enabled = true where id = a.id returning * into a;
  elsif v_action = 'disable_publish' then
    update drink_social_accounts set publish_enabled = false where id = a.id returning * into a;
  elsif v_action = 'request_verification' then
    if a.status not in ('reauth_required','pending_verification','mismatch') then
      perform drinks_fail('invalid_state', '재확인이 필요한 계정이 아닙니다');
    end if;
    update drink_social_accounts set status = 'pending_verification', status_reason = null where id = a.id returning * into a;
  elsif v_action = 'disable' then
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '사용 중지 사유를 적으세요'); end if;
    update drink_social_accounts set status = 'disabled', publish_enabled = false, status_reason = drinks_text(p, 'reason')
      where id = a.id returning * into a;
  else
    perform drinks_fail('invalid_input', '알 수 없는 계정 동작입니다');
  end if;
  -- 발행을 끄거나 계정을 멈추면 그 계정의 예약을 멈춘다(다른 계정으로 대신 게시하지 않는다 — §11).
  if not a.publish_enabled then
    with x as (update drink_publication_requests set status = 'paused', pause_code = 'publish_disabled',
        pause_reason = '계정 발행이 꺼졌습니다' where account_id = a.id and status in ('approved','scheduled') returning 1)
      select count(*) into n from x;
  end if;
  return jsonb_build_object('account_id', a.id, 'status', a.status, 'publish_enabled', a.publish_enabled, 'version', a.version,
    'paused_requests', n);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 운영자 RPC — 발행 요청
-- ─────────────────────────────────────────────────────────────

-- 발행안 작성: 검수 승인된 파일 묶음 하나 + 계정 하나. 계정을 암묵 선택하지 않는다(§2).
create or replace function drinks_create_publication(p jsonb) returns jsonb language plpgsql as $$
declare o drink_output_reviews; m drink_asset_manifests; pl drink_plan_revisions; a drink_social_accounts;
  r drink_publication_requests; v_type text; v_cover uuid; v_pages int;
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
  begin
    insert into drink_publication_requests (topic_id, plan_revision_id, output_review_id, manifest_id, manifest_hash, post_type,
      account_id, target_external_account_id, caption, cover_asset_id, publish_at)
    values (pl.topic_id, pl.id, o.id, m.id, m.manifest_hash, v_type, a.id, a.external_account_id, coalesce(p ->> 'caption', ''),
      v_cover, (drinks_text(p, 'publish_at'))::timestamptz)
    returning * into r;
  exception when unique_violation then
    perform drinks_fail('duplicate_publication', '이 제작안·계정·형식에는 이미 살아 있는(또는 게시된) 발행 요청이 있습니다');
  end;
  perform drinks_pub_log(r, 'created', null, null);
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'post_type', r.post_type);
end $$;

create or replace function drinks_update_publication(p jsonb) returns jsonb language plpgsql as $$
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
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version);
end $$;

create or replace function drinks_publication_action(p jsonb) returns jsonb language plpgsql as $$
declare r drink_publication_requests; v_action text := drinks_text(p, 'action'); v_before text; v_block text;
  v_grace int := (drinks_publish_limits() ->> 'late_grace_sec')::int;
begin
  perform drinks_reap_publications();
  r := drinks_lock_publication(p);
  v_before := r.status;
  if v_action = 'submit' then
    if r.status <> 'draft' then perform drinks_fail('invalid_state', '작성 중인 발행안만 승인 요청합니다'); end if;
    if r.publish_at is null then perform drinks_fail('invalid_input', '게시 시각을 정하세요(지금 게시도 시각으로 적습니다)'); end if;
    update drink_publication_requests set status = 'awaiting_approval', approval_digest = drinks_pub_digest(r)
      where id = r.id returning * into r;
  elsif v_action = 'withdraw' then
    if r.status <> 'awaiting_approval' then perform drinks_fail('invalid_state', '승인 대기 중인 것만 작성으로 되돌립니다'); end if;
    update drink_publication_requests set status = 'draft', approval_digest = null where id = r.id returning * into r;
  elsif v_action = 'approve' then
    if r.status <> 'awaiting_approval' then perform drinks_fail('invalid_state', '승인 대기 중인 것만 승인합니다'); end if;
    -- 승인은 화면에 보인 지문을 그대로 돌려줘야 한다 — 다른 창에서 바뀐 내용을 모르고 승인하지 않게.
    if drinks_text(p, 'expected_digest') is distinct from r.approval_digest or r.approval_digest <> drinks_pub_digest(r) then
      perform drinks_fail('digest_mismatch', '승인 화면의 내용과 지금 내용이 다릅니다 — 새로 불러와 다시 확인하세요');
    end if;
    if not coalesce((select currently_usable from drink_output_validity where review_id = r.output_review_id), false) then
      perform drinks_fail('output_not_usable', '파일 묶음의 검수·근거가 지금은 유효하지 않습니다');
    end if;
    update drink_publication_requests set status = 'approved', approved_by = coalesce(drinks_text(p, 'actor'), 'operator'),
      approved_at = now() where id = r.id returning * into r;
  elsif v_action in ('schedule','resume','retry') then
    if (v_action = 'schedule' and r.status <> 'approved') or (v_action = 'resume' and r.status <> 'paused')
        or (v_action = 'retry' and r.status <> 'failed') then
      perform drinks_fail('invalid_state', case v_action when 'schedule' then '승인된 것만 예약합니다'
        when 'resume' then '멈춘 것만 다시 예약합니다' else '확정 실패한 것만 다시 시도합니다' end);
    end if;
    if r.approved_at is null then perform drinks_fail('invalid_state', '승인 기록이 없습니다 — 다시 승인받으세요'); end if;
    v_block := drinks_pub_block(r.id);
    if v_block is not null then
      perform drinks_fail(case when v_block = 'digest_changed' then 'digest_mismatch' else 'not_publishable' end,
        '지금은 예약할 수 없습니다: ' || v_block);
    end if;
    if r.publish_at < now() - make_interval(secs => v_grace) then
      perform drinks_fail('too_late', '예약 시각이 2시간 넘게 지났습니다 — 취소하고 새 시각으로 다시 승인받으세요');
    end if;
    update drink_publication_requests set status = 'scheduled', pause_code = null, pause_reason = null, error_code = null,
      error_message = null where id = r.id returning * into r;
  elsif v_action = 'pause' then
    if r.status not in ('approved','scheduled') then perform drinks_fail('invalid_state', '승인·예약된 것만 멈춥니다'); end if;
    update drink_publication_requests set status = 'paused', pause_code = 'operator',
      pause_reason = coalesce(drinks_text(p, 'reason'), '운영자 중지') where id = r.id returning * into r;
  elsif v_action = 'cancel' then
    if r.status in ('publishing','unknown') then
      -- 게시 중·여부 불명은 취소로 닫지 않는다. 워커가 게시 직전에 확인하고, unknown 은 조회 대조가 정한다.
      update drink_publication_requests set cancel_requested = true where id = r.id returning * into r;
    elsif r.status in ('draft','awaiting_approval','approved','scheduled','paused') then
      update drink_publication_requests set status = 'canceled', cancel_requested = true,
        error_message = coalesce(drinks_text(p, 'reason'), '운영자 취소') where id = r.id returning * into r;
    else
      perform drinks_fail('invalid_state', '이미 끝난 발행 요청입니다');
    end if;
  else
    perform drinks_fail('invalid_input', '알 수 없는 발행 동작입니다');
  end if;
  perform drinks_pub_log(r, v_action, v_before, drinks_text(p, 'reason'));
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'approval_digest', r.approval_digest,
    'cancel_requested', r.cancel_requested);
end $$;

-- 화면용: 지금 게시 가능 판정과 지문(승인 모달이 보여줄 값).
create or replace function drinks_publication_state(p jsonb) returns jsonb language plpgsql as $$
declare r drink_publication_requests;
begin
  perform drinks_reap_publications();
  select * into r from drink_publication_requests where id = drinks_uuid(p, 'request_id');
  if not found then perform drinks_fail('not_found', '발행 요청을 찾지 못했습니다'); end if;
  return jsonb_build_object('status', r.status, 'block', drinks_pub_block(r.id), 'approval_digest', r.approval_digest,
    'current_digest', drinks_pub_digest(r), 'version', r.version);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 RPC — 계정 대조 (engine/drinks_publish.py)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_accounts_to_verify(p jsonb) returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(jsonb_build_object('account_id', a.id, 'platform', a.platform, 'connection', a.connection,
    'external_account_id', a.external_account_id, 'credential_ref', a.credential_ref) order by a.created_at), '[]')
  from drink_social_accounts a where a.status = 'pending_verification'
$$;

-- 공급자가 돌려준 "이 토큰의 주인"을 등록된 외부 ID 와 대조한다. 다르면 갱신하지 않고 mismatch(§11).
create or replace function drinks_account_verified(p jsonb) returns jsonb language plpgsql as $$
declare a drink_social_accounts; v_ext text := drinks_text(p, 'external_account_id'); n int := 0;
begin
  select * into a from drink_social_accounts where id = drinks_uuid(p, 'account_id') for update;
  if not found then perform drinks_fail('not_found', '계정을 찾지 못했습니다'); end if;
  if not coalesce((p ->> 'ok')::boolean, false) then
    update drink_social_accounts set status = 'reauth_required', publish_enabled = false,
      status_reason = left(coalesce(drinks_text(p, 'error_code'), 'auth_failed'), 200) where id = a.id returning * into a;
  elsif v_ext is distinct from a.external_account_id then
    update drink_social_accounts set status = 'mismatch', publish_enabled = false,
      status_reason = '인증된 계정 ID 가 등록된 ID 와 다릅니다 — 다른 계정은 새로 등록하세요' where id = a.id returning * into a;
  else
    update drink_social_accounts set status = 'active', status_reason = null, verified_at = now(),
      verified_username = drinks_text(p, 'username') where id = a.id returning * into a;
  end if;
  if a.status <> 'active' then
    with x as (update drink_publication_requests set status = 'paused', pause_code = 'account_reauth',
        pause_reason = '계정 연결 확인 실패: ' || a.status where account_id = a.id and status in ('approved','scheduled') returning 1)
      select count(*) into n from x;
  end if;
  return jsonb_build_object('account_id', a.id, 'status', a.status, 'paused_requests', n);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 RPC — 발행
-- ─────────────────────────────────────────────────────────────

-- 예약 시각이 된 요청 하나를 점유한다. 너무 늦었거나 지금은 막혔으면 게시하지 않고 paused 로 보내고 다음을 본다.
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

create or replace function drinks_lock_pub_lease(p jsonb) returns drink_publication_requests language plpgsql as $$
declare r drink_publication_requests;
begin
  r := drinks_lock_publication(p, false);
  if r.status <> 'publishing' or r.lease_token is distinct from drinks_uuid(p, 'lease_token') or r.lease_expires_at < now() then
    perform drinks_fail('lease_lost', '이 발행 시도의 임대를 잃었습니다(다른 워커가 회수했거나 끝났음)');
  end if;
  return r;
end $$;

-- 단계 기록 + 임대 연장. stage='before_publish' 는 최종 게시 호출 직전의 재확인이다 — 취소·승인 무효면 proceed=false.
create or replace function drinks_publication_step(p jsonb) returns jsonb language plpgsql as $$
declare r drink_publication_requests; v_stage text := drinks_text(p, 'stage'); v_block text;
begin
  r := drinks_lock_pub_lease(p);
  if v_stage not in ('containers_created','containers_ready','before_publish','publish_called') then
    perform drinks_fail('invalid_input', '알 수 없는 발행 단계입니다');
  end if;
  update drink_publication_requests set lease_expires_at = now() + make_interval(secs => (drinks_publish_limits() ->> 'lease_sec')::int)
    where id = r.id returning * into r;
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

-- 시도 끝. published 는 외부 게시물 ID 와 그 게시물의 계정 ID 가 대상과 같을 때만.
-- failed 는 "공급자가 실패를 확정했고 게시 호출 전"일 때만 워커가 보낸다 — 게시 호출 뒤 모르는 것은 unknown.
create or replace function drinks_finish_publication(p jsonb) returns jsonb language plpgsql as $$
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

-- 게시 여부 불명(unknown) 목록 — 조회 대조용. 시도별 컨테이너 ID 를 준다(공급자에게 "이 컨테이너가 게시됐나" 묻는다).
create or replace function drinks_unknown_publications(p jsonb) returns jsonb language plpgsql as $$
begin
  perform drinks_reap_publications();
  return coalesce((select jsonb_agg(jsonb_build_object('request_id', r.id, 'caption', r.caption, 'post_type', r.post_type,
      'external_post_id', r.external_post_id, 'cancel_requested', r.cancel_requested, 'updated_at', r.updated_at,
      'account', jsonb_build_object('account_id', a.id, 'connection', a.connection, 'external_account_id', a.external_account_id,
        'credential_ref', a.credential_ref),
      'container_ids', coalesce((select jsonb_agg(c) from drink_publication_attempts t, jsonb_array_elements(t.provider_container_ids) c
        where t.request_id = r.id), '[]')) order by r.updated_at)
    from drink_publication_requests r join drink_social_accounts a on a.id = r.account_id where r.status = 'unknown'), '[]');
end $$;

-- 조회 대조 결과. found=true → published(취소 요청이 있었으면 '취소 미적용' 표시). found=false 는 공급자가
-- "이 컨테이너는 게시되지 않았다"고 확정했을 때만 — 취소 요청이 있었으면 canceled, 아니면 failed(재시도 가능).
create or replace function drinks_reconcile_publication(p jsonb) returns jsonb language plpgsql as $$
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
-- 워커 RPC — 성과 (engine/drinks_metrics.py)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_metric_bucket(p_hours numeric) returns text language sql immutable as $$
  select coalesce((select b ->> 'name' from jsonb_array_elements(drinks_publish_limits() -> 'metric_buckets') b
    where p_hours >= (b ->> 'from_h')::numeric and p_hours < (b ->> 'to_h')::numeric limit 1), 'off_window')
$$;

-- 지금 잴 칸이 열려 있고 아직 그 칸을 못 잰 게시물.
create or replace function drinks_metrics_due(p jsonb) returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(x order by x ->> 'published_at'), '[]') from (
    select jsonb_build_object('request_id', r.id, 'external_post_id', r.external_post_id, 'post_type', r.post_type,
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

-- 스냅샷 기록. 칸은 서버가 게시 시각에서 정한다(워커가 '72h' 라고 우기지 못한다). 값은 0 이상 숫자만.
create or replace function drinks_record_metrics(p jsonb) returns jsonb language plpgsql as $$
declare r drink_publication_requests; v jsonb := coalesce(p -> 'values', '{}'); u jsonb := coalesce(p -> 'unavailable', '{}');
  k text; v_hours numeric; v_bucket text; v_id bigint; v_status text := coalesce(drinks_text(p, 'fetch_status'), 'ok');
begin
  select * into r from drink_publication_requests where id = drinks_uuid(p, 'request_id');
  if not found or r.status <> 'published' then perform drinks_fail('invalid_state', '게시된 요청만 성과를 기록합니다'); end if;
  if drinks_text(p, 'external_post_id') is distinct from r.external_post_id then
    perform drinks_fail('invalid_input', '다른 게시물의 성과입니다');
  end if;
  if jsonb_typeof(v) <> 'object' or jsonb_typeof(u) <> 'object' then perform drinks_fail('invalid_input', '지표 형식이 잘못됐습니다'); end if;
  for k in select jsonb_object_keys(v) loop
    if jsonb_typeof(v -> k) <> 'number' or (v ->> k)::numeric < 0 then
      perform drinks_fail('invalid_input', '지표 값은 0 이상 숫자만 받습니다: ' || k);
    end if;
    if u ? k then perform drinks_fail('invalid_input', '받은 지표를 미제공으로도 적었습니다: ' || k); end if;
  end loop;
  if v_status not in ('ok','partial','failed') then perform drinks_fail('invalid_input', '수집 상태가 잘못됐습니다'); end if;
  v_hours := round(extract(epoch from now() - r.published_at)::numeric / 3600, 2);
  v_bucket := drinks_metric_bucket(v_hours);
  insert into drink_post_metric_snapshots (request_id, external_post_id, hours_since_publish, age_bucket, metric_schema_version,
    metric_values, unavailable, fetch_status, error_code)
  values (r.id, r.external_post_id, v_hours, v_bucket, coalesce(drinks_text(p, 'metric_schema_version'), 'ig-media-v1'), v, u,
    v_status, drinks_text(p, 'error_code'))
  on conflict (request_id, age_bucket, metric_schema_version) where age_bucket <> 'off_window' and fetch_status <> 'failed'
    do nothing
  returning id into v_id;
  return jsonb_build_object('snapshot_id', v_id, 'bucket', v_bucket, 'hours', v_hours, 'duplicate', v_id is null);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 전략 (engine/drinks_strategy.py 가 계산, 사람이 반영)
-- ─────────────────────────────────────────────────────────────

-- 게시 시간대(한국 시각). 아침 06–11 · 낮 11–17 · 저녁 17–22 · 밤 22–06.
create or replace function drinks_time_slot(t timestamptz) returns text language sql immutable as $$
  select case when h >= 6 and h < 11 then 'morning' when h >= 11 and h < 17 then 'afternoon'
    when h >= 17 and h < 22 then 'evening' else 'night' end
  from (select extract(hour from t at time zone 'Asia/Seoul')::int as h) x
$$;

-- 전략 계산 입력: 비교 칸(72h)을 잰 게시물마다 묶음 값과 지표. 지표가 없는 게시물도 내준다(계산 쪽이 표본에서 뺀다).
create or replace function drinks_strategy_inputs(p jsonb) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'active', (select jsonb_build_object('id', v.id, 'label', v.label, 'weights', v.weights) from drink_strategy_versions v
      where v.status = 'active'),
    'limits', drinks_publish_limits(),
    'posts', coalesce((select jsonb_agg(jsonb_build_object('request_id', r.id, 'categories', to_jsonb(t.categories),
        'lane', t.lane, 'post_type', r.post_type, 'slot', drinks_time_slot(r.published_at), 'values', s.metric_values,
        'unavailable', s.unavailable) order by r.published_at)
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
    if d not in ('category','post_type','lane','slot') or jsonb_typeof(w -> d) <> 'object' then
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

-- 운영자 결정. 반영 = 새 전략 버전(옛 버전은 물러난다). 표본 부족 제안은 반영할 것이 없다.
create or replace function drinks_strategy_action(p jsonb) returns jsonb language plpgsql as $$
declare x drink_strategy_proposals; v drink_strategy_versions; nv drink_strategy_versions; v_action text := drinks_text(p, 'action');
begin
  select * into x from drink_strategy_proposals where id = drinks_uuid(p, 'proposal_id') for update;
  if not found then perform drinks_fail('not_found', '전략 제안을 찾지 못했습니다'); end if;
  if x.status <> 'proposed' then perform drinks_fail('invalid_state', '이미 결정됐거나 새 제안으로 대체된 제안입니다'); end if;
  if v_action = 'reject' then
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '기각 사유를 적으세요'); end if;
    update drink_strategy_proposals set status = 'rejected', decided_by = coalesce(drinks_text(p, 'actor'), 'operator'),
      decided_at = now(), reason = drinks_text(p, 'reason') where id = x.id returning * into x;
    return jsonb_build_object('proposal_id', x.id, 'status', x.status);
  elsif v_action <> 'accept' then
    perform drinks_fail('invalid_input', '알 수 없는 전략 동작입니다');
  end if;
  if not x.sufficient then
    perform drinks_fail('insufficient_sample', '표본이 부족한 제안이라 바꿀 가중치가 없습니다 — 게시가 더 쌓인 뒤 다시 계산하세요');
  end if;
  select * into v from drink_strategy_versions where status = 'active' for update;
  if v.id <> x.base_version_id then
    perform drinks_fail('stale_strategy', '이 제안이 기준으로 삼은 전략이 이미 바뀌었습니다 — 다시 계산하세요');
  end if;
  update drink_strategy_versions set status = 'retired', retired_at = now() where id = v.id;
  insert into drink_strategy_versions (label, weights, status, proposal_id)
    values ('strategy-v' || (select count(*) from drink_strategy_versions), x.weights, 'active', x.id) returning * into nv;
  update drink_strategy_proposals set status = 'accepted', decided_by = coalesce(drinks_text(p, 'actor'), 'operator'),
    decided_at = now(), reason = drinks_text(p, 'reason') where id = x.id returning * into x;
  return jsonb_build_object('proposal_id', x.id, 'status', x.status, 'strategy_id', nv.id, 'label', nv.label);
end $$;

-- 전략 가점: 주종(여럿이면 평균)·갈래·더 잘 맞는 형식의 가중치를 더해 임시 점수에 곱한다(0.5~1.5배).
create or replace function drinks_strategy_lift(w jsonb, p_cats text[], p_lane text, p_post_types text[]) returns numeric
language sql immutable as $$
  select greatest(-0.5, least(0.5,
      coalesce((select avg(coalesce((w -> 'category' ->> c)::numeric, 0)) from unnest(p_cats) c), 0)
    + coalesce((w -> 'lane' ->> p_lane)::numeric, 0)
    + coalesce((select max(coalesce((w -> 'post_type' ->> t)::numeric, 0)) from unnest(p_post_types) t), 0)))
$$;

-- 다음 편성 후보 순서(순환의 마지막 고리): 선별 전 소재를 전략 반영 점수로 줄 세운다.
-- 형식은 적합성 2점 이상인 것만 가점 대상이다(카드에 안 맞는 소재가 카드 가점으로 올라오지 않게).
create or replace function drinks_strategy_rank(p jsonb) returns jsonb language sql stable as $$
  with v as (select * from drink_strategy_versions where status = 'active')
  select jsonb_build_object('strategy', (select label from v), 'weights', (select weights from v), 'topics', coalesce(jsonb_agg(x
    order by (x ->> 'adjusted_score')::numeric desc nulls last, x ->> 'title'), '[]'))
  from (select jsonb_build_object('topic_id', t.id, 'title', t.title, 'status', t.status, 'categories', to_jsonb(t.categories),
      'lane', t.lane, 'provisional_score', t.provisional_score,
      'lift', drinks_strategy_lift((select weights from v), t.categories, t.lane, array_remove(array[
        case when coalesce((t.provisional_scores ->> 'fit_carousel')::int, 0) >= 2 then 'carousel' end,
        case when coalesce((t.provisional_scores ->> 'fit_video')::int, 0) >= 2 then 'reel' end], null)),
      'adjusted_score', round(t.provisional_score * (1 + drinks_strategy_lift((select weights from v), t.categories, t.lane,
        array_remove(array[
          case when coalesce((t.provisional_scores ->> 'fit_carousel')::int, 0) >= 2 then 'carousel' end,
          case when coalesce((t.provisional_scores ->> 'fit_video')::int, 0) >= 2 then 'reel' end], null))), 2)) x
    from drink_topics t where t.status in ('triaged','researching','ready')
    limit coalesce(drinks_int(p, 'limit', false), 200)) q
$$;

-- ─────────────────────────────────────────────────────────────
-- 권한 — 0049·0053 방향 그대로: 공개 직접 접근 차단, 쓰기는 Next 라우트(service key) 경유
-- ─────────────────────────────────────────────────────────────

alter table drink_social_accounts enable row level security;
alter table drink_publication_requests enable row level security;
alter table drink_publication_attempts enable row level security;
alter table drink_post_metric_snapshots enable row level security;
alter table drink_strategy_versions enable row level security;
alter table drink_strategy_proposals enable row level security;

revoke all on table drink_social_accounts, drink_publication_requests, drink_publication_attempts, drink_post_metric_snapshots,
  drink_strategy_versions, drink_strategy_proposals from anon, authenticated;
revoke all on sequence drink_post_metric_snapshots_id_seq from anon, authenticated;
grant select, insert, update on table drink_social_accounts, drink_publication_requests, drink_publication_attempts,
  drink_post_metric_snapshots, drink_strategy_versions, drink_strategy_proposals to service_role;
grant usage on sequence drink_post_metric_snapshots_id_seq to service_role;

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
