"use client";

// 주류 제작 운영자 동작 — 렌더 요청(로컬·무료)·재시도·취소, 최종 파일 검수(체크리스트 → 승인/고칠 점/철회).
// ★ 생성 성공은 승인이 아니다. 승인은 사람이 체크리스트를 모두 확인해야 하고, DB 가 그 순간 근거·제작안 유효성을 다시 잰다.
import { useState } from "react";

import { useDrinksAction, type DrinksResult } from "./useDrinksAction";

function note(r: DrinksResult): string | null {
  if (!r.ok) return null;
  if ((r.result as { existing?: boolean } | undefined)?.existing) return "같은 입력의 작업이 이미 대기·진행 중입니다 — 그 작업을 보여줍니다.";
  if (r.dispatch?.triggered) return "제작 워커를 깨웠습니다.";
  return "대기열에 넣었습니다. 워커 자동 깨우기가 설정되지 않아 수동 실행(python -m engine.drinks_produce) 때 처리됩니다.";
}

export function RenderRequest({ planId, retryOf, label }: { planId: string; retryOf?: string; label: string }) {
  const { run, busy } = useDrinksAction();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span>
      <button className="btn pick" disabled={busy} onClick={async () => setMsg(note(await run("request_render",
        { plan_revision_id: planId, ...(retryOf ? { retry_of: retryOf } : {}) }, "렌더를 요청했습니다(로컬·무료)", "렌더 요청")))}>{label}</button>
      {msg && <span className="muted"> {msg}</span>}
    </span>
  );
}

/** 유료 렌더 요청 — 열린 결재가 있고 예상 금액이 남은 금액 안일 때만. 실제 상한은 DB 가 호출마다 잰다. */
export function PaidRenderRequest({ planId, approvalId, estimate, remaining, blocked }: {
  planId: string; approvalId: string; estimate: number; remaining: number; blocked: string | null;
}) {
  const { run, busy } = useDrinksAction();
  const [msg, setMsg] = useState<string | null>(null);
  const why = blocked ?? (estimate > remaining ? `예상 $${estimate.toFixed(3)} 가 남은 결재 금액 $${remaining.toFixed(3)} 보다 큽니다` : null);
  return (
    <span>
      <button className="btn pick" disabled={busy || Boolean(why)} title={why ?? ""}
        onClick={async () => {
          if (!window.confirm(`유료 렌더를 요청합니다. 예상 $${estimate.toFixed(3)} · 남은 결재 금액 $${remaining.toFixed(3)}. 진행할까요?`)) return;
          setMsg(note(await run("request_render", { plan_revision_id: planId, paid: true, spend_approval_id: approvalId },
            "유료 렌더를 요청했습니다(결재 금액 안에서만 삽니다)", "유료 렌더 요청")));
        }}>유료 렌더 요청 (예상 ${estimate.toFixed(3)})</button>
      {why && <span className="muted"> {why}</span>}
      {msg && <span className="muted"> {msg}</span>}
    </span>
  );
}

/** 결재 등록 — 결재권자가 승인한 말을 그대로 남긴다. 상한은 $10 을 넘을 수 없다(DB). */
export function OpenSpendApproval({ planId, suggestedCap }: { planId: string; suggestedCap: number }) {
  const { run, busy } = useDrinksAction();
  const [cap, setCap] = useState(suggestedCap.toFixed(2));
  const [stage, setStage] = useState("");
  const [words, setWords] = useState("");
  return (
    <div className="dk-row">
      <input placeholder="단계(예: 3단계 한 편 완성)" value={stage} onChange={(e) => setStage(e.target.value)} />
      <label className="muted">상한 $<input style={{ width: 80 }} value={cap} onChange={(e) => setCap(e.target.value)} /></label>
      <input placeholder="결재 문장(승인한 말 그대로)" value={words} onChange={(e) => setWords(e.target.value)} />
      <button className="btn" disabled={busy || !stage || !words || !(Number(cap) > 0)}
        onClick={() => run("open_spend_approval", { plan_revision_id: planId, stage, purpose: `${stage} — 이 제작안의 그림 생성`,
          cap_usd: Number(cap), allowed_kinds: ["image"], approver_words: words }, "결재를 등록했습니다", "결재 등록")}>결재 등록</button>
    </div>
  );
}

export function CloseSpendApproval({ approvalId }: { approvalId: string }) {
  const { run, busy } = useDrinksAction();
  const [reason, setReason] = useState("");
  return (
    <span>
      <input placeholder="닫는 이유" value={reason} onChange={(e) => setReason(e.target.value)} />
      <button className="btn" disabled={busy || !reason}
        onClick={() => run("close_spend_approval", { approval_id: approvalId, reason }, "결재를 닫았습니다", "결재 닫기")}>결재 닫기</button>
    </span>
  );
}

export function CancelRender({ jobId }: { jobId: string }) {
  const { run, busy } = useDrinksAction();
  return <button className="btn" disabled={busy} onClick={() => run("cancel_render", { job_id: jobId }, "취소를 요청했습니다", "취소")}>취소</button>;
}

const CHECKS = {
  video: [
    ["scene_types_labeled", "장면마다 유형(연출 장면·설명용 도해)이 보인다"],
    ["no_real_product_implied", "실제 제품·시설 촬영이나 정확한 제조 과정으로 오해될 장면이 없다"],
    ["claims_match_evidence", "말한 사실이 승인된 근거와 같다"],
    ["audio_subtitles_ok", "나레이션이 들리고 자막이 맞다"],
    ["vertical_ok", "세로(9:16)이고 잘린 글자가 없다"],
  ],
  carousel: [
    ["page_order_ok", "페이지 순서가 제작안과 같다"],
    ["no_text_overflow", "넘치거나 잘린 글자가 없다"],
    ["claims_match_evidence", "적힌 사실이 승인된 근거와 같다"],
    ["source_page_ok", "출처 페이지가 정확하다"],
  ],
} as const;

export function OutputReview({ review, format, usableNow }: {
  review: { id: string; version: number; status: string }; format: "video" | "carousel"; usableNow: boolean;
}) {
  const { run, busy } = useDrinksAction();
  const items = CHECKS[format];
  const [ck, setCk] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const all = items.every(([k]) => ck[k]);
  if (review.status === "approved") {
    return (
      <div className="dk-row">
        <input placeholder="철회 사유" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn" disabled={busy || !reason} onClick={() => run("output_review_action",
          { review_id: review.id, expected_version: review.version, action: "revoke", reason }, "파일 승인을 철회했습니다", "철회")}>승인 철회</button>
      </div>
    );
  }
  if (review.status === "blocked") return null;
  return (
    <div className="dk-sub">
      <b>최종 파일 검수</b>
      {items.map(([k, l]) => (
        <label key={k} className="dk-checks" style={{ display: "flex" }}>
          <input type="checkbox" checked={Boolean(ck[k])} onChange={(e) => setCk({ ...ck, [k]: e.target.checked })} /> {l}
        </label>
      ))}
      <div className="actions">
        <button className="btn pick" disabled={busy || !all || !usableNow}
          title={!usableNow ? "제작안·근거가 지금 유효하지 않습니다" : !all ? "모든 항목을 확인하세요" : ""}
          onClick={() => run("output_review_action", { review_id: review.id, expected_version: review.version, action: "approve", checklist: ck },
            "파일 묶음을 승인했습니다", "파일 승인")}>이 파일 묶음 승인</button>
        <input placeholder="고칠 점" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn" disabled={busy || !reason} onClick={() => run("output_review_action",
          { review_id: review.id, expected_version: review.version, action: "request_changes", reason, checklist: ck }, "고칠 점을 남겼습니다", "고칠 점")}>
          고칠 점 남기기</button>
      </div>
    </div>
  );
}
