// ② 채점 결과(report_scores, 4축). 논문 scored 미러.
import { createClient } from "@/lib/supabase/server";
import { getScoredReports } from "@/lib/reportQueries";
import ReportScoredTable from "@/components/ReportScoredTable";

export const dynamic = "force-dynamic";

export default async function FinanceScoredPage() {
  const supabase = createClient();
  const rows = await getScoredReports(supabase);
  return (
    <main className="container container--data">
      <div className="header">
        <h1>② 채점 결과 (4축)</h1>
        <span className="muted">{rows.length}건</span>
      </div>
      {rows.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          채점 결과가 없습니다: <code>python -m engine.report_score</code>
        </p>
      ) : (
        <ReportScoredTable rows={rows} />
      )}
    </main>
  );
}
