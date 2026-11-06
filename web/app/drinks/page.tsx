// 오늘 할 일 (/drinks) — 2026-11-05 부터 주류 공장 홈(docs/deviation-drinks-multi-format.md §3-5 G10). 옛 선별 보드는 /drinks/board 에 그대로.
//   [지금 할 일 하나](rankForHome) · 타일 3개(고를 후보 / 판단 기다리는 작업 / 게시·확인 필요 — 작업 단위 기준) ·
//   이번 주 진행표(형식별 게시 완료 / 목표 DRINKS_WEEKLY_TARGETS) · 수집 건강 한 줄 · 막힘 목록. 집계 규칙은 lib/drinks/home.ts(순수).
//   조회 실패는 0 이 아니라 "모름"으로 — 타일 숫자를 지어내지 않는다.
import Link from "next/link";

import NextActionCard from "@/components/drinks/home/NextActionCard";
import LoadProblem from "@/components/drinks/LoadProblem";
import { mondayOf, todayInSeoul } from "@/lib/date";
import { loadRunHealth } from "@/lib/drinks/collectQueries";
import { pickBudget } from "@/lib/drinks/develop";
import { homeBlockers, homeCounts, homeState, weeklyProgress } from "@/lib/drinks/home";
import { DRINKS_WEEKLY_TARGETS } from "@/lib/drinks/model";
import { ACCOUNT_STATUS_LABEL, loadPublishBoard } from "@/lib/drinks/publishQueries";
import { TOPICS_PAGE_SIZE, countOpenCandidates, loadOpenBudgets } from "@/lib/drinks/topicsQueries";
import { decide, homeTier } from "@/lib/drinks/work/decision";
import { loadWorkItems } from "@/lib/drinks/work/queries";
import { FORMAT_LABEL, type Decision, type WorkItem } from "@/lib/drinks/work/types";

export const dynamic = "force-dynamic";

export default async function DrinksTodayPage() {
  const [work, health, candTotal, budgets, pub] = await Promise.all([
    loadWorkItems("all"), loadRunHealth(), countOpenCandidates(), loadOpenBudgets(), loadPublishBoard(),
  ]);
  const today = todayInSeoul();
  const [y, m, d] = today.split("-").map(Number);
  const dow = ["일", "월", "화", "수", "목", "금", "토"][new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const header = (
    <div className="header">
      <div>
        <p className="muted" style={{ margin: 0, fontSize: 12, letterSpacing: "0.06em" }}>TODAY / {today.slice(5).replace("-", ".")} {dow}</p>
        <h1 style={{ margin: "2px 0" }}>오늘 할 일</h1>
        <span className="muted">승인·검수·예약할 작업을 모았습니다. 지금 필요한 일부터 시작하세요. · <Link href="/drinks/board">옛 선별 보드</Link></span>
      </div>
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
    <main className="container">
      {header}
      {state === "no_candidates_no_work" && (
        <section className="next-action done">
          <div className="next-action-body">
            <div className="next-action-kicker">시작</div>
            <div className="next-action-headline">후보도 소재도 아직 없습니다.</div>
            <p className="muted" style={{ margin: "4px 0 0" }}>발견 수집이 돌면 후보가 쌓이고, 질문을 직접 등록할 수도 있습니다.</p>
          </div>
          <div className="next-action-cta"><Link className="btn pick" href="/drinks/topics">소재 고르기 →</Link></div>
        </section>
      )}
      {state === "no_work" && (
        <section className="next-action done">
          <div className="next-action-body">
            <div className="next-action-kicker">시작</div>
            <div className="next-action-headline">고른 소재가 없습니다 — 후보 {candTotal ?? "?"}건이 기다립니다.</div>
            <p className="muted" style={{ margin: "4px 0 0" }}>[소재 고르기]에서 [이걸로 ▾]를 누르면 첫 결정이 여기에 올라옵니다.</p>
          </div>
          <div className="next-action-cta"><Link className="btn pick" href="/drinks/topics">소재 고르기 →</Link></div>
        </section>
      )}
      {(state === "work" || state === "all_done") && <NextActionCard items={items} decisions={decisions} />}

      <div className="summary-strip">
        <Link className={`summary-tile${candTotal ? " has-work" : ""}`} href="/drinks/topics">
          <div className="n">{candTotal ?? "모름"}</div>
          <div className="k">고를 후보{candTotal !== null && ` · 표시 ${Math.min(candTotal, TOPICS_PAGE_SIZE)} / 전체 ${candTotal}`}{candTotal === null && " · 조회 실패"}</div>
        </Link>
        <Link className={`summary-tile${counts.approve ? " has-work" : ""}`} href="/drinks/work?filter=approve">
          <div className="n">{counts.approve}</div>
          <div className="k">판단 기다리는 작업(작업 단위)</div>
        </Link>
        <Link className={`summary-tile${counts.publish ? " has-work" : ""}`} href="/drinks/work?filter=publish">
          <div className="n">{counts.publish}</div>
          <div className="k">게시·확인 필요(작업 단위)</div>
        </Link>
      </div>

      <section className="section">
        <h3>이번 주, 이만큼 만들었어요 <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>— {mondayOf(today)} 주 · 게시 완료 기준(앱에서 직접 올린 밈 포함)</span></h3>
        {weekly.map((w) => {
          const goal = w.target.min === w.target.max ? `${w.target.max}` : `${w.target.min}~${w.target.max}`;
          const pct = Math.min(100, Math.round((w.done / w.target.max) * 100));
          return (
            <div key={w.format} className="list-row">
              <span><b>{FORMAT_LABEL[w.format]}</b> <span className="muted">· 진행 중 {w.inProgress}</span></span>
              <span className="list-row-meta" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span aria-hidden style={{ width: 160, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
                  <span style={{ display: "block", width: `${pct}%`, height: "100%", background: "var(--accent)" }} />
                </span>
                <b>{w.done} / {goal}</b>
              </span>
            </div>
          );
        })}
        <p className="muted" style={{ fontSize: 12 }}>주간 목표는 운영 가설입니다(설명형은 영상 구매 결재에 묶여 1~2편). <Link href="/drinks/topics">다음 소재 고르기 →</Link></p>
      </section>

      <CollectHealth health={health} />
      <section className="section">
        <h3>막힘 {blockers.length > 0 ? `(${blockers.length})` : ""}</h3>
        {blockers.length === 0 ? <p className="muted">지금 막힌 것이 없습니다.</p> : blockers.map((b) => (
          <p key={b.code} className={b.code.endsWith("unknown") ? "banner-warn" : "banner-block"} role="status" style={{ margin: "6px 0" }}>
            {b.text}{b.href && <> — <Link href={b.href}>열기</Link></>}
          </p>
        ))}
      </section>
    </main>
  );
}

type Health = Awaited<ReturnType<typeof loadRunHealth>>;

/** 수집 상태 한 줄(옛 보드와 같은 규칙). 조회 실패는 "0건"이 아니라 실패로. */
function CollectHealth({ health }: { health: Health }) {
  if (health.state !== "ok") {
    return <p className="banner-warn" style={{ marginTop: 12 }}>수집 상태를 읽지 못했습니다{health.state === "failed" ? ` — ${health.error}` : ""} (0건이 아니라 조회 실패).</p>;
  }
  const h = health.data;
  if (h.active === 0) {
    return <p className="banner-info" style={{ marginTop: 12 }}><b>활성 수집원 없음.</b> 소재는 직접 등록한 것만 들어옵니다. <Link href="/drinks/sources">수집원</Link>에서 검증·활성화하세요.</p>;
  }
  const bad = h.failed + h.partial + h.aborted + h.stuck;
  return (
    <p className={bad > 0 ? "banner-warn" : "banner-info"} style={{ marginTop: 12 }}>
      수집: 활성 수집원 <b>{h.active}</b> · 최근 24시간 성공 {h.succeeded} · 정상 0건 {h.empty} · 부분 {h.partial} · 실패 {h.failed} · 중단 {h.aborted}
      {h.stuck > 0 && <> · <b>응답 끊긴 실행 {h.stuck}</b></>} — <Link href={bad > 0 ? "/drinks/runs?status=failed" : "/drinks/runs"}>실행 기록</Link>
    </p>
  );
}
