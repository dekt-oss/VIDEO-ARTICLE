// [이걸로] 기본값(2026-11-06) — 비워 두면 후보 질문을 다듬어 제목·질문·주종을 채운다.
import test from "node:test";
import assert from "node:assert/strict";
import { inferCategories, pickDefaults, tidyQuestion } from "./pickModal.ts";

test("조사 앞 띄어쓰기와 공백을 다듬는다", () => {
  assert.equal(tidyQuestion("위스키 는 유통기한 이 있을까? 개봉한 위스키 는 언제까지 마셔도 될까?"),
    "위스키는 유통기한이 있을까? 개봉한 위스키는 언제까지 마셔도 될까?");
});

test("머리말 괄호·이모지를 지우고 '|' 앞을 제목으로", () => {
  const d = pickDefaults("[후기] 싱글몰트 vs 블렌디드 위스키 차이 🥃 | 어떤 위스키가 더 좋을까?");
  assert.equal(d.title, "싱글몰트 vs 블렌디드 위스키 차이");
  assert.equal(d.question, "싱글몰트 vs 블렌디드 위스키 차이 — 어떤 위스키가 더 좋을까?");
  assert.deepEqual(d.categories, ["whisky"]);
});

test("주종 추론: 사케·전통주, 없으면 빈 배열", () => {
  assert.deepEqual(inferCategories("사케 유통기한이 어느정도일까요?"), ["sake"]);
  assert.deepEqual(inferCategories("누룩이란 무엇인가?"), ["traditional"]);
  assert.deepEqual(inferCategories("생막걸리와 살균막걸리, 무엇이 다를까?"), ["traditional"]);
  assert.deepEqual(inferCategories("술은 왜 취할까?"), []);
});

test("긴 제목은 60자 안으로 자른다", () => {
  const d = pickDefaults("가".repeat(80));
  assert.ok(d.title.length <= 60);
  assert.ok(d.title.endsWith("…"));
});

test("'|' 가 없으면 첫 물음 문장을 제목으로", () => {
  const d = pickDefaults("위스키 는 유통기한 이 있을까? 개봉한 위스키 는 언제까지 마셔도 될까?");
  assert.equal(d.title, "위스키는 유통기한이 있을까?");
  assert.equal(d.question, "위스키는 유통기한이 있을까? 개봉한 위스키는 언제까지 마셔도 될까?");
});
