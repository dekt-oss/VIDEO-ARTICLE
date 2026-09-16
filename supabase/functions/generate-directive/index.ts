// Supabase Edge Function: 영상 지시서 **요청 큐 적재** (2026-08-29 리뷰 §8 이후).
//
// 이 함수가 하는 일은 두 가지뿐이다: **요청 검증**과 **큐 적재**.
// 생성·정규화·계약 검사·재생성·저장은 전부 Python 워커(engine/directive.py)가 한다.
//
// ★ 왜 생성을 걷어냈나 — 실측(2026-08-28 13:07, Supabase function_logs):
//   이 함수가 202 를 돌려준 뒤 백그라운드 실행(waitUntil) 안에서 LLM 생성을 계속하다가
//   **47초 만에 isolate 가 shutdown** 됐다. 런타임이 끊기면 catch 가 실행되지 않으므로
//   요청 상태를 error 로 바꾸지도 못한다 → 요청이 processing 인 채로 영원히 남고 화면은
//   "생성 중"에서 멈춘다. 실사형처럼 컷이 많은 버전은 이 시간을 넘기기 쉽다.
//
// ★ 두 번째 이유(이중 관리): 예전 이 파일에는 engine/directive.py 의 프롬프트·enum·정규화가
//   통째로 복제돼 있었다(약 1,200줄). 한쪽만 낡으면 **같은 발주가 경로에 따라 다른 결과**가
//   된다 — 배포본이 낡아 실사형 발주가 image_sequence 로 조용히 둔갑한 2026-08-20 사고가 그것이다.
//   복제를 없애면 그 사고 유형 자체가 사라진다.
//
// 남은 실행 경로:
//   대시보드 → 이 함수(또는 Next 라우트) → directive_requests(queued)
//            → Python 워커가 임대(lease)로 집어 생성 → directives 저장 + 요청 done
//   워커가 중간에 죽으면 임대가 만료되고 다른 워커가 되집는다(0043 · engine/db.py).
//
// 배포:  supabase functions deploy generate-directive
// 시크릿: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (LLM 키는 더 이상 필요 없다)
//
// deno-lint-ignore-file no-explicit-any
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// ★ 발주 가능한 버전. engine/config.py:VIDEO_VERSIONS 와 동기화한다
//   (tests/test_prompt_sync.py 가 목록 일치를 검사한다).
//   폐기: editorial 2026-07-28 · webtoon·explainer 2026-08-28.
const VIDEO_VERSIONS = ["comic", "image_sequence", "photo"] as const;
const DEFAULT_VERSION = "comic";

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * 요청을 큐에 넣는다. 이미 대기·처리 중인 같은 (논문, 버전) 요청이 있으면 넣지 않는다 —
 * 중복 발주는 유료 LLM 호출을 그대로 두 배로 만든다.
 */
async function enqueue(supa: any, paperId: string, versionType: string): Promise<string> {
  const now = new Date().toISOString();
  const { data: existing, error: selErr } = await supa
    .from("directive_requests")
    .select("id, status")
    .eq("paper_id", paperId)
    .eq("version_type", versionType)
    .in("status", ["queued", "processing"])
    .limit(1);
  if (selErr) throw selErr;
  if (existing && existing.length) return "already_queued";

  const { error } = await supa.from("directive_requests").insert({
    paper_id: paperId,
    version_type: versionType,
    status: "queued",
    requested_at: now,
    updated_at: now,
  });
  if (error) throw error;
  return "queued";
}

// ★ 공개 저장소 대비(2026-09-15): **서버 전용 공유 비밀**이 있어야 일한다.
//   verify_jwt 는 서명만 본다 — 공개 anon 키도 유효한 JWT 라 누구나 이 함수를 불러 유료 LLM 을
//   돌릴 수 있었다. 역할 클레임(service_role) 검사는 못 쓴다: 이 프로젝트의 서버 키는 JWT 가 아닌
//   신형 sb_secret 형식이다. 그래서 대시보드 서버 라우트만 아는 EDGE_INVOKE_SECRET 을 헤더로 받는다.
//   미설정이면 **막는다**(fail-closed). 설정: supabase secrets set EDGE_INVOKE_SECRET=… + Vercel 같은 값.
const MIN_SECRET_LEN = 32;

function callerCheck(req: Request): { ok: boolean; reason: string } {
  const expected = Deno.env.get("EDGE_INVOKE_SECRET") ?? "";
  const got = req.headers.get("x-edge-secret") ?? "";
  // ★ 사유를 구분해 돌려준다(값은 절대 싣지 않는다). 2026-09-16 실측: 대시보드 호출이 403 인데
  //   "시크릿 미설정"인지 "짧아서 거부"인지 "값 불일치"인지 알 수 없어 원인 규명이 막혔다.
  if (!expected) return { ok: false, reason: "secret_not_configured_on_function" };
  if (expected.length < MIN_SECRET_LEN) return { ok: false, reason: "function_secret_too_short" };
  if (!got) return { ok: false, reason: "caller_sent_no_secret" };
  if (got.length !== expected.length) return { ok: false, reason: "mismatch_length" };
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ got.charCodeAt(i);
  return diff === 0 ? { ok: true, reason: "ok" } : { ok: false, reason: "mismatch_value" };
}

function isTrustedCaller(req: Request): boolean {
  return callerCheck(req).ok;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);
  const caller = callerCheck(req);
  if (!caller.ok) return json({ error: "forbidden", reason: caller.reason }, 403);
  if (!SUPABASE_URL || !SERVICE_KEY) {
    return json({ error: "server misconfigured (secrets 누락)" }, 500);
  }

  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ error: "bad json" }, 400);
  }

  const paperId = body?.paper_id;
  const versionType = body?.version_type ?? DEFAULT_VERSION;
  if (!paperId) return json({ error: "paper_id required" }, 400);

  // ★ 모르는 버전은 큐에 넣지 않고 **크게 실패**한다. 조용히 다른 버전으로 갈아치우면
  //   운영자는 "실사형을 발주했는데 왜 다른 게 나왔지"를 며칠 뒤에나 알게 된다
  //   (미지원 버전 / 이 엣지 함수 배포본이 낡았을 수 있습니다 — 2026-08-20 사고).
  if (!VIDEO_VERSIONS.includes(versionType as any)) {
    return json({
      error: `미지원 버전 '${versionType}' — 이 엣지 함수 배포본이 낡았을 수 있습니다` +
        ` (지원: ${VIDEO_VERSIONS.join(", ")}). supabase functions deploy generate-directive 로 최신화하세요.`,
    }, 400);
  }

  const supa = createClient(SUPABASE_URL, SERVICE_KEY);
  try {
    const result = await enqueue(supa, paperId, versionType);
    return json({ ok: true, status: result, paper_id: paperId, version_type: versionType }, 202);
  } catch (e) {
    console.error("directive 큐 적재 실패", paperId, e);
    return json({ error: String(e).slice(0, 300) }, 500);
  }
});
