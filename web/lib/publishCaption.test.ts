// 리포트 설명란 쌍둥이 검사. 실행: `node --test web/lib/publishCaption.test.ts`.
// 파이썬(engine/report_attribution.py)과 같은 정답 파일을 읽는다 — tests/test_report_caption_twin.py.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildReportPublishCaption } from "./publishCaption.ts";

const golden = JSON.parse(readFileSync(new URL("../../tests/report_caption_golden.json", import.meta.url), "utf-8"));

test("리포트 설명란이 업로드 워커와 글자까지 같다", () => {
  for (const f of golden.fixtures) {
    assert.equal(buildReportPublishCaption(f.report, f.teaser, f.lang), f.expect);
  }
});
