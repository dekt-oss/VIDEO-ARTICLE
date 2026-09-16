// 대본 지문 — 엔진(engine/script_revision.py)과 같은 값을 내야 한다.
// 실행: node --test web/lib/scriptRevision.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { fingerprint, isValidationCurrent } from "./scriptRevision.ts";

test("지문 계약은 sha256 앞 16글자다 — 엔진과 같은 계산", () => {
  const text = "정본 계약";
  assert.equal(
    fingerprint(text),
    createHash("sha256").update(text, "utf8").digest("hex").slice(0, 16),
  );
  assert.equal(fingerprint(text).length, 16);
});

test("한 글자만 달라도 지문이 갈린다", () => {
  assert.notEqual(
    fingerprint("매출은 20% 증가할 전망입니다."),
    fingerprint("매출은 21% 증가할 전망입니다."),
  );
});

test("앞뒤 공백은 무시한다", () => {
  assert.equal(fingerprint("  같은 글  "), fingerprint("같은 글"));
  assert.equal(fingerprint(""), "");
  assert.equal(fingerprint(null), "");
});

test("검사 이후 수정하면 최신이 아니라고 본다", () => {
  const script = "검사받은 대본입니다.";
  const validated = fingerprint(script);
  assert.equal(isValidationCurrent(script, validated), true);
  assert.equal(isValidationCurrent(script + " 한 문장 더.", validated), false);
});

test("지문이 없는 옛 초안은 경고하지 않는다", () => {
  // 전부 빨갛게 뜨면 아무도 안 읽는다 — 판정할 근거가 없으면 조용히 둔다.
  assert.equal(isValidationCurrent("아무 대본", ""), true);
  assert.equal(isValidationCurrent("아무 대본", null), true);
});
