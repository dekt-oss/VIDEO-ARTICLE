"use client";

// 공통 기획 탭 — 기획(질문·결론·제외 범위·효용·형식)과 편성 평가 점수, 검토·승인·철회, 편성.
// ★ 승인·편성 버튼은 화면 조건과 무관하게 서버가 다시 검사한다. 버튼이 눌린다고 통과하는 것이 아니다.
import { useState } from "react";

import {
  FORMAT_FIT_MIN, FORMAT_LABEL, FORMATS, SELECT_THRESHOLD, VERSION_STATUS_LABEL, blockerLabel, fitOk, nextMonday,
  weightedScore, type Format, type Scores,
} from "@/lib/drinks/model";
import type { Brief, PlanRow, ReviewRow, TopicRow } from "@/lib/drinks/types";
import { reviewEditTarget } from "./EvidenceTab";
import ScoreInputs from "./ScoreInputs";
import { useDrinksAction } from "./useDrinksAction";

const EMPTY_BRIEF: Brief = {
  audience_question: null, core_takeaway: null, selected_claim_ids: [], exclusions: null, useful_action: null,
  proposed_formats: [], required_claims: {}, followup_question: null,
};

export default function BriefTab({
  topic,
  review,
  reviews,
  plans,
  today,
}: {
  topic: TopicRow;
  review: ReviewRow | null;
  reviews: ReviewRow[];
  plans: PlanRow[];
  today: string;
}) {
  const { run, busy } = useDrinksAction();
  const [brief, setBrief] = useState<Brief>({ ...EMPTY_BRIEF, ...(review?.brief ?? {}) } as Brief);
  // 편성 평가는 경량 평가(provisional)를 복사하지 않고 새로 매긴다(명세 §6.1). 경량 점수는 옆에 참고로만 보인다.
  const [scores, setScores] = useState<Scores>(review?.scores ?? {});
  const [reason, setReason] = useState("");
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const target = reviewEditTarget(topic, review);
  const claims = review?.evidence_pack?.claims ?? [];
  const set = <K extends keyof Brief>(k: K, v: Brief[K]) => setBrief({ ...brief, [k]: v });
  const required = (f: Format) => brief.required_claims?.[f] ?? [];
  const setRequired = (f: Format, ids: string[]) =>
    setBrief({ ...brief, required_claims: { ...brief.required_claims, [f]: ids } });
  // 형식을 제안하면 필수 주장을 핵심 주장 전체로 미리 채운다(운영자가 형식별로 줄일 수 있다 — 빈 목록은 서버가 막는다).
  const toggleFormat = (f: Format, on: boolean) => setBrief({
    ...brief,
    proposed_formats: on ? [...brief.proposed_formats, f] : brief.proposed_formats.filter((x) => x !== f),
    required_claims: { ...brief.required_claims, [f]: on ? (required(f).length ? required(f) : brief.selected_claim_ids) : [] },
  });
  const toggleCore = (id: string, on: boolean) => setBrief({
    ...brief,
    selected_claim_ids: on ? [...brief.selected_claim_ids, id] : brief.selected_claim_ids.filter((x) => x !== id),
    // 핵심에서 뺀 주장은 형식별 필수 목록에서도 뺀다
    required_claims: on ? brief.required_claims : Object.fromEntries(
      Object.entries(brief.required_claims ?? {}).map(([k, v]) => [k, (v ?? []).filter((x) => x !== id)])),
  });

  const save = () => run("save_review", { ...target.payload, brief, scores }, "공통 기획을 저장했습니다", "기획 저장");
  const reviewAct = async (action: string, msg: string) => {
    if (!review) return;
    const r = await run("review_action", { review_id: review.id, expected_version: review.version, action, reason: reason || null },
      msg, "검토 처리");
    setBlockers(!r.ok && r.code === "review_blocked" && Array.isArray(r.detail) ? (r.detail as string[]) : null);
  };

  // 편성은 "가장 최근 승인 버전"으로만(정책 ③: 새 초안이 있어도 그 승인으로 편성할 수 있다).
  // 이미 편성된 소재는 편성에 쓴 버전으로 형식 추가·주차 변경도 할 수 있다.
  const selectable = reviews.filter(
    // 승인 기록이 아니라 "지금 쓸 수 있는" 승인만(정정·권리 철회·유효 기한 반영 — DB 뷰 drink_review_validity).
    (r) => r.status === "approved" && !r.revoked_at && r.currently_valid === true &&
      (r.id === topic.approved_review_id || (topic.status === "selected" && r.id === topic.selected_review_id))
  );

  return (
    <div>
      <section className="section">
        <h3>공통 기획 {review ? `(버전 ${review.revision_no} · ${VERSION_STATUS_LABEL[review.status]})` : ""}</h3>
        {!target.editable && <p className="muted">{target.lockedReason ?? "조사 후보로 고른 소재만 기획을 작성할 수 있습니다."}</p>}
        <div className="dk-grid">
          <label className="dk-field">
            <span>독자 질문 *</span>
            <input value={brief.audience_question ?? ""} disabled={!target.editable} onChange={(e) => set("audience_question", e.target.value || null)} />
          </label>
          <label className="dk-field">
            <span>핵심 결론 *</span>
            <input value={brief.core_takeaway ?? ""} disabled={!target.editable} onChange={(e) => set("core_takeaway", e.target.value || null)} />
          </label>
          <label className="dk-field">
            <span>다루지 않을 범위</span>
            <input value={brief.exclusions ?? ""} disabled={!target.editable} onChange={(e) => set("exclusions", e.target.value || null)} />
          </label>
          <label className="dk-field">
            <span>보고 나서 할 수 있는 일</span>
            <input value={brief.useful_action ?? ""} disabled={!target.editable} onChange={(e) => set("useful_action", e.target.value || null)} />
          </label>
          <label className="dk-field">
            <span>후속 질문</span>
            <input value={brief.followup_question ?? ""} disabled={!target.editable} onChange={(e) => set("followup_question", e.target.value || null)} />
          </label>
        </div>
        <div className="dk-checks" style={{ marginTop: 8 }}>
          <span className="muted">제안 형식</span>
          {FORMATS.map((f) => (
            <label key={f}>
              <input type="checkbox" disabled={!target.editable} checked={brief.proposed_formats.includes(f)}
                onChange={(e) => toggleFormat(f, e.target.checked)} />
              {FORMAT_LABEL[f]}
            </label>
          ))}
        </div>
        <div style={{ marginTop: 8 }}>
          <span className="muted">핵심 주장 * (편성 전 필수 조건을 검사하는 대상 — 근거 탭에서 저장한 주장)</span>
          {claims.length === 0 && <p className="muted">저장된 주장이 없습니다. 근거 탭에서 먼저 주장을 저장하세요.</p>}
          <div className="dk-checks">
            {claims.map((c) => (
              <label key={c.claim_id}>
                <input type="checkbox" disabled={!target.editable} checked={brief.selected_claim_ids.includes(c.claim_id)}
                  onChange={(e) => toggleCore(c.claim_id, e.target.checked)} />
                [{c.claim_id}] {c.text.slice(0, 50)}
              </label>
            ))}
          </div>
        </div>
        {brief.proposed_formats.map((f) => (
          <div key={f} style={{ marginTop: 8 }}>
            <span className="muted">
              {FORMAT_LABEL[f]} 필수 주장 * — 승인하면 고정되고, 이 형식 제작안은 이 주장을 모두 연결해야 승인됩니다
            </span>
            <div className="dk-checks">
              {brief.selected_claim_ids.map((id) => (
                <label key={id}>
                  <input type="checkbox" disabled={!target.editable} checked={required(f).includes(id)}
                    onChange={(e) => setRequired(f, e.target.checked ? [...required(f), id] : required(f).filter((x) => x !== id))} />
                  {id}
                </label>
              ))}
              {brief.selected_claim_ids.length === 0 && <span className="muted">핵심 주장을 먼저 고르세요</span>}
            </div>
          </div>
        ))}
        <h3 style={{ marginTop: 14 }}>편성 평가 점수 (rubric drinks-v1)</h3>
        {topic.provisional_score !== null && (
          <p className="muted">참고: 경량 평가(임시) {String(topic.provisional_score)}점 — 근거를 본 뒤 다시 매기세요.</p>
        )}
        <ScoreInputs value={scores} onChange={setScores} disabled={!target.editable} />
        {target.editable && (
          <div className="actions">
            <button className="btn pick" disabled={busy} onClick={save}>{target.saveLabel}</button>
          </div>
        )}
      </section>

      {review && (
        <section className="section">
          <h3>검토·승인</h3>
          {(blockers ?? []).length > 0 && (
            <div className="banner-block" role="alert">
              <b>서버가 승인을 막았습니다:</b>
              <ul>{blockers!.map((b) => <li key={b}>{blockerLabel(b)}</li>)}</ul>
            </div>
          )}
          <label className="dk-field">
            <span>사유 (변경 요청·철회 시 필수)</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="actions">
            {review.status === "draft" && (
              <button className="btn pick" disabled={busy} onClick={() => reviewAct("submit", "검토에 올렸습니다")}>기획 검토 요청</button>
            )}
            {review.status === "in_review" && (
              <>
                <button className="btn pick" disabled={busy} onClick={() => reviewAct("approve", "근거·기획을 승인했습니다")}>근거·기획 승인</button>
                <button className="btn" disabled={busy || !reason.trim()} onClick={() => reviewAct("request_changes", "변경을 요청했습니다")}>변경 요청</button>
              </>
            )}
          </div>
        </section>
      )}

      <RevokeList topic={topic} reviews={reviews} plans={plans} />

      {(topic.status === "ready" || topic.status === "selected") && (
        <SelectPanel topic={topic} selectable={selectable} today={today} />
      )}
    </div>
  );
}

function RevokeList({ topic, reviews, plans }: { topic: TopicRow; reviews: ReviewRow[]; plans: PlanRow[] }) {
  const { run, busy } = useDrinksAction();
  const [reason, setReason] = useState("");
  const approved = reviews.filter((r) => r.status === "approved");
  if (approved.length === 0) return null;
  return (
    <section className="section">
      <h3>승인된 근거·기획 버전</h3>
      {approved.map((r) => (
        <div key={r.id} className="dk-sub">
          <p className="dk-kv">
            버전 <b>{r.revision_no}</b> · 점수 <b>{r.score ?? "—"}</b> · 해시 <code>{r.approved_hash?.slice(0, 12)}</code>
            {topic.status === "selected" && r.id === topic.selected_review_id && " · 편성에 쓰는 버전"}
            {r.id === topic.approved_review_id && " · 가장 최근 승인"}
          </p>
          <UsedBy plans={plans.filter((p) => p.topic_review_id === r.id)} revoked={Boolean(r.revoked_at)} />
          {!r.revoked_at && r.currently_valid === false && (
            <div className="banner-block">
              <b>승인 기록은 남아 있지만 지금은 쓸 수 없습니다</b> — 이 버전을 쓴 제작안은 차단됩니다.
              <ul>{(r.current_blockers ?? []).map((b) => <li key={b}>{blockerLabel(b)}</li>)}</ul>
              {plans.some((p) => p.topic_review_id === r.id && !p.blocked_at) && (
                <button className="btn" disabled={busy}
                  onClick={() => run("topic_action", { topic_id: topic.id, expected_version: topic.version, action: "refresh_validity" },
                    "지금 상태로 정리했습니다 — 이 근거를 쓴 제작안을 차단했습니다", "유효성 정리")}>
                  지금 상태로 정리(이 근거를 쓴 제작안 차단)
                </button>
              )}
            </div>
          )}
          {r.revoked_at ? (
            <p className="dk-bad">철회됨: {r.revoked_reason}</p>
          ) : (
            <div className="dk-row">
              <label className="dk-field" style={{ flex: "1 1 240px" }}>
                <span>철회 사유 (오류·권리 철회 등)</span>
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button className="btn" disabled={busy || !reason.trim()}
                onClick={() => run("review_action", { review_id: r.id, expected_version: r.version, action: "revoke", reason },
                  "승인을 철회했습니다 — 이 근거를 쓴 제작안은 차단됩니다", "승인 철회")}>
                승인 철회
              </button>
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

/** 이 버전을 근거로 쓴 제작안 = 철회 시 영향 범위(명세 §8.2). 철회 전에도 미리 보여준다. */
function UsedBy({ plans, revoked }: { plans: PlanRow[]; revoked: boolean }) {
  if (plans.length === 0) return <p className="muted">이 버전을 쓴 제작안 없음</p>;
  return (
    <p className="dk-kv">
      {revoked ? "차단된 제작안" : "철회하면 차단될 제작안"}:{" "}
      <b>
        {plans.map((p) => `${FORMAT_LABEL[p.format]} 버전 ${p.revision_no}(${p.blocked_at ? "차단됨" : VERSION_STATUS_LABEL[p.plan_status]})`).join(", ")}
      </b>
    </p>
  );
}

function SelectPanel({ topic, selectable, today }: { topic: TopicRow; selectable: ReviewRow[]; today: string }) {
  const { run, busy } = useDrinksAction();
  const initial = selectable.find((r) => r.id === topic.selected_review_id) ?? selectable[0] ?? null;
  const [reviewId, setReviewId] = useState(initial?.id ?? "");
  const r = selectable.find((x) => x.id === reviewId) ?? null;
  // 필수 주장이 없는 형식은 편성할 수 없다(서버도 거부) — 미리 체크해 두지 않는다.
  const hasRequired = (rv: ReviewRow | null, f: Format) => (rv?.brief.required_claims?.[f] ?? []).length > 0;
  const [formats, setFormats] = useState<Format[]>((topic.selected_formats ?? []).filter((f) => hasRequired(initial, f)));
  const [week, setWeek] = useState(topic.editorial_week ?? nextMonday(today));
  const [exception, setException] = useState(topic.score_exception_reason ?? "");
  const [fx, setFx] = useState<Partial<Record<Format, string>>>(topic.format_exception_reasons ?? {});
  if (!r) return <p className="muted">편성할 수 있는 승인 버전이 없습니다.</p>;
  const score = weightedScore(r.scores as Record<string, unknown>);
  const below = score !== null && score < SELECT_THRESHOLD;
  const lowFit = formats.filter((f) => !fitOk(r.scores, f));
  const missingFx = lowFit.filter((f) => !(fx[f] ?? "").trim());
  return (
    <section className="section">
      <h3>편성 {topic.status === "selected" ? "(편성됨 — 형식 추가·주차 변경)" : ""}</h3>
      <p className="muted">편성은 제작을 시작하지 않습니다. 형식마다 제작안을 따로 쓰고 따로 승인합니다.</p>
      {selectable.length > 1 && (
        <label className="dk-field">
          <span>편성에 쓸 승인 버전</span>
          <select value={reviewId} onChange={(e) => {
            const next = selectable.find((x) => x.id === e.target.value) ?? null;
            setReviewId(e.target.value);
            setFormats(formats.filter((f) => hasRequired(next, f)));
          }}>
            {selectable.map((x) => (
              <option key={x.id} value={x.id}>
                버전 {x.revision_no}{x.id === topic.approved_review_id ? " (가장 최근 승인)" : " (편성에 쓴 버전)"}
              </option>
            ))}
          </select>
        </label>
      )}
      <p className="dk-kv">
        점수 <b>{score ?? "—"}</b>점 (기준 {SELECT_THRESHOLD}점) · 형식 적합성 {FORMAT_FIT_MIN}점 미만은 경고 — 형식 예외 사유를 남기면 편성할 수 있습니다
      </p>
      <div className="dk-checks">
        {FORMATS.map((f) => {
          const ok = fitOk(r.scores, f);
          const req = hasRequired(r, f);
          const v = r.scores[f === "video" ? "fit_video" : "fit_carousel"];
          return (
            <label key={f} title={req ? "" : "승인 기획에 이 형식의 필수 주장이 없어 편성할 수 없습니다"}>
              <input type="checkbox" disabled={!req} checked={formats.includes(f)}
                onChange={(e) => setFormats(e.target.checked ? [...formats, f] : formats.filter((x) => x !== f))} />
              {FORMAT_LABEL[f]} (적합성 {v ?? "—"}){!req ? " — 필수 주장 없음" : ok ? "" : " — 적합성 낮음(경고)"}
            </label>
          );
        })}
      </div>
      <div className="dk-grid" style={{ marginTop: 8 }}>
        <label className="dk-field">
          <span>편성 주차 (그 주 월요일로 맞춥니다)</span>
          <input type="date" value={week} onChange={(e) => setWeek(e.target.value)} />
        </label>
        {below && (
          <label className="dk-field">
            <span>점수 기준 미만 예외 사유 (필수)</span>
            <input value={exception} onChange={(e) => setException(e.target.value)} />
          </label>
        )}
        {lowFit.map((f) => (
          <label key={f} className="dk-field">
            <span>{FORMAT_LABEL[f]} 적합성 예외 사유 (필수 — 점수 예외와 따로 기록)</span>
            <input value={fx[f] ?? ""} onChange={(e) => setFx({ ...fx, [f]: e.target.value })} />
          </label>
        ))}
      </div>
      <p className="muted">근거 필수 조건(발췌·지지 검토·사용 조건·충돌)은 어떤 예외 사유로도 넘을 수 없습니다.</p>
      <div className="actions">
        <button className="btn pick" disabled={busy || formats.length === 0 || (below && !exception.trim()) || missingFx.length > 0}
          onClick={() => run("select", {
            topic_id: topic.id, expected_version: topic.version, review_id: r.id, review_input_hash: r.approved_hash,
            formats, editorial_week: week, score_exception_reason: below ? exception : null,
            format_exceptions: Object.fromEntries(lowFit.map((f) => [f, fx[f] ?? ""])),
          }, "편성했습니다", "편성")}>
          {topic.status === "selected" ? "편성 갱신" : "편성 확정"}
        </button>
      </div>
    </section>
  );
}
