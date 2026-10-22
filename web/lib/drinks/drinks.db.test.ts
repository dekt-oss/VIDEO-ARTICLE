// 주류 공장 DB 통합 테스트 — PGlite(메모리에서 도는 진짜 Postgres) 위에 0050 을 적용하고
// 라우트와 **같은** 코드 경로(./actions.ts::runDrinksAction)를 태운다. CI: `node --test lib/drinks/*.test.ts`.
//
// ★ 범위: 트리거·복합 FK·부분 고유 인덱스·plpgsql·권한(GRANT/REVOKE). PostgREST(Supabase rpc)는 빠진다.
// ★ PGlite 는 연결이 하나라 "진짜 동시" 트랜잭션을 못 만든다. 여기서는 같은 expected_version 을 두 번 보내는
//   순차 검사만 한다. 두 연결 경합은 실제 Postgres 전용 supabase/tests/drinks_concurrency.pg.mjs 가 맡는다.
// ★ 권한은 하네스가 따로 주지 않는다 — 역할만 만들고 GRANT 는 마이그레이션이 한 것만 쓴다.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction, PHASE_A_EXCLUDED } from "./actions.ts";
import { planCoverage, weightedScore } from "./model.ts";

// A단계 동작이 B단계 마이그레이션(0051) 위에서도 그대로인지 함께 본다 — 운영에는 둘이 순서대로 적용된다.
const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql"]
  .map((f) => join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations", f));

const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(m, "utf8"));

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
type Any = any;
const ok = async (action: string, payload: Record<string, unknown>): Promise<Any> => {
  const r = await act(action, payload);
  assert.equal(r.status, 200, `${action} 실패: ${JSON.stringify(r.body)}`);
  return r.body.result;
};
const fails = async (action: string, payload: Record<string, unknown>, code: string, status?: number): Promise<Any> => {
  const r = await act(action, payload);
  assert.notEqual(r.status, 200, `${action} 가 통과하면 안 된다`);
  assert.equal(r.body.code, code, JSON.stringify(r.body));
  if (status) assert.equal(r.status, status);
  return r.body;
};
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const topicVersion = async (id: string) => (await row("select version from drink_topics where id = $1", [id])).version;
const topicRow = async (id: string) => row("select * from drink_topics where id = $1", [id]);
const reviewRow = async (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = async (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 1, fit_carousel: 4, timeliness: 2 };
const BODY = "준마이 다이긴조는 정미율 50% 이하의 쌀을 사용한다. 양조 알코올을 첨가하지 않는다.";
const QUOTE = "정미율 50% 이하의 쌀을 사용한다";
const QUOTE2 = "양조 알코올을 첨가하지 않는다";
const brief = {
  audience_question: "다이긴조는 왜 비쌀까?", core_takeaway: "쌀을 반 이상 깎는다", selected_claim_ids: ["c1", "c2"],
  proposed_formats: ["carousel", "video"], required_claims: { carousel: ["c1", "c2"], video: ["c1"] },
};
const claims = (sid: string, over: Record<string, unknown> = {}) => [
  { claim_id: "c1", text: "다이긴조는 정미율 50% 이하", claim_type: "process",
    source_refs: [{ snapshot_id: sid, original_quote: QUOTE, locator: "1문단" }], support_review: "supported", ...over },
  { claim_id: "c2", text: "양조 알코올 무첨가", claim_type: "product_fact",
    source_refs: [{ snapshot_id: sid, original_quote: QUOTE2 }], support_review: "supported" },
];
const uniq = () => Math.random().toString(36).slice(2);

async function newTopic(extra: Record<string, unknown> = {}): Promise<string> {
  const r = await ok("create_topic", {
    title: "다이긴조의 정미율", question: "다이긴조는 쌀을 얼마나 깎을까?", categories: ["sake"],
    lane: "evergreen", target_subject: "다이긴조", angle: `정미율-${uniq()}`, ...extra,
  });
  return r.topic_id;
}
async function toResearching(id: string) {
  await ok("triage", { topic_id: id, expected_version: await topicVersion(id), scores: SCORES });
  await ok("topic_action", { topic_id: id, expected_version: await topicVersion(id), action: "start_research" });
}
async function submitApprove(reviewId: string) {
  let rv = await reviewRow(reviewId);
  await ok("review_action", { review_id: rv.id, expected_version: rv.version, action: "submit" });
  rv = await reviewRow(reviewId);
  return ok("review_action", { review_id: rv.id, expected_version: rv.version, action: "approve" });
}
async function approvedTopic(opts: { url?: string; rights?: string; scores?: Record<string, number> } = {}) {
  const id = await newTopic();
  await toResearching(id);
  const src = await ok("add_source", { topic_id: id, source: {
    url: opts.url ?? `https://www.nta.go.jp/sake/${uniq()}`, body_text: BODY, rights_status: opts.rights ?? "summary_only",
    role: "evidence" } });
  const saved = await ok("save_review", { topic_id: id, expected_topic_version: await topicVersion(id),
    scores: opts.scores ?? SCORES, evidence_pack: { claims: claims(src.snapshot_id) }, brief });
  await submitApprove(saved.review_id);
  return { id, reviewId: saved.review_id as string, snapshotId: src.snapshot_id as string };
}
async function select(id: string, reviewId: string, formats: string[], extra: Record<string, unknown> = {}) {
  const rv = await reviewRow(reviewId);
  return act("select", { topic_id: id, expected_version: await topicVersion(id), review_id: reviewId,
    review_input_hash: rv.approved_hash, formats, editorial_week: "2026-10-28", ...extra });
}
const cardPlan = { pages: [
  { position: 1, role: "cover", heading: "다이긴조 = 쌀 50%" },
  { position: 2, role: "explain", heading: "정미율", body: "쌀을 깎은 비율", claim_ids: ["c1"] },
  { position: 3, role: "checklist", heading: "라벨 체크", claim_ids: ["c2"] },
  { position: 4, role: "source", heading: "출처", body: "일본 국세청" }] };
const videoPlan = { scenes: [
  { narration: "다이긴조, 왜 비쌀까요?", content_kind: "transition" },
  { narration: "쌀을 반이나 깎아요", visual_role: "reality", claim_ids: ["c1"], timing_sec: 4 }] };

async function approvePlan(revisionId: string) {
  let pv = await planRow(revisionId);
  await ok("plan_action", { revision_id: pv.id, expected_version: pv.version, action: "submit" });
  pv = await planRow(revisionId);
  return ok("plan_action", { revision_id: pv.id, expected_version: pv.version, action: "approve" });
}

// ─────────────────────────────────────────────────────────────

test("권한: anon·authenticated 차단, service_role 은 마이그레이션이 준 권한만으로 동작", async () => {
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    await assert.rejects(db.query("select * from drink_topics"), /permission denied/);
    await assert.rejects(db.query("select * from drink_snapshot_attestations"), /permission denied/);
    await assert.rejects(db.query(`select drinks_create_topic('{}'::jsonb)`), /permission denied/);
    await db.exec("reset role");
  }
  const priv = await row(`select has_function_privilege('service_role', 'drinks_select(jsonb)', 'EXECUTE') as s,
    has_function_privilege('anon', 'drinks_select(jsonb)', 'EXECUTE') as a,
    has_table_privilege('service_role', 'drink_topics', 'DELETE') as d`);
  assert.deepEqual(priv, { s: true, a: false, d: false });
  await newTopic(); // service_role 로 실제 쓰기가 된다(하네스가 GRANT 를 따로 주지 않았다)
});

test("질문만 등록 → 재조회 / 같은 질문은 병합 제안 후 확인해야 등록", async () => {
  const p = { title: "위스키 숙성 연수", question: "12년은 어느 원액 기준일까?", categories: ["whisky"],
    lane: "reader_question", target_subject: "스카치", angle: "숙성 표기" };
  const first = await ok("create_topic", p);
  const t = await topicRow(first.topic_id);
  assert.equal(t.status, "inbox");
  const dup = await fails("create_topic", { ...p, question: "12년은 어느 원액 기준일까 ?" }, "duplicate_suggested", 409);
  assert.equal(dup.detail[0].id, first.topic_id);
  await ok("create_topic", { ...p, confirm_not_duplicate: true });
});

test("S03·정책②: URL만=metadata_only / 같은 URL·본문 재사용 / 본문 변경=새 버전 / 같은 본문 다른 URL=후보만", async () => {
  const id = await newTopic();
  const url = `https://example.com/news/${uniq()}?utm_source=x&id=7#top`;
  const a = await ok("add_source", { topic_id: id, source: { url, role: "discovery" } });
  assert.equal(a.depth, "metadata_only");
  const again = await ok("add_source", { topic_id: id, source: { url } });
  assert.equal(again.snapshot_id, a.snapshot_id);
  assert.equal(again.dedup, "same_url_same_body");
  const body = `보도자료 원문 ${uniq()}`;
  const b1 = await ok("add_source", { topic_id: id, source: { url, body_text: body } });
  assert.equal(b1.dedup, "changed_version");
  const b3 = await ok("add_source", { topic_id: id, source: { url, body_text: body + " (정정)" } });
  assert.equal((await row("select supersedes_id from drink_source_snapshots where id=$1", [b3.snapshot_id])).supersedes_id, b1.snapshot_id);

  const copies = [];
  for (const host of ["a.kr", "b.kr", "c.kr"]) {
    copies.push(await ok("add_source", { topic_id: id, source: { url: `https://${host}/${uniq()}`, body_text: body } }));
  }
  assert.ok(copies.every((c) => c.dedup === "new"), "다른 URL 은 새 스냅샷");
  assert.ok(copies[2].same_body_candidates.length >= 3, "같은 본문 후보로 알린다");
  const nulls = await row(`select count(*) filter (where origin_group is null) as n from drink_source_snapshots where id = any($1)`,
    [[b1.snapshot_id, ...copies.map((c) => c.snapshot_id)]]);
  assert.equal(Number(nulls.n), 4, "같은 본문이라도 원출처를 자동으로 묶지 않는다");
  const merged = await ok("set_origin_group", { topic_id: id, snapshot_ids: [b1.snapshot_id, ...copies.map((c) => c.snapshot_id)],
    origin_group: "보도자료-A", reason: "같은 보도자료 전재 확인" });
  assert.equal(merged.snapshot_ids.length, 4);
  await assert.rejects(db.query("update drink_source_snapshots set body_text = 'x' where id = $1", [b1.snapshot_id]), /immutable/);
  await fails("add_source", { topic_id: id, source: { url: "http://127.0.0.1/admin" } }, "invalid_input", 400);
});

test("정책②: 공유 스냅샷 묶음 변경은 다른 소재에 영향 범위·이력을 남기고, 연결 안 된 출처는 묶지 못한다", async () => {
  const url = `https://shared.example/${uniq()}`;
  const A = await newTopic(); const B = await newTopic();
  const sa = await ok("add_source", { topic_id: A, source: { url, body_text: BODY } });
  await ok("add_source", { topic_id: B, source: { url, body_text: BODY } });
  const res = await ok("set_origin_group", { topic_id: A, snapshot_id: sa.snapshot_id, origin_group: "NTA-표시기준" });
  assert.deepEqual(res.affected_topics.map((t: Any) => t.id), [B]);
  const ev = await row(`select count(*) as n from drink_workflow_events where topic_id = $1 and action = 'origin_group_set_elsewhere'`, [B]);
  assert.equal(Number(ev.n), 1);
  const C = await newTopic();
  await fails("set_origin_group", { topic_id: C, snapshot_id: sa.snapshot_id, origin_group: "x" }, "ownership", 403);
});

test("S05·S07: 근거 부족·발췌 불일치·지지 부족·본문 없는 출처는 승인과 편성을 막는다", async () => {
  const id = await newTopic();
  await fails("select", { topic_id: id, expected_version: await topicVersion(id), review_id: id, formats: ["carousel"],
    editorial_week: "2026-10-28" }, "invalid_state");
  await toResearching(id);
  const meta = await ok("add_source", { topic_id: id, source: { url: `https://sake.example/${uniq()}` } });
  const body = await ok("add_source", { topic_id: id, source: { url: `https://sake.example/${uniq()}`, body_text: BODY,
    rights_status: "quote_ok" } });
  let s = await ok("save_review", { topic_id: id, expected_topic_version: await topicVersion(id), scores: SCORES,
    brief, evidence_pack: { claims: claims(meta.snapshot_id) } });
  assert.ok(s.readiness.blockers.includes("claim_metadata_only:c1"));
  assert.ok((await reviewRow(s.review_id)).readiness.blockers.includes("claim_metadata_only:c1"), "초안 행에도 남는다");
  s = await ok("save_review", { topic_id: id, review_id: s.review_id, expected_version: s.version,
    evidence_pack: { claims: claims(body.snapshot_id, { support_review: "insufficient" }) } });
  const pack = (await reviewRow(s.review_id)).evidence_pack;
  assert.equal(pack.claims[0].source_refs[0].quote_check, "matched");
  assert.equal(pack.claims[0].support_review, "insufficient");
  assert.ok(s.readiness.blockers.includes("claim_insufficient:c1"));
  s = await ok("save_review", { topic_id: id, review_id: s.review_id, expected_version: s.version,
    evidence_pack: { claims: claims(body.snapshot_id, { source_refs: [{ snapshot_id: body.snapshot_id,
      original_quote: "원문에 없는 문장", quote_check: "matched" }] }) } });
  assert.equal((await reviewRow(s.review_id)).evidence_pack.claims[0].source_refs[0].quote_check, "unmatched");
  await ok("review_action", { review_id: s.review_id, expected_version: s.version, action: "submit" });
  const rv = await reviewRow(s.review_id);
  const blocked = await fails("review_action", { review_id: rv.id, expected_version: rv.version, action: "approve" },
    "review_blocked", 422);
  assert.ok(blocked.detail.includes("claim_quote_unmatched:c1"));
  await assert.rejects(db.query("update drink_topic_reviews set status = 'approved', approved_hash = input_hash where id = $1",
    [rv.id]), /review_blocked/, "함수를 우회한 직접 승인도 막힌다");
});

test("A: 형식별 필수 주장이 없으면 기획 승인 불가, 제안하지 않은 형식은 편성 불가", async () => {
  const id = await newTopic();
  await toResearching(id);
  const src = await ok("add_source", { topic_id: id, source: { body_text: BODY + uniq(), rights_status: "quote_ok" } });
  const s = await ok("save_review", { topic_id: id, expected_topic_version: await topicVersion(id), scores: SCORES,
    brief: { ...brief, proposed_formats: ["carousel"], required_claims: { carousel: [] } },
    evidence_pack: { claims: claims(src.snapshot_id).map((c) => ({ ...c, source_refs: [{ ...c.source_refs[0], snapshot_id: src.snapshot_id }] })) } });
  assert.ok(s.readiness.blockers.includes("required_claims_missing:carousel"));
  await ok("save_review", { topic_id: id, review_id: s.review_id, expected_version: s.version,
    brief: { ...brief, proposed_formats: ["carousel"], required_claims: { carousel: ["c1"] } } });
  await submitApprove(s.review_id);
  const r = await select(id, s.review_id, ["carousel", "video"], { format_exceptions: { video: "실험" } });
  assert.equal(r.body.code, "required_claims_missing", "제안·필수 주장이 없는 영상은 편성 불가");
  assert.equal((await select(id, s.review_id, ["carousel"])).status, 200);
});

test("A: 제작안 — 사실 항목 주장 누락·필수 주장 누락·모르는 주장 차단, 표지·출처·전환은 주장 없이 통과", async () => {
  const A = await approvedTopic();
  assert.equal((await select(A.id, A.reviewId, ["carousel"])).status, 200);
  // 사실 페이지(explain)에 주장 연결이 없으면 저장은 되지만 검수·승인은 막힌다
  const bad = await ok("save_plan", { topic_id: A.id, format: "carousel", topic_review_id: A.reviewId, plan_json: { pages: [
    { role: "cover", heading: "표지" }, { role: "explain", heading: "설명", claim_ids: [] }, { role: "source", heading: "출처" }] } });
  assert.deepEqual(bad.coverage.facts_without_claims, [2]);
  assert.deepEqual(bad.coverage.missing_required, ["c1", "c2"]);
  const pv = await planRow(bad.revision_id);
  const f = await fails("plan_action", { revision_id: pv.id, expected_version: pv.version, action: "submit" }, "plan_coverage", 422);
  assert.deepEqual(f.detail.missing_required, ["c1", "c2"]);
  // 필수 주장 일부만(c1) → 여전히 차단
  await ok("save_plan", { topic_id: A.id, format: "carousel", revision_id: pv.id, expected_version: pv.version,
    topic_review_id: A.reviewId, plan_json: { pages: [{ role: "cover", heading: "표지" },
      { role: "explain", heading: "설명", claim_ids: ["c1"] }] } });
  let p2 = await planRow(pv.id);
  assert.equal((await act("plan_action", { revision_id: p2.id, expected_version: p2.version, action: "submit" })).body.code, "plan_coverage");
  // 모르는 주장·다른 소재 버전의 주장 id
  await fails("save_plan", { topic_id: A.id, format: "carousel", revision_id: p2.id, expected_version: p2.version,
    topic_review_id: A.reviewId, plan_json: { pages: [{ role: "explain", heading: "x", claim_ids: ["c99"] }] } }, "plan_claim_unknown");
  const B = await approvedTopic();
  await fails("save_plan", { topic_id: A.id, format: "carousel", revision_id: p2.id, expected_version: p2.version,
    topic_review_id: B.reviewId, plan_json: cardPlan }, "ownership", 403);
  // 정상: 표지·출처는 주장 없이, 사실 페이지는 필수 주장 모두
  await ok("save_plan", { topic_id: A.id, format: "carousel", revision_id: p2.id, expected_version: p2.version,
    topic_review_id: A.reviewId, plan_json: cardPlan });
  const done = await approvePlan(p2.id);
  assert.equal(done.plan_status, "approved");
  assert.equal(done.coverage.ok, true);
  // 트리거도 같은 검사: 함수를 우회해 필수 주장 없는 초안을 검토로 올릴 수 없다
  p2 = await planRow(p2.id);
  const dv = (await row("select version from drink_deliverables where id = $1", [p2.deliverable_id])).version;
  const nv = await ok("save_plan", { topic_id: A.id, format: "carousel", topic_review_id: A.reviewId, expected_deliverable_version: dv,
    plan_json: { pages: [{ role: "cover", heading: "표지" }] } });
  await assert.rejects(db.query("update drink_plan_revisions set plan_status = 'in_review' where id = $1", [nv.revision_id]), /plan_coverage/);
});

test("소유 관계: 다른 소재의 출처·근거 버전 id 를 제출하면 거부된다", async () => {
  const A = await approvedTopic();
  const B = await approvedTopic();
  await fails("select", { topic_id: A.id, expected_version: await topicVersion(A.id), review_id: B.reviewId,
    review_input_hash: (await reviewRow(B.reviewId)).approved_hash, formats: ["carousel"], editorial_week: "2026-10-28" },
    "ownership", 403);
  const C = await newTopic();
  await toResearching(C);
  await fails("save_review", { topic_id: C, expected_topic_version: await topicVersion(C),
    evidence_pack: { claims: claims(A.snapshotId) } }, "ref_not_owned", 403);
  const disc = await ok("add_source", { topic_id: C, source: { url: `https://insta.example/${uniq()}`, body_text: BODY, role: "discovery" } });
  await fails("save_review", { topic_id: C, expected_topic_version: await topicVersion(C),
    evidence_pack: { claims: claims(disc.snapshot_id) } }, "ref_not_evidence");
  await assert.rejects(db.query("update drink_topics set current_review_id = $1 where id = $2", [B.reviewId, A.id]), /foreign key/);
  await assert.rejects(db.query("update drink_topics set approved_review_id = $1 where id = $2", [B.reviewId, A.id]), /foreign key/);
});

test("정책①·S06: 적합성 미달 형식은 경고 + 형식 예외 사유로 편성, 65점 예외와 따로 기록", async () => {
  const { id, reviewId } = await approvedTopic();
  const rv = await reviewRow(reviewId);
  assert.ok(rv.readiness.warnings.includes("format_fit_low:video"), "차단이 아니라 경고");
  assert.equal((await select(id, reviewId, ["video"])).body.code, "format_fit_low");
  const r = await select(id, reviewId, ["video", "carousel"], { format_exceptions: { video: "짧은 실험 영상으로 반응 확인" } });
  assert.equal(r.status, 200, JSON.stringify(r.body));
  const t = await topicRow(id);
  assert.deepEqual(t.selected_formats, ["carousel", "video"]);
  assert.deepEqual(t.format_exception_reasons, { video: "짧은 실험 영상으로 반응 확인" });
  assert.equal(t.score_exception_reason, null, "점수 예외와 형식 예외는 다른 칸");
  assert.equal(t.editorial_week.toISOString().slice(0, 10), "2026-10-26");

  const low = await approvedTopic({ scores: { relevance: 1, utility: 1, curiosity: 1, fit_video: 4, fit_carousel: 4, timeliness: 0 } });
  assert.equal((await select(low.id, low.reviewId, ["carousel"])).body.code, "below_threshold");
  assert.equal((await select(low.id, low.reviewId, ["carousel"], { score_exception_reason: "시리즈 공백" })).status, 200);
  const lt = await topicRow(low.id);
  assert.equal(lt.score_exception_reason, "시리즈 공백");
  assert.equal(lt.format_exception_reasons, null);
});

test("정책③: 새 근거 버전이 생겨도 기존 승인·편성·제작안 참조는 그대로", async () => {
  const { id, reviewId } = await approvedTopic();
  assert.equal((await select(id, reviewId, ["carousel"])).status, 200);
  const c1 = await ok("save_plan", { topic_id: id, format: "carousel", topic_review_id: reviewId, plan_json: cardPlan });
  await approvePlan(c1.revision_id);
  // 보충 버전 작성 — 상태·편성·제작안 참조 불변
  const s = await ok("save_review", { topic_id: id, expected_topic_version: await topicVersion(id), brief: { ...brief, exclusions: "가격" } });
  assert.equal(s.revision_no, 2);
  let t = await topicRow(id);
  assert.equal(t.status, "selected");
  assert.equal(t.selected_review_id, reviewId);
  assert.equal(t.approved_review_id, reviewId);
  assert.equal((await planRow(c1.revision_id)).topic_review_id, reviewId);
  await submitApprove(s.review_id);
  t = await topicRow(id);
  assert.equal(t.approved_review_id, s.review_id, "최근 승인 포인터만 옮긴다");
  assert.equal(t.selected_review_id, reviewId, "편성 버전은 자동 교체하지 않는다");
  assert.equal((await reviewRow(reviewId)).revoked_at, null, "옛 승인은 철회하지 않는다");
  assert.equal((await planRow(c1.revision_id)).plan_status, "approved");
  // 승인본 불변
  await assert.rejects(db.query(`update drink_topic_reviews set brief = '{}' where id = $1`, [reviewId]), /immutable/);
  await assert.rejects(db.query(`delete from drink_topic_reviews where id = $1`, [reviewId]), /immutable/);
  // 새 버전 철회는 편성에 쓴 옛 버전을 건드리지 않는다
  const nv = await reviewRow(s.review_id);
  const rev = await ok("review_action", { review_id: nv.id, expected_version: nv.version, action: "revoke", reason: "범위 오류" });
  assert.equal(rev.topic_status, "selected");
  assert.equal((await planRow(c1.revision_id)).blocked_at, null, "옛 근거를 쓴 제작안은 차단되지 않는다");
});

test("보류 해제: 유효한 승인 근거가 있으면 편성 가능으로 돌아간다", async () => {
  const A = await approvedTopic();
  await ok("topic_action", { topic_id: A.id, expected_version: await topicVersion(A.id), action: "hold", reason: "다음 달" });
  await ok("topic_action", { topic_id: A.id, expected_version: await topicVersion(A.id), action: "reopen" });
  assert.equal((await topicRow(A.id)).status, "ready");
});

test("B: unknown → 사용 조건 확인으로 승인 가능, 재등록 차이는 버리지 않고 돌려준다", async () => {
  const id = await newTopic();
  await toResearching(id);
  const url = `https://maker.example/${uniq()}`;
  const src = await ok("add_source", { topic_id: id, source: { url, body_text: BODY } });
  const again = await ok("add_source", { topic_id: id, source: { url, body_text: BODY, rights_status: "quote_ok", publisher: "제조사" } });
  assert.deepEqual(Object.keys(again.metadata_diff).sort(), ["publisher", "rights_status"]);
  assert.equal((await row("select rights_status from drink_source_snapshots where id=$1", [src.snapshot_id])).rights_status,
    "unknown", "재등록만으로 몰래 바꾸지 않는다");
  const s = await ok("save_review", { topic_id: id, expected_topic_version: await topicVersion(id), scores: SCORES, brief,
    evidence_pack: { claims: claims(src.snapshot_id) } });
  assert.ok(s.readiness.blockers.includes("claim_rights_unconfirmed:c1"));
  await fails("attest_source", { topic_id: id, snapshot_id: src.snapshot_id, kind: "rights_confirmed",
    fields: { rights_status: "restricted" } }, "invalid_input");
  const a = await ok("attest_source", { topic_id: id, snapshot_id: src.snapshot_id, kind: "rights_confirmed",
    fields: { rights_status: "quote_ok", usage_terms: "제조사 이용약관 3조", checked_at: "2026-10-22" } });
  assert.equal(a.effective.rights_status, "quote_ok");
  await ok("attest_source", { topic_id: id, snapshot_id: src.snapshot_id, kind: "recheck", fields: { checked_at: "2026-10-23" } });
  await fails("attest_source", { topic_id: id, snapshot_id: src.snapshot_id, kind: "correction", fields: { publisher: "x" } }, "invalid_input");
  await ok("attest_source", { topic_id: id, snapshot_id: src.snapshot_id, kind: "correction", fields: { publisher: "OO양조" },
    reason: "발행처 오기" });
  await fails("attest_source", { topic_id: id, snapshot_id: src.snapshot_id, kind: "correction", fields: { rights_status: "quote_ok" },
    reason: "x" }, "invalid_input");
  const rv = await reviewRow(s.review_id);
  await ok("save_review", { topic_id: id, review_id: rv.id, expected_version: rv.version, brief });
  await submitApprove(s.review_id);
  const meta = await row("select drinks_snapshot_meta($1) as m", [src.snapshot_id]);
  assert.equal(meta.m.publisher, "OO양조");
  assert.equal(meta.m.checked_at, "2026-10-23");
  assert.equal(meta.m.attestation_count, 3);
  assert.equal((await row("select publisher from drink_source_snapshots where id=$1", [src.snapshot_id])).publisher, null, "원문 행은 그대로");
  await assert.rejects(db.query("delete from drink_snapshot_attestations where snapshot_id = $1", [src.snapshot_id]), /immutable/);
  assert.ok((await reviewRow(s.review_id)).readiness.source_state[src.snapshot_id], "승인 시점 출처 상태를 남긴다");
});

test("B·S09: 공유 출처 권리 철회 → 영향 범위(다른 소재) 표시, 선택 시 관련 승인 철회·제작안 차단, 편성 재검사", async () => {
  const url = `https://shared-rights.example/${uniq()}`;
  const A = await approvedTopic({ url });
  const B = await approvedTopic({ url });
  assert.equal(A.snapshotId, B.snapshotId, "같은 URL·본문이라 스냅샷 공유");
  assert.equal((await select(A.id, A.reviewId, ["carousel"])).status, 200);
  const pa = await ok("save_plan", { topic_id: A.id, format: "carousel", topic_review_id: A.reviewId, plan_json: cardPlan });
  await approvePlan(pa.revision_id);
  // B 는 편성 전 — 철회만 하고 승인은 그대로 두면(revoke_affected=false) 편성 재검사에서 막힌다
  const res = await ok("attest_source", { topic_id: A.id, snapshot_id: A.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "제조사가 인용 허락 철회", revoke_affected: false });
  assert.deepEqual(res.impact.topics.map((t: Any) => t.id).sort(), [A.id, B.id].sort());
  assert.equal(res.impact.approved_reviews.length, 2);
  assert.equal(res.revoked_reviews.length, 0);
  // 체크박스(revoke_affected)를 안 골라도 지금 쓸 수 없는 근거로는 편성할 수 없다 — 소재가 조사 중으로 내려간다
  assert.equal((await topicRow(B.id)).status, "researching");
  assert.equal((await select(B.id, B.reviewId, ["carousel"])).body.code, "invalid_state");
  assert.ok((await planRow(pa.revision_id)).blocked_at, "A 의 승인된 제작안도 차단");
  // 과거 승인 본문은 바뀌지 않았다
  assert.equal((await reviewRow(A.reviewId)).status, "approved");
  // 이번엔 영향 범위의 승인을 철회 — A 의 제작안 차단, A 는 조사 중
  const url2 = `https://shared-rights2.example/${uniq()}`;
  const C = await approvedTopic({ url: url2 });
  assert.equal((await select(C.id, C.reviewId, ["carousel"])).status, 200);
  const pc = await ok("save_plan", { topic_id: C.id, format: "carousel", topic_review_id: C.reviewId, plan_json: cardPlan });
  await approvePlan(pc.revision_id);
  const res2 = await ok("attest_source", { topic_id: C.id, snapshot_id: C.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "권리 철회", revoke_affected: true });
  assert.equal(res2.revoked_reviews.length, 1);
  assert.ok((await planRow(pc.revision_id)).blocked_at);
  assert.equal((await topicRow(C.id)).status, "researching");
  await assert.rejects(db.query("update drink_plan_revisions set blocked_at = null, blocked_reason = null where id = $1", [pc.revision_id]), /immutable/);
  await assert.rejects(db.query("update drink_topic_reviews set revoked_at = null, revoked_reason = null where id = $1", [C.reviewId]), /immutable/);
});

test("동시 수정·중복 요청(순차): 같은 expected_version 두 번째는 거부되고 승인 버전은 바뀌지 않는다", async () => {
  const id = await newTopic();
  await toResearching(id);
  const src = await ok("add_source", { topic_id: id, source: { body_text: BODY + uniq(), rights_status: "quote_ok" } });
  const s = await ok("save_review", { topic_id: id, expected_topic_version: await topicVersion(id), scores: SCORES,
    brief, evidence_pack: { claims: claims(src.snapshot_id) } });
  await ok("save_review", { topic_id: id, review_id: s.review_id, expected_version: s.version, brief: { ...brief, exclusions: "A" } });
  await fails("save_review", { topic_id: id, review_id: s.review_id, expected_version: s.version, brief: { ...brief, exclusions: "B" } },
    "version_conflict", 409);
  assert.equal((await reviewRow(s.review_id)).brief.exclusions, "A");
  await submitApprove(s.review_id);
  const approved = await reviewRow(s.review_id);
  await fails("review_action", { review_id: s.review_id, expected_version: approved.version - 1, action: "approve" }, "version_conflict");
  await fails("review_action", { review_id: s.review_id, expected_version: approved.version, action: "approve" }, "invalid_state");
  assert.equal((await reviewRow(s.review_id)).approved_hash, approved.approved_hash);
  const v = await topicVersion(id);
  assert.equal((await select(id, s.review_id, ["carousel"], { expected_version: v })).status, 200);
  assert.equal((await select(id, s.review_id, ["carousel"], { expected_version: v })).body.code, "version_conflict");
  assert.equal((await select(id, s.review_id, ["carousel"], { review_input_hash: "deadbeef" })).body.code, "review_changed");
});

test("신호→근거 승격은 한 번, 근거→신호 강등·연결 삭제는 불가", async () => {
  const C = await newTopic();
  const u = `https://insta.example/${uniq()}`;
  const d = await ok("add_source", { topic_id: C, source: { url: u, body_text: BODY, role: "discovery" } });
  assert.equal((await ok("add_source", { topic_id: C, source: { url: u, body_text: BODY, role: "evidence" } })).promoted, true);
  assert.equal((await ok("add_source", { topic_id: C, source: { url: u, body_text: BODY, role: "discovery" } })).role, "evidence");
  await assert.rejects(db.query("update drink_topic_sources set role = 'discovery' where snapshot_id = $1", [d.snapshot_id]), /immutable/);
  await assert.rejects(db.query("delete from drink_topic_sources where snapshot_id = $1", [d.snapshot_id]), /immutable/);
});

test("제외 기능: 임의 URL·LLM·렌더·발행 동작은 서버가 거부하고, 그런 큐·표가 DB 에 없다", async () => {
  for (const a of PHASE_A_EXCLUDED) {
    const r = await act(a, {});
    assert.equal(r.status, 403, a);
    assert.equal(r.body.code, "not_in_phase_a");
  }
  const tables = (await db.query<{ table_name: string }>(`select table_name from information_schema.tables where table_schema='public'
    and table_type = 'BASE TABLE' and table_name like 'drink%' order by 1`)).rows.map((r) => r.table_name);
  const views = (await db.query<{ table_name: string }>(`select table_name from information_schema.views where table_schema='public'
    and table_name like 'drink%' order by 1`)).rows.map((r) => r.table_name);
  assert.deepEqual(views, ["drink_review_validity"], "읽기 전용 판정 뷰 하나뿐");
  // B단계(0051): 수집원·수집 실행·실행 문서, B 보완(0052): 소재 발견 자료·관측·후보·후보 연결 — 렌더·발행 큐는 없다.
  assert.deepEqual(tables, ["drink_candidate_items", "drink_collection_items", "drink_collection_runs", "drink_deliverables",
    "drink_discovery_candidates", "drink_discovery_items", "drink_discovery_observations", "drink_plan_revisions",
    "drink_snapshot_attestations", "drink_source_snapshots", "drink_sources", "drink_topic_reviews", "drink_topic_sources",
    "drink_topics", "drink_workflow_events"]);
});

test("감사 이력은 추가만 된다", async () => {
  const id = await newTopic();
  await assert.rejects(db.query("update drink_workflow_events set reason = 'x' where topic_id = $1", [id]), /immutable/);
  await assert.rejects(db.query("delete from drink_workflow_events where topic_id = $1", [id]), /immutable/);
  await assert.rejects(db.query("delete from drink_topics where id = $1", [id]), /immutable/);
});

test("Fable Review 2차 조치: 편성 버전 철회·직접 편성 우회·검토 중 고아·소수 점수·재등록 기본값·공유 이력·자동 철회 범위", async () => {
  // ② 편성에 쓴 옛 버전 철회 + 더 최근 유효 승인 → 편성 가능으로(조사 중에 갇히지 않는다)
  const A = await approvedTopic();
  assert.equal((await select(A.id, A.reviewId, ["carousel"])).status, 200);
  const s2 = await ok("save_review", { topic_id: A.id, expected_topic_version: await topicVersion(A.id), brief: { ...brief, exclusions: "보충" } });
  await submitApprove(s2.review_id);
  const r1 = await reviewRow(A.reviewId);
  const rev = await ok("review_action", { review_id: r1.id, expected_version: r1.version, action: "revoke", reason: "옛 버전 오류" });
  assert.equal(rev.topic_status, "ready");
  assert.equal((await select(A.id, s2.review_id, ["carousel"])).status, 200, "최근 승인으로 다시 편성");

  // ③ 직접 UPDATE 로 필수 조건이 깨진 승인 버전에 편성할 수 없다
  const B = await approvedTopic();
  await ok("attest_source", { topic_id: B.id, snapshot_id: B.snapshotId, kind: "rights_revoked", fields: { rights_status: "restricted" },
    reason: "권리 철회" });
  await assert.rejects(db.query(`update drink_topics set status='selected', selected_review_id=$1, selected_formats='{carousel}',
    editorial_week='2026-10-26' where id=$2`, [B.reviewId, B.id]), /review_blocked|invalid_transition/);

  // ⑥ 검토 중 버전을 두고 새 버전을 만들 수 없다
  const C = await newTopic();
  await toResearching(C);
  const src = await ok("add_source", { topic_id: C, source: { body_text: BODY + uniq(), rights_status: "quote_ok" } });
  const sc = await ok("save_review", { topic_id: C, expected_topic_version: await topicVersion(C), scores: SCORES, brief,
    evidence_pack: { claims: claims(src.snapshot_id) } });
  await ok("review_action", { review_id: sc.review_id, expected_version: sc.version, action: "submit" });
  await fails("save_review", { topic_id: C, expected_topic_version: await topicVersion(C), brief }, "review_in_progress", 409);

  // ⑧ 2.0 같은 소수 표기 점수는 500 이 아니라 입력 오류
  const D = await newTopic();
  await fails("triage", { topic_id: D, expected_version: await topicVersion(D), scores: { ...SCORES, relevance: 2.5 } }, "invalid_input", 400);
  await assert.rejects(db.query(`select drinks_check_scores('{"relevance":2.0}'::jsonb, true)`), /0~4 정수/);

  // ④ 재등록 때 'unknown' 기본값은 확인된 사용 조건과 다르다고 알리지 않는다
  const url = `https://shared-default.example/${uniq()}`;
  const E1 = await newTopic(); const E2 = await newTopic();
  const se = await ok("add_source", { topic_id: E1, source: { url, body_text: BODY } });
  await ok("attest_source", { topic_id: E1, snapshot_id: se.snapshot_id, kind: "rights_confirmed", fields: { rights_status: "quote_ok" } });
  const again = await ok("add_source", { topic_id: E2, source: { url, body_text: BODY, rights_status: "unknown" } });
  assert.deepEqual(again.metadata_diff, {});

  // ⑤ 공유 출처의 정정 기록은 다른 소재 이력에도 남는다
  await ok("attest_source", { topic_id: E1, snapshot_id: se.snapshot_id, kind: "correction", fields: { publisher: "정정" }, reason: "오기" });
  const ev = await row(`select count(*)::int as n from drink_workflow_events where topic_id=$1 and action='source_correction_elsewhere'`, [E2]);
  assert.equal(ev.n, 1);

  // ⑦ 다른 사용 가능한 근거가 있는 승인은 권리 철회로 자동 철회하지 않는다
  const F = await newTopic();
  await toResearching(F);
  const u1 = await ok("add_source", { topic_id: F, source: { url: `https://f1.example/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const u2 = await ok("add_source", { topic_id: F, source: { url: `https://f2.example/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const twoRefs = claims(u1.snapshot_id).map((c) => ({ ...c, source_refs: [...c.source_refs, { ...c.source_refs[0], snapshot_id: u2.snapshot_id }] }));
  const sf = await ok("save_review", { topic_id: F, expected_topic_version: await topicVersion(F), scores: SCORES, brief,
    evidence_pack: { claims: twoRefs } });
  await submitApprove(sf.review_id);
  const rr = await ok("attest_source", { topic_id: F, snapshot_id: u1.snapshot_id, kind: "rights_revoked", fields: { rights_status: "restricted" },
    reason: "u1 철회", revoke_affected: true });
  assert.equal(rr.impact.approved_reviews.length, 1, "영향 범위에는 보인다");
  assert.equal(rr.now_blocked_reviews.length, 0, "u2 가 남아 있어 필수 조건은 그대로");
  assert.equal(rr.revoked_reviews.length, 0, "깨지지 않은 승인은 철회하지 않는다");
  assert.equal((await reviewRow(sf.review_id)).revoked_at, null);
});

// ── 추가 검토 결함 1: 비사실 항목으로 필수 주장 전달 검사를 통과하던 것 ──
test("결함1: 필수 주장은 사실 항목에서만 전달로 센다(①~⑤)", async () => {
  const A = await approvedTopic();
  assert.equal((await select(A.id, A.reviewId, ["carousel"])).status, 200);
  const save = (pages: Any[], rev?: Any) => act("save_plan", { topic_id: A.id, format: "carousel", topic_review_id: A.reviewId,
    plan_json: { pages }, ...(rev ? { revision_id: rev.id, expected_version: rev.version } : {}) });
  const submitCode = async (id: string) => {
    const p = await planRow(id);
    return (await act("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" })).body.code;
  };
  // ① 표지·출처만, 표지에 필수 주장 c1·c2 → 차단(저장은 초안으로 허용)
  const s1 = await save([{ role: "cover", heading: "표지", claim_ids: ["c1", "c2"] }, { role: "source", heading: "출처", claim_ids: ["c1"] }]);
  assert.equal(s1.status, 200);
  assert.deepEqual(s1.body.result.coverage.covered, []);
  assert.deepEqual(s1.body.result.coverage.reference_only, ["c1", "c2"]);
  assert.equal(s1.body.result.coverage.ok, false);
  assert.equal(await submitCode(s1.body.result.revision_id), "plan_coverage");
  // 함수를 우회한 직접 UPDATE 도 트리거가 같은 규칙으로 막는다
  await assert.rejects(db.query("update drink_plan_revisions set plan_status = 'in_review' where id = $1", [s1.body.result.revision_id]), /plan_coverage/);
  // ③ 필수 c2 는 표지에만, 사실 페이지에는 c1 만 → 차단
  let p = await planRow(s1.body.result.revision_id);
  const s3 = await save([{ role: "cover", heading: "표지", claim_ids: ["c2"] }, { role: "explain", heading: "정미율", claim_ids: ["c1"] }], p);
  assert.deepEqual(s3.body.result.coverage.missing_required, ["c2"]);
  assert.equal(await submitCode(p.id), "plan_coverage");
  // ⑤ 사실 페이지 claim_ids 빈 배열·생략 → 차단 유지
  p = await planRow(p.id);
  const s5 = await save([{ role: "explain", heading: "a", claim_ids: ["c1", "c2"] }, { role: "compare", heading: "b" }], p);
  assert.deepEqual(s5.body.result.coverage.facts_without_claims, [2]);
  assert.equal(await submitCode(p.id), "plan_coverage");
  // ④ 사실 항목에서 필수 주장 전달 + 표지·출처 함께 → 허용(검토 요청·승인까지)
  p = await planRow(p.id);
  await save([{ role: "cover", heading: "표지", claim_ids: ["c1"] }, { role: "explain", heading: "정미율", claim_ids: ["c1"] },
    { role: "checklist", heading: "라벨", claim_ids: ["c2"] }, { role: "source", heading: "출처" }], p);
  const done = await approvePlan(p.id);
  assert.equal(done.plan_status, "approved");

  // ② 전환 장면만 있는 영상(필수 c1 을 전환에 붙임) → 차단
  const V = await approvedTopic({ scores: { ...SCORES, fit_video: 3 } });
  assert.equal((await select(V.id, V.reviewId, ["video"])).status, 200);
  const v1 = await ok("save_plan", { topic_id: V.id, format: "video", topic_review_id: V.reviewId,
    plan_json: { scenes: [{ narration: "궁금하죠?", content_kind: "transition", claim_ids: ["c1"] }] } });
  assert.equal(v1.coverage.ok, false);
  assert.deepEqual(v1.coverage.reference_only, ["c1"]);
  assert.equal(await submitCode(v1.revision_id), "plan_coverage");
  // ④' 전환 + 사실 장면(c1) → 허용
  const pv1 = await planRow(v1.revision_id);
  await ok("save_plan", { topic_id: V.id, format: "video", revision_id: pv1.id, expected_version: pv1.version, topic_review_id: V.reviewId,
    plan_json: { scenes: [{ narration: "궁금하죠?", content_kind: "transition" }, { narration: "쌀을 반 깎아요", claim_ids: ["c1"] }] } });
  assert.equal((await approvePlan(pv1.id)).plan_status, "approved");
  // ⑤ 모르는 주장·다른 소재의 근거 버전은 저장부터 차단(기존 유지)
  const pv2 = await planRow(pv1.id);
  const dv = (await row("select version from drink_deliverables where id = $1", [pv2.deliverable_id])).version;
  await fails("save_plan", { topic_id: V.id, format: "video", topic_review_id: V.reviewId, expected_deliverable_version: dv,
    plan_json: { scenes: [{ narration: "x", claim_ids: ["c77"] }] } }, "plan_claim_unknown");
  await fails("save_plan", { topic_id: V.id, format: "video", topic_review_id: A.reviewId, expected_deliverable_version: dv,
    plan_json: { scenes: [{ narration: "x", claim_ids: ["c1"] }] } }, "ownership", 403);
});

// ── 추가 검토 결함 2: 권리 철회 후 기존 승인·제작안이 "지금 사용 가능"으로 남던 것 ──
async function selectedWithApprovedPlan(opts: { url?: string; extraUsable?: boolean } = {}) {
  const T = await approvedTopic({ url: opts.url });
  let reviewId = T.reviewId;
  let extra: string | null = null;
  if (opts.extraUsable) {
    // 같은 주장을 두 번째 사용 가능한 출처로도 뒷받침하는 새 버전을 승인한다
    const s2 = await ok("add_source", { topic_id: T.id, source: { url: `https://second.example/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
    extra = s2.snapshot_id;
    const two = claims(T.snapshotId).map((c) => ({ ...c, source_refs: [...c.source_refs, { ...c.source_refs[0], snapshot_id: s2.snapshot_id }] }));
    const nv = await ok("save_review", { topic_id: T.id, expected_topic_version: await topicVersion(T.id), evidence_pack: { claims: two } });
    await submitApprove(nv.review_id);
    reviewId = nv.review_id;
  }
  assert.equal((await select(T.id, reviewId, ["carousel"])).status, 200);
  const pl = await ok("save_plan", { topic_id: T.id, format: "carousel", topic_review_id: reviewId, plan_json: cardPlan });
  await approvePlan(pl.revision_id);
  return { ...T, reviewId, planId: pl.revision_id as string, extra };
}
const validity = async (reviewId: string) => row("select * from drink_review_validity where review_id = $1", [reviewId]);

test("결함2-①: 유일한 사용 가능 출처 권리 철회(revoke_affected=false) → 지금 사용 차단, 승인 기록은 보존", async () => {
  const T = await selectedWithApprovedPlan();
  const before = await reviewRow(T.reviewId);
  const res = await ok("attest_source", { topic_id: T.id, snapshot_id: T.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "제조사 인용 허락 철회", revoke_affected: false });
  assert.equal(res.invalidated_reviews.length, 1);
  assert.equal(res.revoked_reviews.length, 0);
  const after = await reviewRow(T.reviewId);
  assert.equal(after.status, "approved", "승인했다는 역사는 그대로");
  assert.equal(after.revoked_at, null);
  assert.equal(after.approved_hash, before.approved_hash);
  assert.deepEqual(after.readiness, before.readiness, "승인 당시 readiness·source_state 를 덮어쓰지 않는다");
  const v = await validity(T.reviewId);
  assert.equal(v.currently_valid, false, "지금은 쓸 수 없다");
  assert.ok(v.current_blockers.includes("claim_rights_unconfirmed:c1"));
  const pl = await planRow(T.planId);
  assert.ok(pl.blocked_at, "승인된 제작안도 차단");
  assert.match(pl.blocked_reason, /^evidence_invalid/);
  assert.equal(pl.plan_status, "approved", "제작안 승인 기록도 보존");
  assert.equal((await topicRow(T.id)).status, "researching", "편성에서 내려온다");
  const ev = await row(`select count(*)::int as n from drink_workflow_events where topic_id=$1 and action='evidence_invalidated'`, [T.id]);
  assert.equal(ev.n, 1);
});

test("결함2-②: 같은 상황 revoke_affected=true → 승인 철회 + 제작안 차단, 이력 일치", async () => {
  const T = await selectedWithApprovedPlan();
  const res = await ok("attest_source", { topic_id: T.id, snapshot_id: T.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "권리 철회", revoke_affected: true });
  assert.equal(res.revoked_reviews.length, 1);
  assert.equal(res.invalidated_reviews.length, 0);
  assert.ok((await reviewRow(T.reviewId)).revoked_at);
  const pl = await planRow(T.planId);
  assert.match(pl.blocked_reason, /^evidence_revoked/);
  const ev = await row(`select count(*)::int as n from drink_workflow_events where topic_id=$1 and action='review_revoke'`, [T.id]);
  assert.equal(ev.n, 1);
  assert.equal((await validity(T.reviewId)).currently_valid, false);
});

test("결함2-③·④: 다른 유효 근거가 남으면 영향 없음 / 공유 출처는 실제로 깨지는 소재만", async () => {
  const url = `https://shared-fix.example/${uniq()}`;
  const T1 = await selectedWithApprovedPlan({ url });                    // 이 출처뿐
  const T2 = await selectedWithApprovedPlan({ url, extraUsable: true });  // 같은 출처 + 다른 사용 가능 출처
  assert.equal(T1.snapshotId, T2.snapshotId);
  const res = await ok("attest_source", { topic_id: T1.id, snapshot_id: T1.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "철회" });
  // 깨진 것: T1 의 승인, T2 의 옛 승인 v1(이 출처뿐이었다). T2 가 편성에 쓰는 v2 는 다른 근거로 유효 → 영향 없음
  const t2v1 = (await row("select id from drink_topic_reviews where topic_id=$1 and revision_no=1", [T2.id])).id;
  assert.deepEqual(res.invalidated_reviews.map((x: Any) => x.review_id).sort(), [T1.reviewId, t2v1].sort());
  assert.ok(!res.invalidated_reviews.some((x: Any) => x.review_id === T2.reviewId), "T2 편성 버전은 영향 없음");
  assert.ok((await planRow(T1.planId)).blocked_at);
  assert.equal((await planRow(T2.planId)).blocked_at, null, "T2 는 다른 근거로 여전히 유효 — 불필요한 차단 없음");
  assert.equal((await topicRow(T2.id)).status, "selected");
  assert.equal((await validity(T2.reviewId)).currently_valid, true);
  const ev2 = await row(`select count(*)::int as n from drink_workflow_events where topic_id=$1 and action='source_rights_revoked_elsewhere'`, [T2.id]);
  assert.equal(ev2.n, 1, "T2 이력에도 남는다");
});

test("결함2-⑥: 권리 재확인 후에도 차단된 제작안은 부활하지 않고, 새 버전 검토 경로는 열린다", async () => {
  const T = await selectedWithApprovedPlan();
  await ok("attest_source", { topic_id: T.id, snapshot_id: T.snapshotId, kind: "rights_revoked", fields: { rights_status: "restricted" },
    reason: "철회" });
  await ok("attest_source", { topic_id: T.id, snapshot_id: T.snapshotId, kind: "rights_confirmed", fields: { rights_status: "quote_ok" },
    reason: "재허락" });
  assert.ok((await planRow(T.planId)).blocked_at, "자동 부활 없음");
  await assert.rejects(db.query("update drink_plan_revisions set blocked_at = null, blocked_reason = null where id = $1", [T.planId]), /immutable/);
  assert.equal((await validity(T.reviewId)).currently_valid, true, "근거는 지금 다시 유효");
  assert.equal((await topicRow(T.id)).status, "ready", "다시 편성할 수 있다");
  const rv = await reviewRow(T.reviewId);
  assert.equal((await select(T.id, T.reviewId, ["carousel"], { review_input_hash: rv.approved_hash })).status, 200);
  const d = await row("select * from drink_deliverables where topic_id = $1 and format = 'carousel'", [T.id]);
  const nv = await ok("save_plan", { topic_id: T.id, format: "carousel", topic_review_id: T.reviewId,
    expected_deliverable_version: d.version, plan_json: cardPlan });
  assert.equal(nv.revision_no, 2, "새 제작안 버전으로 다시 검토");
  assert.equal((await approvePlan(nv.revision_id)).plan_status, "approved");
});

test("결함2: 함수를 우회해도 지금 쓸 수 없는 근거로 편성·제작안 승인 불가(트리거)", async () => {
  const T = await approvedTopic();
  // 정정 기록을 함수 없이 직접 넣는다(상태 맞춤 없이) — 소재는 '편성 가능'에 남지만 근거는 지금 쓸 수 없다
  await db.query(`insert into drink_snapshot_attestations (snapshot_id, topic_id, kind, fields, reason)
    values ($1, $2, 'rights_revoked', '{"rights_status":"restricted"}', '직접')`, [T.snapshotId, T.id]);
  assert.equal((await topicRow(T.id)).status, "ready");
  await assert.rejects(db.query(`update drink_topics set status='selected', selected_review_id=$1, selected_formats='{carousel}',
    editorial_week='2026-10-26' where id=$2`, [T.reviewId, T.id]), /review_blocked/);
  assert.equal((await select(T.id, T.reviewId, ["carousel"])).body.code, "review_blocked");
});

test("결함2 보완(Fable 3차): 이미 깨진 승인도 체크박스로 철회 / 상태 변경 이력 / 사건 없는 무효 정리 / 무효 근거로 제작안 작성·검토 불가", async () => {
  // 두 주장을 서로 다른 출처로 뒷받침하는 승인 — S1 철회(체크박스 없음)로 이미 깨진 뒤 S2 철회(체크박스)
  const T = await newTopic();
  await toResearching(T);
  const s1 = await ok("add_source", { topic_id: T, source: { url: `https://s1.example/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const s2 = await ok("add_source", { topic_id: T, source: { url: `https://s2.example/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const cl = claims(s1.snapshot_id);
  cl[1] = { ...cl[1], source_refs: [{ snapshot_id: s2.snapshot_id, original_quote: QUOTE2 }] };
  const sv = await ok("save_review", { topic_id: T, expected_topic_version: await topicVersion(T), scores: SCORES, brief, evidence_pack: { claims: cl } });
  await submitApprove(sv.review_id);
  assert.equal((await select(T, sv.review_id, ["carousel"])).status, 200);
  const pl = await ok("save_plan", { topic_id: T, format: "carousel", topic_review_id: sv.review_id, plan_json: cardPlan });
  await ok("attest_source", { topic_id: T, snapshot_id: s1.snapshot_id, kind: "rights_revoked", fields: { rights_status: "restricted" }, reason: "S1" });
  // 무효 근거로는 새 제작안을 쓰거나 검토에 올릴 수 없다
  const pv = await planRow(pl.revision_id);
  assert.ok(pv.blocked_at, "초안 제작안도 차단");
  await fails("save_plan", { topic_id: T, format: "carousel", topic_review_id: sv.review_id, plan_json: cardPlan }, "format_not_selected");
  const res = await ok("attest_source", { topic_id: T, snapshot_id: s2.snapshot_id, kind: "rights_revoked", fields: { rights_status: "restricted" },
    reason: "S2", revoke_affected: true });
  assert.equal(res.now_blocked_reviews.length, 0, "이번에 새로 깨진 것은 아니다");
  assert.equal(res.revoked_reviews.length, 1, "그래도 체크박스면 철회한다");
  assert.ok((await reviewRow(sv.review_id)).revoked_at);

  // 재확인으로 다시 유효 → 조사 중 → 편성 가능, 그 변경이 이력에 남는다
  const U = await selectedWithApprovedPlan();
  await ok("attest_source", { topic_id: U.id, snapshot_id: U.snapshotId, kind: "rights_revoked", fields: { rights_status: "restricted" }, reason: "철회" });
  await ok("attest_source", { topic_id: U.id, snapshot_id: U.snapshotId, kind: "rights_confirmed", fields: { rights_status: "quote_ok" }, reason: "재허락" });
  const evs = (await db.query(`select before_status, after_status from drink_workflow_events where topic_id=$1 and action='status_from_evidence' order by id`,
    [U.id])).rows;
  assert.deepEqual(evs.map((e: Any) => `${e.before_status}>${e.after_status}`), ["selected>researching", "researching>ready"]);

  // 사건 없이 생긴 무효(기한 경과 같은 경우를 정정 기록 직접 삽입으로 흉내) → 정리 동작이 제작안 차단·상태 맞춤·이력
  const W = await selectedWithApprovedPlan();
  await db.query(`insert into drink_snapshot_attestations (snapshot_id, topic_id, kind, fields, reason)
    values ($1, $2, 'rights_revoked', '{"rights_status":"restricted"}', '직접')`, [W.snapshotId, W.id]);
  assert.equal((await planRow(W.planId)).blocked_at, null, "아직 아무도 정리하지 않았다");
  assert.equal((await validity(W.reviewId)).currently_valid, false, "그래도 판정 뷰는 지금 사용 불가");
  const wd = await row("select * from drink_deliverables where topic_id = $1 and format = 'carousel'", [W.id]);
  await fails("save_plan", { topic_id: W.id, format: "carousel", topic_review_id: W.reviewId, expected_deliverable_version: wd.version,
    plan_json: cardPlan }, "review_blocked", 422);
  await ok("topic_action", { topic_id: W.id, expected_version: await topicVersion(W.id), action: "refresh_validity" });
  assert.ok((await planRow(W.planId)).blocked_at);
  assert.equal((await topicRow(W.id)).status, "researching");
  const ew = await row(`select count(*)::int as n from drink_workflow_events where topic_id=$1 and action in ('evidence_invalidated','status_from_evidence')`, [W.id]);
  assert.equal(ew.n, 2);
});

test("최종 보완 결함1: 한 트랜잭션 안의 정정 기록도 기록한 순서대로 적용된다", async () => {
  const inOneTx = async (topicId: string, snapId: string, kinds: [string, string][]) => {
    await db.exec("begin");
    await db.exec("set local role service_role");
    for (const [kind, rights] of kinds) {
      await db.query(`select drinks_attest_source($1::jsonb)`, [JSON.stringify({ topic_id: topicId, snapshot_id: snapId, kind,
        fields: { rights_status: rights }, reason: kind })]);
    }
    await db.exec("commit");
  };
  // 확인 → 철회 (같은 트랜잭션: created_at 이 같다)
  const T = await selectedWithApprovedPlan();
  await inOneTx(T.id, T.snapshotId, [["rights_confirmed", "quote_ok"], ["rights_revoked", "restricted"]]);
  const rows = (await db.query<Any>("select seq, created_at, kind from drink_snapshot_attestations where snapshot_id=$1 order by seq",
    [T.snapshotId])).rows;
  assert.equal(new Set(rows.map((x: Any) => String(x.created_at))).size, 1, "시각이 같아 시각으로는 순서를 못 정한다");
  assert.deepEqual(rows.map((x: Any) => x.kind), ["rights_confirmed", "rights_revoked"]);
  assert.equal((await row("select drinks_snapshot_meta($1) ->> 'rights_status' as r", [T.snapshotId])).r, "restricted", "최종 철회");
  assert.equal((await validity(T.reviewId)).currently_valid, false, "마지막 철회 뒤 지금 사용 불가");
  assert.ok((await planRow(T.planId)).blocked_at, "제작안 차단도 일관");
  // 철회 → 재확인
  const U = await selectedWithApprovedPlan();
  await inOneTx(U.id, U.snapshotId, [["rights_revoked", "restricted"], ["rights_confirmed", "quote_ok"]]);
  assert.equal((await row("select drinks_snapshot_meta($1) ->> 'rights_status' as r", [U.snapshotId])).r, "quote_ok", "최종 재확인");
  assert.equal((await validity(U.reviewId)).currently_valid, true);
  assert.ok((await planRow(U.planId)).blocked_at, "중간 철회로 차단된 제작안은 재확인만으로 풀리지 않는다");
});

test("최종 보완 결함2(DB 상태): 옛 근거 R1 무효·새 근거 R2 유효, 제작안 P1 은 R1 참조 유지", async () => {
  const T = await selectedWithApprovedPlan();                           // R1 으로 편성·P1 승인
  const s2 = await ok("add_source", { topic_id: T.id, source: { url: `https://r2.example/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const nv = await ok("save_review", { topic_id: T.id, expected_topic_version: await topicVersion(T.id),
    evidence_pack: { claims: claims(s2.snapshot_id) } });
  await submitApprove(nv.review_id);
  const r2 = await reviewRow(nv.review_id);
  assert.equal((await select(T.id, r2.id, ["carousel"], { review_input_hash: r2.approved_hash })).status, 200, "R2 로 재편성");
  // R1 만 무효(기간 만료를 직접 기록으로 흉내 — 정리 동작은 실행하지 않음)
  await db.query(`insert into drink_snapshot_attestations (snapshot_id, topic_id, kind, fields, reason)
    values ($1, $2, 'rights_revoked', '{"rights_status":"restricted"}', '흉내')`, [T.snapshotId, T.id]);
  assert.equal((await validity(T.reviewId)).currently_valid, false);
  assert.equal((await validity(r2.id)).currently_valid, true);
  const p1 = await planRow(T.planId);
  assert.equal(p1.topic_review_id, T.reviewId, "참조를 새 버전으로 자동 교체하지 않는다");
  assert.equal(p1.plan_status, "approved");
  assert.equal(p1.blocked_at, null, "정리 전이라 저장된 차단은 없다 — 화면 판정(model.test)이 이 상태를 '근거 재확인'으로 안내");
});

test("근거 전달 검사: SQL drinks_plan_coverage 와 TS planCoverage 가 같은 판정을 낸다", async () => {
  const cases: [string, Any[], string[]][] = [
    ["carousel", cardPlan.pages, ["c1", "c2"]],
    ["carousel", [{ role: "cover" }, { role: "compare", claim_ids: [] }], ["c1"]],
    ["video", videoPlan.scenes, ["c1"]],
    ["video", [{ narration: "x" }], ["c1"]],
    ["carousel", [{ role: "cover" }], []],
    ["carousel", [{ role: "cover", claim_ids: ["c1", "c2"] }, { role: "source", claim_ids: ["c1"] }], ["c1", "c2"]],
    ["carousel", [{ role: "cover", claim_ids: ["c2"] }, { role: "explain", claim_ids: ["c1"] }], ["c1", "c2"]],
    ["video", [{ narration: "x", content_kind: "transition", claim_ids: ["c1"] }], ["c1"]],
  ];
  for (const [fmt, items, req] of cases) {
    const key = fmt === "video" ? "scenes" : "pages";
    const sql = (await row(`select drinks_plan_coverage($1, $2::jsonb, row(null,null,1,null,'drinks-v1','{}',null,'{}',
      jsonb_build_object('required_claims', jsonb_build_object($1::text, $3::jsonb)),'{}','','approved',null,null,null,'x',null,null,1,now(),now())::drink_topic_reviews) as c`,
      [fmt, JSON.stringify({ [key]: items }), JSON.stringify(req)])).c;
    const ts = planCoverage(fmt as "video" | "carousel", items, req);
    assert.deepEqual({ ...sql }, { ...ts }, `${fmt} ${JSON.stringify(items)}`);
  }
});

test("가중 합: SQL 과 TS 가 같은 값을 낸다(축 누락은 둘 다 null)", async () => {
  const cases = [SCORES, { relevance: 0, utility: 0, curiosity: 0, fit_video: 0, fit_carousel: 0, timeliness: 0 },
    { relevance: 4, utility: 4, curiosity: 4, fit_video: 4, fit_carousel: 0, timeliness: 4 },
    { relevance: 3, utility: 2, curiosity: 1, fit_video: 2, fit_carousel: 3, timeliness: 1 }, { relevance: 3, utility: 2 }];
  for (const s of cases) {
    const sql = (await row("select drinks_weighted_score($1::jsonb) as v", [JSON.stringify(s)])).v;
    assert.equal(sql === null ? null : Number(sql), weightedScore(s), JSON.stringify(s));
  }
});
