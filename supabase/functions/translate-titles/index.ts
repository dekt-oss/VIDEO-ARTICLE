// Supabase Edge Function: 제목 한국어 번역 백필 (표시용).
//
// 배경: scores.title_ko 가 빈 논문은 대시보드가 영어 원제로 폴백해 목록/아카이브에 영/한이 섞인다.
// 이 함수는 daily_batch ∪ decisions ∪ drafts 에 등장하는 논문 중 title_ko 가 빈 것을 골라
// 제목만 Gemini 로 번역해 채운다. 멱등 — 이미 채운 건 건너뛰므로 재호출로 이어서 처리 가능.
//
// ★ engine/translate.py 의 이식(동일 프롬프트/대상선정). 무료 등급 RPM 대비 요청 간 간격을 둔다.
//
// 배포:  supabase functions deploy translate-titles
// 시크릿: GEMINI_API_KEY (draft 함수와 공용), SUPABASE_URL·SUPABASE_SERVICE_ROLE_KEY 자동 주입.
// 호출:  POST {}  또는  POST {"limit": 20}  (1회 처리 상한, 기본 20 — Edge 실행시간 한도 대비)
//
// deno-lint-ignore-file no-explicit-any
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const MODEL = Deno.env.get("MODEL_SCORING") ?? "gemini-2.5-flash";
const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models";

const GAP_MS = 4500; // 무료 등급 RPM 대비 요청 간격(engine/config.GEMINI_MIN_INTERVAL_SEC 와 동일)
const DEFAULT_LIMIT = 20; // 1회 처리 상한 — Edge 실행시간 한도(≈150s) 내로.
const MAX_RETRIES = 4;
const BACKOFF_BASE_MS = 2000;
const CALL_TIMEOUT_MS = 30_000;

const TRANSLATE_SYSTEM = `너는 학술 논문 제목 번역가다. 주어진 영어(또는 비한국어) 논문 제목을
자연스러운 한국어로 번역한다. 전문용어는 통용 표기를 우선하고, 고유명사·모델명·수식은
원문을 유지해도 된다. 제목만 번역하고 설명·따옴표·주석을 붙이지 마라.
JSON only. 설명 문장·마크다운·코드펜스 금지.
{"title_ko": "<한국어 제목>"}`;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function extractJSON(text: string): any {
  let s = text.trim();
  if (s.startsWith("```")) {
    const fenceCount = (s.match(/```/g) ?? []).length;
    s = fenceCount >= 2 ? s.split("```")[1] ?? s : s.replace(/`/g, "");
    if (s.trimStart().toLowerCase().startsWith("json")) s = s.trimStart().slice(4);
  }
  const start = s.indexOf("{");
  const end = s.lastIndexOf("}");
  if (start === -1 || end === -1 || end < start) throw new Error("JSON 객체를 찾지 못함");
  return JSON.parse(s.slice(start, end + 1));
}

async function geminiJSON(system: string, user: string, maxTokens: number): Promise<any> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const resp = await fetch(`${GEMINI_BASE}/${MODEL}:generateContent?key=${GEMINI_API_KEY}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          system_instruction: { parts: [{ text: system }] },
          contents: [{ role: "user", parts: [{ text: user }] }],
          generationConfig: { responseMimeType: "application/json", maxOutputTokens: maxTokens, temperature: 0.3 },
        }),
        signal: AbortSignal.timeout(CALL_TIMEOUT_MS),
      });
      if (resp.status === 429 || resp.status >= 500) throw new Error(`gemini ${resp.status}`);
      if (!resp.ok) {
        const body = await resp.text();
        const err: any = new Error(`gemini ${resp.status}: ${body.slice(0, 160)}`);
        err.fatal = true;
        throw err;
      }
      const data = await resp.json();
      const raw = (data?.candidates?.[0]?.content?.parts ?? []).map((p: any) => p?.text ?? "").join("");
      return extractJSON(raw);
    } catch (err: any) {
      lastErr = err;
      if (err?.fatal) break;
      if (attempt < MAX_RETRIES - 1) await sleep(BACKOFF_BASE_MS * 2 ** attempt);
    }
  }
  throw lastErr;
}

// 대상: daily_batch ∪ decisions ∪ drafts 에 등장하고 scores.title_ko 가 빈 논문.
async function targets(supa: any, limit: number): Promise<{ id: string; title: string }[]> {
  const [batch, decs, drafts] = await Promise.all([
    supa.from("daily_batch").select("paper_id"),
    supa.from("decisions").select("paper_id"),
    supa.from("drafts").select("paper_id"),
  ]);
  const ids = new Set<string>();
  for (const r of batch.data ?? []) ids.add(r.paper_id);
  for (const r of decs.data ?? []) ids.add(r.paper_id);
  for (const r of drafts.data ?? []) ids.add(r.paper_id);
  if (ids.size === 0) return [];

  const idList = [...ids];
  const hasKo = new Set<string>();
  for (let i = 0; i < idList.length; i += 200) {
    const chunk = idList.slice(i, i + 200);
    const { data } = await supa.from("scores").select("paper_id, title_ko").in("paper_id", chunk);
    for (const s of data ?? []) if ((s.title_ko ?? "").trim()) hasKo.add(s.paper_id);
  }
  const need = idList.filter((id) => !hasKo.has(id));
  if (need.length === 0) return [];

  const out: { id: string; title: string }[] = [];
  for (let i = 0; i < need.length && out.length < limit; i += 200) {
    const chunk = need.slice(i, i + 200);
    const { data } = await supa.from("papers").select("id, title").in("id", chunk);
    for (const p of data ?? []) {
      if ((p.title ?? "").trim()) out.push({ id: p.id, title: p.title });
      if (out.length >= limit) break;
    }
  }
  return out;
}

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
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
  if (!GEMINI_API_KEY || !SUPABASE_URL || !SERVICE_KEY) {
    return json({ error: "server misconfigured (secrets 누락)" }, 500);
  }
  const body = await req.json().catch(() => ({}));
  const limit = Math.max(1, Math.min(50, Number(body?.limit ?? DEFAULT_LIMIT)));

  const supa = createClient(SUPABASE_URL, SERVICE_KEY);
  const list = await targets(supa, limit);
  let filled = 0;
  const errors: string[] = [];

  for (let i = 0; i < list.length; i++) {
    if (i > 0) await sleep(GAP_MS); // RPM 대비 간격
    const { id, title } = list[i];
    try {
      const obj = await geminiJSON(TRANSLATE_SYSTEM, `제목: ${title}`, 512);
      const ko = String(obj?.title_ko ?? "").trim();
      if (ko) {
        await supa.from("scores").upsert({ paper_id: id, title_ko: ko }, { onConflict: "paper_id" });
        filled++;
      }
    } catch (err) {
      errors.push(`${id}: ${String(err).slice(0, 100)}`);
    }
  }

  // 남은 대상 수(대략) — 이번에 못 채운 것 + 상한 초과분.
  const remaining = await targets(supa, 1000).then((r) => r.length).catch(() => -1);
  return json({ processed: list.length, filled, remaining, errors: errors.slice(0, 10) });
});
