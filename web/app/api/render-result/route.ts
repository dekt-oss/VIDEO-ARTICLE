// POST /api/render-result — ⑥ 렌더 결과 처리. body: { job_id, action: 'publish' | 'reject' }
// publish: 렌더 mp4 URL 을 published 에 기록(발행 대기 이관). reject: 새 render_jobs 큐 적재(재렌더).
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";
import { queueWriter } from "@/lib/supabase/admin";

export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.job_id || !["publish", "reject"].includes(body.action)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  // 게이트는 reject(=재렌더 → Veo/Gemini 재과금)에만. publish 는 published 행 기록뿐이라
  // 비용·외부 발행이 없어 그대로 열어둔다(매일 쓰는 흐름에 마찰을 만들지 않는다).
  if (body.action === "reject") {
    const denied = requireOperator();
    if (denied) return denied;
  }

  const { data: job, error: jobErr } = await supabase
    .from("render_jobs")
    .select("id, directive_id, output_url, status")
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

  const { data: directive } = await supabase
    .from("directives")
    .select("paper_id")
    .eq("id", job.directive_id)
    .maybeSingle();

  if (body.action === "publish") {
    if (!job.output_url) {
      return NextResponse.json({ error: "완료된 mp4 가 없어 이관 불가" }, { status: 409 });
    }
    if (directive?.paper_id) {
      const { error } = await supabase.from("published").upsert(
        {
          paper_id: directive.paper_id,
          final_script: `[영상] ${job.output_url}`,
          platforms: { video_url: job.output_url, render_job_id: job.id },
        },
        { onConflict: "paper_id" },
      );
      if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    }
    return NextResponse.json({ ok: true, action: "publish" });
  }

  // reject → 재렌더: 지시서를 approved 로 되돌리고 새 render_jobs 큐 적재.
  await supabase.from("directives").update({ status: "approved" }).eq("id", job.directive_id);
  const { error } = await queueWriter(supabase)
    .from("render_jobs")
    .insert({ directive_id: job.directive_id, status: "queued", progress: 0 });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const trig = await triggerRender(); // 재렌더도 즉시 워커 트리거
  return NextResponse.json({ ok: true, action: "reject", rendering: trig.triggered });
}
