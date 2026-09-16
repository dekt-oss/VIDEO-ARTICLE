-- 논문 원문 보관 (작업명세서_설명엔진_v2 §3 Phase 1)
-- 근거·실측: docs/실측_0ABC_설명엔진.md (0-A 확보율 63%)
--
-- 배경: 논문 라인은 지금까지 **초록만** 보고 Fact Sheet 를 뽑고 대본을 썼다. 초록은 "무엇을
--   발견했다"만 담고 "왜·어떻게"는 본문에 있다. 원리를 설명하는 영상을 만들려면 본문이 필요하다.
--   리포트 라인은 0033 에서 같은 전환을 이미 했다 — 이 테이블은 그 논문판이다.
--
-- ★ 왜 보관하는가(0033 과 같은 세 가지):
--   ① 인용 검증 — 설명 단위의 quote 가 원문에 실제로 있는지 코드가 대조한다. 원문이 없으면
--      대조할 대상이 없다.
--   ② 재현 — 같은 논문으로 전후를 비교하려면 입력이 남아 있어야 한다.
--   ③ 호출 절감 — doc_hash 로 재사용하면 초안 재생성에서 외부 확보 호출이 0 이 된다.
--   보관 범위는 **우리가 영상으로 만든(낙점된) 논문**으로 한정한다 — 수집 시점이 아니라
--   낙점 시점에 확보한다(engine/paper_source.resolve).
--
-- ★ 페이지 번호를 두지 않는다. PDF 를 파싱하는 경로(arXiv PDF / OA PDF)가 있지만, 추출
--   텍스트의 페이지 경계는 인쇄 페이지 번호와 다르다(표지·부록 오프셋). 어긋난 번호를 화면에
--   내보내느니 갖지 않는다 — 0033 과 같은 결정.
--
-- ★ 라이선스를 컬럼으로 남긴다. 확보처가 4곳이고 arXiv·CC-BY·CC-BY-NC-ND 가 섞인다.
--   무엇을 어떤 조건으로 받았는지가 행에 남아야 나중에 판단할 수 있다.

create extension if not exists "pgcrypto";

create table if not exists paper_sources (
  id             uuid primary key default gen_random_uuid(),
  paper_id       uuid references papers(id) on delete cascade,
  external_id    text,          -- 'arxiv:2606.03136' | '10.1186/s12887-026-07516-9'
  provider       text,          -- arxiv_html | arxiv_pdf | openalex_oa | pmc_xml | unpaywall | none
  content_format text,          -- html | xml | pdf | none
  source_url     text,          -- 실제로 본문을 받아온 주소(리다이렉트 이후 최종 URL)
  version        text,          -- submittedVersion | acceptedVersion | publishedVersion
  license        text,          -- cc-by | cc-by-nc-nd | arxiv | '' (미상)
  source_depth   text,          -- full_body | partial_body | abstract_only | parse_failed
  doc_hash       text,          -- sha256(text) — 같은 원문 재저장 방지 + 인용 대조 앵커
  char_count     int,
  truncated      boolean default false,  -- PAPER_SOURCE_MAX_CHARS 상한에 걸려 잘렸는가
  parse_error    text,          -- 'pdf_parse_failed' 등. ★ 비워 두지 않는다 — 실패를 숨기면
                                --   "왜 이 논문만 근거가 없나"를 설명할 수 없다.
  text           text,          -- 본문 전문(참고문헌 제외)
  chunks         jsonb,         -- [{chunk_id, char_start, char_end, text}] — 인용 앵커
  fetched_at     timestamptz default now()
);

-- 멱등: 같은 원문(같은 해시)을 두 번 저장하지 않는다. 논문이 개정되면(v2 → v3) 해시가 달라져
-- 새 행이 쌓이고, 어느 판본으로 영상을 만들었는지가 doc_hash 로 추적된다.
create unique index if not exists paper_sources_extid_hash_idx
  on paper_sources (external_id, doc_hash);
create index if not exists paper_sources_paper_idx on paper_sources (paper_id, fetched_at desc);

-- ─── RLS: 0033 과 같은 자세 — 정책 0개 = service_role 전용 ───
--   ① 논문 본문이 통째로 들어가는 유일한 테이블이다. 보관하지만 공개하지 않는다.
--   ② 대시보드가 이 테이블을 읽을 이유가 없다. 승인 화면이 보여줄 source_depth·char_count 는
--      drafts.fact_sheet 안에 들어간다.
--   ③ 엔진과 Edge Function 은 service_role 로 접근하므로 영향 없다.
alter table paper_sources enable row level security;
drop policy if exists paper_sources_public_all on paper_sources;

comment on table paper_sources is
  '논문 원문 보관(설명엔진 v2 §3). 낙점 논문에 한해 본문을 보관하고 service_role 만 접근한다. '
  '인용 검증·재현·확보 호출 절감이 근거. 페이지 번호는 두지 않는다.';
