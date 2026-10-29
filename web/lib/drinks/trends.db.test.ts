// 주류 동향(0059) DB 통합 테스트 — PGlite 위에 0050~0056·0058·0059.
// 기록 함수(글·언급·판정 대기), 글×제품 유일성, 집계 보기(7일·긍정/부정 문턱), 이슈 보기(14일), 공개 역할 차단.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

const MIGS = ["0050_drinks_factory_phase_a.sql", "0051_drinks_factory_phase_b.sql", "0052_drinks_discovery.sql",
  "0053_drinks_production.sql", "0054_drinks_spend.sql", "0055_drinks_publish_loop.sql", "0056_drinks_function_search_path.sql",
  "0058_drinks_topic_signals.sql", "0059_drinks_trends.sql"]
  .map((f) => join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations", f));
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
const fails = async (fn: string, p: Record<string, unknown>, re: RegExp) => {
  await assert.rejects(() => call(fn, p), re);
};
const asService = async (sql: string): Promise<Any[]> => {
  try {
    await db.exec("set role service_role");
    return (await db.query(sql)).rows;
  } finally {
    await db.exec("reset role");
  }
};
const uniq = () => Math.random().toString(36).slice(2);
const daysAgo = (n: number) => new Date(Date.now() - n * 86400_000).toISOString();

async function post(over: Record<string, unknown> = {}): Promise<Any> {
  return call("drinks_trends_record_post", { kind: "community", platform: "naver_cafe", canonical_url: `https://cafe.naver.com/x/${uniq()}`,
    channel_name: "위스키 코냑 클럽", title: "발베니 12 후기", summary: "발베니가 부드럽다", posted_at: daysAgo(1), query: "위스키", ...over });
}
const mention = (post_id: string, product: string, over: Record<string, unknown> = {}) =>
  call("drinks_trends_record_mention", { post_id, product, category: "whisky", ...over });

test("글 기록: 같은 주소는 한 건 — 두 번째는 created=false, 처음 모은 시각은 그대로", async () => {
  const url = `https://cafe.naver.com/x/${uniq()}`;
  const a = await post({ canonical_url: url });
  assert.equal(a.created, true);
  const t0 = (await asService(`select collected_at from drink_trend_posts where id='${a.post_id}'`))[0].collected_at;
  const b = await post({ canonical_url: url, title: "발베니 12 후기(수정)" });
  assert.equal(b.created, false);
  assert.equal(b.post_id, a.post_id);
  const r = (await asService(`select title, collected_at from drink_trend_posts where id='${a.post_id}'`))[0];
  assert.equal(r.title, "발베니 12 후기(수정)");
  assert.equal(new Date(r.collected_at).getTime(), new Date(t0).getTime());
});

test("글 기록: 잘못된 값은 거절한다", async () => {
  await fails("drinks_trends_record_post", { kind: "blog", platform: "naver_cafe", canonical_url: "https://a.b/c", title: "t" }, /invalid_input/);
  await fails("drinks_trends_record_post", { kind: "issue", platform: "twitter", canonical_url: "https://a.b/c", title: "t" }, /invalid_input/);
  await fails("drinks_trends_record_post", { kind: "issue", platform: "naver_news", canonical_url: "ftp://a.b/c", title: "t" }, /invalid_input/);
  await fails("drinks_trends_record_post", { kind: "issue", platform: "naver_news", canonical_url: "https://a.b/c", title: "" }, /invalid_input/);
  await fails("drinks_trends_record_post", { kind: "issue", platform: "naver_news", canonical_url: "https://a.b/c", title: "t", posted_at: "어제" }, /invalid_input/);
});

test("언급: (글, 제품) 유일 — 반복 기록은 새 행을 만들지 않고, 판정 없는 채로 시작한다", async () => {
  const p = await post();
  const m1 = await mention(p.post_id, "발베니");
  assert.equal(m1.created, true);
  assert.equal(m1.judged, false);
  const m2 = await mention(p.post_id, "발베니");
  assert.equal(m2.created, false);
  assert.equal(m2.mention_id, m1.mention_id);
  assert.equal((await asService(`select count(*)::int n from drink_trend_mentions where post_id='${p.post_id}'`))[0].n, 1);
  const row = (await asService(`select sentiment, jev_p, judged_at from drink_trend_mentions where id='${m1.mention_id}'`))[0];
  assert.equal(row.sentiment, null);
  assert.equal(row.judged_at, null);
});

test("판정 기록: null 이던 언급에만 채우고, 이미 판정된 값은 덮지 않는다", async () => {
  const p = await post();
  const m = await mention(p.post_id, "맥캘란");
  const j = await mention(p.post_id, "맥캘란", { sentiment: 0.6, jev_p: 0.8 });
  assert.equal(j.judged, true);
  assert.equal(j.mention_id, m.mention_id);
  const again = await mention(p.post_id, "맥캘란", { sentiment: -0.9, jev_p: 0.05 });
  assert.equal(again.judged, true);
  const row = (await asService(`select sentiment::float s, jev_p::float j, judged_at from drink_trend_mentions where id='${m.mention_id}'`))[0];
  assert.equal(row.s, 0.6);
  assert.equal(row.j, 0.8);
  assert.ok(row.judged_at);
});

test("언급: 범위·주종·없는 글을 거절한다", async () => {
  const p = await post();
  await fails("drinks_trends_record_mention", { post_id: p.post_id, product: "x", category: "beer" }, /invalid_input/);
  await fails("drinks_trends_record_mention", { post_id: p.post_id, product: "x", category: "sake", sentiment: 1.5, jev_p: 1 }, /invalid_input/);
  await fails("drinks_trends_record_mention", { post_id: p.post_id, product: "x", category: "sake", sentiment: 0.1, jev_p: 2 }, /invalid_input/);
  await fails("drinks_trends_record_mention", { post_id: "00000000-0000-0000-0000-000000000000", product: "x", category: "sake" }, /not_found/);
  await fails("drinks_trends_record_mention", { post_id: "not-a-uuid", product: "x", category: "sake" }, /invalid_input/);
});

test("판정 대기: 판정 없는 커뮤니티 언급만, 판정되면 빠진다", async () => {
  const prod = `대기${uniq()}`;
  const p = await post();
  const m = await mention(p.post_id, prod);
  let pend: Any[] = await call("drinks_trends_pending_mentions", { limit: 1000 });
  const hit = pend.find((x) => x.mention_id === m.mention_id);
  assert.ok(hit);
  assert.equal(hit.product, prod);
  assert.equal(hit.title, "발베니 12 후기");
  await mention(p.post_id, prod, { sentiment: 0.2, jev_p: 0.6 });
  pend = await call("drinks_trends_pending_mentions", { limit: 1000 });
  assert.equal(pend.find((x) => x.mention_id === m.mention_id), undefined);
  // 한도
  const q = await post();
  await mention(q.post_id, `a${uniq()}`);
  await mention(q.post_id, `b${uniq()}`);
  assert.ok((await call("drinks_trends_pending_mentions", { limit: 1 })).length <= 1);
});

test("집계 보기: 7일 안 글만, 긍정·부정 문턱(0.2), 판정 없음은 평균에서 빠진다, 예시 글 3개까지", async () => {
  const prod = `집계${uniq()}`;
  const mk = async (sent: number | null, ago = 1) => {
    const p = await post({ posted_at: daysAgo(ago), title: `글 ${uniq()}` });
    await mention(p.post_id, prod, sent === null ? {} : { sentiment: sent, jev_p: (sent + 1) / 2 });
    return p;
  };
  await mk(0.8);
  await mk(0.2); // 문턱 경계 - 긍정이 아니다(> 0.2)
  await mk(-0.5);
  await mk(null);
  await mk(0.9, 10); // 7일 밖 - 제외
  const [r] = await asService(`select * from drink_trend_products where product='${prod}'`);
  assert.equal(Number(r.posts), 4);
  assert.equal(Number(r.mentions), 4);
  assert.equal(Number(r.judged), 3);
  assert.equal(Number(r.positive), 1);
  assert.equal(Number(r.negative), 1);
  assert.equal(Number(r.avg_sentiment), 0.17); // (0.8+0.2-0.5)/3 = 0.1667
  assert.equal(r.category, "whisky");
  assert.equal(r.sample_urls.length, 3);
  assert.equal(r.sample_titles.length, 3);
  assert.ok(new Date(r.last_seen).getTime() > Date.now() - 3 * 86400_000);
});

test("집계 보기: 판정이 하나도 없으면 평균은 null('판정 없음'), 이슈 글은 제품 집계에 들지 않는다", async () => {
  const prod = `무판정${uniq()}`;
  const p = await post();
  await mention(p.post_id, prod);
  const [r] = await asService(`select * from drink_trend_products where product='${prod}'`);
  assert.equal(r.avg_sentiment, null);
  assert.equal(Number(r.judged), 0);
  const iss = await post({ kind: "issue", platform: "naver_news", channel_name: "연합뉴스" });
  await mention(iss.post_id, prod);
  const [r2] = await asService(`select * from drink_trend_products where product='${prod}'`);
  assert.equal(Number(r2.posts), 1);
});

test("이슈 보기: 최근 14일 이슈 기사만", async () => {
  const fresh = await post({ kind: "issue", platform: "naver_news", title: `주세 개정 ${uniq()}`, posted_at: daysAgo(5) });
  const old = await post({ kind: "issue", platform: "naver_news", title: `옛 이슈 ${uniq()}`, posted_at: daysAgo(20) });
  const com = await post({ title: `커뮤니티 ${uniq()}` });
  const rows = await asService(`select id from drink_trend_issues`);
  const ids = new Set(rows.map((r) => r.id));
  assert.ok(ids.has(fresh.post_id));
  assert.ok(!ids.has(old.post_id));
  assert.ok(!ids.has(com.post_id));
});

test("공개 역할은 표·보기·함수 어디에도 접근하지 못한다", async () => {
  for (const role of ["anon", "authenticated"]) {
    for (const rel of ["drink_trend_posts", "drink_trend_mentions", "drink_trend_products", "drink_trend_issues"]) {
      await db.exec(`set role ${role}`);
      try {
        await assert.rejects(() => db.query(`select * from ${rel}`), /permission denied/, `${role} 가 ${rel} 를 읽으면 안 된다`);
        await assert.rejects(() => db.query(`insert into drink_trend_posts (kind,platform,canonical_url,title) values ('issue','naver_news','https://a.b/${uniq()}','t')`), /permission denied/);
      } finally {
        await db.exec("reset role");
      }
    }
    for (const fn of ["drinks_trends_record_post", "drinks_trends_record_mention", "drinks_trends_pending_mentions"]) {
      await db.exec(`set role ${role}`);
      try {
        await assert.rejects(() => db.query(`select ${fn}('{}'::jsonb)`), /permission denied/, `${role} 가 ${fn} 를 실행하면 안 된다`);
      } finally {
        await db.exec("reset role");
      }
    }
  }
});

test("함수 검색 경로가 고정돼 있다(0056 규칙)", async () => {
  const rows = (await db.query<{ proname: string; proconfig: string[] | null }>(
    `select proname, proconfig from pg_proc where proname like 'drinks\\_trends\\_%'`)).rows;
  assert.equal(rows.length, 3);
  for (const r of rows) assert.ok((r.proconfig ?? []).some((c) => c.startsWith("search_path=")), `${r.proname} 검색 경로 미고정`);
});
