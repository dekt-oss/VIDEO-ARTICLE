import test from "node:test";
import assert from "node:assert/strict";
import { reportApprovalBlockReasons } from "./approvalGate.ts";

test("report approval blocks an edited partial-text directive above 35 seconds", () => {
  const header = {
    content_mode: "standard",
    source_adequacy: {
      contract_version: "source-adequacy-v1",
      domain: "report",
      source_depth: "partial_text",
      source_chars: 807,
      source_mode: "BRIEF_EXPLAINER",
      max_content_mode: "",
      max_duration_sec: 35,
      max_reasoning_units: 1,
      max_reasoning_steps: 3,
      warnings: [],
    },
  };
  const cuts = [
    { cut_no: 1, estimated_sec: 20 },
    { cut_no: 2, estimated_sec: 16 },
  ];

  assert.deepEqual(
    reportApprovalBlockReasons(header, cuts),
    ["source_depth_duration_exceeded:36>35"],
  );
});

test("report approval preserves claim-id and explainer reasons but drops stale edit-sensitive reasons", () => {
  const header = {
    block_reasons: ["photo_mechanism_on_number:4", "claim_id_invalid:missing"],
    explainer: { gate: { block_reasons: ["explanation_chain_broken"] } },
  };

  assert.deepEqual(
    reportApprovalBlockReasons(header, []),
    [
      "claim_id_invalid:missing",
      "explanation_chain_broken",
    ],
  );
});
