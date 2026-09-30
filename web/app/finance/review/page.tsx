// 작업함(리포트) — 논문 작업함(app/review/page.tsx)의 미러(2026-09-30 운영자 결정 2-1).
// 편마다 "지금 단계" 하나, 칩(?stage=)으로 거르기, 정렬(?sort=). 옛 ⑤ 목록은 [지시서 검수]로 넘긴다.
import { createClient } from "@/lib/supabase/server";
import { getPickedReports, getReportDirectiveStatusMap, getReportRenderJobs } from "@/lib/reportQueries";
import { getDirectiveEngineMap } from "@/lib/queries";
import { parseReviewSort } from "@/lib/reviewSort";
import { parseChip } from "@/lib/work/inbox";
import { buildInboxRows, groupJobs } from "@/lib/work/inboxRows";
import { REPORT_VERSION_KEYS } from "@/lib/versions";
import InboxList from "@/components/InboxList";

export const dynamic = "force-dynamic";

export default async function FinanceInboxPage(props: { searchParams: Promise<{ sort?: string; stage?: string }> }) {
  const sp = await props.searchParams;
  const sort = parseReviewSort(sp.sort);
  const chip = parseChip(sp.stage);
  const supabase = createClient();
  const picked = await getPickedReports(supabase);
  const ids = picked.map((p) => p.report_id);
  const [statusMap, engineMap, renders] = await Promise.all([
    getReportDirectiveStatusMap(supabase, ids),
    getDirectiveEngineMap(supabase, "report_directives", "report_id", ids),
    getReportRenderJobs(supabase),
  ]);
  const rows = buildInboxRows(
    picked.map((p) => ({
      id: p.report_id,
      title: p.title_ko || p.title,
      // 컴플라이언스 차단은 단계가 아니라 사실이라 제목 옆에 적는다(종전 목록과 같은 정보).
      sub: [p.company, p.theme].filter(Boolean).join(" · ") + (p.blocked ? " · 🚫 컴플라이언스 차단" : ""),
      href: `/finance/review/${p.report_id}`,
      hasDraft: p.has_draft,
      requestStatus: p.request_status,
      decidedAt: p.decided_at,
      draftCreatedAt: p.draft_created_at,
    })),
    REPORT_VERSION_KEYS, statusMap, engineMap, groupJobs(renders, (j) => j.report_id),
  );

  return (
    <main className="container">
      <div className="header">
        <h1>작업함</h1>
        <span className="muted">낙점된 리포트 {picked.length}건</span>
      </div>
      <div className="flow">낙점 → <b>초안 · 지시서 · 렌더</b> → 업로드</div>
      {picked.length === 0 ? (
        <p className="empty">낙점된 리포트가 없습니다. <a href="/finance">선별</a>에서 낙점하세요.</p>
      ) : (
        <InboxList base="/finance/review" rows={rows} chip={chip} sort={sort} unit="건" />
      )}
    </main>
  );
}
