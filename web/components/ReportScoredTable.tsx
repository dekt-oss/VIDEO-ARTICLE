"use client";

// ② 채점 결과(report_scores, 4축) 테이블. 논문 ScoredTable 미러(경량).
import { useMemo, useState } from "react";
import type { ScoredReport } from "@/lib/reportTypes";

type SortKey = "interest" | "story" | "safety";
type Filter = "all" | "batch" | "picked" | "shortlisted" | "rejected";

function keyOf(r: ScoredReport, k: SortKey): number {
  if (k === "interest") return r.interest_index ?? 0;
  if (k === "story") return r.story_index ?? 0;
  return r.safety_index ?? 0;
}

export default function ReportScoredTable({ rows }: { rows: ScoredReport[] }) {
  const [sort, setSort] = useState<SortKey>("interest");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const view = useMemo(
    () =>
      rows
        .filter((r) =>
          filter === "all"
            ? true
            : filter === "batch"
              ? r.in_batch
              : r.decision_status === filter
        )
        .filter((r) =>
          q.trim() === "" ? true : `${r.title} ${r.company ?? ""} ${r.theme ?? ""}`.toLowerCase().includes(q.toLowerCase())
        )
        .sort((a, b) => keyOf(b, sort) - keyOf(a, sort)),
    [rows, sort, filter, q]
  );

  return (
    <>
      <div className="controls">
        <div className="toggle" role="group" aria-label="정렬">
          {(["interest", "story", "safety"] as SortKey[]).map((k) => (
            <button key={k} data-active={sort === k} onClick={() => setSort(k)}>
              {k === "interest" ? "관심" : k === "story" ? "스토리" : "안전"}
            </button>
          ))}
        </div>
        <div className="toggle" role="group" aria-label="필터">
          {(["all", "batch", "picked", "shortlisted", "rejected"] as Filter[]).map((f) => (
            <button key={f} data-active={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? "전체" : f === "batch" ? "배치" : f === "picked" ? "낙점" : f === "shortlisted" ? "후보" : "탈락"}
            </button>
          ))}
        </div>
        <input className="search" placeholder="검색" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{view.length}건</span>
      </div>
      <div className="table-scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>제목/앵글</th><th>종목/테마</th><th>시의</th><th>이해</th><th>스토리</th><th>안전</th><th>관심指</th><th>스토리指</th><th>안전指</th><th>상태</th>
            </tr>
          </thead>
          <tbody>
            {view.map((r) => (
              <tr key={r.report_id}>
                <td>{r.title_ko || r.title}{r.angle ? <div className="muted" style={{ fontSize: 12 }}>{r.angle}</div> : null}</td>
                <td>{[r.company, r.theme].filter(Boolean).join(" · ") || "–"}</td>
                <td>{r.timeliness ?? "–"}</td>
                <td>{r.explainability ?? "–"}</td>
                <td>{r.story ?? "–"}</td>
                <td>{r.safety ?? "–"}</td>
                <td>{r.interest_index?.toFixed(2) ?? "–"}</td>
                <td>{r.story_index?.toFixed(2) ?? "–"}</td>
                <td>{r.safety_index?.toFixed(2) ?? "–"}</td>
                <td>
                  {r.in_batch && <span className="pill on">배치</span>}
                  {r.decision_status && <span className="pill">{r.decision_status}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
