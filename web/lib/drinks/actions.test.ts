// 주류 공장 쓰기 동작 순수 테스트(가짜 rpc 실행기). DB 까지 태우는 테스트는 supabase/tests/drinks_phase_a.test.mjs.
import test from "node:test";
import assert from "node:assert/strict";
import { DRINKS_ACTIONS, PHASE_A_EXCLUDED, mapDbError, normalizeUrl, runDrinksAction, type RpcExec } from "./actions.ts";

function recorder(result: { data?: unknown; error?: { message: string; details?: string; code?: string } } = {}) {
  const calls: { fn: string; p: Record<string, unknown> }[] = [];
  const exec: RpcExec = async (fn, p) => {
    calls.push({ fn, p });
    return { data: result.data ?? { ok: 1 }, error: result.error ?? null };
  };
  return { exec, calls };
}

test("URL 정규화: 추적 파라미터·조각만 지우고 식별자는 남긴다", () => {
  assert.deepEqual(normalizeUrl("https://Example.COM/p?id=3&utm_source=ig&fbclid=x#a"), { ok: true, url: "https://example.com/p?id=3" });
  assert.deepEqual(normalizeUrl("https://example.com/p?utm_medium=x"), { ok: true, url: "https://example.com/p" });
  assert.deepEqual(normalizeUrl("https://shop.kr/item?vintage=2019&lot=A"), { ok: true, url: "https://shop.kr/item?vintage=2019&lot=A" });
});

test("URL 정규화: http(s) 아닌 주소·내부망·계정 포함 URL 거부", () => {
  for (const bad of ["ftp://x.com/a", "javascript:alert(1)", "http://localhost:3000/x", "http://10.0.0.1/", "http://192.168.1.5",
    "http://169.254.169.254/latest", "http://[::1]/", "https://user:pw@x.com/", "not a url"]) {
    assert.equal(normalizeUrl(bad).ok, false, bad);
  }
  assert.equal(normalizeUrl("https://fd-sake.com/a").ok, true, "fd 로 시작하는 일반 도메인은 통과");
});

test("제외 기능은 rpc 를 부르지 않고 403 not_in_phase_a", async () => {
  const { exec, calls } = recorder();
  for (const a of PHASE_A_EXCLUDED) {
    const r = await runDrinksAction(exec, { action: a, payload: {} });
    assert.equal(r.status, 403);
    assert.equal(r.body.code, "not_in_phase_a");
  }
  assert.equal(calls.length, 0);
  for (const a of PHASE_A_EXCLUDED) assert.ok(!(a in DRINKS_ACTIONS), `${a} 가 허용 목록에도 있다`);
});

test("허용 목록 밖·잘못된 본문은 rpc 전에 거부", async () => {
  const { exec, calls } = recorder();
  assert.equal((await runDrinksAction(exec, null)).status, 400);
  assert.equal((await runDrinksAction(exec, { action: "toString" })).body.code, "unknown_action");
  assert.equal((await runDrinksAction(exec, { action: "add_source", payload: { topic_id: "x" } })).status, 400);
  assert.equal(calls.length, 0);
});

test("출처 URL 은 서버에서 정규화하고, 클라이언트가 보낸 해시·대조 결과는 버린다", async () => {
  const { exec, calls } = recorder();
  const r = await runDrinksAction(exec, {
    action: "add_source",
    payload: { topic_id: "t", source: { url: " https://x.com/a?utm_source=1 ", content_hash: "fake", quote_check: "matched", body_text: "b" } },
  });
  assert.equal(r.status, 200);
  assert.equal(calls[0].fn, "drinks_add_source");
  const src = calls[0].p.source as Record<string, unknown>;
  assert.equal(src.canonical_url, "https://x.com/a");
  assert.equal(src.url_raw, "https://x.com/a?utm_source=1");
  assert.ok(!("content_hash" in src) && !("quote_check" in src) && !("url" in src));
  const blocked = await runDrinksAction(exec, { action: "create_topic", payload: { source: { url: "http://127.0.0.1/" } } });
  assert.equal(blocked.status, 400);
  assert.equal(calls.length, 1);
});

test("DB 오류 → HTTP: 코드별 상태와 한국어 문장, detail JSON 해석", () => {
  const e = mapDbError({ message: "drinks:review_blocked:필수 조건을 채우지 못해 승인할 수 없습니다", details: '["claim_metadata_only:c1"]' });
  assert.equal(e.status, 422);
  assert.equal(e.body.code, "review_blocked");
  assert.deepEqual(e.body.detail, ["claim_metadata_only:c1"]);
  assert.equal(mapDbError({ message: "drinks:version_conflict:x" }).status, 409);
  assert.equal(mapDbError({ message: "drinks:ownership:x" }).status, 403);
  assert.equal(mapDbError({ message: "dup", code: "23505" }).status, 409);
  assert.equal(mapDbError({ message: "Could not find the function", code: "PGRST202" }).body.code, "schema_missing");
  assert.equal(mapDbError({ message: "weird" }).status, 500);
});
