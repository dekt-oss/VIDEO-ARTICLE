-- 주류 함수 검색 경로 고정 (2026-10-28). 0050~0055 운영 적용 직후 Supabase 보안 점검이 주류 함수 154개 전부에
-- function_search_path_mutable(WARN) 를 냈다. 논문·리포트 함수는 harden_function 마이그레이션으로 이미 고정돼 있다.
--
-- 위험 정도: 낮음 — 주류 함수는 공개 역할(anon·authenticated)이 실행할 수 없다(실행 권한 0건, 운영에서 확인).
-- 그래도 경고를 남기지 않고, 앞으로 주류 함수를 만들 때 같은 처리를 잊지 않게 한 곳에서 고정한다.
--
-- search_path = public, pg_temp — 주류 함수가 부르는 것은 public 의 표·함수와 pg_catalog(항상 맨 앞에 암묵 포함)뿐이고,
-- storage 표는 'storage.buckets' 처럼 스키마를 적어 부른다. pg_temp 를 끝에 둬 임시 객체가 이름을 가로채지 못하게 한다.
-- 되돌리기: 같은 반복문으로 `reset search_path`.
do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and (p.proname like 'drinks\_%' or p.proname like 'drink\_%')
  loop
    execute format('alter function %s set search_path = public, pg_temp', f.sig);
  end loop;
end $$;
