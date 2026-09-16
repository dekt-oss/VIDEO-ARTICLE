"use client";

// 상단 고정 바 — 공장 스위처(🎬 논문 / 📈 리포트) + 현재 공장 메뉴. 항상 보인다(데스크톱·모바일).
// 메뉴는 nav.ts 그룹 단위로 렌더한다: 항목 1개 그룹은 직접 탭, 2개 이상은 드롭다운(<details>)으로 접어
// 한 줄이 길어지지 않게 한다(사용자 요구: 옆으로 쭉 나열 불편).
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { MouseEvent } from "react";
import type { Factory } from "@/components/AppShell";
import { groupsFor, isActive } from "@/lib/nav";

export default function TopBar({ factory }: { factory: Factory }) {
  const pathname = usePathname() ?? "/";
  const groups = groupsFor(factory);

  // 드롭다운 안의 링크를 누르면 이동하면서 열린 <details>를 닫는다(상태·라이브러리 불필요).
  const closeDropdown = (e: MouseEvent<HTMLAnchorElement>) => {
    e.currentTarget.closest("details")?.removeAttribute("open");
  };

  return (
    <div className="top-bar">
      <div className="factory-switch" role="group" aria-label="공장 선택">
        <Link href="/" data-active={factory === "paper"} aria-current={factory === "paper" ? "true" : undefined}>
          🎬 논문 공장
        </Link>
        <Link href="/finance" data-active={factory === "finance"} aria-current={factory === "finance" ? "true" : undefined}>
          📈 리포트 공장
        </Link>
      </div>
      <nav className="top-tabs" aria-label="주요 메뉴">
        {groups.map((g) =>
          g.items.length === 1 ? (
            <Link
              key={g.items[0].href}
              href={g.items[0].href}
              data-active={isActive(pathname, g.items[0])}
            >
              {g.items[0].label}
            </Link>
          ) : (
            <details key={g.title} className="nav-group">
              <summary data-active={g.items.some((it) => isActive(pathname, it))}>
                {g.title}
              </summary>
              <div className="nav-panel">
                {g.items.map((it) => (
                  <Link
                    key={it.href}
                    href={it.href}
                    data-active={isActive(pathname, it)}
                    onClick={closeDropdown}
                  >
                    {it.label}
                  </Link>
                ))}
              </div>
            </details>
          )
        )}
      </nav>
    </div>
  );
}
