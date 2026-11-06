// 게시 가능 시각(리뷰 R6, 2026-11-04). 게시 워커 크론이 KST 07:00~23:30 에만 돌므로 그 밖의 예약은 반드시 늦어 멈춘다.
// 정본은 engine/config.py DRINKS_PUBLISH_WINDOW · 0071 drinks_publish_window() 이고 tests/test_drinks_review_fixes.py 가 셋을 대조한다.
// ★ 화면 경고는 편의일 뿐이다 — 막는 것은 DB 다(승인 요청·예약 때 outside_publish_window).
export const PUBLISH_WINDOW = { timezone: "Asia/Seoul", start: "07:00", end: "23:30" } as const;

/** datetime-local 값("2026-11-05T03:00", 한국 시각) → 창 안이면 null, 밖이면 안내 문장. 비어 있으면 null(시각은 승인 요청 때 다시 묻는다). */
export function publishWindowProblem(localKst: string): string | null {
  const m = /T(\d{2}):(\d{2})/.exec(localKst);
  if (!m) return null;
  const t = `${m[1]}:${m[2]}`;
  if (t >= PUBLISH_WINDOW.start && t <= PUBLISH_WINDOW.end) return null;
  return `게시 시각은 한국 ${PUBLISH_WINDOW.start}~${PUBLISH_WINDOW.end} 사이만 됩니다 — 그 밖에는 게시 워커가 돌지 않아 예약이 멈춥니다`;
}
