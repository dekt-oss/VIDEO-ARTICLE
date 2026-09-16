-- 비용·발행 큐 테이블만 anon 쓰기 차단 (UI/UX 개선 지시서 SEC-01 대체안).
--
-- 배경: 0007_public_access.sql 이 "로그인 제거(운영자 요청)"으로 전 테이블을 anon 공개로 열었다.
--   그 결정은 유지한다 — 낙점·검수·승인 등 매일 쓰는 흐름은 계속 로그인 없이 쓴다.
--   그러나 0007 이 근거로 삼은 "데이터는 비민감" 이후 두 가지가 anon 표면에 들어왔다:
--     1) render_jobs 1행 = Veo/Gemini 유료 호출(렌더 워커가 소비)
--     2) upload_requests 1행 = 유튜브 업로드. publish.yml 이 **15분 크론**이라
--        운영자가 아무 것도 누르지 않아도 자동으로 외부 발행된다.
--   즉 이 두 큐는 "데이터"가 아니라 **지출·발행 트리거**다. 여기만 닫는다.
--
-- 변경: 아래 4개 테이블에서 anon 의 for-all 정책을 select 전용으로 바꾼다.
--   대시보드는 계속 상태를 읽는다(진행률·업로드 상태 표시가 깨지지 않는다).
--   쓰기는 service_role 만 — 엔진 워커는 원래 service_role 이라 영향 없음.
--   Next.js 라우트는 web/lib/supabase/admin.ts(서버 전용 service key)로 넣는다.
--
-- 함께 적용: web/lib/apiGuard.ts 의 운영자 키 게이트(라우트 앞단). 이 마이그레이션은
--   그 게이트를 우회하는 직접 REST INSERT 경로를 닫는 쪽이다(둘이 한 쌍).
--
-- 되돌리기: 각 테이블에 for all to anon, authenticated using(true) with check(true) 정책을
--   다시 만들면 0007 상태로 복귀한다(아래 정책 이름을 drop 후 재생성).

do $$
declare t text;
begin
  foreach t in array array['render_jobs', 'upload_requests',
                           'report_render_jobs', 'report_upload_requests']
  loop
    execute format('alter table %I enable row level security', t);

    -- 기존 공개 for-all 정책 제거(0009/0015/0020/0029 에서 만든 것).
    execute format('drop policy if exists %I_public_all on %I', t, t);
    execute format('drop policy if exists %I_read_only_anon on %I', t, t);

    -- 읽기는 계속 공개 — 대시보드가 상태·진행률·유튜브 링크를 보여준다.
    execute format(
      'create policy %I_read_only_anon on %I for select to anon, authenticated using (true)',
      t, t);
  end loop;
end $$;

-- 확인용(적용 후 psql 에서):
--   select tablename, policyname, cmd, roles from pg_policies
--   where tablename in ('render_jobs','upload_requests','report_render_jobs','report_upload_requests');
--   → 각 테이블에 SELECT 정책 1개만, INSERT/UPDATE/DELETE 정책 없음.
