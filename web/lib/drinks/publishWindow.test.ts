import assert from "node:assert/strict";
import { test } from "node:test";

import { publishWindowProblem } from "./publishWindow.ts";

test("게시 가능 시각: 07:00·23:30 은 되고 06:59·23:31·자정·새벽은 안 된다", () => {
  for (const ok of ["2026-11-05T07:00", "2026-11-05T12:30", "2026-11-05T23:30"]) assert.equal(publishWindowProblem(ok), null, ok);
  for (const bad of ["2026-11-05T06:59", "2026-11-05T23:31", "2026-11-05T00:00", "2026-11-05T03:00"]) assert.match(publishWindowProblem(bad) ?? "", /07:00~23:30/, bad);
  assert.equal(publishWindowProblem(""), null);
});
