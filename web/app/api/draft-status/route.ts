// GET /api/draft-status?paper_id=… — 초안 생성 진행 상태 폴링용.
// 반환: { has_draft, status } — status 는 최신 draft_requests.status(queued|processing|done|error).
// (getUser 가드 없음 — 0007 이후 공개 접근, /api/generate-draft·directive-status 와 정합.
//  이전엔 getUser 401 가드 때문에 anon 폴링이 조용히 실패해 항상 타임아웃했다.)
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const supabase = createClient();

  const paperId = new URL(request.url).searchParams.get("paper_id");
  if (!paperId) return NextResponse.json({ error: "paper_id required" }, { status: 400 });

  const [{ data: draft }, { data: req }, { data: dirReqs }] = await Promise.all([
    supabase.from("drafts").select("paper_id").eq("paper_id", paperId).maybeSingle(),
    supabase
      .from("draft_requests")
      .select("status, error, requested_at")
      .eq("paper_id", paperId)
      .order("requested_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    // ★ 초안 뒤 이어서 만드는 지시서(0046)의 진행 — 버전별 최신 요청 하나씩. 화면이
    //   "초안 ✓ → 지시서 만드는 중 · 3D 그래픽" 두 단계를 보여주는 데 쓴다.
    supabase
      .from("directive_requests")
      .select("version_type, status, error, requested_at")
      .eq("paper_id", paperId)
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
