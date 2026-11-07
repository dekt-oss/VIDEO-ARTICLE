// 내용 승인 한 번(0064) DB 통합 테스트 — PGlite 위에 00(5x|6x|7x)_drinks_*. 0072 부터 result.chain 은 형식마다 한 항목인 배열이다.
// 운영자 동작은 라우트와 같은 runDrinksAction 경로, 워커 함수는 rpc 직접. 모델·네트워크 호출 0.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0064_drinks_single_approval.sql"), "0064 가 목록에 있어야 한다");
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
const fails = async (action: string, payload: Record<string, unknown>, code: string): Promise<Any> => {
  const r = await act(action, payload);
  assert.notEqual(r.status, 200, `${action} 가 통과하면 안 된다`);
  assert.equal(r.body.code, code, JSON.stringify(r.body));
  return r.body;
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

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 2, timeliness: 2 };
const QUOTE1 = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";
const QUOTE2 = "the smoky flavour is attributed to phenols, and in particular guaiacol";
const BODY = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking in order to further enhance the taste. " +
  "Chemically, the smoky flavour is attributed to phenols, and in particular guaiacol.";
const WEEK = "2026-11-04"; // 수요일 — 월요일로 맞춘다
const MONDAY = "2026-11-02";

const budget = (cap = 2) => rpc("drinks_open_develop_budget", { cap_usd: cap, stage: "시험", purpose: "시험", approver_words: "승인한다" });
const topicRow = (id: string) => row("select * from drink_topics where id = $1", [id]);
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);
const reqRow = (id: string) => row("select * from drink_develop_requests where id = $1", [id]);
const PLAN = { scenes: [
  { narration: "왜 물을 넣을까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A glass" },
  { narration: "애호가들은 물을 몇 방울 넣어요.", claim_ids: ["c1"], visual_role: "reality", visual_prompt: "A glass", timing_sec: 5 },
], notes: "시청자 결론(c1): 물을 조금 넣는 습관이 있다" };

async function researching(): Promise<string> {
  const t = await ok("create_topic", { title: "위스키에 물", question: `위스키에 물을 넣는 이유 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  const v = (await topicRow(t.topic_id)).version;
  await ok("triage", { topic_id: t.topic_id, expected_version: v, scores: SCORES });
  await ok("topic_action", { topic_id: t.topic_id, expected_version: (await topicRow(t.topic_id)).version, action: "start_research" });
  return t.topic_id;
}

/** 출처가 붙은 소재 → [이걸로] 설명형 → 워커가 근거 초안을 저장·성공 → 이어서 대본 요청이 큐에 들어간 상태. */
async function pickAndEvidence(b: Any, format = "explainer") {
  const topic = await researching();
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const pick = await ok("pick_topic", { topic_id: topic, format, editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(pick.chain.kind, "evidence");
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.request_id, pick.chain.request_id);
  assert.equal(g.job.chain, true);
  assert.equal(g.job.format_intent, format);
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const fmt = format === "card" ? "carousel" : "video";
  const claim = (cid: string, quote: string) => ({ claim_id: cid, text: `주장 ${cid}`, claim_type: "process", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: quote }] });
  const save = await rpc("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [claim("c1", QUOTE1), claim("c2", QUOTE2)] },
    brief: { audience_question: "왜 물을 넣나", selected_claim_ids: ["c1", "c2"], proposed_formats: [fmt], required_claims: { [fmt]: ["c1"] } } });
  const fin = await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: { claims_kept: 2 } });
  return { topic, snapshot: s.snapshot_id as string, reviewId: save.review_id as string, evidenceRequest: l.request_id as string, fin };
}

/** 이어진 대본 요청을 워커처럼 처리해 작성 중 대본까지 만든다. */
async function draftPlan(takeaway: string | null = "물을 조금 넣는 습관이 있어요") {
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.kind, "plan");
  assert.equal(g.job.draft_evidence, true);
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const pl = await rpc("drinks_develop_save_plan", { ...l, plan_json: PLAN, ...(takeaway ? { core_takeaway_draft: takeaway } : {}) });
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: {} });
  return { job: g.job, planId: pl.revision_id as string };
}

/** 사람이 내용 승인 화면에서 채우는 칸: 주장별 확인 + 점수. */
async function operatorFills(reviewId: string, topic: string) {
  const r = await reviewRow(reviewId);
  const claims = r.evidence_pack.claims.map((c: Any) => ({ ...c, support_review: "supported" }));
  return ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims }, brief: r.brief, scores: SCORES });
}

async function approvePayload(topic: string, reviewId: string, planId: string, extra: Record<string, unknown> = {}) {
  const [t, r, p] = [await topicRow(topic), await reviewRow(reviewId), await planRow(planId)];
  return { topic_id: topic, expected_topic_version: t.version, review_id: reviewId, expected_review_version: r.version,
    plan_revision_id: planId, expected_plan_version: p.version, approved_amount_usd: 8.9, format_intent: "explainer", ...extra }; // format_intent: 0072 라우트 검증(작업 단위 = 소재 × 형식)
}

test("[이걸로]: 후보 → 소재 올리기 + 임시 점수 옮기기 + 조사 + 형식 의도 + 근거 요청을 한 번에. 돈은 안 나가고 편성은 아직", async () => {
  const c = await row(`insert into drink_discovery_candidates (key_question, signals, fit_video, fit_carousel, provisional_score, score_reason)
    values ('Why does whisky not spoil?', '{question}', 3, 1, 70, '규칙') returning *`);
  const b = await budget();
  await fails("pick_topic", { candidate_id: c.id, expected_version: c.version, format: "weird", editorial_week: WEEK }, "invalid_input");
  const r = await ok("pick_topic", { candidate_id: c.id, expected_version: c.version, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id,
    title: "고도주는 왜 안 상하나", question: `고도주는 왜 안 상할까요 ${uniq()}`, categories: ["whisky"],
    recommended_format: "explainer", recommended_reason: "왜를 묻는다" });
  assert.equal(r.created, true);
  assert.equal(r.maps_to, "video");
  assert.equal(r.editorial_week, MONDAY, "그 주 월요일로 맞춘다");
  assert.equal(r.chain.queued, true);
  assert.equal(r.chain.kind, "evidence");
  const t = await topicRow(r.topic_id);
  assert.equal(t.status, "researching", "편성(selected)은 승인 때 일어난다");
  assert.equal(t.selected_formats, null);
  assert.equal(Number(t.provisional_score), 70);
  assert.equal(t.provisional_rubric, "discovery-v1", "후보 점수임이 남는다");
  assert.deepEqual(t.provisional_scores, { fit_video: 3, fit_carousel: 1 }, "모르는 축을 지어내지 않는다");
  const pk = await row("select * from drink_topic_picks where topic_id = $1", [t.id]);
  assert.equal(pk.format_intent, "explainer");
  assert.equal(pk.recommended_format, "explainer");
  assert.equal(pk.candidate_id, c.id);
  assert.equal((await row("select status from drink_discovery_candidates where id = $1", [c.id])).status, "promoted");
  assert.equal((await row("select count(*)::int n from drink_develop_holds h join drink_develop_requests q on q.id = h.request_id where q.topic_id = $1", [t.id])).n, 0, "돈은 나가지 않았다");
  await rpc("drinks_cancel_develop", { request_id: r.chain.request_id });

  // 점수 없는 후보는 멈추고 이유를 말한다 / 사람이 쓴 제목·질문이 없으면 올리지 않는다
  const noScore = await row(`insert into drink_discovery_candidates (key_question) values ('how?') returning *`);
  await fails("pick_topic", { candidate_id: noScore.id, expected_version: noScore.version, format: "card", editorial_week: WEEK, title: "x", question: `q ${uniq()}`, categories: ["sake"] }, "scores_incomplete");
  const c2 = await row(`insert into drink_discovery_candidates (key_question, provisional_score) values ('how?', 50) returning *`);
  await fails("pick_topic", { candidate_id: c2.id, expected_version: c2.version, format: "card", editorial_week: WEEK, categories: ["sake"] }, "invalid_input");
  assert.equal((await row("select status from drink_discovery_candidates where id = $1", [c2.id])).status, "suggested", "실패하면 아무것도 바뀌지 않는다");
});

test("이어 만들기: 근거 성공 → 같은 트랜잭션에서 대본 요청 → 승인 전 근거로 초안 저장(표시됨) → 근거·대본은 초안 그대로", async () => {
  const b = await budget();
  const { topic, reviewId, evidenceRequest, fin } = await pickAndEvidence(b);
  assert.equal(fin.result.chain[0].queued, true);
  const planReq = await reqRow(fin.result.chain[0].request_id);
  assert.equal(planReq.kind, "plan");
  assert.equal(planReq.draft_evidence, true);
  assert.equal(planReq.budget_id, b.budget_id, "같은 결재를 쓴다");
  assert.equal(planReq.review_id, reviewId);
  assert.equal((await reqRow(evidenceRequest)).status, "succeeded");
  const { job, planId } = await draftPlan();
  assert.equal(job.review.status, "draft");
  assert.deepEqual(job.review.claims.map((c: Any) => c.claim_id), ["c1", "c2"], "쓸 주장 고르는 규칙은 같다(selected_claim_ids)");
  const plan = await planRow(planId);
  assert.equal(plan.plan_status, "draft");
  assert.equal(plan.drafted_from_unapproved, true);
  assert.equal(plan.topic_review_id, reviewId);
  const rv = await reviewRow(reviewId);
  assert.equal(rv.status, "draft", "워커는 근거를 승인·제출하지 않는다");
  assert.equal(rv.brief.core_takeaway, "물을 조금 넣는 습관이 있어요", "핵심 메시지는 초안으로 채운다");
  for (const c of rv.evidence_pack.claims) assert.equal(c.support_review, "not_reviewed", "주장별 확인은 자동으로 채우지 않는다");
  assert.equal((await topicRow(topic)).status, "researching");
  // 표시를 고칠 수 없다
  await assert.rejects(db.query("update drink_plan_revisions set drafted_from_unapproved = false where id = $1", [planId]), /drinks:immutable:/);
});

test("다시 고르기: 작성 중 근거가 있으면 그 근거로 대본만 잇고, 대본까지 있으면 새로 만들지 않는다. 근거가 모자라 멈춰도 대본은 없다", async () => {
  const b = await budget();
  const topic = await researching();
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  // 근거 부족으로 멈춘 경우(워커가 저장 없이 blocked 로 끝낸다) → 이어지지 않는다
  await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  const g0 = await rpc("drinks_start_develop", { worker_id: "t" });
  const fin0 = await rpc("drinks_finish_develop", { request_id: g0.job.request_id, lease_token: g0.job.lease_token, outcome: "blocked", error_code: "evidence_insufficient", error_message: "근거 1건" });
  assert.equal(fin0.status, "blocked");
  assert.equal(fin0.result.chain, undefined);
  assert.equal((await row("select count(*)::int n from drink_develop_requests where topic_id = $1 and kind = 'plan'", [topic])).n, 0);
  // 근거 탭에서 손으로 만든 초안이 있으면 그 근거로 대본만 잇는다
  const sv = await ok("save_review", { topic_id: topic, expected_topic_version: (await topicRow(topic)).version,
    evidence_pack: { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: QUOTE1 }] }] },
    brief: { audience_question: "왜", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } } });
  const again = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(again.chain.kind, "plan");
  assert.equal((await reqRow(again.chain.request_id)).review_id, sv.review_id);
  const { planId } = await draftPlan();
  assert.equal((await planRow(planId)).drafted_from_unapproved, true);
  const third = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: "2026-11-09", budget_id: b.budget_id });
  assert.equal(third.chain.queued, false);
  assert.equal(third.chain.code, "already_drafted");
  assert.equal(third.editorial_week, "2026-11-09", "주차는 바꿀 수 있다");
  // 검토 중 근거가 있으면 고르기 전에 정리하게 한다
  const r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  await fails("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id }, "review_in_progress");
  // 상태가 바뀌면 큐에 있던 승인 전 대본 요청은 시작하지 않는다
  const t2 = await researching();
  const s2 = await ok("add_source", { topic_id: t2, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  await ok("save_review", { topic_id: t2, expected_topic_version: (await topicRow(t2)).version,
    evidence_pack: { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", source_refs: [{ snapshot_id: s2.snapshot_id, original_quote: QUOTE1 }] }] },
    brief: { audience_question: "왜", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } } });
  const q = await ok("pick_topic", { topic_id: t2, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  const rv = await row("select * from drink_topic_reviews where topic_id = $1", [t2]);
  await ok("review_action", { review_id: rv.id, expected_version: rv.version, action: "submit" });
  assert.equal((await rpc("drinks_start_develop", { worker_id: "t" })).job, null);
  const stopped = await reqRow(q.chain.request_id);
  assert.equal(stopped.status, "canceled");
  assert.equal(stopped.error_code, "review_changed");
});

test("[승인] 한 번: 근거·편성·대본이 함께 승인되고, 설명형은 전용 제작 전까지 옛 렌더로 못 간다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  const hashBefore = (await planRow(planId)).input_hash;
  const res = await ok("approve_content", await approvePayload(topic, reviewId, planId));
  assert.equal(res.status, "selected");
  assert.equal(res.review_status, "approved");
  assert.equal(res.plan_status, "approved");
  assert.deepEqual(res.selected_formats, ["video"]);
  assert.equal(res.editorial_week, MONDAY);
  const t = await topicRow(topic);
  assert.equal(t.approved_review_id, reviewId);
  assert.equal(t.selected_review_id, reviewId);
  const plan = await planRow(planId);
  assert.equal(plan.approved_hash, plan.input_hash);
  assert.notEqual(plan.input_hash, hashBefore, "사람이 채운 칸이 들어간 승인 근거를 기준으로 다시 잰다");
  assert.equal((await reviewRow(reviewId)).approved_hash, (await reviewRow(reviewId)).input_hash);
  const logged = await row("select detail from drink_workflow_events where topic_id = $1 and action = 'content_approved'", [topic]);
  assert.equal(logged.detail.spend_approval_opened, false);
  assert.equal(Number((await row("select approved_amount_usd from drink_topic_picks where topic_id = $1", [topic])).approved_amount_usd), 8.9);
  assert.equal((await row("select count(*)::int n from drink_spend_approvals where plan_revision_id = $1", [planId])).n, 0, "승인은 지출 결재를 열지 않는다");
  assert.equal((await row("select count(*)::int n from drink_production_jobs where plan_revision_id = $1", [planId])).n, 0, "승인은 제작을 시작하지 않는다");
  // 승인해도 옛 그림 나열식 렌더 큐에는 못 들어간다(설명형은 전부 영상, 사진 대체 금지). 0067 부터 표 트리거가 막는다.
  await fails("request_render", { plan_revision_id: planId }, "not_renderable");
  assert.equal((await row("select count(*)::int n from drink_production_jobs where plan_revision_id = $1", [planId])).n, 0);
  assert.equal((await row("select drinks_plan_is_explainer($1) as v", [planId])).v, true);
  // 두 번 승인할 수 없다
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "invalid_state");
});

test("하나라도 무효면 아무것도 승인되지 않는다 — 소재·근거·대본 전부 그대로", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  /** 실패한 승인 뒤: 소재·근거·대본의 내용과 버전이 그대로이고, 승인 이력이 하나도 남지 않았다. */
  const snapshot = async () => ({ t: await topicRow(topic), r: await reviewRow(reviewId), p: await planRow(planId),
    events: (await row("select count(*)::int n from drink_workflow_events where topic_id = $1", [topic])).n });
  const unchanged = async (before: Any) => {
    const after = await snapshot();
    assert.equal(after.t.status, "researching");
    assert.equal(after.t.approved_review_id, null);
    assert.equal(after.t.selected_review_id, null);
    assert.equal(after.t.version, before.t.version);
    assert.equal(after.r.status, "draft");
    assert.equal(after.r.version, before.r.version);
    assert.equal(after.r.approved_hash, null);
    assert.equal(after.p.plan_status, "draft");
    assert.equal(after.p.version, before.p.version);
    assert.equal(after.p.input_hash, before.p.input_hash, "제작안 해시를 다시 잰 것도 되돌아간다");
    assert.equal(after.events, before.events, "이력도 함께 되돌아간다");
    assert.equal((await row("select approved_at from drink_topic_picks where topic_id = $1", [topic])).approved_at, null);
  };
  // ① 근거 쪽은 멀쩡한데 안쪽 세 번째 단계(대본 승인)가 필수 주장을 전달하지 않아 실패 — 앞 단계도 되돌아가야 한다.
  // 대본의 사실 장면에서 주장 연결을 뺀 것을 직접 넣어 만든다(작성 중이라 본문 수정 가능).
  await db.query(`update drink_plan_revisions set plan_json = jsonb_set(plan_json, '{scenes,1,claim_ids}', '[]'::jsonb) where id = $1`, [planId]);
  let before = await snapshot();
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "plan_coverage");
  await unchanged(before);
  await db.query(`update drink_plan_revisions set plan_json = jsonb_set(plan_json, '{scenes,1,claim_ids}', '["c1"]'::jsonb) where id = $1`, [planId]);
  // ② 편성 단계가 실패(65점 미달, 예외 사유 없음)
  const r0 = await reviewRow(reviewId);
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r0.version, scores: { ...SCORES, relevance: 0, utility: 0, curiosity: 0 } });
  before = await snapshot();
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "below_threshold");
  await unchanged(before);
  // ③ 근거 필수 조건 실패는 이유를 돌려준다
  const r1 = await reviewRow(reviewId);
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r1.version, scores: SCORES,
    brief: { ...r1.brief, core_takeaway: null } });
  before = await snapshot();
  const blocked = await fails("approve_content", await approvePayload(topic, reviewId, planId), "review_blocked");
  assert.ok((blocked.detail as string[]).includes("brief_takeaway_missing"));
  await unchanged(before);
  // ④ 화면이 본 버전과 다르면 거부(version_conflict)
  await fails("approve_content", { ...(await approvePayload(topic, reviewId, planId)), expected_review_version: 1 }, "version_conflict");
  // ⑤ 금액이 없거나 상한 초과
  await fails("approve_content", await approvePayload(topic, reviewId, planId, { approved_amount_usd: 10.5 }), "invalid_input");
  const noAmount = await approvePayload(topic, reviewId, planId);
  delete (noAmount as Record<string, unknown>).approved_amount_usd;
  await fails("approve_content", noAmount, "invalid_input");
  await unchanged(before);
});

test("주장별 확인이 안 끝나면 승인되지 않는다 — 자동으로 채우지 않는다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  const r = await reviewRow(reviewId);
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, scores: SCORES });
  const blocked = await fails("approve_content", await approvePayload(topic, reviewId, planId), "review_blocked");
  assert.ok((blocked.detail as string[]).includes("claim_support_not_reviewed:c1"), JSON.stringify(blocked.detail));
  assert.ok((blocked.detail as string[]).includes("claim_support_not_reviewed:c2"));
  // 하나만 하면 나머지가 막는다
  const r2 = await reviewRow(reviewId);
  const one = r2.evidence_pack.claims.map((c: Any) => (c.claim_id === "c1" ? { ...c, support_review: "supported" } : c));
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r2.version, evidence_pack: { claims: one } });
  const again = await fails("approve_content", await approvePayload(topic, reviewId, planId), "review_blocked");
  assert.deepEqual(again.detail, ["claim_support_not_reviewed:c2"]);
  assert.equal((await reviewRow(reviewId)).status, "draft");
});

test("근거를 고치면 대본이 무효가 되고, 다시 만들어야 승인된다. 주장별 확인·핵심 메시지·점수는 무효로 치지 않는다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  assert.equal((await planRow(planId)).blocked_at, null, "사람이 채우는 칸은 대본을 무효로 만들지 않는다");
  let r = await reviewRow(reviewId);
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, brief: { ...r.brief, core_takeaway: "다른 말로 고쳤어요" } });
  assert.equal((await planRow(planId)).blocked_at, null, "핵심 메시지 고치기도 마찬가지다");

  // 주장 문장을 고친다
  r = await reviewRow(reviewId);
  const edited = r.evidence_pack.claims.map((c: Any) => (c.claim_id === "c2" ? { ...c, text: "고친 주장" } : c));
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims: edited } });
  const stale = await planRow(planId);
  assert.ok(stale.blocked_at, "대본이 차단된다");
  assert.match(stale.blocked_reason, /^evidence_edited:/);
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "plan_blocked");
  assert.equal((await reviewRow(reviewId)).status, "draft");
  // 차단은 풀 수 없다
  await assert.rejects(db.query("update drink_plan_revisions set blocked_at = null, blocked_reason = null where id = $1", [planId]), /drinks:immutable:/);

  // 다시 만들면 승인된다
  const q = await ok("request_develop", { topic_id: topic, kind: "plan", format_intent: "explainer", draft_evidence: true, budget_id: b.budget_id });
  assert.equal(q.draft_evidence, true);
  const { planId: planId2 } = await draftPlan();
  assert.notEqual(planId2, planId);
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "plan_not_current");
  const res = await ok("approve_content", await approvePayload(topic, reviewId, planId2));
  assert.equal(res.plan_status, "approved");
  assert.equal((await planRow(planId)).plan_status, "draft", "무효가 된 옛 대본은 그대로 차단된 채 남는다");
});

test("승인 직전 값 대조: 대본이 기댄 근거가 지금 승인하는 근거와 다르면 막는다(트리거가 빠져도, 근거 버전이 바뀌어도)", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  // 차단 트리거를 지나지 않고 근거가 바뀐 경우
  const orig = (await reviewRow(reviewId)).evidence_pack;
  await db.exec("alter table drink_topic_reviews disable trigger drink_review_evidence_edited");
  try {
    await db.query(`update drink_topic_reviews set evidence_pack = jsonb_set(evidence_pack, '{claims,0,text}', '"몰래 고침"'::jsonb) where id = $1`, [reviewId]);
    assert.equal((await planRow(planId)).blocked_at, null);
    await fails("approve_content", await approvePayload(topic, reviewId, planId), "plan_stale");
    assert.equal((await reviewRow(reviewId)).status, "draft");
    await db.query(`update drink_topic_reviews set evidence_pack = $2::jsonb where id = $1`, [reviewId, JSON.stringify(orig)]);
  } finally {
    await db.exec("alter table drink_topic_reviews enable trigger drink_review_evidence_edited");
  }
  // 변경 요청 → 새 근거 버전: 옛 버전으로 쓴 대본은 승인되지 않고, 새로 만들 자리를 비운다
  let r = await reviewRow(reviewId);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(reviewId);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "request_changes", reason: "다시" });
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "invalid_state");
  const sv = await ok("save_review", { topic_id: topic, expected_topic_version: (await topicRow(topic)).version });
  assert.notEqual(sv.review_id, reviewId);
  await fails("approve_content", await approvePayload(topic, sv.review_id, planId), "plan_stale");
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "review_not_current");
  await ok("request_develop", { topic_id: topic, kind: "plan", format_intent: "explainer", draft_evidence: true, budget_id: b.budget_id });
  assert.match((await planRow(planId)).blocked_reason, /^evidence_edited:/, "옛 근거의 대본은 차단된다");
  const { planId: fresh } = await draftPlan();
  const res = await ok("approve_content", await approvePayload(topic, sv.review_id, fresh));
  assert.equal(res.review_id, sv.review_id);
  assert.equal(res.plan_status, "approved");
});

test("대본을 쓰는 사이 근거가 바뀌면 저장을 거부하고, 쓰던 워커에게 취소를 건다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const r = await reviewRow(reviewId);
  const edited = r.evidence_pack.claims.map((c: Any) => (c.claim_id === "c1" ? { ...c, text: "고친 주장" } : c));
  // 0076: 화면 저장은 이제 서버가 거절한다(쓰는 중인 결과와 부딪히지 않게). 다른 길(직접 update)로 고쳐도 아래 트리거가 취소를 건다.
  await fails("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims: edited } }, "develop_in_progress");
  assert.equal((await rpc("drinks_heartbeat_develop", l)).cancel_requested, false);
  await db.query(`update drink_topic_reviews set evidence_pack = $2::jsonb where id = $1`, [reviewId, JSON.stringify({ ...r.evidence_pack, claims: edited })]);
  assert.equal((await rpc("drinks_heartbeat_develop", l)).cancel_requested, true);
  await rpcFails("drinks_develop_save_plan", { ...l, plan_json: PLAN }, "canceled");
  await rpc("drinks_finish_develop", { ...l, outcome: "failed", error_code: "canceled" });
  assert.equal((await reqRow(l.request_id)).status, "canceled");

  // 취소를 놓친 경우에도(값 대조) 저장되지 않는다
  await ok("request_develop", { topic_id: topic, kind: "plan", format_intent: "explainer", draft_evidence: true, budget_id: b.budget_id });
  const g2 = await rpc("drinks_start_develop", { worker_id: "t" });
  const l2 = { request_id: g2.job.request_id, lease_token: g2.job.lease_token };
  await db.query("update drink_develop_requests set evidence_hash = 'stale' where id = $1 and evidence_hash is null", [l2.request_id]);
  const r2 = await reviewRow(reviewId);
  await db.query(`alter table drink_topic_reviews disable trigger drink_review_evidence_edited`);
  try {
    await db.query(`update drink_topic_reviews set evidence_pack = jsonb_set(evidence_pack, '{claims,0,text}', '"또 고침"'::jsonb) where id = $1`, [r2.id]);
  } finally {
    await db.query(`alter table drink_topic_reviews enable trigger drink_review_evidence_edited`);
  }
  await rpcFails("drinks_develop_save_plan", { ...l2, plan_json: PLAN }, "review_changed");
  await rpc("drinks_finish_develop", { ...l2, outcome: "failed", error_code: "review_changed" });
});

test("승인 전 대본은 제작·지출로 넘어갈 수 없다 — 어떤 길로도", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  const r = await fails("request_render", { plan_revision_id: planId }, "not_renderable");
  assert.match(r.error, /승인된 제작안만/);
  await fails("request_render", { plan_revision_id: planId, paid: true }, "not_renderable");
  assert.equal((await row("select count(*)::int n from drink_production_jobs where plan_revision_id = $1", [planId])).n, 0);
  // 제출·승인 함수도 근거가 승인되지 않으면 막는다
  const p = await planRow(planId);
  await fails("plan_action", { revision_id: planId, expected_version: p.version, action: "submit" }, "format_not_selected");
  // 표를 직접 바꿔도 막는다(트리거)
  await assert.rejects(db.query("update drink_plan_revisions set plan_status = 'in_review' where id = $1", [planId]), /drinks:review_not_approved:/);
  // 근거가 승인되지 않은 채로는 편성도 안 된다
  await db.query("update drink_topics set status = 'ready' where id = $1 and status = 'researching'", [topic]);
  await assert.rejects(db.query("update drink_topics set status = 'selected', selected_review_id = $2, selected_formats = '{video}', editorial_week = '2026-11-02' where id = $1", [topic, reviewId]),
    /drinks:review_not_approved:/);
  await db.query("update drink_topics set status = 'researching' where id = $1", [topic]);
  // 렌더 가능 판정 자체가 거부한다
  assert.equal((await row("select drinks_plan_renderable($1) as v", [planId])).v, "plan_not_approved");
  // 승인 함수 안쪽을 거치지 않으면 approved 로 만들 수 없다
  await assert.rejects(db.query("update drink_plan_revisions set plan_status = 'approved', approved_hash = input_hash where id = $1", [planId]), /drinks:invalid_transition:/);
});

test("결재가 없으면 이어 만들기가 멈춘다 — 모델을 못 부르고 대본 요청도 들어가지 않는다", async () => {
  const topic = await researching();
  await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const pick = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK });
  assert.equal(pick.chain.queued, true, "큐에는 들어가지만 워커가 모델 호출을 거부한다(0060 규칙 그대로)");
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.budget_id, null);
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  await rpcFails("drinks_develop_hold", { ...l, est_usd: 0.01, model: "m" }, "budget_missing");
  await rpc("drinks_finish_develop", { ...l, outcome: "blocked", error_code: "budget_missing", error_message: "결재 없음" });
  assert.equal((await row("select count(*)::int n from drink_develop_requests where topic_id = $1 and kind = 'plan'", [topic])).n, 0);
  const st = await rpc("drinks_develop_status", { topic_id: topic });
  assert.equal(st.requests[0].error_code, "budget_missing");
  assert.equal(st.pick.format_intent, "explainer");
  // 승인 전 근거로 대본을 직접 요청해도 결재가 있어야 한다
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", draft_evidence: true }, "budget_missing");
  // 결재를 열고 다시 고르면 멈춘 곳부터 이어 간다
  const open = await budget(1);
  const again = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: open.budget_id });
  assert.equal(again.chain.kind, "evidence");
  assert.equal(again.chain.existing, false);
  assert.equal((await reqRow(again.chain.request_id)).chain, true);
  await rpc("drinks_cancel_develop", { request_id: again.chain.request_id });
  // 결재가 근거 뒤에 닫혀도 대본에 쓰지 않고 멈춘다
  const b = await budget(1);
  const { fin } = await (async () => {
    const t2 = await researching();
    const s = await ok("add_source", { topic_id: t2, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
    await ok("pick_topic", { topic_id: t2, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
    const g2 = await rpc("drinks_start_develop", { worker_id: "t" });
    const l2 = { request_id: g2.job.request_id, lease_token: g2.job.lease_token };
    await rpc("drinks_develop_save_evidence", { ...l2, evidence_pack: { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: QUOTE1 }] }] },
      brief: { audience_question: "왜", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } } });
    await rpc("drinks_close_develop_budget", { budget_id: b.budget_id, reason: "닫음" });
    return { fin: await rpc("drinks_finish_develop", { ...l2, outcome: "succeeded", result: {} }) };
  })();
  assert.equal(fin.status, "succeeded", "근거 초안 자체는 성공이다");
  assert.equal(fin.result.chain[0].queued, false);
  assert.equal(fin.result.chain[0].code, "approval_closed");
  assert.match(fin.result.chain[0].message, /닫힌 결재/);
});

test("근거에 돈 쓰기 전에 고칠 곳이 있으면 이어 만들지 않고 이유를 남긴다 / 카드뉴스·밈은 조용히 건너뛰지 않고 멈춘다", async () => {
  const b = await budget();
  // 원문에 없는 인용(핵심 주장) → 대본 요청 없음
  const topic = await researching();
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const saved = await rpc("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "not in the source at all, this phrase" }] }] },
    brief: { audience_question: "왜", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } } });
  const fin = await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: {} });
  assert.equal(fin.result.chain[0].queued, false);
  assert.equal(fin.result.chain[0].code, "evidence_not_usable");
  assert.deepEqual(fin.result.chain[0].blockers, ["claim_quote_unmatched:c1"]);
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", draft_evidence: true, budget_id: b.budget_id }, "evidence_not_usable");
  assert.equal(saved.quote_check.unmatched, 1);

  // 카드뉴스: 0065 부터 대본까지 이어 간다(자세한 것은 cardReel.db.test.ts)
  const card = await pickAndEvidence(b, "card");
  assert.equal(card.fin.result.chain[0].queued, true);
  const rv = await reviewRow(card.reviewId);
  assert.deepEqual(rv.brief.proposed_formats, ["carousel"]);
  await rpc("drinks_cancel_develop", { request_id: card.fin.result.chain[0].request_id });

  // 밈: 모델을 부르지 않는다. 의도만 적고 이유를 돌려준다
  const memeTopic = await researching();
  const m = await ok("pick_topic", { topic_id: memeTopic, format: "meme", editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(m.maps_to, null, "밈은 영상·카드 어느 쪽으로도 편성되지 않는다");
  assert.equal(m.chain.queued, false);
  assert.equal(m.chain.code, "meme_board");
  assert.equal((await row("select count(*)::int n from drink_develop_requests where topic_id = $1", [memeTopic])).n, 0);
  assert.equal((await rpc("drinks_start_develop", { worker_id: "t" })).job, null);
  // 형식 대응: selected_formats 의 옛 값은 그대로다
  assert.equal((await row("select drinks_intent_format('explainer') v")).v, "video");
  assert.equal((await row("select drinks_intent_format('card') v")).v, "carousel");
  assert.equal((await row("select drinks_intent_format('meme') v")).v, null);
  await assert.rejects(db.query("update drink_topics set selected_formats = '{meme}' where id = $1", [memeTopic]), /check constraint/);
});

test("한 번 승인은 고른 형식의 표시된 대본만 받는다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  // 0072: 카드를 더하면 카드 대본 요청이 따로 들어간다(설명형 선택은 그대로). 설명형 대본을 카드 형식으로 승인할 수는 없다.
  const addCard = await ok("pick_topic", { topic_id: topic, format: "card", editorial_week: WEEK, budget_id: b.budget_id });
  await fails("approve_content", await approvePayload(topic, reviewId, planId, { format_intent: "card" }), "format_not_selected");
  await rpc("drinks_cancel_develop", { request_id: addCard.chain.request_id });
  await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  // 다른 소재의 근거·대본은 받지 않는다
  const other = await researching();
  await fails("approve_content", await approvePayload(other, reviewId, planId), "ownership");
  // 초안을 만드는 중이면 승인하지 않는다
  const active = await row(`insert into drink_develop_requests (topic_id, kind) values ($1, 'evidence') returning id`, [topic]);
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "develop_in_progress");
  await rpc("drinks_cancel_develop", { request_id: active.id });
  // 옛 흐름 대본(표시 없음)은 받지 않는다 — 표시를 벗겨 흉내 낼 수 없으므로 새 소재로 잰다: 작성 중 대본이 없으면 소유·상태에서 막힌다
  await fails("approve_content", { ...(await approvePayload(topic, reviewId, planId)), plan_revision_id: "00000000-0000-0000-0000-000000000000" }, "ownership");
  await ok("approve_content", await approvePayload(topic, reviewId, planId));
});

test("기존 소재의 두 단계 흐름은 그대로다 — 표시 없는 대본 요청은 승인된 근거를 요구한다", async () => {
  const b = await budget();
  const topic = await researching();
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const brief = { audience_question: "왜 물을 넣나", core_takeaway: "물을 조금 타면 향이 산다", selected_claim_ids: ["c1"],
    proposed_formats: ["video"], required_claims: { video: ["c1"] } };
  const pack = { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", support_review: "supported", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: QUOTE1 }] }] };
  const sv = await ok("save_review", { topic_id: topic, expected_topic_version: (await topicRow(topic)).version, scores: SCORES, brief, evidence_pack: pack });
  // ★ 0060 규칙 그대로
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id }, "review_not_approved");
  // 표시를 달아도 [이걸로]를 안 눌렀으면 승인 전 근거를 쓰지 못한다
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id, draft_evidence: true }, "format_not_selected");
  let r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await reviewRow(sv.review_id);
  assert.equal((await topicRow(topic)).status, "ready");
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id }, "format_not_selected");
  await ok("select", { topic_id: topic, expected_version: (await topicRow(topic)).version, review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["video"], editorial_week: MONDAY });
  const q = await rpc("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id });
  assert.equal(q.draft_evidence, false);
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.draft_evidence, false);
  assert.equal(g.job.review.status, "approved");
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const pl = await rpc("drinks_develop_save_plan", { ...l, plan_json: PLAN });
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: {} });
  let p = await planRow(pl.revision_id);
  assert.equal(p.drafted_from_unapproved, false, "옛 흐름 대본에는 표시가 없다");
  assert.equal(p.plan_status, "draft");
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" });
  p = await planRow(p.id);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "approve" });
  assert.equal((await planRow(p.id)).plan_status, "approved");
  assert.ok((await ok("request_render", { plan_revision_id: p.id })).job_id);
  // 0072: 근거가 승인된 소재에도 형식을 더할 수 있다(G4) — 승인된 근거로 일반 대본 요청이 들어간다. 이미 승인된 대본을 한 번 승인으로 다시 승인할 수는 없다.
  const late = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(late.status, "selected");
  assert.equal(late.chain.kind, "plan");
  assert.equal((await reqRow(late.chain.request_id)).draft_evidence, false, "승인된 근거를 쓴다");
  await rpc("drinks_cancel_develop", { request_id: late.chain.request_id });
  await fails("approve_content", await approvePayload(topic, r.id, p.id), "invalid_state");
  // 예전 근거 초안 요청(표시 없음)도 그대로 — 성공해도 이어지지 않는다
  const t2 = await researching();
  const s2 = await ok("add_source", { topic_id: t2, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const q2 = await rpc("drinks_request_develop", { topic_id: t2, kind: "evidence", budget_id: b.budget_id });
  assert.equal(q2.chain, false);
  const g2 = await rpc("drinks_start_develop", { worker_id: "t" });
  const l2 = { request_id: g2.job.request_id, lease_token: g2.job.lease_token };
  await rpc("drinks_develop_save_evidence", { ...l2, evidence_pack: { claims: [{ claim_id: "c1", text: "주장", claim_type: "process", source_refs: [{ snapshot_id: s2.snapshot_id, original_quote: QUOTE1 }] }] },
    brief: { audience_question: "왜", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } } });
  const fin = await rpc("drinks_finish_develop", { ...l2, outcome: "succeeded", result: {} });
  assert.equal(fin.result.chain, undefined);
  assert.equal((await rpc("drinks_start_develop", { worker_id: "t" })).job, null, "이어지는 요청이 없다");
});

test("기존 탭으로 승인해도 앞뒤가 맞는다 — 이어 만든 대본은 근거 승인·편성 뒤 평소처럼 승인된다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  let r = await reviewRow(reviewId);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(reviewId);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await reviewRow(reviewId);
  await ok("select", { topic_id: topic, expected_version: (await topicRow(topic)).version, review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["video"], editorial_week: MONDAY });
  let p = await planRow(planId);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" });
  p = await planRow(planId);
  await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "approve" });
  assert.equal((await planRow(planId)).plan_status, "approved");
  // 승인돼도 설명형은 옛 그림 나열식 렌더로 못 간다(사진 대체 금지). 0067 부터 표 트리거가 막는다.
  assert.equal((await row("select drinks_plan_is_explainer($1) as v", [planId])).v, true);
  await fails("request_render", { plan_revision_id: planId }, "not_renderable");
});

test("근거 검토 중(옛 탭에서 제출)이어도 한 번 승인이 이어받는다 / 근거 승인이 철회되면 그 대본은 제작으로 못 간다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickAndEvidence(b);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  const r = await reviewRow(reviewId);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  const res = await ok("approve_content", await approvePayload(topic, reviewId, planId));
  assert.equal(res.status, "selected");
  // 철회 → 대본 차단 → 제작 불가(0050·0053 규칙 그대로)
  const a = await reviewRow(reviewId);
  await ok("review_action", { review_id: a.id, expected_version: a.version, action: "revoke", reason: "시험" });
  assert.ok((await planRow(planId)).blocked_at);
  assert.equal((await row("select drinks_plan_renderable($1) as v", [planId])).v, "plan_blocked");
});

test("후보별 근거 개수: 승인된 수집원의 공식·전문 글만, 질문 낱말이 걸리는 것만. anon 은 새 함수·표를 못 쓴다", async () => {
  // 수집원 글을 직접 넣는다(수집 흐름은 collect.db.test.ts 가 잰다). 스냅샷 수집 표시는 수집 경로의 설정으로만 켜진다.
  await db.exec("alter table drink_sources disable trigger drink_sources_guard");
  const source = async (kind: string, terms: string, state: string) => (await row(`insert into drink_sources (name, home_url, language, categories, source_kind, method, entry_urls, allowed_hosts, terms_status, state)
    values ('수집원', $1, 'en', '{whisky}', $2, 'feed', $3, '{example.org}', $4, $5) returning id`, [`https://example.org/${uniq()}`, kind, [`https://example.org/${uniq()}.xml`], terms, state])).id as string;
  const official = await source("official", "verified", "active");
  const shop = await source("retailer", "verified", "active");
  const unverified = await source("official", "unverified", "validated");
  await db.exec("alter table drink_sources enable trigger drink_sources_guard");
  const runs = new Map<string, string>();
  const doc = async (sid: string, kind: string, body: string, rights = "quote_ok") => {
    if (!runs.has(sid)) runs.set(sid, (await row(`insert into drink_collection_runs (source_id, mode, requested_by) values ($1, 'collect', 'operator') returning id`, [sid])).id);
    const run = { id: runs.get(sid) };
    await db.exec("set drinks.capture = 'collected'");
    await db.query(`insert into drink_source_snapshots (canonical_url, title, source_kind, depth, body_text, rights_status, collected_source_id, collected_run_id)
      values ($1, '글', $2, 'full_text', $3, $4, $5, $6)`, [`https://example.org/${uniq()}`, kind, body, rights, sid, run.id]);
    await db.exec("set drinks.capture = ''");
  };
  const smoky = "peated whisky is smoky because of phenols ".repeat(5);
  await doc(official, "official", smoky);
  await doc(official, "official", smoky + " more");
  await doc(official, "official", "nothing relevant here at all");
  await doc(official, "official", smoky, "restricted");
  await doc(shop, "retailer", smoky);
  await doc(unverified, "official", smoky);
  const c1 = await row(`insert into drink_discovery_candidates (key_question, provisional_score) values ('Why is peated whisky smoky?', 60) returning id`);
  const c2 = await row(`insert into drink_discovery_candidates (key_question, provisional_score) values ('zzzz qqqq', 60) returning id`);
  const counts = await rpc("drinks_candidate_evidence_counts", { candidate_ids: [c1.id, c2.id] });
  assert.deepEqual(counts[c2.id], { count: 0, chars: 0 }, "안 걸리면 0 — 못 쟀다는 뜻이 아니다");
  assert.equal(counts[c1.id].count, 2, "공식·확인된 수집원의, 낱말이 걸리고 사용 가능한 글만 센다");
  assert.equal(counts[c1.id].chars, smoky.length * 2 + " more".length);
  assert.deepEqual(await rpc("drinks_candidate_evidence_counts", { candidate_ids: [] }), {}, "빈 요청은 빈 답");
  await db.exec("set role anon");
  try {
    await assert.rejects(db.query("select * from drink_topic_picks"), /permission denied/);
    await assert.rejects(db.query("select drinks_pick_topic('{}'::jsonb)"), /permission denied/);
    await assert.rejects(db.query("select drinks_approve_content('{}'::jsonb)"), /permission denied/);
    await assert.rejects(db.query("select drinks_candidate_evidence_counts('{}'::jsonb)"), /permission denied/);
  } finally {
    await db.exec("reset role");
  }
});

test("워커 함수는 승인·제출·편성 함수를 부르지 않는다(소스 검사) — 부르는 곳은 운영자 함수 하나뿐", () => {
  const sql = readFileSync(join(DIR, "0064_drinks_single_approval.sql"), "utf8");
  const bodies = sql.split("create or replace function ").slice(1).map((b) => ({ name: b.split("(")[0], body: b.split("$$;")[0] }));
  for (const f of bodies) {
    if (f.name === "drinks_approve_content" || f.name === "drinks_pick_topic") continue;
    for (const forbidden of ["drinks_review_action", "drinks_plan_action", "drinks_select(", "drinks_approve_content"]) {
      assert.ok(!f.body.includes(forbidden), `${f.name} 은 ${forbidden} 를 부르면 안 된다`);
    }
  }
  // [이걸로]는 승인·편성을 하지 않는다(조사 시작만)
  const pick = bodies.find((f) => f.name === "drinks_pick_topic")!;
  for (const forbidden of ["drinks_review_action", "drinks_plan_action", "drinks_select(", "drinks_approve_content"]) {
    assert.ok(!pick.body.includes(forbidden), `[이걸로]는 ${forbidden} 를 부르면 안 된다`);
  }
  // 모든 표·함수를 잠근다
  assert.ok(sql.includes("revoke all on table drink_topic_picks from anon, authenticated"));
});
