// 순수 로직 테스트. 실행: `node --test web/lib/work/nextAction.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextStep, summarize, HOME_SKIP, FINANCE_HREFS, type WorkCounts } from "./nextAction.ts";
import { classifyRenderJob, primaryAction, countByTab, type QueueJob } from "./renderQueue.ts";

const ZERO: WorkCounts = {
  renderFailed: 0,
  renderNeedsCheck: 0,
  directivePending: 0,
  draftPending: 0,
  draftMissing: 0,
  undecided: 0,
};

test("아무것도 없으면 none", () => {
  assert.equal(nextStep(ZERO).action, "none");
  assert.equal(nextStep(ZERO).count, 0);
});

test("우선순위: 렌더 실패가 다른 모든 것을 앞선다", () => {
  const s = nextStep({ ...ZERO, renderFailed: 1, undecided: 20, draftPending: 3, renderNeedsCheck: 2 });
  assert.equal(s.action, "retry_render");
  assert.match(s.headline, /렌더 실패 1건/);
});

test("우선순위 사슬 — 앞의 것이 0 이 되면 다음으로 내려간다", () => {
  const order = [
    [{ renderNeedsCheck: 1 }, "check_render"],
    [{ directivePending: 1 }, "review_directive"],
    [{ draftPending: 1 }, "review_draft"],
    [{ draftMissing: 1 }, "generate_draft"],
    [{ undecided: 1 }, "decide"],
  ] as const;
  for (const [patch, expected] of order) {
    assert.equal(nextStep({ ...ZERO, ...patch }).action, expected);
  }
});

test("지시서 승인 대기가 대본 검수보다 먼저 (뒤쪽 단계가 앞선다)", () => {
  const s = nextStep({ ...ZERO, directivePending: 1, draftPending: 5, draftMissing: 9, undecided: 30 });
  assert.equal(s.action, "review_directive");
});

test("공장별 경로가 반영된다", () => {
  assert.equal(nextStep({ ...ZERO, undecided: 3 }, FINANCE_HREFS).href, "/finance");
  assert.equal(nextStep({ ...ZERO, renderFailed: 1 }, FINANCE_HREFS).href, "/finance/render");
});

test("요약 타일 3개: 사람 판단 대기와 렌더 대기를 각각 합산", () => {
  const s = summarize({
    renderFailed: 1,
    renderNeedsCheck: 2,
    directivePending: 3,
    draftPending: 4,
    draftMissing: 5,
    undecided: 6,
  });
  assert.deepEqual(s, { undecided: 6, reviewNeeded: 12, renderNeeded: 3 });
});

// ── 렌더 큐 분류 ─────────────────────────────────────────────
const job = (p: Partial<QueueJob>): QueueJob => ({ status: "done", output_url: "u", ...p });

test("실패는 조치 필요 + 재렌더가 주요 행동", () => {
  const j = job({ status: "failed", output_url: null });
  assert.equal(classifyRenderJob(j), "action");
  assert.equal(primaryAction(j).key, "retry_render");
});

test("진행 중은 running + 주요 행동 없음", () => {
  for (const st of ["queued", "assets", "tts", "assembling"]) {
    const j = job({ status: st });
    assert.equal(classifyRenderJob(j), "running");
    assert.equal(primaryAction(j).key, "none");
  }
});

test("완료·업로드 전은 조치 필요 + 업로드가 주요 행동", () => {
  const j = job({});
  assert.equal(classifyRenderJob(j), "action");
  assert.equal(primaryAction(j).key, "upload");
});

test("QA 하드실패는 업로드보다 영상 확인이 먼저", () => {
  const j = job({ qa: { hard_fail: ["오디오 없음"] } });
  assert.equal(classifyRenderJob(j), "action");
  assert.equal(primaryAction(j).key, "review_video");
});

test("업로드 실패는 조치 필요 + 재시도", () => {
  const j = job({ youtube_status: "error" });
  assert.equal(classifyRenderJob(j), "action");
  assert.equal(primaryAction(j).key, "retry_upload");
});

test("업로드 진행 중은 running, 업로드 완료는 done", () => {
  assert.equal(classifyRenderJob(job({ youtube_status: "processing" })), "running");
  assert.equal(classifyRenderJob(job({ youtube_status: "done" })), "done");
  assert.equal(primaryAction(job({ youtube_status: "done" })).key, "none");
});

test("보관은 다른 모든 상태를 덮는다(사용자가 의도적으로 치운 것)", () => {
  assert.equal(classifyRenderJob(job({ saved_at: "2026-07-27", status: "failed" })), "saved");
  assert.equal(classifyRenderJob(job({ saved_at: "2026-07-27" })), "saved");
});

test("완료인데 mp4 주소가 없으면 업로드가 아니라 확인", () => {
  assert.equal(primaryAction(job({ output_url: null })).key, "review_video");
});

test("탭 건수는 전 탭을 0 으로라도 채운다", () => {
  const c = countByTab([job({ status: "failed" }), job({ status: "tts" }), job({ youtube_status: "done" })]);
  assert.deepEqual(c, { action: 1, running: 1, done: 1, saved: 0 });
});

// ── §8-3 사람 대기 상태 ──────────────────────────────────────
test("사람이 봐야 끝나는 상태는 '진행 중'이 아니라 '조치 필요'다", () => {
  // ★ 예전에는 `status !== "done"` 한 줄이 이것들을 전부 '진행 중'으로 삼켰다. 워치독도
  //   안 건드리므로 degraded 잡은 **영원히 진행 중**으로 보였고 승인 버튼이 뜰 자리가 없었다.
  for (const st of ["qa_pending", "degraded"]) {
    assert.equal(classifyRenderJob(job({ status: st })), "action");
  }
  assert.equal(primaryAction(job({ status: "degraded" })).key, "approve_degraded");
  assert.equal(primaryAction(job({ status: "qa_pending" })).key, "review_video");
});

test("degraded 는 '진행 중' 문구를 보여주면 안 된다 — 저절로 끝나지 않는다", () => {
  const why = primaryAction(job({ status: "degraded" })).why;
  assert.ok(!why.includes("진행 중"), why);
});

// 홈은 렌더 큐 작업을 카드에 띄우지 않는다(2026-08-20 운영자 요청).
test("HOME_SKIP: 렌더 실패·완료가 있어도 홈 카드는 선별/검수를 가리킨다", () => {
  const c = { ...ZERO, renderFailed: 2, renderNeedsCheck: 15, undecided: 17 };
  assert.equal(nextStep(c, FINANCE_HREFS, HOME_SKIP).action, "decide");
  // 카운트 자체는 그대로다 — 요약 타일 [렌더·업로드 필요] 는 계속 17을 보여준다.
  assert.equal(summarize(c).renderNeeded, 17);
  // 홈이 아닌 화면(기본 인자)에서는 예전처럼 렌더 실패가 먼저다.
  assert.equal(nextStep(c).action, "retry_render");
});

test("HOME_SKIP: 렌더만 남았고 선별할 것이 없으면 홈은 '작업 없음'", () => {
  const s = nextStep({ ...ZERO, renderFailed: 1 }, FINANCE_HREFS, HOME_SKIP);
  assert.equal(s.action, "none");
});
