// 순수 로직 테스트. 실행: `node --test web/lib/date.test.ts` (Node 22 타입 스트리핑).
// 초안 생성 시각 표시(2026-09-30): "오늘/어제" 는 한국 달력일로 가른다 — 서버가 UTC 여도 하루 밀리면 안 된다.
import test from "node:test";
import assert from "node:assert/strict";
import { seoulDateTimeLabel } from "./date.ts";

const NOW = new Date("2026-09-30T12:00:00Z"); // KST 9/30(수) 21:00

test("오늘 만든 것은 '오늘 HH:mm' (KST)", () => {
  assert.equal(seoulDateTimeLabel("2026-09-30T11:53:13Z", NOW), "오늘 20:53");
});

test("UTC 로는 같은 날이어도 KST 로 어제면 '어제'", () => {
  // UTC 9/29 14:31 = KST 9/29 23:31 → 어제
  assert.equal(seoulDateTimeLabel("2026-09-29T14:31:24Z", NOW), "어제 23:31");
});

test("UTC 로는 어제여도 KST 로 오늘이면 '오늘'", () => {
  // UTC 9/29 16:10 = KST 9/30 01:10
  assert.equal(seoulDateTimeLabel("2026-09-29T16:10:00Z", NOW), "오늘 01:10");
});

test("그보다 전은 월/일(요일) 시각", () => {
  assert.equal(seoulDateTimeLabel("2026-09-28T05:02:00Z", NOW), "9/28(월) 14:02");
});

test("값이 없거나 깨지면 빈 문자열 — 화면에 'Invalid Date' 가 뜨지 않는다", () => {
  assert.equal(seoulDateTimeLabel(null, NOW), "");
  assert.equal(seoulDateTimeLabel("not-a-date", NOW), "");
});
