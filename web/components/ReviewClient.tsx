"use client";

import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { useRouter } from "next/navigation";
import type { Draft, Scene } from "@/lib/types";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import UnsavedGuard from "@/components/UnsavedGuard";
import SaveStatus, { type SaveState } from "@/components/SaveStatus";
import { useGeneration, genPhaseLabel } from "@/lib/useGeneration";
import { apiErrorText } from "@/lib/apiError";
import { VERSION_META, DEFAULT_VERSION_KEY, versionLabel } from "@/lib/versions";
import type { VersionType } from "@/lib/types";
import { warningLabel } from "@/lib/blockLabels";

// 통합 작업 화면(WorkspaceClient)이 이 칸을 다루는 손잡이 — 계약은 lib/work/panes.ts 한 곳.
import type { ScriptPaneHandle } from "@/lib/work/panes";
export type { ScriptPaneHandle } from "@/lib/work/panes";

export default function ReviewClient({
  paperId,
  draft,
  initialPublished = false,
  pending = null,
  pane = false,
  paneRef,
}: {
  paperId: string;
  draft: Draft | null;
  initialPublished?: boolean;
  /** 서버가 읽어 준 큐 상태 — 새로고침해도 "생성 중"이 유지된다. */
  pending?: "queued" | "processing" | null;
  /**
   * 통합 작업 화면의 **왼쪽 칸**으로 쓰일 때 true(설계안 v2). 자기 액션 바·승인·버전 선택을
   * 그리지 않는다 — 그것은 결정 바가 하나로 소유한다(저장 지점 4개가 1개로).
   */
  pane?: boolean;
  paneRef?: MutableRefObject<ScriptPaneHandle | null>;
}) {
  const router = useRouter();
  const toast = useToast();

  // 대본은 유일한 편집 필드. router.refresh() 는 prop 만 갱신하고 useState 를 재초기화하지
  // 않으므로, 서버값이 "실제로 바뀐 경우"에만(그리고 미저장 편집이 없을 때만) 반영한다.
  const [script, setScript] = useState(draft?.script_md ?? "");
  const [dirty, setDirty] = useState(false);
  const serverRef = useRef(draft?.script_md ?? "");
  useEffect(() => {
    const incoming = draft?.script_md ?? "";
    if (incoming !== serverRef.current) {
      serverRef.current = incoming;
      if (!dirty) setScript(incoming); // 편집 중이면 사용자 입력 보존
    }
  }, [draft?.script_md, dirty]);

  // 장면(video_prompts) 인라인 편집 — 대본과 동일한 dirty/서버동기화 패턴.
  const [scenes, setScenes] = useState<Scene[]>(draft?.video_prompts ?? []);
  const [scenesDirty, setScenesDirty] = useState(false);
  const [savingScenes, setSavingScenes] = useState(false);
  const [editScenes, setEditScenes] = useState(false);
  const scenesRef = useRef<Scene[]>(draft?.video_prompts ?? []);
  useEffect(() => {
    const incoming = draft?.video_prompts ?? [];
    if (incoming !== scenesRef.current) {
      scenesRef.current = incoming;
      if (!scenesDirty) setScenes(incoming); // 편집 중이면 사용자 입력 보존
    }
  }, [draft?.video_prompts, scenesDirty]);

  // 저장 상태 표시(SAFE-01 §8-3): 대본·장면 편집을 "현재 초안 변경사항" 하나로 묶어 말한다.
  const [saveError, setSaveError] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const anyDirty = dirty || scenesDirty;
  const saveState: SaveState = savingScenes
    ? "saving"
    : saveError
      ? "error"
      : anyDirty
        ? "dirty"
        : "saved";

  const [published, setPublished] = useState(initialPublished);
  const [approving, setApproving] = useState(false);
  const [showApprove, setShowApprove] = useState(false);
  const [showRegen, setShowRegen] = useState(false);
  // 세부 수정 요청(예: 어려운 용어 풀어쓰기) — 이 지시로 초안을 다시 다듬는다(방향 있는 재생성).
  const [instruction, setInstruction] = useState("");
  // ⑤ 로 넘어갈 때 **어느 버전 지시서를 만들지**(2026-08-20 운영자 요청 — 리포트 ④ 와 같은 방식).
  // 예전에는 ④ 에 [승인] 만 있고, 버전 선택은 ⑤ 화면까지 가야 나왔다. 기본은 만화식 하나 —
  // 체크를 늘리면 그만큼 지시서 생성(LLM) 비용이 는다. 렌더 비용은 ⑤ 에서 승인해야 나간다.
  const [versions, setVersions] = useState<Set<VersionType>>(
    () => new Set<VersionType>([DEFAULT_VERSION_KEY])
  );

  const gen = useGeneration({
    kickoffUrl: "/api/generate-draft",
    kickoffBody: { paper_id: paperId },
    statusUrl: `/api/draft-status?paper_id=${encodeURIComponent(paperId)}`,
    okMsg: "초안이 생성되었습니다.",
    resumeFrom: pending,
  });

  // 빨간깃발(근거 없음) + 긍정 근거(matched_facts) 를 씬별로 정리.
  const { flaggedMap, matchedMap, flaggedScenes, awkwardMap } = useMemo(() => {
    const flaggedMap = new Map<number, string[]>();
    const matchedMap = new Map<number, string[]>();
    // 한국어 문장 축(korean_natural=false) — 어색한 구절과 종류. 사실 판정과 섞지 않는다.
    const awkwardMap = new Map<number, { spans: string[]; kinds: string[] }>();
    for (const s of draft?.self_check?.scenes ?? []) {
      if (s.unsupported.length > 0) flaggedMap.set(s.scene, s.unsupported);
      if (s.matched_facts.length > 0) matchedMap.set(s.scene, s.matched_facts);
      if (s.korean_natural === false) {
        awkwardMap.set(s.scene, { spans: s.awkward_spans ?? [], kinds: s.fluency_issues ?? [] });
      }
    }
    return {
      flaggedMap, matchedMap, awkwardMap,
      flaggedScenes: [...flaggedMap.keys()].sort((a, b) => a - b),
    };
  }, [draft]);
  const polish = draft?.self_check?.korean_polish;

  const allGrounded = draft?.self_check?.all_grounded ?? null;

  async function copyPrompt(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.show(`${label} 복사됨`, "ok");
    } catch {
      toast.show("복사 실패 — 텍스트를 직접 선택해 복사하세요", "err");
    }
  }

  function patchScene(i: number, patch: Partial<Scene>) {
    setScenes((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
    setScenesDirty(true);
  }

  // 장면 편집 저장 — drafts.video_prompts 갱신. 성공 시 dirty 해제.
  async function saveScenes(): Promise<boolean> {
    setSavingScenes(true);
    const res = await fetch("/api/draft-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, video_prompts: scenes }),
    });
    setSavingScenes(false);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      scenesRef.current = scenes; // 방금 저장한 값이 새 서버값 — 이후 refresh 가 되돌리지 않게.
      setScenesDirty(false);
      setSaveError(false);
      setLastSavedAt(new Date().toISOString());
      toast.show("장면 편집을 저장했습니다.", "ok");
      router.refresh();
      return true;
    }
    setSaveError(true);
    toast.show(apiErrorText(e, res.status, "장면 편집을 저장"), "err");
    return false;
  }

  // 대본(script_md)을 drafts 에 저장한다 — 통합 화면(pane)에서만 쓴다.
  // ★ 예전에는 대본 편집이 승인 때 published.final_script 로만 갔고 drafts.script_md 는 그대로였다.
  //   ⑤ 지시서 생성기는 drafts.script_md 를 읽으므로 ④ 에서 고친 문장이 지시서에 닿지 않았다.
  async function saveScript(): Promise<boolean> {
    const res = await fetch("/api/draft-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, script_md: script }),
    });
    if (res.ok) {
      serverRef.current = script;
      setDirty(false);
      setSaveError(false);
      setLastSavedAt(new Date().toISOString());
      return true;
    }
    setSaveError(true);
    const e = await res.json().catch(() => null);
    toast.show(apiErrorText(e, res.status, "대본을 저장"), "err");
    return false;
  }

  /** 대본·씬을 한 번에 저장한다(결정 바의 [변경사항 저장]). 하나라도 실패하면 false. */
  async function saveAll(): Promise<boolean> {
    let ok = true;
    if (scenesDirty) ok = (await saveScenes()) && ok;
    if (dirty) ok = (await saveScript()) && ok;
    return ok;
  }

  // 통합 화면에 손잡이를 내준다. 렌더마다 갱신 — 결정 바가 dirty 를 실시간으로 본다.
  useEffect(() => {
    if (!paneRef) return;
    paneRef.current = {
      dirty: anyDirty,
      save: saveAll,
      getScript: () => script,
      flaggedScenes: flaggedScenes.length,
      sceneCount: scenes.length,
    };
  });

  /**
   * 승인. `alsoDirective` 면 같은 흐름에서 체크한 버전의 ⑤ 지시서까지 발주하고 그 화면으로 간다.
   * 예전에는 승인하고 → 긴 페이지를 끝까지 내려 링크를 누르고 → ⑤ 에서 버전을 고르고 →
   * 생성을 또 눌러야 했다(화면 2개·대기 2회).
   */
  async function approve(alsoDirective = false) {
    setApproving(true);
    // 저장 안 한 장면 편집이 있으면 먼저 저장(승인 시 유실 방지). 실패하면 승인 중단.
    if (scenesDirty) {
      const ok = await saveScenes();
      if (!ok) {
        setApproving(false);
        return;
      }
    }
    const res = await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, final_script: script }),
    });
    if (res.ok) {
      // 승인은 published 테이블에만 기록하고 drafts.script_md 는 그대로다. serverRef(=마지막 서버값)
      // 를 건드리면 이어지는 router.refresh() 의 동기화 효과가 편집본을 원본으로 되돌려버린다 →
      // 건드리지 않는다. dirty 만 내려 편집본(script)을 화면에 유지.
      setDirty(false);
      setSaveError(false);
      setLastSavedAt(new Date().toISOString());
      setPublished(true);

      if (alsoDirective) {
        // 지시서 발주가 실패해도 승인은 유효하다 — 이동은 그대로 하고(⑤ 에서 다시 누를 수 있다)
        // 사유만 알린다.
        const picked = [...versions];
        const gres = await fetch("/api/directive-generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paper_id: paperId, version_types: picked }),
        });
        setApproving(false);
        if (gres.ok) {
          toast.show(
            `승인 완료 · ${picked.map(versionLabel).join(", ")} 지시서를 만들고 있습니다`,
            "ok"
          );
        } else {
          const e = await gres.json().catch(() => null);
          toast.show(apiErrorText(e, gres.status, "지시서 생성을 요청"), "err");
        }
        router.push(
          `/review/${paperId}?step=5&v=${picked[0] ?? DEFAULT_VERSION_KEY}`
        );
        return;
      }

      setApproving(false);
      toast.show("승인되어 아카이브에 기록되었습니다.", "ok");
      router.refresh();
    } else {
      setApproving(false);
      const e = await res.json().catch(() => null);
      toast.show(apiErrorText(e, res.status, "대본을 승인"), "err");
    }
  }

  // 생성 중 진행 표시.
  const progress = gen.busy && (
    <div className="gen-progress">
      <span className="spinner" />
      <span>{genPhaseLabel(gen.phase)} {gen.elapsedSec > 0 && `· ${gen.elapsedSec}s 경과`}</span>
    </div>
  );

  if (!draft) {
    const waiting = gen.busy || !!pending;
    // 통합 화면에서는 생성 버튼·진행 표시를 결정 바가 소유한다 — 여기서는 빈 칸만 알린다.
    if (pane) {
      return (
        <div className="section">
          <p className="muted">
            {waiting ? "초안을 만드는 중입니다…" : "아직 초안이 없습니다. 위 결정 바에서 버전을 고르고 만드세요."}
          </p>
        </div>
      );
    }
    return (
      <div className="section">
        <p className="muted">
          {waiting
            ? "만드는 중입니다 — 이 화면을 닫았다 열어도 진행 상태가 이어집니다."
            : "아직 초안이 없습니다. Fact Sheet 추출 → 대본 → 자기검증까지 약 1분 걸립니다."}
        </p>
        {progress}
        {waiting && (
          <>
            <div className="skeleton skeleton-row" style={{ width: "50%" }} />
            <div className="skeleton skeleton-card" />
            <div className="skeleton skeleton-card" />
          </>
        )}
        <button className="btn pick" onClick={() => gen.run()} disabled={waiting}>
          {waiting ? "생성 중…" : "초안 생성 요청"}
        </button>
      </div>
    );
  }

  const fs = draft.fact_sheet;

  return (
    <>
      {/* SAFE-01: 미저장 편집 상태에서 이탈·내부 이동을 막는다. */}
      <UnsavedGuard dirty={anyDirty} />
      {progress}

      {published && !pane && (
        <div className="banner-ok" style={{ margin: "16px 0", display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <span>✓ 대본 승인·아카이브됨. 이제 아래 <b>④ 만화 영상 지시서</b>에서 생성·승인하면 렌더가 시작됩니다 (↓).</span>
        </div>
      )}

      {polish?.ran && (
        // 대본 다듬기 요약 — 무엇을 고쳤고 무엇을 되돌렸는지. 되돌린 것이 있으면 그 씬을 직접 본다.
        <div className="meta" style={{ margin: "8px 0" }}>
          ✎ 한국어 다듬기: 대상 {polish.targets?.length ?? 0}씬 · 적용 {polish.applied?.length ?? 0}
          {polish.rejected?.length
            ? ` · 되돌림 ${polish.rejected.length}(${polish.rejected.map((r) => `씬${r.scene}`).join(", ")}) — 사실이 흔들려 원문을 뒀습니다`
            : ""}
        </div>
      )}
      {allGrounded !== null && (
        <div className={allGrounded ? "banner-ok" : "banner-warn"} style={{ margin: "16px 0" }}>
          {allGrounded
            ? "✓ 모든 문장이 Fact Sheet로 뒷받침됨 (그래도 숫자는 원문 대조 권장)"
            : `⚠️ 근거 없는 문장 ${flaggedScenes.length}개 씬 — 아래 빨간 표시를 원문과 대조하세요`}
        </div>
      )}

      {flaggedScenes.length > 0 && (
        <div className="flag-jump">
          <span>빠른 이동:</span>
          {flaggedScenes.map((n) => (
            <a key={n} href={`#scene-${n}`}>#{n}</a>
          ))}
        </div>
      )}

      {fs && (
        <div className="section factsheet">
          <h3>Fact Sheet</h3>
          <b>발견</b>
          <ul>{fs.what_found.map((x, i) => <li key={i}>{x}</li>)}</ul>
          <b>방법</b>
          <ul>{fs.how.map((x, i) => <li key={i}>{x}</li>)}</ul>
          <b>수치</b>
          <ul>{fs.numbers.map((x, i) => <li key={i}>{x}</li>)}</ul>
          <b>한계</b>
          <ul>{fs.limitations.map((x, i) => <li key={i}>{x}</li>)}</ul>
          <p className="muted">주장 강도: {fs.claim_strength}</p>

          {/* Claim Ledger(수정명세 §4) — 어느 주장이 무엇으로 뒷받침되는지, 무엇이 비었는지. */}
          {!!fs.claims?.length && (
            <>
              <b>주장 원장 ({fs.claims.length})</b>
              <ul>
                {fs.claims.map((c) => (
                  <li key={c.claim_id} style={{ marginBottom: 6 }}>
                    <code>{c.claim_id}</code> [{c.claim_kind}] {c.claim_ko}
                    <div className="muted">
                      근거등급 {c.evidence_grade} · 인과 {c.causal_strength} · 방향{" "}
                      {c.effect_direction}
                      {c.sample_size ? ` · 표본 ${c.sample_size}` : ""}
                      {c.study_period ? ` · 기간 ${c.study_period}` : ""}
                      {c.effect_size
                        ? ` · 효과 ${c.effect_size}${c.effect_unit ?? ""}`
                        : ""}
                    </div>
                    {c.missing_fields.length > 0 && (
                      <div className="muted">
                        ⚠ 논문에서 확인 안 됨: {c.missing_fields.join(", ")} — 이 값들은 대본에
                        쓸 수 없습니다
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {/* 계획·훅 후보 — 왜 이 길이인지, 어떤 훅이 왜 탈락했는지 */}
      {draft.video_flow?.content_plan && (
        <div className="section">
          <h3>근거 계획</h3>
          <p className="muted">
            모드: <strong>{draft.video_flow.content_plan.selected_mode}</strong> (목표{" "}
            {draft.video_flow.content_plan.target_duration_min_sec}~
            {draft.video_flow.content_plan.target_duration_max_sec}초)
            {draft.video_flow.content_plan.primary_claim_id
              ? ` · 핵심 주장 ${draft.video_flow.content_plan.primary_claim_id}`
              : ""}
            {draft.video_flow.content_plan.essential_evidence_units.length
              ? ` · 필수 근거 ${draft.video_flow.content_plan.essential_evidence_units.join("·")}`
              : ""}
            {draft.video_flow.content_plan.spoken_number_count != null
              ? ` · 읽는 숫자 ${draft.video_flow.content_plan.spoken_number_count}개`
              : ""}
          </p>
          {draft.video_flow.content_plan.duration_reason && (
            <p className="oneliner">⏱ {draft.video_flow.content_plan.duration_reason}</p>
          )}
          {!!draft.video_flow.content_plan.mode_warnings.length && (
            <p className="muted">
              ⚠ {draft.video_flow.content_plan.mode_warnings.map((w) => warningLabel(w)).join(" · ")}
            </p>
          )}
          {!!draft.video_flow.hook_candidates?.length && (
            <>
              <b>훅 후보</b>
              <ul>
                {draft.video_flow.hook_candidates.map((hk) => (
                  <li key={hk.hook_id}>
                    {draft.video_flow?.selected_hook_id === hk.hook_id ? "★ " : ""}
                    <code>{hk.hook_id}</code> {hk.text_ko}
                    <div className="muted">
                      {hk.eligible ? "✓ 사용 가능" : `⛔ 탈락: ${hk.disqualify_reasons.join(", ")}`}
                      {hk.claim_ids.length ? ` · 근거 ${hk.claim_ids.join("·")}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {draft.video_flow && draft.video_flow.beats.length > 0 && (
        <div className="section">
          <h3>전체 영상 흐름 (스토리보드)</h3>
          {draft.video_flow.logline && (
            <p className="oneliner">
              🎬 {draft.video_flow.logline}
              {draft.video_flow.total_duration_sec
                ? ` · 총 ${draft.video_flow.total_duration_sec}s`
                : ""}
            </p>
          )}
          <ol className="flow-beats">
            {draft.video_flow.beats.map((b) => (
              <li key={b.order}>
                <b>{b.label || `비트 ${b.order}`}</b> — {b.summary}
                {b.transition && <span className="muted"> · 전환: {b.transition}</span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="section">
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>장면별 미디어 프롬프트 (이미지 → 영상 → 나레이션)</h3>
          <SaveStatus state={saveState} savedAt={lastSavedAt} />
          <button type="button" className="btn" onClick={() => setEditScenes((v) => !v)} disabled={savingScenes || approving}>
            {editScenes ? "✓ 편집 종료" : "✏️ 장면 편집"}
          </button>
          {scenesDirty && (
            <button
              type="button"
              className="btn pick"
              onClick={saveScenes}
              disabled={savingScenes || approving || gen.busy}
            >
              {savingScenes ? "저장 중…" : "장면 편집 저장"}
              <span className="dirty-dot" />
            </button>
          )}
        </div>
        {editScenes && (
          <p className="muted" style={{ fontSize: 12 }}>
            나레이션·프롬프트를 직접 고칠 수 있습니다. 편집은 <b>[장면 편집 저장]</b>(또는 승인)으로 저장됩니다.
            저장해도 자기검증(근거 표시)은 다시 계산되지 않으니, Fact Sheet 사실 범위를 벗어나지 않게 표현만 다듬으세요.
          </p>
        )}
        {scenes.map((sc, i) => {
          const flags = flaggedMap.get(sc.scene) ?? [];
          const matched = matchedMap.get(sc.scene) ?? [];
          const awkward = awkwardMap.get(sc.scene);
          const polishRejected = polish?.rejected?.find((r) => r.scene === sc.scene);
          const videoPrompt = sc.video_prompt || sc.visual_prompt || "";
          return (
            // FLOW-01: 씬은 기본 접힘 + 요약 헤더. 단, **근거 없는 씬과 편집 모드는 자동 펼침** —
            // 근거 표시를 접어 숨기는 것은 금지(지시서 금지사항 3).
            <details
              className={flags.length ? "scene flagged" : "scene"}
              id={`scene-${sc.scene}`}
              key={sc.scene}
              open={flags.length > 0 || editScenes}
            >
              <summary className="card-summary">
                <span className="meta">
                  #{sc.scene}
                  {sc.title ? ` · ${sc.title}` : ""} · {sc.duration_sec}s ·{" "}
                  {flags.length > 0 ? (
                    <b className="unsupported-inline">⛔ 근거 없음 {flags.length}</b>
                  ) : (
                    <span className="grounded-inline">
                      ✓ 근거 {matched.length || sc.source_facts.length}
                    </span>
                  )}
                  {awkward && (
                    <>
                      {" · "}
                      <span title={awkward.kinds.join(", ")}>
                        ✎ 한국어 어색{polishRejected ? " (다듬기 되돌림)" : polish?.applied?.includes(sc.scene) ? " (다듬음)" : ""}
                      </span>
                    </>
                  )}
                </span>
                <span className="card-peek">{sc.narration_ko}</span>
              </summary>
              <div className="meta" style={{ marginTop: 4 }}>
                근거: {sc.source_facts.join(", ") || "—"}
              </div>
              {awkward && (
                // 한국어 문장 축 — 승인을 막지 않는다. 걸린 구절을 보여 주어 운영자가 직접 다듬을 수 있게 한다.
                <div className="meta" style={{ marginTop: 4 }}>
                  ✎ 어색한 구절: {awkward.spans.length ? awkward.spans.map((s) => `"${s}"`).join(" · ") : "(구절 미표시)"}
                  {awkward.kinds.length ? ` — ${awkward.kinds.join(", ")}` : ""}
                  {polishRejected
                    ? ` — 다듬기 결과를 되돌렸습니다(${polishRejected.reason}): 숫자·단서·내용이 흔들려 원문을 뒀습니다`
                    : ""}
                </div>
              )}

              {editScenes ? (
                <>
                  <div style={{ marginTop: 6 }}>
                    <div className="muted" style={{ fontSize: 12, marginBottom: 2 }}>🇰🇷 나레이션</div>
                    <textarea
                      className="script"
                      style={{ minHeight: 64 }}
                      value={sc.narration_ko}
                      onChange={(e) => patchScene(i, { narration_ko: e.target.value })}
                    />
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <div className="muted" style={{ fontSize: 12, marginBottom: 2 }}>🇬🇧 나레이션 (EN)</div>
                    <textarea
                      className="script"
                      style={{ minHeight: 48 }}
                      value={sc.narration_en}
                      onChange={(e) => patchScene(i, { narration_en: e.target.value })}
                    />
                  </div>
                </>
              ) : (
                <div>{sc.narration_ko}</div>
              )}

              {matched.length > 0 && (
                <div className="grounded-ok">✓ 뒷받침: {matched.join(", ")}</div>
              )}

              {(editScenes || sc.image_prompt) && (
                <div className="prompt-block">
                  <div className="prompt-label">① 이미지 프롬프트 (스틸 먼저)</div>
                  {editScenes ? (
                    <>
                      <textarea
                        className="script"
                        style={{ minHeight: 56 }}
                        value={sc.image_prompt ?? ""}
                        placeholder="영문 텍스트→이미지 프롬프트"
                        onChange={(e) => patchScene(i, { image_prompt: e.target.value })}
                      />
                      <textarea
                        className="script"
                        style={{ minHeight: 40, marginTop: 6 }}
                        value={sc.image_prompt_ko ?? ""}
                        placeholder="🇰🇷 한국어 설명"
                        onChange={(e) => patchScene(i, { image_prompt_ko: e.target.value })}
                      />
                    </>
                  ) : (
                    <>
                      <div className="vp">{sc.image_prompt}</div>
                      {sc.image_prompt_ko && <div className="prompt-ko">🇰🇷 {sc.image_prompt_ko}</div>}
                      <button
                        type="button"
                        className="btn"
                        style={{ marginTop: 6 }}
                        onClick={() => copyPrompt(sc.image_prompt ?? "", `씬 #${sc.scene} 이미지 프롬프트`)}
                      >
                        이미지 프롬프트 복사
                      </button>
                    </>
                  )}
                </div>
              )}

              {(editScenes || videoPrompt) && (
                <div className="prompt-block">
                  <div className="prompt-label">② 영상 프롬프트 (이미지 → 영상)</div>
                  {editScenes ? (
                    <>
                      <textarea
                        className="script"
                        style={{ minHeight: 56 }}
                        value={sc.video_prompt ?? ""}
                        placeholder="영문 이미지→영상 프롬프트"
                        onChange={(e) => patchScene(i, { video_prompt: e.target.value })}
                      />
                      <textarea
                        className="script"
                        style={{ minHeight: 40, marginTop: 6 }}
                        value={sc.video_prompt_ko ?? ""}
                        placeholder="🇰🇷 한국어 설명"
                        onChange={(e) => patchScene(i, { video_prompt_ko: e.target.value })}
                      />
                    </>
                  ) : (
                    <>
                      <div className="vp">{videoPrompt}</div>
                      {sc.video_prompt_ko && <div className="prompt-ko">🇰🇷 {sc.video_prompt_ko}</div>}
                      <button
                        type="button"
                        className="btn"
                        style={{ marginTop: 6 }}
                        onClick={() => copyPrompt(videoPrompt, `씬 #${sc.scene} 영상 프롬프트`)}
                      >
                        영상 프롬프트 복사
                      </button>
                    </>
                  )}
                </div>
              )}

              {flags.map((f, idx) => (
                <div className="unsupported" key={idx}>
                  ⚠️ 근거 없음: {f}
                </div>
              ))}
            </details>
          );
        })}
      </div>

      <div className="section">
        <h3>
          대본 (인라인 편집) <SaveStatus state={saveState} savedAt={lastSavedAt} />
        </h3>
        <textarea
          className="script"
          value={script}
          onChange={(e) => {
            setScript(e.target.value);
            setDirty(true);
          }}
        />
        <p className="muted" style={{ fontSize: 12 }}>
          {pane ? "편집 내용은 위 [변경사항 저장] 또는 승인 시 저장됩니다." : "편집 내용은 [승인] 시 저장됩니다."}
        </p>
      </div>

      <div className="section">
        <h3>세부 수정 요청 (선택)</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          이 초안을 어떤 방향으로 다듬을지 적으면, 그 지시대로 다시 생성합니다(무작정 재생성이 아니라 방향 있는 재생성).
          예: &quot;P=NP 같은 어려운 용어를 쉽게 풀어써줘&quot;, &quot;훅을 더 자극적으로&quot;, &quot;숫자를 더 강조&quot;, &quot;더 짧고 간결하게&quot;.
          ★사실은 Fact Sheet 범위 안에서만 바뀌고 없는 내용은 추가되지 않습니다.
        </p>
        <textarea
          className="script"
          style={{ minHeight: 64 }}
          value={instruction}
          placeholder="예: P=NP, NP-난해 같은 전문 용어를 일상 비유로 풀어서 설명해줘"
          onChange={(e) => setInstruction(e.target.value)}
          disabled={gen.busy || approving}
        />
        <button
          className="btn pick"
          style={{ marginTop: 8 }}
          disabled={gen.busy || approving || !instruction.trim()}
          onClick={() => gen.run({ instruction: instruction.trim() })}
        >
          {gen.busy ? "다듬는 중…" : "이 요청으로 다듬기"}
        </button>
      </div>

      {/* ⑤ 로 넘어갈 때 만들 버전 — 승인·발주·이동을 한 번에 하기 위한 선택.
          체크한 버전의 **지시서만** 만든다. 렌더(=돈)는 ⑤ 에서 승인해야 시작된다.
          이미 승인된 대본에는 합친 버튼이 없으므로 이 선택도 감춘다(⑤ 의 버전 바에서 고른다). */}
      {!pane && !published && (
        <div className="section">
          <h3>⑤ 지시서로 만들 버전</h3>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
            체크한 버전의 <b>지시서만</b> 만듭니다. 여기서 렌더는 시작되지 않습니다 — 비용이
            나가는 것은 ⑤ 에서 [승인]할 때입니다. 버전을 늘리면 지시서 생성(LLM) 비용이 늡니다.
          </p>
          <div className="toggle" style={{ flexWrap: "wrap", gap: 8 }}>
            {VERSION_META.map((m) => (
              <label key={m.key} className="check-chip" title={m.hint}>
                <input
                  type="checkbox"
                  checked={versions.has(m.key)}
                  disabled={approving || gen.busy}
                  onChange={() =>
                    setVersions((prev) => {
                      const next = new Set(prev);
                      if (next.has(m.key)) next.delete(m.key);
                      else next.add(m.key);
                      return next;
                    })
                  }
                />
                <span>{m.label}</span>
              </label>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
            {versions.size === 0
              ? "버전을 하나 이상 선택하세요 — 선택이 없으면 [승인하고 ⑤ 지시서 만들기]를 누를 수 없습니다."
              : `선택: ${[...versions].map(versionLabel).join(", ")} (${versions.size}건)`}
          </p>
        </div>
      )}

      {!pane && (
      <div className="action-bar">
        <SaveStatus state={saveState} savedAt={lastSavedAt} />
        <span className="spacer" />
        <button className="btn" onClick={() => setShowRegen(true)} disabled={gen.busy || approving}>
          초안 재생성
        </button>
        {published ? (
          <span className="status-pill badge-rendered">승인됨</span>
        ) : (
          <>
            <button
              className="btn"
              onClick={() => setShowApprove(true)}
              disabled={gen.busy || approving}
              title="승인만 하고 이 화면에 남는다(지시서는 ⑤ 에서 따로 발주)"
            >
              {approving ? "처리 중…" : "승인만"}
              {dirty && <span className="dirty-dot" />}
            </button>
            {/* 기본 동작 — 승인·지시서 발주·⑤ 이동을 한 번에. */}
            <button
              className="btn pick"
              onClick={() => approve(true)}
              disabled={gen.busy || approving || versions.size === 0}
              title={
                versions.size === 0
                  ? "위에서 만들 버전을 하나 이상 고르세요"
                  : `${[...versions].map(versionLabel).join(", ")} 지시서를 만듭니다`
              }
            >
              {approving ? "처리 중…" : `승인하고 ⑤ 지시서 만들기 (${versions.size}건) →`}
            </button>
          </>
        )}
      </div>
      )}

      <ConfirmModal
        open={showApprove}
        title="대본 승인"
        message={
          // FLOW-01: 무엇을 승인하는지 숫자로 보여준다 — 근거 없는 씬을 모른 채 승인하지 않게.
          `현재 편집된 대본을 승인합니다(지시서는 만들지 않습니다 — ⑤ 에서 따로 발주).\n\n` +
          `· 근거 없는 씬: ${flaggedScenes.length}개\n` +
          `· 씬 수: ${scenes.length}개\n` +
          `· 저장하지 않은 편집: ${anyDirty ? "있음(승인 시 함께 저장)" : "없음"}` +
          (flaggedScenes.length > 0
            ? "\n\n⛔ 근거 없는 씬이 남아 있습니다. 원문과 대조했는지 확인하세요."
            : "")
        }
        confirmLabel="승인"
        busy={approving}
        onCancel={() => setShowApprove(false)}
        onConfirm={() => {
          setShowApprove(false);
          approve();
        }}
      />
      <ConfirmModal
        open={showRegen}
        title="초안 재생성"
        message="새 초안을 생성하면 기존 초안이 대체되고, 저장하지 않은 대본 편집도 사라집니다. 계속할까요?"
        confirmLabel="재생성"
        danger
        onCancel={() => setShowRegen(false)}
        onConfirm={() => {
          setShowRegen(false);
          gen.run();
        }}
      />
    </>
  );
}
