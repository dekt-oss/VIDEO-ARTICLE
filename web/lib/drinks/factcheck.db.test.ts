// AI 사실 확인 자동 표시(2026-11-06, 0075) DB 리허설 — PGlite 위에 00(5x|6x|7x)_drinks_*. 모델·네트워크 호출 0, 비용 0.
// 워커가 실제로 보내는 RPC 내용(tests/fixtures/drinks_factcheck/worker_payloads.json — tests/test_drinks_factcheck.py 가 지금 워커 출력과
// 같은지 대조한다)을 진짜 SQL 에 그대로 다시 보낸다: [이걸로] → 근거 요청 → 출처 추가 → 근거 저장(AI 가 '확인됨' 3건) → 끝내기.
// 보는 것: AI 가 채운 '확인됨'이 저장·검사에서 그대로 통하고, 이어 만들기가 멈추지 않으며(drinks_chain_stop_blockers 비어 있음),
//          AI 가 확인하지 못한 주장만 '직접 확인' 필수 조건으로 남는다. 원출처 묶음·연결 메모가 저장된다. 비용 예상에 사실 확인이 더해진다.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";
import { FACTCHECK_NOTE, AUTO_SOURCE_NOTE, isAutoSupported } from "./factcheck.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIR = join(HERE, "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d|8\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0075_drinks_auto_factcheck.sql"), "0075 가 목록에 있어야 한다");
const FIX = JSON.parse(readFileSync(join(HERE, "../../../tests/fixtures/drinks_factcheck/worker_payloads.json"), "utf8"));
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
const ok = async (action: string, payload: Record<string, unknown>): Promise<Any> => {
  const r = await runDrinksAction(exec, { action, payload });
  assert.equal(r.status, 200, `${action} 실패: ${JSON.stringify(r.body)}`);
  return r.body.result;
};
const rpc = async (fn: string, p: Record<string, unknown>): Promise<Any> => {
  const r = await exec(fn, p);
  if (r.error) throw new Error(r.error.message);
  return r.data;
};
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 2, timeliness: 2 };

test("워커가 보내는 그대로: AI 가 '확인됨'으로 채운 주장은 필수 조건을 통과하고 이어 만들기가 멈추지 않는다", async () => {
  const b = await rpc("drinks_open_develop_budget", { cap_usd: 2, stage: "시험", purpose: "시험", approver_words: "승인한다" });
  const t = await ok("create_topic", { ...FIX.topic, lane: "evergreen" });
  const topic = t.topic_id as string;
  await ok("triage", { topic_id: topic, expected_version: (await row("select version from drink_topics where id = $1", [topic])).version, scores: SCORES });
  await ok("topic_action", { topic_id: topic, expected_version: (await row("select version from drink_topics where id = $1", [topic])).version, action: "start_research" });
  await ok("pick_topic", { topic_id: topic, formats: ["explainer"], editorial_week: "2026-11-04", budget_id: b.budget_id });

  const g = await rpc("drinks_start_develop", { worker_id: "rehearsal" });
  assert.equal(g.job.kind, "evidence");
  const lease = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  // 출처: 워커가 FakeRpc 에서 받은 'new1' 을 진짜 id 로 바꿔 끼운다
  const ids: Record<string, string> = {};
  for (const [i, p] of (FIX.add_source as Any[]).entries()) ids[`new${i + 1}`] = (await rpc("drinks_develop_add_source", { ...lease, ...p })).snapshot_id;
  const snap = await row("select s.*, ts.relation_note, ts.role from drink_source_snapshots s join drink_topic_sources ts on ts.snapshot_id = s.id where s.id = $1", [ids.new1]);
  assert.equal(snap.origin_group, "国税庁", "원출처 묶음이 발행처로 자동 저장된다");
  assert.equal(snap.relation_note, AUTO_SOURCE_NOTE);
  assert.equal(snap.role, "evidence");
  assert.equal(snap.rights_status, "quote_ok");

  const save = JSON.parse(JSON.stringify(FIX.save_evidence).replace(/"new(\d+)"/g, (_m, n) => JSON.stringify(ids[`new${n}`])));
  const saved = await rpc("drinks_develop_save_evidence", { ...lease, ...save });
  assert.equal(saved.quote_check.unmatched, 0, "워커가 대조한 인용은 DB 대조도 통과한다");
  const fin = await rpc("drinks_finish_develop", { ...lease, outcome: "succeeded", result: { factcheck: FIX.factcheck } });
  assert.equal(fin.status, "succeeded");
  const chain = Array.isArray(fin.result.chain) ? fin.result.chain : [fin.result.chain];
  assert.deepEqual(chain.map((c: Any) => [c.format_intent, c.queued]), [["explainer", true]], `이어 만들기가 멈췄다: ${JSON.stringify(chain)}`);

  const stop = (await row("select drinks_chain_stop_blockers($1::uuid) as b", [saved.review_id])).b;
  assert.deepEqual(stop, [], "대본 전 멈춤 조건이 없다");
  const rv = await row("select * from drink_topic_reviews where id = $1", [saved.review_id]);
  const byId = Object.fromEntries(rv.evidence_pack.claims.map((c: Any) => [c.claim_id, c]));
  for (const cid of ["c1", "c2", "c3"]) {
    assert.equal(byId[cid].support_review, "supported", cid);
    assert.equal(byId[cid].limitations, FACTCHECK_NOTE, cid);
    assert.ok(isAutoSupported(byId[cid]), `화면이 ${cid} 를 'AI 확인'으로 알아본다`);
  }
  assert.equal(byId.c4.support_review, "not_reviewed");
  const blockers: string[] = (await row("select drinks_review_blockers($1::uuid) as b", [saved.review_id])).b.blockers;
  const support = blockers.filter((x) => x.startsWith("claim_support_not_reviewed:"));
  // 0076: AI 가 확인하지 못한 c4 는 핵심 주장에서 빠졌다 — 사람 확인 숙제로 남지 않는다(근거 기록에는 그대로 있다)
  assert.deepEqual(support, [], "확인되지 않은 주장은 핵심이 아니라서 필수 조건도 걸지 않는다");
  assert.deepEqual(rv.brief.selected_claim_ids, ["c1", "c2", "c3"]);
  assert.deepEqual(blockers, ["brief_takeaway_missing"], "남는 것은 핵심 메시지 한 줄뿐 — 초안 저장 때 초안의 결론으로 채워진다(0064)");
  assert.ok(!blockers.some((x) => /^claim_(quote_unmatched|rights_unconfirmed|metadata_only|no_source):/.test(x)), blockers.join(","));
});

test("0075: 근거 예상 금액에 AI 사실 확인 1회가 더해진다(모르는 비용을 0 으로 쓰지 않는다)", async () => {
  const est = await rpc("drinks_develop_estimate", { formats: ["explainer"] });
  const ev = est.items.find((i: Any) => i.kind === "evidence");
  assert.ok(ev && ev.known && Number(ev.factcheck_usd) > 0, JSON.stringify(ev));
  const prm = est.params;
  assert.equal(Number(prm.factcheck_max_tokens), 4000);
  // 출처 4곳 추출 상한 + 사실 확인 상한 ≤ 요청 1건 상한
  assert.ok(Number(ev.est_usd) <= Number(est.per_request_cap_usd));
  assert.ok(Number(ev.est_usd) > Number(ev.factcheck_usd));
});
