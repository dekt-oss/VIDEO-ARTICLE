import test from "node:test";
import assert from "node:assert/strict";
import { PROMO_LINES, autoCaption } from "./caption.ts";

test("캡션 자동 채움: 첫 질문·답·술째리고 소개·해시태그, AI 표시 줄은 없다(0088)", () => {
  const c = autoCaption({
    title: "막걸리는 그냥 대충 걸러 마시는 시골 술인 줄 알았죠?",
    takeaway: "쌀과 누룩을 통째로 걸러내 뽀얗게 빚어낸 것, 이게 바로 막걸리만의 진짜 매력이에요.",
    categories: ["traditional"],
  });
  assert.equal(c, [
    "막걸리는 그냥 대충 걸러 마시는 시골 술인 줄 알았죠?\n쌀과 누룩을 통째로 걸러내 뽀얗게 빚어낸 것, 이게 바로 막걸리만의 진짜 매력이에요.",
    PROMO_LINES.join("\n"),
    "#전통주 #우리술 #막걸리 #술째리고 #술추천 #술정보",
  ].join("\n\n"));
  assert.ok(!c.includes("AI 생성"));
});

test("답이 없으면 그 줄을 빼고, 모르는 종류는 태그를 만들지 않는다", () => {
  assert.equal(autoCaption({ title: " 위스키 물 ", takeaway: null, categories: ["whisky", "beer"] }),
    `위스키 물\n\n${PROMO_LINES.join("\n")}\n\n#위스키 #싱글몰트 #술째리고 #술추천 #술정보`);
});

test("소개 문구는 게시 검사를 통과한다: 숫자·권고형(~세요) 끝맺음이 없다", () => {
  for (const line of PROMO_LINES) {
    assert.ok(!/\d/.test(line), line);
    assert.ok(!/(?:보세요|하세요|드세요|마세요|넣으세요|타세요|고르세요|해\s?봐요|해\s?보자)[.!?…]*$/.test(line), line);
  }
});
