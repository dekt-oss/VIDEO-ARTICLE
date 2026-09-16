// 리포트 팩토리 오늘의 후보 (SSR, 결정은 클라이언트에서 /api/report-decide 호출).
// 논문 홈(app/page.tsx)의 report 미러 — /finance 접두로 화면 완전 분리.
// 배치일 바(상단)·요약 통계·✓ 마커까지 논문 홈과 동일 구조.
import { createClient } from "@/lib/supabase/server";
import {
  getReportBatchDates,
  getReportCandidates,
  getReportReviewedDates,
  getPickedReports,
  getReportRenderJobs,
  getPublishedReports,
  getReportDirectiveStatusMap,
} from "@/lib/reportQueries";
import { dayLabelWithDate } from "@/lib/date";
import ReportCandidateList from "@/components/ReportCandidateList";
import BatchDateBar from "@/components/BatchDateBar";
import BatchDateFooter from "@/components/BatchDateFooter";
import NextActionCard from "@/components/NextActionCard";
import WorkSummary from "@/components/WorkSummary";
import { workCounts } from "@/lib/work/viewModel";
import { nextStep, summarize, HOME_SKIP, FINANCE_HREFS } from "@/lib/work/nextAction";

export const dynamic = "force-dynamic";

export default async function FinanceHomePage({
  searchParams,
}: {
  searchParams: { date?: string };
}) {
  const supabase = createClient();
  const [dates, reviewed, picked, renders, published] = await Promise.all([
    getReportBatchDates(supabase),
    getReportReviewedDates(supabase),
    getPickedReports(supabase),
    getReportRenderJobs(supabase), // scope=active(휴지통 제외)
    getPublishedReports(supabase),
  ]);

  // 미확인 배치일(오래된 순). 기본 진입 시 여기 첫 항목부터 보여준다.
  const unreviewedOldestFirst = [...dates].filter((d) => !reviewed.has(d)).sort();
  const firstUnreviewed = unreviewedOldestFirst[0] ?? null;

  // ?date= 가 있으면 그 날짜, 없으면 **가장 오래된 미확인 배치**(없으면 최신).
  //
  // ★ 2026-08-20 운영자 요청으로 되돌렸다. 8/19 에 기본을 "최신"으로 바꿨던 이유는 밀린 날이
  //   쌓이면 홈이 계속 과거를 보여준다는 것이었는데, 선별은 오래된 날부터 순서대로 훑어
  //   내려가는 작업이라 최신부터 열리면 어디까지 봤는지 매번 다시 찾아야 했다. 밀린 날은
  //   상·하단 바의 [✓ 확인하고 다음 날짜로] 로 앞에서부터 지워 나가고, 통째로 넘길 때는
  //   [밀린 N일 한번에 확인] 을 쓴다. 오늘 것만 보고 싶으면 상단 [오늘로].
  const requested = searchParams.date;
  const batchDate =
    requested && dates.includes(requested)
      ? requested
      : firstUnreviewed ?? dates[0] ?? null;

  const candidates = batchDate ? await getReportCandidates(supabase, batchDate) : [];
  const isReviewed = batchDate ? reviewed.has(batchDate) : false;

  // 여러 테이블 상태 → 작업 카운트 → 다음 작업 1개(지시서 §5-3). 논문 공장과 같은 판정을 쓴다.
  const directiveStatus = await getReportDirectiveStatusMap(
    supabase,
    picked.filter((p) => p.has_draft).map((p) => p.report_id)
  );
  // ★ 확인 완료된 날의 후보는 "미결정"으로 세지 않는다(2026-08-20 운영자 요청) — 논문 홈과 동일.
  //   탈락 버튼을 일일이 누르지 않아도, 그날 후보를 다 보고 [확인]을 눌렀으면 그 날은 끝이다.
  const counts = workCounts({
    candidateDecisions: isReviewed ? [] : candidates.map((c) => c.decision_status),
    picked: picked.map((p) => ({ paperId: p.report_id, hasDraft: p.has_draft })),
    approvedScriptIds: new Set(published.map((p) => p.report_id)),
    directiveStatus,
    renders,
  });
  const step = nextStep(counts, FINANCE_HREFS, HOME_SKIP);

  return (
    <main className="container">
      <div className="header">
        <h1>📈 리포트 공장 · 오늘의 작업</h1>
        <span className="muted">
          {batchDate ? `${isReviewed ? "✓ " : ""}${dayLabelWithDate(batchDate)}` : "배치 없음"}
        </span>
      </div>
      <div className="flow">ARIA 신호 → 4축 채점 → <b>후보 선별</b> → 낙점 → (PF1) 초안·컴플라이언스</div>

      {/* 배치 날짜 · 확인 처리 — 첫 화면 맨 위에 둔다(예전에는 페이지 맨 아래 접힌 패널). */}
      {batchDate && (
        <BatchDateBar
          batchDate={batchDate}
          dates={dates}
          reviewedDates={[...reviewed]}
          apiPath="/api/report-review-date"
          homeHref="/finance"
        />
      )}

      <NextActionCard
        step={step}
        batchNote={
          unreviewedOldestFirst.length > 1 && step.action === "decide"
            ? `미확인 배치 ${unreviewedOldestFirst.length}일 — 오래된 날부터 순서대로 열립니다`
            : null
        }
      />

      <WorkSummary counts={summarize(counts)} hrefs={FINANCE_HREFS} />

      {candidates.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          아직 리포트 배치가 없습니다. 엔진을 실행하세요:{" "}
          <code>python -m engine.report_collect</code> → <code>python -m engine.report_score</code>
          <br />
          <span style={{ fontSize: 12 }}>
            (ARIA_MCP_URL 미설정 시 fixture 데이터로 동작 — 로컬 확인용)
          </span>
        </p>
      ) : (
        <ReportCandidateList key={batchDate} initial={candidates} />
      )}

      {/* 목록 끝 — 위로 올라가지 않고 여기서 확인·다음날 이동. */}
      {batchDate && candidates.length > 0 && (
        <BatchDateFooter
          batchDate={batchDate}
          dates={dates}
          reviewedDates={[...reviewed]}
          apiPath="/api/report-review-date"
          homeHref="/finance"
        />
      )}
    </main>
  );
}
