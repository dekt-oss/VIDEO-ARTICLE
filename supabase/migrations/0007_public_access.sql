-- 로그인 제거(운영자 요청): 대시보드를 매직링크 없이 바로 열도록 RLS 를 공개(anon)로 전환.
--
-- ★ 트레이드오프: 이 마이그레이션 이후 anon 키만으로 데이터 read/write 가 가능하다
--   (공개 Vercel URL 을 아는 사람은 낙점/승인/초안요청을 바꿀 수 있음). 데이터는 비민감
--   (논문 메타·점수·대본)이며 SUPABASE_SERVICE_KEY 는 여전히 서버/엔진 전용이다.
-- ★ 되돌리기: 0002_rls.sql 의 authenticated + is_allowed_user() 정책을 다시 적용하고
--   web/middleware.ts 로그인 게이트를 복구하면 원상복구된다.
--
-- 엔진은 계속 service_role 로 RLS 를 우회한다(변경 없음).

-- 읽기 전용 테이블(엔진이 쓰고 사람은 봄): papers/scores/daily_batch/drafts → anon 조회 허용.
do $$
declare t text;
begin
  foreach t in array array['papers','scores','daily_batch','drafts'] loop
    execute format($f$
      drop policy if exists %1$s_select on %1$s;
      drop policy if exists %1$s_public_select on %1$s;
      create policy %1$s_public_select on %1$s
        for select to anon, authenticated using (true);
    $f$, t);
  end loop;
end $$;

-- 사람이 읽고 쓰는 테이블: decisions/draft_requests/published → anon 전체 권한
-- (로그인 없이 낙점/초안요청/승인).
do $$
declare t text;
begin
  foreach t in array array['decisions','draft_requests','published'] loop
    execute format($f$
      drop policy if exists %1$s_all on %1$s;
      drop policy if exists %1$s_select on %1$s;
      drop policy if exists %1$s_public_all on %1$s;
      create policy %1$s_public_all on %1$s
        for all to anon, authenticated
        using (true) with check (true);
    $f$, t);
  end loop;
end $$;
