// 주류 소재 자동 개발(0060) DB 통합 테스트 — PGlite 위에 0050~0060.
// 운영자 동작(소재·근거·승인)은 기존 runDrinksAction 경로, 개발 큐·결재·워커 함수는 rpc 직접(화면이 못 부르는 함수는 워커 전용).
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|60)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0060_drinks_develop.sql"), "0060 이 목록에 있어야 한다");
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

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking in order to further enhance the taste. " +
  "Chemically, the smoky flavour is attributed to phenols, and in particular guaiacol.";
const tv = async (id: string) => (await row("select version from drink_topics where id = $1", [id])).version;
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);

async function researchingTopic() {
  const t = await ok("create_topic", { title: "위스키에 물", question: `위스키에 물을 넣는 이유 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  await ok("triage", { topic_id: t.topic_id, expected_version: await tv(t.topic_id), scores: SCORES });
  await ok("topic_action", { topic_id: t.topic_id, expected_version: await tv(t.topic_id), action: "start_research" });
  return t.topic_id as string;
}
const budget = (cap: number, extra: Record<string, unknown> = {}) => rpc("drinks_open_develop_budget", {
  cap_usd: cap, stage: "0단계 시험", purpose: "시험", approver_words: "승인한다", ...extra });
const claim = (cid: string, snap: string, quote: string) => ({ claim_id: cid, text: `주장 ${cid}`, claim_type: "process",
  source_refs: [{ snapshot_id: snap, original_quote: quote }] });
const QUOTE1 = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";
const QUOTE2 = "the smoky flavour is attributed to phenols, and in particular guaiacol";

test("결재: 상한 $10 초과·결재 문장 없음은 거절, 열고 닫기, 닫으면 못 쓴다", async () => {
  await rpcFails("drinks_open_develop_budget", { cap_usd: 10.5, stage: "x", purpose: "x", approver_words: "ok" }, "invalid_input");
  await rpcFails("drinks_open_develop_budget", { cap_usd: 1, stage: "x", purpose: "x", approver_words: " " }, "invalid_input");
  const b = await budget(1);
  assert.equal(Number(b.cap_usd), 1);
  assert.equal(Number(b.remaining_usd), 1);
  await rpcFails("drinks_close_develop_budget", { budget_id: b.budget_id }, "invalid_input");
  const c = await rpc("drinks_close_develop_budget", { budget_id: b.budget_id, reason: "시험 끝" });
  assert.equal(c.status, "closed");
  await assert.rejects(db.query("update drink_develop_budgets set cap_usd = 5 where id = $1", [b.budget_id]), /drinks:immutable:/);
  await assert.rejects(db.query("delete from drink_develop_budgets where id = $1", [b.budget_id]), /drinks:immutable:/);
  const topic = await researchingTopic();
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "evidence", budget_id: b.budget_id }, "approval_closed");
});

test("요청: 소재×종류 활성 1건(중복 요청은 같은 요청), 취소, 잘못된 상태 거절, anon 거부", async () => {
  const inbox = await ok("create_topic", { title: "x", question: `질문 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  await rpcFails("drinks_request_develop", { topic_id: inbox.topic_id, kind: "evidence" }, "invalid_state");
  await rpcFails("drinks_request_develop", { topic_id: inbox.topic_id, kind: "weird" }, "invalid_input");

  const topic = await researchingTopic();
  const r1 = await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence" });
  assert.equal(r1.status, "queued");
  assert.equal(r1.existing, false);
  assert.equal(r1.budget_id, null, "결재 없이도 큐에는 들어간다 — 워커가 모델 호출을 거부한다");
  const r2 = await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence" });
  assert.equal(r2.request_id, r1.request_id);
  assert.equal(r2.existing, true);
  await assert.rejects(db.query("insert into drink_develop_requests (topic_id, kind) values ($1, 'evidence')", [topic]), /drink_develop_one_active_uq/);
  // plan 은 승인된 근거가 있어야 한다
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan" }, "review_not_approved");
  const st = await rpc("drinks_develop_status", { topic_id: topic });
  assert.equal(st.requests.length, 1);
  assert.equal(st.active.request_id, r1.request_id);
  assert.equal(st.limits.max_usd_per_request, 0.5);
  const c = await rpc("drinks_cancel_develop", { request_id: r1.request_id });
  assert.equal(c.status, "canceled");
  const again = await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence" });
  assert.equal(again.existing, false, "취소된 요청은 활성이 아니다");
  await rpc("drinks_cancel_develop", { request_id: again.request_id });
  // 끝난 요청은 바꿀 수 없다
  await assert.rejects(db.query("update drink_develop_requests set step = 'x' where id = $1", [r1.request_id]), /drinks:immutable:/);

  // anon 은 표도 함수도 쓰지 못한다
  await db.exec("set role anon");
  try {
    await assert.rejects(db.query("select * from drink_develop_requests"), /permission denied/);
    await assert.rejects(db.query("select * from drink_develop_budget_state"), /permission denied/);
    await assert.rejects(db.query("select drinks_request_develop('{}'::jsonb)"), /permission denied/);
    await assert.rejects(db.query("select drinks_start_develop('{}'::jsonb)"), /permission denied/);
    await assert.rejects(db.query("select drinks_develop_hold('{}'::jsonb)"), /permission denied/);
  } finally {
    await db.exec("reset role");
  }
});

test("결재가 없으면 모델을 못 부른다 — 가잡기는 결재·요청 상한·호출 횟수 안에서만, 확정·해제가 남은 금액을 바꾼다", async () => {
  const topic = await researchingTopic();
  const q = await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence" });
  const got = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(got.job.request_id, q.request_id);
  assert.equal(got.job.budget, null);
  assert.equal(got.job.topic.title, "위스키에 물");
  const lease = { request_id: got.job.request_id, lease_token: got.job.lease_token };
  await rpcFails("drinks_develop_hold", { ...lease, est_usd: 0.01, model: "m" }, "budget_missing");
  await rpcFails("drinks_develop_hold", { request_id: lease.request_id, lease_token: "00000000-0000-0000-0000-000000000000", est_usd: 0.01 }, "lease_lost");
  assert.equal((await row("select count(*)::int n from drink_develop_holds where request_id = $1", [lease.request_id])).n, 0);
  await rpc("drinks_finish_develop", { ...lease, outcome: "blocked", error_code: "budget_missing", error_message: "결재 없음" });
  const done = await row("select * from drink_develop_requests where id = $1", [lease.request_id]);
  assert.equal(done.status, "blocked");
  assert.equal(done.error_code, "budget_missing");

  // 결재 있는 요청 — 결재 $5, 요청 상한 $0.5
  const b = await budget(5);
  const q2 = await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence", budget_id: b.budget_id });
  const g2 = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g2.job.request_id, q2.request_id);
  assert.equal(Number(g2.job.budget.remaining_usd), 5);
  const l2 = { request_id: g2.job.request_id, lease_token: g2.job.lease_token };
  const h1 = await rpc("drinks_develop_hold", { ...l2, est_usd: 0.3, model: "m" });
  assert.equal(Number(h1.remaining_usd), 4.7);
  assert.equal(Number(h1.request_remaining_usd), 0.2);
  const over = await exec("drinks_develop_hold", { ...l2, est_usd: 0.3, model: "m" });
  assert.match(over.error!.message, /^drinks:request_cap_exceeded:/);
  const s1 = await rpc("drinks_develop_settle", { hold_id: h1.hold_id, outcome: "settled", actual_usd: 0.12 });
  assert.equal(Number(s1.spent_usd), 0.12);
  assert.equal(Number(s1.remaining_usd), 4.88);
  assert.equal(Number((await row("select cost_usd from drink_develop_requests where id = $1", [l2.request_id])).cost_usd), 0.12);
  await rpcFails("drinks_develop_settle", { hold_id: h1.hold_id, outcome: "released" }, "invalid_state");
  await assert.rejects(db.query("update drink_develop_holds set actual_usd = 0 where id = $1", [h1.hold_id]), /drinks:immutable:/);
  // 해제는 금액을 돌려준다 / 요청 상한은 확정 실제 금액으로 센다
  const h2 = await rpc("drinks_develop_hold", { ...l2, est_usd: 0.3, model: "m" });
  const s2 = await rpc("drinks_develop_settle", { hold_id: h2.hold_id, outcome: "released", note: "실패" });
  assert.equal(Number(s2.remaining_usd), 4.88);
  await rpcFails("drinks_develop_hold", { ...l2, est_usd: 0, model: "m" }, "invalid_input");
  // 호출 횟수 상한 20
  for (let i = 0; i < 18; i++) {
    const h = await rpc("drinks_develop_hold", { ...l2, est_usd: 0.001, model: "m" });
    await rpc("drinks_develop_settle", { hold_id: h.hold_id, outcome: "released" });
  }
  await rpcFails("drinks_develop_hold", { ...l2, est_usd: 0.001, model: "m" }, "hold_limit");
  // 운영자가 취소하면 다음 호출부터 거부한다
  await rpc("drinks_cancel_develop", { request_id: l2.request_id });
  assert.equal((await rpc("drinks_heartbeat_develop", l2)).cancel_requested, true);
  await rpcFails("drinks_develop_hold", { ...l2, est_usd: 0.001, model: "m" }, "canceled");
  await rpc("drinks_finish_develop", { ...l2, outcome: "failed", error_code: "canceled" });
  assert.equal((await row("select status from drink_develop_requests where id = $1", [l2.request_id])).status, "canceled");
});

test("결재 금액이 요청 상한보다 작으면 결재 금액이 상한이다 / 중간에 결재를 닫으면 다음 호출부터 거부", async () => {
  const topic = await researchingTopic();
  const b = await budget(0.2);
  await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence", budget_id: b.budget_id });
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const h = await rpc("drinks_develop_hold", { ...l, est_usd: 0.15, model: "m" });
  const over = await exec("drinks_develop_hold", { ...l, est_usd: 0.1, model: "m" });
  assert.match(over.error!.message, /^drinks:budget_exceeded:/);
  assert.equal(JSON.parse(over.error!.details!).cap_usd, 0.2);
  await rpc("drinks_develop_settle", { hold_id: h.hold_id, outcome: "released" });
  await rpc("drinks_close_develop_budget", { budget_id: b.budget_id, reason: "중간에 닫음" });
  await rpcFails("drinks_develop_hold", { ...l, est_usd: 0.01, model: "m" }, "approval_closed");
  await rpc("drinks_finish_develop", { ...l, outcome: "failed", error_code: "approval_closed" });
});

test("근거 초안: 출처를 붙이고 저장하면 초안만 생긴다(승인·제출 없음) — DB 가 인용 일치를 다시 재고, 수동 등록 출처도 읽힌다", async () => {
  const topic = await researchingTopic();
  // 운영자가 먼저 손으로 붙인 출처(붙여넣은 글)
  const manual = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const b = await budget(1);
  const q = await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence", budget_id: b.budget_id });
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.request_id, q.request_id);
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const srcs = await rpc("drinks_develop_sources", { ...l, terms: ["whisky", "물"] });
  const mine = srcs.find((s: Any) => s.snapshot_id === manual.snapshot_id);
  assert.ok(mine, "수동 등록 출처가 후보에 나온다");
  assert.equal(mine.linked, true);
  assert.equal(mine.body_text, BODY);
  const link = await rpc("drinks_develop_link_snapshot", { ...l, snapshot_id: manual.snapshot_id });
  assert.equal(link.role, "evidence");
  // 새 출처 붙이기(워커가 가져온 글)
  const fresh = await rpc("drinks_develop_add_source", { ...l, source: { url: `https://example.org/${uniq()}`, body_text: BODY + " More.", rights_status: "quote_ok", source_kind: "expert" } });
  assert.equal(fresh.role, "evidence");
  const save = await rpc("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [claim("c1", manual.snapshot_id, QUOTE1),
    claim("c2", manual.snapshot_id, QUOTE2), claim("c3", fresh.snapshot_id, "this phrase is not in the source at all")] },
    brief: { audience_question: "왜 물을 넣나", selected_claim_ids: ["c1", "c2", "c3"], proposed_formats: ["video"], required_claims: { video: ["c1", "c2"] } } });
  assert.deepEqual(save.quote_check, { matched: 2, unmatched: 1, not_checked: 0 });
  const rv = await reviewRow(save.review_id);
  assert.equal(rv.status, "draft", "승인이 아니라 초안");
  const blockers: string[] = rv.readiness.blockers;
  assert.ok(blockers.includes("claim_quote_unmatched:c3"), JSON.stringify(blockers));
  assert.ok(blockers.includes("brief_takeaway_missing"));
  assert.ok(blockers.includes("claim_support_not_reviewed:c1"), "의미 검토는 운영자가 한다");
  assert.ok(!blockers.includes("scores_incomplete"), "소재의 잠정 점수를 그대로 쓴다");
  // 결과 없이는 성공으로 못 닫는다 / 닫고 나면 같은 소재에 초안이 있어 새 근거 요청은 거절
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: { dropped: 1 } });
  const fin = await row("select * from drink_develop_requests where id = $1", [l.request_id]);
  assert.equal(fin.status, "succeeded");
  assert.equal(fin.result_review_id, save.review_id);
  assert.equal(fin.lease_token, null);
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "evidence" }, "draft_exists");
  // 임대를 잃은 워커는 쓰지 못한다
  await rpcFails("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [] } }, "lease_lost");
});

test("제작안 초안: 승인된 근거의 핵심 주장만 쓴다 · 초안으로만 저장 · 성공은 저장된 결과가 있어야", async () => {
  const topic = await researchingTopic();
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const brief = { audience_question: "왜 물을 넣나", core_takeaway: "물을 조금 타면 향이 산다", selected_claim_ids: ["c1"],
    proposed_formats: ["video"], required_claims: { video: ["c1"] } };
  const pack = { claims: [{ ...claim("c1", s.snapshot_id, QUOTE1), support_review: "supported" },
    { ...claim("c2", s.snapshot_id, QUOTE2), support_review: "supported" }] };
  const sv = await ok("save_review", { topic_id: topic, expected_topic_version: await tv(topic), scores: SCORES, brief, evidence_pack: pack });
  const b = await budget(1);
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id }, "review_not_approved");
  let r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await reviewRow(sv.review_id);
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id }, "format_not_selected");
  await ok("select", { topic_id: topic, expected_version: await tv(topic), review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["video"], editorial_week: "2026-11-02" });
  const q = await rpc("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id });
  assert.equal(q.review_id, r.id);
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.kind, "plan");
  assert.deepEqual(g.job.review.core_claim_ids, ["c1"]);
  assert.deepEqual(g.job.review.claims.map((c: Any) => c.claim_id), ["c1"], "핵심 주장만 건넨다");
  assert.equal(g.job.review.sources.length, 1);
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  await rpcFails("drinks_finish_develop", { ...l, outcome: "succeeded" }, "invalid_state");
  // 핵심 주장이 아닌 c2 를 쓴 제작안은 DB 가 거절
  await rpcFails("drinks_develop_save_plan", { ...l, plan_json: { scenes: [{ narration: "왜 물을 넣을까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A glass" },
    { narration: "향이 살아요", claim_ids: ["c2"], visual_role: "reality", visual_prompt: "A glass" }] } }, "plan_claim_not_core");
  const pl = await rpc("drinks_develop_save_plan", { ...l, plan_json: { scenes: [{ narration: "왜 물을 넣을까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A glass" },
    { narration: "애호가들은 물을 몇 방울 넣어요.", claim_ids: ["c1"], visual_role: "reality", visual_prompt: "A glass",
      answers_ko: "무슨 일이", staging_ko: "물방울이 떨어진다" }], notes: "시청자 결론: 물을 조금 넣는 습관이 있다(c1)" } });
  const plan = await row("select * from drink_plan_revisions where id = $1", [pl.revision_id]);
  assert.equal(plan.plan_status, "draft", "제출·승인하지 않는다");
  assert.equal(plan.plan_json.scenes[1].answers_ko, "무슨 일이");
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: { source_table: [{ scene: 2, claim_ids: ["c1"], quotes: [QUOTE1] }] } });
  const fin = await row("select * from drink_develop_requests where id = $1", [l.request_id]);
  assert.equal(fin.result_plan_revision_id, pl.revision_id);
  assert.equal(fin.result.source_table[0].scene, 2);
  // 제작안 초안이 있으면 다시 요청할 수 없다
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id }, "draft_exists");
  // 다른 소재의 요청이 끼어들어도 이 요청 결과는 그대로
  assert.equal((await rpc("drinks_develop_status", { topic_id: topic })).requests[0].status, "succeeded");
});

test("임대가 끊긴 요청은 실패로 회수되고, 대기 중 소재 상태가 바뀌면 시작 전에 취소된다", async () => {
  const topic = await researchingTopic();
  await rpc("drinks_request_develop", { topic_id: topic, kind: "evidence" });
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  await db.query("update drink_develop_requests set lease_expires_at = now() - interval '1 minute' where id = $1", [g.job.request_id]);
  const st = await rpc("drinks_develop_status", { topic_id: topic });
  assert.equal(st.requests[0].status, "failed");
  assert.equal(st.requests[0].error_code, "lease_expired");
  await rpcFails("drinks_heartbeat_develop", { request_id: g.job.request_id, lease_token: g.job.lease_token }, "lease_lost");
  // 큐에 있는 사이 소재가 보류로 가면 시작하지 않는다
  const t2 = await researchingTopic();
  await rpc("drinks_request_develop", { topic_id: t2, kind: "evidence" });
  await db.query("update drink_topics set status = 'on_hold', decision_reason = 'x' where id = $1", [t2]);
  const none = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(none.job, null);
  assert.equal((await row("select status, error_code from drink_develop_requests where topic_id = $1", [t2])).error_code, "topic_state_changed");
});

test("워커 함수는 승인·제출·편성 함수를 부르지 않는다(소스 검사)", () => {
  const sql = readFileSync(join(DIR, "0060_drinks_develop.sql"), "utf8");
  for (const forbidden of ["drinks_review_action", "drinks_plan_action", "drinks_select(", "drinks_topic_action"]) {
    assert.ok(!sql.includes(forbidden), `0060 은 ${forbidden} 를 부르면 안 된다`);
  }
});
