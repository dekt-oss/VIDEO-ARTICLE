"use client";

// 근거 탭 — 출처 목록·추가, 원출처 묶음, 출처 정보 정정·재확인, 핵심 주장별 발췌·지지 검토.
// ★ "발췌가 원문에 있다(quote_check)"와 "그 발췌가 주장을 뒷받침한다(support_review)"는 다른 칸이다(명세 §6.2).
//   quote_check 는 저장할 때 서버가 원문과 대조해 정한다 — 화면에서 고를 수 없다.
// ★ 정책 ②: 다른 URL 에 같은 본문이 있어도 자동으로 같은 원출처로 묶지 않는다 — 후보로 보여주고 운영자가 묶는다.
// ★ 출처 원문은 바뀌지 않는다. 사용 조건 확인·재확인·정정·권리 철회는 기록으로 쌓이고, 판정은 그 유효 값을 쓴다.
import { useMemo, useState } from "react";

import {
  ATTEST_FIELDS, ATTEST_KIND_LABEL, CLAIM_TYPE_LABEL, DEDUP_LABEL, DEPTH_LABEL, QUOTE_LABEL, RIGHTS_LABEL, ROLE_LABEL,
  SOURCE_KIND_LABEL, SUPPORT_LABEL, blockerLabel, effectiveMeta, originSummary, type AttestKind,
} from "@/lib/drinks/model";
import type { AttestationRow, Claim, ReviewRow, SnapshotRow, TopicRow, TopicSourceRow } from "@/lib/drinks/types";
import SourceFields, { EMPTY_SOURCE, hasSource, sourcePayload, type SourceInput } from "./SourceFields";
import { useDrinksAction } from "./useDrinksAction";

type LinkedSource = TopicSourceRow & { snapshot: SnapshotRow };
export interface SameBodyCandidate {
  id: string;
  canonical_url: string | null;
  origin_group: string | null;
  linkedHere: boolean;
}

const blankClaim = (n: number): Claim => ({
  claim_id: `c${n}`, text: "", claim_type: "process", attribution: null,
  scope: { product: null, region: null, lot: null, time: null }, source_refs: [], support_review: "not_reviewed",
  limitations: null, time_sensitive: false, valid_until: null,
});

export function reviewEditTarget(topic: TopicRow, review: ReviewRow | null) {
  const inReview = review?.status === "in_review";
  // 검토 중인 버전을 두고 새 버전을 만들면 그 검토가 고아가 된다 — 서버도 막는다(review_in_progress).
  const editable = ["researching", "ready", "selected"].includes(topic.status) && !inReview;
  const inPlace = Boolean(review && review.status === "draft");
  return {
    editable,
    lockedReason: inReview ? "검토 중인 버전이 있습니다 — 공통 기획 탭에서 승인하거나 변경 요청한 뒤 새 버전을 만드세요." : null,
    inPlace,
    payload: inPlace
      ? { topic_id: topic.id, review_id: review!.id, expected_version: review!.version }
      : { topic_id: topic.id, expected_topic_version: topic.version },
    saveLabel: inPlace ? "저장" : review ? "새 버전으로 저장(기존 승인은 그대로)" : "근거 작성 시작(첫 버전 저장)",
  };
}

const FIELD_LABEL: Record<string, string> = {
  title: "제목", publisher: "발행처", published_at: "자료 발행일", checked_at: "원문 확인일", original_language: "원문 언어",
  excerpt_locator: "발췌 위치", rights_status: "사용 조건", usage_terms: "사용 조건 메모",
};

export default function EvidenceTab({
  topic,
  review,
  sources,
  attestations,
  sameBody,
  sharedWith,
}: {
  topic: TopicRow;
  review: ReviewRow | null;
  sources: LinkedSource[];
  attestations: Record<string, AttestationRow[]>;
  sameBody: Record<string, SameBodyCandidate[]>;
  sharedWith: Record<string, number>;
}) {
  const { run, busy } = useDrinksAction();
  const [adding, setAdding] = useState(false);
  const [src, setSrc] = useState<SourceInput>(EMPTY_SOURCE);
  const [lastDedup, setLastDedup] = useState<string | null>(null);
  const [diff, setDiff] = useState<Record<string, { current: unknown; incoming: string }> | null>(null);
  const [claims, setClaims] = useState<Claim[]>(review?.evidence_pack?.claims ?? []);
  const target = reviewEditTarget(topic, review);
  const evidence = sources.filter((s) => s.role === "evidence");
  const snapById = useMemo(() => new Map(sources.map((s) => [s.snapshot.id, s.snapshot])), [sources]);
  const sum = originSummary(evidence.map((s) => s.snapshot));
  const sameBodyCount = sources.filter((s) => (sameBody[s.snapshot.id] ?? []).length > 0).length;

  const addSource = async () => {
    const r = await run("add_source", { topic_id: topic.id, source: sourcePayload(src) }, "출처를 처리했습니다", "출처 저장");
    if (r.ok) {
      const res = (r.result ?? {}) as Record<string, unknown>;
      setLastDedup(
        res.promoted ? "promoted"
          : res.linked === false ? `already:${String(res.role ?? "")}`
          : String(res.dedup ?? "")
      );
      const d = res.metadata_diff as Record<string, { current: unknown; incoming: string }> | undefined;
      setDiff(d && Object.keys(d).length > 0 ? d : null);
      setSrc(EMPTY_SOURCE);
      setAdding(false);
    }
  };
  const setClaim = (i: number, c: Claim) => setClaims(claims.map((x, j) => (j === i ? c : x)));
  const saveClaims = () =>
    run("save_review", { ...target.payload, evidence_pack: { claims } }, "근거를 저장했습니다", "근거 저장");

  return (
    <div>
      <section className="section">
        <h3>
          출처 {sources.length}개 · 사실 근거 {evidence.length}개 · 확인된 원출처 {sum.confirmedGroups}묶음 · 묶음 미확인{" "}
          {sum.unconfirmed}개{sameBodyCount > 0 ? ` · 같은 본문 후보 있음 ${sameBodyCount}개` : ""}
        </h3>
        <p className="muted">
          독립 원출처는 운영자가 묶음을 정한 것만 셉니다. 묶음 미확인 출처는 독립 출처로 치지 않습니다.
        </p>
        {sources.length === 0 && <p className="muted">연결된 출처가 없습니다.</p>}
        {sources.map((s) => (
          <SourceCard key={s.snapshot.id} topicId={topic.id} link={s} attestations={attestations[s.snapshot.id] ?? []}
            candidates={sameBody[s.snapshot.id] ?? []} sharedWith={sharedWith[s.snapshot.id] ?? 0} />
        ))}
        {lastDedup && (
          <p className="banner-info">
            {lastDedup === "promoted"
              ? "질문·인기 신호로 붙어 있던 출처를 사실 근거로 올렸습니다."
              : lastDedup.startsWith("already:")
                ? `이미 이 소재에 ‘${ROLE_LABEL[lastDedup.slice(8) as keyof typeof ROLE_LABEL] ?? lastDedup.slice(8)}’(으)로 연결된 출처라 바꾸지 않았습니다.`
                : DEDUP_LABEL[lastDedup] ?? ""}
          </p>
        )}
        {diff && (
          <div className="banner-warn" role="alert">
            <b>같은 원문이지만 입력한 정보가 기존 출처와 다릅니다 — 자동으로 바꾸지 않았습니다.</b>
            <ul>
              {Object.entries(diff).map(([k, v]) => (
                <li key={k}>{FIELD_LABEL[k] ?? k}: {String(v.current ?? "없음")} → {v.incoming}</li>
              ))}
            </ul>
            맞는 정보라면 그 출처 카드의 [정보 정정·확인 기록]으로 남기세요(이력이 남고 영향 범위를 보여줍니다).
          </div>
        )}
        {adding ? (
          <div className="dk-sub">
            <SourceFields value={src} onChange={setSrc} />
            <div className="actions">
              <button className="btn pick" disabled={busy || !hasSource(src)} onClick={addSource}>출처 저장</button>
              <button className="btn" onClick={() => setAdding(false)}>취소</button>
            </div>
          </div>
        ) : (
          topic.status !== "duplicate" && <button className="btn" onClick={() => setAdding(true)}>+ 출처 추가</button>
        )}
      </section>

      <section className="section">
        <h3>핵심 주장과 근거 {review ? `(버전 ${review.revision_no} · ${review.status})` : ""}</h3>
        {review?.revoked_at && (
          <p className="banner-block">이 버전은 승인이 철회됐습니다: {review.revoked_reason}. 새 버전을 만들어 다시 검토하세요.</p>
        )}
        {review && review.readiness?.blockers?.length > 0 && (
          <div className="banner-block">
            <b>편성 전 필수 조건 미달 {review.readiness.blockers.length}건</b> (서버가 마지막으로 검사한 결과)
            <ul>{review.readiness.blockers.map((b) => <li key={b}>{blockerLabel(b)}</li>)}</ul>
          </div>
        )}
        {review && review.readiness?.warnings?.length > 0 && (
          <div className="banner-warn">
            <ul>{review.readiness.warnings.map((b) => <li key={b}>{blockerLabel(b)}</li>)}</ul>
          </div>
        )}
        {!target.editable && <p className="muted">{target.lockedReason ?? "조사 후보로 고른 소재만 근거를 작성할 수 있습니다."}</p>}
        {target.editable && !target.inPlace && review && (
          <p className="muted">
            현재 버전({review.status})은 고칠 수 없습니다. 고치면 새 버전이 만들어지고 다시 검토해야 합니다.
            기존 승인·편성·제작안은 새 버전 때문에 바뀌지 않습니다.
          </p>
        )}
        {claims.map((c, i) => (
          <ClaimEditor key={i} claim={c} evidence={evidence} snapById={snapById} disabled={!target.editable || busy}
            onChange={(x) => setClaim(i, x)} onRemove={() => setClaims(claims.filter((_, j) => j !== i))} />
        ))}
        {target.editable && (
          <div className="actions">
            <button className="btn" disabled={busy} onClick={() => setClaims([...claims, blankClaim(nextClaimNo(claims))])}>
              + 주장 추가
            </button>
            <button className="btn pick" disabled={busy} onClick={saveClaims}>{target.saveLabel}</button>
          </div>
        )}
      </section>
    </div>
  );
}

function nextClaimNo(claims: Claim[]): number {
  const nums = claims.map((c) => Number(/^c(\d+)$/.exec(c.claim_id)?.[1] ?? 0));
  return Math.max(0, ...nums) + 1;
}

interface Impact {
  topics?: { id: string; title: string }[];
  approved_reviews?: { id: string; topic_id: string; revision_no: number; core: boolean }[];
  plans?: { id: string; format: string; revision_no: number }[];
}

function SourceCard({ topicId, link, attestations, candidates, sharedWith }: {
  topicId: string;
  link: LinkedSource;
  attestations: AttestationRow[];
  candidates: SameBodyCandidate[];
  sharedWith: number;
}) {
  const { run, busy } = useDrinksAction();
  const s = link.snapshot;
  const m = effectiveMeta(s as unknown as Record<string, string | null>, attestations);
  const [group, setGroup] = useState(s.origin_group ?? "");
  const [mergeIds, setMergeIds] = useState<string[]>([]);
  const [kind, setKind] = useState<AttestKind>("rights_confirmed");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [revokeAffected, setRevokeAffected] = useState(false);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [openAttest, setOpenAttest] = useState(false);
  const mergeable = candidates.filter((c) => c.linkedHere);

  const attest = async () => {
    const payload: Record<string, unknown> = {
      topic_id: topicId, snapshot_id: s.id, kind, reason: reason || null,
      fields: Object.fromEntries(Object.entries(fields).filter(([k, v]) => ATTEST_FIELDS[kind].includes(k) && v.trim() !== "")),
      revoke_affected: kind === "rights_revoked" && revokeAffected,
    };
    const r = await run("attest_source", payload, `${ATTEST_KIND_LABEL[kind]}을(를) 기록했습니다`, "출처 정보 기록");
    if (r.ok) {
      setImpact((r.result?.impact as Impact) ?? null);
      setFields({});
      setReason("");
      setOpenAttest(false);
    }
  };

  return (
    <div className="dk-sub">
      <div className="dk-row">
        <span className="pill">{ROLE_LABEL[link.role]}</span>
        <span className={s.depth === "metadata_only" ? "pill dk-warn" : "pill"}>{DEPTH_LABEL[s.depth]}</span>
        <span className={m.rights_status === "quote_ok" || m.rights_status === "summary_only" ? "pill" : "pill dk-warn"}>
          {RIGHTS_LABEL[(m.rights_status ?? "unknown") as keyof typeof RIGHTS_LABEL]}
        </span>
        <span className="pill">{SOURCE_KIND_LABEL[s.source_kind as keyof typeof SOURCE_KIND_LABEL] ?? s.source_kind}</span>
        {s.supersedes_id && <span className="pill">본문 변경 버전</span>}
        {m.attestationCount > 0 && <span className="pill">정정·확인 기록 {m.attestationCount}건</span>}
        {sharedWith > 0 && <span className="pill dk-warn">다른 소재 {sharedWith}개와 공유</span>}
        <span className="pill">{s.origin_group ? `원출처: ${s.origin_group}` : "원출처 묶음 미확인"}</span>
      </div>
      <p style={{ margin: "6px 0" }}>
        <b>{m.title || m.publisher || "(제목 없음)"}</b> {m.publisher && m.title ? `· ${m.publisher}` : ""}
      </p>
      {s.canonical_url && (
        <p className="dk-kv" style={{ wordBreak: "break-all" }}>
          <a href={s.canonical_url} target="_blank" rel="noreferrer noopener">{s.canonical_url}</a>
        </p>
      )}
      <p className="dk-kv">
        언어 <b>{m.original_language || "—"}</b> · 발행일 <b>{m.published_at || "모름"}</b> · 확인일{" "}
        <b>{m.checked_at || "—"}</b> · 위치 <b>{m.excerpt_locator || "—"}</b>
        {m.usage_terms && <> · 사용 조건 메모 <b>{m.usage_terms}</b></>}
      </p>
      {s.body_text && (
        <details>
          <summary className="muted">입력한 원문·발췌 보기(원문은 바뀌지 않습니다)</summary>
          <div className="dk-body">{s.body_text}</div>
        </details>
      )}
      {attestations.length > 0 && (
        <details>
          <summary className="muted">정정·확인 기록 {attestations.length}건</summary>
          <ul>
            {attestations.map((a) => (
              <li key={a.id} className="dk-kv">
                {a.created_at.slice(0, 10)} · <b>{ATTEST_KIND_LABEL[a.kind]}</b>{" "}
                {Object.entries(a.fields).map(([k, v]) => `${FIELD_LABEL[k] ?? k}=${v ?? "—"}`).join(", ")}
                {a.reason && ` · ${a.reason}`}
              </li>
            ))}
          </ul>
        </details>
      )}
      {candidates.length > 0 && (
        <div className="banner-warn" style={{ marginTop: 6 }}>
          <b>다른 URL 에 글자 그대로 같은 본문이 {candidates.length}개 있습니다</b> — 전재일 수 있습니다. 같은 원출처인지 확인한 뒤 묶으세요.
          <ul>
            {candidates.map((c) => (
              <li key={c.id}>
                <label>
                  <input type="checkbox" disabled={!c.linkedHere} checked={mergeIds.includes(c.id)}
                    onChange={(e) => setMergeIds(e.target.checked ? [...mergeIds, c.id] : mergeIds.filter((x) => x !== c.id))} />{" "}
                  {c.canonical_url ?? "(URL 없음)"} {c.origin_group ? `· 묶음 ${c.origin_group}` : ""}
                  {!c.linkedHere && " · 다른 소재에만 연결됨(여기서 묶을 수 없음)"}
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="dk-row" style={{ marginTop: 6 }}>
        <label className="dk-field" style={{ flex: "1 1 220px" }}>
          <span>원출처 묶음 이름{mergeable.length > 0 ? " (체크한 같은 본문 출처도 함께 묶음)" : ""}</span>
          <input value={group} onChange={(e) => setGroup(e.target.value)} />
        </label>
        <button className="btn" disabled={busy || (group === (s.origin_group ?? "") && mergeIds.length === 0)}
          onClick={async () => {
            const r = await run("set_origin_group", { topic_id: topicId, snapshot_ids: [s.id, ...mergeIds], origin_group: group || null },
              "원출처 묶음을 바꿨습니다", "원출처 묶음 저장");
            const aff = (r.result?.affected_topics as { title: string }[] | undefined) ?? [];
            if (r.ok && aff.length > 0) setImpact({ topics: aff as Impact["topics"] });
            if (r.ok) setMergeIds([]);
          }}>
          묶음 저장
        </button>
        <button className="btn" onClick={() => setOpenAttest(!openAttest)}>정보 정정·확인 기록</button>
      </div>
      {openAttest && (
        <div className="dk-sub">
          <div className="dk-grid">
            <label className="dk-field">
              <span>기록 종류</span>
              <select value={kind} onChange={(e) => { setKind(e.target.value as AttestKind); setFields({}); }}>
                {Object.entries(ATTEST_KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            {ATTEST_FIELDS[kind].map((k) => (
              <label key={k} className="dk-field">
                <span>{FIELD_LABEL[k] ?? k}</span>
                {k === "rights_status" ? (
                  <select value={fields[k] ?? ""} onChange={(e) => setFields({ ...fields, [k]: e.target.value })}>
                    <option value="">—</option>
                    {(kind === "rights_revoked" ? ["restricted", "unknown"] : ["quote_ok", "summary_only"]).map((v) => (
                      <option key={v} value={v}>{RIGHTS_LABEL[v as keyof typeof RIGHTS_LABEL]}</option>
                    ))}
                  </select>
                ) : (
                  <input type={k.endsWith("_at") ? "date" : "text"} value={fields[k] ?? ""}
                    onChange={(e) => setFields({ ...fields, [k]: e.target.value })} />
                )}
              </label>
            ))}
            <label className="dk-field">
              <span>사유 {kind === "correction" || kind === "rights_revoked" ? "(필수)" : "(선택)"}</span>
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
          </div>
          {kind === "rights_revoked" && (
            <div className="dk-checks" style={{ marginTop: 6 }}>
              <label>
                <input type="checkbox" checked={revokeAffected} onChange={(e) => setRevokeAffected(e.target.checked)} />
                이 출처를 핵심 근거로 쓴 승인 버전도 함께 철회(그 근거를 쓴 제작안은 차단됩니다)
              </label>
            </div>
          )}
          <p className="muted">원문과 과거 승인 본문은 바뀌지 않습니다. 이후 승인·편성·제작안 승인은 이 기록을 반영해 다시 검사합니다.</p>
          <div className="actions">
            <button className="btn pick" disabled={busy} onClick={attest}>기록</button>
          </div>
        </div>
      )}
      {impact && (
        <div className="banner-info" style={{ marginTop: 6 }}>
          <b>영향 범위</b>
          {(impact.topics ?? []).length > 0 && <div>이 출처를 쓰는 소재: {(impact.topics ?? []).map((t) => t.title).join(", ")}</div>}
          {impact.approved_reviews && <div>이 출처를 근거로 쓴 승인 버전: {impact.approved_reviews.length}개</div>}
          {impact.plans && <div>그 승인을 쓰는 제작안: {impact.plans.length}개</div>}
        </div>
      )}
    </div>
  );
}

function ClaimEditor({
  claim, evidence, snapById, disabled, onChange, onRemove,
}: {
  claim: Claim;
  evidence: LinkedSource[];
  snapById: Map<string, SnapshotRow>;
  disabled: boolean;
  onChange: (c: Claim) => void;
  onRemove: () => void;
}) {
  const set = <K extends keyof Claim>(k: K, v: Claim[K]) => onChange({ ...claim, [k]: v });
  const opinion = claim.claim_type === "opinion";
  return (
    <div className="dk-sub">
      <div className="dk-grid">
        <label className="dk-field">
          <span>주장 ID</span>
          <input value={claim.claim_id} disabled={disabled} onChange={(e) => set("claim_id", e.target.value.trim())} />
        </label>
        <label className="dk-field">
          <span>종류</span>
          <select value={claim.claim_type} disabled={disabled} onChange={(e) => set("claim_type", e.target.value as Claim["claim_type"])}>
            {Object.entries(CLAIM_TYPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        {opinion ? (
          <label className="dk-field">
            <span>누구의 평가인가 (필수)</span>
            <input value={claim.attribution ?? ""} disabled={disabled} onChange={(e) => set("attribution", e.target.value || null)} placeholder="예: 제조사 설명" />
          </label>
        ) : (
          <label className="dk-field">
            <span>지지 검토 (사람이 판단)</span>
            <select value={claim.support_review} disabled={disabled}
              onChange={(e) => set("support_review", e.target.value as Claim["support_review"])}>
              {(["not_reviewed", "supported", "insufficient", "conflicting"] as const).map((k) => (
                <option key={k} value={k}>{SUPPORT_LABEL[k]}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      <label className="dk-field" style={{ marginTop: 8 }}>
        <span>주장 문장</span>
        <textarea value={claim.text} disabled={disabled} rows={2} onChange={(e) => set("text", e.target.value)} />
      </label>
      <div className="dk-grid" style={{ marginTop: 8 }}>
        {(["product", "region", "lot", "time"] as const).map((k) => (
          <label key={k} className="dk-field">
            <span>{{ product: "적용 제품", region: "시장·지역", lot: "로트·빈티지", time: "시점" }[k]}</span>
            <input value={claim.scope[k] ?? ""} disabled={disabled}
              onChange={(e) => set("scope", { ...claim.scope, [k]: e.target.value || null })} />
          </label>
        ))}
        <label className="dk-field">
          <span>한계·주의</span>
          <input value={claim.limitations ?? ""} disabled={disabled} onChange={(e) => set("limitations", e.target.value || null)} />
        </label>
        <label className="dk-field">
          <span>유효 기한</span>
          <input type="date" value={claim.valid_until ?? ""} disabled={disabled} onChange={(e) => set("valid_until", e.target.value || null)} />
        </label>
      </div>
      <div className="dk-checks" style={{ marginTop: 6 }}>
        <label>
          <input type="checkbox" checked={claim.time_sensitive} disabled={disabled} onChange={(e) => set("time_sensitive", e.target.checked)} />
          가격·재고·행사처럼 기한이 있는 정보 (유효 기한·시장 필수)
        </label>
      </div>
      <div style={{ marginTop: 8 }}>
        <span className="muted">근거 발췌</span>
        {claim.source_refs.map((r, i) => {
          const snap = snapById.get(r.snapshot_id);
          return (
            <div key={i} className="dk-sub">
              <div className="dk-grid">
                <label className="dk-field">
                  <span>출처 (사실 근거로 연결된 것만)</span>
                  <select value={r.snapshot_id} disabled={disabled}
                    onChange={(e) => set("source_refs", claim.source_refs.map((x, j) => (j === i ? { ...x, snapshot_id: e.target.value, quote_check: "not_checked" } : x)))}>
                    {evidence.map((s) => (
                      <option key={s.snapshot.id} value={s.snapshot.id}>
                        {(s.snapshot.title || s.snapshot.publisher || s.snapshot.canonical_url || s.snapshot.id).slice(0, 60)}
                        {s.snapshot.depth === "metadata_only" ? " (URL만)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="dk-field">
                  <span>위치</span>
                  <input value={r.locator ?? ""} disabled={disabled}
                    onChange={(e) => set("source_refs", claim.source_refs.map((x, j) => (j === i ? { ...x, locator: e.target.value || null } : x)))} />
                </label>
              </div>
              <label className="dk-field" style={{ marginTop: 6 }}>
                <span>원문 발췌 (원문 그대로)</span>
                <textarea value={r.original_quote ?? ""} disabled={disabled} rows={2}
                  onChange={(e) => set("source_refs", claim.source_refs.map((x, j) => (j === i ? { ...x, original_quote: e.target.value || null, quote_check: "not_checked" } : x)))} />
              </label>
              <label className="dk-field" style={{ marginTop: 6 }}>
                <span>번역 (원문이 외국어일 때)</span>
                <input value={r.translation ?? ""} disabled={disabled}
                  onChange={(e) => set("source_refs", claim.source_refs.map((x, j) => (j === i ? { ...x, translation: e.target.value || null } : x)))} />
              </label>
              <p className="dk-kv">
                발췌 대조:{" "}
                <b className={r.quote_check === "matched" ? "dk-ok" : r.quote_check === "unmatched" ? "dk-bad" : "dk-warn"}>
                  {QUOTE_LABEL[r.quote_check] ?? r.quote_check}
                </b>
                {snap?.depth === "metadata_only" && " · 이 출처는 URL 만 있어 근거가 될 수 없습니다"} (저장할 때 서버가 다시 대조)
              </p>
              {!disabled && (
                <button className="btn" onClick={() => set("source_refs", claim.source_refs.filter((_, j) => j !== i))}>발췌 삭제</button>
              )}
            </div>
          );
        })}
        {!disabled && (
          <div className="actions">
            <button className="btn" disabled={evidence.length === 0}
              onClick={() => set("source_refs", [...claim.source_refs, { snapshot_id: evidence[0]?.snapshot.id ?? "", locator: null, original_quote: null, translation: null, quote_check: "not_checked" }])}>
              + 발췌 추가
            </button>
            <button className="btn" onClick={onRemove}>주장 삭제</button>
          </div>
        )}
        {evidence.length === 0 && <p className="muted">사실 근거 역할의 출처가 없어 발췌를 붙일 수 없습니다.</p>}
      </div>
    </div>
  );
}
