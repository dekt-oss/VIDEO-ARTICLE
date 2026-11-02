-- 주류 설명형 — 제작 큐 연결 (2026-11-02). 기획 v2 §3-3·§3-5·§3-9. docs/deviation-drinks-explainer-queue.md
--
-- ★ 파일만 만든다. 운영 적용은 따로 결재받는다. 적용 순서: 코드(engine/drinks_produce.py 분기)를 먼저 합치고 그 뒤에 이 파일 — 옛 워커가 explainer_* 작업을 집으면 그림 나열식으로 렌더한다.
-- ★ 0065·0066 이 drinks_plan_renderable 을 다시 정의하면 아래 정의와 합쳐야 한다(이 파일이 뒤에 돈다).
--
-- 무엇이 바뀌나
--   ① 제작 작업에 세 종류가 더해진다: explainer_plan(0원, 지시서) · explainer_buy(결재 안에서 시작 그림·클립) · explainer_render(0원, 선택된 클립 조립).
--      사람 판정을 기다리는 동안 작업을 붙들 수 없어서 나눴다. 사람 차례가 되면 구매 작업은 파일 묶음 없이 닫힌다(drinks_explainer_finish_job).
--   ② drink_explainer_episodes: 한 편의 상태(§3-9)와 장면별 지시서. 전이는 engine/drinks_explainer.py can_transition 과 같다(시험이 대조).
--   ③ 0064 의 막힘(explainer_engine_not_wired)을 푼다. **옛 렌더는 계속 못 간다** — 이제 함수가 아니라 표 트리거가 막는다:
--      설명형 소재의 영상 제작안에는 local·paid 작업을 넣을 수 없다(not_renderable). 형식을 뒤늦게 설명형으로 바꾸면 대기 중인 옛 작업은 취소된다.
--   ④ 최종 파일 승인(drinks_output_review_action)은 과정 검수 + 품질 검수 6항목(§3-8 B)이 끝나야 통과한다. 승인되면 ready_to_publish.
--   ⑤ 0062 함수 셋을 고친다: close_unknown(닫을 때 가잡기 확정·해제), sweep_stale(가잡기·편 상태·received/probed 정리), verdict(자동 판정 근거 저장, 자동 불합격 후보는 사람 판정 불필요).
--   ⑥ 경계 종류에 cut 을 더한다(대본이 이어짐을 선언하지 않은 같은 역할 장면 사이). §3-5 표에 없던 값이다.
--
-- 돈: 이 파일의 어떤 함수도 공급자를 부르지 않는다. 지출은 전부 drinks_hold_spend(0054)를 지난다. 결재를 여는 함수도 추가하지 않았다(운영자가 문장을 적어 연다).
--
-- 되돌리기:
--   1. drop trigger drink_prod_jobs_explainer_guard on drink_production_jobs; drop trigger drink_topic_picks_explainer_cancel on drink_topic_picks;
--      drop trigger drink_output_reviews_explainer_guard on drink_output_reviews; drop trigger drink_output_reviews_explainer_after on drink_output_reviews;
--      drop trigger drink_explainer_selection_advance on drink_explainer_selections;
--   2. 0064 의 drinks_plan_renderable, 0062 의 drinks_explainer_close_unknown·sweep_stale·verdict 를 다시 실행한다.
--   3. drop table drink_explainer_episodes; alter table drink_explainer_candidates drop column auto_report; 이 파일의 drinks_explainer_* 함수를 drop 한다.
--   4. explainer_* 작업이 없는지 본 뒤, 렌더러 체크·결재 체크를 0053·0054 값으로 되돌리고 drink_prod_one_explainer_uq 를 지운다. 경계 체크도 0062 값으로 되돌린다.
--   explainer_* 작업·슬롯 행이 이미 있으면 기록이므로 지우지 않는다.

-- ─────────────────────────────────────────────────────────────
-- 표·칸
-- ─────────────────────────────────────────────────────────────

alter table drink_production_jobs drop constraint if exists drink_production_jobs_renderer_check;
alter table drink_production_jobs add constraint drink_production_jobs_renderer_check
  check (renderer in ('local','paid','explainer_plan','explainer_buy','explainer_render'));
alter table drink_production_jobs drop constraint if exists drink_prod_paid_needs_approval;
alter table drink_production_jobs add constraint drink_prod_paid_needs_approval
  check ((renderer in ('paid','explainer_buy')) = (spend_approval_id is not null));
-- 한 편의 설명형 작업은 종류를 통틀어 동시에 하나뿐이다.
create unique index if not exists drink_prod_one_explainer_uq on drink_production_jobs (plan_revision_id)
  where status in ('queued','running') and renderer like 'explainer\_%';

alter table drink_explainer_candidates add column if not exists auto_report jsonb;

alter table drink_explainer_slots drop constraint if exists drink_explainer_slots_boundary_in_check;
alter table drink_explainer_slots drop constraint if exists drink_explainer_slots_boundary_out_check;
alter table drink_explainer_slots add constraint drink_explainer_slots_boundary_in_check
  check (boundary_in in ('loop','flash_forward','cut_to_mechanism','match','same_clip','cut'));
alter table drink_explainer_slots add constraint drink_explainer_slots_boundary_out_check
  check (boundary_out in ('loop','flash_forward','cut_to_mechanism','match','same_clip','cut'));

create table if not exists drink_explainer_episodes (
  plan_revision_id uuid primary key references drink_plan_revisions(id),
  topic_id         uuid not null references drink_topics(id),
  state            text not null default 'plan_draft' check (state in (
                     'plan_draft','directive_ready','approved','buying','assets_complete','rehearsal','rendered',
                     'auto_qa_pass','process_review_pass','quality_review_pass','ready_to_publish',
                     'blocked_assets','blocked_no_pass','blocked_budget','unknown_billed','auto_qa_fail','review_fail')),
  provider         text not null default 'omni' check (provider in ('omni','veo_fast')),
  directive        jsonb,            -- 장면별 지시서(engine/drinks_explainer_queue.py build_directive). 한 번 저장하면 바꾸지 않는다
  order_hash       text check (order_hash is null or order_hash ~ '^[0-9a-f]{64}$'),
  approval_id      uuid references drink_spend_approvals(id),   -- 지금 구매에 쓰는 결재
  buy_through_n    int check (buy_through_n is null or buy_through_n >= 1),   -- 이 슬롯까지만 산다(S2 처럼 일부만 시험)
  last_code        text check (last_code is null or length(last_code) <= 100),
  last_message     text check (last_message is null or length(last_message) <= 2000),
  process_review   jsonb,
  quality_review   jsonb,
  version          int not null default 1,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  check (state in ('plan_draft') or directive is not null or state like 'blocked%')
);

-- ─────────────────────────────────────────────────────────────
-- 상태 규칙(engine/drinks_explainer.py can_transition 과 같다 — tests/test_drinks_explainer_queue.py 가 대조)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_explainer_can_transition(p_from text, p_to text) returns boolean
language sql immutable set search_path = public, pg_temp as $$
  with f(flow) as (select array['plan_draft','directive_ready','approved','buying','assets_complete','rehearsal','rendered',
                                'auto_qa_pass','process_review_pass','quality_review_pass','ready_to_publish']::text[])
  select case
    when p_from = any(flow) and p_to = any(flow) then array_position(flow, p_to) = array_position(flow, p_from) + 1
    when p_from = any(flow) and p_to in ('blocked_assets','blocked_no_pass','blocked_budget','unknown_billed','auto_qa_fail','review_fail') then true
    when p_from in ('blocked_assets','blocked_no_pass','blocked_budget') then p_to in ('approved','plan_draft')
    when p_from = 'unknown_billed' then p_to = 'buying'
    when p_from in ('auto_qa_fail','review_fail') then p_to in ('rehearsal','approved','plan_draft')
    else false end
  from f
$$;

create or replace function drink_explainer_episodes_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '편 기록은 삭제할 수 없습니다'); end if;
  if new.plan_revision_id <> old.plan_revision_id or new.topic_id <> old.topic_id or new.provider <> old.provider then
    perform drinks_fail('immutable', '편의 제작안·공급자는 바꿀 수 없습니다');
  end if;
  if old.directive is not null and new.directive is distinct from old.directive then
    perform drinks_fail('immutable', '장면별 지시서는 바꿀 수 없습니다 — 대본이 바뀌면 새 제작안입니다');
  end if;
  if new.state <> old.state and not drinks_explainer_can_transition(old.state, new.state) then
    perform drinks_fail('invalid_state', '편 상태를 ' || old.state || ' 에서 ' || new.state || ' 로 바꿀 수 없습니다');
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists drink_explainer_episodes_guard on drink_explainer_episodes;
create trigger drink_explainer_episodes_guard before update or delete on drink_explainer_episodes
  for each row execute function drink_explainer_episodes_guard();

-- 이 제작안이 설명형인가. 고르기 기록이 없는 옛 소재는 아니다.
create or replace function drinks_plan_is_explainer(p_plan uuid) returns boolean language sql stable set search_path = public, pg_temp as $$
  select exists (select 1 from drink_plan_revisions pl join drink_topic_picks tp on tp.topic_id = pl.topic_id
                 where pl.id = p_plan and pl.format = 'video' and tp.format_intent = 'explainer')
$$;

-- 0064 의 막힘을 푼다: 여기서는 유효성만 잰다. 옛 경로는 아래 트리거가 막는다.
create or replace function drinks_plan_renderable(p_plan uuid) returns text language sql stable as $$
  select case
    when pl.id is null then 'not_found'
    when pl.plan_status <> 'approved' then 'plan_not_approved'
    when pl.blocked_at is not null then 'plan_blocked'
    when pl.revoked_at is not null then 'plan_revoked'
    when not drinks_approval_valid(pl.topic_review_id) then 'evidence_invalid'
    else null end
  from (select 1) x left join drink_plan_revisions pl on pl.id = p_plan
$$;

-- 옛 그림 나열식은 사진·대체 카드로 내보낸다. 운영자 규칙 "사진에 설명 하는건 안돼" — 설명형 소재에는 그 작업을 넣을 수 없다.
create or replace function drink_prod_jobs_explainer_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.renderer like 'explainer\_%' then
    if not drinks_plan_is_explainer(new.plan_revision_id) then
      perform drinks_fail('not_renderable', '설명형으로 고른 소재의 영상 제작안이 아닙니다');
    end if;
  elsif drinks_plan_is_explainer(new.plan_revision_id) then
    perform drinks_fail('not_renderable', '설명형은 전부 영상이어야 해서 옛 그림 나열식으로 만들지 않습니다 — 설명형 제작으로 진행하세요');
  end if;
  return new;
end $$;
drop trigger if exists drink_prod_jobs_explainer_guard on drink_production_jobs;
create trigger drink_prod_jobs_explainer_guard before insert on drink_production_jobs
  for each row execute function drink_prod_jobs_explainer_guard();

-- 형식을 뒤늦게 설명형으로 정하면 이미 들어가 있던 옛 작업을 멈춘다(대기 = 취소, 진행 중 = 취소 요청).
create or replace function drink_topic_picks_explainer_cancel() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.format_intent = 'explainer' then
    update drink_production_jobs set status = 'canceled', finished_at = now(), error_code = 'explainer_engine_only',
        error_message = '설명형으로 고른 소재라 옛 그림 나열식 작업을 취소했습니다'
      where topic_id = new.topic_id and format = 'video' and status = 'queued' and renderer in ('local','paid');
    update drink_production_jobs set cancel_requested = true
      where topic_id = new.topic_id and format = 'video' and status = 'running' and renderer in ('local','paid');
  end if;
  return null;
end $$;
drop trigger if exists drink_topic_picks_explainer_cancel on drink_topic_picks;
create trigger drink_topic_picks_explainer_cancel after insert or update on drink_topic_picks
  for each row execute function drink_topic_picks_explainer_cancel();

-- 적용 시점에 이미 들어가 있는 옛 작업도 같은 규칙으로 멈춘다.
update drink_production_jobs j set status = 'canceled', finished_at = now(), error_code = 'explainer_engine_only',
    error_message = '설명형으로 고른 소재라 옛 그림 나열식 작업을 취소했습니다'
  where j.status = 'queued' and j.renderer in ('local','paid') and drinks_plan_is_explainer(j.plan_revision_id);
update drink_production_jobs j set cancel_requested = true
  where j.status = 'running' and j.renderer in ('local','paid') and drinks_plan_is_explainer(j.plan_revision_id);

-- 최종 파일 승인은 품질 검수를 지난 뒤에만(§3-8 B). 승인되면 게시 대기.
create or replace function drink_output_reviews_explainer_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare v_state text;
begin
  if new.status = 'approved' and old.status <> 'approved' and drinks_plan_is_explainer(new.plan_revision_id) then
    select state into v_state from drink_explainer_episodes where plan_revision_id = new.plan_revision_id;
    if v_state is distinct from 'quality_review_pass' then
      perform drinks_fail('review_blocked', '설명형은 과정 검수와 품질 검수 6항목을 먼저 통과해야 파일을 승인할 수 있습니다');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_output_reviews_explainer_guard on drink_output_reviews;
create trigger drink_output_reviews_explainer_guard before update on drink_output_reviews
  for each row execute function drink_output_reviews_explainer_guard();

create or replace function drink_output_reviews_explainer_after() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.status = 'approved' and old.status <> 'approved' and drinks_plan_is_explainer(new.plan_revision_id) then
    update drink_explainer_episodes set state = 'ready_to_publish' where plan_revision_id = new.plan_revision_id;
  end if;
  return null;
end $$;
drop trigger if exists drink_output_reviews_explainer_after on drink_output_reviews;
create trigger drink_output_reviews_explainer_after after update on drink_output_reviews
  for each row execute function drink_output_reviews_explainer_after();

-- 모든 슬롯이 선택되면 assets_complete.
create or replace function drink_explainer_selection_advance() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid; e drink_explainer_episodes; v_need int; v_have int;
begin
  select plan_revision_id into v_plan from drink_explainer_slots where slot_id = new.slot_id;
  select * into e from drink_explainer_episodes where plan_revision_id = v_plan for update;
  if not found or e.state <> 'buying' then return null; end if;
  v_need := jsonb_array_length(coalesce(e.directive -> 'slots', '[]'::jsonb));
  select count(*) into v_have from drink_explainer_selections x join drink_explainer_slots s on s.slot_id = x.slot_id where s.plan_revision_id = v_plan;
  if v_need > 0 and v_have >= v_need then
    update drink_explainer_episodes set state = 'assets_complete', last_code = null, last_message = null where plan_revision_id = v_plan;
  end if;
  return null;
end $$;
drop trigger if exists drink_explainer_selection_advance on drink_explainer_selections;
create trigger drink_explainer_selection_advance after insert on drink_explainer_selections
  for each row execute function drink_explainer_selection_advance();

-- ─────────────────────────────────────────────────────────────
-- 요청 (운영자 — 화면은 운영자 키 게이트 뒤)
-- ─────────────────────────────────────────────────────────────

-- 설명형 작업 한 건을 큐에 넣는다. 활성 작업이 있으면 그것을 돌려준다.
create or replace function drinks_explainer_enqueue(pl drink_plan_revisions, p_renderer text, p_approval uuid) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare rv drink_topic_reviews; j drink_production_jobs; v_input text; v_attempt int;
begin
  select * into j from drink_production_jobs where plan_revision_id = pl.id and status in ('queued','running') and renderer like 'explainer\_%';
  if found then return jsonb_build_object('job_id', j.id, 'status', j.status, 'renderer', j.renderer, 'existing', true); end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_input := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|drinks-explainer-v1|' || p_renderer || '|' || coalesce(p_approval::text, ''), 'UTF8')), 'hex');
  v_attempt := 1 + (select count(*) from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input);
  insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, input_hash, plan_hash, review_hash, renderer, renderer_version, requested_by, spend_approval_id)
  values (pl.topic_id, pl.id, 'video', v_attempt, v_input, pl.approved_hash, rv.approved_hash, p_renderer, 'drinks-explainer-v1', 'operator', p_approval)
  returning * into j;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', 'video', 'attempt_no', j.attempt_no, 'renderer', p_renderer, 'spend_approval_id', p_approval));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'renderer', j.renderer, 'existing', false, 'attempt_no', j.attempt_no);
end $$;

create or replace function drinks_explainer_lock_plan(p jsonb) returns drink_plan_revisions language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; v_block text;
begin
  perform drinks_reap_prod_jobs();
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  v_block := drinks_plan_renderable(pl.id);
  if v_block is not null then
    perform drinks_fail(case v_block when 'not_found' then 'not_found' else 'not_renderable' end, '이 제작안은 지금 제작할 수 없습니다(' || v_block || ')');
  end if;
  if not drinks_plan_is_explainer(pl.id) then perform drinks_fail('not_renderable', '설명형으로 고른 소재의 영상 제작안이 아닙니다'); end if;
  return pl;
end $$;

-- ① 지시서 만들기(0원). 산 것이 생기기 전까지만 다시 만들 수 있다.
create or replace function drinks_explainer_request_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; e drink_explainer_episodes;
begin
  pl := drinks_explainer_lock_plan(p);
  insert into drink_explainer_episodes (plan_revision_id, topic_id, provider)
    values (pl.id, pl.topic_id, coalesce(drinks_text(p, 'provider'), 'omni'))
    on conflict (plan_revision_id) do nothing;
  select * into e from drink_explainer_episodes where plan_revision_id = pl.id for update;
  if e.state <> 'plan_draft' then perform drinks_fail('invalid_state', '지시서가 이미 있습니다(' || e.state || ')'); end if;
  return drinks_explainer_enqueue(pl, 'explainer_plan', null);
end $$;

-- ② 구매 요청. 결재 = 이 제작안 전용·열림·그림과 영상 둘 다 허용. 돈은 워커가 항목마다 drinks_hold_spend 를 지나야 나간다.
create or replace function drinks_explainer_request_buy(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; e drink_explainer_episodes; a drink_spend_approvals; v_through int := drinks_int(p, 'through_n', false); v_res jsonb;
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
  if not (a.allowed_kinds @> array['image','video']) then perform drinks_fail('kind_not_approved', '설명형 결재는 그림과 영상을 둘 다 허용해야 합니다'); end if;
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

-- ③ 조립 요청(0원). 모든 슬롯이 사람 선택을 지났어야 한다. 파일을 복구한 뒤 다시 시도하는 길(blocked_assets)과 다시 렌더(auto_qa_fail·review_fail)도 여기다.
create or replace function drinks_explainer_request_assemble(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pl drink_plan_revisions; e drink_explainer_episodes; v_need int; v_have int;
begin
  pl := drinks_explainer_lock_plan(p);
  select * into e from drink_explainer_episodes where plan_revision_id = pl.id for update;
  if not found or e.directive is null then perform drinks_fail('directive_missing', '장면별 지시서가 없습니다'); end if;
  v_need := jsonb_array_length(coalesce(e.directive -> 'slots', '[]'::jsonb));
  select count(*) into v_have from drink_explainer_selections x join drink_explainer_slots s on s.slot_id = x.slot_id where s.plan_revision_id = pl.id;
  if v_have < v_need then perform drinks_fail('selection_incomplete', '아직 고르지 않은 슬롯이 있습니다(' || v_have || '/' || v_need || ')'); end if;
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

-- ④ 사람 검수(§3-8 B). 과정 → 품질 순서. 하나라도 미확인이면 합격으로 받지 않는다. 불합격은 review_fail.
create or replace function drinks_explainer_review(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare e drink_explainer_episodes; v_stage text := drinks_text(p, 'stage'); v_outcome text := drinks_text(p, 'outcome'); ck jsonb := p -> 'checks';
  required text[]; k text; v_reason text := drinks_text(p, 'reason');
begin
  select * into e from drink_explainer_episodes where plan_revision_id = drinks_uuid(p, 'plan_revision_id') for update;
  if not found then perform drinks_fail('not_found', '편을 찾지 못했습니다'); end if;
  if v_stage = 'process' then
    required := array['directive_matches_clips','selection_reasons_ok','cost_matches_approval'];
    if e.state <> 'auto_qa_pass' then perform drinks_fail('invalid_state', '자동 검사를 통과한 편만 과정 검수를 합니다(' || e.state || ')'); end if;
  elsif v_stage = 'quality' then
    required := array['stops_in_first_1_5s','no_photo_like_scene','match_boundaries_connect','mechanism_explains_why','no_fake_text','loop_natural'];
    if e.state <> 'process_review_pass' then perform drinks_fail('invalid_state', '과정 검수를 통과한 편만 품질 검수를 합니다(' || e.state || ')'); end if;
  else
    perform drinks_fail('invalid_input', '검수 단계는 process 또는 quality 입니다');
  end if;
  if not exists (select 1 from drink_asset_manifests m where m.plan_revision_id = e.plan_revision_id) then
    perform drinks_fail('invalid_state', '최종 파일 묶음이 없습니다');
  end if;
  if v_outcome = 'fail' then
    if v_reason is null then perform drinks_fail('invalid_input', '불합격 이유를 적으세요'); end if;
    update drink_explainer_episodes set state = 'review_fail', last_code = v_stage || '_review_fail', last_message = left(v_reason, 2000),
      process_review = case when v_stage = 'process' then jsonb_build_object('outcome', 'fail', 'checks', ck, 'reason', v_reason, 'at', now()) else process_review end,
      quality_review = case when v_stage = 'quality' then jsonb_build_object('outcome', 'fail', 'checks', ck, 'reason', v_reason, 'at', now()) else quality_review end
      where plan_revision_id = e.plan_revision_id returning * into e;
    return jsonb_build_object('plan_revision_id', e.plan_revision_id, 'state', e.state);
  end if;
  if v_outcome is distinct from 'pass' then perform drinks_fail('invalid_input', '판정은 pass 또는 fail 입니다'); end if;
  if ck is null or jsonb_typeof(ck) <> 'object' then perform drinks_fail('invalid_input', '검수 항목이 필요합니다'); end if;
  foreach k in array required loop
    if coalesce((ck ->> k)::boolean, false) is not true then
      perform drinks_fail('checklist_incomplete', '확인하지 않은 검수 항목이 있습니다: ' || k, to_jsonb(required));
    end if;
  end loop;
  if v_stage = 'process' then
    update drink_explainer_episodes set state = 'process_review_pass', process_review = jsonb_build_object('outcome', 'pass', 'checks', ck, 'reason', v_reason, 'at', now())
      where plan_revision_id = e.plan_revision_id returning * into e;
  else
    update drink_explainer_episodes set state = 'quality_review_pass', quality_review = jsonb_build_object('outcome', 'pass', 'checks', ck, 'reason', v_reason, 'at', now())
      where plan_revision_id = e.plan_revision_id returning * into e;
  end if;
  return jsonb_build_object('plan_revision_id', e.plan_revision_id, 'state', e.state);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 (service_role) — 임대를 가진 워커만
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_explainer_save_directive(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare j drink_production_jobs; v_hash text := drinks_text(p, 'order_hash');
begin
  j := drinks_lock_prod_job(p);
  if j.renderer <> 'explainer_plan' then perform drinks_fail('invalid_state', '지시서 작업이 아닙니다'); end if;
  if jsonb_typeof(p -> 'directive') is distinct from 'object' or jsonb_array_length(coalesce(p -> 'directive' -> 'slots', '[]'::jsonb)) = 0 then
    perform drinks_fail('invalid_input', '지시서에 슬롯이 없습니다');
  end if;
  update drink_explainer_episodes set directive = p -> 'directive', order_hash = v_hash, state = 'directive_ready', last_code = null, last_message = null
    where plan_revision_id = j.plan_revision_id;
  return jsonb_build_object('plan_revision_id', j.plan_revision_id, 'state', 'directive_ready', 'order_hash', v_hash);
end $$;

create or replace function drinks_explainer_episode_event(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare j drink_production_jobs; v_to text := drinks_text(p, 'to_state');
begin
  j := drinks_lock_prod_job(p);
  if j.renderer not like 'explainer\_%' then perform drinks_fail('invalid_state', '설명형 작업이 아닙니다'); end if;
  if v_to is null then perform drinks_fail('invalid_input', 'to_state 가 필요합니다'); end if;
  if v_to in ('process_review_pass','quality_review_pass','ready_to_publish') then
    perform drinks_fail('invalid_input', '사람 검수 상태는 워커가 올리지 않습니다');
  end if;
  update drink_explainer_episodes set state = v_to, last_code = coalesce(drinks_text(p, 'code'), last_code), last_message = coalesce(left(drinks_text(p, 'message'), 2000), last_message)
    where plan_revision_id = j.plan_revision_id;
  return jsonb_build_object('state', v_to);
end $$;

-- 파일 묶음을 만들지 않는 작업(지시서·구매)을 닫는다. 조립 성공은 drinks_finish_render 로만 닫힌다.
create or replace function drinks_explainer_finish_job(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare j drink_production_jobs; v_out text := drinks_text(p, 'outcome'); v_to text := drinks_text(p, 'to_state'); v_code text := drinks_text(p, 'error_code'); v_msg text := left(drinks_text(p, 'error_message'), 2000);
  v_status text; e drink_explainer_episodes;
begin
  j := drinks_lock_prod_job(p);
  if j.renderer not like 'explainer\_%' then perform drinks_fail('invalid_state', '설명형 작업이 아닙니다'); end if;
  if v_out is null or v_out not in ('succeeded','failed') then perform drinks_fail('invalid_input', 'outcome 은 succeeded·failed 입니다'); end if;
  if v_out = 'succeeded' and j.renderer = 'explainer_render' then perform drinks_fail('invalid_state', '조립 성공은 파일 묶음과 함께 닫습니다'); end if;
  v_status := case when j.cancel_requested then 'canceled' else v_out end;
  update drink_production_jobs set status = v_status, finished_at = now(), lease_token = null,
    error_code = case when v_status = 'succeeded' then null when j.cancel_requested then coalesce(v_code, 'canceled') else v_code end, error_message = v_msg
    where id = j.id returning * into j;
  select * into e from drink_explainer_episodes where plan_revision_id = j.plan_revision_id for update;
  if v_to is not null and e.state <> v_to then
    update drink_explainer_episodes set state = v_to where plan_revision_id = j.plan_revision_id;
  end if;
  update drink_explainer_episodes set last_code = case when v_status = 'succeeded' then coalesce(p -> 'result' ->> 'status_code', last_code) else v_code end,
      last_message = case when v_status = 'succeeded' then null else v_msg end
    where plan_revision_id = j.plan_revision_id;
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'error_code', j.error_code, 'result', p -> 'result');
end $$;

-- 워커가 읽는 것 + 화면이 읽는 것. 돈·상태를 바꾸지 않는다. 슬롯별 비용: 시작 그림 + 후보 시도 합계(불합격 후보의 돈도 남는다).
create or replace function drinks_explainer_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid := drinks_uuid(p, 'plan_revision_id'); e drink_explainer_episodes; pl drink_plan_revisions;
begin
  select * into pl from drink_plan_revisions where id = v_plan;
  if not found then perform drinks_fail('not_found', '제작안을 찾지 못했습니다'); end if;
  select * into e from drink_explainer_episodes where plan_revision_id = v_plan;
  return jsonb_build_object(
    'is_explainer', drinks_plan_is_explainer(v_plan),
    'approved_amount_usd', (select approved_amount_usd from drink_topic_picks where topic_id = pl.topic_id),
    'episode', case when e.plan_revision_id is null then null else to_jsonb(e) end,
    'slots', coalesce((select jsonb_agg(jsonb_build_object(
        'slot_id', s.slot_id, 'n', s.n, 'role', s.role, 'status', s.status, 'min_src_ms', s.min_src_ms, 'candidates_planned', s.candidates_planned,
        'boundary_in', s.boundary_in, 'boundary_out', s.boundary_out,
        'image_usd', coalesce((select sum(h.actual_usd) from drink_spend_holds h join drink_spend_approvals a on a.id = h.approval_id
            where a.plan_revision_id = v_plan and h.status = 'settled' and h.kind = 'image' and h.item_key = 'scene-' || lpad(s.n::text, 2, '0') || '-' || s.role), 0),
        'selection', (select jsonb_build_object('candidate_id', x.selected_candidate_id, 'selected_by', x.selected_by, 'reason', x.reason, 'selected_at', x.selected_at)
            from drink_explainer_selections x where x.slot_id = s.slot_id),
        'candidates', coalesce((select jsonb_agg(jsonb_build_object(
            'candidate_id', c.candidate_id, 'k', c.k, 'status', c.status, 'cost_usd', c.cost_usd, 'auto_verdict', c.auto_verdict, 'human_verdict', c.human_verdict, 'auto_report', c.auto_report,
            'asset', (select jsonb_build_object('asset_id', m.id, 'storage_key', m.storage_key, 'sha256', m.sha256, 'width', m.width, 'height', m.height, 'duration_ms', m.duration_ms, 'state', m.state)
                from drink_media_assets m where m.id = c.asset_id),
            'attempts', coalesce((select jsonb_agg(jsonb_build_object('attempt_id', t.attempt_id, 'm', t.m, 'state', t.state, 'provider', t.provider, 'provider_request_id', t.provider_request_id,
                  'approval_id', t.approval_id, 'billed_units', t.billed_units, 'actual_usd', t.actual_usd, 'error_code', t.error_code, 'closed_by', t.closed_by, 'close_note', t.close_note,
                  'est_usd', (select h.est_usd from drink_spend_holds h where h.id = t.hold_id)) order by t.m)
                from drink_explainer_attempts t where t.candidate_id = c.candidate_id), '[]'::jsonb)) order by c.k)
            from drink_explainer_candidates c where c.slot_id = s.slot_id), '[]'::jsonb)) order by s.n)
      from drink_explainer_slots s where s.plan_revision_id = v_plan), '[]'::jsonb),
    'approvals', coalesce((select jsonb_agg(drinks_spend_view(a) order by a.created_at desc) from drink_spend_approvals a where a.plan_revision_id = v_plan), '[]'::jsonb),
    'unknown_attempts', coalesce((select jsonb_agg(t.attempt_id order by t.attempt_id) from drink_explainer_attempts t join drink_explainer_slots s on s.slot_id = t.slot_id
        where s.plan_revision_id = v_plan and t.state = 'unknown_billed'), '[]'::jsonb));
end $$;

create or replace function drinks_explainer_job_context(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid := drinks_uuid(p, 'plan_revision_id'); v_ap uuid := drinks_uuid(p, 'approval_id', false); a drink_spend_approvals;
begin
  select * into a from drink_spend_approvals where id = v_ap;
  return drinks_explainer_status(jsonb_build_object('plan_revision_id', v_plan)) || jsonb_build_object(
    'approval', case when a.id is null then null else drinks_spend_view(a) end,
    -- 시각 주장표는 개발 요청 결과에 있다(0060). 손으로 고친 제작안에는 없다 — 그러면 null 이고 워커가 멈춘다.
    'visual_claims', (select r.result -> 'visual_claims' from drink_develop_requests r
        where r.result_plan_revision_id = v_plan and r.kind = 'plan' and r.status = 'succeeded' order by r.created_at desc limit 1));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 0062 함수 고침
-- ─────────────────────────────────────────────────────────────

-- 닫을 때 가잡기도 함께 닫는다: billed = 그 금액으로 확정, void = 해제. 닫기 전에는 가잡기가 상한을 계속 차지한다(틀리면 덜 쓰는 쪽).
create or replace function drinks_explainer_close_unknown(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare a drink_explainer_attempts; v_res text := drinks_text(p, 'resolution'); v_by text := drinks_text(p, 'closed_by'); v_note text := drinks_text(p, 'note');
  v_usd numeric := nullif(p ->> 'actual_usd', '')::numeric; v_plan uuid;
begin
  if v_res is null or v_res not in ('billed','void') then perform drinks_fail('invalid_input', 'resolution 은 billed 또는 void 입니다'); end if;
  if v_by is null or lower(v_by) in ('worker','system','auto') then perform drinks_fail('invalid_input', '운영자가 닫아야 합니다(closed_by)'); end if;
  if v_note is null then perform drinks_fail('invalid_input', '닫는 이유(note)가 필요합니다'); end if;
  if v_res = 'billed' and v_usd is null then perform drinks_fail('invalid_input', 'billed 로 닫으려면 금액(actual_usd)이 필요합니다'); end if;
  select * into a from drink_explainer_attempts where attempt_id = drinks_text(p, 'attempt_id') for update;
  if not found then perform drinks_fail('not_found', '시도를 찾지 못했습니다'); end if;
  if a.state <> 'unknown_billed' then perform drinks_fail('invalid_state', '결과 불명 시도만 닫습니다'); end if;
  update drink_explainer_attempts set state = 'closed_' || v_res, closed_by = v_by, close_note = v_note, updated_at = now(),
    actual_usd = case when v_res = 'billed' then v_usd else 0 end
   where attempt_id = a.attempt_id;
  update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = a.candidate_id;
  perform drink_explainer_candidate_settle(a.candidate_id);
  if a.hold_id is not null and exists (select 1 from drink_spend_holds h where h.id = a.hold_id and h.status = 'held') then
    if v_res = 'billed' then
      perform drinks_settle_spend(jsonb_build_object('hold_id', a.hold_id, 'outcome', 'settled', 'actual_usd', v_usd, 'note', '운영자가 billed 로 닫음: ' || left(v_note, 300)));
    else
      perform drinks_settle_spend(jsonb_build_object('hold_id', a.hold_id, 'outcome', 'released', 'note', '운영자가 void 로 닫음: ' || left(v_note, 300)));
    end if;
  end if;
  select plan_revision_id into v_plan from drink_explainer_slots where slot_id = a.slot_id;
  if not exists (select 1 from drink_explainer_attempts t join drink_explainer_slots s on s.slot_id = t.slot_id where s.plan_revision_id = v_plan and t.state = 'unknown_billed') then
    update drink_explainer_episodes set state = 'buying', last_code = null, last_message = null where plan_revision_id = v_plan and state = 'unknown_billed';
  end if;
  return jsonb_build_object('attempt_id', a.attempt_id, 'state', 'closed_' || v_res);
end $$;

-- 워커가 죽은 시도 정리. generating = 보냈는지 모름(가잡기 유지, 편도 멈춘다), requested = 안 보냄(가잡기 해제),
-- received·probed = 돈은 나갔는데 파일 등록 전에 죽음(failed_billed, 가잡기가 남아 있으면 확정). 다시 부르지 않는다.
create or replace function drinks_explainer_sweep_stale(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_sec int := coalesce(drinks_int(p, 'older_than_sec', false), 1800); v_unknown int := 0; v_unbilled int := 0; v_billed int := 0; r record;
begin
  if v_sec < 60 then perform drinks_fail('invalid_input', 'older_than_sec 는 60 이상입니다'); end if;
  for r in select t.attempt_id, t.candidate_id, t.slot_id, t.state, t.hold_id, t.actual_usd, s.plan_revision_id from drink_explainer_attempts t join drink_explainer_slots s on s.slot_id = t.slot_id
      where t.state in ('requested','generating','received','probed') and t.updated_at < now() - make_interval(secs => v_sec) for update of t loop
    if r.state = 'generating' then
      update drink_explainer_attempts set state = 'unknown_billed', updated_at = now(), error_code = coalesce(error_code, 'worker_lost') where attempt_id = r.attempt_id;
      update drink_explainer_episodes set state = 'unknown_billed', last_code = 'unknown_billed', last_message = '워커가 호출 중에 끊겼습니다: ' || r.attempt_id
        where plan_revision_id = r.plan_revision_id and state in ('approved','buying');
      v_unknown := v_unknown + 1;
    elsif r.state = 'requested' then
      update drink_explainer_attempts set state = 'failed_unbilled', updated_at = now(), error_code = coalesce(error_code, 'worker_lost') where attempt_id = r.attempt_id;
      update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = r.candidate_id;
      if r.hold_id is not null and exists (select 1 from drink_spend_holds h where h.id = r.hold_id and h.status = 'held') then
        perform drinks_settle_spend(jsonb_build_object('hold_id', r.hold_id, 'outcome', 'released', 'note', '호출 전에 워커가 끊김'));
      end if;
      v_unbilled := v_unbilled + 1;
    else
      update drink_explainer_attempts set state = 'failed_billed', updated_at = now(), error_code = coalesce(error_code, 'worker_lost') where attempt_id = r.attempt_id;
      update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = r.candidate_id;
      if r.hold_id is not null and exists (select 1 from drink_spend_holds h where h.id = r.hold_id and h.status = 'held') then
        perform drinks_settle_spend(jsonb_build_object('hold_id', r.hold_id, 'outcome', 'settled',
          'actual_usd', coalesce(r.actual_usd, (select h.est_usd from drink_spend_holds h where h.id = r.hold_id)), 'note', '받은 뒤 워커가 끊김(청구 유력)'));
      end if;
      perform drink_explainer_candidate_settle(r.candidate_id);
      v_billed := v_billed + 1;
    end if;
  end loop;
  return jsonb_build_object('unknown_billed', v_unknown, 'failed_unbilled', v_unbilled, 'failed_billed', v_billed);
end $$;

-- 0062 + 자동 판정 근거 저장. 자동 불합격 후보에는 사람 판정이 필요 없다(이미 고를 수 없다). 그렇지 않으면 살아남은 후보를 고를 수 없게 된다.
create or replace function drinks_explainer_verdict(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare c drink_explainer_candidates; s drink_explainer_slots; v_auto text := drinks_text(p, 'auto_verdict'); v_human text := drinks_text(p, 'human_verdict');
  v_failed int; v_judged int;
begin
  if (v_auto is null) = (v_human is null) then perform drinks_fail('invalid_input', 'auto_verdict 또는 human_verdict 하나만 보냅니다'); end if;
  if coalesce(v_auto, v_human) not in ('pass','fail') then perform drinks_fail('invalid_input', '판정은 pass 또는 fail 입니다'); end if;
  select * into c from drink_explainer_candidates where candidate_id = drinks_text(p, 'candidate_id') for update;
  if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
  select * into s from drink_explainer_slots where slot_id = c.slot_id for update;
  if s.status in ('selected','no_pass') then perform drinks_fail('invalid_state', '이 슬롯은 끝났습니다(' || s.status || ')'); end if;
  if v_human is not null and c.auto_verdict is null then perform drinks_fail('invalid_state', '자동 판정이 끝난 후보만 사람이 판정합니다'); end if;
  update drink_explainer_candidates set auto_verdict = coalesce(v_auto, auto_verdict), human_verdict = coalesce(v_human, human_verdict), updated_at = now(),
      auto_report = case when v_auto is not null and jsonb_typeof(p -> 'auto_report') = 'object' then p -> 'auto_report' else auto_report end
   where candidate_id = c.candidate_id;
  select count(*) filter (where auto_verdict = 'fail' or human_verdict = 'fail'), count(*) filter (where human_verdict is not null or auto_verdict = 'fail')
    into v_failed, v_judged from drink_explainer_candidates where slot_id = c.slot_id;
  if v_failed >= s.candidates_planned then
    perform drink_explainer_slot_advance(c.slot_id, 'no_pass');
    update drink_explainer_episodes set state = 'blocked_no_pass', last_code = 'no_pass', last_message = s.slot_id || ' 의 후보가 모두 불합격입니다 — 새 제작안으로 계획을 바꾸세요'
      where plan_revision_id = s.plan_revision_id and state in ('approved','buying');
  elsif v_judged >= s.candidates_planned then
    perform drink_explainer_slot_advance(c.slot_id, 'human_checked');
  elsif v_auto is not null then
    perform drink_explainer_slot_advance(c.slot_id, 'auto_checked');
  end if;
  return jsonb_build_object('candidate_id', c.candidate_id, 'slot_status', (select status from drink_explainer_slots where slot_id = c.slot_id));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: anon·authenticated 에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────

alter table drink_explainer_episodes enable row level security;
revoke all on table drink_explainer_episodes from anon, authenticated;
grant select, insert, update on table drink_explainer_episodes to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_explainer\_%' or p.proname like 'drink\_explainer\_%'
      or p.proname in ('drinks_plan_is_explainer','drinks_plan_renderable','drink_prod_jobs_explainer_guard','drink_topic_picks_explainer_cancel',
                       'drink_output_reviews_explainer_guard','drink_output_reviews_explainer_after'))
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;

-- 확인(적용 후):
--   select has_function_privilege('anon', 'public.drinks_explainer_request_buy(jsonb)', 'EXECUTE');   → false
--   select has_table_privilege('anon', 'public.drink_explainer_episodes', 'SELECT');                  → false
--   select drinks_explainer_can_transition('buying', 'ready_to_publish');                             → false
