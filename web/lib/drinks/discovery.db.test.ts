// 주류 소재 발견(B 보완, 0052) DB 통합 테스트 — PGlite 위에 0050+0051+0052.
// 운영자 동작은 라우트와 같은 runDrinksAction 경로, 워커 동작은 rpc 직접.
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
const rows = async (sql: string, params: unknown[] = []): Promise<Any[]> => (await db.query(sql, params)).rows as Any[];
const src = (id: string) => row("select * from drink_sources where id = $1", [id]);
const uniq = () => Math.random().toString(36).slice(2);
const SE = "https://alcohol.stackexchange.com/questions";

async function runOnce(items: Record<string, unknown>[], finish: Record<string, unknown> = {}) {
  const got = await worker("drinks_start_run", { worker_id: "t" });
  assert.ok(got.run);
  const lease = { run_id: got.run.run_id, lease_token: got.run.lease_token };
  const out = [];
  for (const it of items) out.push(await worker("drinks_collect_discovery", { ...lease, item: it }));
  return { run: got.run, items: out, fin: await worker("drinks_finish_run", { ...lease, ...finish }) };
}
const q = (id: number, extra: Record<string, unknown> = {}) => ({
  status: "fetched", platform: "stackexchange", canonical_url: `${SE}/${id}/q`, title: `How long does opened sake last ${id}?`,
  summary: "Should I keep it in the fridge?", channel_name: "Beer, Wine & Spirits SE · sake", coverage: "title_summary",
  questions: ["How long does opened sake last?"], signals: ["question", "storage"], metrics: { views: 10, answers: 1 }, ...extra,
});

async function activeSE(): Promise<string> {
  const r = await ok("register_discovery_source", { platform: "stackexchange", name: `SE ${uniq()}`, categories: ["sake"],
    queries: ["sake", uniq()], allowed_hosts: ["evil.example.com"] });
  const id = r.source_id;
  await ok("request_run", { source_id: id, mode: "validate" });
  const v = await runOnce([q(1)]);
  assert.equal(v.items[0].status, "checked", "검증 실행은 발견 자료를 만들지 않는다");
  assert.equal(v.fin.status, "succeeded");
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "validate" });
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "update_terms",
    terms_status: "verified", terms_note: "CC BY-SA 4.0, API 하루 300회", terms_checked_at: "2026-10-22" });
  await ok("source_action", { source_id: id, expected_version: (await src(id)).version, action: "activate" });
  return id;
}

test("발견 수집원: 주소·허용 호스트는 커넥터 목록이 정한다(입력 무시), 이용 조건 미확인으로 시작", async () => {
  const r = await ok("register_discovery_source", { platform: "stackexchange", name: `SE ${uniq()}`, categories: ["whisky"],
    queries: ["whisky"], allowed_hosts: ["evil.example.com"] });
  const s = await src(r.source_id);
  assert.deepEqual(s.allowed_hosts, ["api.stackexchange.com"]);
  assert.deepEqual(s.item_hosts, ["alcohol.stackexchange.com"]);
  assert.equal(s.purpose, "discovery");
  assert.equal(s.terms_status, "unverified");
  assert.equal(r.needs_key, false);
  await fails("register_discovery_source", { platform: "instagram", name: "x", categories: ["sake"], queries: ["sake"] }, "invalid_input");
  const yt = await ok("register_discovery_source", { platform: "youtube", name: `YT ${uniq()}`, categories: ["sake"], queries: ["사케"] });
  assert.equal(yt.needs_key, true);
});

test("발견 자료: 새 자료 → 같은 요약 재실행은 변화 없음(관측은 쌓임) → 요약 바뀌면 바뀜 · 미제공 지표는 0 이 아니라 없음", async () => {
  const id = await activeSE();
  await ok("request_run", { source_id: id, mode: "collect" });
  const r1 = await runOnce([q(10), q(11, { metrics: { views: 5, answers: -1, likes: "many" } })]);
  assert.deepEqual(r1.items.map((x: Any) => x.status), ["new", "new"]);
  assert.equal(r1.fin.status, "succeeded");
  const a = await row("select * from drink_discovery_items where canonical_url = $1", [`${SE}/10/q`]);
  const b = await row("select * from drink_discovery_items where canonical_url = $1", [`${SE}/11/q`]);
  assert.deepEqual(a.latest_metrics, { views: 10, answers: 1 });
  assert.deepEqual(b.latest_metrics, { views: 5 }, "음수·문자 지표는 버린다 — 0 으로 바꾸지 않는다");
  assert.equal(a.collection_status, "collected");
  await ok("request_run", { source_id: id, mode: "collect" });
  const r2 = await runOnce([q(10, { metrics: { views: 12, answers: 1 } }), q(11, { summary: "changed body", metrics: {} })]);
  assert.deepEqual(r2.items.map((x: Any) => x.status), ["unchanged", "changed"]);
  const obs = await rows("select metrics from drink_discovery_observations where item_id = $1 order by id", [a.id]);
  assert.deepEqual(obs.map((o) => o.metrics.views), [10, 12], "관측은 시각별로 쌓인다");
  const b2 = await row("select latest_metrics from drink_discovery_items where id = $1", [b.id]);
  assert.deepEqual(b2.latest_metrics, { views: 5 }, "이번에 지표가 안 왔으면 지난 관측을 지우지 않는다");
  await assert.rejects(db.query("update drink_discovery_observations set metrics = '{}' where item_id = $1", [a.id]), /immutable/);
});

test("발견 자료 경계: 채널 밖 주소 거부 · 근거용 문서 기록 함수로 발견 수집원 기록 불가", async () => {
  const id = await activeSE();
  await ok("request_run", { source_id: id, mode: "collect" });
  const got = await worker("drinks_start_run", { worker_id: "t" });
  const lease = { run_id: got.run.run_id, lease_token: got.run.lease_token };
  await workerFails("drinks_collect_discovery", { ...lease, item: q(20, { canonical_url: "https://evil.example.com/x" }) }, "host_not_allowed");
  await workerFails("drinks_collect_item", { ...lease, item: { canonical_url: `${SE}/21/q`, status: "fetched",
    body_text: "x ".repeat(200) } }, "host_not_allowed");
  await worker("drinks_finish_run", lease);
});

test("후보 묶기: 자료 하나는 후보 하나에만(부풀리기 방지) · 열린 후보에 더하기 · 승인·편성과 무관", async () => {
  const id = await activeSE();
  await ok("request_run", { source_id: id, mode: "collect" });
  const r = await runOnce([q(30), q(31), q(32)]);
  const ids = r.items.map((x: Any) => x.discovery_item_id);
  const c = await worker("drinks_suggest_candidate", { item_ids: [ids[0], ids[1]], key_question: "How long does opened sake last?",
    signals: ["question", "storage"], fit_video: 3, fit_carousel: 4, provisional_score: 70, score_reason: "규칙", interest: { independent_sources: 1 } });
  assert.ok(c.candidate_id);
  assert.equal((await worker("drinks_suggest_candidate", { item_ids: [ids[0]], key_question: "dup" })).skipped, "already_assigned");
  const add = await worker("drinks_suggest_candidate", { item_ids: [ids[2]], candidate_id: c.candidate_id });
  assert.equal(add.added, 1);
  const cand = await row("select * from drink_discovery_candidates where id = $1", [c.candidate_id]);
  assert.equal(cand.status, "suggested");
  assert.equal(cand.rubric, "discovery-v1");
  assert.equal((await row("select count(*)::int n from drink_candidate_items where candidate_id = $1", [c.candidate_id])).n, 3);
  assert.equal((await row("select count(*)::int n from drink_topics")).n, 0, "후보를 만들어도 소재가 저절로 생기지 않는다");
});

test("후보 → 소재(사람) · 발견 자료는 URL만(metadata_only) 질문·인기 신호로 붙고 근거로 쓰면 막힌다", async () => {
  const id = await activeSE();
  await ok("request_run", { source_id: id, mode: "collect" });
  const r = await runOnce([q(40), q(41)]);
  const c = await worker("drinks_suggest_candidate", { item_ids: r.items.map((x: Any) => x.discovery_item_id),
    key_question: "How long does opened sake last?" });
  const v = (await row("select version from drink_discovery_candidates where id = $1", [c.candidate_id])).version;
  const p = await ok("promote_candidate", { candidate_id: c.candidate_id, expected_version: v, title: "개봉한 사케, 언제까지 마셔도 될까",
    question: "개봉한 사케는 냉장고에서 얼마나 갈까?", categories: ["sake"] });
  assert.equal(p.linked, 2);
  const t = await row("select * from drink_topics where id = $1", [p.topic_id]);
  assert.equal(t.status, "inbox");
  assert.equal(t.lane, "reader_question");
  const links = await rows(`select ts.role, s.depth, s.capture_method from drink_topic_sources ts
    join drink_source_snapshots s on s.id = ts.snapshot_id where ts.topic_id = $1`, [p.topic_id]);
  assert.deepEqual(links.map((l) => [l.role, l.depth, l.capture_method]), [["discovery", "metadata_only", "manual"], ["discovery", "metadata_only", "manual"]]);
  await fails("promote_candidate", { candidate_id: c.candidate_id, expected_version: v, title: "x", question: "y", categories: ["sake"] },
    "version_conflict");
  // 발견 자료를 근거로 쓰려 하면 A단계 규칙이 막는다(역할 discovery·본문 없음).
  const sc = { relevance: 4, utility: 4, curiosity: 3, fit_video: 3, fit_carousel: 4, timeliness: 2 };
  await ok("triage", { topic_id: t.id, expected_version: t.version, scores: sc });
  await ok("topic_action", { topic_id: t.id, expected_version: (await row("select version from drink_topics where id=$1", [t.id])).version,
    action: "start_research" });
  const snap = (await row("select snapshot_id from drink_topic_sources where topic_id = $1 limit 1", [t.id])).snapshot_id;
  const tv = (await row("select version from drink_topics where id=$1", [t.id])).version;
  const r2 = await act("save_review", { topic_id: t.id, expected_topic_version: tv, scores: sc,
    brief: { audience_question: "q", core_takeaway: "t", selected_claim_ids: ["c1"], proposed_formats: ["video"], required_claims: { video: ["c1"] } },
    evidence_pack: { claims: [{ claim_id: "c1", text: "냉장 1주", claim_type: "process", support_review: "supported",
      source_refs: [{ snapshot_id: snap, original_quote: "fridge" }] }] } });
  assert.notEqual(r2.status, 200, "발견 자료로는 근거를 만들 수 없다");
  assert.ok(["ref_not_evidence", "invalid_pack"].includes(r2.body.code), JSON.stringify(r2.body));
});

test("수동 발견 자료(인스타·레딧 등): 서버는 URL 을 열지 않고 운영자가 쓴 것만 · 같은 URL 은 재사용", async () => {
  const a = await ok("add_discovery", { url: "https://www.instagram.com/p/AbC123/?utm_source=ig_web_copy_link&igsh=xyz",
    platform: "instagram", note: "댓글에 '개봉 후 보관' 질문 다수(직접 확인)", question: "개봉한 사케 며칠까지?" });
  const d = await row("select * from drink_discovery_items where id = $1", [a.discovery_item_id]);
  assert.equal(d.canonical_url, "https://www.instagram.com/p/AbC123/", "추적 파라미터만 지운다");
  assert.equal(d.collection_status, "manual");
  assert.equal(d.coverage, "link_only");
  assert.equal(d.latest_metrics, null, "지표를 지어내지 않는다");
  assert.deepEqual(d.questions, ["개봉한 사케 며칠까지?"]);
  const again = await ok("add_discovery", { url: "https://www.instagram.com/p/AbC123/", platform: "instagram" });
  assert.equal(again.existing, true);
  await fails("add_discovery", { url: "http://192.168.0.1/x", platform: "web" }, "invalid_input");
});

test("후보 기각(사유 필수)·병합(자료 옮김)·다시 열기", async () => {
  const id = await activeSE();
  await ok("request_run", { source_id: id, mode: "collect" });
  const r = await runOnce([q(50), q(51)]);
  const [x, y] = r.items.map((i: Any) => i.discovery_item_id);
  const c1 = (await worker("drinks_suggest_candidate", { item_ids: [x], key_question: "A?" })).candidate_id;
  const c2 = (await worker("drinks_suggest_candidate", { item_ids: [y], key_question: "B?" })).candidate_id;
  const ver = async (cid: string) => (await row("select version from drink_discovery_candidates where id = $1", [cid])).version;
  await fails("candidate_action", { candidate_id: c1, expected_version: await ver(c1), action: "dismiss" }, "invalid_input");
  await ok("candidate_action", { candidate_id: c2, expected_version: await ver(c2), action: "merge", into_candidate_id: c1, reason: "같은 질문" });
  assert.equal((await row("select count(*)::int n from drink_candidate_items where candidate_id = $1", [c1])).n, 2);
  await ok("candidate_action", { candidate_id: c1, expected_version: await ver(c1), action: "dismiss", reason: "근거 자료 없음" });
  await ok("candidate_action", { candidate_id: c1, expected_version: await ver(c1), action: "reopen" });
  assert.equal((await row("select status from drink_discovery_candidates where id = $1", [c1])).status, "suggested");
});

test("권한: 발견 표·함수는 anon 에 닫혀 있고, 자료 기록·후보 묶기는 화면 동작이 아니다", async () => {
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    for (const t of ["drink_discovery_items", "drink_discovery_observations", "drink_discovery_candidates", "drink_candidate_items"]) {
      await assert.rejects(db.query(`select * from ${t}`), /permission denied/, `${role} ${t}`);
    }
    await db.exec("reset role");
  }
  const fns = Object.values(DRINKS_ACTIONS) as string[];
  for (const f of ["drinks_collect_discovery", "drinks_suggest_candidate", "drinks_discovery_backlog"]) assert.ok(!fns.includes(f), f);
});
