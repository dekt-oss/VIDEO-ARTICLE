// GET /api/directive-status?paper_id=…&version_type=… — 지시서 생성 진행 상태 폴링.
// 반환: { has_directive, status } — status 는 최신 directive_requests.status.
// (getUser 가드 없음 — 0007 이후 공개 접근, /api/generate-draft 와 정합)
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const supabase = createClient();
  const url = new URL(request.url);
  const paperId = url.searchParams.get("paper_id");
  const versionType = url.searchParams.get("version_type") ?? "image_sequence";
  if (!paperId) return NextResponse.json({ error: "paper_id required" }, { status: 400 });

  const [{ data: directive }, { data: req }] = await Promise.all([
    supabase
      .from("directives")
      .select("id")
      .eq("paper_id", paperId)
      .eq("version_type", versionType)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabase
      .from("directive_requests")
      .select("status, error, requested_at")
      .eq("paper_id", paperId)
      .eq("version_type", versionType)
      .order("requested_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);

  return NextResponse.json({
    has_directive: !!directive,
    status: req?.status ?? null,
    error: req?.error ?? null,
  });
}
