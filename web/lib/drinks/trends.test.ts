import test from "node:test";
import assert from "node:assert/strict";

import {
  clusterIssues, isMissingTrendTables, rankProducts, safeHref, scoreText, sentimentBar, sentimentLabel, titleSimilarity, type TrendIssueRow,
} from "./trends.ts";

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

const issue = (id: string, title: string, at: string, channel = "언론사"): TrendIssueRow => ({
  id, title, summary: null, canonical_url: `https://news.example.kr/${id}`, channel_name: channel, posted_at: at, query: "주세 개정", collected_at: at,
});

test("제목 유사도: 같은 이야기는 0.5 이상, 다른 이야기·겹침 2개 미만은 낮다", () => {
  assert.ok(titleSimilarity("생맥주 주세 20% 경감 3년 연장", "생맥주 주세 20% 경감, 3년 연장 확정") >= 0.5);
  assert.ok(titleSimilarity("생맥주 주세 20% 경감 3년 연장", "위스키 수입 증가 속 가격 인상 우려") < 0.5);
  assert.equal(titleSimilarity("주세", "주세"), 0, "겹친 조각이 2개 미만이면 0");
  assert.equal(titleSimilarity("", "생맥주 주세"), 0);
});

test("이슈 묶기: 같은 이야기 N건 → 최신 제목 대표 + 링크 3개, 많은 묶음이 먼저, 같으면 최근 먼저", () => {
  const rows = [
    issue("a1", "생맥주 주세 20% 경감 3년 연장", "2026-10-20T09:00:00Z", "A일보"),
    issue("a2", "생맥주 주세 20% 경감 3년 연장 확정", "2026-10-22T09:00:00Z", "B뉴스"),
    issue("a3", "[속보] 생맥주 주세 20% 경감 3년 연장", "2026-10-21T09:00:00Z", "C경제"),
    issue("a4", "생맥주 주세 20% 경감 3년 연장 국회 통과", "2026-10-23T09:00:00Z", "D신문"),
    issue("a5", "생맥주 주세 20% 경감 3년 연장 의결", "2026-10-19T09:00:00Z", "E방송"),
    issue("b1", "위스키 수입사들 가격 인상 예고", "2026-10-24T09:00:00Z"),
    issue("c1", "전통주 온라인 판매 허용 확대 논의", "2026-10-18T09:00:00Z"),
    issue("c2", "전통주 온라인 판매 허용 확대 논의 본격화", "2026-10-25T09:00:00Z"),
  ];
  const before = rows.map((r) => r.id).join();
  const cl = clusterIssues(rows);
  assert.equal(rows.map((r) => r.id).join(), before, "원본은 바꾸지 않는다");
  assert.equal(cl.length, 3);
  assert.equal(cl[0].count, 5);
  assert.equal(cl[0].representative.id, "a4", "가장 최근 기사가 대표");
  assert.deepEqual(cl[0].links.map((l) => l.channel), ["D신문", "B뉴스", "C경제"], "최근순 3개까지");
  assert.equal(cl[1].count, 2, "기사 수 다음 순서");
  assert.equal(cl[1].representative.id, "c2");
  assert.equal(cl[2].count, 1);
  assert.equal(cl[2].representative.id, "b1");
  assert.equal(cl.reduce((n, c) => n + c.count, 0), rows.length, "기사가 사라지지 않는다");
});

test("이슈 묶기: 기사 수가 같으면 더 최근 묶음이 먼저, 빈 목록은 빈 목록", () => {
  const cl = clusterIssues([issue("x", "막걸리 업계 수출 확대 전망", "2026-10-01T00:00:00Z"), issue("y", "소주 가격 인상 소비자 부담", "2026-10-05T00:00:00Z")]);
  assert.deepEqual(cl.map((c) => c.representative.id), ["y", "x"]);
  assert.deepEqual(clusterIssues([]), []);
});

test("막대: 의견 없는 글이 많으면 중립 폭이 크다", () => {
  const b = sentimentBar({ judged: 10, positive: 1, negative: 1, neutral: 8 });
  assert.deepEqual([b.positivePct, b.neutralPct, b.negativePct], [10, 80, 10]);
});
