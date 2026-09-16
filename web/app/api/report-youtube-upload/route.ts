// POST /api/report-youtube-upload — ⑥ 리포트 렌더 결과에서 완료 mp4 를 유튜브 업로드 큐에 적재.
// body: { job_id, privacy_status? }. lang 은 report_render_jobs.lang(리포트는 KO 금융 채널).
// report_upload_requests 에 요청을 쓰고 report-publish 워커(GitHub Actions)를 즉시 트리거. /api/youtube-upload 미러.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerPublish } from "@/lib/trigger-publish";
import { requireOperator } from "@/lib/apiGuard";
import { queueWriter } from "@/lib/supabase/admin";

const ALLOWED_PRIVACY = ["private", "unlisted", "public"] as const;

export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.job_id) {
    return NextResponse.json({ error: "job_id required" }, { status: 400 });
  }
  const privacy = ALLOWED_PRIVACY.includes(body.privacy_status)
    ? body.privacy_status
    : "private";

  const { data: job, error: jobErr } = await supabase
    .from("report_render_jobs")
    .select("id, directive_id, output_url, status, lang, degraded_approved_at")
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
  if (!job) return NextResponse.json({ error: "report render job 없음" }, { status: 404 });
  // ★ §8-3 — done 이거나, degraded 를 사람이 확인하고 승인한 것만 발행한다.
  //   degraded 는 "중요 요소가 빠진 채 렌더됨"이라 그냥 올리면 결함이 그대로 나간다.
  //   승인 표식(degraded_approved_at)은 status 를 덮지 않으므로, 발행 후에도 "결함이
  //   있었는데 사람이 승인했다"는 사실이 기록에 남는다(0037).
  const publishable =
    job.status === "done" ||
    (job.status === "degraded" && !!job.degraded_approved_at);
  if (!publishable || !job.output_url) {
    return NextResponse.json(
      {
        error:
          job.status === "degraded"
            ? "중요 요소가 빠진 영상입니다 — ⑥ 화면에서 확인하고 승인한 뒤 업로드하세요"
            : "완료된 mp4 가 없어 업로드 불가",
      },
      { status: 409 },
    );
  }

  const { data: directive } = await supabase
    .from("report_directives")
    .select("report_id")
    .eq("id", job.directive_id)
    .maybeSingle();

  // 이미 활성(대기/처리중/완료) 업로드가 있으면 재적재하지 않는다(중복 방지 — DB 유니크와 이중 방어).
  const { data: existing } = await supabase
    .from("report_upload_requests")
    .select("id, status, youtube_url")
    .eq("render_job_id", job.id)
    .in("status", ["queued", "processing", "done"])
    .maybeSingle();
  if (existing) {
    return NextResponse.json(
      { error: `이미 업로드 요청됨(${existing.status})`, youtube_url: existing.youtube_url },
      { status: 409 }
    );
  }

  const { error } = await queueWriter(supabase).from("report_upload_requests").insert({
    render_job_id: job.id,
    report_id: directive?.report_id ?? null,
    lang: job.lang ?? "ko",
    privacy_status: privacy,
    status: "queued",
    progress: 0,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const trig = await triggerPublish(process.env.REPORT_PUBLISH_WORKFLOW || "report-publish.yml");
  return NextResponse.json({ ok: true, uploading: trig.triggered });
}
