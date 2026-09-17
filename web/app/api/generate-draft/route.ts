// POST /api/generate-draft — 초안 생성 요청.
// draft_requests 큐에 상태 행을 적재(감사/폴링용)한 뒤, Supabase Edge Function
// (generate-draft)을 호출해 클라우드에서 자동 생성한다. 함수는 202로 즉시 반환하고
// 백그라운드로 생성하므로, UI 는 /api/draft-status 로 상태를 폴링한다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOperator } from "@/lib/apiGuard";
import { chainableVersions } from "@/lib/versions";
import { triggerDraft } from "@/lib/trigger-render";
import { isStaleProcessing, STALE_REVIVE_NOTE } from "@/lib/requestQueue";

import { queueWriter } from "@/lib/supabase/admin";
export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.paper_id) {
    return NextResponse.json({ error: "paper_id required" }, { status: 400 });
  }
  // 선택: 사용자 수정 요청(예: 어려운 용어 풀어쓰기). Edge Function 대본 생성에 주입.
  const instruction = String(body?.instruction ?? "").trim().slice(0, 800);
  // ★ 초안 뒤 이어서 만들 지시서 버전(0046, 설계안 v2). 운영자가 초안을 만들 때 고른다.
  //   없으면 옛 동작(지시서는 ⑤ 에서 따로). 미허용 값은 버린다 — 워커의 VERSION_GUIDANCE 가
  //   기본 버전으로 조용히 갈아치우는 사고(2026-08-20)를 여기서 먼저 막는다.
  const versionTypes = chainableVersions(body?.version_types);

  // 이미 대기/처리 중인 요청이 있으면 중복 적재하지 않음(단, 함수 호출은 아래서 재시도).
  const { data: found } = await supabase
    .from("draft_requests")
    .select("id, status, updated_at")
    .eq("paper_id", body.paper_id)
    .in("status", ["queued", "processing"])
    .maybeSingle();

  // ★ 죽은 채로 방치된 요청을 여기서 되살린다(2026-09-17). 워커·Edge 가 중간에 끊기면 행이
  //   'processing' 으로 남고 폴러는 'queued' 만 집으므로 **영원히** 막힌다 — 운영자가
  //   SQL 로 status 를 되돌려야 했던 자리다(핸드오프 남은일 6번).
  //   ★★ 새 행을 넣지 않고 **그 행을 되돌린다.** 새로 넣으면 엔진 워치독이 나중에 옛 행까지
  //     되살려 같은 초안을 두 번 만든다(유료 호출 2배).
  let existing = found;
  if (existing?.status === "processing" && isStaleProcessing(existing.updated_at)) {
    const { error: revErr } = await supabase
      .from("draft_requests")
      .update({ status: "queued", error: STALE_REVIVE_NOTE, updated_at: new Date().toISOString() })
      .eq("id", existing.id)
      .eq("status", "processing");   // 그 사이 워커가 끝냈으면 건드리지 않는다
    if (revErr) {
      console.warn(`[generate-draft] 정체 요청 회수 실패(무시): ${revErr.message}`);
    } else {
      console.warn(`[generate-draft] 정체 요청 회수 paper=${body.paper_id} req=${existing.id}`);
      existing = { ...existing, status: "queued" };
    }
  }

  if (!existing) {
    const { error } = await supabase
      .from("draft_requests")
      .insert({ paper_id: body.paper_id, status: "queued", version_types: versionTypes });
    if (error) {
      // 0046 미적용 DB — 컬럼이 없다고 버튼을 죽이지 않는다. 버전 없이 넣고(옛 동작) 알린다.
      if (!/version_types/i.test(error.message)) {
        return NextResponse.json({ error: error.message }, { status: 500 });
      }
      const retry = await supabase
        .from("draft_requests")
        .insert({ paper_id: body.paper_id, status: "queued" });
      if (retry.error) return NextResponse.json({ error: retry.error.message }, { status: 500 });
      console.warn("[generate-draft] 0046 미적용 — 지시서 자동 생성 없이 큐에 넣었다");
    }
  } else if (existing.status === "queued" && versionTypes.length) {
    // 아직 워커가 안 집어간 요청이면 이번에 고른 버전으로 갱신한다(마지막 선택이 이긴다).
    await supabase
      .from("draft_requests")
      .update({ version_types: versionTypes })
      .eq("id", existing.id);
  }

  // ★ 버전을 골랐으면 **워커를 먼저 깨운다**(2026-09-11 리뷰). 워커(engine.draft)는 초안을 저장한
  //   뒤 같은 실행에서 지시서를 잇는다(chain_directives). 엣지를 함께 부르면 엣지가 초안을 만들고
  //   directive_requests 를 적재하는 시점이 워커의 한 번뿐인 지시서 폴링보다 늦어, 그 행이 다음
  //   크론까지 queued 로 남았다(draft.yml 은 크론이 없다). 디스패치가 되면 엣지는 부르지 않는다.
  //   디스패치가 안 되면(토큰 없음·Actions 차단) 예전처럼 엣지가 초안을 만들고 지시서는 큐에 남는다.
  if (versionTypes.length) {
    const t = await triggerDraft();
    if (t.triggered) {
      return NextResponse.json(
        { ok: true, status: "processing", version_types: versionTypes, note: "워커를 시작했습니다(초안 → 지시서, 수 분)" },
        { status: 202 },
      );
    }
    console.warn(`[generate-draft] 워커 디스패치 실패(${t.reason ?? "미상"}) — 엣지로 초안만 만든다`);
  }

  // Edge Function 호출. 로그인 제거 후에는 세션이 없으므로 anon 키를 Bearer 로 전달한다
  // (anon 키 자체가 서명된 JWT 라 함수의 verify_jwt 를 통과한다. 함수 내부는 service_role 로 동작).
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const edgeKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // ★ 공개 저장소 대비(2026-09-15): anon JWT 는 게이트웨이(verify_jwt)만 통과시킨다. 함수는
  //   서버 전용 공유 비밀(EDGE_INVOKE_SECRET)이 헤더에 있어야 일한다 — anon 키만으로는
  //   누구나 함수를 직접 불러 유료 LLM 을 돌릴 수 있었다. NEXT_PUBLIC_ 을 붙이지 않는다.
  const edgeSecret = process.env.EDGE_INVOKE_SECRET ?? "";

  if (!supabaseUrl || !edgeKey) {
    // 함수 호출 준비가 안 되면 큐 행은 남아 있으니 로컬/Actions 워커로도 처리 가능.
    return NextResponse.json(
      { ok: true, status: "queued", note: "함수 미호출(설정 확인)" },
      { status: 202 },
    );
  }

  try {
    const res = await fetch(`${supabaseUrl}/functions/v1/generate-draft`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${edgeKey}`,
        apikey: edgeKey,
        "x-edge-secret": edgeSecret,
      },
      body: JSON.stringify({ paper_id: body.paper_id, instruction, version_types: versionTypes }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      return NextResponse.json(
        { ok: true, status: "queued", warn: `함수 호출 실패(${res.status}) — 큐 적재됨`, detail: detail.slice(0, 200) },
        { status: 202 },
      );
    }
  } catch (e) {
    return NextResponse.json(
      { ok: true, status: "queued", warn: `함수 호출 예외 — 큐 적재됨: ${String(e).slice(0, 120)}` },
      { status: 202 },
    );
  }

  // 여기까지 왔으면 워커 디스패치가 안 된 경우다(위). 엣지는 초안만 만들고 지시서는 큐에 넣기만
  // 한다 — 지시서 생성은 워커 독점이라(2026-08-29) 로컬 워커(`python -m engine.directive`)가 처리한다.
  const workerNote = versionTypes.length
    ? "워커 자동 시작 실패 — 초안은 엣지가 만들고, 지시서는 큐에 넣었습니다. 로컬 워커(python -m engine.directive)가 처리합니다."
    : undefined;

  return NextResponse.json(
    { ok: true, status: "processing", version_types: versionTypes, note: workerNote },
    { status: 202 },
  );
}
