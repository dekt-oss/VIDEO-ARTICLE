"use client";

// 소재 요약 탭 — 경량 평가(provisional 점수)와 소재 상태 동작(조사 후보 선택·보류·제외·다시 열기·중복).
// ★ 여기 점수는 "조사할 가치" 판단용 임시 점수다. 편성 평가는 근거·기획 버전에서 따로 매긴다(명세 §6.1).
import Link from "next/link";
import { useState } from "react";

import { REASON_CODE_LABEL, TOPIC_STATUS_LABEL, type Scores } from "@/lib/drinks/model";
import type { TopicRow } from "@/lib/drinks/types";
import ScoreInputs from "./ScoreInputs";
import { useDrinksAction } from "./useDrinksAction";

export default function TopicPanel({
  topic,
  canonical,
}: {
  topic: TopicRow;
  canonical: { id: string; title: string; status: string } | null;
}) {
  const { run, busy } = useDrinksAction();
  const [scores, setScores] = useState<Scores>(topic.provisional_scores ?? {});
  const [reason, setReason] = useState("");
  const [code, setCode] = useState("insufficient_evidence");
  const [holdUntil, setHoldUntil] = useState("");
  const [canonId, setCanonId] = useState("");
  const [triageReason, setTriageReason] = useState(topic.triage_reason ?? "");
  const [needs, setNeeds] = useState(topic.research_needs ?? "");
  const base = { topic_id: topic.id, expected_version: topic.version };
  const act = (action: string, extra: Record<string, unknown>, msg: string) =>
    run("topic_action", { ...base, action, ...extra }, msg, "소재 상태 변경");

  const triageOpen = topic.status === "inbox" || topic.status === "triaged";
  const closed = topic.status === "on_hold" || topic.status === "rejected" || topic.status === "duplicate";

  return (
    <div>
      {triageOpen && (
        <section className="dk-sub">
          <h3 style={{ margin: "0 0 6px" }}>경량 평가 (provisional)</h3>
          <p className="muted">조사 후보로 고를지 정하는 임시 점수입니다. 높아도 근거 확인·편성을 대신하지 않습니다.</p>
          <ScoreInputs value={scores} onChange={setScores} disabled={busy} />
          <label className="dk-field">임시 점수 사유
            <input value={triageReason} onChange={(e) => setTriageReason(e.target.value)} maxLength={1000}
              placeholder="왜 이 점수인지 한 줄" />
          </label>
          <label className="dk-field">조사 필요 사항
            <textarea value={needs} onChange={(e) => setNeeds(e.target.value)} maxLength={2000} rows={2}
              placeholder="확인해야 할 사실·찾아야 할 원출처" />
          </label>
          <div className="actions">
            <button className="btn" disabled={busy}
              onClick={() => run("triage", { ...base, scores, reason: triageReason, research_needs: needs },
                "경량 평가를 저장했습니다", "경량 평가 저장")}>
              경량 평가 저장
            </button>
            {topic.status === "triaged" && (
              <button className="btn pick" disabled={busy} onClick={() => act("start_research", {}, "조사 후보로 골랐습니다")}>
                조사하기 (조사 후보로 선택)
              </button>
            )}
          </div>
        </section>
      )}

      {closed ? (
        <section className="dk-sub">
          <p>
            상태: <b>{TOPIC_STATUS_LABEL[topic.status]}</b>
            {topic.decision_reason && ` — ${topic.decision_reason}`}
            {topic.hold_until && ` (재검토일 ${topic.hold_until})`}
          </p>
          {canonical && (
            <p className="muted">
              기준 소재: <Link href={`/drinks/review/${canonical.id}`}>{canonical.title}</Link>
            </p>
          )}
          <button className="btn pick" disabled={busy} onClick={() => act("reopen", {}, "소재를 다시 열었습니다")}>
            다시 열기
          </button>
        </section>
      ) : (
        <section className="dk-sub">
          <h3 style={{ margin: "0 0 6px" }}>보류·제외·중복</h3>
          <div className="dk-grid">
            <label className="dk-field">
              <span>사유 (필수)</span>
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <label className="dk-field">
              <span>제외 사유 분류</span>
              <select value={code} onChange={(e) => setCode(e.target.value)}>
                {Object.entries(REASON_CODE_LABEL).map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </label>
            <label className="dk-field">
              <span>보류 재검토일</span>
              <input type="date" value={holdUntil} onChange={(e) => setHoldUntil(e.target.value)} />
            </label>
          </div>
          <div className="actions">
            <button className="btn" disabled={busy || !reason.trim()}
              onClick={() => act("hold", { reason, hold_until: holdUntil || null }, "보류했습니다")}>
              보류
            </button>
            <button className="btn" disabled={busy || !reason.trim()}
              onClick={() => act("reject", { reason, reason_code: code }, "제외했습니다")}>
              제외
            </button>
            <button className="btn" disabled={busy} onClick={() => act("bump_signal", {}, "같은 질문 1건을 더했습니다")}>
              같은 질문 +1 (현재 {topic.reader_signal_count}건)
            </button>
          </div>
          {topic.status !== "selected" && (
            <div className="dk-row" style={{ marginTop: 8 }}>
              <label className="dk-field" style={{ flex: "1 1 260px" }}>
                <span>중복 처리 — 기준 소재 ID</span>
                <input value={canonId} onChange={(e) => setCanonId(e.target.value.trim())} placeholder="기준 소재 상세 주소의 ID" />
              </label>
              <button className="btn" disabled={busy || !canonId}
                onClick={() => act("mark_duplicate", { canonical_topic_id: canonId, reason: reason || null }, "중복으로 처리했습니다")}>
                중복으로 합치기
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
