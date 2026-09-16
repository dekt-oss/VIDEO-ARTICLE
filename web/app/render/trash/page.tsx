// 휴지통: 소프트 삭제된 렌더 잡(복원/영구삭제).
import { createClient } from "@/lib/supabase/server";
import { getRenderJobs } from "@/lib/queries";
import TrashList from "@/components/TrashList";

export const dynamic = "force-dynamic";

export default async function RenderTrashPage() {
  const supabase = createClient();
  const jobs = await getRenderJobs(supabase, { scope: "trash" });

  return (
    <main className="container">
      <div className="header">
        <h1>휴지통</h1>
        <span className="muted">삭제된 렌더 {jobs.length}</span>
      </div>
      <div className="flow">
        <a href="/render">⑥ 렌더 결과</a> → <b>휴지통</b>
      </div>
      <TrashList jobs={jobs} />
    </main>
  );
}
