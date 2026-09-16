// POST /api/report-render-manage — 리포트 렌더 결과 저장/삭제 관리.
// body: { job_id, action: 'save'|'unsave'|'trash'|'restore'|'purge' }. api/render-manage 미러.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient, queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";

const ACTIONS = ["save", "unsave", "trash", "restore", "purge",
                 "approve_degraded"] as const;
type Action = (typeof ACTIONS)[number];

export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());
  const body = await request.json().catch(() => null);
  if (!body?.job_id || !ACTIONS.includes(body.action)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }
  const action = body.action as Action;

  const { data: job, error: jobErr } = await supabase
    .from("report_render_jobs")
    .select("id, directive_id, output_url, deleted_at, lang, status")
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


  // ★ §8-2 degraded 승인 — 중요 요소가 빠진 채 렌더된 영상을 사람이 보고 발행을 허가한다.
  //   status 를 'done' 으로 덮지 않는다: 덮으면 "무엇을 승인했는지"가 사라져, 결함이 있는
  //   채로 나간 영상과 처음부터 깨끗했던 영상이 기록상 구분되지 않는다. 승인은 판정을
  //   지우는 것이 아니라 판정 위에 사람의 결정을 얹는 것이다(0037 주석).
  if (action === "approve_degraded") {
    if (job.status !== "degraded") {
      return NextResponse.json(
        { error: "degraded 상태인 잡만 승인할 수 있습니다" }, { status: 409 });
    }
    const { error } = await queueWriter(supabase)
      .from("report_render_jobs")
      .update({ degraded_approved_at: new Date().toISOString() })
      .eq("id", job.id);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json({ ok: true, action });
  }

  if (action !== "purge") {
    const patch =
      action === "save"
        ? { saved_at: new Date().toISOString() }
        : action === "unsave"
          ? { saved_at: null }
          : action === "trash"
            ? { deleted_at: new Date().toISOString() }
            : { deleted_at: null };
    const { error } = await queueWriter(supabase).from("report_render_jobs").update(patch).eq("id", job.id);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json({ ok: true, action });
  }

  if (!job.deleted_at) {
    return NextResponse.json({ error: "먼저 휴지통으로 삭제해야 영구삭제할 수 있습니다" }, { status: 409 });
  }
  // ★ 비가역 파괴 액션 — 운영자 키 게이트(web/lib/apiGuard.ts). 0045 가 anon 의 renders
  //   DELETE 정책을 회수했으므로 이제 이 라우트가 유일한 파일 삭제 경로다. 게이트를 두지
  //   않으면 "누구나 지울 수 있다"가 anon 키에서 이 URL 로 옮겨갈 뿐이라 고친 게 없다.
  //   ★ 2026-09-15: 게이트를 핸들러 맨 앞으로 올렸다 — 모든 액션이 운영자 전용이다(공개 저장소 대비).

  // Storage 경로 규칙: report/{directive_id}/{job_id}_{lang}.mp4 (engine/report_render.py).
  if (job.output_url) {
    // ★ service_role 로 지운다: 0045 가 anon/authenticated 의 renders DELETE 정책을 없앴다.
    // ★ 실패하면 행을 남기고 멈춘다. 예전에는 remove() 결과를 버리고 행부터 지웠는데, 그러면
    //   파일이 고아로 남고 engine/storage_gc.py 는 "연결된 잡을 못 찾는 고아 경로"를 일부러
    //   남기므로(모르면 안 지운다) 그 파일은 영원히 회수되지 않는다. 2026-08-24 Storage
    //   1GB 초과로 조직 전체가 정지된 사고가 바로 그 누적에서 나왔다.
    const admin = createAdminClient();
    if (!admin) {
      return NextResponse.json(
        { error: "SUPABASE_SERVICE_KEY 미설정 — 파일을 지울 수 없어 영구삭제를 중단했습니다(고아 파일 방지). Vercel 환경변수를 확인하세요." },
        { status: 503 },
      );
    }
    const { error: rmErr } = await admin.storage.from("renders").remove([`report/${job.directive_id}/${job.id}_${job.lang ?? "ko"}.mp4`]);
    if (rmErr) {
      return NextResponse.json(
        { error: `Storage 파일 삭제 실패 — 행은 그대로 두었습니다(재시도하세요): ${rmErr.message}` },
        { status: 500 },
      );
    }
  }
  const { error } = await queueWriter(supabase).from("report_render_jobs").delete().eq("id", job.id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true, action: "purge" });
}
