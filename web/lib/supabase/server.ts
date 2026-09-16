// 서버 컴포넌트/route handler 용 Supabase 클라이언트(쿠키 기반 세션).
// anon 키만 사용 — service_role 키는 절대 대시보드에 두지 않는다(엔진 전용).
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

type CookieToSet = { name: string; value: string; options: CookieOptions };

/**
 * ★ Next 15 (2026-09-16): `cookies()` 가 **async** 로 바뀌었다.
 *
 *   그대로 옮기면 `createClient()` 도 async 가 되고 **호출부 50여 곳**이 전부
 *   `await createClient()` 로 번진다. 대신 쿠키 어댑터 쪽을 async 로 만들었다 —
 *   @supabase/ssr 의 `getAll`/`setAll` 은 Promise 반환을 허용한다
 *   (`node_modules/@supabase/ssr/.../types.d.ts` 의 GetAllCookies/SetAllCookies).
 *   그래서 `createClient()` 는 계속 동기이고 호출부는 한 줄도 안 바뀐다.
 *
 *   달라지는 점 하나: 예전엔 요청 컨텍스트 밖에서 부르면 **생성 시점**에 터졌는데,
 *   이제는 첫 질의 시점에 터진다. 이 저장소에는 모듈 최상위에서 만드는 곳이 없다.
 */
export function createClient() {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        async getAll() {
          return (await cookies()).getAll();
        },
        async setAll(cookiesToSet: CookieToSet[]) {
          try {
            const cookieStore = await cookies();
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
