// 순수 로직 테스트. 실행: `node --test web/lib/requestQueue.test.ts` (Node 22 타입 스트리핑).
import { test } from "node:test";
import assert from "node:assert/strict";
import { isStaleProcessing, REQUEST_STALE_MINUTES } from "./requestQueue.ts";

const NOW = new Date("2026-09-17T12:00:00Z");
const minutesAgo = (m: number) => new Date(NOW.getTime() - m * 60 * 1000).toISOString();

test("방금 집은 요청은 정체가 아니다 — 살아 있는 워커의 일을 뺏으면 비용이 두 배가 된다", () => {
  assert.equal(isStaleProcessing(minutesAgo(0), NOW), false);
  assert.equal(isStaleProcessing(minutesAgo(5), NOW), false);
});

test("문턱 직전은 아직 살아 있는 것으로 본다", () => {
  assert.equal(isStaleProcessing(minutesAgo(REQUEST_STALE_MINUTES - 1), NOW), false);
});

test("문턱을 넘기면 죽은 것으로 본다", () => {
  assert.equal(isStaleProcessing(minutesAgo(REQUEST_STALE_MINUTES + 1), NOW), true);
});

test("워커 잡 타임아웃(draft.yml 30분 · queues.yml 45분)보다 길어야 한다", () => {
  // 살아 있는 워커는 최대 45분이면 끝나거나 러너가 죽인다. 문턱이 그보다 짧으면
  // 정상 동작 중인 워커의 요청을 다른 워커가 집어가 같은 초안을 두 번 만든다.
  assert.ok(REQUEST_STALE_MINUTES > 45, `문턱 ${REQUEST_STALE_MINUTES}분은 워커 타임아웃 45분보다 짧다`);
});

test("시각이 비었거나 깨졌으면 정체로 본다 — 영원히 막혀 있는 것보다 낫다", () => {
  assert.equal(isStaleProcessing(null, NOW), true);
  assert.equal(isStaleProcessing(undefined, NOW), true);
  assert.equal(isStaleProcessing("그런 날짜 없음", NOW), true);
});
