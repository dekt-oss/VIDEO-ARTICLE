// 카드뉴스 형식 엔진(0065) DB 통합 테스트 — PGlite 위에 00(5x|6x)_drinks_*. 모델·네트워크·실제 인스타 호출 0.
// [이걸로](카드) → 근거 → 카드 제작안 초안 → [승인] 한 번 → 렌더 파일 묶음(카드+릴스) → 검수 → 발행 요청(음원) → 승인·재승인 → 점유.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d|8\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0065_drinks_card_reels.sql"), "0065 가 목록에 있어야 한다");
const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(join(DIR, m), "utf8"));
// 이 파일의 시험은 게시 '창'(0071 R6, 07:00~23:30 KST)을 재지 않는다 — 예약 시각을 '조금 전'으로 잡아 워커 claim 까지 보는데,
// 밤에 돌리면 창 밖이라 시각만으로 실패했다(2026-11-06 00:10 KST 실측). 창 규칙 자체는 tests/test_drinks_review_fixes.py 가 잰다.
await db.exec(`create or replace function drinks_publish_window() returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object('timezone', 'Asia/Seoul', 'start', '00:00', 'end', '23:59:59.999') $$;`);

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

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 3, timeliness: 2 };
const QUOTE1 = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking";
const QUOTE2 = "the smoky flavour is attributed to phenols, and in particular guaiacol";
const BODY = `${QUOTE1} in order to further enhance the taste. Chemically, ${QUOTE2}.`;
const WEEK = "2026-11-04";
const budget = () => rpc("drinks_open_develop_budget", { cap_usd: 2, stage: "시험", purpose: "시험", approver_words: "승인한다" });
const topicRow = (id: string) => row("select * from drink_topics where id = $1", [id]);
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);
const pubRow = (id: string) => row("select * from drink_publication_requests where id = $1", [id]);

const PAGES = [
  { role: "cover", heading: "위스키에 왜 물을 넣을까요?" },
  { role: "explain", heading: "물을 조금 넣어요", body: "애호가들은 물을 넣어요", claim_ids: ["c1"] },
  { role: "explain", heading: "연기 향의 정체", body: "페놀 때문이에요", claim_ids: ["c2"] },
  { role: "source", heading: "출처" },
];
const REEL = { hook_title: "위스키에 왜 물을 넣을까요?", share_line: "위스키 좋아하는 친구에게 보내 주세요" };
const CARD_PLAN = { pages: PAGES, reel: REEL, template_version: "card-reel-v1", notes: "시청자 결론(c1): 물을 넣는 습관이 있어요" };

async function researching(): Promise<string> {
  const t = await ok("create_topic", { title: "위스키에 물", question: `위스키에 물을 넣는 이유 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  await ok("triage", { topic_id: t.topic_id, expected_version: (await topicRow(t.topic_id)).version, scores: SCORES });
  await ok("topic_action", { topic_id: t.topic_id, expected_version: (await topicRow(t.topic_id)).version, action: "start_research" });
  return t.topic_id;
}

/** [이걸로] → 워커가 근거 초안 저장·성공 → 대본 요청이 이어진 상태. */
async function pickCard(b: Any, fmtInBrief = "carousel") {
  const topic = await researching();
  const s = await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const pick = await ok("pick_topic", { topic_id: topic, format: "card", editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(pick.maps_to, "carousel");
  assert.equal(pick.chain.kind, "evidence");
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.format_intent, "card");
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const claim = (cid: string, quote: string) => ({ claim_id: cid, text: `주장 ${cid}`, claim_type: "process", source_refs: [{ snapshot_id: s.snapshot_id, original_quote: quote }] });
  const save = await rpc("drinks_develop_save_evidence", { ...l, evidence_pack: { claims: [claim("c1", QUOTE1), claim("c2", QUOTE2)] },
    brief: { audience_question: "왜 물을 넣나", selected_claim_ids: ["c1", "c2"], proposed_formats: [fmtInBrief], required_claims: { [fmtInBrief]: ["c1"] } } });
  const fin = await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: { claims_kept: 2 } });
  return { topic, reviewId: save.review_id as string, fin };
}

async function draftCard(plan: Record<string, unknown> = CARD_PLAN) {
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  assert.equal(g.job.kind, "plan");
  assert.equal(g.job.draft_evidence, true);
  assert.equal(g.job.format_intent, "card", "워커가 카드 경로를 고를 수 있게 형식이 실린다");
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  const pl = await rpc("drinks_develop_save_plan", { ...l, plan_json: plan, core_takeaway_draft: "물을 조금 넣는 습관이 있어요" });
  await rpc("drinks_finish_develop", { ...l, outcome: "succeeded", result: {} });
  return { job: g.job, planId: pl.revision_id as string };
}

async function fills(reviewId: string, topic: string) {
  const r = await reviewRow(reviewId);
  const claims = r.evidence_pack.claims.map((c: Any) => ({ ...c, support_review: "supported" }));
  return ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims }, brief: r.brief, scores: SCORES });
}

async function approvePayload(topic: string, reviewId: string, planId: string) {
  const [t, r, p] = [await topicRow(topic), await reviewRow(reviewId), await planRow(planId)];
  return { topic_id: topic, expected_topic_version: t.version, review_id: reviewId, expected_review_version: r.version, plan_revision_id: planId, expected_plan_version: p.version,
    format_intent: "card" }; // 0072 라우트 검증(작업 단위 = 소재 × 형식)
}

/** 승인된 카드 제작안 → 렌더(릴스 포함) → 검수 승인까지. */
async function approvedOutput(withReel = true) {
  const b = await budget();
  const { topic, reviewId } = await pickCard(b);
  const { planId } = await draftCard(withReel ? CARD_PLAN : { pages: PAGES });
  await fills(reviewId, topic);
  await ok("approve_content", await approvePayload(topic, reviewId, planId));
  await ok("request_render", { plan_revision_id: planId });
  const job = (await rpc("drinks_start_render", { worker_id: "w" })).job;
  const lease = { job_id: job.job_id, lease_token: job.lease_token };
  const asset = async (role: string, position: number, mime: string) => {
    const key = `drinks/${job.job_id}/${role}_${position}${uniq()}`;
    const a = await rpc("drinks_register_asset", { ...lease, asset: { storage_key: key, sha256: "a".repeat(63) + (position % 10), mime, bytes: 10, rights: "generated_local", provenance: {} } });
    return { asset_id: a.asset_id, role, position };
  };
  const assets = [];
  for (let i = 1; i <= PAGES.length; i++) assets.push(await asset("page", i, "image/png"));
  // 릴스가 있는 제작안인데 영상이 빠지면 묶음을 받지 않는다
  if (withReel) await rpcFails("drinks_finish_render", { ...lease, outcome: "succeeded", assets, qa: {} }, "invalid_manifest");
  if (withReel) {
    assets.push(await asset("final_video", 1, "video/mp4"));
    assets.push(await asset("cover", 1, "image/jpeg"));
  }
  const done = await rpc("drinks_finish_render", { ...lease, outcome: "succeeded", assets, qa: {} });
  assert.equal(done.status, "succeeded");
  const review = await row("select * from drink_output_reviews where manifest_id = $1", [done.manifest_id]);
  const base = { page_order_ok: true, no_text_overflow: true, claims_match_evidence: true, source_page_ok: true };
  if (withReel) await fails("output_review_action", { review_id: review.id, expected_version: review.version, action: "approve", checklist: base }, "checklist_incomplete");
  await ok("output_review_action", { review_id: review.id, expected_version: review.version, action: "approve",
    checklist: withReel ? { ...base, reel_motion_ok: true, reel_hook_share_ok: true } : base });
  return { topic, planId, reviewId: review.id as string, manifestId: done.manifest_id as string };
}

async function account(connection: "fake" | "instagram_login" | "facebook_login" = "fake") {
  const ext = connection === "fake" ? `fake_${uniq()}` : `1784${Math.floor(Math.random() * 1e9)}`;
  const a = await ok("register_account", { external_account_id: ext, display_name: "시험", account_type: "test", connection,
    credential_ref: connection === "fake" ? null : "IG_TOKEN_TEST", capabilities: { post_types: ["carousel", "reel"] } });
  await rpc("drinks_account_verified", { account_id: a.account_id, ok: true, external_account_id: ext, username: "u" });
  const cur = await row("select version from drink_social_accounts where id = $1", [a.account_id]);
  await ok("account_action", { account_id: a.account_id, expected_version: cur.version, action: "enable_publish" });
  return a.account_id as string;
}
const seedAudio = async () => {
  const id = `aud_${uniq()}`;
  await row(`insert into drink_ig_audio (audio_id, audio_type, title, display_artist, first_seen_on, last_seen_on) values ($1, 'music', '노래', '가수', current_date, current_date) returning audio_id`, [id]);
  await row(`insert into drink_ig_audio_observations (audio_id, observed_on, list_position) values ($1, current_date, 1) returning audio_id`, [id]);
  return id;
};
const AUDIO = (id: string) => ({ mode: "ig_audio", audio_id: id, audio_volume: 90, video_volume: 10, sync_grade: "sync_free" });
const SOON = () => new Date(Date.now() - 60_000).toISOString();

test("카드뉴스: [이걸로] → 근거 → 대본 요청이 이어지고, 승인 전 초안은 제작으로 못 간다", async () => {
  const b = await budget();
  const { topic, reviewId, fin } = await pickCard(b);
  assert.equal(fin.result.chain[0].queued, true, "card_plan_not_built 로 멈추지 않는다");
  const { planId } = await draftCard();
  const p = await planRow(planId);
  assert.equal(p.format, "carousel");
  assert.equal(p.aspect_ratio, "4:5");
  assert.equal(p.plan_status, "draft");
  assert.equal(p.drafted_from_unapproved, true);
  assert.deepEqual(p.plan_json.reel, REEL, "릴스 묶음이 DB 검증기를 지나 보존된다");
  assert.equal((await reviewRow(reviewId)).status, "draft", "근거는 초안 그대로");
  assert.equal((await topicRow(topic)).status, "researching", "편성은 승인 때");
  await fails("request_render", { plan_revision_id: planId }, "not_renderable");
  // 근거가 비었으면 표시 없는 대본 요청은 여전히 막힌다
  await rpcFails("drinks_request_develop", { topic_id: topic, kind: "plan", budget_id: b.budget_id }, "review_not_approved");
});

test("카드뉴스 한 번 승인: 금액 없이 근거·편성·제작안이 함께 승인된다. 주장 확인을 안 하면 막힌다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickCard(b);
  const { planId } = await draftCard();
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "review_blocked");
  assert.equal((await reviewRow(reviewId)).status, "draft", "전부 되돌아간다");
  await fills(reviewId, topic);
  const r = await ok("approve_content", await approvePayload(topic, reviewId, planId));
  assert.equal(r.status, "selected");
  assert.equal(r.plan_status, "approved");
  assert.deepEqual(r.selected_formats, ["carousel"]);
  assert.equal(r.approved_amount_usd, null, "카드뉴스는 금액을 기록하지 않는다");
  assert.equal((await row("select drinks_plan_renderable($1) v", [planId])).v, null, "설명형과 달리 바로 렌더할 수 있다");
});

test("근거를 고치면 카드 제작안도 무효 — 승인이 막히고 다시 만들어야 한다", async () => {
  const b = await budget();
  const { topic, reviewId } = await pickCard(b);
  const { planId } = await draftCard();
  const r = await reviewRow(reviewId);
  const claims = r.evidence_pack.claims.map((c: Any, i: number) => ({ ...c, support_review: "supported", text: i === 0 ? "고친 문장" : c.text }));
  await ok("save_review", { topic_id: topic, review_id: reviewId, expected_version: r.version, evidence_pack: { claims }, brief: r.brief, scores: SCORES });
  assert.ok((await planRow(planId)).blocked_at, "근거 내용이 바뀌면 트리거가 차단한다");
  await fails("approve_content", await approvePayload(topic, reviewId, planId), "plan_blocked");
  const again = await ok("request_develop", { topic_id: topic, kind: "plan", format_intent: "card", draft_evidence: true, budget_id: b.budget_id });
  assert.equal(again.existing, false);
  const { planId: fresh } = await draftCard();
  await ok("approve_content", await approvePayload(topic, reviewId, fresh));
});

test("결재가 없으면 대본을 이어 만들지 않는다. 제작안 모양이 틀리면 저장하지 않는다", async () => {
  const topic = await researching();
  await ok("add_source", { topic_id: topic, source: { url: `https://example.org/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const pick = await ok("pick_topic", { topic_id: topic, format: "card", editorial_week: WEEK });
  await rpc("drinks_cancel_develop", { request_id: pick.chain.request_id });

  const b = await budget();
  await pickCard(b);
  const g = await rpc("drinks_start_develop", { worker_id: "t" });
  const l = { request_id: g.job.request_id, lease_token: g.job.lease_token };
  await rpcFails("drinks_develop_save_plan", { ...l, plan_json: { ...CARD_PLAN, reel: { hook_title: "", share_line: "x" } } }, "invalid_plan");
  await rpcFails("drinks_develop_save_plan", { ...l, plan_json: { ...CARD_PLAN, reel: { hook_title: "훅?", share_line: "x".repeat(61) } } }, "invalid_plan");
  await rpcFails("drinks_develop_save_plan", { ...l, plan_json: { pages: PAGES.slice(0, 2), reel: REEL } }, "invalid_plan");
  await rpcFails("drinks_develop_save_plan", { ...l, plan_json: { pages: [{ role: "explain", heading: "x", claim_ids: ["zz"] }] } }, "plan_claim_unknown");
  await rpc("drinks_cancel_develop", { request_id: g.job.request_id });
});

test("카드에 설명형을 더하면(0072: 형식은 바꾸는 게 아니라 더한다) 대기 중 카드 대본 요청은 그대로고, 필수 주장을 카드 형식으로 채운다", async () => {
  // 0065 까지는 형식을 바꾸면 옛 요청을 거뒀다. 0072 부터 요청이 자기 형식을 알아 둘이 나란히 산다 — 의도한 변경(docs/deviation-drinks-multi-format.md G1·G8).
  const b = await budget();
  const { topic, reviewId, fin } = await pickCard(b, "video");   // 브리프가 영상용인 근거
  assert.equal(fin.result.chain[0].queued, true);
  const cardReq = fin.result.chain[0].request_id;
  const toVideo = await ok("pick_topic", { topic_id: topic, format: "explainer", editorial_week: WEEK, budget_id: b.budget_id });
  assert.notEqual(toVideo.chain.request_id, cardReq, "설명형 대본 요청이 따로 들어간다");
  assert.equal((await row("select status from drink_develop_requests where id = $1", [cardReq])).status, "queued", "카드 대본 요청은 거두지 않는다");
  assert.equal((await row("select format_intent from drink_topic_picks where topic_id = $1", [topic])).format_intent, "card", "대표 형식은 바뀌지 않는다");
  assert.equal((await row("select count(*)::int n from drink_topic_format_picks where topic_id = $1", [topic])).n, 2);
  // 다시 카드로 — 이미 있는 요청을 돌려준다
  const toCard = await ok("pick_topic", { topic_id: topic, format: "card", editorial_week: WEEK, budget_id: b.budget_id });
  assert.equal(toCard.chain.queued, true);
  assert.equal(toCard.chain.existing, true);
  assert.equal(toCard.chain.request_id, cardReq);
  const { planId } = await draftCard();   // 먼저 들어간 카드 요청이 먼저 나온다
  const brief = (await reviewRow(reviewId)).brief;
  assert.deepEqual(brief.required_claims.carousel, ["c1"], "다른 형식의 필수 주장을 가져온다");
  assert.deepEqual(brief.proposed_formats, ["carousel", "video"], "형식 목록은 더한다(덮어쓰지 않는다)");
  assert.equal((await planRow(planId)).blocked_at, null, "저장하면서 채운 값이 이 제작안을 무효로 만들지 않는다");
  await rpc("drinks_cancel_develop", { request_id: toVideo.chain.request_id });   // 진행 중 요청이 있으면 승인하지 않는다(규칙 그대로)
  await fills(reviewId, topic);
  await ok("approve_content", await approvePayload(topic, reviewId, planId));
});

test("파일 묶음: 릴스 묶음이 없는 옛 카드 제작안은 옛 규칙 그대로, 릴스로는 못 올린다", async () => {
  const { reviewId } = await approvedOutput(false);
  const acc = await account();
  await fails("create_publication", { output_review_id: reviewId, account_id: acc, post_type: "reel", caption: "c" }, "invalid_input");
  const pub = await ok("create_publication", { output_review_id: reviewId, account_id: acc, caption: "c" });
  assert.equal(pub.post_type, "carousel");
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: AUDIO(await seedAudio()) }, "audio_not_for_carousel");
});

test("음원 계약: 카드 릴스는 음원 필수 · 승인 지문에 들어가고 · 승인 뒤 바꾸면 승인이 풀린다 · 워커가 그대로 받는다", async () => {
  const { reviewId } = await approvedOutput();
  const acc = await account();
  const audioId = await seedAudio();

  const board0 = await rpc("drinks_publish_board", {});
  const ready = board0.ready_outputs.find((o: Any) => o.output_review_id === reviewId);
  assert.deepEqual(ready.post_types, ["carousel", "reel"], "같은 묶음으로 둘 다 낼 수 있다");
  assert.ok(board0.audio_options.some((o: Any) => o.audio_id === audioId), "수집된 음원이 후보로 나온다");

  const carousel = await ok("create_publication", { output_review_id: reviewId, account_id: acc, caption: "카드" });
  assert.equal(carousel.post_type, "carousel");
  const pub = await ok("create_publication", { output_review_id: reviewId, account_id: acc, post_type: "reel", caption: "릴스", publish_at: SOON() });
  assert.equal(pub.post_type, "reel");
  const board1 = await rpc("drinks_publish_board", {});
  assert.equal(board1.ready_outputs.find((o: Any) => o.output_review_id === reviewId), undefined, "둘 다 만들었으면 목록에서 빠진다");

  // 필수인데 없으면 승인 요청이 막힌다. mode=none 도 막힌다.
  await fails("publication_action", { request_id: pub.request_id, expected_version: pub.version, action: "submit" }, "audio_required");
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: { mode: "none" } }, "audio_required");
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: { mode: "licensed_mix", sync_grade: "sync_free" } }, "licensed_mix_not_rendered");
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: AUDIO("없는음원") }, "audio_not_found");
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: { ...AUDIO(audioId), audio_volume: 0 } }, "invalid_input");
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: { ...AUDIO(audioId), sync_grade: undefined } }, "invalid_input");

  const set = await ok("set_publication_audio", { request_id: pub.request_id, expected_version: pub.version, audio: { ...AUDIO(audioId), title_snapshot: "화면이 보낸 거짓 제목" } });
  assert.equal(set.status, "draft");
  assert.equal(set.audio.title_snapshot, "노래", "제목은 서버가 음원 표에서 복사한다");
  assert.equal(set.audio.artist_snapshot, "가수");

  const sub = await ok("publication_action", { request_id: pub.request_id, expected_version: set.version, action: "submit" });
  const digest1 = sub.approval_digest;
  const app = await ok("publication_action", { request_id: pub.request_id, expected_version: sub.version, action: "approve", expected_digest: digest1 });
  assert.equal(app.status, "approved");
  // 직접 update 로 음원만 바꾸는 길은 없다
  await assert.rejects(db.query(`update drink_publication_requests set audio = audio || '{"audio_volume": 5}' where id = $1`, [pub.request_id]), /immutable/);

  // 승인 뒤 음원 변경 → 승인 풀림, 지문 바뀜, 옛 지문으로 승인 안 됨
  const changed = await ok("set_publication_audio", { request_id: pub.request_id, expected_version: app.version, audio: { ...AUDIO(audioId), audio_volume: 80 } });
  assert.equal(changed.status, "awaiting_approval");
  assert.notEqual(changed.approval_digest, digest1);
  const r1 = await pubRow(pub.request_id);
  assert.equal(r1.approved_at, null);
  assert.equal(r1.pause_code, "needs_reconfirm");
  await fails("publication_action", { request_id: pub.request_id, expected_version: changed.version, action: "approve", expected_digest: digest1 }, "digest_mismatch");
  const app2 = await ok("publication_action", { request_id: pub.request_id, expected_version: changed.version, action: "approve", expected_digest: changed.approval_digest });
  const sch = await ok("publication_action", { request_id: pub.request_id, expected_version: app2.version, action: "schedule" });
  assert.equal(sch.status, "scheduled");
  assert.equal((await pubRow(pub.request_id)).pause_code, null, "예약 때 지워진다");

  // 예약 뒤에도 바꾸면 다시 승인
  const again = await ok("set_publication_audio", { request_id: pub.request_id, expected_version: sch.version, audio: { ...AUDIO(audioId), audio_volume: 70 } });
  assert.equal(again.status, "awaiting_approval");
  const app3 = await ok("publication_action", { request_id: pub.request_id, expected_version: again.version, action: "approve", expected_digest: again.approval_digest });
  const sch3 = await ok("publication_action", { request_id: pub.request_id, expected_version: app3.version, action: "schedule" });

  // 워커: 저장된 값이 그대로 온다
  const got = (await rpc("drinks_claim_publication", { worker_id: "w" })).request;
  assert.equal(got.request_id, pub.request_id);
  assert.equal(sch3.status, "scheduled");
  assert.equal(got.audio.audio_id, audioId);
  assert.equal(got.audio.audio_volume, 70);
  assert.equal(got.audio_required, true);
  assert.ok(got.files.some((f: Any) => f.role === "final_video"));
  const lease = { request_id: got.request_id, lease_token: got.lease_token };
  // 재조회 통과 기록은 승인 지문을 바꾸지 않는다
  await rpc("drinks_publication_step", { ...lease, stage: "audio_verified" });
  const after = await pubRow(pub.request_id);
  assert.ok(after.audio_verified_at);
  const gate = await rpc("drinks_publication_step", { ...lease, stage: "before_publish" });
  assert.equal(gate.proceed, true, "재조회 시각은 지문 밖이다");
  // 음원을 못 붙이면 멈춘다 — 게시 호출 전이라 paused 가 받아진다
  const stopped = await rpc("drinks_finish_publication", { ...lease, outcome: "paused", error_code: "audio_failed", error_message: "음원 없이 올리지 않았습니다" });
  assert.equal(stopped.status, "paused");
  const p = await pubRow(pub.request_id);
  assert.equal(p.pause_code, "audio_failed");
  assert.equal(p.external_post_id, null);
  // 다른 음원을 고르면 다시 승인 대기로
  const other = await seedAudio();
  const redo = await ok("set_publication_audio", { request_id: pub.request_id, expected_version: p.version, audio: AUDIO(other) });
  assert.equal(redo.status, "awaiting_approval");
  // 게시된 뒤에는 못 바꾼다(게시 중도)
  await rpc("drinks_publication_action", { request_id: pub.request_id, expected_version: redo.version, action: "cancel", reason: "시험 끝" });
  await fails("set_publication_audio", { request_id: pub.request_id, expected_version: (await pubRow(pub.request_id)).version, audio: AUDIO(other) }, "invalid_state");
});

test("음원 게시 조건: 박자 맞춤은 자동 게시 안 됨 · Instagram 로그인 연결은 인스타 음원 불가", async () => {
  const { reviewId } = await approvedOutput();
  const audioId = await seedAudio();
  const live = await account("instagram_login");
  await fails("create_publication", { output_review_id: reviewId, account_id: live, post_type: "reel", caption: "c", audio: AUDIO(audioId) }, "audio_connection_unsupported");

  const acc = await account();
  const pub = await ok("create_publication", { output_review_id: reviewId, account_id: acc, post_type: "reel", caption: "c", publish_at: SOON(),
    audio: { ...AUDIO(audioId), sync_grade: "sync_required" } });
  const sub = await ok("publication_action", { request_id: pub.request_id, expected_version: pub.version, action: "submit" });
  const app = await ok("publication_action", { request_id: pub.request_id, expected_version: sub.version, action: "approve", expected_digest: sub.approval_digest });
  await fails("publication_action", { request_id: pub.request_id, expected_version: app.version, action: "schedule" }, "not_publishable");
  assert.equal((await row("select drinks_pub_block($1) v", [pub.request_id])).v, "audio_sync_required");
  await rpc("drinks_publication_action", { request_id: pub.request_id, expected_version: app.version, action: "cancel", reason: "시험 끝" });
});

test("옛 승인 지문은 그대로다 — 음원이 없으면 0055 계산과 같다", async () => {
  const { reviewId } = await approvedOutput(false);
  const acc = await account();
  const pub = await ok("create_publication", { output_review_id: reviewId, account_id: acc, caption: "옛 지문" });
  const r = await row(`select encode(sha256(convert_to(concat_ws('|', 'drinks-pub-v1', q.manifest_id::text, q.manifest_hash, q.account_id::text,
      q.target_external_account_id, q.post_type, q.caption, coalesce(q.cover_asset_id::text, ''),
      coalesce(to_char(q.publish_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), '')), 'UTF8')), 'hex') as v1, drinks_pub_digest(q) as now
    from drink_publication_requests q where q.id = $1`, [pub.request_id]);
  assert.equal(r.now, r.v1);
  // 작성 중 요청도 취소된다(0055 결함을 0065 가 고쳤다) — 음원이 없어 보류할 때의 길이다
  const c = await ok("publication_action", { request_id: pub.request_id, expected_version: pub.version, action: "cancel", reason: "보류" });
  assert.equal(c.status, "canceled");
});

test("권한: 새 함수는 anon 이 못 부른다. 워커 함수에 승인 호출이 없다", async () => {
  assert.equal((await row(`select has_function_privilege('anon', 'public.drinks_set_publication_audio(jsonb)', 'EXECUTE') v`)).v, false);
  assert.equal((await row(`select has_function_privilege('anon', 'public.drinks_format_required(jsonb, text)', 'EXECUTE') v`)).v, false);
  const src = readFileSync(join(DIR, "0065_drinks_card_reels.sql"), "utf8");
  for (const fn of ["drinks_start_develop", "drinks_develop_save_plan", "drinks_develop_chain_next"]) {
    const body = src.split(`create or replace function ${fn}(`)[1].split("end $$;")[0];
    assert.doesNotMatch(body, /drinks_(review_action|plan_action|select|approve_content)\(/, `${fn} 는 승인 함수를 부르지 않는다`);
  }
});
