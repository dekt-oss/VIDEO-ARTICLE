// AI 사실 확인(2026-11-06, 운영자 승인 — docs/deviation-drinks-auto-factcheck.md) 화면 계산. 순수 모듈 — 값 import 금지(node --test 가 직접 읽는다).
//
// 워커(engine/drinks_develop.py::run_factcheck)가 근거 요청 기록(result.factcheck)에 판정을 남긴다:
//   assertions[] = 소재 질문이 담은 주장마다 맞음·틀림·불확실 + 이유 + 근거 출처. 코드가 모델 판정을 다시 잰 값이다(code_note = 코드가 바꾼 이유).
//   auto_supported = '확인됨'으로 자동 저장된 주장 · not_supported = 운영자가 직접 봐야 하는 주장(이유 포함).
// ★ 승인은 여전히 사람의 [승인] 한 번이다. 이 화면은 그 사람이 읽고 누르기 쉽게 정리할 뿐이다.

// ★ 아래 두 글은 엔진과 같아야 한다(tests/test_drinks_develop.py::test_official_source_hints_match_config 가 대조).
/** 워커가 직접 가져온 출처의 연결 메모(engine AUTO_SOURCE_NOTE) */
export const AUTO_SOURCE_NOTE = "자동 개발: 공식 출처 목록에서 가져온 원문";
/** AI 사실 확인으로 '확인됨'이 된 주장의 한계·주의 칸(engine DRINKS_DEVELOP_FACTCHECK_NOTE) */
export const FACTCHECK_NOTE = "AI 사실 확인(자동) — 근거 인용 대조 통과";

export type Verdict = "TRUE" | "FALSE" | "UNCERTAIN";
export const VERDICT_LABEL: Record<Verdict, string> = { TRUE: "맞음", FALSE: "틀림", UNCERTAIN: "불확실" };
export const VERDICT_TONE: Record<Verdict, "ok" | "bad" | "warn"> = { TRUE: "ok", FALSE: "bad", UNCERTAIN: "warn" };

export interface FactcheckSource { claim_id: string; title: string; url: string | null; publisher: string | null }
export interface FactcheckAssertion {
  assertion_ko: string;
  verdict: Verdict;
  model_verdict: string | null;
  claim_ids: string[];
  reason_ko: string;
  code_note: string | null;
  sources: FactcheckSource[];
}
export interface FactcheckResult {
  status: "ok" | "failed" | "skipped" | "no_claims" | "disabled";
  note: string | null;
  assertions: FactcheckAssertion[];
  counts: Record<Verdict, number>;
  autoSupported: string[];
  notSupported: { claim_id: string; why: string; text: string }[];
}

export const FACTCHECK_STATUS_TEXT: Record<FactcheckResult["status"], string> = {
  ok: "",
  failed: "AI 사실 확인을 하지 못했습니다(응답을 읽지 못함) — 모든 주장을 직접 확인하세요.",
  skipped: "AI 사실 확인을 건너뛰었습니다(한도·상한) — 모든 주장을 직접 확인하세요.",
  no_claims: "확인할 사실 주장이 없습니다(평가·의견만 있음).",
  disabled: "AI 사실 확인이 꺼져 있습니다 — 모든 주장을 직접 확인하세요.",
};

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const isVerdict = (v: unknown): v is Verdict => v === "TRUE" || v === "FALSE" || v === "UNCERTAIN";

/** 요청 기록의 result → 판정. 모양이 다르거나 없으면 null(판정이 '없었다'와 '못 읽었다'를 화면이 같게 다루지 않도록 status 를 본다). */
export function parseFactcheck(result: unknown): FactcheckResult | null {
  const fc = (result && typeof result === "object" ? (result as Record<string, unknown>).factcheck : null) as Record<string, unknown> | null;
  if (!fc || typeof fc !== "object") return null;
  const status = (["ok", "failed", "skipped", "no_claims", "disabled"] as const).find((s) => s === fc.status) ?? "failed";
  const assertions: FactcheckAssertion[] = arr(fc.assertions).flatMap((a) => {
    const o = (a ?? {}) as Record<string, unknown>;
    if (!str(o.assertion_ko)) return [];
    return [{
      assertion_ko: str(o.assertion_ko),
      verdict: isVerdict(o.verdict) ? o.verdict : "UNCERTAIN",
      model_verdict: strOrNull(o.model_verdict),
      claim_ids: arr(o.claim_ids).map(String),
      reason_ko: str(o.reason_ko),
      code_note: strOrNull(o.code_note),
      sources: arr(o.sources).map((s) => {
        const x = (s ?? {}) as Record<string, unknown>;
        return { claim_id: str(x.claim_id), title: str(x.title) || "(제목 없음)", url: strOrNull(x.url), publisher: strOrNull(x.publisher) };
      }),
    }];
  });
  const counts: Record<Verdict, number> = { TRUE: 0, FALSE: 0, UNCERTAIN: 0 };
  for (const a of assertions) counts[a.verdict] += 1;
  return {
    status,
    note: strOrNull(fc.note),
    assertions,
    counts,
    autoSupported: arr(fc.auto_supported).map(String),
    notSupported: arr(fc.not_supported).map((n) => {
      const x = (n ?? {}) as Record<string, unknown>;
      return { claim_id: str(x.claim_id), why: str(x.why), text: str(x.text) };
    }),
  };
}

interface RequestLike { kind: string; status: string; result?: unknown; result_review_id?: string | null; created_at: string }

/** 이 근거 버전을 만든 근거 요청의 판정. 같은 버전이 없으면 가장 최근 판정을 '이전 버전 기준'으로 준다. */
export function factcheckFor(requests: readonly RequestLike[], reviewId: string | null): { fc: FactcheckResult; sameReview: boolean } | null {
  const done = requests
    .filter((r) => r.kind === "evidence" && r.status === "succeeded")
    .slice()
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const same = reviewId ? done.find((r) => r.result_review_id === reviewId) : undefined;
  const pick = same ?? done[0];
  const fc = pick ? parseFactcheck(pick.result) : null;
  return fc ? { fc, sameReview: Boolean(same) } : null;
}

/** 주장이 AI 사실 확인으로 '확인됨'이 됐는가(사람이 고른 확인됨과 구분). */
export function isAutoSupported(c: { support_review: string; limitations: string | null }): boolean {
  return c.support_review === "supported" && c.limitations === FACTCHECK_NOTE;
}

/** 워커가 직접 가져온 출처인가 — 새 기록은 연결 메모로, 옛 기록은 공식 출처 주소로 알아본다(주소 목록은 부르는 쪽이 준다). */
export function isAutoFetched(relationNote: string | null | undefined, isOfficialUrl: boolean): boolean {
  return (relationNote ?? "").startsWith("자동 개발") || isOfficialUrl;
}

/** 질문이 나온 곳(사실 근거가 아닌 출처) — 근거 카드 대신 접힌 묶음에 둔다. */
export function isQuestionOrigin(role: string, sourceKind: string): boolean {
  return role === "discovery" || sourceKind === "community" || sourceKind === "reader";
}

/** 이 소재에 만드는 중인 AI 초안 요청이 있으면 근거를 고치지 못하게 할 이유. 없으면 null. */
export function evidenceLockReason(requests: readonly { kind: string; status: string }[]): string | null {
  const active = requests.find((r) => r.status === "queued" || r.status === "running");
  if (!active) return null;
  const what = active.kind === "evidence" ? "근거 초안" : "대본 초안";
  const when = active.status === "queued" ? "만들 차례를 기다리는 중" : "만드는 중";
  const harm = active.kind === "evidence" ? "만드는 중인 근거 초안이 저장되지 못하고 실패합니다(draft_exists)" : "만드는 중인 대본이 바뀐 근거와 맞지 않아 무효가 됩니다";
  return `AI 가 ${what}을 ${when}이라 근거를 고칠 수 없습니다 — 지금 저장하면 ${harm}. 끝나면 자동으로 풀립니다.`;
}
