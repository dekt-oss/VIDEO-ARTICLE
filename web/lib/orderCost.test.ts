// 순수 로직 테스트. 실행: `node --test web/lib/orderCost.test.ts` (Node 22 타입 스트리핑).
// 기존 web/lib/work/steps.test.ts 와 같은 방식(이 저장소는 vitest 를 쓰지 않는다).
import test from "node:test";
import assert from "node:assert/strict";
import { estimateOrder, formatUsd } from "./orderCost.ts";
import type { Directive, VersionType } from "./types.ts";

function directive(key: VersionType, usd: number, unique = 4, clips = 2, sec = 8): Directive {
  return {
    id: `d-${key}`,
    paper_id: "p1",
    version_type: key,
    status: "draft",
    created_at: "",
    approved_at: null,
    cuts: [],
    header: {
      cost_plan: {
        estimated_total_generation_cost_usd: usd,
        unique_asset_count: unique,
        video_clip_count: clips,
        video_generated_sec: sec,
      },
    },
  } as unknown as Directive;
}

test("언어를 늘려도 비용은 늘지 않는다 — 에셋이 언어 공유이기 때문", () => {
  const versions = [
    { key: "comic" as VersionType, directive: directive("comic", 0.4) },
    { key: "webtoon" as VersionType, directive: directive("webtoon", 0.25) },
  ];
  const one = estimateOrder(versions, ["ko"]);
  const two = estimateOrder(versions, ["ko", "en"]);

  assert.equal(one.total, 0.65);
  assert.equal(two.total, 0.65, "언어 수가 비용에 곱해졌다 — 실제의 두 배를 보여주게 된다");
  // 다만 만들어지는 렌더 잡 수는 늘어난다(2버전 × 2언어).
  assert.equal(one.renderJobCount, 2);
  assert.equal(two.renderJobCount, 4);
});

test("버전을 늘리면 비용이 늘어난다", () => {
  const oneVersion = estimateOrder(
    [{ key: "comic" as VersionType, directive: directive("comic", 0.4) }], ["ko"]);
  const twoVersions = estimateOrder([
    { key: "comic" as VersionType, directive: directive("comic", 0.4) },
    { key: "webtoon" as VersionType, directive: directive("webtoon", 0.25) },
  ], ["ko"]);
  assert.equal(oneVersion.total, 0.4);
  assert.equal(twoVersions.total, 0.65);
});

test("지시서가 없는 버전은 합계에서 빠지고 unknown 으로 보고된다", () => {
  const r = estimateOrder([
    { key: "comic" as VersionType, directive: directive("comic", 0.4) },
    { key: "webtoon" as VersionType, directive: null },
  ], ["ko", "en"]);

  assert.equal(r.total, 0.4);
  assert.deepEqual(r.unknown, ["webtoon"]);
  assert.equal(r.perVersion[1].usd, null);
  // 잡 수도 지시서 있는 버전만 센다 — 없는 버전은 아직 승인할 대상이 없다.
  assert.equal(r.renderJobCount, 2);
});

test("cost_plan 이 없는 헤더도 죽지 않고 unknown 으로 처리된다", () => {
  const bare = { id: "d", paper_id: "p", version_type: "comic", status: "draft",
                 created_at: "", approved_at: null, cuts: [], header: {} } as unknown as Directive;
  const r = estimateOrder([{ key: "comic" as VersionType, directive: bare }], ["ko"]);
  assert.equal(r.total, 0);
  assert.deepEqual(r.unknown, ["comic"]);
});

test("버전별 내역이 모달에 필요한 값을 그대로 넘긴다", () => {
  const r = estimateOrder(
    [{ key: "webtoon" as VersionType, directive: directive("webtoon", 0.25, 4, 2, 8) }], ["ko"]);
  assert.deepEqual(r.perVersion[0],
    { key: "webtoon", usd: 0.25, uniqueAssets: 4, videoClips: 2, videoSec: 8 });
});

test("빈 발주는 0", () => {
  const r = estimateOrder([], ["ko"]);
  assert.equal(r.total, 0);
  assert.equal(r.renderJobCount, 0);
});

test("formatUsd", () => {
  assert.equal(formatUsd(0.65), "$0.65");
  assert.equal(formatUsd(0), "$0.00");
});
