// ① 수집 원자료(reports) — ARIA 신호 원본. 논문 papers 미러.
import { createClient } from "@/lib/supabase/server";
import { getAllReports } from "@/lib/reportQueries";
import ReportsTable from "@/components/ReportsTable";

export const dynamic = "force-dynamic";

export default async function FinanceReportsPage() {
  const supabase = createClient();
  const reports = await getAllReports(supabase);
  return (
    <main className="container container--data">
      <div className="header">
        <h1>① 수집 원자료 (ARIA 신호)</h1>
        <span className="muted">{reports.length}건</span>
      </div>
      {reports.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          수집된 리포트가 없습니다: <code>python -m engine.report_collect</code>
        </p>
      ) : (
        <ReportsTable reports={reports} />
      )}
    </main>
  );
}
