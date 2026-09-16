-- 언어 추가 렌더 계보 (수정명세 v1 §2-3) — docs/deviation-clip-fit-add-language.md
-- ⑥ 렌더 결과 화면에서 완료된 잡의 "다른 언어 버전 추가 생성"을 누르면, 같은 directive_id 로
-- 언어만 다른 render_jobs 를 하나 더 만든다. 어느 잡에서 파생됐는지(계보)를 남겨 UI 가
-- "KO 원본 → EN 파생" 을 나란히 보여주고, 캐시 미스 조사 시 원본을 되짚을 수 있게 한다.
alter table render_jobs
  add column if not exists source_job_id uuid references render_jobs(id) on delete set null;

create index if not exists render_jobs_source_idx on render_jobs (source_job_id);

-- ★ reuse_assets 컬럼은 두지 않는다(명세 §2-3 의 3개 컬럼 중 1개만 채택).
--   근거: 에셋 캐시(render_assets.content_hash)는 이미 언어 독립이다 — 해시 payload 에 언어가
--   없고(engine/assemble.py content_hash), _gen_still 은 lang 인자를 받지도 않으며,
--   tests/test_shared_assets.py 가 "KO 가 만든 에셋을 EN 이 재사용 → 생성 호출 1회" 를 이미 검증한다.
--   즉 재사용은 잡의 플래그가 아니라 파이프라인의 구조적 불변식이라, 플래그를 두면 같은 사실에
--   대한 두 번째 진실원이 생기고 어긋날 수 있다.
