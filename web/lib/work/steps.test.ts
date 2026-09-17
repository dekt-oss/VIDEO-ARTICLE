// 순수 로직 테스트. 실행: `node --test web/lib/work/steps.test.ts`
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildStages, reportStages, mostAdvanced, directiveHandedOff } from "./steps.ts";
import { renderProgress, type QueueJob } from "./renderQueue.ts";

const base = {
  hasDraft: false,
  scriptApproved: false,
  directiveStatus: {},
  render: renderProgress([]),
};
const doneJob: QueueJob = { status: "done", output_url: "u", youtube_status: "done" };

// ★ 2026-09-17: ④ 초안 검수 + ⑤ 영상 지시서를 **한 단계로 합쳤다**(운영자 지시).
//   steps[0] = 작업(대본·지시서), steps[1] = 렌더 결과. 옛 ?step=4 도 이 단계로 온다.
test("★ 단계는 둘이다 — 초안 검수와 지시서를 따로 세지 않는다", () => {
  const { steps } = buildStages({ ...base, hasDraft: true });
  assert.equal(steps.length, 2);
  assert.equal(steps[0].label, "영상 지시서");
  assert.equal(steps[0].no, 5);            // 옛 ?step=4·5 주소가 둘 다 여기로 온다
  assert.equal(steps[1].label, "렌더 결과");
});

test("초안 없음 → 작업이 할 일, 렌더는 잠김", () => {
  const { steps, defaultStep } = buildStages(base);
  assert.equal(defaultStep, 5);
  assert.equal(steps[0].status, "아직 없음");
  assert.equal(steps[0].needsWork, true);
  assert.equal(steps[1].locked, true);
});

test("초안은 있는데 지시서가 아직이면 작업이 할 일", () => {
  const { steps, defaultStep } = buildStages({ ...base, hasDraft: true });
  assert.equal(defaultStep, 5);
  assert.equal(steps[0].status, "지시서 만드는 중");
  assert.equal(steps[0].needsWork, true);
  assert.equal(steps[1].locked, true);   // 지시서가 승인되기 전에는 렌더가 없다
});

test("대본만 승인하고 지시서가 아직이면 여전히 작업이 할 일", () => {
  // 합치기 전에는 ④ 가 초록이 되어 "끝났다"로 보였다. 지시서가 없으면 끝난 게 아니다.
  const { steps, defaultStep } = buildStages({ ...base, hasDraft: true, scriptApproved: true });
  assert.equal(steps[0].done, false);
  assert.equal(steps[0].needsWork, true);
  assert.equal(defaultStep, 5);
});

test("지시서 승인 → 작업 완료, 렌더 없으면 렌더 단계는 잠기지 않는다(렌더 대기)", () => {
  const { steps, defaultStep } = buildStages({
    ...base,
    hasDraft: true,
    scriptApproved: true,
    directiveStatus: { comic: "approved" },
  });
  assert.equal(steps[0].done, true);
  assert.equal(steps[0].needsWork, false);
  assert.equal(steps[1].locked, false);
  assert.equal(defaultStep, 6); // 손댈 것이 없으면 마지막으로 진행된 단계
});

test("렌더 실패가 있으면 렌더 단계가 할 일이고 기본 단계가 된다", () => {
  const { steps, defaultStep } = buildStages({
    ...base,
    hasDraft: true,
    scriptApproved: true,
    directiveStatus: { comic: "rendered" },
    render: renderProgress([{ status: "failed" }, doneJob]),
  });
  assert.equal(steps[1].status, "실패 1건");
  assert.equal(steps[1].needsWork, true);
  assert.equal(defaultStep, 6);
});

test("업로드까지 끝나면 렌더 단계 완료", () => {
  const { steps } = buildStages({
    ...base,
    hasDraft: true,
    scriptApproved: true,
    directiveStatus: { comic: "rendered" },
    render: renderProgress([doneJob]),
  });
  assert.equal(steps[1].done, true);
  assert.equal(steps[1].status, "완료 1건");
  assert.equal(steps[1].needsWork, false);
});

test("완료·미업로드는 '확인 필요' 로 센다", () => {
  const { steps } = buildStages({
    ...base,
    hasDraft: true,
    scriptApproved: true,
    directiveStatus: { comic: "rendered" },
    render: renderProgress([{ status: "done", output_url: "u" }]),
  });
  assert.equal(steps[1].status, "확인 필요 1건");
  assert.equal(steps[1].needsWork, true);
});

test("진행 중은 할 일이 아니다(사람이 기다리는 것)", () => {
  const { steps, defaultStep } = buildStages({
    ...base,
    hasDraft: true,
    scriptApproved: true,
    directiveStatus: { comic: "rendering" },
    render: renderProgress([{ status: "assembling" }]),
  });
  assert.equal(steps[1].status, "진행 중 1건");
  assert.equal(steps[1].needsWork, false);
  assert.equal(defaultStep, 6);
});

test("여러 버전 중 가장 진행된 상태를 고른다", () => {
  assert.equal(mostAdvanced({ comic: "draft", webtoon: "rendered" }), "rendered");
  assert.equal(mostAdvanced({ comic: "draft" }), "draft");
  assert.equal(mostAdvanced({}), null);
  assert.equal(directiveHandedOff({ comic: "draft" }), false);
  assert.equal(directiveHandedOff({ comic: "approved" }), true);
});

test("리포트 공장도 한 라우트 안에서 ?step= 으로 단계를 옮긴다", () => {
  // 예전에는 ⑤ 가 /finance/directive/r1, ⑥ 이 /finance/render 로 흩어져 화면이 갈아엎어졌다.
  const { steps } = reportStages("r1", { ...base, hasDraft: true });
  assert.equal(steps.length, 2);
  assert.equal(steps[0].href, "/finance/review/r1?step=5");
  assert.equal(steps[1].href, "/finance/review/r1?step=6");
});

test("논문 공장은 href 를 비워 stepper 가 ?step= 을 만들게 한다", () => {
  const { steps } = buildStages({ ...base, hasDraft: true });
  assert.equal(steps[0].href, undefined);
});
