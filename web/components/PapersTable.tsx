"use client";

import { useMemo, useState } from "react";
import type { RawPaper } from "@/lib/types";

type SortKey = "date" | "buzz" | "title";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "date", label: "발행일" },
  { key: "buzz", label: "buzz" },
  { key: "title", label: "제목" },
];

type ScoreFilter = "all" | "scored" | "unscored";
const SCORE_FILTERS: { key: ScoreFilter; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "scored", label: "채점완료" },
  { key: "unscored", label: "미채점" },
];

export default function PapersTable({ papers }: { papers: RawPaper[] }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("date");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [lang, setLang] = useState<string>("all");

  // 데이터에 실제 존재하는 언어값만 필터 옵션으로.
  const langs = useMemo(() => {
    const s = new Set<string>();
    for (const p of papers) if (p.lang) s.add(p.lang);
    return [...s].sort();
  }, [papers]);

  const view = useMemo(() => {
    const k = q.trim().toLowerCase();
    const out = papers
      .filter((p) =>
        scoreFilter === "all" ? true : scoreFilter === "scored" ? p.scored : !p.scored
      )
      .filter((p) => lang === "all" || p.lang === lang)
      .filter(
        (p) =>
          !k ||
          p.title.toLowerCase().includes(k) ||
          (p.venue ?? "").toLowerCase().includes(k) ||
          p.external_id.toLowerCase().includes(k)
      );
    out.sort((a, b) => {
      if (sort === "buzz") return b.buzz_total - a.buzz_total;
      if (sort === "title") return a.title.localeCompare(b.title);
      return (b.published_date ?? "").localeCompare(a.published_date ?? ""); // date desc
    });
    return out;
  }, [papers, q, sort, scoreFilter, lang]);

  return (
    <>
      <div className="controls">
        <div className="toggle" role="group" aria-label="정렬">
          {SORTS.map((s) => (
            <button key={s.key} data-active={sort === s.key} onClick={() => setSort(s.key)}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="toggle" role="group" aria-label="채점 분류">
          {SCORE_FILTERS.map((f) => (
            <button key={f.key} data-active={scoreFilter === f.key} onClick={() => setScoreFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
        {langs.length > 1 && (
          <div className="toggle" role="group" aria-label="언어">
            <button data-active={lang === "all"} onClick={() => setLang("all")}>언어 전체</button>
            {langs.map((l) => (
              <button key={l} data-active={lang === l} onClick={() => setLang(l)}>{l}</button>
            ))}
          </div>
        )}
      </div>
      <input
        className="search"
        placeholder="제목·게재처·ID 검색…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <p className="muted" style={{ margin: "6px 0 12px" }}>
        {view.length} / {papers.length}편
      </p>
      <div className="table-scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>제목</th>
              <th>게재처</th>
              <th>발행일</th>
              <th>언어</th>
              <th className="num">buzz</th>
              <th>채점</th>
              <th>원문</th>
            </tr>
          </thead>
          <tbody>
            {view.map((p) => (
              <tr key={p.paper_id}>
                <td>{p.title}</td>
                <td className="muted">{p.venue ?? "—"}</td>
                <td className="muted">{p.published_date ?? "—"}</td>
                <td className="muted">{p.lang ?? "—"}</td>
                <td className="num">{p.buzz_total || ""}</td>
                <td>{p.scored ? <span className="pill on">✓</span> : <span className="pill">대기</span>}</td>
                <td>
                  {p.url ? (
                    <a href={p.url} target="_blank" rel="noreferrer">
                      ↗
                    </a>
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
