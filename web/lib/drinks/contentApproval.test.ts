// 내용 승인 화면 순수 계산 테스트 (node --test).
import test from "node:test";
import assert from "node:assert/strict";
import {
  INTENT_TO_FORMAT, approvalLocks, chainView, evidenceContentChanged, sceneDirective, usableDraftPlan, visualClaimsOf, type ApprovalInput,
} from "./contentApproval.ts";
import { blockerLabel, contentApprovalState, nextAction, type NextActionInput } from "./model.ts";

const review = { id: "r1", status: "draft" };
const plan = { plan_status: "draft", blocked_at: null, topic_review_id: "r1", drafted_from_unapproved: true };
const pick = { format_intent: "explainer" as const };
const req = (kind: "evidence" | "plan", status: string, o: Record<string, unknown> = {}) =>
  ({ kind, status, created_at: "2026-11-02T00:00:00Z", error_code: null, error_message: null, result: {}, ...o }) as never;

test("시각 주장표는 그 제작안을 만든 요청의 결과에서 장면 번호로 찾는다", () => {
  const requests = [
    { result_plan_revision_id: "old", result: { visual_claims: [{ scene: 1, visual_claim_ko: "옛 표" }] } },
    { result_plan_revision_id: "p1", result: { visual_claims: [{ scene: 2, visual_claim_ko: "새 표" }] } },
  ];
  assert.equal(visualClaimsOf(requests, "p1")[2].visual_claim_ko, "새 표");
  assert.equal(visualClaimsOf(requests, "p1")[1], undefined);
  assert.deepEqual(visualClaimsOf(requests, "손으로 고친 새 버전"), {}, "표가 없는 버전은 비어 있다");
  assert.deepEqual(visualClaimsOf(requests, null), {});
});

test("이어 만들기 상태: 진행 중 → 준비 → 무효", () => {
  assert.equal(chainView({ pick, requests: [req("evidence", "running")], review: null, plan: null }).state, "running");
  assert.match(chainView({ pick, requests: [req("plan", "queued")], review, plan: null }).label, /대기/);
  assert.equal(chainView({ pick, requests: [req("evidence", "succeeded"), req("plan", "succeeded")], review, plan }).state, "ready");
  const stale = chainView({ pick, requests: [], review, plan: { ...plan, blocked_at: "2026-11-02", blocked_reason: "evidence_edited: 근거가 바뀌었습니다" } });
  assert.equal(stale.state, "invalidated");
  assert.equal(stale.reason, "근거가 바뀌었습니다");
});

test("이어 만들기 상태: 어디서 왜 멈췄는지 그대로 말한다", () => {
  const ins = chainView({ pick, requests: [req("evidence", "blocked", { error_code: "evidence_insufficient", error_message: "통과 1건\n출처를 붙이세요" })], review: null, plan: null });
  assert.equal(ins.state, "stopped");
  assert.equal(ins.code, "evidence_insufficient");
  assert.match(ins.reason!, /출처를 붙이세요/);
  const noBudget = chainView({ pick, requests: [req("evidence", "blocked", { error_code: "budget_missing" })], review: null, plan: null });
  assert.match(noBudget.label, /결재/);
  const check = chainView({ pick, requests: [req("plan", "blocked", { error_code: "script_check_failed", error_message: "처방을 지어냄" })], review, plan: null });
  assert.match(check.label, /대본 검사/);
  assert.equal(check.reason, "처방을 지어냄");
  const card = chainView({ pick: { format_intent: "card" }, requests: [req("evidence", "succeeded", { result: { chain: { queued: false, code: "card_plan_not_built", message: "카드뉴스 대본 자동 작성은 아직 없습니다" } } })], review, plan: null });
  assert.equal(card.code, "card_plan_not_built");
  assert.match(card.reason!, /카드뉴스/);
  const meme = chainView({ pick: { format_intent: "meme" }, requests: [], review: null, plan: null });
  assert.equal(meme.code, "meme_board");
  assert.equal(chainView({ pick, requests: [], review: null, plan: null }).code, "not_started");
  assert.equal(chainView({ pick: null, requests: [], review: null, plan: null }).state, "none");
});

test("표시 없는 대본·다른 근거 버전의 대본은 이어 만들기 대본이 아니다", () => {
  assert.equal(usableDraftPlan(plan, review), true);
  assert.equal(usableDraftPlan({ ...plan, drafted_from_unapproved: false }, review), false, "옛 흐름 대본");
  assert.equal(usableDraftPlan({ ...plan, topic_review_id: "r0" }, review), false, "옛 근거 버전");
  assert.equal(usableDraftPlan(plan, { id: "r1", status: "approved" }), false);
  assert.equal(usableDraftPlan(null, review), false);
  assert.equal(chainView({ pick, requests: [req("plan", "succeeded")], review, plan: { ...plan, topic_review_id: "r0" } }).state, "stopped");
});

const clean: ApprovalInput = {
  pick, chain: { state: "ready", label: "준비", reason: null }, dirty: false, blockers: [], score: 80, selectThreshold: 65,
  scoreException: "", formatFit: 3, fitMin: 2, fitException: "", amountUsd: 8.9,
};
const locks = (o: Partial<ApprovalInput>) => approvalLocks({ ...clean, ...o }, blockerLabel);

test("승인 버튼: 모든 조건이 맞을 때만 열리고, 잠길 때는 이유가 쉬운 말로 나온다", () => {
  assert.deepEqual(locks({}), []);
  assert.match(locks({ pick: null })[0], /\[이걸로\]/);
  assert.match(locks({ pick: { format_intent: "meme" } })[0], /밈 보드/);
  assert.deepEqual(locks({ pick: { format_intent: "card" }, amountUsd: 0 }), [], "카드뉴스는 0원이라 승인 금액을 받지 않는다");
  assert.match(locks({ pick: { format_intent: "card" }, formatFit: 1 })[0], /카드뉴스 적합성/);
  assert.match(locks({ amountUsd: 0 })[0], /승인 금액/);
  assert.match(locks({ chain: { state: "running", label: "대본을 만드는 중입니다", reason: null } })[0], /만드는 중/);
  assert.match(locks({ chain: { state: "invalidated", label: "근거가 바뀌어 대본이 무효가 됐습니다", reason: "다시 만드세요" } })[0], /무효.*다시 만드세요/);
  assert.match(locks({ dirty: true })[0], /저장/);
  const support = locks({ blockers: ["claim_support_not_reviewed:c1", "brief_takeaway_missing"] });
  assert.equal(support.length, 2);
  assert.ok(support.every((x) => !x.startsWith("claim_support") && !x.startsWith("brief_")), "코드가 아니라 문장으로 나온다");
  assert.match(support[0], /\[c1\]/);
  assert.match(locks({ score: 60 })[0], /60점/);
  assert.deepEqual(locks({ score: 60, scoreException: "시즌 소재" }), []);
  assert.match(locks({ formatFit: 1 })[0], /적합성/);
  assert.deepEqual(locks({ formatFit: 1, fitException: "화면이 단순" }), []);
  assert.match(locks({ amountUsd: 0 })[0], /승인 금액/);
  assert.match(locks({ amountUsd: 10.5 })[0], /승인 금액/);
  assert.match(locks({ amountUsd: Number("abc") })[0], /승인 금액/);
});

test("근거 내용 변경 경고: 주장 문장·핵심 선택만 무효 사유다(주장별 확인·순서는 아니다)", () => {
  const a = { claims: [{ claim_id: "c1", text: "가" }, { claim_id: "c2", text: "나" }], selected: ["c1", "c2"] };
  assert.equal(evidenceContentChanged(a, { claims: [...a.claims].reverse(), selected: ["c2", "c1"] }), false);
  assert.equal(evidenceContentChanged(a, { claims: [{ claim_id: "c1", text: "다" }, a.claims[1]], selected: a.selected }), true);
  assert.equal(evidenceContentChanged(a, { claims: a.claims, selected: ["c1"] }), true);
});

test("장면 지시: §3-4 칸이 있으면 보여 주고 없으면 비운다", () => {
  assert.deepEqual(sceneDirective({ narration: "x" }), []);
  const d = sceneDirective({ visual_claim_ko: "에탄올이 미생물을 억제한다", forbidden_misreading: " ", depiction_label: "설명용 도해", answers_ko: "왜 안 상하나" });
  assert.deepEqual(d.map((x) => x.value), ["에탄올이 미생물을 억제한다", "설명용 도해", "왜 안 상하나"]);
});

test("형식 대응표: 설명형=영상, 카드뉴스=카드, 밈=아직 없음", () => {
  assert.deepEqual(INTENT_TO_FORMAT, { explainer: "video", card: "carousel", meme: null });
});

test("다음 행동: 준비된 초안은 내용 승인으로, 무효면 다시 만들기로, [이걸로] 뒤 대기는 그 화면으로. 다른 소재는 그대로", () => {
  assert.equal(contentApprovalState("researching", { id: "r1", status: "draft" }, plan as never, pick), "ready");
  assert.equal(contentApprovalState("researching", { id: "r1", status: "in_review" }, plan as never, pick), "ready");
  assert.equal(contentApprovalState("researching", { id: "r1", status: "draft" }, { ...plan, blocked_at: "t" } as never, pick), "invalidated");
  assert.equal(contentApprovalState("researching", null, null, pick), "waiting");
  assert.equal(contentApprovalState("researching", null, null, { format_intent: "meme" }), "waiting");
  assert.equal(contentApprovalState("researching", null, null, { format_intent: "card" }), "waiting", "카드뉴스도 내용 승인으로 간다(0065)");
  assert.equal(contentApprovalState("researching", { id: "r1", status: "draft" }, null, null), null, "[이걸로]를 안 눌렀으면 기존 흐름");
  assert.equal(contentApprovalState("selected", { id: "r1", status: "approved" }, plan as never, pick), null, "승인 뒤에는 기존 흐름");
  assert.equal(contentApprovalState("researching", { id: "r1", status: "approved" }, plan as never, pick), "waiting", "옛 탭으로 근거를 승인한 뒤 철회된 경우 — 무효 대본이 없으면 [이걸로] 상태만 본다");

  const base: NextActionInput = { status: "researching", reviewStatus: "draft", reviewRevoked: false, reviewBlockers: 3, approvalValid: false, selectedFormats: [], plans: {} };
  const ready = nextAction({ ...base, contentApproval: "ready" });
  assert.equal(ready.label, "내용 승인");
  assert.equal(ready.tab, "approval");
  assert.equal(nextAction({ ...base, contentApproval: "invalidated" }).label, "대본 다시 만들기");
  assert.equal(nextAction({ ...base, contentApproval: "waiting" }).tab, "approval");
  assert.equal(nextAction({ ...base, contentApproval: null }).label, "근거 검토", "표시가 없으면 옛 흐름 그대로");
  assert.equal(nextAction(base).label, "근거 검토");
});
