-- 주류 공장 — 독립 리뷰(2026-11-04) 후속 수정. 리뷰 기준 커밋 03de16b. 기록: docs/deviation-drinks-review-fixes-2026-11-04.md
--
-- ★ 파일만 있다. 운영 DB 적용은 따로 결재받는다. 0050~0068·0070 이 먼저 적용돼 있어야 한다.
--   0069 는 없는 번호다(다른 작업 몫으로 비워 둔 자리) — 그 자리를 쓰지 않고 0071 로 간다.
--
-- 무엇이 바뀌나 — 왜
--   A. (R4) 설명형 시도와 가잡기가 끊기던 두 자리.
--      ① drinks_explainer_open_attempt 가 hold_id 를 받아 **시도 행을 만들 때** 같이 적는다. 예전엔 generating 때 적어서,
--         가잡기 → 시도 행 → (generating 전 중단)이면 sweep 이 시도를 failed_unbilled 로 닫아도 가잡기가 영영 held 로 남았다.
--      ② sweep 이 "종결된 시도 + 아직 held 인 가잡기"를 찾아 정산한다(failed_unbilled → 해제, failed_billed → 확정).
--         failed_billed 기록 직후 정산 RPC 가 실패하면 $0.4071 이 held 로 남고 sweep 처리 0건이던 상태를 복구한다.
--         연결이 없는 옛 시도(hold_id null)는 같은 결재·같은 항목 키(= 후보 id)의 held 가잡기를 찾아 잇는다.
--      ③ drinks_spend_orphan_holds(조회만) / drinks_close_orphan_hold(운영자만): 어떤 시도에도 묶이지 않은 held 가잡기
--         (예: R1 의 결과 불명 시작 그림)를 찾아 billed/void 로 닫는다. **자동으로 해제하지 않는다** — 보냈을 수 있기 때문이다.
--   B. (R3) 밈 게시 요청의 근거 계약. drinks_pub_block 이 밈에 대해 "게시 대기 상태"만 보고 근거 유효성은 보지 않아,
--      근거 review 를 철회해도 claim 이 성공하고 before_publish 가 proceed=true 였다. 이제 밈 제작안의 승인 지문 일치와
--      drinks_meme_blockers(0066, 제작 직전에 쓰는 같은 규칙)를 발행 생성·승인·예약·claim·게시 직전 모두에서 본다.
--   C. (R2) Apify 월 상한 동시 실행. drinks_apify_request 가 잠금 없이 월 누적을 세서, 두 요청이 동시에 들어오면 둘 다 통과할 수
--      있었다. 요청 행을 넣는 순간 트랜잭션 잠금을 잡고 다시 센다(트리거).
--   D. (R6) 게시 가능 시각. 게시 크론은 KST 07:00~23:30(30분마다)만 도는데 예약은 새벽도 받아서, 00:00 예약은 다음 크론(07:00)이
--      2시간 유예를 넘겨 반드시 멈췄다. 예약 시각을 크론 창 안으로 제한한다(drinks_publish_window, engine/config.py 와 대조).
--      24시간 크론으로 넓힐지는 운영자 결정이다(docs/결재계획_릴스3형식_2026-11-03.md).
--
-- 되돌리기
--   A. 0062 의 drinks_explainer_open_attempt, 0067 의 drinks_explainer_sweep_stale 을 다시 실행한다.
--      drop function drinks_spend_orphan_holds(jsonb); drop function drinks_close_orphan_hold(jsonb);
--   B. 0068 의 drinks_pub_block 을 다시 실행한다. drop trigger drink_pub_meme_guard_ins on drink_publication_requests;
--      drop trigger drink_pub_meme_guard_upd on drink_publication_requests; drop function drink_pub_meme_guard(); drop function drinks_pub_meme_block(uuid);
--   C. drop trigger drink_apify_month_guard on drink_apify_requests; drop function drink_apify_month_guard();
--   D. drop trigger drink_pub_window_guard on drink_publication_requests; drop function drink_pub_window_guard();
--      drop function drinks_publish_window_ok(timestamptz); drop function drinks_publish_window();

-- ─────────────────────────────────────────────────────────────
-- A. 설명형 시도 ↔ 가잡기 (R4)
-- ─────────────────────────────────────────────────────────────

-- 0062 정의 + hold_id. 가잡기는 같은 결재·같은 항목 키(후보 id)·held 여야 한다(다른 돈을 잘못 잇지 않게).
create or replace function drinks_explainer_open_attempt(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare c drink_explainer_candidates; s drink_explainer_slots; ap drink_spend_approvals; v_m int; v_id text; v_prev drink_explainer_attempts;
  lim jsonb := drinks_explainer_limits(); v_provider text := drinks_text(p, 'provider'); v_hold uuid := drinks_uuid(p, 'hold_id', false);
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
  if v_hold is not null and not exists (select 1 from drink_spend_holds h where h.id = v_hold and h.approval_id = ap.id
      and h.item_key = c.candidate_id and h.status = 'held') then
    perform drinks_fail('invalid_input', '이 후보·결재의 가잡기가 아닙니다');
  end if;
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
  select * into v_prev from drink_explainer_attempts where candidate_id = c.candidate_id order by m desc limit 1;
  if found and v_prev.state in ('failed_billed','closed_billed') and v_prev.approval_id = ap.id then
    perform drinks_fail('retry_needs_new_approval', '청구된 시도 뒤의 재시도는 새 결재로만 합니다');
  end if;
  v_id := c.candidate_id || '#a' || v_m::text;
  insert into drink_explainer_attempts (attempt_id, candidate_id, slot_id, m, spec_hash, idempotency_key, approval_id, provider, hold_id)
  values (v_id, c.candidate_id, c.slot_id, v_m, s.spec_hash, drinks_explainer_idem(v_id, s.spec_hash), ap.id, v_provider, v_hold);
  update drink_explainer_candidates set status = 'attempting', updated_at = now() where candidate_id = c.candidate_id;
  perform drink_explainer_slot_advance(c.slot_id, 'requested');
  return jsonb_build_object('attempt_id', v_id, 'm', v_m, 'idempotency_key', drinks_explainer_idem(v_id, s.spec_hash), 'spec_hash', s.spec_hash);
end $$;

-- 시도가 가리키는 가잡기. 연결이 없는 옛 행은 같은 결재·같은 후보의 held 가잡기를 찾는다(하나일 때만 — 둘 이상이면 사람이 본다).
create or replace function drink_explainer_attempt_hold(t drink_explainer_attempts) returns uuid language sql stable set search_path = public, pg_temp as $$
  select coalesce(t.hold_id, (select min(h.id::text)::uuid from drink_spend_holds h where h.approval_id = t.approval_id and h.item_key = t.candidate_id
    and h.status = 'held' having count(*) = 1))
$$;

-- 0067 정의 + (1) 연결 없는 requested 의 가잡기 해제 (2) 종결 시도 + held 가잡기 정산. 다시 부르지 않는다.
create or replace function drinks_explainer_sweep_stale(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_sec int := coalesce(drinks_int(p, 'older_than_sec', false), 1800); v_unknown int := 0; v_unbilled int := 0; v_billed int := 0; v_repaired int := 0;
  r record; v_hold uuid; v_att drink_explainer_attempts;
begin
  if v_sec < 60 then perform drinks_fail('invalid_input', 'older_than_sec 는 60 이상입니다'); end if;
  for r in select t.attempt_id, t.candidate_id, t.slot_id, t.state, t.hold_id, t.actual_usd, s.plan_revision_id from drink_explainer_attempts t join drink_explainer_slots s on s.slot_id = t.slot_id
      where t.state in ('requested','generating','received','probed') and t.updated_at < now() - make_interval(secs => v_sec) for update of t loop
    select * into v_att from drink_explainer_attempts where attempt_id = r.attempt_id;
    v_hold := drink_explainer_attempt_hold(v_att);
    if r.state = 'generating' then
      update drink_explainer_attempts set state = 'unknown_billed', updated_at = now(), error_code = coalesce(error_code, 'worker_lost'), hold_id = coalesce(hold_id, v_hold)
        where attempt_id = r.attempt_id;
      update drink_explainer_episodes set state = 'unknown_billed', last_code = 'unknown_billed', last_message = '워커가 호출 중에 끊겼습니다: ' || r.attempt_id
        where plan_revision_id = r.plan_revision_id and state in ('approved','buying');
      v_unknown := v_unknown + 1;
    elsif r.state = 'requested' then
      update drink_explainer_attempts set state = 'failed_unbilled', updated_at = now(), error_code = coalesce(error_code, 'worker_lost'), hold_id = coalesce(hold_id, v_hold)
        where attempt_id = r.attempt_id;
      update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = r.candidate_id;
      if v_hold is not null and exists (select 1 from drink_spend_holds h where h.id = v_hold and h.status = 'held') then
        perform drinks_settle_spend(jsonb_build_object('hold_id', v_hold, 'outcome', 'released', 'note', '호출 전에 워커가 끊김'));
      end if;
      v_unbilled := v_unbilled + 1;
    else
      update drink_explainer_attempts set state = 'failed_billed', updated_at = now(), error_code = coalesce(error_code, 'worker_lost'), hold_id = coalesce(hold_id, v_hold)
        where attempt_id = r.attempt_id;
      update drink_explainer_candidates set status = 'failed', updated_at = now() where candidate_id = r.candidate_id;
      if v_hold is not null and exists (select 1 from drink_spend_holds h where h.id = v_hold and h.status = 'held') then
        perform drinks_settle_spend(jsonb_build_object('hold_id', v_hold, 'outcome', 'settled',
          'actual_usd', coalesce(r.actual_usd, (select h.est_usd from drink_spend_holds h where h.id = v_hold)), 'note', '받은 뒤 워커가 끊김(청구 유력)'));
      end if;
      perform drink_explainer_candidate_settle(r.candidate_id);
      v_billed := v_billed + 1;
    end if;
  end loop;
  -- (2) 종결된 시도인데 가잡기가 held 로 남은 것(정산 RPC 가 응답을 잃었다). failed_unbilled = 안 보냄 → 해제, failed_billed = 확정.
  for r in select t.attempt_id, t.state, t.actual_usd from drink_explainer_attempts t
      where t.state in ('failed_unbilled','failed_billed') and t.updated_at < now() - make_interval(secs => v_sec) for update of t loop
    select * into v_att from drink_explainer_attempts where attempt_id = r.attempt_id;
    v_hold := drink_explainer_attempt_hold(v_att);
    continue when v_hold is null or not exists (select 1 from drink_spend_holds h where h.id = v_hold and h.status = 'held');
    if r.state = 'failed_unbilled' then
      perform drinks_settle_spend(jsonb_build_object('hold_id', v_hold, 'outcome', 'released', 'note', '종결(안 보냄) 뒤 해제 기록이 빠짐 — sweep 복구'));
    else
      perform drinks_settle_spend(jsonb_build_object('hold_id', v_hold, 'outcome', 'settled',
        'actual_usd', coalesce(r.actual_usd, (select h.est_usd from drink_spend_holds h where h.id = v_hold)), 'note', '종결(청구) 뒤 확정 기록이 빠짐 — sweep 복구'));
    end if;
    update drink_explainer_attempts set hold_id = coalesce(hold_id, v_hold) where attempt_id = r.attempt_id;
    v_repaired := v_repaired + 1;
  end loop;
  return jsonb_build_object('unknown_billed', v_unknown, 'failed_unbilled', v_unbilled, 'failed_billed', v_billed, 'repaired_holds', v_repaired,
    'orphan_holds', jsonb_array_length(drinks_spend_orphan_holds(jsonb_build_object('older_than_sec', v_sec)) -> 'holds'));
end $$;

-- 어느 시도에도 묶이지 않은 held 가잡기(조회만). 시작 그림 결과 불명(R1)·시도 행을 만들기 전 중단·옛 행이 여기 나온다.
create or replace function drinks_spend_orphan_holds(p jsonb) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('holds', coalesce(jsonb_agg(jsonb_build_object('hold_id', h.id, 'approval_id', h.approval_id, 'item_key', h.item_key, 'kind', h.kind,
      'provider', h.provider, 'est_usd', h.est_usd, 'note', h.note, 'created_at', h.created_at,
      'job_running', exists (select 1 from drink_production_jobs j where j.id = h.job_id and j.status = 'running' and j.lease_expires_at > now()))
      order by h.created_at), '[]'))
  from drink_spend_holds h
  where h.status = 'held' and h.created_at < now() - make_interval(secs => greatest(60, coalesce(drinks_int(p, 'older_than_sec', false), 1800)))
    and not exists (select 1 from drink_explainer_attempts t where t.hold_id = h.id)
    and not exists (select 1 from drink_explainer_attempts t where t.hold_id is null and t.approval_id = h.approval_id and t.candidate_id = h.item_key)
$$;

-- 운영자가 고아 가잡기를 닫는다: billed = 그 금액으로 확정, void = 해제. 워커가 아직 그 작업을 쥐고 있거나 시도에 묶여 있으면 거절한다
-- (묶인 것은 drinks_explainer_close_unknown·sweep 이 닫는다). 정산은 drinks_settle_spend 한 번 — 이미 닫혔으면 invalid_state 로 거절된다(이중 정산 없음).
create or replace function drinks_close_orphan_hold(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare h drink_spend_holds; v_res text := drinks_text(p, 'resolution'); v_by text := drinks_text(p, 'closed_by'); v_note text := drinks_text(p, 'note');
  v_usd numeric := nullif(p ->> 'actual_usd', '')::numeric;
begin
  if v_res is null or v_res not in ('billed','void') then perform drinks_fail('invalid_input', 'resolution 은 billed 또는 void 입니다'); end if;
  if v_by is null or lower(v_by) in ('worker','system','auto') then perform drinks_fail('invalid_input', '운영자가 닫아야 합니다(closed_by)'); end if;
  if v_note is null then perform drinks_fail('invalid_input', '닫는 이유(note)가 필요합니다 — 청구 내역을 무엇으로 확인했는지 적으세요'); end if;
  if v_res = 'billed' and (v_usd is null or v_usd < 0) then perform drinks_fail('invalid_input', 'billed 로 닫으려면 금액(actual_usd)이 필요합니다'); end if;
  select * into h from drink_spend_holds where id = drinks_uuid(p, 'hold_id') for update;
  if not found then perform drinks_fail('not_found', '지출 기록을 찾지 못했습니다'); end if;
  if h.status <> 'held' then perform drinks_fail('invalid_state', '이미 닫힌 지출입니다'); end if;
  if exists (select 1 from drink_explainer_attempts t where t.hold_id = h.id or (t.hold_id is null and t.approval_id = h.approval_id and t.candidate_id = h.item_key)) then
    perform drinks_fail('invalid_state', '설명형 시도에 묶인 가잡기입니다 — drinks_explainer_close_unknown 이나 sweep 으로 닫습니다');
  end if;
  if exists (select 1 from drink_production_jobs j where j.id = h.job_id and j.status = 'running' and j.lease_expires_at > now()) then
    perform drinks_fail('invalid_state', '워커가 아직 이 작업을 쥐고 있습니다 — 끝나거나 임대가 끝난 뒤 닫습니다');
  end if;
  return drinks_settle_spend(jsonb_build_object('hold_id', h.id, 'outcome', case v_res when 'billed' then 'settled' else 'released' end,
    'actual_usd', v_usd, 'note', '운영자(' || left(v_by, 60) || ')가 ' || v_res || ' 로 닫음: ' || left(v_note, 300)));
end $$;

-- ─────────────────────────────────────────────────────────────
-- B. 밈 게시 요청의 근거 계약 (R3)
-- ─────────────────────────────────────────────────────────────

-- 밈 제작안이 지금도 승인된 그대로이고 규칙(근거 유효성 포함)을 지키나. 막히면 첫 사유 코드, 아니면 null.
create or replace function drinks_pub_meme_block(p_draft uuid) returns text language plpgsql stable set search_path = public, pg_temp as $$
declare d drink_meme_drafts; v jsonb;
begin
  if p_draft is null then return null; end if;
  select * into d from drink_meme_drafts where id = p_draft;
  if not found then return 'meme_not_found'; end if;
  if d.approved_digest is null or d.approved_digest is distinct from drinks_meme_digest(d.spec, d.evidence_review_id) then return 'meme_digest_changed'; end if;
  v := drinks_meme_blockers(d.spec, d.evidence_review_id, d.card_id);
  if jsonb_array_length(v) > 0 then return coalesce(v -> 0 ->> 'code', 'meme_blocked'); end if;
  return null;
end $$;

-- 0068 정의 + 밈 근거·승인 지문(drinks_pub_meme_block). claim·before_publish·예약·화면이 모두 이 함수를 본다.
create or replace function drinks_pub_block(p_id uuid) returns text language sql stable set search_path = public, pg_temp as $$
  select case
    when r.id is null then 'not_found'
    when r.approval_digest is distinct from drinks_pub_digest(r) then 'digest_changed'
    when r.meme_draft_id is null and not coalesce((select v.currently_usable from drink_output_validity v where v.review_id = r.output_review_id), false)
      then 'output_not_usable'
    when r.meme_draft_id is not null and not exists (select 1 from drink_meme_drafts d where d.id = r.meme_draft_id and d.status = 'publish_waiting'
        and d.sync_grade = 'sync_free' and coalesce(d.spec -> 'audio' ->> 'mode', '') <> 'app_manual') then 'meme_not_publishable'
    -- 0071(R3): 근거가 철회됐거나 승인 뒤 제작안이 바뀌었으면 게시하지 않는다
    when r.meme_draft_id is not null and drinks_pub_meme_block(r.meme_draft_id) is not null then drinks_pub_meme_block(r.meme_draft_id)
    when drinks_pub_ai_label_missing(r) then 'ai_label_missing'
    when a.status = 'reauth_required' then 'account_reauth'
    when a.status <> 'active' then 'account_not_active'
    when not a.publish_enabled then 'publish_disabled'
    when a.external_account_id <> r.target_external_account_id then 'account_mismatch'
    when drinks_pub_needs_audio(r) and coalesce(r.audio ->> 'mode', 'none') = 'none' then 'audio_missing'
    when r.audio ->> 'mode' = 'ig_audio' and a.connection not in ('facebook_login','fake') then 'audio_connection_unsupported'
    when r.audio ->> 'mode' = 'ig_audio' and r.audio ->> 'sync_grade' is distinct from 'sync_free' then 'audio_sync_required'
    when r.meme_draft_id is not null and r.audio ->> 'mode' = 'ig_audio'
      and r.audio ->> 'audio_id' is distinct from (select d.spec -> 'audio' ->> 'audio_id' from drink_meme_drafts d where d.id = r.meme_draft_id) then 'audio_mismatch'
    else null end
  from (select 1) x left join drink_publication_requests r on r.id = p_id
    left join drink_social_accounts a on a.id = r.account_id
$$;

-- 발행안을 만들 때·승인 요청·승인·예약으로 넘어갈 때 밈 근거를 다시 본다(취소·멈춤으로 가는 길은 막지 않는다).
create or replace function drink_pub_meme_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare v_block text;
begin
  if new.meme_draft_id is null then return new; end if;
  if tg_op = 'INSERT' or (new.status in ('awaiting_approval','approved','scheduled') and new.status is distinct from old.status) then
    v_block := drinks_pub_meme_block(new.meme_draft_id);
    if v_block is not null then
      perform drinks_fail('not_publishable', '밈 제작안의 근거·승인이 지금은 유효하지 않습니다: ' || v_block);
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_pub_meme_guard_ins on drink_publication_requests;
create trigger drink_pub_meme_guard_ins before insert on drink_publication_requests for each row execute function drink_pub_meme_guard();
drop trigger if exists drink_pub_meme_guard_upd on drink_publication_requests;
create trigger drink_pub_meme_guard_upd before update on drink_publication_requests for each row execute function drink_pub_meme_guard();

-- ─────────────────────────────────────────────────────────────
-- C. Apify 월 상한 — 동시 요청 (R2)
-- ─────────────────────────────────────────────────────────────

-- 요청 행이 들어가는 순간 잠그고 다시 센다. plpgsql 의 각 문장은 새 스냅샷을 쓰므로, 잠금을 잡은 뒤의 합계에는
-- 먼저 커밋된 다른 요청이 들어 있다. 기존 행 갱신(정산)에는 걸지 않는다 — 나간 돈은 기록돼야 한다.
create or replace function drink_apify_month_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
declare v_spent numeric; v_cap numeric := (drinks_apify_limits() ->> 'month_cap_usd')::numeric;
begin
  perform pg_advisory_xact_lock(hashtext('drinks_apify_month:' || new.month_key::text));
  v_spent := drinks_apify_month_spent(new.month_key);
  if v_spent + new.cap_usd > v_cap then
    perform drinks_fail('apify_budget_exhausted', '이달 Apify 상한 $' || v_cap || ' 에 닿았습니다(쓴 돈·예약 $' || round(v_spent, 3) || ') — 다음 달까지 실행하지 않습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_apify_month_guard on drink_apify_requests;
create trigger drink_apify_month_guard before insert on drink_apify_requests for each row execute function drink_apify_month_guard();

-- ─────────────────────────────────────────────────────────────
-- D. 게시 가능 시각 (R6) — engine/config.py DRINKS_PUBLISH_WINDOW 와 .github/workflows/drinks-publish.yml 크론과 같아야 한다
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_publish_window() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object('timezone', 'Asia/Seoul', 'start', '07:00', 'end', '23:30')
$$;

create or replace function drinks_publish_window_ok(p_at timestamptz) returns boolean language sql stable set search_path = public, pg_temp as $$
  select p_at is null or ((p_at at time zone (drinks_publish_window() ->> 'timezone'))::time
    between (drinks_publish_window() ->> 'start')::time and (drinks_publish_window() ->> 'end')::time)
$$;

-- 승인 요청·예약·다시 예약으로 넘어갈 때 예약 시각이 크론 창 밖이면 거절한다(그 시각엔 아무 워커도 돌지 않아 2시간 유예를 넘긴다).
create or replace function drink_pub_window_guard() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.status in ('awaiting_approval','scheduled') and new.status is distinct from old.status and not drinks_publish_window_ok(new.publish_at) then
    perform drinks_fail('outside_publish_window', '게시 시각은 KST ' || (drinks_publish_window() ->> 'start') || '~' || (drinks_publish_window() ->> 'end')
      || ' 사이여야 합니다(게시 워커가 그 시간에만 돕니다) — 시각을 바꿔 다시 요청하세요');
  end if;
  return new;
end $$;
drop trigger if exists drink_pub_window_guard on drink_publication_requests;
create trigger drink_pub_window_guard before update on drink_publication_requests for each row execute function drink_pub_window_guard();

-- ─────────────────────────────────────────────────────────────
-- 권한 (0050 방향: 공개 역할에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname in ('drinks_explainer_open_attempt','drink_explainer_attempt_hold','drinks_explainer_sweep_stale',
      'drinks_spend_orphan_holds','drinks_close_orphan_hold','drinks_pub_meme_block','drinks_pub_block','drink_pub_meme_guard',
      'drink_apify_month_guard','drinks_publish_window','drinks_publish_window_ok','drink_pub_window_guard')
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
  end loop;
end $$;
