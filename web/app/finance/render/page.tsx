// ⑥ 리포트 렌더 결과. 논문 render 미러(경량).
import { createClient } from "@/lib/supabase/server";
import { getReportRenderJobs } from "@/lib/reportQueries";
import ReportRenderList from "@/components/ReportRenderList";

export const dynamic = "force-dynamic";

export default async function FinanceRenderPage() {
  const supabase = createClient();
  const jobs = await getReportRenderJobs(supabase, { scope: "active" });
  return (
    <main className="container container--work">
      <div className="header">
        <h1>⑥ 렌더 결과</h1>
        <span className="muted">{jobs.length}건</span>
      </div>
      <div className="flow">④ 초안 → ⑤ 지시서 → <b>⑥ 렌더</b></div>
      <ReportRenderList jobs={jobs} />
    </main>
  );
}
