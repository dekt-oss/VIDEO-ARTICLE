// 주류 소재 개발(0060) 화면 순수 계산 — 버튼 활성 조건·상태 이름·오류 문장·결과 링크.
//
// ★ 판정의 정본은 DB 다(결재 잔액·승인 상태·동시 요청). 여기 있는 계산은 버튼을 잠그고 이유를 보여주는 편의이고,
//   누르면 서버가 같은 조건을 다시 검사한다.
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다.

export type DevelopKind = "evidence" | "plan";
export type DevelopStatus = "queued" | "running" | "succeeded" | "failed" | "canceled" | "blocked";

export const DEVELOP_KIND_LABEL: Record<DevelopKind, string> = { evidence: "근거 초안", plan: "대본·장면 초안" };

export const DEVELOP_STATUS_LABEL: Record<DevelopStatus, string> = {
  queued: "대기",
  running: "만드는 중",
  succeeded: "초안 생성됨",
  failed: "실패",
  canceled: "취소",
  blocked: "막힘",
};

/** drinks_develop_status 한 행. 0060 적용 전에는 이 모양이 오지 않는다. */
export interface DevelopRequestRow {
  request_id: string;
  kind: DevelopKind;
  status: DevelopStatus;
  step: string | null;
  error_code: string | null;
  error_message: string | null;
  cost_usd: number | string | null;
  result_review_id: string | null;
  result_plan_revision_id: string | null;
  created_at: string;
  finished_at: string | null;
}

/** drink_develop_budget_state 한 행. */
export interface DevelopBudgetRow {
  budget_id: string;
  stage: string;
  cap_usd: number | string;
  spent_usd: number | string;
  held_usd: number | string;
  remaining_usd: number | string;
  status: "open" | "closed";
  expires_at: string;
  approver_words: string | null;
}

export type Tone = "ok" | "warn" | "bad" | "info";

export function statusTone(s: DevelopStatus): Tone {
  switch (s) {
    case "succeeded": return "ok";
    case "failed": return "bad";
    case "blocked": return "warn";
    default: return "info";
  }
}

export const isActive = (r: Pick<DevelopRequestRow, "status">): boolean => r.status === "queued" || r.status === "running";

/**
 * 0060 이 아직 운영 DB 에 없다는 오류인가. 함수 없음(42883·PGRST202)·표/뷰 없음(42P01·PGRST205)과
 * 메시지 문구(스키마 캐시에 없음) 모두 본다 — 페이지 읽기 코드가 코드값을 잃고 문장만 넘기는 경로가 있다.
 */
export function isSchemaMissing(err: { code?: string | null; message?: string | null } | null | undefined): boolean {
  if (!err) return false;
  if (err.code && ["42883", "42P01", "PGRST202", "PGRST205"].includes(err.code)) return true;
  const m = err.message ?? "";
  return /schema cache|could not find the (function|table)|does not exist|drinks_develop_status|drink_develop_budget_state/i.test(m)
    && /develop/i.test(m);
}

const money = (v: number | string | null | undefined): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** 지금 쓸 수 있는 결재: 열려 있고, 기한이 안 지났고, 남은 금액이 있다. */
export function usableBudgets(budgets: readonly DevelopBudgetRow[], nowMs: number): DevelopBudgetRow[] {
  return budgets.filter((b) => b.status === "open" && Date.parse(b.expires_at) > nowMs && money(b.remaining_usd) > 0);
}

/** 쓸 결재 하나: 남은 금액이 가장 큰 것(같으면 기한이 늦은 것). 없으면 null. */
export function pickBudget(budgets: readonly DevelopBudgetRow[], nowMs: number): DevelopBudgetRow | null {
  const u = usableBudgets(budgets, nowMs);
  if (u.length === 0) return null;
  return [...u].sort((a, b) => money(b.remaining_usd) - money(a.remaining_usd) || Date.parse(b.expires_at) - Date.parse(a.expires_at))[0];
}

export interface ButtonState {
  enabled: boolean;
  /** 잠겼을 때 왜 잠겼는지 */
  reason: string | null;
}

export interface DevelopInput {
  topicStatus: string;
  /** 쓸 수 있는 결재가 있는가 */
  hasBudget: boolean;
  /** 이 소재에 승인된 근거가 있고 지금도 유효한가(deriveTopic().approvalValid) */
  approvedEvidence: boolean;
  requests: readonly Pick<DevelopRequestRow, "kind" | "status">[];
}

const CLOSED_TOPIC = new Set(["on_hold", "rejected", "duplicate"]);

export function developButtons(i: DevelopInput): Record<DevelopKind, ButtonState> {
  const activeOf = (k: DevelopKind) => i.requests.some((r) => r.kind === k && isActive(r));
  const closedTopic = CLOSED_TOPIC.has(i.topicStatus);
  const common = (k: DevelopKind): string | null => {
    if (closedTopic) return "보류·제외·중복 처리된 소재입니다 — 다시 연 뒤에 만드세요";
    if (!i.hasBudget) return "열린 개발 결재가 없습니다 — 위에서 결재를 먼저 등록하세요";
    if (activeOf(k)) return `${DEVELOP_KIND_LABEL[k]}을(를) 이미 만드는 중입니다`;
    return null;
  };
  const ev = common("evidence");
  let pl = common("plan");
  if (!pl && !i.approvedEvidence) pl = "근거를 승인한 뒤에 만들 수 있습니다(근거 탭에서 승인)";
  return {
    evidence: { enabled: ev === null, reason: ev },
    plan: { enabled: pl === null, reason: pl },
  };
}

// ── 오류 문장 ──

const ERROR_TEXT: Record<string, string> = {
  evidence_insufficient: "공식 근거가 3개 미만이라 멈췄습니다 — 출처를 더 붙이거나 소재를 보류하세요",
  budget_missing: "개발 결재가 없어 멈췄습니다 — 결재를 등록한 뒤 다시 요청하세요",
  budget_exceeded: "결재 금액을 넘게 돼 멈췄습니다 — 남은 금액을 확인하거나 결재를 새로 등록하세요",
  script_check_failed: "대본 검사에서 두 번 막혔습니다 — 아래 사유를 보고 직접 고치세요",
};

export interface ErrorView {
  text: string;
  /** 사유 원문(번역한 코드일 때만 따로 붙인다) */
  detail: string | null;
}

export function developErrorView(code: string | null, message: string | null): ErrorView | null {
  const msg = message?.trim() || null;
  if (!code && !msg) return null;
  if (code && ERROR_TEXT[code]) return { text: ERROR_TEXT[code], detail: msg };
  return { text: [code, msg].filter(Boolean).join(": "), detail: null };
}

// ── 결과 링크 ──

export interface ResultLink {
  label: string;
  href: string;
}

/** 생성된 초안으로 가는 링크. 제작안 형식은 이 소재의 제작안 목록에서 찾고, 못 찾으면 영상 탭으로 보낸다. */
export function resultLinks(
  topicId: string,
  r: Pick<DevelopRequestRow, "result_review_id" | "result_plan_revision_id">,
  plans: readonly { id: string; format: string }[]
): ResultLink[] {
  const out: ResultLink[] = [];
  if (r.result_review_id) out.push({ label: "근거 초안 보기", href: `/drinks/review/${topicId}?tab=evidence` });
  if (r.result_plan_revision_id) {
    const f = plans.find((p) => p.id === r.result_plan_revision_id)?.format;
    out.push({ label: "대본·장면 초안 보기", href: `/drinks/review/${topicId}?tab=${f === "carousel" ? "carousel" : "video"}` });
  }
  return out;
}

/** 최신순. 같은 시각이면 id 로 고정. */
export function sortRequests<T extends Pick<DevelopRequestRow, "created_at" | "request_id">>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || (a.request_id < b.request_id ? 1 : -1));
}

/** 요청 직후 안내 문장. dispatch 가 없으면 다음 실행을 기다린다. */
export function requestNote(r: { existing?: boolean; triggered?: boolean }): string {
  if (r.existing) return "같은 요청이 이미 대기·진행 중입니다 — 그 작업을 보여줍니다.";
  if (r.triggered) return "개발 워커를 깨웠습니다.";
  return "대기열에 넣었습니다. 워커 자동 깨우기가 설정되지 않아 다음 실행 때 처리됩니다.";
}
