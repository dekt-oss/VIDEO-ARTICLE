// 주류 성과·전략 (/drinks/analytics) — 게시물 스냅샷(24h·72h·7d)과 전략 제안(명세 §9.4, D단계 2026-10-27).
// ★ 실제로 받은 지표만 보인다. 없는 지표는 0 이 아니라 '—'(받지 못함)이다. 연결 전이면 '미연결/미수집'.
// ★ 전략은 제안만 한다. 운영자가 [반영]해야 새 전략 버전이 되고, 그때 다음 편성 후보 순서가 바뀐다.
import LoadProblem from "@/components/drinks/LoadProblem";
import { StrategyDecision } from "@/components/drinks/PublishControls";
import { CATEGORY_LABEL, LANE_LABEL } from "@/lib/drinks/model";
import { kst, loadAnalyticsBoard, type SnapshotView } from "@/lib/drinks/publishQueries";

export const dynamic = "force-dynamic";

const METRICS = [["reach", "도달"], ["saved", "저장"], ["shares", "공유"], ["likes", "좋아요"], ["comments", "댓글"], ["views", "조회(릴스)"]] as const;
const BUCKETS = ["24h", "72h", "7d"] as const;
const DIM_LABEL: Record<string, string> = { category: "주종", post_type: "형식", lane: "소재 갈래", slot: "게시 시간대" };
const VALUE_LABEL: Record<string, string> = { ...CATEGORY_LABEL, ...LANE_LABEL, carousel: "카드뉴스", reel: "릴스", morning: "아침",
  afternoon: "낮", evening: "저녁", night: "밤" };
const pct = (x: number | null | undefined) => (typeof x === "number" ? `${(x * 100).toFixed(1)}%` : "—");

function cell(s: SnapshotView | undefined, k: string): string {
  if (!s) return "";
  return typeof s.values?.[k] === "number" ? String(s.values[k]) : "—";
}

export default async function DrinksAnalyticsPage() {
  const board = await loadAnalyticsBoard();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 성과·전략</h1>
        <span className="muted">게시 후 같은 경과시간(24h·72h·7d)끼리 비교</span>
      </div>
      {board.state !== "ok" ? (
        <LoadProblem state={board.state} error={board.state === "failed" ? board.error : undefined} />
      ) : (() => {
        const d = board.data;
        const open = d.proposals.find((p) => p.status === "proposed");
        return (
          <>
            {d.real_active_accounts === 0 && (
              <p className="banner-info" style={{ marginTop: 12 }}>
                미연결/미수집 — 연결 확인된 실제 인스타 계정이 없습니다.
                {d.posts.length > 0 && " 아래 숫자는 시험용 가짜 계정의 값이라 실제 성과가 아닙니다."}
              </p>
            )}
            <h2>게시물 ({d.posts.length}{d.posts_truncated ? "+, 최근 300건만" : ""})</h2>
            {d.posts.length === 0 ? <p className="muted">게시된 것이 없습니다(미수집).</p> : (
              <div className="table-scroll">
                <table className="grid">
                  <thead>
                    <tr><th>게시물</th><th>칸</th>{METRICS.map(([k, l]) => <th key={k}>{l}</th>)}<th>저장·공유율</th></tr>
                  </thead>
                  <tbody>
                    {d.posts.flatMap((p) => {
                      const byB = new Map(p.snapshots.filter((s) => s.status !== "failed").map((s) => [s.bucket, s]));
                      return BUCKETS.map((b, i) => {
                        const s = byB.get(b);
                        const v = s?.values ?? {};
                        const rate = typeof v.reach === "number" && v.reach > 0 && typeof v.saved === "number" && typeof v.shares === "number"
                          ? (v.saved + v.shares) / v.reach : null;
                        return (
                          <tr key={`${p.request_id}-${b}`}>
                            {i === 0 && (
                              <td rowSpan={3}>
                                {p.external_url ? <a href={p.external_url} target="_blank" rel="noreferrer">{p.topic_title}</a> : p.topic_title}
                                {p.is_test && <span className="pill"> 시험(가짜) </span>}
                                <div className="muted">
                                  {[p.categories.map((c) => VALUE_LABEL[c] ?? c).join("·"), VALUE_LABEL[p.post_type] ?? p.post_type,
                                    VALUE_LABEL[p.slot] ?? p.slot, kst(p.published_at)].join(" · ")}
                                </div>
                                {p.snapshots.some((s) => s.status === "failed") && <div className="muted">수집 실패 기록 있음</div>}
                              </td>
                            )}
                            <td>{b}{!s && <span className="muted"> (미수집)</span>}{s?.status === "partial" && <span className="muted"> 일부</span>}</td>
                            {METRICS.map(([k]) => <td key={k}>{cell(s, k)}</td>)}
                            <td>{s ? pct(rate) : ""}</td>
                          </tr>
                        );
                      });
                    })}
                  </tbody>
                </table>
                <p className="muted">— = 공급자가 주지 않은 지표(0 이 아님). 빈 칸 = 그 경과시간에 아직 재지 않았거나 창을 놓침(추정해 채우지 않음).</p>
              </div>
            )}

            <h2 style={{ marginTop: 20 }}>전략</h2>
            <p className="muted">지금 전략: <b>{d.active_strategy?.label ?? "없음"}</b> — 72시간 칸의 (저장 + 공유) ÷ 도달을 묶음별로 비교합니다.
              한 묶음 표본 {String(d.limits.strategy_min_group)}편·전체 {String(d.limits.strategy_min_total)}편이 안 되면 바꾸지 않습니다.</p>
            {d.active_strategy && Object.entries(d.active_strategy.weights).some(([, w]) => Object.keys(w ?? {}).length) && (
              <p className="muted">가중치: {Object.entries(d.active_strategy.weights).flatMap(([dim, w]) => Object.entries(w ?? {})
                .map(([k, v]) => `${DIM_LABEL[dim] ?? dim} ${VALUE_LABEL[k] ?? k} ${v >= 0 ? "+" : ""}${v}`)).join(" · ")}</p>
            )}
            {!open ? <p className="muted">결정할 제안이 없습니다. 제안은 <code>python -m engine.drinks_strategy</code> 가 만듭니다.</p> : (
              <div className="list-row" style={{ alignItems: "flex-start" }}>
                <span style={{ maxWidth: 720 }}>
                  <b>제안</b> <span className="pill">{open.sufficient ? "반영 가능" : "표본 부족"}</span>
                  <span className="muted"> · 표본 {open.sample_total}편 · 전체 저장·공유율 {pct(open.basis.overall)} · {kst(open.created_at)}</span>
                  <div>{open.summary_ko}</div>
                  {Object.entries(open.basis.groups ?? {}).map(([dim, g]) => (
                    <div key={dim} className="muted">
                      {DIM_LABEL[dim] ?? dim}: {Object.entries(g).map(([k, x]) => `${VALUE_LABEL[k] ?? k} ${pct(x.mean)}(${x.n}편${x.enough ? "" : ", 표본 부족"})`).join(" · ")}
                    </div>
                  ))}
                </span>
                <StrategyDecision proposalId={open.id} sufficient={open.sufficient} />
              </div>
            )}

            <h2 style={{ marginTop: 20 }}>다음 편성 후보 순서 (전략 반영, 상위 20)</h2>
            {d.rank.topics.length === 0 ? <p className="muted">선별 전 후보가 없습니다.</p> : (
              <table className="grid">
                <thead><tr><th>소재</th><th>주종</th><th>임시 점수</th><th>전략 가점</th><th>반영 점수</th></tr></thead>
                <tbody>
                  {d.rank.topics.slice(0, 20).map((t) => (
                    <tr key={t.topic_id}>
                      <td>{t.title}</td><td>{t.categories.map((c) => VALUE_LABEL[c] ?? c).join("·")}</td>
                      <td>{t.provisional_score ?? "—"}</td><td>{t.lift ? `${t.lift > 0 ? "+" : ""}${(t.lift * 100).toFixed(0)}%` : "0"}</td>
                      <td>{t.adjusted_score ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        );
      })()}
    </main>
  );
}
