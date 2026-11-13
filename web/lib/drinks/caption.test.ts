import test from "node:test";
import assert from "node:assert/strict";
import { autoCaption } from "./caption.ts";

test("캡션 자동 채움: 제목·승인된 결론·AI 표시·종류 해시태그(청주·탁주 실제 값)", () => {
  const c = autoCaption({
    title: "그렇다면 약주, 탁주, 청주의 차이는 무엇일까요?",
    takeaway: "약주와 탁주의 구별은 빚는 재료가 아니라 맑게 걸렀는지 여부에 따른 것이다.",
    categories: ["traditional"], aiLabel: "AI 생성 영상",
  });
  assert.equal(c, "그렇다면 약주, 탁주, 청주의 차이는 무엇일까요?\n\n약주와 탁주의 구별은 빚는 재료가 아니라 맑게 걸렀는지 여부에 따른 것이다.\n\n※ AI 생성 영상\n\n#전통주 #우리술");
});

test("결론·AI 표시가 없으면 그 줄을 빼고, 모르는 종류는 태그를 만들지 않는다", () => {
  assert.equal(autoCaption({ title: " 위스키 물 ", takeaway: null, categories: ["whisky", "beer"], aiLabel: null }), "위스키 물\n\n#위스키");
});
