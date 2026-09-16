-- 비용 원장 (작업 C, 명세 §6) — 모든 외부 생성 호출 1건 = 1행.
-- 잡당 누적 float(render_jobs.cost_estimate) 한 개로는 Batch/Realtime·Lite/Fast·재생성 혼합을
-- 담을 수 없어(§6.1), 호출별 원장을 둔다. 단가는 호출 시점 값을 unit_price_usd 스냅샷(§6.2)으로
-- 박아 무거운 pricing_versions 테이블 없이 과거 비용을 재현한다(경량 경로).
--
-- 도메인 매핑: 이 저장소는 directive(=주제의 Visual Plan) + render_jobs(=언어별 Variant) 로
-- 명세의 Topic/Asset Bundle/Render Variant 를 이미 구현하므로, 원장은 directive_id(주제) +
-- render_job_id(변형, nullable) + cut_no 로 귀속한다. 공유 시각 에셋은 directive 에 1회만 귀속
-- (§6.3 중복 계상 방지).
--
-- rollback: drop table if exists generation_attempts;

create table if not exists generation_attempts (
  id                 uuid primary key default gen_random_uuid(),
  directive_id       uuid references directives(id) on delete cascade,
  render_job_id      uuid references render_jobs(id) on delete set null,
  cut_no             int,
  asset_type         text,          -- image | video | tts | llm
  provider           text,
  model_id           text,
  generation_mode    text,          -- standard | batch | realtime
  attempt_no         int  default 1,
  requested_units    numeric,
  billed_units       numeric,
  unit_type          text,          -- image_standard | image_batch | video_720p_per_sec | tts_per_char
  unit_price_usd     numeric,       -- ★ 당시 단가 스냅샷 (pricing_versions 테이블 대체)
  price_verified_at  timestamptz,
  estimated_cost_usd numeric,
  actual_cost_usd    numeric,
  status             text,          -- succeeded | failed
  error_class        text,
  idempotency_key    text,
  created_at         timestamptz default now(),
  completed_at       timestamptz,
  -- 같은 논리 호출의 중복 기록 방지(멱등키 있는 호출만; null 키는 Postgres 가 서로 distinct 로 취급).
  unique (idempotency_key, attempt_no)
);
create index if not exists gen_attempts_directive_idx on generation_attempts (directive_id, created_at);
create index if not exists gen_attempts_type_idx on generation_attempts (asset_type, generation_mode);

-- 공개 접근 정책(기존 render_* 테이블과 동일 패턴, 0009). 엔진은 service_role 로 삽입(RLS 무관).
alter table generation_attempts enable row level security;
drop policy if exists generation_attempts_public_all on generation_attempts;
create policy generation_attempts_public_all on generation_attempts
  for all to anon, authenticated using (true) with check (true);
