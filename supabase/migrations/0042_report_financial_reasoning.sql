-- 리포트 논증 단위 보관 (작업명세서_설명엔진_v2 §7 Phase 5)
--
-- 배경: 리포트 초안은 "무엇을 전망했다"(fact_sheet.number_facts)와 "어떤 순서로 말한다"
--   (story_plan.claim_chain)는 갖고 있었지만, **그 전망이 딛는 인과 단계**는 어디에도 없었다.
--   "목표가 9만원"과 "수주가 늘어서"가 같은 평면에 놓여 화면이 숫자 카드 나열이 된다.
--   engine/report_reasoning.py 가 그 사이에 논증 단위를 만들고, 이 컬럼이 그것을 보관한다.
--
-- ★ 신규 테이블을 만들지 않는다(명세 D7). report_drafts 의 JSONB 필드 하나다 —
--   story_plan·evidence(0033)·video_flow(0034)와 같은 자세. 단위 스키마가 아직 굳지 않았고
--   (unit_type 목록·단계 상한이 운영 중 조정된다), 컬럼으로 펼치면 조정 때마다 마이그레이션이 는다.
--
-- ★ versioned: 안에 schema_version 을 넣는다(config.REASONING_SCHEMA_VERSION). 나중에 모양이
--   바뀌어도 옛 초안을 읽는 쪽이 무엇을 보고 있는지 알 수 있다 — 마이그레이션 없이 공존시킨다.
--
-- ★ claim_chain 을 대체하지 않는다. claim_chain 은 **대본의 논증 순서**이고 reasoning unit 은
--   **그 논증이 딛는 인과 단계**다. 대체하면 이미 돌고 있는 근거 게이트
--   (report_evidence.validate_story_plan)가 참조를 잃는다. 위에 얹고 id 로 잇는다.

alter table report_drafts add column if not exists financial_reasoning jsonb;

comment on column report_drafts.financial_reasoning is
  '§7 Financial Reasoning Model. {schema_version, units[{reasoning_id, unit_type, title, '
  'carries_thesis, attributed_to, assumption, breaks_if, steps[{step, text, fact_ids, source_refs}]}], '
  'audit, block_reasons, model}. 대본보다 먼저 만들어지고(D2) 대본·지시서가 소비한다. '
  'fact_ids 는 fact_sheet.number_facts 의 fact_id, source_refs 는 report_sources 의 chunk 를 가리킨다.';
