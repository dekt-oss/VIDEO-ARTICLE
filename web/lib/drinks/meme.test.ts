import test from "node:test";
import assert from "node:assert/strict";

import { DRINKS_ACTIONS } from "./actions.ts";
import { autoBeatMs, buildMemeSpec, isMissingMemeTables, memeNextStep, memeTotalSec, parseBeats, type MemeFormInput } from "./meme.ts";

const form = (o: Partial<MemeFormInput> = {}): MemeFormInput => ({
  frame: "top_text", topLine: " 윗줄 ", titleKeyword: "", beatsText: "앞면을 본다 | 3\n*가격표*만 기억난다", caption: " c ", palette: "wine",
  sound: "ambient_local", audioTitle: "", audioId: "", startHintSec: "", containsInfo: false, claimIds: "", ...o,
});

test("비트 입력: 초·강조 낱말을 읽고, 안 적으면 글 길이로 채운다", () => {
  const b = parseBeats("앞면을 본다 | 3.5\n\n*가격표*만 기억난다");
  assert.equal(b.length, 2);
  assert.deepEqual(b[0], { text: "앞면을 본다", keyword: "", ms: 3500 });
  assert.equal(b[1].text, "가격표만 기억난다");
  assert.equal(b[1].keyword, "가격표");
  assert.equal(b[1].ms, autoBeatMs("가격표만 기억난다"));
  assert.equal(memeTotalSec(b), (3500 + b[1].ms) / 1000);
});

test("글 길이 규칙: 하한·상한", () => {
  assert.equal(autoBeatMs("짧"), 1800);
  assert.equal(autoBeatMs("가".repeat(100)), 8000);
});

test("제작안: 분위기 음원은 박자 무관 등급", () => {
  const s = buildMemeSpec(form());
  assert.equal(s.top_line, "윗줄");
  assert.equal(s.sync_grade, "sync_free");
  assert.deepEqual(s.audio, { mode: "ambient_local" });
  assert.deepEqual(s.scene, { source: "text_bg", palette: "wine" });
});

test("제작안: 앱에서 붙이는 음원은 항상 박자 맞춤 등급이다", () => {
  const s = buildMemeSpec(form({ sound: "app_manual", audioTitle: " 곡 ", audioId: "9", startHintSec: "12.5" }));
  assert.equal(s.sync_grade, "sync_required");
  assert.deepEqual(s.audio, { mode: "app_manual", title: "곡", audio_id: "9", start_hint_sec: 12.5 });
  const noHint = buildMemeSpec(form({ sound: "app_manual", audioTitle: "곡" }));
  assert.equal("start_hint_sec" in noHint.audio, false);
});

test("제작안: 정보 표시를 끄면 주장 ID 를 싣지 않는다", () => {
  assert.deepEqual(buildMemeSpec(form({ containsInfo: false, claimIds: "c1" })).claim_ids, []);
  assert.deepEqual(buildMemeSpec(form({ containsInfo: true, claimIds: "c1, c2" })).claim_ids, ["c1", "c2"]);
});

test("0066 미적용 판별: 0건과 구별한다", () => {
  assert.equal(isMissingMemeTables('relation "drink_meme_board" does not exist'), true);
  assert.equal(isMissingMemeTables("permission denied"), false);
});

test("게시 대기는 발행 화면으로 안내하고(0068 게시 연결), 앱 부착은 자동 게시 안 함을 말한다", () => {
  assert.match(memeNextStep("publish_waiting"), /drinks\/publish/);
  assert.match(memeNextStep("manual_audio"), /자동으로 올라가지 않습니다/);
  assert.match(memeNextStep("published"), /올렸습니다/);
});

test("동작 목록: 화면은 렌더·끝내기·가잡기를 못 부른다", () => {
  const fns = Object.values(DRINKS_ACTIONS) as string[];
  for (const fn of ["drinks_meme_claim", "drinks_meme_finish", "drinks_meme_finish_text", "drinks_meme_hold", "drinks_meme_reap"]) {
    assert.equal(fns.includes(fn), false, fn);
  }
});
