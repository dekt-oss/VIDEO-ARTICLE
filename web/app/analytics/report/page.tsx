// 성과 리포트 (일간/주간/월간 추이 + 잘된점/잘못된점/개선방향).
// 읽기 전용: engine.analytics 가 채운 youtube_analytics_daily(시계열) + engine.perf_report 가 채운
// performance_reports(하이브리드 분석글) + youtube_analytics(최신 스냅샷, 상/하위 쇼츠)를 읽는다.
// 차트는 recharts(클라이언트) 컴포넌트 PerfCharts 로 격리. 채널(언어)별 섹션.
import PerfCharts, { type DailyPoint, type PeriodPoint } from "@/components/PerfCharts";
import { monthKey, mondayOf, todayInSeoul } from "@/lib/date";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const LOOKBACK_DAYS = 90;

interface DailyRow {
  lang: string;
  day: string;
  views: number;
  estimated_minutes_watched: number;
  average_view_percentage: number;
  subscribers_gained: number;
}
interface ReportRow {
  lang: string;
  period_start: string;
  period_end: string;
  went_well: string[];
  went_bad: string[];
  improvements: string[];
  generated_at: string;
}
interface ShortRow {
  video_id: string;
  lang: string;
  snapshot_date: string;
  title: string | null;
  views: number;
  average_view_percentage: number;
  subscribers_gained: number;
}

const fmt = (n: number) => Math.round(n).toLocaleString("ko-KR");
const pctDelta = (cur: number, prev: number): number | null =>
  prev ? Math.round(((cur - prev) / prev) * 1000) / 10 : null;

function sinceDay(days: number): string {
  const today = todayInSeoul();
  const [y, m, d] = today.split("-").map(Number);
  const t = Date.UTC(y, (m ?? 1) - 1, d ?? 1) - days * 86400000;
  return new Date(t).toISOString().slice(0, 10);
}

// 일별 행을 기간 키로 합산(조회수 가중 시청률). period: 'week' → 월요일 키, 'month' → YYYY-MM.
function bucket(rows: DailyRow[], keyFn: (day: string) => string): PeriodPoint[] {
  const map = new Map<string, number>();
  for (const r of rows) {
    const k = keyFn(r.day);
    map.set(k, (map.get(k) ?? 0) + (r.views ?? 0));
  }
  return Array.from(map.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([period, views]) => ({ period, views }));
}

function DeltaBadge({ delta }: { delta: number | null }) {
  if (delta === null) return null;
  const up = delta >= 0;
  return (
    <span className="muted" style={{ color: up ? "#7fdca0" : "var(--warn)", marginLeft: 6 }}>
      {up ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}%
    </span>
  );
}

export default async function PerformanceReportPage() {
  const supabase = createClient();
  const since = sinceDay(LOOKBACK_DAYS);

  const [dailyRes, reportRes, shortsRes] = await Promise.all([
    supabase
      .from("youtube_analytics_daily")
      .select("lang, day, views, estimated_minutes_watched, average_view_percentage, subscribers_gained")
      .gte("day", since)
      .order("day"),
    supabase
      .from("performance_reports")
      .select("lang, period_start, period_end, went_well, went_bad, improvements, generated_at")
      .eq("period_type", "overall")
      .order("generated_at", { ascending: false }),
    supabase
      .from("youtube_analytics")
      .select("video_id, lang, snapshot_date, title, views, average_view_percentage, subscribers_gained")
      .order("snapshot_date", { ascending: false }),
  ]);

  const daily = (dailyRes.data as DailyRow[]) ?? [];
  const reports = (reportRes.data as ReportRow[]) ?? [];
  const shorts = (shortsRes.data as ShortRow[]) ?? [];

  const langs = Array.from(new Set(daily.map((r) => r.lang)));
  const today = todayInSeoul();
  const thisWeek = mondayOf(today);
  const lastWeek = mondayOf(sinceDay(7));
  const thisMonth = monthKey(today);
  const lastMonth = monthKey(sinceDay(28));

  // 최신 리포트(언어별 1건) + 최신 스냅샷 쇼츠(언어별) 매핑.
  const reportByLang = new Map<string, ReportRow>();
  for (const r of reports) if (!reportByLang.has(r.lang)) reportByLang.set(r.lang, r);

  return (
    <main className="container container--data">
      <div className="header">
        <h1>성과 리포트</h1>
        <span className="muted">최근 {LOOKBACK_DAYS}일 · 채널별 추이와 분석</span>
      </div>

      {langs.length === 0 ? (
        <div className="banner-warn" style={{ margin: "16px 0" }}>
          아직 시계열 데이터가 없습니다. 엔진에서 <code>python -m engine.analytics</code> 로 성과를
          수집한 뒤, <code>python -m engine.perf_report</code> 로 분석 리포트를 생성하면 채워집니다.
          선행조건(조회 스코프 OAuth 토큰)은 <code>docs/deviation-youtube-analytics.md</code> 참조.
        </div>
      ) : (
        langs.map((lang) => {
          const rows = daily.filter((r) => r.lang === lang);
          const dailyPoints: DailyPoint[] = rows.map((r) => ({
            day: r.day.slice(5), // MM-DD
            views: r.views ?? 0,
            subscribers_gained: r.subscribers_gained ?? 0,
          }));
          const weekly = bucket(rows, mondayOf).map((p) => ({ ...p, period: p.period.slice(5) }));
          const monthly = bucket(rows, monthKey);

          const sumWhere = (pred: (r: DailyRow) => boolean) =>
            rows.filter(pred).reduce((s, r) => s + (r.views ?? 0), 0);
          const todayViews = sumWhere((r) => r.day === today);
          const thisWeekViews = sumWhere((r) => mondayOf(r.day) === thisWeek);
          const lastWeekViews = sumWhere((r) => mondayOf(r.day) === lastWeek);
          const thisMonthViews = sumWhere((r) => monthKey(r.day) === thisMonth);
          const lastMonthViews = sumWhere((r) => monthKey(r.day) === lastMonth);
          const totalSubs = rows.reduce((s, r) => s + (r.subscribers_gained ?? 0), 0);

          const report = reportByLang.get(lang);

          // 최신 스냅샷의 상/하위 쇼츠.
          const langShorts = shorts.filter((s) => s.lang === lang);
          const latestSnap = langShorts[0]?.snapshot_date;
          const snapRows = langShorts
            .filter((s) => s.snapshot_date === latestSnap)
            .sort((a, b) => b.views - a.views);
          const best = snapRows.slice(0, 3);
          const worst = snapRows.length > 3 ? snapRows.slice(-3).reverse() : [];

          return (
            <div className="section" key={lang} style={{ marginTop: 28 }}>
              <div className="header" style={{ marginBottom: 10 }}>
                <h2 style={{ fontSize: 18 }}>{lang === "en" ? "🇬🇧 영어 채널" : "🇰🇷 한국어 채널"}</h2>
                <span className="muted">구독 전환 합계 +{fmt(totalSubs)}</span>
              </div>

              <div className="summary-strip">
                <div className="summary-tile">
                  <div className="n">{fmt(todayViews)}</div>
                  <div className="k">오늘 조회수</div>
                </div>
                <div className="summary-tile">
                  <div className="n">
                    {fmt(thisWeekViews)}
                    <DeltaBadge delta={pctDelta(thisWeekViews, lastWeekViews)} />
                  </div>
                  <div className="k">이번 주 조회수 (전주 대비)</div>
                </div>
                <div className="summary-tile">
                  <div className="n">
                    {fmt(thisMonthViews)}
                    <DeltaBadge delta={pctDelta(thisMonthViews, lastMonthViews)} />
                  </div>
                  <div className="k">이번 달 조회수 (전월 대비)</div>
                </div>
              </div>

              <PerfCharts daily={dailyPoints} weekly={weekly} monthly={monthly} />

              {report ? (
                <>
                  <div className="banner-ok" style={{ margin: "14px 0 8px" }}>
                    <strong>잘된 점</strong>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {report.went_well.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </div>
                  <div className="banner-warn" style={{ margin: "8px 0" }}>
                    <strong>잘못된 점</strong>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {report.went_bad.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </div>
                  <div className="card" style={{ margin: "8px 0" }}>
                    <h2 style={{ fontSize: 15 }}>개선 방향</h2>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {report.improvements.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                    <div className="muted" style={{ marginTop: 8 }}>
                      생성: {report.generated_at?.slice(0, 10)} · {report.period_start}~{report.period_end}
                    </div>
                  </div>
                </>
              ) : (
                <div className="banner-warn" style={{ margin: "12px 0" }}>
                  분석 리포트가 아직 없습니다. <code>python -m engine.perf_report</code> 를 실행하세요.
                </div>
              )}

              {best.length > 0 && (
                <div style={{ overflowX: "auto", marginTop: 8 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                    <thead>
                      <tr style={{ textAlign: "left", borderBottom: "1px solid #333" }}>
                        <th style={{ padding: "6px 8px" }}>구분</th>
                        <th style={{ padding: "6px 8px" }}>제목</th>
                        <th style={{ padding: "6px 8px", textAlign: "right" }}>조회수</th>
                        <th style={{ padding: "6px 8px", textAlign: "right" }}>시청률</th>
                        <th style={{ padding: "6px 8px", textAlign: "right" }}>구독</th>
                      </tr>
                    </thead>
                    <tbody>
                      {best.map((s) => (
                        <tr key={s.video_id} style={{ borderBottom: "1px solid #222" }}>
                          <td style={{ padding: "6px 8px", color: "#7fdca0" }}>상위</td>
                          <td style={{ padding: "6px 8px" }}>
                            <a href={`https://youtu.be/${s.video_id}`} target="_blank" rel="noreferrer">
                              {s.title || s.video_id}
                            </a>
                          </td>
                          <td style={{ padding: "6px 8px", textAlign: "right" }}>{fmt(s.views)}</td>
                          <td style={{ padding: "6px 8px", textAlign: "right" }}>{s.average_view_percentage.toFixed(0)}%</td>
                          <td style={{ padding: "6px 8px", textAlign: "right" }}>+{fmt(s.subscribers_gained)}</td>
                        </tr>
                      ))}
                      {worst.map((s) => (
                        <tr key={s.video_id} style={{ borderBottom: "1px solid #222" }}>
                          <td style={{ padding: "6px 8px", color: "var(--warn)" }}>하위</td>
                          <td style={{ padding: "6px 8px" }}>
                            <a href={`https://youtu.be/${s.video_id}`} target="_blank" rel="noreferrer">
                              {s.title || s.video_id}
                            </a>
                          </td>
                          <td style={{ padding: "6px 8px", textAlign: "right" }}>{fmt(s.views)}</td>
                          <td style={{ padding: "6px 8px", textAlign: "right" }}>{s.average_view_percentage.toFixed(0)}%</td>
                          <td style={{ padding: "6px 8px", textAlign: "right" }}>+{fmt(s.subscribers_gained)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })
      )}
    </main>
  );
}
