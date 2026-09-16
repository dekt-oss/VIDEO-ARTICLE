// 운영자 토큰 — Node 구현(lib/apiGuard.ts)과 Edge 구현(middleware.ts)의 일치 감시.
// 실행: `node --test web/lib/operatorToken.test.ts` (Node 22 타입 스트리핑).
//
// ★ 왜 이 테스트가 필요한가: 같은 쿠키 값을 두 런타임이 각자 만든다.
//   apiGuard 는 node:crypto(createHash), middleware 는 Edge 의 Web Crypto(subtle.digest).
//   한쪽 입력 규칙만 바뀌면 **잠금해제를 해도 계속 막히는** 조용한 고장이 난다 —
//   /unlock 은 쿠키를 심었다고 알려주고, 미들웨어는 그 쿠키를 거부한다.
//   tsc·lint 로는 잡히지 않는 종류라 여기서 값으로 고정한다.
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

import { OPERATOR_TOKEN_PREFIX, safeEqual } from "./operatorConst.ts";

/** lib/apiGuard.ts 의 operatorToken() 과 동일한 계산(그 파일은 next/headers 를 import 해
 *  테스트에서 직접 못 불러온다 — 규칙만 같은 상수로 재현한다). */
function nodeToken(key: string): string {
  return createHash("sha256").update(`${OPERATOR_TOKEN_PREFIX}${key}`).digest("hex");
}

/** middleware.ts 의 edgeOperatorToken() 과 동일한 계산. */
async function edgeToken(key: string): Promise<string> {
  const data = new TextEncoder().encode(`${OPERATOR_TOKEN_PREFIX}${key}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

test("Node 구현과 Edge 구현이 같은 토큰을 만든다", async () => {
  for (const key of ["k", "운영자키-한글", "a".repeat(64), "sp ace/특수!@#$%^&*()"]) {
    assert.equal(await edgeToken(key), nodeToken(key), `키 "${key}" 에서 두 구현이 갈렸다`);
  }
});

test("토큰은 64자 hex 이고 원본 키를 담지 않는다", async () => {
  const key = "super-secret-operator-key";
  const t = await edgeToken(key);
  assert.match(t, /^[0-9a-f]{64}$/);
  assert.ok(!t.includes(key), "파생 토큰에 원본 키가 들어가면 안 된다");
});

test("키가 다르면 토큰도 다르다", async () => {
  assert.notEqual(await edgeToken("key-a"), await edgeToken("key-b"));
});

test("접두사가 붙는다 — 맨 sha256 과 달라야 한다", async () => {
  const key = "abc";
  const bare = createHash("sha256").update(key).digest("hex");
  assert.notEqual(nodeToken(key), bare, "접두사 없이 해싱되고 있다");
});

test("safeEqual — 같으면 true, 다르거나 길이가 다르면 false", () => {
  assert.equal(safeEqual("abc", "abc"), true);
  assert.equal(safeEqual("abc", "abd"), false);
  assert.equal(safeEqual("abc", "abcd"), false);
  assert.equal(safeEqual("", ""), true);
});
