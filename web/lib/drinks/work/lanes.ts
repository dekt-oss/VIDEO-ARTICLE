// 작업공간(/drinks/work/[topicId]?lane=) 의 순수 계산 — 레인 순서, 레인별 단계 섹션, 어느 섹션을 펼칠지, 미저장 입력 보관 키.
// 값 import 가 없어 node --test 로 돈다. 계약: docs/deviation-drinks-multi-format.md §3-5, 기획 v2 §6-3.
//
// ★ ?lane= 이 상태의 정본이다. 섹션은 레인마다 위에서 아래로 고정 순서이고, "지금 할 일"(결정 함수의 panel)이
//   가리키는 섹션 하나만 펼친다. ?panel= 이 있으면 그것이 이긴다(옛 탭 주소에서 넘어온 사람이 보던 칸을 그대로 연다).
import type { FormatIntent, Panel } from "./types";

export type SectionKey =
  | "draft" | "evidence" | "approve" | "produce" | "output" | "publish" | "post" | "after" | "meme";

export interface LaneSection {
  key: SectionKey;
  label: string;
  /** 결정 함수의 panel 중 이 섹션이 받는 것. 'none' 은 어느 섹션도 받지 않는다. */
  panels: readonly Panel[];
}

/** 레인 표시 순서 — 선택 모달·형식 카드와 같다. */
export const LANE_ORDER: readonly FormatIntent[] = ["explainer", "card", "meme"];

export function orderLanes(formats: Iterable<FormatIntent>): FormatIntent[] {
  const set = new Set(formats);
  return LANE_ORDER.filter((f) => set.has(f));
}

export function isFormatIntent(v: unknown): v is FormatIntent {
  return v === "explainer" || v === "card" || v === "meme";
}

const COMMON_TAIL: LaneSection[] = [
  { key: "publish", label: "발행안", panels: ["publish"] },
  { key: "post", label: "게시 승인", panels: ["post"] },
  { key: "after", label: "게시 뒤", panels: [] },
];

export const LANE_SECTIONS: Record<FormatIntent, readonly LaneSection[]> = {
  explainer: [
    { key: "draft", label: "초안", panels: ["plan"] },
    { key: "evidence", label: "근거", panels: ["evidence"] },
    { key: "approve", label: "대본·내용 승인", panels: ["approve"] },
    // 결재 / 구매 / 후보 판정 / 선택 / 조립 / 과정 검수 / 품질 검수 — 설명형 제작 한 덩어리(ExplainerProduction 그대로)
    { key: "produce", label: "결재·구매·판정·조립·검수", panels: ["spend", "buy", "produce"] },
    { key: "output", label: "산출물 승인", panels: ["review"] },
    ...COMMON_TAIL,
  ],
  card: [
    { key: "draft", label: "초안", panels: ["plan"] },
    { key: "evidence", label: "근거", panels: ["evidence"] },
    { key: "approve", label: "페이지 기획·내용 승인", panels: ["approve"] },
    { key: "produce", label: "제작", panels: ["spend", "buy", "produce"] },
    { key: "output", label: "산출물 승인", panels: ["review"] },
    ...COMMON_TAIL,
  ],
  meme: [
    // 글 요청(결재 안에서만)·차단 사유·승인·렌더·완성본 — 밈 제작안 한 덩어리(MemeDraftForm/Actions 그대로)
    { key: "meme", label: "글·제작안", panels: ["meme", "plan", "approve", "spend", "buy", "produce", "review", "evidence"] },
    ...COMMON_TAIL,
  ],
};

export function laneSections(lane: FormatIntent): readonly LaneSection[] {
  return LANE_SECTIONS[lane];
}

export function sectionForPanel(lane: FormatIntent, panel: Panel | null | undefined): SectionKey | null {
  if (!panel || panel === "none") return null;
  return LANE_SECTIONS[lane].find((s) => s.panels.includes(panel))?.key ?? null;
}

export function isSectionKey(lane: FormatIntent, v: unknown): v is SectionKey {
  return typeof v === "string" && LANE_SECTIONS[lane].some((s) => s.key === v);
}

/**
 * 결정 함수가 가리키는 섹션. decision.ts 는 발행안 작성(S15)과 승인 요청·승인·예약(S16~S19)을 모두 panel 'publish' 로 가리킨다 —
 * 게시 요청이 이미 있으면 그 단계는 '게시 승인' 칸(RequestActions)에 있으므로 거기를 가리킨다.
 */
export function primarySectionOf(lane: FormatIntent, primaryPanel: Panel | null | undefined, hasLivePublication: boolean): SectionKey | null {
  if (primaryPanel === "publish" && hasLivePublication) return sectionForPanel(lane, "post");
  return sectionForPanel(lane, primaryPanel);
}

/**
 * 펼칠 섹션 하나. 우선순위: ?panel=(결정 panel 이름 또는 섹션 키) → 결정 함수의 panel → 게시가 끝났으면 '게시 뒤' → 첫 섹션.
 * `published` 는 결정 panel 이 'none' 일 때(더 할 일이 없을 때) 게시 뒤 칸을 여는 근거다.
 */
export function openSection(
  lane: FormatIntent,
  requested: string | null | undefined,
  primaryPanel: Panel | null | undefined,
  published = false,
  hasLivePublication = false,
): SectionKey {
  const sections = LANE_SECTIONS[lane];
  if (requested) {
    if (isSectionKey(lane, requested)) return requested;
    const byPanel = sectionForPanel(lane, requested as Panel);
    if (byPanel) return byPanel;
  }
  const byPrimary = primarySectionOf(lane, primaryPanel, hasLivePublication);
  if (byPrimary) return byPrimary;
  if (published && sections.some((s) => s.key === "after")) return "after";
  return sections[0].key;
}

/** 미저장 입력(캡션·사유·체크)을 새로고침 뒤 되살리는 sessionStorage 키. 서버 저장과는 무관하다. */
export function draftStorageKey(topicId: string, lane: FormatIntent, memeDraftId?: string | null): string {
  return memeDraftId && lane === "meme" ? `drinks.work.${topicId}.${lane}.${memeDraftId}` : `drinks.work.${topicId}.${lane}`;
}

/** 결정 바가 폼의 submit 을 대신 부를 때 쓰는 열쇠 — 동작 이름(+ 하위 action). 같은 열쇠를 가진 폼만 버튼을 숨긴다. */
export function primaryKey(action: { name: string; payload?: Record<string, unknown> } | null | undefined): string | null {
  if (!action) return null;
  const sub = action.payload?.action;
  return typeof sub === "string" && sub ? `${action.name}:${sub}` : action.name;
}

/** 결정 바가 **직접** 보내면 안 되는 동작 — 지문(expected_digest)을 사람이 보고 눌러야 한다. 바는 그 칸으로 스크롤만 한다. */
export function requiresInPanelConfirm(action: { name: string; payload?: Record<string, unknown> } | null | undefined): boolean {
  if (!action) return false;
  if (action.name === "publication_action" && action.payload?.action === "approve") return true;
  return Object.prototype.hasOwnProperty.call(action.payload ?? {}, "expected_digest");
}
