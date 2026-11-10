// 설명형 제작 큐(0067) DB 통합 테스트 — PGlite 위에 0050~. 공급자 호출 없음.
// 워커까지 물린 한 편 전체는 tests/test_drinks_explainer_queue.py 가 같은 SQL 로 돌린다. 여기서는 규칙만 본다.
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d|8\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0067_drinks_explainer_queue.sql"), "0067 이 목록에 있어야 한다");
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
const fails = async (action: string, payload: Record<string, unknown>, code: string) => {
  const r = await act(action, payload);
  assert.notEqual(r.status, 200, `${action} 가 통과하면 안 된다`);
  assert.equal(r.body.code, code, JSON.stringify(r.body));
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
const stateOf = async (plan: string) => (await row("select state from drink_explainer_episodes where plan_revision_id = $1", [plan])).state;

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking in order to further enhance the taste.";
const QUOTE = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";
const hash = () => createHash("sha256").update(uniq()).digest("hex");

/** 승인된 영상 제작안. explainer=true 면 설명형 의도를 표에 넣는다. */
async function approvedPlan(explainer = true): Promise<{ plan: string; topic: string }> {
  const t = await ok("create_topic", { title: "큐 시험", question: `큐 시험 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  const topic = t.topic_id as string;
  await ok("triage", { topic_id: topic, expected_version: await tv(topic), scores: SCORES });
  await ok("topic_action", { topic_id: topic, expected_version: await tv(topic), action: "start_research" });
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const brief = { audience_question: "왜", core_takeaway: "시험", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } };
  const pack = { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", support_review: "supported", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: QUOTE }] }] };
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
    { narration: "왜 물을 넣을까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A glass", motion_prompt: "camera" },
    { narration: "애호가들은 물을 몇 방울 넣어요.", claim_ids: ["c1"], visual_role: "mechanism", visual_prompt: "A glass", motion_prompt: "camera" }] } });
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: { visual_claims: [{ scene: 1 }, { scene: 2 }] } });
  const plan = pl.revision_id as string;
  let p = await row("select version from drink_plan_revisions where id = $1", [plan]);
  await ok("plan_action", { revision_id: plan, expected_version: p.version, action: "submit" });
  p = await row("select version from drink_plan_revisions where id = $1", [plan]);
  await ok("plan_action", { revision_id: plan, expected_version: p.version, action: "approve" });
  if (explainer) await db.query("insert into drink_topic_picks (topic_id, format_intent, editorial_week) values ($1, 'explainer', '2026-11-02')", [topic]);
  return { plan, topic };
}

const DIRECTIVE = { slots: [{ n: 1 }, { n: 2 }], estimate: { suggested_cap_usd: 5 } };
// 큐는 표 하나다 — 앞 시험이 남긴 대기 작업을 치우고 이 제작안의 작업을 집는다.
const startJob = async (plan: string): Promise<Any> => {
  await db.query("update drink_production_jobs set status = 'canceled', finished_at = now() where status = 'queued' and plan_revision_id <> $1", [plan]);
  return (await rpc("drinks_start_render", { worker_id: "t" })).job;
};
const lease = (j: Any) => ({ job_id: j.job_id, lease_token: j.lease_token });
const ORDER = "a".repeat(64);

async function withDirective(): Promise<{ plan: string; topic: string }> {
  const out = await approvedPlan();
  await ok("explainer_request_plan", { plan_revision_id: out.plan });
  const j = await startJob(out.plan);
  assert.equal(j.renderer, "explainer_plan");
  await rpc("drinks_explainer_save_directive", { ...lease(j), directive: DIRECTIVE, order_hash: ORDER });
  await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "succeeded", result: { status_code: "directive_ready" } });
  return out;
}
const approval = async (plan: string, over: Record<string, unknown> = {}): Promise<string> => (await ok("open_spend_approval", {
  plan_revision_id: plan, stage: "S2", purpose: "시험", cap_usd: 5, allowed_kinds: ["image", "video"], approver_words: "승인한다", ...over })).approval_id;
const asset = async (): Promise<string> => (await row(
  `insert into drink_media_assets (storage_key, sha256, mime, bytes, width, height, duration_ms, rights)
   values ($1, $2, 'video/mp4', 10, 720, 1280, 8000, 'generated_paid') returning id`, [`drinks/generated/${uniq()}.mp4`, hash()])).id;

test("옛 렌더는 계속 못 간다 — 무료·유료 둘 다, 형식을 나중에 정해도", async () => {
  const { plan } = await approvedPlan();
  await fails("request_render", { plan_revision_id: plan }, "not_renderable");
  const a = await approval(plan, { allowed_kinds: ["image"] });
  await fails("request_render", { plan_revision_id: plan, paid: true, spend_approval_id: a }, "not_renderable");
  assert.equal((await row("select count(*)::int n from drink_production_jobs where plan_revision_id = $1", [plan])).n, 0);
  assert.equal((await row("select drinks_plan_renderable($1) as v", [plan])).v, null, "유효성은 따로 잰다");

  // 옛 소재는 그대로 렌더된다
  const old = await approvedPlan(false);
  const j = await ok("request_render", { plan_revision_id: old.plan });
  // 대기 중에 설명형으로 바뀌면 그 옛 작업은 취소된다
  await db.query("insert into drink_topic_picks (topic_id, format_intent, editorial_week) values ($1, 'explainer', '2026-11-02')", [old.topic]);
  const after = await row("select status, error_code from drink_production_jobs where id = $1", [j.job_id]);
  assert.deepEqual([after.status, after.error_code], ["canceled", "explainer_engine_only"]);
  // 설명형 작업은 설명형 소재에만
  const plain = await approvedPlan(false);
  await fails("explainer_request_plan", { plan_revision_id: plain.plan }, "not_renderable");
});

test("지시서: 0원 작업, 한 번 저장하면 못 바꾼다, 작업은 동시에 하나", async () => {
  const { plan } = await approvedPlan();
  const r1 = await ok("explainer_request_plan", { plan_revision_id: plan });
  assert.equal(r1.renderer, "explainer_plan");
  assert.equal((await ok("explainer_request_plan", { plan_revision_id: plan })).existing, true);
  assert.equal((await row("select spend_approval_id from drink_production_jobs where id = $1", [r1.job_id])).spend_approval_id, null);
  const j = await startJob(plan);
  await rpcFails("drinks_explainer_save_directive", { ...lease(j), directive: { slots: [] } }, "invalid_input");
  await rpc("drinks_explainer_save_directive", { ...lease(j), directive: DIRECTIVE, order_hash: ORDER });
  await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "succeeded", result: {} });
  assert.equal(await stateOf(plan), "directive_ready");
  await fails("explainer_request_plan", { plan_revision_id: plan }, "invalid_state");
  await assert.rejects(db.query("update drink_explainer_episodes set directive = '{}'::jsonb where plan_revision_id = $1", [plan]), /drinks:immutable:/);
  await assert.rejects(db.query("delete from drink_explainer_episodes where plan_revision_id = $1", [plan]), /drinks:immutable:/);
});

test("구매 요청: 그 제작안 전용·열림·그림+영상 결재만, 보여 준 지시서와 같아야 한다", async () => {
  const { plan } = await withDirective();
  const other = await withDirective();
  await fails("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: await approval(other.plan) }, "ownership");
  await fails("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: await approval(plan, { allowed_kinds: ["image"] }) }, "kind_not_approved");
  await fails("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: await approval(plan, { order_hash: "b".repeat(64) }) }, "order_changed");
  const closed = await approval(plan);
  await ok("close_spend_approval", { approval_id: closed, reason: "끝" });
  await fails("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: closed }, "approval_closed");
  await fails("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: await approval(plan), through_n: 0 }, "invalid_input");
  const a = await approval(plan, { order_hash: ORDER });
  const r = await ok("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: a, through_n: 2 });
  assert.equal(r.renderer, "explainer_buy");
  const ep = await row("select state, approval_id, buy_through_n from drink_explainer_episodes where plan_revision_id = $1", [plan]);
  assert.deepEqual([ep.state, ep.approval_id, ep.buy_through_n], ["approved", a, 2]);
  const job = await row("select spend_approval_id from drink_production_jobs where id = $1", [r.job_id]);
  assert.equal(job.spend_approval_id, a);
  const noDirective = await approvedPlan();
  await fails("explainer_request_buy", { plan_revision_id: noDirective.plan, spend_approval_id: await approval(noDirective.plan) }, "directive_missing");
});

test("사진클레이(0079): 그림만 허용한 결재로 사고, 고를 후보 없이 조립을 받는다 — 방식은 바꿀 수 없다", async () => {
  const { plan } = await approvedPlan();
  await ok("explainer_request_plan", { plan_revision_id: plan, provider: "clay" });
  const j = await startJob(plan);
  await rpc("drinks_explainer_save_directive", { ...lease(j), directive: DIRECTIVE, order_hash: ORDER });
  await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "succeeded", result: { status_code: "directive_ready" } });
  assert.equal((await row("select provider from drink_explainer_episodes where plan_revision_id = $1", [plan])).provider, "clay");
  await assert.rejects(db.query("update drink_explainer_episodes set provider = 'omni' where plan_revision_id = $1", [plan]), /drinks:immutable:/);
  await fails("explainer_request_assemble", { plan_revision_id: plan }, "invalid_state");   // 그림을 다 사기 전
  const a = await approval(plan, { allowed_kinds: ["image"], order_hash: ORDER });
  assert.equal((await ok("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: a })).renderer, "explainer_buy");
  const b = await startJob(plan);
  await rpc("drinks_explainer_episode_event", { ...lease(b), to_state: "buying" });
  await rpc("drinks_explainer_episode_event", { ...lease(b), to_state: "assets_complete" });
  await rpc("drinks_explainer_finish_job", { ...lease(b), outcome: "succeeded", result: { status_code: "assets_complete" } });
  assert.equal((await ok("explainer_request_assemble", { plan_revision_id: plan })).renderer, "explainer_render", "선택 행 0개여도 조립");
  await assert.rejects(db.query("insert into drink_explainer_episodes (plan_revision_id, topic_id, provider) select id, topic_id, 'sora' from drink_plan_revisions limit 1"),
    /drink_explainer_episodes_provider_check|duplicate key/);
  // 클립 편은 그대로: 그림만 허용한 결재로는 못 사고, 선택 없이는 조립이 안 된다
  const clip = await withDirective();
  await fails("explainer_request_buy", { plan_revision_id: clip.plan, spend_approval_id: await approval(clip.plan, { allowed_kinds: ["image"] }) }, "kind_not_approved");
});

test("표가 직접 막는다: 구매 작업은 결재 없이 못 넣고, 다른 렌더러는 못 넣는다", async () => {
  const { plan, topic } = await approvedPlan();
  const ins = (renderer: string) => db.query(
    `insert into drink_production_jobs (topic_id, plan_revision_id, format, input_hash, plan_hash, review_hash, renderer, renderer_version)
     values ($1, $2, 'video', $3, 'x', 'x', $4, 'v')`, [topic, plan, uniq(), renderer]);
  await assert.rejects(ins("explainer_buy"), /drink_prod_paid_needs_approval/);
  await assert.rejects(ins("explainer_other"), /drink_production_jobs_renderer_check/);
  await assert.rejects(ins("local"), /drinks:not_renderable:/);
  await ins("explainer_plan");
  await assert.rejects(ins("explainer_render"), /drink_prod_one_explainer_uq/, "한 편의 설명형 작업은 동시에 하나");
});

test("가잡기 상한은 0054 그대로 — 구매 작업도 결재 금액을 못 넘고, 다른 결재를 못 쓴다", async () => {
  const { plan } = await withDirective();
  const a = await approval(plan, { cap_usd: 0.5 });
  await ok("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: a });
  const j = await startJob(plan);
  assert.equal(j.renderer, "explainer_buy");
  assert.equal(j.spend_approval_id, a);
  await rpcFails("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: "x", kind: "video", provider: "omni", est_usd: 0.81 }, "budget_exceeded");
  const other = await approval(plan);
  await rpcFails("drinks_hold_spend", { ...lease(j), approval_id: other, item_key: "x", kind: "video", provider: "omni", est_usd: 0.1 }, "ownership");
  const h = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: "x", kind: "video", provider: "omni", est_usd: 0.4 });
  assert.ok(h.hold_id);
  const fin = await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "failed", error_code: "budget_exceeded", error_message: "넘음", to_state: "blocked_budget" });
  assert.equal(fin.status, "failed");
  assert.equal(await stateOf(plan), "blocked_budget");
});

async function buyingEpisode(cap = 5) {
  const out = await withDirective();
  const a = await approval(out.plan, { cap_usd: cap });
  await ok("explainer_request_buy", { plan_revision_id: out.plan, spend_approval_id: a });
  const j = await startJob(out.plan);
  await rpc("drinks_explainer_episode_event", { ...lease(j), to_state: "buying" });
  return { ...out, a, j };
}
const planSlot = async (plan: string, n: number, planned = 1) => (await rpc("drinks_explainer_plan_slot", { plan_revision_id: plan, n, role: "mechanism", spec_hash: hash(), min_src_ms: 7700, candidates_planned: planned,
  boundary_in: "cut", boundary_out: "cut" }));

test("경계 cut 을 받는다 · 워커는 사람 검수 상태를 못 올린다 · 건너뛰기를 표가 막는다", async () => {
  const { plan, j } = await buyingEpisode();
  await planSlot(plan, 1);
  await rpcFails("drinks_explainer_episode_event", { ...lease(j), to_state: "quality_review_pass" }, "invalid_input");
  await rpcFails("drinks_explainer_episode_event", { ...lease(j), to_state: "ready_to_publish" }, "invalid_input");
  await rpcFails("drinks_explainer_episode_event", { ...lease(j), to_state: "rendered" }, "invalid_state");
  await rpcFails("drinks_explainer_episode_event", { job_id: j.job_id, lease_token: "00000000-0000-4000-8000-000000000000", to_state: "blocked_budget" }, "lease_lost");
  await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "succeeded", result: { status_code: "awaiting_review" } });
  assert.equal((await row("select status, result_manifest_id from drink_production_jobs where id = $1", [j.job_id])).result_manifest_id, null, "구매 작업은 파일 없이 닫힌다");
});

test("결과 불명: 닫으면 가잡기도 닫힌다 — billed 확정, void 해제. 닫기 전에는 구매 요청 불가. 다 닫으면 buying 으로", async () => {
  for (const [resolution, status, spent] of [["billed", "settled", 0.81], ["void", "released", 0]] as const) {
    const { plan, a, j } = await buyingEpisode();
    const s = await planSlot(plan, 1);
    const cand = s.candidate_ids[0];
    const h = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: cand, kind: "video", provider: "omni", est_usd: 0.81 });
    const at = await rpc("drinks_explainer_open_attempt", { candidate_id: cand, approval_id: a, provider: "omni" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "generating", hold_id: h.hold_id });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "unknown_billed", error_code: "timeout" });
    await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "failed", error_code: "unknown_billed", error_message: "모름", to_state: "unknown_billed" });
    assert.equal(await stateOf(plan), "unknown_billed");
    const held = await rpc("drinks_spend_state", { approval_id: a });
    assert.equal(Number(held.held_usd), 0.81, "닫기 전에는 상한을 계속 차지한다");
    await fails("explainer_request_buy", { plan_revision_id: plan, spend_approval_id: a }, "unknown_billed_open");
    const st = await rpc("drinks_explainer_status", { plan_revision_id: plan });
    assert.deepEqual(st.unknown_attempts, [at.attempt_id]);
    await ok("explainer_close_unknown", { attempt_id: at.attempt_id, resolution, note: "청구서 확인", ...(resolution === "billed" ? { actual_usd: 0.81 } : {}), closed_by: "worker" });
    const row1 = await row("select closed_by from drink_explainer_attempts where attempt_id = $1", [at.attempt_id]);
    assert.equal(row1.closed_by, "operator", "닫은 사람 이름은 입력값을 믿지 않는다");
    assert.equal((await row("select status from drink_spend_holds where id = $1", [h.hold_id])).status, status);
    const after = await rpc("drinks_spend_state", { approval_id: a });
    assert.equal(Number(after.held_usd), 0);
    assert.equal(Number(after.spent_usd), spent);
    assert.equal(await stateOf(plan), "buying");
  }
});

test("워커가 죽으면: 편도 멈추고 가잡기는 상태별로 — requested 해제, generating 유지, received 확정", async () => {
  const { plan, a, j } = await buyingEpisode();
  const mk = async (n: number) => {
    const s = await planSlot(plan, n);
    const cand = s.candidate_ids[0];
    const h = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: cand, kind: "video", provider: "omni", est_usd: 0.5 });
    const at = await rpc("drinks_explainer_open_attempt", { candidate_id: cand, approval_id: a, provider: "omni" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, hold_id: h.hold_id, to_state: "generating" });
    return { at: at.attempt_id, hold: h.hold_id };
  };
  const gen = await mk(1);
  const rec = await mk(2);
  await rpc("drinks_explainer_attempt_event", { attempt_id: rec.at, to_state: "received" });
  const sReq = await planSlot(plan, 3);
  const hReq = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: sReq.candidate_ids[0], kind: "video", provider: "omni", est_usd: 0.5 });
  const req = await rpc("drinks_explainer_open_attempt", { candidate_id: sReq.candidate_ids[0], approval_id: a, provider: "omni" });
  await db.query("update drink_explainer_attempts set hold_id = $1 where attempt_id = $2", [hReq.hold_id, req.attempt_id]);
  await db.query("alter table drink_explainer_attempts disable trigger drink_explainer_attempts_guard");
  await db.query("update drink_explainer_attempts set updated_at = now() - interval '2 hours' where slot_id like $1", [`${plan}%`]);
  await db.query("alter table drink_explainer_attempts enable trigger drink_explainer_attempts_guard");
  const res = await rpc("drinks_explainer_sweep_stale", { older_than_sec: 1800 });
  assert.ok(res.unknown_billed >= 1 && res.failed_unbilled >= 1 && res.failed_billed >= 1);
  const stateAt = async (id: string) => (await row("select state from drink_explainer_attempts where attempt_id = $1", [id])).state;
  assert.equal(await stateAt(gen.at), "unknown_billed");
  assert.equal(await stateAt(rec.at), "failed_billed");
  assert.equal(await stateAt(req.attempt_id), "failed_unbilled");
  const holdOf = async (id: string) => (await row("select status from drink_spend_holds where id = $1", [id])).status;
  assert.equal(await holdOf(gen.hold), "held");
  assert.equal(await holdOf(rec.hold), "settled");
  assert.equal(await holdOf(hReq.hold_id), "released");
  assert.equal(await stateOf(plan), "unknown_billed");
});

test("자동 불합격 후보에는 사람 판정이 필요 없다 · 화면은 자동 판정을 못 쓴다 · 전부 불합격이면 blocked_no_pass", async () => {
  const { plan, a, j } = await buyingEpisode();
  const s = await planSlot(plan, 1, 2);
  const [c1, c2] = s.candidate_ids;
  const store = async (c: string) => {
    const h = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: c, kind: "video", provider: "omni", est_usd: 0.81 });
    const at = await rpc("drinks_explainer_open_attempt", { candidate_id: c, approval_id: a, provider: "omni" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, hold_id: h.hold_id, to_state: "generating" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "received", actual_usd: 0.81 });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "probed" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "stored", asset_id: await asset() });
  };
  await store(c1);
  await store(c2);
  await rpc("drinks_explainer_verdict", { candidate_id: c1, auto_verdict: "pass", auto_report: { pass: true, blocks: [] } });
  await rpc("drinks_explainer_verdict", { candidate_id: c2, auto_verdict: "fail", auto_report: { pass: false, blocks: ["clip_short"] } });
  assert.deepEqual((await row("select auto_report from drink_explainer_candidates where candidate_id = $1", [c2])).auto_report.blocks, ["clip_short"]);
  // 화면에서 자동 판정을 보내도 무시된다
  await fails("explainer_verdict", { candidate_id: c1, auto_verdict: "pass" }, "invalid_input");
  await ok("explainer_verdict", { candidate_id: c1, human_verdict: "pass", auto_verdict: "fail" });
  assert.equal((await row("select auto_verdict from drink_explainer_candidates where candidate_id = $1", [c1])).auto_verdict, "pass");
  assert.equal((await row("select status from drink_explainer_slots where slot_id = $1", [s.slot_id])).status, "human_checked", "자동 불합격 후보를 기다리지 않는다");
  await fails("explainer_select", { slot_id: s.slot_id, candidate_id: c2, reason: "그나마" }, "not_passed");
  await ok("explainer_select", { slot_id: s.slot_id, candidate_id: c1, reason: "낫다", selected_by: "worker" });
  assert.equal((await row("select selected_by from drink_explainer_selections where slot_id = $1", [s.slot_id])).selected_by, "operator");

  const b = await planSlot(plan, 2, 1);
  await rpcFails("drinks_explainer_verdict", { candidate_id: b.candidate_ids[0], human_verdict: "pass" }, "invalid_state");
  await rpc("drinks_explainer_verdict", { candidate_id: b.candidate_ids[0], auto_verdict: "fail" });
  assert.equal(await stateOf(plan), "blocked_no_pass");
});

test("모든 슬롯 선택 → assets_complete → 조립 → 과정·품질 검수 → 파일 승인 → 게시 대기. 순서를 건너뛸 수 없다", async () => {
  const { plan, a, j } = await buyingEpisode();
  await fails("explainer_request_assemble", { plan_revision_id: plan }, "selection_incomplete");
  for (const n of [1, 2]) {
    const s = await planSlot(plan, n);
    const c = s.candidate_ids[0];
    const h = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: c, kind: "video", provider: "omni", est_usd: 0.81 });
    const at = await rpc("drinks_explainer_open_attempt", { candidate_id: c, approval_id: a, provider: "omni" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, hold_id: h.hold_id, to_state: "generating" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "received", actual_usd: 0.81 });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "probed" });
    await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "stored", asset_id: await asset() });
    await rpc("drinks_explainer_verdict", { candidate_id: c, auto_verdict: "pass" });
    await ok("explainer_verdict", { candidate_id: c, human_verdict: "pass" });
    await ok("explainer_select", { slot_id: s.slot_id, candidate_id: c, reason: "좋다" });
    assert.equal(await stateOf(plan), n === 1 ? "buying" : "assets_complete");
  }
  await rpc("drinks_explainer_finish_job", { ...lease(j), outcome: "succeeded", result: {} });
  await fails("explainer_review", { plan_revision_id: plan, stage: "process", outcome: "pass", checks: {} }, "invalid_state");
  const r = await ok("explainer_request_assemble", { plan_revision_id: plan });
  assert.equal(r.renderer, "explainer_render");
  const job = await row("select spend_approval_id from drink_production_jobs where id = $1", [r.job_id]);
  assert.equal(job.spend_approval_id, null, "조립 작업에는 결재가 없다 — 쓸 돈이 없다");
  const rj = await startJob(plan);
  await rpc("drinks_explainer_episode_event", { ...lease(rj), to_state: "rehearsal" });
  // 조립 성공은 파일 묶음으로만 닫힌다
  await rpcFails("drinks_explainer_finish_job", { ...lease(rj), outcome: "succeeded" }, "invalid_state");
  // 가잡기는 결재가 없는 작업에서 막힌다
  await rpcFails("drinks_hold_spend", { ...lease(rj), approval_id: a, item_key: "y", kind: "video", provider: "omni", est_usd: 0.1 }, "ownership");
  await rpc("drinks_explainer_episode_event", { ...lease(rj), to_state: "rendered" });
  const put = async (name: string, mime: string) => (await rpc("drinks_register_asset", { ...lease(rj), asset: { storage_key: `drinks/${rj.job_id}/${name}`, sha256: hash(), mime, bytes: 10, rights: "generated_paid" } })).asset_id;
  const assets = [{ asset_id: await put("f.mp4", "video/mp4"), role: "final_video", position: 1 }, { asset_id: await put("c.jpg", "image/jpeg"), role: "cover", position: 1 }];
  await rpc("drinks_explainer_episode_event", { ...lease(rj), to_state: "auto_qa_pass" });
  const fin = await rpc("drinks_finish_render", { ...lease(rj), outcome: "succeeded", assets, qa: { format: "explainer" } });
  const review = await row("select * from drink_output_reviews where manifest_id = $1", [fin.manifest_id]);
  const CK = { scene_types_labeled: true, no_real_product_implied: true, claims_match_evidence: true, audio_subtitles_ok: true, vertical_ok: true };
  await fails("output_review_action", { review_id: review.id, expected_version: review.version, action: "approve", checklist: CK }, "review_blocked");
  await fails("explainer_review", { plan_revision_id: plan, stage: "quality", outcome: "pass", checks: {} }, "invalid_state");
  await fails("explainer_review", { plan_revision_id: plan, stage: "process", outcome: "pass", checks: { directive_matches_clips: true } }, "checklist_incomplete");
  await ok("explainer_review", { plan_revision_id: plan, stage: "process", outcome: "pass", checks: { directive_matches_clips: true, selection_reasons_ok: true, cost_matches_approval: true } });
  await fails("explainer_review", { plan_revision_id: plan, stage: "quality", outcome: "pass", checks: { stops_in_first_1_5s: true } }, "checklist_incomplete");
  await ok("explainer_review", { plan_revision_id: plan, stage: "quality", outcome: "pass", checks: { stops_in_first_1_5s: true, no_photo_like_scene: true, match_boundaries_connect: true, mechanism_explains_why: true, no_fake_text: true, loop_natural: true } });
  assert.equal(await stateOf(plan), "quality_review_pass");
  await ok("output_review_action", { review_id: review.id, expected_version: review.version, action: "approve", checklist: CK });
  assert.equal(await stateOf(plan), "ready_to_publish");
  const usable = await row("select currently_usable from drink_output_validity where manifest_id = $1", [fin.manifest_id]);
  assert.equal(usable.currently_usable, true, "게시 경로(0055)가 보는 값");
});

test("사람 검수 불합격 → review_fail → 다시 조립할 수 있다 / 파일 복구 뒤 blocked_assets 에서도 다시 조립", async () => {
  assert.equal((await row("select drinks_explainer_can_transition('review_fail','rehearsal') as v")).v, true);
  assert.equal((await row("select drinks_explainer_can_transition('blocked_assets','approved') as v")).v, true);
  assert.equal((await row("select drinks_explainer_can_transition('blocked_assets','rehearsal') as v")).v, false);
  assert.equal((await row("select drinks_explainer_can_transition('buying','ready_to_publish') as v")).v, false);
  assert.equal((await row("select drinks_explainer_can_transition('unknown_billed','assets_complete') as v")).v, false);
});

test("상태 조회: 슬롯별 비용이 원장과 같다(그림 + 후보), 설명형이 아니면 표시한다", async () => {
  const { plan, a, j } = await buyingEpisode();
  const h = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: "scene-01-mechanism", kind: "image", provider: "gemini", est_usd: 0.134 });
  await rpc("drinks_settle_spend", { hold_id: h.hold_id, outcome: "settled", actual_usd: 0.134 });
  const s = await planSlot(plan, 1);
  const c = s.candidate_ids[0];
  const hc = await rpc("drinks_hold_spend", { ...lease(j), approval_id: a, item_key: c, kind: "video", provider: "omni", est_usd: 0.81 });
  const at = await rpc("drinks_explainer_open_attempt", { candidate_id: c, approval_id: a, provider: "omni" });
  await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, hold_id: hc.hold_id, to_state: "generating" });
  await rpc("drinks_explainer_attempt_event", { attempt_id: at.attempt_id, to_state: "received", actual_usd: 0.81, billed_units: 46336 });
  const st = await rpc("drinks_explainer_status", { plan_revision_id: plan });
  assert.equal(st.is_explainer, true);
  assert.equal(Number(st.slots[0].image_usd), 0.134);
  assert.equal(Number(st.slots[0].candidates[0].cost_usd), 0.81);
  assert.equal(st.slots[0].candidates[0].attempts[0].est_usd, 0.81);
  const plain = await approvedPlan(false);
  const p2 = await rpc("drinks_explainer_status", { plan_revision_id: plain.plan });
  assert.equal(p2.is_explainer, false);
  assert.equal(p2.episode, null);
  const ctx = await rpc("drinks_explainer_job_context", { plan_revision_id: plan, approval_id: a });
  assert.equal(ctx.approval.status, "open");
  assert.deepEqual(ctx.visual_claims.map((x: Any) => x.scene), [1, 2], "시각 주장표는 개발 요청 결과에서 온다");
});

test("anon 은 새 표·함수를 못 쓴다", async () => {
  await db.exec("set role anon");
  try {
    await assert.rejects(db.query("select * from drink_explainer_episodes"), /permission denied/);
    for (const f of ["drinks_explainer_request_plan", "drinks_explainer_request_buy", "drinks_explainer_request_assemble", "drinks_explainer_review", "drinks_explainer_status",
      "drinks_explainer_job_context", "drinks_explainer_save_directive", "drinks_explainer_episode_event", "drinks_explainer_finish_job"]) {
      await assert.rejects(db.query(`select ${f}('{}'::jsonb)`), /permission denied/);
    }
  } finally {
    await db.exec("reset role");
  }
});
