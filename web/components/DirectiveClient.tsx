"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { useRouter } from "next/navigation";
import type { Cut, Directive, DirectiveHeader, DirectiveStatus, VersionType } from "@/lib/types";
import { VERSION_META } from "@/lib/versions";
// 차단 사유 표시 문자열(판정은 서버·approvalGate 가 한다).
import { TIER_LABEL, blockLabel, warningLabel } from "@/lib/blockLabels";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import UnsavedGuard from "@/components/UnsavedGuard";
import SaveStatus, { type SaveState } from "@/components/SaveStatus";
import { useGeneration, genPhaseLabel } from "@/lib/useGeneration";
import { apiErrorText } from "@/lib/apiError";
import { effectLabel, transitionLabel } from "@/lib/effectLabels";

const TRANSITIONS = ["cut", "crossfade"];

// 대담·단정형 훅(H1/H2)인데 근거강도 게이트 미달이면 true(P3, engine bold_hook_gate_violation 미러).
// 게이트: evidence_strength=high AND generalization_risk=low 일 때만 대담 훅 허용.
function boldHookGateViolation(h: DirectiveHeader): boolean {
  if (h.hook_type !== "H1" && h.hook_type !== "H2") return false;
  const sr = h.science_reliability;
  return !(sr?.evidence_strength === "high" && sr?.generalization_risk === "low");
}

// effects 통제 어휘 — engine/config.py ALLOWED_EFFECTS 를 미러링(이중관리 주의).
// 고정 enum + 접두 파라미터 토큰(text_overlay:<문구>, particle:<값>). 엔진 sanitize_effects 가 안전망.
const FIXED_EFFECTS = ["ken_burns_zoom_in", "ken_burns_zoom_out", "pan_left", "pan_right", "highlight"];
const EFFECT_PREFIXES = ["text_overlay:", "particle:"];

// A타입(만화 comic) + 웹툰 장면파생(webtoon). 핵심 컷 3~4개를 영상 클립(I2V)으로 포함한다.
// (이미지 나열식은 UI 에서 제거 — 엔진/DB 는 하위호환 위해 유지. editorial 은 2026-07-28 폐기.)
// 근거밀도·가변길이 개정 — 운영자가 코드값 대신 뜻을 보게 한다.
const MODE_LABEL: Record<string, string> = {
  flash: "Flash(단순·강한 결과)",
  standard: "Standard(범위·방법·결과·한계)",
  deep: "Deep(조절효과·메커니즘)",
  extended: "Extended(예외 — 압축 시 왜곡)",
  series_split: "시리즈 분할 권고",
};
const STATUS_BADGE: Record<DirectiveStatus, string> = {
  draft: "badge-draft",
  approved: "badge-approved",
  rendering: "badge-approved",
  rendered: "badge-rendered",
  failed: "badge-trash",
};
const STATUS_LABEL: Record<DirectiveStatus, string> = {
  draft: "초안",
  approved: "승인",
  rendering: "렌더중",
  rendered: "렌더됨",
  failed: "실패",
};

// 통합 작업 화면(WorkspaceClient)이 이 칸을 다루는 손잡이 — 계약은 lib/work/panes.ts 한 곳.
import type { CutsPaneHandle } from "@/lib/work/panes";
export type { CutsPaneHandle } from "@/lib/work/panes";

export default function DirectiveClient({
  paperId,
  version,
  directive,
  statusMap = {},
  embedded = false,
  pending = null,
  pane = false,
  paneRef,
}: {
  paperId: string;
  version: VersionType;
  directive: Directive | null;
  statusMap?: Partial<Record<VersionType, DirectiveStatus>>;
  // embedded: 초안검수 화면(⑤ 단계)에 인라인 삽입. 버전 탭과 발주 바는 상위가 소유한다.
  embedded?: boolean;
  /** 서버가 읽어 준 큐 상태 — 새로고침해도 "생성 중"이 유지된다. */
  pending?: "queued" | "processing" | null;
  /** 통합 작업 화면의 **오른쪽 칸**으로 쓰일 때 true — 액션 바를 그리지 않는다(결정 바가 소유). */
  pane?: boolean;
  paneRef?: MutableRefObject<CutsPaneHandle | null>;
}) {
  const router = useRouter();
  const toast = useToast();

  const [cuts, setCuts] = useState<Cut[]>(directive?.cuts ?? []);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  // 저장 상태 표시(SAFE-01 §8-3).
  const [saveError, setSaveError] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  // 재생성은 새 directive.id 를 만든다 → id 가 바뀔 때만 컷을 전면 교체(승인 시 status 만 바뀌므로
  // 편집이 날아가지 않는다). status 로 re-seed 하면 승인 시 편집 손실.
  const serverIdRef = useRef(directive?.id);
  useEffect(() => {
    if (directive && directive.id !== serverIdRef.current) {
      serverIdRef.current = directive.id;
      setCuts(directive.cuts ?? []);
      setDirty(false);
    }
  }, [directive]);

  const [showRegen, setShowRegen] = useState(false);
  // 승인은 곧 렌더 발주(과금)다 — 무엇을 발주하는지 숫자로 확인받는다(FLOW-01).
  const [showApprove, setShowApprove] = useState(false);
  // 승인이 차단됐을 때 뜨는 2차 확인. 차단 사유 중에는 ⑤ 화면에서 풀 수 없는 것이 있다
  // (series_split_required — 2편 분할 UI 는 범위 밖). 그걸 막고 끝내면 그 논문은 렌더로 갈 길이
  // 아예 없어서, 리포트 라인과 같은 "강제 승인(흔적 남김)" 길을 둔다.
  const [blockedReasons, setBlockedReasons] = useState<string[] | null>(null);
  // ⑤ 렌더 언어 선택(규격 v2): 한국어 | 영어 | 둘 다. 승인 시 언어별 렌더 잡을 발주.
  // 기본 "둘 다": 한 번 승인에 KO/EN 2개 파일(공통 비주얼 공유). 필요시 단일 언어로 변경 가능.
  const [renderLang, setRenderLang] = useState<"ko" | "en" | "both">("both");
  const [pendingNav, setPendingNav] = useState<VersionType | null>(null);
  const [prefixSel, setPrefixSel] = useState<Record<number, string>>({});
  const [prefixVal, setPrefixVal] = useState<Record<number, string>>({});

  const gen = useGeneration({
    kickoffUrl: "/api/directive-generate",
    kickoffBody: { paper_id: paperId, version_type: version },
    statusUrl: `/api/directive-status?paper_id=${encodeURIComponent(paperId)}&version_type=${version}`,
    okMsg: "지시서가 생성되었습니다.",
    resumeFrom: pending,
  });

  const locked = directive ? directive.status !== "draft" : false;

  function patchCut(i: number, patch: Partial<Cut>) {
    setCuts((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
    setDirty(true);
  }

  function toggleEffect(i: number, token: string) {
    const cur = cuts[i].effects ?? [];
    patchCut(i, { effects: cur.includes(token) ? cur.filter((e) => e !== token) : [...cur, token] });
  }
  function addPrefixed(i: number) {
    const prefix = prefixSel[i] ?? EFFECT_PREFIXES[0];
    const val = (prefixVal[i] ?? "").trim();
    if (!val) return;
    const token = `${prefix}${val}`;
    const cur = cuts[i].effects ?? [];
    if (!cur.includes(token)) patchCut(i, { effects: [...cur, token] });
    setPrefixVal((p) => ({ ...p, [i]: "" }));
  }
  function removeEffect(i: number, token: string) {
    patchCut(i, { effects: (cuts[i].effects ?? []).filter((e) => e !== token) });
  }

  async function save(): Promise<boolean> {
    if (!directive) return true;           // 저장할 것이 없다 — 통합 화면의 [변경사항 저장]이 실패로 읽지 않게
    setSaving(true);
    const res = await fetch("/api/directive-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, cuts }),
    });
    setSaving(false);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      setDirty(false);
      setSaveError(false);
      setLastSavedAt(new Date().toISOString());
      toast.show(`저장됨 · 총 ${e?.total_estimated_sec ?? "?"}초`, "ok");
      return true;
    }
    setSaveError(true);
    toast.show(apiErrorText(e, res.status, "지시서를 저장"), "err");
    return false;
  }

  // 통합 화면에 손잡이를 내준다. 렌더마다 갱신 — 결정 바가 dirty 를 실시간으로 본다.
  useEffect(() => {
    if (!paneRef) return;
    paneRef.current = {
      dirty,
      save,
      directiveId: directive?.id ?? null,
      cutCount: cuts.length,
      ungrounded: cuts.filter((c) => (c.source_facts?.length ?? 0) === 0).length,
    };
  });

  // force=true 면 승인 게이트를 우회한다(서버 로그에 흔적이 남는다). 우회는 사람이 2차 확인
  // 모달에서 직접 고른 경우에만 붙는다 — 첫 승인은 언제나 게이트를 그대로 통과해야 한다.
  async function approve(force = false) {
    if (!directive) return;
    setSaving(true);
    // 편집을 먼저 저장한 뒤 승인. 저장 실패 시 승인 중단.
    const up = await fetch("/api/directive-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, cuts }),
    });
    if (!up.ok) {
      setSaving(false);
      setSaveError(true);
      const e = await up.json().catch(() => null);
      toast.show(
        `승인을 중단했습니다 — ${apiErrorText(e, up.status, "편집을 저장")}`,
        "err",
      );
      return;
    }
    setDirty(false);
    setSaveError(false);
    setLastSavedAt(new Date().toISOString());
    const langs = renderLang === "both" ? ["ko", "en"] : [renderLang];
    const res = await fetch("/api/directive-approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, langs, force }),
    });
    setSaving(false);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      const langLabel = renderLang === "both" ? "한국어·영어" : renderLang === "en" ? "영어" : "한국어";
      toast.show(
        e?.rendering
          ? `승인 · ${langLabel} 렌더가 시작되었습니다.`
          : `승인 · ${langLabel} 렌더 큐에 적재(워커 수동 트리거)`,
        "ok",
      );
      router.refresh();
    } else if (res.status === 409 && (e?.block_reasons ?? []).length > 0) {
      // 차단으로 끝내지 않는다 — 무엇에 걸렸는지 보여주고, 그래도 진행할지 사람이 정한다.
      setBlockedReasons(e.block_reasons as string[]);
    } else {
      toast.show(apiErrorText(e, res.status, "지시서를 승인"), "err");
    }
  }

  function navVersion(v: VersionType) {
    if (v === version) return;
    if (dirty) setPendingNav(v);
    else router.push(`/directive/${paperId}?v=${v}`);
  }

  const saveState: SaveState = saving
    ? "saving"
    : saveError
      ? "error"
      : dirty
        ? "dirty"
        : "saved";

  const progress = gen.busy && (
    <div className="gen-progress">
      <span className="spinner" />
      <span>{genPhaseLabel(gen.phase)} {gen.elapsedSec > 0 && `· ${gen.elapsedSec}s 경과`}</span>
    </div>
  );

  // 버전 탭(상태 뱃지 포함) — dirty 면 전환 시 확인. embedded(초안검수 인라인)에선 숨김.
  const tabs = embedded ? null : (
    <div className="section">
      <h3>영상 버전</h3>
      <div className="toggle">
        {VERSION_META.map((v) => {
          const st = statusMap[v.key];
          return (
            <a
              key={v.key}
              href={`/directive/${paperId}?v=${v.key}`}
              data-active={v.key === version}
              onClick={(e) => {
                e.preventDefault();
                navVersion(v.key);
              }}
            >
              {v.label}
              {st && <span className={`status-pill ${STATUS_BADGE[st]}`}>{STATUS_LABEL[st]}</span>}
            </a>
          );
        })}
      </div>
    </div>
  );

  const navConfirm = (
    <ConfirmModal
      open={pendingNav !== null}
      title="버전 전환"
      message="저장하지 않은 편집이 있습니다. 다른 버전으로 이동하면 편집 내용이 사라집니다. 이동할까요?"
      confirmLabel="이동"
      danger
      onCancel={() => setPendingNav(null)}
      onConfirm={() => {
        const v = pendingNav;
        setPendingNav(null);
        if (v) router.push(`/directive/${paperId}?v=${v}`);
      }}
    />
  );

  if (!directive) {
    return (
      <>
        {tabs}
        <div className="section">
          <p className="muted">
            {pane
              ? pending
                ? "이 버전의 지시서를 만드는 중입니다…"
                : "이 버전의 지시서가 아직 없습니다. 위 결정 바의 [지시서 생성]으로 만듭니다."
              : embedded
                ? "이 버전의 지시서가 아직 없습니다. 위 [버전 · 언어 선택]에서 체크하고 발주하세요."
                : "이 버전의 지시서가 아직 없습니다. 컷 단위 연출 지시서를 생성합니다."}
          </p>
          {progress}
          {/* embedded(⑤ 단계)에서는 발주를 VersionOrderBar 가 소유한다 — 한 화면에 발주
              버튼이 둘이면 어느 쪽이 무엇을 만드는지 알 수 없다. */}
          {!embedded && (
            <button className="btn pick" onClick={() => gen.run()} disabled={gen.busy}>
              {gen.busy ? "생성 중…" : "지시서 생성"}
            </button>
          )}
        </div>
        {navConfirm}
      </>
    );
  }

  const h = directive.header;
  const ungrounded = cuts.filter((c) => (c.source_facts?.length ?? 0) === 0).length;

  return (
    <>
      {/* SAFE-01: 컷 편집이 미저장이면 이탈·내부 이동 전에 확인한다. */}
      <UnsavedGuard dirty={dirty} message="저장하지 않은 컷 편집이 있습니다. 이동하면 사라집니다. 계속할까요?" />
      {tabs}
      {progress}

      <div className={ungrounded ? "banner-warn" : "banner-ok"} style={{ margin: "16px 0" }}>
        {ungrounded
          ? `⚠️ 근거(source_facts) 없는 컷 ${ungrounded}개 — 아래 빨간 컷을 Fact Sheet 와 대조하세요`
          : "✓ 모든 컷이 Fact Sheet 근거를 가짐"}
        {locked && ` · 상태: ${STATUS_LABEL[directive.status]}(편집 잠금)`}
      </div>

      {h && (
        <div className="section">
          <h3>헤더</h3>
          <p className="muted">
            버전: {h.version_type} · 비율: {h.aspect_ratio} · 총 {h.total_estimated_sec}초 · BGM: {h.bgm?.mood || "—"}
          </p>
          {h.global_style && <p className="oneliner">🎨 {h.global_style}</p>}
          {(h.hook_type || h.cta_type) && (
            <p className="muted" style={{ marginTop: 4 }}>
              훅: {h.hook_type ?? "—"}
              {h.hook_reframe_angle ? ` · 앵글: ${h.hook_reframe_angle}` : ""}
              {" · CTA: "}{h.cta_type ?? "none"}
              {h.loop_match ? " · 🔁 루프" : ""}
              {h.series_id ? ` · 시리즈: ${h.series_id}` : ""}
            </p>
          )}
          {h.hook_promise_check && h.hook_promise_check.pass === false && (
            <div className="banner-warn" style={{ margin: "8px 0" }}>
              ⚠️ 훅↔본문 정합 실패(낚시 위험): 훅 약속 &quot;{h.hook_promise_check.promise || "—"}&quot;를
              본문이 지불하지 못함{h.hook_promise_check.reason ? ` — ${h.hook_promise_check.reason}` : ""}
            </div>
          )}
          {boldHookGateViolation(h) && (
            <div className="banner-warn" style={{ margin: "8px 0" }}>
              ⚠️ 대담·단정형 훅({h.hook_type})인데 근거강도 미달(evidence_strength=
              {h.science_reliability?.evidence_strength ?? "?"} / generalization_risk=
              {h.science_reliability?.generalization_risk ?? "?"}) — 훅을 완화하거나 근거를 보강하세요
              {h.science_reliability?.required_caveat ? ` · 단서: ${h.science_reliability.required_caveat}` : ""}
            </div>
          )}

          {/* 근거밀도·가변길이 개정: 왜 이 길이인지 · 근거를 다 지불했는지 · 얼마 드는지 */}
          {h.content_mode && (
            <p className="muted" style={{ marginTop: 4 }}>
              모드: <strong>{MODE_LABEL[h.content_mode] ?? h.content_mode}</strong>
              {h.target_duration_min_sec != null &&
                ` (목표 ${h.target_duration_min_sec}~${h.target_duration_max_sec}초)`}
              {h.primary_claim_id ? ` · 핵심 주장 ${h.primary_claim_id}` : ""}
              {h.essential_evidence_units?.length
                ? ` · 필수 근거 ${h.essential_evidence_units.join("·")}`
                : ""}
            </p>
          )}
          {h.duration_reason && <p className="oneliner">⏱ {h.duration_reason}</p>}
          {h.cost_plan && (
            <p className="muted" style={{ marginTop: 4 }}>
              고유 에셋 {h.cost_plan.unique_asset_count}/{h.cost_plan.max_unique_assets}
              {h.cost_plan.reuse_count ? ` (재사용 ${h.cost_plan.reuse_count})` : ""}
              {" · I2V "}{h.cost_plan.video_clip_count}/{h.cost_plan.max_video_clips}개
              {` (${h.cost_plan.video_generated_sec}초)`}
              {" · 예상 생성비 $"}{h.cost_plan.estimated_total_generation_cost_usd.toFixed(2)}
            </p>
          )}
          {/* ★★ 장면별 내역(시퀀스 등급제 v2). 총액 한 줄로는 "어디에 투자했는지"를 못 본다 —
              운영자가 등급표를 고치려면 어느 장면에 얼마가 가는지 보여야 한다.
              숫자는 전부 엔진이 계산한 것을 그대로 쓴다(웹에서 산수를 다시 하지 않는다). */}
          {!!h.cost_plan?.sequences?.length && (
            <details style={{ marginTop: 6 }}>
              <summary className="muted" style={{ cursor: "pointer" }}>
                장면별 예상 비용 ({h.cost_plan.sequences.length}개 장면
                {h.cost_plan.tiers
                  ? ` · 투자 ${h.cost_plan.tiers.invest ?? 0} · 표준 ${h.cost_plan.tiers.standard ?? 0} · 절약 ${h.cost_plan.tiers.economy ?? 0}`
                  : ""})
              </summary>
              <table className="grid" style={{ marginTop: 6 }}>
                <thead>
                  <tr>
                    <th>장면</th>
                    <th>등급</th>
                    <th className="num">컷</th><th className="num">클립</th>
                    <th className="num">영상초</th><th className="num">예상</th>
                  </tr>
                </thead>
                <tbody>
                  {h.cost_plan.sequences.map((s) => (
                    <tr key={s.sequence_id}>
                      <td>
                        {s.sequence_id}
                        {s.tier_defaulted_count > 0 && (
                          <span className="muted"> (판정없음 {s.tier_defaulted_count})</span>
                        )}
                      </td>
                      <td>{TIER_LABEL[s.tier] ?? s.tier}</td>
                      <td className="num">{s.cuts}</td>
                      <td className="num">
                        {s.clips}
                        {s.candidates > 1 && <span className="muted">{` (후보 ${s.candidates})`}</span>}
                      </td>
                      <td className="num">{s.video_sec}s</td>
                      <td className="num">${s.est_usd.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {h.evidence_coverage && h.evidence_coverage.missing_claim_ids.length > 0 && (
            <div className="banner-warn" style={{ margin: "8px 0" }}>
              ⚠️ 어느 컷도 지불하지 않은 주장: {h.evidence_coverage.missing_claim_ids.join(", ")}
            </div>
          )}
          {h.approval_blocked && (
            <div className="banner-warn" style={{ margin: "8px 0" }}>
              {/* ★ blockLabel() 을 쓴다 — 사유 코드에는 `photo_cut_count_low:11<12` 처럼
                  접미사가 붙는데, 맵을 직접 찾으면 못 찾아 코드가 그대로 나간다. */}
              ⛔ 승인 차단 — {(h.block_reasons ?? []).map((r) => blockLabel(r)).join(" · ")}
            </div>
          )}
          {!!h.mode_warnings?.length && (
            <p className="muted" style={{ marginTop: 4 }}>
              {/* ★ 경고도 읽는 말로 — 종전에는 `photo_world_churn:3.38/분` 이 그대로 나갔다.
                  감지는 하는데 운영자가 못 읽으면 그 신호는 없는 것과 같다. */}
              ⚠ {h.mode_warnings.map((w) => warningLabel(w)).join(" · ")}
            </p>
          )}
        </div>
      )}

      <div className="section">
        <h3>
          컷 ({cuts.length}) <SaveStatus state={saveState} savedAt={lastSavedAt} />
        </h3>
        {cuts.map((c, i) => {
          const flagged = (c.source_facts?.length ?? 0) === 0;
          const prefixed = (c.effects ?? []).filter((e) => EFFECT_PREFIXES.some((p) => e.startsWith(p)));
          return (
            // FLOW-01: 컷은 기본 접힘 + 요약 헤더. **근거 없는 컷은 자동 펼침**(근거 표시를
            // 접어 숨기지 않는다 — 지시서 금지사항 3). 컷 8개여도 첫 화면에서 전체를 훑을 수 있다.
            <details
              className={`scene${flagged ? " flagged" : ""}${locked ? " locked" : ""}`}
              key={c.cut_no}
              open={flagged}
            >
              <summary className="card-summary">
                <span className="meta">
                  #{c.cut_no} · {c.visual_type} · {c.estimated_sec}초 ·{" "}
                  {flagged ? (
                    <b className="unsupported-inline">⛔ 근거 없음</b>
                  ) : (
                    <span className="grounded-inline">✓ 근거 {c.source_facts?.length ?? 0}</span>
                  )}
                  {c.motion_source === "video" ? " · 🎬 영상" : " · 🖼️ 스틸"}
                  {c.claim_ids?.length ? ` · 주장 ${c.claim_ids.join("·")}` : ""}
                  {c.evidence_role ? ` · ${c.evidence_role}` : ""}
                </span>
                <span className="card-peek">{c.narration_ko}</span>
              </summary>
              <div className="meta" style={{ marginTop: 4 }}>
                근거: {c.source_facts?.join(", ") || "⚠️ 없음"}
              </div>
              {(c.motion_value || c.asset_strategy) && (
                <div className="meta" style={{ marginTop: 4 }}>
                  모션 가치: {c.motion_value ?? "—"}
                  {c.motion_value && c.motion_value !== "high" && c.motion_source !== "video"
                    ? " (영상 미배정)"
                    : ""}
                  {" · 에셋: "}
                  {c.asset_strategy ?? "new_asset"}
                  {c.base_asset_ref ? ` ← 컷 ${c.base_asset_ref}` : ""}
                  {c.visual_reuse_group ? ` · 그룹 ${c.visual_reuse_group}` : ""}
                </div>
              )}
              {c.novelty_event && (
                <div className="meta" style={{ marginTop: 4 }}>✨ 새 정보: {c.novelty_event}</div>
              )}
              {c.state_change && (
                <div className="meta" style={{ marginTop: 4 }}>🔀 상태 변화: {c.state_change}</div>
              )}
              {!!c.overlay_plan?.length && (
                <div className="meta" style={{ marginTop: 4 }}>
                  🪧 화면 근거:{" "}
                  {c.overlay_plan
                    .map((o) => `${o.text} (${o.type}, ${o.duration_sec}초)`)
                    .join(" / ")}
                </div>
              )}

              {version === "hybrid" && (
                <div style={{ margin: "4px 0" }}>
                  <button
                    type="button"
                    className="chip"
                    data-on={c.motion_source === "video"}
                    disabled={locked}
                    title="영상 클립(I2V)은 편당 상한이 있어 핵심 컷에만 권장"
                    onClick={() =>
                      patchCut(i, {
                        motion_source: c.motion_source === "video" ? "still" : "video",
                      })
                    }
                  >
                    {c.motion_source === "video" ? "🎬 영상 클립 (I2V)" : "🖼️ 스틸"}
                  </button>
                </div>
              )}

              <label className="prompt-label">나레이션(KO)</label>
              <textarea
                className="script"
                style={{ minHeight: 48 }}
                value={c.narration_ko}
                disabled={locked}
                onChange={(e) => patchCut(i, { narration_ko: e.target.value })}
              />

              <label className="prompt-label">비주얼 프롬프트</label>
              <textarea
                className="script"
                style={{ minHeight: 48 }}
                value={c.visual_prompt}
                disabled={locked}
                onChange={(e) => patchCut(i, { visual_prompt: e.target.value })}
              />

              {c.motion_source === "video" && (
                <>
                  <label className="prompt-label">모션 프롬프트 (영상 컷 전용 · Veo 합류)</label>
                  <textarea
                    className="script"
                    style={{ minHeight: 40 }}
                    value={c.motion_prompt ?? ""}
                    disabled={locked}
                    placeholder="예: slow push-in, subtle motion, elements gently drift"
                    onChange={(e) => patchCut(i, { motion_prompt: e.target.value })}
                  />
                </>
              )}

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
                <span>
                  <label className="prompt-label">길이(초)</label>{" "}
                  <input
                    type="number"
                    min={3}
                    max={8}
                    value={c.estimated_sec}
                    disabled={locked}
                    onChange={(e) => patchCut(i, { estimated_sec: Number(e.target.value) })}
                    style={{ width: 56 }}
                  />
                </span>
                <span>
                  <label className="prompt-label">전환</label>{" "}
                  <select
                    value={c.transition}
                    disabled={locked}
                    onChange={(e) => patchCut(i, { transition: e.target.value })}
                  >
                    {TRANSITIONS.map((t) => (
                      <option key={t} value={t}>{transitionLabel(t)}</option>
                    ))}
                  </select>
                </span>
              </div>

              <div style={{ marginTop: 8 }}>
                <label className="prompt-label">효과(effects)</label>
                <div className="chips">
                  {FIXED_EFFECTS.map((eff) => (
                    <button
                      key={eff}
                      type="button"
                      className="chip"
                      data-on={(c.effects ?? []).includes(eff)}
                      disabled={locked}
                      onClick={() => toggleEffect(i, eff)}
                      title={eff}
                    >
                      {effectLabel(eff)}
                    </button>
                  ))}
                  {prefixed.map((tok) => (
                    <span key={tok} className="chip" data-on="true" title={tok}>
                      {effectLabel(tok)}
                      {!locked && <button type="button" className="x" onClick={() => removeEffect(i, tok)}
                          aria-label={`${tok} 제거`}>✕</button>}
                    </span>
                  ))}
                </div>
                {!locked && (
                  <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                    <select
                      value={prefixSel[i] ?? EFFECT_PREFIXES[0]}
                      onChange={(e) => setPrefixSel((p) => ({ ...p, [i]: e.target.value }))}
                    >
                      {EFFECT_PREFIXES.map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                    <input
                      className="search"
                      style={{ maxWidth: 200 }}
                      placeholder="값 입력 후 추가"
                      value={prefixVal[i] ?? ""}
                      onChange={(e) => setPrefixVal((p) => ({ ...p, [i]: e.target.value }))}
                      onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addPrefixed(i))}
                    />
                    <button type="button" className="btn" onClick={() => addPrefixed(i)}>추가</button>
                  </div>
                )}
              </div>

              {c.bgm_cue && <div className="muted">BGM 큐: {c.bgm_cue}</div>}
              {c.render_notes && <div className="muted">렌더 노트: {c.render_notes}</div>}
              {flagged && <div className="unsupported">⚠️ 근거 없음 — 이 컷은 Fact Sheet 대조 필요</div>}
              {locked && <div className="lock-note">🔒 승인 후 편집 잠금 — 수정하려면 재생성하세요</div>}
            </details>
          );
        })}
      </div>

      {!pane && (
      <div className="action-bar">
        <span className="spacer" />
        <button className="btn" onClick={() => setShowRegen(true)} disabled={gen.busy || saving}>
          지시서 재생성
        </button>
        {!locked && (
          <button className="btn" onClick={save} disabled={saving || gen.busy}>
            {saving ? "저장 중…" : "편집 저장"}
            {dirty && <span className="dirty-dot" />}
          </button>
        )}
        {locked ? (
          <a className="btn pick" href="/render">⑥ 렌더 결과 →</a>
        ) : embedded ? null : (
          <>
            <label className="render-lang" title="렌더할 언어 선택(한/영 동시 운영)">
              <span className="muted">언어</span>
              <select
                value={renderLang}
                onChange={(e) => setRenderLang(e.target.value as "ko" | "en" | "both")}
                disabled={saving || gen.busy}
              >
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="both">한·영 둘 다</option>
              </select>
            </label>
            <button className="btn pick" onClick={() => setShowApprove(true)} disabled={saving || gen.busy}>
              {saving ? "처리 중…" : "승인 → 렌더"}
            </button>
          </>
        )}
      </div>
      )}

      <ConfirmModal
        open={showApprove}
        title="지시서 승인 → 렌더 발주"
        message={
          `승인하면 선택한 언어로 렌더가 시작됩니다(비용이 발생합니다).\n\n` +
          `· 컷 수: ${cuts.length}개 · 예상 총 길이: ${cuts.reduce((n, c) => n + Number(c.estimated_sec ?? 0), 0)}초\n` +
          (h?.content_mode
            ? `· 콘텐츠 모드: ${MODE_LABEL[h.content_mode] ?? h.content_mode}\n`
            : "") +
          (h?.evidence_coverage
            ? `· 필수 근거: ${
                h.evidence_coverage.required_claim_ids.length -
                h.evidence_coverage.missing_claim_ids.length
              }/${h.evidence_coverage.required_claim_ids.length}\n`
            : "") +
          `· 근거 없는 컷: ${ungrounded}개\n` +
          (h?.cost_plan
            ? `· 고유 에셋 ${h.cost_plan.unique_asset_count}개 · I2V ${h.cost_plan.video_clip_count}개(${h.cost_plan.video_generated_sec}초)\n` +
              `· 예상 생성비: $${h.cost_plan.estimated_total_generation_cost_usd.toFixed(2)}\n`
            : "") +
          `· 렌더 언어: ${renderLang === "both" ? "한국어 + 영어(2본)" : renderLang === "en" ? "영어" : "한국어"}` +
          (h?.approval_blocked
            ? `\n\n⛔ 승인 차단: ${(h.block_reasons ?? [])
                .map((r) => blockLabel(r))
                .join(" · ")}`
            : "") +
          (ungrounded > 0
            ? "\n\n⛔ 근거 없는 컷이 남아 있습니다. Fact Sheet 와 대조했는지 확인하세요."
            : "")
        }
        confirmLabel="승인하고 렌더 시작"
        busy={saving}
        onCancel={() => setShowApprove(false)}
        onConfirm={() => {
          setShowApprove(false);
          approve();
        }}
      />

      <ConfirmModal
        open={blockedReasons !== null}
        title="승인이 차단되었습니다"
        danger
        busy={saving}
        message={
          `⛔ 차단 사유\n${(blockedReasons ?? []).map((r) => `· ${blockLabel(r)}`).join("\n")}\n\n` +
          "원칙은 [지시서 재생성]입니다 — 다시 만들면 대부분의 사유가 풀립니다.\n" +
          "다만 '시리즈로 분할'처럼 이 화면에서 풀 수 없는 사유도 있습니다(2편 분할 기능은 아직 없음).\n" +
          "그대로 진행하면 이 지시서 한 편으로 렌더가 시작되고 비용이 발생합니다. 우회 기록은 서버 로그에 남습니다."
        }
        confirmLabel="사유를 확인했고 그대로 렌더"
        onCancel={() => setBlockedReasons(null)}
        onConfirm={() => {
          setBlockedReasons(null);
          approve(true);
        }}
      />

      <ConfirmModal
        open={showRegen}
        title="지시서 재생성"
        message="새 지시서를 생성하면 현재 컷과 저장하지 않은 편집이 대체됩니다. 계속할까요?"
        confirmLabel="재생성"
        danger
        onCancel={() => setShowRegen(false)}
        onConfirm={() => {
          setShowRegen(false);
          gen.run();
        }}
      />
      {navConfirm}
    </>
  );
}
