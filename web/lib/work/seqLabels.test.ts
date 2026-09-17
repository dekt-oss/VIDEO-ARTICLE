// 순수 로직 테스트. 실행: `node --test web/lib/work/seqLabels.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { seqLabel, seqTitle, sequenceRoleLabel } from "./seqLabels.ts";

test("코드 어휘가 한국어로 바뀐다", () => {
  assert.equal(seqLabel("camera_operation", "DOLLY_IN"), "천천히 다가간다");
  assert.equal(seqLabel("continuity_mode", "MUTATE_STATE"), "같은 화면에서 대상만 변한다");
  assert.equal(seqLabel("evidence_role", "caveat"), "단서·한계");
  assert.equal(seqLabel("visual_role", "MECHANISM"), "기전 도해");
});

test("★ 모르는 값은 숨기지 않고 원값을 그대로 — 빠진 표를 눈치챌 수 있어야 한다", () => {
  // 조용히 빈칸이 되면 "표에 안 넣었다"를 영원히 모른다(effectLabels 가 배운 규칙).
  assert.equal(seqLabel("camera_operation", "NEW_MOVE_X"), "NEW_MOVE_X");
  assert.equal(seqLabel("존재하지않는표", "ANY"), "ANY");
});

test("빈 값은 빈 문자열", () => {
  assert.equal(seqLabel("camera_operation", ""), "");
  assert.equal(seqLabel("camera_operation", null), "");
  assert.equal(seqLabel("camera_operation", undefined), "");
});

test("툴팁은 영어 원값을 남긴다 — 렌더·게이트가 쓰는 것은 영어다", () => {
  assert.equal(seqTitle("camera_operation", "ORBIT"), "ORBIT — 둘레를 돌며 본다");
  assert.equal(seqTitle("camera_operation", "UNKNOWN_X"), "UNKNOWN_X");
});

test("시퀀스 역할", () => {
  assert.match(sequenceRoleLabel("MECHANISM_SEQUENCE"), /기전/);
  assert.equal(sequenceRoleLabel("NEW_ROLE_X"), "NEW_ROLE_X");
  assert.equal(sequenceRoleLabel(""), "묶음");
});
