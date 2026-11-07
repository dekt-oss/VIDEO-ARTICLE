"use client";

// 주류 공장 전용 셸(2026-11-06, 승인 목업 docs/mockups/drinks/ 기준) — 왼쪽 세로 메뉴 + 위쪽 얇은 띠(위치 · 공장 바꾸기).
//   논문·리포트 공장은 그대로 TopBar 를 쓴다(AppShell 이 공장으로 가른다). 메뉴 정의는 lib/nav.ts 의 GROUPS_DRINKS 하나뿐이다 —
//   여기서 주소를 새로 적지 않는다. 앞의 네 그룹은 번호(01~04)를 달고, 나머지(자료·설정)는 접히는 묶음으로 조용히 둔다.
//   휴대폰 폭(≤650px)에서는 목업처럼 세로 메뉴가 위쪽 가로 띠로 바뀐다(globals 가 아니라 drinks-theme.css).
import Link from "next/link";
import { usePathname } from "next/navigation";

import { GROUPS_DRINKS, isActive } from "@/lib/nav";

const MAIN_COUNT = 5;

export function DrinksSidebar() {
  const pathname = usePathname() ?? "/drinks";
  const main = GROUPS_DRINKS.slice(0, MAIN_COUNT);
  const rest = GROUPS_DRINKS.slice(MAIN_COUNT);
  return (
    <aside className="dk-sidebar">
      <Link href="/drinks" className="dk-brand">술째리고<small>CONTENT STUDIO</small></Link>
      <nav className="dk-nav" aria-label="주류 공장 메뉴">
        {main.map((g, i) => {
          const first = g.items[0];
          const groupActive = g.items.some((it) => isActive(pathname, it));
          const single = g.items.length === 1;
          return (
            <div key={g.title} className="dk-nav-group" data-active={groupActive}>
              <Link href={first.href} className="dk-nav-item" data-active={groupActive}
                aria-current={single && groupActive ? "page" : undefined}>
                <span className="dk-nav-num" aria-hidden>0{i + 1}</span>{g.title}
              </Link>
              {!single && (
                <div className="dk-subnav">
                  {g.items.map((it) => (
                    <Link key={it.href} href={it.href} data-active={isActive(pathname, it)}
                      aria-current={isActive(pathname, it) ? "page" : undefined}>{it.label}</Link>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {rest.map((g) => {
          const groupActive = g.items.some((it) => isActive(pathname, it));
          return (
            <details key={g.title} className="dk-more" open={groupActive || undefined}>
              <summary data-active={groupActive}>{g.title}</summary>
              <div className="dk-more-list">
                {g.items.map((it) => (
                  <Link key={it.href} href={it.href} data-active={isActive(pathname, it)}
                    aria-current={isActive(pathname, it) ? "page" : undefined}>{it.label}</Link>
                ))}
              </div>
            </details>
          );
        })}
      </nav>
      <div className="dk-side-note">매일 한 편, 차근차근.<br />고르고 → 만들고 → 게시하기</div>
    </aside>
  );
}

/** 본문 위 얇은 띠 — 지금 위치와 다른 공장으로 가는 길(공장 스위처는 사라지면 안 된다). */
export function DrinksTopStrip() {
  return (
    <div className="dk-topstrip">
      <span>술째리고 / 주류 콘텐츠</span>
      <nav className="dk-factory" aria-label="공장 선택">
        <span className="dk-factory-now" aria-current="true">🍶 주류 공장</span>
        <Link href="/">🎬 논문 공장</Link>
        <Link href="/finance">📈 리포트 공장</Link>
      </nav>
    </div>
  );
}
