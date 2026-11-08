// 스튜디오의 나머지 탭(2026-11-08, 옛 /drinks/topics 에서 옮김) — 내 소재 · 보류·제외. 밈 카드는 MemeCardsTab 을 그대로 쓴다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import CandidateCard from "@/components/drinks/topics/CandidateCard";
import MineTab from "@/components/drinks/topics/MineTab";
import { todayInSeoul } from "@/lib/date";
import { UNKNOWN_ESTIMATE, weekOptions } from "@/lib/drinks/pickModal";
import { loadTopicCandidates } from "@/lib/drinks/topicsQueries";
import { decide, rankForHome } from "@/lib/drinks/work/decision";
import { loadWorkItems } from "@/lib/drinks/work/queries";
import type { Decision, WorkItem } from "@/lib/drinks/work/types";

export const STUDIO_TABS = { mine: "내 소재", memes: "밈 카드", held: "보류·제외" } as const;
export type StudioTab = keyof typeof STUDIO_TABS;

export function StudioTabNav({ tab }: { tab: StudioTab | null }) {
  return (
    <nav className="dk-tabs" aria-label="소재 탭">
      <Link href="/drinks/studio" data-active={tab === null}>추천 소재</Link>
      {(Object.keys(STUDIO_TABS) as StudioTab[]).map((k) => <Link key={k} href={`/drinks/studio?tab=${k}`} data-active={k === tab}>{STUDIO_TABS[k]}</Link>)}
    </nav>
  );
}

export async function HeldTab({ page }: { page: number }) {
  const v = await loadTopicCandidates({ statuses: ["dismissed", "merged"], page });
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const d = v.data;
  const weeks = weekOptions(todayInSeoul());
  const last = Math.max(1, Math.ceil(d.total / d.pageSize));
  return (
    <>
      <p className="muted" style={{ fontSize: 13 }}>기각·합쳐진 후보 {d.total}건. 보류·제외된 <b>소재</b>는 <Link href="/drinks/board?tab=held">옛 선별 화면</Link>에 있습니다.</p>
      <div className="dk-topic-grid">
        {d.candidates.map((c) => (
          <CandidateCard key={c.id} c={c} rec={{ format: "unknown", reason: "기각·합쳐진 후보는 추천하지 않습니다" }} evidence={undefined} evidenceLoaded={false}
            dupTopics={c.duplicate_topic_ids.map((id) => ({ id, title: d.topics.get(id)?.title ?? "소재" }))}
            pick={{ ok: false, code: "promoted", reason: "다시 열어야 고를 수 있습니다" }} weeks={weeks} budget={null} estimate={UNKNOWN_ESTIMATE} />
        ))}
      </div>
      {last > 1 && (
        <div className="dk-pager">
          {d.page > 1 ? <Link className="btn" href={`/drinks/studio?tab=held&page=${d.page - 1}`}>← 앞 페이지</Link> : <span className="btn" aria-disabled="true">← 앞 페이지</span>}
          <span className="muted">{d.page} / {last}</span>
          {d.page < last ? <Link className="btn" href={`/drinks/studio?tab=held&page=${d.page + 1}`}>다음 페이지 →</Link> : <span className="btn" aria-disabled="true">다음 페이지 →</span>}
        </div>
      )}
    </>
  );
}

export async function MineSection() {
  const v = await loadWorkItems("all");
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const items: WorkItem[] = v.data;
  const decisions: Decision[] = items.map((it) => decide(it));
  // 막힌 것이 위로 오도록 홈과 같은 순서를 쓴다(스누즈 없음).
  const updatedAt = new Map(items.map((i) => [i.unit_id, i.updated_at]));
  const order = new Map(rankForHome(decisions, new Set<string>(), updatedAt).map((d, i) => [d.unitId, i]));
  const sorted = [...items].sort((a, b) => (order.get(a.unit_id) ?? 9e9) - (order.get(b.unit_id) ?? 9e9));
  return <MineTab items={sorted} decisions={decisions} />;
}
