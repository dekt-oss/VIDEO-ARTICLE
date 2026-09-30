// 검수 대상 목록: 낙점(picked)된 논문 + 초안/요청 상태. 낙점 일자별로 구획한다.
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getPicked } from "@/lib/queries";
import { dayLabelWithDate, seoulDateTimeLabel } from "@/lib/date";
import { groupForReview, parseReviewSort } from "@/lib/reviewSort";
import ReviewSortToggle from "@/components/ReviewSortToggle";

export const dynamic = "force-dynamic";

const STATUS_LABEL: Record<string, string> = {
  queued: "생성 대기",
  processing: "생성 중",
  done: "초안 완료",
  error: "생성 오류",
};

export default async function ReviewListPage(props: { searchParams: Promise<{ sort?: string }> }) {
  const sort = parseReviewSort((await props.searchParams).sort);
  const supabase = createClient();
  const picked = await getPicked(supabase);
  const groups = groupForReview(picked, sort);

  return (
    <main className="container">
      <div className="header">
        <h1>④ 초안 검수</h1>
        <span className="muted">낙점된 논문 {picked.length}편</span>
      </div>
      <div className="flow">① 수집 → ② 채점 → ③ 최종선별 → <b>④ 초안</b></div>
      <ReviewSortToggle base="/review" sort={sort} />

      {picked.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          낙점된 논문이 없습니다. <Link href="/">오늘의 후보</Link>에서 낙점하세요.
        </p>
      ) : (
        groups.map((g) => (
          <div className="section" key={g.date ?? "none"}>
            <h3 className="group-header">
              {sort === "draft"
                ? (g.date ? `초안 ${dayLabelWithDate(g.date)}` : "초안 없음")
                : (g.date ? dayLabelWithDate(g.date) : "날짜 미상")}{" "}
              <span className="muted">· {g.items.length}편</span>
            </h3>
            {g.items.map((p) => (
              <div className="list-row" key={p.paper_id}>
                <a href={`/review/${p.paper_id}`}>{p.title_ko || p.title}</a>
                <span className="list-row-meta">
                {p.has_draft && p.draft_created_at && (
                  <span className="muted" title="초안을 처음 생성한 시각 (한국 시간)">
                    초안 {seoulDateTimeLabel(p.draft_created_at)}
                  </span>
                )}
                <span
                  className={`status-pill ${
                    p.has_draft
                      ? "badge-rendered"
                      : p.request_status === "error"
                        ? "badge-trash"
                        : "badge-draft"
                  }`}
                >
                  {p.has_draft ? "초안 있음" : STATUS_LABEL[p.request_status ?? ""] ?? "초안 없음"}
                </span>
                </span>
              </div>
            ))}
          </div>
        ))
      )}
    </main>
  );
}
