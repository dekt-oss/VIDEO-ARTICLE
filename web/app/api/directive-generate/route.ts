// POST /api/directive-generate — 버전별 영상 지시서 생성 요청.
// body: { paper_id, version_types?: string[], version_type?: string }
//   version_types 로 **여러 버전을 한 번에** 발주한다(만화식·웹툰 비교용).
//   version_type(단수)은 기존 호출부 호환용 별칭이다.
// 버전마다 directive_requests 큐에 상태 행을 적재한 뒤 Edge Function(generate-directive)을 호출한다.
// 함수는 202로 즉시 반환하고 백그라운드로 생성하므로 UI 는 /api/directive-status 로 폴링한다.
// (/api/generate-draft 와 동일 패턴)
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOperator } from "@/lib/apiGuard";

import { queueWriter } from "@/lib/supabase/admin";
// A타입(만화 comic) + 웹툰 장면파생(webtoon) 발주. image_sequence 는 엔진/DB 하위호환만.
// editorial(B타입)은 2026-07-28 폐기 — docs/deviation-webtoon-b1-removal.md.
// 실사형(photo)은 2026-08-20 추가 — 논문 라인도 3D 도해+실사 버전을 발주한다.
const VERSIONS = new Set(["comic", "webtoon", "photo"]);

// 진행 중 요청을 "죽었다"고 보는 시간. 실측 생성 시간은 약 60초이고 UI 폴링 타임아웃이 6분이라
// 그 위인 15분으로 둔다 — 정상 생성을 중간에 죽이지 않으면서, 굳은 행이 발주를 영구히 막지 않는다.
const STALE_REQUEST_MS = 15 * 60 * 1000;

interface VersionResult {
  version_type: string;
  status: "queued" | "processing";
  warn?: string;
  detail?: string;
}

export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.paper_id) {
    return NextResponse.json({ error: "paper_id required" }, { status: 400 });
  }

  // 단수·복수 둘 다 받는다. 중복은 접고, 미허용 값은 버린다. 아무것도 안 남으면 comic.
  const requested: unknown[] = Array.isArray(body.version_types)
    ? body.version_types
    : [body.version_type];
  const versions = [...new Set(requested.map(String).filter((v) => VERSIONS.has(v)))];
  if (versions.length === 0) versions.push("comic");

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const edgeKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // ★ 공개 저장소 대비(2026-09-15): anon JWT 는 게이트웨이(verify_jwt)만 통과시킨다. 함수는
  //   서버 전용 공유 비밀(EDGE_INVOKE_SECRET)이 헤더에 있어야 일한다 — anon 키만으로는
  //   누구나 함수를 직접 불러 유료 LLM 을 돌릴 수 있었다. NEXT_PUBLIC_ 을 붙이지 않는다.
  const edgeSecret = process.env.EDGE_INVOKE_SECRET ?? "";
  const results: VersionResult[] = [];

  const staleBefore = new Date(Date.now() - STALE_REQUEST_MS).toISOString();

  for (const versionType of versions) {
    // 같은 논문·버전으로 대기/처리 중인 요청이 있으면 중복 적재 안 함.
    const { data: existing } = await supabase
      .from("directive_requests")
      .select("id, requested_at")
      .eq("paper_id", body.paper_id)
      .eq("version_type", versionType)
      .in("status", ["queued", "processing"])
      .order("requested_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    // ★ 이미 진행 중이면 함수를 **다시 부르지 않는다.** 예전에는 큐 적재만 건너뛰고 호출은 그대로
    //   해서, 버튼을 두 번 누르면 같은 논문·버전으로 LLM 생성이 동시에 여러 벌 돌았다(실측: 한
    //   논문에 45초 동안 4회). 비용이 그만큼 배로 나가고, 동시 실행끼리 요청 행 상태를 서로
    //   덮어써 실패 사유가 사라진다.
    // ★ 단, 죽은 요청은 길을 막지 않는다 — 엣지 함수가 상태를 못 남기고 죽으면 그 행은 영원히
    //   'processing' 이라, 시간 제한이 없으면 그 논문·버전은 두 번 다시 발주할 수 없다
    //   (실측: 2026-07-29 부터 처리중으로 굳은 행이 있다). 오래된 행은 실패로 닫고 새로 건다.
    const stale = existing && String(existing.requested_at ?? "") < staleBefore;
    if (existing && !stale) {
      results.push({ version_type: versionType, status: "processing", warn: "이미 생성 중" });
      continue;
    }
    if (stale) {
      await supabase
        .from("directive_requests")
        .update({ status: "error", error: "응답 없이 방치돼 자동 종료(재발주됨)" })
        .eq("id", existing!.id);
    }

    const { error } = await supabase
      .from("directive_requests")
      .insert({ paper_id: body.paper_id, version_type: versionType, status: "queued" });
    if (error) {
      // ★ 한 버전이 실패해도 나머지는 계속 발주한다. 전부 되돌리면 운영자가 무엇을 다시
      //   눌러야 하는지 알 수 없다 — 버전별 결과를 그대로 돌려주는 편이 낫다.
      results.push({ version_type: versionType, status: "queued", warn: error.message });
      continue;
    }

    if (!supabaseUrl || !edgeKey) {
      results.push({ version_type: versionType, status: "queued", warn: "함수 미호출(설정 확인)" });
      continue;
    }

    try {
      const res = await fetch(`${supabaseUrl}/functions/v1/generate-directive`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${edgeKey}`,
          apikey: edgeKey,
          "x-edge-secret": edgeSecret,
        },
        body: JSON.stringify({ paper_id: body.paper_id, version_type: versionType }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        results.push({
          version_type: versionType,
          status: "queued",
          warn: `함수 호출 실패(${res.status}) — 큐 적재됨`,
          detail: detail.slice(0, 200),
        });
        continue;
      }
    } catch (e) {
      results.push({
        version_type: versionType,
        status: "queued",
        warn: `함수 호출 예외 — 큐 적재됨: ${String(e).slice(0, 120)}`,
      });
      continue;
    }

    results.push({ version_type: versionType, status: "processing" });
  }

  const allProcessing = results.every((r) => r.status === "processing");
  return NextResponse.json(
    { ok: true, results, status: allProcessing ? "processing" : "queued" },
    { status: 202 },
  );
}
