// POST /api/report-directive-approve — 지시서 승인 → 렌더 큐 + report-video.yml(render) 트리거.
// body: { directive_id, langs? }. api/directive-approve(논문) 미러(report_* 타깃).
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerReportRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";
import { queueWriter } from "@/lib/supabase/admin";
import { RENDER_STATUS_ACTIVE } from "@/lib/renderStatus";

export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());
  const body = await request.json().catch(() => null);
  if (!body?.directive_id) {
    return NextResponse.json({ error: "directive_id required" }, { status: 400 });
  }

  const { data: directive } = await supabase
    .from("report_directives")
    .select("id, status, version_type, header")
    .eq("id", body.directive_id)
    .maybeSingle();
  if (!directive) return NextResponse.json({ error: "directive 없음" }, { status: 404 });

  // 설명판형 게이트(개선명세 v3.3 §9-1) — 클라이언트 버튼만 잠그면 라우트를 직접 부르면 통과한다.
  // 판정은 엔진이 지시서에 박아 둔 값을 쓴다(웹에서 재판정하지 않는다 — 규칙이 갈린다).
  const header = (directive.header ?? {}) as { explainer?: { gate?: { block_reasons?: string[] } } };
  const blockReasons = header.explainer?.gate?.block_reasons ?? [];
  if (blockReasons.length > 0) {
    if (!body.force) {
      return NextResponse.json(
        { error: "설명판형 필수 조건 미달 — 지시서를 재생성하세요.", block_reasons: blockReasons },
        { status: 409 }
      );
    }
    // 우회는 허용하되 조용히 넘기지 않는다(운영 사고 추적용).
    console.warn(
      `[report-directive-approve] explainer 게이트 우회: directive=${body.directive_id} 사유=${blockReasons.join(",")}`
    );
  }

  const ALLOWED = ["ko", "en"];
  const reqLangs: string[] = Array.isArray(body.langs) ? body.langs : ["ko"];
  const langs = [...new Set(reqLangs.filter((l) => ALLOWED.includes(l)))];
  if (langs.length === 0) langs.push("ko");

  const { error: upErr } = await supabase
    .from("report_directives")
    .update({ status: "approved", approved_at: new Date().toISOString() })
    .eq("id", body.directive_id);
  if (upErr) return NextResponse.json({ error: upErr.message }, { status: 500 });

  const { data: activeJobs } = await supabase
    .from("report_render_jobs")
    .select("id, lang")
    .eq("directive_id", body.directive_id)
    .in("status", RENDER_STATUS_ACTIVE);   // ★ lib/renderStatus 가 정본
  const activeLangs = new Set((activeJobs ?? []).map((j) => j.lang ?? "ko"));

  const toInsert = langs
    .filter((l) => !activeLangs.has(l))
    .map((l) => ({ directive_id: body.directive_id, status: "queued", progress: 0, lang: l }));
  if (toInsert.length > 0) {
    const { error: jobErr } = await queueWriter(supabase).from("report_render_jobs").insert(toInsert);
    if (jobErr) return NextResponse.json({ error: jobErr.message }, { status: 500 });
  }

  const trig = await triggerReportRender("render");
  return NextResponse.json({ ok: true, status: "queued", langs, rendering: trig.triggered });
}
