// 밈 제작(0066) DB 통합 테스트 — PGlite 위에 00(5x|6x)_drinks_*. 운영자 동작은 라우트와 같은 runDrinksAction 경로, 워커 함수는 rpc 직접.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0066_drinks_meme_engine.sql"));
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
const rpcFails = async (fn: string, p: Record<string, unknown>, code: string) => {
  const r = await exec(fn, p);
  assert.ok(r.error, `${fn} 가 통과하면 안 된다`);
  assert.match(r.error!.message, new RegExp(`^drinks:${code}:`));
};

let seq = 0;
async function preciseCard(sync?: string): Promise<string> {
  seq += 1;
  const { rows } = await db.query<{ id: string }>(`insert into drink_ig_cards (merge_key, kind, name, first_seen_on, decision, decided_at)
    values ($1, 'structure_hook', $2, current_date, 'use', now()) returning id`, [`k${seq}`, `카드${seq}`]);
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
const FILES = [{ role: "final_video", storage_key: "drinks/memes/x/final.mp4", sha256: "a".repeat(64) }, { role: "cover", storage_key: "drinks/memes/x/cover.jpg", sha256: "b".repeat(64) }];

async function drain() {
  // 앞 시험이 남긴 승인 건이 claim 순서를 흐리지 않게 닫는다.
  await db.exec(`update drink_meme_drafts set status = 'rejected' where status in ('approved')`);
}

test("[쓰자] 카드 → 초안 → 승인 → 제작 → 게시 대기", async () => {
  await drain();
  const card = await preciseCard();
  const saved = await ok("meme_save_draft", { card_id: card, spec: spec() });
  assert.equal(saved.status, "draft");
  assert.deepEqual(saved.blockers, []);
  const approved = await ok("meme_draft_action", { draft_id: saved.draft_id, expected_version: saved.version, action: "approve" });
  assert.equal(approved.status, "approved");
  const { job } = await rpc("drinks_meme_claim", { worker_id: "w" });
  assert.equal(job.draft_id, saved.draft_id);
  assert.equal(job.spec.top_line, "POV: 와인 고르는 척하는 나");
  assert.equal((await rpc("drinks_meme_finish", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "rendered", files: FILES })).status, "publish_waiting");
});

test("★ 박자 맞춤: DB 가 앱 부착으로 보낸다. 표 제약이 게시 대기를 막는다", async () => {
  await drain();
  const card = await preciseCard();
  const saved = await ok("meme_save_draft", { card_id: card, spec: spec(SYNC) });
  await ok("meme_draft_action", { draft_id: saved.draft_id, action: "approve" });
  const { job } = await rpc("drinks_meme_claim", { worker_id: "w" });
  // 안내 없이는 끝낼 수 없다
  await rpcFails("drinks_meme_finish", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "rendered", files: FILES }, "invalid_manifest");
  // 워커가 게시 대기를 달라고 해도 듣지 않는다 - 상태를 받는 칸이 없다
  const done = await rpc("drinks_meme_finish", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "rendered", files: FILES, guide: "앱에서 붙이세요", status: "publish_waiting", next_status: "publish_waiting" });
  assert.equal(done.status, "manual_audio");
  // 표 제약: 손으로 넣어도 안 된다
  await assert.rejects(db.query(`update drink_meme_drafts set status = 'publish_waiting' where id = $1`, [job.draft_id]), /invalid_transition/);
  await db.query(`update drink_meme_drafts set status = 'rendering', lease_token = gen_random_uuid() where id = $1`, [job.draft_id]);
  await assert.rejects(db.query(`update drink_meme_drafts set status = 'publish_waiting' where id = $1`, [job.draft_id]), /drink_meme_sync_gate_ck/);
  await db.query(`update drink_meme_drafts set status = 'manual_audio', lease_token = null where id = $1`, [job.draft_id]);
  // 운영자가 앱에서 올린 뒤 링크 등록
  await fails("meme_draft_action", { draft_id: job.draft_id, action: "manual_posted", url: "https://example.com/x" }, "invalid_input");
  assert.equal((await ok("meme_draft_action", { draft_id: job.draft_id, action: "manual_posted", url: "https://www.instagram.com/reel/ABCDE/" })).status, "posted_manual");
});

test("카드가 박자 맞춤이면 박자 무관으로 승인되지 않는다", async () => {
  const card = await preciseCard("박자에 맞춰야 함(필수)");
  const saved = await ok("meme_save_draft", { card_id: card, spec: spec() });
  assert.equal(saved.blockers[0].code, "meme_sync_blocked");
  await fails("meme_draft_action", { draft_id: saved.draft_id, action: "approve" }, "meme_sync_blocked");
});

test("안전 검사: 조장·미성년·과음은 승인에서 막힌다", async () => {
  for (const [line, code] of [["오늘은 원샷", "meme_encourages_drinking"], ["고딩 때 얘기", "meme_minor"], ["어제 필름 끊겼다", "meme_overdrinking"], ["소주 3병은 기본", "meme_overdrinking"]]) {
    const saved = await ok("meme_save_draft", { card_id: await preciseCard(), spec: spec({ top_line: line }) });
    await fails("meme_draft_action", { draft_id: saved.draft_id, action: "approve" }, code);
  }
});

test("★ 정보 밈: 승인된 근거가 없으면 멈춘다", async () => {
  const info = spec({ top_line: "알코올 10% 이상 음료는", contains_info: true, claim_ids: ["c1"] });
  const s1 = await ok("meme_save_draft", { card_id: await preciseCard(), spec: info });
  await fails("meme_draft_action", { draft_id: s1.draft_id, action: "approve" }, "meme_evidence_missing");
  // 표시 안 하고 빠져나갈 수 없다
  const s2 = await ok("meme_save_draft", { card_id: await preciseCard(), spec: spec({ top_line: "알코올 10% 이상 음료는" }) });
  await fails("meme_draft_action", { draft_id: s2.draft_id, action: "approve" }, "meme_info_undeclared");
});

test("정보 밈: 승인된 근거의 주장을 대면 승인되고, 근거가 취소되면 제작 직전에 멈춘다", async () => {
  await drain();
  const topic = (await ok("create_topic", { title: "근거 소재", question: "근거가 있나?", categories: ["whisky"], lane: "evergreen" })).topic_id;
  await db.exec("set session_replication_role = replica");
  const { rows } = await db.query<{ id: string }>(`insert into drink_topic_reviews (topic_id, revision_no, status, approved_hash, evidence_pack)
    values ($1, 1, 'approved', 'x', $2) returning id`, [topic, JSON.stringify({ claims: [{ claim_id: "c1", text: "주장", source_refs: [{ original_quote: "10 %" }] }] })]);
  await db.exec("set session_replication_role = origin");
  const review = rows[0].id;
  const info = spec({ top_line: "알코올 10% 이상 음료는", contains_info: true, claim_ids: ["c9"] });
  const s = await ok("meme_save_draft", { card_id: await preciseCard(), spec: info, evidence_review_id: review });
  await fails("meme_draft_action", { draft_id: s.draft_id, action: "approve" }, "meme_evidence_missing");
  await ok("meme_save_draft", { draft_id: s.draft_id, spec: { ...info, claim_ids: ["c1"] }, evidence_review_id: review });
  await ok("meme_draft_action", { draft_id: s.draft_id, action: "approve" });
  await db.exec("set session_replication_role = replica");
  await db.query(`update drink_topic_reviews set revoked_at = now(), revoked_reason = '시험' where id = $1`, [review]);
  await db.exec("set session_replication_role = origin");
  assert.equal((await rpc("drinks_meme_claim", { worker_id: "w" })).job, null);
  const { rows: after } = await db.query<{ status: string; error_code: string }>(`select status, error_code from drink_meme_drafts where id = $1`, [s.draft_id]);
  assert.deepEqual(after[0], { status: "stopped", error_code: "meme_evidence_missing" });
});

test("화면 조회가 기대는 외래 키 이름이 그대로다", async () => {
  const { rows } = await db.query(`select 1 from pg_constraint where conname = 'drink_topic_reviews_topic_id_fkey'`);
  assert.equal(rows.length, 1);
});

test("남의 영상 주소는 저장 자체가 거부된다", async () => {
  const card = await preciseCard();
  await fails("meme_save_draft", { card_id: card, spec: spec({ note: "https://www.instagram.com/reel/ABCDE/" }) }, "meme_foreign_media");
  const { rows } = await db.query(`select 1 from drink_meme_drafts where card_id = $1`, [card]);
  assert.equal(rows.length, 0);
});

test("산 장면 칸: 우리 권리 파일이 없으면 승인되지 않는다", async () => {
  const saved = await ok("meme_save_draft", { card_id: await preciseCard(), spec: spec({ scene: { source: "bought_reaction", asset_id: "00000000-0000-0000-0000-000000000000" }, caption: "AI 생성 영상" }) });
  await fails("meme_draft_action", { draft_id: saved.draft_id, action: "approve" }, "meme_foreign_media");
});

test("길이: 6~15초 밖은 막힌다", async () => {
  const saved = await ok("meme_save_draft", { card_id: await preciseCard(), spec: spec({ beats: [{ text: "짧다", keyword: "", ms: 2000 }] }) });
  await fails("meme_draft_action", { draft_id: saved.draft_id, action: "approve" }, "meme_duration");
});

test("카드 조건: [쓰자] + 정밀 틀만", async () => {
  const card = await preciseCard();
  await db.query(`delete from drink_ig_card_fields where card_id = $1 and field = 'twist_at'`, [card]);
  await fails("meme_save_draft", { card_id: card, spec: spec() }, "card_not_precise");
  const later = await preciseCard();
  await db.query(`update drink_ig_cards set decision = 'later' where id = $1`, [later]);
  await fails("meme_save_draft", { card_id: later, spec: spec() }, "invalid_state");
  await fails("meme_save_draft", { spec: spec() }, "invalid_input");
});

test("살아 있는 제작안은 카드당 하나, 승인 뒤 내용은 안 바뀐다, 승인 지문이 다르면 제작이 멈춘다", async () => {
  await drain();
  const card = await preciseCard();
  const saved = await ok("meme_save_draft", { card_id: card, spec: spec() });
  await fails("meme_save_draft", { card_id: card, spec: spec() }, "draft_exists");
  await fails("meme_draft_action", { draft_id: saved.draft_id, expected_version: saved.version + 5, action: "approve" }, "version_conflict");
  await ok("meme_draft_action", { draft_id: saved.draft_id, action: "approve" });
  await fails("meme_save_draft", { draft_id: saved.draft_id, spec: spec() }, "invalid_state");
  await assert.rejects(db.query(`update drink_meme_drafts set spec = spec || '{"top_line":"바꿈"}' where id = $1`, [saved.draft_id]), /immutable/);
  await db.query(`update drink_meme_drafts set approved_digest = 'tampered' where id = $1`, [saved.draft_id]);
  assert.equal((await rpc("drinks_meme_claim", { worker_id: "w" })).job, null);
  const { rows } = await db.query<{ status: string; error_code: string }>(`select status, error_code from drink_meme_drafts where id = $1`, [saved.draft_id]);
  assert.deepEqual(rows[0], { status: "stopped", error_code: "digest_changed" });
  // 되돌리면 다시 고칠 수 있다
  assert.equal((await ok("meme_draft_action", { draft_id: saved.draft_id, action: "reopen" })).status, "draft");
});

test("제작 전이: 임대 없으면 끝낼 수 없고, 렌더 중이 아니면 게시 대기로 못 간다", async () => {
  await drain();
  const saved = await ok("meme_save_draft", { card_id: await preciseCard(), spec: spec() });
  await assert.rejects(db.query(`update drink_meme_drafts set status = 'publish_waiting', files = '[{"role":"final_video"}]', approved_at = now(), approved_digest = 'x' where id = $1`, [saved.draft_id]), /invalid_transition/);
  await ok("meme_draft_action", { draft_id: saved.draft_id, action: "approve" });
  const { job } = await rpc("drinks_meme_claim", { worker_id: "w" });
  await rpcFails("drinks_meme_finish", { draft_id: job.draft_id, lease_token: "00000000-0000-0000-0000-000000000000", outcome: "rendered", files: FILES }, "lease_lost");
  await rpcFails("drinks_meme_finish", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "rendered", files: [{ role: "final_video", storage_key: "elsewhere/x.mp4", sha256: "a".repeat(64) }] }, "invalid_manifest");
  // 임대가 끝나면 실패로 닫힌다
  await db.query(`update drink_meme_drafts set lease_expires_at = now() - interval '1 minute' where id = $1`, [job.draft_id]);
  await rpc("drinks_meme_claim", { worker_id: "w2" });
  const { rows } = await db.query<{ status: string; error_code: string }>(`select status, error_code from drink_meme_drafts where id = $1`, [job.draft_id]);
  assert.deepEqual(rows[0], { status: "failed", error_code: "worker_lost" });
});

test("글 초안: 결재 없으면 요청 불가, 가잡기는 상한·잔액 안에서만, 초안으로만 끝난다", async () => {
  const card = await preciseCard();
  await fails("meme_request_text", { card_id: card, frame: "top_text" }, "budget_missing");
  const b = await ok("open_develop_budget", { stage: "meme-test", purpose: "밈 글 초안 시험", cap_usd: 0.03, approver_words: "시험" });
  const req = await ok("meme_request_text", { card_id: card, frame: "top_text", budget_id: b.budget_id });
  assert.equal(req.status, "text_requested");
  const { job } = await rpc("drinks_meme_claim", { worker_id: "w", kind: "text" });
  assert.equal(job.frame, "top_text");
  assert.equal(job.card.fields.beat_count.value, "3");
  assert.equal("permalink" in job.card, false);
  await rpcFails("drinks_meme_hold", { draft_id: job.draft_id, lease_token: job.lease_token, est_usd: 0.05 }, "request_cap_exceeded");
  const h1 = await rpc("drinks_meme_hold", { draft_id: job.draft_id, lease_token: job.lease_token, est_usd: 0.01, model: "m" });
  await rpc("drinks_develop_settle", { hold_id: h1.hold_id, outcome: "settled", actual_usd: 0.004 });
  const { rows } = await db.query<{ spent_usd: string }>(`select spent_usd from drink_develop_budget_state where budget_id = $1`, [b.budget_id]);
  assert.equal(Number(rows[0].spent_usd), 0.004, "밈 지출도 같은 결재 잔액에서 잡힌다");
  await rpcFails("drinks_meme_finish_text", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "ok", spec: { x: "https://www.tiktok.com/a" } }, "invalid_input");
  const done = await rpc("drinks_meme_finish_text", { draft_id: job.draft_id, lease_token: job.lease_token, outcome: "ok", spec: spec() });
  assert.equal(done.status, "draft");
});

test("소재 고르기 → 밈 의도가 이어진다", async () => {
  const topic = (await ok("create_topic", { title: "밈 소재", question: "왜 웃긴가?", categories: ["whisky"], lane: "evergreen" })).topic_id;
  await fails("meme_save_draft", { topic_id: topic, spec: spec() }, "invalid_state");
  await db.query(`insert into drink_topic_picks (topic_id, format_intent, editorial_week) values ($1, 'meme', date_trunc('week', now())::date)`, [topic]);
  const saved = await ok("meme_save_draft", { topic_id: topic, spec: spec() });
  assert.equal(saved.status, "draft");
  const { rows: board } = await db.query<{ owner_name: string; blockers: unknown[] }>(`select owner_name, blockers from drink_meme_board where id = $1`, [saved.draft_id]);
  assert.deepEqual(board[0].blockers, []);
  assert.ok(board[0].owner_name);
});

test("권한: 공개 역할은 표·보기·함수에 닿지 않는다", async () => {
  await db.exec("set role anon");
  try {
    await assert.rejects(db.query(`select * from drink_meme_drafts`), /permission denied/);
    await assert.rejects(db.query(`select * from drink_meme_board`), /permission denied/);
    await assert.rejects(db.query(`select drinks_meme_claim('{}'::jsonb)`), /permission denied/);
  } finally {
    await db.exec("reset role");
  }
});

test("규칙은 파이썬과 같은 글을 같은 뜻으로 읽는다(한글·공백)", async () => {
  const hit = async (t: string) => (await db.query<{ c: string | null }>(`select substring($1::text from '(?i)' || pattern) as c from drinks_meme_unsafe_rules() order by 1 limit 1`, [t])).rows[0].c;
  assert.equal(await hit("한 잔 더"), "한 잔 더");
  assert.equal(await hit("가격표만 기억난다"), null);
  const info = async (t: string) => (await db.query<{ b: boolean }>(`select $1::text ~* drinks_meme_info_pattern() as b`, [t])).rows[0].b;
  assert.equal(await info("3초 고민"), false);
  assert.equal(await info("도수 40%"), true);
});
