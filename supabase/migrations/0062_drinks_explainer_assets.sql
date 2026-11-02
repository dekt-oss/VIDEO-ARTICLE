-- 주류 설명형 릴스 — 슬롯 → 후보 → 시도 + 선택 (2026-11-02). 기획 v2 §3-3. docs/deviation-drinks-explainer-stage1.md
--
-- ★ 이 파일은 아직 운영 DB 에 적용하지 않았다(적용은 별도 결재 — 기획 v2 §10-6).
--
-- 자산은 3단이다. 편집 컷은 engine/drinks_explainer.py 의 별도 표다.
--   drink_explainer_slots       장면당 하나. slot_id = {plan_id}:A{n}. 사양 해시(모델·문장·시작 그림·길이·해상도)는 바꿀 수 없다
--   drink_explainer_candidates  슬롯당 1~2개. candidate_id = {slot_id}#c{k}. 후보마다 별도 item_key — 0054 의 '항목당 시도' 상한이 후보마다 걸린다
--   drink_explainer_attempts    후보당 2회·슬롯당 4회까지. attempt_id = {candidate_id}#a{m}. idempotency_key = sha256(attempt_id + spec_hash).
--                               **공급자 호출 전에** 행을 만든다(requested). 호출 직전에 generating 으로 올린다 — 그래서 generating 에서 멈춘
--                               시도는 "보냈는지 모름"이고(unknown_billed), requested 에서 멈춘 시도는 "안 보냈음"이다.
--   drink_explainer_selections  슬롯당 하나. 사람만 고른다. 자동 합격 + 사람 합격인 후보만 고를 수 있다.
--
-- 규칙(코드가 아니라 DB 가 막는다):
--   · 후보의 시도는 한 번에 하나만 열린다(부분 유니크 인덱스). unknown_billed 는 "열린" 상태다 — 닫기 전에는 같은 후보로 새 시도를 만들 수 없다.
--   · 재시도: failed_unbilled 는 같은 결재로, failed_billed·closed_billed(돈이 나감)는 **새 결재로만**. closed_void 는 없던 일이라 같은 결재로 된다.
--   · 두 후보가 모두 불합격이면 슬롯은 no_pass — 고를 수 없다("그나마 나은 쪽"을 채택하지 않는다). 선택지는 새 결재 재촬영 또는 계획 변경뿐이다.
--   · 자동 재구매 경로는 없다. 이 파일의 어떤 함수도 공급자를 부르지 않는다.
--
-- ★ 숫자는 engine/config.py DRINKS_EXPLAINER_MAX_* 와 같아야 한다(tests/test_drinks_explainer.py 가 대조).
-- ★ 시각 주장표(§3-4)는 이 파일에 없다 — engine/drinks_develop.py visual_claim_table 이 개발 요청 결과(result)에 남긴다. 근거는 deviation 문서.
--
-- 되돌리기: 표 4개와 이 파일의 drinks_explainer_* · drink_explainer_* 함수를 drop 한다(아래 순서).
--   drop table drink_explainer_selections, drink_explainer_attempts, drink_explainer_candidates, drink_explainer_slots;
--   drop function drinks_explainer_limits, drinks_explainer_idem, drink_explainer_slot_advance, drink_explainer_candidate_settle,
--     drink_explainer_attempts_guard, drink_explainer_candidates_guard, drink_explainer_slots_guard, drink_explainer_selections_guard,
--     drinks_explainer_plan_slot, drinks_explainer_open_attempt, drinks_explainer_attempt_event, drinks_explainer_close_unknown,
--     drinks_explainer_sweep_stale, drinks_explainer_verdict, drinks_explainer_select, drinks_explainer_selected_asset;
--   다른 표는 이 표들을 참조하지 않는다. 기존 함수(0050·0053·0054·0057·0060)는 건드리지 않았다.

create or replace function drinks_explainer_limits() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'max_candidates_per_slot', 2,
    'max_attempts_per_candidate', 2,
    'max_attempts_per_slot', 4)
$$;

create or replace function drinks_explainer_idem(p_attempt text, p_spec text) returns text
language sql immutable set search_path = public, pg_temp as $$
  select encode(sha256(convert_to(p_attempt || p_spec, 'UTF8')), 'hex')
$$;

-- ─────────────────────────────────────────────────────────────
-- 표
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_explainer_slots (
  slot_id            text primary key,
  plan_revision_id   uuid not null references drink_plan_revisions(id),
  n                  int not null check (n >= 1),
  role               text not null check (role in ('reality','mechanism')),
  spec_hash          text not null check (spec_hash ~ '^[0-9a-f]{64}$'),
  min_src_ms         int not null check (min_src_ms > 0),
  candidates_planned int not null check (candidates_planned between 1 and 2),
  boundary_in        text check (boundary_in in ('loop','flash_forward','cut_to_mechanism','match','same_clip')),
  boundary_out       text check (boundary_out in ('loop','flash_forward','cut_to_mechanism','match','same_clip')),
  status             text not null default 'pending' check (status in ('pending','requested','received','probed','auto_checked','human_checked','selected','no_pass')),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check (slot_id = plan_revision_id::text || ':A' || n::text),
  unique (plan_revision_id, n)
);

create table if not exists drink_explainer_candidates (
  candidate_id  text primary key,
  slot_id       text not null references drink_explainer_slots(slot_id),
  k             int not null check (k between 1 and 2),
  seed          bigint,
  status        text not null default 'pending' check (status in ('pending','attempting','stored','failed')),
  cost_usd      numeric(10,4) not null default 0 check (cost_usd >= 0),   -- 시도 합계(불합격 후보의 돈도 남는다)
  auto_verdict  text check (auto_verdict in ('pass','fail')),
  human_verdict text check (human_verdict in ('pass','fail')),
  asset_id      uuid references drink_media_assets(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  check (candidate_id = slot_id || '#c' || k::text),
  check (status <> 'stored' or asset_id is not null),
  unique (slot_id, k)
);

create table if not exists drink_explainer_attempts (
  attempt_id          text primary key,
  candidate_id        text not null references drink_explainer_candidates(candidate_id),
  slot_id             text not null references drink_explainer_slots(slot_id),
  m                   int not null check (m between 1 and 2),
  spec_hash           text not null check (spec_hash ~ '^[0-9a-f]{64}$'),
  idempotency_key     text not null unique check (idempotency_key ~ '^[0-9a-f]{64}$'),
  approval_id         uuid not null references drink_spend_approvals(id),
  hold_id             uuid references drink_spend_holds(id),
  provider            text not null check (length(provider) between 1 and 40),
  provider_request_id text check (provider_request_id is null or length(provider_request_id) <= 500),
  state               text not null default 'requested' check (state in
                        ('requested','generating','received','probed','stored','failed_unbilled','failed_billed','unknown_billed','closed_billed','closed_void')),
  billed_units        numeric(14,4) check (billed_units is null or billed_units >= 0),
  actual_usd          numeric(10,4) check (actual_usd is null or actual_usd >= 0),
  error_code          text check (error_code is null or length(error_code) <= 100),
  closed_by           text check (closed_by is null or length(closed_by) <= 100),
  close_note          text check (close_note is null or length(close_note) <= 500),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  check (attempt_id = candidate_id || '#a' || m::text),
  check (idempotency_key = drinks_explainer_idem(attempt_id, spec_hash)),
  check (state not in ('closed_billed','closed_void') or (closed_by is not null and close_note is not null)),
  unique (candidate_id, m)
);
-- 후보의 시도는 한 번에 하나만 열린다. unknown_billed 도 열린 상태다 — 닫기 전에는 새 시도를 만들 수 없다(§3-3).
create unique index if not exists drink_explainer_one_open_attempt_uq on drink_explainer_attempts (candidate_id)
  where state in ('requested','generating','received','probed','unknown_billed');
create index if not exists drink_explainer_attempts_slot_idx on drink_explainer_attempts (slot_id, state);

create table if not exists drink_explainer_selections (
  slot_id               text primary key references drink_explainer_slots(slot_id),
  selected_candidate_id text not null references drink_explainer_candidates(candidate_id),
  selected_by           text not null check (length(btrim(selected_by)) between 1 and 100 and lower(btrim(selected_by)) not in ('worker','system','auto')),
  reason                text not null check (length(btrim(reason)) between 1 and 500),
  selected_at           timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────
-- 불변 규칙
-- ─────────────────────────────────────────────────────────────

create or replace function drink_explainer_slots_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '슬롯 기록은 삭제할 수 없습니다'); end if;
  if (to_jsonb(new) - 'status' - 'updated_at') is distinct from (to_jsonb(old) - 'status' - 'updated_at') then
    perform drinks_fail('immutable', '슬롯 사양은 바꿀 수 없습니다 — 사양이 바뀌면 새 제작안의 새 슬롯입니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_explainer_slots_guard on drink_explainer_slots;
create trigger drink_explainer_slots_guard before update or delete on drink_explainer_slots
  for each row execute function drink_explainer_slots_guard();

create or replace function drink_explainer_candidates_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '후보 기록은 삭제할 수 없습니다'); end if;
  if (new.candidate_id, new.slot_id, new.k) is distinct from (old.candidate_id, old.slot_id, old.k) then
    perform drinks_fail('immutable', '후보 키는 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_explainer_candidates_guard on drink_explainer_candidates;
create trigger drink_explainer_candidates_guard before update or delete on drink_explainer_candidates
  for each row execute function drink_explainer_candidates_guard();

create or replace function drink_explainer_attempts_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '시도 기록은 삭제할 수 없습니다'); end if;
  if (new.attempt_id, new.candidate_id, new.slot_id, new.m, new.spec_hash, new.idempotency_key, new.approval_id, new.provider, new.created_at)
     is distinct from (old.attempt_id, old.candidate_id, old.slot_id, old.m, old.spec_hash, old.idempotency_key, old.approval_id, old.provider, old.created_at) then
    perform drinks_fail('immutable', '시도 키·사양·결재는 바꿀 수 없습니다');
  end if;
  if new.state is distinct from old.state and not (
       (old.state = 'requested' and new.state in ('generating','failed_unbilled'))
    or (old.state = 'generating' and new.state in ('received','failed_unbilled','failed_billed','unknown_billed'))
    or (old.state = 'received' and new.state in ('probed','failed_billed'))
    or (old.state = 'probed' and new.state in ('stored','failed_billed'))
    -- 조회로 정정하거나(요청 ID 가 있을 때), 운영자가 닫는다
    or (old.state = 'unknown_billed' and new.state in ('received','failed_unbilled','failed_billed','closed_billed','closed_void'))) then
    perform drinks_fail('invalid_state', '시도 상태를 ' || old.state || ' 에서 ' || new.state || ' 로 바꿀 수 없습니다');
  end if;
  if old.state in ('stored','failed_unbilled','failed_billed','closed_billed','closed_void')
     and (to_jsonb(new) - 'updated_at') is distinct from (to_jsonb(old) - 'updated_at') then
    perform drinks_fail('immutable', '끝난 시도는 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_explainer_attempts_guard on drink_explainer_attempts;
create trigger drink_explainer_attempts_guard before update or delete on drink_explainer_attempts
  for each row execute function drink_explainer_attempts_guard();

create or replace function drink_explainer_selections_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare c drink_explainer_candidates;
begin
  if tg_op <> 'INSERT' then perform drinks_fail('immutable', '선택 기록은 바꾸거나 지울 수 없습니다 — 다시 고르려면 새 제작안의 새 슬롯입니다'); end if;
  select * into c from drink_explainer_candidates where candidate_id = new.selected_candidate_id;
  if not found or c.slot_id <> new.slot_id then perform drinks_fail('ownership', '이 슬롯의 후보가 아닙니다'); end if;
  if c.status <> 'stored' or c.asset_id is null then perform drinks_fail('invalid_state', '파일이 저장된 후보만 고를 수 있습니다'); end if;
  if c.auto_verdict is distinct from 'pass' or c.human_verdict is distinct from 'pass' then
    perform drinks_fail('not_passed', '자동 합격 + 사람 합격인 후보만 고를 수 있습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_explainer_selections_guard on drink_explainer_selections;
create trigger drink_explainer_selections_guard before insert or update or delete on drink_explainer_selections
  for each row execute function drink_explainer_selections_guard();

-- ─────────────────────────────────────────────────────────────
-- 내부 도우미
-- ─────────────────────────────────────────────────────────────

-- 슬롯 상태는 앞으로만 간다. 선택·no_pass 뒤에는 움직이지 않는다.
create or replace function drink_explainer_slot_advance(p_slot text, p_to text) returns void language plpgsql set search_path = public, pg_temp as $$
declare flow text[] := array['pending','requested','received','probed','auto_checked','human_checked','selected'];
begin
  update drink_explainer_slots set status = p_to, updated_at = now()
   where slot_id = p_slot and status <> 'no_pass' and status <> 'selected'
     and (p_to = 'no_pass' or array_position(flow, p_to) > array_position(flow, status));
end $$;

-- 후보 비용 = 시도 실제 금액 합계.
create or replace function drink_explainer_candidate_settle(p_candidate text) returns void language plpgsql set search_path = public, pg_temp as $$
begin
  update drink_explainer_candidates c set updated_at = now(),
    cost_usd = coalesce((select sum(a.actual_usd) from drink_explainer_attempts a where a.candidate_id = c.candidate_id), 0)
   where c.candidate_id = p_candidate;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 함수
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_explainer_plan_slot(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid := drinks_uuid(p, 'plan_revision_id'); v_n int := drinks_int(p, 'n'); v_planned int := drinks_int(p, 'candidates_planned');
  v_slot text; s drink_explainer_slots;
begin
  if v_planned is null or v_planned < 1 or v_planned > (drinks_explainer_limits() ->> 'max_candidates_per_slot')::int then
    perform drinks_fail('invalid_input', '후보 수는 1 또는 2 입니다');
  end if;
  v_slot := v_plan::text || ':A' || v_n::text;
  select * into s from drink_explainer_slots where slot_id = v_slot;
  if found then
    if s.spec_hash <> drinks_text(p, 'spec_hash') then perform drinks_fail('immutable', '같은 슬롯에 다른 사양을 넣을 수 없습니다'); end if;
    return jsonb_build_object('slot_id', s.slot_id, 'existing', true);
  end if;
  insert into drink_explainer_slots (slot_id, plan_revision_id, n, role, spec_hash, min_src_ms, candidates_planned, boundary_in, boundary_out)
  values (v_slot, v_plan, v_n, drinks_text(p, 'role'), drinks_text(p, 'spec_hash'), drinks_int(p, 'min_src_ms'), v_planned,
          drinks_text(p, 'boundary_in'), drinks_text(p, 'boundary_out'));
  insert into drink_explainer_candidates (candidate_id, slot_id, k)
  select v_slot || '#c' || k::text, v_slot, k from generate_series(1, v_planned) k;
  return jsonb_build_object('slot_id', v_slot, 'existing', false,
    'candidate_ids', (select jsonb_agg(candidate_id order by k) from drink_explainer_candidates where slot_id = v_slot));
end $$;

-- 공급자 호출 전에 부른다. 돌려주는 idempotency_key 로 요청을 보낸다.
create or replace function drinks_explainer_open_attempt(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare c drink_explainer_candidates; s drink_explainer_slots; ap drink_spend_approvals; v_m int; v_id text; v_prev drink_explainer_attempts;
  lim jsonb := drinks_explainer_limits(); v_provider text := drinks_text(p, 'provider');
begin
  if v_provider is null then perform drinks_fail('invalid_input', 'provider 가 필요합니다'); end if;
  select * into c from drink_explainer_candidates where candidate_id = drinks_text(p, 'candidate_id') for update;
  if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
  select * into s from drink_explainer_slots where slot_id = c.slot_id for update;
  if s.status in ('selected','no_pass') then perform drinks_fail('invalid_state', '이 슬롯은 끝났습니다(' || s.status || ')'); end if;
  if c.status = 'stored' then perform drinks_fail('already_stored', '이 후보는 이미 파일이 있습니다 — 다시 사지 않습니다'); end if;
  select * into ap from drink_spend_approvals where id = drinks_uuid(p, 'approval_id');
  if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
  if ap.status <> 'open' then perform drinks_fail('approval_closed', '닫힌 결재로는 쓸 수 없습니다'); end if;
  if ap.expires_at <= now() then perform drinks_fail('approval_expired', '결재 기간이 지났습니다'); end if;
  if exists (select 1 from drink_explainer_attempts where candidate_id = c.candidate_id and state = 'unknown_billed') then
    perform drinks_fail('unknown_billed_open', '결과를 모르는 시도가 있습니다 — 조회로 정정하거나 billed/void 로 닫기 전에는 새 시도를 만들 수 없습니다');
  end if;
  if exists (select 1 from drink_explainer_attempts where candidate_id = c.candidate_id and state in ('requested','generating','received','probed')) then
    perform drinks_fail('attempt_open', '이 후보의 시도가 진행 중입니다');
  end if;
  select coalesce(max(m), 0) + 1 into v_m from drink_explainer_attempts where candidate_id = c.candidate_id;
  if v_m > (lim ->> 'max_attempts_per_candidate')::int then
    perform drinks_fail('attempt_cap', '후보당 시도 상한(' || (lim ->> 'max_attempts_per_candidate') || '회)에 닿았습니다');
  end if;
  if (select count(*) from drink_explainer_attempts where slot_id = c.slot_id) >= (lim ->> 'max_attempts_per_slot')::int then
    perform drinks_fail('attempt_cap', '슬롯당 시도 상한(' || (lim ->> 'max_attempts_per_slot') || '회)에 닿았습니다');
  end if;
  -- 돈이 나간 시도 뒤의 재시도는 새 결재 금액 안에서만(§3-3).
  select * into v_prev from drink_explainer_attempts where candidate_id = c.candidate_id order by m desc limit 1;
  if found and v_prev.state in ('failed_billed','closed_billed') and v_prev.approval_id = ap.id then
    perform drinks_fail('retry_needs_new_approval', '청구된 시도 뒤의 재시도는 새 결재로만 합니다');
  end if;
  v_id := c.candidate_id || '#a' || v_m::text;
  insert into drink_explainer_attempts (attempt_id, candidate_id, slot_id, m, spec_hash, idempotency_key, approval_id, provider)
  values (v_id, c.candidate_id, c.slot_id, v_m, s.spec_hash, drinks_explainer_idem(v_id, s.spec_hash), ap.id, v_provider);
  update drink_explainer_candidates set status = 'attempting', updated_at = now() where candidate_id = c.candidate_id;
  perform drink_explainer_slot_advance(c.slot_id, 'requested');
  return jsonb_build_object('attempt_id', v_id, 'm', v_m, 'idempotency_key', drinks_explainer_idem(v_id, s.spec_hash), 'spec_hash', s.spec_hash);
end $$;

-- 시도 상태 올리기. stored 면 asset_id 가 필요하다. 끝나면 후보 비용을 다시 더한다.
create or replace function drinks_explainer_attempt_event(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare a drink_explainer_attempts; v_to text := drinks_text(p, 'to_state'); v_asset uuid := drinks_uuid(p, 'asset_id', false);
begin
  select * into a from drink_explainer_attempts where attempt_id = drinks_text(p, 'attempt_id') for update;
  if not found then perform drinks_fail('not_found', '시도를 찾지 못했습니다'); end if;
  if v_to is null or v_to in ('closed_billed','closed_void') then perform drinks_fail('invalid_input', '닫기는 drinks_explainer_close_unknown 으로 합니다'); end if;
  if a.state = 'unknown_billed' and v_to = 'received' and coalesce(drinks_text(p, 'provider_request_id'), a.provider_request_id) is null then
    perform drinks_fail('invalid_input', '조회 정정에는 공급자 요청 ID 가 필요합니다');
  end if;
  if v_to = 'stored' and v_asset is null then perform drinks_fail('invalid_input', '저장 완료에는 asset_id 가 필요합니다'); end if;
  update drink_explainer_attempts set state = v_to, updated_at = now(),
    provider_request_id = coalesce(drinks_text(p, 'provider_request_id'), provider_request_id),
    hold_id = coalesce(drinks_uuid(p, 'hold_id', false), hold_id),
    billed_units = coalesce(nullif(p ->> 'billed_units', '')::numeric, billed_units),
    actual_usd = coalesce(nullif(p ->> 'actual_usd', '')::numeric, actual_usd),
    error_code = coalesce(drinks_text(p, 'error_code'), error_code)
   where attempt_id = a.attempt_id;
  if v_to in ('received','probed') then
    perform drink_explainer_slot_advance(a.slot_id, v_to);
  elsif v_to = 'stored' then
    update drink_explainer_candidates set status = 'stored', asset_id = v_asset, updated_at = now() where candidate_id = a.candidate_id;
    perform drink_explainer_slot_advance(a.slot_id, 'probed');
  elsif v_to in ('failed_unbilled','failed_billed') then
    update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = a.candidate_id;
  end if;
  perform drink_explainer_candidate_settle(a.candidate_id);
  return jsonb_build_object('attempt_id', a.attempt_id, 'state', v_to);
end $$;

-- unknown_billed 닫기: 운영자가 보고 billed(청구된 것으로) 또는 void(없던 일로). 자동으로 닫지 않는다.
create or replace function drinks_explainer_close_unknown(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare a drink_explainer_attempts; v_res text := drinks_text(p, 'resolution'); v_by text := drinks_text(p, 'closed_by'); v_note text := drinks_text(p, 'note');
  v_usd numeric := nullif(p ->> 'actual_usd', '')::numeric;
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
  return jsonb_build_object('attempt_id', a.attempt_id, 'state', 'closed_' || v_res);
end $$;

-- 워커가 죽은 시도를 정리한다: generating 에 멈춘 것 = 보냈는지 모름(unknown_billed), requested 에 멈춘 것 = 안 보냈음(failed_unbilled).
-- 다시 부르지 않는다.
create or replace function drinks_explainer_sweep_stale(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_sec int := coalesce(drinks_int(p, 'older_than_sec', false), 1800); v_unknown int; v_unbilled int; r record;
begin
  if v_sec < 60 then perform drinks_fail('invalid_input', 'older_than_sec 는 60 이상입니다'); end if;
  update drink_explainer_attempts set state = 'unknown_billed', updated_at = now(), error_code = coalesce(error_code, 'worker_lost')
   where state = 'generating' and updated_at < now() - make_interval(secs => v_sec);
  get diagnostics v_unknown = row_count;
  v_unbilled := 0;
  for r in select attempt_id, candidate_id from drink_explainer_attempts where state = 'requested' and updated_at < now() - make_interval(secs => v_sec) loop
    update drink_explainer_attempts set state = 'failed_unbilled', updated_at = now(), error_code = coalesce(error_code, 'worker_lost') where attempt_id = r.attempt_id;
    update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = r.candidate_id;
    v_unbilled := v_unbilled + 1;
  end loop;
  return jsonb_build_object('unknown_billed', v_unknown, 'failed_unbilled', v_unbilled);
end $$;

-- 후보 판정. 자동(auto_verdict)과 사람(human_verdict)은 따로 온다. 계획한 후보가 전부 불합격이면 슬롯은 no_pass.
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
  update drink_explainer_candidates set auto_verdict = coalesce(v_auto, auto_verdict), human_verdict = coalesce(v_human, human_verdict), updated_at = now()
   where candidate_id = c.candidate_id;
  select count(*) filter (where auto_verdict = 'fail' or human_verdict = 'fail'), count(*) filter (where human_verdict is not null)
    into v_failed, v_judged from drink_explainer_candidates where slot_id = c.slot_id;
  if v_failed >= s.candidates_planned then
    perform drink_explainer_slot_advance(c.slot_id, 'no_pass');
  elsif v_human is not null and v_judged >= s.candidates_planned then
    perform drink_explainer_slot_advance(c.slot_id, 'human_checked');
  elsif v_auto is not null then
    perform drink_explainer_slot_advance(c.slot_id, 'auto_checked');
  end if;
  return jsonb_build_object('candidate_id', c.candidate_id, 'slot_status', (select status from drink_explainer_slots where slot_id = c.slot_id));
end $$;

-- 사람이 고른다. 슬롯의 모든 후보가 사람 판정을 받은 뒤에만.
create or replace function drinks_explainer_select(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare s drink_explainer_slots; v_by text := drinks_text(p, 'selected_by'); v_reason text := drinks_text(p, 'reason');
begin
  if v_by is null or lower(v_by) in ('worker','system','auto') then perform drinks_fail('invalid_input', '사람만 고릅니다(selected_by)'); end if;
  if v_reason is null then perform drinks_fail('invalid_input', '고른 이유(reason)가 필요합니다'); end if;
  select * into s from drink_explainer_slots where slot_id = drinks_text(p, 'slot_id') for update;
  if not found then perform drinks_fail('not_found', '슬롯을 찾지 못했습니다'); end if;
  if s.status = 'no_pass' then perform drinks_fail('no_pass', '후보가 모두 불합격입니다 — 새 결재 재촬영 또는 계획 변경뿐입니다'); end if;
  if s.status = 'selected' then perform drinks_fail('invalid_state', '이미 골랐습니다'); end if;
  if s.status <> 'human_checked' then perform drinks_fail('invalid_state', '모든 후보의 사람 판정이 끝나야 고를 수 있습니다'); end if;
  insert into drink_explainer_selections (slot_id, selected_candidate_id, selected_by, reason)
  values (s.slot_id, drinks_text(p, 'candidate_id'), v_by, v_reason);
  perform drink_explainer_slot_advance(s.slot_id, 'selected');
  return jsonb_build_object('slot_id', s.slot_id, 'selected_candidate_id', drinks_text(p, 'candidate_id'));
end $$;

-- 재렌더·언어 추가가 다시 쓰는 유일한 길(§3-3). 선택이 없으면 빈 객체.
create or replace function drinks_explainer_selected_asset(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select coalesce((select jsonb_build_object('slot_id', x.slot_id, 'candidate_id', x.selected_candidate_id, 'asset_id', a.id, 'storage_key', a.storage_key,
      'sha256', a.sha256, 'width', a.width, 'height', a.height, 'duration_ms', a.duration_ms)
    from drink_explainer_selections x
    join drink_explainer_candidates c on c.candidate_id = x.selected_candidate_id
    join drink_media_assets a on a.id = c.asset_id and a.state = 'stored'
    where x.slot_id = drinks_text(p, 'slot_id')), '{}'::jsonb)
$$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0060 과 같은 방향: anon·authenticated 에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────

alter table drink_explainer_slots enable row level security;
alter table drink_explainer_candidates enable row level security;
alter table drink_explainer_attempts enable row level security;
alter table drink_explainer_selections enable row level security;

revoke all on table drink_explainer_slots, drink_explainer_candidates, drink_explainer_attempts, drink_explainer_selections from anon, authenticated;
grant select, insert, update on table drink_explainer_slots, drink_explainer_candidates, drink_explainer_attempts, drink_explainer_selections to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_explainer\_%' or p.proname like 'drink\_explainer\_%')
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;

-- 확인(적용 후):
--   select has_function_privilege('anon', 'public.drinks_explainer_open_attempt(jsonb)', 'EXECUTE');   → false
--   select has_table_privilege('anon', 'public.drink_explainer_attempts', 'SELECT');                   → false
