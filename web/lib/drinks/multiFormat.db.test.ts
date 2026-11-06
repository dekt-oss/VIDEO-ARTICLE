// 한 소재·여러 형식(0072) DB 통합 테스트 — PGlite 위에 00(5x|6x|7x)_drinks_*. 작업명세서 §4 사례. 모델·네트워크 호출 0.
// 운영자 동작은 라우트와 같은 runDrinksAction 경로(허용 목록·payload 검증 포함), 워커 함수는 rpc 직접.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0072_drinks_multi_format.sql"), "0072 가 목록에 있어야 한다");
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
const rows = async (sql: string, params: unknown[] = []): Promise<Any[]> => (await db.query(sql, params)).rows;
const uniq = () => Math.random().toString(36).slice(2);

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 2, timeliness: 2 };
const QUOTE1 = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";
const QUOTE2 = "the smoky flavour is attributed to phenols, and in particular guaiacol";
const BODY = `${QUOTE1} in order to further enhance the taste. Chemically, ${QUOTE2}.`;
const WEEK = "2026-11-04";
const MONDAY = "2026-11-02";
const VIDEO_PLAN = { scenes: [
  { narration: "왜 물을 넣을까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A glass" },
  { narration: "애호가들은 물을 몇 방울 넣어요.", claim_ids: ["c1"], visual_role: "reality", visual_prompt: "A glass", timing_sec: 5 },
], notes: "시청자 결론(c1): 물을 조금 넣는 습관이 있다" };
const CARD_PLAN = { pages: [
  { role: "cover", heading: "위스키에 왜 물을 넣을까요?" },
  { role: "explain", heading: "물을 조금 넣어요", body: "애호가들은 물을 넣어요", claim_ids: ["c1"] },
  { role: "explain", heading: "연기 향의 정체", body: "페놀 때문이에요", claim_ids: ["c2"] },
  { role: "source", heading: "출처" },
], reel: { hook_title: "위스키에 왜 물을 넣을까요?", share_line: "위스키 좋아하는 친구에게 보내 주세요" }, template_version: "card-reel-v1",
  notes: "시청자 결론(c1): 물을 넣는 습관이 있어요" };

const budget = () => rpc("drinks_open_develop_budget", { cap_usd: 2, stage: "시험", purpose: "시험", approver_words: "승인한다" });
const topicRow = (id: string) => row("select * from drink_topics where id = $1", [id]);
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);
const reqRow = (id: string) => row("select * from drink_develop_requests where id = $1", [id]);
const picks = (topic: string) => rows("select * from drink_topic_format_picks where topic_id = $1 order by format_intent", [topic]);
const activeReqs = (topic: string) => rows("select * from drink_develop_requests where topic_id = $1 and status in ('queued','running') order by created_at", [topic]);

async function researching(): Promise<string> {
  const t = await ok("create_topic", { title: "위스키에 물", question: `위스키에 물을 넣는 이유 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  await ok("triage", { topic_id: t.topic_id, expected_version: (await topicRow(t.topic_id)).version, scores: SCORES });
  await ok("topic_action", { topic_id: t.topic_id, expected_version: (await topicRow(t.topic_id)).version, action: "start_research" });
  return t.topic_id;
}
const addSource = (topic: string) => ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });

/** 워커처럼 큐 맨 앞의 요청을 꺼낸다. */
async function take(expectKind?: string) {
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.ok(g.job, "큐에 요청이 있어야 한다");
  if (expectKind) assert.equal(g.job.kind, expectKind);
  return { job: g.job, lease: { request_id: g.job.request_id, lease_token: g.job.lease_token } };
}

/** 근거 요청을 워커처럼 처리한다(두 형식 모두 쓸 수 있게 영상 필수 주장으로 저장 — 카드 필수 주장은 저장 때 채워진다). */
async function finishEvidence(lease: Record<string, unknown>, snapshot: string, fmtInBrief = "video") {
  const claim = (cid: string, quote: string) => ({ claim_id: cid, text: `주장 ${cid}`, claim_type: "process", source_refs: [{ snapshot_id: snapshot, original_quote: quote }] });
  const save = await rpc("drinks_develop_save_evidence", { ...lease, evidence_pack: { claims: [claim("c1", QUOTE1), claim("c2", QUOTE2)] },
    brief: { audience_question: "왜 물을 넣나", selected_claim_ids: ["c1", "c2"], proposed_formats: [fmtInBrief], required_claims: { [fmtInBrief]: ["c1"] } } });
  const fin = await rpc("drinks_finish_develop", { ...lease, outcome: "succeeded", result: { claims_kept: 2 } });
  return { reviewId: save.review_id as string, fin };
}

/** 대본 요청을 워커처럼 처리해 형식에 맞는 작성 중 제작안을 만든다. */
async function draftPlan() {
  const { job, lease } = await take("plan");
  const plan = job.format_intent === "card" ? CARD_PLAN : VIDEO_PLAN;
  const pl = await rpc("drinks_develop_save_plan", { ...lease, plan_json: plan, core_takeaway_draft: "물을 조금 넣는 습관이 있어요" });
  await rpc("drinks_finish_develop", { ...lease, outcome: "succeeded", result: {} });
  return { job, planId: pl.revision_id as string };
}

async function operatorFills(reviewId: string, topic: string) {
  const r = await reviewRow(reviewId);
  const claims = r.evidence_pack.claims.map((c: Any) => ({ ...c, support_review: "supported" }));
  return ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims }, brief: r.brief, scores: SCORES });
}

async function approvePayload(topic: string, reviewId: string, planId: string, formatIntent: string, extra: Record<string, unknown> = {}) {
  const [t, r, p] = [await topicRow(topic), await reviewRow(reviewId), await planRow(planId)];
  return { topic_id: topic, expected_topic_version: t.version, review_id: reviewId, expected_review_version: r.version,
    plan_revision_id: planId, expected_plan_version: p.version, format_intent: formatIntent,
    ...(formatIntent === "explainer" ? { approved_amount_usd: 8.9 } : {}), ...extra };
}

/** 설명형+카드를 한 번에 고르고 → 근거 → 두 형식의 작성 중 제작안까지. */
async function twoDrafts(b: Any) {
  const topic = await researching();
  const s = await addSource(topic);
  const pick = await ok("pick_topic", { topic_id: topic, formats: ["explainer", "card"], editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(pick.picks.length, 2);
  assert.equal(pick.picks[0].chain.kind, "evidence");
  assert.equal(pick.picks[1].chain.existing, true, "근거 요청은 하나를 공유한다");
  assert.equal(pick.picks[1].chain.request_id, pick.picks[0].chain.request_id);
  const { lease } = await take("evidence");
  const { reviewId, fin } = await finishEvidence(lease, s.snapshot_id);
  assert.ok(Array.isArray(fin.result.chain), "0072: chain 은 형식마다 한 항목");
  assert.deepEqual(fin.result.chain.map((c: Any) => [c.format_intent, c.queued]), [["card", true], ["explainer", true]]);
  const a = await draftPlan();
  const c = await draftPlan();
  const byFmt = Object.fromEntries([a, c].map((d) => [d.job.format_intent, d.planId])) as Record<string, string>;
  assert.deepEqual(Object.keys(byFmt).sort(), ["card", "explainer"], "형식마다 대본 하나");
  assert.equal((await planRow(byFmt.explainer)).format, "video");
  assert.equal((await planRow(byFmt.card)).format, "carousel");
  assert.equal((await activeReqs(topic)).length, 0);
  return { topic, reviewId, explainerPlan: byFmt.explainer, cardPlan: byFmt.card };
}

test("형식 조합 7가지가 전부 들어가고, 0개는 막힌다. 근거 요청은 하나를 공유하고 밈은 요청을 만들지 않는다", async () => {
  const b = await budget();
  const combos = [["explainer"], ["card"], ["meme"], ["explainer", "card"], ["explainer", "meme"], ["card", "meme"], ["explainer", "card", "meme"]];
  for (const formats of combos) {
    const topic = await researching();
    const r = await ok("pick_topic", { topic_id: topic, formats, editorial_week: WEEK, budget_id: b.budget_id });
    assert.deepEqual(r.formats, formats);
    assert.equal(r.format_intent, formats[0], "대표 형식은 첫 번째");
    assert.equal(r.editorial_week, MONDAY);
    assert.deepEqual((await picks(topic)).map((p: Any) => p.format_intent), [...formats].sort(), JSON.stringify(formats));
    assert.equal((await row("select format_intent from drink_topic_picks where topic_id = $1", [topic])).format_intent, formats[0]);
    const nonMeme = formats.filter((f) => f !== "meme");
    const evidence = await rows("select * from drink_develop_requests where topic_id = $1 and kind = 'evidence'", [topic]);
    assert.equal(evidence.length, nonMeme.length ? 1 : 0, "근거 요청은 소재당 하나(밈만이면 없음)");
    for (const p of r.picks) {
      if (p.format_intent === "meme") { assert.equal(p.chain.queued, false); assert.equal(p.chain.code, "meme_board"); }
      else { assert.equal(p.chain.kind, "evidence"); assert.equal(p.chain.request_id, evidence[0].id); }
    }
    for (const q of evidence) await rpc("drinks_cancel_develop", { request_id: q.id });
  }
  const t0 = await researching();
  await fails("pick_topic", { topic_id: t0, formats: [], editorial_week: WEEK }, "invalid_input");
  await rpcFails("drinks_pick_topic", { topic_id: t0, formats: [], editorial_week: WEEK }, "invalid_input");
  await rpcFails("drinks_pick_topic", { topic_id: t0, editorial_week: WEEK }, "invalid_input");
  await rpcFails("drinks_pick_topic", { topic_id: t0, formats: ["explainer", "explainer"], editorial_week: WEEK }, "invalid_input");
  await rpcFails("drinks_pick_topic", { topic_id: t0, formats: ["explainer", "card", "meme", "card"], editorial_week: WEEK }, "invalid_input");
  await rpcFails("drinks_pick_topic", { topic_id: t0, formats: ["weird"], editorial_week: WEEK }, "invalid_input");
  assert.equal((await picks(t0)).length, 0, "실패하면 아무것도 남지 않는다");
});

test("옛 호출(format 하나)도 그대로 — 대표 pick + 형식 줄 하나 + 근거 요청", async () => {
  const b = await budget();
  const topic = await researching();
  const r = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(r.chain.kind, "evidence");
  assert.equal(r.maps_to, "video");
  assert.deepEqual(r.formats, ["explainer"]);
  assert.equal((await picks(topic)).length, 1);
  assert.equal((await row("select format_intent from drink_topic_picks where topic_id = $1", [topic])).format_intent, "explainer");
  await rpc("drinks_cancel_develop", { request_id: r.chain.request_id });
});

test("설명형+카드 → 대본 둘 → 설명형만 승인 → 카드는 승인 전 그대로 → 카드를 나중에 승인하면 편성에 더해진다", async () => {
  const b = await budget();
  const { topic, reviewId, explainerPlan, cardPlan } = await twoDrafts(b);
  await operatorFills(reviewId, topic);
  // 형식을 적지 않은 승인은 라우트가 거절한다(작업 단위 = 소재 × 형식)
  const noFmt = await approvePayload(topic, reviewId, explainerPlan, "explainer");
  delete (noFmt as Record<string, unknown>).format_intent;
  await fails("approve_content", noFmt, "invalid_input");
  // 다른 형식의 제작안을 그 형식으로 승인할 수 없다
  await fails("approve_content", await approvePayload(topic, reviewId, cardPlan, "explainer"), "format_not_selected");

  const res = await ok("approve_content", await approvePayload(topic, reviewId, explainerPlan, "explainer"));
  assert.equal(res.status, "selected");
  assert.deepEqual(res.selected_formats, ["video"], "설명형만 편성됐다");
  assert.equal(res.format_intent, "explainer");
  assert.equal(res.spend_approval_opened, false);
  assert.equal((await planRow(explainerPlan)).plan_status, "approved");
  const card = await planRow(cardPlan);
  assert.equal(card.plan_status, "draft", "카드 대본은 그대로 작성 중");
  assert.equal(card.blocked_at, null, "사람이 채운 칸은 근거 내용 변경이 아니다 — 카드 대본도 무효가 되지 않는다");
  const pk = Object.fromEntries((await picks(topic)).map((p: Any) => [p.format_intent, p]));
  assert.ok(pk.explainer.approved_at);
  assert.equal(Number(pk.explainer.approved_amount_usd), 8.9);
  assert.equal(pk.card.approved_at, null, "카드 형식은 승인 전");
  assert.equal(pk.card.approved_amount_usd, null);
  const rep = await row("select * from drink_topic_picks where topic_id = $1", [topic]);
  assert.ok(rep.approved_at, "대표 pick(설명형)도 같이 적힌다");
  // 두 번 승인할 수 없다
  await fails("approve_content", await approvePayload(topic, reviewId, explainerPlan, "explainer"), "invalid_state");

  // (선택) 카드를 나중에 승인: 근거는 승인본 그대로, 편성은 합집합
  const res2 = await ok("approve_content", await approvePayload(topic, reviewId, cardPlan, "card"));
  assert.deepEqual(res2.selected_formats, ["carousel", "video"], "편성 형식은 합집합(drinks_select 가 정렬해 저장한다)");
  assert.equal(res2.editorial_week, MONDAY);
  assert.equal(res2.approved_amount_usd, null, "카드뉴스는 금액이 없다");
  assert.equal((await planRow(cardPlan)).plan_status, "approved");
  const pk2 = Object.fromEntries((await picks(topic)).map((p: Any) => [p.format_intent, p]));
  assert.ok(pk2.card.approved_at);
  assert.equal(pk2.card.approved_amount_usd, null);
  assert.equal(Number(pk2.explainer.approved_amount_usd), 8.9, "먼저 승인한 형식의 기록은 그대로");
  const t = await topicRow(topic);
  assert.deepEqual(t.selected_formats, ["carousel", "video"]);
  assert.equal(t.approved_review_id, reviewId);
  assert.equal((await row("select count(*)::int n from drink_spend_approvals", [])).n, 0, "승인은 지출 결재를 열지 않는다");

  // 다시 골라도 승인 시각·금액·주차를 덮어쓰지 않는다
  const again = await ok("pick_topic", { topic_id: topic, formats: ["explainer", "card"], editorial_week: "2026-11-11", budget_id: b.budget_id });
  assert.deepEqual(again.picks.map((p: Any) => p.existing), [true, true]);
  const pk3 = Object.fromEntries((await picks(topic)).map((p: Any) => [p.format_intent, p]));
  assert.equal(pk3.explainer.approved_at.getTime(), pk.explainer.approved_at.getTime());
  assert.equal(Number(pk3.explainer.approved_amount_usd), 8.9);
  assert.ok(pk3.card.approved_at);
  assert.equal(pk3.card.editorial_week.toISOString().slice(0, 10), MONDAY, "주차도 그대로");
  assert.equal((await row("select approved_at from drink_topic_picks where topic_id = $1", [topic])).approved_at.getTime(), rep.approved_at.getTime());
  for (const q of await activeReqs(topic)) await rpc("drinks_cancel_develop", { request_id: q.id });
});

test("이미 근거가 승인된 소재에 형식을 더한다: 승인된 근거로 일반 대본 요청 → 작성 중 제작안 → 그 형식만 승인하면 편성에 더해진다", async () => {
  const b = await budget();
  const topic = await researching();
  const s = await addSource(topic);
  const pick = await ok("pick_topic", { topic_id: topic, formats: ["explainer"], editorial_week: WEEK, budget_id: b.budget_id });
  const { lease } = await take("evidence");
  const { reviewId } = await finishEvidence(lease, s.snapshot_id);
  const { planId } = await draftPlan();
  await operatorFills(reviewId, topic);
  await ok("approve_content", await approvePayload(topic, reviewId, planId, "explainer"));
  assert.equal((await topicRow(topic)).status, "selected");
  assert.equal(pick.picks.length, 1);

  // 카드 형식을 더한다 — 근거 요청이 아니라 승인된 근거로 쓰는 대본 요청이 바로 들어간다
  const add = await ok("pick_topic", { topic_id: topic, formats: ["card"], editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(add.status, "selected");
  assert.equal(add.picks[0].existing, false);
  assert.equal(add.picks[0].chain.kind, "plan");
  assert.equal(add.picks[0].chain.queued, true);
  const q = await reqRow(add.picks[0].chain.request_id);
  assert.equal(q.format_intent, "card");
  assert.equal(q.draft_evidence, false, "승인된 근거를 쓴다");
  assert.equal(q.review_id, reviewId);
  assert.equal((await row("select format_intent from drink_topic_picks where topic_id = $1", [topic])).format_intent, "explainer", "대표는 바뀌지 않는다");
  // 워커: 형식은 요청 칸에서 온다. 아직 편성 전 형식이라 작성 중 행을 직접 넣고 근거 값을 적는다
  const { job, lease: l2 } = await take("plan");
  assert.equal(job.format_intent, "card");
  assert.equal(job.draft_evidence, false);
  assert.equal(job.review.status, "approved");
  const pl = await rpc("drinks_develop_save_plan", { ...l2, plan_json: CARD_PLAN });
  await rpc("drinks_finish_develop", { ...l2, outcome: "succeeded", result: {} });
  const cardPlan = await planRow(pl.revision_id);
  assert.equal(cardPlan.format, "carousel");
  assert.equal(cardPlan.plan_status, "draft");
  assert.equal(cardPlan.drafted_from_unapproved, false);
  assert.ok(cardPlan.evidence_content_hash, "승인 직전 대조에 쓸 근거 값을 적는다");
  assert.deepEqual((await topicRow(topic)).selected_formats, ["video"], "제작안을 만든 것만으로 편성은 바뀌지 않는다");
  // 승인 전 제작안은 제작으로 못 간다(규칙 그대로)
  await fails("request_render", { plan_revision_id: pl.revision_id }, "not_renderable");
  // 승인된 기획에 카드 필수 주장이 없으면 편성이 막힌다 — 규칙이 줄지 않았다. 기획을 고쳐 다시 승인해야 한다(여기서는 그 분기만 확인)
  const brief = (await reviewRow(reviewId)).brief;
  if (!brief.required_claims?.carousel) {
    await fails("approve_content", await approvePayload(topic, reviewId, pl.revision_id, "card"), "required_claims_missing");
    assert.equal((await planRow(pl.revision_id)).plan_status, "draft", "하나라도 실패하면 아무것도 바뀌지 않는다");
  }
});

test("세 형식 중 하나가 실패해도 나머지는 그대로다 — 실패한 형식만 다시 요청하고, 같은 형식의 활성 요청은 둘이 되지 않는다", async () => {
  const b = await budget();
  const topic = await researching();
  const s = await addSource(topic);
  const pick = await ok("pick_topic", { topic_id: topic, formats: ["explainer", "card", "meme"], editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(pick.picks[2].chain.code, "meme_board");
  const { lease } = await take("evidence");
  const { reviewId, fin } = await finishEvidence(lease, s.snapshot_id);
  assert.equal(fin.result.chain.length, 2, "밈은 대본 요청을 만들지 않는다");
  // 두 대본 요청: 하나는 성공, 하나는 워커 실패
  const first = await take("plan");
  const second = await take("plan");
  const [okJob, badJob] = first.job.format_intent === "explainer" ? [first, second] : [second, first];
  await rpc("drinks_develop_save_plan", { ...okJob.lease, plan_json: VIDEO_PLAN, core_takeaway_draft: "물을 조금" });
  await rpc("drinks_finish_develop", { ...okJob.lease, outcome: "succeeded", result: {} });
  const failed = await rpc("drinks_finish_develop", { ...badJob.lease, outcome: "failed", error_code: "worker_error", error_message: "모델 예외" });
  assert.equal(failed.status, "failed");
  assert.equal(failed.format_intent, "card");
  assert.equal((await reqRow(okJob.job.request_id)).status, "succeeded", "다른 형식은 그대로 성공");
  assert.equal((await rows("select * from drink_plan_revisions where topic_id = $1", [topic])).length, 1, "설명형 대본만 있다");
  // 실패한 형식만 다시 요청 — 두 번 눌러도 활성 요청은 하나
  const retry = await ok("request_develop", { topic_id: topic, kind: "plan", format_intent: "card", draft_evidence: true, budget_id: b.budget_id });
  assert.equal(retry.existing, false);
  assert.equal(retry.format_intent, "card");
  const dup = await ok("request_develop", { topic_id: topic, kind: "plan", format_intent: "card", draft_evidence: true, budget_id: b.budget_id });
  assert.equal(dup.existing, true);
  assert.equal(dup.request_id, retry.request_id);
  // 설명형은 이미 대본이 있어 다시 요청하면 draft_exists — 카드 요청을 건드리지 않는다
  await fails("request_develop", { topic_id: topic, kind: "plan", format_intent: "explainer", draft_evidence: true, budget_id: b.budget_id }, "draft_exists");
  assert.deepEqual((await activeReqs(topic)).map((q: Any) => q.format_intent), ["card"]);
  // 형식을 적지 않은 대본 요청은 둘 중 어느 것인지 몰라 거절한다(라우트도, DB 도)
  await fails("request_develop", { topic_id: topic, kind: "plan", draft_evidence: true, budget_id: b.budget_id }, "invalid_input");
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", draft_evidence: true, budget_id: b.budget_id }, "invalid_input");
  // 고유 색인도 같은 규칙을 표에서 강제한다
  await assert.rejects(db.query(
    "insert into drink_develop_requests (topic_id, kind, review_id, budget_id, draft_evidence, format_intent) values ($1, 'plan', $2, $3, true, 'card')",
    [topic, reviewId, b.budget_id]), /duplicate key|drink_develop_one_active_uq/);
  const { job } = await take("plan");
  assert.equal(job.format_intent, "card");
  await rpc("drinks_cancel_develop", { request_id: job.request_id });
});

test("공통 근거가 바뀌면 그 근거로 쓴 대본은 형식을 가리지 않고 차단되고, 어느 형식도 승인되지 않는다", async () => {
  const b = await budget();
  const { topic, reviewId, explainerPlan, cardPlan } = await twoDrafts(b);
  const r = await reviewRow(reviewId);
  const claims = r.evidence_pack.claims.map((c: Any) => (c.claim_id === "c1" ? { ...c, text: "주장을 고쳤다", support_review: "supported" } : { ...c, support_review: "supported" }));
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims }, brief: r.brief, scores: SCORES });
  for (const id of [explainerPlan, cardPlan]) {
    const p = await planRow(id);
    assert.ok(p.blocked_at, `${p.format} 대본이 차단돼야 한다`);
    assert.match(p.blocked_reason, /evidence_edited/);
  }
  await fails("approve_content", await approvePayload(topic, reviewId, explainerPlan, "explainer"), "plan_blocked");
  await fails("approve_content", await approvePayload(topic, reviewId, cardPlan, "card"), "plan_blocked");
  assert.equal((await topicRow(topic)).status, "researching", "아무것도 승인되지 않았다");
  assert.equal((await reviewRow(reviewId)).status, "draft");
  // 다시 만들면 형식마다 새 요청이 들어간다
  const again = await ok("pick_topic", { topic_id: topic, formats: ["explainer", "card"], editorial_week: WEEK, budget_id: b.budget_id });
  assert.deepEqual(again.picks.map((p: Any) => [p.format_intent, p.chain.kind, p.chain.queued]), [["explainer", "plan", true], ["card", "plan", true]]);
  for (const q of await activeReqs(topic)) await rpc("drinks_cancel_develop", { request_id: q.id });
});

test("작업 단위 뷰: 행 수 = 소재×형식 + 카드 밈 제작안. 조회 RPC 는 읽기만", async () => {
  const before = (await row("select count(*)::int n from drink_work_items")).n;
  const unitsBefore = (await row(`select (select count(*) from drink_topic_format_picks) + (select count(*) from drink_meme_drafts where card_id is not null) as n`)).n;
  assert.equal(before, Number(unitsBefore), "행이 늘거나 줄지 않는다(LATERAL 현재 1건)");
  const b = await budget();
  const { topic, reviewId, explainerPlan, cardPlan } = await twoDrafts(b);
  // 카드 밈 제작안 하나
  const card = await row(`insert into drink_ig_cards (merge_key, kind, name, first_seen_on, decision, decided_at) values ($1, 'structure_hook', '카드 밈', current_date, 'use', now()) returning id`, [`mf-${uniq()}`]);
  for (const f of ["beat_count", "cut_lengths", "twist_at"]) {
    await db.query(`insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, $2, '3', 'operator', 'high')`, [card.id, f]);
  }
  const meme = await ok("meme_save_draft", { card_id: card.id, spec: {
    frame: "top_text", top_line: "POV: 와인 고르는 척하는 나", title_keyword: "", caption: "다들 이러잖아요",
    beats: [{ text: "앞면을 본다", keyword: "", ms: 3000 }, { text: "가격표만 기억난다", keyword: "가격표", ms: 4000 }],
    scene: { source: "text_bg", palette: "wine" }, sync_grade: "sync_free", audio: { mode: "ambient_local" }, contains_info: false, claim_ids: [] } });
  const after = (await row("select count(*)::int n from drink_work_items")).n;
  assert.equal(after, before + 3, "설명형·카드 2행 + 카드 밈 1행");
  const items = await rows("select * from drink_work_items where topic_id = $1 order by format_intent", [topic]);
  assert.deepEqual(items.map((i: Any) => [i.unit_id, i.source, i.plan_format]), [[`topic:${topic}:card`, "topic", "carousel"], [`topic:${topic}:explainer`, "topic", "video"]]);
  for (const i of items) {
    assert.equal(i.review_id, reviewId);
    assert.equal(i.review_status, "draft");
    assert.equal(i.review_valid, false);
    assert.equal(i.plan_status, "draft");
    assert.equal(i.plan_blocked, false);
    assert.equal(i.develop_kind, "plan", "이 형식의 최근 개발 요청");
    assert.equal(i.develop_status, "succeeded");
    assert.equal(i.topic_status, "researching");
    assert.equal(i.pick_approved_at, null);
    assert.equal(i.unknown_billed, false);
    assert.equal(i.orphan_hold, false);
  }
  assert.equal(items[1].plan_revision_id, explainerPlan);
  assert.equal(items[0].plan_revision_id, cardPlan);
  const cm = await row("select * from drink_work_items where unit_id = $1", [`meme_card:${meme.draft_id}`]);
  assert.equal(cm.source, "card");
  assert.equal(cm.format_intent, "meme");
  assert.equal(cm.topic_id, null);
  assert.equal(cm.title, "카드 밈");
  assert.equal(cm.meme_draft_id, meme.draft_id);
  assert.equal(cm.meme_status, "draft");
  // 조회 RPC
  const tf = await ok("topic_formats", { topic_id: topic });
  assert.equal(tf.picks.length, 2);
  assert.equal(tf.items.length, 2);
  assert.equal(tf.representative, "explainer");
  const all = await ok("work_items", { filter: "all", limit: 500 });
  assert.equal(all.length, after);
  const approve = await ok("work_items", { filter: "approve", limit: 500 });
  assert.ok(approve.some((w: Any) => w.unit_id === `topic:${topic}:explainer`), "작성 중 제작안은 결정 대기");
  assert.ok(approve.some((w: Any) => w.unit_id === `meme_card:${meme.draft_id}`), "밈 초안도 결정 대기");
  const publish = await ok("work_items", { filter: "publish", limit: 500 });
  assert.ok(!publish.some((w: Any) => w.topic_id === topic), "아직 게시 단계가 아니다");
  // 승인 뒤 뷰가 바뀐다
  await operatorFills(reviewId, topic);
  await ok("approve_content", await approvePayload(topic, reviewId, explainerPlan, "explainer"));
  const ex = await row("select * from drink_work_items where unit_id = $1", [`topic:${topic}:explainer`]);
  assert.equal(ex.plan_status, "approved");
  assert.equal(ex.review_valid, true);
  assert.ok(ex.pick_approved_at);
  assert.equal(Number(ex.pick_amount_usd), 8.9);
  assert.equal(ex.topic_status, "selected");
  const cd = await row("select * from drink_work_items where unit_id = $1", [`topic:${topic}:card`]);
  assert.equal(cd.plan_status, "draft");
  assert.equal(cd.pick_approved_at, null);
  assert.equal((await row("select count(*)::int n from drink_work_items")).n, after, "승인해도 행 수는 그대로");
  // 공개 역할은 새 표·뷰·함수에 닿지 않는다
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    try {
      await assert.rejects(db.query("select * from drink_topic_format_picks"), /permission denied/);
      await assert.rejects(db.query("select * from drink_work_items"), /permission denied/);
      await assert.rejects(db.query("select drinks_work_items('{}'::jsonb)"), /permission denied/);
      await assert.rejects(db.query("select drinks_develop_estimate('{}'::jsonb)"), /permission denied/);
    } finally {
      await db.exec("reset role");
    }
  }
});

test("예상 비용: 아는 형식은 0 보다 큰 금액, 밈은 null 로 '모른다'고 말한다 — 모르는 비용을 0 으로 쓰지 않는다", async () => {
  const b = await budget();
  const est = await ok("develop_estimate", { formats: ["explainer", "card", "meme"], budget_id: b.budget_id });
  assert.equal(est.all_known, false, "밈이 있으면 전체를 안다고 말하지 않는다");
  const byKind = (k: string, f?: string) => est.items.find((i: Any) => i.kind === k && (f === undefined || i.format_intent === f));
  const ev = byKind("evidence");
  assert.equal(ev.known, true);
  assert.equal(ev.shared, true, "근거는 형식이 공유한다");
  assert.ok(Number(ev.est_usd) > 0);
  for (const f of ["explainer", "card"]) {
    const it = byKind("plan", f);
    assert.equal(it.known, true);
    assert.ok(Number(it.est_usd) > 0 && Number(it.est_usd) <= Number(est.per_request_cap_usd), f);
  }
  const mm = byKind("meme");
  assert.equal(mm.known, false);
  assert.equal(mm.est_usd, null, "모르는 비용은 null — 0 이 아니다");
  assert.notEqual(mm.est_usd, 0);
  const known = est.items.filter((i: Any) => i.known).reduce((s: number, i: Any) => s + Number(i.est_usd), 0);
  assert.ok(Math.abs(known - Number(est.total_est_usd)) < 0.0005, "합계는 아는 항목만 더한다");
  assert.equal(Number(est.budget_remaining_usd), 2, "결재 잔액");
  // 근거가 이미 있는 소재는 근거 비용이 빠진다
  const topic = await researching();
  const s = await addSource(topic);
  await ok("pick_topic", { topic_id: topic, formats: ["card"], editorial_week: WEEK, budget_id: b.budget_id });
  const { lease } = await take("evidence");
  await finishEvidence(lease, s.snapshot_id, "carousel");
  const est2 = await ok("develop_estimate", { topic_id: topic, formats: ["card"] });
  assert.equal(est2.items.some((i: Any) => i.kind === "evidence"), false);
  assert.equal(est2.items.length, 1);
  assert.equal(est2.all_known, true);
  for (const q of await activeReqs(topic)) await rpc("drinks_cancel_develop", { request_id: q.id });
  // 단가표에 없는 모델은 null·known:false 다(함수 단위)
  assert.equal((await row("select drinks_develop_price('no-such-model') as p")).p, null);
  await rpcFails("drinks_develop_estimate", { formats: ["weird"] }, "invalid_input");
});

test("워커 함수는 승인·제출·편성 함수를 부르지 않는다(0072 소스 검사) — 부르는 곳은 운영자 승인 함수 하나뿐", () => {
  const sql = readFileSync(join(DIR, "0072_drinks_multi_format.sql"), "utf8");
  const fn = (name: string) => sql.split(`create or replace function ${name}(`)[1].split("$$;")[0];
  for (const f of ["drinks_request_develop", "drinks_start_develop", "drinks_develop_save_plan", "drinks_develop_chain_next", "drinks_finish_develop",
    "drinks_pick_topic", "drinks_develop_estimate", "drinks_topic_formats", "drinks_work_items"]) {
    for (const forbidden of ["drinks_review_action", "drinks_plan_action", "drinks_select(", "drinks_approve_content"]) {
      assert.ok(!fn(f).includes(forbidden), `${f} 는 ${forbidden} 를 부르면 안 된다`);
    }
  }
  const approve = fn("drinks_approve_content");
  for (const must of ["drinks_review_action", "drinks_select(", "drinks_plan_action", "drinks_evidence_content_hash", "plan_stale", "develop_in_progress"]) {
    assert.ok(approve.includes(must), must);
  }
  assert.ok(!approve.includes("drinks_open_spend_approval"), "승인이 지출 결재를 열지 않는다");
});
