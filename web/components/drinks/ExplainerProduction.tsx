"use client";

// 설명형 제작(0067) — 지시서 보기 · 결재 · 구매 요청 · 후보 검수 · 선택 · 결과 불명 닫기 · 조립 요청 · 사람 검수.
// ★ 화면은 돈을 쓰지 못한다. 구매는 워커가 항목마다 결재 금액 안인지 DB 로 재고 산다. 모든 규칙은 DB 가 막고, 여기서 버튼을 숨기는 것은 편의다.
import { useState } from "react";

import { useDrinksAction } from "./useDrinksAction";
import { useRegisterPrimary } from "./work/primaryBridge";
import {
  CLAY_PROVIDER, EPISODE_LABEL, PROCESS_CHECKS, QUALITY_CHECKS, canJudge, canSelect, kstMinute, neededKinds, nextStep, slotCosts, usableApproval,
  type ExplainerCandidate, type ExplainerSlot, type ExplainerStatus,
} from "@/lib/drinks/explainerQueue";

const usd = (v: unknown, d = 3) => `$${Number(v ?? 0).toFixed(d)}`;
const ROLE: Record<string, string> = { mechanism: "3D 도해", reality: "실사형" };
const BOUNDARY: Record<string, string> = { loop: "루프", flash_forward: "앞당겨 보여 주기", cut_to_mechanism: "실사↔도해 전환", match: "이어짐", same_clip: "같은 클립", cut: "보통 컷" };
const ATTEMPT: Record<string, string> = {
  requested: "요청 기록됨", generating: "생성 중", received: "받음", probed: "실측함", stored: "저장됨", failed_unbilled: "실패(청구 없음)", failed_billed: "실패(청구됨)",
  unknown_billed: "결과 모름", closed_billed: "닫음: 청구됨", closed_void: "닫음: 없던 일",
};

function CloseUnknown({ attemptId, est }: { attemptId: string; est: number }) {
  const { run, busy } = useDrinksAction();
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState(est.toFixed(4));
  return (
    <div className="dk-row">
      <span className="dk-bad">결과 모름 — 다시 부르지 않습니다. 청구서를 보고 닫으세요.</span>
      <input placeholder="확인한 내용" value={note} onChange={(e) => setNote(e.target.value)} />
      <label className="muted">금액 $<input style={{ width: 80 }} value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
      <button className="btn" disabled={busy || !note || !(Number(amount) >= 0)} onClick={() => run("explainer_close_unknown",
        { attempt_id: attemptId, resolution: "billed", note, actual_usd: Number(amount) }, "청구된 것으로 닫았습니다", "닫기")}>청구된 것으로 닫기</button>
      <button className="btn" disabled={busy || !note} onClick={() => run("explainer_close_unknown",
        { attempt_id: attemptId, resolution: "void", note }, "없던 일로 닫았습니다", "닫기")}>없던 일로 닫기</button>
    </div>
  );
}

function Candidate({ slot, c }: { slot: ExplainerSlot; c: ExplainerCandidate }) {
  const { run, busy } = useDrinksAction();
  const [reason, setReason] = useState("");
  const blocks = c.auto_report?.blocks ?? [];
  const selected = slot.selection?.candidate_id === c.candidate_id;
  return (
    <div style={{ maxWidth: 260 }} className="dk-sub">
      <b>후보 {c.k}</b>{selected && <span className="pill dk-ok"> 선택됨</span>}
      {c.url ? <video src={c.url} controls style={{ width: "100%" }} /> : c.asset ? (
        c.asset.storage_key.startsWith("local:") ? <p className="muted">로컬 저장 — 브라우저 미리보기 불가</p> : <p className="dk-bad">미리보기 링크를 만들지 못했습니다 — {c.urlError}</p>
      ) : <p className="muted">파일 없음</p>}
      {c.asset && <div className="muted">실측 {((c.asset.duration_ms ?? 0) / 1000).toFixed(2)}초 · {c.asset.width}×{c.asset.height} · 필요 {(slot.min_src_ms / 1000).toFixed(2)}초</div>}
      <div>
        자동: <span className={c.auto_verdict === "pass" ? "dk-ok" : c.auto_verdict === "fail" ? "dk-bad" : "muted"}>{c.auto_verdict === "pass" ? "통과" : c.auto_verdict === "fail" ? `불합격(${blocks.join(", ")})` : "전"}</span>
        {" · "}사람: <span className={c.human_verdict === "pass" ? "dk-ok" : c.human_verdict === "fail" ? "dk-bad" : "muted"}>{c.human_verdict === "pass" ? "합격" : c.human_verdict === "fail" ? "불합격" : "전"}</span>
      </div>
      <div className="muted">비용 {usd(c.cost_usd)} · 시도 {c.attempts.length}회</div>
      {c.attempts.map((a) => (
        <div key={a.attempt_id} className="muted" style={{ fontSize: 12 }}>
          {a.m}회차 {ATTEMPT[a.state] ?? a.state}{a.actual_usd != null && ` · ${usd(a.actual_usd)}`}{a.error_code && ` · ${a.error_code}`}{a.close_note && ` · ${a.close_note}`}
          {a.state === "unknown_billed" && <CloseUnknown attemptId={a.attempt_id} est={Number(a.est_usd ?? 0)} />}
        </div>
      ))}
      {canJudge(slot, c) && (
        <div className="actions">
          <button className="btn" disabled={busy} onClick={() => run("explainer_verdict", { candidate_id: c.candidate_id, human_verdict: "pass" }, "합격으로 판정했습니다", "판정")}>사람 합격</button>
          <button className="btn" disabled={busy} onClick={() => run("explainer_verdict", { candidate_id: c.candidate_id, human_verdict: "fail" }, "불합격으로 판정했습니다", "판정")}>사람 불합격</button>
        </div>
      )}
      {canSelect(slot, c) && (
        <div className="dk-row">
          <input placeholder="고른 이유" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn pick" disabled={busy || !reason} onClick={() => run("explainer_select", { slot_id: slot.slot_id, candidate_id: c.candidate_id, reason }, "이 후보를 골랐습니다", "선택")}>이 후보 선택</button>
        </div>
      )}
    </div>
  );
}

function ReviewForm({ planId, stage, title, items }: { planId: string; stage: "process" | "quality"; title: string; items: [string, string][] }) {
  const { run, busy } = useDrinksAction();
  const [ck, setCk] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const all = items.every(([k]) => ck[k]);
  return (
    <div className="dk-sub">
      <b>{title}</b> <span className="muted">하나라도 아니면 불합격입니다. 자동 검사 통과는 품질 합격이 아닙니다.</span>
      {items.map(([k, l]) => (
        <label key={k} className="dk-checks" style={{ display: "flex" }}>
          <input type="checkbox" checked={Boolean(ck[k])} onChange={(e) => setCk({ ...ck, [k]: e.target.checked })} /> {l}
        </label>
      ))}
      <div className="actions">
        <button className="btn pick" disabled={busy || !all} onClick={() => run("explainer_review", { plan_revision_id: planId, stage, outcome: "pass", checks: ck }, "합격으로 기록했습니다", "검수")}>합격</button>
        <input placeholder="불합격 이유" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn" disabled={busy || !reason} onClick={() => run("explainer_review", { plan_revision_id: planId, stage, outcome: "fail", checks: ck, reason }, "불합격으로 기록했습니다", "검수")}>불합격</button>
      </div>
    </div>
  );
}

function OpenApproval({ planId, cap, orderHash, provider }: { planId: string; cap: number; orderHash: string | null; provider: string | null | undefined }) {
  const { run, busy } = useDrinksAction();
  const [amount, setAmount] = useState(cap.toFixed(2));
  const [stage, setStage] = useState("");
  const [words, setWords] = useState("");
  return (
    <div className="dk-row">
      <input placeholder="단계(예: S2 연속 장면 시험)" value={stage} onChange={(e) => setStage(e.target.value)} />
      <label className="muted">상한 $<input style={{ width: 80 }} value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
      <input placeholder="결재 문장(승인한 말 그대로)" value={words} onChange={(e) => setWords(e.target.value)} />
      <button className="btn" disabled={busy || !stage || !words || !(Number(amount) > 0)} onClick={() => run("open_spend_approval", {
        plan_revision_id: planId, stage, purpose: `${stage} — ${provider === CLAY_PROVIDER ? "사진클레이 그림" : "설명형 시작 그림·클립"}`, cap_usd: Number(amount), allowed_kinds: neededKinds(provider), approver_words: words, ...(orderHash ? { order_hash: orderHash } : {}),
      }, "결재를 등록했습니다", "결재 등록")}>결재 등록</button>
    </div>
  );
}

export default function ExplainerProduction({ planId, status, activeJob, hidePrimary = false }: {
  planId: string; status: ExplainerStatus; activeJob: { renderer: string; status: string } | null;
  /** 작업공간 결정 바가 [지시서]·[구매 요청]·[조립] 버튼을 대신 누른다(primaryBridge). 옛 제작 화면은 false */
  hidePrimary?: boolean;
}) {
  const { run, busy } = useDrinksAction();
  const [through, setThrough] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const ep = status.episode;
  const d = ep?.directive ?? null;
  const step = nextStep(status);
  const costs = slotCosts(status.slots);
  const bySlot = new Map(costs.map((c) => [c.n, c]));
  const open = usableApproval(status.approvals, ep?.provider);
  const total = costs.length ? costs[costs.length - 1].cumulativeUsd : 0;
  const busyJob = Boolean(activeJob);
  const busyTitle = busyJob ? "진행 중인 작업이 있습니다" : "";
  const requestPlan = () => run("explainer_request_plan", { plan_revision_id: planId }, "지시서 작업을 넣었습니다(0원)", "지시서");
  const planClaimed = useRegisterPrimary("explainer_request_plan", { submit: requestPlan, disabled: busy || busyJob, title: busyTitle }, hidePrimary && step === "request_plan");
  const requestBuy = async () => {
    if (!open) return;
    if (!window.confirm(`결재 "${open.stage}" 안에서 구매를 요청합니다. 남은 금액 ${usd(open.remaining_usd)}. 진행할까요?`)) return;
    const r = await run("explainer_request_buy", { plan_revision_id: planId, spend_approval_id: open.approval_id, ...(through.trim() ? { through_n: Number(through) } : {}) }, "구매를 요청했습니다", "구매 요청");
    if (r.ok) setNote("큐에 넣었습니다. 구매는 실호출 스위치를 켠 워커만 처리합니다 — 스위치가 꺼진 워커가 집으면 아무것도 사지 않고 실패로 닫힙니다.");
  };
  const buyClaimed = useRegisterPrimary("explainer_request_buy", { submit: requestBuy, disabled: busy || busyJob || !open, title: !open ? "열린 결재가 없습니다" : busyTitle },
    hidePrimary && step === "request_buy" && Boolean(open));
  const requestAssemble = () => run("explainer_request_assemble", { plan_revision_id: planId }, "조립을 요청했습니다(0원, 사지 않습니다)", "조립");
  const assembleClaimed = useRegisterPrimary("explainer_request_assemble", { submit: requestAssemble, disabled: busy || busyJob, title: busyTitle }, hidePrimary && step === "request_assemble");
  return (
    <section className="section">
      <h3>설명형 제작 <span className="pill">{ep ? EPISODE_LABEL[ep.state] : "시작 전"}</span></h3>
      <p className="muted">모든 화면이 산 영상 클립입니다. 클립이 없거나 깨졌거나 짧으면 편 전체가 멈추고 사진으로 대신하지 않습니다. 렌더 중에는 아무것도 사지 않습니다.</p>
      {ep?.last_message && <p className={ep.state.startsWith("blocked") || ep.state === "unknown_billed" || ep.state.endsWith("fail") ? "banner-block" : "banner-warn"}>{ep.last_code}: {ep.last_message}</p>}
      {activeJob && <p className="dk-kv">진행 중인 작업: {activeJob.renderer} ({activeJob.status})</p>}

      {step === "request_plan" && (
        <div className="actions">
          {!planClaimed && <button className="btn pick" disabled={busy || busyJob} onClick={requestPlan}>장면별 지시서 만들기 (0원)</button>}
          <span className="muted">무료 TTS 로 길이를 재서 지시서·금액을 만듭니다. 아무것도 사지 않습니다.</span>
        </div>
      )}

      {d && (
        <details open={step === "open_approval" || step === "request_buy"}>
          <summary><b>장면별 지시서</b> · 슬롯 {d.slots.length}개 · 최종 {(d.final_ms / 1000).toFixed(1)}초 · 편집 컷 {d.edit_cuts}개 · 훅 “{d.hook_text}”(장면 {d.hook_scene})</summary>
          <p className="banner-warn">단가 기준일 {d.price_as_of}, 청구서와 대조 전입니다. 공급자 {d.provider} {d.resolution} — <b>미검증:</b> {d.unverified.join(" · ")}</p>
          <p className="dk-kv">예상 {usd(d.estimate.estimate_usd, 2)} (그림 {usd(d.estimate.images_usd)} + 클립 {usd(d.estimate.clips_usd)}) · 재시도 예비 {usd(d.estimate.reserve_usd)} · 제안 상한 <b>{usd(d.estimate.suggested_cap_usd, 2)}</b></p>
          <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead><tr>{["#", "역할·표기", "나레이션", "그림 문장", "움직임 문장", "시각 주장표", "길이", "금액"].map((h) => <th key={h} style={{ textAlign: "left", padding: 4 }}>{h}</th>)}</tr></thead>
            <tbody>
              {d.slots.map((s) => (
                <tr key={s.n} style={{ borderTop: "1px solid var(--line, #ddd)", verticalAlign: "top" }}>
                  <td style={{ padding: 4 }}>{s.n}</td>
                  <td style={{ padding: 4 }}>{ROLE[s.role]}<br /><span className="muted">{s.depiction_label} · {BOUNDARY[s.boundary_in] ?? s.boundary_in}{s.continuity_ref ? `(${s.continuity_ref}번)` : ""}</span></td>
                  <td style={{ padding: 4 }}>{s.narration}</td>
                  <td style={{ padding: 4 }} className="muted">{s.visual_prompt}</td>
                  <td style={{ padding: 4 }} className="muted">{s.motion_prompt}</td>
                  <td style={{ padding: 4 }}><b>{s.visual_claim_ko}</b><br /><span className="muted">근거 {s.claim_ids.join(", ") || "없음"} · 단순화 {s.allowed_simplification}<br />금지할 오해: {s.forbidden_misreading}</span></td>
                  <td style={{ padding: 4 }}>{s.clip_sec}초{s.candidates_planned > 1 ? ` × 후보 ${s.candidates_planned}` : ""}<br /><span className="muted">사용 {(s.last_src_ms / 1000).toFixed(1)}초</span></td>
                  <td style={{ padding: 4 }}>{usd(s.image_est_usd + s.clip_est_usd * s.candidates_planned)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </details>
      )}

      {d && (
        <div className="dk-sub">
          <b>결재</b>
          {status.approvals.length === 0 ? <p className="muted">결재가 없습니다.</p> : status.approvals.map((a) => (
            <div key={a.approval_id} className="list-row">
              <span className={a.status === "open" && !a.expired ? "pill dk-ok" : "pill"}>{a.status === "open" ? (a.expired ? "기간 지남" : "열림") : "닫힘"}</span>{" "}
              {a.stage} · {a.allowed_kinds.join("·")} · 상한 {usd(a.cap_usd, 2)} · 확정 {usd(a.spent_usd)} · 가잡힘 {usd(a.held_usd)} · 남음 <b>{usd(a.remaining_usd)}</b> · 기한 {kstMinute(a.expires_at)}
            </div>
          ))}
          {!open && <OpenApproval planId={planId} cap={Math.min(10, d.estimate.suggested_cap_usd)} orderHash={ep?.order_hash ?? null} provider={ep?.provider} />}
          {open && ["directive_ready", "approved", "buying", "blocked_budget"].includes(ep?.state ?? "") && (
            <div className="actions">
              <label className="muted">이 슬롯까지만 <input style={{ width: 60 }} placeholder="전부" value={through} onChange={(e) => setThrough(e.target.value)} /></label>
              {!buyClaimed && <button className="btn pick" disabled={busy || busyJob} title={busyTitle} onClick={requestBuy}>{status.slots.length ? "이어서 구매 요청" : "구매 요청"}</button>}
              {note && <span className="muted">{note}</span>}
            </div>
          )}
        </div>
      )}

      {status.slots.length > 0 && (
        <div>
          <h4>슬롯·후보 <span className="muted">누적 {usd(total)}</span></h4>
          {[...status.slots].sort((a, b) => a.n - b.n).map((s) => {
            const c = bySlot.get(s.n);
            return (
              <article key={s.slot_id} className="card">
                <div className="dk-row">
                  <b>{s.n}번</b> <span className="pill">{ROLE[s.role]}</span> <span className={s.status === "selected" ? "pill dk-ok" : s.status === "no_pass" ? "pill dk-bad" : "pill"}>{s.status}</span>
                  <span className="muted">들어옴 {BOUNDARY[s.boundary_in ?? ""] ?? s.boundary_in} · 그림 {usd(c?.imageUsd)} + 클립 {usd(c?.clipsUsd)} = <b>{usd(c?.totalUsd)}</b> · 누적 {usd(c?.cumulativeUsd)}{c?.unknownHeldUsd ? ` · 결과 모름 ${usd(c.unknownHeldUsd)} 가잡힘` : ""}</span>
                </div>
                {s.selection && <p className="muted">선택: 후보 {s.selection.candidate_id.slice(-1)} — {s.selection.reason} ({s.selection.selected_by}, {kstMinute(s.selection.selected_at)})</p>}
                <div className="dk-row" style={{ alignItems: "flex-start" }}>{s.candidates.map((x) => <Candidate key={x.candidate_id} slot={s} c={x} />)}</div>
              </article>
            );
          })}
        </div>
      )}

      {step === "request_assemble" && (
        <div className="actions">
          {!assembleClaimed && <button className="btn pick" disabled={busy || busyJob} onClick={requestAssemble}>
            {ep?.state === "assets_complete" ? "조립 요청 (0원)" : "다시 조립 (0원)"}</button>}
          <span className="muted">선택된 클립만 잘라 잇습니다. 자동 검사를 통과해야 파일이 생깁니다.</span>
        </div>
      )}
      {step === "process_review" && <ReviewForm planId={planId} stage="process" title="과정 검수" items={PROCESS_CHECKS} />}
      {step === "quality_review" && <ReviewForm planId={planId} stage="quality" title="품질 검수 6항목" items={QUALITY_CHECKS} />}
      {step === "output_review" && <p className="banner-info">품질 검수를 통과했습니다 — 아래 파일 묶음을 승인하면 게시 대기로 갑니다.</p>}
      {step === "none" && ep?.state === "ready_to_publish" && <p className="banner-info">게시 대기입니다. 게시 화면에서 발행안을 만드세요. 캡션에 “AI 생성 영상” 한 줄을 넣으세요(§3-4, 코드가 넣지 않습니다).</p>}
    </section>
  );
}
