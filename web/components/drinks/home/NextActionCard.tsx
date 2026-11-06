"use client";

// 홈 [지금 할 일 하나] — rankForHome(결정들, 스누즈)[0]. 제목 · 형식 칩 · 막힌 이유 · 버튼 하나(작업공간 링크) ·
//   [확인했음 — 나중에](localStorage, 24시간, 표시 순서만 — 실행 차단을 풀지 않는다) · [다른 작업 보기](다음 순위).
//   첫 렌더는 스누즈 없이 그리고(서버와 같은 HTML), 마운트 뒤 localStorage 를 읽는다 — 수화 불일치를 피한다.
import Link from "next/link";
import { useEffect, useState } from "react";

import { SNOOZE_KEY, parseSnoozed, snoozeValue } from "@/lib/drinks/home";
import { homeTier, rankForHome, snoozeKey } from "@/lib/drinks/work/decision";
import { FORMAT_LABEL, workHref, type Decision, type WorkItem } from "@/lib/drinks/work/types";

export default function NextActionCard({ items, decisions }: { items: WorkItem[]; decisions: Decision[] }) {
  const [snoozed, setSnoozed] = useState<Set<string>>(new Set());
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    try { setSnoozed(parseSnoozed(window.localStorage.getItem(SNOOZE_KEY), Date.now())); } catch { /* 저장소 없음 — 스누즈 없이 */ }
  }, []);
  const updatedAt = new Map(items.map((i) => [i.unit_id, i.updated_at]));
  // 미룬 항목은 목록에서 빠지지 않고 같은 급 안에서 뒤로 간다(decision.ts). 끝난 것(급 7)은 카드에 올리지 않는다.
  const ranked = rankForHome(decisions, snoozed, updatedAt).filter((d) => homeTier(d) < 7);
  const byUnit = new Map(items.map((i) => [i.unit_id, i]));
  if (ranked.length === 0) {
    return (
      <section className="next-action done">
        <div className="next-action-body">
          <div className="next-action-kicker">지금 할 일</div>
          <div className="next-action-headline">{snoozed.size > 0 ? `할 일 ${snoozed.size}건을 나중으로 미뤄 뒀습니다.` : "오늘 결정할 작업이 없습니다 — 전부 완료."}</div>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            {snoozed.size > 0 ? "미룬 것은 24시간 뒤 다시 올라옵니다. 실행 차단은 풀리지 않았습니다." : "다음 소재를 고르면 여기에 첫 결정이 올라옵니다."}
          </p>
          <div className="next-action-cta dk-hero-cta"><Link className="btn pick" href="/drinks/topics">다음 소재 고르기 →</Link></div>
        </div>
        <div className="next-action-art" aria-hidden>✓<small>오늘 결정 끝</small></div>
      </section>
    );
  }
  const d = ranked[offset % ranked.length];
  const it = byUnit.get(d.unitId);
  if (!it) return <p className="banner-warn">결정과 작업 단위가 맞지 않습니다({d.unitId}) — 조회 누락입니다.</p>;
  const block = d.blocks[0];
  const snooze = () => {
    try {
      const raw = window.localStorage.getItem(SNOOZE_KEY);
      window.localStorage.setItem(SNOOZE_KEY, snoozeValue(raw, snoozeKey(d), Date.now()));   // 열쇠 = unit#단계코드 — 단계가 바뀌면 저절로 풀린다
      setSnoozed(parseSnoozed(window.localStorage.getItem(SNOOZE_KEY), Date.now()));
      setOffset(0);
    } catch { /* 저장소 없음 — 그냥 둔다 */ }
  };
  return (
    <section className={block ? "next-action" : "next-action"} aria-label="지금 할 일 하나">
      <div className="next-action-body">
        <div className="next-action-kicker">지금 할 일 하나 · <span className="pill on">{FORMAT_LABEL[it.format_intent]}</span>{ranked.length > 1 && <span className="muted"> · {offset % ranked.length + 1} / {ranked.length}</span>}</div>
        <div className="next-action-headline">{it.title}</div>
        <p style={{ margin: "4px 0" }}>{d.primary.label}</p>
        {block && <p className="dk-bad" style={{ margin: "4px 0", fontSize: 13 }}>막힘: {block.message}</p>}
        {d.warnings.length > 0 && <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>{d.warnings.join(" · ")}</p>}
        <div className="next-action-cta dk-hero-cta">
          <Link className="btn pick" href={workHref(it, d.primary.panel)}>{block ? "막힌 이유 보기 →" : `${d.primary.label} →`}</Link>
        </div>
        <div className="actions" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <button className="btn" type="button" onClick={snooze} title="표시 순서만 바꿉니다. 실행 차단을 풀지 않습니다">확인했음 — 나중에</button>
          {ranked.length > 1 && <button className="btn" type="button" onClick={() => setOffset(offset + 1)}>다른 작업 보기</button>}
        </div>
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 12 }}>[확인했음 — 나중에]는 24시간 동안 순서만 미룹니다 · 실행 차단을 풀지 않습니다.</p>
      </div>
      <div className="next-action-art" aria-hidden>{String(offset % ranked.length + 1).padStart(2, "0")}<small>{offset % ranked.length === 0 ? "오늘의 첫 결정" : "다음 결정"}</small></div>
    </section>
  );
}
