// 옛 주소 → 작업공간 주소의 순수 매핑(기획 v2 §5 넘기기 표). middleware 와 제작 페이지가 쓴다.
// 값 import 가 없어 Edge 런타임과 node --test 양쪽에서 돈다.
//
// ★ 옛 페이지는 지우지 않는다 — `?legacy=1` 을 붙이면 넘기지 않고 옛 화면을 그대로 연다(되돌리기·대조용).

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const LEGACY_BYPASS_PARAM = "legacy";

/** 옛 소재 탭 → 레인·칸. lane 이 없는 탭은 레인을 정하지 않는다(작업공간이 첫 형식을 연다). */
export const REVIEW_TAB_MAP: Record<string, { lane?: "explainer" | "card"; panel?: string }> = {
  approval: { panel: "approve" },
  evidence: { panel: "evidence" },
  brief: { panel: "evidence" },
  video: { lane: "explainer", panel: "plan" },
  carousel: { lane: "card", panel: "plan" },
  overview: {},
  history: {},
};

export function workPath(topicId: string, q: { lane?: string | null; panel?: string | null; plan?: string | null; meme?: string | null } = {}): string {
  const p = new URLSearchParams();
  if (q.lane) p.set("lane", q.lane);
  if (q.panel) p.set("panel", q.panel);
  if (q.plan) p.set("plan", q.plan);
  if (q.meme) p.set("meme", q.meme);
  const s = p.toString();
  return `/drinks/work/${topicId}${s ? `?${s}` : ""}`;
}

/** `/drinks/review/<uuid>?tab=` → 작업공간. 목록(`/drinks/review`)·legacy 플래그·uuid 아님 → null(넘기지 않음). */
export function legacyReviewRedirect(pathname: string, search: string): string | null {
  const m = /^\/drinks\/review\/([^/]+)\/?$/.exec(pathname);
  if (!m || !UUID_RE.test(m[1])) return null;
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  if (params.get(LEGACY_BYPASS_PARAM)) return null;
  const tab = params.get("tab") ?? "";
  const map = REVIEW_TAB_MAP[tab] ?? {};
  return workPath(m[1], { lane: map.lane ?? null, panel: map.panel ?? null });
}

/** 제작안 형식 → 레인. 설명형은 video 제작안이다. */
export function laneOfPlanFormat(format: string): "explainer" | "card" {
  return format === "carousel" ? "card" : "explainer";
}

/** `/drinks/production/<planId>` → 작업공간 제작 칸(동적 조회 결과를 받는다). */
export function productionRedirect(topicId: string, planFormat: string, planId: string): string {
  return workPath(topicId, { lane: laneOfPlanFormat(planFormat), panel: "produce", plan: planId });
}

/** `/drinks/discover` → 소재 고르기의 후보 탭(기획 v2 §5). `?legacy=1` 이면 옛 발견함 그대로. */
export function legacyDiscoverRedirect(pathname: string, search: string): string | null {
  if (pathname !== "/drinks/discover" && pathname !== "/drinks/discover/") return null;
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  if (params.get(LEGACY_BYPASS_PARAM)) return null;
  return "/drinks/topics?tab=candidates";
}

/** 옛 주소 전체를 한 자리에서 — middleware 가 부른다. 정적으로 정해지는 것만(제작 페이지는 DB 조회라 페이지가 한다). */
export function legacyDrinksRedirect(pathname: string, search: string): string | null {
  return legacyReviewRedirect(pathname, search) ?? legacyDiscoverRedirect(pathname, search);
}
