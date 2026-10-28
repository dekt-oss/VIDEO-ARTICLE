// 주류 유료 생성 결재·지출 잠금(0054) DB 통합 테스트 — PGlite 위에 0050~0054.
// 운영자 동작(결재 열기·닫기·유료 렌더 요청)은 runDrinksAction 경로, 워커 동작(가잡기·확정·파일 등록)은 rpc 직접.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { DRINKS_ACTIONS, runDrinksAction } from "./actions.ts";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql", "0054_drinks_spend.sql"].map((f) => join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations", f));
const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(m, "utf8"));

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
const fails = async (action: string, payload: Record<string, unknown>, code: string): Promise<Any> => {
  const r = await act(action, payload);
  assert.notEqual(r.status, 200, `${action} 가 통과하면 안 된다`);
  assert.equal(r.body.code, code, JSON.stringify(r.body));
  return r.body;
};
const worker = async (fn: string, p: Record<string, unknown>): Promise<Any> => {
  const r = await exec(fn, p);
  if (r.error) throw new Error(r.error.message);
  return r.data;
};
const workerFails = async (fn: string, p: Record<string, unknown>, code: string) => {
  const r = await exec(fn, p);
  assert.ok(r.error, `${fn} 가 통과하면 안 된다`);
  assert.match(r.error!.message, new RegExp(`^drinks:${code}:`));
};
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const uniq = () => Math.random().toString(36).slice(2);
const hex = () => Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "산지의 신청에 따라 국세청장관이 지정하면 산지 이름을 독점적으로 쓸 수 있다.";
const brief = { audience_question: "누가 정할까?", core_takeaway: "산지가 신청하고 장관이 지정", selected_claim_ids: ["c1"],
  proposed_formats: ["video"], required_claims: { video: ["c1"] } };
const tv = async (id: string) => (await row("select version from drink_topics where id = $1", [id])).version;
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);

/** 근거 승인 → 영상 편성 → 제작안 승인. 장면: 실사형(그림 지시문 있음)·3D 도해·정리 카드. 예상 = 0.039 + 0.134 = 0.173 */
async function approvedVideoPlan(scenes?: Any[]) {
  const t = await ok("create_topic", { title: "지리적 표시", question: `산지 이름은 누가 정할까 ${uniq()}`, categories: ["sake"], lane: "evergreen" });
  const id = t.topic_id;
  await ok("triage", { topic_id: id, expected_version: await tv(id), scores: SCORES });
  await ok("topic_action", { topic_id: id, expected_version: await tv(id), action: "start_research" });
  const s = await ok("add_source", { topic_id: id, source: { url: `https://www.nta.go.jp/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const sv = await ok("save_review", { topic_id: id, expected_topic_version: await tv(id), scores: SCORES, brief, evidence_pack: { claims: [
    { claim_id: "c1", text: "산지 신청 → 장관 지정 → 독점 사용", claim_type: "process", support_review: "supported",
      source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "국세청장관이 지정하면 산지 이름을 독점적으로 쓸 수 있다" }] }] } });
  let r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await reviewRow(sv.review_id);
  await ok("select", { topic_id: id, expected_version: await tv(id), review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["video"], editorial_week: "2026-10-26" });
  const v = await ok("save_plan", { topic_id: id, format: "video", topic_review_id: r.id, plan_json: { scenes: scenes ?? [
    { narration: "라벨의 지역 이름, 아무나 쓸까요?", content_kind: "transition", visual_role: "reality",
      visual_prompt: "A shelf of five unbranded sake bottles" },
    { narration: "산지가 신청하고 장관이 지정합니다", visual_role: "mechanism", claim_ids: ["c1"],
      visual_prompt: "Isometric diorama of a brewery and an office", motion_prompt: "the envelope slides" },
    { narration: "라벨을 확인해 보세요", content_kind: "transition", visual_role: "text_card" }] } });
  let p = await planRow(v.revision_id);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" });
  p = await planRow(v.revision_id);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "approve" });
  return v.revision_id as string;
}

const open = (plan: string | null, cap: number, extra: Record<string, unknown> = {}) => ok("open_spend_approval", {
  ...(plan ? { plan_revision_id: plan } : {}), stage: "1단계 그림 3장", purpose: "시험", cap_usd: cap, allowed_kinds: ["image"],
  approver_words: "승인한다 진행해", order_hash: hex(), ...extra });
const hold = (approval: string, item: string, est: number, extra: Record<string, unknown> = {}) =>
  exec("drinks_hold_spend", { approval_id: approval, item_key: item, kind: "image", provider: "gemini", model: "gemini-2.5-flash-image", est_usd: est, ...extra });

test("결재는 운영자 동작으로 열고 닫는다 — 상한 $10 초과·결재 문장 없음은 거절, 결재자 이름은 입력을 믿지 않는다", async () => {
  assert.equal(DRINKS_ACTIONS.open_spend_approval, "drinks_open_spend_approval");
  assert.ok(!Object.keys(DRINKS_ACTIONS).some((k) => /hold|settle|register_generated/.test(k)), "화면은 돈을 쓰는 함수를 부르지 못한다");
  await fails("open_spend_approval", { stage: "x", purpose: "x", cap_usd: 10.5, allowed_kinds: ["image"], approver_words: "ok" }, "invalid_input");
  await fails("open_spend_approval", { stage: "x", purpose: "x", cap_usd: 1, allowed_kinds: ["image"], approver_words: " " }, "invalid_input");
  await fails("open_spend_approval", { stage: "x", purpose: "x", cap_usd: 1, allowed_kinds: ["audio"], approver_words: "ok" }, "invalid_input");
  const a = await open(null, 0.3, { approved_by: "누군가" });
  assert.equal(Number(a.cap_usd), 0.3);
  assert.equal(Number(a.remaining_usd), 0.3);
  assert.equal((await row("select approved_by from drink_spend_approvals where id = $1", [a.approval_id])).approved_by, "operator");
  await fails("close_spend_approval", { approval_id: a.approval_id }, "invalid_input");
  const c = await ok("close_spend_approval", { approval_id: a.approval_id, reason: "시험 끝" });
  assert.equal(c.status, "closed");
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "x", kind: "image", est_usd: 0.039 }, "approval_closed");
  // 결재 내용은 바꿀 수 없다(트리거)
  await assert.rejects(db.query("update drink_spend_approvals set cap_usd = 5 where id = $1", [a.approval_id]), /drinks:immutable:/);
  await assert.rejects(db.query("delete from drink_spend_approvals where id = $1", [a.approval_id]), /drinks:immutable:/);
});

test("가잡기는 결재 금액 안에서만 — 넘으면 거절, 확정은 실제 금액, 실패 해제는 금액을 돌려준다", async () => {
  const a = await open(null, 0.3);
  const h1 = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-01-reality", kind: "image", provider: "gemini", est_usd: 0.039 });
  const h2 = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-02-mechanism", kind: "image", provider: "gemini", est_usd: 0.134 });
  assert.equal(Number(h2.remaining_usd), 0.127);
  const over = await hold(a.approval_id, "scene-03-big", 0.2);
  assert.match(over.error!.message, /^drinks:budget_exceeded:/);
  assert.deepEqual(JSON.parse(over.error!.details!), { cap_usd: 0.3, committed_usd: 0.173, requested_usd: 0.2 });
  await worker("drinks_settle_spend", { hold_id: h1.hold_id, outcome: "settled", actual_usd: 0.039 });
  const rel = await worker("drinks_settle_spend", { hold_id: h2.hold_id, outcome: "released", note: "생성 실패" });
  assert.equal(Number(rel.spent_usd), 0.039);
  assert.equal(Number(rel.remaining_usd), 0.261, "해제된 가잡기는 상한을 다시 비운다");
  await workerFails("drinks_settle_spend", { hold_id: h1.hold_id, outcome: "released" }, "invalid_state");
  await assert.rejects(db.query("update drink_spend_holds set actual_usd = 0 where id = $1", [h1.hold_id]), /drinks:immutable:/);
  // 같은 항목: 이미 산 것은 다시 못 산다, 사는 중이면 못 산다, 실패만 3번까지
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-01-reality", kind: "image", est_usd: 0.039 }, "already_bought");
  const h3 = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-02-mechanism", kind: "image", est_usd: 0.134 });
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-02-mechanism", kind: "image", est_usd: 0.134 }, "hold_in_progress");
  await worker("drinks_settle_spend", { hold_id: h3.hold_id, outcome: "released" });
  const h4 = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-02-mechanism", kind: "image", est_usd: 0.134 });
  await worker("drinks_settle_spend", { hold_id: h4.hold_id, outcome: "released" });
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-02-mechanism", kind: "image", est_usd: 0.134 }, "retry_limit");
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "clip", kind: "video", est_usd: 0.1 }, "kind_not_approved");
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "z", kind: "image", est_usd: 0 }, "invalid_input");
});

test("산 파일은 확정된 지출에만 등록되고, 같은 프롬프트 해시는 다시 찾아 쓴다", async () => {
  const a = await open(null, 0.3);
  const h = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-01-reality", kind: "image", model: "m", est_usd: 0.039 });
  const ph = hex();
  const asset = { storage_key: `drinks/generated/${ph.slice(0, 2)}/${ph}.png`, sha256: hex(), mime: "image/png", bytes: 10, width: 768, height: 1344 };
  await workerFails("drinks_register_generated", { hold_id: h.hold_id, prompt_hash: ph, asset }, "invalid_state");
  await worker("drinks_settle_spend", { hold_id: h.hold_id, outcome: "settled", actual_usd: 0.039 });
  const g = await worker("drinks_register_generated", { hold_id: h.hold_id, prompt_hash: ph, asset });
  assert.equal(g.existing, false);
  assert.equal((await row("select rights from drink_media_assets where id = $1", [g.asset_id])).rights, "generated_paid");
  const again = await worker("drinks_register_generated", { hold_id: h.hold_id, prompt_hash: ph, asset });
  assert.equal(again.existing, true);
  const found = await worker("drinks_find_generated", { prompt_hashes: [ph, hex()] });
  assert.equal(found.length, 1);
  assert.equal(found[0].storage_key, asset.storage_key);
});

test("제작안은 장면의 영어 그림·움직임 지시문을 보존하고, 화면용 예상 금액은 정리 카드를 0원으로 센다", async () => {
  const plan = await approvedVideoPlan();
  const p = await planRow(plan);
  assert.equal(p.plan_json.scenes[0].visual_prompt, "A shelf of five unbranded sake bottles");
  assert.equal(p.plan_json.scenes[1].motion_prompt, "the envelope slides");
  const s = await worker("drinks_plan_spend", { plan_revision_id: plan });
  assert.equal(Number(s.estimate.total_usd), 0.173);
  assert.equal(s.estimate.images, 2);
  assert.deepEqual(s.estimate.scenes.map((x: Any) => [x.position, x.role, Number(x.usd)]),
    [[1, "reality", 0.039], [2, "mechanism", 0.134], [3, "text_card", 0]]);
  assert.deepEqual(s.approvals, []);
});

test("유료 렌더 요청은 그 제작안 전용 열린 결재가 있고 예상이 남은 금액 안일 때만 큐에 들어간다", async () => {
  const plan = await approvedVideoPlan();
  await fails("request_render", { plan_revision_id: plan, paid: true }, "paid_disabled");
  const other = await open(null, 1);
  await fails("request_render", { plan_revision_id: plan, paid: true, spend_approval_id: other.approval_id }, "ownership");
  const small = await open(plan, 0.1);
  const r = await fails("request_render", { plan_revision_id: plan, paid: true, spend_approval_id: small.approval_id }, "budget_insufficient");
  assert.equal(Number(r.detail.estimate.total_usd), 0.173);
  await ok("close_spend_approval", { approval_id: small.approval_id, reason: "상한 부족" });
  const a = await open(plan, 0.3);
  const j = await ok("request_render", { plan_revision_id: plan, paid: true, spend_approval_id: a.approval_id });
  assert.equal(j.renderer, "paid");
  const dup = await ok("request_render", { plan_revision_id: plan, paid: true, spend_approval_id: a.approval_id });
  assert.equal(dup.existing, true);
  const local = await ok("request_render", { plan_revision_id: plan });
  assert.equal(local.existing, false, "무료 렌더는 다른 입력(같은 활성 작업으로 합쳐지지 않는다)");
  // 체크 제약: 유료 작업은 결재가 있어야 한다(함수를 우회한 직접 쓰기도 막힌다)
  await assert.rejects(db.query("update drink_production_jobs set spend_approval_id = null where id = $1", [j.job_id]), /drink_prod_paid_needs_approval/);
  // 워커: 시작 페이로드에 renderer·결재가 실린다. 임대로 가잡기 — 다른 결재로는 못 쓴다
  let got = await worker("drinks_start_render", { worker_id: "t" });
  while (got.job && got.job.job_id !== j.job_id) {
    await worker("drinks_finish_render", { job_id: got.job.job_id, lease_token: got.job.lease_token, outcome: "failed", error_code: "x" });
    got = await worker("drinks_start_render", { worker_id: "t" });
  }
  assert.equal(got.job.renderer, "paid");
  assert.equal(got.job.spend_approval_id, a.approval_id);
  const lease = { job_id: j.job_id, lease_token: got.job.lease_token };
  const h = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-01-reality", kind: "image", est_usd: 0.039, ...lease });
  assert.ok(h.hold_id);
  // 이 제작안으로 산 장면은 다음 예상에서 0원(다시 쓴다) — 다시 렌더가 '예상 초과'로 막히지 않는다
  await worker("drinks_settle_spend", { hold_id: h.hold_id, outcome: "settled", actual_usd: 0.039 });
  const est = (await worker("drinks_plan_spend", { plan_revision_id: plan })).estimate;
  assert.equal(Number(est.total_usd), 0.134);
  assert.equal(est.bought, 1);
  assert.deepEqual([est.scenes[0].bought, Number(est.scenes[0].usd), Number(est.scenes[0].price_usd)], [true, 0, 0.039]);
  await workerFails("drinks_hold_spend", { approval_id: other.approval_id, item_key: "scene-01-reality", kind: "image", est_usd: 0.039, ...lease }, "ownership");
  await workerFails("drinks_hold_spend", { approval_id: a.approval_id, item_key: "scene-02", kind: "image", est_usd: 0.134,
    job_id: j.job_id, lease_token: "00000000-0000-0000-0000-000000000000" }, "lease_lost");
});

test("대기 중에 결재가 닫히면 유료 작업은 시작하지 않고 취소된다(돈을 쓰기 전에 멈춘다)", async () => {
  const plan = await approvedVideoPlan();
  const a = await open(plan, 0.3);
  const j = await ok("request_render", { plan_revision_id: plan, paid: true, spend_approval_id: a.approval_id });
  await ok("close_spend_approval", { approval_id: a.approval_id, reason: "보류" });
  for (;;) {
    const got = await worker("drinks_start_render", { worker_id: "t" });
    if (!got.job) break;
    await worker("drinks_finish_render", { job_id: got.job.job_id, lease_token: got.job.lease_token, outcome: "failed", error_code: "x" });
  }
  const jr = await row("select status, error_code from drink_production_jobs where id = $1", [j.job_id]);
  assert.deepEqual([jr.status, jr.error_code], ["canceled", "approval_closed"]);
});

test("브라우저 역할(anon)은 결재·지출·재사용 목록을 읽지도 쓰지도 못한다", async () => {
  await db.exec("set role anon");
  try {
    for (const t of ["drink_spend_approvals", "drink_spend_holds", "drink_generated_assets"]) {
      await assert.rejects(db.query(`select 1 from ${t} limit 1`), /permission denied/);
    }
    await assert.rejects(db.query(`select drinks_hold_spend('{}'::jsonb)`), /permission denied/);
  } finally {
    await db.exec("reset role");
  }
});
