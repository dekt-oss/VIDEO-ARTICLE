import assert from "node:assert/strict";
import test from "node:test";
import { runDrinksAction } from "./actions.ts";
import { JJERI_AVAILABILITY_WARNING, jjeriAvailability, jjeriJobMessage, jjeriPreview, jjeriQa } from "./jjeri.ts";

test("Jjeri requests use a separate RPC and reject paid or legacy routing", async () => {
  const calls: { fn: string; payload: Record<string, unknown> }[] = [];
  const exec = async (fn: string, payload: Record<string, unknown>) => {
    calls.push({ fn, payload });
    return { data: { renderer: "jjeri_class" }, error: null };
  };
  const plan = { plan_revision_id: "test-plan" };
  assert.equal((await runDrinksAction(exec, { action: "request_jjeri_render", payload: plan })).status, 200);
  assert.equal((await runDrinksAction(exec, { action: "request_jjeri_render", payload: { ...plan, paid: true } })).status, 400);
  assert.equal((await runDrinksAction(exec, { action: "request_render", payload: { ...plan, renderer: "jjeri_class" } })).status, 400);
  assert.equal((await runDrinksAction(exec, { action: "request_render", payload: plan })).status, 200);
  assert.deepEqual(calls, [{ fn: "drinks_request_jjeri_render", payload: plan }, { fn: "drinks_request_render", payload: plan }]);
});

test("preview and QA read stored episode fields without changing legacy plans", () => {
  assert.equal(jjeriPreview({ scenes: [] }), null);
  assert.equal(jjeriQa({ warnings: [] }), null);
  const scenes = [{ id: "s1", template: "glass_pair_question", beats: [{ text: "질문" }] }];
  const chapters = [{ from_scene: "s1", title: "첫 장" }];
  assert.deepEqual(jjeriPreview({ jjeri_class: { format: "jjeri_class", version: 1, topic: "모의", scenes, chapters } }),
    { topic: "모의", scenes, chapters });
  assert.deepEqual(jjeriQa({ renderer: "jjeri_class", audio: { lufs: -15.1, true_peak_dbtp: -1.5 },
    evidence: { human_source_review_required: true, source_ids_by_scene: { s1: ["source"], s2: [] } } }),
  { lufs: -15.1, peak: -1.5, reviewedScenes: 1, humanReview: true });
});

test("Jjeri generation actions require consent and expose only operator RPCs", async () => {
  const calls: { fn: string; payload: Record<string, unknown> }[] = [];
  const exec = async (fn: string, payload: Record<string, unknown>) => {
    calls.push({ fn, payload });
    return { data: { status: "queued" }, error: null };
  };
  const request = { topic_id: "topic", review_id: "review", review_hash: "hash",
    budget_id: "budget", max_usd: 0.05, spend_confirmed: true };
  const approval = { request_id: "request", review_confirmed: true };
  assert.equal((await runDrinksAction(exec, { action: "request_jjeri_episode",
    payload: { ...request, spend_confirmed: "true" } })).status, 400);
  assert.equal((await runDrinksAction(exec, { action: "approve_jjeri_episode",
    payload: { ...approval, review_confirmed: false } })).status, 400);
  assert.equal((await runDrinksAction(exec, { action: "finish_jjeri_episode", payload: {} })).status, 400);
  assert.equal((await runDrinksAction(exec, { action: "request_jjeri_episode", payload: request })).status, 200);
  assert.equal((await runDrinksAction(exec, { action: "approve_jjeri_episode", payload: approval })).status, 200);
  assert.deepEqual(calls, [
    { fn: "drinks_request_jjeri_episode", payload: request },
    { fn: "drinks_approve_jjeri_episode", payload: approval },
  ]);
});


test("selector requires a valid directive and a ready database, without affecting other plans", () => {
  const ready = { data: { ready: true }, error: null };
  const valid = { jjeri_class: { format: "jjeri_class", version: 1, topic: "모의",
    scenes: [{ id: "s1", template: "x", beats: [{ text: "질문" }] }], chapters: [] } };
  assert.equal(jjeriAvailability({}, true, ready).state, "hidden");
  assert.equal(jjeriAvailability(valid, false, ready).state, "hidden");
  assert.equal(jjeriAvailability({ jjeri_class: {} }, true, ready).state, "directive_invalid");
  assert.equal(jjeriAvailability(valid, true, { data: null, error: { code: "PGRST202" } }).state, "db_missing");
  assert.equal(jjeriAvailability(valid, true, { data: null, error: { code: "42501" } }).state, "db_unavailable");
  assert.equal(jjeriAvailability(valid, true, { data: { ready: false }, error: null }).state, "db_unavailable");
  assert.equal(jjeriAvailability(valid, true, ready).state, "ready");
  assert.match(JJERI_AVAILABILITY_WARNING.db_missing, /적용되지 않았습니다/);
  assert.match(jjeriJobMessage("jjeri_class", "source_label_invalid", null) ?? "", /발행처명/);
  assert.match(jjeriJobMessage("jjeri_class", "claim_unapproved", null) ?? "", /지지 검토/);
  assert.equal(jjeriJobMessage("local", "claim_unapproved", "기존 오류"), "기존 오류");
});
