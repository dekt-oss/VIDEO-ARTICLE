-- 0040 — 대본 정본 가드 + 원장 종류 제약 (PR #94 후속 리뷰 P1-3 · P2-1).
--
-- ① report_drafts.validated_script_hash
--    "화면에 뜬 검사 결과가 **어느 대본**에 대한 것인가"를 붙들어 둔다.
--    문제: ④ 화면은 [재검사] 로 검사를 받고 나서도 대본을 또 고칠 수 있다. 그러면 화면의
--    "근거 없는 문장 없음"은 고치기 전 대본에 대한 판정인데, 운영자는 그걸 보고 승인한다.
--    이제 초안 생성·재검사 때 그 시점 대본의 지문을 남기고, ④ 가 지금 대본의 지문과 비교해
--    "검증 이후 수정됨"을 표시한다. **차단하지 않는다**(운영자 결정) — 표시하고, 그 상태로
--    승인하면 발행 기록에 흔적을 남긴다. 설명판형 게이트가 쓰는 자세와 같다.
--    지문 계약: sha256(대본 원문 utf-8) 앞 16글자. 엔진(engine/script_revision.py)과
--    웹(web/lib/scriptRevision.ts)이 같은 값을 계산한다 — 갈리면 경고가 늘 켜진다.
--
-- ② report_published.validated_at_approval
--    승인 시점에 그 대본이 검증된 상태였는지. 나중에 문제가 생긴 편을 되짚을 때 쓴다.
--
-- ③ generation_attempts.render_job_kind CHECK
--    0039 에서 외래키를 떼고 kind 로 구분하게 했는데, 허용값을 강제하지 않아 'banana' 도
--    들어갈 수 있었다. 기존 FK 가 보장하던 정합성을 애플리케이션이 떠안은 상태였다.
--
-- 되돌리기:
--   alter table report_drafts drop column if exists validated_script_hash;
--   alter table report_published drop column if exists validated_at_approval;
--   alter table generation_attempts drop constraint if exists generation_attempts_job_kind_chk;

alter table report_drafts
  add column if not exists validated_script_hash text not null default '';

comment on column report_drafts.validated_script_hash is
  '마지막으로 검증(초안 생성·재검사)을 통과한 대본의 지문. sha256(script_md) 앞 16글자.';

alter table report_published
  add column if not exists validated_at_approval boolean not null default true;

comment on column report_published.validated_at_approval is
  '승인 시점에 대본이 검증된 상태였는가. false = 검사 이후 수정된 대본으로 승인함(흔적).';

alter table generation_attempts
  drop constraint if exists generation_attempts_job_kind_chk;

alter table generation_attempts
  add constraint generation_attempts_job_kind_chk
  check (render_job_kind in ('paper', 'report'));
