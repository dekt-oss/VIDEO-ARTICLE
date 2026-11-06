// 오늘 할 일 집계 순수 테스트 (node --test).
import test from "node:test";
import assert from "node:assert/strict";
import { homeBlockers, homeCounts, homeState, parseSnoozed, snoozeValue, weeklyProgress } from "./home.ts";
import type { Decision, WorkItem } from "./work/types.ts";

const dec = (o: Partial<Decision["primary"]> & { blocks?: Decision["blocks"] }): Decision => ({
  unitId: "u", lane: "card", blocks: o.blocks ?? [], warnings: [],
  primary: { code: "S1", label: "x", panel: "none", ...o },
});

test("타일: 판단 기다리는 작업은 사람 패널만, 진행 중은 빼고, 결과 불명은 게시·확인으로", () => {
  const c = homeCounts([
    dec({ panel: "approve" }), dec({ panel: "review", busy: true }), dec({ panel: "produce" }),
    dec({ panel: "publish" }), dec({ panel: "plan", blocks: [{ code: "spend_unknown", message: "" }] }),
  ]);
  assert.deepEqual(c, { approve: 1, publish: 2 });
});

const item = (o: Partial<WorkItem>): WorkItem => ({
  unit_id: "topic:a:card", topic_id: "a", title: "t", question: null, topic_status: "selected", topic_version: 1, format_intent: "card", source: "topic",
  editorial_week: null, pick_approved_at: null, pick_amount_usd: null, review_id: null, review_status: null, review_valid: null, review_version: null,
  develop_kind: null, develop_status: null, develop_request_id: null, develop_error_code: null, plan_revision_id: null, plan_status: null, plan_blocked: null,
  plan_version: null, plan_format: null, job_id: null, job_status: null, job_error_code: null, explainer_state: null, output_review_id: null,
  output_review_status: null, output_usable: null, meme_draft_id: null, meme_status: null, meme_sync_grade: null, meme_external_url: null,
  pub_request_id: null, pub_status: null, pub_pause_code: null, pub_publish_at: null, pub_external_url: null, pub_version: null,
  unknown_billed: false, orphan_hold: false, updated_at: "2026-11-05T01:00:00Z", ...o,
});

test("진행표: 이번 주 게시 완료만 센다(밈 posted_manual 포함), 나머지는 진행 중", () => {
  const targets = { explainer: { min: 1, max: 2 }, card: { min: 5, max: 5 }, meme: { min: 3, max: 3 } };
  const rows = weeklyProgress([
    item({ pub_status: "published", pub_publish_at: "2026-11-03T10:00:00Z" }),
    item({ unit_id: "b", pub_status: "published", pub_publish_at: "2026-10-20T10:00:00Z" }),     // 지난 주 — 안 센다
    item({ unit_id: "c", pub_status: "scheduled" }),
    item({ unit_id: "m", format_intent: "meme", meme_status: "posted_manual", updated_at: "2026-11-04T15:00:00Z" }),
  ], "2026-11-02", targets);
  const by = Object.fromEntries(rows.map((r) => [r.format, r]));
  assert.equal(by.card.done, 1);
  assert.equal(by.card.inProgress, 1);
  assert.equal(by.meme.done, 1);
  assert.equal(by.explainer.done, 0);
  assert.deepEqual(by.explainer.target, { min: 1, max: 2 });
});

test("막힘: 결과 불명·고아 보류·결재 없음·계정·크론 흔적 없음을 따로 말하고, 못 읽은 것은 '모름'으로", () => {
  const b = homeBlockers({
    hasBudget: false, accountsBlocked: [{ name: "@a", reason: "재인증 필요" }], runs: { active: 2, total: 0 },
    items: [item({ orphan_hold: true }), item({ unknown_billed: true })],
  });
  assert.deepEqual(b.map((x) => x.code), ["unknown_billed", "orphan_hold", "no_budget", "account_blocked", "cron_silent"]);
  const unknown = homeBlockers({ hasBudget: null, accountsBlocked: null, runs: null, items: [] });
  assert.deepEqual(unknown.map((x) => x.code), ["budget_unknown", "accounts_unknown", "runs_unknown"]);
  assert.deepEqual(homeBlockers({ hasBudget: true, accountsBlocked: [], runs: { active: 0, total: 0 }, items: [] }), []);
});

test("스누즈: 24시간 뒤 사라지고, 깨진 값은 없는 것으로", () => {
  const now = 1_000_000;
  const v = snoozeValue(null, "u1", now);
  assert.deepEqual([...parseSnoozed(v, now + 1)], ["u1"]);
  assert.deepEqual([...parseSnoozed(v, now + 24 * 3_600_000 + 1)], []);
  assert.deepEqual([...parseSnoozed("{broken", now)], []);
  const v2 = snoozeValue(v, "u2", now);
  assert.deepEqual([...parseSnoozed(v2, now)].sort(), ["u1", "u2"]);
});

test("빈 상태: 후보도 소재도 없음 / 소재 없음 / 전부 완료 / 할 일", () => {
  assert.equal(homeState(0, 0, 0), "no_candidates_no_work");
  assert.equal(homeState(5, 0, 0), "no_work");
  assert.equal(homeState(5, 3, 0), "all_done");
  assert.equal(homeState(null, 3, 1), "work");
});
