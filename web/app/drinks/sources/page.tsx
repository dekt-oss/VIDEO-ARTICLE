// 주류 수집원 (/drinks/sources) — 수집원 등록부. 제안 → 검증 → 활성, 일시 중지·종료. 명세 §5·§13-B.
// ★ 자동 활성화 없음. 활성화는 이용 조건 확인 + 최근 검증 실행 성공 + 활성 12개 이하일 때 사람이 누른다(DB 가 다시 막음).
import Link from "next/link";

import { RetryButton, SourceActionBar, SourceRegisterForm } from "@/components/drinks/CollectControls";
import LoadProblem from "@/components/drinks/LoadProblem";
import RunPill, { fmtTime as fmt } from "@/components/drinks/RunPill";
import { CATEGORY_LABEL, RIGHTS_LABEL } from "@/lib/drinks/model";
import {
  METHOD_LABEL, RUN_MODE_LABEL, SOURCE_STATE_LABEL, TERMS_LABEL, canRetry, runSummary,
} from "@/lib/drinks/collect";
import { loadSources } from "@/lib/drinks/collectQueries";

export const dynamic = "force-dynamic";

export default async function DrinksSourcesPage() {
  const v = await loadSources();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 수집원</h1>
        <span className="muted">승인한 출처만 수집합니다 · <Link href="/drinks/runs">실행 기록 →</Link></span>
      </div>
      {v.state !== "ok" ? (
        <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />
      ) : (
        <>
          <p className="dk-kv">
            활성 <b>{v.data.activeCount}</b> / 상한 <b>{v.data.limits.max_active_sources}</b> · 실행 1회 문서 상한{" "}
            <b>{v.data.limits.max_items_ceiling}</b> · 본문 상한 <b>{v.data.limits.max_bodies_ceiling}</b> · 수집원당 24시간{" "}
            <b>{v.data.limits.runs_per_day}</b>회 · 요청 간격 최소 <b>{v.data.limits.min_interval_sec}</b>초
          </p>
          <SourceRegisterForm />
          {v.data.sources.length === 0 && <p className="muted">등록된 수집원이 없습니다(정상 0건).</p>}
          {v.data.sources.map((s) => {
            const runs = v.data.runs.get(s.id) ?? [];
            const lastVal = v.data.lastValidation.get(s.id) ?? null;
            return (
              <article key={s.id} className="card">
                <div className="dk-row">
                  <span className="status-pill">{SOURCE_STATE_LABEL[s.state]}</span>
                  <span className={s.terms_status === "verified" ? "pill" : "pill dk-warn"}>{TERMS_LABEL[s.terms_status]}</span>
                  <span className="pill">{METHOD_LABEL[s.method]}</span>
                  {s.categories.map((c) => <span key={c} className="pill">{CATEGORY_LABEL[c]}</span>)}
                  <span className="pill">{s.language}</span>
                </div>
                <h2 style={{ marginTop: 8 }}>{s.name}</h2>
                <p className="dk-kv">
                  {s.publisher ?? "발행처 미기재"} · <a href={s.home_url} target="_blank" rel="noreferrer noopener">{s.home_url}</a>
                  {s.state_reason && <> · 상태 사유: {s.state_reason}</>}
                </p>
                <p className="dk-kv">
                  허용 호스트 <b>{s.allowed_hosts.join(", ") || "—"}</b> · 수집 주소 <b>{s.entry_urls.length}</b>개 · 파서 {s.parser_version} ·
                  간격 {s.request_interval_sec}초 · 문서 {s.max_items_per_run} · 본문 {s.max_bodies_per_run} · 문서 기본 사용 조건{" "}
                  {RIGHTS_LABEL[s.rights_default as keyof typeof RIGHTS_LABEL] ?? s.rights_default}
                </p>
                <p className="dk-kv">
                  이용 조건: {s.terms_note ?? "요지 없음"}{s.terms_checked_at && ` (확인 ${s.terms_checked_at})`}
                  {s.terms_url && <> · <a href={s.terms_url} target="_blank" rel="noreferrer noopener">원문</a></>}
                  {s.robots_note && <> · robots: {s.robots_note}</>}
                </p>
                <p className="dk-kv">
                  워처마크(마지막 완전 성공 수집) <b>{fmt(s.watermark_at)}</b> · 마지막 검증{" "}
                  {lastVal ? <><RunPill r={lastVal} /> {fmt(lastVal.finished_at)}</> : "없음"}
                </p>
                {s.entry_urls.length > 0 && (
                  <details><summary className="muted">수집 주소</summary>
                    <ul>{s.entry_urls.map((u) => <li key={u}><a href={u} target="_blank" rel="noreferrer noopener">{u}</a></li>)}</ul>
                  </details>
                )}
                <SourceActionBar s={s} lastValidation={lastVal?.status ?? null} />
                <h3 style={{ fontSize: 14 }}>최근 실행</h3>
                {runs.length === 0 ? <p className="muted">실행 기록 없음</p> : runs.map((r) => (
                  <div key={r.id} className="list-row">
                    <span>
                      <RunPill r={r} /> <span className="pill">{RUN_MODE_LABEL[r.mode]}</span>{" "}
                      <Link href={`/drinks/runs?run=${r.id}`}>{fmt(r.created_at)}</Link> — {runSummary(r)}
                    </span>
                    {canRetry(r) && s.state === "active" && <RetryButton sourceId={s.id} runId={r.id} failed={r.failed_count} />}
                  </div>
                ))}
              </article>
            );
          })}
        </>
      )}
    </main>
  );
}
