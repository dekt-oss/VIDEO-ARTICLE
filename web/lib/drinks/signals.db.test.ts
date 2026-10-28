// 주류 질문 신호(0058) DB 통합 테스트 — PGlite 위에 0050~0056·0058.
// 후보 -> 소재 복사(질문 유형·발견 채널·관심 신호), 수동 등록의 question_kind, 수집원 lookback_days.
// 전략 쪽(입력·제안·가점)은 publish.db.test.ts 에서 같은 마이그레이션 묶음으로 본다.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql", "0054_drinks_spend.sql", "0055_drinks_publish_loop.sql", "0056_drinks_function_search_path.sql",
  "0058_drinks_topic_signals.sql"]
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
const ver = async (table: string, id: string) => (await row(`select version from ${table} where id = $1`, [id])).version;
const SE = "https://alcohol.stackexchange.com/questions";

/** 활성 발견 수집원(실행·검증 절차는 discovery.db.test.ts 와 같다)에서 자료 n건을 받아 후보 하나로 묶는다. */
async function candidateWith(signals: string[], interest: Record<string, unknown> | null) {
  const r = await ok("register_discovery_source", { platform: "stackexchange", name: `SE ${uniq()}`, categories: ["sake"],
    queries: ["sake", uniq()] });
  const id = r.source_id as string;
  const item = (n: number) => ({ status: "fetched", platform: "stackexchange", canonical_url: `${SE}/${uniq()}/${n}`,
    title: `How long does opened sake last ${n}?`, summary: "fridge?", channel_name: "SE", coverage: "title_summary",
    questions: ["How long?"], signals, metrics: { views: 10 } });
  const runOnce = async (items: Record<string, unknown>[]) => {
    const got = await worker("drinks_start_run", { worker_id: "t" });
    const lease = { run_id: got.run.run_id, lease_token: got.run.lease_token };
    const out = [];
    for (const it of items) out.push(await worker("drinks_collect_discovery", { ...lease, item: it }));
    await worker("drinks_finish_run", lease);
    return out;
  };
  await ok("request_run", { source_id: id, mode: "validate" });
  await runOnce([item(0)]);
  const sv = async () => (await row("select version from drink_sources where id = $1", [id])).version;
  await ok("source_action", { source_id: id, expected_version: await sv(), action: "validate" });
  await ok("source_action", { source_id: id, expected_version: await sv(), action: "update_terms", terms_status: "verified",
    terms_note: "CC BY-SA 4.0", terms_checked_at: "2026-10-22" });
  await ok("source_action", { source_id: id, expected_version: await sv(), action: "activate" });
  await ok("request_run", { source_id: id, mode: "collect" });
  const items = await runOnce([item(1), item(2)]);
  const c = await worker("drinks_suggest_candidate", { item_ids: items.map((x: Any) => x.discovery_item_id), key_question: "How long does opened sake last?",
    signals, ...(interest ? { interest } : {}) });
  return { candidateId: c.candidate_id as string };
}

test("후보 -> 소재: 질문 유형(보관>오해>논쟁>선택 우선순위)·발견 채널·관심 신호가 소재에 복사된다", async () => {
  const interest = { independent_sources: 2, items: 2, by_platform: { stackexchange: { views: 20 } } };
  const { candidateId } = await candidateWith(["question", "selection", "storage"], interest);
  const p = await ok("promote_candidate", { candidate_id: candidateId, expected_version: await ver("drink_discovery_candidates", candidateId),
    title: "개봉한 사케 보관", question: "개봉한 사케는 냉장고에서 얼마나 갈까?", categories: ["sake"] });
  const t = await row("select * from drink_topics where id = $1", [p.topic_id]);
  assert.equal(t.question_kind, "storage", "storage 와 selection 이 겹치면 storage");
  assert.deepEqual(t.discovery_platforms, ["stackexchange"]);
  assert.deepEqual(t.interest, interest);
  assert.equal(t.version, 1, "복사는 소재 생성과 같은 쓰기라 버전이 오르지 않는다");
  assert.equal(t.lane, "reader_question");
});

test("후보 -> 소재: 운영자가 고른 질문 유형이 신호보다 우선 · 신호가 없으면 general · 잘못된 값은 거부", async () => {
  const a = await candidateWith(["debate", "selection"], null);
  const pa = await ok("promote_candidate", { candidate_id: a.candidateId, expected_version: await ver("drink_discovery_candidates", a.candidateId),
    title: "논쟁", question: `논쟁 질문 ${uniq()}`, categories: ["whisky"], question_kind: "howto" });
  const ta = await row("select question_kind, interest from drink_topics where id = $1", [pa.topic_id]);
  assert.equal(ta.question_kind, "howto");
  assert.equal(ta.interest, null, "관심 신호가 없으면 비워 둔다 - 빈 객체를 만들지 않는다");

  const b = await candidateWith(["debate", "selection"], null);
  const pb = await ok("promote_candidate", { candidate_id: b.candidateId, expected_version: await ver("drink_discovery_candidates", b.candidateId),
    title: "논쟁2", question: `논쟁 질문 ${uniq()}`, categories: ["whisky"] });
  assert.equal((await row("select question_kind from drink_topics where id = $1", [pb.topic_id])).question_kind, "debate");

  const c = await candidateWith(["new_product", "event"], null);
  await fails("promote_candidate", { candidate_id: c.candidateId, expected_version: await ver("drink_discovery_candidates", c.candidateId),
    title: "x", question: "y", categories: ["sake"], question_kind: "mood" }, "invalid_input");
  const pc = await ok("promote_candidate", { candidate_id: c.candidateId, expected_version: await ver("drink_discovery_candidates", c.candidateId),
    title: "신제품", question: `신제품 질문 ${uniq()}`, categories: ["sake"] });
  assert.equal((await row("select question_kind from drink_topics where id = $1", [pc.topic_id])).question_kind, "general",
    "질문 유형 목록에 없는 신호(신제품·행사)는 general");
});

test("후보를 기존 소재에 붙일 때: 채널은 합치고, 질문 유형은 general 일 때만 채우고, 사람이 정한 값은 덮지 않는다", async () => {
  const mk = await ok("create_topic", { title: "기존", question: `기존 소재 ${uniq()}`, categories: ["sake"], lane: "evergreen" });
  assert.equal((await row("select question_kind from drink_topics where id = $1", [mk.topic_id])).question_kind, "general", "기본값 general");
  const a = await candidateWith(["misconception"], { independent_sources: 1 });
  await ok("promote_candidate", { candidate_id: a.candidateId, expected_version: await ver("drink_discovery_candidates", a.candidateId), topic_id: mk.topic_id });
  const t1 = await row("select * from drink_topics where id = $1", [mk.topic_id]);
  assert.equal(t1.question_kind, "misconception", "general 이던 소재는 후보 신호로 채운다");
  assert.deepEqual(t1.discovery_platforms, ["stackexchange"]);
  assert.deepEqual(t1.interest, { independent_sources: 1 });
  const b = await candidateWith(["storage"], { independent_sources: 9 });
  await ok("promote_candidate", { candidate_id: b.candidateId, expected_version: await ver("drink_discovery_candidates", b.candidateId), topic_id: mk.topic_id });
  const t2 = await row("select * from drink_topics where id = $1", [mk.topic_id]);
  assert.equal(t2.question_kind, "misconception", "이미 정해진 질문 유형은 덮지 않는다");
  assert.deepEqual(t2.interest, { independent_sources: 1 }, "이미 있는 관심 신호도 덮지 않는다");
  assert.equal(t2.version, t1.version, "바뀔 것이 없으면 소재 버전을 올리지 않는다");
});

test("수동 소재 등록: question_kind 를 저장하고(기본 general), 목록 밖 값은 거부 · 발견 채널·관심 신호는 형식을 검사한다", async () => {
  const t = await ok("create_topic", { title: "보관", question: `보관 질문 ${uniq()}`, categories: ["traditional"], lane: "evergreen", question_kind: "storage" });
  assert.equal((await row("select question_kind from drink_topics where id = $1", [t.topic_id])).question_kind, "storage");
  const d = await ok("create_topic", { title: "기본", question: `기본 질문 ${uniq()}`, categories: ["traditional"], lane: "evergreen" });
  assert.equal((await row("select question_kind, discovery_platforms, interest from drink_topics where id = $1", [d.topic_id])).question_kind, "general");
  await fails("create_topic", { title: "x", question: `q ${uniq()}`, categories: ["sake"], lane: "evergreen", question_kind: "mood" }, "invalid_input");
  await fails("create_topic", { title: "x", question: `q ${uniq()}`, categories: ["sake"], lane: "evergreen", discovery_platforms: ["tiktok"] }, "invalid_input");
  await assert.rejects(db.query("update drink_topics set question_kind = 'mood' where id = $1", [t.topic_id]), /question_kind_ck/);
  // 질문 유형 일곱 개가 모두 저장된다
  for (const k of ["storage", "misconception", "selection", "debate", "pairing", "howto", "general"]) {
    const x = await ok("create_topic", { title: k, question: `${k} ${uniq()}`, categories: ["whisky"], lane: "evergreen", question_kind: k });
    assert.equal((await row("select question_kind from drink_topics where id = $1", [x.topic_id])).question_kind, k);
  }
});

test("발견 수집원 등록: lookback_days(1~3650 정수)는 parser_config 로 들어가고, 범위 밖·소수는 거부, 없으면 칸 자체가 없다", async () => {
  const a = await ok("register_discovery_source", { platform: "stackexchange", name: `SE ${uniq()}`, categories: ["sake"], queries: [uniq()], lookback_days: 3000 });
  const sa = await row("select parser_config from drink_sources where id = $1", [a.source_id]);
  assert.equal(sa.parser_config.lookback_days, 3000);
  assert.ok(Array.isArray(sa.parser_config.queries));
  const b = await ok("register_discovery_source", { platform: "stackexchange", name: `SE ${uniq()}`, categories: ["sake"], queries: [uniq()] });
  assert.ok(!("lookback_days" in (await row("select parser_config from drink_sources where id = $1", [b.source_id])).parser_config));
  for (const bad of [0, -1, 3651, 12.5, "abc"]) {
    await fails("register_discovery_source", { platform: "stackexchange", name: "x", categories: ["sake"], queries: [uniq()], lookback_days: bad }, "invalid_input");
  }
  const c = await ok("register_discovery_source", { platform: "stackexchange", name: `SE ${uniq()}`, categories: ["sake"], queries: [uniq()], lookback_days: 3650 });
  assert.equal((await row("select parser_config from drink_sources where id = $1", [c.source_id])).parser_config.lookback_days, 3650);
});
