// 순수 로직 테스트. 실행: `node --test web/lib/work/backlog.test.ts`
// 밀린 일 정리 규칙(2026-09-30 운영자 결정 3-1): 낙점 14일 무초안 → 보류, 조치 필요 렌더 30일 → 보관 제안.
import test from "node:test";
import assert from "node:assert/strict";
import { isOnHold, isStalled, HOLD_AFTER_DAYS } from "./backlog.ts";
import { classifyRenderJob, countByTab, STALE_ACTION_DAYS } from "./renderQueue.ts";

const NOW = new Date("2026-09-30T12:00:00Z");
const daysAgo = (d: number) => new Date(NOW.getTime() - d * 86400000).toISOString();

test("낙점 뒤 14일이 지나도 초안이 없으면 보류", () => {
  assert.equal(HOLD_AFTER_DAYS, 14);
  assert.equal(isOnHold({ hasDraft: false, decidedAt: daysAgo(15) }, NOW), true);
  assert.equal(isOnHold({ hasDraft: false, decidedAt: daysAgo(13) }, NOW), false);
});

test("초안이 있으면 오래돼도 보류가 아니다 — 초안을 만들면 되살아난다", () => {
  assert.equal(isOnHold({ hasDraft: true, decidedAt: daysAgo(90) }, NOW), false);
});

test("검수 단계 멈춤: 마지막 산출물이 14일 넘으면 true, 시각 모르면 false", () => {
  assert.equal(isStalled(daysAgo(15), NOW), true);
  assert.equal(isStalled(daysAgo(2), NOW), false);
  assert.equal(isStalled(null, NOW), false);
});

test("낙점 시각을 모르면 보류로 치우지 않는다", () => {
  assert.equal(isOnHold({ hasDraft: false, decidedAt: null }, NOW), false);
});

test("조치 필요 렌더가 30일 넘으면 보관 제안 탭으로 — 숫자에서 빠진다", () => {
  assert.equal(STALE_ACTION_DAYS, 30);
  const old = { status: "done", output_url: "u", finished_at: daysAgo(82) };
  const fresh = { status: "done", output_url: "u", finished_at: daysAgo(3) };
  const oldFail = { status: "failed", created_at: daysAgo(79) };
  assert.equal(classifyRenderJob(old, NOW), "stale");
  assert.equal(classifyRenderJob(oldFail, NOW), "stale");
  assert.equal(classifyRenderJob(fresh, NOW), "action");
  // 업로드까지 끝난 것·보관한 것은 나이와 무관하게 제자리
  assert.equal(classifyRenderJob({ ...old, youtube_status: "done" }, NOW), "done");
  assert.equal(classifyRenderJob({ ...old, saved_at: daysAgo(1) }, NOW), "saved");
});

test("시각이 없는 잡은 옮기지 않는다(옛 동작 그대로)", () => {
  assert.equal(classifyRenderJob({ status: "failed" }, NOW), "action");
  assert.equal(countByTab([{ status: "failed" }]).stale, 0);
});
