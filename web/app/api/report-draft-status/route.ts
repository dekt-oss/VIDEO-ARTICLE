// GET /api/report-draft-status?report_id=… — 초안 생성 진행 상태 폴링. api/draft-status 미러.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const supabase = createClient();

  const reportId = new URL(request.url).searchParams.get("report_id");
  if (!reportId) return NextResponse.json({ error: "report_id required" }, { status: 400 });

  const [{ data: draft }, { data: req }, { data: dirReqs }] = await Promise.all([
    supabase.from("report_drafts").select("report_id").eq("report_id", reportId).maybeSingle(),
    supabase
      .from("report_draft_requests")
      .select("status, error, requested_at")
      .eq("report_id", reportId)
      .order("requested_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    // ★ 초안 뒤 이어서 만드는 지시서(0046)의 진행 — 버전별 최신 요청 하나씩(논문 draft-status 미러).
    supabase
      .from("report_directive_requests")
      .select("version_type, status, error, requested_at")
      .eq("report_id", reportId)
      .order("requested_at", { ascending: false })
      .limit(20),
  ]);

  const directive: Record<string, { status: string; error: string | null }> = {};
  for (const r of dirReqs ?? []) {
    const v = String(r.version_type ?? "");
    if (v && !directive[v]) directive[v] = { status: String(r.status ?? ""), error: r.error ?? null };
  }

  return NextResponse.json({
    has_draft: !!draft,
    status: req?.status ?? null,
    error: req?.error ?? null,
    directive,
  });
}
