import test from "node:test";
import assert from "node:assert/strict";

import { canJudge, canSelect, kstMinute, nextStep, slotCosts, type ExplainerCandidate, type ExplainerSlot, type ExplainerStatus } from "./explainerQueue.ts";

const cand = (over: Partial<ExplainerCandidate> = {}): ExplainerCandidate => ({
  candidate_id: "P:A1#c1", k: 1, status: "stored", cost_usd: 0.81, auto_verdict: "pass", human_verdict: null, auto_report: null, asset: null, attempts: [], ...over,
});
const slot = (over: Partial<ExplainerSlot> = {}): ExplainerSlot => ({
  slot_id: "P:A1", n: 1, role: "mechanism", status: "auto_checked", min_src_ms: 7700, candidates_planned: 1, boundary_in: "loop", boundary_out: "cut", image_usd: 0.134, selection: null, candidates: [cand()], ...over,
});
const st = (state: string | null, over: Partial<ExplainerStatus> = {}): ExplainerStatus => ({
  is_explainer: true, approved_amount_usd: 8.9, episode: state ? ({ state } as ExplainerStatus["episode"]) : null, slots: [], approvals: [], unknown_attempts: [], ...over,
});
const OPEN = { approval_id: "a", stage: "s", cap_usd: 5, allowed_kinds: ["image", "video"], status: "open" as const, expired: false, expires_at: "", remaining_usd: 5, held_usd: 0, spent_usd: 0, order_hash: null };

test("슬롯별 비용·누적: 번호 순서로 쌓고, 불합격 후보의 돈도 넣고, 결과 모르는 시도는 따로 본다", () => {
  const unknownAttempt = { attempt_id: "x", m: 1, state: "unknown_billed", provider: "omni", provider_request_id: null, approval_id: "a", billed_units: null, actual_usd: null, est_usd: 0.41, error_code: null, closed_by: null, close_note: null };
  const out = slotCosts([
    slot({ n: 2, slot_id: "P:A2", image_usd: "0.039", candidates: [cand({ cost_usd: "0.41", attempts: [unknownAttempt] })] }),
    slot({ n: 1, candidates: [cand({ cost_usd: 0.81 }), cand({ k: 2, cost_usd: 0.81, auto_verdict: "fail" })] }),
  ]);
  assert.deepEqual(out.map((c) => c.n), [1, 2]);
  assert.ok(Math.abs(out[0].totalUsd - (0.134 + 1.62)) < 1e-9);
  assert.ok(Math.abs(out[1].cumulativeUsd - (0.134 + 1.62 + 0.039 + 0.41)) < 1e-9);
  assert.equal(out[1].unknownHeldUsd, 0.41);
  assert.equal(out[0].unknownHeldUsd, 0);
});

test("판정·선택 버튼 조건은 DB 규칙과 같다", () => {
  assert.equal(canJudge(slot(), cand()), true);
  assert.equal(canJudge(slot(), cand({ auto_verdict: "fail" })), false, "자동 불합격은 사람이 뒤집지 못한다");
  assert.equal(canJudge(slot(), cand({ human_verdict: "pass" })), false);
  assert.equal(canJudge(slot({ status: "no_pass" }), cand()), false);
  assert.equal(canSelect(slot({ status: "human_checked" }), cand({ human_verdict: "pass" })), true);
  assert.equal(canSelect(slot({ status: "auto_checked" }), cand({ human_verdict: "pass" })), false, "모든 후보 판정 뒤에만");
  assert.equal(canSelect(slot({ status: "human_checked" }), cand({ human_verdict: "fail" })), false, "그나마 나은 쪽은 없다");
  assert.equal(canSelect(slot({ status: "human_checked", selection: { candidate_id: "x", selected_by: "operator", reason: "r", selected_at: "" } }), cand({ human_verdict: "pass" })), false);
});

test("다음 할 일", () => {
  assert.equal(nextStep(st(null)), "request_plan");
  assert.equal(nextStep(st("plan_draft")), "request_plan");
  assert.equal(nextStep(st("directive_ready")), "open_approval");
  assert.equal(nextStep(st("directive_ready", { approvals: [{ ...OPEN, allowed_kinds: ["image"] }] })), "open_approval", "그림만 허용한 결재로는 살 수 없다");
  assert.equal(nextStep(st("directive_ready", { approvals: [{ ...OPEN, expired: true }] })), "open_approval");
  assert.equal(nextStep(st("directive_ready", { approvals: [OPEN] })), "request_buy");
  assert.equal(nextStep(st("blocked_budget")), "open_approval");
  assert.equal(nextStep(st("unknown_billed")), "close_unknown");
  assert.equal(nextStep(st("buying", { slots: [slot()] })), "review_candidates");
  assert.equal(nextStep(st("buying", { slots: [slot({ status: "selected", selection: { candidate_id: "x", selected_by: "o", reason: "r", selected_at: "" } })] })), "request_buy");
  assert.equal(nextStep(st("assets_complete")), "request_assemble");
  assert.equal(nextStep(st("blocked_assets")), "request_assemble");
  assert.equal(nextStep(st("auto_qa_pass")), "process_review");
  assert.equal(nextStep(st("process_review_pass")), "quality_review");
  assert.equal(nextStep(st("quality_review_pass")), "output_review");
  assert.equal(nextStep(st("ready_to_publish")), "none");
  assert.equal(nextStep(st("blocked_no_pass")), "none", "자동으로 다시 사는 길이 없다");
});

test("시각 표기는 지역 설정과 무관하다(hydration)", () => {
  assert.equal(kstMinute("2026-11-09T00:00:00Z"), "2026-11-09 09:00");
  assert.equal(kstMinute(null), "-");
  assert.equal(kstMinute("엉뚱한 값"), "-");
});
