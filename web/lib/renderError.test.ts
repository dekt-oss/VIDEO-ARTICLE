// 순수 로직 테스트. 실행: `node --test web/lib/renderError.test.ts` (Node 22 타입 스트리핑).
// 기존 web/lib/work/steps.test.ts 와 같은 방식.
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRenderError } from "./renderError.ts";

test("ffmpeg moov atom 실패 = 파일 손상, 재시도 가능", () => {
  const r = parseRenderError(
    "[mov,mp4,m4a] moov atom not found\n/tmp/cut3.mp4: Invalid data found when processing input"
  );
  assert.equal(r.kind, "corrupt_media"); // 더 구체적인 규칙이 먼저 걸려야 한다
  assert.equal(r.retryable, true);
  assert.match(r.action, /재렌더/);
});

test("에셋 읽기 실패는 별도 분류", () => {
  const r = parseRenderError("Invalid data found when processing input: still_2.png");
  assert.equal(r.kind, "unreadable_asset");
  assert.match(r.cause, /에셋/);
});

test("예산 초과는 재시도 대상이 아니다", () => {
  const r = parseRenderError("영상 예산 초과: 요청 6클립 × 4초 > VEO_MAX_CLIPS_PER_DRAFT");
  assert.equal(r.kind, "budget");
  assert.equal(r.retryable, false); // 같은 설정으로 다시 눌러도 또 막힌다
});

test("유튜브 토큰 만료는 인증 갱신을 안내한다", () => {
  const r = parseRenderError('{"error": "invalid_grant", "error_description": "Token has been expired"}');
  assert.equal(r.kind, "youtube_auth");
  assert.match(r.action, /토큰/);
});

test("유튜브 메타데이터 거부는 인증과 구분한다", () => {
  const r = parseRenderError("HttpError 400: invalidDescription");
  assert.equal(r.kind, "youtube_metadata");
});

test("사용량 한도", () => {
  assert.equal(parseRenderError("429 RESOURCE_EXHAUSTED: quota exceeded").kind, "provider_quota");
});

test("분류 실패는 unknown 이지만 재시도 경로는 남긴다", () => {
  const r = parseRenderError("Traceback (most recent call last): KeyError: 'cut_no'");
  assert.equal(r.kind, "unknown");
  assert.equal(r.retryable, true);
  assert.match(r.action, /기술 로그/);
});

test("로그가 비어도 안내 문구가 있다", () => {
  for (const empty of [null, undefined, "", "   "]) {
    const r = parseRenderError(empty);
    assert.equal(r.kind, "unknown");
    assert.ok(r.cause.length > 0 && r.action.length > 0);
  }
});

test("설명판 시각 계약 위반은 원인과 다음 행동을 함께 안내한다", () => {
  // 실측 실패 로그(리포트 KO 렌더). 예전에는 unknown 으로 떨어져 "기술 로그를 보라"만 나왔다.
  const r = parseRenderError(
    "ValueError: DUPLICATE ON-SCREEN TEXT: '이례적인 수준의 일일 급등으로 시장의 강한 매수세를 나타냄' ↔ " +
      "'이례적인 수준의 일일 급등으로 시장의 강한 매수세를 나타냄'"
  );
  assert.equal(r.kind, "board_contract");
  // 배정 결함은 엔진에서 고쳤으므로 재렌더가 첫 행동이다. 그래도 또 잡히면 지시서를 고쳐야 한다.
  assert.equal(r.retryable, true);
  assert.match(r.action, /재렌더/);
  assert.match(r.action, /지시서/);
});

test("글자 넘침·보드 규격 위반도 같은 분류", () => {
  assert.equal(parseRenderError("TEXT TOO LONG for 2 lines @min 48px: '…'").kind, "board_contract");
  assert.equal(
    parseRenderError("컷 3 보드 규격 위반(§22-6): frame:letterbox").kind,
    "board_contract"
  );
});

test("충전율 미달은 '글자가 넘침'이 아니라 '화면이 비었다'로 안내한다", () => {
  // ★ 실측 신고(2026-08-04): 운영자 화면에 "같은 문장이 두 번 나오거나 글자가 칸을 넘침"이
  //   떴는데 실제 원인은 정반대였다. 그 안내대로 문장을 줄이면 더 나빠진다.
  const e = parseRenderError("컷 6 보드 규격 위반(§22-6): core_underfilled:0.18");
  assert.equal(e.kind, "board_underfilled");
  assert.ok(!/글자가 칸을 넘침/.test(e.cause), "반대 원인을 안내하면 안 된다");
  assert.ok(/비어/.test(e.cause));
  // 재렌더는 순수 기하 연산이라 같은 값이 나온다 — 재시도 가능으로 안내하면 안 된다.
  assert.equal(e.retryable, false);
  // 다른 규격 위반은 종전 분류를 유지한다.
  assert.equal(
    parseRenderError("컷 3 보드 규격 위반(§22-6): frame:letterbox").kind,
    "board_contract",
  );
});

test("렌더 잡 조회 라우트는 DB 오류를 '잡 없음'으로 감추지 않는다", async () => {
  // ★ 실측 사고(2026-08-04): 마이그레이션 0037 미적용 DB 에서 select 가 컬럼 부재로 실패했는데
  //   화면에는 "report render job 없음" 이 떴다. 존재하는 잡을 없다고 듣는 셈이라 원인을 못 찾는다.
  const fs = await import("node:fs/promises");
  const routes = [
    "app/api/youtube-upload/route.ts",
    "app/api/report-youtube-upload/route.ts",
    "app/api/render-manage/route.ts",
    "app/api/report-render-manage/route.ts",
    "app/api/render-result/route.ts",
    "app/api/report-render-retry/route.ts",
    "app/api/render-add-language/route.ts",
  ];
  for (const r of routes) {
    const src = await fs.readFile(new URL(`../${r}`, import.meta.url), "utf8");
    assert.match(src, /error: \w+Err/, `${r}: 조회 error 를 받지 않는다`);
    assert.match(src, /렌더 잡 조회 실패/, `${r}: DB 오류를 그대로 드러내지 않는다`);
  }
});
