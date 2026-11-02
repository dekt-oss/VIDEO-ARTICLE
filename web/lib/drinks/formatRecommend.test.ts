// 형식 추천 규칙 순수 테스트 (node --test).
import test from "node:test";
import assert from "node:assert/strict";
import {
  CARD_MIN_EVIDENCE, EXPLAINER_MIN_EVIDENCE, EXPLAINER_MIN_EVIDENCE_CHARS, questionShape, recommendFormat, type FormatInput,
} from "./formatRecommend.ts";

const input = (o: Partial<FormatInput> = {}): FormatInput => ({
  origin: "discovery", question: "고도주는 왜 안 상하나요?", signals: ["question"], evidenceCount: 3, evidenceChars: 5000, ...o,
});

test("설명형: 왜·원리 질문 + 근거 2개 이상 + 40초를 채울 분량", () => {
  const r = recommendFormat(input());
  assert.equal(r.format, "explainer");
  assert.match(r.reason, /글 3개/);
  assert.equal(recommendFormat(input({ question: "Why does whisky not spoil?" })).format, "explainer");
  assert.equal(recommendFormat(input({ question: "막걸리 트림의 원리가 궁금해요" })).format, "explainer");
  assert.equal(recommendFormat(input({ evidenceCount: EXPLAINER_MIN_EVIDENCE, evidenceChars: EXPLAINER_MIN_EVIDENCE_CHARS })).format, "explainer", "문턱 값 그대로면 통과");
});

test("설명형 → 카드뉴스로 내림: 근거가 모자라거나 40초 분량이 안 될 때. 이유에 그 사실이 나온다", () => {
  const few = recommendFormat(input({ evidenceCount: EXPLAINER_MIN_EVIDENCE - 1 }));
  assert.equal(few.format, "card");
  assert.match(few.reason, /카드뉴스로 내립니다/);
  const short = recommendFormat(input({ evidenceChars: EXPLAINER_MIN_EVIDENCE_CHARS - 1 }));
  assert.equal(short.format, "card");
  assert.match(short.reason, /40초/);
});

test("카드뉴스: 비교·보관·선택·이슈 + 근거 1개 이상", () => {
  assert.equal(recommendFormat(input({ question: "사케 보관은 냉장고에 하나요?", signals: ["storage"], evidenceCount: CARD_MIN_EVIDENCE, evidenceChars: 300 })).format, "card");
  assert.equal(recommendFormat(input({ question: "How long does it last", signals: ["selection"] })).format, "card");
  assert.equal(recommendFormat(input({ question: "생막걸리와 살균막걸리 차이", signals: [] })).format, "card");
  assert.equal(recommendFormat(input({ question: "올해 나온 술", signals: ["new_product"] })).format, "card");
});

test("왜·원리가 먼저다 — 보관 신호가 붙어도 '왜'를 물으면 설명형", () => {
  assert.equal(questionShape("고도주는 왜 안 상하나", ["storage"]), "why");
  assert.equal(recommendFormat(input({ question: "고도주는 왜 안 상하나", signals: ["storage"] })).format, "explainer");
});

test("밈형: 트렌드 보드에서 온 카드에만. 근거 값이 없어도 된다", () => {
  const r = recommendFormat(input({ origin: "meme_board", question: null, signals: null, evidenceCount: null, evidenceChars: null }));
  assert.equal(r.format, "meme");
  assert.match(r.reason, /근거/);
  assert.notEqual(recommendFormat(input()).format, "meme", "발견함 후보는 밈으로 추천하지 않는다");
});

test("필요한 값을 못 읽으면 추측하지 않는다 — unknown 과 그 이유", () => {
  const noCount = recommendFormat(input({ evidenceCount: null, evidenceChars: null }));
  assert.equal(noCount.format, "unknown");
  assert.match(noCount.reason, /읽지 못해/);
  const cardNoCount = recommendFormat(input({ question: "보관법", signals: ["storage"], evidenceCount: null, evidenceChars: null }));
  assert.equal(cardNoCount.format, "unknown");
  const noChars = recommendFormat(input({ evidenceChars: null }));
  assert.equal(noChars.format, "unknown", "분량을 모르면 40초를 채울지 모른다");
  assert.match(noChars.reason, /분량/);
  const nothing = recommendFormat(input({ question: "  ", signals: [] }));
  assert.equal(nothing.format, "unknown");
  assert.match(nothing.reason, /판단하지 못했습니다/);
  assert.equal(recommendFormat(input({ question: null, signals: null })).format, "unknown");
});

test("근거 0개면 어느 형식도 추천하지 않는다 / 어느 유형에도 안 잡히면 직접 고른다", () => {
  const zero = recommendFormat(input({ evidenceCount: 0, evidenceChars: 0 }));
  assert.equal(zero.format, "unknown");
  assert.match(zero.reason, /걸린 글이 없어/);
  assert.equal(recommendFormat(input({ question: "보관법", signals: ["storage"], evidenceCount: 0, evidenceChars: 0 })).format, "unknown");
  const other = recommendFormat(input({ question: "오늘 뭐 마셨어요", signals: ["question"] }));
  assert.equal(other.format, "unknown");
  assert.match(other.reason, /직접 고르세요/);
});
