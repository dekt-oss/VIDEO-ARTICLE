// 주류 B단계 화면 규칙 — 실행 결과 문장·재시도 대상·수집원 버튼·비슷한 소재 후보.
import test from "node:test";
import assert from "node:assert/strict";

import { canRetry, runStuck, runSummary, runTone, similarTopics, sourceActions } from "./collect.ts";

const base = { item_count: 0, new_count: 0, changed_count: 0, unchanged_count: 0, metadata_count: 0, skipped_count: 0,
  failed_count: 0, error_code: null };

test("정상 0건과 실패 0건은 문장·색이 다르다", () => {
  const empty = runSummary({ ...base, status: "empty" });
  const failed = runSummary({ ...base, status: "failed", error_code: "http_error" });
  assert.match(empty, /정상 0건/);
  assert.match(failed, /실패/);
  assert.notEqual(empty, failed);
  assert.equal(runTone("empty"), "ok");
  assert.equal(runTone("failed"), "bad");
  assert.equal(runTone("partial"), "warn");
  assert.equal(runTone("aborted"), "warn");
  assert.match(runSummary({ ...base, status: "partial", item_count: 3, new_count: 2, failed_count: 1 }), /새 2 · 실패 1/);
});

test("재시도는 부분 성공·실패·중단된 수집 실행만", () => {
  assert.equal(canRetry({ status: "partial", mode: "collect" }), true);
  assert.equal(canRetry({ status: "aborted", mode: "retry" }), true);
  assert.equal(canRetry({ status: "failed", mode: "validate" }), false);
  assert.equal(canRetry({ status: "empty", mode: "collect" }), false);
  assert.equal(canRetry({ status: "succeeded", mode: "collect" }), false);
});

test("수집원 버튼: 이용 조건 미확인이면 활성화가 없고, 수동 URL 수집원은 실행 버튼이 없다", () => {
  const a = sourceActions({ state: "validated", terms_status: "unverified", method: "approved_page" }, "succeeded");
  assert.equal(a.activate, false);
  assert.equal(a.collectNow, false);
  const b = sourceActions({ state: "validated", terms_status: "verified", method: "listing" }, "succeeded");
  assert.equal(b.activate, true);
  assert.equal(sourceActions({ state: "paused", terms_status: "verified", method: "listing" }, "failed").activate, false,
    "가장 최근 검증이 실패면 활성화 버튼이 없다");
  const m = sourceActions({ state: "proposed", terms_status: "verified", method: "manual_url" }, null);
  assert.equal(m.validateRun, false);
  assert.equal(m.markValidated, false);
  const r = sourceActions({ state: "proposed", terms_status: "restricted", method: "feed" }, "succeeded");
  assert.equal(r.validateRun, false);
  assert.equal(r.markValidated, false);
});

test("비슷한 소재 후보: 겹치는 제목만, 중복 처리된 소재는 빼고, 판정이 아니라 후보 순위", () => {
  const topics = [
    { id: "1", title: "사케 지리적 표시 제도", question: "GI 는 무엇을 보장할까?", status: "triaged" },
    { id: "2", title: "위스키 숙성 연수", question: "12년은 어느 원액 기준일까?", status: "inbox" },
    { id: "3", title: "사케 지리적 표시 제도", question: "중복", status: "duplicate" },
  ];
  const s = similarTopics("사케의 지리적 표시 제도 개정", topics);
  assert.deepEqual(s.map((x) => x.topic.id), ["1"]);
  assert.deepEqual(similarTopics("", topics), []);
});

test("임대가 끝난 running 실행은 멈춘 것으로 본다", () => {
  const now = Date.parse("2026-10-22T10:00:00Z");
  assert.equal(runStuck({ status: "running", lease_expires_at: "2026-10-22T09:59:00Z" }, now), true);
  assert.equal(runStuck({ status: "running", lease_expires_at: "2026-10-22T10:05:00Z" }, now), false);
  assert.equal(runStuck({ status: "failed", lease_expires_at: "2026-10-22T09:00:00Z" }, now), false);
});
