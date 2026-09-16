// ① 수집 원자료(raw): 수집·저장된 전체 논문 (검색 + 원문 링크).
import { createClient } from "@/lib/supabase/server";
import { getAllPapers } from "@/lib/queries";
import PapersTable from "@/components/PapersTable";

export const dynamic = "force-dynamic";

export default async function PapersPage() {
  const supabase = createClient();
  const papers = await getAllPapers(supabase);
  const scoredCount = papers.filter((p) => p.scored).length;

  return (
    <main className="container container--data">
      <div className="header">
        <h1>① 수집 원자료 (raw)</h1>
        <span className="muted">{papers.length}편 · 채점됨 {scoredCount}</span>
      </div>
      <div className="flow">
        <b>① 수집(raw)</b> → ② 채점 → ③ 최종선별 → ④ 초안
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        수집·중복제거·1차 필터(초록+언어)를 통과해 저장된 논문입니다. 원문(↗)으로 바로 접근하세요.
      </p>

      {papers.length === 0 ? (
        <p className="muted">아직 수집된 논문이 없습니다. 엔진 <code>collect</code>를 실행하세요.</p>
      ) : (
        <PapersTable papers={papers} />
      )}
    </main>
  );
}
