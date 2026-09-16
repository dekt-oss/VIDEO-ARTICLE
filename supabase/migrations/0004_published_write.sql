-- 버그픽스: published 는 대시보드 '승인' 시 인증 사용자가 직접 insert 한다.
-- 0002 에서 read-only(SELECT) 정책만 있어 승인이 RLS 에 막혔다 → 쓰기 정책으로 교체.
drop policy if exists published_select on published;
drop policy if exists published_all on published;
create policy published_all on published
  for all to authenticated
  using (public.is_allowed_user())
  with check (public.is_allowed_user());
