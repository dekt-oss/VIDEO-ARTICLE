// 주류 제작안 하나의 제작 (/drinks/production/[planId]) — 렌더 요청·진행·실패·재시도, 파일 묶음 미리보기, 최종 파일 검수.
// ★ 렌더 요청은 로컬·무료(대체 이미지 + 무료 TTS)다. 유료 렌더는 이 제작안 전용 결재(0054)가 있을 때만 큐에 들어가고,
//   그림마다 DB 가 결재 금액 안인지 잰다(drinks_hold_spend). 화면은 결재를 열고 닫고 요청할 뿐 돈을 쓰지 못한다.
import Link from "next/link";

import { CancelRender, CloseSpendApproval, OpenSpendApproval, OutputReview, PaidRenderRequest, RenderRequest } from "@/components/drinks/ProductionControls";
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
  const { plan, topic, review, renderable, jobs, manifests, costs, spend } = v.data;
  const f = plan.format as Format;
  const active = jobs.find((j) => j.status === "queued" || j.status === "running");
  const lastFailed = jobs.find((j) => j.status === "failed" || j.status === "canceled");
  const total = costs.reduce((s, c) => s + Number(c.cost_usd), 0);
  const estimate = Number(spend.estimate.total_usd);
  const scenes = ((plan.plan_json as { scenes?: { visual_role?: string; visual_prompt?: string | null }[] }).scenes ?? []);
  const noPrompt = scenes.map((s, i) => ({ s, i: i + 1 })).filter(({ s }) => (s.visual_role ?? "reality") !== "text_card" && !s.visual_prompt?.trim())
    .map(({ i }) => i);
  const cardPages = spend.estimate.pages ?? [];   // 사진형 카드뉴스의 쪽별 그림 예상(0056)
  const showPaid = f === "video" || cardPages.length > 0;
  const openApproval = spend.approvals.find((a) => a.status === "open" && !a.expired);
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
        <p className="banner-info"><b>렌더 요청</b>은 로컬·무료입니다 — 대체 이미지(장면 유형 표기 카드)와 무료 TTS 로 흐름을 확인합니다. 목표 화풍(3D 도해·무광 CG)
          그림은 <b>유료 렌더</b>로만 나오고, 결재(아래)가 있어야 하며 결재 금액이 상한입니다.</p>
        {renderable ? (
          <p className="banner-block">렌더할 수 없습니다 — {BLOCK_TEXT[renderable] ?? renderable}</p>
        ) : active ? (
          <p className="dk-kv">진행 중: {JOB_LABEL[active.status]} (시도 {active.attempt_no}) <CancelRender jobId={active.id} />
            {active.cancel_requested && <span className="muted"> · 취소 요청됨(워커가 다음 확인 때 멈춥니다)</span>}</p>
        ) : (
          <div className="actions">
            <RenderRequest planId={plan.id} label={manifests.length ? "다시 렌더" : "렌더 요청"} />
            {lastFailed && <RenderRequest planId={plan.id} retryOf={lastFailed.id} label="실패한 작업 재시도" />}
          </div>
        )}
        <p className="muted">비용 합계(이 제작안): ${total.toFixed(4)} — 공급자·모델별 기록 {costs.length}건</p>
      </section>

      {showPaid && (
        <section className="section">
          <h3>유료 그림(결재)</h3>
          <p className="muted">지금 유료 렌더하면 새로 드는 예상(그림만, 정가표): <b>${estimate.toFixed(3)}</b> — 새로 살 그림 {spend.estimate.images}장
            {spend.estimate.bought > 0 && <>, 이 제작안으로 이미 산 그림 {spend.estimate.bought}장은 다시 씀(0원)</>}. 정리 카드 장면은 로컬로 그려 0원입니다.</p>
          <div className="dk-row">
            {spend.estimate.scenes.map((s) => (
              <span key={s.position} className={s.bought ? "pill dk-ok" : "pill"}>{s.position}번 · {s.role === "mechanism" ? "3D 도해" : s.role === "text_card" ? "정리 카드" : "실사형"} ·{" "}
                {s.bought ? "산 그림 다시 씀" : `$${Number(s.usd).toFixed(3)}`}</span>
            ))}
            {cardPages.map((s) => (
              <span key={`p${s.position}`} className={s.bought ? "pill dk-ok" : "pill"}>{s.position}쪽 · 카드 배경 사진 ·{" "}
                {s.bought ? "산 그림 다시 씀" : `$${Number(s.usd).toFixed(3)}`}</span>
            ))}
          </div>
          {noPrompt.length > 0 && <p className="banner-warn">영어 그림 지시문(visual_prompt)이 없는 장면: {noPrompt.join(", ")}번 — 유료 렌더는 아무것도 사기 전에 멈춥니다.
            제작안을 새 버전으로 고쳐 지시문을 넣으세요.</p>}
          {spend.approvals.length === 0 ? <p className="muted">이 제작안의 결재가 없습니다.</p> : spend.approvals.map((a) => (
            <div key={a.approval_id} className="list-row">
              <span>
                <span className={a.status === "open" && !a.expired ? "pill dk-ok" : "pill"}>{a.status === "open" ? (a.expired ? "기간 지남" : "열림") : "닫힘"}</span>{" "}
                {a.stage} · 상한 ${Number(a.cap_usd).toFixed(2)} · 확정 ${Number(a.spent_usd).toFixed(3)} · 가잡힘 ${Number(a.held_usd).toFixed(3)} ·
                남음 <b>${Number(a.remaining_usd).toFixed(3)}</b> · 실패 해제 {a.released}건 · 기한 {fmtTime(a.expires_at)}
              </span>
              {a.status === "open" && <CloseSpendApproval approvalId={a.approval_id} />}
            </div>
          ))}
          {openApproval ? (
            !active && <PaidRenderRequest planId={plan.id} approvalId={openApproval.approval_id} estimate={estimate}
              remaining={Number(openApproval.remaining_usd)}
              blocked={renderable ? (BLOCK_TEXT[renderable] ?? renderable) : noPrompt.length ? "그림 지시문이 없는 장면이 있습니다" : null} />
          ) : (
            <OpenSpendApproval planId={plan.id} suggestedCap={Math.min(10, Math.max(0.01, Math.ceil(estimate * 1.3 * 100) / 100))} />
          )}
        </section>
      )}

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
                  ) : file.state !== "stored" ? (
                    <p className="dk-bad">파일 상태: {file.state}</p>
                  ) : file.storage_key.startsWith("local:") ? (
                    <p className="muted">로컬 저장({file.storage_key.replace(/^local:/, "")}) — 브라우저 미리보기 불가</p>
                  ) : (
                    <p className="dk-bad">미리보기 링크를 만들지 못했습니다 — {file.urlError}</p>
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
