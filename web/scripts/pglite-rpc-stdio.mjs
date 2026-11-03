// 시험 전용 — 메모리 PGlite 에 주류 마이그레이션(0050~)을 올리고 표준 입출력으로 RPC 를 받는다. 파일·네트워크를 쓰지 않는다.
// 파이썬 워커(engine/drinks_explainer_queue.py)를 진짜 SQL 함수에 물려 돌리려고 있다: scripts/explainer_queue_rehearsal.py, tests/test_drinks_explainer_queue.py.
//   입력 한 줄: {"id":1,"fn":"drinks_x","p":{...}}  또는 {"id":2,"sql":"select ...","params":[...]}
//   출력 한 줄: {"id":1,"data":...}  또는 {"id":1,"error":"..."}
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

import { PGlite } from "@electric-sql/pglite";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../../supabase/migrations");
const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of readdirSync(DIR).filter((f) => /^00(5\d|6\d)_drinks_.*\.sql$/.test(f)).sort()) await db.exec(readFileSync(join(DIR, m), "utf8"));
process.stdout.write(JSON.stringify({ ready: true }) + "\n");

// 줄은 순서대로 하나씩 처리한다(워커는 동기 호출이다).
for await (const line of createInterface({ input: process.stdin })) {
  if (!line.trim()) continue;
  const req = JSON.parse(line);
  let out;
  try {
    if (req.sql) {
      out = { id: req.id, data: (await db.query(req.sql, req.params ?? [])).rows };
    } else {
      await db.exec("set role service_role");
      const res = await db.query(`select ${req.fn}($1::jsonb) as r`, [JSON.stringify(req.p ?? {})]);
      out = { id: req.id, data: res.rows[0].r };
    }
  } catch (e) {
    out = { id: req.id, error: String(e.message ?? e) };
  } finally {
    if (!req.sql) await db.exec("reset role");
  }
  process.stdout.write(JSON.stringify(out) + "\n");
}
