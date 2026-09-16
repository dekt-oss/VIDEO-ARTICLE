-- 공개 저장소 전환 전 잠금: anon·authenticated 의 **모든 쓰기**를 닫는다 (2026-09-15)
--
-- 무엇이 문제였나 — 라이브 실측(pg_policies · has_table_privilege, 2026-09-15):
--   0007 이 "로그인 제거"로 전 테이블을 anon 에게 for all using(true) with check(true) 로 열었고,
--   0031 은 렌더·업로드 큐 4개만 닫았다. 남은 anon 쓰기 표면이 24개 정책이었다:
--     · 비용 큐 5개  draft_requests · directive_requests · report_draft_requests ·
--                   report_directive_requests · image_batch_jobs
--                   → 행 1개 = 크론 워커가 유료 LLM·이미지 호출
--     · render_assets · report_render_assets
--                   → 워커가 캐시 적중 시 asset_url 을 **그대로 내려받아** 영상에 넣는다.
--                     anon 이 행을 심으면 남의 그림·영상이 유튜브 업로드본에 들어간다.
--     · directives · report_directives · drafts(update) · report_drafts(update)
--                   → 승인 전후 대본·지시서 변조(화면에 나가는 내용)
--     · decisions · report_decisions · batch_review · report_batch_review · published ·
--       report_published · generation_attempts(비용 원장) · collection_state(수집 워터마크) ·
--       paper_discovery_events · unresolved_buzz_items · youtube_analytics(_daily) ·
--       performance_reports → 운영 상태·원장 변조
--   그리고 RLS 가 **꺼진** public.storage_objects_backup_20260821(471행)을 anon 이 읽고·쓰고·지울 수 있었다.
--   anon 키는 공개값으로 취급해야 한다(설계상 그렇다). 저장소가 공개되면 스키마·큐 이름까지 읽힌다.
--
-- 변경:
--   1) public 스키마의 anon/authenticated/public 대상 ALL·INSERT·UPDATE·DELETE 정책을 전부 지운다.
--      ALL 정책이던 테이블에는 **읽기 전용 정책**을 만들어 대시보드 표시가 깨지지 않게 한다.
--   2) 표 권한도 회수한다(정책이 실수로 다시 열려도 권한이 없으면 못 쓴다 — 이중 잠금).
--      앞으로 만들 표에도 anon 쓰기 권한이 기본으로 붙지 않게 기본 권한을 바꾼다.
--   3) 백업 표는 RLS 를 켜고 anon/authenticated 권한을 전부 회수한다(삭제는 운영자 결정 — 여기서 안 한다).
--
-- 영향 없는 것:
--   · 엔진 워커·엣지 함수 — service_role 로 붙어 RLS·표 권한 회수와 무관하다(engine/db.py).
--   · 대시보드 쓰기 — 같은 커밋에서 모든 쓰기 라우트를 queueWriter(service key)로 옮겼다.
--   · 대시보드 읽기 — SELECT 정책은 그대로다.
--
-- ★ 적용 순서(반드시): ① Vercel 에 SUPABASE_SERVICE_KEY 가 있는지 확인 ② 이 커밋의 web 배포 완료
--   ③ 그다음 이 마이그레이션. 거꾸로 하면 낙점·검수·승인·대본 수정 버튼이 전부 RLS 로 거부된다.
--
-- 되돌리기: 필요한 테이블에 `create policy <t>_public_all on public.<t> for all to anon, authenticated
--   using (true) with check (true)` 와 `grant insert, update, delete on public.<t> to anon, authenticated`.

do $$
declare
  p record;
  has_other_select boolean;
begin
  for p in
    select tablename, policyname, cmd
    from pg_policies
    where schemaname = 'public'
      and cmd in ('ALL', 'INSERT', 'UPDATE', 'DELETE')
      and roles && array['anon', 'authenticated', 'public']::name[]
  loop
    if p.cmd = 'ALL' then
      select exists (
        select 1 from pg_policies q
        where q.schemaname = 'public' and q.tablename = p.tablename
          and q.policyname <> p.policyname and q.cmd = 'SELECT'
          and q.roles && array['anon']::name[]
      ) into has_other_select;
      if not has_other_select then
        execute format(
          'create policy %I on public.%I for select to anon, authenticated using (true)',
          p.tablename || '_read_only_anon', p.tablename);
      end if;
    end if;
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

-- 2) 표 권한 회수(이중 잠금) + 앞으로 생길 표의 기본 권한
revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated;
alter default privileges in schema public revoke insert, update, delete, truncate on tables from anon, authenticated;

-- 3) RLS 가 꺼져 있던 백업 표
alter table if exists public.storage_objects_backup_20260821 enable row level security;
revoke all on table public.storage_objects_backup_20260821 from anon, authenticated;

-- 확인(적용 후):
--   select tablename, policyname, cmd, roles from pg_policies
--   where schemaname = 'public' and cmd <> 'SELECT' and roles && array['anon','authenticated']::name[];
--   → 0행
--   select has_table_privilege('anon', 'public.draft_requests', 'INSERT');  → false
