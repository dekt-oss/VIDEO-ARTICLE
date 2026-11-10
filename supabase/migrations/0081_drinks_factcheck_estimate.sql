-- 소재 개발 예상 비용 가정값: 사실 확인 입력 글자 12,000 → 12,500 (2026-11-10). docs/deviation-drinks-evidence-answers-question.md
--
-- 사실 확인 지시문에 "근거가 소재 질문에 답하는가(question_answer)" 항목을 더해 지시문이 약 300자 길어졌다.
-- 예상 금액이 실제보다 작아지지 않게(지출을 작게 적지 않는다) 가정값만 올린다. 나머지 값은 0075 그대로.
-- 되돌리기: 0075 의 drinks_develop_estimate_params 를 다시 실행한다.

create or replace function drinks_develop_estimate_params() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'extract_model', 'gemini-2.5-flash',       -- DRINKS_DEVELOP_EXTRACT_MODEL 기본값
    'plan_model', 'deepseek-v4-pro',           -- DRINKS_DEVELOP_PLAN_MODEL 기본값(카드뉴스 DRINKS_CARD_PLAN_MODEL 도 같다)
    'fallback_model', 'deepseek-v4-pro',       -- LLM_PAYMENT_FALLBACK_MODEL
    'max_sources', 4,                          -- DRINKS_DEVELOP_MAX_SOURCES (근거 = 출처당 호출 1회)
    'source_max_chars', 40000,                 -- DRINKS_DEVELOP_SOURCE_MAX_CHARS
    'extract_max_tokens', 6000,                -- DRINKS_DEVELOP_EXTRACT_MAX_TOKENS
    'plan_max_tokens', 16000,                  -- DRINKS_DEVELOP_PLAN_MAX_TOKENS
    'chars_per_token', 2.0,                    -- DRINKS_DEVELOP_CHARS_PER_TOKEN
    'plan_prompt_chars', 12000,                -- 대본 프롬프트 뼈대 글자(근거 묶음은 따로 더한다) — 예상 상한용 가정값
    'factcheck_max_tokens', 4000,              -- DRINKS_DEVELOP_FACTCHECK_MAX_TOKENS (0075 AI 사실 확인, 추출과 같은 모델)
    'factcheck_prompt_chars', 12500)           -- 사실 확인 입력 글자(주장 12개 × 인용 + 지시문, 0081 질문 판정 포함) — 예상 상한용 가정값
$$;
