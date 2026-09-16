// ⑥ 렌더 결과: render_jobs 목록 + 진행률 + mp4 미리보기 + 발행 대기 이관/반려.
import { createClient } from "@/lib/supabase/server";
import { getRenderJobs } from "@/lib/queries";
import RenderList from "@/components/RenderList";

export const dynamic = "force-dynamic";

export default async function RenderPage() {
  const supabase = createClient();
  const jobs = await getRenderJobs(supabase);

  return (
    <main className="container container--work">
      <div className="header">
        <h1>⑥ 렌더 결과</h1>
        <span className="muted">렌더 잡 {jobs.length}건</span>
      </div>
      <div className="flow">
        ⑤ 지시서 → <b>⑥ 렌더(mp4)</b> → 발행 대기
      </div>
      <RenderList jobs={jobs} />
    </main>
  );
}
