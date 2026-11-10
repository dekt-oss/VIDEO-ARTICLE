// 인스타 트렌드 보드(0063) DB 통합 테스트 — PGlite 위에 주류 마이그레이션 전부(00(5x|6x)_drinks_*).
// 실행 상태 5종, 정상 관측일, 릴스 합치기·날짜별 마지막 값·null 보존, 카드 병합·형식 칸 근거, 수명 거부, 운영자 동작, 공개 역할 차단.
// ★ 합격 시험(기획 §9 P1)을 시뮬레이션으로 돈다: 토큰을 뺀 날은 failed 로 남고 카드 수명이 멈춘다.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";
import { runDrinksAction } from "./actions.ts";
import { boardHealth, type IgRunRow } from "./igTrends.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d|8\d)_drinks_.*\.sql$/.test(f)).sort().map((f) => join(DIR, f));
const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(m, "utf8"));

type Any = any;
const call = async (fn: string, p: Record<string, unknown>): Promise<Any> => {
  try {
    await db.exec("set role service_role");
    return (await db.query<{ r: unknown }>(`select ${fn}($1::jsonb) as r`, [JSON.stringify(p)])).rows[0].r;
  } finally {
    await db.exec("reset role");
  }
};
const fails = (fn: string, p: Record<string, unknown>, re: RegExp) => assert.rejects(() => call(fn, p), re);
const asService = async (sql: string): Promise<Any[]> => {
  try {
    await db.exec("set role service_role");
    return (await db.query(sql)).rows;
  } finally {
    await db.exec("reset role");
  }
};
const uniq = () => Math.random().toString(36).slice(2, 10);
// 날짜가 겹치지 않게 시험마다 다른 구간을 쓴다.
const day = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

const rec = (source: string, observed_on: string, status: string, o: Record<string, unknown> = {}) =>
  call("drinks_ig_record_run", { source, observed_on, status, ...o });
async function normalDay(d: string) {
  await rec("t1", d, "ok", { attempted: 8, succeeded: 8, items: 100 });
  await rec("t2", d, "ok", { attempted: 10, succeeded: 10, items: 200 });
}
async function failedDay(d: string, reason = "token_missing") {
  await rec("t1", d, "failed", { attempted: 2, succeeded: 0, failure_reasons: { [reason]: 2 } });
  await rec("t2", d, "failed", { attempted: 10, succeeded: 0, failure_reasons: { [reason]: 10 } });
  await rec("t3", d, "failed", { attempted: 0, succeeded: 0, failure_reasons: { [reason]: 1 } });
}
const mediaItem = (media_id: string, o: Record<string, unknown> = {}) => ({ media_id, permalink: `https://www.instagram.com/reel/${media_id}/`, view_count: 100,
  age_bucket: "d3_7", age_hours: 90, trend_flag: "normal", ...o });
const putMedia = (observed_on: string, username: string, items: unknown[], source = "t2") => call("drinks_ig_record_media", { observed_on, username, source, items });
const card = (observed_on: string, merge_key: string, o: Record<string, unknown> = {}) =>
  call("drinks_ig_upsert_card", { observed_on, merge_key, kind: "single_reel", name: "카드", examples: [], fields: [], ...o });
const life = (observed_on: string, cards: unknown[]) => call("drinks_ig_apply_lifecycle", { observed_on, cards });
const cardRow = async (id: string) => (await asService(`select * from drink_ig_cards where id='${id}'`))[0];
const execRpc = async (fn: string, p: Record<string, unknown>) => {
  try {
    return { data: await call(fn, p), error: null };
  } catch (e) {
    return { data: null, error: { message: (e as Error).message } };
  }
};

test("마이그레이션 묶음에 0063 이 들어 있다", () => {
  assert.ok(MIGS.some((m) => m.endsWith("0063_drinks_ig_trend_board.sql")));
});

// ── 실행 상태 ──

test("실행 상태 5종: 숫자와 맞으면 저장, 어긋나면 거부", async () => {
  const d = day(400);
  await rec("t1", d, "ok", { attempted: 8, succeeded: 8, items: 50 });
  await rec("t2", d, "partial", { attempted: 10, succeeded: 7, items: 70, failure_reasons: { invalid_user: 3 }, excluded_no_views: 4 });
  await rec("t3", d, "ok_empty", { attempted: 0, succeeded: 0, items: 0 });
  const r = (await asService(`select * from drink_ig_trend_runs where observed_on='${d}' and source='t2'`))[0];
  assert.deepEqual(r.failure_reasons, { invalid_user: 3 });
  assert.equal(r.excluded_no_views, 4);
  const d2 = day(401);
  await fails("drinks_ig_record_run", { source: "t1", observed_on: d2, status: "ok", attempted: 8, succeeded: 8, items: 0 }, /invalid_input/);
  await fails("drinks_ig_record_run", { source: "t1", observed_on: d2, status: "ok_empty", attempted: 8, succeeded: 8, items: 3 }, /invalid_input/);
  await fails("drinks_ig_record_run", { source: "t1", observed_on: d2, status: "partial", attempted: 8, succeeded: 8, items: 3 }, /invalid_input/);
  await fails("drinks_ig_record_run", { source: "t1", observed_on: d2, status: "partial", attempted: 8, succeeded: 0, items: 0 }, /invalid_input/);
  await fails("drinks_ig_record_run", { source: "t1", observed_on: d2, status: "failed", attempted: 8, succeeded: 2, items: 0 }, /invalid_input/);
  await fails("drinks_ig_record_run", { source: "t1", observed_on: d2, status: "done", attempted: 1, succeeded: 1, items: 1 }, /invalid_input/);
  await fails("drinks_ig_record_run", { source: "t1", status: "ok", attempted: 1, succeeded: 1, items: 1 }, /invalid_input/);
});

test("T4 는 자리만 있다: 기록 함수가 받지 않는다", async () => {
  await fails("drinks_ig_record_run", { source: "t4", observed_on: day(402), status: "ok", attempted: 1, succeeded: 1, items: 1 }, /t4/);
  assert.equal((await asService(`select count(*)::int n from drink_ig_trend_runs where source='t4'`))[0].n, 0);
});

test("not_run 은 빈 날만 채우고 있는 기록을 덮지 않는다. 다른 상태는 같은 날 다시 돌면 마지막 값", async () => {
  const d = day(403);
  await rec("t1", d, "ok", { attempted: 8, succeeded: 8, items: 50 });
  const filled = await rec("t1", d, "not_run");
  assert.equal(filled.written, false);
  assert.equal((await asService(`select status from drink_ig_trend_runs where source='t1' and observed_on='${d}'`))[0].status, "ok");
  const d2 = day(404);
  assert.equal((await rec("t1", d2, "not_run")).written, true);
  await rec("t1", d2, "failed", { attempted: 2, succeeded: 0, failure_reasons: { token_expired: 2 } });
  assert.equal((await asService(`select status from drink_ig_trend_runs where source='t1' and observed_on='${d2}'`))[0].status, "failed");
});

test("정상 관측일: T1 ok + T2 80% 이상, 경계·활성 0개·T1 일부 실패", async () => {
  const d = day(410);
  await rec("t1", d, "ok", { attempted: 8, succeeded: 8, items: 1 });
  assert.equal((await rec("t2", d, "partial", { attempted: 10, succeeded: 8, items: 1 })).normal_day, true);
  const d2 = day(411);
  await rec("t1", d2, "ok", { attempted: 8, succeeded: 8, items: 1 });
  assert.equal((await rec("t2", d2, "partial", { attempted: 10, succeeded: 7, items: 1 })).normal_day, false);
  const d3 = day(412);
  await rec("t1", d3, "ok", { attempted: 8, succeeded: 8, items: 1 });
  assert.equal((await rec("t2", d3, "ok_empty", { attempted: 0, succeeded: 0, items: 0 })).normal_day, false, "활성 계정 0개");
  const d4 = day(413);
  await rec("t1", d4, "partial", { attempted: 8, succeeded: 7, items: 1 });
  assert.equal((await rec("t2", d4, "ok", { attempted: 10, succeeded: 10, items: 1 })).normal_day, false);
  const d5 = day(414);
  await rec("t1", d5, "ok_empty", { attempted: 8, succeeded: 8, items: 0 });
  assert.equal((await rec("t2", d5, "ok", { attempted: 10, succeeded: 10, items: 1 })).normal_day, false);
});

// ── 릴스 ──

test("릴스: 미디어 ID 로 하나, T2·T3 출처 합침, 같은 날은 마지막 값, 날이 다르면 행이 따로", async () => {
  const id = `m${uniq()}`;
  await putMedia(day(20), "acct", [mediaItem(id, { view_count: 100 })]);
  await putMedia(day(20), "acct", [mediaItem(id, { view_count: 250 })], "t3");
  await putMedia(day(19), "acct", [mediaItem(id, { view_count: 300, age_bucket: "d7_plus" })]);
  const m = (await asService(`select * from drink_ig_media where media_id='${id}'`));
  assert.equal(m.length, 1);
  assert.deepEqual(m[0].sources, ["t2", "t3"]);
  const obs = await asService(`select observed_on::text d, view_count::int v, age_bucket b from drink_ig_media_observations where media_id='${id}' order by 1`);
  assert.deepEqual(obs, [{ d: day(20), v: 250, b: "d3_7" }, { d: day(19), v: 300, b: "d7_plus" }]);
});

test("view_count: 없으면 null, 진짜 0 은 0. 뒤 관측이 없으면 앞 값을 끌어 쓰지 않는다", async () => {
  const a = `m${uniq()}`, b = `m${uniq()}`, c = `m${uniq()}`;
  await putMedia(day(21), "acct", [mediaItem(a, { view_count: null, trend_flag: "no_views" }), mediaItem(b, { view_count: 0 }), mediaItem(c, { view_count: 500 })]);
  await putMedia(day(21), "acct", [mediaItem(c, { view_count: null, trend_flag: "no_views" })]);
  const v = async (id: string) => (await asService(`select view_count from drink_ig_media_observations where media_id='${id}'`))[0].view_count;
  assert.equal(await v(a), null);
  assert.equal(Number(await v(b)), 0);
  assert.equal(await v(c), null);
});

test("릴스 값 거부: 음수 조회수·없는 나이 구간·없는 판정·잘못된 계정 이름", async () => {
  const d = day(22);
  await fails("drinks_ig_record_media", { observed_on: d, username: "acct", source: "t2", items: [mediaItem(`m${uniq()}`, { view_count: -1 })] }, /invalid_input/);
  await fails("drinks_ig_record_media", { observed_on: d, username: "acct", source: "t2", items: [mediaItem(`m${uniq()}`, { age_bucket: "오늘" })] }, /invalid_input/);
  await fails("drinks_ig_record_media", { observed_on: d, username: "acct", source: "t2", items: [mediaItem(`m${uniq()}`, { trend_flag: "viral" })] }, /invalid_input/);
  await fails("drinks_ig_record_media", { observed_on: d, username: "No Spaces", source: "t2", items: [] }, /invalid_input/);
  await fails("drinks_ig_record_media", { observed_on: d, username: "acct", source: "t4", items: [] }, /invalid_input/);
});

test("backfill 표시는 처음 적힌 값을 지킨다", async () => {
  const id = `m${uniq()}`;
  await putMedia(day(23), "acct", [mediaItem(id, { is_backfill: true })]);
  await putMedia(day(22), "acct", [mediaItem(id, { is_backfill: false })]);
  assert.equal((await asService(`select is_backfill from drink_ig_media where media_id='${id}'`))[0].is_backfill, true);
});

test("남의 영상 주소를 넣을 칸이 없다", async () => {
  const cols = await asService(`select column_name c from information_schema.columns where table_name like 'drink_ig_%'`);
  assert.ok(cols.length > 30);
  assert.ok(cols.some(({ c }) => c === "has_video_url"), "왔는지만 기록한다");
  for (const { c } of cols.filter(({ c }) => c !== "has_video_url")) assert.ok(!/media_url|video_url|video_path|download_url|storage/.test(c), c);
});

test("기준선 행: 릴스·구간당 가장 최근 값 하나, 조회수 없는 관측은 뺀다, 다른 계정은 안 나온다", async () => {
  const u = `base${uniq()}`.toLowerCase();
  const a = `m${uniq()}`;
  await putMedia(day(30), u, [mediaItem(a, { view_count: 10 })]);
  await putMedia(day(29), u, [mediaItem(a, { view_count: 20 })]);
  await putMedia(day(28), u, [mediaItem(a, { view_count: 30, age_bucket: "d7_plus" })]);
  await putMedia(day(27), u, [mediaItem(a, { view_count: null, age_bucket: "d7_plus", trend_flag: "no_views" })]);
  await putMedia(day(30), "someoneelse", [mediaItem(`m${uniq()}`)]);
  const rows: Any[] = await call("drinks_ig_baseline_rows", { usernames: [u], since: day(60) });
  const got = rows.map((r) => [r.age_bucket, r.view_count]).sort();
  assert.deepEqual(got, [["d3_7", 20], ["d7_plus", 30]]);
});

// ── 카드 ──

test("카드: 정상 관측일이 아니면 거부, 같은 키는 한 장, 릴스 하나는 카드 하나에만", async () => {
  const bad = day(40);
  await failedDay(bad);
  await fails("drinks_ig_upsert_card", { observed_on: bad, merge_key: `reel:${uniq()}`, kind: "single_reel", name: "x" }, /not_normal_day/);
  const d = day(39);
  await normalDay(d);
  const key = `audio:${uniq()}`;
  const m1 = `m${uniq()}`, m2 = `m${uniq()}`;
  await putMedia(d, "acct", [mediaItem(m1), mediaItem(m2)]);
  const a = await card(d, key, { kind: "audio", audio_id: key, examples: [{ media_id: m1, origin: "rising_reel", view_multiple: 3.5 }] });
  assert.equal(a.created, true);
  assert.equal(a.new_examples, 1);
  assert.equal(a.new_accounts, 1);
  const b = await card(d, key, { kind: "audio", audio_id: key, examples: [{ media_id: m1, origin: "rising_reel" }, { media_id: m2, origin: "rising_reel" }] });
  assert.equal(b.created, false);
  assert.equal(b.card_id, a.card_id);
  assert.equal(b.new_examples, 2, "그날 붙은 예시 수");
  assert.equal(b.new_accounts, 1, "같은 계정은 한 번");
  const other = await card(d, `reel:${uniq()}`, { examples: [{ media_id: m1, origin: "rising_reel" }] });
  assert.equal(other.new_examples, 0, "이미 다른 카드에 붙은 릴스");
  await fails("drinks_ig_upsert_card", { observed_on: d, merge_key: `x:${uniq()}`, kind: "whatever", name: "x" }, /invalid_input/);
});

test("같은 음원·다른 구조는 다른 카드, 연결 수만 표시", async () => {
  const d = day(38);
  await normalDay(d);
  const audio = uniq();
  await card(d, `audio:${audio}|s:pov`, { kind: "audio", audio_id: audio, structure: "pov" });
  const x = await card(d, `audio:${audio}|s:list`, { kind: "audio", audio_id: audio, structure: "list" });
  const v = (await asService(`select same_audio_cards::int n, structure from drink_ig_board_cards where id='${x.card_id}'`))[0];
  assert.equal(v.n, 1);
  assert.equal(v.structure, "list");
});

test("형식 칸: 영상 전용 칸은 표지·캡션·API 근거를 DB 가 거부한다", async () => {
  const d = day(37);
  await normalDay(d);
  for (const evidence of ["cover", "caption", "api_metrics"]) {
    await fails("drinks_ig_upsert_card", { observed_on: d, merge_key: `reel:${uniq()}`, kind: "single_reel", name: "x",
      fields: [{ field: "beat_count", value: "4", evidence, confidence: "low" }] }, /invalid_input/);
  }
  const ok = await card(d, `reel:${uniq()}`, { fields: [
    { field: "beat_count", value: "4", evidence: "video", confidence: "high" },
    { field: "caption_hook", value: "훅", evidence: "caption", confidence: "high" },
    { field: "structure", value: "pov", evidence: "cover", confidence: "low" },
  ] });
  const fields = (await asService(`select fields from drink_ig_board_cards where id='${ok.card_id}'`))[0].fields;
  assert.deepEqual(fields.structure, { value: "pov", evidence: "cover", confidence: "low" });
  assert.equal(fields.twist_at, undefined, "값이 없으면 행이 없다(= null)");
  await assert.rejects(() => asService(`insert into drink_ig_card_fields(card_id, field, value, evidence, confidence) values ('${ok.card_id}', 'music_sync', 'x', 'cover', 'low')`), /video_only/);
});

test("정밀 틀 승격: 세 칸이 video·운영자로 다 차야 한다. 운영자가 넣은 값은 워커가 덮지 않는다", async () => {
  const d = day(36);
  await normalDay(d);
  const key = `reel:${uniq()}`;
  const c = await card(d, key, { fields: [{ field: "beat_count", value: "4", evidence: "video", confidence: "high" }] });
  const prec = async () => (await asService(`select precision from drink_ig_board_cards where id='${c.card_id}'`))[0].precision;
  assert.equal(await prec(), "reference");
  await call("drinks_ig_set_card_field", { card_id: c.card_id, field: "cut_lengths", value: "1.2,0.8" });
  assert.equal(await prec(), "reference");
  const done = await call("drinks_ig_set_card_field", { card_id: c.card_id, field: "twist_at", value: "3.2" });
  assert.equal(done.precision, "precise");
  assert.equal(await prec(), "precise");
  await card(d, key, { fields: [{ field: "twist_at", value: "9.9", evidence: "video", confidence: "high" }] });
  assert.equal((await asService(`select value from drink_ig_card_fields where card_id='${c.card_id}' and field='twist_at'`))[0].value, "3.2");
  await call("drinks_ig_set_card_field", { card_id: c.card_id, field: "twist_at", value: "" });
  assert.equal(await prec(), "reference", "칸을 비우면 다시 참고 카드");
  await fails("drinks_ig_set_card_field", { card_id: c.card_id, field: "structure", value: "밈" }, /invalid_input/);
  await fails("drinks_ig_set_card_field", { card_id: c.card_id, field: "없는칸", value: "1" }, /invalid_input/);
  await call("drinks_ig_set_card_field", { card_id: c.card_id, field: "structure", value: "twist" });
  assert.equal((await cardRow(c.card_id)).structure, "twist");
});

test("[쓰자]/[넘기기]/[나중에]: 결정만 기록하고 카드 상태를 바꾸지 않는다", async () => {
  const d = day(35);
  await normalDay(d);
  const c = await card(d, `reel:${uniq()}`);
  const before = await cardRow(c.card_id);
  const tables = async () => (await asService(`select count(*)::int n from drink_ig_cards`))[0].n;
  const n0 = await tables();
  const r = await runDrinksAction(execRpc as never, { action: "ig_card_decide", payload: { card_id: c.card_id, decision: "use", note: "해보자" } });
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.result, { card_id: c.card_id, decision: "use", precision: "reference" });
  const after = await cardRow(c.card_id);
  assert.equal(after.decision, "use");
  assert.equal(after.state, before.state);
  assert.equal(after.quiet_normal_days, before.quiet_normal_days);
  assert.equal(await tables(), n0);
  await call("drinks_ig_card_decide", { card_id: c.card_id, decision: "later" });
  assert.equal((await cardRow(c.card_id)).decision, "later", "다시 고를 수 있다");
  const bad = await runDrinksAction(execRpc as never, { action: "ig_card_decide", payload: { card_id: c.card_id, decision: "publish" } });
  assert.equal(bad.status, 400);
  await fails("drinks_ig_card_decide", { card_id: "00000000-0000-0000-0000-000000000000", decision: "use" }, /not_found/);
});

// ── 수명 ──

test("수명: 7 미만은 식음 거부, 같은 날은 한 번만, 식으면 보관, 다시 살아나면 보관 해제", async () => {
  const d = day(34);
  await normalDay(d);
  const c = await card(d, `reel:${uniq()}`);
  await fails("drinks_ig_apply_lifecycle", { observed_on: d, cards: [{ card_id: c.card_id, state: "cooled", quiet_normal_days: 6 }] }, /invalid_input/);
  await fails("drinks_ig_apply_lifecycle", { observed_on: d, cards: [{ card_id: c.card_id, state: "dead", quiet_normal_days: 1 }] }, /invalid_input/);
  assert.deepEqual(await life(d, [{ card_id: c.card_id, state: "new", quiet_normal_days: 0, increase_streak: 0 }]), { applied: 1, skipped: 0 });
  assert.deepEqual(await life(d, [{ card_id: c.card_id, state: "rising", quiet_normal_days: 9, increase_streak: 9 }]), { applied: 0, skipped: 1 });
  assert.equal((await cardRow(c.card_id)).state, "new");
  const d2 = day(33);
  await normalDay(d2);
  await life(d2, [{ card_id: c.card_id, state: "cooled", quiet_normal_days: 7, increase_streak: 0 }]);
  let row = await cardRow(c.card_id);
  assert.equal(row.state, "cooled");
  assert.ok(row.archived_on, "자동 보관");
  const d3 = day(32);
  await normalDay(d3);
  await life(d3, [{ card_id: c.card_id, state: "new", quiet_normal_days: 0, increase_streak: 0 }]);
  row = await cardRow(c.card_id);
  assert.equal(row.archived_on, null);
});

test("합격 시험(§9 P1 시뮬레이션): 토큰을 뺀 날은 failed 로 남고 카드 수명이 멈춘다", async () => {
  // 7일 전까지 정상. 카드는 새 예시 없이 6일째.
  const n = 7;
  const start = day(n + 200);
  await normalDay(start);
  const c = await card(start, `reel:${uniq()}`);
  await life(start, [{ card_id: c.card_id, state: "new", quiet_normal_days: 6, increase_streak: 0 }]);

  // 토큰을 뺀 날: 워커가 하는 일과 같은 순서로 기록한다.
  const blackout = day(n + 199);
  await call("drinks_ig_record_token_check", { observed_on: blackout, status: "missing", error_code: "token_missing" });
  await failedDay(blackout);
  const runs = await asService(`select source, status, failure_reasons from drink_ig_trend_runs where observed_on='${blackout}' order by source`);
  assert.deepEqual(runs.map((r) => [r.source, r.status]), [["t1", "failed"], ["t2", "failed"], ["t3", "failed"]]);
  assert.ok(runs.every((r) => r.failure_reasons.token_missing >= 1), "사유가 남는다 — 0건처럼 보이지 않는다");
  assert.equal((await asService(`select status from drink_ig_token_checks where checked_on='${blackout}'`))[0].status, "missing");

  // 수명을 세려 하면 DB 가 거부한다. 카드는 하나도 안 바뀐다.
  const before = await cardRow(c.card_id);
  await fails("drinks_ig_apply_lifecycle", { observed_on: blackout, cards: [{ card_id: c.card_id, state: "cooled", quiet_normal_days: 7 }] }, /not_normal_day/);
  await fails("drinks_ig_upsert_card", { observed_on: blackout, merge_key: `reel:${uniq()}`, kind: "single_reel", name: "x" }, /not_normal_day/);
  assert.deepEqual(await cardRow(c.card_id), before);
  assert.equal(before.state, "new");
  assert.equal(before.quiet_normal_days, 6, "식음까지 하루 남은 채로 멈춘다");

  // 사흘 끊기면 화면이 '관측 중단'을 띄운다(이 구간의 실제 행으로 계산).
  const b2 = day(n + 198), b3 = day(n + 197);
  await failedDay(b2);
  await failedDay(b3);
  const rows = (await asService(`select source, observed_on::text observed_on, status, attempted, succeeded, items, failure_reasons, excluded_no_views, detail, finished_at::text finished_at
    from drink_ig_trend_runs where observed_on between '${start}' and '${b3}'`)) as IgRunRow[];
  const frozen = boardHealth(rows, b3, 10);
  assert.equal(frozen.frozen, true);
  assert.equal(frozen.missingStreak, 3);
  assert.equal(frozen.lastNormalDay, start);
  assert.deepEqual(frozen.scope, { succeeded: 0, listed: 10, on: b3 }, "관찰 범위: 계정 성공 0 / 목록 10");

  // 토큰을 되돌리면 그날부터 다시 센다 — 끊긴 사흘은 세지 않았다.
  const back = day(n + 196);
  await normalDay(back);
  await life(back, [{ card_id: c.card_id, state: "cooled", quiet_normal_days: 7, increase_streak: 0 }]);
  assert.equal((await cardRow(c.card_id)).state, "cooled");
  assert.equal(boardHealth((await asService(`select source, observed_on::text observed_on, status, attempted, succeeded from drink_ig_trend_runs where observed_on between '${start}' and '${back}'`)) as IgRunRow[], back, 10).frozen, false);
});

// ── 관찰 계정 ──

test("후보 씨앗은 문서에 있는 이름뿐이고 전부 후보 상태다", async () => {
  const rows = await asService(`select username, status, origin from drink_ig_watch_accounts where origin='doc_measured'`);
  const names = rows.map((r) => r.username);
  for (const n of ["9gag", "pubity", "memezar", "daquan"]) assert.ok(names.includes(n), n);
  assert.ok(rows.every((r) => r.status === "candidate"), "자동 활성화 없음");
  assert.equal((await asService(`select jsonb_array_length(drinks_ig_worker_state('{}'::jsonb) -> 'accounts') n`))[0].n, 0, "체크 전에는 관찰 안 함");
});

test("관찰 계정: 후보 넣기 → 체크 → 뺌, 다시 켜면 첫 관측일을 새로 잡는다(계정 추가 효과 차단)", async () => {
  const u = `acct${uniq()}`;
  const added = await runDrinksAction(execRpc as never, { action: "ig_watch_action", payload: { username: `@${u.toUpperCase()}`, action: "add", kind: "meme" } });
  assert.deepEqual(added.body.result, { username: u, status: "candidate" });
  await call("drinks_ig_watch_action", { username: u, action: "activate" });
  await call("drinks_ig_mark_account", { observed_on: day(50), username: u, ok: true, followers_count: 10 });
  await call("drinks_ig_mark_account", { observed_on: day(49), username: u, ok: true });
  const acc = async () => (await asService(`select * from drink_ig_watch_accounts where username='${u}'`))[0];
  const a = await acc();
  assert.equal(new Date(a.first_observed_on).toISOString().slice(0, 10) <= day(49), true);
  assert.equal(Number(a.followers_count), 10, "새 값이 없으면 지키고");
  const state = (await asService(`select drinks_ig_worker_state('{}'::jsonb) s`))[0].s;
  assert.ok(state.accounts.some((x: Any) => x.username === u));
  await call("drinks_ig_mark_account", { observed_on: day(48), username: u, ok: false, error_code: "invalid_user" });
  assert.equal((await acc()).last_error_code, "invalid_user");
  await call("drinks_ig_watch_action", { username: u, action: "pause" });
  await call("drinks_ig_watch_action", { username: u, action: "activate" });
  assert.equal((await acc()).first_observed_on, null);
  await call("drinks_ig_watch_action", { username: u, action: "pause" });
  await fails("drinks_ig_watch_action", { username: "no such", action: "add" }, /invalid_input/);
  await fails("drinks_ig_watch_action", { username: `none${uniq()}`, action: "activate" }, /not_found/);
  await fails("drinks_ig_watch_action", { username: u, action: "publish" }, /invalid_input/);
});

test("관찰 계정 상한 80", async () => {
  await db.exec(`insert into drink_ig_watch_accounts(username, status) select 'bulk' || g, 'active' from generate_series(1,80) g`);
  await fails("drinks_ig_watch_action", { username: "9gag", action: "activate" }, /active_limit/);
  await call("drinks_ig_watch_action", { username: "bulk1", action: "activate" });   // 이미 활성인 계정을 다시 눌러도 막히지 않는다
  await db.exec(`delete from drink_ig_watch_accounts where username like 'bulk%'`);
});

// ── 운영자 링크 ──

test("링크: 같은 주소는 한 건, 다음 실행의 대기 목록에 오르고, 찾은 뒤 카드에 안 붙으면 다음 정상일을 기다린다", async () => {
  const code = `Ab${uniq()}`;
  const u = `linked${uniq()}`;
  const r = await runDrinksAction(execRpc as never, { action: "ig_add_link", payload: { url: `https://www.instagram.com/reel/${code}/?igsh=1`, username: u } });
  assert.equal(r.status, 200);
  const { link_id } = r.body.result as Any;
  const again = await call("drinks_ig_add_link", { canonical_url: `https://www.instagram.com/reel/${code}/`, shortcode: code, username: u });
  assert.equal(again.existing, true);
  assert.equal(again.link_id, link_id);
  let s = (await asService(`select drinks_ig_worker_state('{}'::jsonb) s`))[0].s;
  assert.ok(s.pending_links.some((l: Any) => l.link_id === link_id));

  const media = `m${uniq()}`;
  await putMedia(day(60), u, [mediaItem(media)], "t3");
  await call("drinks_ig_finish_link", { link_id, status: "resolved", media_id: media, observed_on: day(60) });
  s = (await asService(`select drinks_ig_worker_state('{}'::jsonb) s`))[0].s;
  assert.ok(!s.pending_links.some((l: Any) => l.link_id === link_id));
  assert.ok(s.unattached_links.some((l: Any) => l.media_id === media));

  const d = day(59);
  await normalDay(d);
  await card(d, `reel:${media}`, { examples: [{ media_id: media, origin: "operator_link" }] });
  s = (await asService(`select drinks_ig_worker_state('{}'::jsonb) s`))[0].s;
  assert.ok(!s.unattached_links.some((l: Any) => l.media_id === media));
  assert.ok(s.attached_media.includes(media));

  await fails("drinks_ig_add_link", { canonical_url: "https://evil.com/reel/abcde/", shortcode: "abcde", username: u }, /invalid_input/);
  await fails("drinks_ig_add_link", { canonical_url: "https://www.instagram.com/reel/abcde/", shortcode: "abcde" }, /invalid_input/);
  await fails("drinks_ig_finish_link", { link_id: "00000000-0000-0000-0000-000000000000", status: "failed" }, /not_found/);
});

// ── 읽기 보기 ──

test("보드 카드 보기: 조회수 많은 예시 3개, 조회수 없음은 null, 계정 수, 음원 자리", async () => {
  const d = day(70);
  await normalDay(d);
  const audio = `A${uniq()}`;
  await call("drinks_ig_record_audio", { observed_on: d, items: [{ audio_id: audio, audio_type: "original_sound", title: "곶감 챌린지", list_position: 4, rising_reason: "new" }] });
  const ids = [`m${uniq()}`, `m${uniq()}`, `m${uniq()}`, `m${uniq()}`];
  await putMedia(d, "acct", [mediaItem(ids[0], { view_count: 10 }), mediaItem(ids[1], { view_count: 30 }), mediaItem(ids[2], { view_count: null, trend_flag: "no_views" })]);
  await putMedia(d, "acct2", [mediaItem(ids[3], { view_count: 20 })]);
  const c = await card(d, `audio:${audio}`, { kind: "audio", audio_id: audio, examples: ids.map((media_id) => ({ media_id, origin: "rising_reel", view_multiple: 2 })) });
  const v = (await asService(`select * from drink_ig_board_cards where id='${c.card_id}'`))[0];
  assert.equal(Number(v.examples_count), 4);
  assert.equal(Number(v.accounts_count), 2);
  assert.equal(v.examples.length, 3);
  assert.deepEqual(v.examples.map((e: Any) => e.view_count), [30, 20, 10]);
  assert.equal(v.audio_position, 4);
  assert.equal(new Date(v.audio_position_on).toISOString().slice(0, 10) <= d, true);
});

test("음원: 첫 본 날을 지키고, 같은 날 마지막 자리, 최신 보기는 가장 최근 관측일만", async () => {
  const id = `A${uniq()}`;
  const later = day(5), earlier = day(6);
  await call("drinks_ig_record_audio", { observed_on: later, items: [{ audio_id: id, audio_type: "music", title: "노래", list_position: 3 }] });
  await call("drinks_ig_record_audio", { observed_on: earlier, items: [{ audio_id: id, audio_type: "music", title: "노래", list_position: 9 }] });
  await call("drinks_ig_record_audio", { observed_on: later, items: [{ audio_id: id, audio_type: "music", list_position: 5, preview_url: "http://notsecure" }] });
  const a = (await asService(`select first_seen_on::text f, last_seen_on::text l, title, preview_url from drink_ig_audio where audio_id='${id}'`))[0];
  assert.deepEqual(a, { f: earlier, l: later, title: "노래", preview_url: null });
  const latest = await asService(`select list_position p from drink_ig_audio_latest where audio_id='${id}'`);
  assert.deepEqual(latest, [{ p: 5 }]);
  await fails("drinks_ig_record_audio", { observed_on: later, items: [{ audio_id: `A${uniq()}`, audio_type: "podcast", list_position: 1 }] }, /invalid_input/);
  await fails("drinks_ig_record_audio", { observed_on: later, items: [{ audio_id: `A${uniq()}`, audio_type: "music" }] }, /invalid_input/);
});

test("토큰 기록: 날짜당 하나, 마지막 값. 토큰 값을 넣을 칸이 없다", async () => {
  const d = day(80);
  await call("drinks_ig_record_token_check", { observed_on: d, status: "unavailable", error_code: "network" });
  await call("drinks_ig_record_token_check", { observed_on: d, status: "ok", expires_at: "2026-12-29T14:52:00Z", data_access_expires_at: "2027-01-28T00:00:00Z" });
  const rows = await asService(`select * from drink_ig_token_checks where checked_on='${d}'`);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, "ok");
  assert.equal(rows[0].error_code, null);
  assert.deepEqual(Object.keys(rows[0]).sort(), ["checked_at", "checked_on", "data_access_expires_at", "error_code", "expires_at", "status"]);
  await fails("drinks_ig_record_token_check", { observed_on: d, status: "weird" }, /invalid_input/);
  await fails("drinks_ig_record_token_check", { observed_on: d, status: "ok", expires_at: "어제" }, /invalid_input/);
});

// ── 권한 ──

test("공개 역할은 표·보기·함수 어느 것도 못 쓴다", async () => {
  const objs = ["drink_ig_trend_runs", "drink_ig_watch_accounts", "drink_ig_cards", "drink_ig_media", "drink_ig_board_cards", "drink_ig_audio_latest", "drink_ig_token_checks", "drink_ig_links"];
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    try {
      for (const o of objs) await assert.rejects(() => db.query(`select * from ${o} limit 1`), /permission denied/, `${role} ${o}`);
      await assert.rejects(() => db.query(`select drinks_ig_card_decide('{}'::jsonb)`), /permission denied/);
      await assert.rejects(() => db.query(`select drinks_ig_worker_state('{}'::jsonb)`), /permission denied/);
      await assert.rejects(() => db.query(`select drinks_ig_is_normal_day(current_date)`), /permission denied/);
    } finally {
      await db.exec("reset role");
    }
  }
});

test("모든 표에 RLS 가 켜져 있고 정책은 없다", async () => {
  const t = await asService(`select c.relname n, c.relrowsecurity r from pg_class c join pg_namespace s on s.oid = c.relnamespace where s.nspname='public' and c.relkind='r' and c.relname like 'drink_ig_%'`);
  assert.equal(t.length, 11);
  assert.ok(t.every((x) => x.r === true));
  assert.equal((await asService(`select count(*)::int n from pg_policies where tablename like 'drink_ig_%'`))[0].n, 0);
});
