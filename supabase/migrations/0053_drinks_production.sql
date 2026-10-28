-- 주류 공장 C단계 — 제작 작업·파일·manifest·최종 파일 검수·비용 (2026-10-23). docs/deviation-drinks-production.md
--
-- 명세 §7(production_jobs·media_assets·asset_manifests·deliverable_assets·output_reviews)·§8.3·§12.
-- 0050(A)·0051(B)·0052(B 보완) 위. 기존 논문·리포트 표(render_jobs·report_render_jobs·render_assets)는 건드리지 않는다 —
-- 그 표들에 주류 행이 들어가면 storage_gc 가 걷는다. 주류 파일은 별도 표와 `drinks/` 접두어에만 둔다.
--
--   drink_production_jobs     제작 작업 1회(영상·카드). 입력은 승인된 제작안 버전 + 그 근거 버전의 승인 해시로 고정
--   drink_media_assets        파일(불변). 저장 위치·sha256·크기·길이·출처(공급자·모델)·권리
--   drink_asset_manifests     파일 묶음(불변). 재렌더 = 새 묶음. 같은 제작안에 여러 묶음 가능
--   drink_manifest_assets     묶음 안 파일의 역할·순서(불변). 영상 = final_video 1 + cover 1, 카드 = page 1..n 연속
--   drink_output_reviews      최종 파일 검수(묶음 1:1). 생성 성공과 별개 — 승인 때 제작안·근거 유효성을 다시 잰다
--   drink_cost_entries        비용(append-only). 작업·시도·공급자·모델에 귀속. 공유 파일 비용은 한 번만
--
-- 유료 생성은 **꺼져 있다**: 작업 요청이 paid 를 원하면 'paid_disabled'(예산 미설정) 로 거부한다. 예산·승인 절차를 정할 때
-- 이 함수를 바꾼다. 지금은 로컬 렌더(무료 TTS·로컬 장면 카드)만 돈다.
--
-- 되돌리기: 아래 표 6개와 이 파일의 drinks_* 함수를 drop 한다(다른 표는 이 표들을 참조하지 않는다).

create or replace function drinks_production_limits() returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'lease_sec', 1800,           -- 렌더 1회 임대. 하트비트가 연장한다
    'max_pages', 12,             -- 카드뉴스 페이지 상한
    'renderer_version', 'drinks-render-v1'
  )
$$;

create table if not exists drink_production_jobs (
  id               uuid primary key default gen_random_uuid(),
  topic_id         uuid not null references drink_topics(id),
  plan_revision_id uuid not null references drink_plan_revisions(id),
  format           text not null check (format in ('video','carousel')),
  status           text not null default 'queued' check (status in ('queued','running','succeeded','failed','canceled')),
  attempt_no       int not null default 1 check (attempt_no >= 1),   -- 수동 재시도 차례. 자동 재시도는 없다
  retry_of         uuid references drink_production_jobs(id),
  input_hash       text not null,
  plan_hash        text not null,           -- 요청 시점 제작안 승인 해시
  review_hash      text not null,           -- 요청 시점 근거·기획 승인 해시
  renderer         text not null default 'local' check (renderer in ('local','paid')),
  renderer_version text not null,
  lease_token      uuid,
  lease_expires_at timestamptz,
  heartbeat_at     timestamptz,
  worker_id        text,
  cancel_requested boolean not null default false,
  requested_by     text not null default 'operator',
  error_code       text,
  error_message    text check (error_message is null or length(error_message) <= 2000),
  result_manifest_id uuid,
  created_at       timestamptz not null default now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  check (status <> 'running' or (lease_token is not null and started_at is not null)),
  check (status in ('queued','running') or finished_at is not null)
);
-- 같은 제작안·같은 입력의 활성 작업은 하나(중복 요청은 그 작업을 돌려준다).
create unique index if not exists drink_prod_one_active_uq on drink_production_jobs (plan_revision_id, input_hash)
  where status in ('queued','running');
create index if not exists drink_prod_status_idx on drink_production_jobs (status, created_at);
create index if not exists drink_prod_plan_idx on drink_production_jobs (plan_revision_id, created_at desc);

create table if not exists drink_media_assets (
  id           uuid primary key default gen_random_uuid(),
  storage_key  text not null check (storage_key ~ '^(drinks/|local:)'),   -- 주류 전용 접두어(논문·리포트 GC 가 걷지 않음)
  sha256       text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  mime         text not null check (mime in ('video/mp4','image/png','image/jpeg','audio/mp4','text/plain')),
  bytes        bigint not null check (bytes > 0),
  width        int,
  height       int,
  duration_ms  int,
  rights       text not null check (rights in ('generated_local','generated_paid','licensed','own')),
  provenance   jsonb not null default '{}' check (jsonb_typeof(provenance) = 'object'),   -- 공급자·모델·도구(비밀 없음)
  job_id       uuid references drink_production_jobs(id),
  state        text not null default 'stored' check (state in ('stored','deleting','deleted')),
  created_at   timestamptz not null default now()
);
create unique index if not exists drink_media_key_uq on drink_media_assets (storage_key);
create index if not exists drink_media_hash_idx on drink_media_assets (sha256);

create table if not exists drink_asset_manifests (
  id               uuid primary key default gen_random_uuid(),
  plan_revision_id uuid not null references drink_plan_revisions(id),
  job_id           uuid not null references drink_production_jobs(id),
  format           text not null check (format in ('video','carousel')),
  manifest_hash    text not null,
  input_hash       text not null,
  created_at       timestamptz not null default now()
);
create unique index if not exists drink_manifest_hash_uq on drink_asset_manifests (plan_revision_id, manifest_hash);
alter table drink_production_jobs drop constraint if exists drink_prod_manifest_fk;
alter table drink_production_jobs add constraint drink_prod_manifest_fk foreign key (result_manifest_id)
  references drink_asset_manifests(id);

create table if not exists drink_manifest_assets (
  manifest_id uuid not null references drink_asset_manifests(id),
  asset_id    uuid not null references drink_media_assets(id),
  role        text not null check (role in ('final_video','cover','page','subtitles')),
  position    int not null check (position >= 1),
  primary key (manifest_id, role, position)
);

create table if not exists drink_output_reviews (
  id               uuid primary key default gen_random_uuid(),
  manifest_id      uuid not null references drink_asset_manifests(id),
  plan_revision_id uuid not null references drink_plan_revisions(id),
  status           text not null default 'pending' check (status in ('pending','approved','changes_requested','blocked')),
  qa_summary       jsonb not null default '{}',     -- 렌더가 남긴 기계 검사(길이·해상도·페이지 넘침 등) — 판정이 아니라 참고
  checklist        jsonb,                           -- 사람이 확인한 항목(장면 유형 표기·실제 제품 오인 없음·글자 잘림 없음 …)
  reviewer         text,
  reviewed_at      timestamptz,
  reason           text,
  revoked_at       timestamptz,
  version          int not null default 1,
  created_at       timestamptz not null default now(),
  check (status not in ('changes_requested','blocked') or reason is not null),
  check (status <> 'approved' or (checklist is not null and reviewed_at is not null))
);
create unique index if not exists drink_output_review_manifest_uq on drink_output_reviews (manifest_id);

create table if not exists drink_cost_entries (
  id            bigint generated always as identity primary key,
  job_id        uuid not null references drink_production_jobs(id),
  attempt_no    int not null,
  kind          text not null check (kind in ('image','video','tts','llm','render','card')),
  provider      text not null,
  model         text,
  units         numeric,
  cost_usd      numeric(10,4) not null check (cost_usd >= 0),
  estimated     boolean not null default false,   -- 공급자 청구 확인 전 추정치
  shared_asset_id uuid references drink_media_assets(id),   -- 두 형식이 함께 쓰는 파일 비용은 이 파일에 한 번만
  note          text,
  created_at    timestamptz not null default now()
);
create unique index if not exists drink_cost_shared_uq on drink_cost_entries (shared_asset_id) where shared_asset_id is not null;

-- ─────────────────────────────────────────────────────────────
-- 불변 트리거
-- ─────────────────────────────────────────────────────────────

drop trigger if exists drink_cost_append_only on drink_cost_entries;
create trigger drink_cost_append_only before update or delete on drink_cost_entries
  for each row execute function drink_append_only_guard();
drop trigger if exists drink_manifest_assets_append_only on drink_manifest_assets;
create trigger drink_manifest_assets_append_only before update or delete on drink_manifest_assets
  for each row execute function drink_append_only_guard();
drop trigger if exists drink_manifests_append_only on drink_asset_manifests;
create trigger drink_manifests_append_only before update or delete on drink_asset_manifests
  for each row execute function drink_append_only_guard();

-- 파일: 내용 칸은 불변. 상태(stored → deleting → deleted)만 앞으로 간다. 승인된 묶음에 든 파일은 지울 수 없다.
create or replace function drink_media_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '파일 기록은 삭제할 수 없습니다(상태로만 표시)'); end if;
  if (to_jsonb(new) - 'state') is distinct from (to_jsonb(old) - 'state') then
    perform drinks_fail('immutable', '파일 기록은 바꿀 수 없습니다');
  end if;
  if new.state <> old.state then
    if (old.state, new.state) not in (('stored','deleting'), ('deleting','deleted'), ('deleting','stored')) then
      perform drinks_fail('invalid_transition', '파일 상태 ' || old.state || ' → ' || new.state || ' 는 허용되지 않습니다');
    end if;
    -- 묶음에 든 파일은 검수 상태(승인·대기·고칠 점·차단)와 상관없이 정리할 수 없다 — 차단된 묶음도 "파일 보존"이다.
    -- 정리 규칙(보관 기한·참조 해제)은 아직 없다(명세 §12, 드라이런 검증 후 연결).
    if new.state = 'deleting' and exists (select 1 from drink_manifest_assets ma where ma.asset_id = new.id) then
      perform drinks_fail('asset_in_use', '파일 묶음에 든 파일은 정리할 수 없습니다');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_media_guard on drink_media_assets;
create trigger drink_media_guard before update or delete on drink_media_assets
  for each row execute function drink_media_guard();

create or replace function drink_prod_jobs_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '제작 작업 기록은 삭제할 수 없습니다'); end if;
  if old.status not in ('queued','running') and to_jsonb(new) is distinct from to_jsonb(old) then
    perform drinks_fail('immutable', '끝난 제작 작업은 바꿀 수 없습니다');
  end if;
  if (old.status, new.status) not in (('queued','queued'), ('queued','running'), ('queued','canceled'), ('running','running'),
      ('running','succeeded'), ('running','failed'), ('running','canceled')) then
    perform drinks_fail('invalid_transition', '제작 작업 ' || old.status || ' → ' || new.status || ' 는 허용되지 않습니다');
  end if;
  if new.plan_revision_id <> old.plan_revision_id or new.input_hash <> old.input_hash or new.format <> old.format then
    perform drinks_fail('immutable', '제작 작업의 입력은 바꿀 수 없습니다');
  end if;
  return new;
end $$;
drop trigger if exists drink_prod_jobs_guard on drink_production_jobs;
create trigger drink_prod_jobs_guard before update or delete on drink_production_jobs
  for each row execute function drink_prod_jobs_guard();

-- 검수: 승인 전이는 함수를 우회한 UPDATE 로도 조건을 넘지 못한다(제작안·근거가 지금도 유효해야).
create or replace function drink_output_reviews_guard() returns trigger language plpgsql as $$
declare pl drink_plan_revisions;
begin
  if tg_op = 'DELETE' then perform drinks_fail('immutable', '검수 기록은 삭제할 수 없습니다'); end if;
  if tg_op = 'UPDATE' then
    if new.manifest_id <> old.manifest_id or new.plan_revision_id <> old.plan_revision_id then
      perform drinks_fail('immutable', '검수 대상은 바꿀 수 없습니다');
    end if;
    if old.status = 'blocked' and new.status <> 'blocked' then
      perform drinks_fail('immutable', '차단된 검수는 풀 수 없습니다 — 유효한 근거로 새 제작안을 만들어 다시 렌더하세요');
    end if;
    new.version := old.version + 1;
  end if;
  if new.status = 'approved' and (tg_op = 'INSERT' or old.status <> 'approved') then
    select * into pl from drink_plan_revisions where id = new.plan_revision_id;
    if pl.plan_status <> 'approved' or pl.blocked_at is not null or pl.revoked_at is not null or not drinks_approval_valid(pl.topic_review_id) then
      perform drinks_fail('review_blocked', '이 파일 묶음의 제작안·근거가 지금은 유효하지 않아 승인할 수 없습니다');
    end if;
    if exists (select 1 from drink_manifest_assets ma join drink_media_assets a on a.id = ma.asset_id
        where ma.manifest_id = new.manifest_id and a.state <> 'stored') then
      perform drinks_fail('asset_missing', '묶음의 파일 중 정리된 것이 있어 승인할 수 없습니다');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists drink_output_reviews_guard on drink_output_reviews;
create trigger drink_output_reviews_guard before insert or update or delete on drink_output_reviews
  for each row execute function drink_output_reviews_guard();

-- ─────────────────────────────────────────────────────────────
-- 헬퍼
-- ─────────────────────────────────────────────────────────────

-- 이 제작안을 지금 렌더해도 되는가: 승인됨·차단 안 됨·철회 안 됨·근거 승인이 지금도 유효함.
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

-- 화면용(PostgREST rpc 는 jsonb 하나로 부른다).
create or replace function drinks_plan_render_state(p jsonb) returns jsonb language plpgsql as $$
begin
  -- 워커가 죽어 '렌더 중'에 남은 작업을 화면을 열 때도 정리한다(그대로 두면 요청 버튼이 영영 숨는다 — 검토 지적).
  perform drinks_reap_prod_jobs();
  return jsonb_build_object('block', drinks_plan_renderable(drinks_uuid(p, 'plan_revision_id')));
end $$;

create or replace function drinks_lock_prod_job(p jsonb) returns drink_production_jobs language plpgsql as $$
declare j drink_production_jobs;
begin
  select * into j from drink_production_jobs where id = drinks_uuid(p, 'job_id') for update;
  if not found then perform drinks_fail('not_found', '제작 작업을 찾지 못했습니다'); end if;
  if j.status <> 'running' or j.lease_token is distinct from drinks_uuid(p, 'lease_token') or j.lease_expires_at < now() then
    perform drinks_fail('lease_lost', '이 제작 작업의 임대를 잃었습니다(다른 워커가 회수했거나 끝났음)');
  end if;
  return j;
end $$;

create or replace function drinks_reap_prod_jobs() returns int language plpgsql as $$
declare n int := 0; r record;
begin
  for r in select id from drink_production_jobs where status = 'running' and lease_expires_at < now()
      order by id for update skip locked loop
    update drink_production_jobs set status = 'failed', finished_at = now(), lease_token = null,
      error_code = 'lease_expired', error_message = '워커 응답이 끊겨 실패 처리했습니다 — 늦게 끝난 결과는 저장하지 않습니다'
      where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 운영자 RPC
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_request_render(p jsonb) returns jsonb language plpgsql as $$
declare pl drink_plan_revisions; rv drink_topic_reviews; j drink_production_jobs; v_block text; v_input text;
  v_attempt int; prev drink_production_jobs;
begin
  perform drinks_reap_prod_jobs();
  if coalesce((p ->> 'paid')::boolean, false) then
    perform drinks_fail('paid_disabled', '유료 생성은 예산이 정해지지 않아 꺼져 있습니다 — 로컬 렌더만 요청할 수 있습니다');
  end if;
  select * into pl from drink_plan_revisions where id = drinks_uuid(p, 'plan_revision_id') for update;
  v_block := drinks_plan_renderable(pl.id);
  if v_block is not null then
    perform drinks_fail(case v_block when 'not_found' then 'not_found' else 'not_renderable' end,
      case v_block when 'not_found' then '제작안을 찾지 못했습니다'
        when 'plan_not_approved' then '승인된 제작안만 렌더합니다'
        when 'plan_blocked' then '차단된 제작안입니다(근거 철회·권리 변경)'
        else '이 제작안이 쓴 근거를 지금은 쓸 수 없습니다' end);
  end if;
  select * into rv from drink_topic_reviews where id = pl.topic_review_id;
  v_input := encode(sha256(convert_to(pl.id || '|' || pl.approved_hash || '|' || rv.approved_hash || '|' ||
    (drinks_production_limits() ->> 'renderer_version') || '|local', 'UTF8')), 'hex');
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
      review_hash, renderer, renderer_version, requested_by)
    values (pl.topic_id, pl.id, pl.format, v_attempt, prev.id, v_input, pl.approved_hash, rv.approved_hash, 'local',
      drinks_production_limits() ->> 'renderer_version', 'operator')
    returning * into j;
  exception when unique_violation then
    select * into j from drink_production_jobs where plan_revision_id = pl.id and input_hash = v_input
      and status in ('queued','running');
    return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', true);
  end;
  perform drinks_log(pl.topic_id, 'plan', pl.id, 'render_requested', null, 'queued', j.id::text, null,
    jsonb_build_object('format', pl.format, 'attempt_no', j.attempt_no, 'renderer', 'local'));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'existing', false, 'attempt_no', j.attempt_no);
end $$;

create or replace function drinks_cancel_render(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs;
begin
  perform drinks_reap_prod_jobs();   -- 임대가 끝난 '렌더 중'은 여기서 실패로 닫힌다(취소 표시만 남고 멈추지 않게)
  select * into j from drink_production_jobs where id = drinks_uuid(p, 'job_id') for update;
  if not found then perform drinks_fail('not_found', '제작 작업을 찾지 못했습니다'); end if;
  if j.status = 'queued' then
    update drink_production_jobs set status = 'canceled', finished_at = now(), error_code = 'canceled',
      error_message = coalesce(drinks_text(p, 'reason'), '운영자 취소') where id = j.id returning * into j;
  elsif j.status = 'running' then
    -- 진행 중 취소는 최선 노력: 워커가 다음 하트비트에서 멈춘다. 이미 든 비용·파일은 기록된다.
    update drink_production_jobs set cancel_requested = true where id = j.id returning * into j;
  end if;
  -- 이미 끝난 작업(위 정리로 방금 실패 처리된 것 포함)은 오류 없이 상태만 돌려준다 — 오류를 던지면 정리까지 되돌아간다.
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'cancel_requested', j.cancel_requested);
end $$;

-- 최종 파일 검수. 승인은 체크리스트(사람)가 모두 확인돼야 하고, 지금도 제작안·근거가 유효해야 한다(트리거가 다시 잰다).
create or replace function drinks_output_review_action(p jsonb) returns jsonb language plpgsql as $$
declare r drink_output_reviews; v_action text := drinks_text(p, 'action'); v_block text; ck jsonb := p -> 'checklist';
  k text; required text[];
begin
  select * into r from drink_output_reviews where id = drinks_uuid(p, 'review_id') for update;
  if not found then perform drinks_fail('not_found', '검수 기록을 찾지 못했습니다'); end if;
  if drinks_int(p, 'expected_version') is distinct from r.version then
    perform drinks_fail('version_conflict', '다른 곳에서 먼저 바뀌었습니다 — 화면을 새로 불러오세요');
  end if;
  if r.status not in ('pending','changes_requested') and v_action <> 'revoke' then
    perform drinks_fail('invalid_state', '검수 대기 중인 묶음만 판정합니다');
  end if;
  if v_action = 'approve' then
    -- 권리 철회·근거 무효화는 제작안 행을 바꾼다(blocked_at). 그 행을 먼저 잠가 진행 중인 철회를 기다린 뒤 다시 잰다 —
    -- 아니면 아직 커밋 안 된 철회를 못 보고 승인이 통과한다(실제 Postgres 경합 ⑭).
    perform 1 from drink_plan_revisions where id = r.plan_revision_id for share;
    v_block := drinks_plan_renderable(r.plan_revision_id);
    if v_block is not null then
      update drink_output_reviews set status = 'blocked', reason = '승인 시점 재검사: ' || v_block where id = r.id returning * into r;
      return jsonb_build_object('review_id', r.id, 'status', r.status, 'blocked_by', v_block);
    end if;
    required := case (select format from drink_asset_manifests where id = r.manifest_id)
      when 'video' then array['scene_types_labeled','no_real_product_implied','claims_match_evidence','audio_subtitles_ok','vertical_ok']
      else array['page_order_ok','no_text_overflow','claims_match_evidence','source_page_ok'] end;
    if ck is null or jsonb_typeof(ck) <> 'object' then perform drinks_fail('invalid_input', '검수 체크리스트가 필요합니다'); end if;
    foreach k in array required loop
      if coalesce((ck ->> k)::boolean, false) is not true then
        perform drinks_fail('checklist_incomplete', '확인하지 않은 검수 항목이 있습니다: ' || k, to_jsonb(required));
      end if;
    end loop;
    update drink_output_reviews set status = 'approved', checklist = ck, reviewer = coalesce(drinks_text(p, 'reviewer'), 'operator'),
      reviewed_at = now(), reason = drinks_text(p, 'reason') where id = r.id returning * into r;
  elsif v_action = 'request_changes' then
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '고칠 점을 적으세요'); end if;
    update drink_output_reviews set status = 'changes_requested', reason = drinks_text(p, 'reason'), checklist = ck,
      reviewed_at = now() where id = r.id returning * into r;
  elsif v_action = 'revoke' then
    if r.status <> 'approved' then perform drinks_fail('invalid_state', '승인된 검수만 철회합니다'); end if;
    if drinks_text(p, 'reason') is null then perform drinks_fail('invalid_input', '철회 사유를 적으세요'); end if;
    update drink_output_reviews set status = 'blocked', revoked_at = now(), reason = drinks_text(p, 'reason')
      where id = r.id returning * into r;
  else
    perform drinks_fail('invalid_input', '알 수 없는 검수 동작입니다');
  end if;
  perform drinks_log((select topic_id from drink_plan_revisions where id = r.plan_revision_id), 'plan', r.plan_revision_id,
    'output_review_' || v_action, null, r.status, r.manifest_id::text, r.reason);
  return jsonb_build_object('review_id', r.id, 'status', r.status, 'version', r.version);
end $$;

-- ─────────────────────────────────────────────────────────────
-- 워커 RPC (engine/drinks_produce.py)
-- ─────────────────────────────────────────────────────────────

create or replace function drinks_start_render(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs; pl drink_plan_revisions; rv drink_topic_reviews; t drink_topics; v_block text; v_reaped int;
begin
  v_reaped := drinks_reap_prod_jobs();
  loop
    select * into j from drink_production_jobs where status = 'queued' order by created_at, id limit 1 for update skip locked;
    if not found then return jsonb_build_object('job', null, 'reaped', v_reaped); end if;
    -- 대기 중에 근거가 철회·만료됐거나 제작안이 차단됐으면 돌리지 않는다(비용을 쓰기 전에 멈춘다).
    v_block := drinks_plan_renderable(j.plan_revision_id);
    select * into pl from drink_plan_revisions where id = j.plan_revision_id;
    if v_block is null and pl.approved_hash is distinct from j.plan_hash then v_block := 'plan_changed'; end if;
    if v_block is not null then
      update drink_production_jobs set status = 'canceled', finished_at = now(), error_code = v_block,
        error_message = '대기 중에 제작안·근거가 바뀌어 렌더하지 않았습니다(' || v_block || ')' where id = j.id;
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
      'renderer_version', j.renderer_version, 'plan_revision_id', pl.id, 'plan', pl.plan_json, 'revision_no', pl.revision_no,
      'topic', jsonb_build_object('id', t.id, 'title', t.title, 'question', t.question, 'categories', to_jsonb(t.categories)),
      'brief', rv.brief, 'claims', rv.evidence_pack -> 'claims',
      'sources', coalesce((select jsonb_agg(jsonb_build_object('snapshot_id', s.id, 'title', s.title, 'publisher', s.publisher,
          'url', s.canonical_url, 'published_at', s.published_at))
        from drink_source_snapshots s where s.id in (select (ref ->> 'snapshot_id')::uuid
          from jsonb_array_elements(rv.evidence_pack -> 'claims') c, jsonb_array_elements(c -> 'source_refs') ref)), '[]')));
  end loop;
end $$;

create or replace function drinks_heartbeat_render(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs;
begin
  j := drinks_lock_prod_job(p);
  update drink_production_jobs set heartbeat_at = now(),
    lease_expires_at = now() + make_interval(secs => (drinks_production_limits() ->> 'lease_sec')::int)
    where id = j.id returning * into j;
  return jsonb_build_object('cancel_requested', j.cancel_requested, 'renderable', drinks_plan_renderable(j.plan_revision_id) is null);
end $$;

create or replace function drinks_register_asset(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs; a jsonb := p -> 'asset'; x drink_media_assets;
begin
  j := drinks_lock_prod_job(p);
  select * into x from drink_media_assets where storage_key = drinks_text(a, 'storage_key');
  if found then
    if x.sha256 <> drinks_text(a, 'sha256') then
      perform drinks_fail('immutable', '같은 저장 위치에 다른 내용을 올릴 수 없습니다 — 새 위치를 쓰세요');
    end if;
    return jsonb_build_object('asset_id', x.id, 'existing', true);
  end if;
  insert into drink_media_assets (storage_key, sha256, mime, bytes, width, height, duration_ms, rights, provenance, job_id)
  values (drinks_text(a, 'storage_key'), drinks_text(a, 'sha256'), drinks_text(a, 'mime'), (a ->> 'bytes')::bigint,
    drinks_int(a, 'width', false), drinks_int(a, 'height', false), drinks_int(a, 'duration_ms', false),
    coalesce(drinks_text(a, 'rights'), 'generated_local'),
    coalesce(case when jsonb_typeof(a -> 'provenance') = 'object' then a -> 'provenance' end, '{}'), j.id)
  returning * into x;
  return jsonb_build_object('asset_id', x.id, 'existing', false);
end $$;

create or replace function drinks_record_cost(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs; c jsonb := p -> 'cost'; v_id bigint;
begin
  j := drinks_lock_prod_job(p);
  insert into drink_cost_entries (job_id, attempt_no, kind, provider, model, units, cost_usd, estimated, shared_asset_id, note)
  values (j.id, j.attempt_no, drinks_text(c, 'kind'), drinks_text(c, 'provider'), drinks_text(c, 'model'), (c ->> 'units')::numeric,
    coalesce((c ->> 'cost_usd')::numeric, 0), coalesce((c ->> 'estimated')::boolean, false), drinks_uuid(c, 'shared_asset_id', false),
    left(drinks_text(c, 'note'), 500))
  on conflict (shared_asset_id) where shared_asset_id is not null do nothing
  returning id into v_id;
  return jsonb_build_object('cost_id', v_id, 'duplicate_shared', v_id is null);
end $$;

-- 렌더 끝. 성공이면 묶음(불변)을 만들고 검수를 연다. 진행 중에 근거가 무효가 됐으면 파일·비용은 남기고 검수를 blocked 로.
create or replace function drinks_finish_render(p jsonb) returns jsonb language plpgsql as $$
declare j drink_production_jobs; m drink_asset_manifests; el jsonb; v_hash text; v_block text; v_review drink_output_reviews;
  n_final int; n_cover int; n_pages int; max_pos int;
begin
  j := drinks_lock_prod_job(p);
  if drinks_text(p, 'outcome') = 'failed' or j.cancel_requested then
    update drink_production_jobs set status = case when j.cancel_requested then 'canceled' else 'failed' end, finished_at = now(),
      lease_token = null, error_code = coalesce(drinks_text(p, 'error_code'), case when j.cancel_requested then 'canceled' end),
      error_message = left(drinks_text(p, 'error_message'), 2000) where id = j.id returning * into j;
    return jsonb_build_object('job_id', j.id, 'status', j.status);
  end if;
  if jsonb_typeof(p -> 'assets') is distinct from 'array' or jsonb_array_length(p -> 'assets') = 0 then
    perform drinks_fail('invalid_input', '묶음에 들어갈 파일이 없습니다');
  end if;
  -- 파일은 이 작업이 등록한 것만. 역할·순서 규칙을 DB 가 잰다.
  if exists (select 1 from jsonb_array_elements(p -> 'assets') e where not exists (select 1 from drink_media_assets a
      where a.id = (e ->> 'asset_id')::uuid and a.job_id = j.id and a.state = 'stored')) then
    perform drinks_fail('ownership', '이 작업이 등록하지 않은 파일이 묶음에 있습니다');
  end if;
  select count(*) filter (where e ->> 'role' = 'final_video'), count(*) filter (where e ->> 'role' = 'cover'),
    count(*) filter (where e ->> 'role' = 'page'), max(((e ->> 'position')::int)) filter (where e ->> 'role' = 'page')
    into n_final, n_cover, n_pages, max_pos from jsonb_array_elements(p -> 'assets') e;
  if j.format = 'video' and (n_final <> 1 or n_cover <> 1 or n_pages <> 0) then
    perform drinks_fail('invalid_manifest', '영상 묶음은 최종 영상 1개와 커버 1개여야 합니다');
  end if;
  if j.format = 'carousel' and (n_final <> 0 or n_pages = 0 or max_pos <> n_pages
      or (select count(distinct (e ->> 'position')::int) from jsonb_array_elements(p -> 'assets') e where e ->> 'role' = 'page') <> n_pages
      or n_pages <> jsonb_array_length(coalesce((select plan_json -> 'pages' from drink_plan_revisions where id = j.plan_revision_id), '[]'))) then
    perform drinks_fail('invalid_manifest', '카드 묶음은 제작안 페이지 수만큼 1부터 빈칸·중복 없이 이어져야 합니다');
  end if;
  v_hash := encode(sha256(convert_to(j.input_hash || '|' || (select string_agg((e ->> 'role') || ':' || (e ->> 'position') || ':' ||
      (select a.sha256 from drink_media_assets a where a.id = (e ->> 'asset_id')::uuid), ',' order by e ->> 'role', ((e ->> 'position')::int))
    from jsonb_array_elements(p -> 'assets') e), 'UTF8')), 'hex');
  select * into m from drink_asset_manifests where plan_revision_id = j.plan_revision_id and manifest_hash = v_hash;
  if not found then
    insert into drink_asset_manifests (plan_revision_id, job_id, format, manifest_hash, input_hash)
      values (j.plan_revision_id, j.id, j.format, v_hash, j.input_hash) returning * into m;
    insert into drink_manifest_assets (manifest_id, asset_id, role, position)
      select m.id, (e ->> 'asset_id')::uuid, e ->> 'role', coalesce((e ->> 'position')::int, 1) from jsonb_array_elements(p -> 'assets') e;
  end if;
  v_block := drinks_plan_renderable(j.plan_revision_id);
  insert into drink_output_reviews (manifest_id, plan_revision_id, status, qa_summary, reason)
    values (m.id, j.plan_revision_id, case when v_block is null then 'pending' else 'blocked' end,
      coalesce(case when jsonb_typeof(p -> 'qa') = 'object' then p -> 'qa' end, '{}'),
      case when v_block is not null then '렌더 중 근거·제작안이 무효가 됨(' || v_block || ') — 파일·비용은 보존' end)
    on conflict (manifest_id) do nothing returning * into v_review;
  update drink_production_jobs set status = 'succeeded', finished_at = now(), lease_token = null, result_manifest_id = m.id
    where id = j.id returning * into j;
  perform drinks_log(j.topic_id, 'plan', j.plan_revision_id, 'render_finished', 'running', 'succeeded', m.id::text, v_block,
    jsonb_build_object('format', j.format, 'manifest_hash', v_hash, 'review', coalesce(v_review.status, 'existing')));
  return jsonb_build_object('job_id', j.id, 'status', j.status, 'manifest_id', m.id, 'manifest_hash', v_hash,
    'review_status', coalesce(v_review.status, (select status from drink_output_reviews where manifest_id = m.id)));
end $$;

-- 현재 사용 가능 판정(화면용): 검수 승인 + 제작안·근거가 지금도 유효 + 파일 모두 보관 중.
create or replace view drink_output_validity with (security_invoker = true) as
  select r.id as review_id, r.manifest_id, r.plan_revision_id, r.status,
    drinks_plan_renderable(r.plan_revision_id) as current_block,
    (r.status = 'approved' and drinks_plan_renderable(r.plan_revision_id) is null
      and not exists (select 1 from drink_manifest_assets ma join drink_media_assets a on a.id = ma.asset_id
        where ma.manifest_id = r.manifest_id and a.state <> 'stored')) as currently_usable
  from drink_output_reviews r;

-- 비공개 저장소(Supabase 에서만 — storage 스키마가 없는 테스트 DB 는 건너뛴다). 공개 버킷 renders 를 쓰지 않는다.
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public) values ('drinks', 'drinks', false) on conflict (id) do nothing;
  end if;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 권한
-- ─────────────────────────────────────────────────────────────

alter table drink_production_jobs enable row level security;
alter table drink_media_assets enable row level security;
alter table drink_asset_manifests enable row level security;
alter table drink_manifest_assets enable row level security;
alter table drink_output_reviews enable row level security;
alter table drink_cost_entries enable row level security;

revoke all on table drink_production_jobs, drink_media_assets, drink_asset_manifests, drink_manifest_assets, drink_output_reviews,
  drink_cost_entries from anon, authenticated;
revoke all on table drink_output_validity from anon, authenticated;
revoke all on sequence drink_cost_entries_id_seq from anon, authenticated;
grant select, insert, update on table drink_production_jobs, drink_media_assets, drink_asset_manifests, drink_manifest_assets,
  drink_output_reviews, drink_cost_entries to service_role;
grant select on table drink_output_validity to service_role;
grant usage on sequence drink_cost_entries_id_seq to service_role;

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
