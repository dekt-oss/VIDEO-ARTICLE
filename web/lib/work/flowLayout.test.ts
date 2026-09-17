// 순수 로직 테스트. 실행: `node --test web/lib/work/flowLayout.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildFlowLayout } from "./sequenceView.ts";

// 실제 지시서(논문 6b2d092a)의 구조 — 시퀀스가 컷 사이를 오간다.
const SEQS = [
  { sequence_id: "SEQ1", sequence_role: "MECHANISM_SEQUENCE",
    world: { world_id: "TABLETOP_LAB" },
    stages: [
      { stage_id: "S1", cut_refs: [3] },
      { stage_id: "S2", cut_refs: [4, 6] },
      { stage_id: "S3", cut_refs: [7] },
    ] },
  { sequence_id: "SEQ2", sequence_role: "REALITY_ANCHOR",
    world: { world_id: "RESEARCH_LAB" },
    stages: [
      { stage_id: "S4", cut_refs: [1, 2, 5] },
      { stage_id: "S5", cut_refs: [8, 9] },
    ] },
];

test("★ 위에서 아래로 읽으면 재생 순서 그대로다 — 시퀀스로 묶어 뒤섞지 않는다", () => {
  // 운영자 보고: "보여주는 시퀀스 컷 순서도 뒤죽박죽인데?"
  // 시퀀스로 묶으면 3,4,6,7 다음에 1,2,5,8,9 가 와서 읽는 순서 ≠ 보는 순서였다.
  const blocks = buildFlowLayout([1, 2, 3, 4, 5, 6, 7, 8, 9], SEQS);
  assert.deepEqual(blocks.flatMap((b) => b.cutNos), [1, 2, 3, 4, 5, 6, 7, 8, 9]);
});

test("연속된 컷이 같은 단계면 한 덩어리로 묶는다 — 머리말을 또 내지 않는다", () => {
  const blocks = buildFlowLayout([1, 2, 3, 4, 5, 6, 7, 8, 9], SEQS);
  assert.deepEqual(blocks.map((b) => [b.sequenceId, b.stageId, b.cutNos]), [
    ["SEQ2", "S4", [1, 2]],   // 1,2 는 같은 단계 → 한 덩어리
    ["SEQ1", "S1", [3]],
    ["SEQ1", "S2", [4]],
    ["SEQ2", "S4", [5]],      // 같은 단계지만 사이에 다른 단계가 끼어 끊긴다
    ["SEQ1", "S2", [6]],
    ["SEQ1", "S3", [7]],
    ["SEQ2", "S5", [8, 9]],
  ]);
});

test("세계 설정은 그 시퀀스가 처음 나올 때만 보여 준다", () => {
  const blocks = buildFlowLayout([1, 2, 3, 4, 5, 6, 7, 8, 9], SEQS);
  const firsts = blocks.filter((b) => b.firstOfSequence).map((b) => b.sequenceId);
  assert.deepEqual(firsts, ["SEQ2", "SEQ1"]);   // 등장 순서대로 한 번씩
});

test("★ 어느 단계에도 안 속한 컷도 제 자리에 남는다 — 끝으로 몰아내지 않는다", () => {
  // 몰아내면 위에서 아래로 읽은 것이 실제 영상 순서와 달라진다.
  const blocks = buildFlowLayout([1, 99, 3], SEQS);
  assert.deepEqual(blocks.map((b) => [b.stageId, b.cutNos]), [
    ["S4", [1]], ["", [99]], ["S1", [3]],
  ]);
  assert.equal(blocks[1].seqIndex, -1);
});

test("시퀀스가 아예 없으면 컷 하나짜리 덩어리들이 재생 순서로 늘어선다", () => {
  const blocks = buildFlowLayout([1, 2, 3], []);
  assert.deepEqual(blocks.map((b) => b.cutNos), [[1, 2, 3]]);  // 전부 같은 '없음' 구간
  assert.equal(blocks[0].seqIndex, -1);
});

test("같은 컷을 두 단계가 가리키면 앞 단계가 가진다", () => {
  const dup = [{ sequence_id: "A", stages: [
    { stage_id: "S1", cut_refs: [1, 2] },
    { stage_id: "S2", cut_refs: [2, 3] },
  ] }];
  const blocks = buildFlowLayout([1, 2, 3], dup);
  assert.deepEqual(blocks.map((b) => [b.stageId, b.cutNos]), [["S1", [1, 2]], ["S2", [3]]]);
});
