-- 주류 공장 0050~0055 되돌리기 (2026-10-28). 운영 DB 적용 계획 docs/계획_운영DB적용_주류0050-0055_2026-10-28.md 의 §4.
--
-- ★ 주류 표(drink_*)·주류 함수(drink_*/drinks_*)·비공개 버킷 'drinks'(비어 있을 때만)만 지운다. 논문·리포트 표는 건드리지 않는다
--   (0050~0055 는 다른 표를 바꾸지 않았고, 다른 표도 주류 표를 참조하지 않는다).
-- ★ 데이터가 쌓인 뒤 돌리면 주류 데이터가 **모두 사라진다**. 돌리기 전에 백업(대시보드 → Database → Backups)부터.
-- ★ 마이그레이션 기록(supabase_migrations.schema_migrations)의 0050~0055 줄은 따로 지운다(아래 마지막 문장).
begin;

do $$
declare r record;
begin
  for r in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relkind = 'v' and c.relname like 'drink\_%' loop
    execute format('drop view if exists public.%I cascade', r.relname);
  end loop;
  for r in select tablename from pg_tables where schemaname = 'public' and tablename like 'drink\_%' loop
    execute format('drop table if exists public.%I cascade', r.tablename);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public' and (p.proname like 'drinks\_%' or p.proname like 'drink\_%') loop
    execute format('drop function if exists %s cascade', r.sig);
  end loop;
  -- 버킷은 파일이 하나도 없을 때만 지운다(파일이 있으면 남기고 알린다 — 파일 삭제는 이 스크립트가 하지 않는다).
  if to_regclass('storage.buckets') is not null then
    if to_regclass('storage.objects') is not null
        and exists (select 1 from storage.objects where bucket_id = 'drinks') then
      raise notice 'drinks 버킷에 파일이 있어 버킷은 남겼습니다';
    else
      delete from storage.buckets where id = 'drinks';
    end if;
  end if;
end $$;

-- 마이그레이션 기록 정리(Supabase 운영 DB 에만 있는 표)
do $$
begin
  if to_regclass('supabase_migrations.schema_migrations') is not null then
    delete from supabase_migrations.schema_migrations where name like '005%drinks%' or name like 'drinks%';
  end if;
end $$;

commit;
