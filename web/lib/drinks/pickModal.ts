// 소재 고르기 [이걸로 ▾] 모달의 순수 규칙(2026-11-05, docs/deviation-drinks-multi-format.md §3-5·G6).
//   형식 체크(0개 막음·3개 초과 막음·중복 제거) · 편성 주차 후보(월요일) · 형식별 예상 비용 요약("모르면 모름", 0 으로 쓰지 않는다) ·
//   pick_topic 응답(result.picks[]) 을 형식별 네 갈래(큐 등록+워커 깨움 / 큐 등록(다음 크론) / 이미 있음 / 실패)로 가르기 ·
//   후보 카드가 지금 고를 수 있는지(가능 / 막힘 + 이유).
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다(components/drinks/topics/pickModal.test.ts).

export type PickFormat = "explainer" | "card" | "meme";
export const PICK_FORMATS: readonly PickFormat[] = ["explainer", "meme", "card"];   // 목업 순서(릴스·밈·카드뉴스)
export const PICK_FORMAT_MAX = 3;

export const PICK_FORMAT_LABEL: Record<PickFormat, string> = { explainer: "릴스(설명형)", meme: "밈", card: "카드뉴스" };
export const PICK_FORMAT_HINT: Record<PickFormat, string> = {
  explainer: "대본·장면 구성·영상화 기획", meme: "짧은 글·공감·반전 기획", card: "표지·페이지별 문구·배치 기획",
};

// ── 형식 체크 ──────────────────────────────────────────────────────────────

/** 체크/해제. 같은 형식은 한 번만 들어가고, 알 수 없는 값은 버린다. */
export function toggleFormat(current: readonly string[], format: string, checked: boolean): PickFormat[] {
  const valid = (x: string): x is PickFormat => (PICK_FORMATS as readonly string[]).includes(x);
  const next = current.filter(valid).filter((f) => f !== format);
  if (checked && valid(format)) next.push(format);
  return [...new Set(next)];
}

export type FormatCheck = { ok: true; formats: PickFormat[] } | { ok: false; reason: string };

/** 제출 가능 여부. 0개면 막고, 상한(3)을 넘어도 막는다(중복은 지운 뒤 센다). */
export function validateFormats(current: readonly string[]): FormatCheck {
  const formats = [...new Set(current.filter((x): x is PickFormat => (PICK_FORMATS as readonly string[]).includes(x)))];
  if (formats.length === 0) return { ok: false, reason: "형식을 하나 이상 골라 주세요" };
  if (formats.length > PICK_FORMAT_MAX) return { ok: false, reason: `형식은 최대 ${PICK_FORMAT_MAX}개입니다` };
  return { ok: true, formats };
}

// ── 편성 주차(월요일) ────────────────────────────────────────────────────────

export interface WeekOption { value: string; label: string }

function mondayOfIso(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() - ((dt.getUTCDay() + 6) % 7));
  return dt.toISOString().slice(0, 10);
}

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + n));
  return dt.toISOString().slice(0, 10);
}

const md = (iso: string): string => `${Number(iso.slice(5, 7))}월 ${Number(iso.slice(8, 10))}일`;

/** 오늘(KST, YYYY-MM-DD)이 속한 주부터 n 주의 월요일. 첫째는 "이번 주", 둘째는 "다음 주". */
export function weekOptions(today: string, n = 4): WeekOption[] {
  const first = mondayOfIso(today);
  const out: WeekOption[] = [];
  for (let i = 0; i < n; i++) {
    const mon = addDays(first, i * 7);
    const prefix = i === 0 ? "이번 주" : i === 1 ? "다음 주" : `${i}주 뒤`;
    const sun = addDays(mon, 6);
    // 같은 달이면 끝 날짜의 달을 되풀이하지 않는다(목업: "11월 2일–8일").
    const end = sun.slice(0, 7) === mon.slice(0, 7) ? `${Number(sun.slice(8, 10))}일` : md(sun);
    out.push({ value: mon, label: `${prefix} · ${md(mon)}–${end}` });
  }
  return out;
}

// ── 비용 요약 ──────────────────────────────────────────────────────────────

export type EstimateMap = Record<PickFormat, number | null>;
export const UNKNOWN_ESTIMATE: EstimateMap = { explainer: null, card: null, meme: null };

const usd = (n: number): string => `$${n.toFixed(2)}`;

function numOrNull(x: unknown): number | null {
  if (typeof x === "number" && Number.isFinite(x)) return x;
  if (typeof x === "string" && x.trim() !== "" && Number.isFinite(Number(x))) return Number(x);
  return null;
}

/**
 * drinks_develop_estimate(loadDevelopEstimate) 응답을 형식 → 금액(모르면 null) 로 고른다. 모양이 아직 확정 전이라
 * 흔한 셋을 받는다: `{explainer: 0.15, ...}` · `{per_format: {...}}` · `[{format_intent|format, est_usd|usd|amount_usd}]` · `{formats: [...]}`.
 * 못 알아보면 전부 null — 화면이 "모름"이라고 말한다. 0 으로 채우지 않는다.
 */
export function normalizeEstimate(raw: unknown): EstimateMap {
  const out: EstimateMap = { ...UNKNOWN_ESTIMATE };
  if (!raw || typeof raw !== "object") return out;
  const o = raw as Record<string, unknown>;
  const list = Array.isArray(raw) ? raw : Array.isArray(o.formats) ? o.formats : Array.isArray(o.per_format) ? o.per_format : null;
  if (list) {
    for (const row of list as Record<string, unknown>[]) {
      if (!row || typeof row !== "object") continue;
      const f = (row.format_intent ?? row.format) as string;
      if ((PICK_FORMATS as readonly string[]).includes(f)) out[f as PickFormat] = numOrNull(row.est_usd ?? row.usd ?? row.amount_usd ?? row.estimate_usd);
    }
    return out;
  }
  const map = (o.per_format && typeof o.per_format === "object" ? o.per_format : o) as Record<string, unknown>;
  for (const f of PICK_FORMATS) {
    if (!(f in map)) continue;
    const v = map[f];
    // queries.ts DevelopEstimate: per_format[f] = { usd, shared?, note? }
    out[f] = v && typeof v === "object" ? numOrNull((v as Record<string, unknown>).usd ?? (v as Record<string, unknown>).est_usd) : numOrNull(v);
  }
  return out;
}

export interface CostLine { format: PickFormat; text: string; known: boolean }
export interface CostSummary {
  lines: CostLine[];
  /** 합계. 고른 형식 중 하나라도 모르면 "모름" — 아는 것만 더한 값을 합계로 내지 않는다 */
  total: string;
  totalKnown: boolean;
}

/** 고른 형식의 예상 초안 비용. 모르는 값은 "모름"(0원 아님). 0 은 진짜 0 일 때만 "$0.00". */
export function costSummary(est: EstimateMap, formats: readonly PickFormat[]): CostSummary {
  const lines: CostLine[] = formats.map((f) => {
    const v = est[f];
    return v === null || v === undefined ? { format: f, text: "모름", known: false } : { format: f, text: usd(v), known: true };
  });
  if (formats.length === 0) return { lines, total: "형식을 고르면 보입니다", totalKnown: false };
  const unknown = lines.filter((l) => !l.known).length;
  if (unknown > 0) return { lines, total: `모름 (${unknown}개 형식의 비용을 읽지 못했습니다)`, totalKnown: false };
  return { lines, total: usd(formats.reduce((s, f) => s + (est[f] as number), 0)), totalKnown: true };
}

// ── pick_topic 응답 갈래 ─────────────────────────────────────────────────────

export type PickBranch = "queued_woken" | "queued_wait" | "existing" | "failed";
export const PICK_BRANCH_LABEL: Record<PickBranch, string> = {
  queued_woken: "큐 등록 · 워커를 깨웠습니다", queued_wait: "큐 등록 · 다음 크론이 처리합니다(토큰 없음)", existing: "이미 있음", failed: "실패",
};

/** pick_topic 응답의 형식별 행(서버 모양이 확정 전이라 느슨하게 받는다). */
export interface PickRow {
  format_intent?: string; format?: string;
  queued?: boolean; existing?: boolean; ok?: boolean;
  code?: string | null; message?: string | null; error?: string | null;
}
export interface PickOutcome { format: PickFormat; branch: PickBranch; text: string }

/** result.picks[] (없으면 옛 result.chain 하나를 첫 형식으로) → 형식별 갈래. 고른 형식인데 응답에 없으면 실패(응답 누락)로 본다. */
export function pickOutcomes(
  result: { picks?: PickRow[]; chain?: PickRow } | undefined,
  formats: readonly PickFormat[],
  dispatch: { triggered: boolean } | undefined
): PickOutcome[] {
  const rows: PickRow[] = result?.picks ?? (result?.chain ? [{ ...result.chain, format_intent: formats[0] }] : []);
  return formats.map((f) => {
    const r = rows.find((x) => (x.format_intent ?? x.format) === f);
    if (!r) return { format: f, branch: "failed", text: "응답에 이 형식의 결과가 없습니다 — 작업공간에서 상태를 확인하세요" };
    if (r.ok === false || r.error) return { format: f, branch: "failed", text: `${r.code ?? "error"}: ${r.error ?? r.message ?? "원인 미상"}` };
    if (r.existing) return { format: f, branch: "existing", text: r.message ?? "같은 요청이 이미 대기·진행 중입니다" };
    if (r.queued) {
      return dispatch?.triggered
        ? { format: f, branch: "queued_woken", text: r.message ?? "초안 요청을 넣고 워커를 깨웠습니다" }
        : { format: f, branch: "queued_wait", text: r.message ?? "초안 요청을 넣었습니다. 워커 자동 깨우기 토큰이 없어 다음 크론이 처리합니다" };
    }
    if (r.code) return { format: f, branch: "failed", text: `${r.code}: ${r.message ?? "원인 미상"}` };
    // 큐에 넣지 않았고 오류도 아니다(예: 밈은 형식만 적어 두고 제작안은 작업공간에서 쓴다) — 적어 둔 것으로 본다.
    return { format: f, branch: "existing", text: r.message ?? "형식을 적어 뒀습니다. 제작안은 작업공간에서 씁니다" };
  });
}

// ── 지금 고를 수 있나 ───────────────────────────────────────────────────────

export type Pickability = { ok: true } | { ok: false; code: "no_budget" | "duplicate" | "promoted" | "no_score"; reason: string };

export function pickability(c: {
  status: string; promoted_topic_id: string | null; duplicate_topic_ids: readonly string[]; provisional_score: number | string | null;
}, hasBudget: boolean): Pickability {
  if (c.status !== "suggested" || c.promoted_topic_id) return { ok: false, code: "promoted", reason: "이미 소재로 올렸습니다 — 형식은 작업공간에서 더합니다" };
  if (c.provisional_score === null || c.provisional_score === undefined || c.provisional_score === "") {
    return { ok: false, code: "no_score", reason: "경량 점수가 없어 고를 수 없습니다 — 다음 발견 실행이 채웁니다" };
  }
  if (c.duplicate_topic_ids.length > 0) {
    return { ok: false, code: "duplicate", reason: `비슷한 기존 소재 ${c.duplicate_topic_ids.length}건 — 새로 만들지 말고 그 소재에 형식을 더하세요` };
  }
  if (!hasBudget) return { ok: false, code: "no_budget", reason: "열린 개발 결재가 없어 초안을 쓸 수 없습니다 — 이 화면 맨 위 칸에서 결재를 여세요" };
  return { ok: true };
}
