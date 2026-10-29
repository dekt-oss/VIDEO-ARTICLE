-- 주류 소재 자동 개발 — 근거 초안·제작안 초안을 워커가 쓰는 큐와 비용 결재 (2026-10-30). docs/deviation-drinks-develop.md
--
-- 운영자가 소재를 고르면 워커가 ① 공식·전문 출처에서 '원문 그대로 인용'이 붙은 근거 초안, ② 그 근거만으로 쓴 30~40초 대본·화면 계획 초안을
-- 만든다. 운영자는 **기존 화면에서** 근거 승인 → 제작안 승인을 한다(이 파일은 승인 기능을 만들지 않는다 — 워커는 초안까지만 쓴다).
--   drink_develop_budgets   개발용 모델 호출 결재(상한 ≤ $10 · 기간 · 결재 문장). 결재가 없으면 워커는 모델을 한 번도 부르지 못한다
--   drink_develop_requests  요청 큐: 소재×종류(evidence|plan) 1건. 임대(lease)로 워커 1개만 잡는다. 소재×종류 활성 요청은 하나
--   drink_develop_holds     모델 호출 1회 직전의 '가잡기' → 확정(실제 금액) 또는 해제. 결재 행을 잠그고 상한 안일 때만 만든다
--   drink_develop_budget_state (뷰)  결재별 가잡힘·확정·남은 금액
-- 워커가 쓰는 곳은 전부 이 파일의 래퍼 함수를 거친다 — 임대를 가진 워커만 쓰고, 안쪽에서 기존 drinks_add_source·drinks_save_review·
-- drinks_save_plan 을 그대로 부른다(그래서 기존 검사·잠금·감사 이력이 똑같이 적용된다). 승인·제출 함수는 부르지 않는다.
--
-- ★ 비용은 drink_cost_entries 에 넣지 않는다 — 그 표의 job_id 는 제작 작업(drink_production_jobs) 전용 FK 다. 개발 비용은 이 파일의
--   요청 행(cost_usd)과 holds 표에 남는다.
-- ★ 워커가 죽어 가잡기 뒤에 멈추면 그 금액은 '가잡힘'으로 남아 상한을 계속 차지한다(0054 와 같은 결정 — 틀리면 덜 쓰는 쪽으로).
-- ★ 단가·상한 숫자는 engine/config.py DRINKS_DEVELOP_* 와 같아야 한다(tests/test_drinks_develop.py 가 대조).
--
-- 되돌리기: 표 3개·뷰·이 파일의 drinks_*develop* 함수를 drop 한다(다른 표는 이 표들을 참조하지 않는다).
--          기존 함수(0050·0053·0054)는 건드리지 않았다.

create or replace function drinks_develop_limits() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'max_cap_usd', 10,               -- 결재 1건 상한의 상한
    'max_days', 30,                  -- 결재 유효 기간 상한
    'max_usd_per_request', 0.5,      -- 요청 1건이 쓸 수 있는 상한(결재 금액이 커도 이 안에서만)
    'max_holds_per_request', 20,     -- 요청 1건의 모델 호출 횟수 상한(무한 재시도 방지)
    'lease_sec', 1800)
$$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_develop_budgets (
  id             uuid primary key default gen_random_uuid(),
  stage          text not null check (length(stage) between 1 and 60),
  purpose        text not null check (length(purpose) between 1 and 500),
  cap_usd        numeric(10,4) not null check (cap_usd > 0 and cap_usd <= 10),
  approved_by    text not null check (length(approved_by) between 1 and 100),
  approver_words text not null check (length(approver_words) between 1 and 500),   -- 결재권자의 말 원문
  status         text not null default 'open' check (status in ('open','closed')),
  expires_at     timestamptz not null,
  closed_at      timestamptz,
  close_reason   text check (close_reason is null or length(close_reason) <= 500),
  created_at     timestamptz not null default now(),
  check (status = 'open' or (closed_at is not null and close_reason is not null)),
  check (expires_at > created_at)
);
create index if not exists drink_develop_budgets_open_idx on drink_develop_budgets (status, created_at desc);

create table if not exists drink_develop_requests (
  id                      uuid primary key default gen_random_uuid(),
  topic_id                uuid not null references drink_topics(id),
  kind                    text not null check (kind in ('evidence','plan')),
  review_id               uuid references drink_topic_reviews(id),   -- plan: 이 승인된 근거 버전의 주장만 쓴다
  budget_id               uuid references drink_develop_budgets(id), -- 없으면 워커가 모델 호출을 거부한다(budget_missing)
  status                  text not null default 'queued' check (status in ('queued','running','succeeded','failed','canceled','blocked')),
  step                    text check (step is null or length(step) <= 200),
  lease_token             uuid,
  lease_expires_at        timestamptz,
  heartbeat_at            timestamptz,
  worker_id               text,
  cancel_requested        boolean not null default false,
  requested_by            text not null default 'operator',
  error_code              text,
  error_message           text check (error_message is null or length(error_message) <= 4000),
  cost_usd                numeric(10,4) not null default 0 check (cost_usd >= 0),
  result                  jsonb not null default '{}' check (jsonb_typeof(result) = 'object' and length(result::text) <= 400000),
  result_review_id        uuid references drink_topic_reviews(id),
  result_plan_revision_id uuid references drink_plan_revisions(id),
  created_at              timestamptz not null default now(),
  started_at              timestamptz,
  finished_at             timestamptz,
  check (kind <> 'plan' or review_id is not null),
  check (status <> 'running' or (lease_token is not null and started_at is not null)),
  check (status in ('queued','running') or finished_at is not null)
);
-- 같은 소재·같은 종류의 활성 요청은 하나(중복 요청은 그 요청을 돌려준다).
create unique index if not exists drink_develop_one_active_uq on drink_develop_requests (topic_id, kind) where status in ('queued','running');
create index if not exists drink_develop_status_idx on drink_develop_requests (status, created_at);
create index if not exists drink_develop_topic_idx on drink_develop_requests (topic_id, created_at desc);

create table if not exists drink_develop_holds (
  id          uuid primary key default gen_random_uuid(),
  request_id  uuid not null references drink_develop_requests(id),
  budget_id   uuid not null references drink_develop_budgets(id),
  model       text,
  est_usd     numeric(10,4) not null check (est_usd > 0),
  status      text not null default 'held' check (status in ('held','settled','released')),
  actual_usd  numeric(10,4) check (actual_usd is null or actual_usd >= 0),
  note        text check (note is null or length(note) <= 500),
  created_at  timestamptz not null default now(),
  settled_at  timestamptz,
  check ((status = 'held') = (settled_at is null)),
  check (status <> 'settled' or actual_usd is not null)
);
create index if not exists drink_develop_holds_budget_idx on drink_develop_holds (budget_id, status);
create index if not exists drink_develop_holds_request_idx on drink_develop_holds (request_id, status);

-- ─────────────────────────────────────────────────────────────
-- 불변 규칙
-- ─────────────────────────────────────────────────────────────

create or replace function drink_develop_budgets_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '결재 기록은 삭제할 수 없습니다'); end if;
  if (to_jsonb(new) - 'status' - 'closed_at' - 'close_reason') is distinct from (to_jsonb(old) - 'status' - 'closed_at' - 'close_reason') then
    perform drinks_fail('immutable', '결재 내용(상한·기간·말)은 바꿀 수 없습니다 — 닫고 새로 결재받으세요');
  end if;
  if old.status = 'closed' and to_jsonb(new) is distinct from to_jsonb(old) then
    perform drinks_fail('immutable', '닫힌 결재는 다시 열 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_develop_budgets_guard on drink_develop_budgets;
create trigger drink_develop_budgets_guard before update or delete on drink_develop_budgets
  for each row execute function drink_develop_budgets_guard();

create or replace function drink_develop_holds_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '지출 기록은 삭제할 수 없습니다'); end if;
  if old.status <> 'held' then perform drinks_fail('immutable', '확정·해제된 지출은 바꿀 수 없습니다'); end if;
  if (to_jsonb(new) - 'status' - 'actual_usd' - 'settled_at' - 'note') is distinct from
     (to_jsonb(old) - 'status' - 'actual_usd' - 'settled_at' - 'note') then
    perform drinks_fail('immutable', '지출 항목·예상 금액은 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_develop_holds_guard on drink_develop_holds;
create trigger drink_develop_holds_guard before update or delete on drink_develop_holds
  for each row execute function drink_develop_holds_guard();

create or replace function drink_develop_requests_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '개발 요청 기록은 삭제할 수 없습니다'); end if;
  -- 끝난 요청도 늦게 확정된 비용(cost_usd)만은 받는다 — 나간 돈은 기록돼야 한다.
  if old.status not in ('queued','running') and (to_jsonb(new) - 'cost_usd') is distinct from (to_jsonb(old) - 'cost_usd') then
    perform drinks_fail('immutable', '끝난 개발 요청은 바꿀 수 없습니다');
  end if;
  if (new.topic_id, new.kind, new.review_id, new.budget_id, new.created_at) is distinct from
     (old.topic_id, old.kind, old.review_id, old.budget_id, old.created_at) then
    perform drinks_fail('immutable', '요청 내용(소재·종류·근거·결재)은 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_develop_requests_guard on drink_develop_requests;
create trigger drink_develop_requests_guard before update or delete on drink_develop_requests
  for each row execute function drink_develop_requests_guard();

-- ─────────────────────────────────────────────────────────────
-- 결재 뷰 — 남은 금액 = 상한 − (가잡힌 예상 + 확정된 실제)
-- ─────────────────────────────────────────────────────────────

create or replace view drink_develop_budget_state with (security_invoker = true) as
  select b.id as budget_id, b.stage, b.purpose, b.cap_usd, b.status, b.expires_at, (b.expires_at <= now()) as expired,
    coalesce(h.held_usd, 0) as held_usd, coalesce(h.settled_usd, 0) as spent_usd,
    b.cap_usd - coalesce(h.held_usd, 0) - coalesce(h.settled_usd, 0) as remaining_usd,
    coalesce(h.holds, 0) as holds, coalesce(h.settled, 0) as settled, coalesce(h.released, 0) as released,
    b.created_at, b.approver_words, b.closed_at, b.close_reason
  from drink_develop_budgets b
  left join lateral (
    select sum(est_usd) filter (where status = 'held') as held_usd, sum(actual_usd) filter (where status = 'settled') as settled_usd,
      count(*) filter (where status = 'held') as holds, count(*) filter (where status = 'settled') as settled,
      count(*) filter (where status = 'released') as released
    from drink_develop_holds where budget_id = b.id) h on true;

create or replace function drinks_develop_budget_json(p_id uuid) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('budget_id', budget_id, 'stage', stage, 'purpose', purpose, 'cap_usd', cap_usd, 'status', status,
    'expired', expired, 'expires_at', expires_at, 'held_usd', held_usd, 'spent_usd', spent_usd, 'remaining_usd', remaining_usd,
    'holds', holds, 'settled', settled, 'released', released)
  from drink_develop_budget_state where budget_id = p_id
$$;

create or replace function drinks_develop_request_json(r drink_develop_requests) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('request_id', r.id, 'topic_id', r.topic_id, 'kind', r.kind, 'status', r.status, 'step', r.step,
    'review_id', r.review_id, 'budget_id', r.budget_id, 'cost_usd', r.cost_usd, 'cancel_requested', r.cancel_requested,
    'error_code', r.error_code, 'error_message', r.error_message, 'result', r.result,
    'result_review_id', r.result_review_id, 'result_plan_revision_id', r.result_plan_revision_id,
    'created_at', r.created_at, 'started_at', r.started_at, 'finished_at', r.finished_at)
$$;

-- ─────────────────────────────────────────────────────────────
-- 결재 (운영자 — 화면은 운영자 키 게이트 뒤)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_open_develop_budget(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare b drink_develop_budgets; v_cap numeric := drinks_num(p, 'cap_usd'); v_days int := coalesce(drinks_int(p, 'days', false), 7);
begin
  if v_cap <= 0 or v_cap > (drinks_develop_limits() ->> 'max_cap_usd')::numeric then
    perform drinks_fail('invalid_input', '결재 상한은 0 보다 크고 $' || (drinks_develop_limits() ->> 'max_cap_usd') || ' 이하여야 합니다');
  end if;
  if v_days < 1 or v_days > (drinks_develop_limits() ->> 'max_days')::int then
    perform drinks_fail('invalid_input', '결재 유효 기간은 1~' || (drinks_develop_limits() ->> 'max_days') || '일입니다');
  end if;
  if drinks_text(p, 'approver_words') is null then
    perform drinks_fail('invalid_input', '결재권자의 말(승인 문장)을 그대로 적으세요');
  end if;
  insert into drink_develop_budgets (stage, purpose, cap_usd, approved_by, approver_words, expires_at)
  values (coalesce(drinks_text(p, 'stage'), ''), coalesce(drinks_text(p, 'purpose'), ''), v_cap,
    coalesce(drinks_text(p, 'approved_by'), 'operator'), drinks_text(p, 'approver_words'), now() + make_interval(days => v_days))
  returning * into b;
  return drinks_develop_budget_json(b.id);
end $$;

create or replace function drinks_close_develop_budget(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare b drink_develop_budgets;
begin
  select * into b from drink_develop_budgets where id = drinks_uuid(p, 'budget_id') for update;
  if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
  if b.status = 'closed' then return drinks_develop_budget_json(b.id); end if;
  if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '닫는 이유를 적으세요'); end if;
  update drink_develop_budgets set status = 'closed', closed_at = now(), close_reason = left(drinks_text(p, 'reason'), 500) where id = b.id;
  return drinks_develop_budget_json(b.id);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 요청 (운영자)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_reap_develop() returns int language plpgsql set search_path = public, pg_temp as $$
declare n int := 0; r record;
begin
  for r in select id from drink_develop_requests where status = 'running' and lease_expires_at < now()
      order by id for update skip locked loop
    update drink_develop_requests set status = 'failed', finished_at = now(), lease_token = null,
      error_code = 'lease_expired', error_message = '워커 응답이 끊겨 실패 처리했습니다 — 늦게 끝난 결과는 저장하지 않습니다'
      where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

create or replace function drinks_request_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_kind text := drinks_text(p, 'kind');
  v_budget uuid := drinks_uuid(p, 'budget_id', false); v_review uuid := drinks_uuid(p, 'review_id', false); bs jsonb;
begin
  if v_kind is null or v_kind not in ('evidence','plan') then perform drinks_fail('invalid_input', '종류는 evidence 또는 plan 입니다'); end if;
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
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id) values (t.id, v_kind, v_review, v_budget) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', v_kind, 'budget_id', v_budget, 'review_id', v_review));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

create or replace function drinks_cancel_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests;
begin
  perform drinks_reap_develop();
  select * into q from drink_develop_requests where id = drinks_uuid(p, 'request_id') for update;
  if not found then perform drinks_fail('not_found', '개발 요청을 찾지 못했습니다'); end if;
  if q.status = 'queued' then
    update drink_develop_requests set status = 'canceled', finished_at = now(), error_code = 'canceled', error_message = '운영자가 취소했습니다'
      where id = q.id returning * into q;
  elsif q.status = 'running' then
    update drink_develop_requests set cancel_requested = true where id = q.id returning * into q;
  end if;
  return drinks_develop_request_json(q);
end $$;

-- 소재 화면용: 최근 요청들 + 지금 쓸 수 있는 열린 결재 + 상한. 읽기만(워커 회수만 곁들인다).
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
    'limits', drinks_develop_limits());
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 (service_role)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_develop_lock(p jsonb) returns drink_develop_requests language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests;
begin
  select * into q from drink_develop_requests where id = drinks_uuid(p, 'request_id') for update;
  if not found then perform drinks_fail('not_found', '개발 요청을 찾지 못했습니다'); end if;
  if q.status <> 'running' or q.lease_token is distinct from drinks_uuid(p, 'lease_token') or q.lease_expires_at < now() then
    perform drinks_fail('lease_lost', '이 개발 요청의 임대를 잃었습니다(다른 워커가 회수했거나 끝났음)');
  end if;
  return q;
end $$;

create or replace function drinks_start_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; v_reaped int; v_block text; v_budget jsonb; v_job jsonb;
begin
  v_reaped := drinks_reap_develop();
  loop
    select * into q from drink_develop_requests where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    select * into t from drink_topics where id = q.topic_id;
    v_block := null;
    if q.kind = 'evidence' then
      if t.status not in ('researching','ready','selected') then v_block := 'topic_state_changed'; end if;
    else
      select * into r from drink_topic_reviews where id = q.review_id;
      if r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then v_block := 'review_not_approved';
      elsif t.status <> 'selected' or not 'video' = any(t.selected_formats) then v_block := 'format_not_selected'; end if;
    end if;
    if v_block is not null then
      update drink_develop_requests set status = 'canceled', finished_at = now(), error_code = v_block,
        error_message = '대기 중에 소재·근거 상태가 바뀌어 만들지 않았습니다(' || v_block || ')' where id = q.id;
      continue;
    end if;
    update drink_develop_requests set status = 'running', lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => (drinks_develop_limits() ->> 'lease_sec')::int),
      heartbeat_at = now(), started_at = now(), step = 'started', worker_id = coalesce(drinks_text(p, 'worker_id'), 'worker')
      where id = q.id returning * into q;
    v_budget := case when q.budget_id is null then null else drinks_develop_budget_json(q.budget_id) end;
    v_job := jsonb_build_object('request_id', q.id, 'lease_token', q.lease_token, 'kind', q.kind, 'budget_id', q.budget_id,
      'budget', v_budget, 'limits', drinks_develop_limits(),
      'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'categories', to_jsonb(t.categories),
        'status', t.status, 'version', t.version, 'target_subject', t.target_subject, 'angle', t.angle));
    if q.kind = 'plan' then
      v_job := v_job || jsonb_build_object('review', jsonb_build_object('review_id', r.id, 'brief', r.brief,
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

create or replace function drinks_heartbeat_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests;
begin
  q := drinks_develop_lock(p);
  update drink_develop_requests set heartbeat_at = now(), step = coalesce(left(drinks_text(p, 'step'), 200), step),
    lease_expires_at = now() + make_interval(secs => (drinks_develop_limits() ->> 'lease_sec')::int)
    where id = q.id returning * into q;
  return jsonb_build_object('cancel_requested', q.cancel_requested);
end $$;

-- 모델 호출 직전. 결재 행을 잠그고 (가잡기 + 확정 + 이번 예상) ≤ 상한, 요청 1건 상한, 호출 횟수 상한 안일 때만 만든다.
create or replace function drinks_develop_hold(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; b drink_develop_budgets; h drink_develop_holds; v_est numeric := drinks_num(p, 'est_usd');
  v_req_committed numeric; v_n int; s jsonb; v_lim jsonb := drinks_develop_limits();
begin
  q := drinks_develop_lock(p);
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  if v_est <= 0 then perform drinks_fail('invalid_input', '예상 금액은 0 보다 커야 합니다'); end if;
  if q.budget_id is null then perform drinks_fail('budget_missing', '결재(예산)가 없는 요청은 모델을 부를 수 없습니다'); end if;
  select * into b from drink_develop_budgets where id = q.budget_id for update;
  if b.status <> 'open' then perform drinks_fail('approval_closed', '닫힌 결재로는 쓸 수 없습니다'); end if;
  if b.expires_at <= now() then perform drinks_fail('approval_expired', '결재 기간이 지났습니다 — 새로 결재받으세요'); end if;
  select coalesce(sum(case when status = 'held' then est_usd else actual_usd end) filter (where status in ('held','settled')), 0),
    count(*) into v_req_committed, v_n from drink_develop_holds where request_id = q.id;
  if v_n >= (v_lim ->> 'max_holds_per_request')::int then
    perform drinks_fail('hold_limit', '이 요청의 모델 호출이 ' || v_n || '번입니다 — 멈추고 보고하세요');
  end if;
  if v_req_committed + v_est > (v_lim ->> 'max_usd_per_request')::numeric then
    perform drinks_fail('request_cap_exceeded', '요청 1건 상한을 넘습니다(상한 $' || (v_lim ->> 'max_usd_per_request') || ', 이미 $' || v_req_committed || ', 이번 $' || v_est || ')',
      jsonb_build_object('cap_usd', (v_lim ->> 'max_usd_per_request')::numeric, 'committed_usd', v_req_committed, 'requested_usd', v_est));
  end if;
  s := drinks_develop_budget_json(b.id);
  if (s ->> 'remaining_usd')::numeric < v_est then
    perform drinks_fail('budget_exceeded', '결재 금액을 넘습니다(상한 $' || b.cap_usd || ', 남은 $' || (s ->> 'remaining_usd') || ', 이번 $' || v_est || ')',
      jsonb_build_object('cap_usd', b.cap_usd, 'remaining_usd', (s ->> 'remaining_usd')::numeric, 'requested_usd', v_est));
  end if;
  insert into drink_develop_holds (request_id, budget_id, model, est_usd, note)
    values (q.id, b.id, drinks_text(p, 'model'), v_est, left(drinks_text(p, 'note'), 500)) returning * into h;
  return jsonb_build_object('hold_id', h.id, 'remaining_usd', (s ->> 'remaining_usd')::numeric - v_est,
    'request_remaining_usd', (v_lim ->> 'max_usd_per_request')::numeric - v_req_committed - v_est);
end $$;

-- 호출 끝. 성공 = 확정(실제 금액), 실패 = 해제. 임대를 잃었어도 받는다 — 나간 돈은 기록돼야 한다.
create or replace function drinks_develop_settle(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare h drink_develop_holds; v_outcome text := drinks_text(p, 'outcome');
begin
  select * into h from drink_develop_holds where id = drinks_uuid(p, 'hold_id') for update;
  if not found then perform drinks_fail('not_found', '지출 기록을 찾지 못했습니다'); end if;
  if h.status <> 'held' then
    perform drinks_fail('invalid_state', '이미 ' || case h.status when 'settled' then '확정' else '해제' end || '된 지출입니다');
  end if;
  if v_outcome = 'settled' then
    update drink_develop_holds set status = 'settled', actual_usd = drinks_num(p, 'actual_usd'), settled_at = now(),
      note = coalesce(left(drinks_text(p, 'note'), 500), note) where id = h.id returning * into h;
    update drink_develop_requests set cost_usd = cost_usd + h.actual_usd where id = h.request_id;
  elsif v_outcome = 'released' then
    update drink_develop_holds set status = 'released', settled_at = now(), note = coalesce(left(drinks_text(p, 'note'), 500), note)
      where id = h.id returning * into h;
  else
    perform drinks_fail('invalid_input', 'outcome 은 settled 또는 released 입니다');
  end if;
  return jsonb_build_object('hold_id', h.id, 'status', h.status) || drinks_develop_budget_json(h.budget_id);
end $$;

-- 근거 찾기(무료): 이 소재에 이미 붙은 출처(수동 등록 포함) + 승인된 수집원에서 모은 글 중 낱말이 걸리는 것.
-- 사용 조건이 restricted 인 출처는 주지 않는다. 붙은 출처가 먼저(본문이 없는 것도 — 워커가 '붙여넣기 필요'로 알린다).
create or replace function drinks_develop_sources(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_terms text[] := array(select lower(btrim(x)) from unnest(drinks_text_array(p -> 'terms')) x where length(btrim(x)) >= 2);
  v_limit int := least(coalesce(drinks_int(p, 'limit', false), 8), 12);
begin
  q := drinks_develop_lock(p);
  return coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', x.id, 'canonical_url', x.canonical_url, 'title', x.title,
      'publisher', x.publisher, 'source_kind', x.source_kind, 'rights_status', coalesce(m ->> 'rights_status', x.rights_status),
      'usage_terms', x.usage_terms, 'original_language', x.original_language, 'published_at', x.published_at, 'depth', x.depth,
      'linked', x.linked, 'role', x.role, 'body_text', x.body_text) order by x.linked desc, x.created_at desc)
    from (
      select s.*, ts.role is not null as linked, ts.role, drinks_snapshot_meta(s.id) as m
      from drink_source_snapshots s
      left join drink_topic_sources ts on ts.snapshot_id = s.id and ts.topic_id = q.topic_id
      left join drink_sources src on src.id = s.collected_source_id
      where (ts.snapshot_id is not null   -- 붙은 출처는 본문이 없어도 준다(주소만 등록된 출처를 운영자에게 알리려고)
             or (s.body_text is not null and s.capture_method = 'collected' and src.terms_status = 'verified' and src.state in ('active','validated')
                 and exists (select 1 from unnest(v_terms) t where position(t in lower(coalesce(s.title, '') || ' ' || s.body_text)) > 0)))
      order by (ts.snapshot_id is not null) desc, s.created_at desc limit v_limit) x
    where coalesce(m ->> 'rights_status', x.rights_status) <> 'restricted'), '[]');
end $$;

-- 새 출처를 소재에 붙인다(사실 근거 역할). 안쪽은 기존 drinks_add_source — 같은 URL·같은 본문이면 새로 만들지 않는다.
create or replace function drinks_develop_add_source(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'evidence' then perform drinks_fail('invalid_state', '근거 초안 요청에서만 출처를 붙입니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  return drinks_add_source(jsonb_build_object('topic_id', q.topic_id, 'source', (p -> 'source') || jsonb_build_object('role', 'evidence')));
end $$;

-- 이미 있는 출처(수집·수동)를 사실 근거로 이 소재에 붙인다. 본문을 다시 보내지 않는다.
create or replace function drinks_develop_link_snapshot(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; s drink_source_snapshots; v_role text;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'evidence' then perform drinks_fail('invalid_state', '근거 초안 요청에서만 출처를 붙입니다'); end if;
  select * into s from drink_source_snapshots where id = drinks_uuid(p, 'snapshot_id');
  if not found then perform drinks_fail('not_found', '출처를 찾지 못했습니다'); end if;
  if coalesce(drinks_snapshot_meta(s.id) ->> 'rights_status', s.rights_status) = 'restricted' then
    perform drinks_fail('rights_restricted', '사용 조건이 restricted 인 출처는 근거로 쓸 수 없습니다');
  end if;
  select role into v_role from drink_topic_sources where topic_id = q.topic_id and snapshot_id = s.id for update;
  if not found then
    insert into drink_topic_sources (topic_id, snapshot_id, role, relation_note)
      values (q.topic_id, s.id, 'evidence', left(drinks_text(p, 'relation_note'), 500));
    perform drinks_log(q.topic_id, 'topic', q.topic_id, 'source_linked', null, null, s.id::text, null,
      jsonb_build_object('role', 'evidence', 'by', 'develop', 'request_id', q.id));
    v_role := 'evidence';
  elsif v_role = 'discovery' then
    update drink_topic_sources set role = 'evidence' where topic_id = q.topic_id and snapshot_id = s.id;
    v_role := 'evidence';
  end if;
  return jsonb_build_object('snapshot_id', s.id, 'role', v_role);
end $$;

-- 근거 초안 저장(승인·제출 아님). 안쪽은 drinks_save_review — 인용 일치(quote_check)는 DB 가 다시 계산한다.
create or replace function drinks_develop_save_evidence(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; v_res jsonb; v_scores jsonb; v_pack jsonb; r drink_topic_reviews;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'evidence' then perform drinks_fail('invalid_state', '근거 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  select * into t from drink_topics where id = q.topic_id for update;
  v_scores := coalesce(p -> 'scores', t.provisional_scores);
  begin
    v_res := drinks_save_review(jsonb_build_object('topic_id', t.id, 'expected_topic_version', t.version,
      'evidence_pack', p -> 'evidence_pack', 'brief', p -> 'brief', 'scores', v_scores));
  exception when others then
    if not (v_scores is not null and sqlerrm like 'drinks:invalid_input:%') then raise; end if;
    -- 소재의 잠정 점수 모양이 맞지 않으면 점수 없이 저장한다(운영자가 화면에서 채운다).
    v_res := drinks_save_review(jsonb_build_object('topic_id', t.id, 'expected_topic_version', t.version,
      'evidence_pack', p -> 'evidence_pack', 'brief', p -> 'brief'));
  end;
  select * into r from drink_topic_reviews where id = (v_res ->> 'review_id')::uuid;
  v_pack := r.evidence_pack;
  update drink_develop_requests set result_review_id = r.id, step = 'evidence_saved' where id = q.id;
  return v_res || jsonb_build_object('quote_check', jsonb_build_object(
    'matched', (select count(*) from jsonb_array_elements(v_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref where ref ->> 'quote_check' = 'matched'),
    'unmatched', (select count(*) from jsonb_array_elements(v_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref where ref ->> 'quote_check' = 'unmatched'),
    'not_checked', (select count(*) from jsonb_array_elements(v_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref where ref ->> 'quote_check' = 'not_checked')));
end $$;

-- 제작안 초안 저장(제출·승인 아님). 안쪽은 drinks_save_plan — 이 요청이 가리키는 승인된 근거 버전으로만, 그 핵심 주장만 쓸 수 있다.
create or replace function drinks_develop_save_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_res jsonb;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'plan' then perform drinks_fail('invalid_state', '제작안 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  v_res := drinks_save_plan(jsonb_build_object('topic_id', q.topic_id, 'format', 'video', 'topic_review_id', q.review_id,
    'plan_json', p -> 'plan_json'));
  update drink_develop_requests set result_plan_revision_id = (v_res ->> 'revision_id')::uuid, step = 'plan_saved' where id = q.id;
  return v_res;
end $$;

create or replace function drinks_finish_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_out text := drinks_text(p, 'outcome'); v_status text;
begin
  q := drinks_develop_lock(p);
  if v_out is null or v_out not in ('succeeded','failed','blocked') then perform drinks_fail('invalid_input', 'outcome 은 succeeded·failed·blocked 입니다'); end if;
  if v_out = 'succeeded' and not ((q.kind = 'evidence' and q.result_review_id is not null) or (q.kind = 'plan' and q.result_plan_revision_id is not null)) then
    perform drinks_fail('invalid_state', '저장된 결과(근거 버전·제작안)가 없는 요청은 성공으로 닫을 수 없습니다');
  end if;
  v_status := case when v_out <> 'succeeded' and q.cancel_requested and drinks_text(p, 'error_code') = 'canceled' then 'canceled' else v_out end;
  update drink_develop_requests set status = v_status, finished_at = now(), lease_token = null,
    error_code = case when v_out = 'succeeded' then null else coalesce(drinks_text(p, 'error_code'), v_out) end,
    error_message = left(drinks_text(p, 'error_message'), 4000),
    result = case when jsonb_typeof(p -> 'result') = 'object' then p -> 'result' else '{}'::jsonb end,
    step = v_out where id = q.id returning * into q;
  perform drinks_log(q.topic_id, 'topic', q.topic_id, 'develop_finished', 'running', q.status, q.id::text, q.error_code,
    jsonb_build_object('kind', q.kind, 'cost_usd', q.cost_usd));
  return drinks_develop_request_json(q);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: anon·authenticated 에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────

alter table drink_develop_budgets enable row level security;
alter table drink_develop_requests enable row level security;
alter table drink_develop_holds enable row level security;

revoke all on table drink_develop_budgets, drink_develop_requests, drink_develop_holds from anon, authenticated;
revoke all on table drink_develop_budget_state from anon, authenticated;
grant select, insert, update on table drink_develop_budgets, drink_develop_requests, drink_develop_holds to service_role;
grant select on table drink_develop_budget_state to service_role;

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
--   select has_function_privilege('anon', 'public.drinks_request_develop(jsonb)', 'EXECUTE');   → false
--   select has_table_privilege('anon', 'public.drink_develop_requests', 'SELECT');               → false
