// 실행: `cd web && node --test components/drinks/work/flowSteps.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { flowSteps, weekRangeLabel } from "./flowSteps.ts";

const SECTIONS = [
  { key: "draft", label: "초안" },
  { key: "evidence", label: "근거" },
  { key: "approve", label: "내용 승인" },
  { key: "produce", label: "제작" },
  { key: "after", label: "게시 뒤" },
];
const dec = (code: string, extra: { busy?: boolean; blocks?: number } = {}) => ({
  blocks: Array.from({ length: extra.blocks ?? 0 }, () => ({ code: "no_pass" as const, message: "x" })),
  primary: { code, label: "x", panel: "none" as const, busy: extra.busy },
});

test("지금 칸 위는 끝남, 아래는 기다림", () => {
  assert.deepEqual(flowSteps(SECTIONS, "approve", dec("S4")).map((s) => s.state), ["done", "done", "now", "waiting", "waiting"]);
});

test("차단이 있으면 지금 칸은 막힘, 진행 중이면 진행 중", () => {
  assert.equal(flowSteps(SECTIONS, "produce", dec("B7", { blocks: 1 }))[3].state, "blocked");
  assert.equal(flowSteps(SECTIONS, "produce", dec("S8", { busy: true }))[3].state, "busy");
});

test("게시가 끝났으면 게시 뒤만 지금", () => {
  assert.deepEqual(flowSteps(SECTIONS, null, dec("S20")).map((s) => s.state), ["done", "done", "done", "done", "now"]);
});

test("지금 칸을 모르면 끝남을 지어내지 않는다", () => {
  assert.ok(flowSteps(SECTIONS, null, dec("needs_review")).every((s) => s.state === "unknown"));
  assert.ok(flowSteps(SECTIONS, null, null).every((s) => s.state === "unknown"));
});

test("편성 주차 → 월~일", () => {
  assert.equal(weekRangeLabel("2026-11-02"), "11.02–11.08");
  assert.equal(weekRangeLabel("2026-12-28"), "12.28–01.03");
  assert.equal(weekRangeLabel(null), null);
  assert.equal(weekRangeLabel("다음 주"), "다음 주");
});
