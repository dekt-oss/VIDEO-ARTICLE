// Apify 정밀화·월 상한·수동 카드(0070) DB 통합 테스트 — PGlite 위에 00(5x|6x|70)_drinks_*. 운영자 동작은 라우트와 같은 runDrinksAction, 워커 함수는 rpc 직접.
// ★ 네트워크·Apify·모델 호출 없음. 보이는 것: 클릭 1회 = 요청 1건, 월 $3 에 닿으면 요청이 안 생김, 영상 주소는 저장 거부, 운영자 칸은 덮지 않음,
//   그리고 정밀화로(또는 손으로) 정밀 틀이 된 카드가 밈 제작 엔진의 **같은 함수**(drinks_meme_save_draft → approve → claim → finish)로 간다.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d|8\d)_drinks_.*\.sql$/.test(f)).sort();
assert.ok(MIGS.includes("0070_drinks_apify_refine.sql"));
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
/** 참고 카드(영상 칸 없음) + 공식 API 로 받은 릴스 n개. 카드 만들기 함수는 정상 관측일을 요구하므로 표에 직접 넣는다(시험 전용). */
async function referenceCard(reels = 3): Promise<string> {
  seq += 1;
  const { rows } = await db.query<{ id: string }>(`insert into drink_ig_cards (merge_key, kind, name, first_seen_on) values ($1, 'structure_hook', $2, current_date) returning id`, [`ref${seq}`, `참고카드${seq}`]);
  const id = rows[0].id;
  for (let i = 0; i < reels; i += 1) {
    const mid = `m${seq}_${i}`;
    await db.query(`insert into drink_ig_media (media_id, username, permalink, caption_hook, first_seen_on, last_seen_on) values ($1, 'memeacct', $2, '원본 캡션 첫 줄', current_date, current_date)`,
      [mid, `https://www.instagram.com/reel/R${seq}X${i}AAAA/`]);
    await db.query(`insert into drink_ig_media_observations (media_id, observed_on, view_count, trend_flag) values ($1, current_date, $2, 'rising')`, [mid, 1000 * (i + 1)]);
    await db.query(`insert into drink_ig_card_examples (card_id, media_id, added_on, origin) values ($1, $2, current_date, 'rising_reel')`, [id, mid]);
  }
  return id;
}

const FIELDS = [
  { field: "beat_count", value: "3", evidence: "video", confidence: "high" },
  { field: "cut_lengths", value: "3,3.2,5.3", evidence: "video", confidence: "high" },
  { field: "twist_at", value: "6.2초", evidence: "video", confidence: "low" },
  { field: "music_sync", value: "박자 무관(분위기)", evidence: "video", confidence: "low" },
];
const RESULTS = [{ input_url: "https://www.instagram.com/reel/R1X0AAAA/", status: "ok", duration_sec: 11.5, play_count: 3000, audio_id: "a1", uses_original_audio: true, posted_at: null, has_video: true }];
const spec = (o: Record<string, unknown> = {}) => ({
  frame: "top_text", top_line: "POV: 라벨 읽는 척하는 나", title_keyword: "", caption: "다들 이러죠?",
  beats: [{ text: "앞면을 본다", keyword: "", ms: 3000 }, { text: "뒷면도 본다", keyword: "", ms: 3200 }, { text: "가격표만 기억난다", keyword: "가격표", ms: 5300 }],
  scene: { source: "text_bg", palette: "wine" }, sync_grade: "sync_free", audio: { mode: "ambient_local" }, contains_info: false, claim_ids: [], ...o,
});
const FILES = [{ role: "final_video", storage_key: "drinks/memes/x/final.mp4", sha256: "a".repeat(64) }, { role: "cover", storage_key: "drinks/memes/x/cover.jpg", sha256: "b".repeat(64) }];

test("[쓰자] 한 번 = 결정 기록 + 정밀화 요청 1건(상한 $0.02). 다시 누르면 요청은 하나", async () => {
  const card = await referenceCard();
  const r = await ok("ig_card_use_refine", { card_id: card });
  assert.equal(r.decision, "use");
  assert.equal(r.refine.queued, true);
  assert.equal(Number(r.refine.cap_usd), 0.02);
  assert.equal(Number(r.refine.month.month_cap_usd), 3);
  const again = await ok("ig_card_use_refine", { card_id: card });
  assert.equal(again.refine.queued, false);
  assert.equal(again.refine.code, "request_exists");
  const { rows } = await db.query<{ n: string }>(`select count(*) as n from drink_apify_requests where card_id = $1`, [card]);
  assert.equal(Number(rows[0].n), 1);
});

test("정밀 틀이거나 릴스가 없으면 Apify 를 부르지 않는다(결정은 남는다)", async () => {
  const noReels = await referenceCard(0);
  const r1 = await ok("ig_card_use_refine", { card_id: noReels });
  assert.equal(r1.refine.code, "no_reels");
  const { rows } = await db.query<{ decision: string }>(`select decision from drink_ig_cards where id = $1`, [noReels]);
  assert.equal(rows[0].decision, "use");
  const precise = await referenceCard();
  for (const f of ["beat_count", "cut_lengths", "twist_at"]) {
    await db.query(`insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, $2, '3', 'operator', 'high')`, [precise, f]);
  }
  const r2 = await ok("ig_card_use_refine", { card_id: precise });
  assert.equal(r2.refine.code, "already_precise");
  assert.equal(r2.precision, "precise");
});

test("워커: 점유 → 끝내기. 영상 근거 칸이 카드에 들어가 정밀 틀이 되고, 운영자 칸은 덮지 않고, 실제 금액이 월 누적에 쌓인다", async () => {
  await db.exec(`update drink_apify_requests set status = 'stopped', actual_usd = 0, finished_at = now() where status = 'queued'`);
  const card = await referenceCard();
  await db.query(`insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, 'twist_at', '운영자가 본 9초', 'operator', 'high')`, [card]);
  await ok("ig_card_use_refine", { card_id: card });
  const monthState = async () => (await db.query<{ state: { spent_usd: number } }>(`select state from drink_apify_month_state`)).rows[0].state;
  const before = Number((await monthState()).spent_usd);
  const { job } = await rpc("drinks_apify_claim", { worker_id: "w" });
  assert.equal(job.card.id, card);
  assert.equal(job.reels.length, 3, "공식 API 로 받은 릴스만, 상한 3개");
  assert.ok(job.reels.every((r: Any) => /^https:\/\/www\.instagram\.com\/reel\//.test(r.permalink)));
  assert.equal(Number(job.reels[0].view_count), 3000, "조회수 높은 순");
  assert.deepEqual(job.hooks, ["원본 캡션 첫 줄", "원본 캡션 첫 줄", "원본 캡션 첫 줄"]);
  // 영상 주소가 섞이면 끝내기 자체가 거부된다
  await rpcFails("drinks_apify_finish", { request_id: job.request_id, lease_token: job.lease_token, outcome: "done", results: [{ ...RESULTS[0], videoUrl: "https://x.cdninstagram.com/v.mp4" }], fields: FIELDS, actual_usd: 0.012 }, "media_url_rejected");
  await rpcFails("drinks_apify_finish", { request_id: job.request_id, lease_token: job.lease_token, outcome: "done", results: RESULTS, fields: [{ field: "twist_at", value: "1초", evidence: "cover", confidence: "low" }], actual_usd: 0.012 }, "invalid_input");
  const done = await rpc("drinks_apify_finish", { request_id: job.request_id, lease_token: job.lease_token, outcome: "done", results: RESULTS, fields: FIELDS, actual_usd: 0.0123, run_id: "run1", input_count: 3 });
  assert.equal(done.status, "done");
  assert.equal(done.precision, "precise");
  assert.deepEqual(done.fields_written, ["beat_count", "cut_lengths", "music_sync"], "운영자가 넣은 twist_at 은 덮지 않는다");
  const { rows } = await db.query<{ field: string; value: string; evidence: string }>(`select field, value, evidence from drink_ig_card_fields where card_id = $1 order by field`, [card]);
  assert.deepEqual(rows.find((r) => r.field === "twist_at"), { field: "twist_at", value: "운영자가 본 9초", evidence: "operator" });
  assert.equal(rows.find((r) => r.field === "cut_lengths")?.evidence, "video");
  const after = Number(done.month.spent_usd);
  assert.ok(Math.abs(after - (before - 0.02 + 0.0123)) < 1e-6, `상한 자리(0.02)가 실제 금액(0.0123)으로 바뀐다: ${before} → ${after}`);
  // 정밀 틀이 된 카드 → 밈 제작: 리허설과 같은 DB 함수들
  const saved = await ok("meme_save_draft", { card_id: card, spec: spec() });
  assert.deepEqual(saved.blockers, []);
  await ok("meme_draft_action", { draft_id: saved.draft_id, action: "approve" });
  const m = await rpc("drinks_meme_claim", { worker_id: "w" });
  assert.equal(m.job.draft_id, saved.draft_id);
  assert.equal(m.job.card.fields.cut_lengths.value, "3,3.2,5.3", "정밀화가 채운 컷 길이가 제작 워커에 그대로 간다");
  assert.equal((await rpc("drinks_meme_finish", { draft_id: m.job.draft_id, lease_token: m.job.lease_token, outcome: "rendered", files: FILES })).status, "publish_waiting");
});

test("★ 월 상한 $3: 닿으면 요청이 생기지 않는다(apify_budget_exhausted). 결정은 남는다", async () => {
  await db.exec(`update drink_apify_requests set status = 'stopped', actual_usd = 0, finished_at = now() where status in ('queued','running')`);
  // 이달에 이미 $2.99 를 썼다고 적는다(끝난 요청들)
  const filler = await referenceCard();
  await db.query(`insert into drink_apify_requests (kind, card_id, status, cap_usd, est_usd, actual_usd, month_key, finished_at)
    values ('meme_refine', $1, 'done', 0.02, 0.02, 2.99, drinks_apify_month_key(), now())`, [filler]);
  const card = await referenceCard();
  const r = await ok("ig_card_use_refine", { card_id: card });
  assert.equal(r.decision, "use");
  assert.equal(r.refine.queued, false);
  assert.equal(r.refine.code, "apify_budget_exhausted");
  await fails("ig_card_use_refine", { card_id: "00000000-0000-0000-0000-000000000000" }, "not_found");
  const { rows } = await db.query<{ n: string }>(`select count(*) as n from drink_apify_requests where card_id = $1`, [card]);
  assert.equal(Number(rows[0].n), 0, "요청이 만들어지지 않았다");
  await db.query(`delete from drink_apify_requests where card_id = $1`, [filler]);
});

test("임대가 끝난 실행은 실패로 닫히고 금액은 상한으로 적힌다(모르면 상한)", async () => {
  await db.exec(`update drink_apify_requests set status = 'stopped', actual_usd = 0, finished_at = now() where status in ('queued','running')`);
  const card = await referenceCard();
  await ok("ig_card_use_refine", { card_id: card });
  const { job } = await rpc("drinks_apify_claim", { worker_id: "w" });
  await db.query(`update drink_apify_requests set lease_expires_at = now() - interval '1 minute' where id = $1`, [job.request_id]);
  await rpc("drinks_apify_claim", { worker_id: "w2" });
  const { rows } = await db.query<{ status: string; error_code: string; actual_usd: string }>(`select status, error_code, actual_usd from drink_apify_requests where id = $1`, [job.request_id]);
  assert.deepEqual(rows[0], { status: "failed", error_code: "worker_lost", actual_usd: "0.0200" });
  await rpcFails("drinks_apify_finish", { request_id: job.request_id, lease_token: job.lease_token, outcome: "done", results: [], fields: [] }, "lease_lost");
});

test("손으로 만드는 정밀 틀 카드(정상 관측일 전) → 같은 제작 경로", async () => {
  await db.exec(`update drink_meme_drafts set status = 'rejected' where status = 'approved'`);
  await fails("ig_manual_card", { name: "불완전", fields: { beat_count: "3" } }, "invalid_input");
  await fails("ig_manual_card", { name: "주소", fields: { beat_count: "3", cut_lengths: "3,3,4", twist_at: "6초", cover_text: "https://www.instagram.com/reel/XYZ/" } }, "meme_foreign_media");
  const made = await ok("ig_manual_card", { name: "라벨 읽는 척 POV", structure: "pov", fields: { beat_count: "3", cut_lengths: "3,3,4", twist_at: "6초", music_sync: "박자에 맞춰야 함(필수)" }, note: "운영자가 봄" });
  assert.equal(made.precision, "precise");
  assert.equal(made.sync_required, true);
  const { rows } = await db.query<{ decision: string; merge_key: string; structure: string }>(`select decision, merge_key, structure from drink_ig_cards where id = $1`, [made.card_id]);
  assert.equal(rows[0].decision, "use");
  assert.match(rows[0].merge_key, /^manual:/);
  assert.equal(rows[0].structure, "pov");
  // 박자 맞춤 카드라 박자 무관 제작안은 승인되지 않는다 — 0066 규칙이 그대로 산다
  const bad = await ok("meme_save_draft", { card_id: made.card_id, spec: spec() });
  assert.equal(bad.blockers[0].code, "meme_sync_blocked");
  await ok("meme_draft_action", { draft_id: bad.draft_id, action: "reject" });
  const good = await ok("meme_save_draft", { card_id: made.card_id, spec: spec({ sync_grade: "sync_required", audio: { mode: "app_manual", title: "원본 소리", start_hint_sec: 6 } }) });
  assert.deepEqual(good.blockers, []);
  await ok("meme_draft_action", { draft_id: good.draft_id, action: "approve" });
  const m = await rpc("drinks_meme_claim", { worker_id: "w" });
  assert.equal(m.job.draft_id, good.draft_id);
  const fin = await rpc("drinks_meme_finish", { draft_id: m.job.draft_id, lease_token: m.job.lease_token, outcome: "rendered", files: FILES, guide: "앱에서 붙이세요" });
  assert.equal(fin.status, "manual_audio", "박자 맞춤은 자동 게시로 못 간다");
});

test("표·보기는 공개 역할에 열리지 않고, 요청 표에 영상 주소는 들어갈 수 없다", async () => {
  for (const role of ["anon", "authenticated"]) {
    for (const obj of ["drink_apify_requests", "drink_apify_board", "drink_apify_month_state"]) {
      const { rows } = await db.query<{ ok: boolean }>(`select has_table_privilege($1, $2, 'SELECT') as ok`, [role, obj]);
      assert.equal(rows[0].ok, false, `${role} ${obj}`);
    }
    const { rows } = await db.query<{ ok: boolean }>(`select has_function_privilege($1, 'public.drinks_apify_request(jsonb)', 'EXECUTE') as ok`, [role]);
    assert.equal(rows[0].ok, false);
  }
  const card = await referenceCard();
  await assert.rejects(db.query(`insert into drink_apify_requests (kind, card_id, cap_usd, est_usd, month_key, results)
    values ('meme_refine', $1, 0.02, 0.02, drinks_apify_month_key(), '[{"videoUrl":"https://x.cdninstagram.com/v.mp4"}]')`, [card]), /drink_apify_no_media_url_ck/);
  const { rows } = await db.query(`select 1 from drink_apify_board limit 1`);
  assert.ok(Array.isArray(rows));
});
