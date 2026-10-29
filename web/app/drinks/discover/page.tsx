// 주류 소재 발견함 (/drinks/discover) — 커뮤니티·SNS 에서 사람들이 묻는 것. 사실 근거가 아니라 관심 신호다.
// ★ 후보는 규칙(discovery-v1)이 묶은 임시 제안. 플랫폼 지표는 합산하지 않고, 미제공 지표는 "미제공"으로 둔다.
import Link from "next/link";

import { CandidateActions, DiscoverySourceForm, ManualDiscoveryForm, ReopenCandidate } from "@/components/drinks/DiscoveryControls";
import LoadProblem from "@/components/drinks/LoadProblem";
import RunPill, { fmtTime } from "@/components/drinks/RunPill";
import { errorText } from "@/lib/drinks/collect";
import {
  CHANNEL_STATE_LABEL, CHANNELS, COVERAGE_LABEL, PLATFORM_LABEL, SIGNAL_LABEL, interestText, metricText, type DiscoveryItemRow,
} from "@/lib/drinks/discovery";
import { loadDiscovery } from "@/lib/drinks/discoveryQueries";
import { SOURCE_STATE_LABEL } from "@/lib/drinks/collect";

export const dynamic = "force-dynamic";

const TABS = { suggested: "열린 후보", promoted: "소재로 올림", dismissed: "기각", merged: "합쳐짐" } as const;
type Tab = keyof typeof TABS;

function ItemLine({ it }: { it: DiscoveryItemRow }) {
  return (
    <div className="list-row">
      <span>
        <span className="pill">{PLATFORM_LABEL[it.platform] ?? it.platform}</span>{" "}
        <span className={it.collection_status === "manual" ? "pill dk-warn" : "pill"}>{it.collection_status === "manual" ? "수동" : "수집"}</span>{" "}
        <a href={it.canonical_url} target="_blank" rel="noreferrer noopener">{it.title || it.canonical_url}</a>
        <span className="muted"> · {it.channel_name ?? "채널 미상"} · {COVERAGE_LABEL[it.coverage]} · 게시 {it.posted_at ? it.posted_at.slice(0, 10) : "모름"}
          {" "}· 발견 {it.discovered_at.slice(0, 10)} · {metricText(it.latest_metrics, it.metrics_observed_at)}
          {it.origin_group && ` · 원출처 묶음 ${it.origin_group}`} · 권리 {it.rights_status === "unknown" ? "미확인" : it.rights_status}</span>
        {it.questions.length > 0 && <span className="muted"><br />질문: {it.questions.slice(0, 2).join(" / ")}</span>}
        {it.operator_note && <span className="muted"><br />메모: {it.operator_note}</span>}
      </span>
    </div>
  );
}

export default async function DrinksDiscoverPage(props: { searchParams: Promise<{ tab?: string }> }) {
  const sp = await props.searchParams;
  const tab: Tab = sp.tab && sp.tab in TABS ? (sp.tab as Tab) : "suggested";
  const v = await loadDiscovery(tab);
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 소재 발견함</h1>
        <span className="muted">사람들이 실제로 묻는 것 — 사실 근거가 아닙니다 · <Link href="/drinks/sources">수집원</Link> · <Link href="/drinks/runs">실행 기록</Link> · <Link href="/drinks/trends">커뮤니티 동향·이슈</Link></span>
      </div>
      <section className="section">
        <h3>채널 연결 상태</h3>
        {CHANNELS.map((c) => (
          <div key={c.platform} className="list-row">
            <span><b>{PLATFORM_LABEL[c.platform] ?? (c.platform === "naver" ? "네이버" : c.platform)}</b> <span className="muted">— {c.how} · 확보 범위: {c.coverage} · {c.why}</span></span>
            <span className={c.state === "live" ? "pill dk-ok" : "pill dk-warn"}>{CHANNEL_STATE_LABEL[c.state]}</span>
          </div>
        ))}
      </section>
      <ManualDiscoveryForm />
      <DiscoverySourceForm />
      {v.state !== "ok" ? (
        <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />
      ) : (
        <>
          {v.data.sources.length > 0 && (
            <section className="section">
              <h3>발견 수집원</h3>
              {v.data.sources.map((s) => {
                const r = v.data.lastRun.get(s.id);
                return (
                  <div key={s.id} className="list-row">
                    <span><b>{s.name}</b> <span className="muted">— {SOURCE_STATE_LABEL[s.state]} · 검색어 {((s.parser_config.queries as string[]) ?? []).join(", ")}</span></span>
                    <span>{r ? <><RunPill r={r} /> {fmtTime(r.finished_at)} {r.error_code && <span className="muted">{errorText(r.error_code)}</span>}</> : <span className="muted">실행 기록 없음</span>}</span>
                  </div>
                );
              })}
            </section>
          )}
          <nav className="dk-tabs" aria-label="후보 상태">
            {(Object.keys(TABS) as Tab[]).map((k) => (
              <Link key={k} href={`/drinks/discover?tab=${k}`} data-active={k === tab}>{TABS[k]}</Link>
            ))}
          </nav>
          {v.truncated && <p className="banner-warn">전체 {v.data.candidateTotal}건 중 점수 높은 {v.data.candidates.length}건만 보여줍니다.</p>}
          {v.data.candidates.length === 0 && <p className="muted">이 상태의 후보가 없습니다(정상 0건).</p>}
          {v.data.candidates.map((c) => {
            const items = v.data.itemsByCandidate.get(c.id) ?? [];
            const others = tab === "suggested" ? v.data.candidates.filter((o) => o.id !== c.id) : [];
            return (
              <article key={c.id} className="card">
                <div className="dk-row">
                  <span className="status-pill">임시 {c.provisional_score ?? "—"}점 ({c.rubric})</span>
                  {c.signals.map((s) => <span key={s} className="pill">{SIGNAL_LABEL[s] ?? s}</span>)}
                  {c.duplicate_topic_ids.length > 0 && <span className="pill dk-warn">비슷한 기존 소재 {c.duplicate_topic_ids.length}</span>}
                </div>
                <h2 style={{ marginTop: 8 }}>Q(원문). {c.key_question}</h2>
                <p className="dk-kv">독자 효용: <b>{c.reader_value ?? "—"}</b> · 영상 적합 <b>{c.fit_video ?? "—"}</b> · 카드 적합 <b>{c.fit_carousel ?? "—"}</b></p>
                <p className="dk-kv">관심 신호: {interestText(c.interest)}</p>
                <p className="dk-kv">발견 경로: {c.discovery_path ?? "—"}</p>
                {c.first_scene && <p className="dk-kv">첫 장면: {c.first_scene}</p>}
                <p className="dk-kv">추가로 확인할 사실: {c.facts_to_check.join(" · ") || "—"}</p>
                <p className="muted">{c.score_reason}</p>
                {c.duplicate_topic_ids.length > 0 && (
                  <p className="dk-kv">중복 후보 소재: {c.duplicate_topic_ids.map((id) => {
                    const t = v.data.topics.find((x) => x.id === id);
                    return <span key={id}><Link href={`/drinks/review/${id}`}>{t?.title ?? "소재"}</Link>{" "}</span>;
                  })}</p>
                )}
                <details><summary className="muted">발견 자료 {items.length}건(원문 링크)</summary>{items.map((it) => <ItemLine key={it.id} it={it} />)}</details>
                {c.status === "suggested" && <CandidateActions c={c} others={others} />}
                {c.status === "promoted" && c.promoted_topic_id && <p>→ <Link href={`/drinks/review/${c.promoted_topic_id}`}>올린 소재 보기</Link></p>}
                {c.status === "dismissed" && <p className="muted">기각 사유: {c.decision_reason} <ReopenCandidate id={c.id} version={c.version} /></p>}
              </article>
            );
          })}
          <section className="section">
            <h3>아직 후보에 묶이지 않은 자료 ({v.data.loose.length})</h3>
            <p className="muted">질문·신호가 없는 자료는 후보로 묶지 않습니다. 수동 등록 자료는 다음 실행 때 묶입니다.</p>
            {v.data.loose.length === 0 ? <p className="muted">없음</p> : v.data.loose.slice(0, 100).map((it) => <ItemLine key={it.id} it={it} />)}
          </section>
        </>
      )}
    </main>
  );
}
