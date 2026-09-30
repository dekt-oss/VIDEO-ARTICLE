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

// ★ 상단 메뉴(2026-09-30 운영자 결정 1-1): **매일 쓰는 4개는 직접 탭**, 가끔 쓰는 보관함·데이터만 드롭다운.
//   종전(NAV-01 3축)은 선별·④·⑤·⑥ 이 전부 "오늘의 작업 ▾" 안에 있어 옮길 때마다 두 번 눌러야 했다.
//   · 작업함 = ④⑤ 를 합친 한 목록(결정 2-1). 주소는 /review 그대로 — /directive 는 작업함으로 넘긴다.
//   · 성과는 공장과 무관한 한 화면이다(리포트 영상도 같은 표에 나온다). 리포트 공장은 /finance/analytics 로 같은
//     화면을 연다 — 주소가 /finance 여야 위쪽 공장 표시가 리포트로 남는다.
//   TopBar 는 항목 1개 그룹을 직접 탭으로, 2개 이상을 드롭다운으로 그린다 — 그 규칙을 그대로 쓴다.
//   기존 라우트는 하나도 없애지 않는다.

// 논문 공장 — 루트 경로.
export const GROUPS_PAPER: NavGroup[] = [
  { title: "선별", items: [{ href: "/", label: "선별", match: "exact" }] },
  { title: "작업함", items: [{ href: "/review", label: "작업함", match: "prefix" }] },
  { title: "렌더·업로드", items: [{ href: "/render", label: "렌더·업로드", match: "exact" }] },
  { title: "성과", items: [{ href: "/analytics", label: "성과", match: "prefix" }] },
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
      { href: "/analytics/report", label: "성과 리포트", match: "prefix" },
    ],
  },
];

// 리포트 공장(하루 한 리포트) — /finance 접두. 논문 공장과 같은 모양.
export const GROUPS_FINANCE: NavGroup[] = [
  { title: "선별", items: [{ href: "/finance", label: "선별", match: "exact" }] },
  { title: "작업함", items: [{ href: "/finance/review", label: "작업함", match: "prefix" }] },
  { title: "렌더·업로드", items: [{ href: "/finance/render", label: "렌더·업로드", match: "exact" }] },
  { title: "성과", items: [{ href: "/finance/analytics", label: "성과", match: "prefix" }] },
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
