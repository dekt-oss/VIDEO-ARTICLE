// 주류 작업 단위의 **다음 행동** — 순수 함수(2026-11-05). 계약: docs/deviation-drinks-multi-format.md §3-4,
// 표: docs/기획_작업명세서_주류대시보드_동선개편_v2_2026-11-04.md §7(B1~B8 · S1~S24 · 홈 우선순위).
//
// 왜 순수 함수인가: 논문 공장 `web/lib/work/decision.ts` 와 같은 이유다 — "지금 눌러야 하는 버튼 하나"가 JSX 에
// 흩어지면 상태 조합이 늘 때마다 버튼이 둘 뜨거나 하나도 안 뜬다. 여기서 표로 정하고 `decision.test.ts` 가 모든 줄을 못박는다.
//
// 네 계층: ① 대상 식별(실패 → needs_review, **초안 생성으로 떨어지지 않는다**) ② 차단 B1~B8(그 작업 단위에만)
//          ③ 형식별 단계 S1~S24 ④ 홈 우선순위 rankForHome.
// ★ 서버가 거부할 버튼을 만들지 않는다: `action` 은 **지금 이 행의 값만으로 서버가 받는 호출**에만 채운다
//   (submit·schedule 은 expected_version 만 필요 / request_render·explainer_request_plan·assemble 은 0원·멱등).
//   승인(approve)은 화면이 보여 준 지문(expected_digest)을 그대로 돌려줘야 하므로 action 은 null, panel 'publish'.
// ★ 값 import 는 같은 폴더·형제 모듈의 상대 경로만(node --test 가 `@/` 별칭을 못 푼다).
import { canJudge, canSelect, nextStep, type ExplainerStatus } from "../explainerQueue.ts";
import { PUBLISH_WINDOW, publishWindowProblem } from "../publishWindow.ts";
import { FORMAT_SHORT, workHref, type Block, type BlockCode, type Decision, type FormatIntent, type Panel, type Primary, type WorkItem } from "./types.ts";

const FORMATS: readonly FormatIntent[] = ["explainer", "card", "meme"];
const TOPIC_CLOSED = new Set(["on_hold", "rejected", "duplicate"]);
const DIGEST_PAUSE = new Set(["digest_changed", "meme_digest_changed"]);
/** 표 §7-4 6번 — 사람이 판정·승인하는 단계. 홈에서는 오래 기다린 것부터. */
export const JUDGMENT_STEPS: ReadonlySet<string> = new Set(["S4", "S9", "S10", "S12", "S13", "S14", "S17", "S18"]);
const DONE_STEPS = new Set(["S20", "S22"]);

type Action = { name: string; payload: Record<string, unknown> };
const prim = (code: string, label: string, panel: Panel, extra: Partial<Primary> = {}): Primary => ({ code, label, panel, action: null, ...extra });
const busy = (code: string, label: string, panel: Panel): Primary => prim(code, label, panel, { busy: true });

/** 식별 실패·알 수 없는 상태. 사유를 라벨에 남기고 상태 덤프(작업공간)로 보낸다. */
function needsReview(item: WorkItem, why: string): Primary {
  return prim("needs_review", `확인 필요: ${why}`, "none", { href: safeHref(item) });
}
function safeHref(item: WorkItem, panel?: Panel): string | undefined {
  try { return workHref(item, panel); } catch { return undefined; }
}

// ── ① 대상 식별 ──────────────────────────────────────────────────────────────
function identify(item: WorkItem): string | null {
  if (!FORMATS.includes(item.format_intent)) return `형식 의도가 없거나 모릅니다(${String(item.format_intent)})`;
  if (item.source === "card") {
    if (item.format_intent !== "meme") return `카드 소유 작업은 밈만 됩니다(${item.format_intent})`;
    if (!item.meme_draft_id) return "카드 밈 제작안 id 가 없습니다";
  } else if (item.source === "topic") {
    if (!item.topic_id) return "소재 id 가 없습니다";
  } else {
    return `소유자를 모릅니다(${String(item.source)})`;
  }
  // 제작안 형식 불일치: 설명형은 video 만. 카드는 carousel(카드뉴스)·video(카드 릴스 0065) 둘 다 있다.
  if (item.format_intent === "explainer" && item.plan_revision_id && item.plan_format && item.plan_format !== "video") return `설명형인데 제작안이 ${item.plan_format} 입니다`;
  if (item.format_intent === "card" && item.plan_revision_id && item.plan_format && item.plan_format !== "carousel" && item.plan_format !== "video") return `카드인데 제작안이 ${item.plan_format} 입니다`;
  return null;
}

// ── ② 차단 B1~B8 (순서 고정) ───────────────────────────────────────────────────
const BLOCK_PRIMARY: Record<BlockCode, { code: string; label: string; panel: Panel }> = {
  publish_unknown: { code: "B1", label: "게시 결과 대조", panel: "publish" },
  spend_unknown: { code: "B2", label: "결과 불명 닫기", panel: "spend" },
  evidence_invalid: { code: "B3", label: "근거 재확인 → 새 버전", panel: "evidence" },
  digest_mismatch: { code: "B4", label: "새로 불러와 다시 승인", panel: "publish" },
  publish_blocked: { code: "B5", label: "게시 문제 보기", panel: "publish" },
  budget_blocked: { code: "B6", label: "결재 보충/새 결재", panel: "spend" },
  no_pass: { code: "B7", label: "계획 바꾸기", panel: "plan" },
  develop_blocked: { code: "B8", label: "막힌 이유 → 다시 요청", panel: "evidence" },
};

function findBlocks(item: WorkItem): Block[] {
  const out: Block[] = [];
  const add = (code: BlockCode, message: string) => out.push({ code, message, href: safeHref(item, BLOCK_PRIMARY[code].panel) });
  if (item.pub_status === "unknown") add("publish_unknown", "게시됐는지 모르는 게시 요청이 있습니다 — 대조 전에는 다시 올리지 않습니다");
  if (item.unknown_billed || item.orphan_hold || item.explainer_state === "unknown_billed") add("spend_unknown", "돈이 나갔는지 모르는 시도(또는 고아 가잡기)가 있습니다 — 닫기 전에는 더 사지 않습니다");
  if (item.review_valid === false) add("evidence_invalid", "근거가 철회·만료됐거나 필수 조건을 다시 못 채웁니다");
  else if (item.plan_blocked === true) add("evidence_invalid", "제작안이 근거 철회로 차단됐습니다");
  else if (item.output_review_id && item.output_usable === false) add("evidence_invalid", "산출물을 지금 쓸 수 없습니다(검수 차단)");
  const digest = !!item.pub_pause_code && DIGEST_PAUSE.has(item.pub_pause_code);
  if (digest) add("digest_mismatch", "승인 지문이 바뀌었습니다 — 새로 불러와 다시 승인해야 합니다");
  if ((item.pub_status === "paused" || item.pub_status === "failed") && !digest) add("publish_blocked", `게시 요청이 ${item.pub_status === "paused" ? "멈춤" : "실패"}(${item.pub_pause_code ?? "사유 없음"}) 상태입니다`);
  if (item.explainer_state === "blocked_budget") add("budget_blocked", "결재 금액이 부족하거나 닫혀 있습니다(아직 사지 않았습니다)");
  if (item.explainer_state === "blocked_no_pass") add("no_pass", "합격 후보가 없습니다 — 계획을 바꿔야 합니다");
  if (item.develop_status === "blocked" || item.develop_status === "failed") add("develop_blocked", `개발 요청(${item.develop_kind ?? "?"})이 ${item.develop_status}: ${item.develop_error_code ?? "사유 없음"}`);
  return out;
}

// ── ③ 형식별 단계 ──────────────────────────────────────────────────────────────
/** 게시 요청 단계(세 형식 공용, S16~S20·S23). 없으면 null. */
function publicationStep(item: WorkItem): Primary | null {
  const s = item.pub_status;
  if (!s || !item.pub_request_id) return null;
  const owner = { request_id: item.pub_request_id, expected_version: item.pub_version };
  const canPrefill = typeof item.pub_version === "number";
  switch (s) {
    case "draft": return prim("S16", "승인 요청", "publish", { action: canPrefill ? { name: "publication_action", payload: { ...owner, action: "submit" } } : null });
    case "awaiting_approval": return prim("S17", "승인", "publish"); // 지문은 화면이 보여 주고 그대로 돌려준다 → action null
    case "approved": return prim("S18", "예약", "publish", { action: canPrefill ? { name: "publication_action", payload: { ...owner, action: "schedule" } } : null });
    case "scheduled": return busy("S19", "예약됨(취소만)", "publish");
    case "publishing": return busy("S19", "게시 중(취소 요청만)", "publish");
    case "published": return prim("S20", "성과 보기", "none", { href: "/drinks/analytics" });
    case "canceled": return prim("S23", "다시 열기", "publish");
    default: return null; // unknown/paused/failed 는 ② 에서 잡혔다
  }
}

function developStep(item: WorkItem): Primary | null {
  if (item.develop_status === "queued" || item.develop_status === "running") return busy("S2", "만드는 중…", item.develop_kind === "plan" ? "plan" : "evidence");
  if (item.develop_kind === "evidence" && item.develop_status === "succeeded" && !item.plan_revision_id) return busy("S3", "만드는 중…(대본 이어 만들기)", "plan");
  return null;
}

function explainerStep(item: WorkItem, ex: ExplainerStatus | null | undefined): Primary {
  const dev = developStep(item);
  if (dev) return dev;
  if (!item.plan_revision_id) {
    if (!item.develop_request_id && !item.review_id) return prim("S1", "초안 만들기", "evidence");
    if (item.develop_status === "succeeded" || item.develop_status === "canceled" || item.review_id) return prim("S1", "초안 만들기(대본)", "plan");
    return needsReview(item, `제작안 없이 개발 상태 ${item.develop_status}`);
  }
  if (item.plan_status === "draft" || item.plan_status === "in_review") return prim("S4", "승인", "approve");
  if (item.plan_status === "changes_requested") return prim("S4", "새 제작안 뒤 승인", "plan");
  if (item.plan_status !== "approved") return needsReview(item, `제작안 상태 ${item.plan_status ?? "없음"}`);
  const planId = item.plan_revision_id;
  const step = ex ? nextStep(ex) : null;
  if (ex && step) {
    switch (step) {
      case "request_plan": return prim("S5", "장면별 지시서 만들기 (0원)", "produce", { action: { name: "explainer_request_plan", payload: { plan_revision_id: planId } } });
      case "open_approval": {
        const n = ex.episode?.directive?.estimate.suggested_cap_usd;
        return prim("S5", `결재 열기${Number.isFinite(n) ? ` $${Number(n).toFixed(2)}` : ""}`, "spend");
      }
      case "request_buy": {
        if (ex.episode?.state === "buying") return busy("S8", "구매 중…", "buy");
        const open = ex.approvals.find((a) => a.status === "open" && !a.expired && a.allowed_kinds.includes("image") && a.allowed_kinds.includes("video"));
        return prim("S6", "구매 요청", "buy", { action: open ? { name: "explainer_request_buy", payload: { plan_revision_id: planId, spend_approval_id: open.approval_id } } : null });
      }
      case "review_candidates": {
        const selectable = ex.slots.some((sl) => sl.candidates.some((c) => canSelect(sl, c)));
        if (selectable) return prim("S10", "이 장면으로", "produce");
        const judgeable = ex.slots.some((sl) => sl.candidates.some((c) => canJudge(sl, c)));
        if (judgeable) return prim("S9", "후보 판정하기", "produce");
        return busy("S8", "구매·검수 중…", "produce"); // 후보가 저장됐지만 자동 판정 전
      }
      case "close_unknown": return prim("B2", BLOCK_PRIMARY.spend_unknown.label, "spend"); // ② 가 놓친 경우의 안전망
      case "request_assemble": return prim("S11", "조립 요청 (0원)", "produce", { action: { name: "explainer_request_assemble", payload: { plan_revision_id: planId } } });
      case "process_review": return prim("S12", "과정 검수", "review");
      case "quality_review": return prim("S13", "품질 검수", "review");
      case "output_review": return prim("S14", "산출물 승인", "review");
      case "none": break;
    }
  }
  // 상태 문자열만으로(설명형 상세가 없을 때, 또는 nextStep 이 none 일 때).
  switch (item.explainer_state) {
    case null: case "plan_draft": return prim("S5", "장면별 지시서 만들기 (0원)", "produce", { action: { name: "explainer_request_plan", payload: { plan_revision_id: planId } } });
    case "directive_ready": return prim("S5", "결재 열기", "spend");
    case "approved": return prim("S6", "구매 요청", "buy");
    case "buying": return ex ? busy("S8", "구매 중…", "buy") : prim("S8", "구매·검수 중 — 확인", "produce");
    case "assets_complete": case "rehearsal": case "blocked_assets": case "auto_qa_fail": case "review_fail":
      return prim("S11", "조립 요청 (0원)", "produce", { action: { name: "explainer_request_assemble", payload: { plan_revision_id: planId } } });
    case "rendered": return busy("S8", "조립됨 · 자동 검사 중…", "produce");
    case "auto_qa_pass": return prim("S12", "과정 검수", "review");
    case "process_review_pass": return prim("S13", "품질 검수", "review");
    case "quality_review_pass": return prim("S14", "산출물 승인", "review");
    case "ready_to_publish": return prim("S15", "발행안 만들기", "publish");
    default: return needsReview(item, `설명형 상태 ${item.explainer_state}`);
  }
}

function cardStep(item: WorkItem): Primary {
  const dev = developStep(item);
  if (dev) return dev;
  if (!item.plan_revision_id) {
    if (!item.develop_request_id && !item.review_id) return prim("S1", "초안 만들기", "evidence");
    if (item.develop_status === "succeeded" || item.develop_status === "canceled" || item.review_id) return prim("S1", "초안 만들기(대본)", "plan");
    return needsReview(item, `제작안 없이 개발 상태 ${item.develop_status}`);
  }
  if (item.plan_status === "draft" || item.plan_status === "in_review") return prim("S4", "승인", "approve");
  if (item.plan_status === "changes_requested") return prim("S4", "새 제작안 뒤 승인", "plan");
  if (item.plan_status !== "approved") return needsReview(item, `제작안 상태 ${item.plan_status ?? "없음"}`);
  const render = (label: string, retryOf?: string | null): Primary =>
    prim("S7", label, "produce", { action: { name: "request_render", payload: { plan_revision_id: item.plan_revision_id, ...(retryOf ? { retry_of: retryOf } : {}) } } });
  if (!item.job_id) return render("제작 시작 (로컬·무료)");
  switch (item.job_status) {
    case "queued": case "running": return busy("S8", "제작 중…", "produce");
    case "failed": case "canceled": return render(`다시 제작(${item.job_status === "failed" ? "실패" : "취소"} 뒤)`, item.job_id);
    case "succeeded": break;
    default: return needsReview(item, `제작 작업 상태 ${item.job_status ?? "없음"}`);
  }
  switch (item.output_review_status) {
    case null: case "pending": return prim("S14", "산출물 승인", "review");
    case "approved": return prim("S15", "발행안 만들기", "publish");
    case "changes_requested": return render("다시 제작(검수 수정 요청)", item.job_id);
    default: return needsReview(item, `산출물 검수 상태 ${item.output_review_status}`); // blocked 는 ② B3
  }
}

function memeStep(item: WorkItem): Primary {
  if (!item.meme_draft_id) {
    if (item.develop_status === "queued" || item.develop_status === "running") return busy("S2", "만드는 중…", "meme");
    return prim("S1", "글 초안 요청 (결재 필요)", "meme");
  }
  switch (item.meme_status) {
    case "text_requested": case "text_running": return busy("S2", "글 만드는 중…", "meme");
    case "draft": return prim("S4", "승인", "meme");
    case "approved": return busy("S8", "렌더 대기 중…", "meme");
    case "rendering": return busy("S8", "렌더 중…", "meme");
    case "publish_waiting": return prim("S15", "발행안 만들기", "publish");
    case "manual_audio": return prim("S21", "앱에서 붙이기 → 게시했음 기록", "post", { href: safeHref(item, "post") });
    case "posted_manual": return prim("S22", "성과 보기/URL", "none", { href: item.meme_external_url ?? "/drinks/analytics" });
    case "published": return prim("S20", "성과 보기", "none", { href: "/drinks/analytics" });
    case "stopped": case "failed": case "rejected": return prim("S23", "다시 열기", "meme");
    default: return needsReview(item, `밈 상태 ${item.meme_status ?? "없음"}`);
  }
}

// ── 경고(막지 않는다) ─────────────────────────────────────────────────────────
/** ISO 시각 → 한국 시각 "YYYY-MM-DDTHH:mm"(publishWindowProblem 입력 모양). */
function kstLocal(iso: string): string | null {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  return new Date(t + 9 * 3600 * 1000).toISOString().slice(0, 16);
}

function warnings(item: WorkItem, primary: Primary, now: Date): string[] {
  const out: string[] = [];
  const pubOpen = !!item.pub_status && !["published", "canceled"].includes(item.pub_status);
  if (pubOpen && item.pub_publish_at) {
    const local = kstLocal(item.pub_publish_at);
    const problem = local ? publishWindowProblem(local) : null;
    if (problem) out.push(`게시 시각 ${local!.replace("T", " ")}(KST) 가 창(${PUBLISH_WINDOW.start}~${PUBLISH_WINDOW.end}) 밖입니다 — 예약이 늦어 멈춥니다`);
  }
  if (item.editorial_week && !DONE_STEPS.has(primary.code)) {
    const monday = Date.parse(`${item.editorial_week}T00:00:00+09:00`);
    if (Number.isFinite(monday) && monday + 7 * 86400_000 <= now.getTime()) out.push(`편성 주차 ${item.editorial_week} 가 지났습니다 — 주차를 옮기거나 그대로 올릴지 정하세요`);
  }
  return out;
}

// ── 본체 ───────────────────────────────────────────────────────────────────────
export function decide(item: WorkItem, explainer?: ExplainerStatus | null, now: Date = new Date()): Decision {
  const lane: FormatIntent = FORMATS.includes(item.format_intent) ? item.format_intent : "explainer";
  const base = { unitId: item.unit_id, lane };
  const why = identify(item);
  if (why) return { ...base, blocks: [], primary: needsReview(item, why), warnings: [] };

  const blocks = findBlocks(item);
  let primary: Primary;
  if (blocks.length > 0) {
    const b = BLOCK_PRIMARY[blocks[0].code];
    primary = prim(b.code, b.label, b.panel, { href: blocks[0].href });
  } else if (item.source === "topic" && item.topic_status && TOPIC_CLOSED.has(item.topic_status)) {
    primary = prim("S23", "다시 열기", "none", { href: safeHref(item) });
  } else {
    primary = publicationStep(item)
      ?? (lane === "explainer" ? explainerStep(item, explainer) : lane === "card" ? cardStep(item) : memeStep(item));
  }
  if (!primary.href) primary.href = safeHref(item, primary.panel);
  return { ...base, blocks, primary, warnings: warnings(item, primary, now) };
}

// ── ④ 홈 우선순위 ─────────────────────────────────────────────────────────────
/** 급: 0 B1·B2 / 1 B5 / 2 B3·B4 / 3 B7·B8·needs_review / 4 B6 / 5 판정·승인 단계 / 6 그 밖 / 7 끝난 것. */
export function homeTier(d: Decision): number {
  const c = d.primary.code;
  if (c === "B1" || c === "B2") return 0;
  if (c === "B5") return 1;
  if (c === "B3" || c === "B4") return 2;
  if (c === "B7" || c === "B8" || c === "needs_review") return 3;
  if (c === "B6") return 4;
  if (JUDGMENT_STEPS.has(c)) return 5;
  if (DONE_STEPS.has(c)) return 7;
  return 6;
}

/**
 * 홈 정렬(§7-4). `snoozed` = "확인했음 — 나중에" 로 미룬 것(unit_id 또는 snoozeKey 값, UI 가 localStorage 에 둔다) —
 * 같은 급 **안에서** 뒤로 간다. 목록에서 빠지지 않고 급을 넘지 않는다(실행 차단은 그대로).
 * `updatedAt`(unit_id → updated_at)이 있으면 판정 급(5)은 오래 기다린 것부터; 없으면 입력 순서를 지킨다.
 */
export function rankForHome(decisions: Decision[], snoozed: ReadonlySet<string> = new Set(), updatedAt?: ReadonlyMap<string, string | null>): Decision[] {
  const age = (d: Decision): number => {
    const t = Date.parse(updatedAt?.get(d.unitId) ?? "");
    return Number.isFinite(t) ? t : Number.POSITIVE_INFINITY;
  };
  const isSnoozed = (d: Decision) => snoozed.has(d.unitId) || snoozed.has(snoozeKey(d));
  return decisions
    .map((d, i) => ({ d, i, tier: homeTier(d), snz: isSnoozed(d) ? 1 : 0 }))
    .sort((a, b) => a.tier - b.tier || a.snz - b.snz || (a.tier === 5 ? age(a.d) - age(b.d) : 0) || a.i - b.i)
    .map((x) => x.d);
}

/** 미루기 열쇠(UI 가 localStorage 에 둔다). 단계 코드가 바뀌면 열쇠도 바뀌어 미룸이 저절로 풀린다. */
export function snoozeKey(d: Pick<Decision, "unitId" | "primary">): string {
  return `${d.unitId}#${d.primary.code}`;
}

/** 홈 카드 한 줄 제목용: "릴스 · 승인". */
export function primaryTitle(d: Decision): string {
  return `${FORMAT_SHORT[d.lane]} · ${d.primary.label}`;
}
