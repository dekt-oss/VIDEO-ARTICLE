// 순수 로직 테스트. 실행: `node --test web/lib/work/sequenceView.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildSequenceLayout } from "./sequenceView.ts";

const SEQS = [
  { sequence_id: "SEQ1", sequence_role: "MECHANISM_SEQUENCE",
    world: { world_id: "TABLETOP_LAB", style: "실험실 탁자" },
    entities: [{ entity_id: "BRAIN", visual_identity: "반투명 뇌 모형" }],
    stages: [
      { stage_id: "S1", cut_refs: [3], observable_change: "모형이 놓인다" },
      { stage_id: "S2", cut_refs: [4, 6], observable_change: "토큰이 바뀐다" },
    ] },
  { sequence_id: "SEQ2", sequence_role: "REALITY_ANCHOR",
    stages: [{ stage_id: "S4", cut_refs: [1, 2, 5] }] },
];

test("컷이 시퀀스·단계로 묶이고, 단계 안에서는 지시서 컷 순서를 따른다", () => {
  const L = buildSequenceLayout([1, 2, 3, 4, 5, 6], SEQS);
  assert.equal(L.hasSequences, true);
  assert.deepEqual(L.sequences.map((s) => s.sequenceId), ["SEQ1", "SEQ2"]);
  assert.deepEqual(L.sequences[0].stages.map((s) => s.cutNos), [[3], [4, 6]]);
  assert.deepEqual(L.sequences[1].stages[0].cutNos, [1, 2, 5]);   // cut_refs 순서가 아니라 컷 순서
  assert.deepEqual(L.loose, []);
});

test("★ 어느 단계도 안 가리킨 컷은 버리지 않고 loose 로 내보낸다", () => {
  // 컷을 잃어버리면 화면에서 사라지고, 운영자는 그 컷이 렌더에 나가는 줄도 모른다.
  const L = buildSequenceLayout([1, 2, 3, 4, 5, 6, 7, 9], SEQS);
  assert.deepEqual(L.loose, [7, 9]);
});

test("시퀀스가 아예 없으면 전부 loose — 화면은 같은 코드로 평평한 목록을 그린다", () => {
  const L = buildSequenceLayout([1, 2, 3], []);
  assert.equal(L.hasSequences, false);
  assert.deepEqual(L.loose, [1, 2, 3]);
  assert.deepEqual(L.sequences, []);
  assert.deepEqual(buildSequenceLayout([1, 2], null).loose, [1, 2]);
});

test("같은 컷을 두 단계가 가리키면 앞 단계에만 넣는다", () => {
  // 두 곳에 같은 나레이션이 뜨면 어느 쪽을 고쳐야 정본인지 알 수 없다.
  const dup = [{ sequence_id: "A", stages: [
    { stage_id: "S1", cut_refs: [1, 2] },
    { stage_id: "S2", cut_refs: [2, 3] },
  ] }];
  const L = buildSequenceLayout([1, 2, 3], dup);
  assert.deepEqual(L.sequences[0].stages.map((s) => s.cutNos), [[1, 2], [3]]);
  assert.deepEqual(L.loose, []);
});

test("없는 컷을 가리키는 단계는 missingCutNos 로 드러낸다 — 조용히 넘기지 않는다", () => {
  const ghost = [{ sequence_id: "A", stages: [{ stage_id: "S1", cut_refs: [1, 99] }] }];
  const L = buildSequenceLayout([1], ghost);
  assert.deepEqual(L.sequences[0].stages[0].cutNos, [1]);
  assert.deepEqual(L.sequences[0].stages[0].missingCutNos, [99]);
});

test("cutCount 는 실제로 담긴 컷 수다(유령 컷은 안 센다)", () => {
  const L = buildSequenceLayout([1, 2, 3, 4, 5, 6], SEQS);
  assert.equal(L.sequences[0].cutCount, 3);
  assert.equal(L.sequences[1].cutCount, 3);
});
