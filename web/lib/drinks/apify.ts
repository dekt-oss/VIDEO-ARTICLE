// Apify 밈 틀 정밀화(0070) — 화면 규칙·타입(순수). 값 import 없음(node --test).
// ★ 돈의 정본은 DB(drinks_apify_request·drinks_apify_month_spent)다. 여기는 버튼 옆에 "이번 예상액·이달 누적액"을 말로 바꿔 보여 준다(기획 v2 §6-1).
// ★ 숫자는 engine/config.py DRINKS_APIFY_* 와 같아야 한다(tests/test_drinks_meme_refine.py 가 SQL 과 대조한다).

export const APIFY_MONTH_CAP_USD = 3.0;
export const APIFY_RUN_CAP_USD = { meme_refine: 0.02, explainer_reference: 0.05 } as const;

export type ApifyKind = keyof typeof APIFY_RUN_CAP_USD;
export type ApifyStatus = "queued" | "running" | "done" | "partial" | "failed" | "stopped";

export const APIFY_STATUS_LABEL: Record<ApifyStatus, string> = {
  queued: "정밀화 대기(워커가 가져가길 기다림)",
  running: "정밀화 중",
  done: "정밀화 끝 — 영상 근거 칸이 찼습니다",
  partial: "일부만 — 받지 못한 릴스가 있습니다(돈은 나갔습니다)",
  failed: "실패 — 영상을 하나도 받지 못했습니다(돈은 나갔습니다)",
  stopped: "실행 안 함(상한·릴스 없음)",
};

export interface ApifyMonth { month_key: string; month_cap_usd: number; spent_usd: number; remaining_usd: number; requests: number }
export interface ApifyRequestRow {
  id: string;
  kind: ApifyKind;
  card_id: string | null;
  topic_id: string | null;
  status: ApifyStatus;
  cap_usd: number;
  est_usd: number;
  actual_usd: number | null;
  month_key: string;
  input_count: number;
  run_id: string | null;
  results: { input_url: string; status: string; duration_sec: number | null; play_count: number | null }[];
  analysis: Record<string, unknown>;
  fields_written: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
  owner_name: string | null;
  precision: "reference" | "precise" | null;
}

export function isMissingApifyTables(message: string | null | undefined): boolean {
  const m = message ?? "";
  return /drink_apify_/.test(m) && /does not exist|schema cache|not found|Could not find/i.test(m);
}

export const usd = (n: number): string => `$${n.toFixed(2)}`;

/** [쓰자] 옆 한 줄: 이번 예상액과 이달 누적액. "실행 전에 말한다"를 이 줄이 대신한다(기획 v2 §6-1). */
export function refineCostLine(month: ApifyMonth | null, kind: ApifyKind = "meme_refine"): string {
  const cap = APIFY_RUN_CAP_USD[kind];
  if (!month) return `이번 상한 ${usd(cap)} · 이달 누적 모름(0070 미적용)`;
  return `이번 상한 ${usd(cap)} · 이달 누적 ${usd(month.spent_usd)} / ${usd(month.month_cap_usd)}`;
}

/** 지금 [쓰자]를 누르면 Apify 가 도는가. 정밀 틀이면 돈을 안 쓰고, 월 상한에 닿았으면 결정만 기록된다. */
export function refinePlan(month: ApifyMonth | null, c: { precision: "reference" | "precise"; examples_count: number }, kind: ApifyKind = "meme_refine"):
  { runs: boolean; reason: string } {
  const cap = APIFY_RUN_CAP_USD[kind];
  if (c.precision === "precise") return { runs: false, reason: "이미 정밀 틀 — Apify 를 부르지 않습니다(0원)" };
  if (c.examples_count === 0) return { runs: false, reason: "공식 API 로 받은 릴스가 없어 분석할 영상이 없습니다 — 칸을 직접 넣으세요" };
  if (!month) return { runs: false, reason: "0070 미적용 — 결정만 기록됩니다" };
  if (month.spent_usd + cap > month.month_cap_usd) return { runs: false, reason: `이달 상한 ${usd(month.month_cap_usd)} 에 닿아 실행하지 않습니다(결정만 기록)` };
  return { runs: true, reason: `[쓰자] 를 누르면 릴스 3개 이하를 Apify 로 받아 형식을 잽니다 — ${refineCostLine(month, kind)}` };
}

/** 요청 한 건의 한 줄 요약(화면). 주소는 보여 주지 않는다 — 상태 수만. */
export function requestSummary(r: Pick<ApifyRequestRow, "status" | "results" | "actual_usd" | "cap_usd" | "fields_written" | "error_code">): string {
  const n = r.results.length;
  const ok = r.results.filter((x) => x.status === "ok").length;
  const money = r.actual_usd === null ? `상한 ${usd(r.cap_usd)}` : `실제 $${r.actual_usd.toFixed(4)}`;
  const parts = [APIFY_STATUS_LABEL[r.status], n > 0 ? `릴스 ${ok}/${n} 받음` : "", money];
  if (r.fields_written.length > 0) parts.push(`채운 칸: ${r.fields_written.join("·")}`);
  if (r.error_code) parts.push(r.error_code);
  return parts.filter(Boolean).join(" · ");
}

/** 손으로 만드는 카드 입력 → DB 함수 payload. 비어 있으면 보내지 않는다(DB 가 셋 다 있어야 만든다). */
export interface ManualCardInput { name: string; structure: string; beatCount: string; cutLengths: string; twistAt: string; musicSync: string; coverText: string; note: string }
export function manualCardPayload(f: ManualCardInput): Record<string, unknown> {
  const fields: Record<string, string> = {};
  for (const [k, v] of [["beat_count", f.beatCount], ["cut_lengths", f.cutLengths], ["twist_at", f.twistAt], ["music_sync", f.musicSync], ["cover_text", f.coverText]] as const) {
    if (v.trim()) fields[k] = v.trim();
  }
  return { name: f.name.trim(), ...(f.structure ? { structure: f.structure } : {}), fields, ...(f.note.trim() ? { note: f.note.trim() } : {}) };
}
