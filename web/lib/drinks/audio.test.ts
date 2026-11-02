import test from "node:test";
import assert from "node:assert/strict";

import { CARD_REEL_AUDIO_VOLUME, CARD_REEL_VIDEO_VOLUME, audioPayload, audioSummary, pubBlockLabel } from "./audio.ts";

test("화면은 제목·가수를 보내지 않는다 — 서버가 음원 표에서 복사한다", () => {
  const p = audioPayload({ audioId: "a1", audioVolume: CARD_REEL_AUDIO_VOLUME, videoVolume: CARD_REEL_VIDEO_VOLUME, syncGrade: "sync_free" });
  assert.deepEqual(p, { mode: "ig_audio", audio_id: "a1", audio_volume: 90, video_volume: 10, sync_grade: "sync_free" });
  assert.ok(!("title_snapshot" in p));
});

test("음원 요약: 없음·라이선스·인스타 음원·박자 맞춤을 말로 보여 준다", () => {
  assert.equal(audioSummary(null), "음원 없음");
  assert.equal(audioSummary({ mode: "none" }), "음원 없음");
  assert.match(audioSummary({ mode: "licensed_mix" }), /라이선스/);
  const s = audioSummary({ mode: "ig_audio", audio_id: "a1", title_snapshot: "노래", artist_snapshot: "가수", audio_volume: 90, video_volume: 10, sync_grade: "sync_required" });
  assert.match(s, /노래 — 가수/);
  assert.match(s, /자동 게시 안 됨/);
  assert.match(audioSummary({ mode: "ig_audio", audio_id: "a1", audio_volume: 90, video_volume: 10 }), /^a1 /, "제목이 없으면 ID");
});

test("게시 조건 코드: 음원 코드는 문장으로, 나머지는 코드 그대로", () => {
  assert.match(pubBlockLabel("audio_missing"), /음원/);
  assert.equal(pubBlockLabel("digest_changed"), "digest_changed");
});
