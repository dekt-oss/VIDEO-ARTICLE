// 순수 로직 테스트. 실행: `node --test web/lib/reviewSort.test.ts` (Node 22 타입 스트리핑).
import test from "node:test";
import assert from "node:assert/strict";
import { groupForReview, parseReviewSort } from "./reviewSort.ts";

const rows = [
  { id: "a", decided_at: "2026-09-30T01:00:00Z", draft_created_at: null },
  { id: "b", decided_at: "2026-09-28T01:00:00Z", draft_created_at: "2026-09-30T11:52:00Z" }, // KST 9/30 20:52
  { id: "c", decided_at: "2026-09-26T01:00:00Z", draft_created_at: "2026-09-27T10:16:00Z" }, // KST 9/27 19:16
  { id: "d", decided_at: "2026-09-26T02:00:00Z", draft_created_at: "2026-09-30T10:05:00Z" }, // KST 9/30 19:05
  { id: "e", decided_at: null, draft_created_at: null },
];
const ids = (g: { items: { id: string }[] }[]) => g.map((x) => x.items.map((i) => i.id).join(""));

test("기본(낙점일순): 낙점일 최신 묶음이 먼저, 날짜 없는 것은 맨 뒤", () => {
  const g = groupForReview(rows, "decided");
  assert.deepEqual(g.map((x) => x.date), ["2026-09-30", "2026-09-28", "2026-09-26", null]);
  assert.deepEqual(ids(g), ["a", "b", "dc", "e"]);
});

test("초안 생성순: 초안 만든 날(KST)로 묶고 그 안은 최신순, 초안 없는 것은 맨 아래 한 묶음", () => {
  const g = groupForReview(rows, "draft");
  assert.deepEqual(g.map((x) => x.date), ["2026-09-30", "2026-09-27", null]);
  assert.deepEqual(ids(g), ["bd", "c", "ae"]);
});

test("알 수 없는 값은 기본 정렬", () => {
  assert.equal(parseReviewSort(undefined), "decided");
  assert.equal(parseReviewSort("draft"), "draft");
  assert.equal(parseReviewSort("x"), "decided");
});
