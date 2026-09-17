// 순수 로직 테스트. 실행: `node --test web/lib/work/versionSelection.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickInitialVersions } from "./versionSelection.ts";

const KNOWN = ["comic", "webtoon", "photo"];

test("★ 회귀: 지시서가 photo 로 있으면 photo 를 체크한다 — 기본값 comic 이 이기면 안 된다", () => {
  // 2026-09-17 사고: 결정 바가 comic 만 보고 "지시서 생성(만화식)"을 띄워,
  // 승인만 누르면 렌더로 갈 수 있는 photo 지시서가 화면에서 사라졌다.
  assert.deepEqual(pickInitialVersions(["photo"], null, KNOWN, "comic"), ["photo"]);
});

test("마지막 선택이 남아 있어도 있는 지시서가 이긴다", () => {
  assert.deepEqual(pickInitialVersions(["photo"], ["comic"], KNOWN, "comic"), ["photo"]);
});

test("지시서가 여럿이면 전부 체크한다 — 비교하려고 만든 것이다", () => {
  assert.deepEqual(pickInitialVersions(["comic", "photo"], null, KNOWN, "comic"), ["comic", "photo"]);
});

test("지시서가 없으면 마지막 선택을 이어준다", () => {
  assert.deepEqual(pickInitialVersions([], ["webtoon"], KNOWN, "comic"), ["webtoon"]);
});

test("지시서도 마지막 선택도 없으면 기본값 **한 건**", () => {
  // 전 버전이 기본 체크라 손대지 않고 누르면 3버전이 통째로 발주·렌더되던 사고의 처방.
  assert.deepEqual(pickInitialVersions([], null, KNOWN, "comic"), ["comic"]);
  assert.deepEqual(pickInitialVersions([], [], KNOWN, "comic"), ["comic"]);
});

test("모르는 버전 키는 버린다 — 폐기된 editorial 이 저장돼 있어도 되살아나지 않는다", () => {
  assert.deepEqual(pickInitialVersions([], ["editorial", "photo"], KNOWN, "comic"), ["photo"]);
  assert.deepEqual(pickInitialVersions(["editorial"], null, KNOWN, "comic"), ["comic"]);
});

test("중복은 한 번만", () => {
  assert.deepEqual(pickInitialVersions(["photo", "photo"], null, KNOWN, "comic"), ["photo"]);
});
