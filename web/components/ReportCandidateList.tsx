"use client";

// 리포트 팩토리 오늘의 후보(종목/테마 카드). CandidateList(논문)의 report 미러.
import { useMemo, useRef, useState } from "react";
import type {
  ReportCandidate,
  ReportDecisionStatus,
  ReportSortMode,
} from "@/lib/reportTypes";
import { REPORT_SORT_LABELS } from "@/lib/reportTypes";
import { useToast } from "@/components/Toast";
import { apiErrorText } from "@/lib/apiError";

function score(c: ReportCandidate, mode: ReportSortMode): number {
  if (mode === "interest") return c.interest_index ?? 0;
  if (mode === "story") return c.story_index ?? 0;
  return c.safety_index ?? 0;
}

type DecFilter = "all" | "undecided" | "picked" | "shortlisted" | "rejected";
const DEC_FILTERS: { key: DecFilter; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "undecided", label: "미정" },
  { key: "picked", label: "낙점" },
  { key: "shortlisted", label: "후보" },
  { key: "rejected", label: "탈락" },
];

// 결정 상태를 색·투명도가 아니라 텍스트+아이콘으로도 말한다(A11Y-04 / HOME-01 규칙 5).
const DEC_LABEL: Record<string, { text: string; cls: string }> = {
  picked: { text: "✓ 낙점", cls: "dec-picked" },
  shortlisted: { text: "◦ 후보", cls: "dec-short" },
  rejected: { text: "× 탈락", cls: "dec-rejected" },
  undecided: { text: "· 미정", cls: "dec-undecided" },
};

function DecisionLabel({ status }: { status: string | null }) {
  const m = DEC_LABEL[status ?? "undecided"] ?? DEC_LABEL.undecided;
  return <span className={`status-pill ${m.cls}`}>{m.text}</span>;
}

export default function ReportCandidateList({ initial }: { initial: ReportCandidate[] }) {
  const toast = useToast();
  const [mode, setMode] = useState<ReportSortMode>("interest");
  const [decFilter, setDecFilter] = useState<DecFilter>("all");
  const [newOnly, setNewOnly] = useState(false);
  const [items, setItems] = useState<ReportCandidate[]>(initial);
  // ★★ 배치일이 바뀌면 목록을 **갈아엎는다**(운영자 지적 2026-09-04).
  //   useState(initial) 은 **첫 마운트에서만** 초기값을 쓴다. 홈에서 날짜를 옮기면
  //   Next 가 같은 자리의 이 컴포넌트를 재사용하므로, 서버가 새 날짜의 후보를 내려줘도
  //   화면에는 **이전 날짜 목록이 그대로 남았다.**
  //   실측: 리포트 공장에서 09-02 → 09-03 → 09-04 로 옮겼는데 세 날짜가 전부
  //   09-02 의 후보(메모리반도체·삼성바이오로직스)를 보여줬다. DB 의 관심순 1위는
  //   각각 메모리반도체 / 미국-캐나다 관세 / 애플 폴더블폰으로 **전부 달랐다.**
  //   날짜 제목·칩·카운트는 서버 컴포넌트라 제대로 바뀌어서, 목록만 낡은 것을
  //   알아채기가 더 어려웠다("3일 내내 같은 후보로 보인다").
  //   ★ 호출부가 key={batchDate} 로 한 번 끊고, 여기서도 한 번 더 막는다 —
  //     둘 중 하나만 두면 다음에 누가 key 를 빼면 조용히 되돌아간다.
  const seedRef = useRef(initial);
  if (seedRef.current !== initial) {
    seedRef.current = initial;
    setItems(initial);
  }
  const [busy, setBusy] = useState<string | null>(null);

  const sorted = useMemo(
    () =>
      items
        .filter((c) =>
          decFilter === "all"
            ? true
            : decFilter === "undecided"
              ? !c.decision_status
              : c.decision_status === decFilter
        )
        .filter((c) => !newOnly || c.is_new)
        .sort((a, b) => score(b, mode) - score(a, mode)),
    [items, mode, decFilter, newOnly]
  );

  async function decide(report_id: string, status: ReportDecisionStatus) {
    setBusy(report_id);
    const res = await fetch("/api/report-decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_id, status }),
    });
    setBusy(null);
    if (res.ok) {
      setItems((prev) =>
        prev.map((c) => (c.report_id === report_id ? { ...c, decision_status: status } : c))
      );
    } else {
      toast.show(apiErrorText(null, res.status, "결정을 저장"), "err");
    }
  }

  return (
    <>
      <div className="controls">
        <div className="toggle" role="group" aria-label="정렬 모드">
          {(Object.keys(REPORT_SORT_LABELS) as ReportSortMode[]).map((m) => (
            <button key={m} data-active={mode === m} onClick={() => setMode(m)}>
              {REPORT_SORT_LABELS[m]}
            </button>
          ))}
        </div>
        <div className="toggle" role="group" aria-label="결정 분류">
          {DEC_FILTERS.map((f) => (
            <button key={f.key} data-active={decFilter === f.key} onClick={() => setDecFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
        <div className="toggle" role="group" aria-label="신규만">
          <button data-active={newOnly} onClick={() => setNewOnly((v) => !v)}>NEW만</button>
        </div>
        <span className="muted">{sorted.length}건</span>
      </div>

      {sorted.map((c) => {
        const status = c.decision_status;
        const cls = status === "picked" ? "card picked" : status === "rejected" ? "card rejected" : "card";
        return (
          <article key={c.report_id} className={cls}>
            <div className="card-status">
              <DecisionLabel status={status} />
            </div>
            <h2>
              {c.is_new && <span className="new-badge">NEW</span>}
              {c.signal_level && <span className="lvl-badge">{c.signal_level}</span>}
              {c.title_ko || c.title}
            </h2>
            <div className="muted">
              {[c.theme, c.company].filter(Boolean).join(" · ") || "테마 미상"}
              {c.broker ? ` · 출처 ${c.broker}` : ""}
            </div>
            {c.one_liner_ko && <p className="oneliner">{c.one_liner_ko}</p>}
            {c.angle && <p className="angle">앵글: {c.angle}</p>}

            {(c.target_price != null || c.opinion) && (
              <div className="broker-facts">
                {c.opinion && <span className="pill">{c.opinion}</span>}
                {c.target_price != null && (
                  <span>목표가 <b>{c.target_price.toLocaleString()}</b></span>
                )}
              </div>
            )}

            <div className="scores">
              <span>관심 <b>{c.interest_index?.toFixed(2) ?? "–"}</b></span>
              <span>스토리 <b>{c.story_index?.toFixed(2) ?? "–"}</b></span>
              <span>안전 <b>{c.safety_index?.toFixed(2) ?? "–"}</b></span>
              {c.aria_priority != null && <span className="muted">ARIA {c.aria_priority}</span>}
            </div>

            {c.is_risk && <div className="redflag">⚠️ ARIA 위험 신호로 분류됨 — 컴플라이언스 주의</div>}
            {c.risk_note && <div className="redflag">⚠️ {c.risk_note}</div>}

            <div className="actions">
              <button
                className="btn pick"
                data-active={status === "picked"}
                disabled={busy === c.report_id}
                onClick={() => decide(c.report_id, "picked")}
              >
                낙점
              </button>
              <button
                className="btn"
                data-active={status === "shortlisted"}
                disabled={busy === c.report_id}
                onClick={() => decide(c.report_id, "shortlisted")}
              >
                후보
              </button>
              <button
                className="btn btn-quiet"
                data-active={status === "rejected"}
                disabled={busy === c.report_id}
                onClick={() => decide(c.report_id, "rejected")}
              >
                탈락
              </button>
              {c.report_url && (
                <a className="btn" href={c.report_url} target="_blank" rel="noreferrer">
                  원문 ↗
                </a>
              )}
            </div>
          </article>
        );
      })}
    </>
  );
}
