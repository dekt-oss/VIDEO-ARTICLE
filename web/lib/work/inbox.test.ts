// 순수 로직 테스트. 실행: `node --test web/lib/work/inbox.test.ts`
// 작업함(결정 2-1): 편마다 단계 하나, 칩으로 거른다.
import test from "node:test";
import assert from "node:assert/strict";
import { inboxStage, inChip, chipCounts, renderStateOf, parseChip, STAGE_META } from "./inbox.ts";

const base = { hasDraft: false, requestStatus: null, onHold: false, directive: null, render: null } as const;

test("초안 쪽 단계", () => {
  assert.equal(inboxStage({ ...base }), "draft_missing");
  assert.equal(inboxStage({ ...base, onHold: true }), "hold");
  assert.equal(inboxStage({ ...base, requestStatus: "processing" }), "drafting");
  assert.equal(inboxStage({ ...base, requestStatus: "error" }), "draft_error");
  assert.equal(inboxStage({ ...base, hasDraft: true }), "draft_review");
});

test("지시서 쪽 단계 — 옛 엔진은 따로 보인다", () => {
  const d = { ...base, hasDraft: true };
  assert.equal(inboxStage({ ...d, directive: { status: "draft", outdated: false } }), "directive_review");
  assert.equal(inboxStage({ ...d, directive: { status: "draft", outdated: true } }), "directive_outdated");
  assert.equal(inboxStage({ ...d, directive: { status: "approved", outdated: false } }), "rendering");
});

test("렌더가 있으면 그것이 가장 뒤 단계", () => {
  const d = { ...base, hasDraft: true, directive: { status: "rendered", outdated: false } };
  assert.equal(inboxStage({ ...d, render: "upload_wait" }), "upload_wait");
  assert.equal(inboxStage({ ...d, render: "done" }), "done");
  assert.equal(inboxStage({ ...d, render: "failed" }), "render_failed");
});

test("할 것 칩은 사람이 손댈 단계만 — 보류·진행 중·완료는 빠진다", () => {
  assert.equal(inChip("draft_missing", "todo"), true);
  assert.equal(inChip("directive_outdated", "todo"), true);
  assert.equal(inChip("hold", "todo"), false);
  assert.equal(inChip("rendering", "todo"), false);
  assert.equal(inChip("done", "todo"), false);
  assert.equal(inChip("hold", "hold"), true);
  const c = chipCounts(["draft_missing", "hold", "hold", "directive_review", "done"]);
  assert.equal(c.todo, 2);
  assert.equal(c.hold, 2);
  assert.equal(c.all, 5);
});

test("렌더 상태는 가장 최근 잡 기준, 보관한 잡은 무시", () => {
  assert.equal(renderStateOf([]), null);
  assert.equal(renderStateOf([
    { status: "failed", created_at: "2026-09-01" },
    { status: "done", youtube_status: "done", created_at: "2026-09-20" },
  ]), "done");
  assert.equal(renderStateOf([{ status: "done", created_at: "2026-09-20" }]), "upload_wait");
  assert.equal(renderStateOf([{ status: "assembling", created_at: "2026-09-20" }]), "running");
  assert.equal(renderStateOf([{ status: "done", saved_at: "x", created_at: "2026-09-20" }]), null);
});

test("주소의 ?stage= 는 모르는 값이면 할 것", () => {
  assert.equal(parseChip(undefined), "todo");
  assert.equal(parseChip("hold"), "hold");
  assert.equal(parseChip("nope"), "todo");
  for (const m of Object.values(STAGE_META)) assert.ok(m.label.length > 0);
});
