// GET /api/report-directive-status?report_id=…&version_type=… — 지시서 생성 진행 상태 폴링.
// 반환: { has_directive, status }. api/directive-status(논문) 미러.
//
// ★ version_type 을 받는다: 만화식·설명판형을 각각 만들 수 있으므로, 버전을 안 걸면 만화식을
//   만드는 중에 예전 설명판형 요청의 done 을 보고 "생성 완료"로 끝난다(생기지도 않은 지시서를
//   보러 새로고침하게 된다). 하위호환을 위해 없으면 버전 무관으로 본다(기존 호출부).
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const supabase = createClient();
  const url = new URL(request.url);
  const reportId = url.searchParams.get("report_id");
  const versionType = url.searchParams.get("version_type");
  if (!reportId) return NextResponse.json({ error: "report_id required" }, { status: 400 });

  let dq = supabase.from("report_directives").select("id").eq("report_id", reportId);
  let rq = supabase
    .from("report_directive_requests")
    .select("status, error, requested_at")
    .eq("report_id", reportId);
  if (versionType) {
    dq = dq.eq("version_type", versionType);
    rq = rq.eq("version_type", versionType);
  }

  const [{ data: directive }, { data: req }] = await Promise.all([
    dq.order("created_at", { ascending: false }).limit(1).maybeSingle(),
    rq.order("requested_at", { ascending: false }).limit(1).maybeSingle(),
  ]);

  return NextResponse.json({
    has_directive: !!directive,
    status: req?.status ?? null,
    error: req?.error ?? null,
  });
}
