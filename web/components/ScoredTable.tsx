"use client";

import { useMemo, useState } from "react";
import type { ScoredPaper } from "@/lib/types";

const DEC_LABEL: Record<string, string> = {
  picked: "낙점",
  shortlisted: "후보",
  rejected: "탈락",
};

// §6 제작 준비도 게이트 라벨/색. make=제작우선 / redesign=재설계 / backlog=후순위 / hold=보류.
const GATE_LABEL: Record<string, string> = {
  make: "제작우선",
  redesign: "재설계",
  backlog: "후순위",
  hold: "보류",
};
const GATE_CLASS: Record<string, string> = {
  make: "pick",
  redesign: "on",
  backlog: "",
  hold: "reject",
};

// 정렬 키: 라벨 + 각 행에서 값 뽑는 함수.
type SortKey = "importance" | "fun" | "surprise" | "explainability" | "relatability" | "significance" | "buzz";
const SORTS: { key: SortKey; label: string; get: (r: ScoredPaper) => number }[] = [
  { key: "importance", label: "중요指", get: (r) => r.importance_index ?? 0 },
  { key: "fun", label: "재미指", get: (r) => r.fun_index ?? 0 },
  { key: "surprise", label: "의외", get: (r) => r.surprise ?? 0 },
  { key: "explainability", label: "이해", get: (r) => r.explainability ?? 0 },
  { key: "relatability", label: "일상", get: (r) => r.relatability ?? 0 },
  { key: "significance", label: "중요", get: (r) => r.significance ?? 0 },
  { key: "buzz", label: "buzz", get: (r) => r.buzz ?? 0 },
];

type Filter = "all" | "batch" | "picked" | "shortlisted" | "rejected" | "flag";
const FILTERS: { key: Filter; label: string; test: (r: ScoredPaper) => boolean }[] = [
  { key: "all", label: "전체", test: () => true },
  { key: "batch", label: "선별", test: (r) => r.in_batch },
  { key: "picked", label: "낙점", test: (r) => r.decision_status === "picked" },
  { key: "shortlisted", label: "후보", test: (r) => r.decision_status === "shortlisted" },
  { key: "rejected", label: "탈락", test: (r) => r.decision_status === "rejected" },
  { key: "flag", label: "⚠️ 있음", test: (r) => !!r.red_flag },
];

export default function ScoredTable({ rows }: { rows: ScoredPaper[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("importance");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const view = useMemo(() => {
    const k = q.trim().toLowerCase();
    const f = FILTERS.find((x) => x.key === filter)!;
    const get = SORTS.find((s) => s.key === sortKey)!.get;
    return rows
      .filter((r) => f.test(r))
      .filter(
        (r) =>
          !k ||
          (r.title_ko ?? "").toLowerCase().includes(k) ||
          r.title.toLowerCase().includes(k) ||
          (r.venue ?? "").toLowerCase().includes(k)
      )
      .sort((a, b) => get(b) - get(a));
  }, [rows, sortKey, filter, q]);

  return (
    <>
      <div className="controls">
        <div className="toggle" role="group" aria-label="정렬 축">
          {SORTS.map((s) => (
            <button key={s.key} data-active={sortKey === s.key} onClick={() => setSortKey(s.key)}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="toggle" role="group" aria-label="분류">
          {FILTERS.map((f) => (
            <button key={f.key} data-active={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <input
        className="search"
        placeholder="제목·게재처 검색…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <p className="muted" style={{ margin: "6px 0 12px" }}>
        {view.length} / {rows.length}편
      </p>

      <div className="table-scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>제목 / 한줄요약</th>
              <th className="num">의외</th>
              <th className="num">이해</th>
              <th className="num">일상</th>
              <th className="num">중요</th>
              <th className="num">buzz</th>
              <th className="num">재미指</th>
              <th className="num">중요指</th>
              <th>상태</th>
              <th>원문</th>
            </tr>
          </thead>
          <tbody>
            {view.map((r) => (
              <tr key={r.paper_id}>
                <td>
                  <div>{r.title_ko || r.title}</div>
                  {r.title_ko && <div className="title-en">{r.title}</div>}
                  {r.one_liner_ko && <div className="muted">{r.one_liner_ko}</div>}
                  {r.red_flag && <div className="unsupported">⚠️ {r.red_flag}</div>}
                  {r.production_gate && (
                    <span
                      className={`pill ${GATE_CLASS[r.production_gate] ?? ""}`}
                      title={`제작 준비도 ${r.production_total ?? "?"}/${r.production_max} (§6)`}
                    >
                      {GATE_LABEL[r.production_gate] ?? r.production_gate} {r.production_total ?? "?"}/{r.production_max}
                    </span>
                  )}
                </td>
                <td className="num">{r.surprise ?? "—"}</td>
                <td className="num">{r.explainability ?? "—"}</td>
                <td className="num">{r.relatability ?? "—"}</td>
                <td className="num">{r.significance ?? "—"}</td>
                <td className="num">{r.buzz != null ? Number(r.buzz).toFixed(1) : "—"}</td>
                <td className="num">{r.fun_index != null ? Number(r.fun_index).toFixed(2) : "—"}</td>
                <td className="num">{r.importance_index != null ? Number(r.importance_index).toFixed(2) : "—"}</td>
                <td>
                  {r.in_batch && <span className="pill on">선별</span>}{" "}
                  {r.decision_status && (
                    <span className={`pill ${r.decision_status === "rejected" ? "reject" : "pick"}`}>
                      {DEC_LABEL[r.decision_status]}
                    </span>
                  )}
                </td>
                <td>
                  {r.url ? (
                    <a href={r.url} target="_blank" rel="noreferrer">↗</a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
