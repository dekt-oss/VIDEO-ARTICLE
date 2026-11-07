// 콘텐츠 스튜디오(2026-11-07, 0076) — 서버 상태(drinks_studio_status)에서 화면 단계와 문구를 정하는 순수 함수.
// ★ 진행 표시는 실제 상태에서만 계산한다. 완료율·남은 시간을 지어내지 않는다(목업의 타이머 진행률은 옮기지 않았다).
// ★ 값 import 없음(node --test 가 `@/` 별칭을 못 푼다).

export type StudioScreen = "collect" | "preparing" | "draft" | "versions" | "generating" | "result" | "blocked" | "choice";

export interface StudioRequest {
  request_id: string; kind: "evidence" | "plan"; status: string; step: string | null; format_intent: string | null;
  error_code: string | null; error_message: string | null; recovery_of: string | null; instruction: string | null;
  cancel_requested?: boolean; created_at: string; finished_at: string | null;
}
export interface StudioPage { position: number; role: string; heading: string; body: string | null; claim_ids: string[] }
export interface StudioPlan {
  plan_revision_id: string; format: "video" | "carousel"; version: number; plan_status: string; blocked: boolean; blocked_reason: string | null;
  current: boolean; plan_json: { pages?: StudioPage[]; reel?: { hook_title?: string; share_line?: string }; notes?: string | null };
  unverified_numbers: string[]; topic_review_id: string;
  jobs: { job_id: string; status: string; error_code: string | null; attempt_no: number; created_at: string; finished_at: string | null }[];
}
export interface StudioClaim {
  claim_id: string; text: string; claim_type: string; support_review?: string; limitations?: string;
  source_refs?: { snapshot_id: string; original_quote: string; quote_check?: string }[];
}
export interface StudioStatus {
  topic: { id: string; title: string; question: string; status: string; version: number };
  picks: { format_intent: string; approved_at: string | null; recommended_reason: string | null }[];
  active: StudioRequest | null;
  last: (StudioRequest & { factcheck?: Record<string, unknown> | null; excluded?: { claim_id: string; why: string; text: string }[] | null; has_unsaved?: boolean }) | null;
  recoveries_24h: number;
  limits: { max_recoveries_24h: number };
  review: { review_id: string; status: string; version: number; blank: boolean; core_claim_ids: string[] | null; core_takeaway: string | null;
    claims: StudioClaim[] | null; readiness: { blockers?: string[]; warnings?: string[] } | null } | null;
  plans: StudioPlan[];
  sources: { snapshot_id: string; title: string | null; publisher: string | null; url: string | null; role: string; rights_status: string | null }[];
}

/** 자동으로 다시 하는 실패(DB drinks_studio_recoverable 과 같은 목록 — studio.test.ts 가 SQL 파일과 대조). */
export const RECOVERABLE = ["draft_exists", "version_conflict", "lease_expired", "lease_lost", "worker_error", "transient_error",
  "factcheck_unavailable", "review_changed", "db_error"] as const;
const INSUFFICIENT = new Set(["evidence_insufficient", "script_check_failed", "no_core_claims", "evidence_not_usable"]);

/** 이 화면이 다루는 카드뉴스 초안(현재 버전). */
export function cardPlan(s: StudioStatus | null): StudioPlan | null {
  if (!s) return null;
  return s.plans.find((p) => p.format === "carousel" && p.current && !p.blocked) ?? s.plans.find((p) => p.format === "carousel" && p.plan_status === "approved") ?? null;
}

export interface Phase { screen: StudioScreen; reason?: string; code?: string }

export function studioPhase(s: StudioStatus | null): Phase {
  if (!s) return { screen: "collect" };
  if (s.active) return { screen: "preparing" };
  const plan = cardPlan(s);
  if (plan && plan.plan_status === "approved") {
    const live = plan.jobs.some((j) => j.status === "queued" || j.status === "running");
    return { screen: live ? "generating" : "result" };
  }
  if (plan && plan.plan_status === "draft") return { screen: "draft" };
  const last = s.last;
  if (!last) return { screen: "collect" };
  if (last.status === "canceled") return { screen: "collect", reason: "준비를 취소했어요." };
  if (last.status === "blocked" || INSUFFICIENT.has(last.error_code ?? "")) return { screen: "blocked", code: last.error_code ?? undefined };
  if (last.status === "failed") {
    if ((RECOVERABLE as readonly string[]).includes(last.error_code ?? "")) {
      return s.recoveries_24h >= s.limits.max_recoveries_24h
        ? { screen: "choice", code: "recovery_limit", reason: "자동 복구를 여러 번 했지만 끝내지 못했어요." }
        : { screen: "choice", code: "recoverable", reason: "일시적인 문제로 멈췄어요. 다시 시작하면 멈춘 곳부터 이어서 준비해요." };
    }
    return { screen: "choice", code: last.error_code ?? "failed", reason: failureText(last.error_code) };
  }
  return { screen: "collect" };
}

export function failureText(code: string | null | undefined): string {
  switch (code) {
    case "budget_exceeded": case "budget_missing": case "budget_unavailable": case "approval_expired": case "approval_closed":
      return "이번 주 AI 초안 한도를 모두 썼어요. 한도를 올리거나 다음 주에 이어서 만들 수 있어요.";
    case "draft_has_edits":
      return "예전 화면에서 직접 고친 근거가 있어 자동으로 덮어쓰지 않았어요. 기존 작업공간에서 이어 가세요.";
    case "canceled": return "준비를 취소했어요.";
    default: return "자동으로 다시 할 수 없는 문제로 멈췄어요.";
  }
}

/** 진행 문구 — 워커가 남긴 단계(step) 이름에서만 고른다. 모르는 단계는 일반 문구. */
export function progressText(r: StudioRequest | null): string {
  if (!r) return "준비하고 있어요.";
  if (r.cancel_requested) return "취소하고 있어요. 이미 쓴 비용 기록은 그대로 남아요.";
  if (r.status === "queued") return r.recovery_of ? "일시적인 오류를 자동으로 복구하고 있어요." : "작업 순서를 기다리고 있어요.";
  const step = r.step ?? "";
  if (r.recovery_of && (step === "started" || step === "start" || step === "reuse")) return "일시적인 오류를 자동으로 복구하고 있어요.";
  if (step === "reuse") return "이전에 확인한 자료를 다시 쓰고 있어요.";
  if (step.startsWith("sources") || step.startsWith("extract") || step === "link") return "자료를 확인하고 있어요.";
  if (step === "factcheck") return "사용할 내용을 정리하고 있어요.";
  if (step.startsWith("write") || step.startsWith("check")) return r.instruction ? "말씀하신 방향으로 다시 쓰고 있어요." : "초안을 다듬고 있어요.";
  if (step === "save" || step.endsWith("_saved")) return "초안을 저장하고 있어요.";
  return "준비하고 있어요.";
}

export type VersionId = "card" | "explainer" | "meme";
export interface VersionOption { id: VersionId; label: string; desc: string; enabled: boolean; why?: string; costText: string; costUsd: number | null; href?: string }

/** 고를 수 있는 버전. 끝까지 만들 수 없는 것은 고를 수 없게 보여 주고 이유를 단다(나중에 실패시키지 않는다). */
export function versionOptions(topicId: string, plan: StudioPlan | null): VersionOption[] {
  const pages = plan?.plan_json.pages?.length ?? null;
  return [
    { id: "card", label: "카드뉴스", desc: pages ? `넘겨 읽는 카드 ${pages}장 + 세로 릴스` : "넘겨 읽는 카드 + 세로 릴스",
      enabled: Boolean(plan), why: plan ? undefined : "카드뉴스 초안이 아직 없어요.", costText: "$0.00 · 유료 호출 없음(서버에서 조립)", costUsd: 0 },
    { id: "explainer", label: "설명형 영상", desc: "장면과 내레이션으로 설명하는 세로 영상", enabled: false,
      why: "그림·영상 구매와 장면 판정이 따로 있어 이 화면에서는 아직 한 번에 만들 수 없어요.", costText: "금액은 장면 수가 정해져야 알 수 있어요",
      costUsd: null, href: `/drinks/work/${topicId}?lane=explainer` },
    { id: "meme", label: "밈", desc: "핵심 한 줄을 공감 가는 짧은 영상으로", enabled: false,
      why: "밈은 밈 보드의 틀(원본 릴스)을 먼저 골라야 해서 이 화면에서는 아직 만들 수 없어요.", costText: "—", costUsd: null, href: "/drinks/memes" },
  ];
}

/** 선택한 버전의 합계. 모르는 금액이 하나라도 있으면 null(0 으로 쓰지 않는다). */
export function orderTotal(options: VersionOption[], picked: VersionId[]): number | null {
  let sum = 0;
  for (const id of picked) {
    const o = options.find((x) => x.id === id);
    if (!o || !o.enabled || o.costUsd === null) return null;
    sum += o.costUsd;
  }
  return sum;
}

/** 편집 칸 — 페이지 수·순서는 그대로, 글만. 표지 제목은 첫 페이지 제목이다. */
export interface DraftEdit { pages: { heading: string; body: string }[]; hook_title: string; share_line: string }
export function draftFromPlan(plan: StudioPlan): DraftEdit {
  return {
    pages: (plan.plan_json.pages ?? []).map((p) => ({ heading: p.heading ?? "", body: p.body ?? "" })),
    hook_title: plan.plan_json.reel?.hook_title ?? "",
    share_line: plan.plan_json.reel?.share_line ?? "",
  };
}
export function sameDraft(a: DraftEdit, b: DraftEdit): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
/** 빈 제목·빈 내용 검사(출처 페이지는 서버가 채우므로 제목만). 문제 없으면 null. */
export function draftProblem(d: DraftEdit, roles: string[]): string | null {
  if (!d.pages[0]?.heading.trim()) return "제목을 비워 둘 수 없어요.";
  for (let i = 0; i < d.pages.length; i++) {
    if (roles[i] === "source") continue;
    if (!d.pages[i].heading.trim()) return `${i + 1}장 제목이 비었어요.`;
    if (roles[i] !== "cover" && !d.pages[i].body.trim()) return `${i + 1}장 내용이 비었어요.`;
  }
  return null;
}
