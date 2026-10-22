// 주류 공장 실제 동시성 검증 — **실제 Postgres 서버 전용**(PGlite 는 연결이 하나라 못 한다). CI 에 묶지 않았다.
//
// 두 개의 독립 연결로 같은 행을 동시에 건드려, 잠금(for update)과 버전 비교가 "늦게 온 쪽"을 막는지 본다.
//   ① 검토 요청 vs 초안 수정   ② 같은 버전 승인 두 번   ③ 근거 철회 vs 제작안 승인   ④ 새 제작안 동시 생성 두 번
// 같은 expected_version 을 순차로 두 번 보내는 web/lib/drinks/drinks.db.test.ts 와는 다른 검사다.
//
// ★ 빈 데이터베이스에만 돌린다 — 스크립트가 역할을 만들고 0050 을 적용한다. 운영·공유 DB 에 돌리지 말 것.
// 실행(예: 로컬 Postgres 17):
//   npm i --prefix <임시폴더> pg@8.13.1
//   DATABASE_URL=postgres://postgres:postgres@127.0.0.1:54329/drinks \
//   DRINKS_PG_MODULE=<임시폴더>/node_modules/pg/lib/index.js node supabase/tests/drinks_concurrency.pg.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const url = process.env.DATABASE_URL;
if (!url) throw new Error("DATABASE_URL 이 필요합니다(빈 테스트 DB)");
if (/supabase\.co|pooler\.supabase/.test(url)) throw new Error("원격 Supabase 주소에는 돌리지 않습니다");
const pgMod = process.env.DRINKS_PG_MODULE ? pathToFileURL(process.env.DRINKS_PG_MODULE).href : "pg";
const { default: pg } = await import(pgMod);

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const admin = new pg.Client({ connectionString: url });
await admin.connect();
const exists = await admin.query("select to_regclass('public.drink_topics') as t");
if (exists.rows[0].t) throw new Error("drink_topics 가 이미 있습니다 — 빈 DB 에만 돌리세요");
await admin.query(`do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$; grant usage on schema public to anon, authenticated, service_role;`);
await admin.query(readFileSync(join(ROOT, "supabase/migrations/0050_drinks_factory_phase_a.sql"), "utf8"));

async function conn() {
  const c = new pg.Client({ connectionString: url });
  await c.connect();
  await c.query("set role service_role");
  await c.query("set lock_timeout = '10s'");
  return c;
}
const A = await conn();
const B = await conn();
const call = async (c, fn, p) => (await c.query(`select ${fn}($1::jsonb) as r`, [JSON.stringify(p)])).rows[0].r;
const codeOf = (e) => (/^drinks:([a-z_]+):/.exec(e?.message ?? "")?.[1]) ?? e?.code ?? String(e);
const one = async (sql, params = []) => (await admin.query(sql, params)).rows[0];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** A 가 트랜잭션 안에서 fnA 를 끝내고 잠금을 쥔 채로, B 가 fnB 를 시작한다. B 가 기다리는지 보고 A 를 커밋한다. */
async function race(fnA, fnB) {
  await A.query("begin");
  const ra = await fnA(A);
  let settled = false;
  const pb = fnB(B).then((v) => ({ ok: true, v }), (e) => ({ ok: false, e })).finally(() => { settled = true; });
  await sleep(400);
  const blocked = !settled;
  await A.query("commit");
  return { ra, rb: await pb, blocked };
}

const BODY = "준마이 다이긴조는 정미율 50% 이하의 쌀을 사용한다.";
const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const brief = { audience_question: "왜 비쌀까", core_takeaway: "쌀을 깎는다", selected_claim_ids: ["c1"],
  proposed_formats: ["carousel"], required_claims: { carousel: ["c1"] } };
let n = 0;
async function topicWithDraft() {
  const t = await call(A, "drinks_create_topic", { title: "t", question: `q${n++}`, categories: ["sake"], lane: "evergreen" });
  const id = t.topic_id;
  const v = async () => (await one("select version from drink_topics where id=$1", [id])).version;
  await call(A, "drinks_triage", { topic_id: id, expected_version: await v(), scores: SCORES });
  await call(A, "drinks_topic_action", { topic_id: id, expected_version: await v(), action: "start_research" });
  const s = await call(A, "drinks_add_source", { topic_id: id, source: { body_text: BODY + n, rights_status: "quote_ok" } });
  const claims = [{ claim_id: "c1", text: "정미율 50%", claim_type: "process", support_review: "supported",
    source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "정미율 50% 이하의 쌀을 사용한다" }] }];
  const r = await call(A, "drinks_save_review", { topic_id: id, expected_topic_version: await v(), scores: SCORES, brief,
    evidence_pack: { claims } });
  return { id, reviewId: r.review_id, v };
}
const rv = (id) => one("select * from drink_topic_reviews where id=$1", [id]);
const results = [];
const check = (name, fn) => results.push(fn().then(() => console.log(`✔ ${name}`), (e) => { console.log(`✖ ${name}: ${e.message}`); process.exitCode = 1; }));

// ① 검토 요청(A, 잠금 보유) vs 같은 버전의 초안 수정(B)
await (async () => {
  const { reviewId } = await topicWithDraft();
  const before = await rv(reviewId);
  const { rb, blocked } = await race(
    (c) => call(c, "drinks_review_action", { review_id: reviewId, expected_version: before.version, action: "submit" }),
    (c) => call(c, "drinks_save_review", { topic_id: before.topic_id, review_id: reviewId, expected_version: before.version,
      brief: { ...brief, exclusions: "늦게 온 수정" } }));
  const after = await rv(reviewId);
  await check("① 검토 요청 vs 초안 수정: B 가 잠금을 기다렸고, 늦게 온 수정은 거부", async () => {
    assert.equal(blocked, true, "B 가 A 의 커밋을 기다려야 한다");
    assert.equal(rb.ok, false);
    assert.ok(["version_conflict", "immutable"].includes(codeOf(rb.e)), codeOf(rb.e));
    assert.equal(after.status, "in_review");
    assert.equal(after.brief.exclusions, null, "검토에 올린 본문이 그대로");
  });
})();

// ② 같은 버전 승인 두 번(두 연결)
await (async () => {
  const { reviewId } = await topicWithDraft();
  let r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "submit" });
  r0 = await rv(reviewId);
  const { rb, blocked } = await race(
    (c) => call(c, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "approve" }),
    (c) => call(c, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "approve" }));
  const after = await rv(reviewId);
  await check("② 같은 버전 승인 두 번: 하나만 성공, 승인 해시 불변", async () => {
    assert.equal(blocked, true);
    assert.equal(rb.ok, false);
    assert.equal(codeOf(rb.e), "version_conflict");
    assert.equal(after.status, "approved");
    assert.equal(after.approved_hash, after.input_hash);
    const ev = await one(`select count(*)::int as n from drink_workflow_events where entity_id=$1 and action='review_approve'`, [reviewId]);
    assert.equal(ev.n, 1, "승인 이력도 한 번만");
  });
})();

// ③ 근거 철회(A) vs 제작안 승인(B)
await (async () => {
  const { id, reviewId, v } = await topicWithDraft();
  let r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "submit" });
  r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "approve" });
  r0 = await rv(reviewId);
  await call(A, "drinks_select", { topic_id: id, expected_version: await v(), review_id: reviewId, review_input_hash: r0.approved_hash,
    formats: ["carousel"], editorial_week: "2026-10-26" });
  const plan = await call(A, "drinks_save_plan", { topic_id: id, format: "carousel", topic_review_id: reviewId,
    plan_json: { pages: [{ role: "cover", heading: "표지" }, { role: "explain", heading: "정미율", claim_ids: ["c1"] }] } });
  let pv = await one("select * from drink_plan_revisions where id=$1", [plan.revision_id]);
  await call(A, "drinks_plan_action", { revision_id: pv.id, expected_version: pv.version, action: "submit" });
  pv = await one("select * from drink_plan_revisions where id=$1", [plan.revision_id]);
  const { rb, blocked } = await race(
    (c) => call(c, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "revoke", reason: "오류" }),
    (c) => call(c, "drinks_plan_action", { revision_id: pv.id, expected_version: pv.version, action: "approve" }));
  const after = await one("select * from drink_plan_revisions where id=$1", [plan.revision_id]);
  await check("③ 철회 vs 제작안 승인: 철회가 먼저 잡으면 제작안은 승인되지 않고 차단", async () => {
    assert.equal(blocked, true);
    assert.equal(rb.ok, false);
    assert.ok(["version_conflict", "plan_blocked", "review_not_approved", "format_not_selected"].includes(codeOf(rb.e)), codeOf(rb.e));
    assert.equal(after.plan_status, "in_review");
    assert.ok(after.blocked_at);
  });
})();

// ④ 새 제작안 동시 생성 두 번 → 하나만
await (async () => {
  const { id, reviewId, v } = await topicWithDraft();
  let r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "submit" });
  r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "approve" });
  r0 = await rv(reviewId);
  await call(A, "drinks_select", { topic_id: id, expected_version: await v(), review_id: reviewId, review_input_hash: r0.approved_hash,
    formats: ["carousel"], editorial_week: "2026-10-26" });
  const p = { topic_id: id, format: "carousel", topic_review_id: reviewId, plan_json: { pages: [{ role: "cover", heading: "x" }] } };
  const { rb, blocked } = await race((c) => call(c, "drinks_save_plan", p), (c) => call(c, "drinks_save_plan", p));
  const cnt = await one("select count(*)::int as n from drink_plan_revisions where topic_id=$1", [id]);
  await check("④ 새 제작안 동시 생성 두 번: 하나만 생기고 나머지는 거부", async () => {
    assert.equal(blocked, true);
    assert.equal(rb.ok, false);
    assert.ok(["draft_exists", "version_conflict", "23505"].includes(codeOf(rb.e)), codeOf(rb.e));
    assert.equal(cnt.n, 1);
  });
})();

// ⑤ 공유 출처: 소재1 권리 철회(+영향 승인 철회) vs 소재2 정정 기록 — 교착(40P01) 없이 B 가 기다렸다 성공
await (async () => {
  const url = `https://shared.example/${Date.now()}`;
  const T1 = await topicWithDraft();
  const T2 = await topicWithDraft();
  const s1 = await call(A, "drinks_add_source", { topic_id: T1.id, source: { canonical_url: url, body_text: BODY } });
  await call(A, "drinks_add_source", { topic_id: T2.id, source: { canonical_url: url, body_text: BODY } });
  const { rb, blocked } = await race(
    (c) => call(c, "drinks_attest_source", { topic_id: T1.id, snapshot_id: s1.snapshot_id, kind: "rights_revoked",
      fields: { rights_status: "restricted" }, reason: "철회", revoke_affected: true }),
    (c) => call(c, "drinks_attest_source", { topic_id: T2.id, snapshot_id: s1.snapshot_id, kind: "correction",
      fields: { publisher: "정정" }, reason: "오기" }));
  const n = await one("select count(*)::int as n from drink_snapshot_attestations where snapshot_id=$1", [s1.snapshot_id]);
  await check("⑤ 공유 출처 동시 기록: 교착 없이 순서대로 둘 다 기록", async () => {
    assert.equal(blocked, true, "B 는 같은 잠금 범위를 기다린다");
    assert.equal(rb.ok, true, rb.ok ? "" : codeOf(rb.e));
    assert.equal(n.n, 2);
  });
})();

// ⑥ 권리 철회(체크박스 없이) vs 제작안 승인 — 어느 쪽이 먼저든 "지금 쓸 수 없는 제작안"이 유효하게 남지 않는다
async function inReviewPlan() {
  const { id, reviewId, v } = await topicWithDraft();
  let r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "submit" });
  r0 = await rv(reviewId);
  await call(A, "drinks_review_action", { review_id: reviewId, expected_version: r0.version, action: "approve" });
  r0 = await rv(reviewId);
  await call(A, "drinks_select", { topic_id: id, expected_version: await v(), review_id: reviewId, review_input_hash: r0.approved_hash,
    formats: ["carousel"], editorial_week: "2026-10-26" });
  const plan = await call(A, "drinks_save_plan", { topic_id: id, format: "carousel", topic_review_id: reviewId,
    plan_json: { pages: [{ role: "cover", heading: "표지" }, { role: "explain", heading: "정미율", claim_ids: ["c1"] }] } });
  let pv = await one("select * from drink_plan_revisions where id=$1", [plan.revision_id]);
  await call(A, "drinks_plan_action", { revision_id: pv.id, expected_version: pv.version, action: "submit" });
  pv = await one("select * from drink_plan_revisions where id=$1", [plan.revision_id]);
  const snap = (await one(`select (evidence_pack->'claims'->0->'source_refs'->0->>'snapshot_id')::uuid as s from drink_topic_reviews where id=$1`,
    [reviewId])).s;
  return { id, reviewId, pv, snap };
}
await (async () => {
  // 순서 1: 철회가 먼저 잠금을 잡는다
  const x = await inReviewPlan();
  const { rb, blocked } = await race(
    (c) => call(c, "drinks_attest_source", { topic_id: x.id, snapshot_id: x.snap, kind: "rights_revoked",
      fields: { rights_status: "restricted" }, reason: "철회", revoke_affected: false }),
    (c) => call(c, "drinks_plan_action", { revision_id: x.pv.id, expected_version: x.pv.version, action: "approve" }));
  const after = await one("select * from drink_plan_revisions where id=$1", [x.pv.id]);
  const valid = await one("select currently_valid from drink_review_validity where review_id=$1", [x.reviewId]);
  await check("⑥-1 철회 먼저: 제작안 승인은 거부되고 차단, 근거는 지금 사용 불가", async () => {
    assert.equal(blocked, true);
    assert.equal(rb.ok, false, "승인이 통과하면 안 된다");
    assert.notEqual(after.plan_status, "approved");
    assert.ok(after.blocked_at);
    assert.equal(valid.currently_valid, false);
  });
  // 순서 2: 제작안 승인이 먼저 잠금을 잡는다 → 승인 뒤 철회가 차단한다
  const y = await inReviewPlan();
  const r2 = await race(
    (c) => call(c, "drinks_plan_action", { revision_id: y.pv.id, expected_version: y.pv.version, action: "approve" }),
    (c) => call(c, "drinks_attest_source", { topic_id: y.id, snapshot_id: y.snap, kind: "rights_revoked",
      fields: { rights_status: "restricted" }, reason: "철회", revoke_affected: false }));
  const after2 = await one("select * from drink_plan_revisions where id=$1", [y.pv.id]);
  await check("⑥-2 승인 먼저: 승인 기록은 남되 곧바로 차단(사용 가능으로 남지 않음)", async () => {
    assert.equal(r2.blocked, true);
    assert.equal(r2.rb.ok, true, r2.rb.ok ? "" : codeOf(r2.rb.e));
    assert.equal(after2.plan_status, "approved");
    assert.ok(after2.blocked_at, "차단돼야 한다");
  });
})();

// ⑦ 같은 출처에 두 연결이 동시에 정정 기록 — 잠금을 먼저 잡은 쪽이 먼저 적용되고, 나중 쪽이 최종 상태가 된다
await (async () => {
  for (const [first, second, expected] of [["quote_ok", "restricted", "restricted"], ["restricted", "quote_ok", "quote_ok"]]) {
    const T = await topicWithDraft();
    const s = await call(A, "drinks_add_source", { topic_id: T.id, source: { canonical_url: `https://order.example/${Date.now()}${first}`,
      body_text: BODY } });
    const kind = (r) => (r === "restricted" ? "rights_revoked" : "rights_confirmed");
    const { rb, blocked } = await race(
      (c) => call(c, "drinks_attest_source", { topic_id: T.id, snapshot_id: s.snapshot_id, kind: kind(first),
        fields: { rights_status: first }, reason: "먼저" }),
      (c) => call(c, "drinks_attest_source", { topic_id: T.id, snapshot_id: s.snapshot_id, kind: kind(second),
        fields: { rights_status: second }, reason: "나중" }));
    const fin = await one("select drinks_snapshot_meta($1) ->> 'rights_status' as r", [s.snapshot_id]);
    const order = (await admin.query("select reason from drink_snapshot_attestations where snapshot_id=$1 order by seq", [s.snapshot_id]))
      .rows.map((x) => x.reason);
    await check(`⑦ 동시 정정 ${first}→${second}: 나중에 잠금을 잡은 기록이 최종(${expected})`, async () => {
      assert.equal(blocked, true);
      assert.equal(rb.ok, true, rb.ok ? "" : codeOf(rb.e));
      assert.deepEqual(order, ["먼저", "나중"]);
      assert.equal(fin.r, expected);
    });
  }
})();

// 권한: anon 은 표·함수 모두 거부
await (async () => {
  const c = new pg.Client({ connectionString: url });
  await c.connect();
  await c.query("set role anon");
  const t = await c.query("select * from drink_topics").then(() => "ok", (e) => e.code);
  const f = await c.query(`select drinks_create_topic('{}'::jsonb)`).then(() => "ok", (e) => e.code);
  await c.end();
  await check("권한: anon 은 표 읽기·함수 실행 모두 거부(42501)", async () => {
    assert.equal(t, "42501");
    assert.equal(f, "42501");
  });
})();

await Promise.all(results);
await Promise.all([A.end(), B.end(), admin.end()]);
