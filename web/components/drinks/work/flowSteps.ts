// 작업공간 오른쪽 "이 소재의 흐름" 칸의 단계 표시 — 순수 함수(2026-11-06, 승인 목업 docs/mockups/drinks/03·04·05).
// ★ 새 판단이 아니다. 결정 함수(web/lib/drinks/work/decision.ts)가 이미 고른 "지금 할 일" 칸(primarySection)과
//   레인의 고정 섹션 순서만으로 칠한다: 그 칸보다 위 = 끝남, 그 칸 = 지금, 아래 = 기다림.
//   지금 칸을 못 정했으면(결정 없음·확인 필요) 끝남/기다림을 지어내지 않고 전부 "모름"으로 둔다.
// 값 import 없음(node --test 로 돈다).
import type { Decision } from "../../../lib/drinks/work/types.ts";

export type FlowState = "done" | "now" | "blocked" | "busy" | "waiting" | "unknown";

export interface FlowStep {
  key: string;
  label: string;
  state: FlowState;
}

/** 게시까지 끝난 단계 코드(decision.ts DONE_STEPS 와 같은 뜻 — 성과 보기). */
const FINISHED = new Set(["S20", "S22"]);

export function flowSteps(
  sections: readonly { key: string; label: string }[],
  primarySection: string | null,
  decision: Pick<Decision, "blocks" | "primary"> | null,
): FlowStep[] {
  const idx = primarySection ? sections.findIndex((s) => s.key === primarySection) : -1;
  if (idx >= 0) {
    const nowState: FlowState = decision && decision.blocks.length > 0 ? "blocked" : decision?.primary.busy ? "busy" : "now";
    return sections.map((s, i) => ({ key: s.key, label: s.label, state: i < idx ? "done" : i === idx ? nowState : "waiting" }));
  }
  if (decision && FINISHED.has(decision.primary.code)) {
    const after = sections.findIndex((s) => s.key === "after");
    return sections.map((s, i) => ({ key: s.key, label: s.label, state: after >= 0 && i === after ? "now" : "done" }));
  }
  return sections.map((s) => ({ key: s.key, label: s.label, state: "unknown" }));
}

export const FLOW_STATE_LABEL: Record<FlowState, string> = {
  done: "끝남",
  now: "지금",
  blocked: "막힘",
  busy: "진행 중",
  waiting: "기다림",
  unknown: "모름",
};

/** 편성 주차(월요일 YYYY-MM-DD) → "11.02–11.08". 모양이 다르면 받은 값을 그대로. */
export function weekRangeLabel(week: string | null | undefined): string | null {
  if (!week) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(week);
  if (!m) return week;
  const start = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  if (!Number.isFinite(start)) return week;
  const end = new Date(start + 6 * 86400_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${m[2]}.${m[3]}–${pad(end.getUTCMonth() + 1)}.${pad(end.getUTCDate())}`;
}
