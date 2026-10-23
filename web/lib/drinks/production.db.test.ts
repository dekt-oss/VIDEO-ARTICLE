// 주류 C단계 제작·파일·검수(0053) DB 통합 테스트 — PGlite 위에 0050~0053.
// 운영자 동작은 runDrinksAction 경로, 워커 동작(drinks_start_render 등)은 rpc 직접.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { DRINKS_ACTIONS, runDrinksAction } from "./actions.ts";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql"].map((f) => join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations", f));
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
const workerFails = async (fn: string, p: Record<string, unknown>, code: string) => {
  const r = await exec(fn, p);
  assert.ok(r.error, `${fn} 가 통과하면 안 된다`);
  assert.match(r.error!.message, new RegExp(`^drinks:${code}:`));
};
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const uniq = () => Math.random().toString(36).slice(2);
const hex = () => Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");

const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
const BODY = "준마이 다이긴조는 정미율 50% 이하의 쌀을 사용한다. 양조 알코올을 첨가하지 않는다.";
const brief = { audience_question: "왜 비쌀까?", core_takeaway: "쌀을 반 이상 깎는다", selected_claim_ids: ["c1", "c2"],
  proposed_formats: ["carousel", "video"], required_claims: { carousel: ["c1", "c2"], video: ["c1"] } };
const claims = (sid: string) => [
  { claim_id: "c1", text: "정미율 50% 이하", claim_type: "process", support_review: "supported",
    source_refs: [{ snapshot_id: sid, original_quote: "정미율 50% 이하의 쌀을 사용한다" }] },
  { claim_id: "c2", text: "양조 알코올 무첨가", claim_type: "product_fact", support_review: "supported",
    source_refs: [{ snapshot_id: sid, original_quote: "양조 알코올을 첨가하지 않는다" }] },
];
const tv = async (id: string) => (await row("select version from drink_topics where id = $1", [id])).version;
const reviewRow = (id: string) => row("select * from drink_topic_reviews where id = $1", [id]);
const planRow = (id: string) => row("select * from drink_plan_revisions where id = $1", [id]);
const jobRow = (id: string) => row("select * from drink_production_jobs where id = $1", [id]);

async function approvePlan(id: string) {
  let p = await planRow(id);
  await ok("plan_action", { revision_id: id, expected_version: p.version, action: "submit" });
  p = await planRow(id);
  await ok("plan_action", { revision_id: id, expected_version: p.version, action: "approve" });
}

/** 근거 승인 → 영상·카드 편성 → 두 제작안 승인까지. */
async function approvedPlans() {
  const t = await ok("create_topic", { title: "다이긴조", question: `다이긴조는 왜 비쌀까 ${uniq()}`, categories: ["sake"], lane: "evergreen" });
  const id = t.topic_id;
  await ok("triage", { topic_id: id, expected_version: await tv(id), scores: SCORES });
  await ok("topic_action", { topic_id: id, expected_version: await tv(id), action: "start_research" });
  const s = await ok("add_source", { topic_id: id, source: { url: `https://www.nta.go.jp/${uniq()}`, body_text: BODY, rights_status: "quote_ok" } });
  const sv = await ok("save_review", { topic_id: id, expected_topic_version: await tv(id), scores: SCORES, brief,
    evidence_pack: { claims: claims(s.snapshot_id) } });
  let r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "submit" });
  r = await reviewRow(sv.review_id);
  await ok("review_action", { review_id: r.id, expected_version: r.version, action: "approve" });
  r = await reviewRow(sv.review_id);
  await ok("select", { topic_id: id, expected_version: await tv(id), review_id: r.id, review_input_hash: r.approved_hash,
    formats: ["video", "carousel"], editorial_week: "2026-10-26" });
  const v = await ok("save_plan", { topic_id: id, format: "video", topic_review_id: r.id, plan_json: { scenes: [
    { narration: "다이긴조, 왜 비쌀까요?", content_kind: "transition", visual_role: "reality" },
    { narration: "쌀을 반 이상 깎아요", visual_role: "mechanism", claim_ids: ["c1"], timing_sec: 4 }] } });
  await approvePlan(v.revision_id);
  const c = await ok("save_plan", { topic_id: id, format: "carousel", topic_review_id: r.id, plan_json: { pages: [
    { role: "cover", heading: "다이긴조 = 쌀 50%" },
    { role: "explain", heading: "정미율", body: "쌀을 깎은 비율", claim_ids: ["c1"] },
    { role: "checklist", heading: "라벨 체크", body: "양조 알코올 무첨가", claim_ids: ["c2"] }] } });
  await approvePlan(c.revision_id);
  return { topicId: id, reviewId: r.id as string, snapshotId: s.snapshot_id as string, video: v.revision_id as string,
    card: c.revision_id as string };
}

/** 워커처럼 렌더 하나를 끝까지: 파일 등록 → 비용 → 끝내기. */
async function renderOnce(format: "video" | "carousel", pages = 3) {
  const got = await worker("drinks_start_render", { worker_id: "t" });
  assert.ok(got.job, "가져갈 제작 작업이 있어야 한다");
  const lease = { job_id: got.job.job_id, lease_token: got.job.lease_token };
  const reg = async (role: string, pos: number, mime: string) => (await worker("drinks_register_asset", { ...lease, asset: {
    storage_key: `drinks/${got.job.job_id}/${role}_${pos}`, sha256: hex(), mime, bytes: 1000, rights: "generated_local" } })).asset_id;
  const assets = format === "video"
    ? [{ asset_id: await reg("final_video", 1, "video/mp4"), role: "final_video", position: 1 },
       { asset_id: await reg("cover", 1, "image/png"), role: "cover", position: 1 }]
    : await Promise.all(Array.from({ length: pages }, async (_, i) => ({ asset_id: await reg("page", i + 1, "image/png"), role: "page", position: i + 1 })));
  await worker("drinks_record_cost", { ...lease, cost: { kind: "tts", provider: "edge", cost_usd: 0 } });
  return { job: got.job, lease, assets, fin: () => worker("drinks_finish_render", { ...lease, outcome: "succeeded", assets, qa: { warnings: [] } }) };
}
const VIDEO_CK = { scene_types_labeled: true, no_real_product_implied: true, claims_match_evidence: true, audio_subtitles_ok: true, vertical_ok: true };
const CARD_CK = { page_order_ok: true, no_text_overflow: true, claims_match_evidence: true, source_page_ok: true };
const reviewFor = (manifest: string) => row("select * from drink_output_reviews where manifest_id = $1", [manifest]);

// ─────────────────────────────────────────────────────────────

test("렌더 요청: 승인된 제작안만 · 유료는 예산 미설정으로 거부 · 같은 입력의 중복 요청은 같은 작업", async () => {
  const P = await approvedPlans();
  await fails("request_render", { plan_revision_id: P.video, paid: true }, "paid_disabled");
  const a = await ok("request_render", { plan_revision_id: P.video });
  const b = await ok("request_render", { plan_revision_id: P.video });
  assert.equal(b.existing, true);
  assert.equal(b.job_id, a.job_id);
  await fails("request_render", { plan_revision_id: "00000000-0000-0000-0000-000000000000" }, "not_found");
  await ok("cancel_render", { job_id: a.job_id });
  assert.equal((await jobRow(a.job_id)).status, "canceled", "대기 중 취소는 바로");
});

test("영상 렌더 → 불변 묶음 + 검수 대기 · 생성 성공 ≠ 승인 · 체크리스트 없이는 승인 불가", async () => {
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.video });
  const r = await renderOnce("video");
  assert.equal(r.job.plan.scenes.length, 2);
  assert.ok(r.job.sources.length >= 1, "출처 정보를 워커에 준다");
  const fin = await r.fin();
  assert.equal(fin.status, "succeeded");
  assert.equal(fin.review_status, "pending", "생성 성공은 검수 대기일 뿐");
  const rev = await reviewFor(fin.manifest_id);
  await fails("output_review_action", { review_id: rev.id, expected_version: rev.version, action: "approve" }, "invalid_input");
  await fails("output_review_action", { review_id: rev.id, expected_version: rev.version, action: "approve",
    checklist: { ...VIDEO_CK, no_real_product_implied: false } }, "checklist_incomplete");
  await ok("output_review_action", { review_id: rev.id, expected_version: rev.version, action: "approve", checklist: VIDEO_CK });
  assert.equal((await reviewFor(fin.manifest_id)).status, "approved");
  await assert.rejects(db.query("delete from drink_manifest_assets where manifest_id = $1", [fin.manifest_id]), /immutable/);
  await assert.rejects(db.query("update drink_asset_manifests set manifest_hash = 'x' where id = $1", [fin.manifest_id]), /immutable/);
  await assert.rejects(db.query("update drink_media_assets set state = 'deleting' where id = $1", [r.assets[0].asset_id]), /asset_in_use/,
    "승인 묶음의 파일은 정리 대상이 될 수 없다");
});

test("묶음 규칙: 영상 = 최종 1 + 커버 1, 카드 = 제작안 페이지 수만큼 1..n · 다른 작업의 파일은 못 넣는다", async () => {
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.card });
  const r = await renderOnce("carousel", 2);
  await workerFails("drinks_finish_render", { ...r.lease, outcome: "succeeded", assets: r.assets }, "invalid_manifest");
  await workerFails("drinks_finish_render", { ...r.lease, outcome: "succeeded",
    assets: [...r.assets, { asset_id: r.assets[0].asset_id, role: "page", position: 4 }] }, "invalid_manifest");
  const extra = await worker("drinks_register_asset", { ...r.lease, asset: { storage_key: `drinks/${r.job.job_id}/page_3`, sha256: hex(),
    mime: "image/png", bytes: 10, rights: "generated_local" } });
  const fin = await worker("drinks_finish_render", { ...r.lease, outcome: "succeeded",
    assets: [...r.assets, { asset_id: extra.asset_id, role: "page", position: 3 }] });
  assert.equal(fin.status, "succeeded");
  // 남의 작업 파일
  await ok("request_render", { plan_revision_id: P.video });
  const v = await renderOnce("video");
  await workerFails("drinks_finish_render", { ...v.lease, outcome: "succeeded",
    assets: [v.assets[0], { asset_id: extra.asset_id, role: "cover", position: 1 }] }, "ownership");
  await v.fin();
});

test("재렌더 = 새 묶음, 옛 묶음·승인 보존 · 카드만 다시 렌더해도 영상 승인은 그대로", async () => {
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.video });
  const v1 = await (await renderOnce("video")).fin();
  const rv1 = await reviewFor(v1.manifest_id);
  await ok("output_review_action", { review_id: rv1.id, expected_version: rv1.version, action: "approve", checklist: VIDEO_CK });
  await ok("request_render", { plan_revision_id: P.card });
  const c1 = await (await renderOnce("carousel")).fin();
  const rc1 = await reviewFor(c1.manifest_id);
  await ok("output_review_action", { review_id: rc1.id, expected_version: rc1.version, action: "request_changes", reason: "3쪽 글자 넘침" });
  await ok("request_render", { plan_revision_id: P.card });
  const c2 = await (await renderOnce("carousel")).fin();
  assert.notEqual(c2.manifest_id, c1.manifest_id, "카드는 새 묶음");
  assert.equal((await reviewFor(c1.manifest_id)).status, "changes_requested", "옛 카드 판정 보존");
  assert.equal((await reviewFor(v1.manifest_id)).status, "approved", "영상 승인은 카드 재렌더와 무관");
  const v2job = await ok("request_render", { plan_revision_id: P.video });
  const j2 = await jobRow(v2job.job_id);
  assert.equal(j2.attempt_no, 2);
  const v2 = await (await renderOnce("video")).fin();
  assert.notEqual(v2.manifest_id, v1.manifest_id);
  assert.equal((await reviewFor(v1.manifest_id)).status, "approved", "새 영상 묶음이 생겨도 옛 승인을 바꾸지 않는다");
  assert.equal((await reviewFor(v2.manifest_id)).status, "pending");
});

test("렌더 중 근거 철회 → 파일·비용은 보존, 검수는 blocked · 승인된 묶음도 지금 사용 불가 · 대기 작업은 시작 때 취소", async () => {
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.video });
  const old = await (await renderOnce("video")).fin();
  const oldRev = await reviewFor(old.manifest_id);
  await ok("output_review_action", { review_id: oldRev.id, expected_version: oldRev.version, action: "approve", checklist: VIDEO_CK });
  await ok("request_render", { plan_revision_id: P.card });
  const running = await renderOnce("carousel");
  await ok("attest_source", { topic_id: P.topicId, snapshot_id: P.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "인용 허락 철회", revoke_affected: false });
  const fin = await running.fin();
  assert.equal(fin.status, "succeeded", "만든 파일은 기록한다");
  const rev = await reviewFor(fin.manifest_id);
  assert.equal(rev.status, "blocked");
  assert.match(rev.reason, /보존/);
  assert.ok((await row("select count(*)::int n from drink_cost_entries where job_id = $1", [running.job.job_id])).n >= 1, "비용 기록 보존");
  await assert.rejects(db.query("update drink_output_reviews set status = 'approved', checklist = '{}', reviewed_at = now() where id = $1",
    [rev.id]), /immutable|review_blocked/, "차단은 직접 UPDATE 로도 풀 수 없다");
  const usable = await row("select * from drink_output_validity where review_id = $1", [oldRev.id]);
  assert.equal(usable.status, "approved", "승인 기록은 남는다");
  assert.equal(usable.currently_usable, false, "하지만 지금은 쓸 수 없다");
  // 철회 뒤 요청은 거부
  await fails("request_render", { plan_revision_id: P.video }, "not_renderable");
});

test("대기 중에 근거가 무효가 되면 워커가 시작하지 않는다 · 오래된 임대의 완료는 저장되지 않는다", async () => {
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.video });
  const q = await row("select id from drink_production_jobs where plan_revision_id = $1 and status = 'queued'", [P.video]);
  await ok("attest_source", { topic_id: P.topicId, snapshot_id: P.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "철회", revoke_affected: false });
  const got = await worker("drinks_start_render", { worker_id: "t" });
  assert.equal(got.job, null);
  assert.equal((await jobRow(q.id)).status, "canceled");
  assert.ok(["evidence_invalid", "plan_blocked"].includes((await jobRow(q.id)).error_code), "근거 무효 또는 그 때문에 차단된 제작안");

  const Q = await approvedPlans();
  await ok("request_render", { plan_revision_id: Q.video });
  const r = await renderOnce("video");
  await db.query("update drink_production_jobs set lease_expires_at = now() - interval '1 minute' where id = $1", [r.job.job_id]);
  await ok("request_render", { plan_revision_id: Q.card });   // 다른 요청이 정리를 일으킨다
  assert.equal((await jobRow(r.job.job_id)).status, "failed");
  await workerFails("drinks_finish_render", { ...r.lease, outcome: "succeeded", assets: r.assets }, "lease_lost");
  await workerFails("drinks_register_asset", { ...r.lease, asset: { storage_key: "drinks/x/y", sha256: hex(), mime: "image/png", bytes: 1,
    rights: "generated_local" } }, "lease_lost");
  const retry = await ok("request_render", { plan_revision_id: Q.video, retry_of: r.job.job_id });
  assert.equal((await jobRow(retry.job_id)).retry_of, r.job.job_id);
});

test("파일·비용 원장: 저장 위치는 drinks/ 전용 · 같은 위치에 다른 내용 금지 · 공유 파일 비용은 한 번만", async () => {
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.video });
  const got = await worker("drinks_start_render", { worker_id: "t" });
  const lease = { job_id: got.job.job_id, lease_token: got.job.lease_token };
  const h = hex();
  const a = await worker("drinks_register_asset", { ...lease, asset: { storage_key: `drinks/${got.job.job_id}/x`, sha256: h,
    mime: "image/png", bytes: 5, rights: "generated_local" } });
  assert.equal((await worker("drinks_register_asset", { ...lease, asset: { storage_key: `drinks/${got.job.job_id}/x`, sha256: h,
    mime: "image/png", bytes: 5, rights: "generated_local" } })).existing, true);
  await workerFails("drinks_register_asset", { ...lease, asset: { storage_key: `drinks/${got.job.job_id}/x`, sha256: hex(),
    mime: "image/png", bytes: 5, rights: "generated_local" } }, "immutable");
  await assert.rejects(db.query(`insert into drink_media_assets (storage_key, sha256, mime, bytes, rights) values
    ('${uniq()}/final.mp4', '${hex()}', 'video/mp4', 1, 'generated_local')`), /check/, "논문 폴더(directive_id/…) 모양 위치는 못 쓴다");
  const c1 = await worker("drinks_record_cost", { ...lease, cost: { kind: "image", provider: "x", cost_usd: 0.1, shared_asset_id: a.asset_id } });
  const c2 = await worker("drinks_record_cost", { ...lease, cost: { kind: "image", provider: "x", cost_usd: 0.1, shared_asset_id: a.asset_id } });
  assert.ok(c1.cost_id);
  assert.equal(c2.duplicate_shared, true);
  await assert.rejects(db.query("update drink_cost_entries set cost_usd = 0 where job_id = $1", [got.job.job_id]), /immutable/);
  await worker("drinks_finish_render", { ...lease, outcome: "failed", error_code: "test", error_message: "끝" });
});

test("권한: 제작 표·뷰·함수는 anon 에 닫혀 있고, 워커 함수는 화면 동작이 아니다", async () => {
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    for (const t of ["drink_production_jobs", "drink_media_assets", "drink_asset_manifests", "drink_manifest_assets",
      "drink_output_reviews", "drink_cost_entries", "drink_output_validity"]) {
      await assert.rejects(db.query(`select * from ${t}`), /permission denied/, `${role} ${t}`);
    }
    await db.exec("reset role");
  }
  const fns = Object.values(DRINKS_ACTIONS) as string[];
  for (const f of ["drinks_start_render", "drinks_register_asset", "drinks_record_cost", "drinks_finish_render", "drinks_heartbeat_render"]) {
    assert.ok(!fns.includes(f), f);
  }
});

// ── 독립 검토 반영(2026-10-23) ──

const clearQueue = () => db.query("update drink_production_jobs set status = 'canceled', finished_at = now(), error_code = 'test' where status = 'queued'");

test("차단·고칠 점 묶음의 파일도 정리 불가(파일 보존) · 워커가 죽은 '렌더 중'은 화면 조회·취소에서 정리된다", async () => {
  await clearQueue();   // 앞 테스트가 남긴 대기 작업
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.card });
  const running = await renderOnce("carousel");
  await ok("attest_source", { topic_id: P.topicId, snapshot_id: P.snapshotId, kind: "rights_revoked",
    fields: { rights_status: "restricted" }, reason: "철회", revoke_affected: false });
  await running.fin();
  await assert.rejects(db.query("update drink_media_assets set state = 'deleting' where id = $1", [running.assets[0].asset_id]),
    /asset_in_use/, "차단된 묶음도 파일 보존");

  const Q = await approvedPlans();
  await ok("request_render", { plan_revision_id: Q.video });
  const r = await renderOnce("video");
  await db.query("update drink_production_jobs set lease_expires_at = now() - interval '1 minute' where id = $1", [r.job.job_id]);
  await ok("cancel_render", { job_id: r.job.job_id }).catch(() => null);
  assert.equal((await jobRow(r.job.job_id)).status, "failed", "취소 요청이 정리를 일으킨다(영원히 '렌더 중'이 아님)");
  assert.equal((await jobRow(r.job.job_id)).error_code, "lease_expired");
});

test("화면 상태 조회도 멈춘 작업을 정리한다", async () => {
  await clearQueue();
  const P = await approvedPlans();
  await ok("request_render", { plan_revision_id: P.video });
  const r = await renderOnce("video");
  await db.query("update drink_production_jobs set lease_expires_at = now() - interval '1 minute' where id = $1", [r.job.job_id]);
  const st = await worker("drinks_plan_render_state", { plan_revision_id: P.video });
  assert.equal(st.block, null);
  assert.equal((await jobRow(r.job.job_id)).status, "failed");
});
