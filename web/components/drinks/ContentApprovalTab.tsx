"use client";

// 내용 승인 탭 — 근거표(원문 인용)·주장별 확인·핵심 메시지·대본·장면 지시·금액을 한 화면에서 보고 [승인] 한 번으로 근거와 제작안을 함께 승인한다.
// ★ 주장별 뒷받침 확인(support_review)은 사람이 이 화면에서 한다. 자동으로 채우지 않는다.
// ★ 근거 문장을 고치거나 주장을 빼면 그 근거로 쓴 대본은 서버가 무효로 만든다 — [이 근거로 대본 다시 만들기] 뒤에야 승인할 수 있다.
// ★ 버튼 잠금은 편의다. 막는 것은 DB(drinks_approve_content + 기존 승인 함수들)다.
// ★ 승인 금액은 기록만 한다. 결재를 열지 않고 돈이 나가지 않는다 — 제작 화면의 결재는 지시서의 실측 금액을 보고 따로 연다(docs/deviation-drinks-explainer-queue.md).
// ★ 카드뉴스(0065)도 같은 화면이다. 금액을 받지 않는다 — 렌더가 로컬 0원이다.
import { useState } from "react";

import {
  EXPLAINER_APPROVAL_CAP_USD, EXPLAINER_ESTIMATE_USD, approvalLocks, chainView, evidenceContentChanged, sceneDirective, type PickRow,
  visualClaimsOf,
} from "@/lib/drinks/contentApproval";
import type { DevelopBudgetRow, DevelopRequestRow } from "@/lib/drinks/develop";
import { requestNote } from "@/lib/drinks/develop";
import { FORMAT_INTENT_LABEL, type FormatIntent } from "@/lib/drinks/formatRecommend";
import {
  FORMAT_FIT_MIN, QUOTE_LABEL, SELECT_THRESHOLD, SUPPORT_LABEL, VISUAL_ROLE_LABEL, blockerLabel, fitOk, nextMonday, weightedScore, type Scores,
} from "@/lib/drinks/model";
import type { Brief, CarouselPage, Claim, PlanRow, ReviewRow, SnapshotRow, TopicRow, VideoScene } from "@/lib/drinks/types";
import { AutoRefresh } from "./DevelopControls";
import ScoreInputs from "./ScoreInputs";
import { useDrinksAction } from "./useDrinksAction";
import { useRegisterPrimary } from "./work/primaryBridge";

export default function ContentApprovalTab({
  topic, review, plan, pick, requests, budget, snapshots, developProblem, today, formatIntent, hidePrimary = false,
}: {
  topic: TopicRow;
  review: ReviewRow | null;
  /** 고른 형식(설명형=영상, 카드뉴스=카드)의 현재 제작안 */
  plan: PlanRow | null;
  pick: PickRow | null;
  requests: DevelopRequestRow[];
  /** 지금 쓸 개발 결재(없으면 null) */
  budget: DevelopBudgetRow | null;
  snapshots: Record<string, Pick<SnapshotRow, "title" | "canonical_url" | "publisher" | "rights_status">>;
  /** 개발 상태를 못 읽었을 때 그 사실(요청 0건이 아니다) */
  developProblem: string | null;
  today: string;
  /** 0072 복수 형식: 이 화면이 승인하는 형식. 없으면 대표 pick 의 형식(옛 화면) */
  formatIntent?: "explainer" | "card";
  /** 작업공간 결정 바가 [승인]을 대신 누른다(primaryBridge — 금액·예외 사유는 이 폼의 값이 실린다). 옛 화면은 false */
  hidePrimary?: boolean;
}) {
  const { run, busy } = useDrinksAction();
  const savedClaims = review?.evidence_pack?.claims ?? [];
  const savedSelected = review?.brief?.selected_claim_ids ?? [];
  const [claims, setClaims] = useState<Claim[]>(savedClaims);
  const [selected, setSelected] = useState<string[]>(savedSelected);
  const [takeaway, setTakeaway] = useState(review?.brief?.core_takeaway ?? "");
  const [scores, setScores] = useState<Scores>(review?.scores ?? {});
  const [amount, setAmount] = useState(String(EXPLAINER_APPROVAL_CAP_USD));
  const [scoreExc, setScoreExc] = useState("");
  const [fitExc, setFitExc] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [serverBlockers, setServerBlockers] = useState<string[] | null>(null);

  const chain = chainView({ pick, requests, review, plan });
  const contentEdited = evidenceContentChanged({ claims: savedClaims, selected: savedSelected }, { claims, selected });
  const dirty = contentEdited
    || (takeaway.trim() || null) !== (review?.brief?.core_takeaway ?? null)
    || JSON.stringify(scores) !== JSON.stringify(review?.scores ?? {})
    || claims.some((c) => c.support_review !== savedClaims.find((s) => s.claim_id === c.claim_id)?.support_review);
  const score = weightedScore(scores as Record<string, unknown>);
  const intent = formatIntent ?? pick?.format_intent ?? null;
  const isCard = intent === "card";
  const planFormat = isCard ? "carousel" : "video";
  const fitRaw = isCard ? scores.fit_carousel : scores.fit_video;
  const formatFit = typeof fitRaw === "number" ? fitRaw : null;
  const blockers = review?.readiness?.blockers ?? [];
  const locks = approvalLocks({
    pick, chain, dirty, blockers, score, selectThreshold: SELECT_THRESHOLD, scoreException: scoreExc,
    formatFit, fitMin: FORMAT_FIT_MIN, fitException: fitExc, amountUsd: Number(amount),
  }, blockerLabel);
  const editable = review !== null && review.status === "draft" && topic.status === "researching";
  // 0072 G4: 다른 형식이 먼저 승인돼 소재가 ready/selected 여도, 이 형식의 제작안이 아직 승인 전이면 **제작안만** 승인한다(근거는 현재 승인본 그대로).
  const secondFormat = Boolean(formatIntent) && ["ready", "selected"].includes(topic.status) && plan !== null && plan.plan_status !== "approved";

  const save = () => {
    if (!review) return;
    // 주장에서 빠진 것은 형식별 필수 목록에서도 뺀다(서버가 '핵심 주장이 아닌 필수 주장'을 막는다).
    const required = Object.fromEntries(Object.entries(review.brief?.required_claims ?? {}).map(([k, v]) => [k, (v ?? []).filter((x) => selected.includes(x))]));
    const brief: Partial<Brief> = { ...review.brief, core_takeaway: takeaway.trim() || null, selected_claim_ids: selected, required_claims: required };
    return run("save_review", { topic_id: topic.id, review_id: review.id, expected_version: review.version, evidence_pack: { claims }, brief, scores },
      contentEdited ? "저장했습니다 — 근거가 바뀌어 대본이 무효가 됐습니다" : "저장했습니다", "내용 저장");
  };
  const approve = async () => {
    if (!review || !plan) return;
    const r = await run("approve_content", {
      topic_id: topic.id, expected_topic_version: topic.version, review_id: review.id, expected_review_version: review.version,
      plan_revision_id: plan.id, expected_plan_version: plan.version, ...(isCard ? {} : { approved_amount_usd: Number(amount) }),
      ...(formatIntent ? { format_intent: formatIntent } : {}),
      ...(scoreExc.trim() ? { score_exception_reason: scoreExc.trim() } : {}),
      ...(fitExc.trim() ? { format_exceptions: { [planFormat]: fitExc.trim() } } : {}),
    }, "근거와 대본을 함께 승인하고 편성했습니다", "내용 승인");
    setServerBlockers(!r.ok && Array.isArray(r.detail) ? (r.detail as string[]) : null);
  };
  const approveClaimed = useRegisterPrimary("approve_content", { submit: approve, disabled: busy || locks.length > 0 || !review || !plan,
    title: locks.length > 0 ? locks.join(" · ") : "" }, hidePrimary && (["triaged", "researching"].includes(topic.status) || secondFormat));
  const regenerate = async () => {
    const r = await run("request_develop", { topic_id: topic.id, kind: "plan", draft_evidence: true, ...(budget ? { budget_id: budget.budget_id } : {}) },
      "이 근거로 대본을 다시 요청했습니다", "대본 다시 만들기");
    if (r.ok) setNote(requestNote({ existing: (r.result as { existing?: boolean } | undefined)?.existing, triggered: r.dispatch?.triggered }));
  };
  const rePick = async (format: FormatIntent) => {
    const r = await run("pick_topic", {
      topic_id: topic.id, format, editorial_week: pick?.editorial_week ?? nextMonday(today), ...(budget ? { budget_id: budget.budget_id } : {}),
    }, `${FORMAT_INTENT_LABEL[format]}으로 이어 만들기를 요청했습니다`, "이어 만들기");
    if (r.ok) {
      const c = (r.result as { chain?: { queued?: boolean; existing?: boolean; message?: string } } | undefined)?.chain;
      setNote(c?.queued ? requestNote({ existing: c.existing, triggered: r.dispatch?.triggered }) : c?.message ?? null);
    }
  };

  if (["ready", "selected"].includes(topic.status) && !secondFormat) {
    return (
      <section className="section">
        <h3>내용 승인</h3>
        <p className="muted">
          {pick?.approved_at ? `이 소재는 내용 승인을 마쳤습니다${pick.approved_amount_usd ? `(승인 금액 기록 $${Number(pick.approved_amount_usd).toFixed(2)})` : ""}. ` : "이 소재는 이미 근거가 승인됐습니다. "}
          이어지는 일은 공통 기획·영상·카드뉴스 탭과 제작 화면에서 합니다.
          {isCard ? " 카드뉴스는 제작 화면에서 [렌더 요청]을 누르면 카드와 릴스 영상이 함께 나옵니다(로컬·0원)." : " 설명형은 전부 영상이어야 해서 옛 그림 나열식 렌더는 막혀 있고, 제작 화면의 설명형 제작으로 진행합니다."}
        </p>
      </section>
    );
  }
  if (!["triaged", "researching"].includes(topic.status) && !secondFormat) {
    return <section className="section"><h3>내용 승인</h3><p className="muted">조사 후보로 고른 소재만 이 화면을 씁니다. 요약 탭에서 먼저 처리하세요.</p></section>;
  }

  const scenes = plan?.plan_json?.scenes ?? [];
  const pages: CarouselPage[] = plan?.plan_json?.pages ?? [];
  const reel = plan?.plan_json?.reel;
  const visualClaims = visualClaimsOf(requests, plan?.id);
  const totalSec = scenes.reduce((n, s) => n + (typeof s.timing_sec === "number" ? s.timing_sec : 0), 0);
  const claimOf = (id: string) => claims.find((c) => c.claim_id === id);
  const canRegenerate = review?.status === "draft" && (pick?.format_intent === "explainer" || isCard)
    && (chain.state === "invalidated" || (chain.state === "stopped" && chain.code !== "meme_board"));

  return (
    <div>
      <AutoRefresh active={chain.state === "running"} />
      <section className="section">
        <h3>내용 승인 — 근거·대본을 한 번에</h3>
        {developProblem && <p className="banner-block" role="alert">{developProblem}</p>}
        <p className={chain.state === "ready" ? "banner-ok" : chain.state === "running" ? "banner-info" : chain.state === "none" ? "muted" : "banner-warn"} role="status">
          <b>{chain.label}</b>{chain.reason && <span style={{ display: "block", whiteSpace: "pre-wrap" }}>{chain.reason}</span>}
        </p>
        <p className="dk-kv">
          고른 형식 <b>{pick ? FORMAT_INTENT_LABEL[pick.format_intent] : "없음"}</b>
          {pick && <> · 편성 주차 <b>{pick.editorial_week}</b> (승인할 때 편성됩니다)</>}
          {pick?.recommended_format && pick.recommended_format !== pick.format_intent && <> · 추천은 {pick.recommended_format === "unknown" ? "없었음" : FORMAT_INTENT_LABEL[pick.recommended_format as FormatIntent]}</>}
        </p>
        {!budget && <p className="banner-warn">열린 개발 결재가 없습니다 — 아래 개발 카드에서 결재를 연 뒤에 이어 만들 수 있습니다. 결재 없이는 모델을 부르지 않습니다.</p>}
        <div className="actions">
          {!pick && (
            <>
              <button className="btn pick" disabled={busy} onClick={() => rePick("explainer")}>이걸로 — 설명형</button>
              <button className="btn" disabled={busy} onClick={() => rePick("card")}>이걸로 — 카드뉴스</button>
            </>
          )}
          {pick && chain.state === "stopped" && !review && chain.code !== "meme_board" && (
            <button className="btn pick" disabled={busy || !budget} onClick={() => rePick(pick.format_intent)}>다시 이어 만들기</button>
          )}
          {pick?.format_intent === "explainer" && chain.code === "evidence_insufficient" && (
            <button className="btn" disabled={busy} onClick={() => rePick("card")}>카드뉴스로 바꾸기</button>
          )}
          {canRegenerate && (
            <button className="btn pick" disabled={busy || !budget || dirty} title={dirty ? "수정을 먼저 저장하세요" : ""} onClick={regenerate}>
              이 근거로 대본 다시 만들기
            </button>
          )}
        </div>
        {note && <p className="muted">{note}</p>}
      </section>

      {review && (
        <section className="section">
          <h3>근거표 — 버전 {review.revision_no}</h3>
          <p className="muted">
            주장마다 <b>원문 인용이 그 주장을 정말 뒷받침하는지</b> 직접 읽고 고르세요. 이 칸은 사람만 채웁니다. 코드는 인용이 원문에 글자 그대로 있는지만 봅니다.
            뒷받침 확인과 핵심 메시지는 고쳐도 대본이 그대로지만, 주장 문장을 고치거나 핵심에서 빼면 대본이 무효가 됩니다.
          </p>
          {claims.length === 0 && <p className="muted">주장이 없습니다.</p>}
          {claims.map((c, idx) => (
            <div key={c.claim_id} className="dk-sub">
              <div className="dk-row">
                <span className="pill">{c.claim_id}</span>
                <label className="dk-checks"><input type="checkbox" disabled={!editable} checked={selected.includes(c.claim_id)}
                  onChange={(e) => setSelected(e.target.checked ? [...selected, c.claim_id] : selected.filter((x) => x !== c.claim_id))} /> 핵심 주장</label>
                {c.claim_type === "opinion" ? <span className="muted">주관 평가 — 지지 확인 해당 없음</span> : (
                  <label className="dk-checks">뒷받침 확인
                    <select value={c.support_review} disabled={!editable} onChange={(e) => {
                      const next = [...claims]; next[idx] = { ...c, support_review: e.target.value as Claim["support_review"] }; setClaims(next);
                    }}>
                      {(["not_reviewed", "supported", "insufficient", "conflicting"] as const).map((k) => <option key={k} value={k}>{SUPPORT_LABEL[k]}</option>)}
                    </select>
                  </label>
                )}
              </div>
              <label className="dk-field"><span>주장</span>
                <input value={c.text} disabled={!editable} onChange={(e) => {
                  const next = [...claims]; next[idx] = { ...c, text: e.target.value }; setClaims(next);
                }} />
              </label>
              {c.source_refs.map((r, i) => {
                const s = snapshots[r.snapshot_id];
                return (
                  <div key={i} style={{ marginTop: 6 }}>
                    <p className="dk-quote" style={{ margin: 0 }}>{r.original_quote ?? "(인용 없음)"}</p>
                    <span className="muted">
                      {s?.canonical_url ? <a href={s.canonical_url} target="_blank" rel="noreferrer noopener">{s.title || s.canonical_url}</a> : s?.title ?? "출처"}
                      {s?.publisher && ` · ${s.publisher}`} · {QUOTE_LABEL[r.quote_check ?? "not_checked"]}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
          <label className="dk-field"><span>핵심 메시지 한 줄(대본의 결론을 초안으로 채웠습니다 — 맞는지 보고 고치세요)</span>
            <input value={takeaway} disabled={!editable} onChange={(e) => setTakeaway(e.target.value)} maxLength={300} />
          </label>
          <h4 style={{ margin: "12px 0 4px" }}>편성 평가</h4>
          <ScoreInputs value={scores} onChange={setScores} disabled={!editable} />
          {score !== null && score < SELECT_THRESHOLD && (
            <label className="dk-field"><span>{score}점 — 기준 {SELECT_THRESHOLD}점 미만 예외 사유</span><input value={scoreExc} onChange={(e) => setScoreExc(e.target.value)} /></label>
          )}
          {formatFit !== null && !fitOk(scores, planFormat) && (
            <label className="dk-field"><span>{isCard ? "카드뉴스" : "영상"} 적합성 {FORMAT_FIT_MIN}점 미만 예외 사유</span><input value={fitExc} onChange={(e) => setFitExc(e.target.value)} /></label>
          )}
          {contentEdited && <p className="banner-warn">근거 내용이 바뀌었습니다. 저장하면 지금 대본은 무효가 되고, 대본을 다시 만들어야 승인할 수 있습니다(모델 비용이 듭니다).</p>}
          <div className="actions"><button className="btn" disabled={busy || !dirty || !editable} onClick={save}>저장</button></div>
        </section>
      )}

      {plan && isCard && (
        <section className="section">
          <h3>카드 제작안 — 버전 {plan.revision_no} · {pages.length}장{plan.blocked_at ? " · 무효" : ""}</h3>
          {plan.plan_json?.notes && <p className="dk-kv">{plan.plan_json.notes}</p>}
          {reel && (
            <p className="dk-kv">릴스 첫 화면 큰 제목 <b>{reel.hook_title}</b> · 마지막 화면 한 줄 <b>{reel.share_line}</b></p>
          )}
          {pages.map((pg, i) => (
            <div key={i} className="dk-sub" style={plan.blocked_at ? { opacity: 0.6 } : undefined}>
              <div className="dk-row"><b>{i + 1}쪽</b> <span className="pill">{pg.role}</span> <b>{pg.heading}</b></div>
              {pg.body && <p style={{ margin: "6px 0", whiteSpace: "pre-line" }}>{pg.body}</p>}
              {pg.claim_ids.map((id) => {
                const c = claimOf(id);
                return <p key={id} className="muted" style={{ margin: "2px 0" }}>근거 {id}: {c?.source_refs[0]?.original_quote ?? c?.text ?? "(이 버전에 없는 주장)"}</p>;
              })}
            </div>
          ))}
        </section>
      )}

      {plan && !isCard && (
        <section className="section">
          <h3>대본 — 버전 {plan.revision_no} · {scenes.length}장면 · 합계 {totalSec}초{plan.blocked_at ? " · 무효" : ""}</h3>
          {plan.plan_json?.notes && <p className="dk-kv">{plan.plan_json.notes}</p>}
          {scenes.map((sc: VideoScene, i) => {
            const directive = sceneDirective({ ...(sc as unknown as Record<string, unknown>), ...visualClaims[i + 1] });
            return (
              <div key={i} className="dk-sub" style={plan.blocked_at ? { opacity: 0.6 } : undefined}>
                <div className="dk-row">
                  <b>{i + 1}번</b>
                  <span className="pill">{VISUAL_ROLE_LABEL[sc.visual_role] ?? sc.visual_role}</span>
                  <span className="muted">{sc.timing_sec ?? "—"}초 · {sc.content_kind === "transition" ? "도입·전환" : "사실 설명"}</span>
                </div>
                <p style={{ margin: "6px 0" }}>{sc.narration}</p>
                {sc.claim_ids.map((id) => {
                  const c = claimOf(id);
                  return <p key={id} className="muted" style={{ margin: "2px 0" }}>근거 {id}: {c?.source_refs[0]?.original_quote ?? c?.text ?? "(이 버전에 없는 주장)"}</p>;
                })}
                {directive.length > 0 && (
                  <details><summary className="muted" style={{ cursor: "pointer" }}>장면 지시</summary>
                    {directive.map((d) => <p key={d.label} className="dk-kv" style={{ margin: "2px 0" }}>{d.label}: <b>{d.value}</b></p>)}
                  </details>
                )}
              </div>
            );
          })}
        </section>
      )}

      {isCard && (
        <section className="section">
          <h3>금액</h3>
          <p className="muted">카드와 릴스 영상은 로컬에서 만들어 렌더 비용이 0원입니다. 승인 금액을 받지 않습니다. 근거·대본을 만드는 데 든 비용은 개발 카드에 있습니다.</p>
        </section>
      )}

      {!isCard && <section className="section">
        <h3>금액</h3>
        <p className="dk-kv">
          설명형 영상 구매 계획값(기획 §3-7, 48초 기준 — 이 편의 실측이 아닙니다): 예상 <b>${EXPLAINER_ESTIMATE_USD.toFixed(2)}</b>, 승인 상한 <b>${EXPLAINER_APPROVAL_CAP_USD.toFixed(2)}</b>
        </p>
        <label className="dk-field" style={{ maxWidth: 220 }}><span>이 편 승인 금액($)</span>
          <input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
        </label>
        <p className="muted">
          이 금액은 기록만 합니다. 승인해도 결재가 열리지 않고 돈이 나가지 않습니다 — 영상 구매는 제작 화면에서 장면별 지시서와 실측 금액을 본 뒤 결재를 따로 엽니다.
          근거·대본을 만드는 데 든 비용은 개발 카드에 있습니다.
        </p>
      </section>}

      <section className="section">
        {locks.length > 0 ? (
          <div className="banner-warn" role="status">
            <b>아직 승인할 수 없습니다</b>
            <ul style={{ margin: "6px 0 0 18px" }}>{locks.map((l) => <li key={l}>{l}</li>)}</ul>
          </div>
        ) : <p className="banner-ok">모든 조건을 채웠습니다. 승인하면 근거와 대본이 함께 승인되고 {pick?.editorial_week} 주로 편성됩니다.</p>}
        {serverBlockers && (
          <div className="banner-block" role="alert"><b>서버가 막았습니다</b>
            <ul style={{ margin: "6px 0 0 18px" }}>{serverBlockers.map((b) => <li key={b}>{blockerLabel(b)}</li>)}</ul>
          </div>
        )}
        {!approveClaimed && <div className="actions"><button className="btn pick" disabled={busy || locks.length > 0} onClick={approve}>승인</button></div>}
      </section>
    </div>
  );
}
