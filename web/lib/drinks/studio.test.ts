import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { RECOVERABLE, draftProblem, orderTotal, progressText, studioPhase, versionOptions, type StudioRequest, type StudioStatus } from "./studio.ts";

const base = (over: Partial<StudioStatus> = {}): StudioStatus => ({
  topic: { id: "t", title: "사케", question: "사케 유통기한?", status: "researching", version: 1 },
  picks: [{ format_intent: "card", approved_at: null, recommended_reason: null }], active: null, last: null, recoveries_24h: 0,
  limits: { max_recoveries_24h: 3 }, review: null, plans: [], sources: [], ...over,
});
const req = (over: Partial<StudioRequest> = {}): StudioRequest => ({ request_id: "r", kind: "evidence", status: "running", step: null, format_intent: null,
  error_code: null, error_message: null, recovery_of: null, instruction: null, created_at: "", finished_at: null, ...over });
const plan = (status: string, jobs: { status: string }[] = []) => ({ plan_revision_id: "p", format: "carousel" as const, version: 1, plan_status: status, blocked: false,
  blocked_reason: null, current: true, plan_json: { pages: [] }, unverified_numbers: [], topic_review_id: "rv",
  jobs: jobs.map((j, i) => ({ job_id: `j${i}`, status: j.status, error_code: null, attempt_no: 1, created_at: "", finished_at: null })) });

test("화면 단계는 서버 상태에서만 정한다", () => {
  assert.equal(studioPhase(null).screen, "collect");
  assert.equal(studioPhase(base({ active: req() })).screen, "preparing");
  assert.equal(studioPhase(base({ plans: [plan("draft")] })).screen, "draft");
  assert.equal(studioPhase(base({ plans: [plan("approved", [{ status: "running" }])] })).screen, "generating");
  assert.equal(studioPhase(base({ plans: [plan("approved", [{ status: "succeeded" }])] })).screen, "result");
  assert.equal(studioPhase(base({ plans: [plan("approved", [{ status: "failed" }])] })).screen, "result", "실패해도 영구히 '만드는 중'으로 남지 않는다");
  assert.equal(studioPhase(base({ last: { ...req({ status: "blocked", error_code: "evidence_insufficient" }) } })).screen, "blocked");
  const rec = studioPhase(base({ last: req({ status: "failed", error_code: "draft_exists" }) }));
  assert.deepEqual([rec.screen, rec.code], ["choice", "recoverable"]);
  const lim = studioPhase(base({ last: req({ status: "failed", error_code: "worker_error" }), recoveries_24h: 3 }));
  assert.equal(lim.code, "recovery_limit");
  assert.equal(studioPhase(base({ last: req({ status: "failed", error_code: "budget_exceeded" }) })).code, "budget_exceeded");
});

test("진행 문구는 워커가 남긴 단계 이름에서만 — 지어낸 완료율 없음", () => {
  assert.equal(progressText(req({ step: "extract:国税庁" })), "자료를 확인하고 있어요.");
  assert.equal(progressText(req({ step: "factcheck" })), "사용할 내용을 정리하고 있어요.");
  assert.equal(progressText(req({ step: "write:0", kind: "plan" })), "초안을 다듬고 있어요.");
  assert.equal(progressText(req({ status: "queued", recovery_of: "x" })), "일시적인 오류를 자동으로 복구하고 있어요.");
  assert.equal(progressText(req({ step: "write:0", instruction: "짧게" })), "말씀하신 방향으로 다시 쓰고 있어요.");
  assert.doesNotMatch(progressText(req({ step: "???" })), /%/);
});

test("만들 수 없는 버전은 고를 수 없고, 모르는 금액은 0 으로 쓰지 않는다", () => {
  const opts = versionOptions("t", plan("draft") as never);
  assert.deepEqual(opts.filter((o) => o.enabled).map((o) => o.id), ["card"]);
  assert.ok(opts.filter((o) => !o.enabled).every((o) => o.why && o.href));
  assert.equal(orderTotal(opts, ["card"]), 0);
  assert.equal(orderTotal(opts, ["card", "explainer"]), null);
  assert.equal(versionOptions("t", null).find((o) => o.id === "card")!.enabled, false);
});

test("빈 제목·빈 내용은 막는다(출처 장은 제목만)", () => {
  const roles = ["cover", "explain", "source"];
  assert.equal(draftProblem({ pages: [{ heading: "", body: "" }, { heading: "a", body: "b" }, { heading: "출처", body: "" }], hook_title: "", share_line: "" }, roles), "제목을 비워 둘 수 없어요.");
  assert.match(draftProblem({ pages: [{ heading: "t", body: "" }, { heading: "a", body: " " }, { heading: "출처", body: "" }], hook_title: "", share_line: "" }, roles)!, /2장 내용/);
  assert.equal(draftProblem({ pages: [{ heading: "t", body: "" }, { heading: "a", body: "b" }, { heading: "출처", body: "" }], hook_title: "", share_line: "" }, roles), null);
});

test("자동 복구 목록은 SQL(0076 drinks_studio_recoverable)과 같다", () => {
  const sql = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations/0076_drinks_studio.sql"), "utf8");
  const m = /function drinks_studio_recoverable[\s\S]*?in \(([\s\S]*?)\)\s*\$\$/.exec(sql);
  assert.ok(m, "SQL 정의를 찾지 못함");
  const codes = [...m![1].matchAll(/'([a-z_]+)'/g)].map((x) => x[1]).sort();
  assert.deepEqual(codes, [...RECOVERABLE].sort());
});

test("0077 사진형 카드는 배경 사진 금액을 보여 주고 합계에 넣는다 — 금액을 못 읽으면 고를 수 없다(0원으로 지어내지 않는다)", () => {
  const photo = { ...plan("draft"), plan_json: { pages: [{}, {}, {}, {}, {}], layout: "photo" }, estimate: { photo: true, images: 4, bought: 1, total_usd: 0.117 } };
  const card = versionOptions("t", photo as never).find((o) => o.id === "card")!;
  assert.equal(card.costUsd, 0.117);
  assert.match(card.costText, /\$0\.12 · 배경 사진 4장/);
  assert.match(card.costText, /1장은 이미 산 사진 재사용/);
  assert.equal(orderTotal(versionOptions("t", photo as never), ["card"]), 0.117);
  const unknown = versionOptions("t", { ...photo, estimate: undefined } as never).find((o) => o.id === "card")!;
  assert.equal(unknown.enabled, false);
  assert.equal(unknown.costUsd, null);
});
