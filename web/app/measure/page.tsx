// P0 합격기준 측정 뷰 (engine/measure.py 와 동일 기준).
// 최근 7 배치일에서 낙점가능(shortlisted+picked) ≥3편인 날이 ≥5일이면 합격.
import { createClient } from "@/lib/supabase/server";
import { selectIn } from "@/lib/supabase/chunked";

export const dynamic = "force-dynamic";

const WINDOW_DAYS = 7;
const MIN_PICKS_PER_DAY = 3;
const MIN_PASS_DAYS = 5;
const ACCEPTABLE = new Set(["shortlisted", "picked"]);

export default async function MeasurePage() {
  const supabase = createClient();

  const { data: batchRows } = await supabase
    .from("daily_batch")
    .select("batch_date, paper_id")
    .order("batch_date", { ascending: false });

  // 최근 7개 배치일로 그룹핑.
  const byDate = new Map<string, string[]>();
  for (const r of batchRows ?? []) {
    if (!byDate.has(r.batch_date)) {
      if (byDate.size >= WINDOW_DAYS) continue;
      byDate.set(r.batch_date, []);
    }
    byDate.get(r.batch_date)!.push(r.paper_id);
  }

  const allIds = Array.from(byDate.values()).flat();
  const decMap = new Map<string, string>();
  if (allIds.length > 0) {
    const decisions = await selectIn<{ paper_id: string; status: string }>(
      allIds,
      (c) => supabase.from("decisions").select("paper_id, status").in("paper_id", c),
      "decisions.paper_id");
    for (const d of decisions) decMap.set(d.paper_id, d.status);
  }

  const days = Array.from(byDate.entries()).map(([date, ids]) => {
    const acceptable = ids.filter((id) => ACCEPTABLE.has(decMap.get(id) ?? "")).length;
    return { date, batchSize: ids.length, acceptable, pass: acceptable >= MIN_PICKS_PER_DAY };
  });
  const passDays = days.filter((d) => d.pass).length;
  const passed = passDays >= MIN_PASS_DAYS && days.length > 0;

  return (
    <main className="container">
      <div className="header">
        <h1>P0 측정</h1>
        <span className="muted">최근 {days.length}/{WINDOW_DAYS}일</span>
      </div>

      <div className={passed ? "banner-ok" : "banner-warn"} style={{ margin: "16px 0" }}>
        {passed ? "✓ P0 합격" : "P0 미달"} — 낙점가능 ≥{MIN_PICKS_PER_DAY}편인 날 {passDays}일
        (합격 기준: {MIN_PASS_DAYS}일 이상)
      </div>

      {days.length === 0 ? (
        <p className="muted">측정할 배치가 없습니다.</p>
      ) : (
        <div className="section">
          {days.map((d) => (
            <div className="list-row" key={d.date}>
              <span>{d.date}</span>
              <span className={d.pass ? "" : "muted"}>
                낙점가능 {d.acceptable}/{d.batchSize} {d.pass ? "✓" : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
