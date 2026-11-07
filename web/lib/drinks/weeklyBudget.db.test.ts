// 주간 AI 초안 한도(0073) DB 시험 — PGlite 위에 00(5x|6x|7x)_drinks_*. 모델·네트워크 호출 0.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";

import { runDrinksAction } from "./actions.ts";
import { parseWeeklyBudget } from "./weeklyBudgetModel.ts";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations");
const MIGS = readdirSync(DIR).filter((f) => /^00(5\d|6\d|7\d)_drinks_.*\.sql$/.test(f)).sort();

const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(join(DIR, m), "utf8"));

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
type Any = any;
const rpc = async (fn: string, p: Record<string, unknown> = {}): Promise<Any> => {
  const r = await exec(fn, p);
  if (r.error) throw new Error(r.error.message);
  return r.data;
};

test("주간 한도: 처음 부르면 $5 한 줄, 다시 불러도 같은 줄", async () => {
  const a = parseWeeklyBudget(await rpc("drinks_ensure_weekly_budget"));
  const b = parseWeeklyBudget(await rpc("drinks_ensure_weekly_budget"));
  assert.ok(a && b);
  assert.equal(a.budget_id, b.budget_id);
  assert.equal(a.cap_usd, 5);
  assert.equal(a.remaining_usd, 5);
  assert.equal(a.total_spent_usd, 0);
  assert.match(a.week_start, /^\d{4}-\d{2}-\d{2}$/);
  const n = await db.query<{ n: number }>("select count(*)::int n from drink_develop_budgets where stage like 'weekly:%'");
  assert.equal(n.rows[0].n, 1);
});

test("[한도 +$1]: 화면 동작으로 $1씩 오르고, $10 에서 멈춘다", async () => {
  let last: Any = null;
  for (let i = 0; i < 5; i++) {
    const r = await runDrinksAction(exec, { action: "raise_weekly_budget", payload: { cap_usd: 999 } });   // 보낸 금액은 버려진다
    assert.equal(r.status, 200, JSON.stringify(r.body));
    last = (r.body as Any).result;
  }
  assert.equal(Number(last.cap_usd), 10);
  const over = await runDrinksAction(exec, { action: "raise_weekly_budget", payload: {} });
  assert.notEqual(over.status, 200);
  assert.match(JSON.stringify(over.body), /\$10/);
  const raises = await db.query<{ n: number }>("select count(*)::int n from drink_develop_budget_raises");
  assert.equal(raises.rows[0].n, 5);
});

test("불변 규칙은 그대로: 함수 밖에서 상한을 바꾸거나 내리면 거부", async () => {
  await assert.rejects(db.exec("update drink_develop_budgets set cap_usd = cap_usd + 1 where stage like 'weekly:%'"), /바꿀 수 없습니다/);
  await assert.rejects(db.exec("update drink_develop_budgets set cap_usd = 1 where stage like 'weekly:%'"), /바꿀 수 없습니다/);
  await assert.rejects(db.exec("delete from drink_develop_budget_raises"), /지울 수 없습니다/);
});

test("손으로 여는 결재: 목적(purpose)을 안 보내도 등록된다(옛 화면의 실패 원인)", async () => {
  const r = await runDrinksAction(exec, { action: "open_develop_budget", payload: { stage: "초안", cap_usd: 1, days: 7, approver_words: "승인" } });
  assert.equal(r.status, 200, JSON.stringify(r.body));
});

test("anon 은 새 함수·표에 손대지 못한다", async () => {
  const q = await db.query<{ a: boolean; b: boolean; c: boolean }>(`select
    has_function_privilege('anon', 'drinks_raise_weekly_budget(jsonb)', 'EXECUTE') a,
    has_function_privilege('anon', 'drinks_ensure_weekly_budget(jsonb)', 'EXECUTE') b,
    has_table_privilege('anon', 'drink_develop_budget_raises', 'SELECT') c`);
  assert.deepEqual(q.rows[0], { a: false, b: false, c: false });
});
