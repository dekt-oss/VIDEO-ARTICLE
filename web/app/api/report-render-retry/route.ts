// POST /api/report-render-retry — ⑥ 리포트 렌더 재시도. body: { job_id }
//
// 논문 라인은 실패 카드에 "↻ 재렌더"(=/api/render-result action=reject)가 있었는데 리포트 라인에는
// 아예 없었다 — 실패하면 운영자가 할 수 있는 일이 "삭제"뿐이었고, 원인을 고친 뒤에도 그 편을 다시
// 만들 방법이 화면에 없었다. 여기서 같은 행동을 리포트 큐에 붙인다.
//
// 논문 라인과 같은 방식으로 **새 큐 행을 넣는다**(실패 행을 되살리지 않는다). 실패 기록은 원인
// 추적용으로 남고, 새 잡이 처음부터 돈다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerReportRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";
import { queueWriter } from "@/lib/supabase/admin";
import { RENDER_STATUS_ACTIVE } from "@/lib/renderStatus";

const ACTIVE = RENDER_STATUS_ACTIVE;   // ★ lib/renderStatus 가 정본

export async function POST(request: Request) {
  // 재렌더는 이미지·클립·TTS 를 다시 만들 수 있다 = 돈이 나간다. 비용 라우트 게이트.
  const denied = requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());
  const body = await request.json().catch(() => null);
  if (!body?.job_id) return NextResponse.json({ error: "job_id required" }, { status: 400 });

  const { data: job, error: jobErr } = await supabase
    .from("report_render_jobs")
    .select("id, directive_id, lang, status")
    .eq("id", body.job_id)
    .maybeSingle();
  // ★ 조회 **오류**와 **행 없음**을 구분해서 말한다. 예전에는 error 를 버리고
  //   무조건 "없음"이라고 답했다 — 마이그레이션 0037 이 안 올라간 DB 에서 이 select 가
  //   `degraded_approved_at` 컬럼 부재로 실패했는데, 화면에는 "잡 없음"이 떴다(실측
  //   2026-08-04, 유튜브 업로드 불가). 운영자가 존재하는 잡을 없다고 듣는 셈이라
  //   원인을 영원히 못 찾는다. 스키마·권한 오류는 그대로 드러낸다.
  if (jobErr) {
    return NextResponse.json(
      { error: `렌더 잡 조회 실패: ${jobErr.message}` },
      { status: 500 },
    );
  }
  if (!job) return NextResponse.json({ error: "render job 없음" }, { status: 404 });
  if (job.status !== "failed") {
    return NextResponse.json({ error: "실패한 잡만 재렌더할 수 있습니다" }, { status: 409 });
  }

  // 같은 지시서·같은 언어가 이미 큐에 있으면 또 넣지 않는다 — 버튼을 두 번 눌러 비용이 두 배로
  // 나가는 것을 막는다(report-directive-approve 와 같은 규칙).
  const lang = job.lang ?? "ko";
  const { data: active } = await supabase
    .from("report_render_jobs")
    .select("id, lang")
    .eq("directive_id", job.directive_id)
    .in("status", ACTIVE);
  if ((active ?? []).some((a) => (a.lang ?? "ko") === lang)) {
    return NextResponse.json({ ok: true, status: "already_queued", lang });
  }

  const { error } = await queueWriter(supabase)
    .from("report_render_jobs")
    .insert({ directive_id: job.directive_id, status: "queued", progress: 0, lang });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const trig = await triggerReportRender("render");
  return NextResponse.json({ ok: true, status: "queued", lang, rendering: trig.triggered });
}
