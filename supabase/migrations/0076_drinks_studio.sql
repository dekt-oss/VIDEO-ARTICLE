-- 주류 콘텐츠 스튜디오 — 3단계(소재 고르기 → 초안 다듬기 → 버전·생성) 서버 계약 (2026-11-07). docs/deviation-drinks-studio.md
--
-- ★ 운영자 지시(2026-11-07): "사용자 작업을 3단계로 단순화 … 근거 단계에 개입하고 싶지 않다. 출처 등록, 원출처 묶음, 주장 선택,
--   지지 판정, 평가 점수, 공통 기획, 제작 지시서, 중간 검수를 필수 수동 작업으로 요구하지 마세요. … 서버 계약도 바꿔야 합니다."
--
-- 무엇이 바뀌나 — 왜
--   ① 저장 충돌(2026-11-06 사케 소재 실측): 근거 요청이 도는 사이 화면 저장이 빈 작성 중 버전을 만들었고, 워커 결과 저장이
--      draft_exists 로 거절됐다. 이제 (a) 사람 저장(drinks_save_review)은 초안을 만드는 중이면 서버가 거절하고,
--      (b) 워커는 빈 작성 중 버전에 이어 쓰며(사람이 쓴 내용이 있으면 덮어쓰지 않고 draft_has_edits), (c) 근거 요청도 빈 버전은 막지 않는다.
--   ② 자동 복구: 정해진 실패(저장 충돌·워커 중단·일시 오류)만, 소재당 24시간 3번, 같은 결재 안에서만 다시 넣는다(drinks_studio_recover_*).
--      자료 부족·검사 실패·예산·권리·취소는 다시 하지 않는다. 워커는 저장만 실패한 결과를 요청 기록에 보관하고, 다음 요청이 그 결과를
--      다시 쓴다(drinks_develop_context.reusable — 출처·사용 조건이 그대로일 때만). 모델을 다시 부르지 않는다.
--   ③ 5축 점수는 승인 필수 조건에서 경고로 내린다(drinks_review_blockers 한 줄). 점수는 소재를 고르는 참고값이고, 스튜디오에서는
--      운영자가 소재를 직접 고르는 것이 선택 판단이다. discovery-v1 의 형식 적합성 두 칸을 완성된 평가로 치지 않는다(가중 합 null → 경고).
--      나머지 필수 조건(핵심 질문·핵심 메시지·핵심 주장·인용 대조·사용 조건·지지 확인·시효)은 그대로 막는다 —
--      워커가 AI 사실 확인을 통과한 주장만 핵심 주장으로 고르고(engine/drinks_develop.py), 못 통과하면 '자료 부족'으로 멈춘다.
--   ④ 스튜디오 함수: prepare(한 번에 초안까지) · status(읽기) · save_draft(사람의 글 저장) · rewrite(수정 지시) · generate(확정+제작).
--      generate 의 승인은 기존 drinks_approve_content 다(검사가 줄지 않는다). 사람의 [콘텐츠 생성] 한 번이 그 승인이다.
--      카드뉴스만 끝까지 만든다(로컬 조립, 유료 호출 없음). 설명형·밈은 이 화면에서 만들지 않는다 — 기존 작업공간 그대로.
--
-- 바뀌지 않는 것
--   · 워커 함수는 승인·제출·편성 함수를 부르지 않는다(tests/test_drinks_develop.py). 게시는 이 파일과 무관하다(생성 ≠ 게시).
--   · AI 가 채운 '확인됨'은 한계 칸의 자동 문구로 사람 확인과 구분된다(0075). 이 파일은 그것을 사람 확인으로 바꾸지 않는다.
--
-- 되돌리기
--   1. 0050 drinks_review_blockers · 0072 drinks_request_develop · 0060 drinks_develop_save_evidence · 0072 drinks_develop_request_json 을 다시 실행한다.
--   2. 0050 drinks_save_review 를 다시 실행한다(사람 저장 잠금 해제).
--   3. drop function drinks_studio_generate(jsonb), drinks_studio_rewrite(jsonb), drinks_studio_save_draft(jsonb), drinks_studio_prepare(jsonb),
--      drinks_studio_status(jsonb), drinks_studio_unverified_numbers(jsonb, drink_topic_reviews), drinks_studio_recover_all(jsonb),
--      drinks_studio_recover_topic(uuid, text), drinks_studio_recoverable(text), drinks_studio_limits(), drinks_develop_save_rewrite(jsonb),
--      drinks_develop_context(jsonb), drinks_review_is_blank(drink_topic_reviews);
--      새 칸(instruction·recovery_of·supersedes_plan_id·supersedes_plan_version)은 남겨 둬도 된다.

-- ─────────────────────────────────────────────────────────────
-- 1. 요청 기록에 붙는 칸 — 복구·수정 지시·대체 대상
-- ─────────────────────────────────────────────────────────────
alter table drink_develop_requests add column if not exists instruction text check (instruction is null or length(instruction) between 2 and 500);
alter table drink_develop_requests add column if not exists recovery_of uuid references drink_develop_requests(id);
alter table drink_develop_requests add column if not exists supersedes_plan_id uuid references drink_plan_revisions(id);
alter table drink_develop_requests add column if not exists supersedes_plan_version int;
create index if not exists drink_develop_recovery_idx on drink_develop_requests (topic_id, created_at) where recovery_of is not null;

create or replace function drinks_develop_request_json(r drink_develop_requests) returns jsonb language sql stable set search_path = public, pg_temp as $$
  select jsonb_build_object('request_id', r.id, 'topic_id', r.topic_id, 'kind', r.kind, 'status', r.status, 'step', r.step,
    'review_id', r.review_id, 'budget_id', r.budget_id, 'cost_usd', r.cost_usd, 'cancel_requested', r.cancel_requested,
    'error_code', r.error_code, 'error_message', r.error_message, 'result', r.result,
    'result_review_id', r.result_review_id, 'result_plan_revision_id', r.result_plan_revision_id,
    'chain', r.chain, 'draft_evidence', r.draft_evidence, 'format_intent', r.format_intent,
    'instruction', r.instruction, 'recovery_of', r.recovery_of, 'supersedes_plan_id', r.supersedes_plan_id,
    'created_at', r.created_at, 'started_at', r.started_at, 'finished_at', r.finished_at)
$$;

-- 빈 작성 중 근거: 주장·질문·핵심 메시지·핵심 주장·점수가 모두 비었다. 덮어써도 잃는 것이 없다(사람이 쓴 내용이 없다).
create or replace function drinks_review_is_blank(r drink_topic_reviews) returns boolean language sql stable set search_path = public, pg_temp as $$
  select r.status = 'draft'
    and jsonb_array_length(coalesce(r.evidence_pack -> 'claims', '[]'::jsonb)) = 0
    and cardinality(drinks_text_array(r.brief -> 'selected_claim_ids')) = 0
    and drinks_text(r.brief, 'audience_question') is null
    and drinks_text(r.brief, 'core_takeaway') is null
    and coalesce(r.scores, '{}'::jsonb) = '{}'::jsonb
$$;

-- ─────────────────────────────────────────────────────────────
-- 2. 사람 저장(0050 정의) — 초안을 만드는 중이면 서버가 막는다(맨 위 검사 한 덩어리만 더했다)
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_save_review(p jsonb) returns jsonb language plpgsql as $$
declare
  v_topic uuid := drinks_uuid(p, 'topic_id'); v_review uuid := drinks_uuid(p, 'review_id', false);
  t drink_topics; r drink_topic_reviews; base drink_topic_reviews; v_no int;
  v_pack jsonb; v_brief jsonb; v_scores jsonb;
begin
  -- 0076: 사람 저장은 AI 가 이 소재의 초안을 만드는 중이면 거절한다(화면 잠금에만 기대지 않는다). 워커의 저장(drinks_develop_save_evidence)은
  --       같은 트랜잭션에서 drinks.worker_save=on 을 켜고 부른다 — 그 요청의 임대를 이미 확인한 뒤다.
  perform drinks_reap_develop();
  if coalesce(current_setting('drinks.worker_save', true), '') <> 'on'
      and exists (select 1 from drink_develop_requests where topic_id = v_topic and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', 'AI 가 이 소재의 초안을 만드는 중입니다 — 끝난 뒤에 저장하세요(지금 저장하면 그 결과와 부딪힙니다)');
  end if;
  if v_review is null then
    t := drinks_lock_topic(v_topic, drinks_int(p, 'expected_topic_version'));
  else
    t := drinks_lock_topic(v_topic, null, false);
  end if;
  if t.status not in ('researching','ready','selected') then
    perform drinks_fail('invalid_state', '조사 후보로 고른 소재만 근거·기획을 작성할 수 있습니다');
  end if;
  if v_review is null then
    if exists (select 1 from drink_topic_reviews where topic_id = t.id and status = 'draft') then
      perform drinks_fail('draft_exists', '작성 중인 버전이 이미 있습니다 — 그 버전을 이어서 고치세요');
    end if;
    -- 검토 중인 버전을 두고 새 버전을 만들면 그 검토가 고아가 된다(승인·변경요청 모두 불가). 먼저 결정하게 한다.
    if exists (select 1 from drink_topic_reviews where id = t.current_review_id and status = 'in_review') then
      perform drinks_fail('review_in_progress', '검토 중인 버전이 있습니다 — 승인하거나 변경 요청한 뒤 새 버전을 만드세요');
    end if;
    if t.current_review_id is not null then
      select * into base from drink_topic_reviews where id = t.current_review_id;
    end if;
    v_pack := drinks_normalize_pack(t.id, coalesce(p -> 'evidence_pack', base.evidence_pack, '{"claims": []}'));
    v_brief := drinks_normalize_brief(coalesce(p -> 'brief', base.brief));
    v_scores := drinks_check_scores(coalesce(p -> 'scores', base.scores), true);
    select coalesce(max(revision_no), 0) + 1 into v_no from drink_topic_reviews where topic_id = t.id;
    insert into drink_topic_reviews (topic_id, revision_no, based_on_review_id, scores, evidence_pack, brief)
      values (t.id, v_no, base.id, v_scores, v_pack, v_brief) returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    update drink_topics set current_review_id = r.id where id = t.id returning * into t;
    perform drinks_log(t.id, 'review', r.id, 'review_created', null, 'draft', r.input_hash, null,
      jsonb_build_object('revision_no', v_no, 'based_on', base.id));
  else
    select * into r from drink_topic_reviews where id = v_review for update;
    if not found or r.topic_id <> t.id then
      perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다');
    end if;
    if r.status <> 'draft' then
      perform drinks_fail('immutable', '검토 중·승인된 버전은 수정할 수 없습니다 — 새 버전으로 저장하세요');
    end if;
    if r.version <> drinks_int(p, 'expected_version') then
      perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 화면을 새로 불러오세요',
        jsonb_build_object('current_version', r.version));
    end if;
    update drink_topic_reviews set
      evidence_pack = drinks_normalize_pack(t.id, coalesce(p -> 'evidence_pack', r.evidence_pack)),
      brief = drinks_normalize_brief(coalesce(p -> 'brief', r.brief)),
      scores = drinks_check_scores(coalesce(p -> 'scores', r.scores), true)
      where id = r.id returning * into r;
    update drink_topic_reviews set readiness = drinks_review_blockers(r.id) where id = r.id returning * into r;
    perform drinks_log(t.id, 'review', r.id, 'review_saved', 'draft', 'draft', r.input_hash, null);
  end if;
  return jsonb_build_object('review_id', r.id, 'revision_no', r.revision_no, 'version', r.version,
    'input_hash', r.input_hash, 'score', r.score, 'readiness', r.readiness);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 3. 워커의 근거 저장 — 빈 작성 중 초안은 이어 쓴다, 사람이 쓴 초안은 덮어쓰지 않는다
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_develop_save_evidence(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; t drink_topics; v_res jsonb; v_scores jsonb; v_pack jsonb; r drink_topic_reviews; d drink_topic_reviews;
  v_base jsonb;
begin
  q := drinks_develop_lock(p);
  if q.kind <> 'evidence' then perform drinks_fail('invalid_state', '근거 초안 요청이 아닙니다'); end if;
  if q.cancel_requested then perform drinks_fail('canceled', '운영자가 취소했습니다'); end if;
  select * into t from drink_topics where id = q.topic_id for update;
  select * into d from drink_topic_reviews where topic_id = t.id and status = 'draft' order by created_at desc limit 1 for update;
  if found and not drinks_review_is_blank(d) then
    perform drinks_fail('draft_has_edits', '사람이 쓴 작성 중 근거가 있어 덮어쓰지 않았습니다 — 만든 결과는 요청 기록에 보관했습니다');
  end if;
  v_scores := coalesce(p -> 'scores', t.provisional_scores);
  v_base := jsonb_build_object('topic_id', t.id, 'evidence_pack', p -> 'evidence_pack', 'brief', p -> 'brief')
    || case when d.id is null then jsonb_build_object('expected_topic_version', t.version)
            else jsonb_build_object('review_id', d.id, 'expected_version', d.version) end;
  perform set_config('drinks.worker_save', 'on', true);
  begin
    v_res := drinks_save_review(v_base || case when v_scores is null then '{}'::jsonb else jsonb_build_object('scores', v_scores) end);
  exception when others then
    if not (v_scores is not null and sqlerrm like 'drinks:invalid_input:%') then raise; end if;
    -- 잠정 점수 모양이 맞지 않으면 점수 없이 저장한다(0060 그대로). 점수는 승인 필수 조건이 아니다(0076 §4).
    v_res := drinks_save_review(v_base);
  end;
  perform set_config('drinks.worker_save', 'off', true);
  select * into r from drink_topic_reviews where id = (v_res ->> 'review_id')::uuid;
  if d.id is not null then
    perform drinks_log(t.id, 'review', r.id, 'blank_draft_continued', 'draft', 'draft', r.input_hash, null,
      jsonb_build_object('request_id', q.id));
  end if;
  v_pack := r.evidence_pack;
  update drink_develop_requests set result_review_id = r.id, step = 'evidence_saved' where id = q.id;
  return v_res || jsonb_build_object('continued_blank_draft', d.id is not null, 'quote_check', jsonb_build_object(
    'matched', (select count(*) from jsonb_array_elements(v_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref where ref ->> 'quote_check' = 'matched'),
    'unmatched', (select count(*) from jsonb_array_elements(v_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref where ref ->> 'quote_check' = 'unmatched'),
    'not_checked', (select count(*) from jsonb_array_elements(v_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref where ref ->> 'quote_check' = 'not_checked')));
end $$;

-- 워커가 시작한 뒤 읽는 요청 부가 정보: 수정 지시, 대체할 초안, 그리고 다시 쓸 수 있는 보관 결과(저장만 실패했던 근거).
-- 보관 결과는 그 출처들이 지금도 이 소재에 근거로 붙어 있고 사용 조건이 그대로일 때만 준다(입력이 바뀌었으면 다시 만든다).
create or replace function drinks_develop_context(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; prev drink_develop_requests; v_snap uuid[]; v_ok boolean := false;
begin
  q := drinks_develop_lock(p);
  if q.kind = 'evidence' then
    select * into prev from drink_develop_requests x where x.topic_id = q.topic_id and x.kind = 'evidence' and x.id <> q.id
      and x.status = 'failed' and x.result ? 'unsaved_evidence' order by x.finished_at desc limit 1;
    if found then
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

-- 수정 지시로 다시 쓴 초안 저장: 대체할 초안을 막고(그대로 남는다 — 지우지 않는다) 새 초안을 같은 트랜잭션에서 넣는다.
-- 그 사이 사람이 고쳤으면(버전이 다르면) 저장하지 않는다 — 사람의 편집이 이긴다.
create or replace function drinks_develop_save_rewrite(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare q drink_develop_requests; old drink_plan_revisions;
begin
  q := drinks_develop_lock(p);
  if q.supersedes_plan_id is null then return drinks_develop_save_plan(p); end if;
  select * into old from drink_plan_revisions where id = q.supersedes_plan_id for update;
  if old.plan_status <> 'draft' or old.version is distinct from q.supersedes_plan_version then
    perform drinks_fail('draft_changed', '수정하는 사이 초안이 바뀌었습니다 — 바뀐 초안을 그대로 두고 새 초안은 저장하지 않았습니다');
  end if;
  if old.blocked_at is null then
    update drink_plan_revisions set blocked_at = now(), blocked_reason = 'rewritten: 수정 지시로 새 초안이 만들어졌습니다' where id = old.id;
  end if;
  return drinks_develop_save_plan(p) || jsonb_build_object('superseded_plan_id', old.id);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 4. 필수 조건 검사(0050 정의) — 점수 한 줄만 바뀐다(차단 → 경고)
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_review_blockers(p_review uuid) returns jsonb
language plpgsql stable as $$
declare
  r drink_topic_reviews; b text[] := '{}'; w text[] := '{}';
  c jsonb; ref jsonb; cid text; core text[]; claim_ids text[]; fmts text[]; f text; req text[];
  has_ref boolean; has_body boolean; has_match boolean; has_usable boolean; groups int;
  s_has_body boolean; s_rights text; m jsonb; state jsonb := '{}';
begin
  select * into r from drink_topic_reviews where id = p_review;
  if not found then perform drinks_fail('not_found', '근거·기획 버전을 찾지 못했습니다'); end if;
  -- 0076: 5축 점수는 고르는 데 쓰는 참고값이다. 운영자가 소재를 직접 고르면 그것이 선택 판단이라 승인을 막지 않는다(경고로 남긴다).
  --       discovery-v1 의 형식 적합성 두 칸만 있는 값을 완성된 5축 평가로 치지 않는다 — 가중 합이 null 이면 'scores_not_evaluated' 경고.
  if drinks_weighted_score(r.scores) is null then w := array_append(w, 'scores_not_evaluated'); end if;
  if drinks_text(r.brief, 'audience_question') is null then b := array_append(b, 'brief_question_missing'); end if;
  if drinks_text(r.brief, 'core_takeaway') is null then b := array_append(b, 'brief_takeaway_missing'); end if;
  claim_ids := array(select x ->> 'claim_id' from jsonb_array_elements(r.evidence_pack -> 'claims') x);
  core := drinks_text_array(r.brief -> 'selected_claim_ids');
  if cardinality(core) = 0 then b := array_append(b, 'no_core_claims'); end if;
  -- 형식별 필수 주장: 제안한 형식마다 그 형식이 반드시 전달할 핵심 주장(빈 목록 금지)
  fmts := drinks_text_array(r.brief -> 'proposed_formats');
  if cardinality(fmts) = 0 then b := array_append(b, 'no_proposed_format'); end if;
  foreach f in array fmts loop
    req := drinks_text_array(r.brief -> 'required_claims' -> f);
    if cardinality(req) = 0 then b := array_append(b, 'required_claims_missing:' || f); end if;
    if exists (select 1 from unnest(req) x where not x = any(core)) then
      b := array_append(b, 'required_claim_not_core:' || f);
    end if;
    -- 형식 적합성은 차단이 아니라 경고(정책 ①). 편성 때 형식별 예외 사유를 받는다.
    if coalesce((r.scores ->> ('fit_' || f))::int, 0) < 2 then w := array_append(w, 'format_fit_low:' || f); end if;
  end loop;
  foreach cid in array core loop
    if not cid = any(claim_ids) then b := array_append(b, 'unknown_claim:' || cid); continue; end if;
    select x into c from jsonb_array_elements(r.evidence_pack -> 'claims') x where x ->> 'claim_id' = cid limit 1;
    if c ->> 'claim_type' = 'opinion' then
      if drinks_text(c, 'attribution') is null then b := array_append(b, 'opinion_unattributed:' || cid); end if;
      continue;
    end if;
    has_ref := false; has_body := false; has_match := false; has_usable := false;
    for ref in select * from jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) loop
      has_ref := true;
      select (s.body_text is not null) into s_has_body from drink_source_snapshots s where s.id = (ref ->> 'snapshot_id')::uuid;
      m := drinks_snapshot_meta((ref ->> 'snapshot_id')::uuid);
      s_rights := m ->> 'rights_status';   -- 정정·철회까지 반영한 사용 조건
      state := state || jsonb_build_object(ref ->> 'snapshot_id', jsonb_build_object('rights', s_rights,
        'attestation', m -> 'last_attestation_id'));
      if s_has_body then has_body := true; end if;
      if ref ->> 'quote_check' = 'matched' then
        has_match := true;
        if s_rights in ('quote_ok','summary_only') then has_usable := true; end if;
      end if;
    end loop;
    if not has_ref then b := array_append(b, 'claim_no_source:' || cid);
    elsif not has_body then b := array_append(b, 'claim_metadata_only:' || cid);
    elsif not has_match then b := array_append(b, 'claim_quote_unmatched:' || cid);
    elsif not has_usable then b := array_append(b, 'claim_rights_unconfirmed:' || cid);
    end if;
    case coalesce(c ->> 'support_review', 'not_reviewed')
      when 'supported' then null;
      when 'conflicting' then b := array_append(b, 'claim_conflicting:' || cid);
      when 'insufficient' then b := array_append(b, 'claim_insufficient:' || cid);
      else b := array_append(b, 'claim_support_not_reviewed:' || cid);
    end case;
    if c -> 'time_sensitive' = 'true'::jsonb then
      if drinks_text(c, 'valid_until') is null or drinks_text(c -> 'scope', 'region') is null then
        b := array_append(b, 'claim_time_scope_missing:' || cid);
      elsif (c ->> 'valid_until')::date < current_date then
        b := array_append(b, 'claim_expired:' || cid);
      end if;
    end if;
    if c ->> 'claim_type' = 'comparison' then
      -- 독립 원출처는 운영자가 묶음을 정한 것만 센다(정책 ②). 묶음 미확인 출처는 독립으로 치지 않는다.
      select count(distinct s.origin_group) into groups
        from jsonb_array_elements(coalesce(c -> 'source_refs', '[]')) x
        join drink_source_snapshots s on s.id = (x ->> 'snapshot_id')::uuid
        where s.origin_group is not null;
      if groups < 2 then w := array_append(w, 'comparison_origin_unconfirmed:' || cid); end if;
    end if;
  end loop;
  return jsonb_build_object('blockers', to_jsonb(b), 'warnings', to_jsonb(w), 'source_state', state,
    'checked_at', now());
end $$;

-- ─────────────────────────────────────────────────────────────
-- 5. 개발 요청(0072 정의) — 근거 요청의 draft_exists 조건 한 줄만 바뀐다(빈 작성 중 버전은 이어 쓴다)
-- ─────────────────────────────────────────────────────────────
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
    -- 0076: 빈 작성 중 버전(사람이 쓴 내용이 없음)은 막지 않는다 — 워커가 그 버전에 이어 쓴다(drinks_develop_save_evidence).
    if exists (select 1 from drink_topic_reviews x where x.topic_id = t.id and x.status = 'draft' and not drinks_review_is_blank(x)) then
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

-- ─────────────────────────────────────────────────────────────
-- 6. 자동 복구 — 실패한 요청을 정해진 경우에만, 정해진 횟수만 다시 넣는다
--   · 같은 요청을 그대로 되풀이하지 않는다: 저장 충돌(draft_exists·version_conflict)은 0076 이 원인을 없앤 뒤의 재시도이고,
--     워커 중단(lease_expired·worker_error)·일시 오류는 중단 지점부터(보관 결과가 있으면 모델을 다시 부르지 않는다).
--   · 자료 부족·검사 실패·예산·권리·취소는 자동으로 다시 하지 않는다(사람이 고를 일이다).
--   · 한도: 소재당 24시간에 3번, 그리고 같은 결재 안에서만(결재 금액·요청 상한은 워커의 가잡기가 그대로 센다).
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_studio_limits() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object('max_recoveries_24h', 3)
$$;

create or replace function drinks_studio_recoverable(p_code text) returns boolean language sql immutable set search_path = public, pg_temp as $$
  select coalesce(p_code, '') in ('draft_exists','version_conflict','lease_expired','lease_lost','worker_error','transient_error',
    'factcheck_unavailable','review_changed','db_error')
$$;

create or replace function drinks_studio_recover_topic(p_topic uuid, p_actor text) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare t drink_topics; last drink_develop_requests; r drink_topic_reviews; bs jsonb; v_n int; v_res jsonb; v_budget uuid; v_lim int := (drinks_studio_limits() ->> 'max_recoveries_24h')::int;
begin
  select * into t from drink_topics where id = p_topic for update;
  if not found or t.status <> 'researching' then return null; end if;
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then return null; end if;
  select * into last from drink_develop_requests where topic_id = t.id order by created_at desc limit 1;
  if not found or last.status <> 'failed' or not drinks_studio_recoverable(last.error_code) then return null; end if;
  select count(*) into v_n from drink_develop_requests where topic_id = t.id and recovery_of is not null and created_at > now() - interval '24 hours';
  if v_n >= v_lim then return jsonb_build_object('code', 'recovery_limit', 'recoveries', v_n); end if;
  v_budget := last.budget_id;
  bs := case when v_budget is null then null else drinks_develop_budget_json(v_budget) end;
  -- 원래 결재가 주간 한도(0073)이고 주가 바뀌어 끝났으면(또는 결재 없이 들어간 옛 요청이면) 이번 주 한도로 잇는다(같은 종류의 자동 한도 — 새 결재를 지어내지 않는다).
  if bs is null or ((bs ->> 'expired')::boolean
      and exists (select 1 from drink_develop_budgets b where b.id = v_budget and b.stage like 'weekly:%')) then
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
    bs := drinks_develop_budget_json(v_budget);
  end if;
  if bs is null or bs ->> 'status' <> 'open' or (bs ->> 'expired')::boolean or (bs ->> 'remaining_usd')::numeric <= 0 then
    return jsonb_build_object('code', 'budget_unavailable');
  end if;
  begin
    if last.kind = 'evidence' then
      v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', last.chain));
    else
      select * into r from drink_topic_reviews where id = t.current_review_id;
      if not found or r.status <> 'draft' then return null; end if;
      if last.supersedes_plan_id is not null then
        -- 수정 지시 재시도: 사람이 그 뒤에 초안을 고쳤으면 다시 하지 않는다.
        if not exists (select 1 from drink_plan_revisions where id = last.supersedes_plan_id and plan_status = 'draft' and blocked_at is null
            and version = last.supersedes_plan_version) then return null; end if;
        insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent, instruction, supersedes_plan_id, supersedes_plan_version)
          values (t.id, 'plan', r.id, v_budget, true, last.format_intent, last.instruction, last.supersedes_plan_id, last.supersedes_plan_version)
          returning jsonb_build_object('request_id', id) into v_res;
      else
        v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true,
          'format_intent', last.format_intent));
      end if;
    end if;
  exception when raise_exception then
    if sqlerrm not like 'drinks:%' then raise; end if;
    return jsonb_build_object('code', split_part(sqlerrm, ':', 2), 'message', substr(sqlerrm, length(split_part(sqlerrm, ':', 2)) + 9));
  end;
  update drink_develop_requests set recovery_of = last.id where id = (v_res ->> 'request_id')::uuid;
  perform drinks_log(t.id, 'topic', t.id, 'develop_recovered', 'failed', 'queued', (v_res ->> 'request_id'), last.error_code,
    jsonb_build_object('recovery_of', last.id, 'kind', last.kind, 'actor', p_actor, 'recoveries_24h', v_n + 1));
  return jsonb_build_object('request_id', v_res ->> 'request_id', 'recovery_of', last.id, 'kind', last.kind);
end $$;

-- 워커가 큐를 비우기 전에 부른다 — 브라우저가 닫혀 있어도 같은 실행 안에서 복구 요청을 집어 간다.
-- 최근 2시간 안에 실패한 것만 본다: 이 파일을 적용하기 전의 옛 실패(다른 소재)를 워커가 몰래 다시 돌려 돈을 쓰지 않게.
-- 그보다 오래된 실패는 운영자가 그 소재에서 [초안 만들기]를 누를 때(drinks_studio_prepare) 복구된다.
create or replace function drinks_studio_recover_all(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare x record; v_out jsonb := '[]'::jsonb; v_res jsonb;
begin
  perform drinks_reap_develop();
  for x in select distinct on (topic_id) topic_id, status, error_code, finished_at from drink_develop_requests
      where created_at > now() - interval '1 day' order by topic_id, created_at desc loop
    if x.status = 'failed' and x.finished_at > now() - interval '2 hours' and drinks_studio_recoverable(x.error_code) then
      v_res := drinks_studio_recover_topic(x.topic_id, 'worker');
      if v_res ? 'request_id' then v_out := v_out || jsonb_build_object('topic_id', x.topic_id) || v_res; end if;
    end if;
  end loop;
  return jsonb_build_object('recovered', v_out);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 7. 스튜디오 읽기 — 화면이 진행 상태를 계산할 재료(읽기만, 회수만 곁들인다)
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_studio_status(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id'); t drink_topics; r drink_topic_reviews;
begin
  perform drinks_reap_develop();
  select * into t from drink_topics where id = v_topic;
  if not found then perform drinks_fail('not_found', '소재를 찾지 못했습니다'); end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  return jsonb_build_object(
    'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'status', t.status, 'version', t.version, 'categories', to_jsonb(t.categories)),
    'picks', coalesce((select jsonb_agg(jsonb_build_object('format_intent', k.format_intent, 'approved_at', k.approved_at, 'recommended_format', k.recommended_format,
        'recommended_reason', k.recommended_reason) order by k.created_at) from drink_topic_format_picks k where k.topic_id = t.id), '[]'::jsonb),
    'active', (select drinks_develop_request_json(a) - 'result' from drink_develop_requests a where a.topic_id = t.id and a.status in ('queued','running')
      order by a.created_at desc limit 1),
    'last', (select drinks_develop_request_json(l) - 'result' || jsonb_build_object('result_cost', l.result -> 'cost',
        'factcheck', l.result -> 'factcheck', 'excluded', l.result -> 'excluded', 'has_unsaved', l.result ? 'unsaved_evidence' or l.result ? 'unsaved_plan')
      from drink_develop_requests l where l.topic_id = t.id order by l.created_at desc limit 1),
    'recoveries_24h', (select count(*) from drink_develop_requests where topic_id = t.id and recovery_of is not null and created_at > now() - interval '24 hours'),
    'limits', drinks_studio_limits(),
    'review', case when r.id is null then null else jsonb_build_object('review_id', r.id, 'status', r.status, 'version', r.version, 'blank', drinks_review_is_blank(r),
      'core_claim_ids', r.brief -> 'selected_claim_ids', 'core_takeaway', r.brief -> 'core_takeaway', 'claims', r.evidence_pack -> 'claims',
      'readiness', r.readiness) end,
    'plans', coalesce((select jsonb_agg(jsonb_build_object('plan_revision_id', pl.id, 'format', pl.format, 'version', pl.version, 'plan_status', pl.plan_status,
        'blocked', pl.blocked_at is not null, 'blocked_reason', pl.blocked_reason, 'plan_json', pl.plan_json, 'topic_review_id', pl.topic_review_id,
        'current', d.current_revision_id = pl.id, 'updated_at', pl.updated_at,
        'unverified_numbers', drinks_studio_unverified_numbers(pl.plan_json, (select x from drink_topic_reviews x where x.id = pl.topic_review_id)),
        'jobs', coalesce((select jsonb_agg(jsonb_build_object('job_id', j.id, 'status', j.status, 'error_code', j.error_code, 'attempt_no', j.attempt_no,
            'created_at', j.created_at, 'finished_at', j.finished_at) order by j.created_at desc) from drink_production_jobs j where j.plan_revision_id = pl.id), '[]'::jsonb))
      order by pl.created_at desc)
      from drink_plan_revisions pl join drink_deliverables d on d.id = pl.deliverable_id
      where pl.topic_id = t.id and (d.current_revision_id = pl.id or pl.plan_status = 'approved')), '[]'::jsonb),
    'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher, 'url', s.canonical_url,
        'role', ts.role, 'rights_status', drinks_snapshot_meta(s.id) ->> 'rights_status', 'usage_terms', s.usage_terms) order by ts.created_at)
      from drink_topic_sources ts join drink_source_snapshots s on s.id = ts.snapshot_id where ts.topic_id = t.id), '[]'::jsonb));
end $$;

-- 고친 글에 근거 인용에 없는 숫자가 있나(엔진 drinks_script_check._nums 와 같은 규칙: 앞에 영문·숫자·점이 없는 수, 쉼표는 뺀다).
-- 근거 인용 + 출처 표기(제목·발행처)에 있는 숫자만 허용한다. 뜻이 넘었는지는 여기서 못 본다 — 숫자만 다시 잰다.
create or replace function drinks_studio_unverified_numbers(p_plan jsonb, r drink_topic_reviews) returns jsonb language sql stable set search_path = public, pg_temp as $$
  with txt as (
    select string_agg(coalesce(e ->> 'heading', '') || ' ' || coalesce(e ->> 'body', '') || ' ' || coalesce(e ->> 'narration', ''), ' ') s
    from jsonb_array_elements(coalesce(p_plan -> 'pages', p_plan -> 'scenes', '[]'::jsonb)) e
  ), reel as (
    select coalesce(p_plan -> 'reel' ->> 'hook_title', '') || ' ' || coalesce(p_plan -> 'reel' ->> 'share_line', '') s
  ), quotes as (
    select coalesce(string_agg(ref ->> 'original_quote', ' '), '') s
    from jsonb_array_elements(coalesce(r.evidence_pack -> 'claims', '[]'::jsonb)) c, jsonb_array_elements(coalesce(c -> 'source_refs', '[]'::jsonb)) ref
  ), meta as (
    select coalesce(string_agg(coalesce(s.title, '') || ' ' || coalesce(s.publisher, '') || ' ' || coalesce(s.published_at::text, '') || ' ' || coalesce(s.canonical_url, ''), ' '), '') s
    from drink_topic_sources ts join drink_source_snapshots s on s.id = ts.snapshot_id where ts.topic_id = r.topic_id
  ), used as (
    select distinct replace(m[1], ',', '') n from txt, reel, regexp_matches(txt.s || ' ' || reel.s, '(?<![A-Za-z0-9.])([0-9]+(?:[.,][0-9]+)?)', 'g') m
  ), known as (
    select distinct replace(m[1], ',', '') n from quotes, meta, regexp_matches(quotes.s || ' ' || meta.s, '(?<![A-Za-z0-9.])([0-9]+(?:[.,][0-9]+)?)', 'g') m
  )
  select coalesce(jsonb_agg(u.n order by u.n), '[]'::jsonb) from used u where u.n not in (select n from known)
$$;

-- ─────────────────────────────────────────────────────────────
-- 8. [이 소재로 초안 만들기] — 한 번 누르면 끝까지(같은 요청이면 그 작업으로 이어 준다)
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_studio_prepare(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare v_topic uuid := drinks_uuid(p, 'topic_id', false); v_cand uuid := drinks_uuid(p, 'candidate_id', false);
  v_fmt text := coalesce(drinks_text(p, 'format_intent'), 'card'); c drink_discovery_candidates; t drink_topics; r drink_topic_reviews;
  v_budget uuid; v_week date := (now() at time zone 'Asia/Seoul')::date; v_res jsonb; v_rec jsonb; v_action text := 'none'; last drink_develop_requests;
  v_intent text;
begin
  perform drinks_reap_develop();
  if v_fmt not in ('card','explainer') then perform drinks_fail('invalid_input', '초안 형식은 카드뉴스·설명형 중 하나입니다'); end if;
  v_week := v_week - (extract(isodow from v_week)::int - 1);
  if (v_topic is null) = (v_cand is null) then perform drinks_fail('invalid_input', '후보 또는 소재 중 하나를 지정하세요'); end if;
  if v_cand is not null then
    select * into c from drink_discovery_candidates where id = v_cand;
    if not found then perform drinks_fail('not_found', '후보를 찾지 못했습니다'); end if;
    v_topic := c.promoted_topic_id;
  end if;
  if v_topic is null then
    -- 새 후보: 소재로 올리고 형식 하나(추천)를 의도로 적고 근거 요청까지(0072 [이걸로] 그대로). 편성 주차 = 이번 주, 예산 = 이번 주 AI 초안 한도.
    v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
    v_res := drinks_pick_topic(jsonb_build_object('candidate_id', v_cand, 'expected_version', c.version, 'formats', jsonb_build_array(v_fmt), 'editorial_week', to_char(v_week, 'YYYY-MM-DD'),
      'budget_id', v_budget, 'recommended_format', v_fmt, 'recommended_reason', left(drinks_text(p, 'recommended_reason'), 500),
      'lane', 'reader_question', 'title', coalesce(drinks_text(p, 'title'), c.key_question), 'question', coalesce(drinks_text(p, 'question'), c.key_question))
      || jsonb_strip_nulls(jsonb_build_object('categories', p -> 'categories', 'reader_value', drinks_text(p, 'reader_value'),
        'confirm_not_duplicate', p -> 'confirm_not_duplicate')));
    return jsonb_build_object('topic_id', v_res ->> 'topic_id', 'action', 'picked', 'queued', coalesce((v_res -> 'chain' ->> 'queued')::boolean, false),
      'existing', coalesce((v_res -> 'chain' ->> 'existing')::boolean, false), 'pick', v_res);
  end if;
  t := drinks_lock_topic(v_topic, null, false);
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then
    return jsonb_build_object('topic_id', t.id, 'action', 'already_running', 'queued', false, 'existing', true);
  end if;
  if exists (select 1 from drink_plan_revisions pl join drink_deliverables d on d.id = pl.deliverable_id
      where pl.topic_id = t.id and d.current_revision_id = pl.id and pl.blocked_at is null and pl.plan_status in ('draft','approved')) then
    return jsonb_build_object('topic_id', t.id, 'action', 'draft_ready', 'queued', false, 'existing', true);
  end if;
  if t.status not in ('triaged','researching','ready','selected') then
    perform drinks_fail('invalid_state', '보류·제외·중복 처리된 소재입니다 — 다른 소재를 고르세요');
  end if;
  v_rec := drinks_studio_recover_topic(t.id, 'studio');
  if v_rec ? 'request_id' then
    return jsonb_build_object('topic_id', t.id, 'action', 'recovered', 'queued', true, 'existing', false, 'recovery', v_rec);
  end if;
  if v_rec ? 'code' then
    return jsonb_build_object('topic_id', t.id, 'action', 'needs_choice', 'queued', false, 'code', v_rec ->> 'code', 'message', v_rec ->> 'message');
  end if;
  select * into last from drink_develop_requests where topic_id = t.id order by created_at desc limit 1;
  if found and last.status in ('blocked','failed') then
    -- 자동으로 다시 하지 않는 실패(자료 부족·검사 실패·예산 등). 같은 실패를 되풀이하지 않는다 — 화면이 이유와 선택지를 보여 준다.
    return jsonb_build_object('topic_id', t.id, 'action', 'stopped', 'queued', false, 'code', last.error_code);
  end if;
  v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  if not exists (select 1 from drink_topic_format_picks where topic_id = t.id and format_intent in ('card','explainer')) then
    v_res := drinks_pick_topic(jsonb_build_object('topic_id', t.id, 'formats', jsonb_build_array(v_fmt), 'editorial_week', to_char(v_week, 'YYYY-MM-DD'),
      'budget_id', v_budget, 'recommended_format', v_fmt));
    return jsonb_build_object('topic_id', t.id, 'action', 'picked', 'queued', coalesce((v_res -> 'chain' ->> 'queued')::boolean, false),
      'existing', coalesce((v_res -> 'chain' ->> 'existing')::boolean, false), 'pick', v_res);
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if t.status = 'researching' and r.id is not null and r.status = 'draft' and not drinks_review_is_blank(r) then
    -- 근거는 있고 초안만 없다(옛 흐름에서 멈춘 소재): 고른 형식의 초안을 이 근거로 만든다.
    select format_intent into v_intent from drink_topic_format_picks where topic_id = t.id and format_intent in ('card','explainer') order by created_at limit 1;
    v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'draft_evidence', true, 'format_intent', v_intent));
    v_action := 'plan_requested';
  elsif t.status = 'researching' then
    v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'evidence', 'budget_id', v_budget, 'chain', true));
    v_action := 'evidence_requested';
  else
    -- 근거가 이미 승인된 소재(ready/selected)에 카드 초안만 없다: 승인된 근거로 카드 초안을 만든다(0072 일반 대본 요청 그대로).
    v_res := drinks_request_develop(jsonb_build_object('topic_id', t.id, 'kind', 'plan', 'budget_id', v_budget, 'format_intent', 'card'));
    v_action := 'plan_requested';
  end if;
  return jsonb_build_object('topic_id', t.id, 'action', v_action, 'queued', true, 'existing', coalesce((v_res ->> 'existing')::boolean, false),
    'request_id', v_res ->> 'request_id');
end $$;

-- ─────────────────────────────────────────────────────────────
-- 9. 초안 다듬기 — 사람이 쓴 글을 그 자리에 저장(제출·승인 아님)
--   · 페이지 수·순서·페이지마다의 근거 연결(claim_ids)은 그대로, 글(제목·본문·릴스 두 줄)만 바꾼다.
--   · AI 가 초안을 만드는 중이면 막는다. 버전이 다르면 막는다(다른 탭·자동 결과와 부딪히지 않는다).
--   · 근거 인용에 없는 숫자는 저장은 하되 돌려준다 — 생성(9-3)이 그 숫자가 남아 있으면 막는다.
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_studio_save_draft(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; v_pages jsonb := p -> 'pages'; v_new jsonb; v_out jsonb := '[]'::jsonb;
  el jsonb; i int := 0; ed jsonb; v_plan jsonb;
begin
  perform drinks_reap_develop();
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pr from drink_plan_revisions where id = pr.id for update;
  if pr.format <> 'carousel' then perform drinks_fail('invalid_state', '이 화면에서는 카드뉴스 초안만 고칩니다'); end if;
  if pr.plan_status <> 'draft' or pr.blocked_at is not null then
    perform drinks_fail('immutable', '이미 생성에 쓴(또는 바뀐) 초안입니다 — 고치려면 [초안 수정하기]로 새 초안을 만드세요');
  end if;
  if pr.version <> drinks_int(p, 'expected_version') then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 저장됐습니다 — 새로 불러온 뒤 다시 고치세요', jsonb_build_object('current_version', pr.version));
  end if;
  if exists (select 1 from drink_develop_requests where topic_id = t.id and status in ('queued','running')) then
    perform drinks_fail('develop_in_progress', 'AI 가 초안을 만드는 중입니다 — 끝난 뒤에 저장하세요');
  end if;
  if jsonb_typeof(v_pages) is distinct from 'array' or jsonb_array_length(v_pages) <> jsonb_array_length(pr.plan_json -> 'pages') then
    perform drinks_fail('invalid_input', '페이지 수는 바꿀 수 없습니다 — 글만 고칩니다');
  end if;
  for el in select * from jsonb_array_elements(pr.plan_json -> 'pages') loop
    i := i + 1;
    ed := v_pages -> (i - 1);
    if jsonb_typeof(ed) <> 'object' then perform drinks_fail('invalid_input', i || '번 페이지 형식이 잘못됐습니다'); end if;
    if (el ->> 'role') <> 'source' and nullif(btrim(coalesce(ed ->> 'heading', '')), '') is null then
      perform drinks_fail('invalid_input', i || '번 페이지 제목이 비었습니다');
    end if;
    if length(coalesce(ed ->> 'heading', '')) > 120 or length(coalesce(ed ->> 'body', '')) > 1200 then
      perform drinks_fail('invalid_input', i || '번 페이지 글이 너무 깁니다');
    end if;
    v_out := v_out || jsonb_build_array(el || jsonb_build_object('heading', btrim(coalesce(ed ->> 'heading', el ->> 'heading')),
      'body', nullif(btrim(coalesce(ed ->> 'body', '')), '')));
  end loop;
  v_new := jsonb_set(pr.plan_json, '{pages}', v_out);
  if jsonb_typeof(p -> 'reel') = 'object' then
    v_new := jsonb_set(v_new, '{reel}', coalesce(pr.plan_json -> 'reel', '{}'::jsonb)
      || jsonb_strip_nulls(jsonb_build_object('hook_title', nullif(btrim(p -> 'reel' ->> 'hook_title'), ''), 'share_line', nullif(btrim(p -> 'reel' ->> 'share_line'), ''))));
  end if;
  select * into r from drink_topic_reviews where id = pr.topic_review_id;
  v_plan := drinks_validate_plan(pr.format, v_new, r);
  if v_plan is not distinct from pr.plan_json then
    return jsonb_build_object('plan_revision_id', pr.id, 'version', pr.version, 'changed', false, 'unverified_numbers', drinks_studio_unverified_numbers(pr.plan_json, r));
  end if;
  update drink_plan_revisions set plan_json = v_plan where id = pr.id returning * into pr;
  perform drinks_log(t.id, 'plan', pr.id, 'studio_draft_saved', 'draft', 'draft', pr.input_hash, null,
    jsonb_build_object('actor', 'operator', 'edited_by', 'human'));
  return jsonb_build_object('plan_revision_id', pr.id, 'version', pr.version, 'changed', true, 'input_hash', pr.input_hash,
    'unverified_numbers', drinks_studio_unverified_numbers(pr.plan_json, r));
end $$;

-- [이 방향으로 수정] — AI 가 지시대로 다시 쓴다. 지금 초안은 새 초안이 저장될 때까지 그대로 쓸 수 있다(실패하면 그대로 남는다).
create or replace function drinks_studio_rewrite(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; q drink_develop_requests; v_ins text := btrim(coalesce(drinks_text(p, 'instruction'), ''));
  v_budget uuid; bs jsonb;
begin
  perform drinks_reap_develop();
  if length(v_ins) < 2 or length(v_ins) > 500 then perform drinks_fail('invalid_input', '수정 방향을 2~500자로 적어 주세요'); end if;
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pr from drink_plan_revisions where id = pr.id for update;
  if pr.version <> drinks_int(p, 'expected_version') then perform drinks_fail('version_conflict', '초안이 다른 곳에서 바뀌었습니다 — 새로 불러오세요'); end if;
  if pr.format <> 'carousel' or pr.plan_status <> 'draft' or pr.blocked_at is not null or not pr.drafted_from_unapproved then
    perform drinks_fail('invalid_state', '고칠 수 있는 카드뉴스 초안이 아닙니다');
  end if;
  select * into r from drink_topic_reviews where id = t.current_review_id;
  if t.status <> 'researching' or r.id is distinct from pr.topic_review_id or r.status <> 'draft' then
    perform drinks_fail('review_changed', '초안이 기대던 근거가 바뀌었습니다 — 새로 불러오세요');
  end if;
  select * into q from drink_develop_requests where topic_id = t.id and status in ('queued','running') limit 1;
  if found then return drinks_develop_request_json(q) || jsonb_build_object('existing', true); end if;
  v_budget := (drinks_ensure_weekly_budget('{}'::jsonb) ->> 'budget_id')::uuid;
  bs := drinks_develop_budget_json(v_budget);
  if bs ->> 'status' <> 'open' or (bs ->> 'expired')::boolean or (bs ->> 'remaining_usd')::numeric <= 0 then
    perform drinks_fail('budget_exceeded', '이번 주 AI 초안 한도를 모두 썼습니다');
  end if;
  insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent, instruction, supersedes_plan_id, supersedes_plan_version)
    values (t.id, 'plan', r.id, v_budget, true, 'card', v_ins, pr.id, pr.version) returning * into q;
  perform drinks_log(t.id, 'topic', t.id, 'develop_requested', null, null, q.id::text, null,
    jsonb_build_object('kind', 'plan', 'budget_id', v_budget, 'review_id', r.id, 'draft_evidence', true, 'format_intent', 'card', 'rewrite_of', pr.id));
  return drinks_develop_request_json(q) || jsonb_build_object('existing', false);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 10. [이 초안으로 콘텐츠 생성] — 사람의 확정 한 번 = 내용 승인(기존 함수 그대로) + 제작 요청을 한 트랜잭션으로.
--   · 승인은 drinks_approve_content 다. 근거 필수 조건·인용·사용 조건·대본 커버리지 검사가 하나도 줄지 않는다.
--   · 지금 이 화면에서 끝까지 만드는 형식은 카드뉴스뿐이다(로컬 조립, 유료 호출 없음). 설명형·밈은 거절한다 — 선택지를 보여 주고 나중에 실패시키지 않는다.
--   · 이미 성공한 결과가 있으면 다시 만들지 않는다. 실패한 것만 retry_of 로 다시 만든다.
-- ─────────────────────────────────────────────────────────────
create or replace function drinks_studio_generate(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare pr drink_plan_revisions; t drink_topics; r drink_topic_reviews; pk drink_topic_format_picks; v_ap jsonb; v_render jsonb; v_nums jsonb;
  j drink_production_jobs; v_retry uuid := drinks_uuid(p, 'retry_of', false);
begin
  if coalesce(drinks_text(p, 'format_intent'), '') <> 'card' then
    perform drinks_fail('format_not_supported', '이 화면에서 끝까지 만드는 형식은 카드뉴스뿐입니다');
  end if;
  select * into pr from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id');
  if not found then perform drinks_fail('not_found', '초안을 찾지 못했습니다'); end if;
  if pr.format <> 'carousel' then perform drinks_fail('format_not_supported', '카드뉴스 초안이 아닙니다'); end if;
  t := drinks_lock_topic(pr.topic_id, null, false);
  select * into pk from drink_topic_format_picks where topic_id = t.id and format_intent = 'card';
  if not found then perform drinks_fail('format_not_selected', '카드뉴스로 고른 소재가 아닙니다'); end if;
  if pk.approved_at is null then
    select * into r from drink_topic_reviews where id = pr.topic_review_id;
    v_nums := drinks_studio_unverified_numbers(pr.plan_json, r);
    if jsonb_array_length(v_nums) > 0 then
      perform drinks_fail('numbers_unverified', '근거 인용에 없는 숫자가 초안에 있습니다(' || (select string_agg(x, ', ') from jsonb_array_elements_text(v_nums) x)
        || ') — 고치거나 지운 뒤 생성하세요', v_nums);
    end if;
    v_ap := drinks_approve_content(jsonb_build_object('topic_id', t.id, 'expected_topic_version', drinks_int(p, 'expected_topic_version'),
      'review_id', r.id, 'expected_review_version', drinks_int(p, 'expected_review_version'),
      'plan_revision_id', pr.id, 'expected_plan_version', drinks_int(p, 'expected_plan_version'), 'format_intent', 'card',
      'note', '스튜디오 [콘텐츠 생성] — 운영자가 초안을 읽고 확정',
      -- 5축 점수는 참고값(0076 §4) — 65점 기준 아래여도 운영자가 직접 골라 확정한 것이므로 그 사실을 예외 사유로 기록한다(빈칸으로 우회하지 않는다).
      'score_exception_reason', '스튜디오에서 운영자가 소재를 직접 골라 초안을 확정함(점수는 참고값, 0076)',
      'format_exceptions',
      jsonb_build_object('carousel', '운영자가 스튜디오에서 카드뉴스를 직접 골랐습니다')));
    select * into pr from drink_plan_revisions where id = pr.id;
  elsif pr.plan_status <> 'approved' then
    perform drinks_fail('invalid_state', '이 소재의 카드뉴스는 다른 초안으로 이미 확정됐습니다 — 새로 불러오세요');
  end if;
  if v_retry is null then
    select * into j from drink_production_jobs where plan_revision_id = pr.id and status in ('queued','running','succeeded') order by created_at desc limit 1;
    if found then
      return jsonb_build_object('topic_id', t.id, 'plan_revision_id', pr.id, 'approved', v_ap is not null, 'approve', v_ap,
        'render', jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true), 'existing', true);
    end if;
  end if;
  v_render := drinks_request_render(jsonb_strip_nulls(jsonb_build_object('plan_revision_id', pr.id, 'retry_of', v_retry)));
  return jsonb_build_object('topic_id', t.id, 'plan_revision_id', pr.id, 'approved', v_ap is not null, 'approve', v_ap, 'render', v_render,
    'existing', coalesce((v_render ->> 'existing')::boolean, false));
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한 (0073 과 같은 방식: anon·authenticated 에 아무것도 주지 않는다)
-- ─────────────────────────────────────────────────────────────
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
