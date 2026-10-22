// 조회 잘림 재현 — 서버 행 상한(1000·500)과 일부 요청 실패를 가짜 PostgREST 로 흉내 낸다.
import test from "node:test";
import assert from "node:assert/strict";
import { fetchAllIn, fetchAllPages, missingIds, type PageResponse } from "./paging.ts";

/** max_rows 로 자르는 가짜 서버. count 는 실제 전체 건수(Prefer: count=exact). */
function server<T>(rows: T[], maxRows: number, opts: { failAt?: number; noCount?: boolean } = {}) {
  let calls = 0;
  return {
    get calls() { return calls; },
    page: async (from: number, to: number): Promise<PageResponse<T>> => {
      calls += 1;
      if (opts.failAt === calls) return { data: null, error: { message: "fetch failed" } };
      const end = Math.min(to + 1, from + maxRows);
      return { data: rows.slice(from, end), error: null, count: opts.noCount ? null : rows.length };
    },
  };
}
const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `r${i}` }));

test("응답 상한(1000)을 넘는 2,500행을 끝까지 읽는다", async () => {
  const s = server(rows(2500), 1000);
  const r = await fetchAllPages(s.page, "제작안");
  assert.ok(r.ok);
  assert.equal(r.ok && r.rows.length, 2500);
  assert.equal(s.calls, 3);
});

test("서버 상한이 요청 쪽 크기보다 작아도(500) 전체 건수로 판정해 놓치지 않는다", async () => {
  const s = server(rows(1200), 500);
  const r = await fetchAllPages(s.page, "근거");
  assert.ok(r.ok && r.rows.length === 1200);
});

test("중간 쪽 실패·전체 건수 없음은 실패 — 받은 만큼을 정상 목록으로 내보내지 않는다", async () => {
  const r1 = await fetchAllPages(server(rows(2500), 1000, { failAt: 2 }).page, "제작안");
  assert.equal(r1.ok, false);
  assert.match(!r1.ok ? r1.error : "", /제작안: fetch failed/);
  const r2 = await fetchAllPages(server(rows(10), 1000, { noCount: true }).page, "출처");
  assert.equal(r2.ok, false);
});

test("id 청크(150) × 행 페이징: 한 청크가 1000행을 넘어도 전부 읽고, 한 청크 실패는 전체 실패", async () => {
  const ids = Array.from({ length: 400 }, (_, i) => `t${i}`);
  const chunks: number[] = [];
  const ok = await fetchAllIn(ids, async (c, from, to) => {
    if (from === 0) chunks.push(c.length);
    const all = c.flatMap((t) => Array.from({ length: 8 }, (_, k) => ({ id: `${t}-${k}` }))); // 150×8 = 1200
    return { data: all.slice(from, Math.min(to + 1, from + 1000)), error: null, count: all.length };
  }, "연결");
  assert.deepEqual(chunks, [150, 150, 100]);
  assert.equal(ok.ok && ok.rows.length, 3200);
  let n = 0;
  const bad = await fetchAllIn(ids, async () => {
    n += 1;
    return n === 2 ? { data: null, error: { message: "boom" } } : { data: [], error: null, count: 0 };
  }, "연결");
  assert.equal(bad.ok, false);
});

test("포인터 누락 감지: 가리키는 id 가 결과에 없으면 누락으로 센다", () => {
  assert.deepEqual(missingIds(["a", null, "b", "a"], ["a"]), ["b"]);
  assert.deepEqual(missingIds([null, undefined], []), []);
});
