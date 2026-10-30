"use client";

// 주류 소재 개발 운영자 동작 — 근거 초안·대본 초안 요청/취소, 개발 결재 열기/닫기, 진행 중 자동 새로고침.
// ★ 화면은 요청을 큐에 넣을 뿐이다. 초안을 쓰는 일과 결재 금액 안에서의 비용 확정은 워커·DB 가 한다.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { requestNote, type DevelopKind } from "@/lib/drinks/develop";

import { useDrinksAction } from "./useDrinksAction";

export function DevelopRequest({ topicId, kind, budgetId, enabled, reason, label }: {
  topicId: string; kind: DevelopKind; budgetId: string | null; enabled: boolean; reason: string | null; label: string;
}) {
  const { run, busy } = useDrinksAction();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span>
      <button className="btn pick" disabled={busy || !enabled} title={reason ?? ""}
        onClick={async () => {
          const r = await run("request_develop", { topic_id: topicId, kind, ...(budgetId ? { budget_id: budgetId } : {}) },
            `${kind === "evidence" ? "근거 초안" : "대본·장면 초안"}을 요청했습니다`, "초안 요청");
          if (r.ok) setMsg(requestNote({ existing: (r.result as { existing?: boolean } | undefined)?.existing, triggered: r.dispatch?.triggered }));
        }}>{label}</button>
      {!enabled && reason && <span className="muted"> {reason}</span>}
      {msg && <span className="muted"> {msg}</span>}
    </span>
  );
}

export function CancelDevelop({ requestId }: { requestId: string }) {
  const { run, busy } = useDrinksAction();
  return <button className="btn" disabled={busy} onClick={() => run("cancel_develop", { request_id: requestId }, "취소를 요청했습니다", "취소")}>취소</button>;
}

/** 개발 결재 등록 — 결재권자가 승인한 말을 그대로 남긴다. 상한·기간은 DB 가 다시 잰다. */
export function OpenDevelopBudget() {
  const { run, busy } = useDrinksAction();
  const [stage, setStage] = useState("");
  const [cap, setCap] = useState("1.00");
  const [days, setDays] = useState("7");
  const [words, setWords] = useState("");
  const ok = Boolean(stage.trim() && words.trim()) && Number(cap) > 0 && Number.isInteger(Number(days)) && Number(days) >= 1;
  return (
    <div className="dk-row">
      <input placeholder="단계(예: 0단계 근거·대본 초안)" value={stage} onChange={(e) => setStage(e.target.value)} />
      <label className="muted">상한 $<input style={{ width: 80 }} value={cap} onChange={(e) => setCap(e.target.value)} /></label>
      <label className="muted">기간 <input style={{ width: 50 }} value={days} onChange={(e) => setDays(e.target.value)} />일</label>
      <input placeholder="결재 문장(승인한 말 그대로)" value={words} onChange={(e) => setWords(e.target.value)} />
      <button className="btn" disabled={busy || !ok}
        onClick={() => run("open_develop_budget", { stage: stage.trim(), cap_usd: Number(cap), days: Number(days), approver_words: words },
          "개발 결재를 등록했습니다", "결재 등록")}>결재 등록</button>
    </div>
  );
}

export function CloseDevelopBudget({ budgetId }: { budgetId: string }) {
  const { run, busy } = useDrinksAction();
  return (
    <button className="btn" disabled={busy}
      onClick={() => run("close_develop_budget", { budget_id: budgetId, reason: "운영자가 대시보드에서 닫음" }, "개발 결재를 닫았습니다", "결재 닫기")}>결재 닫기</button>
  );
}

/** 대기·진행 중인 요청이 있는 동안 화면을 주기적으로 다시 읽는다(탭이 보일 때만). */
export function AutoRefresh({ active, everyMs = 8000 }: { active: boolean; everyMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, everyMs);
    return () => clearInterval(t);
  }, [active, everyMs, router]);
  return null;
}
