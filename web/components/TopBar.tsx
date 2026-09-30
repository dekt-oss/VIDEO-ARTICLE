"use client";

// 상단 고정 바 — 공장 스위처(🎬 논문 / 📈 리포트) + 현재 공장 메뉴. 항상 보인다(데스크톱·모바일).
// 메뉴는 nav.ts 그룹 단위로 렌더한다: 항목 1개 그룹은 직접 탭, 2개 이상은 드롭다운(<details>)으로 접어
// 한 줄이 길어지지 않게 한다(사용자 요구: 옆으로 쭉 나열 불편).
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type MouseEvent } from "react";
import type { Factory } from "@/components/AppShell";
import { groupsFor, isActive } from "@/lib/nav";

export default function TopBar({ factory }: { factory: Factory }) {
  const pathname = usePathname() ?? "/";
  const groups = groupsFor(factory);

  // ★ 이 바의 실제 높이를 --topbar-h 로 알린다(2026-09-30 UI/UX 리뷰 #1). 작업 화면의 결정 바도
  //   sticky top:0 이라 스크롤하면 이 바 **밑으로** 숨어 상태·경고 줄이 가려졌다. 휴대폰에서는
  //   메뉴가 두 줄로 접혀 높이가 바뀌므로 숫자를 박지 않고 재서 넣는다.
  const barRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = barRef.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--topbar-h", `${el.offsetHeight}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 드롭다운 안의 링크를 누르면 이동하면서 열린 <details>를 닫는다(상태·라이브러리 불필요).
  const closeDropdown = (e: MouseEvent<HTMLAnchorElement>) => {
    e.currentTarget.closest("details")?.removeAttribute("open");
  };

  return (
    <div className="top-bar" ref={barRef}>
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
