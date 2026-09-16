// POST /api/report-generate-draft — 리포트 초안 생성 요청. api/generate-draft(논문) 미러.
// report_draft_requests 큐에 적재 → report-draft 워크플로를 즉시 디스패치(202 반환).
// 디스패치가 안 되면 안전망 크론(하루 3번, KST 09/15/21)이 폴백으로 집어간다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOperator } from "@/lib/apiGuard";
import { triggerReportDraft } from "@/lib/trigger-render";
import { chainableVersions, REPORT_VERSION_KEYS } from "@/lib/versions";

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
  const instruction = String(body?.instruction ?? "").trim().slice(0, 800);
  // ★ 초안 뒤 이어서 만들 지시서 버전(0046, 설계안 v2). 리포트 공장이 발주하는 버전만 받는다.
  const versionTypes = chainableVersions(body?.version_types, REPORT_VERSION_KEYS);

  const { data: existing } = await supabase
    .from("report_draft_requests")
    .select("id, status")
    .eq("report_id", body.report_id)
    .in("status", ["queued", "processing"])
    // ★ 재검사 요청은 빼고 찾는다(2026-09-11 리뷰). 대기 중인 recheck 행에 이번 [초안 생성]의
    //   instruction·version_types 를 얹으면 워커가 재검사만 돌리고(재검사는 지시서를 잇지 않는다)
    //   초안도 지시서도 안 만드는데 화면은 202 로 성공처럼 보였다. mode 는 0035 부터 not null.
    .neq("mode", "recheck")
    .maybeSingle();

  // ★ 중복 요청 계약(PR #94 후속 리뷰 §9). 예전에는 진행 중인 요청이 있으면 **조용히 무시**하고
  //   202 를 돌려줬다 — 운영자가 "리스크를 더 강조"를 새로 적고 눌러도 그 지시가 어디에도
  //   닿지 않는데 화면은 성공처럼 보였다.
  //   이제 상태에 따라 갈린다:
  //     · queued(아직 워커가 안 집어감)  → 그 행의 instruction 을 **갱신**한다. 운영자가
  //       방금 적은 지시가 그대로 반영된다(마지막에 적은 것이 이긴다 — 사람이 기대하는 동작).
  //     · processing(생성 중)            → 409. 이미 만들고 있는 것을 바꿀 수는 없다.
  //   리뷰는 둘 다 409(방식 A)를 권했지만, queued 를 거절하면 운영자가 지시를 고칠 방법이
  //   "완료될 때까지 기다렸다 재생성"뿐이라 오히려 헛돈이 나간다. 계약이 애매한 것이 문제였지
  //   갱신 자체가 문제는 아니었다.
  if (existing?.status === "processing") {
    return NextResponse.json(
      {
        error: "이미 생성 중입니다. 완료된 뒤에 새 요청을 보내세요.",
        status: "processing",
      },
      { status: 409 }
    );
  }
  if (existing && instruction) {
    const { error } = await supabase
      .from("report_draft_requests")
      .update({ instruction })
      .eq("id", existing.id);
    if (error && !/instruction/i.test(error.message)) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
  }
  if (existing && versionTypes.length) {
    // 아직 워커가 안 집어간 요청이면 이번에 고른 버전으로 갱신한다(마지막 선택이 이긴다).
    const { error } = await supabase
      .from("report_draft_requests")
      .update({ version_types: versionTypes })
      .eq("id", existing.id);
    if (error && !/version_types/i.test(error.message)) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
  }

  if (!existing) {
    // ★ instruction 을 반드시 함께 넣는다(0038). 예전에는 위에서 읽어만 두고 큐에 넣지 않아,
    //   ④ 화면의 "세부 수정 요청"에 무엇을 적어도 초안이 똑같이 나왔다 — 워커가 정본인
    //   리포트 라인에서는 큐가 유일한 전달 통로다.
    // ★ version_types(0046)도 같은 통로로 간다 — 워커가 초안 뒤 그 버전의 지시서를 잇는다.
    const { error } = await supabase
      .from("report_draft_requests")
      .insert({ report_id: body.report_id, status: "queued", instruction, version_types: versionTypes });
    if (error) {
      // 0038/0046 이 아직 적용되지 않은 DB — 컬럼이 없다고 버튼 자체를 죽이지는 않는다.
      // 빠진 칸 없이 큐에 넣고(예전 동작) 무엇이 빠졌는지 알린다.
      const missingInstruction = /instruction/i.test(error.message);
      const missingVersions = /version_types/i.test(error.message);
      if (!missingInstruction && !missingVersions) {
        return NextResponse.json({ error: error.message }, { status: 500 });
      }
      const retry = await supabase
        .from("report_draft_requests")
        .insert(missingInstruction
          ? { report_id: body.report_id, status: "queued" }
          : { report_id: body.report_id, status: "queued", instruction });
      if (retry.error) {
        return NextResponse.json({ error: retry.error.message }, { status: 500 });
      }
      console.warn(missingInstruction
        ? "[report-generate-draft] 0038 미적용 — 세부 수정 요청은 무시된다"
        : "[report-generate-draft] 0046 미적용 — 지시서 자동 생성 없이 큐에 넣었다");
    }
  }

  // ★ 워커가 정본이다(v3 P1 적대적 리뷰 결정). 근거 게이트(§5)·논증 설계(§6)·원문 인용 대조는
  //   engine/report_draft.py 에만 있고 엣지에는 없다. 엣지가 먼저 처리해 큐를 done 으로 닫으면
  //   워커가 손댈 것이 남지 않아 그 검증들이 통째로 건너뛰어진다 — 실제로 그래서 report_drafts
  //   21행 중 number_facts 를 가진 행이 0건이었다.
  //   기본은 큐 적재만. 되돌리려면 REPORT_DRAFT_EDGE_FALLBACK=true.
  if (process.env.REPORT_DRAFT_EDGE_FALLBACK !== "true") {
    // ★ 큐에 넣고 **바로 워커를 부른다** — 렌더·발행 버튼이 이미 쓰는 방식(trigger-render.ts).
    //   크론만 두면 버튼을 눌러도 다음 안전망 시각까지 기다린다. 디스패치가 실패해도(토큰 없음 등)
    //   크론이 폴백이므로 흐름은 막히지 않는다 — 다만 2026-08-12 부터 그 폴백이 하루 3번
    //   (KST 09/15/21)이라 "조금 늦음"이 아니라 "몇 시간 대기"다. 실패 문구가 그렇게 안내한다.
    const t = await triggerReportDraft();
    return NextResponse.json(
      {
        ok: true,
        status: t.triggered ? "processing" : "queued",
        note: t.triggered
          ? "워커를 시작했습니다(1~3분)"
          : `워커 자동 시작 실패(${t.reason ?? "미상"}) — 큐에는 넣었습니다. 다음 안전망 크론(KST 09/15/21)까지 대기합니다. 급하면 GitHub Actions 탭에서 report-draft 를 직접 실행하세요.`,
      },
      { status: 202 }
    );
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const edgeKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // ★ 공개 저장소 대비(2026-09-15): anon JWT 는 게이트웨이(verify_jwt)만 통과시킨다. 함수는
  //   서버 전용 공유 비밀(EDGE_INVOKE_SECRET)이 헤더에 있어야 일한다 — anon 키만으로는
  //   누구나 함수를 직접 불러 유료 LLM 을 돌릴 수 있었다. NEXT_PUBLIC_ 을 붙이지 않는다.
  const edgeSecret = process.env.EDGE_INVOKE_SECRET ?? "";
  if (!supabaseUrl || !edgeKey) {
    return NextResponse.json(
      { ok: true, status: "queued", note: "함수 미호출(설정 확인)" },
      { status: 202 }
    );
  }

  try {
    const res = await fetch(`${supabaseUrl}/functions/v1/generate-report-draft`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${edgeKey}`,
        apikey: edgeKey,
        "x-edge-secret": edgeSecret,
      },
      body: JSON.stringify({ report_id: body.report_id, instruction }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      return NextResponse.json(
        { ok: true, status: "queued", warn: `함수 호출 실패(${res.status}) — 큐 적재됨`, detail: detail.slice(0, 200) },
        { status: 202 }
      );
    }
  } catch (e) {
    return NextResponse.json(
      { ok: true, status: "queued", warn: `함수 호출 예외 — 큐 적재됨: ${String(e).slice(0, 120)}` },
      { status: 202 }
    );
  }

  return NextResponse.json({ ok: true, status: "processing" }, { status: 202 });
}
