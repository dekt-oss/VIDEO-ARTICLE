// ★ 서버 전용 Supabase 클라이언트(service_role). 절대 클라이언트 컴포넌트에서 import 하지 말 것.
//
// 왜 필요한가: 0031_lock_cost_queues.sql 이 비용·발행 큐(render_jobs, upload_requests,
//   report_render_jobs, report_upload_requests)의 anon 쓰기를 닫았다. anon 키로는 더 이상
//   INSERT 가 되지 않으므로, 정당한 경로(운영자 키 게이트를 통과한 Next 라우트)는 이 클라이언트로 쓴다.
//   읽기는 여전히 lib/supabase/server.ts(anon)로 한다 — 권한을 필요한 곳에만 좁게 쓴다.
//
// 저장소 관례 편차: CLAUDE.md 는 SUPABASE_SERVICE_KEY 를 "서버/엔진 전용"으로 규정하고 지금까지
//   web/ 에는 두지 않았다. 이 파일이 그 예외다 — 근거·트레이드오프는
//   docs/deviation-cost-surface-guard.md. NEXT_PUBLIC_ 접두사는 절대 붙이지 않는다.
import { createClient as createSupabaseClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * service_role 클라이언트. 키가 없으면 null — 호출부가 anon 폴백이나 명확한 오류를 고를 수 있게
 * 예외를 던지지 않는다(키 설정 전 배포에서 라우트가 500 으로 죽지 않게).
 */
export function createAdminClient(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !serviceKey) return null;
  return createSupabaseClient(url, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

/** 큐 쓰기용 클라이언트를 고른다. service key 가 있으면 그것, 없으면 넘겨받은 anon 클라이언트. */
export function queueWriter(fallback: SupabaseClient): SupabaseClient {
  const admin = createAdminClient();
  if (!admin) {
    console.warn(
      "[supabase/admin] SUPABASE_SERVICE_KEY 미설정 — 큐 쓰기를 anon 키로 시도합니다. " +
        "0031 마이그레이션 적용 후에는 RLS 로 거부됩니다(Vercel 환경변수에 추가하세요)."
    );
    return fallback;
  }
  return admin;
}
