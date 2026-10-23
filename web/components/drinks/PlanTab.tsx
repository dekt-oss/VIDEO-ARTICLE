"use client";

// 형식별 제작안 탭 — 영상(장면) / 카드뉴스(페이지). 사람이 쓰고 고친다(LLM 생성 없음).
// ★ 형식마다 결과물·버전·승인이 따로다. 영상 제작안을 고쳐도 카드뉴스 승인은 그대로다(명세 §2).
// ★ 승인된 제작안은 고칠 수 없다 — [새 버전 작성]이 같은 내용으로 새 draft 를 만든다.
// ★ "제작 요청"은 A단계에 연결되지 않았다. 버튼은 잠겨 있고, 서버에도 그 동작이 없다.
import { useState } from "react";

import {
  FORMAT_LABEL, PAGE_ROLE_LABEL, VERSION_STATUS_LABEL, VISUAL_ROLE_LABEL, isFactItem, planCoverage, type Coverage, type Format,
} from "@/lib/drinks/model";
import type { CarouselPage, DeliverableRow, PlanRow, ReviewRow, TopicRow, VideoScene } from "@/lib/drinks/types";
import { useDrinksAction } from "./useDrinksAction";

const blankScene = (): VideoScene => ({
  narration: "", visual_role: "reality", content_kind: "fact", explanation: null, claim_ids: [], timing_sec: null, continuity: null, overlays: null,
});
const blankPage = (n: number): CarouselPage => ({
  position: n, role: n === 1 ? "cover" : "explain", heading: "", body: null, graphic_spec: null, claim_ids: [],
});

export default function PlanTab({
  format, topic, reviews, deliverable, plans,
}: {
  format: Format;
  topic: TopicRow;
  reviews: ReviewRow[];
  deliverable: DeliverableRow | null;
  plans: PlanRow[];
}) {
  const { run, busy } = useDrinksAction();
  const current = deliverable?.current_revision_id ? plans.find((p) => p.id === deliverable.current_revision_id) ?? null : null;
  // 지금 쓸 수 있는 승인 버전만(승인 기록 ≠ 현재 사용 가능 — DB 뷰 drink_review_validity).
  const usable = reviews.filter((r) => r.status === "approved" && !r.revoked_at && r.currently_valid === true);
  const currentReview = current ? reviews.find((r) => r.id === current.topic_review_id) ?? null : null;
  const selected = topic.status === "selected" && (topic.selected_formats ?? []).includes(format);
  const editingInPlace = Boolean(current && current.plan_status === "draft" && !current.blocked_at);
  const [creating, setCreating] = useState(false);
  const editorOpen = selected && (editingInPlace || creating || !current);

  const defaultReview = current && usable.some((r) => r.id === current.topic_review_id)
    ? current.topic_review_id
    : topic.selected_review_id && usable.some((r) => r.id === topic.selected_review_id) ? topic.selected_review_id : usable[0]?.id ?? "";
  const [reviewId, setReviewId] = useState(defaultReview);
  // 새로고침 뒤 고른 버전이 더는 쓸 수 없으면(정정·권리 철회) 쓸 수 있는 버전으로 바꿔 보여주고 그 버전으로 저장한다.
  const review = usable.find((r) => r.id === reviewId) ?? usable.find((r) => r.id === defaultReview) ?? usable[0] ?? null;
  const [scenes, setScenes] = useState<VideoScene[]>(current?.plan_json.scenes ?? [blankScene()]);
  const [pages, setPages] = useState<CarouselPage[]>(current?.plan_json.pages ?? [blankPage(1)]);
  const [notes, setNotes] = useState(current?.plan_json.notes ?? "");
  const [visual, setVisual] = useState(current?.visual_profile ?? "");
  const [brand, setBrand] = useState(current?.brand_profile_version ?? "");
  const [aspect, setAspect] = useState(current?.aspect_ratio ?? (format === "video" ? "9:16" : "4:5"));
  const [reason, setReason] = useState("");

  const coreClaims = (review?.evidence_pack.claims ?? []).filter((c) => (review?.brief.selected_claim_ids ?? []).includes(c.claim_id));
  const required = review?.brief.required_claims?.[format] ?? [];
  const liveCoverage = planCoverage(format, format === "video" ? scenes : pages, required);
  const name = FORMAT_LABEL[format];

  const save = async () => {
    const plan_json = format === "video"
      ? { scenes, notes: notes || null }
      : { pages: pages.map((p, i) => ({ ...p, position: i + 1 })), notes: notes || null };
    const payload: Record<string, unknown> = {
      topic_id: topic.id, format, topic_review_id: review?.id ?? null, plan_json,
      visual_profile: visual || null, brand_profile_version: brand || null, aspect_ratio: aspect,
    };
    if (editingInPlace && current) Object.assign(payload, { revision_id: current.id, expected_version: current.version });
    else if (deliverable) payload.expected_deliverable_version = deliverable.version;
    const r = await run("save_plan", payload, `${name} 제작안을 저장했습니다`, "제작안 저장");
    if (r.ok) setCreating(false);
  };
  const planAct = (action: string, msg: string) =>
    current && run("plan_action", { revision_id: current.id, expected_version: current.version, action, reason: reason || null }, msg, "제작안 처리");

  if (!selected) {
    // 편성이 풀린 뒤(근거 철회 등)에도 이미 쓴 제작안과 차단 사유는 보여준다 — 영향 범위를 숨기지 않는다.
    return (
      <div>
        <p className="banner-info">
          {topic.status === "selected"
            ? `이 소재는 ${name} 형식으로 편성되지 않았습니다. 공통 기획 탭의 [편성]에서 형식을 고르면 제작안을 쓸 수 있습니다.`
            : `소재가 편성 상태가 아니라 ${name} 제작안을 쓰거나 승인할 수 없습니다.`}
        </p>
        {current && (
          <section className="section">
            <h3>마지막 {name} 제작안 — 버전 {current.revision_no} · {VERSION_STATUS_LABEL[current.plan_status]}</h3>
            {current.blocked_at && <p className="banner-block">근거 철회로 차단됨: {current.blocked_reason}</p>}
            <PlanPreview plan={current} />
          </section>
        )}
        <PlanHistory name={name} plans={plans} reviews={reviews} currentId={deliverable?.current_revision_id ?? null} />
      </div>
    );
  }

  return (
    <div>
      {current && (
        <section className="section">
          <h3>현재 {name} 제작안 — 버전 {current.revision_no} · {VERSION_STATUS_LABEL[current.plan_status]}</h3>
          {current.blocked_at && <p className="banner-block">근거 철회·사용 불가로 차단됨: {current.blocked_reason}. 유효한 근거로 새 버전을 만드세요(권리를 다시 확인해도 자동으로 풀리지 않습니다).</p>}
          {!current.blocked_at && currentReview && currentReview.currently_valid === false && (
            <p className="banner-block">이 제작안이 쓴 근거 버전을 지금은 쓸 수 없습니다(사용 조건·유효 기한 등) — 승인할 수 없습니다.</p>
          )}
          {current.topic_review_id !== topic.selected_review_id && (
            <p className="banner-warn">이 제작안은 편성 버전과 다른 근거·기획 버전(버전 {reviews.find((r) => r.id === current.topic_review_id)?.revision_no ?? "?"})을 씁니다.</p>
          )}
          <p className="dk-kv">
            표현 설정 <b>{current.visual_profile || "—"}</b> · 브랜드 프로필 <b>{current.brand_profile_version || "—"}</b> · 비율{" "}
            <b>{current.aspect_ratio}</b> · 입력 해시 <code>{current.input_hash.slice(0, 12)}</code>
            {current.decision_note && <> · 메모 <b>{current.decision_note}</b></>}
          </p>
          {!editingInPlace && <PlanPreview plan={current} />}
          {currentReview && (
            <CoverageView label="저장된 제작안 기준"
              coverage={planCoverage(format, (format === "video" ? current.plan_json.scenes : current.plan_json.pages) ?? [],
                currentReview.brief.required_claims?.[format] ?? [])} />
          )}
          <label className="dk-field">
            <span>사유 (변경 요청 시 필수)</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="actions">
            {current.plan_status === "draft" && !current.blocked_at && (
              <button className="btn pick" disabled={busy} onClick={() => planAct("submit", "검수에 올렸습니다")}>제작안 검수 요청</button>
            )}
            {current.plan_status === "in_review" && !current.blocked_at && (
              <>
                <button className="btn pick" disabled={busy || currentReview?.currently_valid !== true}
                  title={currentReview?.currently_valid !== true ? "이 제작안이 쓴 근거를 지금은 쓸 수 없습니다" : ""}
                  onClick={() => planAct("approve", `${name} 제작안을 승인했습니다`)}>제작안 승인</button>
                <button className="btn" disabled={busy || !reason.trim()} onClick={() => planAct("request_changes", "변경을 요청했습니다")}>변경 요청</button>
              </>
            )}
            {!editingInPlace && !creating && current.plan_status !== "in_review" && (
              <button className="btn" disabled={busy} onClick={() => setCreating(true)}>새 버전 작성</button>
            )}
            <button className="btn" disabled title="실제 영상·카드 제작은 B~C단계에서 연결됩니다">
              제작 요청 — 실제 제작 미연결
            </button>
          </div>
        </section>
      )}

      {editorOpen && (
        <section className="section">
          <h3>{current && !editingInPlace ? "새 버전 작성" : `${name} 제작안 작성`}</h3>
          {usable.length === 0 ? (
            <p className="banner-block">승인된(철회되지 않은) 근거·기획 버전이 없어 제작안을 쓸 수 없습니다.</p>
          ) : (
            <>
              <div className="dk-grid">
                <label className="dk-field">
                  <span>사용할 근거·기획 버전 (고정됨)</span>
                  <select value={reviewId} onChange={(e) => setReviewId(e.target.value)}>
                    {usable.map((r) => (
                      <option key={r.id} value={r.id}>
                        버전 {r.revision_no}{r.id === topic.selected_review_id ? " (편성 버전)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="dk-field">
                  <span>표현 설정 (기록만 — 렌더 가능 여부와 무관)</span>
                  <input value={visual} onChange={(e) => setVisual(e.target.value)} placeholder="예: drinks-photo-v0" />
                </label>
                <label className="dk-field">
                  <span>브랜드 프로필 버전</span>
                  <input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="예: 술째리고-v1" />
                </label>
                <label className="dk-field">
                  <span>화면 비율</span>
                  <select value={aspect} onChange={(e) => setAspect(e.target.value)}>
                    {["9:16", "4:5", "1:1"].map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
              </div>
              <p className="dk-kv">비용 추정: <b>산정하지 않음</b> — 실제 제작이 연결되지 않아 유료 호출이 없습니다.</p>
              <CoverageView coverage={liveCoverage} label="작성 중 내용 기준(저장 전)" />
              {format === "video" ? (
                <SceneEditor scenes={scenes} onChange={setScenes} claims={coreClaims} required={required} />
              ) : (
                <PageEditor pages={pages} onChange={setPages} claims={coreClaims} required={required} />
              )}
              <label className="dk-field" style={{ marginTop: 8 }}>
                <span>메모</span>
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
              </label>
              <div className="actions">
                <button className="btn pick" disabled={busy || !review} onClick={save}>
                  {editingInPlace || !current ? "저장" : "새 버전으로 저장"}
                </button>
                {creating && <button className="btn" onClick={() => setCreating(false)}>취소</button>}
              </div>
            </>
          )}
        </section>
      )}

      <PlanHistory name={name} plans={plans} reviews={reviews} currentId={deliverable?.current_revision_id ?? null} />
    </div>
  );
}

function PlanHistory({ name, plans, reviews, currentId }: { name: string; plans: PlanRow[]; reviews: ReviewRow[]; currentId: string | null }) {
  return (
    <section className="section">
      <h3>{name} 제작안 버전 이력</h3>
      {plans.length === 0 ? (
        <p className="muted">아직 없습니다.</p>
      ) : (
        plans.map((p) => (
          <p key={p.id} className="dk-kv">
            버전 <b>{p.revision_no}</b> · {VERSION_STATUS_LABEL[p.plan_status]}
            {p.blocked_at && <span className="dk-bad"> · 차단됨</span>} · 근거 버전{" "}
            {reviews.find((r) => r.id === p.topic_review_id)?.revision_no ?? "?"}
            {p.id === currentId && " · 현재"}
          </p>
        ))
      )}
    </section>
  );
}

type CoreClaim = { claim_id: string; text: string };

function ClaimChecks({ value, claims, required, onChange }: {
  value: string[]; claims: CoreClaim[]; required: string[]; onChange: (v: string[]) => void;
}) {
  if (claims.length === 0) return <p className="muted">핵심 주장이 없습니다.</p>;
  return (
    <div className="dk-checks">
      <span className="muted">쓰는 주장</span>
      {claims.map((c) => (
        <label key={c.claim_id} title={c.text}>
          <input type="checkbox" checked={value.includes(c.claim_id)}
            onChange={(e) => onChange(e.target.checked ? [...value, c.claim_id] : value.filter((x) => x !== c.claim_id))} />
          {c.claim_id}{required.includes(c.claim_id) ? " (필수)" : ""}
        </label>
      ))}
    </div>
  );
}

/** 필수 주장 전달 현황. 주장 연결은 근거 범위 표시일 뿐 — 문장이 주장과 맞는지는 사람이 검토한다. */
function CoverageView({ coverage, label }: { coverage: Coverage; label: string }) {
  return (
    <div className={coverage.ok ? "banner-ok" : "banner-warn"} style={{ marginTop: 8 }}>
      <b>근거 전달 검사 — {label}</b>
      <div>필수 주장: {coverage.required.length ? coverage.required.join(", ") : "없음(승인 기획에 이 형식의 필수 주장이 없어 승인 불가)"}</div>
      <div>사실 항목에서 전달한 주장: {coverage.covered.length ? coverage.covered.join(", ") : "없음"}</div>
      {coverage.reference_only.length > 0 && (
        <div className="dk-warn">표지·출처·전환에만 붙은 주장(참고 연결 — 전달로 치지 않음): {coverage.reference_only.join(", ")}</div>
      )}
      {coverage.missing_required.length > 0 && <div className="dk-bad">빠진 필수 주장: {coverage.missing_required.join(", ")}</div>}
      {coverage.facts_without_claims.length > 0 && (
        <div className="dk-bad">주장 연결 없는 사실 항목: {coverage.facts_without_claims.map((n) => `${n}번`).join(", ")}</div>
      )}
      <div className="muted">검수 요청·승인 때 서버가 같은 검사를 다시 합니다. 문장이 주장과 맞는지는 사람이 확인하세요.</div>
    </div>
  );
}

function SceneEditor({ scenes, onChange, claims, required }: { scenes: VideoScene[]; onChange: (v: VideoScene[]) => void; claims: CoreClaim[]; required: string[] }) {
  const set = (i: number, patch: Partial<VideoScene>) => onChange(scenes.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  return (
    <div>
      {scenes.map((s, i) => (
        <div key={i} className="dk-sub">
          <b>장면 {i + 1}</b>{" "}
          <span className={isFactItem("video", s) ? "pill" : "pill dk-ok"}>{isFactItem("video", s) ? "사실 설명 — 주장 연결 필수" : "도입·전환·마무리"}</span>
          <label className="dk-field">
            <span>나레이션 *</span>
            <textarea value={s.narration} rows={2} onChange={(e) => set(i, { narration: e.target.value })} />
          </label>
          <div className="dk-grid" style={{ marginTop: 6 }}>
            <label className="dk-field">
              <span>화면 역할</span>
              <select value={s.visual_role} onChange={(e) => set(i, { visual_role: e.target.value as VideoScene["visual_role"] })}>
                {Object.entries(VISUAL_ROLE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label className="dk-field">
              <span>내용 종류</span>
              <select value={s.content_kind ?? "fact"} onChange={(e) => set(i, { content_kind: e.target.value as VideoScene["content_kind"] })}>
                <option value="fact">사실 설명(주장 연결 필수)</option>
                <option value="transition">도입·전환·마무리(사실 주장 없음)</option>
              </select>
            </label>
            <label className="dk-field">
              <span>길이(초)</span>
              <input type="number" min={0.5} max={60} step={0.5} value={s.timing_sec ?? ""}
                onChange={(e) => set(i, { timing_sec: e.target.value === "" ? null : Number(e.target.value) })} />
            </label>
            <label className="dk-field">
              <span>화면 설명</span>
              <input value={s.explanation ?? ""} onChange={(e) => set(i, { explanation: e.target.value || null })} />
            </label>
            <label className="dk-field">
              <span>앞 장면과 이어짐</span>
              <input value={s.continuity ?? ""} onChange={(e) => set(i, { continuity: e.target.value || null })} />
            </label>
            <label className="dk-field">
              <span>화면 글자·주석</span>
              <input value={s.overlays ?? ""} onChange={(e) => set(i, { overlays: e.target.value || null })} />
            </label>
            {s.visual_role !== "text_card" && (
              <label className="dk-field">
                <span>그림 지시문(영어, 유료 렌더용)</span>
                <textarea rows={2} value={s.visual_prompt ?? ""} placeholder="예: A small wooden shelf holding five unbranded sake bottles…"
                  onChange={(e) => set(i, { visual_prompt: e.target.value || null })} />
              </label>
            )}
          </div>
          <ClaimChecks value={s.claim_ids} claims={claims} required={required} onChange={(v) => set(i, { claim_ids: v })} />
          <div className="actions">
            <button className="btn" disabled={i === 0} onClick={() => onChange(move(scenes, i, -1))}>↑</button>
            <button className="btn" disabled={i === scenes.length - 1} onClick={() => onChange(move(scenes, i, 1))}>↓</button>
            <button className="btn" disabled={scenes.length === 1} onClick={() => onChange(scenes.filter((_, j) => j !== i))}>장면 삭제</button>
          </div>
        </div>
      ))}
      <button className="btn" onClick={() => onChange([...scenes, blankScene()])}>+ 장면 추가</button>
    </div>
  );
}

function PageEditor({ pages, onChange, claims, required }: { pages: CarouselPage[]; onChange: (v: CarouselPage[]) => void; claims: CoreClaim[]; required: string[] }) {
  const set = (i: number, patch: Partial<CarouselPage>) => onChange(pages.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <div>
      {pages.map((p, i) => (
        <div key={i} className="dk-sub">
          <b>{i + 1}쪽</b>{" "}
          <span className={isFactItem("carousel", p) ? "pill" : "pill dk-ok"}>{isFactItem("carousel", p) ? "사실 페이지 — 주장 연결 필수" : "표지·출처(사실 주장 없음)"}</span>
          <div className="dk-grid">
            <label className="dk-field">
              <span>역할</span>
              <select value={p.role} onChange={(e) => set(i, { role: e.target.value as CarouselPage["role"] })}>
                {Object.entries(PAGE_ROLE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label className="dk-field">
              <span>제목 *</span>
              <input value={p.heading} onChange={(e) => set(i, { heading: e.target.value })} />
            </label>
            <label className="dk-field">
              <span>그래픽 지시</span>
              <input value={p.graphic_spec ?? ""} onChange={(e) => set(i, { graphic_spec: e.target.value || null })} />
            </label>
          </div>
          <label className="dk-field" style={{ marginTop: 6 }}>
            <span>본문</span>
            <textarea value={p.body ?? ""} rows={2} onChange={(e) => set(i, { body: e.target.value || null })} />
          </label>
          <ClaimChecks value={p.claim_ids} claims={claims} required={required} onChange={(v) => set(i, { claim_ids: v })} />
          <div className="actions">
            <button className="btn" disabled={i === 0} onClick={() => onChange(move(pages, i, -1))}>↑</button>
            <button className="btn" disabled={i === pages.length - 1} onClick={() => onChange(move(pages, i, 1))}>↓</button>
            <button className="btn" disabled={pages.length === 1} onClick={() => onChange(pages.filter((_, j) => j !== i))}>페이지 삭제</button>
          </div>
        </div>
      ))}
      <button className="btn" onClick={() => onChange([...pages, blankPage(pages.length + 1)])}>+ 페이지 추가</button>
    </div>
  );
}

function move<T>(arr: T[], i: number, d: number): T[] {
  const out = [...arr];
  const [x] = out.splice(i, 1);
  out.splice(i + d, 0, x);
  return out;
}

function PlanPreview({ plan }: { plan: PlanRow }) {
  if (plan.format === "video") {
    return (
      <ol className="flow-beats">
        {(plan.plan_json.scenes ?? []).map((s, i) => (
          <li key={i}>
            <b>{VISUAL_ROLE_LABEL[s.visual_role] ?? s.visual_role}</b> {s.timing_sec ? `${s.timing_sec}초` : ""} — {s.narration}
            {s.claim_ids.length > 0 && <span className="muted"> [{s.claim_ids.join(", ")}]</span>}
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="flow-beats">
      {(plan.plan_json.pages ?? []).map((p) => (
        <li key={p.position}>
          <b>{PAGE_ROLE_LABEL[p.role] ?? p.role}</b> — {p.heading}
          {p.body && <span className="muted"> · {p.body.slice(0, 60)}</span>}
          {p.claim_ids.length > 0 && <span className="muted"> [{p.claim_ids.join(", ")}]</span>}
        </li>
      ))}
    </ol>
  );
}
