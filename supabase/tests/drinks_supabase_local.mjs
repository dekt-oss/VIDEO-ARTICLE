// 주류 공장 실제 Supabase(로컬 스택) 검증 — 실제 PostgREST·RLS·역할을 거친다. CI 에 묶지 않았다.
//
// ★ 상태(2026-10-22): 준비만 하고 **한 번도 실행하지 않았다**(Docker 미설치 — 운영자 결정). 0050 을 운영에 적용하기 전에 돌린다.
//
// 이 스크립트가 보는 것(PGlite·순수 Postgres 로는 못 보던 것):
//   · Supabase 기본 권한(anon/authenticated 에 기본 GRANT)이 있는 환경에서 0050 의 회수가 실제로 먹는가
//   · 실제 PostgREST: anon 키로 표·판정 뷰·rpc 모두 거부되는가, service_role 키로 rpc·count·range 가 되는가
//   · 라우트와 같은 코드(web/lib/drinks/actions.ts::runDrinksAction)가 실제 PostgREST 오류 모양을 올바른 HTTP 로 바꾸는가
//
// ★ 로컬 주소에만 돈다(운영·원격 Supabase 금지). 키는 `supabase status` 가 보여주는 **로컬 개발용** 키다.
// 실행:
//   SUPABASE_URL=http://127.0.0.1:54321 SUPABASE_ANON_KEY=<로컬 anon> SUPABASE_SERVICE_KEY=<로컬 service_role> \
//   node supabase/tests/drinks_supabase_local.mjs
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const url = process.env.SUPABASE_URL ?? "";
const anonKey = process.env.SUPABASE_ANON_KEY ?? "";
const serviceKey = process.env.SUPABASE_SERVICE_KEY ?? "";
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url)) throw new Error("로컬 Supabase 주소(http://127.0.0.1:포트)에만 돌립니다");
if (!anonKey || !serviceKey) throw new Error("SUPABASE_ANON_KEY·SUPABASE_SERVICE_KEY(로컬 키)가 필요합니다");

const req = createRequire(join(ROOT, "web", "package.json"));
const { createClient } = await import(pathToFileURL(req.resolve("@supabase/supabase-js")).href);
const { runDrinksAction } = await import(pathToFileURL(join(ROOT, "web/lib/drinks/actions.ts")).href);

const opts = { auth: { persistSession: false, autoRefreshToken: false } };
const anon = createClient(url, anonKey, opts);
const admin = createClient(url, serviceKey, opts);
const act = (action, payload) => runDrinksAction((fn, p) => admin.rpc(fn, { p }), { action, payload });
let failed = 0;
const check = async (name, fn) => {
  try { await fn(); console.log(`✔ ${name}`); } catch (e) { failed += 1; console.log(`✖ ${name}: ${e.message}`); }
};
const ok = async (a, p) => { const r = await act(a, p); assert.equal(r.status, 200, `${a}: ${JSON.stringify(r.body)}`); return r.body.result; };
const one = async (table, col, val) => {
  const r = await admin.from(table).select("*").eq(col, val).maybeSingle();
  if (r.error) throw new Error(r.error.message);
  return r.data;
};
const tv = async (id) => (await one("drink_topics", "id", id)).version;
const rv = (id) => one("drink_topic_reviews", "id", id);
const pv = (id) => one("drink_plan_revisions", "id", id);

await check("anon: 표·판정 뷰 읽기와 rpc 실행이 모두 거부된다(데이터 0행 반환이 아니라 오류)", async () => {
  for (const t of ["drink_topics", "drink_source_snapshots", "drink_snapshot_attestations", "drink_topic_reviews",
    "drink_plan_revisions", "drink_workflow_events", "drink_review_validity"]) {
    const r = await anon.from(t).select("*").limit(1);
    assert.ok(r.error, `${t}: anon 에게 오류가 나야 한다 (받은 데이터 ${JSON.stringify(r.data)})`);
  }
  const rpc = await anon.rpc("drinks_create_topic", { p: { title: "x", question: "y", categories: ["sake"], lane: "evergreen" } });
  assert.ok(rpc.error, "anon rpc 는 거부");
  const w = await anon.from("drink_topics").insert({ title: "x", question: "y", categories: ["sake"], lane: "evergreen", dedupe_key: "k" });
  assert.ok(w.error, "anon 직접 쓰기 거부");
});

const SC = { relevance: 4, utility: 4, curiosity: 3, fit_video: 1, fit_carousel: 4, timeliness: 2 };
const BODY = `대음양주는 정미율 50% 이하의 백미를 사용한 것이다. ${Date.now()}`;
const brief = { audience_question: "50%?", core_takeaway: "절반", selected_claim_ids: ["c1"], proposed_formats: ["carousel"],
  required_claims: { carousel: ["c1"] } };
let ctx = {};

await check("service_role: 실제 PostgREST rpc 로 등록 → 근거 → 승인 → 카드만 편성 → 제작안 승인", async () => {
  const t = await ok("create_topic", { title: "실제 Supabase 검증", question: `정미율 ${Date.now()}`, categories: ["sake"], lane: "evergreen" });
  const id = t.topic_id;
  await ok("triage", { topic_id: id, expected_version: await tv(id), scores: SC });
  await ok("topic_action", { topic_id: id, expected_version: await tv(id), action: "start_research" });
  const s = await ok("add_source", { topic_id: id, source: { url: `https://nta.example/${Date.now()}?utm_source=x`, body_text: BODY,
    rights_status: "quote_ok" } });
  const claims = [{ claim_id: "c1", text: "정미율 50% 이하", claim_type: "process", support_review: "supported",
    source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "정미율 50% 이하의 백미" }] }];
  const sv = await ok("save_review", { topic_id: id, expected_topic_version: await tv(id), scores: SC, brief, evidence_pack: { claims } });
  let r = await rv(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await rv(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await rv(sv.review_id);
  const vid = await act("select", { topic_id: id, expected_version: await tv(id), review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["video"], editorial_week: "2026-10-26" });
  assert.equal(vid.status, 422);
  assert.ok(["format_fit_low", "required_claims_missing"].includes(vid.body.code), vid.body.code);
  await ok("select", { topic_id: id, expected_version: await tv(id), review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["carousel"], editorial_week: "2026-10-26" });
  const pl = await ok("save_plan", { topic_id: id, format: "carousel", topic_review_id: r.id,
    plan_json: { pages: [{ role: "cover", heading: "표지", claim_ids: ["c1"] }] } });
  let p = await pv(pl.revision_id);
  const bad = await act("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" });
  assert.equal(bad.status, 422, "표지에만 필수 주장 → 실제 PostgREST 오류가 422 로 변환");
  assert.equal(bad.body.code, "plan_coverage");
  assert.ok(bad.body.detail && Array.isArray(bad.body.detail.missing_required), "오류 detail(JSON)이 PostgREST details 로 전달");
  await ok("save_plan", { topic_id: id, format: "carousel", revision_id: p.id, expected_version: p.version, topic_review_id: r.id,
    plan_json: { pages: [{ role: "cover", heading: "표지" }, { role: "explain", heading: "설명", claim_ids: ["c1"] }] } });
  p = await pv(pl.revision_id);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" });
  p = await pv(pl.revision_id);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "approve" });
  ctx = { id, reviewId: r.id, planId: p.id, snapshotId: s.snapshot_id };
});

await check("오류 변환: 같은 expected_version 두 번째 → 409 version_conflict, 다른 소재의 버전 → 403 ownership", async () => {
  const v = await tv(ctx.id);
  const a = await act("topic_action", { topic_id: ctx.id, expected_version: v, action: "bump_signal" });
  assert.equal(a.status, 200);
  const b = await act("topic_action", { topic_id: ctx.id, expected_version: v, action: "bump_signal" });
  assert.equal(b.status, 409);
  assert.equal(b.body.code, "version_conflict");
  const t2 = await ok("create_topic", { title: "다른 소재", question: `q ${Date.now()}`, categories: ["whisky"], lane: "evergreen" });
  await ok("triage", { topic_id: t2.topic_id, expected_version: await tv(t2.topic_id), scores: SC });
  await ok("topic_action", { topic_id: t2.topic_id, expected_version: await tv(t2.topic_id), action: "start_research" });
  const o = await act("save_plan", { topic_id: t2.topic_id, format: "carousel", topic_review_id: ctx.reviewId, plan_json: { pages: [] } });
  assert.ok([403, 422].includes(o.status), JSON.stringify(o.body));
  const x = await act("render", {});
  assert.equal(x.status, 403);
  assert.equal(x.body.code, "not_in_phase_a");
});

await check("권리 철회(체크박스 없음) → 판정 뷰 '지금 사용 불가'·제작안 차단, 실제 PostgREST 로 count·range 조회", async () => {
  await ok("attest_source", { topic_id: ctx.id, snapshot_id: ctx.snapshotId, kind: "rights_revoked", fields: { rights_status: "restricted" },
    reason: "검증" });
  const v = await admin.from("drink_review_validity").select("*", { count: "exact" }).in("review_id", [ctx.reviewId]).range(0, 0);
  assert.ifError(v.error);
  assert.equal(v.count, 1, "count=exact 가 실제 PostgREST 에서 온다");
  assert.equal(v.data[0].currently_valid, false);
  assert.ok(v.data[0].current_blockers.includes("claim_rights_unconfirmed:c1"));
  const p = await pv(ctx.planId);
  assert.ok(p.blocked_at);
  assert.equal(p.plan_status, "approved", "승인 기록은 보존");
  const t = await one("drink_topics", "id", ctx.id);
  assert.equal(t.status, "researching");
  const ev = await admin.from("drink_workflow_events").select("id", { count: "exact" }).eq("topic_id", ctx.id).range(0, 1);
  assert.ifError(ev.error);
  assert.ok(ev.count > 2 && ev.data.length === 2, "range 로 쪽을 나눠도 전체 건수가 함께 온다");
});

console.log(failed === 0 ? "모두 통과" : `${failed}개 실패`);
process.exitCode = failed === 0 ? 0 : 1;
