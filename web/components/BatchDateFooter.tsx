"use client";

// 홈 **맨 아래** 배치일 바 (2026-08-20 운영자 요청).
//
// 왜 필요한가: 후보 20편을 위에서 아래로 훑고 나면 손이 화면 맨 아래에 있다. 그런데 확인·
// 다음날 버튼은 맨 위에만 있어서, 다 보고 나면 매번 위로 스크롤해 올라가야 했다.
// 그래서 목록이 끝나는 자리에 같은 동작을 다시 놓는다:
//   [← 이전 날짜] [✓ 확인하고 다음 날짜로 →] [다음 날짜 →]  그리고 그 아래 [↑ 맨 위로].
//
// 확인 처리 로직은 상단 바(BatchDateBar)와 같은 훅을 쓴다 — lib/useBatchReview.
import { dayLabelWithDate } from "@/lib/date";
import { useBatchReview } from "@/lib/useBatchReview";

export default function BatchDateFooter({
  batchDate,
  dates,
  reviewedDates,
  apiPath,
  homeHref,
}: {
  batchDate: string;
  dates: string[];
  reviewedDates: string[];
  apiPath: string;
  homeHref: string;
}) {
  const r = useBatchReview({ batchDate, dates, reviewedDates, apiPath, homeHref });

  return (
    <section className="batch-footer" aria-label="배치 날짜 (아래)">
      <div className="batch-footer-row">
        <button
          className="btn"
          onClick={() => r.go(r.olderDate)}
          disabled={!r.olderDate}
          title="더 오래된 배치"
        >
          ← 이전 날짜
        </button>

        <span className="batch-footer-date">
          {r.isReviewed ? "✓ " : ""}
          {dayLabelWithDate(batchDate)}
        </span>

        {r.isReviewed ? (
          <button className="btn" onClick={r.undo} disabled={r.busy} title="확인 완료를 되돌린다">
            ✓ 확인 완료 · 되돌리기
          </button>
        ) : (
          <button className="btn pick" onClick={r.confirmAndNext} disabled={r.busy}>
            {r.busy
              ? "저장 중…"
              : r.nextTarget && r.nextTarget !== batchDate
                ? "✓ 확인하고 다음 날짜로 →"
                : "✓ 확인 완료"}
          </button>
        )}

        <button
          className="btn"
          onClick={() => r.go(r.newerDate)}
          disabled={!r.newerDate}
          title="더 최신 배치 (확인 처리 없이 이동)"
        >
          다음 날짜 →
        </button>
      </div>

      {/* 맨 위로 — 다시 목록 위쪽 후보를 보러 갈 때. 스크롤을 손으로 올리지 않게. */}
      <div className="batch-footer-row">
        <a className="btn to-top" href="#batch-top" title="화면 맨 위로">
          ↑ 맨 위로
        </a>
      </div>
    </section>
  );
}
