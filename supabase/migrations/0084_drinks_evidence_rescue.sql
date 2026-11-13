-- 주류 — 근거 막힘 해결안 [적용] (2026-11-13). docs/deviation-drinks-evidence-rescue.md
--
-- 무엇이 — 왜: 근거 초안이 "모은 근거로는 소재 질문에 답할 수 없음"(evidence_off_topic)으로 막히면 지금까지는
--   "[출처 추가]로 원문을 붙이고 다시 요청하세요"로 끝났다. 운영자 지시(2026-11-13): 막히면 끝내지 말고 해결안을 가져와
--   운영자는 적용 여부만 고르게. 워커가 막힘 결과에 rescue(지금 근거로 답할 수 있는 질문 — AI 사실 확인을 미리 통과한 것)를 남긴다.
-- 이 파일:
--   1. drinks_apply_rescue — [적용] 한 번: 소재 제목·질문을 해결안으로 바꾸고, 같은 결재(없으면 이번 주 한도)로 근거 요청을 다시 넣는다.
--      원래 요청의 이어 만들기(chain) 표시를 그대로 잇는다 — [이걸로]로 고른 소재면 대본까지 이어 만든다. 승인은 하지 않는다.
--   2. drinks_develop_context — 해결안을 적용한 뒤의 요청은 막혔던 요청의 근거(이미 산 추출 결과)를 다시 쓴다(모델 재추출 없음).
--      조건: 그 막힘 결과의 rescue 질문이 지금 소재 질문과 같을 때만. 출처를 새로 붙이고 그냥 다시 요청하면 예전처럼 새로 읽는다.
-- 되돌리기: drop function drinks_apply_rescue(jsonb); 0076 의 drinks_develop_context 를 다시 실행한다.

create or replace function drinks_apply_rescue(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_req uuid := drinks_uuid(p, 'request_id'); last drink_develop_requests; t drink_topics; rs jsonb;
  v_q text; v_title text; v_budget uuid; bs jsonb; v_res jsonb;
begin
  select * into last from drink_develop_requests where id = v_req;
  if not found then perform drinks_fail('not_found', '개발 요청을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(last.topic_id, null, false);
  if last.kind <> 'evidence' or last.status <> 'blocked' or not (last.result ? 'rescue') then
    perform drinks_fail('invalid_state', '해결안이 있는 막힌 근거 요청이 아닙니다');
  end if;
  if exists (select 1 from drink_develop_requests x where x.topic_id = t.id and x.created_at > last.created_at) then
    perform drinks_fail('stale_rescue', '이 소재에 더 최근 요청이 있습니다 — 화면을 새로 불러오세요');
  end if;
  rs := last.result -> 'rescue';
  v_q := left(btrim(coalesce(rs ->> 'question', '')), 1000);
  v_title := left(btrim(coalesce(nullif(rs ->> 'title', ''), v_q)), 200);
  if v_q = '' then perform drinks_fail('invalid_state', '해결안에 질문이 없습니다'); end if;
  v_budget := last.budget_id;
  bs := case when v_budget is null then null else drinks_develop_budget_json(v_budget) end;
  -- drinks_studio_recover_topic 과 같은 규칙: 주간 한도가 끝났으면 이번 주 한도로 잇는다(새 결재를 지어내지 않는다).
  if bs is null or ((bs ->> 'expired')::boolean
      and exists (select 1 from drink_develop_budgets b where b.id = v_budget and b.stage like 'weekly:%')) then
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  end if;
  perform drinks_log(t.id, 'topic', t.id, 'rescue_applied', t.question, v_q, last.id::text, coalesce(rs ->> 'kind', 'reframe'),
    jsonb_build_object('old_title', t.title, 'new_title', v_title, 'actor', coalesce(drinks_text(p, 'actor'), 'operator')));
  update drink_topics set question = v_q, title = v_title, version = version + 1 where id = t.id;
  v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', last.chain));
  update drink_develop_requests set recovery_of = last.id where id = (v_res ->> 'request_id')::uuid;
  return v_res || jsonb_build_object('rescued_from', last.id, 'question', v_q, 'title', v_title);
end $$;

create or replace function drinks_develop_context(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; prev drink_develop_requests; v_snap uuid[]; v_ok boolean := false; v_question text;
begin
  q := drinks_develop_lock(p);
  if q.kind = 'evidence' then
    select question into v_question from drink_topics where id = q.topic_id;
    select * into prev from drink_develop_requests x where x.topic_id = q.topic_id and x.kind = 'evidence' and x.id <> q.id
      and x.result ? 'unsaved_evidence'
      and (x.status = 'failed' or (x.status = 'blocked' and x.result -> 'rescue' ->> 'question' = v_question))
      order by x.finished_at desc limit 1;
    if found then
      v_snap := array(select distinct (ref ->> 'snapshot_id')::uuid
        from jsonb_array_elements(prev.result -> 'unsaved_evidence' -> 'evidence_pack' -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref);
      v_ok := cardinality(v_snap) > 0 and not exists (
        select 1 from unnest(v_snap) s(id)
        where not exists (select 1 from drink_topic_sources ts where ts.topic_id = q.topic_id and ts.snapshot_id = s.id and ts.role = 'evidence')
           or coalesce(drinks_snapshot_meta(s.id) ->> 'rights_status', '') not in ('quote_ok','summary_only'));
    end if;
  end if;
  return jsonb_build_object('instruction', q.instruction, 'supersedes_plan_id', q.supersedes_plan_id,
    'current_plan', (select pl.plan_json from drink_plan_revisions pl where pl.id = q.supersedes_plan_id),
    'reusable', case when v_ok then jsonb_build_object('from_request_id', prev.id) || (prev.result -> 'unsaved_evidence') end);
end $$;

revoke all on function drinks_apply_rescue(jsonb) from public, anon, authenticated;
grant execute on function drinks_apply_rescue(jsonb) to service_role;
revoke all on function drinks_develop_context(jsonb) from public, anon, authenticated;
grant execute on function drinks_develop_context(jsonb) to service_role;
