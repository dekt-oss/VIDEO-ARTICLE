// 주류 작업함 (/drinks/review) — 소재 단위, "다음 행동" 순(명세 §9.2).
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import { CATEGORY_LABEL, TOPIC_STATUS_LABEL, deriveTopic } from "@/lib/drinks/model";
import { loadBoard } from "@/lib/drinks/queries";

export const dynamic = "force-dynamic";

const ACTIVE = new Set(["inbox", "triaged", "researching", "ready", "selected"]);

export default async function DrinksReviewListPage() {
  const board = await loadBoard();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 작업함</h1>
        <span className="muted">지금 할 수 있는 일부터</span>
      </div>
      {board.state !== "ok" ? (
        <LoadProblem state={board.state} error={board.state === "failed" ? board.error : undefined} />
      ) : (
        (() => {
          const rows = board.data.topics
            .filter((t) => ACTIVE.has(t.status))
            .map((t) => ({ t, d: deriveTopic(t, board.data.reviews, board.data.deliverables, board.data.plans) }))
            .sort((a, b) => a.d.rank - b.d.rank || b.t.updated_at.localeCompare(a.t.updated_at));
          if (rows.length === 0) return <p className="muted">진행 중인 소재가 없습니다(정상 0건). <Link href="/drinks">선별</Link>에서 등록하세요.</p>;
          return rows.map(({ t, d }) => (
            <div key={t.id} className="list-row">
              <span>
                <Link href={`/drinks/review/${t.id}?tab=${d.action.tab}`}>{t.title}</Link>{" "}
                <span className="muted">
                  {t.categories.map((c) => CATEGORY_LABEL[c]).join("·")} · {TOPIC_STATUS_LABEL[t.status]}
                </span>
              </span>
              <span className="list-row-meta">
                <Link className={d.action.unavailable ? "btn" : "btn pick"} href={`/drinks/review/${t.id}?tab=${d.action.tab}`}>
                  {d.action.label}{d.action.unavailable ? " (미연결)" : ""}
                </Link>
              </span>
            </div>
          ));
        })()
      )}
    </main>
  );
}
