// 오늘의 작업 (서버 컴포넌트로 SSR, 결정은 클라이언트에서 /api/decide 호출).
//
// 개선 지시서 HOME-01: 통계 화면이 아니라 "오늘의 다음 작업" 화면. 순서를 뒤집었다 —
// 배치일 바 → 다음 작업 카드 → 요약 타일 3개 → 후보 카드.
// ★ 날짜 이동·확인 처리는 2026-08-19 부터 첫 화면 맨 위에 있다(예전에는 페이지 맨 아래
//   접이식 패널이라, 후보를 다 훑고 화면 끝까지 내려가야 눌렀다 — 운영자 요청).
import { createClient } from "@/lib/supabase/server";
import {
  getBatchDates,
  getCandidates,
  getReviewedDates,
  getPicked,
  getRenderJobs,
  getDirectiveStatusMap,
  getPublished,
} from "@/lib/queries";
import { dayLabelWithDate } from "@/lib/date";
import { workCounts } from "@/lib/work/viewModel";
import { nextStep, summarize, HOME_SKIP, PAPER_HREFS } from "@/lib/work/nextAction";
import CandidateList from "@/components/CandidateList";
import BatchDateBar from "@/components/BatchDateBar";
import BatchDateFooter from "@/components/BatchDateFooter";
import NextActionCard from "@/components/NextActionCard";
import WorkSummary from "@/components/WorkSummary";

export const dynamic = "force-dynamic";

export default async function HomePage({
  searchParams,
}: {
  searchParams: { date?: string };
}) {
  const supabase = createClient();
  const [dates, reviewed, picked, renders, published] = await Promise.all([
    getBatchDates(supabase),
    getReviewedDates(supabase),
    getPicked(supabase),
    getRenderJobs(supabase), // scope=active(휴지통 제외)
    getPublished(supabase),
  ]);

  // 미확인 배치일(오래된 순). 기본 진입 시 여기 첫 항목부터 보여준다.
  const unreviewedOldestFirst = [...dates]
    .filter((d) => !reviewed.has(d))
    .sort(); // 문자열 YYYY-MM-DD 오름차순 = 오래된 순
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

  const candidates = batchDate ? await getCandidates(supabase, batchDate) : [];
  const isReviewed = batchDate ? reviewed.has(batchDate) : false;

  // 지시서 승인 여부 — 초안이 있는 낙점 편만 조회(다음 작업 판정에 필요).
  const directiveStatus = await getDirectiveStatusMap(
    supabase,
    picked.filter((p) => p.has_draft).map((p) => p.paper_id)
  );

  // 여러 테이블 상태 → 작업 카운트 → 다음 작업 1개(지시서 §5-3 우선순위).
  // ★ 확인 완료된 날의 후보는 "미결정"으로 세지 않는다(2026-08-20 운영자 요청).
  //   탈락 버튼을 일일이 누르지 않아도, 그날 후보를 다 보고 [확인]을 눌렀으면 그 날은 끝난
  //   것이다. 예전에는 낙점하지 않은 나머지가 계속 미결정으로 남아 할 일 숫자가 줄지 않았다.
  //   후보 카드 자체는 그대로 보인다 — 카운트에서만 빠진다(decisions 행은 건드리지 않는다).
  const counts = workCounts({
    candidateDecisions: isReviewed ? [] : candidates.map((c) => c.decision_status),
    picked: picked.map((p) => ({ paperId: p.paper_id, hasDraft: p.has_draft })),
    approvedScriptIds: new Set(published.map((p) => p.paper_id)),
    directiveStatus,
    renders,
  });
  const step = nextStep(counts, PAPER_HREFS, HOME_SKIP);

  return (
    <main className="container">
      <div className="header">
        <h1>🎬 논문 공장 · 오늘의 작업</h1>
        <span className="muted">
          {batchDate
            ? `③ 최종 선별 · ${isReviewed ? "✓ " : ""}${dayLabelWithDate(batchDate)}`
            : "배치 없음"}
        </span>
      </div>
      <div className="flow">
        ① 수집 → ② 채점 → <b>③ 최종선별</b> → ④ 초안 → ⑤ 지시서 → ⑥ 렌더
      </div>

      {/* 배치 날짜 · 확인 처리 — 첫 화면 맨 위에 둔다(예전에는 페이지 맨 아래 접힌 패널). */}
      {batchDate && (
        <BatchDateBar
          batchDate={batchDate}
          dates={dates}
          reviewedDates={[...reviewed]}
          apiPath="/api/review-date"
          homeHref="/"
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

      <WorkSummary counts={summarize(counts)} hrefs={PAPER_HREFS} />

      {candidates.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          아직 배치가 없습니다. 엔진을 실행하세요: <code>python -m engine.collect</code> →{" "}
          <code>python -m engine.score</code>
        </p>
      ) : (
        <CandidateList key={batchDate} initial={candidates} />
      )}

      {/* 목록 끝 — 위로 올라가지 않고 여기서 확인·다음날 이동. */}
      {batchDate && candidates.length > 0 && (
        <BatchDateFooter
          batchDate={batchDate}
          dates={dates}
          reviewedDates={[...reviewed]}
          apiPath="/api/review-date"
          homeHref="/"
        />
      )}
    </main>
  );
}
