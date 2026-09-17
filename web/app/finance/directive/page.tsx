// ⑤ 리포트 영상 지시서 목록: 초안이 있는(=지시서 생성 가능) 리포트. 상세에서 생성·승인한다.
// 논문 /directive 인덱스의 report 미러(단일 comic 버전).
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { selectIn } from "@/lib/supabase/chunked";
import { getPickedReports } from "@/lib/reportQueries";
import type { DirectiveStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

const STATUS_BADGE: Record<DirectiveStatus, string> = {
  draft: "badge-draft",
  approved: "badge-approved",
  rendering: "badge-approved",
  rendered: "badge-rendered",
  failed: "badge-trash",
};
const STATUS_LABEL: Record<DirectiveStatus, string> = {
  draft: "초안",
  approved: "승인",
  rendering: "렌더중",
  rendered: "렌더됨",
  failed: "실패",
};

export default async function FinanceDirectiveListPage() {
  const supabase = createClient();
  const picked = await getPickedReports(supabase);
  const ready = picked.filter((p) => p.has_draft);

  // 각 리포트의 최신 지시서 상태(created_at 내림차순 → 첫 행). 단일 comic 이라 상태 하나.
  const statusByReport = new Map<string, DirectiveStatus>();
  if (ready.length > 0) {
    const data = await selectIn<{ report_id: string; status: string }>(
      ready.map((p) => p.report_id),
      (c) => supabase
        .from("report_directives")
        .select("report_id, status, created_at")
        .in("report_id", c)
        .order("created_at", { ascending: false }),
      "report_directives.report_id");
    for (const d of data) {
      if (!statusByReport.has(d.report_id)) {
        statusByReport.set(d.report_id, d.status as DirectiveStatus);
      }
    }
  }

  return (
    <main className="container">
      <div className="header">
        <h1>⑤ 영상 지시서</h1>
        <span className="muted">초안 완료 {ready.length}편</span>
      </div>
      <div className="flow">
        ④ 초안 → <b>⑤ 지시서(생성·승인)</b> → ⑥ 렌더
      </div>

      {ready.length === 0 ? (
        <p className="empty">
          지시서를 만들 초안이 없습니다. <Link href="/finance/review">④ 초안 검수</Link>에서 대본을 먼저 생성하세요.
        </p>
      ) : (
        <div className="section">
          {ready.map((p) => {
            const st = statusByReport.get(p.report_id);
            return (
              <div className="list-row" key={p.report_id}>
                <a href={`/finance/review/${p.report_id}?step=5`}>{p.title_ko || p.title}</a>
                <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
                  {st ? (
                    <span className={`status-pill ${STATUS_BADGE[st]}`}>{STATUS_LABEL[st]}</span>
                  ) : (
                    <span className="status-pill">지시서 만들기 →</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
