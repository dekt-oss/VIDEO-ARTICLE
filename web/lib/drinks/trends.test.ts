import test from "node:test";
import assert from "node:assert/strict";

import { isMissingTrendTables, rankProducts, safeHref, scoreText, sentimentBar, sentimentLabel } from "./trends.ts";

test("반응 라벨: 판정 없음은 중립이 아니다, 문턱은 ±0.2(경계는 중립)", () => {
  assert.equal(sentimentLabel(null), "판정 없음");
  assert.equal(sentimentLabel(undefined), "판정 없음");
  assert.equal(sentimentLabel(0.21), "긍정");
  assert.equal(sentimentLabel(0.2), "중립");
  assert.equal(sentimentLabel(0), "중립");
  assert.equal(sentimentLabel(-0.2), "중립");
  assert.equal(sentimentLabel(-0.21), "부정");
});

test("막대: 판정된 언급만 분모, 판정 없으면 none", () => {
  assert.deepEqual(sentimentBar({ judged: 0, positive: 0, negative: 0 }), { positivePct: 0, neutralPct: 0, negativePct: 0, none: true });
  assert.deepEqual(sentimentBar({ judged: 4, positive: 2, negative: 1 }), { positivePct: 50, neutralPct: 25, negativePct: 25, none: false });
  const b = sentimentBar({ judged: 3, positive: 1, negative: 1 });
  assert.equal(b.positivePct + b.neutralPct + b.negativePct, 100);
});

test("점수 표시와 순위", () => {
  assert.equal(scoreText(0.4), "+0.40");
  assert.equal(scoreText(-0.31), "-0.31");
  assert.equal(scoreText(null), "판정 없음");
  const rows = [{ product: "나", posts: 2, judged: 1 }, { product: "가", posts: 5, judged: 0 }, { product: "다", posts: 2, judged: 2 }];
  assert.deepEqual(rankProducts(rows).map((r) => r.product), ["가", "다", "나"]);
  assert.deepEqual(rows.map((r) => r.product), ["나", "가", "다"], "원본은 바꾸지 않는다");
});

test("0059 미적용 오류 판별과 안전한 링크", () => {
  assert.equal(isMissingTrendTables('relation "public.drink_trend_products" does not exist'), true);
  assert.equal(isMissingTrendTables("Could not find the table 'public.drink_trend_issues' in the schema cache"), true);
  assert.equal(isMissingTrendTables("fetch failed"), false);
  assert.equal(isMissingTrendTables(null), false);
  assert.equal(safeHref("https://cafe.naver.com/a/1"), "https://cafe.naver.com/a/1");
  assert.equal(safeHref("javascript:alert(1)"), null);
  assert.equal(safeHref(null), null);
});
