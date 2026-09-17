// 순수 로직 테스트. 실행: `node --test web/lib/work/reseed.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { decideReseed, afterSave } from "./reseed.ts";

test("★ 회귀: 저장 직후 서버가 아직 옛 값을 들고 있어도 되돌리지 않는다", () => {
  // 2026-09-17 운영자 보고: "제목 바꿔서 저장했는데 원래 제목 그대로 되면서
  // '제목 저장 (고친 내용 없음)' 이라고 뜹니다." 저장은 됐는데 화면이 스스로 되돌렸다.
  const state = afterSave("청각을 잃으면 진짜 시각이 강화된다??");
  const r = decideReseed("소리를 잃으면 시야가 넓어지는 놀라운 이유", state, false);
  assert.equal(r.reseed, false, "옛 값으로 덮어쓰면 '저장이 안 됐다'는 거짓말이 된다");
  assert.equal(r.known, "청각을 잃으면 진짜 시각이 강화된다??");
  assert.equal(r.awaitingServer, true, "서버가 따라올 때까지 계속 기다린다");
});

test("서버가 우리가 저장한 값을 들고 오면 대기가 끝난다", () => {
  const state = afterSave("새 제목");
  const r = decideReseed("새 제목", state, false);
  assert.equal(r.reseed, false);          // 이미 그 값이다 — 건드릴 것이 없다
  assert.equal(r.awaitingServer, false);  // 이제부터 서버가 다시 정본
});

test("대기가 끝난 뒤 서버 값이 진짜로 바뀌면 갈아끼운다", () => {
  // 다른 탭·다른 사람·지시서 재생성으로 값이 바뀌는 경우.
  const r = decideReseed("서버가 바꾼 제목", { known: "옛 제목", awaitingServer: false }, false);
  assert.equal(r.reseed, true);
  assert.equal(r.known, "서버가 바꾼 제목");
});

test("편집 중이면 서버 값이 와도 갈아끼우지 않는다 — 타이핑을 빼앗지 않는다", () => {
  const r = decideReseed("서버가 바꾼 제목", { known: "옛 제목", awaitingServer: false }, true);
  assert.equal(r.reseed, false);
  assert.equal(r.known, "서버가 바꾼 제목"); // 알고는 있다(다음에 안 고쳤으면 반영된다)
});

test("값이 그대로면 아무 일도 일어나지 않는다", () => {
  const r = decideReseed("같은 값", { known: "같은 값", awaitingServer: false }, false);
  assert.deepEqual(r, { reseed: false, known: "같은 값", awaitingServer: false });
});

test("여러 칸을 묶어서도 쓸 수 있다(한/영 제목)", () => {
  type T = { ko: string; en: string };
  const eq = (a: T, b: T) => a.ko === b.ko && a.en === b.en;
  const state = afterSave<T>({ ko: "새 한글", en: "new en" });
  const stale = decideReseed({ ko: "옛 한글", en: "old en" }, state, false, eq);
  assert.equal(stale.reseed, false);
  const caught = decideReseed({ ko: "새 한글", en: "new en" }, state, false, eq);
  assert.equal(caught.awaitingServer, false);
});
