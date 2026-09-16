// POST /api/report-approve — 검수 완료 대본을 report_published 에 기록. api/approve(논문) 미러.
// ★ 컴플라이언스 하드게이트 제거(사용자 요청) — compliance 는 참고 표시 전용, 승인을 막지 않는다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { isValidationCurrent } from "@/lib/scriptRevision";

import { queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";
export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = await requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.report_id || typeof body.final_script !== "string") {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  // ★ 승인 흔적(PR #94 후속 리뷰 P1-3): 지금 승인하는 대본이 **마지막 검사를 받은 그 대본**인가.
  //   막지는 않는다(운영자 결정 — 재검사가 워커 왕복 1~3분이라 차단하면 규칙이 무시당한다).
  //   대신 사실을 발행 기록에 남긴다: 나중에 문제가 생긴 편을 되짚을 때 "이 편은 검사 이후
  //   수정된 대본으로 승인됐다"를 바로 찾을 수 있다.
  const { data: draft } = await supabase
    .from("report_drafts")
    .select("validated_script_hash")
    .eq("report_id", body.report_id)
    .maybeSingle();
  const validated = isValidationCurrent(body.final_script, draft?.validated_script_hash);

  const { error } = await supabase.from("report_published").upsert(
    {
      report_id: body.report_id,
      final_script: body.final_script,
      platforms: body.platforms ?? null,
      validated_at_approval: validated,
    },
    { onConflict: "report_id" }
  );
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!validated) {
    console.warn(
      `[report-approve] 검사 이후 수정된 대본으로 승인 report=${body.report_id}`);
  }

  return NextResponse.json({ ok: true, validated_at_approval: validated });
}
