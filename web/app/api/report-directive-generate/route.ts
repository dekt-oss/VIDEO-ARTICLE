// POST /api/report-directive-generate — 리포트 영상 지시서 생성 요청.
// body: { report_id, version_types?: string[], version_type?: string }
//   version_types 로 **여러 버전을 한 번에** 발주한다(만화식·설명판형·실사형 비교용).
//   version_type(단수)은 기존 호출부 호환용 별칭이다.
// report_directive_requests 큐에 적재 후 report-video.yml(mode=directive) 워커를 트리거한다.
// (논문과 달리 엣지 함수를 두지 않고 Actions 러너에서 python -m engine.report_directive 로 생성.)
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerReportRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";

import { queueWriter } from "@/lib/supabase/admin";
// 화이트리스트 — 리포트 라인이 발주할 수 있는 버전만(lib/versions.ts REPORT_VERSION_META 와 동기화).
const REPORT_VERSIONS = new Set(["comic", "explainer", "photo"]);

export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());
  const body = await request.json().catch(() => null);
  if (!body?.report_id) {
    return NextResponse.json({ error: "report_id required" }, { status: 400 });
  }

  // 단수·복수 둘 다 받는다. 중복은 접고, 미허용 값은 버린다. 아무것도 안 남으면 comic.
  const requested: unknown[] = Array.isArray(body.version_types)
    ? body.version_types
    : [body.version_type];
  const versions = [...new Set(requested.map(String).filter((v) => REPORT_VERSIONS.has(v)))];
  if (versions.length === 0) versions.push("comic");

  const results: { version_type: string; status: "queued" | "processing"; warn?: string }[] = [];

  for (const versionType of versions) {
    // 같은 리포트·버전으로 대기/처리 중인 요청이 있으면 중복 적재하지 않는다(중복 생성 = 중복 비용).
    const { data: existing } = await supabase
      .from("report_directive_requests")
      .select("id")
      .eq("report_id", body.report_id)
      .eq("version_type", versionType)
      .in("status", ["queued", "processing"])
      .maybeSingle();

    if (existing) {
      results.push({ version_type: versionType, status: "processing" });
      continue;
    }

    const { error } = await supabase
      .from("report_directive_requests")
      .insert({ report_id: body.report_id, version_type: versionType, status: "queued" });
    // ★ 한 버전이 실패해도 나머지는 계속 발주한다 — 전부 되돌리면 무엇을 다시 눌러야 하는지
    //   운영자가 알 수 없다. 실패 사유는 그 버전 결과에 붙여 화면에 그대로 보여준다.
    results.push(
      error
        ? { version_type: versionType, status: "queued", warn: error.message }
        : { version_type: versionType, status: "queued" }
    );
  }

  const trig = await triggerReportRender("directive");
  return NextResponse.json(
    { ok: true, status: "queued", versions, results, triggered: trig.triggered },
    { status: 202 }
  );
}
