// 주류 공장 B단계 DB 통합 테스트 — PGlite 위에 0050+0051 을 적용하고 수집원·실행·문서 규칙을 본다.
// 운영자 동작은 라우트와 같은 runDrinksAction 경로로, 워커 동작(drinks_start_run 등)은 워커처럼 rpc 를 직접 부른다.
// ★ PGlite 는 연결 하나라 진짜 동시 실행은 못 만든다 — 같은 요청을 순서대로 두 번 보내는 검사만 한다.
//   두 연결 경합은 supabase/tests/drinks_concurrency.pg.mjs(B 시나리오 포함)가 맡는다.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { DRINKS_ACTIONS, runDrinksAction } from "./actions.ts";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql"]
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
/** 워커 rpc — 라우트를 거치지 않는다(워커는 service key 로 DB 함수를 직접 부른다). */
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
const src = (id: string) => row("select * from drink_sources where id = $1", [id]);
const runRow = (id: string) => row("select * from drink_collection_runs where id = $1", [id]);
const uniq = () => Math.random().toString(36).slice(2);
const LONG = (s: string) => `${s} `.repeat(30);

async function register(extra: Record<string, unknown> = {}): Promise<string> {
  const host = `www.${uniq()}.example.jp`;
  const r = await ok("register_source", {
    name: `국세청 ${uniq()}`, home_url: `https://${host}/`, publisher: "国税庁", language: "ja", categories: ["sake"],
    method: "approved_page", entry_urls: [`https://${host}/a.htm`, `https://${host}/b.htm?id=7&utm_source=x`],
    terms_status: "verified", terms_note: "公共データ利用規約 1.0 — 出典 기재", terms_checked_at: "2026-10-22",
    rights_default: "quote_ok", max_items_per_run: 10, max_bodies_per_run: 3, ...extra,
  });
  return r.source_id;
}
const hostOf = async (id: string) => (await src(id)).allowed_hosts[0] as string;

/** 워커처럼: 실행 하나를 가져와 문서를 기록하고 끝낸다. */
async function runOnce(items: Record<string, unknown>[], finish: Record<string, unknown> = {}) {
  const got = await worker("drinks_start_run", { worker_id: "test" });
  assert.ok(got.run, "가져갈 실행이 있어야 한다");
  const lease = { run_id: got.run.run_id, lease_token: got.run.lease_token };
  const out = [];
  for (const it of items) out.push(await worker("drinks_collect_item", { ...lease, item: it }));
  const fin = await worker("drinks_finish_run", { ...lease, ...finish });
  return { run: got.run, items: out, fin };
}

async function activeSource(extra: Record<string, unknown> = {}): Promise<{ id: string; host: string }> {
  const id = await register(extra);
  const host = await hostOf(id);
  await ok("request_run", { source_id: id, mode: "validate" });
  const v = await runOnce([{ canonical_url: `https://${host}/a.htm`, status: "fetched", title: "A", body_text: LONG("酒類の定義") }]);
  assert.equal(v.fin.status, "succeeded");
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "validate" });
  // 앞 테스트가 활성 12개를 채웠으면 진행 중 실행이 없는 것 하나를 종료해 자리를 만든다(상한 테스트와 독립).
  if ((await row("select count(*)::int n from drink_sources where state = 'active'")).n >= 12) {
    const old = await row(`select id, version from drink_sources s where state = 'active' and not exists
      (select 1 from drink_collection_runs r where r.source_id = s.id and r.status in ('queued','running')) limit 1`);
    await ok("source_action", { source_id: old.id, expected_version: old.version, action: "retire", reason: "테스트 자리" });
  }
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" });
  return { id, host };
}

// ─────────────────────────────────────────────────────────────

test("등록은 항상 제안 상태 — 직접 INSERT 로도 active 로 넣을 수 없고, 허용 호스트는 수집 주소에서만 만든다", async () => {
  const id = await register({ allowed_hosts: ["evil.example.com"] });
  const s = await src(id);
  assert.equal(s.state, "proposed");
  assert.deepEqual(s.allowed_hosts, [new URL(s.entry_urls[0]).hostname]);
  assert.ok(!s.entry_urls[1].includes("utm_source"), "추적 파라미터는 지우고");
  assert.ok(s.entry_urls[1].includes("id=7"), "의미 있는 파라미터는 남긴다");
  await assert.rejects(db.query(`insert into drink_sources (name, home_url, language, categories, method, entry_urls, allowed_hosts,
    terms_status, state) values ('x','https://a.example.jp/','ja','{sake}','approved_page','{https://a.example.jp/}','{a.example.jp}',
    'verified','active')`), /proposed/);
});

test("수집원 주소 검사: http·IP·내부 이름·포트·계정 정보는 등록부터 막는다", async () => {
  for (const u of ["http://a.example.jp/", "https://127.0.0.1/", "https://intranet.local/", "https://a.example.jp:8443/",
    "https://u:p@a.example.jp/", "https://localhost/"]) {
    const r = await act("register_source", { name: "x", home_url: "https://ok.example.jp/", language: "ja", categories: ["sake"],
      method: "approved_page", entry_urls: [u] });
    assert.equal(r.status, 400, `${u}: ${JSON.stringify(r.body)}`);
  }
});

test("활성화 조건: 검증 실행 성공 + 이용 조건 확인 — 하나라도 없으면 거부, 자동 활성화 없음", async () => {
  const id = await register({ terms_status: "unverified" });
  const host = await hostOf(id);
  await fails("source_action", { source_id: id, expected_version: (await src(id)).version, action: "validate" }, "not_validated");
  await fails("request_run", { source_id: id, mode: "collect" }, "source_not_active");
  // 본문을 하나도 못 뽑은 검증 실행은 실패다.
  await ok("request_run", { source_id: id, mode: "validate" });
  const bad = await runOnce([{ canonical_url: `https://${host}/a.htm`, status: "metadata_only", title: "A" }]);
  assert.equal(bad.fin.status, "failed");
  assert.equal((await runRow(bad.run.run_id)).error_code, "no_body_extracted");
  assert.equal((await src(id)).state, "proposed", "검증 실행이 끝나도 상태는 사람이 바꾼다");
  await ok("request_run", { source_id: id, mode: "validate" });
  const good = await runOnce([{ canonical_url: `https://${host}/a.htm`, status: "fetched", title: "A", body_text: LONG("本文") }]);
  assert.equal(good.fin.status, "succeeded");
  assert.equal(good.items[0].status, "checked");
  assert.equal(good.items[0].snapshot_id, null, "검증 실행은 스냅샷을 만들지 않는다");
  assert.equal((await src(id)).state, "proposed");
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "validate" });
  await fails("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" }, "terms_unverified");
  await assert.rejects(db.query("update drink_sources set state = 'active' where id = $1", [id]), /terms_unverified/,
    "함수를 우회한 직접 UPDATE 도 막힌다");
  await fails("source_action", { source_id: id, expected_version: (await src(id)).version, action: "update_terms",
    terms_status: "verified" }, "invalid_input");
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "update_terms",
    terms_status: "verified", terms_note: "출처 기재 시 이용 가능", terms_checked_at: "2026-10-22" });
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" });
  assert.equal((await src(id)).state, "active");
  // 이용 조건을 내리면 수집이 멈춘다.
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "update_terms", terms_status: "restricted" });
  assert.equal((await src(id)).state, "paused");
  await fails("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" }, "terms_unverified");
});

test("수집: 새 문서 → 같은 본문 재실행은 재사용 → 본문 바뀌면 새 버전 → 다른 URL 의 같은 본문은 원출처 후보만", async () => {
  const { id, host } = await activeSource();
  const A = `https://${host}/a.htm`;
  await ok("request_run", { source_id: id, mode: "collect" });
  const r1 = await runOnce([{ canonical_url: A, status: "fetched", title: "A", body_text: LONG("吟醸酒は精米歩合60%以下") }]);
  assert.equal(r1.fin.status, "succeeded");
  assert.equal(r1.items[0].status, "new");
  const snap = await row("select * from drink_source_snapshots where id = $1", [r1.items[0].snapshot_id]);
  assert.equal(snap.capture_method, "collected");
  assert.equal(snap.collected_source_id, id);
  assert.equal(snap.rights_status, "quote_ok", "수집원 기본 사용 조건을 따른다");
  assert.equal((await src(id)).watermark_at !== null, true, "성공한 수집 실행이 워처마크를 올린다");

  await ok("request_run", { source_id: id, mode: "collect" });
  const r2 = await runOnce([{ canonical_url: A, status: "fetched", title: "A", body_text: LONG("吟醸酒は精米歩合60%以下") }]);
  assert.equal(r2.items[0].status, "unchanged");
  assert.equal(r2.items[0].snapshot_id, r1.items[0].snapshot_id);
  assert.equal((await row("select count(*)::int n from drink_source_snapshots where canonical_url = $1", [A])).n, 1);

  await ok("request_run", { source_id: id, mode: "collect" });
  const r3 = await runOnce([
    { canonical_url: A, status: "fetched", title: "A", body_text: LONG("吟醸酒は精米歩合60%以下（改定）") },
    { canonical_url: `https://${host}/copy.htm`, status: "fetched", title: "copy", body_text: LONG("吟醸酒は精米歩合60%以下") },
  ]);
  assert.equal(r3.items[0].status, "changed");
  const v2 = await row("select * from drink_source_snapshots where id = $1", [r3.items[0].snapshot_id]);
  assert.equal(v2.supersedes_id, r1.items[0].snapshot_id);
  assert.equal(r3.items[1].status, "new");
  assert.equal(r3.items[1].same_body_count, 1, "다른 URL 의 같은 본문 — 묶지 않고 센다");
  assert.equal((await row("select origin_group from drink_source_snapshots where id = $1", [r3.items[1].snapshot_id])).origin_group, null);
});

test("결과 구분: 정상 0건 / 부분 성공(워처마크 그대로) / 목록 실패 / 실행 중단", async () => {
  const { id, host } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  const empty = await runOnce([]);
  assert.equal(empty.fin.status, "empty");
  const w1 = (await src(id)).watermark_at;
  assert.ok(w1, "정상 0건도 성공이다 — 워처마크를 올린다");

  await ok("request_run", { source_id: id, mode: "collect" });
  const part = await runOnce([
    { canonical_url: `https://${host}/a.htm`, status: "fetched", title: "A", body_text: LONG("本文A") },
    { canonical_url: `https://${host}/b.htm`, status: "failed", error_code: "http_error", http_status: 503, error_message: "HTTP 503" },
  ]);
  assert.equal(part.fin.status, "partial");
  assert.equal(part.fin.watermark_advanced, false);
  assert.equal(String((await src(id)).watermark_at), String(w1), "부분 성공은 워처마크를 올리지 않는다");

  // 수집원 하나는 24시간에 4번까지 — 나머지 두 경우는 다른 수집원으로 본다.
  const other = await activeSource();
  await ok("request_run", { source_id: other.id, mode: "collect" });
  const fatal = await runOnce([], { error_code: "http_error", error_message: "목록 HTTP 500" });
  assert.equal(fatal.fin.status, "failed", "목록을 못 가져온 0건은 정상 0건이 아니다");

  assert.equal((await src(other.id)).watermark_at, null, "실패는 워처마크를 올리지 않는다");
  await ok("request_run", { source_id: other.id, mode: "collect" });
  const ab = await runOnce([{ canonical_url: `https://${other.host}/c.htm`, status: "metadata_only", title: "C" }],
    { aborted: true, error_code: "time_budget", error_message: "시간 예산" });
  assert.equal(ab.fin.status, "aborted");
  assert.equal((await src(other.id)).watermark_at, null, "중단도 워처마크를 올리지 않는다");
});

test("재시도: 실패 문서만 다시 — 재시도 실행은 워처마크를 올리지 않는다", async () => {
  const { id, host } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  const part = await runOnce([
    { canonical_url: `https://${host}/a.htm`, status: "fetched", title: "A", body_text: LONG("本文A") },
    { canonical_url: `https://${host}/b.htm`, status: "failed", error_code: "timeout", error_message: "시간 초과" },
  ]);
  const w = (await src(id)).watermark_at;
  const req = await ok("request_run", { source_id: id, mode: "retry", retry_of: part.run.run_id });
  assert.equal(req.retry_urls, 1);
  const got = await worker("drinks_start_run", { worker_id: "t" });
  assert.deepEqual(got.run.retry_urls, [`https://${host}/b.htm`]);
  const lease = { run_id: got.run.run_id, lease_token: got.run.lease_token };
  await worker("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/b.htm`, status: "fetched", title: "B",
    body_text: LONG("本文B") } });
  const fin = await worker("drinks_finish_run", lease);
  assert.equal(fin.status, "succeeded");
  assert.equal(String((await src(id)).watermark_at), String(w));
  await fails("request_run", { source_id: id, mode: "retry", retry_of: got.run.run_id }, "invalid_state");
});

test("동시성(순차): 수집원 하나에 대기·실행 중 실행은 하나, 24시간 실행 수 상한, 예약은 하루 한 번", async () => {
  const { id } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  await fails("request_run", { source_id: id, mode: "collect" }, "run_in_progress");
  await runOnce([]);
  const sched = await worker("drinks_request_run", { source_id: id, mode: "collect", requested_by: "schedule", scheduled_for: "2026-10-23" });
  assert.ok(sched.run_id);
  await runOnce([]);
  const again = await worker("drinks_request_run", { source_id: id, mode: "collect", requested_by: "schedule", scheduled_for: "2026-10-23" });
  assert.equal(again.skipped, "already_scheduled");
  // 검증 1 + 수집 2 = 3 → 하나 더 하면 4, 그다음은 상한.
  await ok("request_run", { source_id: id, mode: "collect" });
  await runOnce([]);
  await fails("request_run", { source_id: id, mode: "collect" }, "run_limit");
  // 화면은 예약 실행을 만들 수 없다(route 가 operator 로 고정).
  const forged = await act("request_run", { source_id: id, mode: "collect", requested_by: "schedule", scheduled_for: "2030-01-01" });
  assert.notEqual(forged.status, 200);
  assert.equal((await row("select count(*)::int n from drink_collection_runs where scheduled_for = '2030-01-01'")).n, 0);
});

test("임대: 응답이 끊긴 실행은 running 에 멈추지 않고 다음 워커가 중단 처리 · 임대 잃은 워커의 기록은 거부", async () => {
  const { id, host } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  const got = await worker("drinks_start_run", { worker_id: "w1" });
  await db.query("update drink_collection_runs set lease_expires_at = now() - interval '1 minute' where id = $1", [got.run.run_id]);
  const next = await worker("drinks_start_run", { worker_id: "w2" });
  assert.ok(next.reaped >= 1);
  const r = await runRow(got.run.run_id);
  assert.equal(r.status, "aborted");
  assert.equal(r.error_code, "lease_expired");
  await workerFails("drinks_collect_item", { run_id: got.run.run_id, lease_token: got.run.lease_token,
    item: { canonical_url: `https://${host}/a.htm`, status: "metadata_only" } }, "lease_lost");
  await workerFails("drinks_finish_run", { run_id: got.run.run_id, lease_token: got.run.lease_token }, "lease_lost");
  await assert.rejects(db.query("update drink_collection_runs set status = 'succeeded' where id = $1", [got.run.run_id]), /immutable/,
    "끝난 실행은 고칠 수 없다");
  await assert.rejects(db.query("delete from drink_collection_runs where id = $1", [got.run.run_id]), /immutable/);
});

test("실행 상한: 문서·본문 상한을 넘는 기록, 승인 밖 호스트, 같은 실행의 같은 URL 은 거부·무시", async () => {
  const { id, host } = await activeSource({ max_items_per_run: 3, max_bodies_per_run: 1 });
  await ok("request_run", { source_id: id, mode: "collect" });
  const got = await worker("drinks_start_run", { worker_id: "t" });
  const lease = { run_id: got.run.run_id, lease_token: got.run.lease_token };
  await worker("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/1`, status: "fetched", body_text: LONG("一") } });
  await workerFails("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/2`, status: "fetched",
    body_text: LONG("二") } }, "limit_exceeded");
  await workerFails("drinks_collect_item", { ...lease, item: { canonical_url: "https://other.example.com/x", status: "metadata_only" } },
    "host_not_allowed");
  const dup = await worker("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/1`, status: "metadata_only" } });
  assert.equal(dup.duplicate_in_run, true);
  await worker("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/2`, status: "metadata_only", title: "二" } });
  await worker("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/3`, status: "metadata_only" } });
  await workerFails("drinks_collect_item", { ...lease, item: { canonical_url: `https://${host}/4`, status: "metadata_only" } },
    "limit_exceeded");
  const fin = await worker("drinks_finish_run", lease);
  assert.equal(fin.status, "succeeded");
  const r = await runRow(got.run.run_id);
  assert.equal(r.item_count, 3);
  assert.equal(r.body_count, 1);
  assert.equal(r.metadata_count, 2);
});

test("대기 중 수집원이 멈추면 그 실행은 돌지 않는다", async () => {
  const { id } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "pause", reason: "사이트 개편" });
  const got = await worker("drinks_start_run", { worker_id: "t" });
  assert.equal(got.run, null);
  const r = await row("select * from drink_collection_runs where source_id = $1 order by created_at desc limit 1", [id]);
  assert.equal(r.status, "aborted");
  assert.equal(r.error_code, "source_not_runnable");
});

test("활성 수집원 상한(12)", async () => {
  const active = (await row("select count(*)::int n from drink_sources where state = 'active'")).n;
  for (let i = active; i < 12; i++) await activeSource();
  const id = await register();
  const host = await hostOf(id);
  await ok("request_run", { source_id: id, mode: "validate" });
  await runOnce([{ canonical_url: `https://${host}/a.htm`, status: "fetched", body_text: LONG("本文") }]);
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "validate" });
  await fails("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" }, "active_limit");
  // 다른 테스트가 이어서 활성화할 수 있게 하나를 종료한다.
  const one = await row("select id, version from drink_sources where state = 'active' limit 1");
  await ok("source_action", { source_id: one.id, expected_version: one.version, action: "retire", reason: "테스트 정리" });
  await fails("source_action", { source_id: one.id, expected_version: (await src(one.id)).version, action: "activate" }, "invalid_state");
});

test("수집 문서 → 소재 후보(사람이 질문 작성) · 기존 소재 조사 연결 — 점수·승인·편성은 바뀌지 않는다", async () => {
  const { id, host } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  const r = await runOnce([{ canonical_url: `https://${host}/gi.htm`, status: "fetched", title: "地理的表示",
    body_text: LONG("酒類の地理的表示制度") }]);
  const snapId = r.items[0].snapshot_id;
  const t = await ok("create_topic_from_snapshot", { snapshot_id: snapId, title: "사케 지리적 표시", question: `GI 는 무엇을 보장할까 ${uniq()}`,
    categories: ["sake"], lane: "timely" });
  const topic = await row("select * from drink_topics where id = $1", [t.topic_id]);
  assert.equal(topic.status, "inbox", "후보 등록은 자동 평가·승인하지 않는다");
  assert.equal(topic.provisional_score, null);
  const link = await row("select * from drink_topic_sources where topic_id = $1", [t.topic_id]);
  assert.equal(link.snapshot_id, snapId);
  assert.equal(link.role, "discovery");
  // 경량 평가 사유·조사 필요 사항은 임시 점수와 따로 저장된다.
  await ok("triage", { topic_id: t.topic_id, expected_version: topic.version, reason: "공식 자료가 있음", research_needs: "원문 GI 목록 확인",
    scores: { relevance: 4, utility: 3, curiosity: 3, fit_video: 2, fit_carousel: 4, timeliness: 3 } });
  const tr = await row("select * from drink_topics where id = $1", [t.topic_id]);
  assert.equal(tr.triage_reason, "공식 자료가 있음");
  assert.equal(tr.research_needs, "원문 GI 목록 확인");
  // 조사 연결: discovery → evidence 로 올린다. 이 소재의 승인·편성 포인터는 그대로다.
  const l = await ok("link_snapshot", { topic_id: t.topic_id, snapshot_id: snapId, role: "evidence" });
  assert.equal(l.promoted, true);
  const after = await row("select approved_review_id, selected_review_id, status from drink_topics where id = $1", [t.topic_id]);
  assert.deepEqual(after, { approved_review_id: null, selected_review_id: null, status: "triaged" });
});

test("수동 입력은 '수집 문서'로 위장할 수 없다", async () => {
  await db.query(`insert into drink_source_snapshots (canonical_url, depth, body_text, capture_method)
    values ('https://fake.example.jp/x', 'excerpt', 'x', 'collected')`);
  const s = await row("select capture_method from drink_source_snapshots where canonical_url = 'https://fake.example.jp/x'");
  assert.equal(s.capture_method, "manual");
});

test("권한: 새 표·함수는 anon·authenticated 에 닫혀 있고, 워커 함수는 화면 동작 목록에 없다", async () => {
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    for (const t of ["drink_sources", "drink_collection_runs", "drink_collection_items"]) {
      await assert.rejects(db.query(`select * from ${t}`), /permission denied/, `${role} ${t}`);
    }
    await assert.rejects(db.query(`select drinks_start_run('{}'::jsonb)`), /permission denied/);
    await db.exec("reset role");
  }
  const fns = Object.values(DRINKS_ACTIONS) as string[];
  for (const f of ["drinks_start_run", "drinks_collect_item", "drinks_finish_run", "drinks_heartbeat_run", "drinks_reap_runs"]) {
    assert.ok(!fns.includes(f), `${f} 는 운영자 화면에서 부를 수 없다`);
  }
  const priv = await row(`select has_table_privilege('service_role', 'drink_collection_runs', 'DELETE') as d`);
  assert.equal(priv.d, false);
});

// ── 검토 반영(2026-10-22) ──

test("다 못 본 실행은 성공이 아니다: 상한에 걸린 새 글 → 부분 성공(워처마크 그대로) · 목록에서 링크 0개 → 실패 · 전부 건너뜀 → 실패", async () => {
  const { id, host } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  const capped = await runOnce([{ canonical_url: `https://${host}/a.htm`, status: "fetched", body_text: LONG("本文") }],
    { incomplete_count: 5, parsed_count: 6 });
  assert.equal(capped.fin.status, "partial");
  assert.equal((await runRow(capped.run.run_id)).error_code, "limit_reached");
  assert.equal((await src(id)).watermark_at, null, "다 못 본 실행은 워처마크를 올리지 않는다");

  await ok("request_run", { source_id: id, mode: "collect" });
  const skipped = await runOnce([{ canonical_url: `https://${host}/b.htm`, status: "skipped", error_code: "robots_disallowed" }]);
  assert.equal(skipped.fin.status, "failed");
  assert.equal((await runRow(skipped.run.run_id)).error_code, "all_skipped");

  const lst = await register({ method: "listing", entry_urls: [`https://www.${uniq()}.example.jp/news/`] });
  await ok("request_run", { source_id: lst, mode: "validate" });
  const zero = await runOnce([], { parsed_count: 0 });
  assert.equal(zero.fin.status, "failed", "목록을 받았는데 링크가 0개면 정상 0건이 아니다");
  assert.equal((await runRow(zero.run.run_id)).error_code, "no_candidates");
});

test("버전 판정은 최신 본문과 비교: A→B→A 는 '바뀜'(기존 A 를 가리킴) · 제목만 있던 URL 의 첫 본문은 '새 문서'", async () => {
  const { id, host } = await activeSource({ max_bodies_per_run: 5 });
  const U = `https://${host}/rev.htm`;
  const M = `https://${host}/meta.htm`;
  await ok("request_run", { source_id: id, mode: "collect" });
  const r1 = await runOnce([{ canonical_url: U, status: "fetched", body_text: LONG("版A") },
    { canonical_url: M, status: "metadata_only", title: "M" }]);
  await ok("request_run", { source_id: id, mode: "collect" });
  const r2 = await runOnce([{ canonical_url: U, status: "fetched", body_text: LONG("版B") },
    { canonical_url: M, status: "fetched", body_text: LONG("初本文") }]);
  assert.equal(r2.items[0].status, "changed");
  assert.equal(r2.items[1].status, "new", "제목만 있던 URL 에 처음 본문이 생기면 새 문서");
  await ok("request_run", { source_id: id, mode: "collect" });
  const r3 = await runOnce([{ canonical_url: U, status: "fetched", body_text: LONG("版A") }]);
  assert.equal(r3.items[0].status, "changed", "옛 버전으로 돌아간 것도 최신과 다르면 바뀐 것");
  assert.equal(r3.items[0].snapshot_id, r1.items[0].snapshot_id);
});

test("활성화는 '가장 최근' 검증이 성공이어야 — 옛 성공 뒤 실패한 검증이 있으면 거부", async () => {
  const { id, host } = await activeSource();
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "pause", reason: "개편 확인" });
  await ok("request_run", { source_id: id, mode: "validate" });
  const bad = await runOnce([{ canonical_url: `https://${host}/a.htm`, status: "failed", error_code: "http_error" }]);
  assert.equal(bad.fin.status, "failed");
  await fails("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" }, "not_validated");
});

test("워커가 죽어 running 에 남은 실행은 다음 요청이 먼저 정리한다(일일 실행을 기다리지 않음)", async () => {
  const { id } = await activeSource();
  await ok("request_run", { source_id: id, mode: "collect" });
  const got = await worker("drinks_start_run", { worker_id: "dead" });
  await db.query("update drink_collection_runs set lease_expires_at = now() - interval '1 minute' where id = $1", [got.run.run_id]);
  const again = await ok("request_run", { source_id: id, mode: "collect" });
  assert.ok(again.run_id, "막혀 있지 않다");
  assert.equal((await runRow(got.run.run_id)).status, "aborted");
  await runOnce([]);
});

test("이용 조건 '확인됨' 등록은 요지·확인일이 있어야", async () => {
  const h = `www.${uniq()}.example.jp`;
  const r = await act("register_source", { name: "x", home_url: `https://${h}/`, language: "ja", categories: ["sake"],
    method: "approved_page", entry_urls: [`https://${h}/a`], terms_status: "verified" });
  assert.equal(r.status, 400);
  assert.equal(r.body.code, "invalid_input");
});
