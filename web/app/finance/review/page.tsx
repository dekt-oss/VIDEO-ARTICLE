// 리포트 검수 목록 — 낙점된 리포트, 낙점일자별 그룹. 논문 review/page.tsx 미러.
import { createClient } from "@/lib/supabase/server";
import { getPickedReports } from "@/lib/reportQueries";
import { dayLabelWithDate, seoulDateOf } from "@/lib/date";
import type { PickedReport } from "@/lib/reportTypes";

export const dynamic = "force-dynamic";

function statusPill(p: PickedReport): { cls: string; label: string } {
  if (!p.has_draft) {
    if (p.request_status === "error") return { cls: "badge-trash", label: "생성 오류" };
    if (p.request_status === "processing") return { cls: "badge-draft", label: "생성 중" };
    if (p.request_status === "queued") return { cls: "badge-draft", label: "생성 대기" };
    return { cls: "badge-draft", label: "초안 없음" };
  }
  if (p.blocked) return { cls: "badge-trash", label: "🚫 컴플라이언스 차단" };
  return { cls: "badge-rendered", label: "초안 완료" };
}

export default async function FinanceReviewPage() {
  const supabase = createClient();
  const picked = await getPickedReports(supabase);

  const groups = new Map<string, PickedReport[]>();
  for (const p of picked) {
    const d = p.decided_at ? seoulDateOf(p.decided_at) : "날짜 미상";
    if (!groups.has(d)) groups.set(d, []);
    groups.get(d)!.push(p);
  }
  const dates = [...groups.keys()].sort((a, b) => (a < b ? 1 : -1));

  return (
    <main className="container">
      <div className="header">
        <h1>④ 리포트 초안 검수</h1>
        <span className="muted">{picked.length}건</span>
      </div>
      <div className="flow">낙점 → <b>초안·컴플라이언스</b> → 승인</div>

      {picked.length === 0 ? (
        <p className="empty">낙점된 리포트가 없습니다. <a href="/finance">오늘의 후보</a>에서 낙점하세요.</p>
      ) : (
        dates.map((d) => (
          <div className="section" key={d}>
            <div className="group-header">{d === "날짜 미상" ? d : dayLabelWithDate(d)}</div>
            {groups.get(d)!.map((p) => {
              const pill = statusPill(p);
              return (
                <a className="list-row" key={p.report_id} href={`/finance/review/${p.report_id}`}>
                  <span>{p.title_ko || p.title}<span className="muted"> · {[p.company, p.theme].filter(Boolean).join(" · ")}</span></span>
                  <span className={`status-pill ${pill.cls}`}>{pill.label}</span>
                </a>
              );
            })}
          </div>
        ))
      )}
    </main>
  );
}
