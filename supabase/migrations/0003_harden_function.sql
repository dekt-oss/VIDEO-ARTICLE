-- 보안 하드닝(Supabase advisor 0028): is_allowed_user() 는 RLS 정책 내부에서만
-- 쓰이면 되므로 anon/public 의 직접 실행(RPC) 권한을 제거하고 authenticated 에만 허용.
revoke execute on function public.is_allowed_user() from public;
grant execute on function public.is_allowed_user() to authenticated;
