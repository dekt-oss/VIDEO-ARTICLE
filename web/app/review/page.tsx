// 작업함(논문) — ④ 초안 검수 · ⑤ 영상 지시서를 합친 한 목록(2026-09-30 운영자 결정 2-1).
// 편마다 "지금 단계" 하나를 보이고 칩(?stage=)으로 거른다. 기본은 [할 것]. 정렬(?sort=)은 낙점일순·초안 생성순.
// 옛 ⑤ 목록(/directive)은 이 화면의 [지시서 검수]로 넘긴다.
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getPicked, getDirectiveStatusMap, getDirectiveEngineMap, getRenderJobs } from "@/lib/queries";
import { parseReviewSort } from "@/lib/reviewSort";
import { parseChip } from "@/lib/work/inbox";
import { buildInboxRows, groupJobs } from "@/lib/work/inboxRows";
import { VERSION_KEYS } from "@/lib/versions";
import InboxList from "@/components/InboxList";

export const dynamic = "force-dynamic";

export default async function InboxPage(props: { searchParams: Promise<{ sort?: string; stage?: string }> }) {
  const sp = await props.searchParams;
  const sort = parseReviewSort(sp.sort);
  const chip = parseChip(sp.stage);
  const supabase = createClient();
  const picked = await getPicked(supabase);
  const ids = picked.map((p) => p.paper_id);
  const [statusMap, engineMap, renders] = await Promise.all([
    getDirectiveStatusMap(supabase, ids),
    getDirectiveEngineMap(supabase, "directives", "paper_id", ids),
    getRenderJobs(supabase),
  ]);
  const rows = buildInboxRows(
    picked.map((p) => ({
      id: p.paper_id,
      title: p.title_ko || p.title,
      href: `/review/${p.paper_id}`,
      hasDraft: p.has_draft,
      requestStatus: p.request_status,
      decidedAt: p.decided_at,
      draftCreatedAt: p.draft_created_at,
    })),
    VERSION_KEYS, statusMap, engineMap, groupJobs(renders, (j) => j.paper_id),
  );

  return (
    <main className="container">
      <div className="header">
        <h1>작업함</h1>
        <span className="muted">낙점된 논문 {picked.length}편</span>
      </div>
      <div className="flow">낙점 → <b>초안 · 지시서 · 렌더</b> → 업로드</div>
      {picked.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          낙점된 논문이 없습니다. <Link href="/">선별</Link>에서 낙점하세요.
        </p>
      ) : (
        <InboxList base="/review" rows={rows} chip={chip} sort={sort} unit="편" />
      )}
    </main>
  );
}
