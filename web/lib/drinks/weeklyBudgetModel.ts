// 주간 AI 초안 한도(0073, 2026-11-06 운영자 지시: "주간한도는 5달러로 고정 … 증액은 1달러씩 … 누적사용액 보여주게").
// 순수 모듈(타입·응답 해석) — node --test 가 별칭(@/) 없이 읽는다. 불러오기는 weeklyBudget.ts.
// 소재 고르기 화면이 서버에서 부른다. 이번 주 한도 줄이 없으면 DB 가 $5 로 만든다(돈을 쓰는 것이 아니라 상한을 정하는 것).

export type WeeklyBudget = {
  budget_id: string;
  week_start: string;      // YYYY-MM-DD (서울 기준 월요일)
  expires_at: string;
  cap_usd: number;
  base_cap_usd: number;
  max_cap_usd: number;
  week_spent_usd: number;
  week_held_usd: number;
  remaining_usd: number;
  total_spent_usd: number; // 지금까지 정산된 AI 초안 비용 전체
};

export type WeeklyBudgetLoad = { state: "ok"; data: WeeklyBudget } | { state: "error"; message: string };

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
};

/** RPC 응답을 화면 타입으로. 숫자가 아니면 null — 모르는 값을 0 으로 보이지 않는다. */
export function parseWeeklyBudget(raw: unknown): WeeklyBudget | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const out = {
    budget_id: String(r.budget_id ?? ""),
    week_start: String(r.week_start ?? ""),
    expires_at: String(r.expires_at ?? ""),
    cap_usd: num(r.cap_usd),
    base_cap_usd: num(r.base_cap_usd),
    max_cap_usd: num(r.max_cap_usd),
    week_spent_usd: num(r.week_spent_usd),
    week_held_usd: num(r.week_held_usd),
    remaining_usd: num(r.remaining_usd),
    total_spent_usd: num(r.total_spent_usd),
  };
  if (!out.budget_id || !out.expires_at) return null;
  for (const k of ["cap_usd", "base_cap_usd", "max_cap_usd", "week_spent_usd", "week_held_usd", "remaining_usd", "total_spent_usd"] as const) {
    if (Number.isNaN(out[k])) return null;
  }
  return out;
}

