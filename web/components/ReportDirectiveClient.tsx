"use client";

// 리포트 영상 지시서 편집(단일 comic 버전). 논문 DirectiveClient 미러 — 버전탭·hybrid 모션칩 제거,
// API 를 report_* 라우트로 타깃. 컷별 편집·근거 빨간표시·승인후 잠금·언어선택은 그대로.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Cut, Directive, DirectiveStatus, VersionType } from "@/lib/types";
import type { DirectiveStatusMap } from "@/lib/queries";
import type { CutsPaneRef } from "@/lib/work/panes";
import { REPORT_VERSION_META, reportVersionLabel } from "@/lib/versions";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import { useGeneration, genPhaseLabel } from "@/lib/useGeneration";
import { apiErrorText } from "@/lib/apiError";
import UnsavedGuard from "@/components/UnsavedGuard";
import SaveStatus from "@/components/SaveStatus";
import ExplainerPanel from "@/components/ExplainerPanel";

const TRANSITIONS = ["cut", "crossfade"];
const FIXED_EFFECTS = ["ken_burns_zoom_in", "ken_burns_zoom_out", "pan_left", "pan_right", "highlight"];
const EFFECT_PREFIXES = ["text_overlay:", "particle:"];

const STATUS_LABEL: Record<DirectiveStatus, string> = {
  draft: "초안", approved: "승인", rendering: "렌더중", rendered: "렌더됨", failed: "실패",
};
const STATUS_BADGE: Record<DirectiveStatus, string> = {
  draft: "warn", approved: "ok", rendering: "warn", rendered: "ok", failed: "err",
};

export default function ReportDirectiveClient({
  reportId,
  version,
  directive,
  statusMap = {},
  pending = null,
  pane = false,
  paneRef,
}: {
  reportId: string;
  /** 지금 보고 있는 버전(?v=). 생성·승인·폴링이 전부 이 버전을 향한다. */
  version: VersionType;
  directive: Directive | null;
  /** 버전별 지시서 상태 — 탭 뱃지로 "어느 버전이 어디까지 갔는지" 한눈에. */
  statusMap?: DirectiveStatusMap;
  /** 서버가 읽어 준 큐 상태 — 새로고침해도 "생성 중"이 유지된다. */
  pending?: "queued" | "processing" | null;
  /** 통합 작업 화면의 오른쪽 칸으로 쓰일 때 true — 버전 탭·액션 바를 그리지 않는다(결정 바가 소유). */
  pane?: boolean;
  paneRef?: CutsPaneRef;
}) {
  const router = useRouter();
  const toast = useToast();

  const [cuts, setCuts] = useState<Cut[]>(directive?.cuts ?? []);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const serverIdRef = useRef(directive?.id);
  useEffect(() => {
    if (directive && directive.id !== serverIdRef.current) {
      serverIdRef.current = directive.id;
      setCuts(directive.cuts ?? []);
      setDirty(false);
    }
  }, [directive]);

  const [showRegen, setShowRegen] = useState(false);
  const [renderLang, setRenderLang] = useState<"ko" | "en" | "both">("both");
  const [prefixSel, setPrefixSel] = useState<Record<number, string>>({});
  const [prefixVal, setPrefixVal] = useState<Record<number, string>>({});
  const [showForce, setShowForce] = useState(false);
  const [showRerender, setShowRerender] = useState(false);
  const [pendingNav, setPendingNav] = useState<VersionType | null>(null);

  const gen = useGeneration({
    kickoffUrl: "/api/report-directive-generate",
    kickoffBody: { report_id: reportId, version_type: version },
    // ★ 폴링도 버전을 실어야 한다. 안 그러면 만화식을 만드는 중에 예전 설명판형 요청의
    //   done 을 보고 "생성 완료"로 끝난다.
    statusUrl: `/api/report-directive-status?report_id=${encodeURIComponent(reportId)}`
      + `&version_type=${version}`,
    okMsg: "지시서가 생성되었습니다.",
    resumeFrom: pending,
  });

  function navVersion(v: VersionType) {
    if (v === version) return;
    // 편집 중이면 확인 후 이동(저장 안 한 컷이 날아가지 않게).
    if (dirty) setPendingNav(v);
    else router.push(`/finance/review/${reportId}?step=5&v=${v}`);
  }

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
    const res = await fetch("/api/report-directive-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, cuts }),
    });
    setSaving(false);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      setDirty(false);
      toast.show(`저장됨 · 총 ${e?.total_estimated_sec ?? "?"}초`, "ok");
      return true;
    }
    toast.show(apiErrorText(e, res.status, "지시서를 저장"), "err");
    return false;
  }

  // 통합 화면에 손잡이를 내준다(lib/work/panes.ts). 렌더마다 갱신 — 결정 바가 dirty 를 본다.
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

  async function approve(force = false) {
    if (!directive) return;
    setSaving(true);
    const up = await fetch("/api/report-directive-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, cuts }),
    });
    if (!up.ok) {
      setSaving(false);
      const e = await up.json().catch(() => null);
      toast.show(`저장 실패로 승인 중단: ${e?.error ?? up.status}`, "err");
      return;
    }
    setDirty(false);
    const langs = renderLang === "both" ? ["ko", "en"] : [renderLang];
    const res = await fetch("/api/report-directive-approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, langs, force }),
    });
    setSaving(false);
    if (res.ok) {
      const j = await res.json().catch(() => null);
      const langLabel = renderLang === "both" ? "한국어·영어" : renderLang === "en" ? "영어" : "한국어";
      toast.show(
        j?.rendering ? `승인 · ${langLabel} 렌더 시작` : `승인 · ${langLabel} 렌더 큐 적재(워커 수동)`,
        "ok"
      );
      router.refresh();
    } else {
      const e = await res.json().catch(() => null);
      toast.show(apiErrorText(e, res.status, "지시서를 승인"), "err");
    }
  }

  // ★ 승인 잠금 뒤의 재렌더(⑤에서 바로). 렌더가 실패했거나 결과가 마음에 안 들 때, 지시서를 다시
  //   만들지 않고 **같은 지시서로 영상만 다시** 뽑는 길이다. ⑤ 에는 이 길이 없어서 잠금 뒤 남는
  //   선택지가 "지시서 재생성"(LLM 재호출 = 별도 비용)과 ⑥ 이동뿐이었다.
  //   approve() 와 달리 컷 저장을 하지 않는다 — 잠긴 지시서는 report-directive-update 가 409 를
  //   돌려주므로, 저장을 먼저 하면 재렌더가 시작도 못 한다.
  async function rerender(force = false) {
    if (!directive) return;
    setSaving(true);
    const langs = renderLang === "both" ? ["ko", "en"] : [renderLang];
    const res = await fetch("/api/report-directive-approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_id: directive.id, langs, force }),
    });
    setSaving(false);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      const langLabel = renderLang === "both" ? "한국어·영어" : renderLang === "en" ? "영어" : "한국어";
      toast.show(
        e?.rendering ? `${langLabel} 재렌더 시작` : `${langLabel} 재렌더 큐 적재(워커 수동)`,
        "ok"
      );
      router.refresh();
    } else if (res.status === 409 && (e?.block_reasons ?? []).length > 0) {
      // 게이트를 우회해 승인했던 지시서다. 여기서 막고 끝내면 되돌릴 길이 없으므로,
      // 승인 때와 같은 확인 모달을 띄워 사람이 다시 판단하게 한다.
      setShowForce(true);
    } else {
      toast.show(apiErrorText(e, res.status, "재렌더를 요청"), "err");
    }
  }

  const progress = gen.busy && (
    <div className="gen-progress">
      <span className="spinner" />
      <span>{genPhaseLabel(gen.phase)} {gen.elapsedSec > 0 && `· ${gen.elapsedSec}s 경과`}</span>
    </div>
  );

  // 버전 탭 — 만화식·설명판형을 **각각** 만들어 나란히 비교한다(논문 라인과 같은 구조).
  // 뱃지는 그 버전 지시서가 어디까지 갔는지(초안/승인/렌더됨) 보여준다.
  const tabs = pane ? null : (
    <div className="section">
      <h3>영상 버전</h3>
      <div className="toggle">
        {REPORT_VERSION_META.map((v) => {
          const st = statusMap[v.key];
          return (
            <a
              key={v.key}
              href={`/finance/review/${reportId}?step=5&v=${v.key}`}
              data-active={v.key === version}
              title={v.hint}
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
      <p className="muted">{REPORT_VERSION_META.find((v) => v.key === version)?.hint}</p>
    </div>
  );

  // 버전 전환 시 저장 안 한 편집 보호.
  const navConfirm = (
    <ConfirmModal
      open={pendingNav !== null}
      title="저장하지 않은 편집이 있습니다"
      message={`${pendingNav ? reportVersionLabel(pendingNav) : ""} 버전으로 이동하면 저장하지 않은 컷 편집이 사라집니다. 계속할까요?`}
      confirmLabel="이동" danger
      onCancel={() => setPendingNav(null)}
      onConfirm={() => {
        const v = pendingNav;
        setPendingNav(null);
        setDirty(false);
        if (v) router.push(`/finance/review/${reportId}?step=5&v=${v}`);
      }}
    />
  );

  if (!directive) {
    return (
      <>
        {tabs}
        <div className="section">
          <p className="muted">
            <b>{reportVersionLabel(version)}</b> 버전 지시서가 아직 없습니다.
            {pane ? " 위 결정 바의 [지시서 생성]으로 만듭니다." : " 승인된 대본을 컷 단위 연출 지시서로 생성합니다."}
          </p>
          {progress}
          {!gen.busy && pending && (
            <div className="gen-progress">
              <span className="spinner" /> 만드는 중입니다(보통 1~3분) — 이 화면을 닫았다 열어도
              이어집니다.
            </div>
          )}
          {!pane && (
            <button className="btn pick" onClick={() => gen.run()} disabled={gen.busy || !!pending}>
              {gen.busy || pending ? "생성 중…" : `${reportVersionLabel(version)} 지시서 생성`}
            </button>
          )}
        </div>
        {navConfirm}
      </>
    );
  }

  const h = directive.header;
  const ungrounded = cuts.filter((c) => (c.source_facts?.length ?? 0) === 0).length;
  const explainer = h?.explainer;
  // 승인 잠금은 엔진이 지시서에 박아 둔 판정을 따른다(웹에서 재판정하지 않는다).
  const gateBlocked = !!explainer?.gate?.blocked;

  return (
    <>
      {/* SAFE-01: 저장하지 않은 컷 편집 이탈 방지. */}
      <UnsavedGuard dirty={dirty} message="저장하지 않은 컷 편집이 있습니다. 이동하면 사라집니다. 계속할까요?" />
      {tabs}
      {navConfirm}
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
            버전: {reportVersionLabel(directive.version_type)}
            {" "}· 비율: {h.aspect_ratio} · 총 {h.total_estimated_sec}초 · BGM: {h.bgm?.mood || "—"}
          </p>
          {h.global_style && <p className="oneliner">🎨 {h.global_style}</p>}
        </div>
      )}

      {/* 설명판형 승인 패널(v3.3 §10) — 렌더 전에 주장 귀속·근거·숫자 의미를 확인한다. */}
      {explainer && <ExplainerPanel block={explainer} />}

      <div className="section">
        <h3>컷 ({cuts.length}) <SaveStatus state={saving ? "saving" : dirty ? "dirty" : "saved"} /></h3>
        {cuts.map((c, i) => {
          const flagged = (c.source_facts?.length ?? 0) === 0;
          const prefixed = (c.effects ?? []).filter((e) => EFFECT_PREFIXES.some((p) => e.startsWith(p)));
          return (
            <div className={`scene${flagged ? " flagged" : ""}${locked ? " locked" : ""}`} key={c.cut_no}>
              <div className="meta">
                #{c.cut_no} · {c.board ? `${c.board} · ${c.beat_role ?? "—"}` : c.visual_type} ·
                근거: {c.source_facts?.join(", ") || "⚠️ 없음"}
                {(c.number_claim_refs?.length ?? 0) > 0 &&
                  ` · 숫자주장 #${c.number_claim_refs!.join(", #")}`}
              </div>
              {(c.overlay_plan?.length ?? 0) > 0 && (
                <div className="muted">
                  화면 카드: {c.overlay_plan!.map((o) => `[${o.type}] ${o.text}`).join(" / ")}
                </div>
              )}

              <label className="prompt-label">나레이션(KO)</label>
              <textarea
                className="script" style={{ minHeight: 48 }} value={c.narration_ko} disabled={locked}
                onChange={(e) => patchCut(i, { narration_ko: e.target.value })}
              />
              <label className="prompt-label">비주얼 프롬프트</label>
              <textarea
                className="script" style={{ minHeight: 48 }} value={c.visual_prompt} disabled={locked}
                onChange={(e) => patchCut(i, { visual_prompt: e.target.value })}
              />

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
                <span>
                  <label className="prompt-label">길이(초)</label>{" "}
                  <input type="number" min={3} max={8} value={c.estimated_sec} disabled={locked}
                    onChange={(e) => patchCut(i, { estimated_sec: Number(e.target.value) })} style={{ width: 56 }} />
                </span>
                <span>
                  <label className="prompt-label">전환</label>{" "}
                  <select value={c.transition} disabled={locked}
                    onChange={(e) => patchCut(i, { transition: e.target.value })}>
                    {TRANSITIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </span>
              </div>

              <div style={{ marginTop: 8 }}>
                <label className="prompt-label">효과(effects)</label>
                <div className="chips">
                  {FIXED_EFFECTS.map((eff) => (
                    <button key={eff} type="button" className="chip"
                      data-on={(c.effects ?? []).includes(eff)} disabled={locked}
                      onClick={() => toggleEffect(i, eff)}>{eff}</button>
                  ))}
                  {prefixed.map((tok) => (
                    <span key={tok} className="chip" data-on="true">
                      {tok}{!locked && <button type="button" className="x" onClick={() => removeEffect(i, tok)}
                          aria-label={`${tok} 제거`}>✕</button>}
                    </span>
                  ))}
                </div>
                {!locked && (
                  <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                    <select value={prefixSel[i] ?? EFFECT_PREFIXES[0]}
                      onChange={(e) => setPrefixSel((p) => ({ ...p, [i]: e.target.value }))}>
                      {EFFECT_PREFIXES.map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                    <input className="search" style={{ maxWidth: 200 }} placeholder="값 입력 후 추가"
                      value={prefixVal[i] ?? ""}
                      onChange={(e) => setPrefixVal((p) => ({ ...p, [i]: e.target.value }))}
                      onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addPrefixed(i))} />
                    <button type="button" className="btn" onClick={() => addPrefixed(i)}>추가</button>
                  </div>
                )}
              </div>

              {c.bgm_cue && <div className="muted">BGM 큐: {c.bgm_cue}</div>}
              {c.render_notes && <div className="muted">렌더 노트: {c.render_notes}</div>}
              {flagged && <div className="unsupported">⚠️ 근거 없음 — 이 컷은 Fact Sheet 대조 필요</div>}
              {locked && <div className="lock-note">🔒 승인 후 편집 잠금 — 수정하려면 재생성하세요</div>}
            </div>
          );
        })}
      </div>

      {!pane && (
      <div className="action-bar">
        <span className="spacer" />
        <button className="btn" onClick={() => setShowRegen(true)} disabled={gen.busy || saving}>지시서 재생성</button>
        {!locked && (
          <button className="btn" onClick={save} disabled={saving || gen.busy}>
            {saving ? "저장 중…" : "편집 저장"}{dirty && <span className="dirty-dot" />}
          </button>
        )}
        {locked ? (
          <>
            <label className="render-lang" title="다시 렌더할 언어 선택">
              <span className="muted">언어</span>
              <select value={renderLang} onChange={(e) => setRenderLang(e.target.value as "ko" | "en" | "both")}
                disabled={saving || gen.busy}>
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="both">한·영 둘 다</option>
              </select>
            </label>
            <button
              className="btn"
              onClick={() => setShowRerender(true)}
              disabled={saving || gen.busy}
              title="지시서는 그대로 두고 영상만 다시 만듭니다(이미지·클립·나레이션 재생성 = 비용 발생)"
            >
              ↻ 다시 렌더
            </button>
            <a className="btn pick" href={`/finance/review/${reportId}?step=6`}>⑥ 렌더 결과 →</a>
          </>
        ) : (
          <>
            <label className="render-lang" title="렌더할 언어 선택">
              <span className="muted">언어</span>
              <select value={renderLang} onChange={(e) => setRenderLang(e.target.value as "ko" | "en" | "both")}
                disabled={saving || gen.busy}>
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="both">한·영 둘 다</option>
              </select>
            </label>
            {gateBlocked ? (
              <button
                className="btn"
                onClick={() => setShowForce(true)}
                disabled={saving || gen.busy}
                title="설명판형 필수 조건이 빠졌습니다. 재생성이 원칙이고, 그래도 렌더하려면 확인이 필요합니다."
              >
                ⛔ 승인 차단 — 사유 보기
              </button>
            ) : (
              <button className="btn pick" onClick={() => approve()} disabled={saving || gen.busy}>
                {saving ? "처리 중…" : "승인 → 렌더"}
              </button>
            )}
          </>
        )}
      </div>
      )}

      <ConfirmModal
        open={showRegen} title="지시서 재생성"
        message={`${reportVersionLabel(version)} 버전 지시서를 새로 생성합니다. 다른 버전은 그대로 남습니다. 현재 컷과 저장하지 않은 편집은 대체됩니다. 계속할까요?`}
        confirmLabel="재생성" danger
        onCancel={() => setShowRegen(false)}
        onConfirm={() => { setShowRegen(false); gen.run(); }}
      />

      {/* 재렌더는 돈이 나간다 — 누르기 전에 무엇이 다시 만들어지는지 한 번 보여준다. */}
      <ConfirmModal
        open={showRerender}
        title="다시 렌더"
        message={`지시서는 그대로 두고 영상만 다시 만듭니다(${
          renderLang === "both" ? "한국어·영어" : renderLang === "en" ? "영어" : "한국어"
        }). 이미지·클립·나레이션을 다시 생성하므로 비용이 발생합니다. 같은 언어가 이미 렌더 대기·진행 중이면 새로 넣지 않습니다. 계속할까요?`}
        confirmLabel="다시 렌더"
        onCancel={() => setShowRerender(false)}
        onConfirm={() => { setShowRerender(false); void rerender(); }}
      />

      {/* 게이트 차단 우회 — 원칙은 재생성이다. 우회는 서버 로그에 남는다. */}
      <ConfirmModal
        open={showForce}
        title="설명판형 필수 조건 미달"
        message={`${(explainer?.gate?.block_reasons ?? []).join(" / ")}\n\n권장: [지시서 재생성]으로 다시 만드세요. 이 상태로 렌더하면 "리포트 근거 명시형" 기준을 못 채운 영상이 나갑니다.`}
        confirmLabel={locked ? "그래도 재렌더(우회)" : "그래도 승인(우회)"} danger
        onCancel={() => setShowForce(false)}
        onConfirm={() => { setShowForce(false); void (locked ? rerender(true) : approve(true)); }}
      />
    </>
  );
}
