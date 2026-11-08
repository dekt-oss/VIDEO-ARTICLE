import test from "node:test";
import assert from "node:assert/strict";

import { groupSimilar, isAnswerable, isStopped } from "./studioList.ts";

const row = (id: string, text: string, cat = "traditional") => ({ id, text, categories: [cat] });
// 희귀도 계산이 뜻을 가지려면 서로 다른 질문이 섞여 있어야 한다.
const noise = ["누룩이란 무엇인가", "증류기는 왜 구리일까", "정미율 뜻", "오크통을 왜 태울까", "라벨 읽는 법", "도수가 높으면 좋은 술일까"].map((t, i) => row(`n${i}`, t, "other"));

test("같은 질문의 다른 표현은 한 묶음이 되고 대표는 맨 앞(점수 높은) 것이다", () => {
  const { groups } = groupSimilar([row("a", "왜 비오는 날 막걸리와 파전이 생각날까요"), row("b", "비오는날 왜 막걸리와 파전이 당길까"), row("c", "왜 비오는 날에는 파전과 막걸리 생각이 간절할까요"), ...noise]);
  const g = groups.find((x) => x.lead.id === "a")!;
  assert.equal(g.merged, 2);
  assert.ok(!groups.some((x) => x.lead.id === "b" || x.lead.id === "c"));
});

test("주종이 다르면 같은 표현이어도 묶지 않는다", () => {
  const { groups } = groupSimilar([row("a", "남은 막걸리 어떻게 보관해야 할까"), row("b", "남은 사케 어떻게 보관해야 할까", "sake"), ...noise]);
  assert.ok(groups.some((x) => x.lead.id === "a") && groups.some((x) => x.lead.id === "b"));
});

test("이미 있는 소재와 비슷한 후보는 목록에 남기지 않는다", () => {
  const r = groupSimilar([row("a", "생막걸리와 살균막걸리의 차이점은 어떻게 되나요"), ...noise], [row("t", "생막걸리와 살균막걸리, 라벨에서 뭐가 다를까")]);
  assert.equal(r.droppedAsExisting, 1);
  assert.ok(!r.groups.some((x) => x.lead.id === "a"));
});

test("취향을 묻는 글은 근거로 답할 수 없다", () => {
  assert.equal(isAnswerable("여러분이 제일 좋아하는 막걸리는 뭔가요??"), false);
  assert.equal(isAnswerable("술 추천 부탁드려도 될까요"), false);
  assert.equal(isAnswerable("막걸리는 왜 흔들어 마실까"), true);
});

test("자료 부족으로 멈춘 소재는 빼고, 자동 복구되는 실패는 남긴다", () => {
  const rec = ["worker_error"];
  assert.equal(isStopped({ status: "blocked", error_code: "evidence_insufficient" }, rec), true);
  assert.equal(isStopped({ status: "failed", error_code: "worker_error" }, rec), false);
  assert.equal(isStopped({ status: "failed", error_code: "budget_exceeded" }, rec), true);
  assert.equal(isStopped({ status: "succeeded", error_code: null }, rec), false);
  assert.equal(isStopped(null, rec), false);
});
