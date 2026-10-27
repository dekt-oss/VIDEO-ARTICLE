// 사진형 카드뉴스 유료 그림(0056) DB 통합 테스트 — PGlite 위에 0050~0056.
// 0056: 사진형 카드(layout=photo / template_version=card-photo-v1)도 결재 안에서 쪽마다 4:5 그림을 살 수 있다.
//   · drinks_request_render 유료 허용 조건  · drinks_estimate_render 카드 쪽 계산(항목 이름 page-NN-photo)
//   · drinks_validate_plan 이 카드 필드(image_prompt·kicker·category·photo_shift·layout·caption)를 버리지 않는다
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql", "0054_drinks_spend.sql", "0055_drinks_publish_loop.sql", "0056_drinks_card_paid.sql"]
  .map((f) => join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations", f));
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
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const uniq = () => Math.random().toString(36).slice(2);
const hex = () => Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "산지의 신청에 따라 국세청장관이 지정하면 산지 이름을 독점적으로 쓸 수 있다.";
const brief = { audience_question: "누가 정할까?", core_takeaway: "산지가 신청하고 장관이 지정", selected_claim_ids: ["c1"],
  proposed_formats: ["carousel", "video"], required_claims: { carousel: ["c1"], video: ["c1"] } };
const tv = async (id: string) => (await row("select version from drink_topics where id = $1", [id])).version;
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);

/** 근거 승인 → 편성 → (선택) 제작안 저장. 승인까지 가려면 approve=true. */
let lastReview = "";
async function plan(format: "carousel" | "video", plan_json: Any, approve = true) {
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
  lastReview = r.id;
  await ok("select", { topic_id: id, expected_version: await tv(id), review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["carousel", "video"], editorial_week: "2026-10-26" });
  const v = await ok("save_plan", { topic_id: id, format, topic_review_id: r.id, plan_json });
  if (approve) {
    let p = await planRow(v.revision_id);
    await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "submit" });
    p = await planRow(v.revision_id);
    await ok("plan_action", { revision_id: p.id, expected_version: p.version, action: "approve" });
  }
  return v.revision_id as string;
}

const CAPTION = { title: "지리적 표시, 누가 정할까?", emoji: "🍶", intro: "산지 이름은 아무나 못 써요.", points: ["산지가 신청해요", "장관이 지정해요"],
  hashtags: ["사케", "술째리고"] };
const photoPages = () => [
  { role: "cover", heading: "산지 이름,\n누가 [정할까]?", kicker: "술째리고 · 사케 상식", category: "지리적 표시", photo_shift: -110,
    image_prompt: "A shelf of unbranded sake bottles" },
  { role: "explain", heading: "산지가 [신청]해요", body: "국세청장관이 지정해요", claim_ids: ["c1"], image_prompt: "An office desk with an envelope" },
  { role: "explain", heading: "그림 없는 쪽", claim_ids: ["c1"], image_prompt: "   " },
  { role: "source", heading: "출처", body: "국세청", image_prompt: "무시되어야 하는 출처 장 그림" },
];
const photoPlan = (extra: Any = {}) => ({ layout: "photo", pages: photoPages(), caption: CAPTION, ...extra });

const open = (planId: string | null, cap: number) => ok("open_spend_approval", {
  ...(planId ? { plan_revision_id: planId } : {}), stage: "사진형 카드 그림", purpose: "시험", cap_usd: cap, allowed_kinds: ["image"],
  approver_words: "승인한다 진행해", order_hash: hex() });

test("제작안 저장이 사진형 카드 필드를 버리지 않는다 — 쪽 필드·layout·caption 보존, 글자 카드 모양은 그대로", async () => {
  const id = await plan("carousel", photoPlan());
  const pj = (await planRow(id)).plan_json;
  assert.equal(pj.layout, "photo");
  assert.deepEqual(pj.caption, CAPTION);
  assert.equal(pj.pages[0].image_prompt, "A shelf of unbranded sake bottles");
  assert.deepEqual([pj.pages[0].kicker, pj.pages[0].category, pj.pages[0].photo_shift], ["술째리고 · 사케 상식", "지리적 표시", -110]);
  assert.equal(pj.pages[0].heading, "산지 이름,\n누가 [정할까]?", "강조 대괄호·줄바꿈은 그대로");
  assert.equal(pj.pages[3].image_prompt, "무시되어야 하는 출처 장 그림", "출처 장에 적힌 지시문도 저장은 된다(사는 쪽에서 뺀다)");
  // 글자 카드: 새 키가 하나도 생기지 않는다(0054 와 같은 저장 모양)
  const text = await plan("carousel", { pages: [{ role: "cover", heading: "표지" }, { role: "explain", heading: "설명", claim_ids: ["c1"] }] }, false);
  const tj = (await planRow(text)).plan_json;
  assert.deepEqual(Object.keys(tj).sort(), ["notes", "pages", "template_version"]);
  assert.deepEqual(Object.keys(tj.pages[0]).sort(), ["body", "claim_ids", "graphic_spec", "heading", "position", "role"]);
});

test("카드 제작안의 새 필드 검사 — 알 수 없는 layout·숫자가 아닌 photo_shift·객체가 아닌 caption 은 거절", async () => {
  await plan("carousel", photoPlan(), false);   // 근거 승인된 검토 행 하나가 필요하다
  // save_plan 은 주제·근거부터 필요하니 검사 함수를 직접 부른다
  const probe = async (planJson: Any) => {
    try {
      await db.exec("set role service_role");
      const res = await db.query<{ r: Any }>(
        "select drinks_validate_plan('carousel', $1::jsonb, r) as r from drink_topic_reviews r where r.id = $2", [JSON.stringify(planJson), lastReview]);
      return { out: res.rows[0].r as Any, err: null as string | null };
    } catch (e) {
      return { out: null, err: (e as Error).message };
    } finally {
      await db.exec("reset role");
    }
  };
  assert.match((await probe({ layout: "grid", pages: photoPages() })).err ?? "", /^drinks:invalid_plan:.*layout/);
  const shiftBad = photoPages(); (shiftBad[0] as Any).photo_shift = "위로";
  assert.match((await probe({ layout: "photo", pages: shiftBad })).err ?? "", /^drinks:invalid_plan:.*photo_shift/);
  assert.match((await probe({ layout: "photo", pages: photoPages(), caption: "그냥 글" })).err ?? "", /^drinks:invalid_plan:.*caption/);
  const good = await probe({ layout: "photo", pages: photoPages(), caption: CAPTION });
  assert.equal(good.err, null);
  assert.equal(good.out.layout, "photo");
});

test("화면용 예상: 사진형 카드는 image_prompt 가 있는 쪽(출처 장 제외)을 실사 단가로 센다 — scenes 는 비고 pages 에 담긴다", async () => {
  const id = await plan("carousel", photoPlan());
  const s = (await worker("drinks_plan_spend", { plan_revision_id: id })).estimate;
  assert.deepEqual(s.scenes, [], "영상 장면 배열은 그대로(카드는 비어 있다)");
  assert.deepEqual(s.pages.map((x: Any) => [x.position, x.role, x.kind, Number(x.usd), Number(x.price_usd), x.bought]),
    [[1, "cover", "photo", 0.039, 0.039, false], [2, "explain", "photo", 0.039, 0.039, false]]);
  assert.equal(Number(s.total_usd), 0.078);
  assert.equal(s.images, 2);
  assert.equal(s.bought, 0);
  // template_version 만으로도 사진형이다(엔진 is_photo_plan 과 같은 판정)
  const tvOnly = await plan("carousel", { template_version: "card-photo-v1", pages: photoPages() }, false);
  assert.equal(Number((await worker("drinks_plan_spend", { plan_revision_id: tvOnly })).estimate.total_usd), 0.078);
  // 글자 카드는 0원
  const text = await plan("carousel", { pages: photoPages() }, false);
  const t = (await worker("drinks_plan_spend", { plan_revision_id: text })).estimate;
  assert.deepEqual([t.pages, Number(t.total_usd), t.images], [[], 0, 0]);
});

test("영상 제작안의 예상은 0054 와 같은 꼴(pages 는 빈 배열, 합계는 장면만)", async () => {
  const id = await plan("video", { scenes: [
    { narration: "산지 이름, 아무나 쓸까요?", content_kind: "transition", visual_role: "reality", visual_prompt: "A shelf of bottles" },
    { narration: "산지가 신청하고 장관이 지정합니다", visual_role: "mechanism", claim_ids: ["c1"], visual_prompt: "Isometric diorama" },
    { narration: "라벨을 확인해 보세요", content_kind: "transition", visual_role: "text_card" }] }, false);
  const s = (await worker("drinks_plan_spend", { plan_revision_id: id })).estimate;
  assert.deepEqual(s.pages, []);
  assert.deepEqual(s.scenes.map((x: Any) => [x.position, x.role, Number(x.usd)]), [[1, "reality", 0.039], [2, "mechanism", 0.134], [3, "text_card", 0]]);
  assert.equal(Number(s.total_usd), 0.173);
  assert.equal(s.images, 2);
});

test("유료 렌더 요청: 사진형 카드는 결재 안에서 허용, 글자 카드는 여전히 거절 — 나머지 검사(결재 필수·전용·상한)는 그대로", async () => {
  const text = await plan("carousel", { pages: [{ role: "cover", heading: "표지" }, { role: "explain", heading: "설명", claim_ids: ["c1"] }] });
  const ta = await open(text, 1);
  const refused = await fails("request_render", { plan_revision_id: text, paid: true, spend_approval_id: ta.approval_id }, "paid_disabled");
  assert.match(JSON.stringify(refused), /사진형 카드뉴스/);

  const id = await plan("carousel", photoPlan());
  await fails("request_render", { plan_revision_id: id, paid: true }, "paid_disabled");   // 결재 없이는 안 된다
  const other = await open(null, 1);
  await fails("request_render", { plan_revision_id: id, paid: true, spend_approval_id: other.approval_id }, "ownership");
  const small = await open(id, 0.05);
  const low = await fails("request_render", { plan_revision_id: id, paid: true, spend_approval_id: small.approval_id }, "budget_insufficient");
  assert.equal(Number(low.detail.estimate.total_usd), 0.078);
  await ok("close_spend_approval", { approval_id: small.approval_id, reason: "상한 부족" });

  const a = await open(id, 0.2);
  const j = await ok("request_render", { plan_revision_id: id, paid: true, spend_approval_id: a.approval_id });
  assert.equal(j.renderer, "paid");
  assert.equal(Number(j.estimate.total_usd), 0.078);
  const jr = await row("select format, renderer, spend_approval_id from drink_production_jobs where id = $1", [j.job_id]);
  assert.deepEqual([jr.format, jr.renderer, jr.spend_approval_id], ["carousel", "paid", a.approval_id]);

  // 워커가 page-01-photo 를 사고 나면 다음 예상에서 그 쪽은 0원(다시 쓴다)
  let got = await worker("drinks_start_render", { worker_id: "t" });
  while (got.job && got.job.job_id !== j.job_id) {
    await worker("drinks_finish_render", { job_id: got.job.job_id, lease_token: got.job.lease_token, outcome: "failed", error_code: "x" });
    got = await worker("drinks_start_render", { worker_id: "t" });
  }
  assert.equal(got.job.plan.layout, "photo", "워커가 받는 제작안에 layout 이 남아 있다");
  assert.equal(got.job.plan.pages[0].image_prompt, "A shelf of unbranded sake bottles");
  const lease = { job_id: j.job_id, lease_token: got.job.lease_token };
  const h = await worker("drinks_hold_spend", { approval_id: a.approval_id, item_key: "page-01-photo", kind: "image", provider: "gemini",
    model: "gemini-2.5-flash-image", est_usd: 0.039, ...lease });
  await worker("drinks_settle_spend", { hold_id: h.hold_id, outcome: "settled", actual_usd: 0.039 });
  const est = (await worker("drinks_plan_spend", { plan_revision_id: id })).estimate;
  assert.equal(Number(est.total_usd), 0.039);
  assert.equal(est.bought, 1);
  assert.equal(est.images, 1);
  assert.deepEqual(est.pages.map((x: Any) => [x.position, x.bought, Number(x.usd)]), [[1, true, 0], [2, false, 0.039]]);
});

test("브라우저 역할(anon)은 새·다시 만든 함수를 부르지 못한다", async () => {
  await db.exec("set role anon");
  try {
    await assert.rejects(db.query(`select drinks_is_photo_plan('{}'::jsonb)`), /permission denied/);
    await assert.rejects(db.query(`select drinks_estimate_render(gen_random_uuid())`), /permission denied/);
    await assert.rejects(db.query(`select drinks_request_render('{}'::jsonb)`), /permission denied/);
  } finally {
    await db.exec("reset role");
  }
});
