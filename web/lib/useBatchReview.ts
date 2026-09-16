"use client";

// 배치일 확인 처리 로직 — 화면 위/아래 두 곳에서 같은 동작을 쓴다.
//
// 왜 훅으로 뺐나(2026-08-20 운영자 요청): 후보를 다 훑고 나면 화면 **맨 아래**에 있는데,
// 확인·다음날 버튼은 맨 위에만 있었다. 그래서 아래에도 같은 버튼을 놓는다(BatchDateFooter).
// 두 곳이 각자 fetch 를 짜면 API 경로·낙관적 갱신·이동 규칙이 갈라진다 — 여기 한 곳에 둔다.
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import { dayLabelWithDate } from "@/lib/date";
import { apiErrorText } from "@/lib/apiError";

export interface BatchReviewArgs {
  /** 지금 보고 있는 배치일(YYYY-MM-DD) */
  batchDate: string;
  /** 전체 배치일 — 최신순 */
  dates: string[];
  /** 확인 완료된 배치일 */
  reviewedDates: string[];
  /** 확인 상태 저장 API (논문 /api/review-date · 리포트 /api/report-review-date) */
  apiPath: string;
  /** 이동 기준 경로 (/ 또는 /finance) */
  homeHref: string;
}

export function useBatchReview({
  batchDate,
  dates,
  reviewedDates,
  apiPath,
  homeHref,
}: BatchReviewArgs) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState<Set<string>>(() => new Set(reviewedDates));

  const isReviewed = reviewed.has(batchDate);
  const idx = dates.indexOf(batchDate);
  const newerDate = idx > 0 ? dates[idx - 1] : null; // dates 는 최신순
  const olderDate = idx >= 0 && idx < dates.length - 1 ? dates[idx + 1] : null;
  const latest = dates[0] ?? null;

  // 밀린 날(오래된 순) — 지금 보고 있는 날도 포함한다.
  const unreviewed = useMemo(
    () => dates.filter((d) => !reviewed.has(d)).sort(),
    [dates, reviewed]
  );
  // 확인 후 갈 곳: 남은 미확인 중 가장 오래된 날(없으면 최신).
  const nextTarget = unreviewed.find((d) => d !== batchDate) ?? latest;

  const go = (d: string | null) => {
    if (d) router.push(`${homeHref}?date=${d}`);
  };

  async function post(batch: string[], next: boolean) {
    const res = await fetch(apiPath, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_dates: batch, reviewed: next }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => null);
      toast.show(apiErrorText(e, res.status, "확인 상태를 저장"), "err");
      return false;
    }
    setReviewed((prev) => {
      const s = new Set(prev);
      for (const d of batch) next ? s.add(d) : s.delete(d);
      return s;
    });
    return true;
  }

  /** 이 날짜를 확인 완료로 표시하고 곧바로 다음 미확인 날짜로 이동. */
  async function confirmAndNext() {
    setBusy(true);
    const ok = await post([batchDate], true);
    setBusy(false);
    if (!ok) return;
    if (nextTarget && nextTarget !== batchDate) {
      toast.show(`${dayLabelWithDate(batchDate)} 확인 완료 · 다음 날짜로 이동합니다`, "ok");
      router.push(`${homeHref}?date=${nextTarget}`);
      // 확인한 날의 후보가 카운트에서 빠지려면 서버 렌더가 다시 돌아야 한다.
      router.refresh();
    } else {
      toast.show("모든 배치일을 확인했습니다", "ok");
      router.refresh();
    }
  }

  /** 되돌리기(잘못 눌렀을 때) — 지금 날짜만 미확인으로. */
  async function undo() {
    setBusy(true);
    const ok = await post([batchDate], false);
    setBusy(false);
    if (ok) router.refresh();
  }

  /** 여러 날짜를 한 번에 확인 완료로. */
  async function markMany(list: string[]) {
    if (list.length === 0) return false;
    setBusy(true);
    const ok = await post(list, true);
    setBusy(false);
    if (ok) {
      toast.show(`${list.length}일을 확인 완료로 표시했습니다`, "ok");
      router.refresh();
    }
    return ok;
  }

  return {
    busy,
    isReviewed,
    newerDate,
    olderDate,
    latest,
    unreviewed,
    nextTarget,
    go,
    confirmAndNext,
    undo,
    markMany,
  };
}
