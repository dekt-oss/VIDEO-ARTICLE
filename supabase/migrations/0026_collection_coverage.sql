-- 수집 커버리지 개정 v2 (최상위 저널 누락 해결) — docs/deviation-collection-coverage-v2.md
-- 플래그십 본지가 게재일 창으로는 등록 지연 탓에 항상 누락되던 문제를 created_date 워터마크로 해결.
-- 이 마이그레이션은 (1) papers 진단·가시성 컬럼, (2) 워터마크 상태, (3) 발견 이벤트, (4) 미매칭 큐.

-- (1) papers 보강 컬럼 — 전부 nullable additive(기존 1,300+행 무영향).
alter table papers add column if not exists doi text;                   -- 정규화 DOI(=external_id, 명시)
alter table papers add column if not exists work_type text;             -- OpenAlex type(article|review|…)
alter table papers add column if not exists openalex_id text;           -- OpenAlex work id(역참조·진단)
alter table papers add column if not exists source_created_date date;   -- OpenAlex 등록일(지연 진단)

-- (2) 수집 워터마크 상태 — created_date 증분 수집 경계(§3-2). DB 저장 성공 후에만 전진.
create table if not exists collection_state (
  key         text primary key,       -- 예: 'flagship_openalex_created'
  watermark   timestamptz,            -- 마지막 성공 to_created_date
  updated_at  timestamptz not null default now()
);

-- (3) 발견 이벤트(§7) — 한 논문이 여러 경로로 발견될 수 있어 단일 route 컬럼 대신 이벤트로.
create table if not exists paper_discovery_events (
  id                  bigserial primary key,
  paper_id            uuid references papers(id) on delete cascade,
  external_id         text,                 -- 매칭 전에도 기록 가능(논문 생성 전 발견)
  route               text not null,        -- flagship_openalex | main_openalex | arxiv | buzz | eurekalert | physorg | flagship_news
  source_name         text,
  source_item_url     text,
  source_published_at timestamptz,
  discovered_at       timestamptz not null default now(),
  match_method        text,                 -- doi_direct | url_extract | arxiv | title_match | none
  match_confidence    numeric,
  collection_run_id   uuid,
  metadata            jsonb not null default '{}'::jsonb
);
-- NULLS NOT DISTINCT(Postgres 15+): NULL 도 중복 취급 → PostgREST on_conflict 가 평문 컬럼으로 매칭됨.
-- (coalesce() 표현식 인덱스는 on_conflict 대상이 못 된다 — 42P10.)
create unique index if not exists uq_paper_discovery_event
  on paper_discovery_events (route, external_id, source_item_url) nulls not distinct;
create index if not exists paper_discovery_events_paper_idx on paper_discovery_events (paper_id);

-- (4) 미매칭 화제성 큐(§6) — RSS/언론에서 DOI 자동연결 임계 미달 항목을 사람이 검토.
create table if not exists unresolved_buzz_items (
  id              bigserial primary key,
  route           text not null,           -- eurekalert | physorg | flagship_news ...
  title           text,
  source_item_url text,
  candidate_doi   text,
  best_similarity numeric,
  metadata        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);
create unique index if not exists uq_unresolved_buzz
  on unresolved_buzz_items (route, source_item_url) nulls not distinct;

-- 공개 접근 정책(기존 테이블과 동일). 엔진 워커는 service_role 로 동작하므로 정책과 무관.
alter table collection_state enable row level security;
drop policy if exists collection_state_public_all on collection_state;
create policy collection_state_public_all on collection_state for all to anon, authenticated using (true) with check (true);
alter table paper_discovery_events enable row level security;
drop policy if exists paper_discovery_events_public_all on paper_discovery_events;
create policy paper_discovery_events_public_all on paper_discovery_events for all to anon, authenticated using (true) with check (true);
alter table unresolved_buzz_items enable row level security;
drop policy if exists unresolved_buzz_items_public_all on unresolved_buzz_items;
create policy unresolved_buzz_items_public_all on unresolved_buzz_items for all to anon, authenticated using (true) with check (true);
