-- 주류 공장 A단계 — 수동 작업 기반 (2026-10-22, 검토 보완 2026-10-22)
--
-- 명세: docs/주류공장_구조명세_v1_2026-10-21.md §7·§8·§13-A. 구현 결정: docs/deviation-drinks-phase-a.md
--
-- ★ 이 파일은 어느 환경에도 적용된 적이 없다(운영 video-article 의 마지막 마이그레이션은 0049, 브랜치 없음 —
--   2026-10-22 확인). 그래서 검토 보완을 덧대는 마이그레이션을 따로 두지 않고 0050 을 고쳐 썼다.
--   한 번이라도 적용된 뒤에는 이 파일을 고치지 말고 0051 이후로 쌓을 것.
--
-- 무엇을 만드나 — A단계(수동 입력 → 근거 → 선정 → 공통 기획 → 형식별 제작안)에 필요한 것만:
--   drink_source_snapshots        수동 등록 출처(URL·직접 입력한 원문/발췌). 원문 불변, 본문 해시로 중복·변경 판별
--   drink_snapshot_attestations   출처 정보의 정정·재확인·사용 조건 확인·권리 철회 기록(append-only)
--   drink_topics                  소재(질문). 상태·provisional 점수·편성(형식·주차·예외 사유)
--   drink_topic_sources           소재↔출처 연결. 역할 discovery(질문·인기 신호) / evidence(사실 근거)
--   drink_topic_reviews           근거 + 공통 기획 버전. 승인 후 본문 불변, 수정은 새 revision
--   drink_deliverables            소재×형식(video/carousel)×언어 결과물 1개
--   drink_plan_revisions          형식별 제작안 버전. 사용한 근거 버전을 FK 로 고정
--   drink_workflow_events         감사 이력(append-only)
--
-- 만들지 않는 것(B~D단계): 수집원·수집 실행 기록, 제작 작업 큐, 파일·manifest·파일 검수,
--   SNS 계정·발행 요청·성과. 그래서 이 스키마로는 렌더·업로드·발행이 **구조적으로** 불가능하다.
--   기존 paper/report 테이블은 건드리지 않는다.
--
-- 보호 원칙 — UI 가 아니라 DB 가 막는다:
--   · 상태 전이는 전부 drinks_* 함수가 한 트랜잭션으로 처리한다(행 잠금 + version 비교).
--   · 다른 소재의 버전 id 제출은 복합 FK 가 막는다.
--   · 승인·검토 중 본문 수정, 철회 부활, 차단 해제, 감사 이력·정정 이력 수정·삭제는 트리거가 막는다.
--   · 승인 전이는 트리거도 필수 조건(근거·필수 주장 전달)을 다시 잰다 — 함수를 우회한 UPDATE 도 막힌다.
--   · 신규 표·함수는 anon/authenticated 에 아무 권한도 주지 않는다(0049 방향).
--
-- 확정 정책(2026-10-22 운영자):
--   ① 형식 적합성 2점 미만은 경고 + 형식별 예외 사유로 편성 가능. 65점 점수 예외와 칸이 다르다.
--      근거 필수 조건은 어떤 예외로도 넘지 못한다.
--   ② 다른 URL 의 같은 본문은 "같은 본문 후보"로 알리기만 한다. 원출처 묶음은 운영자가 정한다.
--   ③ 새 근거 버전이 생겨도 기존 승인·제작안 참조를 자동 교체·철회하지 않는다.
--
-- 되돌리기: 아래 표 8개와 drinks_* / drink_* 함수를 drop 한다(다른 표는 이 표들을 참조하지 않는다).

-- ─────────────────────────────────────────────────────────────
-- 공통 헬퍼
-- ─────────────────────────────────────────────────────────────

-- 오류는 'drinks:<code>:<문장>' 형식으로 던진다. 라우트가 code 로 HTTP 상태를 고른다.
create or replace function drinks_fail(p_code text, p_msg text, p_detail jsonb default null)
returns void language plpgsql as $$
begin
  raise exception using errcode = 'P0001',
    message = 'drinks:' || p_code || ':' || p_msg,
    detail = coalesce(p_detail::text, '');
end $$;

create or replace function drinks_text(p jsonb, k text) returns text
language sql immutable as $$ select nullif(btrim(p ->> k), '') $$;

create or replace function drinks_uuid(p jsonb, k text, req boolean default true) returns uuid
language plpgsql as $$
declare v text := drinks_text(p, k);
begin
  if v is null then
    if req then perform drinks_fail('invalid_input', k || ' 가 필요합니다'); end if;
    return null;
  end if;
  begin
    return v::uuid;
  exception when invalid_text_representation then
    perform drinks_fail('invalid_input', k || ' 형식이 잘못됐습니다');
  end;
  return null;
end $$;

create or replace function drinks_int(p jsonb, k text, req boolean default true) returns int
language plpgsql as $$
declare v text := drinks_text(p, k);
begin
  if v is null then
    if req then perform drinks_fail('invalid_input', k || ' 가 필요합니다'); end if;
    return null;
  end if;
  if v !~ '^-?[0-9]{1,9}$' then perform drinks_fail('invalid_input', k || ' 는 정수여야 합니다'); end if;
  return v::int;
end $$;

create or replace function drinks_date(p jsonb, k text) returns date
language plpgsql as $$
declare v text := drinks_text(p, k);
begin
  if v is null then return null; end if;
  if v !~ '^\d{4}-\d{2}-\d{2}$' then perform drinks_fail('invalid_input', k || ' 는 YYYY-MM-DD 날짜여야 합니다'); end if;
  begin
    return v::date;
  exception when others then
    perform drinks_fail('invalid_input', k || ' 날짜가 잘못됐습니다');
  end;
  return null;
end $$;

-- 문자열 배열(jsonb)을 text[] 로. 배열이 아니면 빈 배열.
create or replace function drinks_text_array(j jsonb) returns text[]
language sql immutable as $$
  select case when jsonb_typeof(j) = 'array'
    then array(select distinct btrim(x) from jsonb_array_elements_text(j) x where btrim(x) <> '' order by 1)
    else '{}'::text[] end
$$;

-- 인용 대조용 정규화(대소문자·공백 차이 무시). 자동 문자열 일치는 "발췌 존재 확인"일 뿐이다.
create or replace function drinks_norm_text(t text) returns text
language sql immutable as $$ select lower(regexp_replace(btrim(coalesce(t, '')), '\s+', ' ', 'g')) $$;

-- 본문 해시: 공백만 정규화한다(글자 하나라도 바뀌면 다른 버전).
create or replace function drinks_body_hash(t text) returns text
language sql immutable as $$
  select case when t is null then null
    else encode(sha256(convert_to(regexp_replace(btrim(t), '\s+', ' ', 'g'), 'UTF8')), 'hex') end
$$;

create or replace function drinks_dedupe_part(t text) returns text
language sql immutable as $$ select regexp_replace(lower(coalesce(t, '')), '[[:space:][:punct:]]+', '', 'g') $$;

-- 소재 1차 중복키: 주종 + 핵심 질문 + 대상 제품/공정 + 각도(명세 §5.4-3). 병합 "제안"에만 쓴다.
create or replace function drinks_dedupe_key(p_cats text[], p_question text, p_target text, p_angle text)
returns text language sql immutable as $$
  select array_to_string(array(select unnest(p_cats) order by 1), ',')
    || '|' || drinks_dedupe_part(p_question)
    || '|' || drinks_dedupe_part(p_target)
    || '|' || drinks_dedupe_part(p_angle)
$$;

-- 5축 가중 합(명세 §6.3, rubric drinks-v1). 축 하나라도 비면 null — 0점으로 채우지 않는다.
-- web/lib/drinks/model.ts::weightedScore 와 같은 값을 내야 한다(web/lib/drinks/drinks.db.test.ts 가 대조).
create or replace function drinks_weighted_score(s jsonb) returns numeric
language plpgsql immutable as $$
declare k text;
begin
  if s is null or jsonb_typeof(s) <> 'object' then return null; end if;
  foreach k in array array['relevance','utility','curiosity','fit_video','fit_carousel','timeliness'] loop
    if coalesce(jsonb_typeof(s -> k), '') <> 'number' then return null; end if;
  end loop;
  return round(
      25 * (s->>'relevance')::numeric / 4
    + 25 * (s->>'utility')::numeric / 4
    + 20 * (s->>'curiosity')::numeric / 4
    + 20 * greatest((s->>'fit_video')::numeric, (s->>'fit_carousel')::numeric) / 4
    + 10 * (s->>'timeliness')::numeric / 4, 2);
end $$;

-- 점수 입력 검증: 알려진 축만, 0~4 정수만. partial=true 면 빈 축 허용(작성 중 초안).
create or replace function drinks_check_scores(s jsonb, p_partial boolean) returns jsonb
language plpgsql as $$
declare
  axes text[] := array['relevance','utility','curiosity','fit_video','fit_carousel','timeliness'];
  k text; v jsonb; out jsonb := '{}';
begin
  if s is null or s = 'null'::jsonb then
    if p_partial then return out; end if;
    perform drinks_fail('scores_incomplete', '5축 점수를 모두 입력하세요');
  end if;
  if jsonb_typeof(s) <> 'object' then perform drinks_fail('invalid_input', '점수 형식이 잘못됐습니다'); end if;
  for k in select jsonb_object_keys(s) loop
    if not k = any(axes) then perform drinks_fail('invalid_input', '알 수 없는 점수 항목: ' || k); end if;
  end loop;
  foreach k in array axes loop
    v := s -> k;
    if v is null or v = 'null'::jsonb then
      if not p_partial then perform drinks_fail('scores_incomplete', '5축 점수를 모두 입력하세요(' || k || ' 없음)'); end if;
      continue;
    end if;
    if jsonb_typeof(v) <> 'number' or (v::text) !~ '^[0-4]$' then   -- 2.0 같은 소수 표기도 거부(500 대신 깔끔한 오류)
      perform drinks_fail('invalid_input', k || ' 점수는 0~4 정수여야 합니다');
    end if;
    out := out || jsonb_build_object(k, (v::text)::int);
  end loop;
  return out;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_source_snapshots (
  id                uuid primary key default gen_random_uuid(),
  url_raw           text,
  canonical_url     text check (canonical_url is null or canonical_url ~ '^https?://'),
  title             text,
  publisher         text,
  source_kind       text not null default 'other' check (source_kind in
                      ('official','expert','manufacturer','importer','media','retailer','community','reader','other')),
  depth             text not null check (depth in ('metadata_only','excerpt','full_text')),
  body_text         text check (body_text is null or length(body_text) <= 200000),
  excerpt_locator   text,
  content_hash      text,
  original_language text,
  published_at      date,                       -- 자료 발행일. 모르면 null(수집일로 대체 금지)
  checked_at        date,                       -- 처음 등록할 때 원문을 확인한 날(이후 확인은 attestations)
  rights_status     text not null default 'unknown' check (rights_status in
                      ('unknown','quote_ok','summary_only','restricted')),
  usage_terms       text,
  origin_group      text,                       -- 운영자가 확인한 원출처 묶음(자동으로 채우지 않는다)
  supersedes_id     uuid references drink_source_snapshots(id),
  capture_method    text not null default 'manual' check (capture_method = 'manual'),
  created_at        timestamptz not null default now(),
  check ((depth = 'metadata_only') = (body_text is null)),
  check ((body_text is null) = (content_hash is null)),
  check (canonical_url is not null or body_text is not null)
);
create unique index if not exists drink_snapshots_url_hash_uq
  on drink_source_snapshots (canonical_url, content_hash) where canonical_url is not null and content_hash is not null;
create unique index if not exists drink_snapshots_url_meta_uq
  on drink_source_snapshots (canonical_url) where canonical_url is not null and content_hash is null;
create unique index if not exists drink_snapshots_nourl_hash_uq
  on drink_source_snapshots (content_hash) where canonical_url is null;
create index if not exists drink_snapshots_hash_idx on drink_source_snapshots (content_hash);

create table if not exists drink_topics (
  id                       uuid primary key default gen_random_uuid(),
  title                    text not null check (length(btrim(title)) between 1 and 200),
  question                 text not null check (length(btrim(question)) between 1 and 1000),
  reader_value             text,
  categories               text[] not null check (cardinality(categories) between 1 and 3
                             and categories <@ array['sake','traditional','whisky']::text[]),
  lane                     text not null check (lane in ('evergreen','timely','reader_question')),
  target_subject           text,
  angle                    text,
  dedupe_key               text not null,
  reader_signal_count      int not null default 0 check (reader_signal_count >= 0),
  status                   text not null default 'inbox' check (status in
                             ('inbox','triaged','researching','ready','selected','on_hold','rejected','duplicate')),
  provisional_scores       jsonb,
  provisional_score        numeric(5,2),
  provisional_rubric       text,
  current_review_id        uuid,               -- 작업 중인 최신 버전(초안일 수 있다)
  approved_review_id       uuid,               -- 가장 최근에 승인된 버전(철회됐을 수 있다 — 유효성은 그 행이 말한다)
  selected_review_id       uuid,               -- 편성에 쓴 버전
  selected_formats         text[] check (selected_formats is null or (cardinality(selected_formats) between 1 and 2
                             and selected_formats <@ array['video','carousel']::text[])),
  editorial_week           date check (editorial_week is null or extract(isodow from editorial_week) = 1),
  score_exception_reason   text,               -- 65점 미만 예외 편성 사유
  format_exception_reasons jsonb check (format_exception_reasons is null or jsonb_typeof(format_exception_reasons) = 'object'),
                                               -- 형식 적합성 2점 미만 형식별 예외 사유 {video?, carousel?}
  decision_reason_code     text check (decision_reason_code is null or decision_reason_code in
                             ('duplicate','insufficient_evidence','audience_mismatch','hard_to_visualize','expired','cost','other')),
  decision_reason          text,
  hold_until               date,
  canonical_topic_id       uuid references drink_topics(id),
  version                  int not null default 1,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  check (status <> 'selected' or (selected_review_id is not null and selected_formats is not null and editorial_week is not null)),
  check (status <> 'duplicate' or (canonical_topic_id is not null and canonical_topic_id <> id)),
  check (status not in ('on_hold','rejected') or decision_reason is not null),
  check (status not in ('triaged','researching','ready','selected') or provisional_score is not null)
);
create index if not exists drink_topics_status_idx on drink_topics (status);
create index if not exists drink_topics_dedupe_idx on drink_topics (dedupe_key);

create table if not exists drink_topic_sources (
  topic_id      uuid not null references drink_topics(id),
  snapshot_id   uuid not null references drink_source_snapshots(id),
  role          text not null check (role in ('discovery','evidence')),
  relation_note text,
  created_at    timestamptz not null default now(),
  primary key (topic_id, snapshot_id)
);
create index if not exists drink_topic_sources_snapshot_idx on drink_topic_sources (snapshot_id);

-- 출처 정보 정정·재확인. 원문(스냅샷)은 그대로 두고, 그 위의 정보 변경을 순서대로 쌓는다.
-- 유효한 값 = 스냅샷 값 위에 이 기록을 시간순으로 덮은 것(drinks_snapshot_meta).
create table if not exists drink_snapshot_attestations (
  id          uuid primary key default gen_random_uuid(),
  snapshot_id uuid not null references drink_source_snapshots(id),
  topic_id    uuid references drink_topics(id),     -- 어느 소재 화면에서 기록했나(맥락)
  kind        text not null check (kind in ('rights_confirmed','recheck','correction','rights_revoked')),
  fields      jsonb not null default '{}' check (jsonb_typeof(fields) = 'object'),
  reason      text,
  impact      jsonb not null default '{}',          -- 기록 시점의 영향 범위(다른 소재·승인·제작안)
  -- 적용 순서. created_at(now())은 트랜잭션 시작 시각이라 한 트랜잭션 안의 기록끼리 같아지고, UUID 는 순서가 없다.
  -- 기록은 스냅샷 잠금(drinks_lock_snapshot_scope)을 잡은 채 넣으므로 같은 스냅샷에서는 이 번호가 실제 순서다.
  seq         bigint generated always as identity,
  created_at  timestamptz not null default now(),
  unique (seq),
  check (kind not in ('correction','rights_revoked') or reason is not null)
);
create index if not exists drink_attest_snapshot_idx on drink_snapshot_attestations (snapshot_id, seq);

create table if not exists drink_topic_reviews (
  id                 uuid primary key default gen_random_uuid(),
  topic_id           uuid not null references drink_topics(id),
  revision_no        int not null check (revision_no > 0),
  based_on_review_id uuid references drink_topic_reviews(id),
  rubric_version     text not null default 'drinks-v1',
  scores             jsonb not null default '{}',
  score              numeric(5,2),
  evidence_pack      jsonb not null default '{"claims": []}',
  brief              jsonb not null default '{}',
  readiness          jsonb not null default '{"blockers": [], "warnings": []}',
  input_hash         text not null default '',
  status             text not null default 'draft' check (status in ('draft','in_review','approved','changes_requested')),
  submitted_at       timestamptz,
  decided_at         timestamptz,
  decision_note      text,
  approved_hash      text,
  revoked_at         timestamptz,
  revoked_reason     text,
  version            int not null default 1,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (topic_id, revision_no),
  unique (id, topic_id),
  check (revoked_at is null or status = 'approved'),
  check ((revoked_at is null) = (revoked_reason is null)),
  check (status <> 'approved' or approved_hash is not null)
);
-- 소재당 작성 중 초안은 하나 — 중복 요청이 초안을 두 개 만들지 못한다.
create unique index if not exists drink_reviews_one_draft_uq on drink_topic_reviews (topic_id) where status = 'draft';

alter table drink_topics
  add constraint drink_topics_current_review_fk foreign key (current_review_id, id)
    references drink_topic_reviews (id, topic_id),
  add constraint drink_topics_approved_review_fk foreign key (approved_review_id, id)
    references drink_topic_reviews (id, topic_id),
  add constraint drink_topics_selected_review_fk foreign key (selected_review_id, id)
    references drink_topic_reviews (id, topic_id);

create table if not exists drink_deliverables (
  id                  uuid primary key default gen_random_uuid(),
  topic_id            uuid not null references drink_topics(id),
  format              text not null check (format in ('video','carousel')),
  locale              text not null default 'ko' check (locale = 'ko'),
  current_revision_id uuid,
  archived_at         timestamptz,
  version             int not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (topic_id, format, locale),
  unique (id, topic_id, format)
);

create table if not exists drink_plan_revisions (
  id                    uuid primary key default gen_random_uuid(),
  deliverable_id        uuid not null,
  topic_id              uuid not null,
  format                text not null check (format in ('video','carousel')),
  revision_no           int not null check (revision_no > 0),
  topic_review_id       uuid not null,
  plan_json             jsonb not null,
  visual_profile        text,
  brand_profile_version text,
  schema_version        text not null default 'drinks-plan-v2',
  aspect_ratio          text not null check (aspect_ratio in ('9:16','4:5','1:1')),
  input_hash            text not null default '',
  plan_status           text not null default 'draft' check (plan_status in ('draft','in_review','approved','changes_requested')),
  submitted_at          timestamptz,
  decided_at            timestamptz,
  decision_note         text,
  approved_hash         text,
  revoked_at            timestamptz,
  revoked_reason        text,
  blocked_at            timestamptz,
  blocked_reason        text,
  version               int not null default 1,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  foreign key (deliverable_id, topic_id, format) references drink_deliverables (id, topic_id, format),
  foreign key (topic_review_id, topic_id) references drink_topic_reviews (id, topic_id),
  unique (deliverable_id, revision_no),
  unique (id, deliverable_id),
  check ((format = 'video' and jsonb_typeof(plan_json -> 'scenes') = 'array')
      or (format = 'carousel' and jsonb_typeof(plan_json -> 'pages') = 'array')),
  check (plan_status <> 'approved' or approved_hash is not null),
  check ((blocked_at is null) = (blocked_reason is null)),
  check ((revoked_at is null) = (revoked_reason is null))
);
create unique index if not exists drink_plans_one_draft_uq
  on drink_plan_revisions (deliverable_id) where plan_status = 'draft' and blocked_at is null;
create index if not exists drink_plans_review_idx on drink_plan_revisions (topic_review_id);

alter table drink_deliverables
  add constraint drink_deliverables_current_fk foreign key (current_revision_id, id)
    references drink_plan_revisions (id, deliverable_id);

create table if not exists drink_workflow_events (
  id            bigint generated always as identity primary key,
  topic_id      uuid references drink_topics(id),
  entity_type   text not null check (entity_type in ('topic','snapshot','review','deliverable','plan')),
  entity_id     uuid not null,
  action        text not null,
  actor         text not null default 'operator',
  before_status text,
  after_status  text,
  version_ref   text,
  reason        text,
  detail        jsonb not null default '{}',
  created_at    timestamptz not null default now()
);
create index if not exists drink_events_topic_idx on drink_workflow_events (topic_id, id desc);

-- ─────────────────────────────────────────────────────────────
-- 출처 유효 정보 (스냅샷 + 정정·재확인 기록)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_snapshot_meta(p_id uuid) returns jsonb
language plpgsql stable as $$
declare
  s drink_source_snapshots; a record; out jsonb; k text; n int := 0; last_id uuid; last_kind text;
  meta_keys text[] := array['title','publisher','published_at','checked_at','original_language',
                            'excerpt_locator','rights_status','usage_terms'];
begin
  select * into s from drink_source_snapshots where id = p_id;
  if not found then return null; end if;
  out := jsonb_build_object('title', s.title, 'publisher', s.publisher, 'published_at', s.published_at,
    'checked_at', s.checked_at, 'original_language', s.original_language, 'excerpt_locator', s.excerpt_locator,
    'rights_status', s.rights_status, 'usage_terms', s.usage_terms);
  for a in select * from drink_snapshot_attestations where snapshot_id = p_id order by seq loop
    n := n + 1; last_id := a.id; last_kind := a.kind;
    foreach k in array meta_keys loop
      if a.fields ? k then out := out || jsonb_build_object(k, a.fields -> k); end if;
    end loop;
  end loop;
  return out || jsonb_build_object('attestation_count', n, 'last_attestation_id', last_id, 'last_kind', last_kind);
end $$;

create or replace function drinks_snapshot_rights(p_id uuid) returns text
language sql stable as $$ select drinks_snapshot_meta(p_id) ->> 'rights_status' $$;

-- 이 스냅샷을 쓰는 곳: 연결된 소재, 그 근거를 쓰는 승인(철회 안 됨) 버전, 그 버전을 쓰는 제작안(차단 안 됨).
create or replace function drinks_snapshot_impact(p_id uuid) returns jsonb
language sql stable as $$
  with topics as (
    select t.id, t.title, t.status from drink_topic_sources ts join drink_topics t on t.id = ts.topic_id
    where ts.snapshot_id = p_id),
  reviews as (
    select r.id, r.topic_id, r.revision_no,
      exists (select 1 from jsonb_array_elements(r.evidence_pack -> 'claims') c
              cross join jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) x
              where x ->> 'snapshot_id' = p_id::text
                and (c ->> 'claim_id') = any(drinks_text_array(r.brief -> 'selected_claim_ids'))) as core
    from drink_topic_reviews r
    where r.status = 'approved' and r.revoked_at is null
      and exists (select 1 from jsonb_array_elements(r.evidence_pack -> 'claims') c
                  cross join jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) x
                  where x ->> 'snapshot_id' = p_id::text)),
  plans as (
    select p.id, p.topic_id, p.format, p.revision_no, p.plan_status from drink_plan_revisions p
    where p.blocked_at is null and p.topic_review_id in (select id from reviews))
  select jsonb_build_object(
    'topics', coalesce((select jsonb_agg(to_jsonb(topics)) from topics), '[]'),
    'approved_reviews', coalesce((select jsonb_agg(to_jsonb(reviews)) from reviews), '[]'),
    'plans', coalesce((select jsonb_agg(to_jsonb(plans)) from plans), '[]'))
$$;

-- ─────────────────────────────────────────────────────────────
-- 불변·전이 트리거 (함수를 우회한 직접 UPDATE 도 막는다)
-- ─────────────────────────────────────────────────────────────

create or replace function drink_snapshots_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'INSERT' then
    if new.body_text is not null and btrim(new.body_text) = '' then new.body_text := null; end if;
    -- 본문이 없으면 서버가 metadata_only 로 정한다. 클라이언트가 보낸 해시는 쓰지 않는다.
    if new.body_text is null then new.depth := 'metadata_only';
    elsif new.depth is null or new.depth = 'metadata_only' then new.depth := 'excerpt'; end if;
    new.content_hash := drinks_body_hash(new.body_text);
    new.capture_method := 'manual';
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
drop trigger if exists drink_snapshots_guard on drink_source_snapshots;
create trigger drink_snapshots_guard before insert or update or delete on drink_source_snapshots
  for each row execute function drink_snapshots_guard();

create or replace function drink_append_only_guard() returns trigger language plpgsql as $$
begin
  perform drinks_fail('immutable', tg_table_name || ' 는 추가만 할 수 있습니다');
  return null;
end $$;
drop trigger if exists drink_attest_guard on drink_snapshot_attestations;
create trigger drink_attest_guard before update or delete on drink_snapshot_attestations
  for each row execute function drink_append_only_guard();
drop trigger if exists drink_events_guard on drink_workflow_events;
create trigger drink_events_guard before update or delete on drink_workflow_events
  for each row execute function drink_append_only_guard();

-- 연결은 지울 수 없다. 바꿀 수 있는 것은 하나뿐: 질문·인기 신호(discovery)로 붙인 출처를 사실 근거(evidence)로
-- 올리는 것. 근거 → 신호로 내리는 것은 막는다 — 승인 근거가 참조할 수 있다.
create or replace function drink_topic_sources_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' and old.role = 'discovery' and new.role = 'evidence'
      and (new.topic_id, new.snapshot_id, new.created_at) = (old.topic_id, old.snapshot_id, old.created_at) then
    return new;
  end if;
  perform drinks_fail('immutable', '소재·출처 연결은 지울 수 없고, 사실 근거를 신호로 내릴 수 없습니다');
  return null;
end $$;
drop trigger if exists drink_topic_sources_guard on drink_topic_sources;
create trigger drink_topic_sources_guard before update or delete on drink_topic_sources
  for each row execute function drink_topic_sources_guard();

create or replace function drinks_topic_transition_ok(a text, b text) returns boolean
language sql immutable as $$
  select a = b or (a, b) in (
    ('inbox','triaged'), ('inbox','on_hold'), ('inbox','rejected'), ('inbox','duplicate'),
    ('triaged','researching'), ('triaged','on_hold'), ('triaged','rejected'), ('triaged','duplicate'),
    ('researching','ready'), ('researching','on_hold'), ('researching','rejected'), ('researching','duplicate'),
    ('ready','selected'), ('ready','researching'), ('ready','on_hold'), ('ready','rejected'), ('ready','duplicate'),
    ('selected','researching'), ('selected','ready'), ('selected','on_hold'), ('selected','rejected'),
    ('on_hold','inbox'), ('on_hold','triaged'), ('on_hold','researching'), ('on_hold','ready'),
    ('rejected','inbox'), ('rejected','triaged'), ('rejected','researching'), ('rejected','ready'),
    ('duplicate','inbox'), ('duplicate','triaged'), ('duplicate','researching'), ('duplicate','ready'))
$$;

create or replace function drink_topics_guard() returns trigger language plpgsql as $$
declare r drink_topic_reviews;
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '소재는 삭제할 수 없습니다(보류·제외를 쓰세요)'); end if;
  if tg_op = 'UPDATE' then
    if not drinks_topic_transition_ok(old.status, new.status) then
      perform drinks_fail('invalid_transition', old.status || ' → ' || new.status || ' 전이는 허용되지 않습니다');
    end if;
    new.version := old.version + 1;
    new.updated_at := now();
  end if;
  if new.approved_review_id is not null
      and (tg_op = 'INSERT' or new.approved_review_id is distinct from old.approved_review_id) then
    select * into r from drink_topic_reviews where id = new.approved_review_id;
    if not found or r.status <> 'approved' then
      perform drinks_fail('review_not_approved', '승인된 버전만 승인 포인터가 될 수 있습니다');
    end if;
  end if;
  if new.status = 'selected' and (tg_op = 'INSERT' or old.status <> 'selected'
      or new.selected_review_id is distinct from old.selected_review_id) then
    select * into r from drink_topic_reviews where id = new.selected_review_id;
    if not found or r.status <> 'approved' or r.revoked_at is not null then
      perform drinks_fail('review_not_approved', '승인된(철회되지 않은) 근거·기획 버전으로만 편성할 수 있습니다');
    end if;
    -- 함수를 우회한 직접 UPDATE 도 근거 필수 조건(정정·권리 철회 반영)을 다시 잰다.
    if jsonb_array_length(drinks_review_blockers(r.id) -> 'blockers') > 0 then
      perform drinks_fail('review_blocked', '근거 필수 조건이 맞지 않는 버전으로는 편성할 수 없습니다',
        drinks_review_blockers(r.id) -> 'blockers');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_topics_guard on drink_topics;
create trigger drink_topics_guard before insert or update or delete on drink_topics
  for each row execute function drink_topics_guard();

-- 근거 버전 필수 조건(편성 전, §6.2·§7.2) — 트리거와 함수가 같이 쓰므로 표 정의 뒤, 트리거 앞에 둔다.
create or replace function drinks_review_blockers(p_review uuid) returns jsonb
language plpgsql stable as $$
declare
  r drink_topic_reviews; b text[] := '{}'; w text[] := '{}';
  c jsonb; ref jsonb; cid text; core text[]; claim_ids text[]; fmts text[]; f text; req text[];
  has_ref boolean; has_body boolean; has_match boolean; has_usable boolean; groups int;
  s_has_body boolean; s_rights text; m jsonb; state jsonb := '{}';
begin
  select * into r from drink_topic_reviews where id = p_review;
  if not found then perform drinks_fail('not_found', '근거·기획 버전을 찾지 못했습니다'); end if;
  if drinks_weighted_score(r.scores) is null then b := array_append(b, 'scores_incomplete'); end if;
  if drinks_text(r.brief, 'audience_question') is null then b := array_append(b, 'brief_question_missing'); end if;
  if drinks_text(r.brief, 'core_takeaway') is null then b := array_append(b, 'brief_takeaway_missing'); end if;
  claim_ids := array(select x ->> 'claim_id' from jsonb_array_elements(r.evidence_pack -> 'claims') x);
  core := drinks_text_array(r.brief -> 'selected_claim_ids');
  if cardinality(core) = 0 then b := array_append(b, 'no_core_claims'); end if;
  -- 형식별 필수 주장: 제안한 형식마다 그 형식이 반드시 전달할 핵심 주장(빈 목록 금지)
  fmts := drinks_text_array(r.brief -> 'proposed_formats');
  if cardinality(fmts) = 0 then b := array_append(b, 'no_proposed_format'); end if;
  foreach f in array fmts loop
    req := drinks_text_array(r.brief -> 'required_claims' -> f);
    if cardinality(req) = 0 then b := array_append(b, 'required_claims_missing:' || f); end if;
    if exists (select 1 from unnest(req) x where not x = any(core)) then
      b := array_append(b, 'required_claim_not_core:' || f);
    end if;
    -- 형식 적합성은 차단이 아니라 경고(정책 ①). 편성 때 형식별 예외 사유를 받는다.
    if coalesce((r.scores ->> ('fit_' || f))::int, 0) < 2 then w := array_append(w, 'format_fit_low:' || f); end if;
  end loop;
  foreach cid in array core loop
    if not cid = any(claim_ids) then b := array_append(b, 'unknown_claim:' || cid); continue; end if;
    select x into c from jsonb_array_elements(r.evidence_pack -> 'claims') x where x ->> 'claim_id' = cid limit 1;
    if c ->> 'claim_type' = 'opinion' then
      if drinks_text(c, 'attribution') is null then b := array_append(b, 'opinion_unattributed:' || cid); end if;
      continue;
    end if;
    has_ref := false; has_body := false; has_match := false; has_usable := false;
    for ref in select * from jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) loop
      has_ref := true;
      select (s.body_text is not null) into s_has_body from drink_source_snapshots s where s.id = (ref ->> 'snapshot_id')::uuid;
      m := drinks_snapshot_meta((ref ->> 'snapshot_id')::uuid);
      s_rights := m ->> 'rights_status';   -- 정정·철회까지 반영한 사용 조건
      state := state || jsonb_build_object(ref ->> 'snapshot_id', jsonb_build_object('rights', s_rights,
        'attestation', m -> 'last_attestation_id'));
      if s_has_body then has_body := true; end if;
      if ref ->> 'quote_check' = 'matched' then
        has_match := true;
        if s_rights in ('quote_ok','summary_only') then has_usable := true; end if;
      end if;
    end loop;
    if not has_ref then b := array_append(b, 'claim_no_source:' || cid);
    elsif not has_body then b := array_append(b, 'claim_metadata_only:' || cid);
    elsif not has_match then b := array_append(b, 'claim_quote_unmatched:' || cid);
    elsif not has_usable then b := array_append(b, 'claim_rights_unconfirmed:' || cid);
    end if;
    case coalesce(c ->> 'support_review', 'not_reviewed')
      when 'supported' then null;
      when 'conflicting' then b := array_append(b, 'claim_conflicting:' || cid);
      when 'insufficient' then b := array_append(b, 'claim_insufficient:' || cid);
      else b := array_append(b, 'claim_support_not_reviewed:' || cid);
    end case;
    if c -> 'time_sensitive' = 'true'::jsonb then
      if drinks_text(c, 'valid_until') is null or drinks_text(c -> 'scope', 'region') is null then
        b := array_append(b, 'claim_time_scope_missing:' || cid);
      elsif (c ->> 'valid_until')::date < current_date then
        b := array_append(b, 'claim_expired:' || cid);
      end if;
    end if;
    if c ->> 'claim_type' = 'comparison' then
      -- 독립 원출처는 운영자가 묶음을 정한 것만 센다(정책 ②). 묶음 미확인 출처는 독립으로 치지 않는다.
      select count(distinct s.origin_group) into groups
        from jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) x
        join drink_source_snapshots s on s.id = (x ->> 'snapshot_id')::uuid
        where s.origin_group is not null;
      if groups < 2 then w := array_append(w, 'comparison_origin_unconfirmed:' || cid); end if;
    end if;
  end loop;
  return jsonb_build_object('blockers', to_jsonb(b), 'warnings', to_jsonb(w), 'source_state', state,
    'checked_at', now());
end $$;

create or replace function drink_reviews_guard() returns trigger language plpgsql as $$
declare
  frozen_keys text[] := array['version','updated_at'];
  rd jsonb;
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '근거·기획 버전은 삭제할 수 없습니다'); end if;
  if tg_op = 'INSERT' then
    if new.status <> 'draft' or new.revoked_at is not null then
      perform drinks_fail('invalid_transition', '새 버전은 작성 중(draft)으로만 만들 수 있습니다');
    end if;
  else
    if old.revoked_at is not null then
      perform drinks_fail('immutable', '철회된 버전은 바꿀 수 없습니다 — 유효한 근거로 새 버전을 만드세요');
    end if;
    if old.status <> 'draft' and (new.scores, new.evidence_pack, new.brief, new.rubric_version, new.topic_id,
        new.revision_no, new.based_on_review_id) is distinct from (old.scores, old.evidence_pack, old.brief,
        old.rubric_version, old.topic_id, old.revision_no, old.based_on_review_id) then
      perform drinks_fail('immutable', '검토 중·승인된 버전의 본문은 수정할 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    if not (old.status = new.status
        or (old.status = 'draft' and new.status = 'in_review')
        or (old.status = 'in_review' and new.status in ('approved','changes_requested'))) then
      perform drinks_fail('invalid_transition', old.status || ' → ' || new.status || ' 전이는 허용되지 않습니다');
    end if;
    if old.status = 'approved' and (to_jsonb(new) - frozen_keys - 'revoked_at' - 'revoked_reason')
        is distinct from (to_jsonb(old) - frozen_keys - 'revoked_at' - 'revoked_reason') then
      perform drinks_fail('immutable', '승인된 버전은 철회 외에 바꿀 수 없습니다');
    end if;
    if old.status = 'changes_requested' and (to_jsonb(new) - frozen_keys) is distinct from (to_jsonb(old) - frozen_keys) then
      perform drinks_fail('immutable', '변경 요청된 버전은 바꿀 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    new.version := old.version + 1;
    new.updated_at := now();
  end if;
  if new.status = 'draft' then
    new.score := drinks_weighted_score(new.scores);
    new.input_hash := encode(sha256(convert_to(jsonb_build_object(
      'rubric', new.rubric_version, 'scores', new.scores,
      'evidence_pack', new.evidence_pack, 'brief', new.brief)::text, 'UTF8')), 'hex');
  end if;
  if new.status = 'approved' and (tg_op = 'INSERT' or old.status <> 'approved') then
    if new.approved_hash is distinct from new.input_hash then
      perform drinks_fail('review_changed', '승인 대상 본문이 검토 시점과 다릅니다');
    end if;
    -- 본문은 바뀌지 않았으므로(위 불변 검사) 저장된 행으로 잰 결과가 이 승인 대상의 결과다.
    rd := drinks_review_blockers(new.id);
    if jsonb_array_length(rd -> 'blockers') > 0 then
      perform drinks_fail('review_blocked', '필수 조건을 채우지 못한 버전은 승인할 수 없습니다', rd -> 'blockers');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_reviews_guard on drink_topic_reviews;
create trigger drink_reviews_guard before insert or update or delete on drink_topic_reviews
  for each row execute function drink_reviews_guard();

create or replace function drink_deliverables_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '결과물은 삭제할 수 없습니다'); end if;
  if (new.topic_id, new.format, new.locale) is distinct from (old.topic_id, old.format, old.locale) then
    perform drinks_fail('immutable', '결과물의 소재·형식·언어는 바꿀 수 없습니다');
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists drink_deliverables_guard on drink_deliverables;
create trigger drink_deliverables_guard before update or delete on drink_deliverables
  for each row execute function drink_deliverables_guard();

-- 사실 항목 판정(명세 §7.3 확장): 카드는 역할로, 영상은 장면의 content_kind 로.
--   사실 항목 = 설명·비교·체크리스트 페이지, content_kind='fact' 장면. 표지·출처 페이지, 전환 장면은 비사실.
create or replace function drinks_plan_item_is_fact(p_format text, el jsonb) returns boolean
language sql immutable as $$
  select case p_format
    when 'carousel' then coalesce(el ->> 'role', '') in ('explain','compare','checklist')
    else coalesce(el ->> 'content_kind', 'fact') = 'fact' end
$$;

-- 제작안이 근거를 전달하는가: 사실 항목마다 주장 연결이 있고, 이 형식의 필수 주장을 모두 연결했는가.
-- ★ 주장이 연결됐다는 것은 "근거 범위 안에서 말한다"는 표시일 뿐이다. 문장이 그 주장과 맞는지는 사람이 검토한다.
create or replace function drinks_plan_coverage(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql stable as $$
declare
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; i int := 0; no_claim int[] := '{}'; used text[] := '{}'; ref_only text[] := '{}';
  req text[] := drinks_text_array(p_review.brief -> 'required_claims' -> p_format);
  missing text[];
begin
  for el in select * from jsonb_array_elements(coalesce(p_plan -> k, '[]')) loop
    i := i + 1;
    if drinks_plan_item_is_fact(p_format, el) then
      if cardinality(drinks_text_array(el -> 'claim_ids')) = 0 then no_claim := array_append(no_claim, i); end if;
      used := used || drinks_text_array(el -> 'claim_ids');
    else
      -- 표지·출처·전환에 붙은 주장은 참고 연결일 뿐 "전달"이 아니다(전달 계산에서 뺀다).
      ref_only := ref_only || drinks_text_array(el -> 'claim_ids');
    end if;
  end loop;
  missing := array(select x from unnest(req) x where not x = any(used) order by 1);
  return jsonb_build_object('required', to_jsonb(req), 'covered', to_jsonb(array(select distinct unnest(used) order by 1)),
    'reference_only', to_jsonb(array(select distinct x from unnest(ref_only) x where not x = any(used) order by 1)),
    'missing_required', to_jsonb(missing), 'facts_without_claims', to_jsonb(no_claim),
    'required_defined', cardinality(req) > 0,
    'ok', cardinality(req) > 0 and cardinality(missing) = 0 and cardinality(no_claim) = 0);
end $$;

create or replace function drink_plans_guard() returns trigger language plpgsql as $$
declare
  rh text; rv drink_topic_reviews; cov jsonb;
  frozen_keys text[] := array['version','updated_at'];
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '제작안 버전은 삭제할 수 없습니다'); end if;
  if tg_op = 'INSERT' then
    if new.plan_status <> 'draft' or new.blocked_at is not null or new.revoked_at is not null then
      perform drinks_fail('invalid_transition', '새 제작안은 작성 중(draft)으로만 만들 수 있습니다');
    end if;
  else
    if old.blocked_at is not null and new.blocked_at is distinct from old.blocked_at then
      perform drinks_fail('immutable', '차단된 제작안은 차단을 풀 수 없습니다 — 유효한 근거로 새 버전을 만드세요');
    end if;
    if old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at then
      perform drinks_fail('immutable', '철회된 제작안 승인은 되살릴 수 없습니다');
    end if;
    if (old.plan_status <> 'draft' or old.blocked_at is not null) and (new.plan_json, new.topic_review_id,
        new.visual_profile, new.brand_profile_version, new.aspect_ratio, new.schema_version, new.deliverable_id,
        new.topic_id, new.format, new.revision_no) is distinct from (old.plan_json, old.topic_review_id,
        old.visual_profile, old.brand_profile_version, old.aspect_ratio, old.schema_version, old.deliverable_id,
        old.topic_id, old.format, old.revision_no) then
      perform drinks_fail('immutable', '검토 중·승인·차단된 제작안은 수정할 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    if not (old.plan_status = new.plan_status
        or (old.plan_status = 'draft' and new.plan_status = 'in_review')
        or (old.plan_status = 'in_review' and new.plan_status in ('approved','changes_requested'))) then
      perform drinks_fail('invalid_transition', old.plan_status || ' → ' || new.plan_status || ' 전이는 허용되지 않습니다');
    end if;
    if old.blocked_at is not null and new.plan_status <> old.plan_status then
      perform drinks_fail('plan_blocked', '근거 철회로 차단된 제작안은 진행할 수 없습니다');
    end if;
    if old.plan_status in ('approved','changes_requested') and
        (to_jsonb(new) - frozen_keys - 'blocked_at' - 'blocked_reason' - 'revoked_at' - 'revoked_reason')
        is distinct from (to_jsonb(old) - frozen_keys - 'blocked_at' - 'blocked_reason' - 'revoked_at' - 'revoked_reason') then
      perform drinks_fail('immutable', '승인·변경요청된 제작안은 바꿀 수 없습니다');
    end if;
    new.version := old.version + 1;
    new.updated_at := now();
  end if;
  if new.plan_status = 'draft' and new.blocked_at is null then
    select input_hash into rh from drink_topic_reviews where id = new.topic_review_id;
    new.input_hash := encode(sha256(convert_to(jsonb_build_object(
      'plan', new.plan_json, 'review_id', new.topic_review_id, 'review_hash', rh,
      'visual', new.visual_profile, 'brand', new.brand_profile_version,
      'aspect', new.aspect_ratio, 'schema', new.schema_version)::text, 'UTF8')), 'hex');
  end if;
  if new.plan_status in ('in_review','approved') and (tg_op = 'INSERT' or old.plan_status <> new.plan_status) then
    if new.blocked_at is not null then
      perform drinks_fail('plan_blocked', '차단된 제작안은 진행할 수 없습니다');
    end if;
    select * into rv from drink_topic_reviews where id = new.topic_review_id;
    if rv.status <> 'approved' or rv.revoked_at is not null then
      perform drinks_fail('review_not_approved', '이 제작안이 쓴 근거·기획 버전이 승인 상태가 아닙니다');
    end if;
    cov := drinks_plan_coverage(new.format, new.plan_json, rv);
    if not (cov ->> 'ok')::boolean then
      perform drinks_fail('plan_coverage', '제작안이 이 형식의 필수 주장을 전달하지 않거나, 주장 연결 없는 사실 항목이 있습니다', cov);
    end if;
    if jsonb_array_length(drinks_review_blockers(rv.id) -> 'blockers') > 0 then
      perform drinks_fail('review_blocked', '근거 필수 조건이 다시 깨졌습니다(유효 기한·사용 조건 등)',
        drinks_review_blockers(rv.id) -> 'blockers');
    end if;
    if new.plan_status = 'approved' and new.approved_hash is distinct from new.input_hash then
      perform drinks_fail('plan_changed', '승인 대상 제작안이 검토 시점과 다릅니다');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_plans_guard on drink_plan_revisions;
create trigger drink_plans_guard before insert or update or delete on drink_plan_revisions
  for each row execute function drink_plans_guard();

-- ─────────────────────────────────────────────────────────────
-- 내부 헬퍼
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_log(p_topic uuid, p_type text, p_id uuid, p_action text,
  p_before text, p_after text, p_ref text, p_reason text, p_detail jsonb default '{}')
returns void language sql as $$
  insert into drink_workflow_events (topic_id, entity_type, entity_id, action, before_status, after_status,
    version_ref, reason, detail)
  values (p_topic, p_type, p_id, p_action, p_before, p_after, p_ref, p_reason, coalesce(p_detail, '{}'));
$$;

-- 잠금 순서는 항상 topic → review → deliverable → plan(교착 방지).
create or replace function drinks_lock_topic(p_id uuid, p_expected int, p_require boolean default true)
returns drink_topics language plpgsql as $$
declare t drink_topics;
begin
  if p_id is null then perform drinks_fail('invalid_input', 'topic_id 가 필요합니다'); end if;
  select * into t from drink_topics where id = p_id for update;
  if not found then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  if p_require and p_expected is null then perform drinks_fail('invalid_input', 'expected_version 이 필요합니다'); end if;
  if p_expected is not null and t.version <> p_expected then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요',
      jsonb_build_object('current_version', t.version));
  end if;
  return t;
end $$;

-- 공유 출처를 건드리는 동작(원출처 묶음·정정 기록)의 잠금: 그 출처를 쓰는 **모든** 소재를 id 순으로 먼저,
-- 그다음 스냅샷을 id 순으로 잠근다. 두 소재가 같은 출처를 동시에 건드려도 순서가 같아 교착이 생기지 않는다.
create or replace function drinks_lock_snapshot_scope(p_context uuid, p_snaps uuid[]) returns void
language plpgsql as $$
begin
  perform 1 from drink_topics
    where id = p_context or id in (select ts.topic_id from drink_topic_sources ts where ts.snapshot_id = any(p_snaps))
    order by id for update;
  if not found then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  perform 1 from drink_source_snapshots where id = any(p_snaps) order by id for update;
end $$;

-- 근거 팩 정규화: 구조 검증 + 출처 소유 확인 + quote_check 를 **서버가** 계산한다.
create or replace function drinks_normalize_pack(p_topic uuid, p_pack jsonb) returns jsonb
language plpgsql as $$
declare
  c jsonb; ref jsonb; out_claims jsonb := '[]'; out_refs jsonb;
  ids text[] := '{}'; cid text; ctype text; sup text; sid uuid; v_role text; quote text; qc text;
  body text; vu date;
begin
  if p_pack is null or jsonb_typeof(p_pack -> 'claims') is distinct from 'array' then
    perform drinks_fail('invalid_pack', '근거 팩에 claims 배열이 필요합니다');
  end if;
  if jsonb_array_length(p_pack -> 'claims') > 60 then
    perform drinks_fail('invalid_pack', '주장은 60개까지 담을 수 있습니다');
  end if;
  for c in select * from jsonb_array_elements(p_pack -> 'claims') loop
    if jsonb_typeof(c) <> 'object' then perform drinks_fail('invalid_pack', '주장 형식이 잘못됐습니다'); end if;
    cid := drinks_text(c, 'claim_id');
    if cid is null then perform drinks_fail('invalid_pack', '주장마다 claim_id 가 필요합니다'); end if;
    if cid = any(ids) then perform drinks_fail('invalid_pack', '같은 claim_id 가 두 번 있습니다: ' || cid); end if;
    ids := array_append(ids, cid);
    if drinks_text(c, 'text') is null then perform drinks_fail('invalid_pack', cid || ' 주장 문장이 비었습니다'); end if;
    ctype := drinks_text(c, 'claim_type');
    if ctype is null or ctype not in ('product_fact','process','comparison','opinion') then
      perform drinks_fail('invalid_pack', cid || ' 주장 종류가 잘못됐습니다');
    end if;
    sup := coalesce(drinks_text(c, 'support_review'), 'not_reviewed');
    if ctype = 'opinion' then
      sup := 'not_applicable';   -- 취향 평가는 사실 검증 상태를 갖지 않는다(§7.2)
    elsif sup not in ('supported','conflicting','insufficient','not_reviewed') then
      perform drinks_fail('invalid_pack', cid || ' 지지 검토 값이 잘못됐습니다');
    end if;
    if c ? 'source_refs' and jsonb_typeof(c -> 'source_refs') <> 'array' then
      perform drinks_fail('invalid_pack', cid || ' source_refs 는 배열이어야 합니다');
    end if;
    out_refs := '[]';
    for ref in select * from jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) loop
      sid := drinks_uuid(ref, 'snapshot_id');
      select ts.role into v_role from drink_topic_sources ts where ts.topic_id = p_topic and ts.snapshot_id = sid;
      if not found then
        perform drinks_fail('ref_not_owned', cid || ': 이 소재에 연결되지 않은 출처는 근거로 쓸 수 없습니다');
      end if;
      if v_role <> 'evidence' then
        perform drinks_fail('ref_not_evidence', cid || ': 질문·인기 신호 출처는 사실 근거로 쓸 수 없습니다');
      end if;
      select s.body_text into body from drink_source_snapshots s where s.id = sid;
      quote := drinks_text(ref, 'original_quote');
      qc := case
        when body is null or quote is null then 'not_checked'
        when position(drinks_norm_text(quote) in drinks_norm_text(body)) > 0 then 'matched'
        else 'unmatched' end;
      out_refs := out_refs || jsonb_build_array(jsonb_build_object(
        'snapshot_id', sid, 'locator', drinks_text(ref, 'locator'), 'original_quote', quote,
        'translation', drinks_text(ref, 'translation'), 'quote_check', qc));
    end loop;
    vu := drinks_date(c, 'valid_until');
    out_claims := out_claims || jsonb_build_array(jsonb_build_object(
      'claim_id', cid, 'text', drinks_text(c, 'text'), 'claim_type', ctype,
      'attribution', drinks_text(c, 'attribution'),
      'scope', jsonb_build_object(
        'product', drinks_text(c -> 'scope', 'product'), 'region', drinks_text(c -> 'scope', 'region'),
        'lot', drinks_text(c -> 'scope', 'lot'), 'time', drinks_text(c -> 'scope', 'time')),
      'source_refs', out_refs, 'support_review', sup,
      'limitations', drinks_text(c, 'limitations'),
      'time_sensitive', coalesce(c -> 'time_sensitive' = 'true'::jsonb, false),
      'valid_until', to_char(vu, 'YYYY-MM-DD')));
  end loop;
  return jsonb_build_object('claims', out_claims);
end $$;

create or replace function drinks_normalize_brief(b jsonb) returns jsonb language plpgsql as $$
declare fmts text[]; req jsonb;
begin
  if b is null or b = 'null'::jsonb then b := '{}'; end if;
  if jsonb_typeof(b) <> 'object' then perform drinks_fail('invalid_input', '기획 형식이 잘못됐습니다'); end if;
  if b ? 'selected_claim_ids' and jsonb_typeof(b -> 'selected_claim_ids') <> 'array' then
    perform drinks_fail('invalid_input', 'selected_claim_ids 는 배열이어야 합니다');
  end if;
  if b ? 'proposed_formats' and jsonb_typeof(b -> 'proposed_formats') <> 'array' then
    perform drinks_fail('invalid_input', 'proposed_formats 는 배열이어야 합니다');
  end if;
  if b ? 'required_claims' and jsonb_typeof(b -> 'required_claims') not in ('object','null') then
    perform drinks_fail('invalid_input', 'required_claims 는 형식별 객체여야 합니다');
  end if;
  fmts := array(select x from unnest(drinks_text_array(b -> 'proposed_formats')) x where x in ('video','carousel'));
  req := jsonb_build_object(
    'video', to_jsonb(drinks_text_array(b -> 'required_claims' -> 'video')),
    'carousel', to_jsonb(drinks_text_array(b -> 'required_claims' -> 'carousel')));
  return jsonb_build_object(
    'audience_question', drinks_text(b, 'audience_question'),
    'core_takeaway', drinks_text(b, 'core_takeaway'),
    'selected_claim_ids', to_jsonb(drinks_text_array(b -> 'selected_claim_ids')),
    'exclusions', drinks_text(b, 'exclusions'),
    'useful_action', drinks_text(b, 'useful_action'),
    'proposed_formats', to_jsonb(fmts),
    'required_claims', req,
    'followup_question', drinks_text(b, 'followup_question'));
end $$;

create or replace function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql as $$
declare
  core text[] := drinks_text_array(p_review.brief -> 'selected_claim_ids');
  all_claims text[] := array(select x ->> 'claim_id' from jsonb_array_elements(p_review.evidence_pack -> 'claims') x);
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; out jsonb := '[]'; i int := 0; cids text[]; cid text; v_role text; v_kind text; n int;
begin
  if p_plan is null or jsonb_typeof(p_plan -> k) is distinct from 'array' then
    perform drinks_fail('invalid_plan', case k when 'scenes' then '영상 제작안에는 장면(scenes) 배열이 필요합니다'
      else '카드뉴스 제작안에는 페이지(pages) 배열이 필요합니다' end);
  end if;
  n := jsonb_array_length(p_plan -> k);
  if n = 0 then perform drinks_fail('invalid_plan', '장면·페이지가 하나 이상 있어야 합니다'); end if;
  if n > 40 then perform drinks_fail('invalid_plan', '장면·페이지는 40개까지입니다'); end if;
  for el in select * from jsonb_array_elements(p_plan -> k) loop
    i := i + 1;
    if jsonb_typeof(el) <> 'object' then perform drinks_fail('invalid_plan', i || '번 항목 형식이 잘못됐습니다'); end if;
    if el ? 'claim_ids' and jsonb_typeof(el -> 'claim_ids') not in ('array','null') then
      perform drinks_fail('invalid_plan', i || '번 항목 claim_ids 는 배열이어야 합니다');
    end if;
    cids := drinks_text_array(el -> 'claim_ids');
    foreach cid in array cids loop
      if not cid = any(all_claims) then
        perform drinks_fail('plan_claim_unknown', i || '번 항목의 ' || cid || ' 는 이 근거 버전에 없는 주장입니다');
      end if;
      if not cid = any(core) then
        perform drinks_fail('plan_claim_not_core', i || '번 항목이 승인 근거의 핵심 주장이 아닌 ' || cid || ' 를 씁니다');
      end if;
    end loop;
    if p_format = 'video' then
      if drinks_text(el, 'narration') is null then perform drinks_fail('invalid_plan', i || '번 장면에 나레이션이 없습니다'); end if;
      v_role := coalesce(drinks_text(el, 'visual_role'), 'reality');
      if v_role not in ('reality','mechanism','text_card','other') then
        perform drinks_fail('invalid_plan', i || '번 장면의 화면 역할이 잘못됐습니다');
      end if;
      v_kind := coalesce(drinks_text(el, 'content_kind'), 'fact');
      if v_kind not in ('fact','transition') then
        perform drinks_fail('invalid_plan', i || '번 장면 내용 종류는 사실 설명(fact) 또는 도입·전환·마무리(transition)입니다');
      end if;
      if el ? 'timing_sec' and el -> 'timing_sec' <> 'null'::jsonb
          and (jsonb_typeof(el -> 'timing_sec') <> 'number' or (el ->> 'timing_sec')::numeric <= 0
               or (el ->> 'timing_sec')::numeric > 60) then
        perform drinks_fail('invalid_plan', i || '번 장면 길이는 0초 초과 60초 이하 숫자여야 합니다');
      end if;
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'narration', drinks_text(el, 'narration'), 'visual_role', v_role, 'content_kind', v_kind,
        'explanation', drinks_text(el, 'explanation'), 'claim_ids', to_jsonb(cids),
        'timing_sec', case when jsonb_typeof(el -> 'timing_sec') = 'number' then el -> 'timing_sec' end,
        'continuity', drinks_text(el, 'continuity'), 'overlays', drinks_text(el, 'overlays')));
    else
      if el ? 'position' and el -> 'position' <> 'null'::jsonb and el ->> 'position' <> i::text then
        perform drinks_fail('invalid_plan', '페이지 순서는 1부터 빈칸·중복 없이 이어져야 합니다(' || i || '번째)');
      end if;
      v_role := drinks_text(el, 'role');
      if v_role is null or v_role not in ('cover','explain','compare','checklist','source') then
        perform drinks_fail('invalid_plan', i || '번 페이지 역할이 잘못됐습니다');
      end if;
      if drinks_text(el, 'heading') is null then perform drinks_fail('invalid_plan', i || '번 페이지 제목이 없습니다'); end if;
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'role', v_role, 'heading', drinks_text(el, 'heading'),
        'body', drinks_text(el, 'body'), 'graphic_spec', drinks_text(el, 'graphic_spec'),
        'claim_ids', to_jsonb(cids)));
    end if;
  end loop;
  if p_format = 'video' then
    return jsonb_build_object('scenes', out, 'notes', drinks_text(p_plan, 'notes'));
  end if;
  return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
    'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1'));
end $$;

-- 재등록한 정보가 기존(정정 반영) 정보와 다른 칸. 조용히 버리지 않고 돌려준다.
create or replace function drinks_meta_diff(p_id uuid, s jsonb) returns jsonb language plpgsql stable as $$
declare cur jsonb := drinks_snapshot_meta(p_id); k text; out jsonb := '{}'; v text;
begin
  foreach k in array array['title','publisher','published_at','checked_at','original_language',
                           'excerpt_locator','rights_status','usage_terms'] loop
    v := drinks_text(s, k);
    -- 'unknown' 은 "확인 안 함"이다 — 이미 확인된 사용 조건과 다르다고 알리지 않는다(강등은 권리 철회 기록으로만).
    if k = 'rights_status' and v = 'unknown' then continue; end if;
    if v is not null and v is distinct from (cur ->> k) then
      out := out || jsonb_build_object(k, jsonb_build_object('current', cur -> k, 'incoming', v));
    end if;
  end loop;
  return out;
end $$;

create or replace function drinks_add_source_internal(p_topic uuid, s jsonb) returns jsonb
language plpgsql as $$
declare
  v_url text := drinks_text(s, 'canonical_url');
  v_body text := drinks_text(s, 'body_text');
  v_role text := coalesce(drinks_text(s, 'role'), 'evidence');
  v_hash text; v_dedup text; v_existing text; v_promoted boolean := false; v_linked boolean := false;
  snap drink_source_snapshots; prev drink_source_snapshots; v_diff jsonb := '{}'; v_same jsonb;
begin
  if s is null or jsonb_typeof(s) <> 'object' then perform drinks_fail('invalid_input', '출처 형식이 잘못됐습니다'); end if;
  if v_role not in ('discovery','evidence') then perform drinks_fail('invalid_input', '출처 역할이 잘못됐습니다'); end if;
  if v_url is null and v_body is null then
    perform drinks_fail('invalid_input', 'URL 또는 직접 입력한 원문·발췌 중 하나는 있어야 합니다');
  end if;
  if v_url is not null and v_url !~ '^https?://[^\s/]+' then
    perform drinks_fail('invalid_input', 'URL 은 http(s):// 로 시작해야 합니다');
  end if;
  if coalesce(drinks_text(s, 'rights_status'), 'unknown') not in ('unknown','quote_ok','summary_only','restricted') then
    perform drinks_fail('invalid_input', '사용 조건 값이 잘못됐습니다');
  end if;
  v_hash := drinks_body_hash(v_body);
  if v_url is not null then
    select * into snap from drink_source_snapshots
      where canonical_url = v_url and content_hash is not distinct from v_hash limit 1;
  else
    select * into snap from drink_source_snapshots where canonical_url is null and content_hash = v_hash limit 1;
  end if;
  if found then
    v_dedup := 'same_url_same_body';    -- 같은 URL·같은 본문: 새 스냅샷을 만들지 않는다(§5.4-2)
    v_diff := drinks_meta_diff(snap.id, s);
  else
    if v_url is not null then
      select * into prev from drink_source_snapshots where canonical_url = v_url order by created_at desc limit 1;
    end if;
    insert into drink_source_snapshots (url_raw, canonical_url, title, publisher, source_kind, depth, body_text,
      excerpt_locator, original_language, published_at, checked_at, rights_status, usage_terms, origin_group, supersedes_id)
    values (drinks_text(s, 'url_raw'), v_url, drinks_text(s, 'title'), drinks_text(s, 'publisher'),
      coalesce(drinks_text(s, 'source_kind'), 'other'), coalesce(drinks_text(s, 'depth'), 'excerpt'), v_body,
      drinks_text(s, 'excerpt_locator'), drinks_text(s, 'original_language'), drinks_date(s, 'published_at'),
      drinks_date(s, 'checked_at'), coalesce(drinks_text(s, 'rights_status'), 'unknown'), drinks_text(s, 'usage_terms'),
      drinks_text(s, 'origin_group'), prev.id)
    returning * into snap;
    v_dedup := case when prev.id is not null then 'changed_version' else 'new' end;
    perform drinks_log(p_topic, 'snapshot', snap.id, 'snapshot_created', null, snap.depth, snap.content_hash, null,
      jsonb_build_object('dedup', v_dedup, 'supersedes_id', prev.id));
  end if;
  -- 다른 URL 에 글자 그대로 같은 본문 — 전재 의심 신호. 묶지 않고 알린다(정책 ②).
  if v_hash is not null then
    select coalesce(jsonb_agg(jsonb_build_object('snapshot_id', x.id, 'canonical_url', x.canonical_url,
        'origin_group', x.origin_group, 'linked_here', exists (select 1 from drink_topic_sources ts
          where ts.topic_id = p_topic and ts.snapshot_id = x.id))), '[]')
      into v_same from drink_source_snapshots x
      where x.content_hash = v_hash and x.id <> snap.id;
  else
    v_same := '[]';
  end if;
  select role into v_existing from drink_topic_sources where topic_id = p_topic and snapshot_id = snap.id for update;
  if found then
    if v_existing = 'discovery' and v_role = 'evidence' then
      update drink_topic_sources set role = 'evidence', relation_note = coalesce(drinks_text(s, 'relation_note'), relation_note)
        where topic_id = p_topic and snapshot_id = snap.id;
      perform drinks_log(p_topic, 'topic', p_topic, 'source_promoted', 'discovery', 'evidence', snap.id::text, null);
      v_promoted := true; v_existing := 'evidence';
    end if;
  else
    insert into drink_topic_sources (topic_id, snapshot_id, role, relation_note)
      values (p_topic, snap.id, v_role, drinks_text(s, 'relation_note'));
    perform drinks_log(p_topic, 'topic', p_topic, 'source_linked', null, null, snap.id::text, null,
      jsonb_build_object('role', v_role, 'depth', snap.depth, 'dedup', v_dedup));
    v_linked := true; v_existing := v_role;
  end if;
  return jsonb_build_object('snapshot_id', snap.id, 'dedup', v_dedup, 'depth', snap.depth, 'linked', v_linked,
    'promoted', v_promoted, 'role', v_existing, 'origin_group', snap.origin_group, 'supersedes_id', snap.supersedes_id,
    'metadata_diff', v_diff, 'same_body_candidates', v_same);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 공개 RPC (service_role 전용). 인자는 전부 jsonb 하나 — PostgREST rpc 로 { p: {...} }
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_create_topic(p jsonb) returns jsonb language plpgsql as $$
declare
  t drink_topics; cats text[]; v_key text; dups jsonb; src jsonb;
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
  v_key := drinks_dedupe_key(cats, drinks_text(p, 'question'), drinks_text(p, 'target_subject'), drinks_text(p, 'angle'));
  select jsonb_agg(jsonb_build_object('id', id, 'title', title, 'status', status, 'version', version) order by created_at)
    into dups from drink_topics where dedupe_key = v_key and status <> 'duplicate';
  -- 중복 의심은 자동 병합하지 않고 사람에게 묻는다(§5.4-3).
  if dups is not null and coalesce(p -> 'confirm_not_duplicate' = 'true'::jsonb, false) is false then
    perform drinks_fail('duplicate_suggested', '같은 주종·질문·대상·각도의 소재가 이미 있습니다', dups);
  end if;
  insert into drink_topics (title, question, reader_value, categories, lane, target_subject, angle, dedupe_key,
    reader_signal_count)
  values (drinks_text(p, 'title'), drinks_text(p, 'question'), drinks_text(p, 'reader_value'), cats,
    drinks_text(p, 'lane'), drinks_text(p, 'target_subject'), drinks_text(p, 'angle'), v_key,
    greatest(coalesce(drinks_int(p, 'reader_signal_count', false), 0), 0))
  returning * into t;
  perform drinks_log(t.id, 'topic', t.id, 'topic_created', null, t.status, null, null,
    jsonb_build_object('possible_duplicates', coalesce(dups, '[]')));
  if p ? 'source' and p -> 'source' <> 'null'::jsonb then
    src := drinks_add_source_internal(t.id, p -> 'source');
  end if;
  return jsonb_build_object('topic_id', t.id, 'source', src, 'possible_duplicates', coalesce(dups, '[]'));
end $$;

create or replace function drinks_add_source(p jsonb) returns jsonb language plpgsql as $$
declare t drink_topics;
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  if t.status = 'duplicate' then perform drinks_fail('invalid_state', '중복 처리된 소재에는 출처를 붙일 수 없습니다'); end if;
  return drinks_add_source_internal(t.id, p -> 'source');
end $$;

-- 원출처 묶음(정책 ②): 운영자가 확인한 것만. 이 소재에 연결된 출처만 묶을 수 있고, 공유 출처면 영향받는
-- 다른 소재에도 이력을 남긴다.
create or replace function drinks_set_origin_group(p jsonb) returns jsonb language plpgsql as $$
declare
  v_topic uuid := drinks_uuid(p, 'topic_id'); v_group text := drinks_text(p, 'origin_group');
  ids uuid[]; v_id uuid; v_old text; affected jsonb; other uuid;
begin
  if v_topic is null then perform drinks_fail('invalid_input', 'topic_id 가 필요합니다'); end if;
  if jsonb_typeof(p -> 'snapshot_ids') = 'array' then
    begin
      ids := array(select distinct x::uuid from jsonb_array_elements_text(p -> 'snapshot_ids') x);
    exception when invalid_text_representation then
      perform drinks_fail('invalid_input', 'snapshot_ids 형식이 잘못됐습니다');
    end;
  else
    ids := array[drinks_uuid(p, 'snapshot_id')];
  end if;
  if cardinality(ids) = 0 then perform drinks_fail('invalid_input', '묶을 출처를 고르세요'); end if;
  ids := array(select x from unnest(ids) x order by x);
  perform drinks_lock_snapshot_scope(v_topic, ids);
  if exists (select 1 from unnest(ids) x where not exists (
      select 1 from drink_topic_sources ts where ts.topic_id = v_topic and ts.snapshot_id = x)) then
    perform drinks_fail('ownership', '이 소재에 연결된 출처만 묶을 수 있습니다');
  end if;
  foreach v_id in array ids loop
    select origin_group into v_old from drink_source_snapshots where id = v_id;
    update drink_source_snapshots set origin_group = v_group where id = v_id;
    perform drinks_log(v_topic, 'snapshot', v_id, 'origin_group_set', v_old, v_group, null, drinks_text(p, 'reason'),
      jsonb_build_object('grouped_with', to_jsonb(ids)));
    -- 같은 스냅샷을 쓰는 다른 소재에도 남긴다 — 그 소재의 독립 출처 수가 바뀌었을 수 있다.
    for other in select ts.topic_id from drink_topic_sources ts where ts.snapshot_id = v_id and ts.topic_id <> v_topic loop
      perform drinks_log(other, 'snapshot', v_id, 'origin_group_set_elsewhere', v_old, v_group, v_topic::text,
        drinks_text(p, 'reason'));
    end loop;
  end loop;
  select coalesce(jsonb_agg(distinct jsonb_build_object('id', t.id, 'title', t.title)), '[]') into affected
    from drink_topic_sources ts join drink_topics t on t.id = ts.topic_id
    where ts.snapshot_id = any(ids) and ts.topic_id <> v_topic;
  return jsonb_build_object('snapshot_ids', to_jsonb(ids), 'origin_group', v_group, 'affected_topics', affected);
end $$;

-- 출처 정보 정정·재확인·사용 조건 확인·권리 철회(B). 원문과 과거 승인 본문은 바꾸지 않는다.
-- 권리 철회는 영향받는 승인 버전을 돌려주고, revoke_affected=true 면 같은 트랜잭션에서 그 승인을 철회한다.
create or replace function drinks_attest_source(p jsonb) returns jsonb language plpgsql as $$
declare
  v_topic uuid := drinks_uuid(p, 'topic_id'); v_snap uuid := drinks_uuid(p, 'snapshot_id');
  v_kind text := drinks_text(p, 'kind'); v_reason text := drinks_text(p, 'reason');
  f jsonb := coalesce(p -> 'fields', '{}'); out jsonb := '{}'; k text; allowed text[]; v_rights text;
  v_impact jsonb; a drink_snapshot_attestations; rv record; revoked jsonb := '[]'; res jsonb; other uuid;
  breaks jsonb := '[]'; unusable jsonb := '[]'; valid_before uuid[]; invalidated jsonb := '[]';
begin
  if v_topic is null then perform drinks_fail('invalid_input', 'topic_id 가 필요합니다'); end if;
  perform drinks_lock_snapshot_scope(v_topic, array[v_snap]);
  if not exists (select 1 from drink_topic_sources where topic_id = v_topic and snapshot_id = v_snap) then
    perform drinks_fail('ownership', '이 소재에 연결된 출처가 아닙니다');
  end if;
  if jsonb_typeof(f) <> 'object' then perform drinks_fail('invalid_input', '정정 내용 형식이 잘못됐습니다'); end if;
  allowed := case v_kind
    when 'rights_confirmed' then array['rights_status','usage_terms','checked_at']
    when 'recheck' then array['checked_at']
    when 'correction' then array['title','publisher','published_at','original_language','excerpt_locator','usage_terms','checked_at']
    when 'rights_revoked' then array['rights_status','usage_terms']
    else null end;
  if allowed is null then perform drinks_fail('invalid_input', '기록 종류가 잘못됐습니다'); end if;
  for k in select jsonb_object_keys(f) loop
    if not k = any(allowed) then perform drinks_fail('invalid_input', k || ' 는 이 기록 종류로 바꿀 수 없습니다'); end if;
    if k in ('published_at','checked_at') then
      out := out || jsonb_build_object(k, to_char(drinks_date(f, k), 'YYYY-MM-DD'));
    else
      out := out || jsonb_build_object(k, drinks_text(f, k));
    end if;
  end loop;
  v_rights := out ->> 'rights_status';
  if v_kind = 'rights_confirmed' and coalesce(v_rights, '') not in ('quote_ok','summary_only') then
    perform drinks_fail('invalid_input', '사용 조건 확인은 인용 가능 또는 요약·출처 표기만 중 하나여야 합니다');
  end if;
  if v_kind = 'rights_revoked' and coalesce(v_rights, '') not in ('restricted','unknown') then
    perform drinks_fail('invalid_input', '권리 철회는 사용 불가 또는 미확인으로만 바꿀 수 있습니다');
  end if;
  if v_kind = 'recheck' and out ->> 'checked_at' is null then
    perform drinks_fail('invalid_input', '재확인한 날짜를 입력하세요');
  end if;
  if v_kind in ('correction','rights_revoked') and v_reason is null then
    perform drinks_fail('invalid_input', '정정·철회 사유를 입력하세요');
  end if;
  if v_kind = 'correction' and out = '{}'::jsonb then
    perform drinks_fail('invalid_input', '정정할 내용이 없습니다');
  end if;
  v_impact := drinks_snapshot_impact(v_snap);
  -- 기록 전에 필수 조건을 만족하던 승인들. 기록 뒤 깨지는 것만 "이 기록 때문에" 쓸 수 없게 된 것이다.
  valid_before := array(select (x ->> 'id')::uuid from jsonb_array_elements(v_impact -> 'approved_reviews') x
    where jsonb_array_length(drinks_review_blockers((x ->> 'id')::uuid) -> 'blockers') = 0);
  insert into drink_snapshot_attestations (snapshot_id, topic_id, kind, fields, reason, impact)
    values (v_snap, v_topic, v_kind, out, v_reason, v_impact) returning * into a;
  perform drinks_log(v_topic, 'snapshot', v_snap, 'source_' || v_kind, null, v_rights, a.id::text, v_reason,
    jsonb_build_object('fields', out, 'impact', v_impact));
  -- 같은 출처를 쓰는 다른 소재에도 이력을 남긴다 — 그쪽 승인이 이 기록 때문에 막힐 수 있다.
  for other in select ts.topic_id from drink_topic_sources ts where ts.snapshot_id = v_snap and ts.topic_id <> v_topic loop
    perform drinks_log(other, 'snapshot', v_snap, 'source_' || v_kind || '_elsewhere', null, v_rights, a.id::text, v_reason,
      jsonb_build_object('fields', out, 'by_topic', v_topic));
  end loop;
  -- 이 기록 **뒤에** 필수 조건이 실제로 깨진 승인만 고른다(다른 사용 가능한 근거가 있으면 깨지지 않는다).
  select coalesce(jsonb_agg(x), '[]') into breaks from jsonb_array_elements(v_impact -> 'approved_reviews') x
    where (x ->> 'id')::uuid = any(valid_before)
      and jsonb_array_length(drinks_review_blockers((x ->> 'id')::uuid) -> 'blockers') > 0;
  -- 처리 대상 = 이 기록 뒤 "지금 쓸 수 없는" 승인 전부(이번에 새로 깨진 것 + 이미 다른 이유로 깨져 있던 것).
  -- 이미 깨져 있던 승인도 제작안이 미차단으로 남아 있으면 지금 차단하고, 체크박스면 철회한다.
  select coalesce(jsonb_agg(x), '[]') into unusable from jsonb_array_elements(v_impact -> 'approved_reviews') x
    where jsonb_array_length(drinks_review_blockers((x ->> 'id')::uuid) -> 'blockers') > 0;
  -- 깨진 승인은 체크박스와 무관하게 "지금 쓸 수 없음"으로 처리한다: 그 승인을 쓴 제작안 차단 + 소재 상태 맞춤.
  -- revoke_affected=true(권리 철회)면 승인 자체도 철회한다. 승인 본문·해시·승인 당시 source_state 는 그대로 둔다.
  for rv in select (x ->> 'id')::uuid as id from jsonb_array_elements(unusable) x loop
    if v_kind = 'rights_revoked' and coalesce(p -> 'revoke_affected' = 'true'::jsonb, false) then
      res := drinks_revoke_review_internal(rv.id, '출처 권리 철회: ' || v_reason);
      revoked := revoked || jsonb_build_array(res);
    else
      res := drinks_invalidate_review_internal(rv.id, '출처 ' || coalesce(v_kind, '') || ': ' || coalesce(v_reason, '사용 조건 변경'));
      invalidated := invalidated || jsonb_build_array(res);
    end if;
  end loop;
  -- 이 출처를 쓰는 모든 소재의 상태를 지금 유효성에 맞춘다(재확인으로 유효해진 경우 포함). 잠금은 위에서 이미 잡았다.
  for other in select ts.topic_id from drink_topic_sources ts where ts.snapshot_id = v_snap order by ts.topic_id loop
    perform drinks_settle_topic(other, '출처 ' || v_kind || coalesce(': ' || v_reason, ''));
  end loop;
  return jsonb_build_object('attestation_id', a.id, 'kind', v_kind, 'fields', out, 'impact', v_impact,
    'now_blocked_reviews', breaks, 'unusable_reviews', unusable, 'revoked_reviews', revoked, 'invalidated_reviews', invalidated,
    'effective', drinks_snapshot_meta(v_snap));
end $$;

create or replace function drinks_triage(p jsonb) returns jsonb language plpgsql as $$
declare t drink_topics; sc jsonb; v_score numeric;
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_version'));
  if t.status not in ('inbox','triaged') then
    perform drinks_fail('invalid_state', '경량 평가는 등록·분류 단계에서만 바꿀 수 있습니다(조사 이후는 근거·기획 버전에서 채점)');
  end if;
  sc := drinks_check_scores(p -> 'scores', false);
  v_score := drinks_weighted_score(sc);
  update drink_topics set provisional_scores = sc, provisional_score = v_score,
    provisional_rubric = 'drinks-v1', status = 'triaged' where id = t.id returning * into t;
  perform drinks_log(t.id, 'topic', t.id, 'triaged', 'inbox', t.status, 'drinks-v1', drinks_text(p, 'reason'),
    jsonb_build_object('scores', sc, 'score', v_score));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'provisional_score', v_score, 'version', t.version);
end $$;

-- 승인 포인터가 유효하고(철회 안 됨) 필수 조건이 지금도 맞으면 true.
create or replace function drinks_approval_valid(p_review uuid) returns boolean
language sql stable as $$
  select p_review is not null and exists (select 1 from drink_topic_reviews r where r.id = p_review
    and r.status = 'approved' and r.revoked_at is null
    and jsonb_array_length(drinks_review_blockers(r.id) -> 'blockers') = 0)
$$;

create or replace function drinks_topic_action(p jsonb) returns jsonb language plpgsql as $$
declare
  t drink_topics; v_action text := drinks_text(p, 'action'); v_reason text := drinks_text(p, 'reason');
  v_before text; canon drink_topics; v_code text := drinks_text(p, 'reason_code');
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_version'));
  v_before := t.status;
  if v_code is not null and v_code not in ('duplicate','insufficient_evidence','audience_mismatch','hard_to_visualize','expired','cost','other') then
    perform drinks_fail('invalid_input', '사유 분류가 잘못됐습니다');
  end if;
  if v_action = 'start_research' then
    if t.status <> 'triaged' then perform drinks_fail('invalid_state', '경량 평가를 마친 소재만 조사 후보로 고를 수 있습니다'); end if;
    update drink_topics set status = 'researching' where id = t.id returning * into t;
  elsif v_action in ('hold','reject') then
    if t.status not in ('inbox','triaged','researching','ready','selected') then
      perform drinks_fail('invalid_state', '이미 보류·제외·중복 처리된 소재입니다');
    end if;
    if v_reason is null then perform drinks_fail('invalid_input', '사유를 입력하세요'); end if;
    if v_action = 'reject' and v_code is null then perform drinks_fail('invalid_input', '제외 사유 분류를 고르세요'); end if;
    update drink_topics set status = case v_action when 'hold' then 'on_hold' else 'rejected' end,
      decision_reason = v_reason, decision_reason_code = v_code,
      hold_until = case v_action when 'hold' then drinks_date(p, 'hold_until') end
      where id = t.id returning * into t;
  elsif v_action = 'reopen' then
    if t.status not in ('on_hold','rejected','duplicate') then
      perform drinks_fail('invalid_state', '보류·제외·중복 소재만 다시 열 수 있습니다');
    end if;
    -- 이미 승인된 유효 근거가 있으면 편성 가능으로, 버전만 있으면 조사 중으로 돌아간다(처음부터 다시 하지 않는다).
    update drink_topics set status = case
        when drinks_approval_valid(t.approved_review_id) then 'ready'
        when t.current_review_id is not null then 'researching'
        when provisional_score is null then 'inbox' else 'triaged' end,
      decision_reason = null, decision_reason_code = null, hold_until = null, canonical_topic_id = null
      where id = t.id returning * into t;
  elsif v_action = 'mark_duplicate' then
    if t.status not in ('inbox','triaged','researching','ready') then
      perform drinks_fail('invalid_state', '편성·보류·제외된 소재는 중복으로 합칠 수 없습니다');
    end if;
    select * into canon from drink_topics where id = drinks_uuid(p, 'canonical_topic_id');
    if not found or canon.id = t.id then perform drinks_fail('invalid_input', '기준 소재를 다시 고르세요'); end if;
    if canon.status = 'duplicate' then perform drinks_fail('invalid_input', '기준 소재가 이미 다른 소재의 중복입니다'); end if;
    update drink_topics set status = 'duplicate', canonical_topic_id = canon.id,
      decision_reason = coalesce(v_reason, '중복'), decision_reason_code = 'duplicate'
      where id = t.id returning * into t;
  elsif v_action = 'refresh_validity' then
    -- 지금 쓸 수 없는 승인(유효 기한 경과·사용 조건)을 쓰는 제작안을 차단하고 상태를 맞춘다. 승인 기록은 그대로.
    perform drinks_invalidate_review_internal(r.id, coalesce(v_reason, '현재 필수 조건 미달(재확인)'))
      from drink_topic_reviews r
      where r.topic_id = t.id and r.status = 'approved' and r.revoked_at is null
        and jsonb_array_length(drinks_review_blockers(r.id) -> 'blockers') > 0
        and exists (select 1 from drink_plan_revisions pl where pl.topic_review_id = r.id and pl.blocked_at is null);
    t := drinks_settle_topic(t.id, coalesce(v_reason, '현재 유효성 재확인'));
  elsif v_action = 'bump_signal' then
    if t.status = 'duplicate' then perform drinks_fail('invalid_state', '중복 처리된 소재입니다 — 기준 소재에 기록하세요'); end if;
    update drink_topics set reader_signal_count = reader_signal_count + 1 where id = t.id returning * into t;
  else
    perform drinks_fail('invalid_input', '알 수 없는 소재 동작입니다');
  end if;
  perform drinks_log(t.id, 'topic', t.id, v_action, v_before, t.status, null, v_reason,
    jsonb_build_object('reason_code', v_code, 'canonical_topic_id', t.canonical_topic_id));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version);
end $$;

-- 근거·기획 저장. 정책 ③: 새 버전(초안)을 만들어도 소재 상태·기존 승인·편성은 그대로 둔다.
create or replace function drinks_save_review(p jsonb) returns jsonb language plpgsql as $$
declare
  v_topic uuid := drinks_uuid(p, 'topic_id'); v_review uuid := drinks_uuid(p, 'review_id', false);
  t drink_topics; r drink_topic_reviews; base drink_topic_reviews; v_no int;
  v_pack jsonb; v_brief jsonb; v_scores jsonb;
begin
  if v_review is null then
    t := drinks_lock_topic(v_topic, drinks_int(p, 'expected_topic_version'));
  else
    t := drinks_lock_topic(v_topic, null, false);
  end if;
  if t.status not in ('researching','ready','selected') then
    perform drinks_fail('invalid_state', '조사 후보로 고른 소재만 근거·기획을 작성할 수 있습니다');
  end if;
  if v_review is null then
    if exists (select 1 from drink_topic_reviews where topic_id = t.id and status = 'draft') then
      perform drinks_fail('draft_exists', '작성 중인 버전이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
    -- 검토 중인 버전을 두고 새 버전을 만들면 그 검토가 고아가 된다(승인·변경요청 모두 불가). 먼저 결정하게 한다.
    if exists (select 1 from drink_topic_reviews where id = t.current_review_id and status = 'in_review') then
      perform drinks_fail('review_in_progress', '검토 중인 버전이 있습니다 — 승인하거나 변경 요청한 뒤 새 버전을 만드세요');
    end if;
    if t.current_review_id is not null then
      select * into base from drink_topic_reviews where id = t.current_review_id;
    end if;
    v_pack := drinks_normalize_pack(t.id, coalesce(p -> 'evidence_pack', base.evidence_pack, '{"claims": []}'));
    v_brief := drinks_normalize_brief(coalesce(p -> 'brief', base.brief));
    v_scores := drinks_check_scores(coalesce(p -> 'scores', base.scores), true);
    select coalesce(max(revision_no), 0) + 1 into v_no from drink_topic_reviews where topic_id = t.id;
    insert into drink_topic_reviews (topic_id, revision_no, based_on_review_id, scores, evidence_pack, brief)
      values (t.id, v_no, base.id, v_scores, v_pack, v_brief) returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    update drink_topics set current_review_id = r.id where id = t.id returning * into t;
    perform drinks_log(t.id, 'review', r.id, 'review_created', null, 'draft', r.input_hash, null,
      jsonb_build_object('revision_no', v_no, 'based_on', base.id));
  else
    select * into r from drink_topic_reviews where id = v_review for update;
    if not found or r.topic_id <> t.id then
      perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다');
    end if;
    if r.status <> 'draft' then
      perform drinks_fail('immutable', '검토 중·승인된 버전은 수정할 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    if r.version <> drinks_int(p, 'expected_version') then
      perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 화면을 새로 불러오세요',
        jsonb_build_object('current_version', r.version));
    end if;
    update drink_topic_reviews set
      evidence_pack = drinks_normalize_pack(t.id, coalesce(p -> 'evidence_pack', r.evidence_pack)),
      brief = drinks_normalize_brief(coalesce(p -> 'brief', r.brief)),
      scores = drinks_check_scores(coalesce(p -> 'scores', r.scores), true)
      where id = r.id returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    perform drinks_log(t.id, 'review', r.id, 'review_saved', 'draft', 'draft', r.input_hash, null);
  end if;
  return jsonb_build_object('review_id', r.id, 'revision_no', r.revision_no, 'version', r.version,
    'input_hash', r.input_hash, 'score', r.score, 'readiness', r.readiness);
end $$;

-- 승인 철회(공용). 그 근거를 쓴 제작안을 차단하고, 그 버전에 기대던 소재 상태를 조사 중으로 돌린다.
-- 다른 승인 버전(편성에 쓴 옛 버전 등)은 건드리지 않는다(정책 ③).
-- 소재 상태를 "지금 쓸 수 있는가"에 맞춘다(철회·권리 변경 공용). 편성에 쓴 버전이 지금 유효하지 않으면
-- 더 최근의 유효한 승인이 있을 때 편성 가능, 없으면 조사 중. 편성 가능인데 승인이 유효하지 않으면 조사 중.
create or replace function drinks_settle_topic(p_topic uuid, p_reason text default null) returns drink_topics
language plpgsql as $$
declare t drink_topics; v_before text;
begin
  select * into t from drink_topics where id = p_topic for update;
  v_before := t.status;
  if t.status = 'selected' and not drinks_approval_valid(t.selected_review_id) then
    update drink_topics set status = case when drinks_approval_valid(t.approved_review_id) then 'ready' else 'researching' end
      where id = t.id returning * into t;
  elsif t.status = 'ready' and not drinks_approval_valid(t.approved_review_id) then
    update drink_topics set status = 'researching' where id = t.id returning * into t;
  elsif t.status = 'researching' and drinks_approval_valid(t.approved_review_id) then
    -- 사용 조건을 다시 확인해 최근 승인이 지금 유효해지면 다시 편성할 수 있다(제작안 차단은 풀지 않는다).
    update drink_topics set status = 'ready' where id = t.id returning * into t;
  end if;
  if t.status <> v_before then
    perform drinks_log(t.id, 'topic', t.id, 'status_from_evidence', v_before, t.status, null, p_reason);
  end if;
  return t;
end $$;

-- 출처 사용 조건 변경으로 필수 조건이 깨진 승인: **승인 기록은 그대로 두고**(본문·해시·source_state 보존)
-- 그 승인을 쓴 제작안을 차단하고 소재 상태를 맞춘다. 차단은 풀 수 없다 — 권리를 다시 확인해도 자동 부활하지 않는다.
create or replace function drinks_invalidate_review_internal(p_review uuid, p_reason text) returns jsonb
language plpgsql as $$
declare r drink_topic_reviews; t drink_topics; blocked jsonb; v_before text;
begin
  select * into t from drink_topics where id = (select topic_id from drink_topic_reviews where id = p_review) for update;
  select * into r from drink_topic_reviews where id = p_review;
  v_before := t.status;
  with b as (
    update drink_plan_revisions set blocked_at = now(), blocked_reason = 'evidence_invalid: ' || p_reason
      where topic_review_id = r.id and blocked_at is null
      returning id, format, revision_no, plan_status)
  select coalesce(jsonb_agg(jsonb_build_object('plan_id', id, 'format', format, 'revision_no', revision_no,
    'plan_status', plan_status)), '[]') into blocked from b;
  perform drinks_log(t.id, 'review', r.id, 'evidence_invalidated', 'approved', 'approved', r.input_hash, p_reason,
    jsonb_build_object('blocked_plans', blocked, 'current_blockers', drinks_review_blockers(r.id) -> 'blockers'));
  t := drinks_settle_topic(t.id, p_reason);
  return jsonb_build_object('review_id', r.id, 'topic_id', t.id, 'revoked', false, 'topic_status', t.status,
    'blocked_plans', blocked);
end $$;

create or replace function drinks_revoke_review_internal(p_review uuid, p_reason text) returns jsonb
language plpgsql as $$
declare r drink_topic_reviews; t drink_topics; blocked jsonb; v_before text;
begin
  select * into t from drink_topics where id = (select topic_id from drink_topic_reviews where id = p_review) for update;
  select * into r from drink_topic_reviews where id = p_review for update;
  if r.status <> 'approved' or r.revoked_at is not null then
    perform drinks_fail('invalid_state', '승인된(철회되지 않은) 버전만 철회할 수 있습니다');
  end if;
  if p_reason is null then perform drinks_fail('invalid_input', '철회 사유를 입력하세요'); end if;
  v_before := t.status;
  update drink_topic_reviews set revoked_at = now(), revoked_reason = p_reason where id = r.id returning * into r;
  with b as (
    update drink_plan_revisions set blocked_at = now(), blocked_reason = 'evidence_revoked: ' || p_reason
      where topic_review_id = r.id and blocked_at is null
      returning id, format, revision_no, plan_status)
  select coalesce(jsonb_agg(jsonb_build_object('plan_id', id, 'format', format, 'revision_no', revision_no,
    'plan_status', plan_status)), '[]') into blocked from b;
  perform drinks_log(t.id, 'review', r.id, 'review_revoke', 'approved', 'approved', r.input_hash, p_reason,
    jsonb_build_object('blocked_plans', blocked, 'revoked', true));
  t := drinks_settle_topic(t.id, p_reason);
  return jsonb_build_object('review_id', r.id, 'topic_id', t.id, 'status', r.status, 'version', r.version,
    'revoked', true, 'topic_status', t.status, 'blocked_plans', blocked);
end $$;

create or replace function drinks_review_action(p jsonb) returns jsonb language plpgsql as $$
declare
  v_id uuid := drinks_uuid(p, 'review_id'); v_action text := drinks_text(p, 'action');
  v_reason text := drinks_text(p, 'reason'); v_topic uuid;
  t drink_topics; r drink_topic_reviews; rd jsonb; v_before text; v_tbefore text;
begin
  select topic_id into v_topic from drink_topic_reviews where id = v_id;
  if not found then perform drinks_fail('not_found', '근거·기획 버전을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(v_topic, null, false);
  v_tbefore := t.status;
  select * into r from drink_topic_reviews where id = v_id for update;
  if r.version <> drinks_int(p, 'expected_version') then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요',
      jsonb_build_object('current_version', r.version));
  end if;
  if v_action = 'revoke' then
    return drinks_revoke_review_internal(r.id, v_reason);
  end if;
  v_before := r.status;
  if v_action in ('submit','approve','request_changes') and t.current_review_id is distinct from r.id then
    perform drinks_fail('review_not_current', '최신 버전이 아닙니다 — 최신 버전을 검토하세요');
  end if;
  if v_action in ('submit','approve') and t.status in ('on_hold','rejected','duplicate') then
    perform drinks_fail('invalid_state', '보류·제외·중복 소재의 버전은 진행할 수 없습니다');
  end if;
  if v_action = 'submit' then
    if r.status <> 'draft' then perform drinks_fail('invalid_state', '작성 중인 버전만 검토에 올릴 수 있습니다'); end if;
    rd := drinks_review_blockers(r.id);
    update drink_topic_reviews set status = 'in_review', submitted_at = now(), readiness = rd
      where id = r.id returning * into r;
  elsif v_action = 'approve' then
    if r.status <> 'in_review' then perform drinks_fail('invalid_state', '검토 중인 버전만 승인할 수 있습니다'); end if;
    rd := drinks_review_blockers(r.id);
    if jsonb_array_length(rd -> 'blockers') > 0 then
      perform drinks_fail('review_blocked', '필수 조건을 채우지 못해 승인할 수 없습니다', rd -> 'blockers');
    end if;
    -- readiness 에는 승인 시점 출처 사용 조건(source_state)이 같이 남는다 — 이후 정정과 대조할 기준.
    update drink_topic_reviews set status = 'approved', approved_hash = r.input_hash, decided_at = now(),
      decision_note = v_reason, readiness = rd where id = r.id returning * into r;
    update drink_topics set approved_review_id = r.id,
      status = case when status = 'researching' then 'ready' else status end
      where id = t.id returning * into t;
  elsif v_action = 'request_changes' then
    if r.status <> 'in_review' then perform drinks_fail('invalid_state', '검토 중인 버전만 변경 요청할 수 있습니다'); end if;
    if v_reason is null then perform drinks_fail('invalid_input', '변경 요청 사유를 입력하세요'); end if;
    update drink_topic_reviews set status = 'changes_requested', decided_at = now(), decision_note = v_reason
      where id = r.id returning * into r;
  else
    perform drinks_fail('invalid_input', '알 수 없는 검토 동작입니다');
  end if;
  perform drinks_log(t.id, 'review', r.id, 'review_' || v_action, v_before, r.status, r.input_hash, v_reason,
    jsonb_build_object('readiness', rd));
  if t.status <> v_tbefore then
    perform drinks_log(t.id, 'topic', t.id, 'status_from_review', v_tbefore, t.status, r.id::text, v_reason);
  end if;
  return jsonb_build_object('review_id', r.id, 'status', r.status, 'version', r.version, 'revoked', false,
    'topic_status', t.status, 'readiness', rd, 'blocked_plans', '[]'::jsonb);
end $$;

-- 편성. 정책 ①: 적합성 2점 미만 형식은 형식별 예외 사유가 있어야 하고(65점 예외와 별개),
-- 근거 필수 조건은 어떤 예외로도 넘지 못한다. 정책 ③: 편성 버전은 "가장 최근 승인 버전"(또는 이미 편성에 쓴 버전).
create or replace function drinks_select(p jsonb) returns jsonb language plpgsql as $$
declare
  t drink_topics; r drink_topic_reviews; rd jsonb; fmts text[]; f text; v_week date; v_exc text;
  v_before text; v_score numeric; fx jsonb := coalesce(p -> 'format_exceptions', '{}'); fx_out jsonb := '{}';
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_version'));
  v_before := t.status;
  if t.status not in ('ready','selected') then
    perform drinks_fail('invalid_state', '근거·기획이 승인된(편성 가능) 소재만 편성할 수 있습니다');
  end if;
  select * into r from drink_topic_reviews where id = drinks_uuid(p, 'review_id') for update;
  if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다'); end if;
  if r.status <> 'approved' or r.revoked_at is not null then
    perform drinks_fail('review_not_approved', '승인된(철회되지 않은) 근거·기획 버전으로만 편성할 수 있습니다');
  end if;
  if not (r.id = t.approved_review_id or (t.status = 'selected' and r.id = t.selected_review_id)) then
    perform drinks_fail('review_not_current', '가장 최근 승인 버전(또는 이미 편성에 쓴 버전)으로만 편성할 수 있습니다');
  end if;
  if drinks_text(p, 'review_input_hash') is distinct from r.approved_hash or r.approved_hash <> r.input_hash then
    perform drinks_fail('review_changed', '화면에서 본 승인 버전과 서버의 버전이 다릅니다 — 새로 불러오세요');
  end if;
  rd := drinks_review_blockers(r.id);
  if jsonb_array_length(rd -> 'blockers') > 0 then
    perform drinks_fail('review_blocked', '필수 조건이 다시 깨졌습니다(유효 기한·사용 조건 등)', rd -> 'blockers');
  end if;
  if jsonb_typeof(p -> 'formats') is distinct from 'array' then perform drinks_fail('invalid_input', '형식을 고르세요'); end if;
  if jsonb_typeof(fx) <> 'object' then perform drinks_fail('invalid_input', '형식 예외 사유 형식이 잘못됐습니다'); end if;
  fmts := drinks_text_array(p -> 'formats');
  if cardinality(fmts) = 0 or not fmts <@ array['video','carousel'] then
    perform drinks_fail('invalid_input', '형식은 영상·카드뉴스 중 하나 이상 고르세요');
  end if;
  foreach f in array fmts loop
    if cardinality(drinks_text_array(r.brief -> 'required_claims' -> f)) = 0 then
      perform drinks_fail('required_claims_missing', case f when 'video' then '영상' else '카드뉴스' end
        || ' 형식의 필수 주장이 승인 기획에 없습니다 — 기획에서 형식과 필수 주장을 정해 다시 승인하세요');
    end if;
    if coalesce((r.scores ->> ('fit_' || f))::int, 0) < 2 then
      if drinks_text(fx, f) is null then
        perform drinks_fail('format_fit_low', case f when 'video' then '영상' else '카드뉴스' end
          || ' 적합성이 2점 미만입니다 — 이 형식으로 편성하려면 형식 예외 사유를 입력하세요');
      end if;
      fx_out := fx_out || jsonb_build_object(f, drinks_text(fx, f));
    end if;
  end loop;
  if t.selected_formats is not null then
    foreach f in array t.selected_formats loop
      if not f = any(fmts) and exists (select 1 from drink_plan_revisions
          where topic_id = t.id and format = f and blocked_at is null) then
        perform drinks_fail('format_in_use', '제작안이 있는 형식은 편성에서 뺄 수 없습니다');
      end if;
    end loop;
  end if;
  v_week := drinks_date(p, 'editorial_week');
  if v_week is null then perform drinks_fail('invalid_input', '편성 주차를 고르세요'); end if;
  v_week := v_week - (extract(isodow from v_week)::int - 1);   -- 그 주 월요일로 맞춘다
  v_score := drinks_weighted_score(r.scores);
  v_exc := drinks_text(p, 'score_exception_reason');
  if v_score < 65 and v_exc is null then
    perform drinks_fail('below_threshold', '점수 ' || v_score || '점(기준 65점 미만) — 점수 예외 편성 사유를 입력하세요');
  end if;
  update drink_topics set status = 'selected', selected_review_id = r.id, selected_formats = fmts,
    editorial_week = v_week, score_exception_reason = case when v_score < 65 then v_exc end,
    format_exception_reasons = case when fx_out = '{}'::jsonb then null else fx_out end
    where id = t.id returning * into t;
  perform drinks_log(t.id, 'topic', t.id, 'selected', v_before, t.status, r.id::text, v_exc,
    jsonb_build_object('formats', fmts, 'editorial_week', v_week, 'score', v_score, 'review_hash', r.approved_hash,
      'score_exception_reason', t.score_exception_reason, 'format_exception_reasons', t.format_exception_reasons,
      'warnings', rd -> 'warnings'));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version,
    'selected_formats', to_jsonb(fmts), 'editorial_week', v_week, 'format_exception_reasons', t.format_exception_reasons);
end $$;

create or replace function drinks_save_plan(p jsonb) returns jsonb language plpgsql as $$
declare
  t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions;
  v_fmt text := drinks_text(p, 'format'); v_rev uuid := drinks_uuid(p, 'revision_id', false);
  v_plan jsonb; v_no int; v_aspect text;
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  if v_fmt is null or v_fmt not in ('video','carousel') then perform drinks_fail('invalid_input', '형식이 잘못됐습니다'); end if;
  if t.status <> 'selected' or not v_fmt = any(t.selected_formats) then
    perform drinks_fail('format_not_selected', '편성된 형식에서만 제작안을 쓸 수 있습니다');
  end if;
  select * into r from drink_topic_reviews where id = drinks_uuid(p, 'topic_review_id');
  if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다'); end if;
  if r.status <> 'approved' or r.revoked_at is not null then
    perform drinks_fail('review_not_approved', '승인된(철회되지 않은) 근거·기획 버전으로만 제작안을 쓸 수 있습니다');
  end if;
  if not drinks_approval_valid(r.id) then
    perform drinks_fail('review_blocked', '이 근거·기획 버전은 지금 필수 조건을 만족하지 않습니다(사용 조건·유효 기한)',
      drinks_review_blockers(r.id) -> 'blockers');
  end if;
  v_plan := drinks_validate_plan(v_fmt, p -> 'plan_json', r);
  v_aspect := coalesce(drinks_text(p, 'aspect_ratio'), case v_fmt when 'video' then '9:16' else '4:5' end);
  select * into d from drink_deliverables where topic_id = t.id and format = v_fmt and locale = 'ko' for update;
  if not found then
    insert into drink_deliverables (topic_id, format) values (t.id, v_fmt) returning * into d;
    perform drinks_log(t.id, 'deliverable', d.id, 'deliverable_created', null, null, v_fmt, null);
  end if;
  if v_rev is null then
    if exists (select 1 from drink_plan_revisions where deliverable_id = d.id and plan_status = 'draft' and blocked_at is null) then
      perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
    if d.current_revision_id is not null and d.version is distinct from drinks_int(p, 'expected_deliverable_version', false) then
      perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 화면을 새로 불러오세요');
    end if;
    select coalesce(max(revision_no), 0) + 1 into v_no from drink_plan_revisions where deliverable_id = d.id;
    insert into drink_plan_revisions (deliverable_id, topic_id, format, revision_no, topic_review_id, plan_json,
      visual_profile, brand_profile_version, aspect_ratio)
    values (d.id, t.id, v_fmt, v_no, r.id, v_plan, drinks_text(p, 'visual_profile'),
      drinks_text(p, 'brand_profile_version'), v_aspect)
    returning * into pr;
    update drink_deliverables set current_revision_id = pr.id where id = d.id returning * into d;
    perform drinks_log(t.id, 'plan', pr.id, 'plan_created', null, 'draft', pr.input_hash, null,
      jsonb_build_object('format', v_fmt, 'revision_no', v_no, 'topic_review_id', r.id));
  else
    select * into pr from drink_plan_revisions where id = v_rev for update;
    if not found or pr.deliverable_id <> d.id then perform drinks_fail('ownership', '이 결과물의 제작안 버전이 아닙니다'); end if;
    if pr.blocked_at is not null then perform drinks_fail('plan_blocked', '차단된 제작안은 고칠 수 없습니다 — 새 버전을 만드세요'); end if;
    if pr.plan_status <> 'draft' then
      perform drinks_fail('immutable', '검토 중·승인된 제작안은 수정할 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    if pr.version <> drinks_int(p, 'expected_version') then
      perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 화면을 새로 불러오세요',
        jsonb_build_object('current_version', pr.version));
    end if;
    update drink_plan_revisions set plan_json = v_plan, topic_review_id = r.id,
      visual_profile = drinks_text(p, 'visual_profile'), brand_profile_version = drinks_text(p, 'brand_profile_version'),
      aspect_ratio = v_aspect where id = pr.id returning * into pr;
    perform drinks_log(t.id, 'plan', pr.id, 'plan_saved', 'draft', 'draft', pr.input_hash, null);
  end if;
  return jsonb_build_object('revision_id', pr.id, 'deliverable_id', d.id, 'revision_no', pr.revision_no,
    'version', pr.version, 'input_hash', pr.input_hash, 'coverage', drinks_plan_coverage(v_fmt, pr.plan_json, r));
end $$;

create or replace function drinks_plan_action(p jsonb) returns jsonb language plpgsql as $$
declare
  v_id uuid := drinks_uuid(p, 'revision_id'); v_action text := drinks_text(p, 'action');
  v_reason text := drinks_text(p, 'reason'); v_topic uuid;
  t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions; v_before text;
  v_mismatch boolean := false; cov jsonb; rd jsonb;
begin
  select topic_id into v_topic from drink_plan_revisions where id = v_id;
  if not found then perform drinks_fail('not_found', '제작안을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(v_topic, null, false);
  select * into pr from drink_plan_revisions where id = v_id;
  select * into d from drink_deliverables where id = pr.deliverable_id for update;
  select * into pr from drink_plan_revisions where id = v_id for update;
  if pr.version <> drinks_int(p, 'expected_version') then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요',
      jsonb_build_object('current_version', pr.version));
  end if;
  v_before := pr.plan_status;
  if v_action in ('submit','approve') then
    if pr.blocked_at is not null then perform drinks_fail('plan_blocked', '근거 철회로 차단된 제작안입니다 — 유효한 근거로 새 버전을 만드세요'); end if;
    if d.current_revision_id is distinct from pr.id then perform drinks_fail('plan_not_current', '최신 제작안이 아닙니다'); end if;
    if t.status <> 'selected' or not pr.format = any(t.selected_formats) then
      perform drinks_fail('format_not_selected', '편성된 형식이 아닙니다');
    end if;
    select * into r from drink_topic_reviews where id = pr.topic_review_id;
    if r.status <> 'approved' or r.revoked_at is not null then
      perform drinks_fail('review_not_approved', '이 제작안이 쓴 근거·기획 버전이 승인 상태가 아닙니다');
    end if;
    v_mismatch := r.id is distinct from t.selected_review_id;
    cov := drinks_plan_coverage(pr.format, pr.plan_json, r);
    if not (cov ->> 'ok')::boolean then
      perform drinks_fail('plan_coverage', '제작안이 이 형식의 필수 주장을 전달하지 않거나, 주장 연결 없는 사실 항목이 있습니다', cov);
    end if;
    if v_action in ('submit','approve') then
      rd := drinks_review_blockers(r.id);
      if jsonb_array_length(rd -> 'blockers') > 0 then
        perform drinks_fail('review_blocked', '근거 필수 조건이 다시 깨졌습니다(유효 기한·사용 조건 등) — 근거를 다시 확인하세요',
          rd -> 'blockers');
      end if;
    end if;
  end if;
  if v_action = 'submit' then
    if pr.plan_status <> 'draft' then perform drinks_fail('invalid_state', '작성 중인 제작안만 검토에 올릴 수 있습니다'); end if;
    update drink_plan_revisions set plan_status = 'in_review', submitted_at = now() where id = pr.id returning * into pr;
  elsif v_action = 'approve' then
    if pr.plan_status <> 'in_review' then perform drinks_fail('invalid_state', '검토 중인 제작안만 승인할 수 있습니다'); end if;
    update drink_plan_revisions set plan_status = 'approved', approved_hash = pr.input_hash, decided_at = now(),
      decision_note = v_reason where id = pr.id returning * into pr;
  elsif v_action = 'request_changes' then
    if pr.plan_status <> 'in_review' then perform drinks_fail('invalid_state', '검토 중인 제작안만 변경 요청할 수 있습니다'); end if;
    if v_reason is null then perform drinks_fail('invalid_input', '변경 요청 사유를 입력하세요'); end if;
    update drink_plan_revisions set plan_status = 'changes_requested', decided_at = now(), decision_note = v_reason
      where id = pr.id returning * into pr;
  else
    perform drinks_fail('invalid_input', '알 수 없는 제작안 동작입니다');
  end if;
  perform drinks_log(t.id, 'plan', pr.id, 'plan_' || v_action, v_before, pr.plan_status, pr.input_hash, v_reason,
    jsonb_build_object('format', pr.format, 'review_mismatch', v_mismatch, 'coverage', cov));
  return jsonb_build_object('revision_id', pr.id, 'plan_status', pr.plan_status, 'version', pr.version,
    'review_mismatch', v_mismatch, 'coverage', cov);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 현재 유효성: "승인했던 기록"(drink_topic_reviews.status/approved_hash/readiness)과 "지금 쓸 수 있는가"를 나눈다.
-- 지금 판정은 저장하지 않고 매번 잰다 — 정정 기록·유효 기한까지 반영되고, 과거 승인 스냅샷을 덮어쓰지 않는다.
-- 화면(선별·작업함·제작·기획·제작안)이 모두 이 뷰를 읽고, 서버 판정(drinks_approval_valid)과 같은 함수를 쓴다.
-- ─────────────────────────────────────────────────────────────

create or replace view drink_review_validity with (security_invoker = true) as
  select r.id as review_id, r.topic_id, b.blk as current_blockers,
    (r.status = 'approved' and r.revoked_at is null and jsonb_array_length(b.blk) = 0) as currently_valid
  from drink_topic_reviews r
  cross join lateral (select case when r.status = 'approved'
    then drinks_review_blockers(r.id) -> 'blockers' else '[]'::jsonb end as blk) b;

-- ─────────────────────────────────────────────────────────────
-- 권한: RLS on + anon/authenticated 전면 차단. 함수 실행은 service_role 만.
-- ─────────────────────────────────────────────────────────────

alter table drink_source_snapshots enable row level security;
alter table drink_snapshot_attestations enable row level security;
alter table drink_topics enable row level security;
alter table drink_topic_sources enable row level security;
alter table drink_topic_reviews enable row level security;
alter table drink_deliverables enable row level security;
alter table drink_plan_revisions enable row level security;
alter table drink_workflow_events enable row level security;

revoke all on table drink_source_snapshots, drink_snapshot_attestations, drink_topics, drink_topic_sources,
  drink_topic_reviews, drink_deliverables, drink_plan_revisions, drink_workflow_events from anon, authenticated;
revoke all on sequence drink_workflow_events_id_seq from anon, authenticated;
revoke all on table drink_review_validity from anon, authenticated;
grant select on table drink_review_validity to service_role;
-- service_role 권한을 Supabase 기본 권한에 기대지 않고 명시한다 — 테스트 하네스가 따로 부여해 누락을 가리지 않게.
-- 삭제 권한은 주지 않는다(트리거도 막지만 권한부터 없다).
grant select, insert, update on table drink_source_snapshots, drink_snapshot_attestations, drink_topics,
  drink_topic_sources, drink_topic_reviews, drink_deliverables, drink_plan_revisions, drink_workflow_events
  to service_role;
grant usage on sequence drink_workflow_events_id_seq to service_role;
revoke all on sequence drink_snapshot_attestations_seq_seq from anon, authenticated;
grant usage on sequence drink_snapshot_attestations_seq_seq to service_role;

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

-- 확인(적용 후):
--   select has_table_privilege('anon', 'public.drink_topics', 'SELECT');                 → false
--   select has_function_privilege('anon', 'public.drinks_select(jsonb)', 'EXECUTE');     → false
