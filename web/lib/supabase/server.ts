// 서버 컴포넌트/route handler 용 Supabase 클라이언트(쿠키 기반 세션).
// anon 키만 사용 — service_role 키는 절대 대시보드에 두지 않는다(엔진 전용).
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

type CookieToSet = { name: string; value: string; options: CookieOptions };

export function createClient() {
  const cookieStore = cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: CookieToSet[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // 서버 컴포넌트에서 set 호출 시 무시(미들웨어가 세션 갱신 담당).
          }
        },
      },
    }
  );
}
