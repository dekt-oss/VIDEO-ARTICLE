"use client";

// 저장 상태 한 줄 (개선 지시서 SAFE-01 §8-3). 편집 화면 상단·액션바에 둔다.
// 기존 .dirty-dot(노란 점)만으로는 "저장된 상태인지"를 알 수 없었다 — 점이 없는 것과
// 저장에 실패한 것이 화면에서 같아 보였다. 상태를 텍스트+아이콘+색 3종으로 말한다(A11Y-04).
export type SaveState = "saved" | "saving" | "dirty" | "error";

const META: Record<SaveState, { icon: string; text: string; cls: string }> = {
  saved: { icon: "✓", text: "저장됨", cls: "grounded-ok" },
  saving: { icon: "⏳", text: "저장 중…", cls: "muted" },
  dirty: { icon: "●", text: "저장하지 않은 변경", cls: "save-dirty" },
  error: { icon: "⚠", text: "저장 실패", cls: "unsupported" },
};

export default function SaveStatus({
  state,
  savedAt,
}: {
  state: SaveState;
  /** 마지막 저장 시각(ISO 또는 Date). 있으면 HH:MM 으로 덧붙인다. */
  savedAt?: string | Date | null;
}) {
  const m = META[state];
  const stamp = savedAt ? new Date(savedAt) : null;
  const hhmm = stamp
    ? `${String(stamp.getHours()).padStart(2, "0")}:${String(stamp.getMinutes()).padStart(2, "0")}`
    : null;
  return (
    <span className={`save-status ${m.cls}`} aria-live="polite">
      <span aria-hidden="true">{m.icon}</span> {m.text}
      {hhmm && state !== "dirty" && <span className="muted"> · 마지막 저장 {hhmm}</span>}
    </span>
  );
}
