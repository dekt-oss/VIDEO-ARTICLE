// 순수 로직 테스트. 실행: `node --test web/lib/drinks/work/lanes.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LANE_SECTIONS, draftStorageKey, laneSections, openSection, orderLanes, primaryKey, primarySectionOf, requiresInPanelConfirm, sectionForPanel,
} from "./lanes.ts";

test("레인 순서는 선택 모달과 같다(릴스 → 카드 → 밈), 중복 제거", () => {
  assert.deepEqual(orderLanes(["meme", "card", "explainer", "card"]), ["explainer", "card", "meme"]);
  assert.deepEqual(orderLanes([]), []);
});

test("설명형 레인: 초안 → 근거 → 승인 → 제작 → 산출물 → 발행안 → 게시 승인 → 게시 뒤", () => {
  assert.deepEqual(laneSections("explainer").map((s) => s.key), ["draft", "evidence", "approve", "produce", "output", "publish", "post", "after"]);
  assert.deepEqual(laneSections("card").map((s) => s.key), ["draft", "evidence", "approve", "produce", "output", "publish", "post", "after"]);
  assert.deepEqual(laneSections("meme").map((s) => s.key), ["meme", "publish", "post", "after"]);
});

test("결정 함수의 panel 전부가 레인마다 어느 섹션엔가 닿는다('none' 제외)", () => {
  const panels = ["evidence", "plan", "approve", "spend", "buy", "produce", "review", "publish", "post", "meme"] as const;
  for (const lane of ["explainer", "card", "meme"] as const) {
    for (const p of panels) {
      if (lane !== "meme" && p === "meme") continue;
      assert.ok(sectionForPanel(lane, p), `${lane}/${p}`);
    }
  }
  assert.equal(sectionForPanel("explainer", "none"), null);
  assert.equal(sectionForPanel("explainer", null), null);
});

test("펼칠 섹션: ?panel= 이 결정 panel 보다 이기고, 둘 다 없으면 첫 섹션", () => {
  assert.equal(openSection("explainer", "evidence", "approve"), "evidence");
  assert.equal(openSection("explainer", "output", "approve"), "output"); // 섹션 키로도 받는다
  assert.equal(openSection("explainer", null, "buy"), "produce");
  assert.equal(openSection("card", "", "review"), "output");
  assert.equal(openSection("explainer", null, null), "draft");
  assert.equal(openSection("explainer", "nonsense", "none"), "draft");
});

test("decision 의 panel 'publish' 는 게시 요청이 이미 있으면 '게시 승인' 칸이다(S16~S19)", () => {
  assert.equal(primarySectionOf("card", "publish", false), "publish");
  assert.equal(primarySectionOf("card", "publish", true), "post");
  assert.equal(primarySectionOf("meme", "post", false), "post");
  assert.equal(openSection("explainer", null, "publish", false, true), "post");
  assert.equal(openSection("explainer", "publish", "publish", false, true), "publish"); // ?panel= 은 그대로 이긴다
});

test("더 할 일이 없고(panel none) 게시가 끝났으면 '게시 뒤'를 연다", () => {
  assert.equal(openSection("card", null, "none", true), "after");
  assert.equal(openSection("meme", null, "none", true), "after");
  assert.equal(openSection("card", null, "none", false), "draft");
});

test("미저장 입력 키는 소재·레인(·카드 밈이면 제작안)별", () => {
  assert.equal(draftStorageKey("t1", "card"), "drinks.work.t1.card");
  assert.equal(draftStorageKey("meme", "meme", "d9"), "drinks.work.meme.meme.d9");
  assert.equal(draftStorageKey("t1", "card", "d9"), "drinks.work.t1.card");
});

test("결정 바 열쇠 = 동작 이름(+하위 action)", () => {
  assert.equal(primaryKey({ name: "approve_content", payload: { topic_id: "t" } }), "approve_content");
  assert.equal(primaryKey({ name: "publication_action", payload: { action: "submit" } }), "publication_action:submit");
  assert.equal(primaryKey(null), null);
});

test("지문이 드는 동작은 바가 직접 보내지 않는다", () => {
  assert.equal(requiresInPanelConfirm({ name: "publication_action", payload: { action: "approve" } }), true);
  assert.equal(requiresInPanelConfirm({ name: "publication_action", payload: { action: "approve", expected_digest: "abc" } }), true);
  assert.equal(requiresInPanelConfirm({ name: "publication_action", payload: { action: "submit" } }), false);
  assert.equal(requiresInPanelConfirm({ name: "explainer_request_assemble", payload: {} }), false);
  assert.equal(requiresInPanelConfirm(null), false);
});

test("각 섹션의 panels 는 레인 안에서 겹치지 않는다(한 panel → 한 섹션)", () => {
  for (const [lane, sections] of Object.entries(LANE_SECTIONS)) {
    const seen = new Set<string>();
    for (const s of sections) for (const p of s.panels) {
      assert.ok(!seen.has(p), `${lane}: ${p} 가 두 섹션에`);
      seen.add(p);
    }
  }
});
