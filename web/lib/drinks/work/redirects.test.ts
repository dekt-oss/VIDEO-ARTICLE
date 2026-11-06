// 순수 로직 테스트. 실행: `node --test web/lib/drinks/work/redirects.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { laneOfPlanFormat, legacyDiscoverRedirect, legacyDrinksRedirect, legacyReviewRedirect, productionRedirect, workPath } from "./redirects.ts";

const ID = "6f1c2a3b-1111-4222-8333-444455556666";

test("옛 소재 탭 → 작업공간 레인·칸 (기획 v2 §5 표)", () => {
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=approval"), `/drinks/work/${ID}?panel=approve`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=evidence"), `/drinks/work/${ID}?panel=evidence`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=brief"), `/drinks/work/${ID}?panel=evidence`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=video"), `/drinks/work/${ID}?lane=explainer&panel=plan`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=carousel"), `/drinks/work/${ID}?lane=card&panel=plan`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=overview"), `/drinks/work/${ID}`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=history&events=700"), `/drinks/work/${ID}`);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, ""), `/drinks/work/${ID}`);
});

test("넘기지 않는 것: 작업함 목록, uuid 아닌 id, legacy 플래그", () => {
  assert.equal(legacyReviewRedirect("/drinks/review", ""), null);
  assert.equal(legacyReviewRedirect("/drinks/review/", ""), null);
  assert.equal(legacyReviewRedirect("/drinks/review/not-a-uuid", "?tab=approval"), null);
  assert.equal(legacyReviewRedirect(`/drinks/review/${ID}`, "?tab=approval&legacy=1"), null);
  assert.equal(legacyDrinksRedirect("/drinks/production/" + ID, ""), null); // 제작은 DB 조회라 페이지가 한다
  assert.equal(legacyDrinksRedirect("/review/" + ID, ""), null); // 논문 공장은 건드리지 않는다
});

test("소재 발견 → 소재 고르기 후보 탭, legacy 플래그면 그대로", () => {
  assert.equal(legacyDiscoverRedirect("/drinks/discover", ""), "/drinks/topics?tab=candidates");
  assert.equal(legacyDrinksRedirect("/drinks/discover", "?page=2"), "/drinks/topics?tab=candidates");
  assert.equal(legacyDiscoverRedirect("/drinks/discover", "?legacy=1"), null);
  assert.equal(legacyDiscoverRedirect("/drinks/discovery", ""), null);
});

test("제작 페이지 → 제작 칸(제작안 형식으로 레인을 정한다)", () => {
  assert.equal(productionRedirect("t1", "carousel", "p1"), "/drinks/work/t1?lane=card&panel=produce&plan=p1");
  assert.equal(productionRedirect("t1", "video", "p2"), "/drinks/work/t1?lane=explainer&panel=produce&plan=p2");
  assert.equal(laneOfPlanFormat("video"), "explainer");
  assert.equal(laneOfPlanFormat("carousel"), "card");
});

test("workPath 는 빈 값을 안 싣는다", () => {
  assert.equal(workPath("t1"), "/drinks/work/t1");
  assert.equal(workPath("meme", { lane: "meme", meme: "d1" }), "/drinks/work/meme?lane=meme&meme=d1");
});
