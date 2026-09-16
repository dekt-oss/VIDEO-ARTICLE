-- 0046 — 초안 요청에 "이어서 만들 지시서 버전"을 싣는다 (설계안_초안지시서_통합발주_v2 §3).
--
-- 운영자 지시(2026-09-11): "초안 생성이랑 작업지시서를 하나로 합쳐 초안 생성에서 바로 스타일을
-- 고를 수 있게." 초안을 만들 때 버전을 고르면 워커가 초안을 저장한 뒤 **같은 실행에서** 그
-- 버전들의 지시서를 이어서 만든다(engine/draft.py · engine/report_draft.py).
--
-- ★ null 이면 지금과 같다 — 지시서를 자동으로 만들지 않는다. 옛 행·옛 웹이 그대로 돈다.
-- ★ 허용값은 engine/config.VIDEO_VERSIONS 와 web/lib/versions.ts 가 이미 갖고 있는 것
--   (comic · photo). DB 제약으로 묶지 않는다 — 버전 목록은 코드가 정본이고, 여기서 CHECK 를
--   걸면 버전을 하나 늘릴 때마다 마이그레이션이 또 필요해진다.
alter table draft_requests        add column if not exists version_types text[];
alter table report_draft_requests add column if not exists version_types text[];

comment on column draft_requests.version_types is
  '초안 저장 뒤 이어서 만들 지시서 버전(comic·photo). null=자동 생성 없음(옛 동작).';
comment on column report_draft_requests.version_types is
  '초안 저장 뒤 이어서 만들 지시서 버전(comic·photo). null=자동 생성 없음(옛 동작).';

-- ── 낡은 지시서 감지용 updated_at (설계안 v2 §2-2) ─────────────────────────────
-- 초안을 고쳐 저장하면 이미 만든 지시서는 옛 대본 기준이다. 화면이 `drafts.updated_at >
-- directives.created_at` 이면 주 버튼을 [지시서 재생성]으로 바꾼다. 트리거로 갱신한다 —
-- 쓰는 곳이 셋(웹 라우트·엣지·워커)이라 각자 now() 를 넣게 하면 하나는 빠진다.
-- search_path 를 고정한다(0003 harden_function 과 같은 이유 — 보안 어드바이저가 잡는다).
create or replace function set_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at = now();
  return new;
end $$;

alter table drafts        add column if not exists updated_at timestamptz default now();
alter table report_drafts add column if not exists updated_at timestamptz default now();

drop trigger if exists drafts_set_updated_at on drafts;
create trigger drafts_set_updated_at before update on drafts
  for each row execute function set_updated_at();
drop trigger if exists report_drafts_set_updated_at on report_drafts;
create trigger report_drafts_set_updated_at before update on report_drafts
  for each row execute function set_updated_at();
