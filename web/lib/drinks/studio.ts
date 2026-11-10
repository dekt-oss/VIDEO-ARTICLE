// 콘텐츠 스튜디오(0076·0078) — 서버 상태에서 화면 단계와 문구를 정하는 순수 함수.
// 흐름: 소재 → 초안(글로 된 구성표 + 코멘트 재생성) → 작업 명세서 승인 → 제작 → 검수 → 등록. 근거는 뒤에서 자동 검사한다(docs/deviation-drinks-studio-flow.md).
// ★ 진행 표시는 실제 상태에서만 계산한다. 완료율·남은 시간을 지어내지 않는다.
// ★ 값 import 없음(node --test 가 `@/` 별칭을 못 푼다).

export type StudioScreen = "collect" | "preparing" | "draft" | "spec" | "generating" | "result" | "publish" | "blocked" | "choice";

export interface StudioRequest {
  request_id: string; kind: "evidence" | "plan"; status: string; step: string | null; format_intent: string | null;
  error_code: string | null; error_message: string | null; recovery_of: string | null; instruction: string | null;
  cancel_requested?: boolean; created_at: string; finished_at: string | null;
}
export interface StudioPage { position: number; role: string; heading: string; body: string | null; claim_ids: string[]; image_prompt?: string }
export interface StudioScene {
  position?: number; timing_sec?: number | null; visual_role?: string | null; narration?: string | null; staging_ko?: string | null; answers_ko?: string | null;
  explanation?: string | null; overlays?: unknown;
}
/** 사진형 카드 배경 사진 예상(0077 drinks_studio_card_estimate). 글자 카드는 photo=false·0원. */
export interface StudioEstimate { photo: boolean; images: number; bought: number; total_usd: number }
export interface StudioPlan {
  plan_revision_id: string; format: "video" | "carousel"; version: number; plan_status: string; blocked: boolean; blocked_reason: string | null;
  current: boolean; plan_json: { pages?: StudioPage[]; scenes?: StudioScene[]; reel?: { hook_title?: string; share_line?: string }; notes?: string | null; layout?: string; template_version?: string };
  estimate?: StudioEstimate;
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
export const INSUFFICIENT: ReadonlySet<string> = new Set(["evidence_insufficient", "script_check_failed", "no_core_claims", "evidence_not_usable"]);

export type StudioLane = "card" | "explainer";

/** 이 화면이 다루는 초안(현재 버전). 형식을 지정하지 않으면 카드뉴스 → 릴스 순으로 있는 것. */
export function activePlan(s: StudioStatus | null, lane?: StudioLane | null): StudioPlan | null {
  if (!s) return null;
  const of = (f: StudioPlan["format"]) => s.plans.find((p) => p.format === f && p.current && !p.blocked) ?? s.plans.find((p) => p.format === f && p.plan_status === "approved") ?? null;
  if (lane) return of(lane === "card" ? "carousel" : "video");
  return of("carousel") ?? of("video");
}

export interface Phase { screen: StudioScreen; reason?: string; code?: string }

/** 화면 단계를 정하는 데 필요한 제작 쪽 상태. */
export interface PhaseContext {
  lane?: StudioLane | null;
  /** 설명형 편의 상태(drink_explainer_episodes.state). 시작 전이면 null */
  episodeState?: string | null;
  /** 최신 파일 묶음의 검수 상태 */
  outputStatus?: string | null;
}

const EPISODE_SPEC = new Set(["plan_draft", "directive_ready", "blocked_budget"]);
const EPISODE_REVIEW = new Set(["auto_qa_pass", "process_review_pass", "quality_review_pass", "ready_to_publish"]);

export function studioPhase(s: StudioStatus | null, ctx: PhaseContext = {}): Phase {
  if (!s) return { screen: "collect" };
  if (s.active) return { screen: "preparing" };
  const plan = activePlan(s, ctx.lane);
  if (plan?.plan_status === "draft") return { screen: "draft" };
  if (plan?.plan_status === "approved") {
    if (ctx.outputStatus === "approved") return { screen: "publish" };
    if (plan.format === "carousel") {
      if (plan.jobs.length === 0) return { screen: "spec" };
      return { screen: plan.jobs.some((j) => j.status === "queued" || j.status === "running") ? "generating" : "result" };
    }
    const st = ctx.episodeState ?? null;
    if (!st || EPISODE_SPEC.has(st)) return { screen: "spec" };
    return { screen: EPISODE_REVIEW.has(st) ? "result" : "generating" };
  }
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
    case "provider_payment_required":
      return "초안 AI 계정 잔액이 없어 멈췄어요(DeepSeek·Gemini 모두). 충전한 뒤 다시 준비하면 이어서 만들어요.";
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
  if (step.startsWith("write") || step.startsWith("check")) return r.instruction ? "말씀하신 방향으로 다시 쓰고 있어요." : "초안을 쓰고 있어요. 보통 1~3분 걸려요.";
  if (step === "save" || step.endsWith("_saved")) return "초안을 저장하고 있어요.";
  return "준비하고 있어요.";
}

/** 사진형 카드인가(0077). 배경 사진은 쪽마다 사서(유료) 금액을 화면에 보이고, 그 클릭이 그 금액의 결재다. */
export function isPhotoPlan(plan: StudioPlan | null): boolean {
  return Boolean(plan && (plan.estimate?.photo || plan.plan_json.layout === "photo" || plan.plan_json.template_version === "card-photo-v1"));
}

export function cardCost(plan: StudioPlan | null): { usd: number | null; text: string } {
  if (!plan || !isPhotoPlan(plan)) return { usd: 0, text: "$0.00 · 유료 호출 없음(서버에서 조립)" };
  const e = plan.estimate;
  if (!e) return { usd: null, text: "배경 사진 금액을 불러오지 못했어요" };
  const reused = e.bought > 0 ? ` · ${e.bought}장은 이미 산 사진 재사용` : "";
  return { usd: e.total_usd, text: `$${e.total_usd.toFixed(2)} · 배경 사진 ${e.images}장(AI 생성, 유료)${reused}` };
}

/** ① 소재 화면: 소재마다 이미 시작한 유형(started)·초안이 있는 유형(drafts). 어느 소재든 유형을 고를 수 있다. */
export interface FormatProgress { topicId: string | null; started: string[]; drafts: string[] }
export type FormatChoice = "card" | "explainer" | "meme";
/** 한 번에 맡기는 소재 수. 소재 하나가 작업 2건(자료 확인 + 초안)이고 작업기 한 번 실행이 10건까지 처리한다. */
export const BATCH_MAX = 5;

/** 처음 고른 칸: 초안이 있는 유형 → 시작한 유형 → 카드뉴스. */
export function defaultFormat(p: FormatProgress | null): FormatChoice {
  const f = p?.drafts[0] ?? p?.started[0];
  return f === "explainer" || f === "card" ? f : "card";
}

/**
 * 고른 유형으로 무엇을 하나.
 * open=초안 열기 · prepare=스튜디오 준비(새 소재, 또는 이 유형 하나로 시작해 멈춘 소재 복구) · add=시작한 소재에 유형 더하기(근거는 공유) · meme=밈 보드.
 * ★ drinks_studio_prepare 는 이미 고른 유형이 있으면 요청한 유형을 따르지 않는다 — 그래서 더하기는 pick_topic 으로 간다.
 */
export function formatAction(p: FormatProgress, f: FormatChoice): "open" | "prepare" | "add" | "meme" {
  if (f === "meme") return "meme";
  if (p.drafts.includes(f)) return "open";
  const others = p.started.filter((x) => x !== f);
  return p.topicId && others.length > 0 ? "add" : "prepare";
}

/** 묶음으로 실제 만들 소재: 이 유형의 초안이 이미 있으면 빼고, 밈은 원본 릴스를 소재마다 골라야 해서 묶지 않는다. */
export function batchTargets<T extends FormatProgress>(list: T[], f: FormatChoice): T[] {
  return list.filter((i) => formatAction(i, f) === "prepare" || formatAction(i, f) === "add");
}

/** 초안 구성표 한 줄: 어떤 화면에 무엇을 보여 주고 무엇을 말하는가. */
export interface DraftRow { title: string; lines: { label: string; text: string }[] }

const PAGE_ROLE: Record<string, string> = { cover: "표지", explain: "설명", compare: "비교", checklist: "체크리스트", source: "출처" };
const SCENE_ROLE: Record<string, string> = { reality: "실사", mechanism: "3D 도해" };

/** 영상 화면 글자는 문자열·JSON 문자열·배열로 저장돼 있다. 화면에는 글자만 보인다. */
export function overlayTexts(v: unknown): string[] {
  let x = v;
  if (typeof v === "string") {
    try { x = JSON.parse(v); } catch { return v.trim() ? [v.trim()] : []; }
  }
  if (!Array.isArray(x)) return [];
  return x.flatMap((o) => (typeof o === "string" ? [o] : typeof (o as { text?: unknown })?.text === "string" ? [(o as { text: string }).text] : [])).filter((t) => t.trim());
}

/** "위스키 [통]이" → 글자와 금색 강조 낱말을 가른다. */
function splitAccent(heading: string): { text: string; accent: string | null } {
  return { text: heading.replace(/\[|\]/g, ""), accent: /\[([^\]]+)\]/.exec(heading)?.[1] ?? null };
}

export function draftRows(plan: StudioPlan): DraftRow[] {
  const photo = isPhotoPlan(plan);
  const line = (label: string, text: string | null | undefined) => (text?.trim() ? [{ label, text: text.trim() }] : []);
  if (plan.format === "video") {
    return (plan.plan_json.scenes ?? []).map((sc, i) => ({
      title: `${i + 1}번 장면${typeof sc.timing_sec === "number" ? ` · ${sc.timing_sec}초` : ""}${sc.visual_role ? ` · ${SCENE_ROLE[sc.visual_role] ?? sc.visual_role}` : ""}`,
      lines: [...line("화면", sc.staging_ko ?? sc.explanation), ...line("내레이션·자막", sc.narration), ...line("화면 글자", overlayTexts(sc.overlays).join(" / "))],
    }));
  }
  const reel = plan.plan_json.reel;
  const rows: DraftRow[] = (plan.plan_json.pages ?? []).map((pg, i) => {
    if (pg.role === "source") return { title: `${i + 1}장 · 출처`, lines: [{ label: "화면 글자", text: "사용한 출처 목록이 자동으로 들어가요." }] };
    const h = splitAccent(pg.heading ?? "");
    return {
      title: `${i + 1}장 · ${PAGE_ROLE[pg.role] ?? pg.role}`,
      lines: [...line("제목", h.text), ...line("본문", pg.body), ...line("이미지", pg.image_prompt),
        ...line("배치", photo ? `배경 사진 위에 제목·본문${h.accent ? ` · '${h.accent}'을 금색으로 강조` : ""}` : "글자 카드")],
    };
  });
  if (reel?.hook_title || reel?.share_line) rows.push({ title: "함께 나오는 세로 릴스", lines: [...line("첫 화면", reel.hook_title), ...line("마지막 화면", reel.share_line)] });
  return rows;
}

/** 게시 시각 기본값(datetime-local, 한국 시각): 지금부터 15분 뒤. 게시 가능 시간 밖이면 다음 시작 시각. 사람이 바꿀 수 있다. */
export function defaultPublishAt(nowMs: number, window: { start: string; end: string }): string {
  const kst = new Date(nowMs + 15 * 60_000 + 9 * 3_600_000).toISOString().slice(0, 16);
  const time = kst.slice(11);
  if (time >= window.start && time <= window.end) return kst;
  const base = time > window.end ? new Date(Date.parse(`${kst.slice(0, 10)}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10) : kst.slice(0, 10);
  return `${base}T${window.start}`;
}
