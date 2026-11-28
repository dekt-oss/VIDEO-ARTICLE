"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DEVELOP_STATUS_LABEL, type DevelopRequestRow } from "@/lib/drinks/develop";
import { jjeriPreview, type JjeriFormat } from "@/lib/drinks/jjeri";
import { CancelDevelop } from "./DevelopControls";
import { useDrinksAction } from "./useDrinksAction";

type GenerationRequest = Omit<DevelopRequestRow, "kind"> & { format?: JjeriFormat; lesson: string | null; max_usd: number };
export interface JjeriGeneration {
  current_review: { id: string; hash: string } | null;
  max_calls: number;
  max_usd: number;
  revision_id: string | null;
  request_current: boolean;
  can_request: boolean;
  can_approve: boolean;
  request: GenerationRequest | null;
  budgets: { budget_id: string; stage: string; remaining_usd: number | string }[];
}

const stepLabel: Record<string, string> = {
  started: "준비", start: "근거 확인", "jjeri:generate": "초안 작성",
  "jjeri:correction": "검사 결과 반영", "jjeri:save_preview": "미리보기 저장",
};
// Reference estimate for the approved-evidence sample; the worker prices each actual prompt before its hold.
const SAMPLE_PER_CALL_USD = 0.1293;

export function JjeriEpisodePanel({ topicId, generation, anatomyEnabled }: { topicId: string; generation: JjeriGeneration; anatomyEnabled: boolean }) {
  const { request, current_review: review, budgets } = generation;
  const [format, setFormat] = useState<JjeriFormat>(request?.format ?? "jjeri_class");
  const [lesson, setLesson] = useState(request?.lesson?.replace(/교시$/, "") ?? "1");
  const [budgetId, setBudgetId] = useState("");
  const [cap, setCap] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [dispatch, setDispatch] = useState<string | null>(null);
  const router = useRouter();
  const { run, busy } = useDrinksAction();
  const active = request?.status === "queued" || request?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => router.refresh(), 3500);
    return () => window.clearInterval(timer);
  }, [active, router]);

  const anatomy = format === "jjeri_anatomy";
  const requestFormat = request?.format ?? "jjeri_class";
  const sameRequest = generation.request_current && requestFormat === format && (anatomy || request?.lesson === `${lesson}교시`);
  const retry = sameRequest && request && ["failed", "blocked", "canceled"].includes(request.status);
  const regenerate = sameRequest && request?.status === "succeeded";
  const budget = budgets.find((row) => row.budget_id === budgetId);
  const sampleTotal = (SAMPLE_PER_CALL_USD * generation.max_calls).toFixed(4);
  const budgetLimit = Math.min(generation.max_usd, Number(budget?.remaining_usd ?? 0));
  const amount = Number(cap);
  const canRequest = generation.can_request && review && budget && authorized && (anatomy ? anatomyEnabled : /^[1-9][0-9]{0,2}$/.test(lesson))
    && /^\d+(?:\.\d{1,4})?$/.test(cap) && amount > 0
    && amount <= budgetLimit;
  const plan = request?.result?.plan as Partial<Record<JjeriFormat, unknown>> | undefined;
  const preview = jjeriPreview(plan, requestFormat);
  const work = `/drinks/work/${topicId}?detail=1&lane=explainer`;

  async function requestEpisode() {
    if (!canRequest || !review) return;
    setDispatch(null);
    setAuthorized(false);
    const res = await run("request_jjeri_episode", { topic_id: topicId, review_id: review.id, review_hash: review.hash,
      format, ...(!anatomy ? { lesson: `${lesson}교시` } : {}), budget_id: budgetId, max_usd: amount, spend_confirmed: true,
      ...(retry ? { retry_of: request.request_id } : {}),
      ...(regenerate && request ? { regenerate_of: request.request_id } : {}) }, "째리 지시서를 요청했습니다", "째리 초안 요청");
    if (res.ok && res.result?.existing === true) setDispatch("같은 요청이 이미 있어 이전 결과를 표시합니다.");
    else if (res.ok && res.dispatch?.triggered !== true) setDispatch("요청이 대기 중입니다. 개발 워커 실행이 필요합니다.");
  }

  return (
    <section className="dk-sub" aria-labelledby="jjeri-episode-heading">
      <h2 id="jjeri-episode-heading">째리 지시서</h2>
      {!review && <p className="banner-warn">현재 유효한 승인 근거와 영상 필수 주장이 필요합니다. <Link href={`${work}&panel=evidence`}>근거 확인</Link></p>}
      {review && !generation.can_request && <p className="banner-warn">현재 승인 근거로 영상을 편성한 뒤 지시서를 요청하세요. <Link href={`${work}&panel=evidence`}>편성 열기</Link></p>}
      {request && <p aria-live="polite">{requestFormat === "jjeri_anatomy" ? "술 해부" : `술 수업 ${request.lesson ?? ""}`} · {DEVELOP_STATUS_LABEL[request.status]}
        {active && request.step && stepLabel[request.step] ? ` · ${stepLabel[request.step]}` : ""}
        {request.cost_usd != null ? ` · 기록된 비용 $${Number(request.cost_usd).toFixed(4)}` : ""}</p>}
      {request?.error_message && <p className="banner-warn">{request.error_message}</p>}
      {request?.status === "queued" && <p className="muted">개발 워커가 대기열에서 이 요청을 가져갑니다.</p>}
      {active && request && <CancelDevelop requestId={request.request_id} />}
      {dispatch && <p className="muted" role="status">{dispatch}</p>}
      {request && !generation.request_current && <p className="banner-warn">이 요청의 근거가 현재 승인 근거와 다릅니다.</p>}
      {!active && generation.can_request && (
        <fieldset className="dk-sub" disabled={busy}>
          <legend>{regenerate ? "같은 형식 새 지시서 생성" : "새 지시서 생성"}</legend>
          <div className="dk-row">
            {anatomyEnabled && <label>형식 <select value={format} onChange={(e) => {
              setFormat(e.target.value as JjeriFormat); setAuthorized(false);
            }}>
              <option value="jjeri_class">술 수업</option>
              <option value="jjeri_anatomy">술 해부</option>
            </select></label>}
            {!anatomy && <label>교시 <input type="number" min="1" max="999" value={lesson} onChange={(e) => { setLesson(e.target.value); setAuthorized(false); }} /></label>}
            <label>개발 결재 <select value={budgetId} onChange={(e) => { setBudgetId(e.target.value); setAuthorized(false); }}>
              <option value="">결재 선택</option>
              {budgets.map((row) => <option key={row.budget_id} value={row.budget_id}>{row.stage} · 남은 ${row.remaining_usd}</option>)}
            </select></label>
            <label>요청 상한 ($) <input inputMode="decimal" value={cap} onChange={(e) => { setCap(e.target.value); setAuthorized(false); }} /></label>
          </div>
          {budgets.length === 0 && <p className="muted">사용할 수 있는 개발 결재가 없습니다.</p>}
          <p className="muted">예시 1회 약 ${SAMPLE_PER_CALL_USD.toFixed(4)} USD · 최대 {generation.max_calls}회 약 {sampleTotal} USD.
            실제 예약액은 승인 근거와 교정 입력에 따라 달라집니다.</p>
          {budget && <button type="button" className="btn" disabled={Number(sampleTotal) > budgetLimit}
            onClick={() => { setCap(sampleTotal); setAuthorized(false); }}>예시 {generation.max_calls}회 상한 사용</button>}
          {amount > 0 && amount < Number(sampleTotal) && <p className="muted">설정한 상한이 부족하면 작성 또는 교정 호출 전에 멈춥니다.</p>}
          {regenerate && <p className="muted">새 결재 확인이 필요합니다. 이미 승인한 제작안은 새 지시서를 사람이 승인할 때까지 유지됩니다.</p>}
          <label className="dk-row"><input type="checkbox" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />
            요청 상한 {amount > 0 ? `${amount.toFixed(4)} USD` : "입력 필요"}와 모델 호출 최대 {generation.max_calls}회를 승인합니다.
            시스템 상한 ${generation.max_usd}
          </label>
          <button type="button" className="btn pick" disabled={!canRequest} onClick={requestEpisode}>
            {retry ? "실패한 생성 재시도" : regenerate ? "같은 형식 다시 생성" : "지시서 생성 요청"}
          </button>
        </fieldset>
      )}
      {preview && request && (
        <>
          <details open>
            <summary>지시서 미리보기 · {preview.topic} · 장면 {preview.scenes.length}개</summary>
            <ol>{preview.scenes.map((scene) => <li key={scene.id}>
              <b>{preview.chapters.find((ch) => ch.from_scene === scene.id)?.title ?? scene.template}</b>
              {scene.beats.map((beat, i) => <div key={i} style={{ whiteSpace: "pre-line" }}>{beat.text}</div>)}
            </li>)}</ol>
            <details><summary>화면 문구·캡션·주장 연결 전체</summary>
              <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(plan?.[requestFormat], null, 2)}</pre>
            </details>
            <p><Link href={`${work}&panel=evidence`}>승인 근거 원문 보기</Link></p>
          </details>
          {generation.revision_id ? <Link href={`${work}&panel=produce&plan=${generation.revision_id}`}>승인된 째리 제작안 열기</Link>
            : generation.can_approve ? <fieldset className="dk-sub" disabled={busy}>
              <legend>사람 원문 검수</legend>
              <label className="dk-row"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
                화면·음성·캡션의 가격, 건강 효능, 수치와 주장 연결을 원문과 대조했습니다.
              </label>
              <button type="button" className="btn pick" disabled={!reviewed} onClick={() =>
                run("approve_jjeri_episode", { request_id: request.request_id, review_confirmed: true }, "째리 제작안을 승인했습니다", "제작안 승인")
              }>지시서 승인 및 제작안 만들기</button>
            </fieldset> : <p className="banner-warn">승인하려면 현재 근거로 영상을 편성하고 작성·검토 중인 제작안과 버전 변경을 확인하세요. <Link href={`${work}&panel=evidence`}>근거·편성 열기</Link></p>}
        </>
      )}
    </section>
  );
}
