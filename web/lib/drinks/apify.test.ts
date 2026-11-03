// Apify 정밀화 화면 규칙(순수) — 버튼 옆 금액 문장·실행 여부·수동 카드 payload.
import test from "node:test";
import assert from "node:assert/strict";
import { APIFY_MONTH_CAP_USD, APIFY_RUN_CAP_USD, isMissingApifyTables, manualCardPayload, refineCostLine, refinePlan, requestSummary, type ApifyMonth } from "./apify.ts";

const month = (spent: number): ApifyMonth => ({ month_key: "2026-11-01", month_cap_usd: APIFY_MONTH_CAP_USD, spent_usd: spent, remaining_usd: APIFY_MONTH_CAP_USD - spent, requests: 0 });

test("상한 숫자는 결정 1 그대로(월 $3, [쓰자] $0.02, [이걸로] $0.05)", () => {
  assert.equal(APIFY_MONTH_CAP_USD, 3);
  assert.deepEqual(APIFY_RUN_CAP_USD, { meme_refine: 0.02, explainer_reference: 0.05 });
});

test("버튼 옆 한 줄: 이번 상한과 이달 누적", () => {
  assert.equal(refineCostLine(month(0.5)), "이번 상한 $0.02 · 이달 누적 $0.50 / $3.00");
  assert.match(refineCostLine(null), /0070 미적용/);
});

test("실행 여부: 정밀 틀·릴스 없음·월 상한·미적용은 돈을 안 쓴다", () => {
  assert.equal(refinePlan(month(0), { precision: "precise", examples_count: 3 }).runs, false);
  assert.equal(refinePlan(month(0), { precision: "reference", examples_count: 0 }).runs, false);
  assert.equal(refinePlan(null, { precision: "reference", examples_count: 3 }).runs, false);
  assert.equal(refinePlan(month(2.99), { precision: "reference", examples_count: 3 }).runs, false);
  const ok = refinePlan(month(2.98), { precision: "reference", examples_count: 3 });
  assert.equal(ok.runs, true);
  assert.match(ok.reason, /릴스 3개 이하/);
});

test("요청 요약은 주소를 보여 주지 않고 상태·돈·채운 칸만", () => {
  const s = requestSummary({ status: "partial", results: [{ input_url: "https://www.instagram.com/reel/x/", status: "ok", duration_sec: 11, play_count: 1 },
    { input_url: "https://www.instagram.com/reel/y/", status: "age_restricted", duration_sec: null, play_count: null }], actual_usd: 0.0123, cap_usd: 0.02, fields_written: ["beat_count", "cut_lengths"], error_code: null });
  assert.ok(!s.includes("instagram.com"));
  assert.match(s, /릴스 1\/2 받음 · 실제 \$0.0123 · 채운 칸: beat_count·cut_lengths/);
  assert.match(requestSummary({ status: "queued", results: [], actual_usd: null, cap_usd: 0.02, fields_written: [], error_code: null }), /상한 \$0.02/);
});

test("수동 카드 payload: 빈 칸은 보내지 않는다(셋 다 있어야 만든다는 판정은 DB 가 한다)", () => {
  const p = manualCardPayload({ name: " 라벨 POV ", structure: "pov", beatCount: "3", cutLengths: "3,3,4", twistAt: "6초", musicSync: "", coverText: "", note: "" });
  assert.deepEqual(p, { name: "라벨 POV", structure: "pov", fields: { beat_count: "3", cut_lengths: "3,3,4", twist_at: "6초" } });
  assert.deepEqual(manualCardPayload({ name: "x", structure: "", beatCount: "", cutLengths: "", twistAt: "", musicSync: "", coverText: "", note: "메모" }), { name: "x", fields: {}, note: "메모" });
});

test("0070 미적용 판정", () => {
  assert.equal(isMissingApifyTables('relation "public.drink_apify_month_state" does not exist'), true);
  assert.equal(isMissingApifyTables("permission denied for table drink_apify_requests"), false);
});
