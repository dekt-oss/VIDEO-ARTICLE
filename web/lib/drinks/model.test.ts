// 주류 공장 화면 모델 순수 테스트. 실행: `node --test web/lib/drinks/*.test.ts`
import test from "node:test";
import assert from "node:assert/strict";
import {
  weightedScore, fitOk, nextAction, actionRank, blockerLabel, fromQuery, nextMonday, deriveTopic, originSummary,
  planCoverage, effectiveMeta,
  type NextActionInput,
} from "./model.ts";

const full = { relevance: 4, utility: 4, curiosity: 4, fit_video: 4, fit_carousel: 0, timeliness: 4 };

test("가중 합: 만점 100, 형식 적합은 두 형식 중 높은 값, 축 누락은 null(0으로 채우지 않음)", () => {
  assert.equal(weightedScore(full), 100);
  assert.equal(weightedScore({ ...full, fit_video: 0, fit_carousel: 4 }), 100);
  assert.equal(weightedScore({ relevance: 4, utility: 3, curiosity: 3, fit_video: 1, fit_carousel: 4, timeliness: 2 }), 83.75);
  assert.equal(weightedScore({ relevance: 4 }), null);
  assert.equal(weightedScore(null), null);
});

test("형식 적합성 기준 2점", () => {
  assert.equal(fitOk({ fit_video: 1, fit_carousel: 4 }, "video"), false);
  assert.equal(fitOk({ fit_video: 1, fit_carousel: 4 }, "carousel"), true);
  assert.equal(fitOk(null, "carousel"), false);
});

const base: NextActionInput = {
  status: "researching", reviewStatus: null, reviewRevoked: false, reviewBlockers: 0, approvalValid: false,
  selectedFormats: [], plans: {},
};

test("다음 행동: 상태마다 하나", () => {
  assert.equal(nextAction({ ...base, status: "inbox" }).label, "경량 평가");
  assert.equal(nextAction({ ...base, status: "triaged" }).label, "조사하기");
  assert.equal(nextAction(base).label, "근거 작성");
  assert.equal(nextAction({ ...base, reviewStatus: "draft", reviewBlockers: 2 }).label, "근거 검토");
  assert.equal(nextAction({ ...base, reviewStatus: "draft" }).label, "기획 검토 요청");
  assert.equal(nextAction({ ...base, reviewStatus: "in_review" }).label, "기획 승인");
  assert.equal(nextAction({ ...base, status: "ready", reviewStatus: "approved", approvalValid: true }).label, "편성");
  assert.equal(nextAction({ ...base, reviewStatus: "approved", reviewRevoked: true }).label, "새 버전 작성");
  // 정책 ③: 승인 뒤 보충 초안이 있어도 편성 가능 상태는 유지되고, 힌트가 그 사실을 알려준다
  const supp = nextAction({ ...base, status: "ready", reviewStatus: "draft", approvalValid: true });
  assert.equal(supp.label, "기획 검토 요청");
  assert.match(supp.hint, /편성할 수도/);
  assert.equal(nextAction({ ...base, status: "rejected" }).label, "다시 열기");
});

test("다음 행동: 편성 후에는 형식별로, 둘 다 승인되면 '제작 요청'은 미연결로 잠긴다", () => {
  const sel = { ...base, status: "selected" as const, reviewStatus: "approved" as const, approvalValid: true, selectedFormats: ["video", "carousel"] as ("video" | "carousel")[] };
  assert.equal(nextAction(sel).label, "영상 제작안 작성");
  assert.equal(nextAction({ ...sel, plans: { video: { status: "approved", blocked: false, evidenceValid: true } } }).label, "카드뉴스 제작안 작성");
  assert.equal(nextAction({ ...sel, plans: { video: { status: "approved", blocked: true, evidenceValid: true } } }).label, "영상 제작안 작성");
  const done = nextAction({ ...sel, plans: { video: { status: "approved", blocked: false, evidenceValid: true }, carousel: { status: "approved", blocked: false, evidenceValid: true } } });
  assert.equal(done.label, "제작 요청");
  assert.equal(done.unavailable, true);
  assert.ok(actionRank(done, "selected") > actionRank(nextAction({ ...base, reviewStatus: "in_review" }), "researching"));
});

test("차단 사유 이름표: 주장 id 를 앞에 붙인다", () => {
  assert.equal(blockerLabel("claim_quote_unmatched:c2"), "[c2] 발췌가 원문에서 확인되지 않았습니다");
  assert.equal(blockerLabel("no_core_claims"), "핵심 주장을 하나 이상 고르세요");
  assert.equal(blockerLabel("new_code_x"), "new_code_x");
});

test("최종 보완 결함2: 제작안이 참조하는 근거가 무효면 '모두 승인·제작 요청'으로 안내하지 않는다", () => {
  const topic = { id: "t1", status: "selected", current_review_id: "r2", approved_review_id: "r2", selected_review_id: "r2",
    selected_formats: ["carousel"], provisional_score: "70", provisional_scores: null } as never;
  const rv = (id: string, valid: boolean) => ({ id, status: "approved", revoked_at: null, readiness: { blockers: [], warnings: [] },
    score: "80", scores: { fit_carousel: 4 }, currently_valid: valid, current_blockers: valid ? [] : ["claim_expired:c1"] });
  const deliverables = [{ id: "d1", topic_id: "t1", format: "carousel", current_revision_id: "p1" }] as never;
  // P1 은 정책대로 옛 근거 R1 을 계속 참조한다
  const plans = new Map([["p1", { id: "p1", plan_status: "approved", blocked_at: null, topic_review_id: "r1" }]]) as never;
  const bad = deriveTopic(topic, new Map([["r1", rv("r1", false)], ["r2", rv("r2", true)]]) as never, deliverables, plans);
  assert.equal(bad.selectedValid, true, "편성 버전 R2 는 유효");
  assert.equal(bad.action.label, "카드뉴스 근거 재확인");
  assert.equal(bad.planEvidenceValid.carousel, false, "선별 편성함·상세 배지가 쓰는 같은 판정");
  assert.notEqual(bad.action.label, "제작 요청");
  const good = deriveTopic(topic, new Map([["r1", rv("r1", true)], ["r2", rv("r2", true)]]) as never, deliverables, plans);
  assert.equal(good.action.label, "제작 요청", "둘 다 유효면 기존대로");
  assert.equal(good.planEvidenceValid.carousel, true);
  const lost = deriveTopic(topic, new Map([["r2", rv("r2", true)]]) as never, deliverables, plans);
  assert.ok(lost.missingPointers.includes("카드뉴스 제작안의 근거 버전"), "근거 행 누락은 조회 누락");
  assert.notEqual(lost.action.label, "제작 요청");
  const blocked = new Map([["p1", { id: "p1", plan_status: "approved", blocked_at: "2026-10-22", topic_review_id: "r1" }]]) as never;
  assert.equal(deriveTopic(topic, new Map([["r1", rv("r1", true)], ["r2", rv("r2", true)]]) as never, deliverables, blocked).action.label,
    "카드뉴스 제작안 작성", "재확인으로 근거가 유효해져도 차단된 제작안은 차단 그대로");
});

test("원출처: 운영자가 묶은 것만 독립 원출처로 센다(같은 본문·같은 URL 자동 묶음 없음)", () => {
  const o = originSummary([
    { id: "s1", origin_group: null }, { id: "s2", origin_group: null },
    { id: "s3", origin_group: "보도자료A" }, { id: "s4", origin_group: "보도자료A" }, { id: "s5", origin_group: "NTA" },
  ]);
  assert.deepEqual(o, { total: 5, confirmedGroups: 2, unconfirmed: 2 });
});

test("결함1: 표지·출처·전환에 붙은 필수 주장은 전달로 세지 않는다", () => {
  const coverOnly = planCoverage("carousel", [{ role: "cover", claim_ids: ["c1", "c2"] }, { role: "source", claim_ids: ["c1"] }], ["c1", "c2"]);
  assert.equal(coverOnly.ok, false);
  assert.deepEqual(coverOnly.covered, []);
  assert.deepEqual(coverOnly.reference_only, ["c1", "c2"]);
  assert.equal(planCoverage("video", [{ content_kind: "transition", claim_ids: ["c1"] }], ["c1"]).ok, false);
  const mixed = planCoverage("carousel", [{ role: "cover", claim_ids: ["c2"] }, { role: "explain", claim_ids: ["c1"] }], ["c1", "c2"]);
  assert.deepEqual(mixed.missing_required, ["c2"]);
  assert.equal(planCoverage("carousel", [{ role: "cover", claim_ids: ["c1"] }, { role: "explain", claim_ids: ["c1", "c2"] },
    { role: "source" }], ["c1", "c2"]).ok, true);
});

test("제작안 근거 전달: 사실 항목 주장 누락·필수 주장 누락, 표지·출처·전환은 주장 없이 통과", () => {
  const pages = [{ role: "cover" }, { role: "explain", claim_ids: ["c1"] }, { role: "compare", claim_ids: [] }, { role: "source" }];
  const c = planCoverage("carousel", pages, ["c1", "c2"]);
  assert.deepEqual(c.facts_without_claims, [3]);
  assert.deepEqual(c.missing_required, ["c2"]);
  assert.equal(c.ok, false);
  assert.equal(planCoverage("carousel", [{ role: "cover" }, { role: "explain", claim_ids: ["c1", "c2"] }], ["c1", "c2"]).ok, true);
  assert.equal(planCoverage("video", [{ content_kind: "transition" }, { claim_ids: ["c1"] }], ["c1"]).ok, true);
  assert.deepEqual(planCoverage("video", [{}], ["c1"]).facts_without_claims, [1], "content_kind 생략은 사실 장면");
  assert.equal(planCoverage("carousel", [{ role: "cover" }], []).ok, false, "필수 주장이 정의되지 않으면 승인 불가");
});

test("출처 유효 정보: 원문 값 위에 정정·확인 기록을 시간순으로 덮는다", () => {
  // 같은 트랜잭션이라 시각이 같아도 기록 순번(seq)대로 적용한다 — id(UUID) 순서는 쓰지 않는다
  const m = effectiveMeta({ rights_status: "unknown", publisher: null, checked_at: "2026-10-01" }, [
    { seq: 12, fields: { publisher: "OO양조" } },
    { seq: 11, fields: { rights_status: "quote_ok", checked_at: "2026-10-02" } },
  ]);
  assert.equal(effectiveMeta({ rights_status: "unknown" }, [{ seq: 2, fields: { rights_status: "restricted" } },
    { seq: 1, fields: { rights_status: "quote_ok" } }]).rights_status, "restricted", "확인→철회면 최종 철회");
  assert.equal(m.rights_status, "quote_ok");
  assert.equal(m.publisher, "OO양조");
  assert.equal(m.checked_at, "2026-10-02");
  assert.equal(m.attestationCount, 2);
});

test("조회 실패는 빈 목록이 아니다", () => {
  assert.deepEqual(fromQuery({ data: [], error: null }, "소재"), { state: "ok", data: [] });
  assert.equal(fromQuery({ data: null, error: { message: "boom" } }, "소재").state, "failed");
  assert.equal(fromQuery({ data: null, error: null }, "소재").state, "failed");
});

test("편성 주차 기본값은 다음 주 월요일", () => {
  assert.equal(nextMonday("2026-10-22"), "2026-10-26"); // 목 → 다음 월
  assert.equal(nextMonday("2026-10-26"), "2026-11-02"); // 월 → 그다음 월
  assert.equal(nextMonday("2026-11-01"), "2026-11-02"); // 일 → 다음날 월
});

test("deriveTopic: 형식별 현재 제작안을 따로 본다", () => {
  const topic = {
    id: "t1", status: "selected", current_review_id: "r1", approved_review_id: "r1", selected_review_id: "r1",
    selected_formats: ["video", "carousel"],
    provisional_score: "70.00", provisional_scores: null,
  } as never;
  const review = { id: "r1", status: "approved", revoked_at: null, readiness: { blockers: [], warnings: [] }, score: "83.75",
    scores: { fit_video: 3, fit_carousel: 4 }, currently_valid: true, current_blockers: [] } as never;
  const deliverables = [
    { id: "d1", topic_id: "t1", format: "video", current_revision_id: "p1" },
    { id: "d2", topic_id: "t1", format: "carousel", current_revision_id: "p2" },
  ] as never;
  const plans = new Map([
    ["p1", { id: "p1", plan_status: "approved", blocked_at: null, topic_review_id: "r1" }],
    ["p2", { id: "p2", plan_status: "in_review", blocked_at: null, topic_review_id: "r1" }],
  ]) as never;
  const d = deriveTopic(topic, new Map([["r1", review]]), deliverables, plans);
  assert.equal(d.action.label, "카드뉴스 제작안 승인");
  assert.equal(d.finalScore, 83.75);
  assert.equal(d.provisionalScore, 70);
  assert.deepEqual(d.missingPointers, []);
  const lost = deriveTopic({ ...(topic as object), current_review_id: "r9" } as never, new Map([["r1", review]]), deliverables, plans);
  assert.deepEqual(lost.missingPointers, ["현재 근거·기획 버전"], "포인터가 가리키는 행이 없으면 '없음'이 아니라 누락");

  // 결함2-⑤: 승인 기록이 있어도 지금 쓸 수 없으면(권리 철회·유효 기한) 사용 가능으로 보이지 않는다
  const stale = { ...(review as object), currently_valid: false, current_blockers: ["claim_rights_unconfirmed:c1"] } as never;
  const d2 = deriveTopic(topic, new Map([["r1", stale]]), deliverables, plans);
  assert.equal(d2.approvalValid, false);
  assert.equal(d2.selectedValid, false);
  assert.equal(d2.action.label, "근거 재확인");
  const ready = deriveTopic({ ...(topic as object), status: "ready" } as never, new Map([["r1", stale]]), [] as never, new Map() as never);
  assert.notEqual(ready.action.label, "편성", "지금 쓸 수 없는 승인으로 편성을 권하지 않는다");
  const unknown = { ...(review as object), currently_valid: undefined } as never;
  assert.equal(deriveTopic(topic, new Map([["r1", unknown]]), deliverables, plans).approvalValid, false, "판정이 없으면 유효로 보지 않는다");
});
