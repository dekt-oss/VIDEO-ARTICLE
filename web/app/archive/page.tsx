// 아카이브: 보관된 영상 + 생성 완료된 초안 + 발행 이력.
import { createClient } from "@/lib/supabase/server";
import { getDraftList, getPublished, getSavedRenderJobs } from "@/lib/queries";
import { dayLabelWithDate, seoulDateOf } from "@/lib/date";
import type { DraftListItem } from "@/lib/types";
import SavedRenderList from "@/components/SavedRenderList";

export const dynamic = "force-dynamic";

// 초안 생성일(created_at, KST 달력일)별로 그룹핑 — getDraftList 는 created_at 내림차순.
function groupByCreatedDate(drafts: DraftListItem[]): { date: string | null; items: DraftListItem[] }[] {
  const groups: { date: string | null; items: DraftListItem[] }[] = [];
  const index = new Map<string, number>();
  for (const d of drafts) {
    const key = d.created_at ? seoulDateOf(d.created_at) : "__none__";
    if (!index.has(key)) {
      index.set(key, groups.length);
      groups.push({ date: key === "__none__" ? null : key, items: [] });
    }
    groups[index.get(key)!].items.push(d);
  }
  return groups;
}

export default async function ArchivePage() {
  const supabase = createClient();
  const [drafts, published, savedRenders] = await Promise.all([
    getDraftList(supabase),
    getPublished(supabase),
    getSavedRenderJobs(supabase),
  ]);
  const draftGroups = groupByCreatedDate(drafts);

  return (
    <main className="container">
      <div className="header">
        <h1>아카이브</h1>
        <span className="muted">
          보관 영상 {savedRenders.length} · 생성된 초안 {drafts.length} · 발행 {published.length}
        </span>
      </div>

      <h2 style={{ fontSize: 15, marginTop: 8 }}>보관된 영상</h2>
      <SavedRenderList jobs={savedRenders} />

      <h2 style={{ fontSize: 15, marginTop: 24 }}>생성된 초안</h2>
      {drafts.length === 0 ? (
        <p className="muted">아직 생성된 초안이 없습니다. <a href="/review">④ 초안</a>에서 생성 요청하세요.</p>
      ) : (
        draftGroups.map((g) => (
          <div className="section" key={g.date ?? "none"}>
            <h3 className="group-header">
              {g.date ? dayLabelWithDate(g.date) : "날짜 미상"}{" "}
              <span className="muted">· {g.items.length}편</span>
            </h3>
            {g.items.map((d) => (
              <div className="list-row" key={d.paper_id}>
                <a href={`/review/${d.paper_id}`}>{d.title_ko || d.title}</a>
                <span className="status-pill">{d.published ? "발행됨" : "초안 완료"}</span>
              </div>
            ))}
          </div>
        ))
      )}

      <h2 style={{ fontSize: 15, marginTop: 24 }}>발행 이력</h2>
      {published.length === 0 ? (
        <p className="muted">아직 발행(승인)된 초안이 없습니다. 검수 화면에서 [승인]하면 여기 기록됩니다.</p>
      ) : (
        <div className="section">
          {published.map((it) => (
            <div className="list-row" key={it.paper_id}>
              <a href={`/review/${it.paper_id}`}>{it.title}</a>
              <span className="muted">{new Date(it.published_at).toLocaleDateString("ko-KR")}</span>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
