-- 리포트 원문 보관 (작업지시서 영상엔진품질 v3 §4 Source Contract)
-- 근거·결정: docs/phase0-영상엔진품질_v3.md §1-3 · §8-1 (운영자 결정 2026-08-02)
--
-- 배경: Fact Sheet 추출이 ARIA 목록 미리보기(평균 366자)만 보고 돌았다. ARIA 는 같은 리포트의
--   전문(get_research.content_raw — PDF 추출 본문+표)을 갖고 있었지만 엔진이 그 도구를 부르지
--   않았다. 608e3e6 이 런타임 주입을 배선했고, 이 마이그레이션은 그 전문을 **보관**한다.
--
-- ★ 0018 주석의 "원문 전문은 저장하지 않는다"를 뒤집는 결정이다. 뒤집은 이유 세 가지:
--   ① 인용 검증 — §5-2 는 "quote 안의 숫자가 원문에 실제로 있는가"를 기계로 대조하라고 한다.
--      원문이 없으면 대조할 대상이 없다. 매번 ARIA 를 다시 부르면 그 사이 원문이 바뀌거나
--      사라졌을 때 같은 영상을 두 번 검증할 수 없다.
--   ② 재현 — Phase 4 는 같은 리포트로 전후 비교를 요구한다. 입력이 사라지면 비교가 무의미하다.
--   ③ 호출 절감 — doc_hash 로 재사용하면 초안 재생성·재검사에서 ARIA 호출이 0 이 된다.
--   보관 범위는 **우리가 영상으로 만든 리포트**로 한정된다(reports 에 FK). 배포·공개하지 않는다.
--
-- ★ 페이지 번호를 두지 않는다. 우리가 PDF 를 파싱하지 않으므로 page_start/page_end 를 만들면
--   그건 지어낸 값이다(§21 K1 — 근거 없는 숫자가 화면에 박히는 사고). chunk 는 문자 오프셋만
--   갖는다(engine/report_source.chunk_text).

create extension if not exists "pgcrypto";

create table if not exists report_sources (
  id            uuid primary key default gen_random_uuid(),
  report_id     uuid references reports(id) on delete cascade,
  external_id   text,          -- 'aria_research:4902' | 'aria_signal:2871' (ARIA 원본 식별자)
  source_type   text,          -- 'research'(포털 정식 리포트) | 'signal'(텔레그램 계열)
  source_depth  text,          -- full_text | partial_text | summary_only | parse_failed
  source_url    text,          -- 리포트 PDF 직링크(research) 또는 채널 링크(signal)
  doc_hash      text,          -- sha256(text) — 같은 원문 재저장 방지 + 인용 대조 앵커
  char_count    int,
  truncated     boolean default false,   -- SOURCE_FULLTEXT_MAX_CHARS 상한에 걸려 잘렸는가
  text          text,          -- 원문 전문
  chunks        jsonb,         -- [{chunk_id, char_start, char_end, text}] — 인용 앵커
  fetched_at    timestamptz default now()
);

-- 멱등: 같은 원문(같은 해시)을 두 번 저장하지 않는다. 원문이 개정되면 해시가 달라져 새 행이
-- 쌓이고, 그때 어느 판본으로 영상을 만들었는지가 doc_hash 로 추적된다.
create unique index if not exists report_sources_extid_hash_idx
  on report_sources (external_id, doc_hash);
create index if not exists report_sources_report_idx on report_sources (report_id, fetched_at desc);

-- ─── RLS: ★ 여기서 기존 report_* 패턴(anon 전면 허용)을 의도적으로 어긴다 ───
--   0018~0020 의 모든 테이블은 anon 에게 열려 있다. 이 테이블만 **정책 0개** = service_role 전용.
--   ① 증권사 리포트 전문이 통째로 들어가는 유일한 테이블이다. 0018 주석의 저작권 자세를
--      뒤집되 최소한으로만 뒤집는다 — 보관하지만 공개하지는 않는다.
--   ② 대시보드가 이 테이블을 읽을 이유가 없다. 승인 화면이 보여줄 source_depth·source_chars 는
--      이미 report_drafts.fact_sheet 안에 들어간다(engine/report_factsheet.extract 가 심는다).
--   ③ 엔진과 Edge Function 은 service_role 로 접근하므로 영향 없다.
alter table report_sources enable row level security;
drop policy if exists report_sources_public_all on report_sources;

-- 0018 주석 정정: "원문 전문(raw_content)은 저장하지 않는다"는 이 마이그레이션 이후로 거짓이다.
comment on table report_sources is
  '리포트 원문 보관(v3 §4). 0018 의 "원문 미저장" 주석을 대체한다 — 영상으로 만든 리포트에 한해 '
  '전문을 보관하고, service_role 만 접근한다. 인용 검증(§5-2)·재현(Phase 4)·ARIA 호출 절감이 근거.';

-- ─── 초안 산출물 확장 (v3 §5-3 근거 게이트 · §6 story_plan) ───
-- 같은 마이그레이션에 둔 이유: 원문 보관이 있어야 인용 대조가 가능하고, 그 대조 결과가
-- evidence 에 담긴다. 둘은 한 몸이라 따로 적용하면 중간 상태가 의미가 없다.
--
-- ★ 둘 다 jsonb 다. 게이트 결과의 모양은 아직 굳지 않았고(임계값·범주가 운영 중 조정된다),
--   컬럼으로 펼치면 조정 때마다 마이그레이션이 필요해진다. 기존 self_check·compliance 와
--   같은 자세다.
alter table report_drafts add column if not exists story_plan jsonb;
alter table report_drafts add column if not exists evidence   jsonb;

comment on column report_drafts.story_plan is
  '§6 논증 설계(thesis·claim_chain·excluded_evidence). 독립 LLM 스테이지가 아니라 대본 출력의 필드.';
comment on column report_drafts.evidence is
  '§5 근거 게이트 결과(block_reasons·warnings·story_warnings·density_warnings). '
  'blocked 는 EVIDENCE_HARD_BLOCK_ENABLED 가 켜졌을 때만 true — 기본 off(현 재고가 요약 기반이라).';
