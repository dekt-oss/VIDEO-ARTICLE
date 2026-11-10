// 설명형 제작 화면의 순수 계산 — 슬롯별 비용 누적, 다음에 누를 것(0067). 값 import 가 없어 node --test 로 돈다.

export type EpisodeState =
  | "plan_draft" | "directive_ready" | "approved" | "buying" | "assets_complete" | "rehearsal" | "rendered"
  | "auto_qa_pass" | "process_review_pass" | "quality_review_pass" | "ready_to_publish"
  | "blocked_assets" | "blocked_no_pass" | "blocked_budget" | "unknown_billed" | "auto_qa_fail" | "review_fail";

export const EPISODE_LABEL: Record<EpisodeState, string> = {
  plan_draft: "지시서 전", directive_ready: "지시서 나옴 · 결재 대기", approved: "결재됨 · 구매 대기", buying: "구매·검수 중", assets_complete: "클립 전부 선택됨",
  rehearsal: "조립 중", rendered: "조립됨", auto_qa_pass: "자동 검사 통과(품질 합격 아님)", process_review_pass: "과정 검수 통과", quality_review_pass: "품질 검수 통과",
  ready_to_publish: "게시 대기", blocked_assets: "멈춤: 클립 문제", blocked_no_pass: "멈춤: 후보 전부 불합격", blocked_budget: "멈춤: 결재 금액 부족",
  unknown_billed: "멈춤: 결과 모르는 시도", auto_qa_fail: "멈춤: 자동 검사 불합격", review_fail: "멈춤: 사람 검수 불합격",
};

export interface ExplainerAttempt {
  attempt_id: string; m: number; state: string; provider: string; provider_request_id: string | null; approval_id: string;
  billed_units: number | string | null; actual_usd: number | string | null; est_usd: number | string | null; error_code: string | null; closed_by: string | null; close_note: string | null;
}
export interface ExplainerCandidate {
  candidate_id: string; k: number; status: string; cost_usd: number | string; auto_verdict: "pass" | "fail" | null; human_verdict: "pass" | "fail" | null;
  auto_report: { pass?: boolean; blocks?: string[]; duration_ms?: number; min_src_ms?: number; width?: number; height?: number } | null;
  asset: { asset_id: string; storage_key: string; sha256: string; width: number | null; height: number | null; duration_ms: number | null; state: string } | null;
  attempts: ExplainerAttempt[]; url?: string | null; urlError?: string | null;
}
export interface ExplainerSlot {
  slot_id: string; n: number; role: "reality" | "mechanism"; status: string; min_src_ms: number; candidates_planned: number; boundary_in: string | null; boundary_out: string | null;
  image_usd: number | string; selection: { candidate_id: string; selected_by: string; reason: string; selected_at: string } | null; candidates: ExplainerCandidate[];
}
export interface DirectiveSlot {
  n: number; slot_id: string; role: "reality" | "mechanism"; narration: string; tts_ms: number; last_src_ms: number; min_src_ms: number; clip_sec: number; candidates_planned: number;
  boundary_in: string; boundary_out: string; continuity_ref: number | null; visual_prompt: string; image_prompt: string; image_model: string; image_est_usd: number; motion_prompt: string; clip_prompt: string; clip_model: string; clip_est_usd: number;
  claim_ids: string[]; visual_claim_ko: string; allowed_simplification: string; forbidden_misreading: string; depiction_label: string; overlays: string | null;
  /** 사진클레이만: 화면 자막 줄, 그림 속에 째리가 나오나 */
  lines?: string[]; mascot_in_scene?: boolean;
}
export interface Directive {
  provider: string; resolution: string; price_as_of: string; hook_text: string; hook_scene: number; playback_speed: number; raw_ms: number; final_ms: number; edit_cuts: number; slots: DirectiveSlot[]; warnings: string[];
  estimate: { images_usd: number; clips_usd: number; estimate_usd: number; reserve_usd: number; suggested_cap_usd: number }; unverified: string[];
  variant?: "clay"; voice?: { name: string; rate: string };
}

/** 설명형 만드는 방식(편의 provider). clay = 사진클레이(0079): 장면마다 점토 그림 1장, 클립 없음. */
export const CLAY_PROVIDER = "clay";
export type MakeMethod = "clay" | "omni";
export const MAKE_METHOD_LABEL: Record<MakeMethod, string> = { clay: "사진클레이", omni: "영상 클립" };

/** 이 편을 사는 데 결재가 허용해야 할 종류. DB(0079 drinks_explainer_request_buy)와 같은 규칙. */
export function neededKinds(provider: string | null | undefined): string[] {
  return provider === CLAY_PROVIDER ? ["image"] : ["image", "video"];
}

/** 지금 이 편에 쓸 수 있는 열린 결재. */
export function usableApproval<A extends Pick<ExplainerApproval, "status" | "expired" | "allowed_kinds">>(approvals: A[], provider: string | null | undefined): A | null {
  const need = neededKinds(provider);
  return approvals.find((a) => a.status === "open" && !a.expired && need.every((k) => a.allowed_kinds.includes(k))) ?? null;
}
export interface ExplainerEpisode {
  plan_revision_id: string; state: EpisodeState; provider: string; directive: Directive | null; order_hash: string | null; approval_id: string | null; buy_through_n: number | null;
  last_code: string | null; last_message: string | null; process_review: Record<string, unknown> | null; quality_review: Record<string, unknown> | null; version: number;
}
export interface ExplainerApproval {
  approval_id: string; stage: string; cap_usd: number | string; allowed_kinds: string[]; status: "open" | "closed"; expired: boolean; expires_at: string; remaining_usd: number | string;
  held_usd: number | string; spent_usd: number | string; order_hash: string | null;
}
export interface ExplainerStatus {
  is_explainer: boolean; approved_amount_usd: number | string | null; episode: ExplainerEpisode | null; slots: ExplainerSlot[]; approvals: ExplainerApproval[]; unknown_attempts: string[];
}

/** 한국 시각 "YYYY-MM-DD HH:mm". 서버와 브라우저가 같은 글자를 내야 한다 — 지역 설정에 기대면 클라이언트 컴포넌트에서 hydration 이 깨진다(실측). */
export function kstMinute(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(t)) return "-";
  return new Date(t + 9 * 3600 * 1000).toISOString().slice(0, 16).replace("T", " ");
}

export interface SlotCost { n: number; imageUsd: number; clipsUsd: number; totalUsd: number; cumulativeUsd: number; unknownHeldUsd: number }

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** 슬롯별 비용과 누적. 불합격 후보의 돈도 든다. 결과 모르는 시도는 금액에 넣지 않고 "가잡힌 금액"으로 따로 보여 준다. */
export function slotCosts(slots: ExplainerSlot[]): SlotCost[] {
  let cum = 0;
  return [...slots].sort((a, b) => a.n - b.n).map((s) => {
    const imageUsd = num(s.image_usd);
    const clipsUsd = s.candidates.reduce((acc, c) => acc + num(c.cost_usd), 0);
    const unknownHeldUsd = s.candidates.flatMap((c) => c.attempts).filter((a) => a.state === "unknown_billed").reduce((acc, a) => acc + num(a.est_usd), 0);
    const totalUsd = imageUsd + clipsUsd;
    cum += totalUsd;
    return { n: s.n, imageUsd, clipsUsd, totalUsd, cumulativeUsd: cum, unknownHeldUsd };
  });
}

/** 후보 판정 버튼을 보여도 되나: 파일이 저장됐고 자동 합격이고 아직 사람 판정 전이고 슬롯이 끝나지 않았다. */
export function canJudge(slot: ExplainerSlot, c: ExplainerCandidate): boolean {
  return slot.status !== "selected" && slot.status !== "no_pass" && c.status === "stored" && c.auto_verdict === "pass" && !c.human_verdict;
}

/** 후보를 고를 수 있나 — DB(0062·0067)와 같은 규칙: 슬롯이 사람 판정까지 끝났고, 자동+사람 합격인 후보만. "그나마 나은 쪽"은 없다. */
export function canSelect(slot: ExplainerSlot, c: ExplainerCandidate): boolean {
  return slot.status === "human_checked" && !slot.selection && c.status === "stored" && c.auto_verdict === "pass" && c.human_verdict === "pass";
}

export type NextStep = "request_plan" | "open_approval" | "request_buy" | "review_candidates" | "close_unknown" | "request_assemble" | "process_review" | "quality_review" | "output_review" | "none";

/** 지금 운영자가 할 일 하나. 화면의 안내일 뿐이고 막는 것은 DB 다. */
export function nextStep(s: ExplainerStatus): NextStep {
  const st = s.episode?.state;
  if (!st || st === "plan_draft") return "request_plan";
  if (st === "unknown_billed") return "close_unknown";
  if (st === "directive_ready" || st === "blocked_budget") {
    return usableApproval(s.approvals, s.episode?.provider) ? "request_buy" : "open_approval";
  }
  if (st === "approved") return "request_buy";
  if (st === "buying") {
    const judging = s.slots.some((sl) => sl.status !== "selected" && sl.status !== "no_pass" && sl.candidates.some((c) => c.status === "stored" && !sl.selection));
    return judging ? "review_candidates" : "request_buy";
  }
  if (st === "assets_complete" || st === "rehearsal" || st === "blocked_assets" || st === "auto_qa_fail" || st === "review_fail") return "request_assemble";
  if (st === "auto_qa_pass") return "process_review";
  if (st === "process_review_pass") return "quality_review";
  if (st === "quality_review_pass") return "output_review";
  return "none";
}

export const PROCESS_CHECKS: [string, string][] = [
  ["directive_matches_clips", "장면별 지시서 ↔ 시각 주장표 ↔ 산 클립이 맞다"],
  ["selection_reasons_ok", "후보 선택 이유가 적혀 있고 납득된다"],
  ["cost_matches_approval", "비용 합계가 결재 금액 안이고 원장과 맞다"],
];
export const QUALITY_CHECKS: [string, string][] = [
  ["stops_in_first_1_5s", "첫 1.5초에 멈추게 한다"],
  ["no_photo_like_scene", "사진처럼 보이는 장면이 0개다"],
  ["match_boundaries_connect", "이어지는 장면(match)이 정말 이어진다"],
  ["mechanism_explains_why", "도해가 '왜'를 소리 없이 보여 준다"],
  ["no_fake_text", "가짜 글자·깨짐이 0개다"],
  ["loop_natural", "루프가 자연스럽다"],
];
