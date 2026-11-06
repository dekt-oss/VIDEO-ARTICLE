// 만들기 목록 (/drinks/work?filter=approve|publish|all) — 작업 단위(소재 × 형식, 카드 밈) 행을 소재별로 묶어 보여 준다.
// 행의 "지금 할 일"은 web/lib/drinks/work/decision.ts(담당 B) 가 정하고, 행 자체는 queries.ts::loadWorkItems(담당 B) 가 준다.
// 설명형 단계(결재·구매·판정…)는 제작 상태를 읽어야 정확한데, 목록에서는 제작 상태를 싣지 않는다 — 작업공간이 다시 계산한다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import { decide } from "@/lib/drinks/work/decision";
import { loadWorkItems } from "@/lib/drinks/work/queries";
import { FORMAT_SHORT, workHref, type Decision, type WorkItem } from "@/lib/drinks/work/types";

export const dynamic = "force-dynamic";

const FILTERS = [["all", "전부"], ["approve", "승인할 것"], ["publish", "게시할 것"]] as const;
type Filter = (typeof FILTERS)[number][0];

function unpack(res: unknown): { items: WorkItem[]; state: "ok" | "failed" | "unconfigured"; error?: string } {
  if (Array.isArray(res)) return { items: res as WorkItem[], state: "ok" };
  const r = res as { state?: string; error?: string; data?: unknown; items?: unknown } | null;
  if (!r || typeof r !== "object") return { items: [], state: "failed", error: "조회 결과가 비었습니다." };
  if (r.state === "failed") return { items: [], state: "failed", error: r.error };
  if (r.state === "unconfigured") return { items: [], state: "unconfigured" };
  const d = (r.data ?? r) as { items?: unknown } | unknown[];
  const list = Array.isArray(d) ? d : Array.isArray((d as { items?: unknown }).items) ? (d as { items: unknown[] }).items : null;
  return list ? { items: list as WorkItem[], state: "ok" } : { items: [], state: "failed", error: "작업 단위 행 모양을 알 수 없습니다(items 배열 없음)." };
}

function safeDecide(item: WorkItem): Decision | null {
  try { return decide(item); } catch { return null; }
}

export default async function DrinksWorkListPage(props: { searchParams: Promise<{ filter?: string }> }) {
  const { filter: raw } = await props.searchParams;
  const filter: Filter = FILTERS.some(([k]) => k === raw) ? (raw as Filter) : "all";
  const res = await loadWorkItems(filter).catch((e: unknown) => ({ state: "failed", error: e instanceof Error ? e.message : String(e) }));
  const { items, state, error } = unpack(res);
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 만들기</h1>
        <span className="muted">소재 하나의 형식마다 한 줄 — 지금 할 일부터</span>
      </div>
      <nav className="dk-tabs" aria-label="만들기 필터">
        {FILTERS.map(([k, label]) => <Link key={k} href={`/drinks/work?filter=${k}`} data-active={k === filter}>{label}</Link>)}
      </nav>
      {state !== "ok" ? (
        <LoadProblem state={state} error={error} />
      ) : items.length === 0 ? (
        <p className="muted">해당하는 작업이 없습니다(정상 0건). <Link href="/drinks/topics">소재 고르기</Link>에서 형식을 고르면 여기 생깁니다.</p>
      ) : (
        groupByTopic(items).map((g) => (
          <section key={g.key} className="card" style={{ marginBottom: 10 }}>
            <div className="dk-row" style={{ justifyContent: "space-between" }}>
              <b>{g.title}</b>
              <span className="muted">{g.week ? `${g.week} 주` : ""}{g.topicStatus ? ` · ${g.topicStatus}` : ""}</span>
            </div>
            {g.items.map((it) => {
              const d = safeDecide(it);
              const href = workHref(it, d?.primary.panel);
              return (
                <div key={it.unit_id} className="list-row">
                  <span>
                    <span className="pill on">{FORMAT_SHORT[it.format_intent]}{it.source === "card" ? " · 카드" : ""}</span>{" "}
                    <Link href={href}>{d ? d.primary.label : "상태 모름"}</Link>
                    {d?.blocks.map((b) => <span key={b.code} className="pill dk-bad" style={{ marginLeft: 6 }}>{b.message}</span>)}
                    {it.unknown_billed && <span className="pill dk-warn" style={{ marginLeft: 6 }}>돈 결과 모름</span>}
                  </span>
                  <span className="list-row-meta">
                    <Link className={d && d.blocks.length ? "btn" : "btn pick"} href={href}>{d ? d.primary.label : "열기"}</Link>
                  </span>
                </div>
              );
            })}
          </section>
        ))
      )}
    </main>
  );
}

function groupByTopic(items: WorkItem[]) {
  const groups = new Map<string, { key: string; title: string; week: string | null; topicStatus: string | null; items: WorkItem[]; updated: string }>();
  for (const it of items) {
    const key = it.topic_id ?? `card:${it.unit_id}`;
    const g = groups.get(key) ?? { key, title: it.title, week: it.editorial_week, topicStatus: it.topic_id ? it.topic_status : "카드 밈", items: [], updated: it.updated_at ?? "" };
    g.items.push(it);
    if ((it.updated_at ?? "") > g.updated) g.updated = it.updated_at ?? "";
    groups.set(key, g);
  }
  const order = { explainer: 0, card: 1, meme: 2 } as const;
  return [...groups.values()]
    .map((g) => ({ ...g, items: [...g.items].sort((a, b) => order[a.format_intent] - order[b.format_intent]) }))
    .sort((a, b) => b.updated.localeCompare(a.updated));
}
