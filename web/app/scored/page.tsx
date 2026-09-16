// ② 분류(채점) 결과: 5축 점수 매겨진 논문. 정렬·분류·검색은 ScoredTable(클라)에서.
import { createClient } from "@/lib/supabase/server";
import { getScoredPapers } from "@/lib/queries";
import ScoredTable from "@/components/ScoredTable";

export const dynamic = "force-dynamic";

export default async function ScoredPage() {
  const supabase = createClient();
  const rows = await getScoredPapers(supabase);
  const inBatch = rows.filter((r) => r.in_batch).length;

  return (
    <main className="container container--data">
      <div className="header">
        <h1>② 채점 결과</h1>
        <span className="muted">{rows.length}편 채점 · 최종선별 {inBatch}</span>
      </div>
      <div className="flow">
        ① 수집 → <b>② 채점</b> → ③ 최종선별 → ④ 초안
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        5축 LLM 채점 결과. 의외성/이해/일상 = 재미, 학술중요/buzz = 중요. 정렬 축·분류를 골라 보세요.
      </p>

      {rows.length === 0 ? (
        <p className="muted">아직 채점된 논문이 없습니다. 엔진 <code>score</code>를 실행하세요.</p>
      ) : (
        <ScoredTable rows={rows} />
      )}
    </main>
  );
}
