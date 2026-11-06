// 후보 카드(서버 컴포넌트) — 질문 · 추천 형식 + 이유 · 신호 · 중복 경고 · 지금 고를 수 있나(가능 / 막힘 + 이유) · [이걸로 ▾].
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

export default function CandidateCard({ c, rec, evidence, evidenceLoaded, dupTopics, pick, weeks, budget, estimate }: CandidateCardProps) {
  const evText = !evidenceLoaded || evidence === undefined ? "모름" : evidence.count === 0 ? "없음" : `${evidence.count}개`;
  const evTone = !evidenceLoaded || evidence === undefined ? "pill dk-warn" : evidence.count === 0 ? "pill dk-warn" : "pill dk-ok";
  return (
    <article className="card">
      <div className="dk-row">
        <span className={rec.format === "unknown" ? "pill dk-warn" : "pill on"}>{rec.format === "unknown" ? "추천 모름" : `${RECOMMENDED_LABEL[rec.format]} 추천`}</span>
        <span className="status-pill">임시 {c.provisional_score ?? "—"}점</span>
        {c.signals.map((s) => <span key={s} className="pill">{SIGNAL_LABEL[s] ?? s}</span>)}
        <span className={evTone}>근거 {evText}</span>
        {dupTopics.length > 0 && <span className="pill dk-warn">비슷한 기존 소재 {dupTopics.length}</span>}
        {c.status !== "suggested" && <span className="pill">{c.status === "promoted" ? "소재로 올림" : c.status === "dismissed" ? "기각" : "합쳐짐"}</span>}
      </div>
      <h2 style={{ marginTop: 8, fontSize: 18 }}>{c.key_question}</h2>
      <p className="dk-kv">독자 효용: <b>{c.reader_value ?? "—"}</b> · 영상 적합 <b>{c.fit_video ?? "—"}</b> · 카드 적합 <b>{c.fit_carousel ?? "—"}</b> · 관심 신호: {interestText(c.interest)}</p>
      <p className="dk-kv">추천 이유: {rec.reason}</p>
      {dupTopics.length > 0 && (
        <p className="dk-kv">
          중복 후보 소재: {dupTopics.map((t) => <span key={t.id}><Link href={`/drinks/work/${t.id}`}>{t.title}</Link>{" "}</span>)}
          <span className="muted">— 새로 만들지 말고 그 소재의 작업공간에서 형식을 더하세요.</span>
        </p>
      )}
      {c.status === "promoted" && c.promoted_topic_id && <p className="dk-kv">→ <Link href={`/drinks/work/${c.promoted_topic_id}`}>올린 소재의 작업공간</Link></p>}
      {c.status === "dismissed" && <p className="dk-kv">기각 사유: {c.decision_reason} <ReopenCandidate id={c.id} version={c.version} /></p>}
      {c.status === "suggested" && (
        <div className="actions" style={{ alignItems: "center" }}>
          {pick.ok ? (
            <PickModal c={c} recommended={rec} weeks={weeks} budget={budget} estimate={estimate} />
          ) : (
            <>
              <button className="btn" type="button" disabled aria-disabled="true">막힘</button>
              <span className="muted">{pick.reason}</span>
            </>
          )}
          {pick.ok && <span className="muted">지금 고를 수 있음</span>}
        </div>
      )}
    </article>
  );
}
