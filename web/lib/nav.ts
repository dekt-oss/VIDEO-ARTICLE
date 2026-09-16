// 두 공장(논문 / 리포트) 네비게이션 정의. TopBar 가 그룹 단위(직접 탭 / 드롭다운)로 렌더한다.
import type { Factory } from "@/components/AppShell";

export interface NavItem {
  href: string;
  label: string;
  match?: "exact" | "prefix";
}
export interface NavGroup {
  title: string;
  items: NavItem[];
}

// ★ 상단 메뉴는 3축이다: 오늘의 작업 / 보관함 / 데이터 (개선 지시서 NAV-01 §4-1).
//   이전에는 "검수 · 제작"(④⑤⑥)이 별 그룹이라 상단이 4축이었다. ④⑤⑥ 은 매일의 작업이므로
//   "오늘의 작업" 안으로 넣었다 — 상단은 3개로 줄고 직접 링크는 그대로 남는다.
//   기존 라우트는 하나도 없애지 않는다(지시서 §4-2 1차 방침).

// 논문 공장 — 루트 경로.
export const GROUPS_PAPER: NavGroup[] = [
  {
    title: "오늘의 작업",
    items: [
      { href: "/", label: "🏠 홈 · 오늘의 작업", match: "exact" },
      { href: "/review", label: "④ 초안 검수", match: "prefix" },
      { href: "/directive", label: "⑤ 영상 지시서", match: "prefix" },
      { href: "/render", label: "⑥ 렌더 결과", match: "exact" },
    ],
  },
  {
    title: "보관함",
    items: [
      { href: "/archive", label: "아카이브", match: "prefix" },
      { href: "/render/trash", label: "휴지통", match: "exact" },
    ],
  },
  {
    title: "데이터",
    items: [
      { href: "/papers", label: "① 수집 원자료", match: "prefix" },
      { href: "/scored", label: "② 채점 결과", match: "prefix" },
      { href: "/measure", label: "P0 측정", match: "prefix" },
      { href: "/analytics", label: "쇼츠 성과", match: "exact" },
      { href: "/analytics/report", label: "성과 리포트", match: "prefix" },
    ],
  },
];

// 리포트 공장(하루 한 리포트) — /finance 접두. 논문 공장과 같은 3축.
export const GROUPS_FINANCE: NavGroup[] = [
  {
    title: "오늘의 작업",
    items: [
      { href: "/finance", label: "🏠 홈 · 오늘의 작업", match: "exact" },
      { href: "/finance/review", label: "④ 초안 검수", match: "prefix" },
      { href: "/finance/directive", label: "⑤ 영상 지시서", match: "prefix" },
      { href: "/finance/render", label: "⑥ 렌더 결과", match: "exact" },
    ],
  },
  { title: "보관함", items: [{ href: "/finance/archive", label: "아카이브", match: "prefix" }] },
  {
    title: "데이터",
    items: [
      { href: "/finance/reports", label: "① 수집 원자료", match: "prefix" },
      { href: "/finance/scored", label: "② 채점 결과", match: "prefix" },
    ],
  },
];

export const BRAND: Record<Factory, { emoji: string; label: string; home: string }> = {
  paper: { emoji: "🎬", label: "video-article", home: "/" },
  finance: { emoji: "📈", label: "리포트 공장", home: "/finance" },
};

export function groupsFor(factory: Factory): NavGroup[] {
  return factory === "finance" ? GROUPS_FINANCE : GROUPS_PAPER;
}

export function isActive(pathname: string, item: NavItem): boolean {
  if (item.match === "prefix") return pathname === item.href || pathname.startsWith(item.href + "/");
  return pathname === item.href;
}
