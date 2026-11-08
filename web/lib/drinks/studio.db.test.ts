// 콘텐츠 스튜디오(0076) DB 통합 테스트 — PGlite 위에 00(5x|6x|7x)_drinks_*. 모델·네트워크 호출 0, 비용 0.
// 보는 것: 저장 충돌(2026-11-06 사케 소재 재현) · 빈 초안 이어쓰기 · 사람 편집 보존 · 자동 복구 한도 · 보관 결과 재사용 ·
//          점수·주장 선택·승인 체크리스트 없이 [초안 만들기] → [저장] → [생성] 이 끝까지 가는가 · 같은 버튼 반복이 중복을 만들지 않는가.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0076_drinks_studio.sql"), "0076 이 목록에 있어야 한다");
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
const rows = async (sql: string, params: unknown[] = []): Promise<Any[]> => (await db.query(sql, params)).rows as Any[];
/** 0076 이전의 저장 경로(잠금 없음)를 흉내 낸다 — 운영에서 실제로 생겼던 상태를 다시 만들 때만 쓴다. */
const workerSave = async <T,>(f: () => Promise<T>): Promise<T> => {
  await db.exec("select set_config('drinks.worker_save', 'on', false)");
  try { return await f(); } finally { await db.exec("select set_config('drinks.worker_save', 'off', false)"); }
};
const uniq = () => Math.random().toString(36).slice(2);

const QUOTE1 = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";
const QUOTE2 = "the smoky flavour is attributed to phenols, and in particular guaiacol";
const QUOTE3 = "beverages containing 10 % or more by volume of alcohol";
const BODY = `${QUOTE1} in order to further enhance the taste. Chemically, ${QUOTE2}. Exempt: ${QUOTE3}.`;
const AUTO = "AI 사실 확인(자동) — 근거 인용 대조 통과";
const PAGES = [
  { role: "cover", heading: "사케, 왜 날짜가 없을까요?" },
  { role: "explain", heading: "물을 조금 넣어요", body: "애호가들은 물을 넣어요", claim_ids: ["c1"] },
  { role: "explain", heading: "연기 향의 정체", body: "페놀 때문이에요", claim_ids: ["c2"] },
  { role: "explain", heading: "표시 의무", body: "10% 넘는 술은 빠져요", claim_ids: ["c3"] },
  { role: "source", heading: "출처" },
];
const CARD_PLAN = { pages: PAGES, reel: { hook_title: "사케, 왜 날짜가 없을까요?", share_line: "사케 좋아하는 친구에게 보내 주세요" }, template_version: "card-reel-v1" };

/** 시험끼리 큐를 나눠 쓰지 않게: 앞 시험이 남긴 대기·진행 요청을 닫는다(워커는 가장 오래된 대기 요청부터 집는다). */
async function drain() {
  await db.exec("update drink_develop_requests set status = 'canceled', finished_at = now(), lease_token = null, error_code = 'test_drain' where status in ('queued','running')");
}

/** 수집함 후보 하나(임시 점수만 — discovery-v1 형식 적합성 두 칸, 5축 점수 없음). */
async function candidate(): Promise<string> {
  await drain();
  const r = await row(`insert into drink_discovery_candidates (status, key_question, reader_value, discovery_path, fit_video, fit_carousel, provisional_score, rubric, score_reason)
    values ('suggested', $1, '독자 가치', 'naver_cafe', 1, 3, 80, 'discovery-v1', '시험') returning id`, [`사케 유통기한이 어느정도일까요? ${uniq()}`]);
  return r.id;
}
const topicOf = async (cand: string) => (await row("select promoted_topic_id from drink_discovery_candidates where id = $1", [cand])).promoted_topic_id as string;
const lease = (g: Any) => ({ request_id: g.job.request_id, lease_token: g.job.lease_token });
const claim = (cid: string, snap: string, quote: string, supported = true) => ({ claim_id: cid, text: `주장 ${cid}`, claim_type: "process",
  support_review: supported ? "supported" : "not_reviewed", ...(supported ? { limitations: AUTO } : {}), source_refs: [{ snapshot_id: snap, original_quote: quote }] });

/** 워커 근거 단계를 흉내: 출처 추가 → 근거 저장(AI 확인된 주장만 핵심) → 성공. */
async function workerEvidence(g: Any, opts: { finish?: boolean } = {}) {
  const l = lease(g);
  const s = await rpc("drinks_develop_add_source", { ...l, source: { url: `https://example.org/${uniq()}`, title: "공식 문서", publisher: "国税庁",
    body_text: BODY, rights_status: "quote_ok", source_kind: "official" } });
  const save = await rpc("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [claim("c1", s.snapshot_id, QUOTE1), claim("c2", s.snapshot_id, QUOTE2), claim("c3", s.snapshot_id, QUOTE3)] },
    brief: { audience_question: g.job.topic.question, selected_claim_ids: ["c1", "c2", "c3"], proposed_formats: ["carousel"], required_claims: { carousel: ["c1", "c2", "c3"] } } });
  if (opts.finish !== false) await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: { claims_kept: 3 } });
  return { save, snap: s.snapshot_id as string, l };
}

async function workerCard(plan: Record<string, unknown> = CARD_PLAN) {
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.kind, "plan");
  assert.equal(g.job.format_intent, "card");
  const l = lease(g);
  const ctx = await rpc("drinks_develop_context", l);
  const pl = await rpc(ctx.supersedes_plan_id ? "drinks_develop_save_rewrite" : "drinks_develop_save_plan", { ...l, plan_json: plan, core_takeaway_draft: "날짜보다 제품 안내를 봐요" });
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: {} });
  return { job: g.job, ctx, planId: pl.revision_id as string };
}

const status = (topic: string) => ok("studio_status", { topic_id: topic });

test("사케 소재 재현: 근거를 만드는 사이 화면 저장이 들어오면 서버가 막고, 이미 생긴 빈 초안에는 워커가 이어 쓴다", async () => {
  const cand = await candidate();
  const prep = await ok("studio_prepare", { candidate_id: cand, format_intent: "card", categories: ["sake"] });
  assert.equal(prep.action, "picked");
  assert.equal(prep.queued, true);
  const topic = prep.topic_id as string;
  // 같은 버튼을 다시 눌러도 새 요청이 생기지 않는다
  const again = await ok("studio_prepare", { topic_id: topic });
  assert.equal(again.action, "already_running");
  assert.equal((await rows("select id from drink_develop_requests where topic_id = $1", [topic])).length, 1);

  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  // ① 사람 저장(근거 탭)이 도는 중에 들어오면 서버가 거절한다 — 화면 잠금이 없어도
  const t = await row("select version from drink_topics where id = $1", [topic]);
  await fails("save_review", { topic_id: topic, expected_topic_version: t.version, brief: { audience_question: null } }, "develop_in_progress");
  // ② 옛 경로가 이미 빈 작성 중 버전을 만들었다고 치자(2026-11-06 23:53:56 실측과 같은 상태)
  await workerSave(() => rpc("drinks_save_review", { topic_id: topic, expected_topic_version: t.version }));
  const blank = await row("select * from drink_topic_reviews where topic_id = $1 and status = 'draft'", [topic]);
  assert.equal(blank.evidence_pack.claims.length, 0);
  // ③ 워커 결과 저장은 draft_exists 로 실패하지 않고 그 빈 버전에 이어 쓴다
  const { save } = await workerEvidence(g);
  assert.equal(save.review_id, blank.id, "새 버전을 만들지 않고 빈 버전을 이어 쓴다");
  assert.equal(save.continued_blank_draft, true);
  const rv = await row("select * from drink_topic_reviews where id = $1", [blank.id]);
  assert.equal(rv.evidence_pack.claims.length, 3);
  const st = await status(topic);
  assert.ok(st.active?.kind === "plan", "근거가 끝나면 카드 초안 요청이 같은 트랜잭션에서 이어진다");
  // 5축 점수가 없어도 승인을 막지 않는다(경고로만). 나머지 필수 조건은 다 통과.
  const rb = (await row("select drinks_review_blockers($1::uuid) as b", [blank.id])).b;
  assert.ok(!rb.blockers.includes("scores_incomplete"));
  assert.ok(rb.warnings.includes("scores_not_evaluated"));
});

test("사람이 쓴 작성 중 근거는 덮어쓰지 않는다(draft_has_edits) — 저장 결과는 잃지 않는다", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  const t = await row("select version from drink_topics where id = $1", [topic]);
  // 사람이 질문을 적은 작성 중 버전(옛 경로)
  await workerSave(() => rpc("drinks_save_review", { topic_id: topic, expected_topic_version: t.version, brief: { audience_question: "사람이 고친 질문" } }));
  const l = lease(g);
  await rpcFails("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [] }, brief: {} }, "draft_has_edits");
  const kept = await row("select brief from drink_topic_reviews where topic_id = $1 and status = 'draft'", [topic]);
  assert.equal(kept.brief.audience_question, "사람이 고친 질문");
  // draft_has_edits 는 자동 복구 대상이 아니다
  await rpc("drinks_finish_develop", { ...l, outcome: "failed", error_code: "draft_has_edits", error_message: "x", result: { unsaved_evidence: { evidence_pack: { claims: [] } } } });
  const p2 = await ok("studio_prepare", { topic_id: topic });
  assert.equal(p2.action, "stopped");
  assert.equal(p2.code, "draft_has_edits");
});

test("저장 충돌로 실패한 소재는 [초안 만들기]가 복구한다 — 보관 결과를 다시 쓰고, 24시간 3번까지만", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  let g = await rpc("drinks_start_develop", { worker_id: "t" });
  // 1회차: 저장이 draft_exists 로 실패했다(옛 버그). 워커는 이제 만든 결과를 요청 기록에 보관한다.
  const l = lease(g);
  const s = await rpc("drinks_develop_add_source", { ...l, source: { url: `https://example.org/${uniq()}`, title: "공식", body_text: BODY, rights_status: "quote_ok", source_kind: "official" } });
  const unsaved = { evidence_pack: { claims: [claim("c1", s.snapshot_id, QUOTE1), claim("c2", s.snapshot_id, QUOTE2), claim("c3", s.snapshot_id, QUOTE3)] },
    brief: { audience_question: "q", selected_claim_ids: ["c1", "c2", "c3"] } };
  await rpc("drinks_finish_develop", { ...l, outcome: "failed", error_code: "draft_exists", error_message: "x", result: { unsaved_evidence: unsaved, cost: { spent_usd: 0.006 } } });
  // [초안 만들기] → 같은 실패를 되풀이하지 않고 복구 요청 1건
  const rec = await ok("studio_prepare", { topic_id: topic });
  assert.equal(rec.action, "recovered");
  const q = await row("select * from drink_develop_requests where id = $1", [rec.recovery.request_id]);
  assert.equal(q.recovery_of, l.request_id);
  assert.equal(q.chain, true, "이어 만들기 표시도 그대로");
  // 워커는 보관 결과를 받는다 → 모델을 다시 부르지 않는다
  g = await rpc("drinks_start_develop", { worker_id: "t" });
  const ctx = await rpc("drinks_develop_context", lease(g));
  assert.equal(ctx.reusable.from_request_id, l.request_id);
  assert.equal(ctx.reusable.evidence_pack.claims.length, 3);
  // 출처의 사용 조건이 바뀌면(권리 철회) 재사용하지 않는다 — 시험에서는 트리거를 잠시 꺼 철회를 흉내 낸다
  const flip = (to: string) => db.exec(`set session_replication_role = replica; update drink_source_snapshots set rights_status = '${to}' where id = '${s.snapshot_id}'; set session_replication_role = origin;`);
  await flip("restricted");
  assert.equal((await rpc("drinks_develop_context", lease(g))).reusable, null);
  await flip("quote_ok");
  // 한도: 워커 중단이 세 번 더 이어지면 네 번째는 멈춘다
  for (let i = 0; i < 3; i++) {
    const cur = await row("select id, lease_token from drink_develop_requests where topic_id = $1 and status = 'running'", [topic]);
    await rpc("drinks_finish_develop", { request_id: cur.id, lease_token: cur.lease_token, outcome: "failed", error_code: "worker_error", error_message: "x", result: {} });
    const r = await rpc("drinks_studio_recover_all", {});
    const mine = r.recovered.filter((x: Any) => x.topic_id === topic);
    await db.exec(`update drink_develop_requests set status = 'canceled', finished_at = now(), error_code = 'test_drain' where status = 'queued' and topic_id <> '${topic}'`);
    if (i < 2) {
      assert.equal(mine.length, 1, `워커가 ${i + 2}번째 복구를 넣는다`);
      await rpc("drinks_start_develop", { worker_id: "t" });
    } else {
      assert.equal(mine.length, 0, "24시간 3번을 넘기면 자동으로 다시 하지 않는다");
    }
  }
  const stop = await ok("studio_prepare", { topic_id: topic });
  assert.equal(stop.action, "needs_choice");
  assert.equal(stop.code, "recovery_limit");
});

test("자료 부족(blocked)·취소는 자동으로 다시 하지 않는다", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  await rpc("drinks_finish_develop", { ...lease(g), outcome: "blocked", error_code: "evidence_insufficient", error_message: "x", result: {} });
  assert.equal((await rpc("drinks_studio_recover_all", {})).recovered.filter((x: Any) => x.topic_id === prep.topic_id).length, 0);
  const p2 = await ok("studio_prepare", { topic_id: prep.topic_id });
  assert.equal(p2.action, "stopped");
  assert.equal(p2.code, "evidence_insufficient");
});

test("끝까지: 초안 → 사람의 저장(숫자 대조) → 수정 지시 → [생성] 한 번이 승인과 제작 요청을 함께 — 다시 눌러도 중복 없음", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  await workerEvidence(await rpc("drinks_start_develop", { worker_id: "t" }));
  const { planId } = await workerCard();
  let st = await status(topic);
  const plan = st.plans.find((p: Any) => p.plan_revision_id === planId);
  assert.ok(plan && plan.plan_status === "draft" && !plan.blocked);
  assert.deepEqual(plan.unverified_numbers, [], "근거 인용에 있는 숫자(10)는 통과");
  assert.equal(st.review.core_takeaway, "날짜보다 제품 안내를 봐요", "핵심 메시지는 초안의 결론에서 자동으로 채워진다");

  // 사람이 글을 고친다 — 근거에 없는 숫자를 넣으면 저장은 되지만 생성이 막힌다
  const pages = plan.plan_json.pages.map((p: Any) => ({ heading: p.heading, body: p.body }));
  pages[1] = { heading: "물을 조금 넣어요", body: "애호가들은 물을 3방울 넣어요" };
  const saved = await ok("studio_save_draft", { plan_revision_id: planId, expected_version: plan.version, pages });
  assert.equal(saved.changed, true);
  assert.deepEqual(saved.unverified_numbers, ["3"]);
  st = await status(topic);
  const gen = () => ({ topic_id: topic, format_intent: "card", plan_revision_id: planId, expected_topic_version: st.topic.version,
    expected_review_version: st.review.version, expected_plan_version: st.plans.find((p: Any) => p.plan_revision_id === planId).version });
  await fails("studio_generate", gen(), "numbers_unverified");
  // 옛 버전으로 저장하면 거절(다른 탭과 부딪히지 않게)
  await fails("studio_save_draft", { plan_revision_id: planId, expected_version: plan.version, pages }, "version_conflict");
  // 페이지 수는 못 바꾼다
  await fails("studio_save_draft", { plan_revision_id: planId, expected_version: saved.version, pages: pages.slice(1) }, "invalid_input");

  // 수정 지시: 새 초안이 저장될 때까지 지금 초안은 그대로
  const rw = await ok("studio_rewrite", { plan_revision_id: planId, expected_version: saved.version, instruction: "더 짧고 친근하게" });
  assert.equal(rw.existing, false);
  assert.equal((await ok("studio_rewrite", { plan_revision_id: planId, expected_version: saved.version, instruction: "다시 한번" })).existing, true, "반복 클릭은 같은 요청");
  await fails("studio_save_draft", { plan_revision_id: planId, expected_version: saved.version, pages }, "develop_in_progress");
  assert.equal((await row("select blocked_at from drink_plan_revisions where id = $1", [planId])).blocked_at, null, "다시 쓰는 동안 지금 초안은 막히지 않는다");
  const re = await workerCard();
  assert.equal(re.ctx.instruction, "더 짧고 친근하게");
  assert.equal(re.ctx.supersedes_plan_id, planId);
  assert.ok((await row("select blocked_at from drink_plan_revisions where id = $1", [planId])).blocked_at, "새 초안이 저장되면 옛 초안은 막힌다(지우지 않는다)");
  const newPlan = re.planId;

  st = await status(topic);
  const np = st.plans.find((p: Any) => p.plan_revision_id === newPlan);
  const payload = { topic_id: topic, format_intent: "card", plan_revision_id: newPlan, expected_topic_version: st.topic.version,
    expected_review_version: st.review.version, expected_plan_version: np.version };
  // 지원하지 않는 형식은 거절(나중에 실패시키지 않는다)
  await fails("studio_generate", { ...payload, format_intent: "explainer" }, "format_not_supported");
  const out = await ok("studio_generate", payload);
  assert.equal(out.approved, true);
  assert.equal(out.render.existing, false);
  const pl = await row("select plan_status from drink_plan_revisions where id = $1", [newPlan]);
  assert.equal(pl.plan_status, "approved");
  const ev = await row("select * from drink_workflow_events where topic_id = $1 and action = 'content_approved'", [topic]);
  assert.match(ev.reason, /스튜디오/);
  // 다시 눌러도 같은 제작 작업
  const again = await ok("studio_generate", payload);
  assert.equal(again.render.job_id, out.render.job_id);
  assert.equal(again.approved, false, "두 번 승인하지 않는다");
  assert.equal((await rows("select id from drink_production_jobs where plan_revision_id = $1", [newPlan])).length, 1);
  // 확정된 초안은 고칠 수 없다(결과가 어느 초안에서 나왔는지 섞이지 않는다)
  await fails("studio_save_draft", { plan_revision_id: newPlan, expected_version: np.version, pages }, "immutable");
  // 생성은 게시가 아니다
  assert.equal((await rows("select id from drink_publication_requests where topic_id = $1", [topic])).length, 0);
});

test("실패한 제작만 다시: 성공한 결과가 있으면 새로 만들지 않고, 실패한 작업은 retry_of 로만", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  await workerEvidence(await rpc("drinks_start_develop", { worker_id: "t" }));
  const { planId } = await workerCard();
  const st = await status(topic);
  const pv = st.plans.find((p: Any) => p.plan_revision_id === planId).version;
  const payload = { topic_id: topic, format_intent: "card", plan_revision_id: planId, expected_topic_version: st.topic.version, expected_review_version: st.review.version, expected_plan_version: pv };
  const out = await ok("studio_generate", payload);
  await db.exec(`set session_replication_role = replica; update drink_production_jobs set status = 'failed', finished_at = now(), error_code = 'render_error' where id = '${out.render.job_id}'; set session_replication_role = origin;`);
  const retry = await ok("studio_generate", { ...payload, retry_of: out.render.job_id });
  assert.notEqual(retry.render.job_id, out.render.job_id);
  assert.equal(retry.approved, false);
});

test("주가 바뀌어 원래 주간 한도가 끝났으면 이번 주 한도로 복구한다(새 결재를 지어내지 않는다)", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  await rpc("drinks_finish_develop", { ...lease(g), outcome: "failed", error_code: "draft_exists", error_message: "x", result: {} });
  // 지난주 한도로 바꿔 끼운다(트리거를 잠시 꺼 '그 요청이 지난주에 들어갔다'를 흉내 낸다)
  const old = await row(`insert into drink_develop_budgets (stage, purpose, cap_usd, approved_by, approver_words, expires_at, created_at)
    values ('weekly:2026-10-26', '지난주', 5, 'operator', '시험', now() - interval '1 day', now() - interval '8 days') returning id`);
  await db.exec(`set session_replication_role = replica; update drink_develop_requests set budget_id = '${old.id}' where id = '${g.job.request_id}'; set session_replication_role = origin;`);
  const rec = await ok("studio_prepare", { topic_id: topic });
  assert.equal(rec.action, "recovered");
  const q = await row("select budget_id from drink_develop_requests where id = $1", [rec.recovery.request_id]);
  const cur = await rpc("drinks_ensure_weekly_budget", {});
  assert.equal(q.budget_id, cur.budget_id);
  assert.notEqual(q.budget_id, old.id);
});

test("5축 점수가 65점 아래인 소재도 [생성]이 막히지 않는다 — 예외 사유는 '운영자가 직접 골랐다'로 기록된다", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  await workerEvidence(await rpc("drinks_start_develop", { worker_id: "t" }));
  const { planId } = await workerCard();
  const rv = await row("select id from drink_topic_reviews where topic_id = $1 and status = 'draft'", [topic]);
  await db.exec(`set session_replication_role = replica; update drink_topic_reviews set scores = '{"relevance":1,"utility":1,"curiosity":1,"fit_video":1,"fit_carousel":1,"timeliness":1}' where id = '${rv.id}'; set session_replication_role = origin;`);
  const st = await status(topic);
  const pv = st.plans.find((p: Any) => p.plan_revision_id === planId).version;
  const out = await ok("studio_generate", { topic_id: topic, format_intent: "card", plan_revision_id: planId, expected_topic_version: st.topic.version,
    expected_review_version: st.review.version, expected_plan_version: pv });
  assert.equal(out.approved, true);
  assert.match((await row("select score_exception_reason from drink_topics where id = $1", [topic])).score_exception_reason, /스튜디오/);
});

// ── 0077 사진형 카드 복구(2026-11-08) ──────────────────────────────────────────
const PHOTO_PAGES = PAGES.map((p) => p.role === "source" ? p : { ...p, heading: `[${p.heading}]`, image_prompt: `A sake bottle on a counter ${p.role}` });
const PHOTO_PLAN = { ...CARD_PLAN, pages: PHOTO_PAGES, layout: "photo", template_version: "card-photo-v1" };

test("0077 사진형: 화면에 보인 금액으로만 생성 — 금액 없이 누르면 아무것도 확정·구매하지 않고, 금액이 맞으면 그 초안 전용 결재로 유료 제작", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  await workerEvidence(await rpc("drinks_start_develop", { worker_id: "t" }));
  const { planId } = await workerCard(PHOTO_PLAN);
  let st = await status(topic);
  const plan = st.plans.find((p: Any) => p.plan_revision_id === planId);
  assert.equal(plan.plan_json.layout, "photo", "검증기가 사진형 칸을 버리지 않는다");
  assert.ok(plan.plan_json.pages.slice(0, 4).every((p: Any) => p.image_prompt), "쪽마다 사진 지시문 보존");
  assert.equal(plan.estimate.photo, true);
  assert.equal(plan.estimate.images, 4, "출처 장은 사진을 사지 않는다");
  const total = Number(plan.estimate.total_usd);
  assert.ok(total > 0);
  // 사람이 글을 고쳐도 사진 지시문은 남는다
  const pages = plan.plan_json.pages.map((p: Any) => ({ heading: p.heading, body: p.body }));
  pages[1] = { heading: "[물을] 조금 넣어요", body: "애호가들은 물을 넣어요" };
  const saved = await ok("studio_save_draft", { plan_revision_id: planId, expected_version: plan.version, pages });
  assert.equal((await row("select plan_json->'pages'->1->>'image_prompt' ip from drink_plan_revisions where id = $1", [planId])).ip, PHOTO_PAGES[1].image_prompt);
  st = await status(topic);
  const gen = (extra: Record<string, unknown>) => ({ topic_id: topic, format_intent: "card", plan_revision_id: planId, expected_topic_version: st.topic.version,
    expected_review_version: st.review.version, expected_plan_version: saved.version, ...extra });
  await fails("studio_generate", gen({}), "spend_confirm_required");
  await fails("studio_generate", gen({ approve_usd: total - 0.01 }), "spend_confirm_required");
  assert.equal((await row("select plan_status from drink_plan_revisions where id = $1", [planId])).plan_status, "draft", "금액 확인 전에는 확정도 하지 않는다(한 트랜잭션)");
  assert.equal((await rows("select id from drink_spend_approvals where plan_revision_id = $1", [planId])).length, 0);
  const out = await ok("studio_generate", gen({ approve_usd: total }));
  assert.equal(out.approved, true);
  const job = await row("select renderer, spend_approval_id from drink_production_jobs where id = $1", [out.render.job_id]);
  assert.equal(job.renderer, "paid");
  const ap = await row("select cap_usd, allowed_kinds, plan_revision_id, approver_words, expires_at from drink_spend_approvals where id = $1", [job.spend_approval_id]);
  assert.equal(Number(ap.cap_usd), total, "결재 상한 = 화면에 보인 금액");
  assert.deepEqual(ap.allowed_kinds, ["image"]);
  assert.equal(ap.plan_revision_id, planId);
  assert.match(ap.approver_words, /스튜디오/);
  assert.equal((await ok("studio_generate", gen({ approve_usd: total }))).render.job_id, out.render.job_id, "다시 눌러도 같은 작업");
  assert.equal((await rows("select id from drink_spend_approvals where plan_revision_id = $1", [planId])).length, 1, "결재도 하나");
});

test("0077 확정된 글자 카드 → [사진형으로 다시 만들기]: 같은 확정 근거로 새 초안, 옛 결과는 그대로, 새 초안 생성은 제출·승인을 거친다", async () => {
  const prep = await ok("studio_prepare", { candidate_id: await candidate(), format_intent: "card", categories: ["sake"] });
  const topic = prep.topic_id as string;
  await workerEvidence(await rpc("drinks_start_develop", { worker_id: "t" }));
  const { planId } = await workerCard();
  let st = await status(topic);
  const p0 = st.plans.find((p: Any) => p.plan_revision_id === planId);
  assert.equal(p0.estimate.photo, false);
  assert.equal(Number(p0.estimate.total_usd), 0, "글자 카드는 0원");
  const first = await ok("studio_generate", { topic_id: topic, format_intent: "card", plan_revision_id: planId, expected_topic_version: st.topic.version,
    expected_review_version: st.review.version, expected_plan_version: p0.version });
  assert.equal((await row("select renderer from drink_production_jobs where id = $1", [first.render.job_id])).renderer, "local");
  st = await status(topic);
  const approved = st.plans.find((p: Any) => p.plan_revision_id === planId);
  const rw = await ok("studio_rewrite", { plan_revision_id: planId, expected_version: approved.version, instruction: "사진형 카드로 다시 써 주세요" });
  assert.equal(rw.existing, false);
  const req = await row("select draft_evidence, format_intent, supersedes_plan_id from drink_develop_requests where id = $1", [rw.request_id]);
  assert.deepEqual([req.draft_evidence, req.format_intent, req.supersedes_plan_id], [false, "card", null]);
  const re = await workerCard(PHOTO_PLAN);
  assert.equal(re.ctx.instruction, "사진형 카드로 다시 써 주세요");
  assert.equal((await row("select plan_status from drink_plan_revisions where id = $1", [planId])).plan_status, "approved", "옛 확정은 그대로");
  st = await status(topic);
  const np = st.plans.find((p: Any) => p.plan_revision_id === re.planId);
  assert.ok(np.current && np.plan_status === "draft" && np.estimate.photo);
  await fails("studio_rewrite", { plan_revision_id: planId, expected_version: approved.version, instruction: "또" }, "invalid_input");
  await fails("studio_rewrite", { plan_revision_id: planId, expected_version: approved.version, instruction: "한 번 더" }, "draft_exists");
  const out = await ok("studio_generate", { topic_id: topic, format_intent: "card", plan_revision_id: re.planId, expected_plan_version: np.version,
    approve_usd: Number(np.estimate.total_usd) });
  assert.equal((await row("select plan_status from drink_plan_revisions where id = $1", [re.planId])).plan_status, "approved");
  assert.equal((await row("select renderer from drink_production_jobs where id = $1", [out.render.job_id])).renderer, "paid");
  const ev = await rows("select action from drink_workflow_events where entity_id = $1 and action in ('plan_submit','plan_approve') order by id", [re.planId]);
  assert.deepEqual(ev.map((e: Any) => e.action), ["plan_submit", "plan_approve"], "제출·승인 검사를 건너뛰지 않는다");
});
