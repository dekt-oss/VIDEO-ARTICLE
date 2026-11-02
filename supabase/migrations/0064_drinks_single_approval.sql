-- 주류 소재 — 형식 고르기와 내용 승인 한 번 (2026-11-02). docs/deviation-drinks-develop.md, docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md §7 결정 2
--
-- ★ 파일만 만든다. 운영 DB 적용은 따로 결재받는다.
--
-- 무엇이 바뀌나
--   ① [이걸로](drinks_pick_topic) 한 번이 후보를 소재로 올리고 → 형식·편성 주차(의도)를 적고 → 근거 초안 요청까지 넣는다.
--   ② 근거 초안이 성공하면 같은 트랜잭션에서 대본 초안 요청이 이어진다(drinks_finish_develop). **아직 승인되지 않은 근거로** 만든다.
--   ③ [승인](drinks_approve_content) 한 번이 근거·편성·제작안을 **한 트랜잭션으로** 승인한다. 안쪽은 기존 함수
--      (drinks_review_action → drinks_select → drinks_plan_action)를 그대로 부른다 — 검사가 줄지 않고, 하나라도 실패하면 전부 되돌아간다.
--
-- 안전 장치 — 약해지는 것이 없다
--   · 승인 전 대본은 draft 로만 존재한다. drink_plans_guard(0050)·drinks_plan_action 은 근거가 승인되지 않으면 제출·승인을 막고,
--     drinks_plan_renderable(0053)은 승인된 제작안 + 지금 유효한 근거만 제작으로 보낸다. 이 파일은 그 함수들을 고치지 않는다.
--   · 표시 없는 대본 요청은 0060 그대로 review_not_approved 다. 승인 전 근거로 쓰려면 draft_evidence 표시가 있어야 하고,
--     그 표시가 있는 요청은 설명형 의도·결재·근거 상태를 따로 검사한다.
--   · 근거 내용이 바뀌면(주장 문장·인용·핵심 주장 선택 등) 그 근거로 쓴 대본을 트리거가 차단한다(blocked_at). 차단은 풀 수 없다 —
--     새 대본을 만들어야 승인할 수 있다. 주장별 확인(support_review)과 핵심 메시지 한 줄은 사람이 채우는 칸이라 내용 변경으로 치지 않는다.
--   · support_review 는 여기서 자동으로 채우지 않는다. 필수 조건 검사(drinks_review_blockers)가 그대로 막는다.
--   · 워커 함수(drinks_develop_*·drinks_start_develop·drinks_finish_develop)는 승인·제출·편성 함수를 부르지 않는다(tests/test_drinks_develop.py 가 감시).
--
-- 형식(의도)과 기존 selected_formats 의 대응 — selected_formats 는 그대로 video·carousel 만 받는다
--     explainer(설명형) → video
--     card(카드뉴스)   → carousel
--     meme(밈형)       → 없음(밈 제작 엔진이 생기기 전까지는 어느 형식으로도 편성되지 않는다. drinks_intent_format 이 null 을 준다)
--   drink_topic_picks 는 **의도만** 적는다. 돈이 나가지 않고, 편성(drink_topics.status='selected')은 승인 때 비로소 일어난다
--   — 0050 규칙상 승인되지 않은 근거로는 편성할 수 없기 때문이다.
--
-- 지금 못 하는 것(코드로 멈춘다, 조용히 건너뛰지 않는다)
--   · 카드뉴스 대본 자동 작성은 없다 → 근거 초안까지 만들고 card_plan_not_built 로 멈춘다. 기존 탭에서 이어 간다.
--   · 밈은 근거·대본을 만들지 않는다 → meme_board 로 멈춘다(밈 보드는 다른 작업).
--   · drinks_approve_content 는 설명형(video)만 받는다.
--   · 승인 금액(approved_amount_usd)은 기록만 한다. 결재(drink_spend_approvals)를 열지 않는다 — 영상 구매가 연결되기 전이다.
--
-- 되돌리기(0060·0061 정의로 돌아간다):
--   1. 0060 의 drink_develop_requests_guard·drinks_develop_request_json·drinks_request_develop·drinks_start_develop·
--      drinks_finish_develop·drinks_develop_status, 0061 의 drinks_develop_save_plan 을 다시 실행한다.
--   2. drop trigger drink_review_evidence_edited on drink_topic_reviews; drop trigger drink_plans_draft_flag_guard on drink_plan_revisions;
--      drop function drink_review_evidence_edited(); drop function drink_plans_draft_flag_guard();
--   3. drop function drinks_pick_topic(jsonb); drop function drinks_approve_content(jsonb); drop function drinks_candidate_evidence_counts(jsonb);
--      drop function drinks_develop_chain_next(drink_develop_requests); drop function drinks_chain_stop_blockers(uuid);
--      drop function drinks_evidence_content_hash(jsonb, jsonb); drop function drinks_intent_format(text);
--   4. drop table drink_topic_picks;
--      alter table drink_develop_requests drop column chain, drop column draft_evidence, drop column evidence_hash;
--      alter table drink_plan_revisions drop column drafted_from_unapproved, drop column evidence_content_hash;
--   이미 승인된 근거·제작안은 평범한 승인 기록이라 되돌려도 그대로 쓸 수 있다. 작성 중인 '승인 전 근거로 쓴 대본'은 다시 만들어야 한다.

-- ─────────────────────────────────────────────────────────────
-- 표·칸
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_topic_picks (
  topic_id            uuid primary key references drink_topics(id),
  format_intent       text not null check (format_intent in ('explainer','card','meme')),
  recommended_format  text check (recommended_format is null or recommended_format in ('explainer','card','meme','unknown')),
  recommended_reason  text check (recommended_reason is null or length(recommended_reason) <= 500),
  editorial_week      date not null check (extract(isodow from editorial_week) = 1),
  budget_id           uuid references drink_develop_budgets(id),
  candidate_id        uuid references drink_discovery_candidates(id),
  approved_at         timestamptz,
  approved_amount_usd numeric(10,4) check (approved_amount_usd is null or approved_amount_usd > 0),
  version             int not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists drink_topic_picks_intent_idx on drink_topic_picks (format_intent);

alter table drink_develop_requests add column if not exists chain boolean not null default false;           -- 근거가 성공하면 대본을 이어 만든다
alter table drink_develop_requests add column if not exists draft_evidence boolean not null default false;  -- 승인 전 근거로 대본을 쓴다
alter table drink_develop_requests add column if not exists evidence_hash text;                              -- 워커가 일을 시작할 때 본 근거 내용
alter table drink_develop_requests drop constraint if exists drink_develop_draft_evidence_ck;
alter table drink_develop_requests add constraint drink_develop_draft_evidence_ck check (not draft_evidence or kind = 'plan');
alter table drink_develop_requests drop constraint if exists drink_develop_chain_ck;
alter table drink_develop_requests add constraint drink_develop_chain_ck check (not chain or kind = 'evidence');

alter table drink_plan_revisions add column if not exists drafted_from_unapproved boolean not null default false;
alter table drink_plan_revisions add column if not exists evidence_content_hash text;
alter table drink_plan_revisions drop constraint if exists drink_plans_draft_flag_ck;
alter table drink_plan_revisions add constraint drink_plans_draft_flag_ck
  check (not drafted_from_unapproved or (format = 'video' and evidence_content_hash is not null));

-- ─────────────────────────────────────────────────────────────
-- 규칙 함수
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_intent_format(p_intent text) returns text language sql immutable set search_path = public, pg_temp as $$
  select case p_intent when 'explainer' then 'video' when 'card' then 'carousel' else null end
$$;

-- 대본이 기대는 근거 내용. support_review(사람의 확인)·core_takeaway(사람이 고치는 한 줄)·점수는 뺀다 —
-- 이것들을 채운다고 대본이 무효가 되면 승인에 영영 닿지 못한다. 주장을 빼거나 문장을 고치면 값이 바뀐다.
create or replace function drinks_evidence_content_hash(p_pack jsonb, p_brief jsonb) returns text
language sql immutable set search_path = public, pg_temp as $$
  select encode(sha256(convert_to(jsonb_build_object(
    'claims', coalesce((select jsonb_agg(c - 'support_review' order by c ->> 'claim_id')
      from jsonb_array_elements(coalesce(p_pack -> 'claims', '[]'::jsonb)) c), '[]'::jsonb),
    'selected', coalesce(p_brief -> 'selected_claim_ids', '[]'::jsonb),
    'required', coalesce(p_brief -> 'required_claims', '{}'::jsonb),
    'question', p_brief -> 'audience_question')::text, 'UTF8')), 'hex')
$$;

-- 대본을 쓰기 전에 멈춰야 하는 결함. 사람이 승인 화면에서 채우는 칸(점수·핵심 메시지·주장별 확인·사용 조건·시효 범위)은 멈추지 않는다.
-- 이 결함이 남은 채로 모델을 부르면 어차피 승인할 수 없는 대본에 돈을 쓴다.
create or replace function drinks_chain_stop_blockers(p_review uuid) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(b), '[]'::jsonb)
  from jsonb_array_elements_text(drinks_review_blockers(p_review) -> 'blockers') b
  where split_part(b, ':', 1) not in ('scores_incomplete','brief_takeaway_missing','claim_support_not_reviewed',
    'claim_rights_unconfirmed','claim_time_scope_missing')
$$;

-- ─────────────────────────────────────────────────────────────
-- 불변 규칙
-- ─────────────────────────────────────────────────────────────

create or replace function drink_topic_picks_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '형식 선택 기록은 삭제할 수 없습니다'); end if;
  if new.topic_id <> old.topic_id then perform drinks_fail('immutable', '다른 소재로 옮길 수 없습니다'); end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists drink_topic_picks_guard on drink_topic_picks;
create trigger drink_topic_picks_guard before update or delete on drink_topic_picks
  for each row execute function drink_topic_picks_guard();

-- 요청 내용 불변(0060) + 이어 만들기 표시도 바꾸지 못한다. evidence_hash 는 시작할 때 한 번만 쓴다.
create or replace function drink_develop_requests_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '개발 요청 기록은 삭제할 수 없습니다'); end if;
  if old.status not in ('queued','running') and (to_jsonb(new) - 'cost_usd') is distinct from (to_jsonb(old) - 'cost_usd') then
    perform drinks_fail('immutable', '끝난 개발 요청은 바꿀 수 없습니다');
  end if;
  if (new.topic_id, new.kind, new.review_id, new.budget_id, new.created_at, new.chain, new.draft_evidence) is distinct from
     (old.topic_id, old.kind, old.review_id, old.budget_id, old.created_at, old.chain, old.draft_evidence) then
    perform drinks_fail('immutable', '요청 내용(소재·종류·근거·결재)은 바꿀 수 없습니다');
  end if;
  if old.evidence_hash is not null and new.evidence_hash is distinct from old.evidence_hash then
    perform drinks_fail('immutable', '시작 때 본 근거 값은 바꿀 수 없습니다');
  end if;
  return new;
end $$;

-- '승인 전 근거로 씀' 표시와 그때의 근거 값은 기록이다.
create or replace function drink_plans_draft_flag_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if (new.drafted_from_unapproved, new.evidence_content_hash) is distinct from (old.drafted_from_unapproved, old.evidence_content_hash) then
    perform drinks_fail('immutable', '제작안이 어떤 근거로 쓰였는지는 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_plans_draft_flag_guard on drink_plan_revisions;
create trigger drink_plans_draft_flag_guard before update on drink_plan_revisions
  for each row execute function drink_plans_draft_flag_guard();

-- 근거 내용이 바뀌면 그 근거로 쓴 대본을 차단한다. 어떤 경로로 고쳐도(새 화면·근거 탭·직접 update) 여기를 지난다.
-- 쓰고 있는 워커에게는 취소를 건다 — 어차피 저장 때 거절되므로(evidence_hash) 돈을 더 쓰지 않게 한다.
create or replace function drink_review_evidence_edited() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare n int;
begin
  if old.status <> 'draft' then return null; end if;
  if drinks_evidence_content_hash(old.evidence_pack, old.brief) is not distinct from drinks_evidence_content_hash(new.evidence_pack, new.brief) then
    return null;
  end if;
  update drink_plan_revisions set blocked_at = now(),
      blocked_reason = 'evidence_edited: 이 대본을 만든 뒤 근거가 바뀌었습니다 — 대본을 다시 만들어야 승인할 수 있습니다'
    where topic_review_id = new.id and drafted_from_unapproved and plan_status = 'draft' and blocked_at is null;
  get diagnostics n = row_count;
  update drink_develop_requests set cancel_requested = true
    where review_id = new.id and kind = 'plan' and draft_evidence and status = 'running';
  if n > 0 then
    perform drinks_log(new.topic_id, 'review', new.id, 'script_invalidated_by_evidence_edit', 'draft', 'draft', new.input_hash, null,
      jsonb_build_object('blocked_plans', n));
  end if;
  return null;
end $$;
drop trigger if exists drink_review_evidence_edited on drink_topic_reviews;
create trigger drink_review_evidence_edited after update on drink_topic_reviews
  for each row execute function drink_review_evidence_edited();

-- ─────────────────────────────────────────────────────────────
-- 요청 (0060 정의 대체 — 표시 없는 요청의 규칙은 그대로다)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_develop_request_json(r drink_develop_requests) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('request_id', r.id, 'topic_id', r.topic_id, 'kind', r.kind, 'status', r.status, 'step', r.step,
    'review_id', r.review_id, 'budget_id', r.budget_id, 'cost_usd', r.cost_usd, 'cancel_requested', r.cancel_requested,
    'error_code', r.error_code, 'error_message', r.error_message, 'result', r.result,
    'result_review_id', r.result_review_id, 'result_plan_revision_id', r.result_plan_revision_id,
    'chain', r.chain, 'draft_evidence', r.draft_evidence,
    'created_at', r.created_at, 'started_at', r.started_at, 'finished_at', r.finished_at)
$$;

create or replace function drinks_request_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_kind text := drinks_text(p, 'kind');
  v_budget uuid := drinks_uuid(p, 'budget_id', false); v_review uuid := drinks_uuid(p, 'review_id', false); bs jsonb;
  v_draft boolean := coalesce(p -> 'draft_evidence' = 'true'::jsonb, false);
  v_chain boolean := coalesce(p -> 'chain' = 'true'::jsonb, false);
  v_stop jsonb;
begin
  if v_kind is null or v_kind not in ('evidence','plan') then perform drinks_fail('invalid_input', '종류는 evidence 또는 plan 입니다'); end if;
  if v_draft and v_kind <> 'plan' then perform drinks_fail('invalid_input', '승인 전 근거 표시는 대본 초안 요청에만 씁니다'); end if;
  if v_chain and v_kind <> 'evidence' then perform drinks_fail('invalid_input', '이어 만들기 표시는 근거 초안 요청에만 씁니다'); end if;
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  select * into q from drink_develop_requests where topic_id = t.id and kind = v_kind and status in ('queued','running');
  if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
  if v_budget is not null then
    bs := drinks_develop_budget_json(v_budget);
    if bs is null then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
    if bs ->> 'status' <> 'open' then perform drinks_fail('approval_closed', '닫힌 결재입니다'); end if;
    if (bs ->> 'expired')::boolean then perform drinks_fail('approval_expired', '결재 기간이 지났습니다 — 새로 결재받으세요'); end if;
    if (bs ->> 'remaining_usd')::numeric <= 0 then perform drinks_fail('budget_exceeded', '결재 금액을 모두 썼습니다'); end if;
  end if;
  if v_kind = 'evidence' then
    if t.status not in ('researching','ready','selected') then
      perform drinks_fail('invalid_state', '조사 후보로 고른 소재만 근거 초안을 만들 수 있습니다');
    end if;
    if exists (select 1 from drink_topic_reviews where topic_id = t.id and status = 'draft') then
      perform drinks_fail('draft_exists', '작성 중인 근거 버전이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
    if exists (select 1 from drink_topic_reviews where id = t.current_review_id and status = 'in_review') then
      perform drinks_fail('review_in_progress', '검토 중인 버전이 있습니다 — 승인하거나 변경 요청한 뒤 요청하세요');
    end if;
    v_review := null;
  elsif v_draft then
    -- 승인 전 근거로 대본 초안: 결재 필수, 설명형으로 고른 소재의 작업 중 근거만.
    if v_budget is null then perform drinks_fail('budget_missing', '결재(예산)가 없어 대본을 만들 수 없습니다 — 개발 결재를 열고 다시 요청하세요'); end if;
    if t.status <> 'researching' then perform drinks_fail('invalid_state', '근거를 작성 중인 소재에서만 승인 전 대본 초안을 만듭니다'); end if;
    if not exists (select 1 from drink_topic_picks where topic_id = t.id and format_intent = 'explainer') then
      perform drinks_fail('format_not_selected', '설명형으로 고른 소재만 승인 전 근거로 대본을 만듭니다');
    end if;
    select * into r from drink_topic_reviews where id = t.current_review_id;
    if not found or r.status <> 'draft' then
      perform drinks_fail('review_not_draft', '작성 중인 근거 버전이 없습니다 — 근거 초안을 먼저 만드세요');
    end if;
    if v_review is not null and v_review <> r.id then perform drinks_fail('review_not_current', '작업 중인 근거 버전으로만 만듭니다'); end if;
    v_review := r.id;
    v_stop := drinks_chain_stop_blockers(r.id);
    if jsonb_array_length(v_stop) > 0 then
      perform drinks_fail('evidence_not_usable', '근거에 고칠 곳이 있어 대본을 만들지 않았습니다 — 주장·인용을 먼저 고치세요', v_stop);
    end if;
    -- 옛 근거 버전을 가리키던 초안은 승인될 수 없다 — 새 대본의 자리를 비운다.
    update drink_plan_revisions set blocked_at = now(), blocked_reason = 'evidence_edited: 더 새로운 근거 버전이 있습니다'
      where topic_id = t.id and format = 'video' and drafted_from_unapproved and plan_status = 'draft' and blocked_at is null
        and topic_review_id <> r.id;
    if exists (select 1 from drink_deliverables d join drink_plan_revisions pr on pr.deliverable_id = d.id
        where d.topic_id = t.id and d.format = 'video' and pr.plan_status = 'draft' and pr.blocked_at is null) then
      perform drinks_fail('draft_exists', '이 근거로 만든 대본이 이미 있습니다');
    end if;
  else
    v_review := coalesce(v_review, t.approved_review_id);
    if v_review is null then perform drinks_fail('review_not_approved', '승인된 근거 버전이 있어야 제작안 초안을 만들 수 있습니다'); end if;
    select * into r from drink_topic_reviews where id = v_review;
    if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다'); end if;
    if r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then
      perform drinks_fail('review_not_approved', '승인되고 지금도 유효한 근거 버전으로만 제작안 초안을 만들 수 있습니다');
    end if;
    if t.status <> 'selected' or not 'video' = any(t.selected_formats) then
      perform drinks_fail('format_not_selected', '영상으로 편성된 소재만 제작안 초안을 만들 수 있습니다');
    end if;
    if exists (select 1 from drink_deliverables d join drink_plan_revisions pr on pr.deliverable_id = d.id
        where d.topic_id = t.id and d.format = 'video' and pr.plan_status = 'draft' and pr.blocked_at is null) then
      perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
  end if;
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id, chain, draft_evidence)
    values (t.id, v_kind, v_review, v_budget, v_chain, v_draft) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', v_kind, 'budget_id', v_budget, 'review_id', v_review, 'chain', v_chain, 'draft_evidence', v_draft));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

-- 소재 화면용: 0060 + 형식 선택.
create or replace function drinks_develop_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id');
begin
  perform drinks_reap_develop();
  if not exists (select 1 from drink_topics where id = v_topic) then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  return jsonb_build_object('topic_id', v_topic,
    'requests', coalesce((select jsonb_agg(drinks_develop_request_json(x) order by x.created_at desc)
      from drink_develop_requests x where x.id in (select id from drink_develop_requests where topic_id = v_topic
        order by created_at desc limit 10)), '[]'),
    'active', (select drinks_develop_request_json(a) from drink_develop_requests a where a.topic_id = v_topic and a.status in ('queued','running')
      order by a.created_at desc limit 1),
    'budgets', coalesce((select jsonb_agg(drinks_develop_budget_json(s.budget_id) order by s.created_at desc)
      from drink_develop_budget_state s where s.status = 'open' and not s.expired), '[]'),
    'pick', (select to_jsonb(k) from drink_topic_picks k where k.topic_id = v_topic),
    'limits', drinks_develop_limits());
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 (service_role) — 초안까지만. 승인·제출·편성 함수를 부르지 않는다
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_start_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; v_reaped int; v_block text; v_budget jsonb; v_job jsonb; v_intent text;
begin
  v_reaped := drinks_reap_develop();
  loop
    select * into q from drink_develop_requests where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    select * into t from drink_topics where id = q.topic_id;
    select format_intent into v_intent from drink_topic_picks where topic_id = q.topic_id;
    v_block := null;
    if q.kind = 'evidence' then
      if t.status not in ('researching','ready','selected') then v_block := 'topic_state_changed'; end if;
    else
      select * into r from drink_topic_reviews where id = q.review_id;
      if q.draft_evidence then
        if t.status <> 'researching' then v_block := 'topic_state_changed';
        elsif r.status <> 'draft' or r.id is distinct from t.current_review_id then v_block := 'review_changed';
        elsif v_intent is distinct from 'explainer' then v_block := 'format_not_selected'; end if;
      elsif r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then v_block := 'review_not_approved';
      elsif t.status <> 'selected' or not 'video' = any(t.selected_formats) then v_block := 'format_not_selected'; end if;
    end if;
    if v_block is not null then
      update drink_develop_requests set status = 'canceled', finished_at = now(), error_code = v_block,
        error_message = '대기 중에 소재·근거 상태가 바뀌어 만들지 않았습니다(' || v_block || ')' where id = q.id;
      continue;
    end if;
    update drink_develop_requests set status = 'running', lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => (drinks_develop_limits() ->> 'lease_sec')::int),
      heartbeat_at = now(), started_at = now(), step = 'started', worker_id = coalesce(drinks_text(p, 'worker_id'), 'worker'),
      evidence_hash = case when q.draft_evidence then drinks_evidence_content_hash(r.evidence_pack, r.brief) end
      where id = q.id returning * into q;
    v_budget := case when q.budget_id is null then null else drinks_develop_budget_json(q.budget_id) end;
    v_job := jsonb_build_object('request_id', q.id, 'lease_token', q.lease_token, 'kind', q.kind, 'budget_id', q.budget_id,
      'budget', v_budget, 'limits', drinks_develop_limits(), 'chain', q.chain, 'draft_evidence', q.draft_evidence, 'format_intent', v_intent,
      'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'categories', to_jsonb(t.categories),
        'status', t.status, 'version', t.version, 'target_subject', t.target_subject, 'angle', t.angle));
    if q.kind = 'plan' then
      v_job := v_job || jsonb_build_object('review', jsonb_build_object('review_id', r.id, 'status', r.status, 'brief', r.brief,
        'core_claim_ids', to_jsonb(drinks_text_array(r.brief -> 'selected_claim_ids')),
        'claims', coalesce((select jsonb_agg(c) from jsonb_array_elements(r.evidence_pack -> 'claims') c
          where c ->> 'claim_id' = any(drinks_text_array(r.brief -> 'selected_claim_ids'))), '[]'),
        'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher,
            'url', s.canonical_url, 'published_at', s.published_at))
          from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
            from jsonb_array_elements(r.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]')));
    end if;
    return jsonb_build_object('reaped', v_reaped, 'job', v_job);
  end loop;
end $$;

-- 제작안 초안 저장(제출·승인 아님). 표시 없는 요청은 0061 그대로 drinks_save_plan 을 부른다.
-- 승인 전 근거 경로: 편성 전이라 drinks_save_plan 을 쓸 수 없다. 대신 작성 중인 그 근거 버전 + 워커가 시작 때 본 내용과 같을 때만 저장한다.
-- 핵심 메시지가 비어 있으면 대본의 결론 한 줄을 초안으로 채운다(운영자가 승인 화면에서 고친다). support_review 는 건드리지 않는다.
create or replace function drinks_develop_save_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_res jsonb; v_dver int; t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions;
  v_plan jsonb; v_no int; v_hash text; v_take text := left(drinks_text(p, 'core_takeaway_draft'), 300);
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'plan' then perform drinks_fail('invalid_state', '제작안 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  if not q.draft_evidence then
    select dv.version into v_dver from drink_deliverables dv where dv.topic_id = q.topic_id and dv.format = 'video' for update;
    v_res := drinks_save_plan(jsonb_build_object('topic_id', q.topic_id, 'format', 'video', 'topic_review_id', q.review_id,
      'plan_json', p -> 'plan_json') || case when v_dver is null then '{}'::jsonb
                                         else jsonb_build_object('expected_deliverable_version', v_dver) end);
    update drink_develop_requests set result_plan_revision_id = (v_res ->> 'revision_id')::uuid, step = 'plan_saved' where id = q.id;
    return v_res;
  end if;
  t := drinks_lock_topic(q.topic_id, null, false);
  select * into r from drink_topic_reviews where id = q.review_id for update;
  if t.status <> 'researching' or r.status <> 'draft' or t.current_review_id is distinct from r.id then
    perform drinks_fail('review_changed', '대본을 쓰는 사이 근거·소재 상태가 바뀌었습니다 — 저장하지 않습니다');
  end if;
  v_hash := drinks_evidence_content_hash(r.evidence_pack, r.brief);
  if q.evidence_hash is distinct from v_hash then
    perform drinks_fail('review_changed', '대본을 쓰는 사이 근거가 바뀌었습니다 — 바뀐 근거로 다시 만들어야 합니다');
  end if;
  if not exists (select 1 from drink_topic_picks where topic_id = t.id and format_intent = 'explainer') then
    perform drinks_fail('format_not_selected', '설명형으로 고른 소재가 아닙니다');
  end if;
  v_plan := drinks_validate_plan('video', p -> 'plan_json', r);
  select * into d from drink_deliverables where topic_id = t.id and format = 'video' and locale = 'ko' for update;
  if not found then
    insert into drink_deliverables (topic_id, format) values (t.id, 'video') returning * into d;
    perform drinks_log(t.id, 'deliverable', d.id, 'deliverable_created', null, null, 'video', null);
  end if;
  if exists (select 1 from drink_plan_revisions where deliverable_id = d.id and plan_status = 'draft' and blocked_at is null) then
    perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다');
  end if;
  if v_take is not null and drinks_text(r.brief, 'core_takeaway') is null then
    update drink_topic_reviews set brief = jsonb_set(brief, '{core_takeaway}', to_jsonb(v_take)) where id = r.id returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    perform drinks_log(t.id, 'review', r.id, 'core_takeaway_prefilled', 'draft', 'draft', r.input_hash, null, jsonb_build_object('request_id', q.id));
  end if;
  select coalesce(max(revision_no), 0) + 1 into v_no from drink_plan_revisions where deliverable_id = d.id;
  insert into drink_plan_revisions (deliverable_id, topic_id, format, revision_no, topic_review_id, plan_json, aspect_ratio,
      drafted_from_unapproved, evidence_content_hash)
    values (d.id, t.id, 'video', v_no, r.id, v_plan, '9:16', true, v_hash) returning * into pr;
  update drink_deliverables set current_revision_id = pr.id where id = d.id;
  update drink_develop_requests set result_plan_revision_id = pr.id, step = 'plan_saved' where id = q.id;
  perform drinks_log(t.id, 'plan', pr.id, 'plan_created', null, 'draft', pr.input_hash, null,
    jsonb_build_object('format', 'video', 'revision_no', v_no, 'topic_review_id', r.id, 'drafted_from_unapproved', true));
  return jsonb_build_object('revision_id', pr.id, 'deliverable_id', d.id, 'revision_no', pr.revision_no, 'version', pr.version,
    'input_hash', pr.input_hash, 'coverage', drinks_plan_coverage('video', pr.plan_json, r), 'drafted_from_unapproved', true);
end $$;

-- 근거 초안 성공 뒤 대본 요청을 넣는다. 막히면 그 이유를 돌려준다(근거 초안 자체는 성공이다).
-- 이 함수가 대본 요청을 넣지 못한 것은 오류가 아니라 '여기서 멈춤'이다 — 요청 기록의 result.chain 으로 화면에 나간다.
create or replace function drinks_develop_chain_next(q drink_develop_requests) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_intent text; v_stop jsonb; v_res jsonb;
begin
  select format_intent into v_intent from drink_topic_picks where topic_id = q.topic_id;
  if v_intent = 'card' then
    return jsonb_build_object('queued', false, 'code', 'card_plan_not_built', 'message',
      '카드뉴스 대본 자동 작성은 아직 없습니다 — 근거 초안까지 만들고 멈췄습니다. 근거 탭에서 승인·편성한 뒤 카드뉴스 탭에서 페이지를 쓰세요');
  end if;
  if v_intent is distinct from 'explainer' then
    return jsonb_build_object('queued', false, 'code', 'format_not_selected', 'message', '설명형으로 고른 소재가 아니라 대본을 이어 만들지 않았습니다');
  end if;
  if q.budget_id is null then
    return jsonb_build_object('queued', false, 'code', 'budget_missing', 'message', '개발 결재가 없어 대본을 만들지 않았습니다');
  end if;
  v_stop := drinks_chain_stop_blockers(q.result_review_id);
  if jsonb_array_length(v_stop) > 0 then
    return jsonb_build_object('queued', false, 'code', 'evidence_not_usable', 'blockers', v_stop, 'message',
      '근거에 고칠 곳이 있어 대본을 만들지 않았습니다 — 돈을 쓰기 전에 멈췄습니다. 주장·인용을 고친 뒤 대본을 다시 요청하세요');
  end if;
  begin
    v_res := drinks_request_develop(jsonb_build_object('topic_id', q.topic_id, 'kind', 'plan', 'budget_id', q.budget_id, 'draft_evidence', true));
    return jsonb_build_object('queued', true, 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
  exception when raise_exception then
    if sqlerrm not like 'drinks:%' then raise; end if;
    return jsonb_build_object('queued', false, 'code', split_part(sqlerrm, ':', 2), 'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
  end;
end $$;

create or replace function drinks_finish_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_out text := drinks_text(p, 'outcome'); v_status text; v_chain jsonb;
  v_result jsonb := case when jsonb_typeof(p -> 'result') = 'object' then p -> 'result' else '{}'::jsonb end;
begin
  q := drinks_develop_lock(p);
  if v_out is null or v_out not in ('succeeded','failed','blocked') then perform drinks_fail('invalid_input', 'outcome 은 succeeded·failed·blocked 입니다'); end if;
  if v_out = 'succeeded' and not ((q.kind = 'evidence' and q.result_review_id is not null) or (q.kind = 'plan' and q.result_plan_revision_id is not null)) then
    perform drinks_fail('invalid_state', '저장된 결과(근거 버전·제작안)가 없는 요청은 성공으로 닫을 수 없습니다');
  end if;
  v_status := case when v_out <> 'succeeded' and q.cancel_requested and drinks_text(p, 'error_code') = 'canceled' then 'canceled' else v_out end;
  -- 같은 트랜잭션: 워커가 이 사이에 죽어 '근거는 성공했는데 대본 요청이 안 들어간' 상태가 생기지 않는다.
  if v_out = 'succeeded' and q.kind = 'evidence' and q.chain then
    v_chain := drinks_develop_chain_next(q);
    v_result := v_result || jsonb_build_object('chain', v_chain);
  end if;
  update drink_develop_requests set status = v_status, finished_at = now(), lease_token = null,
    error_code = case when v_out = 'succeeded' then null else coalesce(drinks_text(p, 'error_code'), v_out) end,
    error_message = left(drinks_text(p, 'error_message'), 4000),
    result = v_result,
    step = v_out where id = q.id returning * into q;
  perform drinks_log(q.topic_id, 'topic', q.topic_id, 'develop_finished', 'running', q.status, q.id::text, q.error_code,
    jsonb_build_object('kind', q.kind, 'cost_usd', q.cost_usd, 'chain', v_chain));
  return drinks_develop_request_json(q);
end $$;

-- ─────────────────────────────────────────────────────────────
-- [이걸로] (운영자) — 소재 올리기 + 형식·편성 의도 + 이어 만들기 요청. 돈은 여기서 나가지 않는다.
-- 후보에서 오면 제목·질문·주종은 사람이 쓴 값이어야 한다(drinks_promote_candidate 가 검사한다). 후보의 임시 점수를 소재의 경량 점수로 옮기고
-- (rubric 이 discovery-v1 이라 경량 평가와 구별된다) 5축 편성 평가는 승인 화면에서 사람이 매긴다.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_pick_topic(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_format text := drinks_text(p, 'format'); v_cand uuid := drinks_uuid(p, 'candidate_id', false); v_topic uuid := drinks_uuid(p, 'topic_id', false);
  v_week date := drinks_date(p, 'editorial_week'); v_budget uuid := drinks_uuid(p, 'budget_id', false);
  c drink_discovery_candidates; t drink_topics; r drink_topic_reviews; v_res jsonb; v_chain jsonb; v_created boolean := false; v_fits jsonb;
begin
  if v_format is null or v_format not in ('explainer','card','meme') then perform drinks_fail('invalid_input', '형식(설명형·카드뉴스·밈형)을 고르세요'); end if;
  if v_week is null then perform drinks_fail('invalid_input', '편성 주차를 고르세요'); end if;
  v_week := v_week - (extract(isodow from v_week)::int - 1);
  if (v_cand is null) = (v_topic is null) then perform drinks_fail('invalid_input', '후보 또는 소재 중 하나를 지정하세요'); end if;
  if v_cand is not null then
    select * into c from drink_discovery_candidates where id = v_cand;
    if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
    if c.provisional_score is null then
      perform drinks_fail('scores_incomplete', '이 후보에는 임시 점수가 없습니다 — 소재로 올린 뒤 경량 평가를 먼저 하세요');
    end if;
    v_res := drinks_promote_candidate(p - 'topic_id');
    v_topic := (v_res ->> 'topic_id')::uuid;
    v_created := true;
    t := drinks_lock_topic(v_topic, null, false);
    v_fits := jsonb_strip_nulls(jsonb_build_object('fit_video', c.fit_video, 'fit_carousel', c.fit_carousel));
    update drink_topics set status = 'triaged', provisional_score = c.provisional_score, provisional_rubric = c.rubric,
      provisional_scores = case when v_fits = '{}'::jsonb then null else v_fits end,
      triage_reason = c.score_reason
      where id = t.id returning * into t;
    perform drinks_log(t.id, 'topic', t.id, 'triaged', 'inbox', t.status, c.rubric, '후보 임시 점수를 옮김',
      jsonb_build_object('candidate_id', c.id, 'score', c.provisional_score));
  else
    t := drinks_lock_topic(v_topic, drinks_int(p, 'expected_version', false), false);
  end if;
  if t.status = 'triaged' then
    perform drinks_topic_action(jsonb_build_object('topic_id', t.id, 'expected_version', t.version, 'action', 'start_research'));
    t := drinks_lock_topic(t.id, null, false);
  end if;
  if t.status = 'inbox' then
    perform drinks_fail('invalid_state', '경량 평가를 먼저 하세요(요약 탭)');
  elsif t.status in ('ready','selected') then
    perform drinks_fail('invalid_state', '이미 근거가 승인된 소재입니다 — 기존 공통 기획·제작안 탭에서 이어 가세요');
  elsif t.status <> 'researching' then
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재입니다 — 다시 연 뒤에 고르세요');
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if found and r.status = 'in_review' then
    perform drinks_fail('review_in_progress', '검토 중인 근거 버전이 있습니다 — 공통 기획 탭에서 승인하거나 변경 요청한 뒤 고르세요');
  end if;
  insert into drink_topic_picks (topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id)
    values (t.id, v_format, drinks_text(p, 'recommended_format'), left(drinks_text(p, 'recommended_reason'), 500), v_week, v_budget, v_cand)
    on conflict (topic_id) do update set format_intent = excluded.format_intent, recommended_format = excluded.recommended_format,
      recommended_reason = excluded.recommended_reason, editorial_week = excluded.editorial_week, budget_id = excluded.budget_id,
      candidate_id = coalesce(drink_topic_picks.candidate_id, excluded.candidate_id), approved_at = null, approved_amount_usd = null;
  perform drinks_log(t.id, 'topic', t.id, 'format_picked', t.status, t.status, v_format, null,
    jsonb_build_object('format_intent', v_format, 'maps_to', drinks_intent_format(v_format), 'recommended_format', drinks_text(p, 'recommended_format'),
      'editorial_week', v_week, 'budget_id', v_budget, 'candidate_id', v_cand));
  if v_format = 'meme' then
    v_chain := jsonb_build_object('queued', false, 'code', 'meme_board', 'message',
      '밈형은 근거·대본을 만들지 않습니다. 형식만 적어 두었고, 제작은 밈 보드에서 이어집니다(밈 제작 엔진은 아직 없습니다)');
  elsif r.id is not null and r.status = 'draft' then
    if v_format = 'card' then
      v_chain := jsonb_build_object('queued', false, 'code', 'card_plan_not_built', 'message',
        '카드뉴스 대본 자동 작성은 아직 없습니다 — 이 근거를 근거 탭에서 승인·편성한 뒤 카드뉴스 탭에서 페이지를 쓰세요');
    elsif exists (select 1 from drink_plan_revisions pl where pl.topic_review_id = r.id and pl.format = 'video' and pl.plan_status = 'draft' and pl.blocked_at is null) then
      v_chain := jsonb_build_object('queued', false, 'code', 'already_drafted', 'message', '이 근거로 만든 대본이 이미 있습니다');
    else
      v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true)));
      v_chain := jsonb_build_object('queued', true, 'kind', 'plan', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
    end if;
  else
    v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', true)));
    v_chain := jsonb_build_object('queued', true, 'kind', 'evidence', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
  end if;
  return jsonb_build_object('topic_id', t.id, 'created', v_created, 'status', t.status, 'format_intent', v_format,
    'maps_to', drinks_intent_format(v_format), 'editorial_week', v_week, 'chain', v_chain);
end $$;

-- ─────────────────────────────────────────────────────────────
-- [승인] (운영자) — 근거·편성·제작안을 한 트랜잭션으로. 안쪽은 기존 함수 그대로라 검사가 똑같다.
-- 하나라도 실패하면 예외로 전부 되돌아간다(근거만 승인되고 제작안이 남는 일이 없다).
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_approve_content(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions; pk drink_topic_picks;
  v_amount numeric; v_note text := drinks_text(p, 'note'); v_id uuid; v_hash text; v_sel jsonb; v_planned jsonb;
begin
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_topic_version'));
  v_id := drinks_uuid(p, 'review_id');
  select * into r from drink_topic_reviews where id = v_id for update;
  if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거 버전이 아닙니다'); end if;
  v_id := drinks_uuid(p, 'plan_revision_id');
  select * into pr from drink_plan_revisions where id = v_id;
  if not found or pr.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 제작안이 아닙니다'); end if;
  select * into d from drink_deliverables where id = pr.deliverable_id for update;
  select * into pr from drink_plan_revisions where id = v_id for update;
  if r.version <> drinks_int(p, 'expected_review_version') or pr.version <> drinks_int(p, 'expected_plan_version') then
    perform drinks_fail('version_conflict', '보고 있던 근거·대본이 다른 곳에서 바뀌었습니다 — 화면을 새로 불러와 다시 확인하세요');
  end if;
  select * into pk from drink_topic_picks where topic_id = t.id for update;
  if not found then perform drinks_fail('format_not_selected', '[이걸로]로 형식을 고른 소재만 한 번에 승인합니다 — 기존 탭을 쓰세요'); end if;
  if drinks_intent_format(pk.format_intent) is distinct from 'video' or pr.format <> 'video' then
    perform drinks_fail('format_not_selected', '한 번 승인은 지금 설명형(영상)만 됩니다 — 카드뉴스는 기존 탭을 쓰세요');
  end if;
  if t.status <> 'researching' then
    perform drinks_fail('invalid_state', '근거를 작성 중인 소재만 한 번에 승인합니다 — 기존 탭을 쓰세요');
  end if;
  if t.current_review_id is distinct from r.id then perform drinks_fail('review_not_current', '최신 근거 버전이 아닙니다'); end if;
  if r.status not in ('draft','in_review') then perform drinks_fail('invalid_state', '이미 결정된 근거 버전입니다 — 기존 탭을 쓰세요'); end if;
  if not pr.drafted_from_unapproved or pr.plan_status <> 'draft' then
    perform drinks_fail('invalid_state', '승인 전 근거로 만든 작성 중 대본만 한 번에 승인합니다');
  end if;
  if d.current_revision_id is distinct from pr.id then perform drinks_fail('plan_not_current', '최신 대본이 아닙니다'); end if;
  if pr.blocked_at is not null then
    perform drinks_fail('plan_blocked', '이 대본을 만든 뒤 근거가 바뀌었습니다 — 이 근거로 대본을 다시 만들어야 승인할 수 있습니다');
  end if;
  -- ★ 대본이 기댄 근거가 바로 지금 승인하는 근거인가. 트리거가 차단하지만, 승인 직전에 값으로 한 번 더 잰다.
  if pr.topic_review_id is distinct from r.id
      or pr.evidence_content_hash is distinct from drinks_evidence_content_hash(r.evidence_pack, r.brief) then
    perform drinks_fail('plan_stale', '대본이 지금 근거 내용으로 만들어진 것이 아닙니다 — 이 근거로 대본을 다시 만드세요');
  end if;
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', '초안을 만드는 중입니다 — 끝난 뒤에 승인하세요');
  end if;
  -- 승인 금액: 기록만 한다. 결재를 열지 않는다. 상한은 유료 결재 1건 상한(0054)과 같다.
  v_amount := drinks_num(p, 'approved_amount_usd');
  if v_amount <= 0 or v_amount > (drinks_spend_limits() ->> 'max_cap_usd')::numeric then
    perform drinks_fail('invalid_input', '승인 금액은 0 보다 크고 $' || (drinks_spend_limits() ->> 'max_cap_usd') || ' 이하여야 합니다');
  end if;

  -- 1) 근거: 작성 중 → 검토 → 승인. drinks_review_action 이 필수 조건(support_review·핵심 메시지·점수·인용·사용 조건)을 다시 잰다.
  if r.status = 'draft' then
    perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'submit'));
    select * into r from drink_topic_reviews where id = r.id;
  end if;
  perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'approve', 'reason', v_note));
  select * into r from drink_topic_reviews where id = r.id;
  -- 2) 편성: [이걸로] 때 고른 주차·형식. drinks_select 가 65점 기준·형식 적합성·필수 주장을 다시 잰다.
  select * into t from drink_topics where id = t.id;
  v_sel := drinks_select(jsonb_build_object('topic_id', t.id, 'expected_version', t.version, 'review_id', r.id,
    'review_input_hash', r.approved_hash, 'formats', jsonb_build_array('video'), 'editorial_week', to_char(pk.editorial_week, 'YYYY-MM-DD'),
    'score_exception_reason', drinks_text(p, 'score_exception_reason'), 'format_exceptions', coalesce(p -> 'format_exceptions', '{}'::jsonb)));
  -- 3) 대본: 사람이 채운 칸이 근거 해시에 들어갔으니 제작안 해시를 승인된 근거 기준으로 다시 잰다(본문은 그대로) → 제출 → 승인.
  update drink_plan_revisions set updated_at = now() where id = pr.id returning * into pr;
  perform drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'submit'));
  select * into pr from drink_plan_revisions where id = pr.id;
  v_planned := drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'approve', 'reason', v_note));
  select * into pr from drink_plan_revisions where id = pr.id;

  update drink_topic_picks set approved_at = now(), approved_amount_usd = v_amount where topic_id = t.id;
  select * into t from drink_topics where id = t.id;
  perform drinks_log(t.id, 'topic', t.id, 'content_approved', 'researching', t.status, pr.id::text, v_note,
    jsonb_build_object('review_id', r.id, 'review_hash', r.approved_hash, 'plan_revision_id', pr.id, 'plan_hash', pr.approved_hash,
      'format_intent', pk.format_intent, 'approved_amount_usd', v_amount, 'spend_approval_opened', false));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version, 'review_id', r.id, 'review_status', r.status,
    'plan_revision_id', pr.id, 'plan_status', pr.plan_status, 'selected_formats', v_sel -> 'selected_formats',
    'editorial_week', v_sel -> 'editorial_week', 'approved_amount_usd', v_amount, 'coverage', v_planned -> 'coverage');
end $$;

-- ─────────────────────────────────────────────────────────────
-- 형식 추천 입력(읽기만) — 후보 질문의 낱말이 걸리는, 승인된 수집원 글의 개수·글자 수. 사실 근거 판정이 아니라 대강 센 값이다.
-- 단어 매칭은 drinks_develop_sources(0060)와 같고, 출처 종류는 engine/config.py DRINKS_DEVELOP_SOURCE_KINDS_AUTO 와 같다(tests/test_drinks_develop.py 가 대조).
-- 한 번에 후보 50개까지만 잰다(engine/config.py DRINKS_FORMAT_EVIDENCE_MAX_CANDIDATES) — 나머지는 '못 쟀음'으로 화면이 말한다.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_candidate_evidence_counts(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  with ids as (
    select (x)::uuid as id from jsonb_array_elements_text(coalesce(p -> 'candidate_ids', '[]'::jsonb)) x limit 50
  ), cand as (
    select c.id, array(select t from (
        select distinct m[1] as t from regexp_matches(lower(c.key_question), '[a-z0-9가-힣一-龥ぁ-んァ-ヶ]{2,}', 'g') m) w
        where t not in ('the','and','for','why','how','what','does','with','that','this','왜','어떻게','무엇','하는','있는','에서','으로','이유')
        order by t limit 8) as terms
    from drink_discovery_candidates c join ids on ids.id = c.id
  ), docs as (
    select s.id, length(s.body_text) as chars, lower(coalesce(s.title, '') || ' ' || s.body_text) as hay
    from drink_source_snapshots s join drink_sources src on src.id = s.collected_source_id
    where s.body_text is not null and s.capture_method = 'collected' and src.terms_status = 'verified' and src.state in ('active','validated')
      and s.source_kind in ('official','expert','manufacturer')
      and coalesce(drinks_snapshot_meta(s.id) ->> 'rights_status', s.rights_status) <> 'restricted'
  ), hit as (
    select c.id as candidate_id, count(*) as n, coalesce(sum(d.chars), 0) as chars
    from cand c join docs d on exists (select 1 from unnest(c.terms) t where position(t in d.hay) > 0)
    group by c.id
  )
  select coalesce(jsonb_object_agg(c.id, jsonb_build_object('count', coalesce(h.n, 0), 'chars', coalesce(h.chars, 0))), '{}'::jsonb)
  from cand c left join hit h on h.candidate_id = c.id
$$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: anon·authenticated 에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────

alter table drink_topic_picks enable row level security;
revoke all on table drink_topic_picks from anon, authenticated;
grant select, insert, update on table drink_topic_picks to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_%' or p.proname like 'drink\_%')
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;

-- 확인(적용 후):
--   select has_function_privilege('anon', 'public.drinks_approve_content(jsonb)', 'EXECUTE');   → false
--   select has_table_privilege('anon', 'public.drink_topic_picks', 'SELECT');                    → false
