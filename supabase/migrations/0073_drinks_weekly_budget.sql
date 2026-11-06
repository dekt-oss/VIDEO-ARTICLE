-- 주류 — AI 초안 주간 한도(고정 $5, [+$1] 증액) (2026-11-06, 운영자 지시)
--
-- ★ 운영자 지시 원문(2026-11-06): "결재문장칸 없애. 결재등록도 안되네. 그냥 주간한도는 5달러로 고정시키고 그냥 그걸 보여주기만해줘.
--   대신 한도증액 버튼을 따로 만들어서 증액누르면 1달러씩 올라가는걸로합시다. 대신 누적사용액 보여주게할수있어?"
--
-- 무엇이 바뀌나 — 왜
--   A. 개발 결재(drink_develop_budgets)를 화면에서 손으로 여는 대신, 이번 주(서울 기준 월요일 0시 ~ 다음 월요일 0시) 한도 한 줄을
--      자동으로 만든다(drinks_ensure_weekly_budget). 기본 $5. 같은 주에 두 줄이 생기지 않게 stage='weekly:<월요일>' 고유 색인.
--      ※ 손으로 여는 경로(drinks_open_develop_budget)는 그대로 남는다 — 옛 화면이 쓴다. 다만 그 화면은 purpose 를 보내지 않아
--        0060 의 length(purpose) >= 1 검사에 걸려 등록이 실패했다(운영자가 겪은 "결재등록도 안되네"의 원인). 여기서 빈 목적을 채우도록 고친다.
--   B. [한도 +$1] (drinks_raise_weekly_budget): 이번 주 한 줄의 상한을 $1 올린다. 0060 의 불변 규칙(결재 내용은 못 바꾼다)은 그대로 두고,
--      이 함수 안에서만 **올리기**를 허용한다(트랜잭션 지역 설정 drinks.raise_weekly). 내리기·기간 변경·다른 결재 변경은 여전히 막힌다.
--      상한의 상한은 0060 표 검사 그대로 $10. 올린 기록은 drink_develop_budget_raises 에 남는다(지울 수 없다).
--   C. 화면이 보여 줄 숫자: 이번 주 한도·사용(정산)·잡아 둔 금액·남은 금액, 그리고 **누적 사용액**(지금까지 정산된 전체 합).
--
-- 안전 장치 — 약해지는 것이 없다
--   · 돈은 여전히 요청마다 가잡기(hold) → 정산 순서로만 나간다. 한도는 상한일 뿐이고 이 파일은 돈을 쓰지 않는다.
--   · 요청 1건 상한(max_usd_per_request $0.5)·호출 횟수 상한은 그대로.
--   · 쓰기 함수 둘 다 service_role 전용(아래 반복문). 웹은 운영자 키 게이트를 통과한 /api/drinks 로만 부른다.
--
-- 되돌리기:
--   drop function drinks_raise_weekly_budget(jsonb); drop function drinks_ensure_weekly_budget(jsonb); drop function drinks_weekly_budget_json(uuid);
--   drop table drink_develop_budget_raises; drop index drink_develop_budgets_weekly_uq;
--   0060 의 drink_develop_budgets_guard·drinks_open_develop_budget 를 다시 실행한다. 이미 만든 주간 한도 줄은 그대로 남는다(닫으려면 drinks_close_develop_budget).

create table if not exists drink_develop_budget_raises (
  id          bigint generated always as identity primary key,
  budget_id   uuid not null references drink_develop_budgets(id),
  from_cap    numeric(10,4) not null,
  to_cap      numeric(10,4) not null check (to_cap > from_cap),
  actor       text not null default 'operator',
  created_at  timestamptz not null default now()
);

create or replace function drink_develop_budget_raises_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  perform drinks_fail('immutable', '한도 증액 기록은 바꾸거나 지울 수 없습니다');
  return null;
end $$;
drop trigger if exists drink_develop_budget_raises_guard on drink_develop_budget_raises;
create trigger drink_develop_budget_raises_guard before update or delete on drink_develop_budget_raises
  for each row execute function drink_develop_budget_raises_guard();

create unique index if not exists drink_develop_budgets_weekly_uq on drink_develop_budgets (stage) where stage like 'weekly:%';

-- 0060 불변 규칙 + 예외 하나: drinks_raise_weekly_budget 안에서(drinks.raise_weekly='on') 열린 주간 한도의 cap_usd 를 **올리는 것**만.
create or replace function drink_develop_budgets_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '결재 기록은 삭제할 수 없습니다'); end if;
  if coalesce(current_setting('drinks.raise_weekly', true), '') = 'on'
     and old.status = 'open' and old.stage like 'weekly:%' and new.cap_usd > old.cap_usd
     and (to_jsonb(new) - 'cap_usd') = (to_jsonb(old) - 'cap_usd') then
    return new;
  end if;
  if (to_jsonb(new) - 'status' - 'closed_at' - 'close_reason') is distinct from (to_jsonb(old) - 'status' - 'closed_at' - 'close_reason') then
    perform drinks_fail('immutable', '결재 내용(상한·기간·말)은 바꿀 수 없습니다 — 닫고 새로 결재받으세요');
  end if;
  if old.status = 'closed' and to_jsonb(new) is distinct from to_jsonb(old) then
    perform drinks_fail('immutable', '닫힌 결재는 다시 열 수 없습니다');
  end if;
  return new;
end $$;

-- 0060 정의 + 빈 목적(purpose)을 채운다. 나머지는 그대로.
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
  values (coalesce(drinks_text(p, 'stage'), '초안'), coalesce(drinks_text(p, 'purpose'), drinks_text(p, 'stage'), 'AI 근거·대본 초안'), v_cap,
    coalesce(drinks_text(p, 'approved_by'), 'operator'), drinks_text(p, 'approver_words'), now() + make_interval(days => v_days))
  returning * into b;
  return drinks_develop_budget_json(b.id);
end $$;

-- 화면용 숫자 한 덩어리.
create or replace function drinks_weekly_budget_json(p_id uuid) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('budget_id', s.budget_id, 'week_start', substr(s.stage, 8), 'expires_at', s.expires_at, 'status', s.status,
    'cap_usd', s.cap_usd, 'base_cap_usd', 5, 'max_cap_usd', (drinks_develop_limits() ->> 'max_cap_usd')::numeric,
    'week_spent_usd', s.spent_usd, 'week_held_usd', s.held_usd, 'remaining_usd', greatest(s.remaining_usd, 0),
    'total_spent_usd', (select coalesce(sum(h.actual_usd), 0) from drink_develop_holds h where h.status = 'settled'),
    'raises', (select count(*) from drink_develop_budget_raises r where r.budget_id = s.budget_id))
  from drink_develop_budget_state s where s.budget_id = p_id
$$;

-- 이번 주 한도 줄을 돌려준다. 없으면 $5 로 만든다(서울 기준 월요일 0시 ~ 다음 월요일 0시). 동시에 두 번 불려도 한 줄만 생긴다.
create or replace function drinks_ensure_weekly_budget(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_today date := (now() at time zone 'Asia/Seoul')::date; v_week date; v_stage text; v_id uuid;
begin
  v_week := v_today - (extract(isodow from v_today)::int - 1);
  v_stage := 'weekly:' || to_char(v_week, 'YYYY-MM-DD');
  insert into drink_develop_budgets (stage, purpose, cap_usd, approved_by, approver_words, expires_at)
  values (v_stage, '주간 AI 초안 한도(자동) — ' || to_char(v_week, 'YYYY-MM-DD') || ' 주', 5, 'operator',
    '운영자 지시(2026-11-06): 주간 한도는 5달러로 고정, 증액은 버튼으로 1달러씩',
    ((v_week + 7)::timestamp at time zone 'Asia/Seoul'))
  on conflict (stage) where stage like 'weekly:%' do nothing;
  select id into v_id from drink_develop_budgets where stage = v_stage;
  return drinks_weekly_budget_json(v_id);
end $$;

-- [한도 +$1]. 이번 주 줄이 없으면 먼저 만든다. 상한의 상한($10)을 넘으면 거절.
create or replace function drinks_raise_weekly_budget(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare b drink_develop_budgets; v_id uuid; v_to numeric; v_max numeric := (drinks_develop_limits() ->> 'max_cap_usd')::numeric;
begin
  v_id := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  select * into b from drink_develop_budgets where id = v_id for update;
  if b.status <> 'open' then perform drinks_fail('approval_closed', '이번 주 한도가 닫혀 있습니다'); end if;
  v_to := b.cap_usd + 1;
  if v_to > v_max then perform drinks_fail('budget_cap_max', '주간 한도는 $' || v_max || ' 까지입니다'); end if;
  perform set_config('drinks.raise_weekly', 'on', true);
  update drink_develop_budgets set cap_usd = v_to where id = b.id;
  perform set_config('drinks.raise_weekly', 'off', true);
  insert into drink_develop_budget_raises (budget_id, from_cap, to_cap, actor) values (b.id, b.cap_usd, v_to, coalesce(drinks_text(p, 'actor'), 'operator'));
  return drinks_weekly_budget_json(b.id);
end $$;

alter table drink_develop_budget_raises enable row level security;
revoke all on table drink_develop_budget_raises from anon, authenticated;
grant select, insert on table drink_develop_budget_raises to service_role;

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
