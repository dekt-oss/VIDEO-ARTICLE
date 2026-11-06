// [이걸로 ▾] 모달 순수 규칙 테스트 (node --test). 화면 없이 규칙만 본다.
import test from "node:test";
import assert from "node:assert/strict";
import {
  PICK_FORMAT_MAX, costSummary, normalizeEstimate, pickOutcomes, pickability, toggleFormat, validateFormats, weekOptions,
} from "../../../lib/drinks/pickModal.ts";

test("형식 체크: 0개는 막고, 중복은 한 번만, 3개 초과는 막는다", () => {
  assert.equal(validateFormats([]).ok, false);
  const dup = toggleFormat(["explainer", "explainer"], "card", true);
  assert.deepEqual(dup, ["explainer", "card"]);
  assert.deepEqual(toggleFormat(["explainer", "card"], "explainer", false), ["card"]);
  assert.deepEqual(toggleFormat(["explainer"], "bogus", true), ["explainer"]);        // 모르는 형식은 버린다
  const over = validateFormats(["explainer", "card", "meme", "explainer"]);           // 중복 지우면 3개 → 통과
  assert.equal(over.ok, true);
  assert.equal(PICK_FORMAT_MAX, 3);
  // 상한 초과는 PICK_FORMATS 가 3개뿐이라 자연히 못 만든다 — 규칙 자체는 남겨 둔다(형식이 늘어도 막는다).
});

test("편성 주차: 오늘이 속한 주 월요일부터, 첫째는 이번 주", () => {
  const w = weekOptions("2026-11-05", 3);        // 목요일
  assert.deepEqual(w.map((x) => x.value), ["2026-11-02", "2026-11-09", "2026-11-16"]);
  assert.match(w[0].label, /^이번 주 · 11월 2일–8일$/);
  assert.match(w[1].label, /^다음 주/);
  assert.equal(weekOptions("2026-11-02", 1)[0].value, "2026-11-02");   // 월요일이면 그날
});

test("비용 요약: 모르는 값은 '모름'이고 0 으로 쓰지 않는다 · 합계는 하나라도 모르면 모름", () => {
  const est = normalizeEstimate({ explainer: 0.15, card: null, meme: 0 });
  const s = costSummary(est, ["explainer", "card"]);
  assert.equal(s.lines[0].text, "$0.15");
  assert.equal(s.lines[1].text, "모름");
  assert.equal(s.totalKnown, false);
  assert.match(s.total, /^모름/);
  assert.doesNotMatch(s.total, /\$0\.00/);
  const known = costSummary(est, ["explainer", "meme"]);
  assert.equal(known.total, "$0.15");                 // 진짜 0 은 더해진다
  assert.equal(known.lines[1].text, "$0.00");
  assert.equal(costSummary(est, []).totalKnown, false);
});

test("예상 비용 응답 모양 셋을 다 읽고, 모르는 모양은 전부 모름", () => {
  assert.deepEqual(normalizeEstimate({ per_format: { explainer: "0.12" } }), { explainer: 0.12, card: null, meme: null });
  // queries.ts DevelopEstimate 모양: per_format[f] = { usd, shared }, total_usd 는 따로
  assert.deepEqual(normalizeEstimate({ total_usd: 0.2, per_format: { explainer: { usd: 0.15, shared: true }, card: { usd: 0.05 } } }),
    { explainer: 0.15, card: 0.05, meme: null });
  assert.deepEqual(normalizeEstimate([{ format_intent: "card", est_usd: 0.05 }, { format: "meme", usd: null }]), { explainer: null, card: 0.05, meme: null });
  assert.deepEqual(normalizeEstimate({ formats: [{ format_intent: "explainer", amount_usd: 1 }] }), { explainer: 1, card: null, meme: null });
  assert.deepEqual(normalizeEstimate("nope"), { explainer: null, card: null, meme: null });
  assert.deepEqual(normalizeEstimate(undefined), { explainer: null, card: null, meme: null });
});

test("응답 갈래: 깨움 / 다음 크론 / 이미 있음 / 실패 — 형식마다 따로", () => {
  const out = pickOutcomes({ picks: [
    { format_intent: "explainer", queued: true },
    { format_intent: "card", queued: true, existing: true },
    { format_intent: "meme", ok: false, code: "meme_board", error: "보드에서" },
  ] }, ["explainer", "card", "meme"], { triggered: true });
  assert.deepEqual(out.map((o) => o.branch), ["queued_woken", "existing", "failed"]);
  assert.match(out[2].text, /meme_board: 보드에서/);
  const wait = pickOutcomes({ picks: [{ format_intent: "explainer", queued: true }] }, ["explainer"], { triggered: false });
  assert.equal(wait[0].branch, "queued_wait");
  // 응답에 없는 형식은 실패(누락)로 — 성공처럼 보이지 않는다
  const missing = pickOutcomes({ picks: [] }, ["card"], undefined);
  assert.equal(missing[0].branch, "failed");
  // 옛 응답(chain 하나)은 첫 형식으로 읽는다
  const old = pickOutcomes({ chain: { queued: true } }, ["card"], { triggered: false });
  assert.equal(old[0].branch, "queued_wait");
  // 큐에도 안 넣고 오류도 아니면(밈: 형식만 적어 둠) 적어 둔 것으로
  const noted = pickOutcomes({ picks: [{ format_intent: "meme", queued: false, message: "적어 둠" }] }, ["meme"], undefined);
  assert.equal(noted[0].branch, "existing");
});

test("고를 수 있나: 승격됨 · 점수 없음 · 중복 · 결재 없음 순으로 막힘, 아니면 가능", () => {
  const base = { status: "suggested", promoted_topic_id: null, duplicate_topic_ids: [] as string[], provisional_score: 70 };
  assert.equal(pickability(base, true).ok, true);
  assert.equal((pickability({ ...base, status: "promoted", promoted_topic_id: "t" }, true) as { code: string }).code, "promoted");
  assert.equal((pickability({ ...base, provisional_score: null }, true) as { code: string }).code, "no_score");
  assert.equal((pickability({ ...base, duplicate_topic_ids: ["a"] }, true) as { code: string }).code, "duplicate");
  assert.equal((pickability(base, false) as { code: string }).code, "no_budget");
});
