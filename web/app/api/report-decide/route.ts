// POST /api/report-decide — 리포트 낙점/탈락 기록. body: { report_id, status, note? }
// api/decide(논문)의 report 미러.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

import { queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";
const VALID = new Set(["shortlisted", "picked", "rejected"]);

export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = await requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.report_id || !VALID.has(body.status)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const { error } = await supabase
    .from("report_decisions")
    .upsert(
      { report_id: body.report_id, status: body.status, note: body.note ?? null },
      { onConflict: "report_id" }
    );

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
