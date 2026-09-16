// POST /api/report-compliance-check — [재검사] 편집된 대본으로 컴플라이언스 + 근거 게이트 재실행.
//
// ★ 워커가 정본이다(v3 P1 결정을 재검사에도 적용). 예전에는 여기서 generate-report-draft
//   엣지 함수를 recheck 모드로 불렀는데, 근거 게이트(§5)·논증 설계(§6) 재계산은
//   engine/report_draft.recheck_compliance 에만 있고 엣지에는 없다. 그래서 대본을 고치고
//   재검사를 눌러도 근거 경고가 옛날 것으로 남았고, recheck_compliance 는 HTTP 호출자가
//   하나도 없는 죽은 함수였다.
//
//   지금은 report_draft_requests 에 mode='recheck' 로 적재하고 report-draft 워크플로를 바로
//   디스패치한다(초안 생성과 같은 방식). 디스패치가 안 되면 크론이 폴백인데, 2026-08-12 부터
//   그 크론은 하루 3번(KST 09/15/21)이라 대기가 몇 시간이다 — 실패 문구가 그렇게 안내한다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOperator } from "@/lib/apiGuard";
import { triggerReportDraft } from "@/lib/trigger-render";

import { queueWriter } from "@/lib/supabase/admin";
export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());
  const body = await request.json().catch(() => null);
  if (!body?.report_id) {
    return NextResponse.json({ error: "report_id required" }, { status: 400 });
  }

  // 편집한 대본을 먼저 저장(전달된 경우)해 재검사가 최신본을 보게 한다.
  // ★ 이 저장이 큐 적재보다 **먼저** 끝나야 한다 — 워커가 옛 대본을 읽으면 재검사가 무의미하다.
  if (typeof body.script_md === "string" || Array.isArray(body.scenes)) {
    const patch: Record<string, unknown> = {};
    if (typeof body.script_md === "string") patch.script_md = body.script_md;
    if (Array.isArray(body.scenes)) patch.scenes = body.scenes;
    const { error } = await supabase
      .from("report_drafts").update(patch).eq("report_id", body.report_id);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // 같은 리포트의 대기 중인 재검사 요청이 있으면 겹쳐 넣지 않는다.
  const { data: existing } = await supabase
    .from("report_draft_requests")
    .select("id")
    .eq("report_id", body.report_id)
    .eq("mode", "recheck")
    .in("status", ["queued", "processing"])
    .maybeSingle();

  if (!existing) {
    const { error } = await supabase
      .from("report_draft_requests")
      .insert({ report_id: body.report_id, status: "queued", mode: "recheck" });
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // 큐에 넣고 바로 워커를 부른다(초안 생성과 같은 방식). 실패해도 크론이 폴백이다.
  const t = await triggerReportDraft();
  return NextResponse.json(
    {
      ok: true,
      status: t.triggered ? "processing" : "queued",
      note: t.triggered
        ? "재검사를 시작했습니다(1~3분)"
        : `워커 자동 시작 실패(${t.reason ?? "미상"}) — 큐에는 넣었습니다. 다음 안전망 크론(KST 09/15/21)까지 대기합니다. 급하면 GitHub Actions 탭에서 report-draft 를 직접 실행하세요.`,
    },
    { status: 202 }
  );
}
