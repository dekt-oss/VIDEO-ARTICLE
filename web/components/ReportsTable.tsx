"use client";

// ① 수집 원자료(reports) 테이블. 논문 PapersTable 미러(경량).
import { useMemo, useState } from "react";
import type { RawReport } from "@/lib/reportTypes";

type ScoreFilter = "all" | "scored" | "unscored";

export default function ReportsTable({ reports }: { reports: RawReport[] }) {
  const [filter, setFilter] = useState<ScoreFilter>("all");
  const [q, setQ] = useState("");

  const rows = useMemo(
    () =>
      reports
        .filter((r) => (filter === "all" ? true : filter === "scored" ? r.scored : !r.scored))
        .filter((r) =>
          q.trim() === ""
            ? true
            : `${r.title} ${r.company ?? ""} ${r.theme ?? ""}`.toLowerCase().includes(q.toLowerCase())
        ),
    [reports, filter, q]
  );

  return (
    <>
      <div className="controls">
        <div className="toggle" role="group" aria-label="채점 필터">
          {(["all", "scored", "unscored"] as ScoreFilter[]).map((f) => (
            <button key={f} data-active={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? "전체" : f === "scored" ? "채점됨" : "미채점"}
            </button>
          ))}
        </div>
        <input className="search" placeholder="검색(종목/테마/제목)" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{rows.length}건</span>
      </div>
      <div className="table-scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>제목</th><th>테마</th><th>종목</th><th>출처</th><th>신호</th><th>ARIA</th><th>채점</th><th>원문</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.report_id}>
                <td>{r.title}{r.is_risk && <span className="lvl-badge" style={{ marginLeft: 6 }}>위험</span>}</td>
                <td>{r.theme ?? "–"}</td>
                <td>{r.company ?? "–"}</td>
                <td>{r.broker ?? "–"}</td>
                <td>{r.signal_level ?? "–"}</td>
                <td>{r.aria_priority ?? "–"}</td>
                <td>{r.scored ? "✓" : "–"}</td>
                <td>{r.report_url ? <a href={r.report_url} target="_blank" rel="noreferrer">↗</a> : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
