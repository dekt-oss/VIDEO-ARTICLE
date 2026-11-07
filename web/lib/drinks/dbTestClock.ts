// DB 시험(PGlite)용 시계 — 실제 시각과 무관하게 낮(KST)에서 출발해 실제 경과만큼만 흐른다.
//
// 왜: 0071(R6)이 예약 시각을 게시 크론 창(KST 07:00~23:30) 안으로 막고, 워커 claim 은
// publish_at ≤ now() 이면서 2시간(late_grace_sec) 안이어야 받는다. 실제 시계로는 KST 01:30~07:00 에
// 두 조건을 함께 만족하는 publish_at 이 없어서, 밤에 돌리면 게시 시험 5개가 깨졌다(2026-11-06 15:10 UTC 관측).
// publish_at 만 "다음 날 12:00" 으로 옮기면 창은 통과해도 claim 이 미래 예약이라 받지 않는다 —
// 그래서 시각이 아니라 시계를 고정한다. DB 규칙은 그대로다.
//
// 어떻게: PGlite(WASM Postgres)의 now()·current_date 는 JS Date.now() 를 읽는다(2026-11-07 실측).
// Date.now 만 바꾸면 DB 시계도 같이 움직인다. ★ 인자 없는 `new Date()` 는 바뀌지 않는다 —
// 시험 코드의 "지금" 은 반드시 Date.now() 로 구한다. assertDbFollowsTestClock 이 DB 가 따라오는지 확인한다.
import assert from "node:assert/strict";
import type { PGlite } from "@electric-sql/pglite";

/** 2026-11-04(수) 12:00 KST. 시험에 박힌 editorial_week "2026-11-02" 와 같은 주이고, 창 끝(23:30)까지 11시간 넘게 남는다. */
export const TEST_CLOCK_START = "2026-11-04T03:00:00.000Z";

const PINNED = Symbol.for("drinks.dbTestClock");

/** PGlite 를 만들기 전에 부른다. 두 번 불러도 한 번만 적용된다. */
export function pinTestClock(start: string = TEST_CLOCK_START): void {
  const g = globalThis as Record<symbol, unknown>;
  if (g[PINNED]) return;
  const real = Date.now.bind(Date);
  const offset = Date.parse(start) - real();
  Date.now = () => real() + offset;
  g[PINNED] = start;
}

/** DB 시계가 고정 시계를 따라오고(오차 5초 미만) 그 시각이 게시 창 안인지 — 아니면 시험 전제가 무너진 것이다. */
export async function assertDbFollowsTestClock(db: PGlite): Promise<void> {
  const { rows } = await db.query<{ in_window: boolean; drift_ms: number; kst: string }>(
    `select drinks_publish_window_ok(now()) as in_window,
            abs(extract(epoch from now()) * 1000 - $1::float8)::float8 as drift_ms,
            (now() at time zone 'Asia/Seoul')::text as kst`,
    [Date.now()],
  );
  const r = rows[0];
  assert.ok(r.drift_ms < 5000, `PGlite 시계가 고정 시계를 안 따른다(오차 ${r.drift_ms}ms) — dbTestClock 전제가 깨졌다`);
  assert.equal(r.in_window, true, `시험 시계 ${r.kst} KST 가 게시 창 밖이다`);
}
