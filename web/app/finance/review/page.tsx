// 리포트 검수 목록 — 낙점된 리포트, 낙점일자별 그룹. 논문 review/page.tsx 미러.
import { createClient } from "@/lib/supabase/server";
import { getPickedReports } from "@/lib/reportQueries";
import { dayLabelWithDate, seoulDateTimeLabel } from "@/lib/date";
import { groupForReview, parseReviewSort } from "@/lib/reviewSort";
import ReviewSortToggle from "@/components/ReviewSortToggle";
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

export default async function FinanceReviewPage(props: { searchParams: Promise<{ sort?: string }> }) {
  const sort = parseReviewSort((await props.searchParams).sort);
  const supabase = createClient();
  const picked = await getPickedReports(supabase);
  const groups = groupForReview(picked, sort);

  return (
    <main className="container">
      <div className="header">
        <h1>④ 리포트 초안 검수</h1>
        <span className="muted">{picked.length}건</span>
      </div>
      <div className="flow">낙점 → <b>초안·컴플라이언스</b> → 승인</div>
      <ReviewSortToggle base="/finance/review" sort={sort} />

      {picked.length === 0 ? (
        <p className="empty">낙점된 리포트가 없습니다. <a href="/finance">오늘의 후보</a>에서 낙점하세요.</p>
      ) : (
        groups.map((g) => (
          <div className="section" key={g.date ?? "none"}>
            <div className="group-header">
              {sort === "draft"
                ? (g.date ? `초안 ${dayLabelWithDate(g.date)}` : "초안 없음")
                : (g.date ? dayLabelWithDate(g.date) : "날짜 미상")}
              <span className="muted"> · {g.items.length}건</span>
            </div>
            {g.items.map((p) => {
              const pill = statusPill(p);
              return (
                <a className="list-row" key={p.report_id} href={`/finance/review/${p.report_id}`}>
                  <span>{p.title_ko || p.title}<span className="muted"> · {[p.company, p.theme].filter(Boolean).join(" · ")}</span></span>
                  <span className="list-row-meta">
                    {p.has_draft && p.draft_created_at && (
                      <span className="muted" title="초안을 처음 생성한 시각 (한국 시간)">
                        초안 {seoulDateTimeLabel(p.draft_created_at)}
                      </span>
                    )}
                    <span className={`status-pill ${pill.cls}`}>{pill.label}</span>
                  </span>
                </a>
              );
            })}
          </div>
        ))
      )}
    </main>
  );
}
