"use client";

// 진행 중 잡 한 줄 (개선 지시서 ASYNC-01 §6-5 "진행 중 표현").
// 반드시 담는 것: 현재 단계 · 경과 시간 · 자동 확인 여부 · 화면을 닫아도 계속된다는 안내.
// 담지 않는 것: **예상 완료 시간** — 렌더 소요를 측정한 적이 없다. 측정 없이 표시하는 것은
// 지시서 금지사항 7 이다(먼저 시작·종료 시각을 쌓고 중앙값이 생긴 뒤에 넣는다).
import { elapsedLabel, POLL_FOREGROUND_MS } from "@/lib/useJobPolling";

export default function AsyncJobStatus({
  stageLabel,
  startedAt,
  autoRefresh,
  lastCheckedAt,
  what = "렌더",
}: {
  stageLabel: string;
  startedAt: string | null | undefined;
  autoRefresh: boolean;
  lastCheckedAt: Date | null;
  what?: string;
}) {
  const elapsed = elapsedLabel(startedAt);
  const hhmm = lastCheckedAt
    ? `${String(lastCheckedAt.getHours()).padStart(2, "0")}:${String(
        lastCheckedAt.getMinutes()
      ).padStart(2, "0")}:${String(lastCheckedAt.getSeconds()).padStart(2, "0")}`
    : null;
  return (
    <div className="job-progress" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>
        <b>{stageLabel}</b>
        {elapsed && <span className="muted"> · {elapsed}</span>}
        <span className="muted" style={{ display: "block", fontSize: 12 }}>
          {autoRefresh
            ? `${Math.round(POLL_FOREGROUND_MS / 1000)}초마다 자동 확인 · 이 화면을 닫아도 ${what}는 계속됩니다`
            : `이 화면을 닫아도 ${what}는 계속됩니다`}
          {hhmm && ` · 마지막 확인 ${hhmm}`}
        </span>
      </span>
    </div>
  );
}
