// 내용 승인 한 화면(0064) 순수 계산 — 이어 만들기 상태, 승인 버튼을 잠그는 이유.
//
// ★ 판정의 정본은 DB 다(drinks_approve_content 가 같은 조건을 다시 재고, 안쪽의 기존 승인 함수들이 또 잰다). 여기 계산은 버튼을 잠그고 이유를 보여주는 편의다.
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다.
import type { DevelopRequestRow } from "./develop";
import type { FormatIntent } from "./formatRecommend";

/** drink_topic_picks 한 행(0064). 형식 의도만 담는다 — 돈이 나가지 않는다. */
export interface PickRow {
  topic_id: string;
  format_intent: FormatIntent;
  recommended_format: string | null;
  recommended_reason: string | null;
  editorial_week: string;
  budget_id: string | null;
  candidate_id: string | null;
  approved_at: string | null;
  approved_amount_usd: number | string | null;
  version: number;
}

export const INTENT_TO_FORMAT: Record<FormatIntent, "video" | "carousel" | null> = { explainer: "video", card: "carousel", meme: null };

/** 기획 v2 §3-7 계획값 — engine/config.py DRINKS_EXPLAINER_* 와 같아야 한다(tests/test_drinks_develop.py 가 대조). 이 편의 실측이 아니다. */
export const EXPLAINER_ESTIMATE_USD = 7.95;
export const EXPLAINER_APPROVAL_CAP_USD = 8.9;
/** 0054 drinks_spend_limits().max_cap_usd — DB 가 다시 잰다. */
export const MAX_APPROVAL_USD = 10;

export type ChainState = "none" | "running" | "stopped" | "ready" | "invalidated";

export interface ChainView {
  state: ChainState;
  /** 운영자에게 보이는 지금 단계 한 줄 */
  label: string;
  /** 멈췄을 때 이유(서버가 준 문장 그대로) */
  reason: string | null;
  /** 멈춘 코드: evidence_insufficient·budget_missing·script_check_failed·meme_board … (card_plan_not_built 는 0065 이전 기록에만 있다) */
  code: string | null;
}

interface PlanLike {
  plan_status: string;
  blocked_at: string | null;
  blocked_reason?: string | null;
  topic_review_id: string;
  drafted_from_unapproved?: boolean;
}

interface ReviewLike {
  id: string;
  status: string;
}

type RequestLike = Pick<DevelopRequestRow, "kind" | "status" | "created_at" | "error_code" | "error_message"> & {
  result?: Record<string, unknown> | null;
};

const newest = <T extends { created_at: string }>(rows: readonly T[]): T[] =>
  [...rows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

const STOPPED_REQUEST: Record<string, string> = {
  evidence_insufficient: "원문 대조를 통과한 근거가 모자라 멈췄습니다",
  budget_missing: "개발 결재가 없어 모델을 부르지 않고 멈췄습니다",
  budget_exceeded: "개발 결재 금액을 넘게 돼 멈췄습니다",
  script_check_failed: "대본 검사에서 두 번 막혀 저장하지 않았습니다",
  review_changed: "대본을 쓰는 사이 근거가 바뀌어 저장하지 않았습니다",
};

/** 지금 쓸 수 있는 이어 만들기 대본: 표시가 있고, 차단되지 않았고, 작업 중 근거 버전으로 쓴 작성 중 대본. */
export function usableDraftPlan(plan: PlanLike | null | undefined, review: ReviewLike | null | undefined): boolean {
  return Boolean(plan && review && plan.drafted_from_unapproved && plan.plan_status === "draft" && !plan.blocked_at
    && plan.topic_review_id === review.id && (review.status === "draft" || review.status === "in_review"));
}

export function chainView(i: {
  pick: Pick<PickRow, "format_intent"> | null;
  requests: readonly RequestLike[];
  review: ReviewLike | null;
  plan: PlanLike | null;
}): ChainView {
  const reqs = newest(i.requests);
  const active = reqs.find((r) => r.status === "queued" || r.status === "running");
  if (active) {
    const what = active.kind === "evidence" ? "근거 초안" : "대본·장면 초안";
    return { state: "running", label: `${what}을 만드는 중입니다${active.status === "queued" ? "(대기)" : ""}`, reason: null, code: null };
  }
  if (usableDraftPlan(i.plan, i.review)) return { state: "ready", label: "근거·대본 초안이 준비됐습니다", reason: null, code: null };
  if (i.plan?.drafted_from_unapproved && i.plan.blocked_at && i.plan.plan_status === "draft") {
    return {
      state: "invalidated", label: "근거가 바뀌어 대본이 무효가 됐습니다", code: "evidence_edited",
      reason: (i.plan.blocked_reason ?? "").replace(/^evidence_edited:\s*/, "") || "이 대본을 만든 뒤 근거가 바뀌었습니다",
    };
  }
  if (i.pick?.format_intent === "meme") {
    return { state: "stopped", label: "밈형은 근거·대본을 만들지 않습니다", code: "meme_board",
      reason: "형식만 적어 두었습니다. 제작안은 밈 보드의 [밈 제작] 칸에서 씁니다(0066 적용 후)." };
  }
  const last = reqs[0];
  if (last && last.status !== "succeeded") {
    const code = last.error_code ?? last.status;
    return {
      state: "stopped", label: STOPPED_REQUEST[code] ?? `${last.kind === "evidence" ? "근거 초안" : "대본 초안"}에서 멈췄습니다`,
      reason: last.error_message?.trim() || code, code,
    };
  }
  const chain = last?.result?.chain as { queued?: boolean; code?: string; message?: string } | undefined;
  if (last?.kind === "evidence" && chain && chain.queued === false) {
    return { state: "stopped", label: "근거까지 만들고 멈췄습니다", reason: chain.message ?? chain.code ?? null, code: chain.code ?? null };
  }
  if (i.pick) {
    return { state: "stopped", label: "아직 이어 만들고 있지 않습니다", reason: "진행 중인 요청이 없습니다 — [다시 이어 만들기]를 누르세요.", code: "not_started" };
  }
  return { state: "none", label: "[이걸로]로 형식을 고르지 않은 소재입니다", reason: null, code: null };
}

export interface ApprovalInput {
  pick: Pick<PickRow, "format_intent"> | null;
  chain: Pick<ChainView, "state" | "label" | "reason">;
  /** 저장 안 한 수정이 있는가 */
  dirty: boolean;
  /** 서버가 잰 필수 조건 미달(readiness.blockers) */
  blockers: readonly string[];
  /** 5축 가중 합. 축이 비면 null(점수 미완은 blockers 가 말한다) */
  score: number | null;
  selectThreshold: number;
  scoreException: string;
  /** 고른 형식의 적합성 점수(fit_video·fit_carousel). 없으면 null */
  formatFit: number | null;
  fitMin: number;
  fitException: string;
  amountUsd: number;
}

/** 승인 버튼을 잠그는 이유 전부. 빈 배열이면 누를 수 있다(서버가 다시 잰다). blockerText 는 model.ts 의 blockerLabel. */
export function approvalLocks(i: ApprovalInput, blockerText: (code: string) => string): string[] {
  const out: string[] = [];
  if (!i.pick) out.push("[이걸로]로 형식을 고른 소재만 이 화면에서 승인합니다.");
  else if (INTENT_TO_FORMAT[i.pick.format_intent] === null) out.push("밈형은 내용 승인을 하지 않습니다 — 밈 보드에서 이어 가세요.");
  if (i.chain.state !== "ready") out.push(`${i.chain.label}${i.chain.reason ? ` — ${i.chain.reason}` : ""}`);
  if (i.dirty) out.push("저장하지 않은 수정이 있습니다 — 먼저 저장하세요.");
  for (const b of i.blockers) out.push(blockerText(b));
  if (i.score !== null && i.score < i.selectThreshold && !i.scoreException.trim()) {
    out.push(`편성 평가 ${i.score}점이 기준 ${i.selectThreshold}점 미만입니다 — 예외 사유를 적으세요.`);
  }
  if (i.formatFit !== null && i.formatFit < i.fitMin && !i.fitException.trim()) {
    out.push(`${i.pick?.format_intent === "card" ? "카드뉴스" : "영상"} 적합성이 ${i.fitMin}점 미만입니다 — 예외 사유를 적으세요.`);
  }
  // 카드뉴스는 로컬 렌더 0원이라 승인 금액을 받지 않는다(0065).
  if (i.pick?.format_intent !== "card" && (!(i.amountUsd > 0) || i.amountUsd > MAX_APPROVAL_USD)) {
    out.push(`승인 금액은 0보다 크고 $${MAX_APPROVAL_USD} 이하여야 합니다.`);
  }
  return out;
}

/** 근거 내용이 바뀌었나 — DB drinks_evidence_content_hash 와 같은 범위(주장별 확인·핵심 메시지·점수는 내용 변경이 아니다). 경고 문구용. */
export function evidenceContentChanged(
  before: { claims: readonly { claim_id: string; text: string }[]; selected: readonly string[] },
  after: { claims: readonly { claim_id: string; text: string }[]; selected: readonly string[] }
): boolean {
  const sel = (s: readonly string[]) => [...s].sort().join("|");
  if (sel(before.selected) !== sel(after.selected)) return true;
  const key = (cs: readonly { claim_id: string; text: string }[]) =>
    [...cs].sort((a, b) => a.claim_id.localeCompare(b.claim_id)).map((c) => `${c.claim_id}=${c.text}`).join("\n");
  return key(before.claims) !== key(after.claims);
}

/** 장면의 시각 주장 칸(기획 v2 §3-4) + 화면 계약 칸. 없으면 비어 있다 — 있는 것만 보여 준다. */
export const SCENE_DIRECTIVE_FIELDS: readonly { key: string; label: string }[] = [
  { key: "visual_claim_ko", label: "화면이 사실이라고 말하는 것" },
  { key: "allowed_simplification", label: "허용한 단순화" },
  { key: "forbidden_misreading", label: "오해하면 안 되는 것" },
  { key: "depiction_label", label: "화면 표기" },
  { key: "answers_ko", label: "이 장면이 답하는 질문" },
  { key: "staging_ko", label: "화면에서 일어나는 일" },
];

/**
 * 이 제작안을 만든 요청이 남긴 시각 주장표 → 장면 번호별 칸. DB 검증기가 이 칸을 제작안 본문에 보존하지 않아 요청 결과에 있다.
 * 사람이 고쳐 저장한 새 버전에는 표가 없다(빈 객체) — 없는 것을 있는 척하지 않는다.
 */
export function visualClaimsOf(
  requests: readonly { result_plan_revision_id: string | null; result?: Record<string, unknown> | null }[],
  planId: string | null | undefined,
): Record<number, Record<string, unknown>> {
  if (!planId) return {};
  const table = requests.find((r) => r.result_plan_revision_id === planId)?.result?.visual_claims;
  if (!Array.isArray(table)) return {};
  const out: Record<number, Record<string, unknown>> = {};
  for (const row of table) {
    const scene = (row as { scene?: unknown } | null)?.scene;
    if (typeof scene === "number") out[scene] = row as Record<string, unknown>;
  }
  return out;
}

export function sceneDirective(scene: Record<string, unknown>): { label: string; value: string }[] {
  return SCENE_DIRECTIVE_FIELDS.flatMap((f) => {
    const v = scene[f.key];
    return typeof v === "string" && v.trim() ? [{ label: f.label, value: v.trim() }] : [];
  });
}
