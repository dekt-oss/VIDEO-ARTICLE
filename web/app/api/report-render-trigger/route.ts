// POST /api/report-render-trigger — "지금 렌더" 버튼. report-video.yml(render) 워커를 즉시 트리거.
import { NextResponse } from "next/server";
import { triggerReportRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";

export async function POST() {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const trig = await triggerReportRender("render");
  return NextResponse.json({ ok: true, triggered: trig.triggered, reason: trig.reason });
}
