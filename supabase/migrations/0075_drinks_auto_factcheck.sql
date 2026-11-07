-- 주류 — AI 사실 확인 자동 표시 (2026-11-06, 운영자 승인). docs/deviation-drinks-auto-factcheck.md
--
-- ★ 운영자 원문(2026-11-06): "둘 다 예. 바로 만들고 배포해"
--   ① "AI 가 사실 확인에 통과한 근거는 '확인됨'으로 자동 표시" ② "유통기한·보관 질문에 쓸 공식 사이트를 더한다"
--
-- 무엇이 바뀌나 — 왜
--   · 0064 머리말 18행("support_review 는 여기서 자동으로 채우지 않는다")의 정책을 뒤집는다. 다만 **SQL 은 그대로다** —
--     support_review='supported' 는 원래부터 근거 저장(drinks_save_review → drinks_normalize_pack)이 받는 값이고, 그것을 채우는 쪽은
--     워커(engine/drinks_develop.py::run_factcheck → apply_factcheck)다. 필수 조건 검사(drinks_review_blockers)·이어 만들기 멈춤
--     (drinks_chain_stop_blockers)·승인(drinks_approve_content)은 한 글자도 바꾸지 않는다. 승인은 여전히 사람의 [승인] 한 번이다.
--   · 이 파일이 바꾸는 것은 **비용 예상** 하나다: 근거 단계에 모델 호출이 1회(AI 사실 확인) 늘었으니 drinks_develop_estimate 의
--     근거 예상 금액에 그 상한을 더한다(화면이 실제보다 작은 돈을 말하지 않게). 상수는 engine/config.py 와 같아야 한다
--     (tests/test_drinks_factcheck.py 가 대조). 실제 지출은 지금처럼 가잡기(hold) → 확정으로만 나가고 요청 1건 상한 $0.5 가 그대로 막는다.
--
-- 안전 장치 — 약해지는 것이 없다
--   · 워커 함수는 승인·제출·편성 함수를 부르지 않는다(tests/test_drinks_develop.py 가 감시). 이 파일은 워커 함수를 고치지 않는다.
--   · AI 가 '확인됨'으로 채운 주장에는 한계·주의 칸에 "AI 사실 확인(자동) — 근거 인용 대조 통과" 가 남는다 — 화면이 '사람 확인'과 구분한다.
--
-- 되돌리기
--   1. 0072 의 drinks_develop_estimate_params()·drinks_develop_estimate(jsonb) 를 다시 실행한다.
--   2. 자동 표시를 끄려면 SQL 이 아니라 워커 환경변수 DRINKS_DEVELOP_FACTCHECK_ENABLED=false (이미 저장된 '확인됨'은 그대로 남는다 —
--      지우려면 근거 화면에서 그 주장의 '뒷받침 확인'을 다시 고른다).

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
    'factcheck_prompt_chars', 12000)           -- 사실 확인 입력 글자(주장 12개 × 인용 + 지시문) — 예상 상한용 가정값
$$;

-- 단가표(engine/config.py TEXT_PRICING 의 해당 항목, USD/토큰). 없으면 null.
create or replace function drinks_develop_price(p_model text) returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select case p_model
    when 'gemini-2.5-flash' then jsonb_build_object('in', 0.30 / 1e6, 'out', 2.50 / 1e6)
    when 'gemini-2.5-pro'   then jsonb_build_object('in', 1.25 / 1e6, 'out', 10.00 / 1e6)
    when 'deepseek-v4-pro'  then jsonb_build_object('in', 1.32 / 1e6, 'out', 3.96 / 1e6)
    when 'deepseek-flash'   then jsonb_build_object('in', 0.30 / 1e6, 'out', 1.20 / 1e6)
    else null end
$$;

create or replace function drinks_develop_estimate(p jsonb) returns jsonb language plpgsql stable set search_path = public, pg_temp as $$
declare prm jsonb := drinks_develop_estimate_params(); v_topic uuid := drinks_uuid(p, 'topic_id', false); v_formats text[]; f text;
  v_items jsonb := '[]'::jsonb; v_total numeric := 0; v_known boolean := true; v_need_evidence boolean := true; v_pack_chars int := 0;
  v_cap numeric := (drinks_develop_limits() ->> 'max_usd_per_request')::numeric; v_est numeric; v_budget uuid := drinks_uuid(p, 'budget_id', false);
  cpt numeric := (prm ->> 'chars_per_token')::numeric; pe jsonb; pf jsonb; pp jsonb; v_in numeric;
  v_remaining numeric; v_fc numeric;
begin
  if jsonb_typeof(p -> 'formats') = 'array' then v_formats := drinks_text_array(p -> 'formats');
  elsif drinks_text(p, 'format') is not null then v_formats := array[drinks_text(p, 'format')];
  else v_formats := array['explainer','card','meme']; end if;
  if v_topic is not null then
    -- 근거가 이미 있으면(작성 중이든 승인본이든) 근거 비용은 들지 않는다. 대본 입력 크기는 그 근거 묶음으로 잰다.
    select coalesce(length(r.evidence_pack::text), 0) into v_pack_chars from drink_topics t join drink_topic_reviews r on r.id = coalesce(t.current_review_id, t.approved_review_id)
      where t.id = v_topic;
    v_need_evidence := not found;
  end if;
  pe := drinks_develop_price(prm ->> 'extract_model'); pf := drinks_develop_price(prm ->> 'fallback_model'); pp := drinks_develop_price(prm ->> 'plan_model');
  if v_need_evidence and exists (select 1 from unnest(v_formats) x where x in ('explainer','card')) then
    if pe is null then
      v_items := v_items || jsonb_build_object('kind', 'evidence', 'format_intent', null, 'est_usd', null, 'known', false, 'model', prm ->> 'extract_model');
      v_known := false;
    else
      v_in := (prm ->> 'source_max_chars')::numeric / cpt;
      v_est := greatest(v_in * (pe ->> 'in')::numeric + (prm ->> 'extract_max_tokens')::numeric * (pe ->> 'out')::numeric,
        case when pf is null then 0 else v_in * (pf ->> 'in')::numeric + (prm ->> 'extract_max_tokens')::numeric * (pf ->> 'out')::numeric end);
      -- 0075: 근거 단계 끝의 AI 사실 확인 1회(추출과 같은 모델·대체 모델 단가 중 큰 쪽)를 근거 비용에 더한다.
      v_fc := greatest((prm ->> 'factcheck_prompt_chars')::numeric / cpt * (pe ->> 'in')::numeric + (prm ->> 'factcheck_max_tokens')::numeric * (pe ->> 'out')::numeric,
        case when pf is null then 0 else (prm ->> 'factcheck_prompt_chars')::numeric / cpt * (pf ->> 'in')::numeric + (prm ->> 'factcheck_max_tokens')::numeric * (pf ->> 'out')::numeric end);
      v_est := least(round(v_est * (prm ->> 'max_sources')::numeric + v_fc + 0.00005, 4), v_cap);
      v_est := greatest(v_est, 0.0001);
      v_items := v_items || jsonb_build_object('kind', 'evidence', 'format_intent', null, 'est_usd', v_est, 'known', true, 'model', prm ->> 'extract_model', 'shared', true,
        'factcheck_usd', round(v_fc, 4));
      v_total := v_total + v_est;
    end if;
  end if;
  foreach f in array v_formats loop
    if f = 'meme' then
      v_items := v_items || jsonb_build_object('kind', 'meme', 'format_intent', 'meme', 'est_usd', null, 'known', false,
        'note', '밈 글·렌더 비용은 밈 결재(drink_develop_budgets)에서 따로 잡는다 — 여기서는 모른다');
      v_known := false;
    elsif f in ('explainer','card') then
      if pp is null then
        v_items := v_items || jsonb_build_object('kind', 'plan', 'format_intent', f, 'est_usd', null, 'known', false, 'model', prm ->> 'plan_model');
        v_known := false;
      else
        v_in := ((prm ->> 'plan_prompt_chars')::numeric + v_pack_chars) / cpt;
        v_est := v_in * (pp ->> 'in')::numeric + (prm ->> 'plan_max_tokens')::numeric * (pp ->> 'out')::numeric;
        v_est := greatest(least(round(v_est + 0.00005, 4), v_cap), 0.0001);
        v_items := v_items || jsonb_build_object('kind', 'plan', 'format_intent', f, 'est_usd', v_est, 'known', true, 'model', prm ->> 'plan_model');
        v_total := v_total + v_est;
      end if;
    else
      perform drinks_fail('invalid_input', '형식(설명형·카드뉴스·밈형)을 고르세요');
    end if;
  end loop;
  if v_budget is not null then
    v_remaining := (drinks_develop_budget_json(v_budget) ->> 'remaining_usd')::numeric;
  else
    select sum(remaining_usd) into v_remaining from drink_develop_budget_state where status = 'open' and not expired;
  end if;
  return jsonb_build_object('topic_id', v_topic, 'formats', to_jsonb(v_formats), 'items', v_items,
    'total_est_usd', round(v_total, 4), 'all_known', v_known, 'per_request_cap_usd', v_cap,
    'budget_remaining_usd', v_remaining, 'budget_id', v_budget, 'params', prm);
end $$;


do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname in ('drinks_develop_estimate_params', 'drinks_develop_estimate')
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;

-- 확인(적용 후):
--   select drinks_develop_estimate_params() ->> 'factcheck_max_tokens';   → 4000
--   select (drinks_develop_estimate('{"formats":["explainer"]}'::jsonb) -> 'items' -> 0 ->> 'factcheck_usd')::numeric > 0;   → true
