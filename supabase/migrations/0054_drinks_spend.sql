-- 주류 공장 — 유료 생성 결재·지출 잠금·생성 그림 재사용 (2026-10-24). docs/deviation-drinks-paid-pilot.md
--
-- 운영자 결정(2026-10-23): 예산을 한꺼번에 받지 않는다. 단계마다 작은 결재를 받고, **결재 금액이 곧 상한**이다.
--   drink_spend_approvals   결재 1건 = 단계·목적·상한(USD)·허용 종류(그림/영상)·운영자 말 원문. 열림 → 닫힘만
--   drink_spend_holds       유료 호출 1회 직전의 '가잡기'. 결재 행을 잠그고 (가잡기 + 확정 지출 + 이번 예상) ≤ 상한 일 때만 만든다.
--                           호출이 끝나면 확정(실제 금액) 또는 해제(실패 — 청구 없음). 확정은 임대가 없어도 받는다(돈은 이미 나갔다).
--   drink_generated_assets  산 그림·영상의 재사용 목록(프롬프트 해시 → 파일). 같은 그림을 두 번 사지 않는다.
--
-- ★ 워커가 가잡기 뒤에 죽으면 그 금액은 '가잡힘'으로 남아 상한을 계속 차지한다 — 틀리면 덜 쓰는 쪽으로 틀린다.
-- ★ 0053 의 drinks_request_render·drinks_start_render 를 다시 정의한다(유료 렌더는 열린 결재가 있어야만 큐에 들어간다).
-- ★ 0050 의 drinks_validate_plan 을 다시 정의한다 — 장면의 영어 그림·움직임 지시문(visual_prompt·motion_prompt)을 보존한다.
--
-- 되돌리기: 표 3개와 이 파일 함수를 drop 하고, drink_production_jobs.spend_approval_id 와 그 체크를 지운 뒤
--          0053 의 두 함수·0050 의 drinks_validate_plan 정의를 다시 실행한다.

create or replace function drinks_spend_limits() returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'max_cap_usd', 10,               -- 결재 1건 상한의 상한(실수로 0 하나 더 붙이는 것을 막는다)
    'max_days', 30,                  -- 결재 유효 기간 상한
    'max_attempts_per_item', 3,      -- 같은 항목(그림 1장)의 유료 시도 횟수 상한(실패 재시도 포함)
    -- 예상 금액 단가 — engine/config.py DRINKS_PAID_PRICES 와 같아야 한다(tests/test_drinks_paid.py 가 대조).
    'price_image_mechanism', 0.134,  -- 3D 도해(gemini-3-pro-image, 1K·2K)
    'price_image_reality', 0.039,    -- 실사(gemini-2.5-flash-image)
    'price_video_per_sec', 0.05      -- 움직이는 장면(veo-3.1-lite 720p)
  )
$$;

create table if not exists drink_spend_approvals (
  id               uuid primary key default gen_random_uuid(),
  stage            text not null check (length(stage) between 1 and 60),
  purpose          text not null check (length(purpose) between 1 and 500),
  cap_usd          numeric(10,4) not null check (cap_usd > 0 and cap_usd <= 10),
  allowed_kinds    text[] not null check (cardinality(allowed_kinds) > 0 and allowed_kinds <@ array['image','video']),
  plan_revision_id uuid references drink_plan_revisions(id),   -- 있으면 이 제작안에만 쓸 수 있다
  order_hash       text check (order_hash is null or order_hash ~ '^[0-9a-f]{64}$'),   -- 보여드린 주문서의 해시(감사용)
  approved_by      text not null check (length(approved_by) between 1 and 100),
  approver_words   text not null check (length(approver_words) between 1 and 500),     -- 결재권자의 말 원문
  status           text not null default 'open' check (status in ('open','closed')),
  expires_at       timestamptz not null,
  closed_at        timestamptz,
  close_reason     text check (close_reason is null or length(close_reason) <= 500),
  created_at       timestamptz not null default now(),
  check (status = 'open' or (closed_at is not null and close_reason is not null)),
  check (expires_at > created_at)
);
create index if not exists drink_spend_approvals_open_idx on drink_spend_approvals (status, created_at desc);

create table if not exists drink_spend_holds (
  id           uuid primary key default gen_random_uuid(),
  approval_id  uuid not null references drink_spend_approvals(id),
  job_id       uuid references drink_production_jobs(id),
  item_key     text not null check (length(item_key) between 1 and 200),   -- 주문서 항목(예: scene-02-mechanism)
  kind         text not null check (kind in ('image','video')),
  provider     text not null,
  model        text,
  est_usd      numeric(10,4) not null check (est_usd > 0),
  status       text not null default 'held' check (status in ('held','settled','released')),
  actual_usd   numeric(10,4) check (actual_usd is null or actual_usd >= 0),
  note         text check (note is null or length(note) <= 500),
  created_at   timestamptz not null default now(),
  settled_at   timestamptz,
  check ((status = 'held') = (settled_at is null)),
  check (status <> 'settled' or actual_usd is not null)
);
-- 같은 결재 안에서 같은 항목은 한 번만 산다(가잡기 중이거나 이미 산 것). 실패로 해제된 것만 다시 시도할 수 있다.
create unique index if not exists drink_spend_holds_item_uq on drink_spend_holds (approval_id, item_key)
  where status in ('held','settled');
create index if not exists drink_spend_holds_approval_idx on drink_spend_holds (approval_id, status);

create table if not exists drink_generated_assets (
  prompt_hash  text primary key check (prompt_hash ~ '^[0-9a-f]{64}$'),   -- 모델·프롬프트·참조 그림·규격의 해시
  kind         text not null check (kind in ('image','video')),
  model        text not null,
  asset_id     uuid not null references drink_media_assets(id),
  hold_id      uuid not null references drink_spend_holds(id),
  created_at   timestamptz not null default now()
);

alter table drink_production_jobs add column if not exists spend_approval_id uuid references drink_spend_approvals(id);
alter table drink_production_jobs drop constraint if exists drink_prod_paid_needs_approval;
alter table drink_production_jobs add constraint drink_prod_paid_needs_approval
  check ((renderer = 'paid') = (spend_approval_id is not null));

-- ─────────────────────────────────────────────────────────────
-- 불변 규칙
-- ─────────────────────────────────────────────────────────────

create or replace function drink_spend_approvals_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '결재 기록은 삭제할 수 없습니다'); end if;
  if (to_jsonb(new) - 'status' - 'closed_at' - 'close_reason') is distinct from (to_jsonb(old) - 'status' - 'closed_at' - 'close_reason') then
    perform drinks_fail('immutable', '결재 내용(상한·범위·말)은 바꿀 수 없습니다 — 닫고 새로 결재받으세요');
  end if;
  if old.status = 'closed' and to_jsonb(new) is distinct from to_jsonb(old) then
    perform drinks_fail('immutable', '닫힌 결재는 다시 열 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_spend_approvals_guard on drink_spend_approvals;
create trigger drink_spend_approvals_guard before update or delete on drink_spend_approvals
  for each row execute function drink_spend_approvals_guard();

create or replace function drink_spend_holds_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '지출 기록은 삭제할 수 없습니다'); end if;
  if old.status <> 'held' then perform drinks_fail('immutable', '확정·해제된 지출은 바꿀 수 없습니다'); end if;
  if (to_jsonb(new) - 'status' - 'actual_usd' - 'settled_at' - 'note') is distinct from
     (to_jsonb(old) - 'status' - 'actual_usd' - 'settled_at' - 'note') then
    perform drinks_fail('immutable', '지출 항목·예상 금액은 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_spend_holds_guard on drink_spend_holds;
create trigger drink_spend_holds_guard before update or delete on drink_spend_holds
  for each row execute function drink_spend_holds_guard();

drop trigger if exists drink_generated_append_only on drink_generated_assets;
create trigger drink_generated_append_only before update or delete on drink_generated_assets
  for each row execute function drink_append_only_guard();

-- ─────────────────────────────────────────────────────────────
-- 헬퍼
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_num(p jsonb, k text) returns numeric language plpgsql as $$
declare v text := drinks_text(p, k);
begin
  if v is null then perform drinks_fail('invalid_input', k || ' 가 필요합니다'); end if;
  begin
    return v::numeric;
  exception when invalid_text_representation then
    perform drinks_fail('invalid_input', k || ' 는 숫자여야 합니다');
  end;
  return null;
end $$;

-- 결재 1건의 지금 상태. 남은 금액 = 상한 − (가잡힌 예상 + 확정된 실제).
create or replace function drinks_spend_totals(p_approval uuid) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'held_usd', coalesce(sum(est_usd) filter (where status = 'held'), 0),
    'spent_usd', coalesce(sum(actual_usd) filter (where status = 'settled'), 0),
    'holds', count(*) filter (where status = 'held'),
    'settled', count(*) filter (where status = 'settled'),
    'released', count(*) filter (where status = 'released'))
  from drink_spend_holds where approval_id = p_approval
$$;

create or replace function drinks_spend_view(a drink_spend_approvals) returns jsonb language sql stable as $$
  select jsonb_build_object('approval_id', a.id, 'stage', a.stage, 'purpose', a.purpose, 'cap_usd', a.cap_usd,
    'allowed_kinds', to_jsonb(a.allowed_kinds), 'plan_revision_id', a.plan_revision_id, 'order_hash', a.order_hash, 'status', a.status,
    'expired', a.expires_at <= now(), 'expires_at', a.expires_at,
    'remaining_usd', a.cap_usd - ((t ->> 'held_usd')::numeric + (t ->> 'spent_usd')::numeric)) || t
  from (select drinks_spend_totals(a.id) t) x
$$;

-- 이 제작안을 유료로 한 번 렌더할 때 새로 드는 예상 금액(그림만). 정리 카드는 로컬로 그리므로 0.
-- 이 제작안 버전으로 이미 산 장면도 0 — 승인된 제작안은 바뀌지 않으므로 같은 그림을 다시 쓴다(engine/drinks_paid.py).
--   항목 이름 'scene-NN-역할' 은 engine/drinks_paid.image_item 과 같아야 한다(tests/test_drinks_paid.py 가 대조).
--   시험 스크립트로(제작 작업 없이) 산 그림은 여기서 모른다 — 그만큼 예상이 실제보다 크게(안전한 쪽으로) 나온다.
create or replace function drinks_estimate_render(p_plan uuid) returns jsonb language sql stable as $$
  with sc as (
    select (e.ord)::int as position, coalesce(nullif(e.s ->> 'visual_role', ''), 'reality') as role
    from drink_plan_revisions pl, jsonb_array_elements(coalesce(pl.plan_json -> 'scenes', '[]')) with ordinality e(s, ord)
    where pl.id = p_plan and pl.format = 'video'
  ), priced as (
    select position, role,
      exists (select 1 from drink_spend_holds h join drink_production_jobs j on j.id = h.job_id
        where j.plan_revision_id = p_plan and h.status = 'settled'
          and h.item_key = 'scene-' || lpad(sc.position::text, 2, '0') || '-' || sc.role) as bought,
      case role when 'text_card' then 0
        when 'mechanism' then (drinks_spend_limits() ->> 'price_image_mechanism')::numeric
        else (drinks_spend_limits() ->> 'price_image_reality')::numeric end as price
    from sc
  ), est as (
    select position, role, bought, price, case when bought then 0 else price end as usd from priced
  )
  select jsonb_build_object('scenes', coalesce(jsonb_agg(jsonb_build_object('position', position, 'role', role, 'usd', usd,
      'bought', bought, 'price_usd', price) order by position), '[]'),
    'images', count(*) filter (where usd > 0), 'bought', count(*) filter (where bought), 'total_usd', coalesce(sum(usd), 0))
  from est
$$;

-- ─────────────────────────────────────────────────────────────
-- 결재 (운영자 — 화면은 운영자 키 게이트 뒤)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_open_spend_approval(p jsonb) returns jsonb language plpgsql as $$
declare a drink_spend_approvals; v_cap numeric := drinks_num(p, 'cap_usd'); v_days int := coalesce(drinks_int(p, 'days', false), 7);
  v_kinds text[] := drinks_text_array(p -> 'allowed_kinds'); v_plan uuid := drinks_uuid(p, 'plan_revision_id', false);
begin
  if v_cap <= 0 or v_cap > (drinks_spend_limits() ->> 'max_cap_usd')::numeric then
    perform drinks_fail('invalid_input', '결재 상한은 0 보다 크고 $' || (drinks_spend_limits() ->> 'max_cap_usd') || ' 이하여야 합니다');
  end if;
  if v_days < 1 or v_days > (drinks_spend_limits() ->> 'max_days')::int then
    perform drinks_fail('invalid_input', '결재 유효 기간은 1~' || (drinks_spend_limits() ->> 'max_days') || '일입니다');
  end if;
  if v_kinds is null or cardinality(v_kinds) = 0 or not (v_kinds <@ array['image','video']) then
    perform drinks_fail('invalid_input', '허용 종류는 image·video 중에서 고르세요');
  end if;
  if drinks_text(p, 'approver_words') is null then
    perform drinks_fail('invalid_input', '결재권자의 말(승인 문장)을 그대로 적으세요');
  end if;
  if v_plan is not null and not exists (select 1 from drink_plan_revisions where id = v_plan) then
    perform drinks_fail('not_found', '제작안을 찾지 못했습니다');
  end if;
  insert into drink_spend_approvals (stage, purpose, cap_usd, allowed_kinds, plan_revision_id, order_hash, approved_by, approver_words, expires_at)
  values (coalesce(drinks_text(p, 'stage'), ''), coalesce(drinks_text(p, 'purpose'), ''), v_cap, v_kinds, v_plan,
    drinks_text(p, 'order_hash'), coalesce(drinks_text(p, 'approved_by'), 'operator'), drinks_text(p, 'approver_words'),
    now() + make_interval(days => v_days))
  returning * into a;
  if v_plan is not null then
    perform drinks_log((select topic_id from drink_plan_revisions where id = v_plan), 'plan', v_plan, 'spend_approved', null, 'open',
      a.id::text, a.approver_words, jsonb_build_object('stage', a.stage, 'cap_usd', a.cap_usd, 'kinds', to_jsonb(a.allowed_kinds)));
  end if;
  return drinks_spend_view(a);
end $$;

create or replace function drinks_close_spend_approval(p jsonb) returns jsonb language plpgsql as $$
declare a drink_spend_approvals;
begin
  select * into a from drink_spend_approvals where id = drinks_uuid(p, 'approval_id') for update;
  if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
  if a.status = 'closed' then return drinks_spend_view(a); end if;
  if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '닫는 이유를 적으세요'); end if;
  update drink_spend_approvals set status = 'closed', closed_at = now(), close_reason = drinks_text(p, 'reason')
    where id = a.id returning * into a;
  return drinks_spend_view(a);
end $$;

create or replace function drinks_spend_state(p jsonb) returns jsonb language plpgsql as $$
declare a drink_spend_approvals;
begin
  select * into a from drink_spend_approvals where id = drinks_uuid(p, 'approval_id');
  if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
  return drinks_spend_view(a);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 지출 (워커·시험 스크립트 — service_role)
-- ─────────────────────────────────────────────────────────────

-- 유료 호출 직전. 결재 행을 잠그고 남은 금액 안일 때만 가잡는다(동시에 두 워커가 와도 합계가 상한을 넘지 못한다).
create or replace function drinks_hold_spend(p jsonb) returns jsonb language plpgsql as $$
declare a drink_spend_approvals; j drink_production_jobs; h drink_spend_holds; t jsonb; v_est numeric := drinks_num(p, 'est_usd');
  v_kind text := drinks_text(p, 'kind'); v_item text := drinks_text(p, 'item_key'); v_tries int; v_committed numeric;
begin
  if v_est <= 0 then perform drinks_fail('invalid_input', '예상 금액은 0 보다 커야 합니다'); end if;
  if v_item is null then perform drinks_fail('invalid_input', 'item_key 가 필요합니다'); end if;
  if drinks_uuid(p, 'job_id', false) is not null then
    j := drinks_lock_prod_job(p);   -- 임대를 가진 워커만 새 돈을 쓴다
  end if;
  select * into a from drink_spend_approvals where id = drinks_uuid(p, 'approval_id') for update;
  if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
  if a.status <> 'open' then perform drinks_fail('approval_closed', '닫힌 결재로는 쓸 수 없습니다'); end if;
  if a.expires_at <= now() then perform drinks_fail('approval_expired', '결재 기간이 지났습니다 — 새로 결재받으세요'); end if;
  if v_kind is null or not (v_kind = any(a.allowed_kinds)) then
    perform drinks_fail('kind_not_approved', '이 결재는 ' || array_to_string(a.allowed_kinds, '·') || ' 만 허용합니다');
  end if;
  if j.id is not null then
    if j.spend_approval_id is distinct from a.id then
      perform drinks_fail('ownership', '이 제작 작업은 다른 결재로 요청됐습니다');
    end if;
  end if;
  if a.plan_revision_id is not null and j.id is not null and j.plan_revision_id <> a.plan_revision_id then
    perform drinks_fail('ownership', '이 결재는 다른 제작안 전용입니다');
  end if;
  if exists (select 1 from drink_spend_holds where approval_id = a.id and item_key = v_item and status = 'settled') then
    perform drinks_fail('already_bought', '이 결재로 이미 산 항목입니다 — 저장된 것을 다시 쓰세요: ' || v_item);
  end if;
  if exists (select 1 from drink_spend_holds where approval_id = a.id and item_key = v_item and status = 'held') then
    perform drinks_fail('hold_in_progress', '같은 항목을 다른 곳에서 사는 중입니다: ' || v_item);
  end if;
  select count(*) into v_tries from drink_spend_holds where approval_id = a.id and item_key = v_item;
  if v_tries >= (drinks_spend_limits() ->> 'max_attempts_per_item')::int then
    perform drinks_fail('retry_limit', '같은 항목의 유료 시도가 ' || v_tries || '번입니다 — 멈추고 보고하세요: ' || v_item);
  end if;
  t := drinks_spend_totals(a.id);
  v_committed := (t ->> 'held_usd')::numeric + (t ->> 'spent_usd')::numeric;
  if v_committed + v_est > a.cap_usd then
    perform drinks_fail('budget_exceeded', '결재 금액을 넘습니다(상한 $' || a.cap_usd || ', 이미 $' || v_committed || ', 이번 $' || v_est || ')',
      jsonb_build_object('cap_usd', a.cap_usd, 'committed_usd', v_committed, 'requested_usd', v_est));
  end if;
  insert into drink_spend_holds (approval_id, job_id, item_key, kind, provider, model, est_usd, note)
  values (a.id, j.id, v_item, v_kind, coalesce(drinks_text(p, 'provider'), 'unknown'), drinks_text(p, 'model'), v_est,
    left(drinks_text(p, 'note'), 500))
  returning * into h;
  return jsonb_build_object('hold_id', h.id, 'remaining_usd', a.cap_usd - v_committed - v_est);
end $$;

-- 호출 끝. 성공 = 확정(실제 금액), 실패 = 해제(청구 없음). 임대를 잃었어도 받는다 — 나간 돈은 기록돼야 한다.
create or replace function drinks_settle_spend(p jsonb) returns jsonb language plpgsql as $$
declare h drink_spend_holds; v_outcome text := drinks_text(p, 'outcome');
begin
  select * into h from drink_spend_holds where id = drinks_uuid(p, 'hold_id') for update;
  if not found then perform drinks_fail('not_found', '지출 기록을 찾지 못했습니다'); end if;
  if h.status <> 'held' then
    perform drinks_fail('invalid_state', '이미 ' || case h.status when 'settled' then '확정' else '해제' end || '된 지출입니다');
  end if;
  if v_outcome = 'settled' then
    update drink_spend_holds set status = 'settled', actual_usd = drinks_num(p, 'actual_usd'), settled_at = now(),
      note = coalesce(left(drinks_text(p, 'note'), 500), note) where id = h.id returning * into h;
  elsif v_outcome = 'released' then
    update drink_spend_holds set status = 'released', settled_at = now(), note = coalesce(left(drinks_text(p, 'note'), 500), note)
      where id = h.id returning * into h;
  else
    perform drinks_fail('invalid_input', 'outcome 은 settled 또는 released 입니다');
  end if;
  return jsonb_build_object('hold_id', h.id, 'status', h.status) || drinks_spend_view((select a from drink_spend_approvals a where a.id = h.approval_id));
end $$;

-- 산 파일을 등록하고 재사용 목록에 올린다. 확정된 지출에만 붙는다(돈을 안 낸 파일이 '산 것'으로 둔갑하지 않게).
create or replace function drinks_register_generated(p jsonb) returns jsonb language plpgsql as $$
declare h drink_spend_holds; a jsonb := p -> 'asset'; x drink_media_assets; g drink_generated_assets;
begin
  select * into h from drink_spend_holds where id = drinks_uuid(p, 'hold_id');
  if not found then perform drinks_fail('not_found', '지출 기록을 찾지 못했습니다'); end if;
  if h.status <> 'settled' then perform drinks_fail('invalid_state', '확정된 지출의 파일만 등록합니다'); end if;
  select * into g from drink_generated_assets where prompt_hash = drinks_text(p, 'prompt_hash');
  if found then
    return jsonb_build_object('asset_id', g.asset_id, 'existing', true);
  end if;
  select * into x from drink_media_assets where storage_key = drinks_text(a, 'storage_key');
  if found then
    if x.sha256 <> drinks_text(a, 'sha256') then
      perform drinks_fail('immutable', '같은 저장 위치에 다른 내용을 올릴 수 없습니다 — 새 위치를 쓰세요');
    end if;
  else
    insert into drink_media_assets (storage_key, sha256, mime, bytes, width, height, duration_ms, rights, provenance, job_id)
    values (drinks_text(a, 'storage_key'), drinks_text(a, 'sha256'), drinks_text(a, 'mime'), (a ->> 'bytes')::bigint,
      drinks_int(a, 'width', false), drinks_int(a, 'height', false), drinks_int(a, 'duration_ms', false), 'generated_paid',
      coalesce(case when jsonb_typeof(a -> 'provenance') = 'object' then a -> 'provenance' end, '{}'), h.job_id)
    returning * into x;
  end if;
  insert into drink_generated_assets (prompt_hash, kind, model, asset_id, hold_id)
  values (drinks_text(p, 'prompt_hash'), h.kind, coalesce(h.model, 'unknown'), x.id, h.id);
  return jsonb_build_object('asset_id', x.id, 'existing', false);
end $$;

create or replace function drinks_find_generated(p jsonb) returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(jsonb_build_object('prompt_hash', g.prompt_hash, 'kind', g.kind, 'model', g.model, 'asset_id', a.id,
      'storage_key', a.storage_key, 'sha256', a.sha256, 'mime', a.mime, 'state', a.state)), '[]')
  from drink_generated_assets g join drink_media_assets a on a.id = g.asset_id
  where g.prompt_hash in (select jsonb_array_elements_text(coalesce(p -> 'prompt_hashes', '[]'))) and a.state = 'stored'
$$;

-- ─────────────────────────────────────────────────────────────
-- 0053 재정의: 유료 렌더는 열린 결재가 있어야 큐에 들어간다
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_request_render(p jsonb) returns jsonb language plpgsql as $$
declare pl drink_plan_revisions; rv drink_topic_reviews; j drink_production_jobs; v_block text; v_input text;
  v_attempt int; prev drink_production_jobs; v_paid boolean := coalesce((p ->> 'paid')::boolean, false);
  ap drink_spend_approvals; v_est jsonb; v_view jsonb;
begin
  perform drinks_reap_prod_jobs();
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  v_block := drinks_plan_renderable(pl.id);
  if v_block is not null then
    perform drinks_fail(case v_block when 'not_found' then 'not_found' else 'not_renderable' end,
      case v_block when 'not_found' then '제작안을 찾지 못했습니다'
        when 'plan_not_approved' then '승인된 제작안만 렌더합니다'
        when 'plan_blocked' then '차단된 제작안입니다(근거 철회·권리 변경)'
        else '이 제작안이 쓴 근거를 지금은 쓸 수 없습니다' end);
  end if;
  if v_paid then
    if pl.format <> 'video' then perform drinks_fail('paid_disabled', '유료 생성은 영상 제작안에만 씁니다(카드는 영상 그림을 재사용)'); end if;
    if drinks_uuid(p, 'spend_approval_id', false) is null then
      perform drinks_fail('paid_disabled', '유료 렌더는 결재가 있어야 합니다 — 결재 금액 안에서만 그림을 삽니다');
    end if;
    select * into ap from drink_spend_approvals where id = drinks_uuid(p, 'spend_approval_id') for share;
    if not found then perform drinks_fail('not_found', '결재를 찾지 못했습니다'); end if;
    if ap.status <> 'open' or ap.expires_at <= now() then perform drinks_fail('approval_closed', '열린 결재가 아닙니다'); end if;
    if not ('image' = any(ap.allowed_kinds)) then perform drinks_fail('kind_not_approved', '이 결재는 그림 생성을 허용하지 않습니다'); end if;
    if ap.plan_revision_id is distinct from pl.id then
      perform drinks_fail('ownership', '렌더 결재는 그 제작안 전용이어야 합니다');
    end if;
    -- 발주 전 예상 금액 > 남은 금액이면 큐에 넣지 않는다. 실제로 막는 것은 호출마다의 가잡기(drinks_hold_spend)다.
    v_est := drinks_estimate_render(pl.id);
    v_view := drinks_spend_view(ap);
    if (v_est ->> 'total_usd')::numeric > (v_view ->> 'remaining_usd')::numeric then
      perform drinks_fail('budget_insufficient', '예상 $' || (v_est ->> 'total_usd') || ' 가 남은 결재 금액 $' || (v_view ->> 'remaining_usd') || ' 보다 큽니다',
        jsonb_build_object('estimate', v_est, 'approval', v_view));
    end if;
  end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_input := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|' ||
    (drinks_production_limits() ->> 'renderer_version') || '|' || case when v_paid then 'paid|' || ap.id::text else 'local' end, 'UTF8')), 'hex');
  select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
    and status in ('queued','running');
  if found then
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);   -- 중복 요청은 같은 작업
  end if;
  if drinks_uuid(p, 'retry_of', false) is not null then
    select * into prev from drink_production_jobs where id = drinks_uuid(p, 'retry_of') and plan_revision_id = pl.id;
    if not found or prev.status not in ('failed','canceled') then
      perform drinks_fail('invalid_state', '실패·취소된 같은 제작안의 작업만 재시도합니다');
    end if;
  end if;
  v_attempt := 1 + (select count(*) from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input);
  begin
    insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, retry_of, input_hash, plan_hash,
      review_hash, renderer, renderer_version, requested_by, spend_approval_id)
    values (pl.topic_id, pl.id, pl.format, v_attempt, prev.id, v_input, pl.approved_hash, rv.approved_hash,
      case when v_paid then 'paid' else 'local' end, drinks_production_limits() ->> 'renderer_version', 'operator', ap.id)
    returning * into j;
  exception when unique_violation then
    select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
      and status in ('queued','running');
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);
  end;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', pl.format, 'attempt_no', j.attempt_no, 'renderer', j.renderer, 'spend_approval_id', ap.id,
      'estimate_usd', v_est -> 'total_usd'));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', false, 'attempt_no', j.attempt_no,
    'renderer', j.renderer, 'estimate', v_est);
end $$;

create or replace function drinks_start_render(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs; pl drink_plan_revisions; rv drink_topic_reviews; t drink_topics; v_block text; v_reaped int;
  ap drink_spend_approvals;
begin
  v_reaped := drinks_reap_prod_jobs();
  loop
    select * into j from drink_production_jobs where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    -- 대기 중에 근거가 철회·만료됐거나 제작안이 차단됐으면 돌리지 않는다(비용을 쓰기 전에 멈춘다).
    v_block := drinks_plan_renderable(j.plan_revision_id);
    select * into pl from drink_plan_revisions where id = j.plan_revision_id;
    if v_block is null and pl.approved_hash is distinct from j.plan_hash then v_block := 'plan_changed'; end if;
    -- 유료 작업은 결재가 지금도 열려 있어야 시작한다(대기 중에 결재가 닫히면 돈을 쓰지 않는다).
    if v_block is null and j.renderer = 'paid' then
      select * into ap from drink_spend_approvals where id = j.spend_approval_id;
      if ap.status <> 'open' or ap.expires_at <= now() then v_block := 'approval_closed'; end if;
    end if;
    if v_block is not null then
      update drink_production_jobs set status = 'canceled', finished_at = now(), error_code = v_block,
        error_message = '대기 중에 제작안·근거·결재가 바뀌어 렌더하지 않았습니다(' || v_block || ')' where id = j.id;
      continue;
    end if;
    update drink_production_jobs set status = 'running', lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => (drinks_production_limits() ->> 'lease_sec')::int),
      heartbeat_at = now(), started_at = now(), worker_id = coalesce(drinks_text(p, 'worker_id'), 'worker')
      where id = j.id returning * into j;
    select * into rv from drink_topic_reviews where id = pl.topic_review_id;
    select * into t from drink_topics where id = j.topic_id;
    return jsonb_build_object('reaped', v_reaped, 'job', jsonb_build_object(
      'job_id', j.id, 'lease_token', j.lease_token, 'format', j.format, 'attempt_no', j.attempt_no, 'input_hash', j.input_hash,
      'renderer', j.renderer, 'spend_approval_id', j.spend_approval_id,
      'renderer_version', j.renderer_version, 'plan_revision_id', pl.id, 'plan', pl.plan_json, 'revision_no', pl.revision_no,
      'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'categories', to_jsonb(t.categories)),
      'brief', rv.brief, 'claims', rv.evidence_pack -> 'claims',
      'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher,
          'url', s.canonical_url, 'published_at', s.published_at))
        from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
          from jsonb_array_elements(rv.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]')));
  end loop;
end $$;

-- 0050 재정의: 장면의 visual_prompt·motion_prompt 를 버리지 않는다(나머지 검사는 0050 과 같다).
create or replace function drinks_validate_plan(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql as $$
declare
  core text[] := drinks_text_array(p_review.brief -> 'selected_claim_ids');
  all_claims text[] := array(select x ->> 'claim_id' from jsonb_array_elements(p_review.evidence_pack -> 'claims') x);
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; out jsonb := '[]'; i int := 0; cids text[]; cid text; v_role text; v_kind text; n int;
begin
  if p_plan is null or jsonb_typeof(p_plan -> k) is distinct from 'array' then
    perform drinks_fail('invalid_plan', case k when 'scenes' then '영상 제작안에는 장면(scenes) 배열이 필요합니다'
      else '카드뉴스 제작안에는 페이지(pages) 배열이 필요합니다' end);
  end if;
  n := jsonb_array_length(p_plan -> k);
  if n = 0 then perform drinks_fail('invalid_plan', '장면·페이지가 하나 이상 있어야 합니다'); end if;
  if n > 40 then perform drinks_fail('invalid_plan', '장면·페이지는 40개까지입니다'); end if;
  for el in select * from jsonb_array_elements(p_plan -> k) loop
    i := i + 1;
    if jsonb_typeof(el) <> 'object' then perform drinks_fail('invalid_plan', i || '번 항목 형식이 잘못됐습니다'); end if;
    if el ? 'claim_ids' and jsonb_typeof(el -> 'claim_ids') not in ('array','null') then
      perform drinks_fail('invalid_plan', i || '번 항목 claim_ids 는 배열이어야 합니다');
    end if;
    cids := drinks_text_array(el -> 'claim_ids');
    foreach cid in array cids loop
      if not cid = any(all_claims) then
        perform drinks_fail('plan_claim_unknown', i || '번 항목의 ' || cid || ' 는 이 근거 버전에 없는 주장입니다');
      end if;
      if not cid = any(core) then
        perform drinks_fail('plan_claim_not_core', i || '번 항목이 승인 근거의 핵심 주장이 아닌 ' || cid || ' 를 씁니다');
      end if;
    end loop;
    if p_format = 'video' then
      if drinks_text(el, 'narration') is null then perform drinks_fail('invalid_plan', i || '번 장면에 나레이션이 없습니다'); end if;
      v_role := coalesce(drinks_text(el, 'visual_role'), 'reality');
      if v_role not in ('reality','mechanism','text_card','other') then
        perform drinks_fail('invalid_plan', i || '번 장면의 화면 역할이 잘못됐습니다');
      end if;
      v_kind := coalesce(drinks_text(el, 'content_kind'), 'fact');
      if v_kind not in ('fact','transition') then
        perform drinks_fail('invalid_plan', i || '번 장면 내용 종류는 사실 설명(fact) 또는 도입·전환·마무리(transition)입니다');
      end if;
      if el ? 'timing_sec' and el -> 'timing_sec' <> 'null'::jsonb
          and (jsonb_typeof(el -> 'timing_sec') <> 'number' or (el ->> 'timing_sec')::numeric <= 0
               or (el ->> 'timing_sec')::numeric > 60) then
        perform drinks_fail('invalid_plan', i || '번 장면 길이는 0초 초과 60초 이하 숫자여야 합니다');
      end if;
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'narration', drinks_text(el, 'narration'), 'visual_role', v_role, 'content_kind', v_kind,
        'explanation', drinks_text(el, 'explanation'), 'claim_ids', to_jsonb(cids),
        'timing_sec', case when jsonb_typeof(el -> 'timing_sec') = 'number' then el -> 'timing_sec' end,
        'continuity', drinks_text(el, 'continuity'), 'overlays', drinks_text(el, 'overlays'),
        -- 0054: 유료 그림 주문에 쓰는 영어 지시문(그림·움직임). 화면에 나가는 글이 아니다 — 사실 주장은 나레이션·근거가 진다.
        'visual_prompt', left(drinks_text(el, 'visual_prompt'), 1500), 'motion_prompt', left(drinks_text(el, 'motion_prompt'), 600)));
    else
      if el ? 'position' and el -> 'position' <> 'null'::jsonb and el ->> 'position' <> i::text then
        perform drinks_fail('invalid_plan', '페이지 순서는 1부터 빈칸·중복 없이 이어져야 합니다(' || i || '번째)');
      end if;
      v_role := drinks_text(el, 'role');
      if v_role is null or v_role not in ('cover','explain','compare','checklist','source') then
        perform drinks_fail('invalid_plan', i || '번 페이지 역할이 잘못됐습니다');
      end if;
      if drinks_text(el, 'heading') is null then perform drinks_fail('invalid_plan', i || '번 페이지 제목이 없습니다'); end if;
      out := out || jsonb_build_array(jsonb_build_object(
        'position', i, 'role', v_role, 'heading', drinks_text(el, 'heading'),
        'body', drinks_text(el, 'body'), 'graphic_spec', drinks_text(el, 'graphic_spec'),
        'claim_ids', to_jsonb(cids)));
    end if;
  end loop;
  if p_format = 'video' then
    return jsonb_build_object('scenes', out, 'notes', drinks_text(p_plan, 'notes'));
  end if;
  return jsonb_build_object('pages', out, 'notes', drinks_text(p_plan, 'notes'),
    'template_version', coalesce(drinks_text(p_plan, 'template_version'), 'card-v1'));
end $$;

-- 화면용: 이 제작안의 유료 예상·열린 결재.
create or replace function drinks_plan_spend(p jsonb) returns jsonb language sql stable as $$
  select jsonb_build_object('estimate', drinks_estimate_render(drinks_uuid(p, 'plan_revision_id')),
    'approvals', coalesce((select jsonb_agg(drinks_spend_view(a) order by a.created_at desc) from drink_spend_approvals a
      where a.plan_revision_id = drinks_uuid(p, 'plan_revision_id')), '[]'))
$$;

-- ─────────────────────────────────────────────────────────────
-- 권한 — service_role 만. 브라우저(anon)는 읽지도 쓰지도 못한다
-- ─────────────────────────────────────────────────────────────

alter table drink_spend_approvals enable row level security;
alter table drink_spend_holds enable row level security;
alter table drink_generated_assets enable row level security;
revoke all on table drink_spend_approvals, drink_spend_holds, drink_generated_assets from anon, authenticated;
grant select, insert, update on table drink_spend_approvals, drink_spend_holds, drink_generated_assets to service_role;

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
  end loop;
end $$;
