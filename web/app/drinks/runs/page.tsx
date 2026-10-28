// 주류 수집 실행 기록 (/drinks/runs, ?run=<id> 상세) — 정상 0건·성공·부분 성공·실패·실행 중단을 갈라 보여준다.
import Link from "next/link";

import { RetryButton } from "@/components/drinks/CollectControls";
import LoadProblem from "@/components/drinks/LoadProblem";
import RunPill, { fmtTime } from "@/components/drinks/RunPill";
import { ITEM_STATUS_LABEL, RUN_MODE_LABEL, canRetry, errorText, runSummary } from "@/lib/drinks/collect";
import { loadRun, loadRuns, RUN_LIST_LIMIT } from "@/lib/drinks/collectQueries";

export const dynamic = "force-dynamic";

type SP = { run?: string; source?: string; status?: string };

export default async function DrinksRunsPage(props: { searchParams: Promise<SP> }) {
  const sp = await props.searchParams;
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 수집 실행 기록</h1>
        <span className="muted"><Link href="/drinks/sources">수집원 →</Link></span>
      </div>
      {sp.run ? <RunDetailView id={sp.run} /> : <RunList sp={sp} />}
    </main>
  );
}

async function RunList({ sp }: { sp: SP }) {
  const v = await loadRuns(RUN_LIST_LIMIT, sp.source);
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const runs = sp.status ? v.data.runs.filter((r) => r.status === sp.status) : v.data.runs;
  return (
    <>
      <nav className="dk-tabs" aria-label="실행 상태">
        {[["", "전체"], ["failed", "실패"], ["partial", "부분 성공"], ["aborted", "실행 중단"], ["empty", "정상 0건"],
          ["succeeded", "성공"], ["running", "실행 중"], ["queued", "대기"]].map(([k, l]) => (
          <Link key={k} href={`/drinks/runs${k ? `?status=${k}` : ""}`} data-active={(sp.status ?? "") === k}>{l}</Link>
        ))}
      </nav>
      {v.truncated && <p className="banner-warn">전체 {v.data.total}건 중 최근 {v.data.runs.length}건만 보여줍니다.</p>}
      {runs.length === 0 ? (
        <p className="muted">{v.data.runs.length === 0 ? "실행 기록이 없습니다(정상 0건 — 아직 한 번도 돌지 않았습니다)." : "이 상태의 실행이 없습니다."}</p>
      ) : runs.map((r) => {
        const s = v.data.sources.get(r.source_id)!;
        return (
          <div key={r.id} className="list-row">
            <span>
              <RunPill r={r} /> <span className="pill">{RUN_MODE_LABEL[r.mode]}</span>{" "}
              <span className="pill">{r.requested_by === "schedule" ? "예약" : "운영자"}</span>{" "}
              <b>{s.name}</b> · <Link href={`/drinks/runs?run=${r.id}`}>{fmtTime(r.created_at)}</Link> — {runSummary(r)}
            </span>
            {canRetry(r) && s.state === "active" && <RetryButton sourceId={s.id} runId={r.id} failed={r.failed_count} />}
          </div>
        );
      })}
    </>
  );
}

async function RunDetailView({ id }: { id: string }) {
  const v = await loadRun(id);
  if (v.state === "not_found") return <p className="banner-warn">실행을 찾지 못했습니다.</p>;
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const { run: r, source: s, items, retryOf } = v.data;
  return (
    <section className="card">
      <div className="dk-row">
        <RunPill r={r} /> <span className="pill">{RUN_MODE_LABEL[r.mode]}</span>
        <span className="pill">{r.requested_by === "schedule" ? `예약 ${r.scheduled_for}` : "운영자 요청"}</span>
      </div>
      <h2 style={{ marginTop: 8 }}>{s.name}</h2>
      <p className="dk-kv">{runSummary(r)}</p>
      <p className="dk-kv">
        요청 {fmtTime(r.created_at)} · 시작 {fmtTime(r.started_at)} · 끝 {fmtTime(r.finished_at)} · 워커 {r.worker_id ?? "—"} ·
        외부 요청 <b>{r.request_count}</b>회 · 목록 {r.listed_count}건
      </p>
      <p className="dk-kv">
        워처마크: 시작 시점 <b>{fmtTime(r.cursor_from)}</b> → {r.cursor_to ? <>새 값 <b>{fmtTime(r.cursor_to)}</b></> : <b>그대로(성공한 수집 실행만 올립니다)</b>}
        {r.limits && <> · 상한 문서 {r.limits.max_items} · 본문 {r.limits.max_bodies} · 요청 {r.limits.max_requests} · 간격 {r.limits.interval_sec}초</>}
      </p>
      {r.error_code && <p className={r.status === "failed" ? "banner-block" : "banner-warn"}>{errorText(r.error_code)} — {r.error_message}</p>}
      {retryOf && <p className="dk-kv">재시도 대상: <Link href={`/drinks/runs?run=${retryOf.id}`}>{fmtTime(retryOf.created_at)} 실행</Link> (실패 문서 {r.retry_urls.length}건)</p>}
      {canRetry(r) && s.state === "active" && <RetryButton sourceId={s.id} runId={r.id} failed={r.failed_count} />}
      <h3 style={{ fontSize: 14 }}>문서 {items.length}건</h3>
      {items.length === 0 && <p className="muted">기록된 문서가 없습니다.</p>}
      {items.map((it) => (
        <div key={it.id} className="list-row">
          <span>
            <span className={it.status === "failed" ? "pill dk-bad" : it.status === "skipped" ? "pill dk-warn" : "pill"}>
              {ITEM_STATUS_LABEL[it.status]}</span>{" "}
            <a href={it.canonical_url} target="_blank" rel="noreferrer noopener">{it.title || it.canonical_url}</a>
            {it.body_chars !== null && <span className="muted"> · 본문 {it.body_chars.toLocaleString()}자</span>}
            {it.same_body_count > 0 && <span className="pill dk-warn"> 같은 본문 다른 URL {it.same_body_count}</span>}
            {it.error_code && <span className="muted"> · {errorText(it.error_code)}{it.http_status ? ` (HTTP ${it.http_status})` : ""}</span>}
          </span>
        </div>
      ))}
    </section>
  );
}
