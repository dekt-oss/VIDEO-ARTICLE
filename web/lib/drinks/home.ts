// 오늘 할 일(/drinks) 의 순수 집계(2026-11-05, docs/deviation-drinks-multi-format.md §3-5 G10).
//   요약 타일(판단 기다리는 작업 · 게시·확인 필요 — 소재가 아니라 작업 단위를 센다) · 이번 주 진행표(형식별 게시 완료) ·
//   막힘 목록(결재 없음·게시 계정 재인증·수집 크론 흔적 없음·결과 불명 보류) · [확인했음 — 나중에] 스누즈(표시 순서만 바꾼다).
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다(lib/drinks/home.test.ts).
import type { Decision, FormatIntent, Panel, WorkItem } from "@/lib/drinks/work/types";

/** 사람 판단을 기다리는 패널. 진행 중(busy)이면 세지 않는다. */
const APPROVE_PANELS: ReadonlySet<Panel> = new Set<Panel>(["evidence", "plan", "approve", "spend", "buy", "review"]);
const PUBLISH_PANELS: ReadonlySet<Panel> = new Set<Panel>(["publish", "post"]);
const PUBLISH_BLOCKS = new Set(["publish_unknown", "spend_unknown"]);

export interface HomeCounts { approve: number; publish: number }

/** 타일 2개. 작업 단위(소재 × 형식) 기준. 게시·확인 = 게시 패널이거나 결과 불명 차단이 걸린 것. */
export function homeCounts(decisions: readonly Decision[]): HomeCounts {
  let approve = 0, publish = 0;
  for (const d of decisions) {
    const unknown = d.blocks.some((b) => PUBLISH_BLOCKS.has(b.code));
    if (unknown || PUBLISH_PANELS.has(d.primary.panel)) publish++;
    else if (!d.primary.busy && APPROVE_PANELS.has(d.primary.panel)) approve++;
  }
  return { approve, publish };
}

// ── 이번 주 진행표 ──────────────────────────────────────────────────────────

/** 게시 완료로 치는 상태. 밈은 앱에서 직접 올린 posted_manual 도 완료다. */
const DONE_PUB = new Set(["published"]);
const DONE_MEME = new Set(["published", "posted_manual"]);

function seoulDate(ts: string): string {
  return new Date(Date.parse(ts) + 9 * 3_600_000).toISOString().slice(0, 10);
}

function inWeek(ts: string | null, weekMonday: string): boolean {
  if (!ts) return false;
  const d = ts.length === 10 ? ts : seoulDate(ts);
  const [y, m, dd] = weekMonday.split("-").map(Number);
  const end = new Date(Date.UTC(y, m - 1, dd + 6)).toISOString().slice(0, 10);
  return d >= weekMonday && d <= end;
}

export interface WeeklyRow { format: FormatIntent; done: number; inProgress: number; target: { min: number; max: number } }

/** 형식별: 이번 주 게시 완료 수(게시 시각 또는 갱신 시각이 그 주) · 아직 끝나지 않은 작업 수. */
export function weeklyProgress(
  items: readonly WorkItem[], weekMonday: string, targets: Record<FormatIntent, { min: number; max: number }>
): WeeklyRow[] {
  const formats: FormatIntent[] = ["explainer", "card", "meme"];
  return formats.map((format) => {
    let done = 0, inProgress = 0;
    for (const it of items) {
      if (it.format_intent !== format) continue;
      const posted = (it.pub_status && DONE_PUB.has(it.pub_status)) || (it.meme_status && DONE_MEME.has(it.meme_status));
      if (posted) {
        if (inWeek(it.pub_publish_at ?? it.updated_at, weekMonday)) done++;
      } else inProgress++;
    }
    return { format, done, inProgress, target: targets[format] };
  });
}

// ── 막힘 목록 ──────────────────────────────────────────────────────────────

export interface Blocker { code: string; text: string; href?: string }

export interface BlockerInput {
  /** 쓸 수 있는 개발 결재가 있는가(pickBudget). null = 못 읽음 */
  hasBudget: boolean | null;
  /** 게시 계정 중 지금 게시 못 하는 것(재인증 필요 등). null = 못 읽음 */
  accountsBlocked: { name: string; reason: string }[] | null;
  /** 최근 24시간 수집 실행 수·활성 수집원 수. null = 못 읽음 */
  runs: { active: number; total: number } | null;
  items: readonly Pick<WorkItem, "orphan_hold" | "unknown_billed">[];
}

export function homeBlockers(i: BlockerInput): Blocker[] {
  const out: Blocker[] = [];
  const orphan = i.items.filter((x) => x.orphan_hold).length;
  const unknown = i.items.filter((x) => x.unknown_billed).length;
  if (unknown > 0) out.push({ code: "unknown_billed", text: `돈이 나갔는지 모르는 작업 ${unknown}건 — 같은 요청을 다시 보내기 전에 공급자 내역을 확인하세요`, href: "/drinks/work?filter=publish" });
  if (orphan > 0) out.push({ code: "orphan_hold", text: `결과 불명으로 잡아 둔 금액(고아 보류) ${orphan}건 — 확인 뒤 닫아야 결재 잔액이 돌아옵니다`, href: "/drinks/work?filter=publish" });
  if (i.hasBudget === false) out.push({ code: "no_budget", text: "열린 개발 결재가 없습니다 — 초안(근거·대본)을 쓸 수 없습니다", href: "/drinks/review" });
  if (i.hasBudget === null) out.push({ code: "budget_unknown", text: "개발 결재 상태를 읽지 못했습니다(없는 것이 아니라 모름)" });
  if (i.accountsBlocked === null) out.push({ code: "accounts_unknown", text: "게시 계정 상태를 읽지 못했습니다(정상이 아니라 모름)" });
  else for (const a of i.accountsBlocked) out.push({ code: "account_blocked", text: `게시 계정 ${a.name}: ${a.reason}`, href: "/drinks/publish" });
  if (i.runs && i.runs.active > 0 && i.runs.total === 0) {
    out.push({ code: "cron_silent", text: "활성 수집원이 있는데 최근 24시간 실행 기록이 없습니다 — 수집 워크플로(크론)가 꺼졌는지 확인하세요", href: "/drinks/runs" });
  }
  if (i.runs === null) out.push({ code: "runs_unknown", text: "수집 상태를 읽지 못했습니다(0건이 아니라 조회 실패)" });
  return out;
}

// ── 스누즈(표시 순서만) ──────────────────────────────────────────────────────

export const SNOOZE_KEY = "drinks.home.snooze";
export const SNOOZE_MS = 24 * 3_600_000;

/** localStorage 값 → 아직 살아 있는 unit_id 집합. 깨진 값·지난 값은 버린다. 실행 차단을 풀지 않는다 — 카드 순서만 바꾼다. */
export function parseSnoozed(raw: string | null, nowMs: number): Set<string> {
  const out = new Set<string>();
  if (!raw) return out;
  try {
    const o = JSON.parse(raw) as unknown;
    if (!o || typeof o !== "object") return out;
    for (const [k, v] of Object.entries(o as Record<string, unknown>)) if (typeof v === "number" && v > nowMs) out.add(k);
  } catch { /* 깨진 값은 없는 것으로 */ }
  return out;
}

export function snoozeValue(raw: string | null, unitId: string, nowMs: number): string {
  const alive: Record<string, number> = {};
  for (const k of parseSnoozed(raw, nowMs)) {
    try { alive[k] = (JSON.parse(raw ?? "{}") as Record<string, number>)[k]; } catch { /* */ }
  }
  alive[unitId] = nowMs + SNOOZE_MS;
  return JSON.stringify(alive);
}

export type HomeState = "no_candidates_no_work" | "no_work" | "all_done" | "work";

/** 빈 상태 셋을 가른다: 후보도 소재도 없음 · 소재 없음(후보는 있음) · 전부 완료(할 일 카드 없음) · 할 일 있음. */
export function homeState(candidateTotal: number | null, itemCount: number, rankedCount: number): HomeState {
  if (itemCount === 0) return candidateTotal === 0 ? "no_candidates_no_work" : "no_work";
  return rankedCount === 0 ? "all_done" : "work";
}
