// AI 사실 확인 화면 계산(lib/drinks/factcheck.ts) — 순수 함수 시험. DB·네트워크 없음.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  FACTCHECK_NOTE, evidenceLockReason, factcheckFor, isAutoFetched, isAutoSupported, isQuestionOrigin, parseFactcheck,
} from "./factcheck.ts";
import { depthLabel } from "./model.ts";
import { isOfficialSourceUrl, officialSourceHits } from "./officialSources.ts";

const FIX = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../../tests/fixtures/drinks_factcheck/worker_payloads.json"), "utf8"));

const result = (over: Record<string, unknown> = {}) => ({
  factcheck: {
    status: "ok",
    assertions: [
      { assertion_ko: "사케에는 날짜가 있다", verdict: "TRUE", model_verdict: "TRUE", claim_ids: ["c1"], reason_ko: "인용이 말한다", code_note: null,
        sources: [{ claim_id: "c1", title: "국세청", url: "https://www.nta.go.jp/x", publisher: "国税庁" }] },
      { assertion_ko: "바로 상한다", verdict: "UNCERTAIN", model_verdict: "TRUE", claim_ids: [], reason_ko: "", code_note: "근거 목록에 없는 번호를 댔음(c9)", sources: [] },
      { assertion_ko: "", verdict: "TRUE" },
    ],
    auto_supported: ["c1"],
    not_supported: [{ claim_id: "c2", why: "맞음·틀림 판정의 근거로 쓰이지 않음", text: "주장 2" }],
    ...over,
  },
});

test("판정 읽기: 빈 주장은 버리고, 모르는 값은 불확실, 개수는 다시 센다", () => {
  const fc = parseFactcheck(result())!;
  assert.equal(fc.status, "ok");
  assert.equal(fc.assertions.length, 2);
  assert.deepEqual(fc.counts, { TRUE: 1, FALSE: 0, UNCERTAIN: 1 });
  assert.deepEqual(fc.autoSupported, ["c1"]);
  assert.equal(fc.notSupported[0].claim_id, "c2");
  assert.equal(fc.assertions[1].code_note, "근거 목록에 없는 번호를 댔음(c9)");
  const weird = parseFactcheck(result({ status: "???", assertions: [{ assertion_ko: "x", verdict: "MAYBE" }] }))!;
  assert.equal(weird.status, "failed", "모르는 상태는 '못 함'으로 — 괜찮다고 보이지 않게");
  assert.equal(weird.assertions[0].verdict, "UNCERTAIN");
  assert.equal(parseFactcheck({}), null);
  assert.equal(parseFactcheck(null), null);
});

test("어느 요청의 판정을 보여 주나: 지금 근거 버전을 만든 요청 > 가장 최근 요청(이전 버전 표시)", () => {
  const reqs = [
    { kind: "evidence", status: "succeeded", result: result(), result_review_id: "r1", created_at: "2026-11-05T00:00:00Z" },
    { kind: "evidence", status: "succeeded", result: result({ auto_supported: ["c9"] }), result_review_id: "r2", created_at: "2026-11-06T00:00:00Z" },
    { kind: "plan", status: "succeeded", result: {}, result_review_id: null, created_at: "2026-11-07T00:00:00Z" },
    { kind: "evidence", status: "failed", result: result(), result_review_id: null, created_at: "2026-11-08T00:00:00Z" },
  ];
  assert.deepEqual(factcheckFor(reqs, "r1")?.fc.autoSupported, ["c1"]);
  assert.equal(factcheckFor(reqs, "r1")?.sameReview, true);
  const other = factcheckFor(reqs, "r3")!;
  assert.equal(other.sameReview, false);
  assert.deepEqual(other.fc.autoSupported, ["c9"]);
  assert.equal(factcheckFor([], "r1"), null);
});

test("'AI 확인' 표시는 확인됨 + 자동 문구일 때만 — 사람이 다른 값을 고르면 사라진다", () => {
  assert.equal(isAutoSupported({ support_review: "supported", limitations: FACTCHECK_NOTE }), true);
  assert.equal(isAutoSupported({ support_review: "insufficient", limitations: FACTCHECK_NOTE }), false);
  assert.equal(isAutoSupported({ support_review: "supported", limitations: null }), false);
  // 워커가 오늘 저장하는 값으로도 같은 답(엔진 문구와 화면 문구가 같다)
  const claims = FIX.save_evidence.evidence_pack.claims;
  assert.deepEqual(claims.filter(isAutoSupported).map((c: { claim_id: string }) => c.claim_id), FIX.factcheck.auto_supported);
});

test("AI 초안 요청이 대기·진행 중이면 근거를 잠그고 왜인지 말한다", () => {
  assert.equal(evidenceLockReason([{ kind: "evidence", status: "succeeded" }]), null);
  assert.match(evidenceLockReason([{ kind: "evidence", status: "queued" }])!, /draft_exists/);
  assert.match(evidenceLockReason([{ kind: "evidence", status: "queued" }])!, /기다리는 중/);
  assert.match(evidenceLockReason([{ kind: "plan", status: "running" }])!, /대본.*무효/);
});

test("질문이 나온 곳·자동으로 가져온 쪽 알아보기, 깊이 이름", () => {
  assert.equal(isQuestionOrigin("discovery", "official"), true);
  assert.equal(isQuestionOrigin("evidence", "community"), true);
  assert.equal(isQuestionOrigin("evidence", "official"), false);
  assert.equal(isAutoFetched("자동 개발: 공식 출처 목록에서 가져온 원문", false), true);
  assert.equal(isAutoFetched(null, isOfficialSourceUrl("https://www.nta.go.jp/law/tsutatsu/kihon/sake/8-09a.htm")), true, "옛 기록은 주소로");
  assert.equal(isAutoFetched(null, isOfficialSourceUrl("https://example.org/a")), false);
  assert.equal(depthLabel("full_text", "manual"), "원문 전문 직접 입력");
  assert.equal(depthLabel("full_text", "manual", true), "AI 가 공식 출처에서 가져온 원문 전문");
  assert.equal(depthLabel("full_text", "collected"), "수집한 본문");
  assert.match(depthLabel("metadata_only", "manual", true), /본문 미확보/);
});

test("공식 출처 목록: 보관·기한 질문은 보관 전용 쪽만 센다", () => {
  assert.equal(officialSourceHits("개봉한 위스키 보관 어떻게 해요").count, 1);
  assert.ok(officialSourceHits("사케 유통기한 있나요").count >= 1);
  assert.equal(officialSourceHits("위스키 맛 차이").count, 0, "보관 낱말이 없으면 보관 전용 쪽은 세지 않는다");
  assert.equal(officialSourceHits("막걸리 유통기한 알려주세요").count, 0, "막걸리 보관은 아직 비어 있다");
});
