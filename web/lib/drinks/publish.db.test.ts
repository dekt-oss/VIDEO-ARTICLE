// 주류 D단계 순환(0055) DB 통합 테스트 — PGlite 위에 0050~0055.
// 운영자 동작은 runDrinksAction 경로(라우트와 같은 코드), 워커 동작(점유·단계·끝내기·대조·성과)은 rpc 직접.
// 한 바퀴 전체(수집 → 렌더 → 게시 → 성과 → 전략 반영)는 Python 워커로 tests/test_drinks_loop_e2e.py 가 본다.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql", "0054_drinks_spend.sql", "0055_drinks_publish_loop.sql", "0056_drinks_function_search_path.sql"]
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
const fails = async (action: string, payload: Record<string, unknown>, code: string) => {
  const r = await act(action, payload);
  assert.notEqual(r.status, 200, `${action} 가 통과하면 안 된다`);
  assert.equal(r.body.code, code, JSON.stringify(r.body));
};
const worker = async (fn: string, p: Record<string, unknown>): Promise<Any> => {
  const r = await exec(fn, p);
  if (r.error) throw new Error(r.error.message);
  return r.data;
};
const workerFails = async (fn: string, p: Record<string, unknown>, code: string) => {
  const r = await exec(fn, p);
  assert.ok(r.error, `${fn} 가 통과하면 안 된다`);
  assert.match(r.error!.message, new RegExp(`^drinks:${code}:`));
};
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const uniq = () => Math.random().toString(36).slice(2);
const hex = () => Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");
const ver = async (table: string, id: string) => (await row(`select version from ${table} where id = $1`, [id])).version;
const pub = (id: string) => row("select * from drink_publication_requests where id = $1", [id]);
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "준마이 다이긴조는 정미율 50% 이하의 쌀을 사용한다. 양조 알코올을 첨가하지 않는다.";
const CARD_CK = { page_order_ok: true, no_text_overflow: true, claims_match_evidence: true, source_page_ok: true };

/** 근거 승인 → 카드 편성 → 제작안 승인 → (워커처럼) 렌더 → 검수 승인. 검수 id 와 묶음 id. */
async function approvedCard(cats = ["sake"]) {
  const t = await ok("create_topic", { title: "다이긴조", question: `다이긴조는 왜 비쌀까 ${uniq()}`, categories: cats, lane: "evergreen" });
  const id = t.topic_id;
  await ok("triage", { topic_id: id, expected_version: await ver("drink_topics", id), scores: SCORES });
  await ok("topic_action", { topic_id: id, expected_version: await ver("drink_topics", id), action: "start_research" });
  const s = await ok("add_source", { topic_id: id, source: { url: `https://www.nta.go.jp/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const claims = [
    { claim_id: "c1", text: "정미율 50% 이하", claim_type: "process", support_review: "supported",
      source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "정미율 50% 이하의 쌀을 사용한다" }] },
    { claim_id: "c2", text: "양조 알코올 무첨가", claim_type: "product_fact", support_review: "supported",
      source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "양조 알코올을 첨가하지 않는다" }] }];
  const sv = await ok("save_review", { topic_id: id, expected_topic_version: await ver("drink_topics", id), scores: SCORES,
    evidence_pack: { claims }, brief: { audience_question: "왜?", core_takeaway: "쌀을 깎는다", selected_claim_ids: ["c1", "c2"],
      proposed_formats: ["carousel"], required_claims: { carousel: ["c1", "c2"] } } });
  for (const a of ["submit", "approve"]) {
    await ok("review_action", { review_id: sv.review_id, expected_version: await ver("drink_topic_reviews", sv.review_id), action: a });
  }
  const rv = await row("select approved_hash from drink_topic_reviews where id = $1", [sv.review_id]);
  await ok("select", { topic_id: id, expected_version: await ver("drink_topics", id), review_id: sv.review_id,
    review_input_hash: rv.approved_hash, formats: ["carousel"], editorial_week: "2026-10-26" });
  const c = await ok("save_plan", { topic_id: id, format: "carousel", topic_review_id: sv.review_id, plan_json: { pages: [
    { role: "cover", heading: "다이긴조" }, { role: "explain", heading: "정미율", body: "50% 이하", claim_ids: ["c1"] },
    { role: "checklist", heading: "라벨", body: "양조 알코올 무첨가", claim_ids: ["c2"] }] } });
  for (const a of ["submit", "approve"]) {
    await ok("plan_action", { revision_id: c.revision_id, expected_version: await ver("drink_plan_revisions", c.revision_id), action: a });
  }
  await ok("request_render", { plan_revision_id: c.revision_id });
  const got = await worker("drinks_start_render", { worker_id: "t" });
  const lease = { job_id: got.job.job_id, lease_token: got.job.lease_token };
  const assets = [];
  for (let i = 1; i <= 3; i++) {
    const a = await worker("drinks_register_asset", { ...lease, asset: { storage_key: `drinks/${got.job.job_id}/page_${i}`, sha256: hex(),
      mime: "image/png", bytes: 1000, width: 1080, height: 1350, rights: "generated_local" } });
    assets.push({ asset_id: a.asset_id, role: "page", position: i });
  }
  const fin = await worker("drinks_finish_render", { ...lease, outcome: "succeeded", assets, qa: {} });
  const rev = await row("select id, version from drink_output_reviews where manifest_id = $1", [fin.manifest_id]);
  await ok("output_review_action", { review_id: rev.id, expected_version: rev.version, action: "approve", checklist: CARD_CK });
  return { reviewId: rev.id as string, manifestId: fin.manifest_id as string, planId: c.revision_id as string, topicId: id as string,
    reviewVersion: (await row("select version from drink_output_reviews where id = $1", [rev.id])).version as number };
}

async function activeAccount(ext = `fake_${uniq()}`) {
  const a = await ok("register_account", { external_account_id: ext, display_name: "술째리고(시험)", account_type: "test",
    connection: "fake", capabilities: { post_types: ["carousel", "reel"] } });
  await worker("drinks_account_verified", { account_id: a.account_id, ok: true, external_account_id: ext, username: "t" });
  await ok("account_action", { account_id: a.account_id, expected_version: await ver("drink_social_accounts", a.account_id),
    action: "enable_publish" });
  return a.account_id as string;
}

/** 작성 → 승인 요청 → 지문 승인 → 예약. */
async function scheduled(reviewId: string, accountId: string, publishAt = minutesAgo(1), caption = "쌀을 깎아요") {
  const r = await ok("create_publication", { output_review_id: reviewId, account_id: accountId, caption, publish_at: publishAt });
  await ok("publication_action", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id), action: "submit" });
  const p = await pub(r.request_id);
  await ok("publication_action", { request_id: r.request_id, expected_version: p.version, action: "approve", expected_digest: p.approval_digest });
  await ok("publication_action", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id), action: "schedule" });
  return r.request_id as string;
}

// ─────────────────────────────────────────────────────────────

test("계정: 가짜·실제 ID 접두어가 섞이지 않는다 · 토큰 원문 거부 · 외부 ID 불변 · 대조 전엔 발행을 못 켠다 · 불일치는 mismatch", async () => {
  await fails("register_account", { external_account_id: "fake_x", display_name: "x", connection: "instagram_login",
    credential_ref: "IG_TOKEN" }, "invalid_input");
  await fails("register_account", { external_account_id: "17841400000", display_name: "x", connection: "fake" }, "invalid_input");
  await fails("register_account", { external_account_id: "17841400000", display_name: "x", connection: "instagram_login" }, "invalid_input");
  await fails("register_account", { external_account_id: "17841400000", display_name: "x", connection: "instagram_login",
    credential_ref: "IG_TOKEN", access_token: "EAAB..." }, "invalid_input");
  const a = await ok("register_account", { external_account_id: "17841400001", display_name: "술째리고", connection: "instagram_login",
    credential_ref: "SOOLJJERIGO_IG_TOKEN", capabilities: { post_types: ["carousel"] } });
  assert.equal(a.status, "pending_verification");
  await fails("account_action", { account_id: a.account_id, expected_version: await ver("drink_social_accounts", a.account_id),
    action: "enable_publish" }, "invalid_state");
  await assert.rejects(db.query("update drink_social_accounts set external_account_id = '1' where id = $1", [a.account_id]), /immutable/);
  const v = await worker("drinks_account_verified", { account_id: a.account_id, ok: true, external_account_id: "999", username: "other" });
  assert.equal(v.status, "mismatch", "다른 계정의 토큰으로 기존 연결을 갱신하지 않는다");
  await fails("register_account", { external_account_id: "17841400001", display_name: "중복", connection: "instagram_login",
    credential_ref: "X_TOKEN" }, "duplicate_account");
});

test("발행안: 검수 승인된 묶음만 · 같은 제작안·계정·형식에 살아 있는 요청 하나 · 작성 중에만 고친다 · 승인은 화면의 지문으로만", async () => {
  const C = await approvedCard();
  const acc = await activeAccount();
  const r = await ok("create_publication", { output_review_id: C.reviewId, account_id: acc, caption: "첫 캡션" });
  assert.equal(r.post_type, "carousel");
  await fails("create_publication", { output_review_id: C.reviewId, account_id: acc, caption: "중복" }, "duplicate_publication");
  await ok("update_publication", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id),
    caption: "고친 캡션", publish_at: minutesAgo(-60) });
  await fails("publication_action", { request_id: r.request_id, expected_version: 1, action: "submit" }, "version_conflict");
  await ok("publication_action", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id), action: "submit" });
  let p = await pub(r.request_id);
  await fails("update_publication", { request_id: r.request_id, expected_version: p.version, caption: "몰래" }, "invalid_state");
  await assert.rejects(db.query("update drink_publication_requests set caption = 'x' where id = $1", [r.request_id]), /immutable/,
    "함수를 우회한 UPDATE 도 내용을 못 바꾼다");
  await fails("publication_action", { request_id: r.request_id, expected_version: p.version, action: "approve",
    expected_digest: "0".repeat(64) }, "digest_mismatch");
  await ok("publication_action", { request_id: r.request_id, expected_version: p.version, action: "approve", expected_digest: p.approval_digest });
  p = await pub(r.request_id);
  assert.equal(p.status, "approved");
  await ok("publication_action", { request_id: r.request_id, expected_version: p.version, action: "cancel", reason: "시험" });
  assert.equal((await pub(r.request_id)).status, "canceled");
  await ok("create_publication", { output_review_id: C.reviewId, account_id: acc, caption: "취소 뒤 새 요청" });
});

test("예약: 발행 스위치가 꺼진 계정·검수 철회·너무 늦은 시각은 막는다 · 계정 끄면 예약이 멈춘다", async () => {
  const C = await approvedCard();
  const acc = await activeAccount();
  await ok("account_action", { account_id: acc, expected_version: await ver("drink_social_accounts", acc), action: "disable_publish" });
  const r = await ok("create_publication", { output_review_id: C.reviewId, account_id: acc, caption: "c", publish_at: minutesAgo(1) });
  await ok("publication_action", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id), action: "submit" });
  const p = await pub(r.request_id);
  await ok("publication_action", { request_id: r.request_id, expected_version: p.version, action: "approve", expected_digest: p.approval_digest });
  await fails("publication_action", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id),
    action: "schedule" }, "not_publishable");
  await ok("account_action", { account_id: acc, expected_version: await ver("drink_social_accounts", acc), action: "enable_publish" });
  await ok("publication_action", { request_id: r.request_id, expected_version: await ver("drink_publication_requests", r.request_id), action: "schedule" });
  await ok("account_action", { account_id: acc, expected_version: await ver("drink_social_accounts", acc), action: "disable_publish" });
  const q = await pub(r.request_id);
  assert.equal(q.status, "paused");
  assert.equal(q.pause_code, "publish_disabled", "다른 계정으로 대신 게시하지 않고 멈춘다");

  const L = await approvedCard();
  const acc2 = await activeAccount();
  const old = await ok("create_publication", { output_review_id: L.reviewId, account_id: acc2, caption: "c", publish_at: minutesAgo(180) });
  await ok("publication_action", { request_id: old.request_id, expected_version: await ver("drink_publication_requests", old.request_id), action: "submit" });
  const o = await pub(old.request_id);
  await ok("publication_action", { request_id: old.request_id, expected_version: o.version, action: "approve", expected_digest: o.approval_digest });
  await fails("publication_action", { request_id: old.request_id, expected_version: await ver("drink_publication_requests", old.request_id),
    action: "schedule" }, "too_late");
});

test("워커: 예약 뒤 검수가 철회되면 게시하지 않고 paused · 게시 직전 취소는 canceled · 게시 호출 뒤엔 failed 로 못 닫는다", async () => {
  const acc = await activeAccount();
  const A = await approvedCard();
  const a = await scheduled(A.reviewId, acc);
  await ok("output_review_action", { review_id: A.reviewId, expected_version: A.reviewVersion, action: "revoke", reason: "글자 잘림 발견" });
  const none = await worker("drinks_claim_publication", { worker_id: "t" });
  assert.equal(none.request, null);
  assert.equal((await pub(a)).pause_code, "output_not_usable");

  const B = await approvedCard();
  const b = await scheduled(B.reviewId, acc);
  const got = await worker("drinks_claim_publication", { worker_id: "t" });
  assert.equal(got.request.request_id, b);
  assert.equal(got.request.files.length, 3);
  assert.deepEqual(got.request.files.map((f: Any) => f.position), [1, 2, 3]);
  const lease = { request_id: b, lease_token: got.request.lease_token };
  await worker("drinks_publication_step", { ...lease, stage: "containers_created", container_ids: ["c1", "c2", "c3", "p"] });
  await ok("publication_action", { request_id: b, expected_version: await ver("drink_publication_requests", b), action: "cancel" });
  assert.equal((await pub(b)).status, "publishing", "게시 중에는 취소 요청만 남는다");
  const gate = await worker("drinks_publication_step", { ...lease, stage: "before_publish" });
  assert.deepEqual(gate, { proceed: false, block: "cancel_requested" });
  await worker("drinks_finish_publication", { ...lease, outcome: "canceled" });
  assert.equal((await pub(b)).status, "canceled");

  const C = await approvedCard();
  const c = await scheduled(C.reviewId, acc);
  const g2 = await worker("drinks_claim_publication", { worker_id: "t" });
  const l2 = { request_id: c, lease_token: g2.request.lease_token };
  await worker("drinks_publication_step", { ...l2, stage: "publish_called", container_ids: ["p2"] });
  await workerFails("drinks_finish_publication", { ...l2, outcome: "failed", error_code: "x" }, "invalid_input");
  await workerFails("drinks_finish_publication", { ...l2, outcome: "paused", error_code: "x" }, "invalid_input");
  // 게시물 계정이 대상과 다르게 보고되면 published 가 아니다
  await worker("drinks_finish_publication", { ...l2, outcome: "published", external_post_id: "m1", owner_account_id: "someone_else" });
  assert.equal((await pub(c)).status, "unknown");
});

test("unknown: 임대가 끊긴 게시 중은 unknown(실패 아님) · 다시 집지 않는다 · 대조로 published 정정, 취소 요청은 '취소 미적용' 표시", async () => {
  const acc = await activeAccount();
  const A = await approvedCard();
  const a = await scheduled(A.reviewId, acc);
  const got = await worker("drinks_claim_publication", { worker_id: "t" });
  await worker("drinks_publication_step", { request_id: a, lease_token: got.request.lease_token, stage: "publish_called", container_ids: ["px"] });
  await db.query("update drink_publication_requests set lease_expires_at = now() - interval '1 minute' where id = $1", [a]);
  // 화면이 열릴 때(상태 조회) 끊긴 게시 중을 unknown 으로 정리한다 — 그 뒤의 버전으로 버튼을 누른다.
  assert.equal((await worker("drinks_publication_state", { request_id: a })).status, "unknown");
  await ok("publication_action", { request_id: a, expected_version: await ver("drink_publication_requests", a), action: "cancel" });
  let p = await pub(a);
  assert.equal(p.status, "unknown", "게시됐을 수 있다 — 실패로 닫지 않는다");
  assert.equal(p.cancel_requested, true, "unknown 의 취소는 요청 표시만");
  assert.equal((await worker("drinks_claim_publication", { worker_id: "t" })).request, null, "자동 재게시 금지");
  await fails("create_publication", { output_review_id: A.reviewId, account_id: acc, caption: "새로" }, "duplicate_publication");
  const list = await worker("drinks_unknown_publications", {});
  assert.deepEqual(list.find((x: Any) => x.request_id === a).container_ids, ["px"]);
  const ext = (await row("select external_account_id from drink_social_accounts where id = $1", [acc])).external_account_id;
  await workerFails("drinks_reconcile_publication", { request_id: a, found: true, external_post_id: "m9", owner_account_id: "other" }, "invalid_input");
  await worker("drinks_reconcile_publication", { request_id: a, found: true, external_post_id: "m9", owner_account_id: ext });
  p = await pub(a);
  assert.equal(p.status, "published");
  assert.equal(p.reconcile_state, "cancel_not_applied");
});

test("성과: 칸은 서버가 정한다 · 받은 지표만(음수·문자·중복 표기 거부) · 같은 칸 두 번 없음 · 창 밖은 off_window", async () => {
  const acc = await activeAccount();
  const A = await approvedCard();
  const a = await scheduled(A.reviewId, acc);
  const got = await worker("drinks_claim_publication", { worker_id: "t" });
  const ext = (await row("select external_account_id from drink_social_accounts where id = $1", [acc])).external_account_id;
  await worker("drinks_finish_publication", { request_id: a, lease_token: got.request.lease_token, outcome: "published",
    external_post_id: "m_a", external_url: "https://www.instagram.com/p/m_a/", owner_account_id: ext });
  const base = { request_id: a, external_post_id: "m_a" };
  assert.equal((await worker("drinks_record_metrics", { ...base, values: { reach: 10 } })).bucket, "off_window", "게시 직후는 어느 칸도 아니다");
  const due0 = await worker("drinks_metrics_due", {});
  assert.ok(!due0.some((d: Any) => d.request_id === a));
  await db.query("alter table drink_publication_requests disable trigger drink_publications_guard");
  await db.query("update drink_publication_requests set published_at = now() - interval '25 hours' where id = $1", [a]);
  await db.query("alter table drink_publication_requests enable trigger drink_publications_guard");
  assert.equal((await worker("drinks_metrics_due", {})).find((d: Any) => d.request_id === a).bucket, "24h");
  await workerFails("drinks_record_metrics", { ...base, values: { reach: -1 } }, "invalid_input");
  await workerFails("drinks_record_metrics", { ...base, values: { reach: "많음" } }, "invalid_input");
  await workerFails("drinks_record_metrics", { ...base, values: { reach: 5 }, unavailable: { reach: "not_provided" } }, "invalid_input");
  await workerFails("drinks_record_metrics", { request_id: a, external_post_id: "m_other", values: {} }, "invalid_input");
  const s1 = await worker("drinks_record_metrics", { ...base, values: { reach: 500, saved: 10 }, unavailable: { shares: "not_provided" },
    fetch_status: "partial" });
  assert.equal(s1.bucket, "24h");
  const s2 = await worker("drinks_record_metrics", { ...base, values: { reach: 999 } });
  assert.equal(s2.duplicate, true, "같은 칸은 한 번만");
  const snap = await row("select metric_values, unavailable from drink_post_metric_snapshots where id = $1", [s1.snapshot_id]);
  assert.deepEqual(snap.metric_values, { reach: 500, saved: 10 });
  assert.ok(!("shares" in snap.metric_values), "못 받은 지표는 0 이 아니라 키 없음");
  await assert.rejects(db.query("update drink_post_metric_snapshots set metric_values = '{}' where id = $1", [s1.snapshot_id]), /immutable/);
});

test("전략: 기준이 바뀐 제안은 저장·반영 거부 · 가중치 상한 · 기각엔 사유 · 반영은 새 버전, 옛 버전은 물러남", async () => {
  const active = await row("select id from drink_strategy_versions where status = 'active'");
  await workerFails("drinks_save_strategy_proposal", { base_version_id: "00000000-0000-0000-0000-000000000000", weights: {} }, "stale_strategy");
  await workerFails("drinks_save_strategy_proposal", { base_version_id: active.id, weights: { category: { sake: 0.9 } } }, "invalid_input");
  await workerFails("drinks_save_strategy_proposal", { base_version_id: active.id, weights: { mood: {} } }, "invalid_input");
  const p1 = await worker("drinks_save_strategy_proposal", { base_version_id: active.id, weights: { category: { whisky: 0.2 } },
    basis: {}, sample_total: 6, sufficient: true });
  const p2 = await worker("drinks_save_strategy_proposal", { base_version_id: active.id, weights: { category: { sake: 0.1 } },
    basis: {}, sample_total: 7, sufficient: true });
  await fails("strategy_action", { proposal_id: p1.proposal_id, action: "accept" }, "invalid_state");   // 새 제안에 밀려남
  await fails("strategy_action", { proposal_id: p2.proposal_id, action: "reject" }, "invalid_input");
  const acc = await ok("strategy_action", { proposal_id: p2.proposal_id, action: "accept", actor: "누군가" });
  const nv = await row("select * from drink_strategy_versions where id = $1", [acc.strategy_id]);
  assert.equal(nv.status, "active");
  assert.equal((await row("select status from drink_strategy_versions where id = $1", [active.id])).status, "retired");
  assert.equal((await row("select decided_by from drink_strategy_proposals where id = $1", [p2.proposal_id])).decided_by, "operator",
    "결정자 이름은 입력값을 믿지 않는다");
  await assert.rejects(db.query("update drink_strategy_versions set weights = '{}' where id = $1", [nv.id]), /immutable/);
  const p3 = await worker("drinks_save_strategy_proposal", { base_version_id: nv.id, weights: {}, basis: {}, sample_total: 1, sufficient: false });
  await fails("strategy_action", { proposal_id: p3.proposal_id, action: "accept" }, "insufficient_sample");
});
