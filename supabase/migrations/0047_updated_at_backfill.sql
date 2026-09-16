-- 0047 — updated_at 백필 + 트리거가 명시 지정을 존중하게 (0046 후속, 2026-09-11 실측).
--
-- 0046 이 `updated_at default now()` 로 컬럼을 더하면서 **기존 행 전부가 "지금 고쳐졌다"**가 됐다.
-- 그러면 이미 만들어 둔 지시서가 전부 "옛 대본 기준"으로 보여 통합 화면이 [지시서 재생성]을
-- 들이민다(실측: 고정 대상 논문에서 바로 그렇게 떴다). 기존 행은 created_at 으로 되돌린다.
--
-- 백필하려면 트리거가 명시 지정을 덮어쓰지 않아야 한다 — 값이 바뀐 UPDATE 만 now() 로 찍는다.
create or replace function set_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.updated_at is not distinct from old.updated_at then
    new.updated_at = now();
  end if;
  return new;
end $$;

update drafts        set updated_at = created_at where created_at is not null;
update report_drafts set updated_at = created_at where created_at is not null;
