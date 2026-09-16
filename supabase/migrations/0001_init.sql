-- video-article 초기 스키마 (명세 4절)
-- 메타데이터만 저장(PDF 미저장, 링크만). 중복·재탕 방지는 papers.external_id unique 로.

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- 수집·점수 매긴 논문 (메타데이터만)
create table if not exists papers (
  id             uuid primary key default gen_random_uuid(),
  external_id    text unique,          -- DOI 또는 arXiv ID (중복제거 키)
  source         text,                 -- 'openalex' | 'arxiv'
  title          text,
  abstract       text,
  authors        jsonb,
  venue          text,
  published_date date,
  url            text,                 -- 원문 링크
  lang           text,                 -- 1차 필터 언어 판별 결과
  buzz_raw       jsonb,                -- HN/Reddit 신호 원본
  collected_at   timestamptz default now()
);
create index if not exists papers_published_date_idx on papers (published_date desc);

create table if not exists scores (
  paper_id         uuid primary key references papers(id) on delete cascade,
  surprise         int,
  explainability   int,
  relatability     int,
  significance     int,
  buzz             numeric,            -- ⑤ 정규화 화제성(코드 계산)
  fun_index        numeric,            -- 재미 지수(코드 계산)
  importance_index numeric,            -- 중요성 지수(코드 계산)
  one_liner_ko     text,
  one_liner_en     text,
  rationale        text,
  red_flag         text,
  model            text,
  scored_at        timestamptz default now()
);

create table if not exists daily_batch (              -- 그날의 상위 10편
  batch_date date,
  paper_id   uuid references papers(id) on delete cascade,
  rank       int,
  sort_mode  text,                      -- 'fun' | 'importance' | 'golden'
  primary key (batch_date, paper_id)
);
create index if not exists daily_batch_date_idx on daily_batch (batch_date desc);

create table if not exists decisions (                -- 사람의 낙점/탈락
  paper_id   uuid primary key references papers(id) on delete cascade,
  status     text,                      -- 'shortlisted' | 'picked' | 'rejected'
  note       text,
  decided_at timestamptz default now()
);

create table if not exists drafts (                   -- P1 산출물
  paper_id      uuid primary key references papers(id) on delete cascade,
  fact_sheet    jsonb,                  -- 추출된 사실들
  script_md     text,                   -- 숏폼 대본
  video_prompts jsonb,                  -- 씬별 영상 생성 프롬프트
  self_check    jsonb,                  -- 문장별 근거 매핑 결과
  created_at    timestamptz default now()
);

create table if not exists published (               -- 발행 이력
  paper_id     uuid primary key references papers(id) on delete cascade,
  final_script text,
  platforms    jsonb,
  published_at timestamptz default now()
);

-- P1 트리거 큐 (D4 — 대시보드가 요청 행을 쓰고 로컬 엔진이 폴링)
create table if not exists draft_requests (
  id           uuid primary key default gen_random_uuid(),
  paper_id     uuid references papers(id) on delete cascade,
  status       text default 'queued',   -- 'queued' | 'processing' | 'done' | 'error'
  error        text,
  requested_at timestamptz default now(),
  updated_at   timestamptz default now()
);
create index if not exists draft_requests_status_idx on draft_requests (status, requested_at);
