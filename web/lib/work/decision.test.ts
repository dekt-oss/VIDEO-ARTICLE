// 순수 로직 테스트. 실행: `node --test web/lib/work/decision.test.ts`
//
// 결정 바의 주 버튼이 상태마다 **하나로** 정해지는지 못박는다(설계안 v2 §2-2 표).
import { test } from "node:test";
import assert from "node:assert/strict";
import { decide, isStale, type DecisionInput } from "./decision.ts";

const base: DecisionInput = {
  hasDraft: true,
  draftPending: null,
  draftUpdatedAt: "2026-09-11T02:00:00Z",
  scriptApproved: false,
  chosen: ["photo"],
  versions: [{ key: "photo", status: "draft", createdAt: "2026-09-11T02:05:00Z", pending: null }],
  dirty: false,
};

test("초안 없음 → [초안 + 지시서 생성]", () => {
  const d = decide({ ...base, hasDraft: false, versions: [] });
  assert.equal(d.action, "generate");
  assert.match(d.label, /초안 \+ 지시서 생성 \(1건\)/);
});

test("초안 만드는 중 → 대기(초안 유무와 무관)", () => {
  assert.equal(decide({ ...base, hasDraft: false, draftPending: "processing" }).action, "wait_draft");
  assert.equal(decide({ ...base, draftPending: "queued" }).action, "wait_draft");
});

test("초안 있음 + 고른 버전 지시서 생성 중 → 대기", () => {
  const d = decide({ ...base, versions: [{ key: "photo", status: null, pending: "processing" }] });
  assert.equal(d.action, "wait_directive");
  assert.deepEqual(d.targets, ["photo"]);
});

test("초안 있음 + 지시서 없음 → [지시서 생성]", () => {
  const d = decide({ ...base, versions: [{ key: "photo", status: null }] });
  assert.equal(d.action, "make_directive");
});

test("검수 필요 → [대본 확정 + 승인 → 렌더]; 대본이 이미 승인됐으면 접두 없음", () => {
  assert.match(decide(base).label, /^대본 확정 \+ 승인 → 렌더/);
  assert.match(decide({ ...base, scriptApproved: true }).label, /^승인 → 렌더/);
  assert.equal(decide(base).action, "approve_render");
});

test("대본을 지시서 이후에 고쳤으면 → [지시서 재생성]이 승인을 가로막는다", () => {
  const d = decide({ ...base, draftUpdatedAt: "2026-09-11T03:00:00Z" });
  assert.equal(d.action, "regen_stale");
  assert.deepEqual(d.stale, ["photo"]);
});

test("같은 초 안의 저장(초안 직후 이어 만든 지시서)은 낡은 것이 아니다", () => {
  assert.equal(isStale("2026-09-11T02:05:01Z", "2026-09-11T02:05:00Z"), false);
  assert.equal(isStale("2026-09-11T02:05:03Z", "2026-09-11T02:05:00Z"), true);
  assert.equal(isStale(null, "2026-09-11T02:05:00Z"), false);   // 모르면 낡지 않음
});

test("차단 사유가 있으면 → [사유 보기](강제 승인은 그 안에서)", () => {
  const d = decide({ ...base, versions: [{ ...base.versions[0], blocked: ["photo_hook_missing"] }] });
  assert.equal(d.action, "blocked");
});

test("고른 버전이 전부 승인·렌더로 넘어갔으면 → [렌더 결과]", () => {
  for (const status of ["approved", "rendering", "rendered"] as const) {
    assert.equal(decide({ ...base, versions: [{ key: "photo", status }] }).action, "view_render", status);
  }
});

test("두 버전 중 하나만 없으면 없는 쪽 생성이 먼저다", () => {
  const d = decide({
    ...base,
    chosen: ["comic", "photo"],
    versions: [base.versions[0], { key: "comic", status: null }],
  });
  assert.equal(d.action, "make_directive");
  assert.deepEqual(d.targets, ["comic"]);
});

test("초안은 있는데 체크한 버전이 없으면 → [버전을 고르세요](렌더 결과가 아니다)", () => {
  // 실측: 체크를 다 풀면 [렌더 결과 보기]가 떠서 다시 고를 길이 없었다.
  const d = decide({ ...base, chosen: [] });
  assert.equal(d.action, "choose_version");
  assert.deepEqual(d.targets, []);
});

test("체크한 버전이 없으면 생성 버튼은 이유를 말한다", () => {
  const d = decide({ ...base, hasDraft: false, chosen: [], versions: [] });
  assert.equal(d.action, "generate");
  assert.match(d.reason, /하나 이상/);
});
