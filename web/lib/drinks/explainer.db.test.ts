// 주류 설명형 슬롯·후보·시도·선택(0062) DB 통합 테스트 — PGlite 위에 0050~.
// 공급자 호출 없음: 이 표들은 "호출 전에 행을 만들고, 호출 뒤에 상태를 올리는" 장부다. 여기서는 장부 규칙만 본다.
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0062_drinks_explainer_assets.sql"), "0062 가 목록에 있어야 한다");
const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(join(DIR, m), "utf8"));

type Any = any;
const exec = async (fn: string, p: Record<string, unknown>) => {
  try {
    await db.exec("set role service_role");
    const res = await db.query<{ r: unknown }>(`select ${fn}($1::jsonb) as r`, [JSON.stringify(p)]);
    return { data: res.rows[0].r, error: null };
  } catch (e) {
    const err = e as { message: string; detail?: string; code?: string };
    return { data: null, error: { message: err.message, details: err.detail ?? null, code: err.code ?? null } };
  } finally {
    await db.exec("reset role");
  }
};
const act = (action: string, payload: Record<string, unknown>) => runDrinksAction(exec, { action, payload });
const ok = async (action: string, payload: Record<string, unknown>): Promise<Any> => {
  const r = await act(action, payload);
  assert.equal(r.status, 200, `${action} 실패: ${JSON.stringify(r.body)}`);
  return r.body.result;
};
const rpc = async (fn: string, p: Record<string, unknown>): Promise<Any> => {
  const r = await exec(fn, p);
  if (r.error) throw new Error(r.error.message);
  return r.data;
};
const rpcFails = async (fn: string, p: Record<string, unknown>, code: string) => {
  const r = await exec(fn, p);
  assert.ok(r.error, `${fn} 가 통과하면 안 된다`);
  assert.match(r.error!.message, new RegExp(`^drinks:${code}:`), r.error!.message);
};
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const uniq = () => Math.random().toString(36).slice(2);
const tv = async (id: string) => (await row("select version from drink_topics where id = $1", [id])).version;
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking in order to further enhance the taste.";
const QUOTE = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";

async function planRevision(): Promise<string> {
  const t = await ok("create_topic", { title: "슬롯 시험", question: `슬롯 시험 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  const topic = t.topic_id as string;
  await ok("triage", { topic_id: topic, expected_version: await tv(topic), scores: SCORES });
  await ok("topic_action", { topic_id: topic, expected_version: await tv(topic), action: "start_research" });
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const brief = { audience_question: "왜", core_takeaway: "시험", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } };
  const pack = { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", support_review: "supported",
    source_refs: [{ snapshot_id: s.snapshot_id, original_quote: QUOTE }] }] };
  const sv = await ok("save_review", { topic_id: topic, expected_topic_version: await tv(topic), scores: SCORES, brief, evidence_pack: pack });
  let r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await reviewRow(sv.review_id);
  await ok("select", { topic_id: topic, expected_version: await tv(topic), review_id: r.id, review_input_hash: r.approved_hash, formats: ["video"], editorial_week: "2026-11-02" });
  const b = await rpc("drinks_open_develop_budget", { cap_usd: 1, stage: "시험", purpose: "시험", approver_words: "승인" });
  await rpc("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id });
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const pl = await rpc("drinks_develop_save_plan", { ...l, plan_json: { scenes: [
    { narration: "왜 물을 넣을까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A glass" },
    { narration: "애호가들은 물을 몇 방울 넣어요.", claim_ids: ["c1"], visual_role: "reality", visual_prompt: "A glass" }] } });
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: {} });
  return pl.revision_id as string;
}

const PLAN = await planRevision();
const approval = async (cap = 5): Promise<string> => (await rpc("drinks_open_spend_approval", {
  cap_usd: cap, stage: "S2 시험", purpose: "시험", allowed_kinds: ["video"], approver_words: "승인한다" })).approval_id ?? "";
const specHash = () => createHash("sha256").update(uniq()).digest("hex");
let nextN = 1;
const slot = async (planned = 1, spec = specHash()) => {
  const n = nextN++;
  const s = await rpc("drinks_explainer_plan_slot", { plan_revision_id: PLAN, n, role: "mechanism", spec_hash: spec, min_src_ms: 7700, candidates_planned: planned,
    boundary_in: "cut_to_mechanism", boundary_out: "match" });
  return { slotId: s.slot_id as string, cand: s.candidate_ids as string[], spec };
};
const event = (attempt_id: string, to_state: string, extra: Record<string, unknown> = {}) => rpc("drinks_explainer_attempt_event", { attempt_id, to_state, ...extra });
const asset = async (): Promise<string> => (await row(
  `insert into drink_media_assets (storage_key, sha256, mime, bytes, width, height, duration_ms, rights)
   values ($1, $2, 'video/mp4', 10, 720, 1280, 8000, 'generated_paid') returning id`,
  [`drinks/generated/${uniq()}.mp4`, createHash("sha256").update(uniq()).digest("hex")])).id;
async function storedCandidate(cand: string, appr: string, provider = "omni") {
  const a = await rpc("drinks_explainer_open_attempt", { candidate_id: cand, approval_id: appr, provider });
  await event(a.attempt_id, "generating");
  await event(a.attempt_id, "received", { actual_usd: 0.81, billed_units: 46336 });
  await event(a.attempt_id, "probed");
  const id = await asset();
  await event(a.attempt_id, "stored", { asset_id: id });
  return { attempt: a, assetId: id };
}

test("상한 숫자가 config 와 같다", async () => {
  const lim: Any = await row("select drinks_explainer_limits() as l");
  assert.deepEqual(lim.l, { max_candidates_per_slot: 2, max_attempts_per_candidate: 2, max_attempts_per_slot: 4 });
});

test("슬롯: 후보를 계획한 만큼 만들고, 같은 슬롯에 다른 사양은 거절, 사양은 바꿀 수 없다", async () => {
  const { slotId, cand, spec } = await slot(2);
  assert.match(slotId, new RegExp(`^${PLAN}:A\\d+$`));
  assert.deepEqual(cand, [`${slotId}#c1`, `${slotId}#c2`]);
  const n = (await row("select n from drink_explainer_slots where slot_id = $1", [slotId])).n;
  const again = await rpc("drinks_explainer_plan_slot", { plan_revision_id: PLAN, n, role: "mechanism", spec_hash: spec, min_src_ms: 7700, candidates_planned: 2 });
  assert.equal(again.existing, true);
  await rpcFails("drinks_explainer_plan_slot", { plan_revision_id: PLAN, n, role: "mechanism", spec_hash: specHash(), min_src_ms: 7700, candidates_planned: 2 }, "immutable");
  await rpcFails("drinks_explainer_plan_slot", { plan_revision_id: PLAN, n: nextN++, role: "mechanism", spec_hash: specHash(), min_src_ms: 1, candidates_planned: 3 }, "invalid_input");
  await assert.rejects(db.query("update drink_explainer_slots set spec_hash = $1 where slot_id = $2", [specHash(), slotId]), /drinks:immutable:/);
  await assert.rejects(db.query("delete from drink_explainer_slots where slot_id = $1", [slotId]), /drinks:immutable:/);
});

test("멱등키 = sha256(attempt_id + spec_hash) — 파이썬 공식과 같고, 시도는 호출 전에 requested 로 만들어진다", async () => {
  const fixed: Any = await row("select drinks_explainer_idem('P:A1#c1#a1', $1) as k", ["a".repeat(64)]);
  assert.equal(fixed.k, "6840b8eadc5bd23d8e5f2f09ae2ee806da9cf0c72bb4caec82fc9cdec5565455", "tests/test_drinks_explainer.py 와 같은 값");
  const { cand, spec } = await slot();
  const a = await rpc("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: await approval(), provider: "omni" });
  assert.equal(a.attempt_id, `${cand[0]}#a1`);
  assert.equal(a.idempotency_key, createHash("sha256").update(a.attempt_id + spec).digest("hex"));
  const r = await row("select * from drink_explainer_attempts where attempt_id = $1", [a.attempt_id]);
  assert.equal(r.state, "requested");
  assert.equal(r.idempotency_key, a.idempotency_key);
  // 가짜 키로는 넣지 못한다(CHECK)
  await assert.rejects(db.query(
    `insert into drink_explainer_attempts (attempt_id, candidate_id, slot_id, m, spec_hash, idempotency_key, approval_id, provider)
     select attempt_id || 'x', candidate_id, slot_id, 2, spec_hash, $1, approval_id, provider from drink_explainer_attempts where attempt_id = $2`,
    ["f".repeat(64), a.attempt_id]), /check constraint/);
});

test("시도는 한 번에 하나, 후보당 2회까지 — 3번째는 함수도 표도 막는다", async () => {
  const appr = await approval();
  const { cand } = await slot();
  const a1 = await rpc("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" });
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" }, "attempt_open");
  await assert.rejects(db.query(
    `insert into drink_explainer_attempts (attempt_id, candidate_id, slot_id, m, spec_hash, idempotency_key, approval_id, provider)
     select candidate_id || '#a2', candidate_id, slot_id, 2, spec_hash, drinks_explainer_idem(candidate_id || '#a2', spec_hash), approval_id, provider
     from drink_explainer_attempts where attempt_id = $1`, [a1.attempt_id]), /drink_explainer_one_open_attempt_uq/);
  await event(a1.attempt_id, "failed_unbilled", { error_code: "429" });
  const a2 = await rpc("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" });
  assert.equal(a2.m, 2, "청구 없는 실패는 같은 결재로 다시 시도한다");
  await event(a2.attempt_id, "failed_unbilled");
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" }, "attempt_cap");
  await assert.rejects(db.query(
    `insert into drink_explainer_attempts (attempt_id, candidate_id, slot_id, m, spec_hash, idempotency_key, approval_id, provider)
     select candidate_id || '#a3', candidate_id, slot_id, 3, spec_hash, drinks_explainer_idem(candidate_id || '#a3', spec_hash), approval_id, provider
     from drink_explainer_attempts where attempt_id = $1`, [a2.attempt_id]), /check constraint/);
});

test("슬롯당 합계 4회 — 후보 둘이 2회씩 쓰면 끝이다", async () => {
  const appr = await approval();
  const { slotId, cand } = await slot(2);
  for (const c of cand) {
    for (let i = 0; i < 2; i++) {
      const a = await rpc("drinks_explainer_open_attempt", { candidate_id: c, approval_id: appr, provider: "omni" });
      await event(a.attempt_id, "failed_unbilled");
    }
  }
  assert.equal((await row("select count(*)::int n from drink_explainer_attempts where slot_id = $1", [slotId])).n, 4);
  for (const c of cand) await rpcFails("drinks_explainer_open_attempt", { candidate_id: c, approval_id: appr, provider: "omni" }, "attempt_cap");
});

test("unknown_billed: 닫기 전에는 새 시도 금지 · 운영자만 닫는다 · billed 뒤 재시도는 새 결재로만 · 비용이 후보에 남는다", async () => {
  const appr = await approval();
  const { cand } = await slot();
  const a = await rpc("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" });
  await event(a.attempt_id, "generating");
  await event(a.attempt_id, "unknown_billed", { error_code: "timeout" });
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" }, "unknown_billed_open");
  await rpcFails("drinks_explainer_close_unknown", { attempt_id: a.attempt_id, resolution: "billed", closed_by: "worker", note: "x", actual_usd: 0.8 }, "invalid_input");
  await rpcFails("drinks_explainer_close_unknown", { attempt_id: a.attempt_id, resolution: "billed", closed_by: "운영자", note: "청구서 확인" }, "invalid_input");
  await rpcFails("drinks_explainer_close_unknown", { attempt_id: a.attempt_id, resolution: "maybe", closed_by: "운영자", note: "x" }, "invalid_input");
  // event 경로로는 닫지 못한다
  const viaEvent = await exec("drinks_explainer_attempt_event", { attempt_id: a.attempt_id, to_state: "closed_void" });
  assert.match(viaEvent.error!.message, /^drinks:invalid_input:/);
  const closed = await rpc("drinks_explainer_close_unknown", { attempt_id: a.attempt_id, resolution: "billed", closed_by: "운영자", note: "청구서 확인", actual_usd: 0.81 });
  assert.equal(closed.state, "closed_billed");
  assert.equal(Number((await row("select cost_usd from drink_explainer_candidates where candidate_id = $1", [cand[0]])).cost_usd), 0.81);
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" }, "retry_needs_new_approval");
  const a2 = await rpc("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: await approval(), provider: "omni" });
  assert.equal(a2.m, 2);
  // void 는 없던 일: 금액 0, 같은 결재로 다시 시도할 수 있다
  const b = await slot();
  const v1 = await rpc("drinks_explainer_open_attempt", { candidate_id: b.cand[0], approval_id: appr, provider: "omni" });
  await event(v1.attempt_id, "generating");
  await event(v1.attempt_id, "unknown_billed");
  await rpc("drinks_explainer_close_unknown", { attempt_id: v1.attempt_id, resolution: "void", closed_by: "운영자", note: "청구 없음 확인" });
  assert.equal(Number((await row("select cost_usd from drink_explainer_candidates where candidate_id = $1", [b.cand[0]])).cost_usd), 0);
  assert.equal((await rpc("drinks_explainer_open_attempt", { candidate_id: b.cand[0], approval_id: appr, provider: "omni" })).m, 2);
});

test("요청 ID 가 있으면 조회로 정정할 수 있다 / 없으면 정정 못 한다", async () => {
  const { cand } = await slot();
  const a = await rpc("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: await approval(), provider: "veo_fast" });
  await event(a.attempt_id, "generating");
  await event(a.attempt_id, "unknown_billed");
  await rpcFails("drinks_explainer_attempt_event", { attempt_id: a.attempt_id, to_state: "received" }, "invalid_input");
  assert.equal((await event(a.attempt_id, "received", { provider_request_id: "operations/abc", actual_usd: 0.64 })).state, "received");
});

test("워커가 죽으면: generating 은 unknown_billed, requested 는 failed_unbilled — 다시 부르지 않는다", async () => {
  const appr = await approval();
  const g = await slot();
  const r = await slot();
  const ag = await rpc("drinks_explainer_open_attempt", { candidate_id: g.cand[0], approval_id: appr, provider: "omni" });
  await event(ag.attempt_id, "generating");
  const ar = await rpc("drinks_explainer_open_attempt", { candidate_id: r.cand[0], approval_id: appr, provider: "omni" });
  await db.query("update drink_explainer_attempts set updated_at = now() - interval '2 hours' where attempt_id in ($1, $2)", [ag.attempt_id, ar.attempt_id]);
  const res = await rpc("drinks_explainer_sweep_stale", { older_than_sec: 1800 });
  assert.ok(res.unknown_billed >= 1 && res.failed_unbilled >= 1);
  assert.equal((await row("select state from drink_explainer_attempts where attempt_id = $1", [ag.attempt_id])).state, "unknown_billed");
  assert.equal((await row("select state from drink_explainer_attempts where attempt_id = $1", [ar.attempt_id])).state, "failed_unbilled");
  assert.equal((await row("select count(*)::int n from drink_explainer_attempts where candidate_id = $1", [g.cand[0]])).n, 1, "새 시도를 만들지 않는다");
  await rpcFails("drinks_explainer_sweep_stale", { older_than_sec: 1 }, "invalid_input");
});

test("상태는 앞으로만 — 건너뛰기·되돌리기·끝난 시도 고치기·지우기를 표가 막는다", async () => {
  const { cand } = await slot();
  const { attempt } = await storedCandidate(cand[0], await approval());
  await assert.rejects(db.query("update drink_explainer_attempts set state = 'generating' where attempt_id = $1", [attempt.attempt_id]), /drinks:invalid_state:/);
  await assert.rejects(db.query("update drink_explainer_attempts set actual_usd = 0 where attempt_id = $1", [attempt.attempt_id]), /drinks:immutable:/);
  await assert.rejects(db.query("delete from drink_explainer_attempts where attempt_id = $1", [attempt.attempt_id]), /drinks:immutable:/);
  const b = await slot();
  const a = await rpc("drinks_explainer_open_attempt", { candidate_id: b.cand[0], approval_id: await approval(), provider: "omni" });
  await assert.rejects(db.query("update drink_explainer_attempts set state = 'stored' where attempt_id = $1", [a.attempt_id]), /drinks:invalid_state:/);
  await assert.rejects(db.query("update drink_explainer_attempts set state = 'unknown_billed' where attempt_id = $1", [a.attempt_id]), /drinks:invalid_state:/, "보내기 전 시도는 결과 불명이 될 수 없다");
  await rpcFails("drinks_explainer_attempt_event", { attempt_id: a.attempt_id, to_state: "generating", asset_id: "not-a-uuid" }, "invalid_input");
  await event(a.attempt_id, "generating");
  await event(a.attempt_id, "received");
  await event(a.attempt_id, "probed");
  await rpcFails("drinks_explainer_attempt_event", { attempt_id: a.attempt_id, to_state: "stored" }, "invalid_input");
});

test("저장된 후보는 다시 사지 않는다", async () => {
  const appr = await approval();
  const { cand } = await slot();
  await storedCandidate(cand[0], appr);
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" }, "already_stored");
});

test("선택: 사람만, 자동+사람 합격 후보만, 모든 후보 판정 뒤에만 · 기록은 못 바꾼다 · 재사용은 선택된 파일뿐", async () => {
  const appr = await approval();
  const { slotId, cand } = await slot(2);
  const c1 = await storedCandidate(cand[0], appr);
  await storedCandidate(cand[1], appr);
  assert.deepEqual(await rpc("drinks_explainer_selected_asset", { slot_id: slotId }), {}, "선택 전에는 다시 쓸 것이 없다");
  await rpc("drinks_explainer_verdict", { candidate_id: cand[0], auto_verdict: "pass" });
  await rpc("drinks_explainer_verdict", { candidate_id: cand[1], auto_verdict: "pass" });
  await rpcFails("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[0], selected_by: "운영자", reason: "더 낫다" }, "invalid_state");
  await rpc("drinks_explainer_verdict", { candidate_id: cand[0], human_verdict: "pass" });
  await rpcFails("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[0], selected_by: "운영자", reason: "더 낫다" }, "invalid_state");
  const v = await rpc("drinks_explainer_verdict", { candidate_id: cand[1], human_verdict: "fail" });
  assert.equal(v.slot_status, "human_checked");
  await rpcFails("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[0], selected_by: "worker", reason: "자동" }, "invalid_input");
  await rpcFails("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[1], selected_by: "운영자", reason: "불합격 후보" }, "not_passed");
  const sel = await rpc("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[0], selected_by: "운영자", reason: "훅으로 더 낫다" });
  assert.equal(sel.selected_candidate_id, cand[0]);
  assert.equal((await row("select status from drink_explainer_slots where slot_id = $1", [slotId])).status, "selected");
  const got = await rpc("drinks_explainer_selected_asset", { slot_id: slotId });
  assert.equal(got.asset_id, c1.assetId);
  assert.equal(got.duration_ms, 8000);
  await assert.rejects(db.query("update drink_explainer_selections set reason = 'x' where slot_id = $1", [slotId]), /drinks:immutable:/);
  await assert.rejects(db.query("delete from drink_explainer_selections where slot_id = $1", [slotId]), /drinks:immutable:/);
  await rpcFails("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[0], selected_by: "운영자", reason: "또" }, "invalid_state");
});

test("후보가 모두 불합격이면 no_pass — 고를 수 없고 더 살 수도 없다('그나마 나은 쪽' 없음)", async () => {
  const appr = await approval();
  const { slotId, cand } = await slot(2);
  await storedCandidate(cand[0], appr);
  await storedCandidate(cand[1], appr);
  await rpc("drinks_explainer_verdict", { candidate_id: cand[0], auto_verdict: "pass" });
  await rpc("drinks_explainer_verdict", { candidate_id: cand[0], human_verdict: "fail" });
  const v = await rpc("drinks_explainer_verdict", { candidate_id: cand[1], auto_verdict: "fail" });
  assert.equal(v.slot_status, "no_pass");
  await rpcFails("drinks_explainer_select", { slot_id: slotId, candidate_id: cand[0], selected_by: "운영자", reason: "그나마" }, "no_pass");
  await rpcFails("drinks_explainer_verdict", { candidate_id: cand[1], human_verdict: "pass" }, "invalid_state");
  const b = await slot(2);
  await rpc("drinks_explainer_verdict", { candidate_id: b.cand[0], auto_verdict: "fail" });
  await rpc("drinks_explainer_verdict", { candidate_id: b.cand[1], auto_verdict: "fail" });
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: b.cand[0], approval_id: appr, provider: "omni" }, "invalid_state");
});

test("닫힌 결재로는 시도를 만들지 못한다", async () => {
  const appr = await approval();
  await rpc("drinks_close_spend_approval", { approval_id: appr, reason: "끝" });
  const { cand } = await slot();
  await rpcFails("drinks_explainer_open_attempt", { candidate_id: cand[0], approval_id: appr, provider: "omni" }, "approval_closed");
});

test("anon 은 표도 함수도 쓰지 못한다", async () => {
  await db.exec("set role anon");
  try {
    for (const t of ["drink_explainer_slots", "drink_explainer_candidates", "drink_explainer_attempts", "drink_explainer_selections"]) {
      await assert.rejects(db.query(`select * from ${t}`), /permission denied/);
    }
    for (const f of ["drinks_explainer_plan_slot", "drinks_explainer_open_attempt", "drinks_explainer_attempt_event", "drinks_explainer_close_unknown",
      "drinks_explainer_verdict", "drinks_explainer_select", "drinks_explainer_selected_asset", "drinks_explainer_sweep_stale"]) {
      await assert.rejects(db.query(`select ${f}('{}'::jsonb)`), /permission denied/);
    }
  } finally {
    await db.exec("reset role");
  }
});
