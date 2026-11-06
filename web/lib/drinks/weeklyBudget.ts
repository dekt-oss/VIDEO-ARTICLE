// 주간 AI 초안 한도 불러오기(0073). 타입·해석은 weeklyBudgetModel.ts.
import { createAdminClient } from "@/lib/supabase/admin";
import { parseWeeklyBudget, type WeeklyBudgetLoad } from "@/lib/drinks/weeklyBudgetModel";

export type { WeeklyBudget, WeeklyBudgetLoad } from "@/lib/drinks/weeklyBudgetModel";

export async function loadWeeklyBudget(): Promise<WeeklyBudgetLoad> {
  try {
    const db = createAdminClient();
    if (!db) return { state: "error", message: "서버 키(SUPABASE_SERVICE_KEY)가 없어 한도를 읽지 못했습니다" };
    const r = await db.rpc("drinks_ensure_weekly_budget", { p: {} });
    if (r.error) return { state: "error", message: r.error.message };
    const b = parseWeeklyBudget(r.data);
    return b ? { state: "ok", data: b } : { state: "error", message: "한도 응답을 읽지 못했습니다" };
  } catch (e) {
    return { state: "error", message: e instanceof Error ? e.message : String(e) };
  }
}
