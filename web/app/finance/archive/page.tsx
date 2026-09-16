// 리포트 아카이브 — 생성된 초안 + 발행 이력. 논문 archive 미러(렌더 섹션 제외).
import { createClient } from "@/lib/supabase/server";
import { getReportDraftList, getPublishedReports } from "@/lib/reportQueries";
import { dayLabelWithDate, seoulDateOf } from "@/lib/date";
import type { ReportDraftListItem } from "@/lib/reportTypes";

export const dynamic = "force-dynamic";

export default async function FinanceArchivePage() {
  const supabase = createClient();
  const [drafts, published] = await Promise.all([
    getReportDraftList(supabase),
    getPublishedReports(supabase),
  ]);

  const groups = new Map<string, ReportDraftListItem[]>();
  for (const d of drafts) {
    const day = d.created_at ? seoulDateOf(d.created_at) : "날짜 미상";
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day)!.push(d);
  }
  const days = [...groups.keys()].sort((a, b) => (a < b ? 1 : -1));

  return (
    <main className="container">
      <div className="header"><h1>리포트 아카이브</h1></div>

      <div className="section">
        <h3>생성된 초안 ({drafts.length})</h3>
        {drafts.length === 0 ? (
          <p className="muted">초안이 없습니다.</p>
        ) : (
          days.map((day) => (
            <div key={day}>
              <div className="group-header">{day === "날짜 미상" ? day : dayLabelWithDate(day)}</div>
              {groups.get(day)!.map((d) => (
                <a className="list-row" key={d.report_id} href={`/finance/review/${d.report_id}`}>
                  <span>{d.title_ko || d.title}</span>
                  <span>
                    {d.blocked && <span className="status-pill badge-trash">🚫 차단</span>}
                    <span className={`status-pill ${d.published ? "badge-rendered" : "badge-draft"}`}>
                      {d.published ? "발행됨" : "초안 완료"}
                    </span>
                  </span>
                </a>
              ))}
            </div>
          ))
        )}
      </div>

      <div className="section">
        <h3>발행 이력 ({published.length})</h3>
        {published.length === 0 ? (
          <p className="muted">발행 이력이 없습니다.</p>
        ) : (
          published.map((p) => (
            <div className="list-row" key={p.report_id}>
              <span>{p.title}</span>
              <span className="muted">{seoulDateOf(p.published_at)}</span>
            </div>
          ))
        )}
      </div>
    </main>
  );
}
