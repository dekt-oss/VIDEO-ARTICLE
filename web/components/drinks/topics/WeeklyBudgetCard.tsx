"use client";

// 이번 주 AI 초안 한도 카드(소재 고르기 맨 위, 2026-11-06 운영자 결정) — 입력 칸 없이 보여 주기만 하고, 버튼은 [한도 +$1] 하나.
//   버튼은 허용 목록의 `raise_weekly_budget`(payload {})만 부른다. 상한·주 계산·금액 검사는 전부 서버(DB)가 한다 — 여기서 막는 것은
//   "이미 주간 최대치"인 경우의 버튼 잠금뿐이고, 서버가 거절하면 그 문장을 그대로 보여 준다.
//   데이터는 page 가 lib/drinks/weeklyBudget.ts::loadWeeklyBudget() 으로 읽어 prop 으로 넘긴다(화면 쪽은 표시만).
import { useState } from "react";

import type { WeeklyBudget } from "@/lib/drinks/weeklyBudgetModel";

import { useDrinksAction } from "../useDrinksAction";

// 숫자가 아니면 "모름" — 모르는 값을 $0.00 으로 보이지 않는다.
const usd = (n: number) => (Number.isFinite(n) ? `$${n.toFixed(2)}` : "모름");

/** 만료 시각을 서울 기준 "M/D" 로. 못 읽으면 원문 앞 10자. */
function monthDay(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" }).formatToParts(new Date(t));
  const m = parts.find((p) => p.type === "month")?.value;
  const d = parts.find((p) => p.type === "day")?.value;
  return m && d ? `${m}/${d}` : iso.slice(0, 10);
}

export default function WeeklyBudgetCard({ budget, error }: { budget: WeeklyBudget | null; error?: string }) {
  const { run, busy } = useDrinksAction();
  const [serverError, setServerError] = useState<string | null>(null);

  if (!budget) {
    return (
      <section className="dk-budget dk-budget--warn" aria-label="이번 주 AI 초안 한도" role="status">
        <p className="dk-budget-main">이번 주 AI 초안 한도를 읽지 못했습니다{error ? ` — ${error}` : ""}.</p>
        <p className="dk-budget-sub">0원이 아니라 조회 실패입니다. 한도를 모르는 동안에는 AI 초안을 쓰지 않습니다.</p>
      </section>
    );
  }

  const max = Number.isFinite(budget.max_cap_usd) && budget.max_cap_usd > 0 ? budget.max_cap_usd : 10;
  const atMax = budget.cap_usd >= max;
  const empty = budget.remaining_usd <= 0;
  const lockReason = atMax ? `주간 한도는 ${usd(max).replace(".00", "")} 까지입니다` : null;

  const raise = async () => {
    setServerError(null);
    const r = await run("raise_weekly_budget", {}, "이번 주 AI 초안 한도를 $1 올렸습니다", "한도 올리기");
    if (!r.ok) setServerError(r.error ?? "한도를 올리지 못했습니다");
  };

  return (
    <section className={`dk-budget${empty ? " dk-budget--warn" : ""}`} aria-label="이번 주 AI 초안 한도">
      <div className="dk-budget-body">
        <p className="dk-budget-main">
          이번 주 AI 초안 한도 <b>{usd(budget.cap_usd)}</b> · 사용 <b>{usd(budget.week_spent_usd)}</b> · 남은 <b>{usd(budget.remaining_usd)}</b> · {monthDay(budget.expires_at)}까지
        </p>
        <p className="dk-budget-sub">누적 사용액 {usd(budget.total_spent_usd)} (지금까지 전체)</p>
        <p className="dk-budget-note">한도 안에서만 AI가 근거·대본 초안을 씁니다. 돈이 바로 나가지 않습니다.</p>
        {serverError && <p className="dk-budget-err" role="alert">{serverError}</p>}
      </div>
      <div className="dk-budget-act">
        <button type="button" className="btn" disabled={busy || atMax} aria-disabled={busy || atMax} title={lockReason ?? ""} onClick={raise}>
          {busy ? "올리는 중…" : "한도 +$1"}
        </button>
        {lockReason && <span className="dk-budget-why">{lockReason}</span>}
      </div>
    </section>
  );
}
