// 주류 소재 상세 (/drinks/review/[topicId]?tab=) — 요약 / 근거 / 공통 기획 / 영상 / 카드뉴스 / 이력(명세 §9.2).
// 주 버튼(다음 행동)은 상태에서 계산한 하나만 위에 보여준다. 모든 승인·편성은 서버가 다시 검사한다.
import Link from "next/link";

import BriefTab from "@/components/drinks/BriefTab";
import EvidenceTab from "@/components/drinks/EvidenceTab";
import LoadProblem from "@/components/drinks/LoadProblem";
import PlanTab from "@/components/drinks/PlanTab";
import TopicPanel from "@/components/drinks/TopicPanel";
import { seoulDateTimeLabel, todayInSeoul } from "@/lib/date";
import {
  CATEGORY_LABEL, FORMAT_LABEL, LANE_LABEL, TOPIC_STATUS_LABEL, VERSION_STATUS_LABEL, deriveTopic, type Format,
} from "@/lib/drinks/model";
import { EVENTS_LIMIT, loadTopic } from "@/lib/drinks/queries";
import type { EventRow } from "@/lib/drinks/types";

export const dynamic = "force-dynamic";

const TABS = [
  ["overview", "요약"],
  ["evidence", "근거"],
  ["brief", "공통 기획"],
  ["video", "영상"],
  ["carousel", "카드뉴스"],
  ["history", "이력"],
] as const;
type Tab = (typeof TABS)[number][0];

export default async function DrinksTopicPage(props: {
  params: Promise<{ topicId: string }>;
  searchParams: Promise<{ tab?: string; events?: string }>;
}) {
  const { topicId } = await props.params;
  const { tab: rawTab, events: rawEvents } = await props.searchParams;
  // 이력은 의도적 상한(기본 200, 최대 1000). [더 보기]로 늘린다.
  const eventsLimit = Math.min(1000, Math.max(EVENTS_LIMIT, Number(rawEvents) || EVENTS_LIMIT));
  const res = await loadTopic(topicId, eventsLimit);
  if (res.state === "not_found") {
    return (
      <main className="container">
        <p>소재를 찾지 못했습니다. <Link href="/drinks">선별로</Link></p>
      </main>
    );
  }
  if (res.state !== "ok") {
    return (
      <main className="container">
        <LoadProblem state={res.state} error={res.state === "failed" ? res.error : undefined} />
      </main>
    );
  }
  const { topic, sources, reviews, deliverables, plans, events, eventsTotal, canonical } = res.data;
  // 클라이언트 컴포넌트로 넘기려고 Map 을 평범한 객체로 바꾼다.
  const attestations = Object.fromEntries(res.data.attestations);
  const sameBody = Object.fromEntries(res.data.sameBody);
  const sharedWith = Object.fromEntries(res.data.sharedWith);
  const d = deriveTopic(topic, new Map(reviews.map((r) => [r.id, r])), deliverables, new Map(plans.map((p) => [p.id, p])));
  const tab: Tab = TABS.some(([k]) => k === rawTab) ? (rawTab as Tab) : d.action.tab;
  const review = d.review;
  const reviewKey = `${review?.id ?? "none"}-${review?.version ?? 0}-${topic.version}`;
  const deliverableOf = (f: Format) => deliverables.find((x) => x.format === f) ?? null;

  return (
    <main className="container">
      <p className="muted"><Link href="/drinks/review">← 작업함</Link></p>
      <div className="dk-row">
        <span className="status-pill">{TOPIC_STATUS_LABEL[topic.status]}</span>
        {topic.categories.map((c) => <span key={c} className="pill">{CATEGORY_LABEL[c]}</span>)}
        <span className="pill">{LANE_LABEL[topic.lane]}</span>
        {topic.status === "selected" && (
          <span className="pill">
            {topic.editorial_week} 주 · {(topic.selected_formats ?? []).map((f) => FORMAT_LABEL[f]).join("+")}
          </span>
        )}
      </div>
      <h1 style={{ fontSize: 20, margin: "8px 0" }}>{topic.title}</h1>
      <p className="oneliner">Q. {topic.question}</p>
      {topic.reader_value && <p className="muted">효용: {topic.reader_value}</p>}
      <p className="dk-kv">
        대상 <b>{topic.target_subject || "—"}</b> · 각도 <b>{topic.angle || "—"}</b> · 경량 점수 <b>{d.provisionalScore ?? "—"}</b> ·
        편성 평가 <b>{d.finalScore ?? "—"}</b>
        {d.approvedReview && d.review && d.approvedReview.id !== d.review.id && (
          <> · 승인 버전 <b>{d.approvedReview.revision_no}</b>{d.approvalValid ? "" : d.approvedReview.revoked_at ? "(철회됨)" : "(지금 사용 불가)"} / 작업 중 버전 <b>{d.review.revision_no}</b></>
        )}
      </p>

      <div className={d.action.unavailable ? "banner-warn" : "banner-info"} style={{ marginTop: 10 }}>
        <b>다음 행동: {d.action.label}{d.action.unavailable ? " (미연결)" : ""}</b> — {d.action.hint}{" "}
        {!d.action.unavailable && d.action.tab !== tab && (
          <Link href={`/drinks/review/${topic.id}?tab=${d.action.tab}`}>이 작업으로 가기 →</Link>
        )}
      </div>

      <nav className="dk-tabs" aria-label="소재 탭">
        {TABS.map(([k, label]) => (
          <Link key={k} href={`/drinks/review/${topic.id}?tab=${k}`} data-active={k === tab}>
            {label}
            {k === "video" || k === "carousel" ? formatBadge(d.plans[k as Format], (topic.selected_formats ?? []).includes(k as Format) && topic.status === "selected", d.planEvidenceValid[k as Format]) : ""}
          </Link>
        ))}
      </nav>

      {tab === "overview" && <TopicPanel key={topic.version} topic={topic} canonical={canonical} />}
      {tab === "evidence" && (
        <EvidenceTab key={reviewKey} topic={topic} review={review} sources={sources}
          attestations={attestations} sameBody={sameBody} sharedWith={sharedWith} />
      )}
      {tab === "brief" && <BriefTab key={reviewKey} topic={topic} review={review} reviews={reviews} plans={plans} today={todayInSeoul()} />}
      {(tab === "video" || tab === "carousel") && (
        <PlanTab
          key={`${tab}-${deliverableOf(tab)?.version ?? 0}-${topic.version}`}
          format={tab}
          topic={topic}
          reviews={reviews}
          deliverable={deliverableOf(tab)}
          plans={plans.filter((p) => p.format === tab)}
        />
      )}
      {tab === "history" && <History events={events} total={eventsTotal} topicId={topic.id} limit={eventsLimit} />}
    </main>
  );
}

function formatBadge(p: { plan_status: keyof typeof VERSION_STATUS_LABEL; blocked_at: string | null } | null | undefined, selected: boolean,
  evidenceValid: boolean | undefined) {
  if (!selected) return "";
  if (!p) return " · 제작안 없음";
  if (!p.blocked_at && evidenceValid === false) return " · 근거 사용 불가";
  return p.blocked_at ? " · 차단" : ` · ${VERSION_STATUS_LABEL[p.plan_status]}`;
}

function History({ events, total, topicId, limit }: { events: EventRow[]; total: number; topicId: string; limit: number }) {
  if (events.length === 0) return <p className="muted">이력이 없습니다(정상 0건).</p>;
  return (
    <section className="section">
      <h3>이력 — 전체 {total}건 중 최근 {events.length}건 (추가만 가능)</h3>
      {total > events.length && (
        <p className="banner-warn">
          오래된 이력 {total - events.length}건은 이 화면에 없습니다.{" "}
          {limit < 1000 ? (
            <Link href={`/drinks/review/${topicId}?tab=history&events=${Math.min(1000, limit + 500)}`}>더 보기 →</Link>
          ) : "한 화면 최대 1,000건입니다."}
        </p>
      )}
      {events.map((e) => (
        <div key={e.id} className="list-row">
          <span>
            <b>{e.action}</b> <span className="muted">{e.entity_type}</span>
            {e.before_status || e.after_status ? ` · ${e.before_status ?? "—"} → ${e.after_status ?? "—"}` : ""}
            {e.reason && <span className="muted"> · {e.reason}</span>}
          </span>
          <span className="muted">{seoulDateTimeLabel(e.created_at)}</span>
        </div>
      ))}
    </section>
  );
}
