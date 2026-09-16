// 순수 로직 테스트. 실행: `node --test web/lib/supabase/chunked.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { chunk, selectIn, selectAll, IN_CHUNK_SIZE, PAGE_SIZE, MAX_PAGES } from "./chunked.ts";

const id = (n: number) => `id-${String(n).padStart(4, "0")}`;
const ids = (n: number) => Array.from({ length: n }, (_, i) => id(i));

test("chunk: 경계·나머지·빈 배열", () => {
  assert.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepEqual(chunk([1, 2], 2), [[1, 2]]);
  assert.deepEqual(chunk([], 3), []);
  // size 가 0 이하면 무한루프가 된다 — 1 로 올려 막는다.
  assert.equal(chunk([1, 2, 3], 0).length, 3);
});

test("selectIn: 청크 크기를 넘지 않는다(헤더 오버플로의 직접 원인)", async () => {
  const seen: number[] = [];
  const rows = await selectIn(
    ids(478),
    (c) => {
      seen.push(c.length);
      return Promise.resolve({ data: c.map((x) => ({ id: x })), error: null });
    },
    "test",
  );
  assert.equal(rows.length, 478);
  assert.ok(Math.max(...seen) <= IN_CHUNK_SIZE, `청크 최대 ${Math.max(...seen)}`);
  assert.equal(seen.length, Math.ceil(478 / IN_CHUNK_SIZE));
});

test("selectIn: 실측 임계치(400개)보다 작은 청크로 쪼갠다", () => {
  // 실측: 350개 성공 / 400개 HEADERS_OVERFLOW. 기본값이 그 사이로 올라오면 회귀다.
  assert.ok(IN_CHUNK_SIZE <= 300, `IN_CHUNK_SIZE=${IN_CHUNK_SIZE} 는 실측 임계치에 너무 가깝다`);
});

test("selectIn: id 가 없으면 조회하지 않는다", async () => {
  let called = 0;
  const rows = await selectIn([], () => { called += 1; return Promise.resolve({ data: [], error: null }); }, "test");
  assert.deepEqual(rows, []);
  assert.equal(called, 0);
});

test("selectIn: 중복 id 는 접는다", async () => {
  const seen: string[][] = [];
  await selectIn(["a", "a", "b", ""], (c) => { seen.push(c); return Promise.resolve({ data: [], error: null }); }, "test");
  assert.deepEqual(seen, [["a", "b"]]);
});

test("selectIn: 청크 하나가 죽어도 나머지는 살린다(전멸 금지)", async () => {
  const rows = await selectIn(
    ids(300),
    (c) => c.includes(id(0))
      ? Promise.resolve({ data: null, error: { message: "boom" } })
      : Promise.resolve({ data: c.map((x) => ({ id: x })), error: null }),
    "test",
  );
  // 첫 청크만 실패 → 나머지는 그대로 온다.
  assert.equal(rows.length, 300 - IN_CHUNK_SIZE);
});

test("selectIn: fetch 자체가 던져도 페이지를 죽이지 않는다", async () => {
  const rows = await selectIn(ids(10), () => { throw new Error("HeadersOverflowError"); }, "test");
  assert.deepEqual(rows, []);
});

test("selectAll: 1,000행 상한을 넘겨 전부 읽는다", async () => {
  const total = 4447;
  const calls: [number, number][] = [];
  const rows = await selectAll((from, to) => {
    calls.push([from, to]);
    const slice = Array.from({ length: Math.max(0, Math.min(to, total - 1) - from + 1) },
      (_, i) => ({ id: id(from + i) }));
    return Promise.resolve({ data: slice, error: null });
  }, "test");
  assert.equal(rows.length, total);
  assert.equal(calls[0][0], 0);
  assert.equal(calls[0][1], PAGE_SIZE - 1);
  assert.equal(calls.length, Math.ceil(total / PAGE_SIZE));
});

test("selectAll: 마지막 페이지가 꽉 차면 한 번 더 확인한다", async () => {
  const total = PAGE_SIZE; // 정확히 한 페이지
  let calls = 0;
  const rows = await selectAll((from, to) => {
    calls += 1;
    const slice = Array.from({ length: Math.max(0, Math.min(to, total - 1) - from + 1) },
      (_, i) => ({ id: id(from + i) }));
    return Promise.resolve({ data: slice, error: null });
  }, "test");
  assert.equal(rows.length, total);
  assert.equal(calls, 2, "꽉 찬 페이지 뒤에 빈 페이지를 한 번 더 확인해야 잘림을 피한다");
});

test("selectAll: 폭주 상한에서 멈춘다", async () => {
  let calls = 0;
  const rows = await selectAll((from, to) => {
    calls += 1;
    return Promise.resolve({
      data: Array.from({ length: to - from + 1 }, (_, i) => ({ id: id(from + i) })),
      error: null,
    });
  }, "test");
  assert.equal(calls, MAX_PAGES);
  assert.equal(rows.length, MAX_PAGES * PAGE_SIZE);
});

test("selectAll: 중간에 실패하면 거기까지만 돌려준다(빈 배열로 뭉개지 않는다)", async () => {
  const rows = await selectAll((from, to) => {
    if (from > 0) return Promise.resolve({ data: null, error: { message: "boom" } });
    return Promise.resolve({
      data: Array.from({ length: to - from + 1 }, (_, i) => ({ id: id(i) })),
      error: null,
    });
  }, "test");
  assert.equal(rows.length, PAGE_SIZE);
});
