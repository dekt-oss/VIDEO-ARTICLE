// 작업함 — ④ 초안 검수 · ⑤ 영상 지시서 목록을 하나로 합친 목록의 "지금 단계" 판정
// (2026-09-30 운영자 결정 2-1, UI/UX 리뷰 #3).
//
// 종전에는 같은 작업 화면으로 가는 목록이 세 곳(홈 카드 · ④ · ⑤)에 흩어져 있어, 한 편이 지금 어느
// 단계인지 보려면 목록을 오가야 했다. 여기서 편마다 **단계 하나**를 정하고, 작업함은 그것을 칩으로 거른다.
//
// 순수 모듈 — import 없음(node --test 로 직접 돈다). 테스트: lib/work/inbox.test.ts
// 보류(낙점 14일 · 초안 없음) 판정은 lib/work/backlog.ts 가 하고 결과만 `onHold` 로 받는다.

export type InboxStage =
  | "draft_error"        // 초안 생성 실패
  | "drafting"           // 초안 만드는 중(요청 대기·처리)
  | "draft_missing"      // 낙점했지만 초안 없음
  | "hold"               // 보류 — 낙점 뒤 14일 · 초안 없음
  | "draft_review"       // 초안은 있고 지시서가 아직 없음
  | "directive_outdated" // 지시서가 옛 엔진 — 재생성 권장
  | "directive_review"   // 지시서 검수(승인 전)
  | "render_failed"      // 렌더 실패
  | "rendering"          // 승인 뒤 렌더·업로드 진행 중
  | "upload_wait"        // 렌더 끝 — 확인·업로드 남음
  | "done";              // 유튜브 업로드까지 끝

export type RenderState = "failed" | "running" | "upload_wait" | "done" | null;

export interface InboxInput {
  hasDraft: boolean;
  /** 초안 요청 최신 상태 */
  requestStatus: string | null;
  onHold: boolean;
  /** 초안·지시서 검수에서 14일 넘게 멈춤(backlog.isStalled) — 검수 단계면 보류로 보낸다. */
  stalled?: boolean;
  /** 보고 있는 버전의 최신 지시서(없으면 null) */
  directive: { status: string; outdated: boolean } | null;
  /** 그 편의 최신 렌더 상태(없으면 null) */
  render: RenderState;
}

/** 사람이 검수해야 하는 단계 — 14일 넘게 멈추면 보류로 간다(결정 3-1 을 지시서까지, 2026-09-30). */
const REVIEW_STAGES: InboxStage[] = ["draft_review", "directive_review", "directive_outdated"];

export function inboxStage(i: InboxInput): InboxStage {
  const s = stageBeforeHold(i);
  return i.stalled && REVIEW_STAGES.includes(s) ? "hold" : s;
}

function stageBeforeHold(i: InboxInput): InboxStage {
  // 렌더가 있으면 그것이 가장 뒤 단계다.
  if (i.render === "failed") return "render_failed";
  if (i.render === "running") return "rendering";
  if (i.render === "upload_wait") return "upload_wait";
  if (i.render === "done") return "done";
  if (!i.hasDraft) {
    if (i.requestStatus === "queued" || i.requestStatus === "processing") return "drafting";
    if (i.requestStatus === "error") return "draft_error";
    return i.onHold ? "hold" : "draft_missing";
  }
  if (!i.directive) return i.requestStatus === "queued" || i.requestStatus === "processing" ? "drafting" : "draft_review";
  if (i.directive.status === "draft") return i.directive.outdated ? "directive_outdated" : "directive_review";
  if (i.directive.status === "failed") return "render_failed";
  return "rendering"; // approved · rendering · rendered(잡 없음) — 사람 손을 떠났다
}

export type InboxChip = "todo" | "draft_missing" | "directive" | "rendering" | "upload" | "done" | "hold" | "all";

export const INBOX_CHIPS: { key: InboxChip; label: string }[] = [
  { key: "todo", label: "할 것" },
  { key: "draft_missing", label: "초안 없음" },
  { key: "directive", label: "지시서 검수" },
  { key: "rendering", label: "렌더 중" },
  { key: "upload", label: "업로드 대기" },
  { key: "done", label: "완료" },
  { key: "hold", label: "보류" },
  { key: "all", label: "전체" },
];

export type Tone = "bad" | "warn" | "blue" | "ok" | "muted";

/** 단계별 표시 · 어느 칩에 드는지 · 사람이 할 일인지. */
export const STAGE_META: Record<InboxStage, { label: string; tone: Tone; chip: Exclude<InboxChip, "todo" | "all">; todo: boolean }> = {
  draft_error:        { label: "초안 오류",        tone: "bad",   chip: "draft_missing", todo: true },
  drafting:           { label: "초안 만드는 중",   tone: "muted", chip: "draft_missing", todo: false },
  draft_missing:      { label: "초안 없음",        tone: "muted", chip: "draft_missing", todo: true },
  hold:               { label: "보류",             tone: "muted", chip: "hold",          todo: false },
  draft_review:       { label: "초안 검수",        tone: "blue",  chip: "directive",     todo: true },
  directive_outdated: { label: "지시서 · 옛 엔진", tone: "bad",   chip: "directive",     todo: true },
  directive_review:   { label: "지시서 검수",      tone: "warn",  chip: "directive",     todo: true },
  render_failed:      { label: "렌더 실패",        tone: "bad",   chip: "rendering",     todo: true },
  rendering:          { label: "렌더 중",          tone: "muted", chip: "rendering",     todo: false },
  upload_wait:        { label: "업로드 대기",      tone: "ok",    chip: "upload",        todo: true },
  done:               { label: "완료",             tone: "ok",    chip: "done",          todo: false },
};

export function inChip(stage: InboxStage, chip: InboxChip): boolean {
  if (chip === "all") return true;
  if (chip === "todo") return STAGE_META[stage].todo;
  return STAGE_META[stage].chip === chip;
}

export function parseChip(v: string | string[] | undefined): InboxChip {
  const s = Array.isArray(v) ? v[0] : v;
  return INBOX_CHIPS.some((c) => c.key === s) ? (s as InboxChip) : "todo";
}

export function chipCounts(stages: InboxStage[]): Record<InboxChip, number> {
  const out = Object.fromEntries(INBOX_CHIPS.map((c) => [c.key, 0])) as Record<InboxChip, number>;
  for (const s of stages) for (const c of INBOX_CHIPS) if (inChip(s, c.key)) out[c.key] += 1;
  return out;
}

/** 렌더 잡 여럿 → 편 하나의 렌더 상태(가장 최근 잡 기준). 잡 모양은 renderQueue.QueueJob 과 같다. */
export function renderStateOf(
  jobs: { status: string; youtube_status?: string | null; created_at?: string | null; saved_at?: string | null }[],
): RenderState {
  const live = jobs.filter((j) => !j.saved_at);
  if (!live.length) return null;
  const j = [...live].sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))[0];
  if (j.status === "failed") return "failed";
  if (j.status === "qa_pending" || j.status === "degraded") return "upload_wait";
  if (j.status !== "done") return "running";
  if (j.youtube_status === "done") return "done";
  if (j.youtube_status === "queued" || j.youtube_status === "processing") return "running";
  return "upload_wait";
}
