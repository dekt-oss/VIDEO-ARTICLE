// 소재 개발 화면 순수 계산 테스트 (node --test).
import test from "node:test";
import assert from "node:assert/strict";
import {
  developButtons, developErrorView, isActive, isSchemaMissing, pickBudget, requestNote, resultLinks, sortRequests, statusTone, usableBudgets,
  type DevelopBudgetRow,
} from "./develop.ts";

const NOW = Date.parse("2026-10-30T00:00:00Z");
const budget = (o: Partial<DevelopBudgetRow> = {}): DevelopBudgetRow => ({
  budget_id: "b1", stage: "0단계", cap_usd: 1, spent_usd: 0, held_usd: 0, remaining_usd: 1, status: "open",
  expires_at: "2026-11-05T00:00:00Z", approver_words: "승인", ...o,
});

test("쓸 수 있는 결재: 열림 + 기한 안 지남 + 남은 금액 > 0", () => {
  const rows = [
    budget({ budget_id: "ok" }),
    budget({ budget_id: "closed", status: "closed" }),
    budget({ budget_id: "expired", expires_at: "2026-10-01T00:00:00Z" }),
    budget({ budget_id: "empty", remaining_usd: "0" }),
  ];
  assert.deepEqual(usableBudgets(rows, NOW).map((b) => b.budget_id), ["ok"]);
});

test("결재 고르기: 남은 금액이 큰 것, 같으면 기한이 늦은 것, 없으면 null(문자열 숫자도 허용)", () => {
  assert.equal(pickBudget([], NOW), null);
  assert.equal(pickBudget([budget({ status: "closed" })], NOW), null);
  const a = budget({ budget_id: "a", remaining_usd: "0.50" });
  const b = budget({ budget_id: "b", remaining_usd: "2.00" });
  const c = budget({ budget_id: "c", remaining_usd: "2.00", expires_at: "2026-12-01T00:00:00Z" });
  assert.equal(pickBudget([a, b], NOW)?.budget_id, "b");
  assert.equal(pickBudget([a, b, c], NOW)?.budget_id, "c");
});

test("버튼: 결재가 없으면 둘 다 잠기고 이유를 말한다", () => {
  const r = developButtons({ topicStatus: "researching", hasBudget: false, approvedEvidence: true, requests: [] });
  assert.equal(r.evidence.enabled, false);
  assert.match(r.evidence.reason ?? "", /결재/);
  assert.equal(r.plan.enabled, false);
  assert.match(r.plan.reason ?? "", /결재/);
});

test("버튼: 결재가 있으면 근거 초안은 열리고, 대본 초안은 승인된 근거가 있어야 열린다", () => {
  const noApproval = developButtons({ topicStatus: "researching", hasBudget: true, approvedEvidence: false, requests: [] });
  assert.equal(noApproval.evidence.enabled, true);
  assert.equal(noApproval.evidence.reason, null);
  assert.equal(noApproval.plan.enabled, false);
  assert.match(noApproval.plan.reason ?? "", /승인/);
  const approved = developButtons({ topicStatus: "ready", hasBudget: true, approvedEvidence: true, requests: [] });
  assert.equal(approved.plan.enabled, true);
});

test("버튼: 같은 종류의 대기·진행 요청이 있으면 그 종류만 잠긴다(끝난 요청은 막지 않는다)", () => {
  const base = { topicStatus: "researching", hasBudget: true, approvedEvidence: true } as const;
  const ev = developButtons({ ...base, requests: [{ kind: "evidence", status: "running" }] });
  assert.equal(ev.evidence.enabled, false);
  assert.equal(ev.plan.enabled, true);
  const pl = developButtons({ ...base, requests: [{ kind: "plan", status: "queued" }] });
  assert.equal(pl.plan.enabled, false);
  assert.equal(pl.evidence.enabled, true);
  const done = developButtons({
    ...base,
    requests: [{ kind: "evidence", status: "failed" }, { kind: "plan", status: "succeeded" }, { kind: "plan", status: "canceled" }, { kind: "plan", status: "blocked" }],
  });
  assert.equal(done.evidence.enabled && done.plan.enabled, true);
});

test("버튼: 보류·제외·중복 소재는 둘 다 잠긴다", () => {
  for (const s of ["on_hold", "rejected", "duplicate"]) {
    const r = developButtons({ topicStatus: s, hasBudget: true, approvedEvidence: true, requests: [] });
    assert.equal(r.evidence.enabled || r.plan.enabled, false, s);
  }
});

test("활성 상태는 queued·running 뿐", () => {
  for (const s of ["queued", "running"] as const) assert.equal(isActive({ status: s }), true);
  for (const s of ["succeeded", "failed", "canceled", "blocked"] as const) assert.equal(isActive({ status: s }), false);
});

test("상태 색: 성공 초록 / 실패 빨강 / 막힘 주황 / 나머지 중립", () => {
  assert.equal(statusTone("succeeded"), "ok");
  assert.equal(statusTone("failed"), "bad");
  assert.equal(statusTone("blocked"), "warn");
  assert.equal(statusTone("queued"), "info");
  assert.equal(statusTone("canceled"), "info");
});

test("오류 문장: 알려진 코드는 쉬운 말 + 사유 원문, 모르는 코드는 원문 그대로", () => {
  const ev = developErrorView("evidence_insufficient", "official sources 2");
  assert.match(ev!.text, /공식 근거가 3개 미만/);
  assert.equal(ev!.detail, "official sources 2");
  assert.match(developErrorView("budget_missing", null)!.text, /결재/);
  assert.match(developErrorView("budget_exceeded", null)!.text, /결재 금액/);
  const sc = developErrorView("script_check_failed", "숫자 불일치 2건");
  assert.match(sc!.text, /두 번 막혔/);
  assert.equal(sc!.detail, "숫자 불일치 2건");
  assert.deepEqual(developErrorView("weird_code", "boom"), { text: "weird_code: boom", detail: null });
  assert.deepEqual(developErrorView(null, "메시지만"), { text: "메시지만", detail: null });
  assert.equal(developErrorView(null, null), null);
  assert.equal(developErrorView("", "  "), null);
});

test("결과 링크: 근거는 근거 탭, 대본은 제작안 형식 탭(모르면 영상)", () => {
  const plans = [{ id: "p1", format: "carousel" }, { id: "p2", format: "video" }];
  assert.deepEqual(resultLinks("t", { result_review_id: "r", result_plan_revision_id: null }, plans), [
    { label: "근거 초안 보기", href: "/drinks/review/t?tab=evidence" },
  ]);
  assert.equal(resultLinks("t", { result_review_id: null, result_plan_revision_id: "p1" }, plans)[0].href, "/drinks/review/t?tab=carousel");
  assert.equal(resultLinks("t", { result_review_id: null, result_plan_revision_id: "p2" }, plans)[0].href, "/drinks/review/t?tab=video");
  assert.equal(resultLinks("t", { result_review_id: null, result_plan_revision_id: "zz" }, plans)[0].href, "/drinks/review/t?tab=video");
  assert.deepEqual(resultLinks("t", { result_review_id: null, result_plan_revision_id: null }, plans), []);
});

test("요청 목록은 최신순", () => {
  const rows = [
    { request_id: "a", created_at: "2026-10-29T00:00:00Z" },
    { request_id: "b", created_at: "2026-10-30T00:00:00Z" },
    { request_id: "c", created_at: "2026-10-28T00:00:00Z" },
  ];
  assert.deepEqual(sortRequests(rows).map((r) => r.request_id), ["b", "a", "c"]);
});

test("0060 미적용 오류 판별: 코드로도 문장으로도, 다른 오류는 아니다", () => {
  for (const code of ["42883", "42P01", "PGRST202", "PGRST205"]) assert.equal(isSchemaMissing({ code, message: "x" }), true, code);
  assert.equal(isSchemaMissing({ message: "Could not find the function public.drinks_develop_status(p) in the schema cache" }), true);
  assert.equal(isSchemaMissing({ message: '개발 결재: relation "drink_develop_budget_state" does not exist' }), true);
  assert.equal(isSchemaMissing({ message: "permission denied for table drink_topics" }), false);
  assert.equal(isSchemaMissing({ message: "relation \"drink_topics\" does not exist" }), false);
  assert.equal(isSchemaMissing(null), false);
});

test("요청 직후 안내: 이미 있음 / 워커 깨움 / 다음 실행 대기", () => {
  assert.match(requestNote({ existing: true }), /이미/);
  assert.match(requestNote({ triggered: true }), /깨웠/);
  assert.match(requestNote({ triggered: false }), /다음 실행/);
  assert.match(requestNote({}), /다음 실행/);
});
