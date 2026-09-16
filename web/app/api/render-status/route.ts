// GET /api/render-status?directive_id=… (또는 ?job_id=…) — 렌더 진행 상태 폴링.
// 반환: 최신 render_jobs 의 { status, progress, output_url, error_log }.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const supabase = createClient();
  const url = new URL(request.url);
  const jobId = url.searchParams.get("job_id");
  const directiveId = url.searchParams.get("directive_id");
  if (!jobId && !directiveId) {
    return NextResponse.json({ error: "job_id or directive_id required" }, { status: 400 });
  }

  let query = supabase
    .from("render_jobs")
    .select("id, status, progress, output_url, error_log, directive_id")
    .order("created_at", { ascending: false })
    .limit(1);
  query = jobId ? query.eq("id", jobId) : query.eq("directive_id", directiveId!);

  const { data } = await query.maybeSingle();
  return NextResponse.json({
    status: data?.status ?? null,
    progress: data?.progress ?? 0,
    output_url: data?.output_url ?? null,
    error_log: data?.error_log ?? null,
    job_id: data?.id ?? null,
  });
}
