-- 주류 소재 — 한 소재에 형식 1~3개(설명형·카드뉴스·밈형) (2026-11-05). docs/deviation-drinks-multi-format.md §2·§3-1·§3-3
--
-- ★ 파일만 만든다. 운영 DB 적용은 따로 결재받는다. 0050~0068·0070·0071 이 먼저 적용돼 있어야 한다.
--
-- 무엇이 바뀌나 — 왜
--   A. drink_topic_picks 는 소재당 한 줄(PK topic_id)이라 형식을 하나만 적었고, [이걸로]를 다시 누르면 형식·승인 시각·금액을 **덮어썼다**(0065:440-444).
--      새 표 drink_topic_format_picks(PK topic_id+format_intent)가 형식마다 한 줄을 적는다. 기존 행은 전부 옮긴다(백필).
--      drink_topic_picks 는 **첫 형식(대표)** 로 남는다 — 옛 화면·memeQueries·publish_board 가 읽는다. 없을 때만 넣고, 다시는 덮어쓰지 않는다.
--   B. drink_develop_requests 에 format_intent 칸. 대본 요청이 어느 형식의 대본인지 요청 자체가 안다(전엔 대표 pick 하나를 읽어 정했다 →
--      형식을 바꾸면 큐에 있던 요청이 다른 틀의 대본을 썼다). 활성 요청 고유 색인을 (topic_id, kind, coalesce(format_intent,'')) 로 넓혀
--      형식마다 대본 요청이 하나씩 산다(근거 요청은 format_intent null → 소재당 하나, 공유).
--   C. 형식별 승인. drinks_approve_content(format_intent) 는 **그 형식의 제작안만** 승인한다.
--      · 소재가 researching 이면 0065 그대로 — 근거 제출·승인 → 편성(그 형식) → 제작안 제출·승인, 한 트랜잭션.
--      · 소재가 이미 ready/selected(다른 형식이 먼저 승인됨)이면 근거는 **지금 승인된 그 버전**이어야 하고, 편성 형식을 합집합으로 더한 뒤
--        제작안만 제출·승인한다. 안쪽은 전부 기존 함수라 검사가 줄지 않는다.
--      · 승인 기록(approved_at·approved_amount_usd)은 drink_topic_format_picks 의 그 형식 줄에 적고, 대표 pick 이 같은 형식이면 같이 적는다.
--   D. 이미 근거가 승인된 소재(ready/selected)에 형식을 더할 수 있다. 그 형식의 대본은 **승인된 근거로** 일반 요청(draft_evidence=false)이 만든다.
--      편성(selected_formats)에 아직 없는 형식의 제작안은 drinks_save_plan 이 거부하므로(0050 format_not_selected), 그 경우에만
--      drinks_develop_save_plan 이 직접 **작성 중(draft) 행**을 넣는다 — 근거가 승인·유효한지, 그 형식을 골랐는지, 작성 중 제작안이 없는지는
--      똑같이 잰다. 승인은 여전히 편성 뒤 drinks_plan_action 이 한다(이 함수는 승인하지 않는다).
--   E. 근거가 성공하면 **고른 설명형·카드뉴스 각각** 대본 요청을 잇는다(drinks_finish_develop). 이미 그 근거로 만든 대본이 있는 형식은 건넌다.
--      result.chain 은 이제 **배열**이다(형식마다 한 항목). 워커(engine/drinks_develop.py)는 배열도 로그만 남긴다.
--   F. 밈형은 형식으로 고르되 편성(selected_formats ⊂ {video,carousel})에는 들어가지 않는다 — drink_topic_format_picks(meme) 한 줄이 선택이고,
--      제작안은 기존 drinks_meme_save_draft(topic_id) 경로다. drinks_meme_check_owner 가 이 표를 보도록 바꿨다(두 번째 형식이 밈일 수 있다).
--   G. 조회 3개(읽기만, stable): drinks_develop_estimate(형식별 예상 비용 — 모르는 값은 null, 0 으로 쓰지 않는다)·drinks_topic_formats·
--      drinks_work_items. 뷰 drink_work_items 는 작업 단위(소재×형식 + 카드 밈 제작안) 한 줄씩 — LATERAL '현재 1건' 조회라 행이 늘지 않는다.
--
-- 안전 장치 — 약해지는 것이 없다
--   · 승인 전 대본은 draft 로만 존재한다. drink_plans_guard·drinks_plan_action·drinks_select·drinks_review_action 을 고치지 않았다.
--   · 승인 경로는 기존 함수를 그대로 거친다. 검사 항목(버전 충돌·최신 근거·최신 대본·차단·근거 값 대조·진행 중 요청·금액 상한)은 전부 그대로다.
--   · 승인 금액은 기록만 한다. 결재(drink_spend_approvals)를 열지 않는다(spend_approval_opened:false).
--   · 근거 내용이 바뀌면 그 근거로 쓴 대본은 형식을 가리지 않고 차단된다(0064 트리거 그대로).
--   · 워커 함수(drinks_develop_*·drinks_start_develop·drinks_finish_develop)는 승인·제출·편성 함수를 부르지 않는다(tests/test_drinks_develop.py 가 0072 도 읽는다).
--   · 설명형은 옛 그림 나열식 렌더로 못 간다 — drinks_plan_is_explainer 가 형식 표를 보고, 형식 표에도 취소 트리거를 단다.
--
-- 0065 와 달라진 동작(의도한 것)
--   · [이걸로]를 다시 눌러도 형식·승인·금액을 덮어쓰지 않는다. 형식을 더하는 것만 된다(빼기는 없다 — 선택 기록은 삭제 불가).
--     그래서 0065 의 '형식을 바꾸면 옛 대본 요청을 거둔다'는 사라졋다 — 요청이 자기 형식을 알아 다른 형식의 대본을 쓰는 일이 없다.
--   · 근거가 아직 작성 중인 소재에 형식을 **뒤에** 더하면 그 형식의 필수 주장이 기획에 들어가면서(내용 변경) 먼저 만든 다른 형식의 대본이
--     차단될 수 있다(0064 G7 규칙 그대로) — 다시 만들면 된다. 한 번에 고른 형식들은 이어 만들기가 대본 전에 전부 채워 서로 차단하지 않는다.
--   · 대본 요청(kind=plan)의 format_intent: 형식이 둘 이상 골라진 소재에서는 **필수**다. 하나만 골랐으면 그 형식, 고른 적 없는 옛 소재는
--     0단계 그대로 영상(설명형)이다 — 옛 호출(DevelopCard·시험)이 깨지지 않는다.
--
-- 되돌리기(0065·0066·0067 정의로 돌아간다):
--   1. 0065 의 drinks_request_develop·drinks_start_develop·drinks_develop_save_plan·drinks_develop_chain_next·drinks_pick_topic·drinks_approve_content,
--      0064 의 drinks_develop_request_json·drink_develop_requests_guard·drinks_develop_status, 0066 의 drinks_meme_check_owner,
--      0067 의 drinks_plan_is_explainer·drinks_explainer_status 를 다시 실행한다(그다음 0056 의 반복문도 한 번 더).
--   2. drop view drink_work_items; drop function drinks_develop_estimate(jsonb); drop function drinks_topic_formats(jsonb); drop function drinks_work_items(jsonb);
--      drop function drinks_develop_estimate_params(); drop function drinks_develop_price(text); drop function drinks_pick_formats(jsonb);
--      drop function drinks_resolve_plan_intent(uuid, text); drop function drinks_format_picked(uuid, text); drop function drinks_representative_intent(uuid);
--      drop function drinks_review_fill_required(uuid, text);
--   3. drop index drink_develop_one_active_uq; create unique index drink_develop_one_active_uq on drink_develop_requests (topic_id, kind) where status in ('queued','running');
--      (같은 소재·같은 종류의 활성 요청이 둘이면 먼저 하나를 취소해야 한다)
--      alter table drink_develop_requests drop column format_intent;
--   4. drop trigger drink_topic_format_picks_explainer_cancel on drink_topic_format_picks; drop trigger drink_topic_format_picks_guard on drink_topic_format_picks;
--      drop trigger drink_topic_picks_mirror_format on drink_topic_picks; drop function drink_topic_picks_mirror_format();
--      drop function drink_topic_format_picks_guard(); drop table drink_topic_format_picks;
--   대표 pick(drink_topic_picks)은 그대로라 되돌려도 첫 형식은 남는다. 두 번째 형식 이후의 선택·승인 기록은 표와 함께 사라진다(워크플로 이벤트에는 남는다).

-- ─────────────────────────────────────────────────────────────
-- 표·칸
-- ─────────────────────────────────────────────────────────────

create table if not exists drink_topic_format_picks (
  topic_id            uuid not null references drink_topics(id),
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
  updated_at          timestamptz not null default now(),
  primary key (topic_id, format_intent)
);
create index if not exists drink_topic_format_picks_intent_idx on drink_topic_format_picks (format_intent);

-- 백필: 옛 단일 선택을 형식 줄로. 이미 있으면 건드리지 않는다.
insert into drink_topic_format_picks (topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id,
    approved_at, approved_amount_usd, created_at, updated_at)
  select topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id,
    approved_at, approved_amount_usd, created_at, updated_at
  from drink_topic_picks
  on conflict (topic_id, format_intent) do nothing;

-- 형식 선택 기록은 지우지 못하고 다른 소재·다른 형식으로 옮기지 못한다(0064 drink_topic_picks_guard 와 같은 규칙).
create or replace function drink_topic_format_picks_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '형식 선택 기록은 삭제할 수 없습니다'); end if;
  if new.topic_id <> old.topic_id or new.format_intent <> old.format_intent then
    perform drinks_fail('immutable', '다른 소재·다른 형식으로 옮길 수 없습니다');
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists drink_topic_format_picks_guard on drink_topic_format_picks;
create trigger drink_topic_format_picks_guard before update or delete on drink_topic_format_picks
  for each row execute function drink_topic_format_picks_guard();

-- 설명형을 (두 번째 형식으로라도) 고르면 옛 그림 나열식 작업을 멈춘다 — 0067 과 같은 함수(new.topic_id·new.format_intent 만 읽는다).
drop trigger if exists drink_topic_format_picks_explainer_cancel on drink_topic_format_picks;
create trigger drink_topic_format_picks_explainer_cancel after insert or update on drink_topic_format_picks
  for each row execute function drink_topic_picks_explainer_cancel();

-- 옛 표(drink_topic_picks)에 직접 넣는 경로(옛 화면·시험 고정물)도 형식 줄을 갖게 한다 — 읽는 쪽은 형식 표 하나만 본다.
create or replace function drink_topic_picks_mirror_format() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  insert into drink_topic_format_picks (topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id,
      approved_at, approved_amount_usd)
    values (new.topic_id, new.format_intent, new.recommended_format, new.recommended_reason, new.editorial_week, new.budget_id, new.candidate_id,
      new.approved_at, new.approved_amount_usd)
    on conflict (topic_id, format_intent) do nothing;
  return null;
end $$;
drop trigger if exists drink_topic_picks_mirror_format on drink_topic_picks;
create trigger drink_topic_picks_mirror_format after insert on drink_topic_picks
  for each row execute function drink_topic_picks_mirror_format();

alter table drink_develop_requests add column if not exists format_intent text
  check (format_intent is null or format_intent in ('explainer','card'));   -- 대본 요청의 형식. null = 옛 요청 = 대표 형식
alter table drink_develop_requests drop constraint if exists drink_develop_format_intent_ck;
alter table drink_develop_requests add constraint drink_develop_format_intent_ck check (format_intent is null or kind = 'plan');

-- 활성 요청은 (소재, 종류, 형식) 마다 하나. 근거 요청은 형식이 없어 소재당 하나(공유).
drop index if exists drink_develop_one_active_uq;
create unique index drink_develop_one_active_uq on drink_develop_requests (topic_id, kind, coalesce(format_intent, ''))
  where status in ('queued','running');

-- ─────────────────────────────────────────────────────────────
-- 규칙 함수
-- ─────────────────────────────────────────────────────────────

-- 입력의 형식 목록. formats 배열(1~3, 중복 없음) 또는 옛 format 하나. 순서를 지킨다(첫 번째가 대표).
create or replace function drinks_pick_formats(p jsonb) returns text[] language plpgsql set search_path = public, pg_temp as $$
declare v_out text[] := '{}'; f text;
begin
  if jsonb_typeof(p -> 'formats') = 'array' then
    for f in select x from jsonb_array_elements_text(p -> 'formats') with ordinality e(x, o) order by o loop
      if f is null or f not in ('explainer','card','meme') then perform drinks_fail('invalid_input', '형식(설명형·카드뉴스·밈형)을 고르세요'); end if;
      if f = any(v_out) then perform drinks_fail('invalid_input', '같은 형식을 두 번 골랐습니다: ' || f); end if;
      v_out := v_out || f;
    end loop;
  elsif drinks_text(p, 'format') is not null then
    f := drinks_text(p, 'format');
    if f not in ('explainer','card','meme') then perform drinks_fail('invalid_input', '형식(설명형·카드뉴스·밈형)을 고르세요'); end if;
    v_out := array[f];
  end if;
  if cardinality(v_out) = 0 then perform drinks_fail('invalid_input', '형식(설명형·카드뉴스·밈형)을 하나 이상 고르세요'); end if;
  if cardinality(v_out) > 3 then perform drinks_fail('invalid_input', '형식은 3개까지 고를 수 있습니다'); end if;
  return v_out;
end $$;

-- 대표 형식(옛 drink_topic_picks). 고른 적 없으면 null.
create or replace function drinks_representative_intent(p_topic uuid) returns text language sql stable set search_path = public, pg_temp as $$
  select format_intent from drink_topic_picks where topic_id = p_topic
$$;

-- 이 형식을 골랐나. 형식을 고른 적이 없는 옛 소재(0060 경로)는 true — 그쪽은 편성(selected_formats) 규칙이 그대로 잰다.
create or replace function drinks_format_picked(p_topic uuid, p_intent text) returns boolean language sql stable set search_path = public, pg_temp as $$
  select not exists (select 1 from drink_topic_format_picks where topic_id = p_topic)
      or exists (select 1 from drink_topic_format_picks where topic_id = p_topic and format_intent = p_intent)
$$;

-- 대본 요청의 형식을 정한다. 입력이 있으면 그것. 없으면: 설명형·카드뉴스를 둘 다 골랐으면 모른다(지정 필수) / 하나면 그것 /
-- 형식을 고른 적 없는 옛 소재는 0단계 그대로 영상(explainer) / 밈만 고른 소재는 null(대본 형식이 없다).
create or replace function drinks_resolve_plan_intent(p_topic uuid, p_intent text) returns text language plpgsql stable set search_path = public, pg_temp as $$
declare n int; v text;
begin
  if p_intent is not null then
    if p_intent not in ('explainer','card') then perform drinks_fail('invalid_input', '대본 형식(format_intent)은 explainer·card 중 하나입니다'); end if;
    return p_intent;
  end if;
  select count(*), min(format_intent) into n, v from drink_topic_format_picks where topic_id = p_topic and format_intent in ('explainer','card');
  if n > 1 then
    perform drinks_fail('invalid_input', '형식이 여럿 골라진 소재입니다 — 어느 형식의 대본인지(format_intent: explainer·card)를 지정하세요');
  end if;
  if n = 1 then return v; end if;
  if not exists (select 1 from drink_topic_format_picks where topic_id = p_topic) then return 'explainer'; end if;
  return null;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 불변 규칙 (0064 정의 + format_intent)
-- ─────────────────────────────────────────────────────────────

create or replace function drink_develop_requests_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '개발 요청 기록은 삭제할 수 없습니다'); end if;
  if old.status not in ('queued','running') and (to_jsonb(new) - 'cost_usd') is distinct from (to_jsonb(old) - 'cost_usd') then
    perform drinks_fail('immutable', '끝난 개발 요청은 바꿀 수 없습니다');
  end if;
  if (new.topic_id, new.kind, new.review_id, new.budget_id, new.created_at, new.chain, new.draft_evidence, new.format_intent) is distinct from
     (old.topic_id, old.kind, old.review_id, old.budget_id, old.created_at, old.chain, old.draft_evidence, old.format_intent) then
    perform drinks_fail('immutable', '요청 내용(소재·종류·형식·근거·결재)은 바꿀 수 없습니다');
  end if;
  if old.evidence_hash is not null and new.evidence_hash is distinct from old.evidence_hash then
    perform drinks_fail('immutable', '시작 때 본 근거 값은 바꿀 수 없습니다');
  end if;
  return new;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 요청 (0065 정의 + 형식)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_develop_request_json(r drink_develop_requests) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('request_id', r.id, 'topic_id', r.topic_id, 'kind', r.kind, 'status', r.status, 'step', r.step,
    'review_id', r.review_id, 'budget_id', r.budget_id, 'cost_usd', r.cost_usd, 'cancel_requested', r.cancel_requested,
    'error_code', r.error_code, 'error_message', r.error_message, 'result', r.result,
    'result_review_id', r.result_review_id, 'result_plan_revision_id', r.result_plan_revision_id,
    'chain', r.chain, 'draft_evidence', r.draft_evidence, 'format_intent', r.format_intent,
    'created_at', r.created_at, 'started_at', r.started_at, 'finished_at', r.finished_at)
$$;

create or replace function drinks_request_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_kind text := drinks_text(p, 'kind');
  v_budget uuid := drinks_uuid(p, 'budget_id', false); v_review uuid := drinks_uuid(p, 'review_id', false); bs jsonb;
  v_draft boolean := coalesce(p -> 'draft_evidence' = 'true'::jsonb, false);
  v_chain boolean := coalesce(p -> 'chain' = 'true'::jsonb, false);
  v_stop jsonb; v_intent text := drinks_text(p, 'format_intent'); v_fmt text; v_rep text; v_has_picks boolean;
begin
  if v_kind is null or v_kind not in ('evidence','plan') then perform drinks_fail('invalid_input', '종류는 evidence 또는 plan 입니다'); end if;
  if v_draft and v_kind <> 'plan' then perform drinks_fail('invalid_input', '승인 전 근거 표시는 대본 초안 요청에만 씁니다'); end if;
  if v_chain and v_kind <> 'evidence' then perform drinks_fail('invalid_input', '이어 만들기 표시는 근거 초안 요청에만 씁니다'); end if;
  if v_intent is not null and v_kind <> 'plan' then perform drinks_fail('invalid_input', '형식(format_intent)은 대본 초안 요청에만 씁니다'); end if;
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), null, false);
  v_rep := drinks_representative_intent(t.id);
  v_has_picks := exists (select 1 from drink_topic_format_picks where topic_id = t.id);
  if v_kind = 'plan' then
    v_intent := drinks_resolve_plan_intent(t.id, v_intent);
    v_fmt := drinks_intent_format(v_intent);
    if v_fmt is null then
      perform drinks_fail('format_not_selected', '설명형·카드뉴스로 고른 소재만 대본을 만듭니다');
    end if;
  end if;
  -- 활성 중복: 근거는 소재당 하나, 대본은 (소재, 형식)마다 하나. 옛 요청(형식 칸 없음)은 대표 형식으로 본다.
  select * into q from drink_develop_requests where topic_id = t.id and kind = v_kind and status in ('queued','running')
    and (v_kind = 'evidence' or coalesce(format_intent, v_rep) is not distinct from v_intent)
    order by created_at limit 1;
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
    -- 승인 전 근거로 대본 초안: 결재 필수, 그 형식으로 고른 소재의 작업 중 근거만.
    if v_budget is null then perform drinks_fail('budget_missing', '결재(예산)가 없어 대본을 만들 수 없습니다 — 개발 결재를 열고 다시 요청하세요'); end if;
    if t.status <> 'researching' then perform drinks_fail('invalid_state', '근거를 작성 중인 소재에서만 승인 전 대본 초안을 만듭니다'); end if;
    if not v_has_picks or not drinks_format_picked(t.id, v_intent) then
      perform drinks_fail('format_not_selected', '그 형식으로 고른 소재만 승인 전 근거로 대본을 만듭니다 — [이걸로]에서 형식을 더하세요');
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
      where topic_id = t.id and format = v_fmt and drafted_from_unapproved and plan_status = 'draft' and blocked_at is null
        and topic_review_id <> r.id;
    if exists (select 1 from drink_deliverables d join drink_plan_revisions pr on pr.deliverable_id = d.id
        where d.topic_id = t.id and d.format = v_fmt and pr.plan_status = 'draft' and pr.blocked_at is null) then
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
    if v_has_picks then
      -- [이걸로]로 고른 소재: 근거가 승인된 상태(ready/selected)에서 고른 형식이면 된다. 편성은 승인 때 합집합으로 더한다.
      if t.status not in ('ready','selected') then
        perform drinks_fail('invalid_state', '근거가 승인된 소재에서만 승인된 근거로 제작안 초안을 만듭니다');
      end if;
      if not drinks_format_picked(t.id, v_intent) then
        perform drinks_fail('format_not_selected', '[이걸로]에서 고르지 않은 형식입니다 — 형식을 먼저 더하세요');
      end if;
    elsif t.status <> 'selected' or not v_fmt = any(t.selected_formats) then
      perform drinks_fail('format_not_selected', '영상으로 편성된 소재만 제작안 초안을 만들 수 있습니다');
    end if;
    if exists (select 1 from drink_deliverables d join drink_plan_revisions pr on pr.deliverable_id = d.id
        where d.topic_id = t.id and d.format = v_fmt and pr.plan_status = 'draft' and pr.blocked_at is null) then
      perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
  end if;
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id, chain, draft_evidence, format_intent)
    values (t.id, v_kind, v_review, v_budget, v_chain, v_draft, case when v_kind = 'plan' then v_intent end) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', v_kind, 'budget_id', v_budget, 'review_id', v_review, 'chain', v_chain, 'draft_evidence', v_draft, 'format_intent', q.format_intent));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

-- 소재 화면용: 0064 + 형식 줄 전부.
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
    'picks', coalesce((select jsonb_agg(to_jsonb(k) order by k.created_at, k.format_intent) from drink_topic_format_picks k where k.topic_id = v_topic), '[]'),
    'limits', drinks_develop_limits());
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 (service_role) — 초안까지만. 승인·제출·편성 함수를 부르지 않는다
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_start_develop(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; r drink_topic_reviews; v_reaped int; v_block text; v_budget jsonb; v_job jsonb; v_intent text; v_fmt text;
  v_has_picks boolean;
begin
  v_reaped := drinks_reap_develop();
  loop
    select * into q from drink_develop_requests where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    select * into t from drink_topics where id = q.topic_id;
    -- 요청의 형식 → 없으면(옛 요청) 대표 형식. 형식을 고른 적 없는 옛 소재는 null(워커가 영상으로 읽는다, 0단계 그대로).
    v_intent := coalesce(q.format_intent, drinks_representative_intent(q.topic_id));
    v_has_picks := exists (select 1 from drink_topic_format_picks where topic_id = q.topic_id);
    v_fmt := drinks_intent_format(coalesce(v_intent, 'explainer'));
    v_block := null;
    if q.kind = 'evidence' then
      if t.status not in ('researching','ready','selected') then v_block := 'topic_state_changed'; end if;
    else
      select * into r from drink_topic_reviews where id = q.review_id;
      if q.draft_evidence then
        if t.status <> 'researching' then v_block := 'topic_state_changed';
        elsif r.status <> 'draft' or r.id is distinct from t.current_review_id then v_block := 'review_changed';
        elsif drinks_intent_format(v_intent) is null or not v_has_picks or not drinks_format_picked(q.topic_id, v_intent) then v_block := 'format_not_selected'; end if;
      elsif r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then v_block := 'review_not_approved';
      elsif v_has_picks then
        if t.status not in ('ready','selected') then v_block := 'topic_state_changed';
        elsif drinks_intent_format(v_intent) is null or not drinks_format_picked(q.topic_id, v_intent) then v_block := 'format_not_selected'; end if;
      elsif t.status <> 'selected' or not v_fmt = any(t.selected_formats) then v_block := 'format_not_selected'; end if;
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

-- 작성 중 기획에 이 형식의 필수 주장이 없으면 채운다(0065 save_plan 의 규칙을 한 자리로). 형식 목록은 더한다(덮어쓰지 않는다).
-- 기획 내용이 바뀌므로 그 근거로 이미 쓴 대본은 트리거가 차단한다 — 그래서 이어 만들기는 대본을 요청하기 **전에** 고른 형식 전부를 채운다.
create or replace function drinks_review_fill_required(p_review uuid, p_fmt text) returns boolean language plpgsql set search_path = public, pg_temp as $$
declare r drink_topic_reviews; v_req jsonb;
begin
  select * into r from drink_topic_reviews where id = p_review for update;
  if not found or r.status <> 'draft' or cardinality(drinks_text_array(r.brief -> 'required_claims' -> p_fmt)) > 0 then return false; end if;
  v_req := drinks_format_required(r.brief, p_fmt);
  update drink_topic_reviews set brief = jsonb_set(jsonb_set(brief, '{required_claims}',
      coalesce(brief -> 'required_claims', '{}'::jsonb) || jsonb_build_object(p_fmt, v_req)), '{proposed_formats}',
      (select coalesce(jsonb_agg(distinct x), '[]'::jsonb) from (select x from jsonb_array_elements_text(coalesce(brief -> 'proposed_formats', '[]'::jsonb)) x
        union select p_fmt) s(x)))
    where id = r.id;
  update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id;
  return true;
end $$;

-- 제작안 초안 저장(제출·승인 아님). 형식은 요청의 format_intent → 대표 pick 순.
--   · 표시 없는 요청 + 그 형식이 이미 편성됨 → 0061 그대로 drinks_save_plan.
--   · 표시 없는 요청 + 근거는 승인됐지만 그 형식은 아직 편성 전(형식을 뒤에 더함) → 승인·유효한 근거인지, 그 형식을 골랐는지, 작성 중
--     제작안이 없는지 재고 작성 중(draft) 행을 직접 넣는다. 근거 값(evidence_content_hash)을 같이 적어 승인 직전 대조에 쓴다.
--   · 승인 전 근거 경로는 0065 그대로(형식만 요청에서 읽는다).
create or replace function drinks_develop_save_plan(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; v_res jsonb; v_dver int; t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions;
  v_plan jsonb; v_no int; v_hash text; v_take text := left(drinks_text(p, 'core_takeaway_draft'), 300); v_fmt text; v_intent text;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'plan' then perform drinks_fail('invalid_state', '제작안 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  v_intent := coalesce(q.format_intent, drinks_representative_intent(q.topic_id));
  if not q.draft_evidence then
    v_fmt := drinks_intent_format(coalesce(v_intent, 'explainer'));
    t := drinks_lock_topic(q.topic_id, null, false);
    if t.status = 'selected' and v_fmt = any(t.selected_formats) then
      select dv.version into v_dver from drink_deliverables dv where dv.topic_id = q.topic_id and dv.format = v_fmt for update;
      v_res := drinks_save_plan(jsonb_build_object('topic_id', q.topic_id, 'format', v_fmt, 'topic_review_id', q.review_id,
        'plan_json', p -> 'plan_json') || case when v_dver is null then '{}'::jsonb
                                           else jsonb_build_object('expected_deliverable_version', v_dver) end);
      update drink_develop_requests set result_plan_revision_id = (v_res ->> 'revision_id')::uuid, step = 'plan_saved' where id = q.id;
      return v_res;
    end if;
    -- 형식을 뒤에 더한 소재: 승인된 근거, 아직 편성 전 형식.
    if t.status not in ('ready','selected') then perform drinks_fail('review_changed', '대본을 쓰는 사이 소재 상태가 바뀌었습니다 — 저장하지 않습니다'); end if;
    select * into r from drink_topic_reviews where id = q.review_id for update;
    if r.id is distinct from t.approved_review_id or r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then
      perform drinks_fail('review_not_approved', '승인되고 지금도 유효한 근거 버전으로만 제작안 초안을 저장합니다');
    end if;
    if drinks_intent_format(v_intent) is null or not exists (select 1 from drink_topic_format_picks where topic_id = t.id and format_intent = v_intent) then
      perform drinks_fail('format_not_selected', '그 형식으로 고른 소재가 아닙니다');
    end if;
    v_plan := drinks_validate_plan(v_fmt, p -> 'plan_json', r);
    v_hash := drinks_evidence_content_hash(r.evidence_pack, r.brief);
    select * into d from drink_deliverables where topic_id = t.id and format = v_fmt and locale = 'ko' for update;
    if not found then
      insert into drink_deliverables (topic_id, format) values (t.id, v_fmt) returning * into d;
      perform drinks_log(t.id, 'deliverable', d.id, 'deliverable_created', null, null, v_fmt, null);
    end if;
    if exists (select 1 from drink_plan_revisions where deliverable_id = d.id and plan_status = 'draft' and blocked_at is null) then
      perform drinks_fail('draft_exists', '작성 중인 제작안이 이미 있습니다');
    end if;
    select coalesce(max(revision_no), 0) + 1 into v_no from drink_plan_revisions where deliverable_id = d.id;
    insert into drink_plan_revisions (deliverable_id, topic_id, format, revision_no, topic_review_id, plan_json, aspect_ratio,
        drafted_from_unapproved, evidence_content_hash)
      values (d.id, t.id, v_fmt, v_no, r.id, v_plan, case v_fmt when 'video' then '9:16' else '4:5' end, false, v_hash) returning * into pr;
    update drink_deliverables set current_revision_id = pr.id where id = d.id;
    update drink_develop_requests set result_plan_revision_id = pr.id, step = 'plan_saved' where id = q.id;
    perform drinks_log(t.id, 'plan', pr.id, 'plan_created', null, 'draft', pr.input_hash, null,
      jsonb_build_object('format', v_fmt, 'revision_no', v_no, 'topic_review_id', r.id, 'drafted_from_unapproved', false, 'format_added_later', true));
    return jsonb_build_object('revision_id', pr.id, 'deliverable_id', d.id, 'revision_no', pr.revision_no, 'version', pr.version,
      'input_hash', pr.input_hash, 'coverage', drinks_plan_coverage(v_fmt, pr.plan_json, r), 'drafted_from_unapproved', false);
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
  v_fmt := drinks_intent_format(v_intent);
  if v_fmt is null or not exists (select 1 from drink_topic_format_picks where topic_id = t.id and format_intent = v_intent) then
    perform drinks_fail('format_not_selected', '설명형·카드뉴스로 고른 소재가 아닙니다');
  end if;
  v_plan := drinks_validate_plan(v_fmt, p -> 'plan_json', r);
  -- 다른 형식으로 만든 근거면 이 형식의 필수 주장이 비어 있다 — 편성이 막히기 전에 채운다(0065 그대로). 형식 목록은 더한다(덮어쓰지 않는다).
  if drinks_review_fill_required(r.id, v_fmt) then
    select * into r from drink_topic_reviews where id = r.id;
    -- 트리거가 '쓰는 중인 요청'에 건 취소를 푼다 — 이 요청의 결과를 지금 저장하는 중이다.
    update drink_develop_requests set cancel_requested = false where id = q.id;
    v_hash := drinks_evidence_content_hash(r.evidence_pack, r.brief);
  end if;
  select * into d from drink_deliverables where topic_id = t.id and format = v_fmt and locale = 'ko' for update;
  if not found then
    insert into drink_deliverables (topic_id, format) values (t.id, v_fmt) returning * into d;
    perform drinks_log(t.id, 'deliverable', d.id, 'deliverable_created', null, null, v_fmt, null);
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
    values (d.id, t.id, v_fmt, v_no, r.id, v_plan, case v_fmt when 'video' then '9:16' else '4:5' end, true, v_hash) returning * into pr;
  update drink_deliverables set current_revision_id = pr.id where id = d.id;
  update drink_develop_requests set result_plan_revision_id = pr.id, step = 'plan_saved' where id = q.id;
  perform drinks_log(t.id, 'plan', pr.id, 'plan_created', null, 'draft', pr.input_hash, null,
    jsonb_build_object('format', v_fmt, 'revision_no', v_no, 'topic_review_id', r.id, 'drafted_from_unapproved', true));
  return jsonb_build_object('revision_id', pr.id, 'deliverable_id', d.id, 'revision_no', pr.revision_no, 'version', pr.version,
    'input_hash', pr.input_hash, 'coverage', drinks_plan_coverage(v_fmt, pr.plan_json, r), 'drafted_from_unapproved', true);
end $$;

-- 근거 초안 성공 뒤, 고른 설명형·카드뉴스 **각각** 대본 요청을 넣는다. 돌려주는 값은 형식마다 한 항목인 배열이다.
-- 막힌 항목은 code·message 를 담는다(근거 초안 자체는 성공이다). 이미 그 근거로 만든 대본이 있는 형식은 건넌다(already_drafted).
create or replace function drinks_develop_chain_next(q drink_develop_requests) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_stop jsonb; v_res jsonb; v_out jsonb := '[]'::jsonb; v_item jsonb; f record; v_fmt text; v_shared_code text; v_shared_msg text;
begin
  if not exists (select 1 from drink_topic_format_picks where topic_id = q.topic_id and format_intent in ('explainer','card')) then
    return v_out;   -- 밈만 고른 소재(또는 고른 적 없음): 이어 만들 대본 형식이 없다
  end if;
  if q.budget_id is null then
    v_shared_code := 'budget_missing'; v_shared_msg := '개발 결재가 없어 대본을 만들지 않았습니다';
  else
    v_stop := drinks_chain_stop_blockers(q.result_review_id);
    if jsonb_array_length(v_stop) > 0 then
      v_shared_code := 'evidence_not_usable';
      v_shared_msg := '근거에 고칠 곳이 있어 대본을 만들지 않았습니다 — 돈을 쓰기 전에 멈췄습니다. 주장·인용을 고친 뒤 대본을 다시 요청하세요';
    end if;
  end if;
  -- 고른 형식 전부의 필수 주장을 먼저 채운다 — 대본이 하나라도 만들어진 뒤에 채우면 그 변경이 먼저 만든 대본을 차단한다.
  if v_shared_code is null then
    for f in select format_intent from drink_topic_format_picks where topic_id = q.topic_id and format_intent in ('explainer','card') loop
      perform drinks_review_fill_required(q.result_review_id, drinks_intent_format(f.format_intent));
    end loop;
  end if;
  for f in select format_intent from drink_topic_format_picks where topic_id = q.topic_id and format_intent in ('explainer','card')
      order by created_at, format_intent loop
    v_fmt := drinks_intent_format(f.format_intent);
    if v_shared_code is not null then
      v_item := jsonb_build_object('format_intent', f.format_intent, 'queued', false, 'code', v_shared_code, 'message', v_shared_msg)
        || case when v_stop is null then '{}'::jsonb else jsonb_build_object('blockers', v_stop) end;
    elsif exists (select 1 from drink_plan_revisions pl where pl.topic_review_id = q.result_review_id and pl.format = v_fmt
        and pl.plan_status = 'draft' and pl.blocked_at is null) then
      v_item := jsonb_build_object('format_intent', f.format_intent, 'queued', false, 'code', 'already_drafted', 'message', '이 근거로 만든 대본이 이미 있습니다');
    else
      begin
        v_res := drinks_request_develop(jsonb_build_object('topic_id', q.topic_id, 'kind', 'plan', 'budget_id', q.budget_id, 'draft_evidence', true,
          'format_intent', f.format_intent));
        v_item := jsonb_build_object('format_intent', f.format_intent, 'queued', true, 'kind', 'plan', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
      exception when raise_exception then
        if sqlerrm not like 'drinks:%' then raise; end if;
        v_item := jsonb_build_object('format_intent', f.format_intent, 'queued', false, 'code', split_part(sqlerrm, ':', 2),
          'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
      end;
    end if;
    v_out := v_out || v_item;
  end loop;
  return v_out;
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
  -- 같은 트랜잭션: 워커가 이 사이에 죽어 '근거는 성공했는데 대본 요청이 안 들어간' 상태가 생기지 않는다. 형식마다 한 항목(배열).
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
    jsonb_build_object('kind', q.kind, 'cost_usd', q.cost_usd, 'chain', v_chain, 'format_intent', q.format_intent));
  return drinks_develop_request_json(q);
end $$;

-- ─────────────────────────────────────────────────────────────
-- [이걸로] (운영자) — 소재 올리기 + 형식 1~3개 + 편성 의도 + 형식마다 이어 만들기 요청. 돈은 여기서 나가지 않는다.
--   · 형식 줄은 없을 때만 넣는다(있는 줄의 승인·금액은 그대로). 대표 pick 도 없을 때만.
--   · researching + 근거 없음 → 근거 요청 1건(공유, chain) / researching + 작성 중 근거 → 형식마다 대본 요청(승인 전 근거) /
--     ready·selected → 형식마다 대본 요청(승인된 근거, 일반 요청) / 밈 → 요청 없음.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_pick_topic(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  v_formats text[] := drinks_pick_formats(p); v_format text; v_cand uuid := drinks_uuid(p, 'candidate_id', false); v_topic uuid := drinks_uuid(p, 'topic_id', false);
  v_week date := drinks_date(p, 'editorial_week'); v_budget uuid := drinks_uuid(p, 'budget_id', false);
  c drink_discovery_candidates; t drink_topics; r drink_topic_reviews; v_res jsonb; v_chain jsonb; v_created boolean := false; v_fits jsonb;
  v_fmt text; v_picks jsonb := '[]'::jsonb; v_evidence jsonb; v_first_chain jsonb; v_n int; v_existing boolean; v_rep text := v_formats[1];
begin
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
  elsif t.status not in ('researching','ready','selected') then
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재입니다 — 다시 연 뒤에 고르세요');
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if found and r.status = 'in_review' then
    perform drinks_fail('review_in_progress', '검토 중인 근거 버전이 있습니다 — 공통 기획 탭에서 승인하거나 변경 요청한 뒤 고르세요');
  end if;
  -- 대표 pick(옛 화면 호환): 없을 때만. 다시는 덮어쓰지 않는다.
  insert into drink_topic_picks (topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id)
    values (t.id, v_rep, drinks_text(p, 'recommended_format'), left(drinks_text(p, 'recommended_reason'), 500), v_week, v_budget, v_cand)
    on conflict (topic_id) do nothing;
  foreach v_format in array v_formats loop
    v_fmt := drinks_intent_format(v_format);
    insert into drink_topic_format_picks (topic_id, format_intent, recommended_format, recommended_reason, editorial_week, budget_id, candidate_id)
      values (t.id, v_format, drinks_text(p, 'recommended_format'), left(drinks_text(p, 'recommended_reason'), 500), v_week, v_budget, v_cand)
      on conflict (topic_id, format_intent) do nothing;
    get diagnostics v_n = row_count;
    v_existing := v_n = 0;
    perform drinks_log(t.id, 'topic', t.id, 'format_picked', t.status, t.status, v_format, null,
      jsonb_build_object('format_intent', v_format, 'maps_to', v_fmt, 'recommended_format', drinks_text(p, 'recommended_format'),
        'editorial_week', v_week, 'budget_id', v_budget, 'candidate_id', v_cand, 'existing', v_existing, 'formats', to_jsonb(v_formats)));
    if v_format = 'meme' then
      v_chain := jsonb_build_object('queued', false, 'code', 'meme_board', 'message',
        '밈형은 근거·대본을 만들지 않습니다. 형식만 적어 두었고, 제작은 밈 보드에서 이어집니다');
    elsif t.status = 'researching' and r.id is not null and r.status = 'draft' then
      if exists (select 1 from drink_plan_revisions pl where pl.topic_review_id = r.id and pl.format = v_fmt and pl.plan_status = 'draft' and pl.blocked_at is null) then
        v_chain := jsonb_build_object('queued', false, 'code', 'already_drafted', 'message', '이 근거로 만든 대본이 이미 있습니다');
      else
        begin
          v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true,
            'format_intent', v_format)));
          v_chain := jsonb_build_object('queued', true, 'kind', 'plan', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
        exception when raise_exception then
          if sqlerrm not like 'drinks:%' then raise; end if;
          v_chain := jsonb_build_object('queued', false, 'kind', 'plan', 'code', split_part(sqlerrm, ':', 2), 'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
        end;
      end if;
    elsif t.status = 'researching' then
      -- 근거 요청은 소재당 하나(공유). 첫 형식이 넣고 나머지는 같은 요청을 가리킨다.
      if v_evidence is null then
        v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', true)));
        v_evidence := jsonb_build_object('queued', true, 'kind', 'evidence', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
        v_chain := v_evidence;
      else
        v_chain := v_evidence || jsonb_build_object('existing', true);
      end if;
    else
      -- ready·selected: 승인된 근거로 일반 대본 요청. 이미 작성 중인 제작안이 있으면 그 이유(draft_exists)가 code 로 나온다.
      begin
        v_res := drinks_request_develop(jsonb_strip_nulls(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'format_intent', v_format)));
        v_chain := jsonb_build_object('queued', true, 'kind', 'plan', 'request_id', v_res -> 'request_id', 'existing', v_res -> 'existing');
      exception when raise_exception then
        if sqlerrm not like 'drinks:%' then raise; end if;
        v_chain := jsonb_build_object('queued', false, 'kind', 'plan', 'code', split_part(sqlerrm, ':', 2), 'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
      end;
    end if;
    if v_first_chain is null then v_first_chain := v_chain; end if;
    v_picks := v_picks || jsonb_build_object('format_intent', v_format, 'maps_to', v_fmt, 'existing', v_existing, 'chain', v_chain);
  end loop;
  return jsonb_build_object('topic_id', t.id, 'created', v_created, 'status', t.status, 'formats', to_jsonb(v_formats),
    'format_intent', v_rep, 'maps_to', drinks_intent_format(v_rep), 'editorial_week', v_week, 'chain', v_first_chain, 'picks', v_picks);
end $$;

-- ─────────────────────────────────────────────────────────────
-- [승인] (운영자) — 그 형식의 제작안을 승인한다. 안쪽은 기존 함수 그대로라 검사가 똑같다. 하나라도 실패하면 전부 되돌아간다.
--   · researching: 근거 제출·승인 → 편성(그 형식) → 제작안 제출·승인 (0065 그대로).
--   · ready/selected(다른 형식이 먼저 승인됨): 근거는 지금 승인된 그 버전이어야 한다 → 편성 형식 합집합 → 제작안 제출·승인.
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_approve_content(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  t drink_topics; r drink_topic_reviews; d drink_deliverables; pr drink_plan_revisions; pk drink_topic_format_picks;
  v_amount numeric; v_note text := drinks_text(p, 'note'); v_id uuid; v_sel jsonb; v_planned jsonb;
  v_intent text := drinks_text(p, 'format_intent'); v_before text; v_formats text[]; v_week date; v_fresh boolean;
begin
  perform drinks_reap_develop();
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_topic_version'));
  v_before := t.status;
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
  -- 어느 형식을 승인하나: 입력 → 없으면 대표 형식(옛 호출).
  v_intent := coalesce(v_intent, drinks_representative_intent(t.id));
  if v_intent is null then perform drinks_fail('format_not_selected', '[이걸로]로 형식을 고른 소재만 한 번에 승인합니다 — 기존 탭을 쓰세요'); end if;
  select * into pk from drink_topic_format_picks where topic_id = t.id and format_intent = v_intent for update;
  if not found then perform drinks_fail('format_not_selected', '[이걸로]로 고르지 않은 형식입니다 — 형식을 먼저 더하세요'); end if;
  if drinks_intent_format(pk.format_intent) is null or pr.format <> drinks_intent_format(pk.format_intent) then
    perform drinks_fail('format_not_selected', '고른 형식의 제작안이 아닙니다 — 형식을 다시 고르거나 그 형식의 대본을 만드세요');
  end if;
  if pk.approved_at is not null then
    perform drinks_fail('invalid_state', '이 형식은 이미 승인됐습니다');
  end if;
  v_fresh := t.status = 'researching';
  if v_fresh then
    -- A. 근거가 아직 승인 전 — 0065 와 같은 검사.
    if t.current_review_id is distinct from r.id then perform drinks_fail('review_not_current', '최신 근거 버전이 아닙니다'); end if;
    if r.status not in ('draft','in_review') then perform drinks_fail('invalid_state', '이미 결정된 근거 버전입니다 — 기존 탭을 쓰세요'); end if;
    if not pr.drafted_from_unapproved or pr.plan_status <> 'draft' then
      perform drinks_fail('invalid_state', '승인 전 근거로 만든 작성 중 대본만 한 번에 승인합니다');
    end if;
  elsif t.status in ('ready','selected') then
    -- B. 다른 형식이 먼저 승인돼 근거는 이미 승인본이다. 그 승인본으로 쓴 작성 중 제작안만.
    if r.id is distinct from t.approved_review_id then perform drinks_fail('review_not_current', '지금 승인된 근거 버전이 아닙니다'); end if;
    if r.status <> 'approved' or r.revoked_at is not null or not drinks_approval_valid(r.id) then
      perform drinks_fail('review_not_approved', '승인되고 지금도 유효한 근거 버전으로만 제작안을 승인합니다');
    end if;
    if pr.plan_status <> 'draft' then perform drinks_fail('invalid_state', '작성 중인 제작안만 승인합니다'); end if;
  else
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재는 승인할 수 없습니다');
  end if;
  if d.current_revision_id is distinct from pr.id then perform drinks_fail('plan_not_current', '최신 대본이 아닙니다'); end if;
  if pr.blocked_at is not null then
    perform drinks_fail('plan_blocked', '이 대본을 만든 뒤 근거가 바뀌었습니다 — 이 근거로 대본을 다시 만들어야 승인할 수 있습니다');
  end if;
  -- ★ 대본이 기댄 근거가 바로 지금 승인하는(또는 승인된) 근거인가. 트리거가 차단하지만, 승인 직전에 값으로 한 번 더 잰다.
  --   승인된 근거로 쓴 옛 제작안(drinks_save_plan 경로)은 근거 값을 적지 않았다 — 승인본은 내용이 고정이라 버전 일치만 잰다.
  if pr.topic_review_id is distinct from r.id
      or ((pr.drafted_from_unapproved or pr.evidence_content_hash is not null)
          and pr.evidence_content_hash is distinct from drinks_evidence_content_hash(r.evidence_pack, r.brief)) then
    perform drinks_fail('plan_stale', '대본이 지금 근거 내용으로 만들어진 것이 아닙니다 — 이 근거로 대본을 다시 만드세요');
  end if;
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', '초안을 만드는 중입니다 — 끝난 뒤에 승인하세요');
  end if;
  -- 승인 금액: 기록만 한다. 결재를 열지 않는다. 상한은 유료 결재 1건 상한(0054)과 같다. 카드뉴스는 로컬 렌더 0원이라 금액을 받지 않는다.
  if pr.format = 'video' then
    v_amount := drinks_num(p, 'approved_amount_usd');
    if v_amount <= 0 or v_amount > (drinks_spend_limits() ->> 'max_cap_usd')::numeric then
      perform drinks_fail('invalid_input', '승인 금액은 0 보다 크고 $' || (drinks_spend_limits() ->> 'max_cap_usd') || ' 이하여야 합니다');
    end if;
  end if;

  if v_fresh then
    -- 1) 근거: 작성 중 → 검토 → 승인. drinks_review_action 이 필수 조건(주장별 확인·핵심 메시지·점수·인용·사용 조건)을 다시 잰다.
    if r.status = 'draft' then
      perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'submit'));
      select * into r from drink_topic_reviews where id = r.id;
    end if;
    perform drinks_review_action(jsonb_build_object('review_id', r.id, 'expected_version', r.version, 'action', 'approve', 'reason', v_note));
    select * into r from drink_topic_reviews where id = r.id;
    v_formats := array[pr.format];
    v_week := pk.editorial_week;
  else
    -- 1') 근거는 이미 승인본. 편성 형식에 이 형식을 더한다(합집합). 편성 주차는 이미 편성됐으면 그대로, 아니면 이 형식의 선택 주차.
    v_formats := coalesce(t.selected_formats, '{}'::text[]);
    if not pr.format = any(v_formats) then v_formats := v_formats || pr.format; end if;
    v_week := case when t.status = 'selected' then t.editorial_week else pk.editorial_week end;
  end if;
  -- 2) 편성. drinks_select 가 65점 기준·형식 적합성·필수 주장을 다시 잰다.
  select * into t from drink_topics where id = t.id;
  v_sel := drinks_select(jsonb_build_object('topic_id', t.id, 'expected_version', t.version, 'review_id', r.id,
    'review_input_hash', r.approved_hash, 'formats', to_jsonb(v_formats), 'editorial_week', to_char(v_week, 'YYYY-MM-DD'),
    'score_exception_reason', drinks_text(p, 'score_exception_reason'), 'format_exceptions', coalesce(p -> 'format_exceptions', '{}'::jsonb)));
  -- 3) 대본: 제작안 해시를 승인된 근거 기준으로 다시 잰다(본문은 그대로) → 제출 → 승인.
  update drink_plan_revisions set updated_at = now() where id = pr.id returning * into pr;
  perform drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'submit'));
  select * into pr from drink_plan_revisions where id = pr.id;
  v_planned := drinks_plan_action(jsonb_build_object('revision_id', pr.id, 'expected_version', pr.version, 'action', 'approve', 'reason', v_note));
  select * into pr from drink_plan_revisions where id = pr.id;

  update drink_topic_format_picks set approved_at = now(), approved_amount_usd = v_amount where topic_id = t.id and format_intent = pk.format_intent;
  update drink_topic_picks set approved_at = now(), approved_amount_usd = v_amount where topic_id = t.id and format_intent = pk.format_intent and approved_at is null;
  select * into t from drink_topics where id = t.id;
  perform drinks_log(t.id, 'topic', t.id, 'content_approved', v_before, t.status, pr.id::text, v_note,
    jsonb_build_object('review_id', r.id, 'review_hash', r.approved_hash, 'plan_revision_id', pr.id, 'plan_hash', pr.approved_hash,
      'format_intent', pk.format_intent, 'approved_amount_usd', v_amount, 'spend_approval_opened', false, 'formats', to_jsonb(v_formats)));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version, 'review_id', r.id, 'review_status', r.status,
    'plan_revision_id', pr.id, 'plan_status', pr.plan_status, 'selected_formats', v_sel -> 'selected_formats',
    'editorial_week', v_sel -> 'editorial_week', 'approved_amount_usd', v_amount, 'coverage', v_planned -> 'coverage',
    'format_intent', pk.format_intent, 'spend_approval_opened', false);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 형식 표를 읽어야 하는 기존 함수 (0066·0067 정의 + 형식 표)
-- ─────────────────────────────────────────────────────────────

-- 밈 제작안의 주인 검사: 두 번째 형식이 밈일 수 있어 형식 표를 본다.
create or replace function drinks_meme_check_owner(p_card uuid, p_topic uuid) returns void language plpgsql stable set search_path = public, pg_temp as $$
declare c drink_ig_cards;
begin
  if (p_card is null) = (p_topic is null) then perform drinks_fail('invalid_input', '밈 카드 또는 소재 중 하나를 지정하세요'); end if;
  if p_card is not null then
    select * into c from drink_ig_cards where id = p_card;
    if not found then perform drinks_fail('not_found', '카드를 찾지 못했습니다'); end if;
    if c.decision is distinct from 'use' then perform drinks_fail('invalid_state', '[쓰자]로 고른 카드만 제작안을 만듭니다'); end if;
    if drinks_ig_card_precision(p_card) <> 'precise' then
      perform drinks_fail('card_not_precise', '참고 카드입니다 - 원본 릴스를 보고 비트 수·컷 길이·반전 시점을 넣으면 정밀 틀이 됩니다');
    end if;
  elsif not exists (select 1 from drink_topic_format_picks pk where pk.topic_id = p_topic and pk.format_intent = 'meme') then
    perform drinks_fail('invalid_state', '밈형으로 고른 소재가 아닙니다');
  end if;
end $$;

-- 설명형 판정: 영상 제작안 + 그 소재가 설명형을 골랐다(몇 번째 형식이든). 백필 덕에 옛 단일 선택도 형식 표에 있다.
create or replace function drinks_plan_is_explainer(p_plan uuid) returns boolean language sql stable set search_path = public, pg_temp as $$
  select exists (select 1 from drink_plan_revisions pl join drink_topic_format_picks fp on fp.topic_id = pl.topic_id
                 where pl.id = p_plan and pl.format = 'video' and fp.format_intent = 'explainer')
$$;

create or replace function drinks_explainer_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_plan uuid := drinks_uuid(p, 'plan_revision_id'); e drink_explainer_episodes; pl drink_plan_revisions;
begin
  select * into pl from drink_plan_revisions where id = v_plan;
  if not found then perform drinks_fail('not_found', '제작안을 찾지 못했습니다'); end if;
  select * into e from drink_explainer_episodes where plan_revision_id = v_plan;
  return jsonb_build_object(
    'is_explainer', drinks_plan_is_explainer(v_plan),
    'approved_amount_usd', (select approved_amount_usd from drink_topic_format_picks where topic_id = pl.topic_id and format_intent = 'explainer'),
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

-- ─────────────────────────────────────────────────────────────
-- 비용 예상 (읽기만) — engine/drinks_develop.estimate_usd 와 같은 공식: 입력 글자/글자당토큰 × 입력 단가 + 출력 상한 × 출력 단가,
-- 결제 실패 대체 모델이 더 비싸면 그 단가. 상수는 engine/config.py 와 같아야 한다(tests/test_drinks_develop.py 가 대조).
-- 단가표에 없는 모델·밈은 null 이다 — **모르는 비용을 0 으로 쓰지 않는다**.
-- ─────────────────────────────────────────────────────────────

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
    'plan_prompt_chars', 12000)                -- 대본 프롬프트 뼈대 글자(근거 묶음은 따로 더한다) — 예상 상한용 가정값
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
  v_remaining numeric;
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
      v_est := least(round(v_est * (prm ->> 'max_sources')::numeric + 0.00005, 4), v_cap);
      v_est := greatest(v_est, 0.0001);
      v_items := v_items || jsonb_build_object('kind', 'evidence', 'format_intent', null, 'est_usd', v_est, 'known', true, 'model', prm ->> 'extract_model', 'shared', true);
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

-- ─────────────────────────────────────────────────────────────
-- 작업 단위 뷰 (§3-3) — 소재×형식 한 줄 + 카드 밈 제작안 한 줄. LATERAL '현재 1건' 조회라 행이 늘지 않는다.
--   현재 근거 = 소재의 작업 중 버전(없으면 승인본) · 현재 제작안 = deliverable.current_revision_id · 작업 = 최근 1 ·
--   발행 요청 = 끝나지 않은 것 우선, 없으면 최근 · 개발 요청 = 이 형식의 대본 요청 또는 근거 요청 중 최근 1.
-- ─────────────────────────────────────────────────────────────

create or replace view drink_work_items with (security_invoker = true) as
with units as (
  select 'topic:' || fp.topic_id::text || ':' || fp.format_intent as unit_id, fp.topic_id, t.title, t.question, t.status as topic_status, t.version as topic_version,
    fp.format_intent, 'topic'::text as source, fp.editorial_week, fp.approved_at as pick_approved_at, fp.approved_amount_usd as pick_amount_usd,
    null::uuid as card_draft_id, fp.updated_at as pick_updated_at, t.current_review_id, t.approved_review_id
  from drink_topic_format_picks fp join drink_topics t on t.id = fp.topic_id
  union all
  select 'meme_card:' || m.id::text, null::uuid, c.name, null::text, null::text, null::int,
    'meme'::text, 'card'::text, null::date, null::timestamptz, null::numeric,
    m.id, m.updated_at, null::uuid, null::uuid
  from drink_meme_drafts m join drink_ig_cards c on c.id = m.card_id
  where m.card_id is not null
)
select u.unit_id, u.topic_id, u.title, u.question, u.topic_status, u.topic_version, u.format_intent, u.source,
  u.editorial_week, u.pick_approved_at, u.pick_amount_usd,
  rv.id as review_id, rv.status as review_status,
  (rv.id is not null and rv.status = 'approved' and rv.revoked_at is null and drinks_approval_valid(rv.id)) as review_valid, rv.version as review_version,
  dq.kind as develop_kind, dq.status as develop_status, dq.id as develop_request_id, dq.error_code as develop_error_code,
  pl.id as plan_revision_id, pl.plan_status, (pl.id is not null and pl.blocked_at is not null) as plan_blocked, pl.version as plan_version, pl.format as plan_format,
  jb.id as job_id, jb.status as job_status, jb.error_code as job_error_code,
  ep.state as explainer_state,
  orv.id as output_review_id, orv.status as output_review_status, coalesce(ov.currently_usable, false) as output_usable,
  mm.id as meme_draft_id, mm.status as meme_status, mm.sync_grade as meme_sync_grade, mm.external_url as meme_external_url,
  pb.id as pub_request_id, pb.status as pub_status, pb.pause_code as pub_pause_code, pb.publish_at as pub_publish_at, pb.external_url as pub_external_url, pb.version as pub_version,
  coalesce(ep.state = 'unknown_billed', false) or coalesce(pb.status = 'unknown', false)
    or coalesce(dq.status = 'running' and dq.lease_expires_at < now(), false) as unknown_billed,
  (exists (select 1 from drink_develop_holds h where h.status = 'held'
      and ((h.request_id = dq.id and dq.status not in ('queued','running')) or (h.meme_draft_id = mm.id and mm.status not in ('text_running','rendering'))))
   or exists (select 1 from drink_spend_holds h join drink_spend_approvals a on a.id = h.approval_id
      where a.plan_revision_id = pl.id and h.status = 'held'
        and not exists (select 1 from drink_production_jobs j where j.id = h.job_id and j.status = 'running' and j.lease_expires_at > now()))) as orphan_hold,
  greatest(u.pick_updated_at, pl.updated_at, coalesce(dq.finished_at, dq.started_at, dq.created_at), coalesce(jb.finished_at, jb.started_at, jb.created_at),
    ep.updated_at, pb.updated_at, mm.updated_at) as updated_at
from units u
left join lateral (select r.* from drink_topic_reviews r where r.id = coalesce(u.current_review_id, u.approved_review_id)) rv on true
left join lateral (
  select q.* from drink_develop_requests q
  where u.source = 'topic' and u.format_intent in ('explainer','card') and q.topic_id = u.topic_id
    and (q.kind = 'evidence' or coalesce(q.format_intent, drinks_representative_intent(u.topic_id)) = u.format_intent)
  order by q.created_at desc limit 1) dq on true
left join lateral (
  select pr.* from drink_deliverables d join drink_plan_revisions pr on pr.id = d.current_revision_id
  where u.source = 'topic' and d.topic_id = u.topic_id and d.format = drinks_intent_format(u.format_intent) and d.locale = 'ko'
  limit 1) pl on true
left join lateral (select j.* from drink_production_jobs j where j.plan_revision_id = pl.id order by j.created_at desc limit 1) jb on true
left join lateral (select e.* from drink_explainer_episodes e where e.plan_revision_id = pl.id) ep on true
left join lateral (select o.* from drink_output_reviews o where o.plan_revision_id = pl.id order by o.created_at desc limit 1) orv on true
left join lateral (select v.currently_usable from drink_output_validity v where v.review_id = orv.id) ov on true
left join lateral (
  select m.* from drink_meme_drafts m
  where (u.source = 'card' and m.id = u.card_draft_id) or (u.source = 'topic' and u.format_intent = 'meme' and m.topic_id = u.topic_id)
  order by (m.status not in ('rejected','stopped','failed','posted_manual')) desc, m.updated_at desc limit 1) mm on true
left join lateral (
  select b.* from drink_publication_requests b
  where (mm.id is not null and b.meme_draft_id = mm.id) or (pl.id is not null and b.plan_revision_id = pl.id)
  order by (b.status in ('published','canceled')) asc, b.created_at desc limit 1) pb on true;

-- 소재 하나의 형식별 요약(작업공간·홈 입력).
create or replace function drinks_topic_formats(p jsonb) returns jsonb language plpgsql stable set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id');
begin
  if not exists (select 1 from drink_topics where id = v_topic) then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  return jsonb_build_object('topic_id', v_topic,
    'representative', drinks_representative_intent(v_topic),
    'picks', coalesce((select jsonb_agg(to_jsonb(k) order by k.created_at, k.format_intent) from drink_topic_format_picks k where k.topic_id = v_topic), '[]'::jsonb),
    'items', coalesce((select jsonb_agg(to_jsonb(w) order by w.format_intent) from drink_work_items w where w.topic_id = v_topic), '[]'::jsonb),
    'selected_formats', (select to_jsonb(selected_formats) from drink_topics where id = v_topic));
end $$;

-- 작업 단위 목록. filter: approve(사람 결정 대기) · publish(게시 단계) · all. 최종 판단은 web/lib/drinks/work/decision.ts 가 한다 — 여기서는 거르기만.
create or replace function drinks_work_items(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(to_jsonb(w) order by w.updated_at desc nulls last, w.unit_id), '[]'::jsonb)
  from (
    select * from drink_work_items w
    where case coalesce(drinks_text(p, 'filter'), 'all')
      when 'approve' then (w.plan_status in ('draft','in_review') and not w.plan_blocked) or w.review_status in ('draft','in_review')
        or w.pub_status = 'awaiting_approval' or w.meme_status = 'draft' or w.output_review_status = 'pending'
      when 'publish' then w.output_usable or w.pub_status in ('approved','scheduled','paused','failed','unknown','publishing')
        or w.meme_status in ('publish_waiting','manual_audio')
      else true end
    order by w.updated_at desc nulls last, w.unit_id
    limit least(greatest(coalesce(drinks_int(p, 'limit', false), 100), 1), 500)) w
$$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: anon·authenticated 에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────

alter table drink_topic_format_picks enable row level security;
revoke all on table drink_topic_format_picks from anon, authenticated;
grant select, insert, update on table drink_topic_format_picks to service_role;
revoke all on table drink_work_items from anon, authenticated;
grant select on table drink_work_items to service_role;

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
--   select has_table_privilege('anon', 'public.drink_topic_format_picks', 'SELECT');   → false
--   select has_table_privilege('anon', 'public.drink_work_items', 'SELECT');           → false
--   select count(*) from drink_topic_picks k where not exists (select 1 from drink_topic_format_picks f where f.topic_id = k.topic_id and f.format_intent = k.format_intent);  → 0
