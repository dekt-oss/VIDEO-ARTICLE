// 후보 카드(서버 컴포넌트) — 승인 목업(docs/mockups/drinks/02-topics) 모양: 추천 형식 · 신호 · 큰 질문 · 한 줄 · 근거 칩 · [이걸로 →] / 막힘.
//   임시 점수·적합도·관심 신호·추천 이유·중복 소재 링크는 지우지 않고 [자세히] 안으로 접었다.
//   근거 수는 보이는 쪽만 센다: 못 읽었으면 "모름", 읽었는데 없으면 0, 있으면 N — 셋을 섞지 않는다.
import Link from "next/link";

import { SIGNAL_LABEL, interestText, type CandidateRow } from "@/lib/drinks/discovery";
import { RECOMMENDED_LABEL, type Recommendation } from "@/lib/drinks/formatRecommend";
import { type EstimateMap, type Pickability, type WeekOption } from "@/lib/drinks/pickModal";
import { ReopenCandidate } from "../DiscoveryControls";
import PickModal from "./PickModal";

export interface CandidateCardProps {
  c: CandidateRow;
  rec: Recommendation;
  /** undefined = 근거 수를 못 읽음(모름). { count: 0 } = 읽었는데 없음 */
  evidence: { count: number; chars: number } | undefined;
  evidenceLoaded: boolean;
  dupTopics: { id: string; title: string }[];
  pick: Pickability;
  weeks: WeekOption[];
  budget: { budget_id: string; remaining_usd: number | string; expires_at: string } | null;
  estimate: EstimateMap;
}

// 막힌 카드의 회색 버튼 글자(짧게) — 긴 이유는 버튼 아래 한 줄로. 규칙(pickability)은 그대로 lib/drinks/pickModal.ts.
const BLOCKED_LABEL: Record<string, string> = { promoted: "이미 소재로 올림", no_score: "점수 대기", duplicate: "비슷한 소재 있음", no_budget: "AI 초안 한도 없음" };
/** 이 화면에서는 "결재" 대신 "AI 초안 한도"로 말한다(2026-11-06 운영자). 한도 없음은 위쪽 한도 카드를 가리킨다. */
function blockedReason(pick: Extract<Pickability, { ok: false }>): string {
  if (pick.code === "no_budget") return "이번 주 AI 초안 한도를 다 썼습니다 — 위에서 [한도 +$1]";
  return pick.reason;
}

export default function CandidateCard({ c, rec, evidence, evidenceLoaded, dupTopics, pick, weeks, budget, estimate }: CandidateCardProps) {
  const evText = !evidenceLoaded || evidence === undefined ? "모름" : evidence.count === 0 ? "없음" : `${evidence.count}개`;
  const evTone = !evidenceLoaded || evidence === undefined ? "pill dk-warn" : evidence.count === 0 ? "pill dk-warn" : "pill dk-ok";
  const topRight = c.signals.map((s) => SIGNAL_LABEL[s] ?? s).join(" · ");
  return (
    <article className="card dk-topic">
      <div className="dk-topic-top">
        <span className={rec.format === "unknown" ? "pill dk-warn" : "pill"}>{rec.format === "unknown" ? "추천 모름" : `${RECOMMENDED_LABEL[rec.format]} 추천`}</span>
        {topRight && <span className="dk-cat">{topRight}</span>}
      </div>
      <h2>{c.key_question}</h2>
      <p className="dk-one">{c.reader_value ?? rec.reason}</p>
      {c.status === "promoted" && c.promoted_topic_id && <p className="dk-kv" style={{ marginTop: 8 }}>→ <Link href={`/drinks/work/${c.promoted_topic_id}`}>올린 소재의 작업공간</Link></p>}
      {c.status === "dismissed" && <p className="dk-kv" style={{ marginTop: 8 }}>기각 사유: {c.decision_reason} <ReopenCandidate id={c.id} version={c.version} /></p>}

      <details className="dk-more-info">
        <summary>자세히</summary>
        <div className="dk-row">
          <span className="status-pill">임시 {c.provisional_score ?? "—"}점</span>
          {c.signals.map((s) => <span key={s} className="pill">{SIGNAL_LABEL[s] ?? s}</span>)}
          {c.status !== "suggested" && <span className="pill">{c.status === "promoted" ? "소재로 올림" : c.status === "dismissed" ? "기각" : "합쳐짐"}</span>}
        </div>
        <p className="dk-kv">독자 효용: <b>{c.reader_value ?? "—"}</b> · 영상 적합 <b>{c.fit_video ?? "—"}</b> · 카드 적합 <b>{c.fit_carousel ?? "—"}</b> · 관심 신호: {interestText(c.interest)}</p>
        <p className="dk-kv">추천 이유: {rec.reason}</p>
        {dupTopics.length > 0 && (
          <p className="dk-kv">
            중복 후보 소재: {dupTopics.map((t) => <span key={t.id}><Link href={`/drinks/work/${t.id}`}>{t.title}</Link>{" "}</span>)}
            <span className="muted">— 새로 만들지 말고 그 소재의 작업공간에서 형식을 더하세요.</span>
          </p>
        )}
      </details>

      <div className="dk-topic-foot">
        <span className="dk-row">
          <span className={evTone}>근거 {evText}</span>
          {dupTopics.length > 0 && <span className="pill dk-warn">비슷한 기존 소재 {dupTopics.length}</span>}
        </span>
        {c.status === "suggested" && (pick.ok ? (
          <PickModal c={c} recommended={rec} weeks={weeks} budget={budget} estimate={estimate} />
        ) : (
          <>
            <button className="btn" type="button" disabled aria-disabled="true" aria-describedby={`why-${c.id}`}>{BLOCKED_LABEL[pick.code] ?? "막힘"}</button>
            <p className="dk-blocked-why" id={`why-${c.id}`}>막힘: {blockedReason(pick)}</p>
          </>
        ))}
      </div>
    </article>
  );
}
