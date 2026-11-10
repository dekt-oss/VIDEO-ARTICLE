// 5단계 게시 연결(0068) DB 통합 테스트 — PGlite 위에 00(5x|6x)_drinks_*. 운영자 동작은 라우트와 같은 runDrinksAction 경로, 워커 함수는 rpc 직접.
// 한 바퀴(밈·설명형·카드 → 가짜 게시 → 성과 → 전략)는 Python 리허설(scripts/publish_loop_rehearsal.py, tests/test_drinks_stage5_publish_loop.py)이 본다.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d|8\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0068_drinks_stage5_publish_loop.sql"));
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
const fails = async (action: string, payload: Record<string, unknown>, code: string) => {
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
const row = async (sql: string, params: unknown[] = []): Promise<Any> => (await db.query(sql, params)).rows[0];
const uniq = () => Math.random().toString(36).slice(2, 8);
const SOON = () => new Date(Date.now() - 60_000).toISOString();

let seq = 0;
async function preciseCard(sync?: string): Promise<string> {
  seq += 1;
  const { rows } = await db.query<{ id: string }>(`insert into drink_ig_cards (merge_key, kind, name, first_seen_on, decision, decided_at)
    values ($1, 'structure_hook', $2, current_date, 'use', now()) returning id`, [`k${seq}-${uniq()}`, `카드${seq}`]);
  const id = rows[0].id;
  for (const f of ["beat_count", "cut_lengths", "twist_at"]) {
    await db.query(`insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, $2, '3', 'operator', 'high')`, [id, f]);
  }
  if (sync) await db.query(`insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, 'music_sync', $2, 'operator', 'high')`, [id, sync]);
  return id;
}
const spec = (o: Record<string, unknown> = {}) => ({
  frame: "top_text", top_line: "POV: 와인 고르는 척하는 나", title_keyword: "", caption: "다들 이러잖아요",
  beats: [{ text: "앞면을 본다", keyword: "", ms: 3000 }, { text: "가격표만 기억난다", keyword: "가격표", ms: 4000 }],
  scene: { source: "text_bg", palette: "wine" }, sync_grade: "sync_free", audio: { mode: "ambient_local" }, contains_info: false, claim_ids: [], ...o,
});
const SYNC = { sync_grade: "sync_required", audio: { mode: "app_manual", title: "가짜 음원", start_hint_sec: 12 } };
const FILES = (tag: string) => [
  { role: "final_video", storage_key: `drinks/memes/${tag}/final.mp4`, sha256: "a".repeat(64), mime: "video/mp4", width: 1080, height: 1920, duration_ms: 7000 },
  { role: "cover", storage_key: `drinks/memes/${tag}/cover.jpg`, sha256: "b".repeat(64), mime: "image/jpeg", width: 1080, height: 1920 }];

/** 제작 끝난 밈 제작안(publish_waiting 또는 manual_audio). */
async function renderedMeme(o: Record<string, unknown> = {}, sync?: string): Promise<{ draftId: string; status: string }> {
  await db.exec(`update drink_meme_drafts set status = 'rejected' where status = 'approved'`);
  const card = await preciseCard(sync);
  const saved = await ok("meme_save_draft", { card_id: card, spec: spec(o) });
  assert.deepEqual(saved.blockers, [], JSON.stringify(saved.blockers));
  await ok("meme_draft_action", { draft_id: saved.draft_id, expected_version: saved.version, action: "approve" });
  const { job } = await rpc("drinks_meme_claim", { worker_id: "w" });
  assert.equal(job.draft_id, saved.draft_id);
  const done = await rpc("drinks_meme_finish", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "rendered", files: FILES(uniq()),
    guide: sync ? "앱에서 붙이세요" : undefined });
  return { draftId: saved.draft_id, status: done.status };
}

async function account(connection: "fake" | "instagram_login" | "facebook_login" = "fake", ext?: string) {
  const extId = ext ?? (connection === "fake" ? `fake_${uniq()}` : `1784${Math.floor(Math.random() * 1e9)}`);
  const a = await ok("register_account", { external_account_id: extId, display_name: "시험", account_type: "test", connection,
    credential_ref: connection === "fake" ? null : (connection === "facebook_login" ? "SOOLJJERIGO_FB_TOKEN" : "SOOLJJERIGO_IG_TOKEN"),
    capabilities: { post_types: ["carousel", "reel"] } });
  await rpc("drinks_account_verified", { account_id: a.account_id, ok: true, external_account_id: extId, username: "u" });
  const cur = await row("select version from drink_social_accounts where id = $1", [a.account_id]);
  await ok("account_action", { account_id: a.account_id, expected_version: cur.version, action: "enable_publish" });
  return a.account_id as string;
}

async function approveAndSchedule(rid: string) {
  const v = async () => (await row("select version from drink_publication_requests where id = $1", [rid])).version;
  await ok("publication_action", { request_id: rid, expected_version: await v(), action: "submit" });
  const shown = await rpc("drinks_publication_state", { request_id: rid });
  await ok("publication_action", { request_id: rid, expected_version: shown.version, action: "approve", expected_digest: shown.approval_digest });
  return ok("publication_action", { request_id: rid, expected_version: await v(), action: "schedule" });
}

test("밈 발행안: 게시 대기 → 발행안(제작안 캡션) → 승인·예약 → 워커가 파일·제작안을 받는다 → 게시되면 제작안이 published", async () => {
  const { draftId, status } = await renderedMeme();
  assert.equal(status, "publish_waiting");
  const acc = await account();
  const board0 = await rpc("drinks_publish_board", {});
  assert.ok(board0.ready_memes.some((m: Any) => m.draft_id === draftId), "게시 대기 밈이 발행 화면 목록에 온다");
  assert.equal(board0.ai_label_text, "AI 생성 영상");

  const pub = await ok("create_meme_publication", { draft_id: draftId, account_id: acc, publish_at: SOON() });
  assert.equal(pub.content_format, "meme");
  assert.equal(pub.post_type, "reel");
  assert.equal(pub.caption, "다들 이러잖아요", "캡션을 비우면 제작안의 캡션(승인된 글)");
  await fails("create_meme_publication", { draft_id: draftId, account_id: acc, publish_at: SOON() }, "duplicate_publication");
  const board1 = await rpc("drinks_publish_board", {});
  assert.ok(!board1.ready_memes.some((m: Any) => m.draft_id === draftId), "발행안을 만들면 목록에서 빠진다");
  const req = board1.requests.find((r: Any) => r.id === pub.request_id);
  assert.equal(req.content_format, "meme");
  assert.equal(req.meme_draft_id, draftId);
  assert.equal(req.files.length, 2, "제작안의 파일(영상·표지)이 화면에 보인다");

  const sch = await approveAndSchedule(pub.request_id);
  assert.equal(sch.status, "scheduled");
  const got = (await rpc("drinks_claim_publication", { worker_id: "w" })).request;
  assert.equal(got.request_id, pub.request_id);
  assert.equal(got.content_format, "meme");
  assert.equal(got.meme_spec.sync_grade, "sync_free", "워커가 assert_auto_publishable 에 쓸 제작안이 동봉된다");
  assert.ok(got.files.some((f: Any) => f.role === "final_video" && f.storage_key.startsWith("drinks/memes/")));
  assert.deepEqual(got.claims, [], "농담 밈은 근거가 없다 — 캡션의 숫자·권고는 근거 없이 검사된다");
  assert.equal(got.audio_required, false);
  const lease = { request_id: got.request_id, lease_token: got.lease_token };
  await rpc("drinks_publication_step", { ...lease, stage: "containers_created", container_ids: ["c1"] });
  await rpc("drinks_publication_step", { ...lease, stage: "publish_called", container_ids: ["c1"] });
  const fin = await rpc("drinks_finish_publication", { ...lease, outcome: "published", external_post_id: "m_1", external_url: "https://www.instagram.com/p/m_1/",
    owner_account_id: got.account.external_account_id });
  assert.equal(fin.status, "published");
  const draft = await row("select status, external_url from drink_meme_drafts where id = $1", [draftId]);
  assert.equal(draft.status, "published");
  assert.equal(draft.external_url, "https://www.instagram.com/p/m_1/");
  await assert.rejects(db.query(`update drink_meme_drafts set status = 'draft' where id = $1`, [draftId]), /immutable/);
  await fails("meme_draft_action", { draft_id: draftId, expected_version: (await row("select version from drink_meme_drafts where id = $1", [draftId])).version, action: "reopen" }, "invalid_state");
  // 다른 계정으로 또 올리는 길도 없다 — 제작안이 published 라 게시 대기가 아니다
  await fails("create_meme_publication", { draft_id: draftId, account_id: await account(), publish_at: SOON() }, "invalid_state");
});

test("★ 박자 맞춤 밈: 앱 부착 대기라 발행안을 못 만든다. 게시 대기 제작안도 되돌리면 승인·예약·게시 직전에 막힌다", async () => {
  const synced = await renderedMeme(SYNC, "박자에 맞춰야 함(필수)");
  assert.equal(synced.status, "manual_audio");
  const acc = await account();
  await fails("create_meme_publication", { draft_id: synced.draftId, account_id: acc }, "invalid_state");
  const board = await rpc("drinks_publish_board", {});
  assert.ok(!board.ready_memes.some((m: Any) => m.draft_id === synced.draftId), "박자 맞춤은 목록에 안 온다");

  const { draftId } = await renderedMeme();
  const pub = await ok("create_meme_publication", { draft_id: draftId, account_id: acc, publish_at: SOON() });
  await approveAndSchedule(pub.request_id);
  // 운영자가 제작안을 초안으로 되돌리면: 승인 지문(제작안 승인 지문 포함)이 달라져 게시 직전 재확인이 막는다 → paused
  const d = await row("select version from drink_meme_drafts where id = $1", [draftId]);
  await ok("meme_draft_action", { draft_id: draftId, expected_version: d.version, action: "reopen" });
  const state = await rpc("drinks_publication_state", { request_id: pub.request_id });
  assert.equal(state.block, "digest_changed");
  const claim = await rpc("drinks_claim_publication", { worker_id: "w" });
  assert.equal(claim.request, null);
  assert.equal(claim.paused, 1);
  const r = await row("select status, pause_code from drink_publication_requests where id = $1", [pub.request_id]);
  assert.equal(r.status, "paused");
  assert.equal(r.pause_code, "digest_changed");
});

test("산 장면 밈: 캡션에 'AI 생성' 이 없으면 발행안 거부. 제작안이 정한 음원과 다른 음원은 거부", async () => {
  const asset = await row(`insert into drink_media_assets (storage_key, sha256, mime, bytes, rights, provenance) values ($1, $2, 'video/mp4', 10, 'generated_paid', '{}') returning id`,
    [`drinks/memes/scene-${uniq()}.mp4`, "c".repeat(64)]);
  const { draftId, status } = await renderedMeme({ scene: { source: "bought_reaction", asset_id: asset.id, beat: 1 }, caption: "다들 이러잖아요 — AI 생성 영상" });
  assert.equal(status, "publish_waiting");
  const acc = await account();
  await fails("create_meme_publication", { draft_id: draftId, account_id: acc, caption: "표기를 지운 캡션" }, "ai_label_missing");
  const pub = await ok("create_meme_publication", { draft_id: draftId, account_id: acc, publish_at: SOON() });
  assert.match(pub.caption, /AI 생성/);
  await fails("update_publication", { request_id: pub.request_id, expected_version: pub.version, caption: "표기 지움" }, "ai_label_missing");
  // 영상에 소리가 든 밈에는 게시 때 음원을 따로 붙이지 않는다
  const audioId = `aud_${uniq()}`;
  await row(`insert into drink_ig_audio (audio_id, audio_type, title, display_artist, first_seen_on, last_seen_on) values ($1, 'music', '노래', '가수', current_date, current_date) returning audio_id`, [audioId]);
  const other = await renderedMeme();
  await fails("create_meme_publication", { draft_id: other.draftId, account_id: acc, publish_at: SOON(),
    audio: { mode: "ig_audio", audio_id: audioId, audio_volume: 90, video_volume: 10, sync_grade: "sync_free" } }, "invalid_input");
});

test("설명형: 캡션에 'AI 생성 영상' 한 줄이 없으면 작성·수정·승인 요청이 막힌다. 카드는 무관", async () => {
  // 설명형 소재의 영상 묶음을 가장 짧은 길로 만든다(검수 승인까지). 큐·클립은 Python 리허설이 본다.
  const t = await ok("create_topic", { title: "설명형 시험", question: `왜 안 상할까 ${uniq()}`, categories: ["whisky"], lane: "evergreen" });
  const tv = async () => (await row("select version from drink_topics where id = $1", [t.topic_id])).version;
  const SCORES = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 2, timeliness: 2 };
  await ok("triage", { topic_id: t.topic_id, expected_version: await tv(), scores: SCORES });
  await ok("topic_action", { topic_id: t.topic_id, expected_version: await tv(), action: "start_research" });
  const s = await ok("add_source", { topic_id: t.topic_id, source: { url: `https://example.org/${uniq()}`, body_text: "Whisky enthusiasts often also add a few drops of water to the spirit before drinking", rights_status: "quote_ok" } });
  const pack = { claims: [{ claim_id: "c1", text: "물을 몇 방울 넣는다", claim_type: "process", support_review: "supported",
    source_refs: [{ snapshot_id: s.snapshot_id, original_quote: "Whisky enthusiasts often also add a few drops of water" }] }] };
  const brief = { audience_question: "왜", core_takeaway: "시험", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } };
  const sv = await ok("save_review", { topic_id: t.topic_id, expected_topic_version: await tv(), scores: SCORES, brief, evidence_pack: pack });
  const rv = async () => row("select * from drink_topic_reviews where id = $1", [sv.review_id]);
  await ok("review_action", { review_id: sv.review_id, expected_version: (await rv()).version, action: "submit" });
  await ok("review_action", { review_id: sv.review_id, expected_version: (await rv()).version, action: "approve" });
  await ok("select", { topic_id: t.topic_id, expected_version: await tv(), review_id: sv.review_id, review_input_hash: (await rv()).approved_hash, formats: ["video"], editorial_week: "2026-11-02" });
  const pl = await ok("save_plan", { topic_id: t.topic_id, format: "video", topic_review_id: sv.review_id, plan_json: { scenes: [
    { narration: "물을 몇 방울 넣어요", visual_role: "reality", content_kind: "fact", claim_ids: ["c1"], visual_prompt: "a glass", motion_prompt: "push in" }] } });
  const pv = async () => (await row("select version from drink_plan_revisions where id = $1", [pl.revision_id])).version;
  await ok("plan_action", { revision_id: pl.revision_id, expected_version: await pv(), action: "submit" });
  await ok("plan_action", { revision_id: pl.revision_id, expected_version: await pv(), action: "approve" });
  await db.query(`insert into drink_topic_picks (topic_id, format_intent, editorial_week) values ($1, 'explainer', '2026-11-02')`, [t.topic_id]);
  // 묶음은 설명형 작업으로만 만들 수 있다(0067) — 시험은 표에 직접 넣는다(explainer_render 작업 + 묶음 + 검수 승인)
  const job = await row(`insert into drink_production_jobs (topic_id, plan_revision_id, format, attempt_no, input_hash, plan_hash, review_hash, renderer, renderer_version, requested_by, status, started_at, finished_at)
    values ($1, $2, 'video', 1, $3, 'p', 'r', 'explainer_render', 'drinks-explainer-v1', 'operator', 'succeeded', now(), now()) returning id`, [t.topic_id, pl.revision_id, uniq()]);
  const m = await row(`insert into drink_asset_manifests (plan_revision_id, job_id, format, manifest_hash, input_hash) values ($1, $2, 'video', $3, 'i') returning id`, [pl.revision_id, job.id, uniq()]);
  for (const [role, mime, ext] of [["final_video", "video/mp4", "mp4"], ["cover", "image/jpeg", "jpg"]]) {
    const a = await row(`insert into drink_media_assets (storage_key, sha256, mime, bytes, rights, provenance, job_id) values ($1, $2, $3, 10, 'generated_paid', '{}', $4) returning id`,
      [`drinks/${job.id}/${role}.${ext}`, (role === "cover" ? "d" : "e").repeat(64), mime, job.id]);
    await db.query(`insert into drink_manifest_assets (manifest_id, asset_id, role, position) values ($1, $2, $3, 1)`, [m.id, a.id, role]);
  }
  const review = await row(`insert into drink_output_reviews (manifest_id, plan_revision_id, status, checklist, reviewer, reviewed_at) values ($1, $2, 'approved', '{}', 'operator', now()) returning id`, [m.id, pl.revision_id]);
  const acc = await account();
  const board = await rpc("drinks_publish_board", {});
  assert.equal(board.ready_outputs.find((o: Any) => o.output_review_id === review.id)?.content_format, "explainer");
  await fails("create_publication", { output_review_id: review.id, account_id: acc, caption: "물 이야기", publish_at: SOON() }, "ai_label_missing");
  const pub = await ok("create_publication", { output_review_id: review.id, account_id: acc, caption: "물 이야기\nAI 생성 영상", publish_at: SOON() });
  assert.equal(pub.content_format, "explainer");
  await fails("update_publication", { request_id: pub.request_id, expected_version: pub.version, caption: "표기 지움" }, "ai_label_missing");
  // 가드를 우회해 캡션만 바꾸면(작성 중) 승인 요청에서 막힌다
  await db.query(`update drink_publication_requests set caption = '표기 없음' where id = $1`, [pub.request_id]);
  const v = (await row("select version from drink_publication_requests where id = $1", [pub.request_id])).version;
  await fails("publication_action", { request_id: pub.request_id, expected_version: v, action: "submit" }, "ai_label_missing");
});

test("전략: 'format' 묶음을 받고 모르는 형식 값은 거부한다. 가점은 소재의 형식 의도를 본다", async () => {
  const v = await row("select id from drink_strategy_versions where status = 'active'");
  const ok1 = await rpc("drinks_save_strategy_proposal", { base_version_id: v.id, weights: { format: { meme: 0.2, card: -0.1 } }, basis: {}, sample_total: 6, sufficient: true, summary_ko: "x" });
  assert.equal(ok1.status, "proposed");
  const bad = await exec("drinks_save_strategy_proposal", { base_version_id: v.id, weights: { format: { reel: 0.2 } }, basis: {}, sample_total: 6, sufficient: true });
  assert.match(bad.error!.message, /invalid_input/);
  const lift = await row(`select drinks_strategy_lift('{"format":{"meme":0.3}}'::jsonb, array['sake'], 'evergreen', array['reel'], 'general', 'meme') l`);
  assert.equal(Number(lift.l), 0.3);
  const n = await row("select count(*)::int n from pg_proc where proname = 'drinks_strategy_lift'");
  assert.equal(n.n, 1, "옛 5-인자 함수는 지웠다(호출 모호성 방지)");
  const inputs = await rpc("drinks_strategy_inputs", {});
  assert.ok(Array.isArray(inputs.posts));
});

test("계정: 같은 인스타 계정을 Facebook 로그인 연결로 한 번 더 등록할 수 있다(음원 릴스용). 같은 연결은 여전히 중복", async () => {
  const ext = `1784${Math.floor(Math.random() * 1e9)}`;
  await account("instagram_login", ext);
  const fb = await ok("register_account", { external_account_id: ext, display_name: "술째리고(FB)", account_type: "creator", connection: "facebook_login",
    credential_ref: "SOOLJJERIGO_FB_TOKEN", capabilities: { post_types: ["reel"] } });
  assert.equal(fb.status, "pending_verification");
  await fails("register_account", { external_account_id: ext, display_name: "또", account_type: "creator", connection: "facebook_login",
    credential_ref: "SOOLJJERIGO_FB_TOKEN", capabilities: {} }, "duplicate_account");
});

test("옛 승인 지문은 그대로다 — meme_draft_id 가 없으면 0065 계산과 같다", async () => {
  // 0065 의 지문 식을 그대로 적어 새 함수와 글자 단위로 대조한다(밈이 아닌 모든 요청 — 작성 중 포함).
  const same = await row(`select bool_and(drinks_pub_digest(r) = encode(sha256(convert_to(concat_ws('|', 'drinks-pub-v1', r.manifest_id::text, r.manifest_hash,
      r.account_id::text, r.target_external_account_id, r.post_type, r.caption, coalesce(r.cover_asset_id::text, ''),
      coalesce(to_char(r.publish_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''))
      || case when r.audio is null then '' else '|audio:' || (r.audio - 'selected_by' - 'selected_at')::text end, 'UTF8')), 'hex')) ok, count(*)::int n
    from drink_publication_requests r where r.meme_draft_id is null`);
  assert.ok(same.n >= 1 && same.ok === true, JSON.stringify(same));
  const memes = await row(`select bool_and(drinks_pub_digest(r) like '%') ok, count(*)::int n from drink_publication_requests r where r.meme_draft_id is not null`);
  assert.ok(memes.n >= 1 && memes.ok === true);
});

test("권한: 공개 역할은 새 함수에 닿지 않는다. 밈 발행 요청은 출처 제약을 지킨다", async () => {
  for (const fn of ["drinks_create_meme_publication(jsonb)", "drinks_pub_after_published(drink_publication_requests)"]) {
    const r = await row(`select has_function_privilege('anon', $1, 'EXECUTE') a, has_function_privilege('service_role', $1, 'EXECUTE') s`, [`public.${fn}`]);
    assert.equal(r.a, false, fn);
    assert.equal(r.s, true, fn);
  }
  const acc = await row("select id, external_account_id from drink_social_accounts limit 1");
  await assert.rejects(db.query(`insert into drink_publication_requests (content_format, post_type, account_id, target_external_account_id) values ('meme', 'reel', $1, $2)`,
    [acc.id, acc.external_account_id]), /drink_pub_origin_ck|drink_pub_source_ck/);
});
