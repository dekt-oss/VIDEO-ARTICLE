-- 주류 — 근거 다시 찾기가 옛 결과를 재사용하지 않게(2026-11-18). 계획: 스튜디오 막힘 화면 [자료 더 찾아서 다시 만들기].
-- 0084 drinks_develop_context 는 '실패했거나 해결안 질문과 같은 막힌 결과' 중 가장 최근 것을 재사용했다. 그래서 질문 그대로 다시 찾기를
-- 누르면 막힌 결과는 건너뛰고 그보다 오래된 실패 결과를 골라 같은 근거로 같은 판정을 되풀이할 수 있었다.
-- 바뀌는 것: 가장 최근 결과 하나만 보고, 그것이 재사용 조건에 맞을 때만 쓴다. 되돌리기: 0084 의 drinks_develop_context 를 다시 실행한다.

create or replace function drinks_develop_context(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; prev drink_develop_requests; v_snap uuid[]; v_ok boolean := false; v_question text;
begin
  q := drinks_develop_lock(p);
  if q.kind = 'evidence' then
    select question into v_question from drink_topics where id = q.topic_id;
    -- 0089: 가장 최근 결과 하나만 본다. 그 뒤에 막힌 요청이 있으면(질문 그대로 [자료 더 찾아서 다시 만들기]) 옛 실패 결과를
    --   다시 쓰지 않고 새로 찾는다 — 0084 는 막힌 결과를 건너뛰고 더 오래된 실패 결과를 골라 같은 근거를 되풀이할 수 있었다(코덱스 리뷰).
    --   보관 결과가 없는 막힘·성공도 '가장 최근'에 넣는다 — 그래야 그보다 오래된 실패 결과를 건너뛰어 집지 않는다.
    select * into prev from drink_develop_requests x where x.topic_id = q.topic_id and x.kind = 'evidence' and x.id <> q.id
      and x.status in ('failed','blocked','succeeded')
      order by x.finished_at desc nulls last limit 1;
    if found and prev.result ? 'unsaved_evidence'
       and (prev.status = 'failed' or (prev.status = 'blocked' and prev.result -> 'rescue' ->> 'question' = v_question)) then
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

revoke all on function drinks_develop_context(jsonb) from public, anon, authenticated;
grant execute on function drinks_develop_context(jsonb) to service_role;
