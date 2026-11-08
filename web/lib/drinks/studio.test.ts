import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { RECOVERABLE, activePlan, cardCost, defaultFormat, defaultPublishAt, draftRows, formatAction, overlayTexts, progressText, studioPhase, type StudioRequest, type StudioStatus } from "./studio.ts";

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

test("릴스도 초안 → 명세서 → 제작 → 검수 → 등록 순서로 간다", () => {
  const video = (st: string) => ({ ...plan(st), format: "video" as const });
  const ph = (st: string, ep: string | null, out: string | null = null) => studioPhase(base({ plans: [video(st)] }), { episodeState: ep, outputStatus: out }).screen;
  assert.equal(ph("draft", null), "draft");
  assert.equal(ph("approved", null), "spec", "승인 뒤 명세서를 만든다");
  assert.equal(ph("approved", "plan_draft"), "spec");
  assert.equal(ph("approved", "directive_ready"), "spec", "명세서 승인 전에는 돈이 나가지 않는다");
  assert.equal(ph("approved", "approved"), "generating");
  assert.equal(ph("approved", "buying"), "generating");
  assert.equal(ph("approved", "assets_complete"), "generating");
  assert.equal(ph("approved", "auto_qa_pass"), "result", "자동 검사를 통과하면 사람 검수");
  assert.equal(ph("approved", "ready_to_publish", "approved"), "publish");
});

test("카드뉴스도 승인과 제작이 나뉜다", () => {
  assert.equal(studioPhase(base({ plans: [plan("approved")] })).screen, "spec");
  assert.equal(studioPhase(base({ plans: [plan("approved", [{ status: "succeeded" }])] }), { outputStatus: "approved" }).screen, "publish");
});

test("지정한 형식의 초안을 고르고, 지정이 없으면 카드뉴스 → 릴스 순", () => {
  const video = { ...plan("draft"), format: "video" as const, plan_revision_id: "v" };
  const s = base({ plans: [video, plan("draft")] });
  assert.equal(activePlan(s)!.format, "carousel");
  assert.equal(activePlan(s, "explainer")!.plan_revision_id, "v");
  assert.equal(activePlan(base({ plans: [video] }))!.format, "video");
  assert.equal(activePlan(base({ plans: [{ ...video, blocked: true }] })), null, "막힌 초안은 쓰지 않는다");
});

test("진행 문구는 워커가 남긴 단계 이름에서만 — 지어낸 완료율 없음", () => {
  assert.equal(progressText(req({ step: "extract:国税庁" })), "자료를 확인하고 있어요.");
  assert.equal(progressText(req({ step: "factcheck" })), "사용할 내용을 정리하고 있어요.");
  assert.equal(progressText(req({ step: "write:0", kind: "plan" })), "초안을 쓰고 있어요. 보통 1~3분 걸려요.");
  assert.equal(progressText(req({ status: "queued", recovery_of: "x" })), "일시적인 오류를 자동으로 복구하고 있어요.");
  assert.equal(progressText(req({ step: "write:0", instruction: "짧게" })), "말씀하신 방향으로 다시 쓰고 있어요.");
  assert.doesNotMatch(progressText(req({ step: "???" })), /%/);
});

test("어느 소재든 유형을 고르고, 시작한 소재에는 다른 유형을 더한다", () => {
  const fresh = { topicId: null, started: [], drafts: [] };
  assert.equal(defaultFormat(fresh), "card");
  assert.equal(formatAction(fresh, "explainer"), "prepare");
  assert.equal(formatAction(fresh, "meme"), "meme");
  const reel = { topicId: "t", started: ["explainer"], drafts: ["explainer"] };
  assert.equal(defaultFormat(reel), "explainer", "이미 만든 유형이 먼저 골라져 있다");
  assert.equal(formatAction(reel, "explainer"), "open");
  assert.equal(formatAction(reel, "card"), "add", "준비 함수는 고른 유형을 따르지 않으므로 더하기로");
  const stalled = { topicId: "t", started: ["card"], drafts: [] };
  assert.equal(formatAction(stalled, "card"), "prepare", "멈춘 소재는 복구");
  assert.equal(formatAction(stalled, "explainer"), "add");
  assert.equal(formatAction({ topicId: "t", started: [], drafts: [] }, "explainer"), "prepare");
});

test("초안 구성표는 화면·내레이션·글자·이미지를 글로 보여 준다", () => {
  const video = { ...plan("draft"), format: "video" as const, plan_json: { scenes: [
    { timing_sec: 4, visual_role: "reality", staging_ko: "술잔 세 개", narration: "뭐가 다를까요?", overlays: "[\"준마이슈\"]" },
    { visual_role: "mechanism", explanation: "도정", narration: "깎아요", overlays: null },
  ] } };
  const v = draftRows(video as never);
  assert.equal(v[0].title, "1번 장면 · 4초 · 실사");
  assert.deepEqual(v[0].lines, [{ label: "화면", text: "술잔 세 개" }, { label: "내레이션·자막", text: "뭐가 다를까요?" }, { label: "화면 글자", text: "준마이슈" }]);
  assert.equal(v[1].lines[0].text, "도정", "연출 글이 없으면 설명으로");
  const card = { ...plan("draft"), plan_json: { layout: "photo", reel: { hook_title: "왜?", share_line: "저장" }, pages: [
    { role: "cover", heading: "위스키 [통]이 맛을 바꿔요", body: "왜 다를까요?", claim_ids: [], image_prompt: "barrels" },
    { role: "source", heading: "출처", body: null, claim_ids: [] },
  ] } };
  const c = draftRows(card as never);
  assert.equal(c[0].lines[0].text, "위스키 통이 맛을 바꿔요", "대괄호는 화면에 안 나간다");
  assert.match(c[0].lines.at(-1)!.text, /'통'을 금색/);
  assert.match(c[1].lines[0].text, /출처 목록/);
  assert.equal(c[2].title, "함께 나오는 세로 릴스");
  assert.deepEqual(overlayTexts([{ text: "가" }, "나", { x: 1 }]), ["가", "나"]);
  assert.deepEqual(overlayTexts("그냥 글자"), ["그냥 글자"]);
});

test("게시 시각 기본값은 15분 뒤, 게시 가능 시간 밖이면 다음 시작 시각", () => {
  const w = { start: "07:00", end: "23:30" };
  assert.equal(defaultPublishAt(Date.parse("2026-11-08T03:00:00Z"), w), "2026-11-08T12:15");
  assert.equal(defaultPublishAt(Date.parse("2026-11-08T15:00:00Z"), w), "2026-11-09T07:00", "한국 자정 넘겨 00:15");
  assert.equal(defaultPublishAt(Date.parse("2026-11-08T14:30:00Z"), w), "2026-11-09T07:00", "한국 23:45 → 다음 날");
});

test("자동 복구 목록은 SQL(0076 drinks_studio_recoverable)과 같다", () => {
  const sql = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../../supabase/migrations/0076_drinks_studio.sql"), "utf8");
  const m = /function drinks_studio_recoverable[\s\S]*?in \(([\s\S]*?)\)\s*\$\$/.exec(sql);
  assert.ok(m, "SQL 정의를 찾지 못함");
  const codes = [...m![1].matchAll(/'([a-z_]+)'/g)].map((x) => x[1]).sort();
  assert.deepEqual(codes, [...RECOVERABLE].sort());
});

test("0077 사진형 카드는 배경 사진 금액을 보여 준다 — 금액을 못 읽으면 0원으로 지어내지 않는다", () => {
  const photo = { ...plan("draft"), plan_json: { pages: [{}, {}, {}, {}, {}], layout: "photo" }, estimate: { photo: true, images: 4, bought: 1, total_usd: 0.117 } };
  const cost = cardCost(photo as never);
  assert.equal(cost.usd, 0.117);
  assert.match(cost.text, /\$0\.12 · 배경 사진 4장/);
  assert.match(cost.text, /1장은 이미 산 사진 재사용/);
  assert.equal(cardCost({ ...photo, estimate: undefined } as never).usd, null);
});
