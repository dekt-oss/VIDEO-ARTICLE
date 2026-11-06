// 순수 로직 테스트. 실행: `cd web && node --test lib/drinks/work/decision.test.ts`
//
// 작업명세서 v2 §7 의 모든 줄(B1~B8 · S1~S24)과 형식 분기를 표로 고정한다. 한 줄 = 한 상태 = 주 버튼 하나.
import { test } from "node:test";
import assert from "node:assert/strict";
import { decide, homeTier, rankForHome, snoozeKey, JUDGMENT_STEPS } from "./decision.ts";
import type { Decision, FormatIntent, WorkItem } from "./types.ts";
import type { EpisodeState, ExplainerStatus, ExplainerSlot, ExplainerCandidate } from "../explainerQueue.ts";
import { nextAction } from "../model.ts";

const NOW = new Date("2026-11-05T03:00:00Z"); // 2026-11-05 12:00 KST (수요일). 이번 주 월요일 = 11-02.
const TOPIC = "11111111-1111-4111-8111-111111111111";

function item(over: Partial<WorkItem> = {}): WorkItem {
  const intent: FormatIntent = over.format_intent ?? "explainer";
  return {
    unit_id: `topic:${TOPIC}:${intent}`, topic_id: TOPIC, title: "소재", question: null, topic_status: "selected", topic_version: 1,
    format_intent: intent, source: "topic", editorial_week: "2026-11-02", pick_approved_at: "2026-11-01T00:00:00Z", pick_amount_usd: 3,
    review_id: null, review_status: null, review_valid: null, review_version: null,
    develop_kind: null, develop_status: null, develop_request_id: null, develop_error_code: null,
    plan_revision_id: null, plan_status: null, plan_blocked: null, plan_version: null, plan_format: null,
    job_id: null, job_status: null, job_error_code: null, explainer_state: null,
    output_review_id: null, output_review_status: null, output_usable: null,
    meme_draft_id: null, meme_status: null, meme_sync_grade: null, meme_external_url: null,
    pub_request_id: null, pub_status: null, pub_pause_code: null, pub_publish_at: null, pub_external_url: null, pub_version: null,
    unknown_billed: false, orphan_hold: false, updated_at: "2026-11-04T00:00:00Z",
    ...over,
  };
}
/** 근거·제작안 있음(승인 대기). */
const withPlan = (intent: FormatIntent, plan_status = "draft", over: Partial<WorkItem> = {}) => item({
  format_intent: intent, review_id: "r1", review_status: "approved", review_valid: true, review_version: 2,
  develop_kind: "plan", develop_status: "succeeded", develop_request_id: "d2",
  plan_revision_id: "p1", plan_status, plan_blocked: false, plan_version: 1, plan_format: intent === "card" ? "carousel" : "video", ...over,
});
const approvedPlan = (intent: FormatIntent, over: Partial<WorkItem> = {}) => withPlan(intent, "approved", over);
const memeCard = (meme_status: string | null, over: Partial<WorkItem> = {}) => item({
  unit_id: "meme_card:m1", topic_id: null, source: "card", format_intent: "meme", meme_draft_id: "m1", meme_status, topic_status: null, editorial_week: null, ...over,
});
const d = (it: WorkItem, ex?: ExplainerStatus | null) => decide(it, ex, NOW);
const code = (it: WorkItem, ex?: ExplainerStatus | null) => d(it, ex).primary.code;

function exStatus(state: string, over: Partial<ExplainerStatus> = {}): ExplainerStatus {
  return {
    is_explainer: true, approved_amount_usd: 3, slots: [], approvals: [], unknown_attempts: [],
    episode: { plan_revision_id: "p1", state: state as EpisodeState,
      provider: "veo", directive: null, order_hash: null, approval_id: null, buy_through_n: null, last_code: null, last_message: null, process_review: null, quality_review: null, version: 1 },
    ...over,
  };
}
const openApproval = { approval_id: "a1", stage: "buy", cap_usd: 5, allowed_kinds: ["image", "video"], status: "open" as const, expired: false, expires_at: "2027-01-01", remaining_usd: 5, held_usd: 0, spent_usd: 0, order_hash: null };
const cand = (over: Partial<ExplainerCandidate>): ExplainerCandidate => ({ candidate_id: "c1", k: 1, status: "stored", cost_usd: 0.5, auto_verdict: "pass", human_verdict: null, auto_report: null, asset: null, attempts: [], ...over });
const slot = (status: string, candidates: ExplainerCandidate[], selection: ExplainerSlot["selection"] = null): ExplainerSlot =>
  ({ slot_id: "s1", n: 1, role: "reality", status, min_src_ms: 3000, candidates_planned: 2, boundary_in: null, boundary_out: null, image_usd: 0.1, selection, candidates });

// ── ① 식별 실패 → needs_review (초안 생성으로 떨어지지 않는다) ──
test("① 식별 실패는 전부 needs_review 이고 S1 로 떨어지지 않는다", () => {
  const cases: [string, WorkItem][] = [
    ["형식 의도 없음", item({ format_intent: "" as FormatIntent })],
    ["소재 id 없음", item({ topic_id: null })],
    ["카드 소유인데 밈 아님", item({ source: "card", format_intent: "card", meme_draft_id: "m" })],
    ["카드 밈인데 제작안 id 없음", item({ source: "card", format_intent: "meme", meme_draft_id: null })],
    ["설명형인데 제작안이 carousel", withPlan("explainer", "draft", { plan_format: "carousel" })],
    ["소유자 모름", item({ source: "nobody" as WorkItem["source"] })],
  ];
  for (const [why, it] of cases) {
    const r = d(it);
    assert.equal(r.primary.code, "needs_review", why);
    assert.match(r.primary.label, /^확인 필요/, why);
    assert.notEqual(r.primary.code, "S1", why);
  }
  // 카드 릴스(0065)는 카드 + video 가 정상이다.
  assert.notEqual(code(withPlan("card", "draft", { plan_format: "video" })), "needs_review");
});

// ── ② 차단 B1~B8 ──
test("② 차단은 B1~B8 순서로 쌓이고 주 버튼은 첫 차단이다", () => {
  const table: [string, Partial<WorkItem>, string][] = [
    ["publish_unknown", { pub_request_id: "q", pub_status: "unknown", pub_version: 1 }, "B1"],
    ["spend_unknown(unknown_billed)", { unknown_billed: true }, "B2"],
    ["spend_unknown(orphan_hold)", { orphan_hold: true }, "B2"],
    ["spend_unknown(explainer_state)", { explainer_state: "unknown_billed" }, "B2"],
    ["evidence_invalid(review_valid=false)", { review_valid: false }, "B3"],
    ["evidence_invalid(plan_blocked)", { plan_blocked: true }, "B3"],
    ["evidence_invalid(output_usable=false)", { output_review_id: "o", output_usable: false }, "B3"],
    ["digest_mismatch", { pub_request_id: "q", pub_status: "paused", pub_pause_code: "digest_changed" }, "B4"],
    ["digest_mismatch(meme)", { pub_request_id: "q", pub_status: "paused", pub_pause_code: "meme_digest_changed" }, "B4"],
    ["publish_blocked(paused)", { pub_request_id: "q", pub_status: "paused", pub_pause_code: "late" }, "B5"],
    ["publish_blocked(failed)", { pub_request_id: "q", pub_status: "failed" }, "B5"],
    ["budget_blocked", { explainer_state: "blocked_budget" }, "B6"],
    ["no_pass", { explainer_state: "blocked_no_pass" }, "B7"],
    ["develop_blocked(blocked)", { develop_kind: "evidence", develop_status: "blocked", develop_request_id: "d" }, "B8"],
    ["develop_blocked(failed)", { develop_kind: "plan", develop_status: "failed", develop_request_id: "d", develop_error_code: "llm_timeout" }, "B8"],
  ];
  for (const [name, over, expected] of table) {
    const r = d(approvedPlan("explainer", over));
    assert.equal(r.primary.code, expected, name);
    assert.equal(r.blocks.length, 1, name);
    assert.equal(r.primary.action, null, `${name}: 차단 버튼은 서버 호출을 미리 채우지 않는다`);
  }
  // 산출물 검수가 없으면 output_usable 이 null/false 라도 B3 가 아니다(검사 대상이 없다).
  assert.notEqual(code(approvedPlan("card", { output_usable: false })), "B3");
  // 지문 불일치는 B4 하나로 세고 B5 로 겹쳐 세지 않는다.
  const both = d(approvedPlan("card", { pub_request_id: "q", pub_status: "paused", pub_pause_code: "digest_changed" }));
  assert.deepEqual(both.blocks.map((b) => b.code), ["digest_mismatch"]);
  // 여러 차단이 함께 있으면 순서가 B1 → B8 이다.
  const many = d(approvedPlan("explainer", { pub_request_id: "q", pub_status: "unknown", review_valid: false, explainer_state: "blocked_budget", develop_status: "failed", develop_request_id: "d" }));
  assert.deepEqual(many.blocks.map((b) => b.code), ["publish_unknown", "evidence_invalid", "budget_blocked", "develop_blocked"]);
  assert.equal(many.primary.code, "B1");
});

test("② 차단은 그 작업 단위에만 — 다른 형식의 끝난 단위는 그대로", () => {
  const blocked = d(approvedPlan("explainer", { explainer_state: "blocked_budget" }));
  const done = d(approvedPlan("card", { job_id: "j", job_status: "succeeded", output_review_id: "o", output_review_status: "approved", output_usable: true, pub_request_id: "q", pub_status: "published", pub_version: 3 }));
  assert.equal(blocked.primary.code, "B6");
  assert.equal(done.primary.code, "S20");
  assert.equal(done.blocks.length, 0);
});

// ── ③ 단계 S1~S24 — 형식별 표 ──
test("③ 설명형 S1~S4·S23", () => {
  assert.equal(code(item()), "S1");
  assert.equal(code(item({ develop_kind: "evidence", develop_status: "queued", develop_request_id: "d" })), "S2");
  assert.equal(code(item({ develop_kind: "evidence", develop_status: "running", develop_request_id: "d" })), "S2");
  assert.equal(d(item({ develop_kind: "evidence", develop_status: "running", develop_request_id: "d" })).primary.busy, true);
  assert.equal(code(item({ develop_kind: "evidence", develop_status: "succeeded", develop_request_id: "d", review_id: "r" })), "S3");
  assert.equal(code(withPlan("explainer", "draft")), "S4");
  assert.equal(code(withPlan("explainer", "in_review")), "S4");
  assert.equal(d(withPlan("explainer", "draft")).primary.panel, "approve");
  assert.equal(code(item({ topic_status: "on_hold" })), "S23");
  assert.equal(code(item({ topic_status: "rejected" })), "S23");
  assert.equal(code(withPlan("explainer", "approved", { pub_request_id: "q", pub_status: "canceled", pub_version: 1 })), "S23");
});

test("③ 설명형 S5~S14 는 explainerQueue.nextStep 에 위임한다", () => {
  const p = approvedPlan("explainer");
  // S5: 지시서 전(0원·멱등이라 action 을 채운다) / 지시서 나옴·결재 없음 → 결재 열기
  const s5a = d(p, exStatus("plan_draft"));
  assert.equal(s5a.primary.code, "S5");
  assert.deepEqual(s5a.primary.action, { name: "explainer_request_plan", payload: { plan_revision_id: "p1" } });
  const s5b = d(p, exStatus("directive_ready"));
  assert.equal(s5b.primary.code, "S5");
  assert.match(s5b.primary.label, /결재 열기/);
  assert.equal(s5b.primary.action, null);
  // S6: 결재 열림 → 구매 요청(열린 결재 id 를 채운다) / approved 인데 결재 못 찾으면 action null
  const s6 = d(p, exStatus("directive_ready", { approvals: [openApproval] }));
  assert.equal(s6.primary.code, "S6");
  assert.deepEqual(s6.primary.action, { name: "explainer_request_buy", payload: { plan_revision_id: "p1", spend_approval_id: "a1" } });
  const s6b = d(p, exStatus("approved"));
  assert.equal(s6b.primary.code, "S6");
  assert.equal(s6b.primary.action, null);
  // S8: buying 인데 판정할 후보 없음 → 구매 중(비활성)
  const s8 = d(p, exStatus("buying", { slots: [slot("buying", [cand({ status: "requested", auto_verdict: null })])] }));
  assert.equal(s8.primary.code, "S8");
  assert.equal(s8.primary.busy, true);
  // S9: 자동 합격·사람 판정 전 후보 → 후보 판정하기
  assert.equal(d(p, exStatus("buying", { slots: [slot("buying", [cand({})])] })).primary.code, "S9");
  // S10: human_checked · 선택 없음 · 합격 후보 → 이 장면으로
  assert.equal(d(p, exStatus("buying", { slots: [slot("human_checked", [cand({ human_verdict: "pass" })])] })).primary.code, "S10");
  // S11~S14
  for (const [st, expected] of [["assets_complete", "S11"], ["rehearsal", "S11"], ["blocked_assets", "S11"], ["auto_qa_fail", "S11"], ["review_fail", "S11"],
    ["auto_qa_pass", "S12"], ["process_review_pass", "S13"], ["quality_review_pass", "S14"]] as const) {
    assert.equal(d(p, exStatus(st)).primary.code, expected, st);
  }
  assert.deepEqual(d(p, exStatus("assets_complete")).primary.action, { name: "explainer_request_assemble", payload: { plan_revision_id: "p1" } });
  // nextStep 이 none 인 상태는 행의 explainer_state 로 판정한다.
  assert.equal(d(approvedPlan("explainer", { explainer_state: "ready_to_publish" }), exStatus("ready_to_publish")).primary.code, "S15");
  assert.equal(d(approvedPlan("explainer", { explainer_state: "rendered" }), exStatus("rendered")).primary.busy, true);
});

test("③ 설명형: 상세 없이 explainer_state 문자열만으로도 같은 코드가 나온다", () => {
  const table: [string | null, string][] = [
    [null, "S5"], ["plan_draft", "S5"], ["directive_ready", "S5"], ["approved", "S6"], ["buying", "S8"], ["assets_complete", "S11"], ["rehearsal", "S11"],
    ["rendered", "S8"], ["auto_qa_pass", "S12"], ["process_review_pass", "S13"], ["quality_review_pass", "S14"], ["ready_to_publish", "S15"],
  ];
  for (const [st, expected] of table) assert.equal(code(approvedPlan("explainer", { explainer_state: st })), expected, String(st));
  // 상세 없는 buying 은 "구매 중(비활성)" 으로 가리지 않는다 — 판정 대기가 숨을 수 있다.
  assert.notEqual(d(approvedPlan("explainer", { explainer_state: "buying" })).primary.busy, true);
  assert.equal(code(approvedPlan("explainer", { explainer_state: "wat" })), "needs_review");
});

test("③ 카드 S1~S8·S14·S15·S23", () => {
  assert.equal(code(item({ format_intent: "card" })), "S1");
  assert.equal(code(item({ format_intent: "card", develop_kind: "evidence", develop_status: "queued", develop_request_id: "d" })), "S2");
  assert.equal(code(item({ format_intent: "card", develop_kind: "evidence", develop_status: "succeeded", develop_request_id: "d", review_id: "r" })), "S3");
  assert.equal(code(withPlan("card", "draft")), "S4");
  assert.equal(code(withPlan("card", "in_review")), "S4");
  const s7 = d(approvedPlan("card"));
  assert.equal(s7.primary.code, "S7");
  assert.deepEqual(s7.primary.action, { name: "request_render", payload: { plan_revision_id: "p1" } });
  for (const js of ["queued", "running"]) {
    const r = d(approvedPlan("card", { job_id: "j", job_status: js }));
    assert.equal(r.primary.code, "S8", js);
    assert.equal(r.primary.busy, true, js);
  }
  const retry = d(approvedPlan("card", { job_id: "j", job_status: "failed" }));
  assert.equal(retry.primary.code, "S7");
  assert.deepEqual(retry.primary.action, { name: "request_render", payload: { plan_revision_id: "p1", retry_of: "j" } });
  const done = approvedPlan("card", { job_id: "j", job_status: "succeeded" });
  assert.equal(code({ ...done, output_review_id: "o", output_review_status: "pending", output_usable: null }), "S14");
  assert.equal(code(done), "S14"); // 검수 행이 아직 없어도 다음은 산출물 승인
  assert.equal(code({ ...done, output_review_id: "o", output_review_status: "approved", output_usable: true }), "S15");
  assert.equal(code({ ...done, output_review_id: "o", output_review_status: "changes_requested", output_usable: true }), "S7");
  assert.equal(code({ ...done, output_review_id: "o", output_review_status: "blocked", output_usable: false }), "B3");
  assert.equal(code(item({ format_intent: "card", topic_status: "duplicate" })), "S23");
  assert.equal(code(approvedPlan("card", { job_id: "j", job_status: "weird" })), "needs_review");
});

test("③ 밈 S1·S2·S4·S8·S15·S20~S23 (카드 소유·소재 소유 둘 다)", () => {
  assert.equal(code(item({ format_intent: "meme" })), "S1");                       // 소재 밈, 제작안 없음 → 글 초안 요청
  assert.equal(code(memeCard("text_requested")), "S2");
  assert.equal(code(memeCard("text_running")), "S2");
  assert.equal(d(memeCard("text_running")).primary.busy, true);
  assert.equal(code(memeCard("draft")), "S4");
  assert.equal(d(memeCard("draft")).primary.panel, "meme");
  assert.equal(code(memeCard("approved")), "S8");
  assert.equal(code(memeCard("rendering")), "S8");
  assert.equal(code(memeCard("publish_waiting")), "S15");
  const s21 = d(memeCard("manual_audio"));
  assert.equal(s21.primary.code, "S21");
  assert.equal(s21.primary.panel, "post");
  assert.equal(s21.primary.action, null, "앱 게시는 웹 발행 동작이 없다 — href 만");
  assert.ok(s21.primary.href?.includes("/drinks/work/meme") && s21.primary.href.includes("meme=m1"));
  const s22 = d(memeCard("posted_manual", { meme_external_url: "https://instagram.com/p/x" }));
  assert.equal(s22.primary.code, "S22");
  assert.equal(s22.primary.href, "https://instagram.com/p/x");
  assert.equal(code(memeCard("published")), "S20");
  for (const st of ["stopped", "failed", "rejected"]) assert.equal(code(memeCard(st)), "S23", st);
  assert.equal(code(memeCard("nope")), "needs_review");
  // 소재 소유 밈도 같은 표를 탄다.
  assert.equal(code(item({ format_intent: "meme", meme_draft_id: "m2", meme_status: "draft" })), "S4");
});

test("③ 게시 요청 S16~S20·S23 은 세 형식이 같다; submit·schedule 만 미리 채우고 approve 는 비운다", () => {
  const owners: WorkItem[] = [
    approvedPlan("explainer", { explainer_state: "ready_to_publish" }),
    approvedPlan("card", { job_id: "j", job_status: "succeeded", output_review_id: "o", output_review_status: "approved", output_usable: true }),
    memeCard("publish_waiting"),
  ];
  for (const o of owners) {
    const pub = (pub_status: string) => d({ ...o, pub_request_id: "q1", pub_status, pub_version: 4 });
    const s16 = pub("draft");
    assert.equal(s16.primary.code, "S16", o.format_intent);
    assert.deepEqual(s16.primary.action, { name: "publication_action", payload: { request_id: "q1", expected_version: 4, action: "submit" } });
    const s17 = pub("awaiting_approval");
    assert.equal(s17.primary.code, "S17");
    assert.equal(s17.primary.action, null, "승인은 화면이 보여 준 지문을 돌려줘야 한다");
    assert.equal(s17.primary.panel, "publish");
    const s18 = pub("approved");
    assert.equal(s18.primary.code, "S18");
    assert.deepEqual(s18.primary.action, { name: "publication_action", payload: { request_id: "q1", expected_version: 4, action: "schedule" } });
    for (const st of ["scheduled", "publishing"]) {
      assert.equal(pub(st).primary.code, "S19", st);
      assert.equal(pub(st).primary.busy, true, st);
    }
    assert.equal(pub("published").primary.code, "S20");
    assert.equal(pub("published").primary.href, "/drinks/analytics");
    assert.equal(pub("canceled").primary.code, "S23");
  }
  // 버전을 모르면 submit 도 미리 채우지 않는다(서버가 거부할 버튼을 만들지 않는다).
  const noVer = d({ ...owners[1], pub_request_id: "q1", pub_status: "draft", pub_version: null });
  assert.equal(noVer.primary.code, "S16");
  assert.equal(noVer.primary.action, null);
});

test("③ S24: 어디에도 없는 조합은 needs_review 이고 상태 덤프 링크가 있다", () => {
  const r = d(withPlan("explainer", "weird"));
  assert.equal(r.primary.code, "needs_review");
  assert.ok(r.primary.href?.startsWith(`/drinks/work/${TOPIC}?lane=explainer`));
  assert.equal(code(item({ format_intent: "card", develop_kind: "evidence", develop_status: "canceled", develop_request_id: "d" })), "S1"); // 취소된 초안 요청은 다시 S1
});

test("모든 결정에는 작업공간 href 가 있고 lane 이 형식과 같다", () => {
  for (const it of [item(), withPlan("card"), memeCard("draft"), approvedPlan("explainer", { explainer_state: "blocked_budget" })]) {
    const r = d(it);
    assert.ok(r.primary.href, r.primary.code);
    assert.equal(r.lane, it.format_intent);
    assert.equal(r.unitId, it.unit_id);
  }
});

// ── 경고 ──
test("경고: 게시 시각이 KST 07:00~23:30 밖 / 편성 주차가 지남 — 막지 않는다", () => {
  const base = approvedPlan("card", { job_id: "j", job_status: "succeeded", output_review_id: "o", output_review_status: "approved", output_usable: true, pub_request_id: "q", pub_status: "approved", pub_version: 1 });
  const late = d({ ...base, pub_publish_at: "2026-11-06T16:00:00Z" });      // 11-07 01:00 KST
  assert.equal(late.warnings.filter((w) => /창\(07:00~23:30\) 밖/.test(w)).length, 1);
  assert.equal(late.primary.code, "S18", "경고는 주 버튼을 바꾸지 않는다");
  const ok = d({ ...base, pub_publish_at: "2026-11-06T03:00:00Z" });        // 11-06 12:00 KST
  assert.equal(ok.warnings.filter((w) => /밖/.test(w)).length, 0);
  // 게시가 끝난 요청의 시각은 경고하지 않는다.
  assert.equal(d({ ...base, pub_status: "published", pub_publish_at: "2026-11-06T16:00:00Z" }).warnings.filter((w) => /밖/.test(w)).length, 0);
  // 편성 주차: 10-26 주는 11-02 에 끝났다 → 경고. 이번 주(11-02)는 아니다. 끝난 단위(S20)는 경고하지 않는다.
  assert.equal(d(item({ editorial_week: "2026-10-26" })).warnings.filter((w) => /편성 주차/.test(w)).length, 1);
  assert.equal(d(item({ editorial_week: "2026-11-02" })).warnings.filter((w) => /편성 주차/.test(w)).length, 0);
  assert.equal(d({ ...base, editorial_week: "2026-10-26", pub_status: "published" }).warnings.filter((w) => /편성 주차/.test(w)).length, 0);
});

// ── ④ 홈 우선순위 ──
test("④ rankForHome: B1/B2 → B5 → B3/B4 → B7/B8 → B6 → 판정 단계(오래된 것부터) → 그 밖 → 끝난 것", () => {
  const mk = (unit: string, primaryCode: string): Decision => ({ unitId: unit, lane: "card", blocks: [], warnings: [], primary: { code: primaryCode, label: primaryCode, panel: "none", action: null } });
  const input = [mk("done", "S20"), mk("s1", "S1"), mk("b6", "B6"), mk("judgeNew", "S4"), mk("b8", "B8"), mk("nr", "needs_review"), mk("b3", "B3"), mk("b5", "B5"), mk("judgeOld", "S17"), mk("b2", "B2"), mk("b1", "B1"), mk("b4", "B4"), mk("b7", "B7")];
  const updatedAt = new Map([["judgeNew", "2026-11-04T00:00:00Z"], ["judgeOld", "2026-10-20T00:00:00Z"]]);
  const out = rankForHome(input, new Set(), updatedAt).map((x) => x.unitId);
  assert.deepEqual(out, ["b2", "b1", "b5", "b3", "b4", "b8", "nr", "b7", "b6", "judgeOld", "judgeNew", "s1", "done"]);
  assert.deepEqual([...JUDGMENT_STEPS].sort(), ["S10", "S12", "S13", "S14", "S17", "S18", "S4", "S9"]);
  assert.equal(homeTier(mk("x", "B1")), 0);
  assert.equal(homeTier(mk("x", "S9")), 5);
});

test("④ 미룬 항목은 같은 급 안에서만 뒤로 간다 — 목록에서 빠지지 않고 급을 넘지 않는다", () => {
  const mk = (unit: string, primaryCode: string): Decision => ({ unitId: unit, lane: "meme", blocks: [], warnings: [], primary: { code: primaryCode, label: primaryCode, panel: "none", action: null } });
  const a = mk("a", "S4"), b = mk("b", "S4"), c = mk("c", "S1"), top = mk("top", "B1");
  const snoozed = new Set([snoozeKey(a), snoozeKey(top)]);
  const out = rankForHome([a, b, c, top], snoozed).map((x) => x.unitId);
  assert.deepEqual(out, ["top", "b", "a", "c"]);
  // unit_id 만 넣어도 같은 뜻이다(홈이 그렇게 부른다).
  assert.deepEqual(rankForHome([a, b, c, top], new Set(["a"])).map((x) => x.unitId), ["top", "b", "a", "c"]);
  assert.deepEqual(rankForHome([a, b]).map((x) => x.unitId), ["a", "b"]);
  // 열쇠는 단계 코드를 품어, 단계가 바뀌면 미룸이 저절로 풀린다.
  assert.equal(snoozeKey(a), "a#S4");
  assert.notEqual(snoozeKey(a), snoozeKey({ ...a, primary: { ...a.primary, code: "S14" } }));
});

// ── model.ts::nextAction 과의 호환(§7-5) ──
test("§7-5 호환표: nextAction 의 낙점 전 라벨과 decide 가 서로 모순되지 않는다", () => {
  const na = (status: Parameters<typeof nextAction>[0]["status"], contentApproval: "ready" | "invalidated" | "waiting" | null = null) =>
    nextAction({ status, reviewStatus: null, reviewRevoked: false, reviewBlockers: 0, approvalValid: false, selectedValid: true, selectedFormats: [], plans: {}, contentApproval }).label;
  // 경량 평가 / 조사하기 — [이걸로]를 안 거친 소재(작업 단위 행이 아직 없다). decide 는 그런 행을 받지 않으므로 라벨만 확인.
  assert.equal(na("inbox"), "경량 평가");
  assert.equal(na("triaged"), "조사하기");
  // 다시 열기 — 둘 다 "다시 열기".
  assert.equal(na("on_hold"), "다시 열기");
  assert.equal(d(item({ topic_status: "on_hold" })).primary.label, "다시 열기");
  assert.equal(d(item({ topic_status: "rejected" })).primary.code, "S23");
  // 내용 승인 → S4 [승인]. 라벨은 다르되 둘 다 "승인" 으로 끝나 뜻이 같다.
  assert.equal(na("researching", "ready"), "내용 승인");
  const s4 = d(withPlan("explainer", "draft"));
  assert.equal(s4.primary.code, "S4");
  assert.ok(na("researching", "ready").endsWith("승인") && s4.primary.label.endsWith("승인"));
  // 대본 다시 만들기(근거 무효) → v2 는 차단 계층 B3 로 올렸다. 둘 다 "승인" 이 아니다.
  assert.equal(na("researching", "invalidated"), "대본 다시 만들기");
  const b3 = d(withPlan("explainer", "draft", { review_valid: false }));
  assert.equal(b3.primary.code, "B3");
  assert.ok(!b3.primary.label.endsWith("승인") && b3.primary.panel === "evidence");
  // 이어 만들기 확인(waiting) → S2/S3 만드는 중(비활성). 둘 다 승인 버튼이 아니다.
  assert.equal(na("researching", "waiting"), "이어 만들기 확인");
  const s2 = d(item({ develop_kind: "evidence", develop_status: "running", develop_request_id: "d" }));
  assert.equal(s2.primary.busy, true);
  assert.ok(!s2.primary.label.endsWith("승인"));
});
