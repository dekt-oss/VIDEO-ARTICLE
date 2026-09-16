-- 텍스트 LLM 토큰 사용량 (2026-08-29)
--
-- 왜 필요한가 — 실측 사고:
--   운영자가 "어제 1.7만원을 뭐에 썼냐"고 물었는데 **코드가 답하지 못했다.**
--   `generation_attempts` 는 이미지·영상만 기록하고 있었고, Fact Sheet 추출·대본 생성·
--   지시서 생성·품질 채점 같은 **텍스트 호출은 한 줄도 남지 않았다.**
--   그래서 원장을 뒤져 봐야 이미지 $2.79 만 나오고, 실제로 돈을 쓴 텍스트는 보이지 않았다.
--   (그날의 실제 지출은 논문 16편 × 3안 = 대본 48벌 + 그것을 두 번 채점한 것이었다.)
--
-- 비용 원장의 존재 이유가 바로 그 질문에 답하는 것인데 가장 큰 항목이 빠져 있었다.
--
-- ★ 왜 컬럼 두 개인가: 텍스트는 **입력과 출력 단가가 다르다**(pro 기준 1.25 vs 10.00 /백만).
--   출력만 기록하면 "왜 이 호출이 비쌌나"를 설명할 수 없다 — 원문 전문을 프롬프트에 넣는
--   이 파이프라인에서는 입력 토큰이 곧 비용이다.
-- ★ nullable 이다. 이미지·영상 행은 이 값이 없고, 옛 행도 그대로 유효하다.

alter table generation_attempts
  add column if not exists input_tokens  int,
  add column if not exists output_tokens int;

comment on column generation_attempts.input_tokens is
  '텍스트 LLM 입력 토큰(asset_type=llm 일 때만). 원문 주입 비용을 설명하는 값.';
comment on column generation_attempts.output_tokens is
  '텍스트 LLM 출력 토큰(asset_type=llm 일 때만). 단가가 입력의 4~8배라 비용을 지배한다.';

-- 비용 질문에 바로 답하기 위한 색인 — "언제·무엇에" 를 날짜와 용도로 묶어 본다.
create index if not exists generation_attempts_llm_idx
  on generation_attempts (asset_type, created_at desc)
  where asset_type = 'llm';
