// POST /api/directive-approve — 지시서 승인 → 렌더 파이프라인 트리거.
// body: { directive_ids?: string[], directive_id?: string, langs?: string[], force?: boolean }
//   directive_ids 로 **여러 버전을 한 번에** 승인한다(만화식·웹툰 비교용).
//   directive_id(단수)는 기존 호출부 호환용 별칭이다.
// directives.status=approved 로 바꾸고 (지시서 × 언어)마다 render_jobs 큐에 행을 넣는다.
// 렌더는 GitHub Actions/로컬 워커(python -m engine.render)가 render_jobs 를 폴링해 처리한다(P-V1).
//
// ★ 실패 의미론: 하나가 차단돼도 **배치를 중단하지 않는다.** 나머지는 큐에 넣고 버전별 결과를
//   돌려준다. 전부 차단됐을 때만 409 다. 전부 되돌리면 운영자가 무엇이 왜 막혔는지 알 수 없다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";
import { queueWriter } from "@/lib/supabase/admin";
import { approvalBlockReasons } from "@/lib/approvalGate";
import { RENDER_STATUS_ACTIVE } from "@/lib/renderStatus";

const ALLOWED_LANGS = ["ko", "en"];
// ★ 목록을 여기 다시 적지 않는다 — 새 상태(qa_pending·degraded)를 한 곳이라도 빠뜨리면
//   승인 대기 중인 지시서에 두 번째 렌더 잡이 생긴다(같은 영상 두 번, 비용 두 번).
const ACTIVE_JOB_STATUSES = RENDER_STATUS_ACTIVE;

interface ApproveResult {
  directive_id: string;
  version_type?: string;
  queued: number;
  langs: string[];
  blocked?: string[];
  error?: string;
}

export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  const rawIds: unknown[] = Array.isArray(body?.directive_ids)
    ? body.directive_ids
    : [body?.directive_id];
  const requestedIds: string[] = [
    ...new Set(rawIds.filter((x): x is string => typeof x === "string" && x.length > 0)),
  ];
  if (requestedIds.length === 0) {
    return NextResponse.json({ error: "directive_id required" }, { status: 400 });
  }

  // ⑤ 언어 선택(규격 v2): langs = ["ko"] | ["en"] | ["ko","en"]. 기본 ko.
  // ★ 언어는 비용을 늘리지 않는다 — 에셋이 언어 독립 캐시라 두 번째 언어는 $0 다.
  const reqLangs: unknown[] = Array.isArray(body?.langs) ? body.langs : ["ko"];
  const langs = [...new Set(reqLangs.map(String).filter((l) => ALLOWED_LANGS.includes(l)))];
  if (langs.length === 0) langs.push("ko");

  const results: ApproveResult[] = [];
  let anyQueued = false;

  for (const directiveId of requestedIds) {
    const { data: directive } = await supabase
      .from("directives")
      .select("id, version_type, status, header, cuts")
      .eq("id", directiveId)
      .maybeSingle();
    if (!directive) {
      results.push({ directive_id: directiveId, queued: 0, langs: [], error: "directive 없음" });
      continue;
    }

    // 근거밀도 개정(수정명세 §14-3) — 서버에서 차단 사유를 재검증한다. 클라이언트 배지는 참고용일
    // 뿐이라 여기서 막지 않으면 게이트가 장식이 된다.
    // ★ 차단은 **코드가 데이터로 확정한 사유만**이다(운영자 결정 2026-07-27): 길이 80초 초과 ·
    //   시리즈 분할 필요 · 영상 예산 초과 · 존재하지 않는 claim_id · 필수 Claim 누락.
    //   범위확대·인과과장·숫자불일치 같은 자기검증 LLM 의 **판단**은 경고로만 표시하고 승인을
    //   막지 않는다 — 리포트 라인 컴플라이언스 하드차단을 제거한 것과 같은 이유(커밋 6a28761).
    // ★ 저장된 header.block_reasons 를 **그대로 믿지 않는다.** 그건 지시서 생성 시점 값인데,
    //   그 뒤 운영자가 컷을 편집하고 /api/directive-update 는 total_estimated_sec 만 갱신한다.
    //   60초(차단 없음)를 95초로 늘려도 저장값은 빈 배열이라 80초 상한이 샌다 → 승인 순간에 다시 센다.
    const recomputed = approvalBlockReasons(
      directive.header as Parameters<typeof approvalBlockReasons>[0],
      directive.cuts as Parameters<typeof approvalBlockReasons>[1],
    );
    const stored: string[] = Array.isArray((directive.header as Record<string, unknown> | null)
      ?.block_reasons)
      ? ((directive.header as Record<string, unknown>).block_reasons as string[])
      : [];
    // 편집으로 사라진 사유는 빼되(재계산이 정본), 재계산이 못 보는 축(존재하지 않는 claim_id 등)은 살린다.
    const blockReasons = [...new Set([
      ...recomputed,
      ...stored.filter((r) => r.startsWith("claim_id_invalid")),
    ])].sort();
    if (blockReasons.length > 0) {
      if (body?.force !== true) {
        results.push({
          directive_id: directiveId,
          version_type: directive.version_type as string,
          queued: 0,
          langs: [],
          blocked: blockReasons,
        });
        continue;
      }
      // 강제 승인은 허용하되 조용히 넘기지 않는다 — 운영자 결정(작업지시서 v3 §8: "강제 승인은
      // 허용하되 흔적을 남긴다")이고, 리포트 라인 report-directive-approve 와 같은 처리다.
      // 이 길이 없으면 series_split_required 처럼 **운영자가 화면에서 풀 방법이 없는 사유**에
      // 걸린 지시서는 영영 렌더로 못 간다(2편 분할 UI 는 명세 §8 열린 질문 2 로 범위 밖).
      console.warn(
        `[directive-approve] 승인 게이트 우회: directive=${directiveId} 사유=${blockReasons.join(",")}`,
      );
    }

    const { error: upErr } = await supabase
      .from("directives")
      .update({ status: "approved", approved_at: new Date().toISOString() })
      .eq("id", directiveId);
    if (upErr) {
      results.push({
        directive_id: directiveId,
        version_type: directive.version_type as string,
        queued: 0, langs: [], error: upErr.message,
      });
      continue;
    }

    // 언어별로 큐 적재. 같은 (지시서, 언어) 로 이미 대기/진행 중인 잡이 있으면 중복 발주하지 않는다.
    const { data: activeJobs } = await supabase
      .from("render_jobs")
      .select("id, lang")
      .eq("directive_id", directiveId)
      .in("status", ACTIVE_JOB_STATUSES);
    const activeLangs = new Set((activeJobs ?? []).map((j) => j.lang ?? "ko"));

    const toInsert = langs
      .filter((l) => !activeLangs.has(l))
      .map((l) => ({ directive_id: directiveId, status: "queued", progress: 0, lang: l }));
    if (toInsert.length > 0) {
      const { error: jobErr } = await queueWriter(supabase).from("render_jobs").insert(toInsert);
      if (jobErr) {
        results.push({
          directive_id: directiveId,
          version_type: directive.version_type as string,
          queued: 0, langs: [], error: jobErr.message,
        });
        continue;
      }
      anyQueued = true;
    }
    results.push({
      directive_id: directiveId,
      version_type: directive.version_type as string,
      queued: toInsert.length,
      langs,
    });
  }

  // 전부 차단됐으면 409 — 운영자가 아무것도 진행되지 않았음을 분명히 알아야 한다.
  const allBlocked = results.length > 0 && results.every((r) => (r.blocked?.length ?? 0) > 0);
  if (allBlocked) {
    return NextResponse.json(
      {
        error: "승인 차단: " + [...new Set(results.flatMap((r) => r.blocked ?? []))].join(", "),
        code: "approval_blocked",
        block_reasons: [...new Set(results.flatMap((r) => r.blocked ?? []))],
        results,
      },
      { status: 409 },
    );
  }

  // 승인 즉시 렌더 워커를 트리거(토큰 없으면 no-op → 수동 폴백).
  // ★ 지시서마다 부르지 않는다 — 워커는 큐 전체를 폴링하므로 한 번이면 충분하다.
  const trig = anyQueued ? await triggerRender() : { triggered: false };
  return NextResponse.json({
    ok: true,
    status: "queued",
    langs,
    results,
    rendering: trig.triggered,
  });
}
