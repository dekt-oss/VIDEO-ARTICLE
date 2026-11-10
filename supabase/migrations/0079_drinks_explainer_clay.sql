-- 주류 설명형 — 사진클레이 버전 (2026-11-10). docs/deviation-drinks-explainer-clay.md
--
-- 운영자 지시(2026-11-10): "이건 일단 우리 엔진에는 새로운 버전으로 추가해서 넣자. 설명형 릴스-사진클레이 이런식으로".
-- ★ 0067 의 운영자 규칙 "사진에 설명 하는건 안돼" 와 부딪힌다. 이 파일은 그 규칙을 **사진클레이 한 버전에만** 푼다:
--   클립 경로(omni·veo_fast)와 옛 그림 나열식(local·paid) 막힘은 그대로다.
--
-- ★ 적용 순서: 코드(engine/drinks_explainer_queue.py 의 clay 분기)를 먼저 합치고 그 뒤에 이 파일 — 옛 워커가 clay 편의 지시서를 만들면
--   클립 지시서가 저장된다. 운영 적용은 따로 결재받는다.
--
-- 무엇이 바뀌나
--   ① drink_explainer_episodes.provider 에 'clay' 를 더한다. 편을 만들 때 정하고 바꿀 수 없다(0067 가드 그대로).
--   ② 구매 결재: clay 편은 그림만 허용한 결재로 산다(클립을 사지 않는다). 클립 편은 여전히 그림+영상 둘 다.
--   ③ 조립 요청: clay 편은 후보·사람 선택이 없다. 워커가 그림을 다 사고 assets_complete 로 올린 뒤에만 조립을 받는다.
--      그 밖의 상태 규칙·검수(과정 → 품질 → 파일 승인)·게시 막음은 그대로다.
--
-- 되돌리기: clay 편이 없는지 본 뒤 provider 체크를 ('omni','veo_fast') 로, 두 함수를 0067 본문으로 다시 실행한다.
--   clay 편이 이미 있으면 기록이므로 지우지 않는다(체크만 되돌리면 그 행은 그대로 남는다 — not valid 로 다시 건다).

alter table drink_explainer_episodes drop constraint if exists drink_explainer_episodes_provider_check;
alter table drink_explainer_episodes add constraint drink_explainer_episodes_provider_check
  check (provider in ('omni','veo_fast','clay'));

-- ② 구매 요청. 결재 = 이 제작안 전용·열림. 클립 편은 그림과 영상 둘 다, 사진클레이 편은 그림만 허용하면 된다.
create or replace function drinks_explainer_request_buy(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; e drink_explainer_episodes; a drink_spend_approvals; v_through int := drinks_int(p, 'through_n', false); v_res jsonb;
  v_kinds text[];
begin
  pl := drinks_explainer_lock_plan(p);
  select * into e from drink_explainer_episodes where plan_revision_id = pl.id for update;
  if not found or e.directive is null then perform drinks_fail('directive_missing', '장면별 지시서를 먼저 만드세요'); end if;
  if exists (select 1 from drink_explainer_attempts t join drink_explainer_slots s on s.slot_id = t.slot_id
             where s.plan_revision_id = pl.id and t.state = 'unknown_billed') then
    perform drinks_fail('unknown_billed_open', '결과를 모르는 시도가 있습니다 — billed/void 로 닫기 전에는 사지 않습니다');
  end if;
  if e.state not in ('directive_ready','approved','buying','blocked_budget') then
    perform drinks_fail('invalid_state', '지금은 구매를 요청할 수 없습니다(' || e.state || ')');
  end if;
  select * into a from drink_spend_approvals where id = drinks_uuid(p, 'spend_approval_id') for share;
  if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
  if a.status <> 'open' or a.expires_at <= now() then perform drinks_fail('approval_closed', '열린 결재가 아닙니다'); end if;
  if a.plan_revision_id is distinct from pl.id then perform drinks_fail('ownership', '이 제작안 전용 결재여야 합니다'); end if;
  v_kinds := case when e.provider = 'clay' then array['image'] else array['image','video'] end;
  if not (a.allowed_kinds @> v_kinds) then
    perform drinks_fail('kind_not_approved', case when e.provider = 'clay' then '사진클레이 결재는 그림을 허용해야 합니다' else '설명형 결재는 그림과 영상을 둘 다 허용해야 합니다' end);
  end if;
  if a.order_hash is not null and a.order_hash is distinct from e.order_hash then
    perform drinks_fail('order_changed', '결재 때 본 지시서와 지금 지시서가 다릅니다');
  end if;
  v_res := drinks_explainer_enqueue(pl, 'explainer_buy', a.id);
  if not (v_res ->> 'existing')::boolean then
    update drink_explainer_episodes set approval_id = a.id, buy_through_n = v_through, last_code = null, last_message = null,
      state = case when state in ('directive_ready','blocked_budget') then 'approved' else state end
      where plan_revision_id = pl.id;
  end if;
  return v_res;
end $$;

-- ③ 조립 요청(0원). 클립 편은 모든 슬롯이 사람 선택을 지났어야 한다. 사진클레이 편은 고를 것이 없다 — 워커가 그림을 다 사서 올린 상태만 본다.
create or replace function drinks_explainer_request_assemble(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; e drink_explainer_episodes; v_need int; v_have int;
begin
  pl := drinks_explainer_lock_plan(p);
  select * into e from drink_explainer_episodes where plan_revision_id = pl.id for update;
  if not found or e.directive is null then perform drinks_fail('directive_missing', '장면별 지시서가 없습니다'); end if;
  if e.provider <> 'clay' then
    v_need := jsonb_array_length(coalesce(e.directive -> 'slots', '[]'::jsonb));
    select count(*) into v_have from drink_explainer_selections x join drink_explainer_slots s on s.slot_id = x.slot_id where s.plan_revision_id = pl.id;
    if v_have < v_need then perform drinks_fail('selection_incomplete', '아직 고르지 않은 슬롯이 있습니다(' || v_have || '/' || v_need || ')'); end if;
  end if;
  if e.state = 'blocked_assets' then
    update drink_explainer_episodes set state = 'approved' where plan_revision_id = pl.id;
    update drink_explainer_episodes set state = 'buying' where plan_revision_id = pl.id;
    update drink_explainer_episodes set state = 'assets_complete' where plan_revision_id = pl.id;
  elsif e.state not in ('assets_complete','rehearsal','auto_qa_fail','review_fail') then
    perform drinks_fail('invalid_state', '지금은 조립을 요청할 수 없습니다(' || e.state || ')');
  end if;
  update drink_explainer_episodes set last_code = null, last_message = null where plan_revision_id = pl.id;
  return drinks_explainer_enqueue(pl, 'explainer_render', null);
end $$;
