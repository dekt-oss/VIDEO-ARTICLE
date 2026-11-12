// 오늘 할 일 (/drinks) — 2026-11-05 부터 주류 공장 홈(docs/deviation-drinks-multi-format.md §3-5 G10). 옛 선별 보드는 /drinks/board 에 그대로.
//   [지금 할 일 하나](rankForHome) · 타일 3개(고를 후보 / 판단 기다리는 작업 / 게시·확인 필요 — 작업 단위 기준) ·
//   이번 주 진행표(형식별 게시 완료 / 목표 DRINKS_WEEKLY_TARGETS) · 수집 건강 한 줄 · 막힘 목록. 집계 규칙은 lib/drinks/home.ts(순수).
//   조회 실패는 0 이 아니라 "모름"으로 — 타일 숫자를 지어내지 않는다.
import Link from "next/link";

import DrinksHomeView, { CollectHealth } from "@/components/drinks/home/HomeView";
import LoadProblem from "@/components/drinks/LoadProblem";
import { mondayOf, todayInSeoul } from "@/lib/date";
import { loadRunHealth } from "@/lib/drinks/collectQueries";
import { pickBudget } from "@/lib/drinks/develop";
import { homeBlockers, homeCounts, homeState, weeklyProgress } from "@/lib/drinks/home";
import { DRINKS_WEEKLY_TARGETS } from "@/lib/drinks/model";
import { ACCOUNT_STATUS_LABEL, loadPublishBoard } from "@/lib/drinks/publishQueries";
import { countOpenCandidates, loadOpenBudgets, loadTodayCandidates } from "@/lib/drinks/topicsQueries";
import { decide, homeTier } from "@/lib/drinks/work/decision";
import { loadWorkItems } from "@/lib/drinks/work/queries";
import type { Decision, WorkItem } from "@/lib/drinks/work/types";

export const dynamic = "force-dynamic";

export default async function DrinksTodayPage() {
  const today = todayInSeoul();
  const [work, health, candTotal, budgets, pub, todayCands] = await Promise.all([
    loadWorkItems("all"), loadRunHealth(), countOpenCandidates(), loadOpenBudgets(), loadPublishBoard(), loadTodayCandidates(today),
  ]);
  const [y, m, d] = today.split("-").map(Number);
  const dow = ["일", "월", "화", "수", "목", "금", "토"][new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const header = (
    <div className="dk-head dk-head-row">
      <div>
        <p className="dk-eyebrow">TODAY / {today.slice(5).replace("-", ".")} {dow}</p>
        <h1 className="dk-h1">오늘 할 일</h1>
        <p className="dk-lead">승인·검수·예약할 작업을 모았습니다. 지금 필요한 일부터 시작하세요. · <Link href="/drinks/board">옛 선별 보드</Link></p>
      </div>
      <span className="dk-badge">{today.replaceAll("-", ".")}</span>
    </div>
  );
  if (work.state !== "ok") {
    return <main className="container">{header}<LoadProblem state={work.state} error={work.state === "failed" ? work.error : undefined} /><CollectHealth health={health} /></main>;
  }
  const items: WorkItem[] = work.data;
  const decisions: Decision[] = items.map((it) => decide(it));
  const openCount = decisions.filter((d) => homeTier(d) < 7).length;   // 급 7 = 끝난 것
  const counts = homeCounts(decisions);
  const state = homeState(candTotal, items.length, openCount);
  const accountsBlocked = pub.state === "ok"
    ? pub.data.accounts.filter((a) => a.status !== "active" || !a.publish_enabled)
        .map((a) => ({ name: a.display_name, reason: a.status_reason ?? (a.publish_enabled ? ACCOUNT_STATUS_LABEL[a.status] ?? a.status : "발행 꺼짐") }))
    : null;
  const blockers = homeBlockers({
    hasBudget: budgets === null ? null : Boolean(pickBudget(budgets, Date.now())),
    accountsBlocked,
    runs: health.state === "ok" ? { active: health.data.active, total: health.data.failed + health.data.partial + health.data.aborted + health.data.empty + health.data.succeeded } : null,
    items,
  });
  const weekly = weeklyProgress(items, mondayOf(today), DRINKS_WEEKLY_TARGETS);

  return (
    <DrinksHomeView header={header} state={state} items={items} decisions={decisions} candTotal={candTotal} todayCands={todayCands}
      counts={counts} weekly={weekly} blockers={blockers} health={health} />
  );
}
