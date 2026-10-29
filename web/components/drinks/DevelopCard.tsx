// 주류 소재 개발 카드 — 개발 결재(예산) 한 줄, 초안 요청 버튼, 요청 상태 목록. 서버 컴포넌트.
// 초안은 기존 근거 검토·제작안 화면에 들어온다(이 카드는 요청·상태·결재만). 0060 이 없으면 카드가 그 사실만 말한다.
import Link from "next/link";

import {
  AutoRefresh, CancelDevelop, CloseDevelopBudget, DevelopRequest, OpenDevelopBudget,
} from "@/components/drinks/DevelopControls";
import { fmtTime } from "@/components/drinks/RunPill";
import {
  DEVELOP_KIND_LABEL, DEVELOP_STATUS_LABEL, developButtons, developErrorView, isActive, pickBudget, resultLinks, sortRequests,
  statusTone, usableBudgets, type DevelopRequestRow,
} from "@/lib/drinks/develop";
import type { DevelopLoad } from "@/lib/drinks/queries";

const TONE_CLASS = { ok: "pill dk-ok", warn: "pill dk-warn", bad: "pill dk-bad", info: "pill" } as const;
const usd = (v: number | string | null | undefined, digits = 3) => `$${(Number.isFinite(Number(v)) ? Number(v) : 0).toFixed(digits)}`;

export default function DevelopCard({ topicId, topicStatus, approvedEvidence, plans, develop }: {
  topicId: string; topicStatus: string; approvedEvidence: boolean; plans: { id: string; format: string }[]; develop: DevelopLoad;
}) {
  return (
    <section className="card" style={{ marginTop: 12 }}>
      <h3 style={{ marginTop: 0 }}>소재 개발 — 근거·대본 초안 자동 생성</h3>
      <Body topicId={topicId} topicStatus={topicStatus} approvedEvidence={approvedEvidence} plans={plans} develop={develop} />
    </section>
  );
}

function Body({ topicId, topicStatus, approvedEvidence, plans, develop }: {
  topicId: string; topicStatus: string; approvedEvidence: boolean; plans: { id: string; format: string }[]; develop: DevelopLoad;
}) {
  if (develop.state === "missing") {
    return <p className="banner-warn">0060 이 운영 DB 에 아직 없습니다 — 마이그레이션을 적용하면 이 카드가 열립니다. 지금은 근거·제작안을 직접 입력하는 기존 방식만 쓸 수 있습니다.</p>;
  }
  if (develop.state === "unconfigured") {
    return <p className="banner-warn">서버에 SUPABASE_SERVICE_KEY 가 없어 개발 상태를 읽을 수 없습니다.</p>;
  }
  if (develop.state === "failed") {
    return <p className="banner-block" role="alert">개발 상태를 불러오지 못했습니다 — 요청 0건이 아니라 조회 실패입니다. {develop.error}</p>;
  }
  const now = Date.now();
  const budgets = usableBudgets(develop.budgets, now);
  const budget = pickBudget(develop.budgets, now);
  const requests = sortRequests(develop.requests);
  const btn = developButtons({ topicStatus, hasBudget: budget !== null, approvedEvidence, requests });
  const anyActive = requests.some(isActive);
  return (
    <>
      <AutoRefresh active={anyActive} />
      <p className="muted" style={{ marginTop: 0 }}>
        소재의 출처로 근거 초안을, 승인된 근거로 대본·장면 초안을 만듭니다. 만든 초안은 기존 <b>근거</b> 탭·제작안 탭에 <b>작성 중</b>으로 들어오고,
        승인은 사람이 합니다.
      </p>

      <div className="dk-sub">
        <b>개발 결재</b>
        {budgets.length === 0 ? (
          <p className="muted" style={{ margin: "6px 0" }}>열린 개발 결재 없음 — 근거·대본 초안은 결재가 있어야 만듭니다.</p>
        ) : budgets.map((b) => (
          <div key={b.budget_id} className="list-row">
            <span>
              <span className={b.budget_id === budget?.budget_id ? "pill dk-ok" : "pill"}>열림</span> {b.stage} · 상한 {usd(b.cap_usd, 2)} · 확정 {usd(b.spent_usd)} ·
              가잡힘 {usd(b.held_usd)} · 남음 <b>{usd(b.remaining_usd)}</b> · 기한 {fmtTime(b.expires_at)}
              {b.approver_words && <span className="muted"> · “{b.approver_words}”</span>}
            </span>
            <CloseDevelopBudget budgetId={b.budget_id} />
          </div>
        ))}
        <details style={{ marginTop: 6 }}>
          <summary className="muted" style={{ cursor: "pointer" }}>개발 결재 등록</summary>
          <OpenDevelopBudget />
        </details>
      </div>

      <div className="actions" style={{ marginTop: 10 }}>
        <DevelopRequest topicId={topicId} kind="evidence" budgetId={budget?.budget_id ?? null} enabled={btn.evidence.enabled}
          reason={btn.evidence.reason} label="근거 초안 만들기" />
      </div>
      <div className="actions" style={{ marginTop: 6 }}>
        <DevelopRequest topicId={topicId} kind="plan" budgetId={budget?.budget_id ?? null} enabled={btn.plan.enabled}
          reason={btn.plan.reason} label="대본·장면 초안 만들기" />
      </div>

      <h4 style={{ margin: "14px 0 4px" }}>요청 상태</h4>
      {requests.length === 0 ? <p className="muted">아직 요청한 초안이 없습니다.</p> : requests.map((r) => (
        <RequestRow key={r.request_id} r={r} topicId={topicId} plans={plans} />
      ))}
    </>
  );
}

function RequestRow({ r, topicId, plans }: { r: DevelopRequestRow; topicId: string; plans: { id: string; format: string }[] }) {
  const err = developErrorView(r.error_code, r.error_message);
  const links = resultLinks(topicId, r, plans);
  return (
    <div className="list-row" style={{ alignItems: "flex-start" }}>
      <span>
        <b>{DEVELOP_KIND_LABEL[r.kind] ?? r.kind}</b>{" "}
        <span className={TONE_CLASS[statusTone(r.status)]}>{DEVELOP_STATUS_LABEL[r.status] ?? r.status}</span>
        {r.step && <span className="muted"> · 단계 {r.step}</span>}
        <span className="muted"> · 비용 {usd(r.cost_usd, 4)} · 요청 {fmtTime(r.created_at)} · 끝 {fmtTime(r.finished_at)}</span>
        {err && (
          <span className="dk-bad" style={{ display: "block" }}>
            {err.text}
            {err.detail && <span className="muted" style={{ display: "block" }}>사유: {err.detail}</span>}
          </span>
        )}
        {links.map((l) => <span key={l.href}> · <Link href={l.href}>{l.label} →</Link></span>)}
      </span>
      {isActive(r) && <CancelDevelop requestId={r.request_id} />}
    </div>
  );
}
