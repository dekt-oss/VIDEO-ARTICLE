// 순수 로직 테스트. 실행: `node --test web/lib/versions.test.ts` (Node 22 타입 스트리핑).
// 기존 web/lib/orderCost.test.ts 와 같은 방식(이 저장소는 vitest 를 쓰지 않는다).
//
// 검사 대상은 "발주 가능한 버전 목록". 2026-08-28 운영자 결정으로 웹툰·설명판형을 뺐다
// (docs/deviation-drop-explainer-webtoon.md) — 두 공장 모두 만화식·3D 그래픽만 만든다.
// 저장된 옛 행은 계속 열려야 하므로 라벨·타입은 남는다.
import test from "node:test";
import assert from "node:assert/strict";
import {
  VERSION_KEYS,
  REPORT_VERSION_KEYS,
  REPORT_DEFAULT_VERSION_KEY,
  isOfferedVersion,
  isOfferedReportVersion,
  reportVersionLabel,
  VERSION_META,
  REPORT_VERSION_META,
} from "./versions.ts";

test("두 공장 모두 만화식·3D 그래픽만 발주한다", () => {
  assert.deepEqual(REPORT_VERSION_KEYS, ["comic", "photo"]);
  assert.deepEqual(VERSION_KEYS, ["comic", "photo"]);
  assert.equal(REPORT_DEFAULT_VERSION_KEY, "comic");
});

test("폐기된 버전은 어느 화면에서도 발주할 수 없다", () => {
  for (const dead of ["webtoon", "explainer", "editorial"]) {
    assert.equal(VERSION_KEYS.includes(dead as never), false, `논문 화면에 남았다: ${dead}`);
    assert.equal(REPORT_VERSION_KEYS.includes(dead as never), false, `리포트 화면에 남았다: ${dead}`);
  }
});

test("?v= 검증은 발주 가능한 버전만 통과시킨다", () => {
  assert.equal(isOfferedReportVersion("comic"), true);
  assert.equal(isOfferedReportVersion("photo"), true);
  // 폐기된 버전을 ?v= 로 요청해도 통과시키지 않는다(기본값으로 떨어진다).
  assert.equal(isOfferedReportVersion("webtoon"), false);
  assert.equal(isOfferedReportVersion("explainer"), false);
  assert.equal(isOfferedReportVersion("editorial"), false);
  assert.equal(isOfferedReportVersion(undefined), false);
  assert.equal(isOfferedReportVersion(""), false);
  // 논문 쪽 검증도 대칭으로 동작한다.
  assert.equal(isOfferedVersion("comic"), true);
  assert.equal(isOfferedVersion("photo"), true);
  assert.equal(isOfferedVersion("webtoon"), false);
  assert.equal(isOfferedVersion("explainer"), false);
});

test("라벨은 저장된 옛 버전에도 무언가를 돌려준다", () => {
  assert.equal(reportVersionLabel("comic"), "만화식");
  // 폐기 버전은 목록에서 빠져 라벨이 없다 — 빈 문자열 대신 원래 키를 보여준다(⑥ 화면의
  // 옛 렌더 뱃지가 비어 보이지 않게).
  assert.equal(reportVersionLabel("explainer"), "explainer");
  assert.equal(reportVersionLabel("editorial"), "editorial");
});

test("표시 이름은 3D 그래픽이고 저장 키는 photo 그대로다", () => {
  // ★ 2026-09-08 운영자 지시로 이름만 바꿨다("실사형" → "3D 그래픽"). 화풍을 무광 CG 로
  //   확정하면서 REALITY 컷도 더는 사진이 아니라, 이름이 화면과 어긋나 있었다.
  //   ★★ **키는 절대 바꾸지 않는다** — 저장된 지시서·렌더 잡·업로드가 전부 `photo` 를 쓴다.
  //   이 테스트는 다음 사람이 "이름 바꾼 김에 키도" 하는 것을 막는다.
  assert.equal(reportVersionLabel("photo"), "3D 그래픽");
  assert.equal(VERSION_META.find((v) => v.key === "photo")?.label, "3D 그래픽");
  assert.equal(VERSION_KEYS.includes("photo"), true);
  for (const meta of [VERSION_META, REPORT_VERSION_META]) {
    assert.equal(meta.some((v) => v.label.includes("실사")), false, "옛 이름이 남았다");
  }
});
