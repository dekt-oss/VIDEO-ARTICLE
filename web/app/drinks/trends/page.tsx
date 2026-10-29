// 주류 동향 (/drinks/trends) — 술 커뮤니티에서 많이 언급된 술(최근 7일) + 주류 이슈(최근 14일). 읽기 전용.
// ★ 신호일 뿐 사실 근거가 아니다. 반응 점수는 Jev 가 검색 요약만 보고 낸 판정이고, 못 한 것은 '판정 없음'이다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import { CATEGORY_LABEL } from "@/lib/drinks/model";
import {
  NEGATIVE_BELOW, POSITIVE_ABOVE, safeHref, scoreText, sentimentBar, sentimentLabel, type TrendIssueRow, type TrendProductRow,
} from "@/lib/drinks/trends";
import { loadTrends } from "@/lib/drinks/trendsQueries";

export const dynamic = "force-dynamic";

const day = (t: string | null) => (t ? new Date(t).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" }) : "날짜 모름");

function ReactionCell({ r }: { r: TrendProductRow }) {
  const bar = sentimentBar(r);
  if (bar.none) return <span className="muted">판정 없음 <span className="pill">언급 {r.mentions}</span></span>;
  return (
    <div style={{ minWidth: 190 }}>
      <div
        role="img"
        aria-label={`긍정 ${r.positive} · 부정 ${r.negative} · 판정 ${r.judged}건`}
        style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: "var(--border)" }}
      >
        <span style={{ width: `${bar.positivePct}%`, background: "#50c878" }} />
        <span style={{ width: `${bar.neutralPct}%`, background: "transparent" }} />
        <span style={{ width: `${bar.negativePct}%`, background: "var(--danger)" }} />
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
        평균 {scoreText(r.avg_sentiment)} ({sentimentLabel(r.avg_sentiment)}) · 긍정 {r.positive} · 부정 {r.negative} · 판정 {r.judged}/{r.mentions}
      </div>
    </div>
  );
}

function ProductTable({ rows }: { rows: TrendProductRow[] }) {
  if (rows.length === 0) {
    return <p className="muted">최근 7일에 사전에 있는 제품을 언급한 커뮤니티 글이 없습니다. (수집 전이거나, 사전에 없는 제품만 나왔을 수 있습니다)</p>;
  }
  return (
    <div className="table-scroll">
      <table className="grid">
        <thead>
          <tr><th>제품</th><th>주종</th><th className="num">언급 글 수</th><th>긍정/부정</th><th>마지막 언급</th><th>예시 글</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.product}>
              <td><b>{r.product}</b></td>
              <td>{CATEGORY_LABEL[r.category] ?? r.category}</td>
              <td className="num">{r.posts}</td>
              <td><ReactionCell r={r} /></td>
              <td className="muted">{day(r.last_seen)}</td>
              <td>
                {(r.sample_urls ?? []).map((u, i) => {
                  const href = safeHref(u);
                  const title = r.sample_titles?.[i] ?? `글 ${i + 1}`;
                  return href ? (
                    <div key={u}><a href={href} target="_blank" rel="noreferrer noopener" title={title}>{title.length > 28 ? `${title.slice(0, 28)}…` : title}</a></div>
                  ) : null;
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IssueList({ rows }: { rows: TrendIssueRow[] }) {
  if (rows.length === 0) return <p className="muted">최근 14일에 모은 주류 이슈 기사가 없습니다.</p>;
  return (
    <div>
      {rows.map((i) => {
        const href = safeHref(i.canonical_url);
        return (
          <div key={i.id} className="list-row">
            <span>
              {href ? <a href={href} target="_blank" rel="noreferrer noopener">{i.title}</a> : i.title}
              <span className="muted"> · {day(i.posted_at ?? i.collected_at)} · {i.channel_name ?? "출처 미상"}{i.query && ` · 검색어 ${i.query}`}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default async function DrinksTrendsPage() {
  const v = await loadTrends();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 커뮤니티 동향·이슈</h1>
        <span className="muted">소재 신호일 뿐 사실 근거가 아닙니다 · <Link href="/drinks/discover">소재 발견함</Link> · <Link href="/drinks/runs">실행 기록</Link></span>
      </div>
      {v.state === "missing" ? (
        <div className="banner-block" role="alert">
          <b>0059 가 운영 DB 에 아직 없습니다.</b>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            동향 표(drink_trend_*)가 없어 이 화면은 비어 있습니다. 0건이 아니라 적용 전입니다 — 운영자가 승인해 0059_drinks_trends.sql 을 적용하면 보입니다.
          </p>
        </div>
      ) : v.state !== "ok" ? (
        <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />
      ) : (
        <>
          <section className="section">
            <h3>커뮤니티에서 많이 언급된 술 (최근 7일)</h3>
            <p className="muted" style={{ fontSize: 13 }}>
              술 전문 카페 글의 제목·검색 요약에서 제품 사전에 있는 이름을 찾아 센 것입니다(본문 전문 아님, 사전에 없는 제품은 안 잡힘).
              반응은 Jev 가 &quot;글쓴이가 좋게 말하나&quot;를 판정한 점수(-1~1)이며 +{POSITIVE_ABOVE} 초과를 긍정, {NEGATIVE_BELOW} 미만을 부정으로 셉니다.
              판정하지 못한 글은 &apos;판정 없음&apos;으로 남고 평균에서 빠집니다.
            </p>
            <ProductTable rows={v.data.products} />
          </section>
          <section className="section">
            <h3>주류 이슈 (최근 14일)</h3>
            <p className="muted" style={{ fontSize: 13 }}>제품이 아니라 세금·규제·가격·수입·업계 소식입니다(네이버 뉴스 검색 결과 제목).</p>
            <IssueList rows={v.data.issues} />
          </section>
        </>
      )}
    </main>
  );
}
