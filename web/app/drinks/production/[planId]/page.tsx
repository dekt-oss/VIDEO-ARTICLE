// 주류 제작안 하나의 제작 (/drinks/production/[planId]) — 렌더 요청·진행·실패·재시도, 파일 묶음 미리보기, 최종 파일 검수.
// ★ 지금 렌더는 로컬·무료(대체 이미지 + 무료 TTS)다. 흐름 검증용이며 목표 화풍 품질이 아니다. 유료 생성은 예산 미설정으로 꺼져 있다.
import Link from "next/link";

import { CancelRender, OutputReview, RenderRequest } from "@/components/drinks/ProductionControls";
import LoadProblem from "@/components/drinks/LoadProblem";
import { fmtTime } from "@/components/drinks/RunPill";
import { FORMAT_LABEL, VERSION_STATUS_LABEL, type Format } from "@/lib/drinks/model";
import { loadPlanProduction } from "@/lib/drinks/productionQueries";

export const dynamic = "force-dynamic";

const JOB_LABEL = { queued: "대기", running: "렌더 중", succeeded: "파일 생성됨", failed: "실패", canceled: "취소" } as const;
const REVIEW_LABEL = { pending: "검수 대기", approved: "파일 승인", changes_requested: "고칠 점 있음", blocked: "차단" } as const;
const BLOCK_TEXT: Record<string, string> = {
  plan_not_approved: "제작안이 승인 상태가 아님", plan_blocked: "제작안 차단(근거 철회·권리 변경)", evidence_invalid: "근거를 지금 쓸 수 없음",
  not_found: "제작안 없음",
};

export default async function PlanProductionPage(props: { params: Promise<{ planId: string }> }) {
  const { planId } = await props.params;
  const v = await loadPlanProduction(planId);
  if (v.state === "not_found") return <main className="container"><p className="banner-warn">제작안을 찾지 못했습니다.</p></main>;
  if (v.state !== "ok") return <main className="container"><LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} /></main>;
  const { plan, topic, review, renderable, jobs, manifests, costs } = v.data;
  const f = plan.format as Format;
  const active = jobs.find((j) => j.status === "queued" || j.status === "running");
  const lastFailed = jobs.find((j) => j.status === "failed" || j.status === "canceled");
  const total = costs.reduce((s, c) => s + Number(c.cost_usd), 0);
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 {FORMAT_LABEL[f]} 제작</h1>
        <span className="muted"><Link href="/drinks/production">← 제작</Link> · <Link href={`/drinks/review/${topic.id}?tab=${f}`}>제작안 보기</Link></span>
      </div>
      <section className="card">
        <h2>{topic.title}</h2>
        <p className="dk-kv">제작안 버전 <b>{plan.revision_no}</b> ({VERSION_STATUS_LABEL[plan.plan_status]}) · 근거 버전 <b>{review.revision_no}</b>{" "}
          {review.currently_valid === false ? <span className="dk-bad">· 근거 지금 사용 불가</span> : <span className="dk-ok">· 근거 유효</span>}</p>
        <p className="banner-info">지금 렌더는 <b>로컬·무료</b>입니다 — 대체 이미지(장면 유형 표기 카드)와 무료 TTS 로 흐름을 확인합니다. 목표 화풍(3D 도해·실사감)은
          유료 생성이 필요하고, 예산이 정해지지 않아 꺼져 있습니다.</p>
        {renderable ? (
          <p className="banner-block">렌더할 수 없습니다 — {BLOCK_TEXT[renderable] ?? renderable}</p>
        ) : active ? (
          <p className="dk-kv">진행 중: {JOB_LABEL[active.status]} (시도 {active.attempt_no}) {active.status === "queued" && <CancelRender jobId={active.id} />}
            {active.status === "running" && <CancelRender jobId={active.id} />}</p>
        ) : (
          <div className="actions">
            <RenderRequest planId={plan.id} label={manifests.length ? "다시 렌더" : "렌더 요청"} />
            {lastFailed && <RenderRequest planId={plan.id} retryOf={lastFailed.id} label="실패한 작업 재시도" />}
          </div>
        )}
        <p className="muted">비용 합계(이 제작안): ${total.toFixed(4)} — 공급자·모델별 기록 {costs.length}건</p>
      </section>

      <section className="section">
        <h3>제작 작업</h3>
        {jobs.length === 0 ? <p className="muted">아직 요청한 렌더가 없습니다.</p> : jobs.map((j) => (
          <div key={j.id} className="list-row">
            <span>
              <span className={j.status === "failed" ? "pill dk-bad" : j.status === "succeeded" ? "pill dk-ok" : "pill"}>{JOB_LABEL[j.status]}</span>{" "}
              시도 {j.attempt_no} · {j.renderer}({j.renderer_version}) · 요청 {fmtTime(j.created_at)} · 끝 {fmtTime(j.finished_at)}
              {j.error_code && <span className="muted"> · {j.error_code}: {j.error_message}</span>}
            </span>
          </div>
        ))}
      </section>

      <section className="section">
        <h3>파일 묶음(불변)</h3>
        <p className="muted">다시 렌더해 파일이 달라지면 새 묶음이 생기고 옛 묶음·판정은 그대로 남습니다. 제작안이 같아 파일이 똑같이 나오면 같은 묶음으로 합쳐집니다 —
          고칠 점이 있으면 제작안을 새 버전으로 고친 뒤 렌더하세요.</p>
        {manifests.length === 0 && <p className="muted">아직 만들어진 파일이 없습니다.</p>}
        {manifests.map((m) => (
          <article key={m.manifest.id} className="card">
            <div className="dk-row">
              {m.review && <span className={m.review.status === "approved" ? "pill dk-ok" : m.review.status === "blocked" ? "pill dk-bad" : "pill dk-warn"}>
                {REVIEW_LABEL[m.review.status]}</span>}
              {m.review?.status === "approved" && !m.currentlyUsable && <span className="pill dk-bad">지금 사용 불가 — {BLOCK_TEXT[m.currentBlock ?? ""] ?? m.currentBlock}</span>}
              <span className="pill">묶음 {m.manifest.manifest_hash.slice(0, 10)}</span>
              <span className="muted">{fmtTime(m.manifest.created_at)}</span>
            </div>
            {m.review?.reason && <p className="muted">{m.review.reason}</p>}
            {Array.isArray((m.review?.qa_summary as { warnings?: string[] })?.warnings) && ((m.review!.qa_summary as { warnings: string[] }).warnings.length > 0) && (
              <p className="banner-warn">기계 검사 경고: {(m.review!.qa_summary as { warnings: string[] }).warnings.join(", ")}</p>
            )}
            <div className="dk-row" style={{ alignItems: "flex-start" }}>
              {m.files.map((file) => (
                <div key={file.id} style={{ maxWidth: f === "video" ? 260 : 200 }}>
                  <div className="muted">{file.role === "page" ? `${file.position}쪽` : file.role === "final_video" ? "최종 영상" : "커버"}
                    {file.width ? ` · ${file.width}×${file.height}` : ""}{file.duration_ms ? ` · ${(file.duration_ms / 1000).toFixed(1)}초` : ""}</div>
                  {file.url ? (
                    file.mime === "video/mp4"
                      ? <video src={file.url} controls style={{ width: "100%" }} />
                      // eslint-disable-next-line @next/next/no-img-element
                      : <img src={file.url} alt={`${file.role} ${file.position}`} style={{ width: "100%" }} />
                  ) : (
                    <p className="muted">로컬 저장({file.storage_key.replace(/^local:/, "")}) — 브라우저 미리보기 불가</p>
                  )}
                  {file.url && <a href={file.url} download>다운로드</a>}
                  <div className="muted" style={{ fontSize: 11 }}>sha256 {file.sha256.slice(0, 12)} · {file.state}</div>
                </div>
              ))}
            </div>
            {m.review && <OutputReview review={m.review} format={f} usableNow={!m.currentBlock} />}
          </article>
        ))}
      </section>
    </main>
  );
}
