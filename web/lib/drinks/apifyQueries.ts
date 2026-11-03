// Apify 정밀화(0070) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 0070 이 운영 DB 에 아직 없으면 'missing' — 밈 보드 나머지는 그대로 보이고, [쓰자] 는 결정만 기록한다(옛 동작).
import { createAdminClient } from "@/lib/supabase/admin";
import { fetchAllPages } from "@/lib/drinks/paging";
import { isMissingApifyTables, type ApifyMonth, type ApifyRequestRow } from "@/lib/drinks/apify";

export interface ApifyBoard { month: ApifyMonth; requests: ApifyRequestRow[] }
export type ApifyBoardLoaded = { state: "ok"; data: ApifyBoard } | { state: "missing" } | { state: "failed"; error: string } | { state: "unconfigured" };

const num = (x: unknown): number => (typeof x === "number" ? x : Number(x ?? 0));
const numOrNull = (x: unknown): number | null => (x === null || x === undefined ? null : Number(x));

export async function loadApifyBoard(): Promise<ApifyBoardLoaded> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const state = await db.from("drink_apify_month_state").select("state").limit(1);
  if (state.error) return isMissingApifyTables(state.error.message) ? { state: "missing" } : { state: "failed", error: state.error.message };
  const raw = (state.data?.[0] as { state?: Record<string, unknown> } | undefined)?.state ?? {};
  const month: ApifyMonth = {
    month_key: String(raw.month_key ?? ""), month_cap_usd: num(raw.month_cap_usd), spent_usd: num(raw.spent_usd),
    remaining_usd: num(raw.remaining_usd), requests: num(raw.requests),
  };
  const requests = await fetchAllPages<ApifyRequestRow>((f, to) => db.from("drink_apify_board").select("*", { count: "exact" })
    .order("created_at", { ascending: false }).order("id").range(f, to), "정밀화 요청");
  if (!requests.ok) return { state: "failed", error: requests.error };
  return {
    state: "ok",
    data: {
      month,
      requests: requests.rows.map((r) => ({
        ...r, cap_usd: num(r.cap_usd), est_usd: num(r.est_usd), actual_usd: numOrNull(r.actual_usd), input_count: num(r.input_count),
        results: Array.isArray(r.results) ? r.results : [], fields_written: Array.isArray(r.fields_written) ? r.fields_written : [],
      })),
    },
  };
}
