"use client";

// 공장(factory) 인식 셸. 경로로 현재 공장을 판정해 data-factory 를 셸에 부여하고
// 해당 공장의 사이드바를 렌더한다. data-factory 가 globals.css 의 강조색 토큰을 덮어써
// 두 공장(논문=파랑 / 리포트=바이올렛)의 화면이 색으로 즉시 구분된다.
import { usePathname } from "next/navigation";
import TopBar from "@/components/TopBar";

export type Factory = "paper" | "finance";

export function factoryOf(pathname: string): Factory {
  return pathname.startsWith("/finance") ? "finance" : "paper";
}

// 단일 상단 고정 바 네비게이션. 공장 스위처 + 주요 탭이 항상 보여, 모바일에서 햄버거로
// 왕복할 필요가 없다(사용자 요구). data-factory 로 공장별 강조색(논문 파랑 / 리포트 바이올렛).
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const factory = factoryOf(pathname);
  return (
    <div className="app-shell" data-factory={factory}>
      <TopBar factory={factory} />
      <div className="app-main">{children}</div>
    </div>
  );
}
