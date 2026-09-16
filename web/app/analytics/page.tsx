// 유튜브 쇼츠 성과 뷰 (engine/analytics.py 가 채운 youtube_analytics 스냅샷을 읽음).
// 최근 스냅샷일의 쇼츠별 조회수·평균 시청 지속률·좋아요·구독전환을 언어(채널)별로 보여준다.
// 읽기 전용 — 업로드(⑥ 렌더 결과)와 별개 흐름. 데이터가 없으면 수집 방법을 안내한다.
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

interface Row {
  video_id: string;
  lang: string;
  snapshot_date: string;
  title: string | null;
  published_at: string | null;
  views: number;
  average_view_percentage: number;
  average_view_duration_sec: number;
  likes: number;
  comments: number;
  shares: number;
  subscribers_gained: number;
  ctr_percent: number | null;
}

function fmt(n: number): string {
  return n.toLocaleString("ko-KR");
}

export default async function AnalyticsPage() {
  const supabase = createClient();

  // 가장 최근 스냅샷일을 찾고 그 날짜의 행만 보여준다(일 단위 최신값).
  const { data: latest } = await supabase
    .from("youtube_analytics")
    .select("snapshot_date")
    .order("snapshot_date", { ascending: false })
    .limit(1)
    .maybeSingle();

  const snapshotDate = latest?.snapshot_date as string | undefined;

  let rows: Row[] = [];
  if (snapshotDate) {
    const { data } = await supabase
      .from("youtube_analytics")
      .select(
        "video_id, lang, snapshot_date, title, published_at, views, average_view_percentage, average_view_duration_sec, likes, comments, shares, subscribers_gained, ctr_percent"
      )
      .eq("snapshot_date", snapshotDate)
      .order("views", { ascending: false });
    rows = (data as Row[]) ?? [];
  }

  const byLang = new Map<string, Row[]>();
  for (const r of rows) {
    if (!byLang.has(r.lang)) byLang.set(r.lang, []);
    byLang.get(r.lang)!.push(r);
  }

  return (
    <main className="container container--data">
      <div className="header">
        <h1>유튜브 쇼츠 성과</h1>
        <span className="muted">{snapshotDate ? `스냅샷 ${snapshotDate}` : "데이터 없음"}</span>
      </div>

      {rows.length === 0 ? (
        <div className="banner-warn" style={{ margin: "16px 0" }}>
          아직 수집된 성과가 없습니다. 엔진에서{" "}
          <code>python -m engine.analytics</code> 를 실행하면 최근{" "}
          {"7"}일 쇼츠 성과가 채워집니다. 선행조건(조회 스코프 OAuth 토큰)은{" "}
          <code>docs/deviation-youtube-analytics.md</code> 참조.
        </div>
      ) : (
        Array.from(byLang.entries()).map(([lang, langRows]) => {
          const totalViews = langRows.reduce((s, r) => s + r.views, 0);
          const totalSubs = langRows.reduce((s, r) => s + r.subscribers_gained, 0);
          const avgPct =
            langRows.length > 0
              ? langRows.reduce((s, r) => s + r.average_view_percentage, 0) / langRows.length
              : 0;
          return (
            <div className="section" key={lang} style={{ marginTop: 20 }}>
              <div className="header" style={{ marginBottom: 8 }}>
                <h2 style={{ fontSize: 18 }}>{lang === "en" ? "🇬🇧 영어 채널" : "🇰🇷 한국어 채널"}</h2>
                <span className="muted">
                  쇼츠 {langRows.length}편 · 조회 {fmt(totalViews)} · 평균 시청 {avgPct.toFixed(1)}% · 구독 +{fmt(totalSubs)}
                </span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                  <thead>
                    <tr style={{ textAlign: "left", borderBottom: "1px solid #333" }}>
                      <th style={{ padding: "6px 8px" }}>제목</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>조회수</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>평균 시청률</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>평균 시청(초)</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>CTR</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>좋아요</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>댓글</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>공유</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>구독 전환</th>
                    </tr>
                  </thead>
                  <tbody>
                    {langRows.map((r) => (
                      <tr key={r.video_id} style={{ borderBottom: "1px solid #222" }}>
                        <td style={{ padding: "6px 8px" }}>
                          <a
                            href={`https://youtu.be/${r.video_id}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {r.title || r.video_id}
                          </a>
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{fmt(r.views)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {r.average_view_percentage.toFixed(1)}%
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {r.average_view_duration_sec.toFixed(0)}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {r.ctr_percent == null ? "—" : `${r.ctr_percent.toFixed(1)}%`}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{fmt(r.likes)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{fmt(r.comments)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>{fmt(r.shares)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          +{fmt(r.subscribers_gained)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })
      )}
    </main>
  );
}
