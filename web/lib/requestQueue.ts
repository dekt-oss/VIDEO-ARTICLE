// 초안 요청 큐(draft_requests·report_draft_requests)의 "정체" 판단 — engine/config.py 쌍둥이.
//
// ★ 무엇을 막는가: 워커나 Edge Function 이 중간에 죽으면 요청이 'processing' 인 채로 남는다.
//   폴러는 'queued' 만 집으므로 그 요청은 **영원히** 방치되고, 화면의 [초안 생성] 은
//   "이미 처리 중"으로 막힌다. 종전에는 운영자가 SQL 로 status 를 되돌려야 했다.
//   (실측 사고: 2026-08-28 13:07 Edge isolate 가 47초에 shutdown — supabase/migrations/0043 머리말)
//
// ★★ 되살릴 때 **새 행을 넣지 않는다.** 그 행 자체를 'queued' 로 되돌린다. 새 행을 넣으면
//   엔진 워치독이 나중에 옛 행까지 되살려 같은 초안을 두 번 만든다(유료 호출 2배).
//
// ★★★ 값이 Python 과 갈리면 tests/test_schema_parity.py 가 잡는다. 바꿀 때는 두 곳을 함께.
//   engine/config.py 의 REQUEST_STALE_MINUTES 가 정본이다.

/** 이 시간(분)을 넘겨 'processing' 인 요청은 워커가 죽은 것으로 본다. */
export const REQUEST_STALE_MINUTES = 60;

/** 되살릴 때 error 칸에 남기는 흔적. 왜 다시 큐에 들어갔는지 화면에서 보이게 한다. */
export const STALE_REVIVE_NOTE = "응답 없어 재큐됨(watchdog)";

/**
 * 'processing' 요청이 죽은 것으로 볼 만큼 오래됐는가.
 *
 * updated_at 이 비어 있으면 **정체로 본다** — 임대 이전 옛 행이거나 시각을 못 찍은 행이고,
 * 어느 쪽이든 영원히 막혀 있는 것보다 되살리는 편이 낫다(0043 의 "NULL lease = 만료" 와 같은 자세).
 */
export function isStaleProcessing(
  updatedAt: string | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!updatedAt) return true;
  const t = Date.parse(updatedAt);
  if (Number.isNaN(t)) return true;
  return now.getTime() - t > REQUEST_STALE_MINUTES * 60 * 1000;
}
