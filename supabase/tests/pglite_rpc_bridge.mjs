// 시험용 다리: PGlite(메모리 안 진짜 Postgres)에 주류 마이그레이션을 올리고, Python 워커가 부를 수 있게
// PostgREST 의 rpc 모양(POST /rpc/<함수> {p})으로 연다. tests/test_drinks_loop_e2e.py 가 띄운다.
//
// ★ 127.0.0.1 에만 열린다. 운영 DB·원격과 무관하고, 프로세스가 끝나면 데이터도 사라진다.
// ★ POST /sql 은 시험 전용(시간 되돌리기·가짜 지표 확인). 운영 경로에는 이런 문이 없다.
//
//   node supabase/tests/pglite_rpc_bridge.mjs   → 첫 줄에 "READY <port>" 를 찍는다
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const req = createRequire(join(ROOT, "web", "package.json"));
const { PGlite } = await import(pathToFileURL(req.resolve("@electric-sql/pglite")).href);

const MIGS = ["0050_drinks_factory_phase_a", "0051_drinks_factory_phase_b", "0052_drinks_discovery", "0053_drinks_production",
  "0054_drinks_spend", "0055_drinks_publish_loop"];
const db = new PGlite();
await db.exec(`create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  grant usage on schema public to anon, authenticated, service_role;`);
for (const m of MIGS) await db.exec(readFileSync(join(ROOT, "supabase", "migrations", `${m}.sql`), "utf8"));

// PGlite 는 연결 하나다 — 요청을 한 줄로 세워 role 전환이 섞이지 않게 한다.
let chain = Promise.resolve();
const serial = (fn) => (chain = chain.then(fn, fn));

const send = (res, code, body) => {
  res.writeHead(code, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

const server = createServer((rq, res) => {
  let raw = "";
  rq.on("data", (c) => (raw += c));
  rq.on("end", () => serial(async () => {
    try {
      const body = raw ? JSON.parse(raw) : {};
      const m = /^\/rpc\/([a-z_]+)$/.exec(rq.url ?? "");
      if (rq.method === "POST" && m) {
        try {
          await db.exec("set role service_role");
          const r = await db.query(`select ${m[1]}($1::jsonb) as r`, [JSON.stringify(body.p ?? {})]);
          send(res, 200, { data: r.rows[0].r });
        } catch (e) {
          send(res, 400, { error: { message: e.message, code: e.code ?? null } });
        } finally {
          await db.exec("reset role");
        }
        return;
      }
      if (rq.method === "POST" && rq.url === "/sql") {
        try {
          const r = await db.query(body.sql, body.params ?? []);
          send(res, 200, { rows: r.rows });
        } catch (e) {
          send(res, 400, { error: { message: e.message } });
        }
        return;
      }
      send(res, 404, { error: { message: "not found" } });
    } catch (e) {
      send(res, 500, { error: { message: String(e) } });
    }
  }));
});
server.listen(0, "127.0.0.1", () => console.log(`READY ${server.address().port}`));
