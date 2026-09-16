"use client";

// 리포트 검수 상세 클라이언트. 논문 ReviewClient 미러(영상 프롬프트 블록 제거) +
// 컴플라이언스 패널 + ★ 하드게이트(blocked 시 승인 잠금).
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { ReportDraft } from "@/lib/reportTypes";
import type { ScriptPaneRef } from "@/lib/work/panes";
import { useGeneration, genPhaseLabel } from "@/lib/useGeneration";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import CompliancePanel from "@/components/CompliancePanel";
import EvidencePanel from "@/components/EvidencePanel";
import { apiErrorText } from "@/lib/apiError";
import { REPORT_VERSION_META, REPORT_DEFAULT_VERSION_KEY, reportVersionLabel } from "@/lib/versions";
import type { VersionType } from "@/lib/types";
import UnsavedGuard from "@/components/UnsavedGuard";
import SaveStatus from "@/components/SaveStatus";

export default function ReportReviewClient({
  reportId,
  draft,
  initialPublished = false,
  pending = null,
  validationCurrent = true,
  pane = false,
  paneRef,
}: {
  reportId: string;
  draft: ReportDraft | null;
  initialPublished?: boolean;
  /** 서버가 읽어 준 큐 상태 — 새로고침해도 "생성 중"이 유지되게 한다. */
  pending?: "queued" | "processing" | null;
  /**
   * 화면에 뜬 검사 결과가 **지금 대본**의 것인가(PR #94 후속 리뷰 P1-3).
   * false = 검사 이후 대본이 수정됐다. 승인을 막지는 않고 알리기만 한다.
   */
  validationCurrent?: boolean;
  /** 통합 작업 화면의 왼쪽 칸으로 쓰일 때 true — 자기 액션 바·승인·버전 선택을 그리지 않는다. */
  pane?: boolean;
  paneRef?: ScriptPaneRef;
}) {
  const router = useRouter();
  const toast = useToast();
  const [instruction, setInstruction] = useState("");
  const [script, setScript] = useState(draft?.script_md ?? "");
  const [dirty, setDirty] = useState(false);
  const [published, setPublished] = useState(initialPublished);
  const [approving, setApproving] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  // ⑤ 로 넘어갈 때 **어느 버전 지시서를 만들지**. 예전에는 이 선택이 화면에 없어서 버튼이
  // 말없이 만화식(comic) 하나만 발주했다 — 운영자는 "3가지가 다 만들어지는가?"를 알 수 없었다.
  // 기본은 만화식 하나(=예전 동작). 체크를 늘리면 그만큼 지시서 생성 LLM 비용이 는다.
  // (렌더 비용은 여기서 나가지 않는다 — ⑤ 에서 승인해야 렌더가 시작된다.)
  const [versions, setVersions] = useState<Set<VersionType>>(
    () => new Set<VersionType>([REPORT_DEFAULT_VERSION_KEY])
  );
  const serverRef = useRef(draft?.script_md ?? "");

  // router.refresh() 로 서버값이 바뀌면(편집 중 아닐 때만) 반영.
  if (draft?.script_md != null && draft.script_md !== serverRef.current && !dirty) {
    serverRef.current = draft.script_md;
    if (script !== draft.script_md) setScript(draft.script_md);
  }

  const gen = useGeneration({
    kickoffUrl: "/api/report-generate-draft",
    kickoffBody: { report_id: reportId },
    statusUrl: `/api/report-draft-status?report_id=${reportId}`,
    okMsg: "초안 생성 완료",
    resumeFrom: pending,
  });

  const compliance = draft?.compliance ?? null;
  // ★ 하드 차단 제거(사용자 요청) — 컴플라이언스는 참고 표시만, 승인·영상화를 잠그지 않는다.

  const fs = draft?.fact_sheet;
  const scenes = draft?.scenes ?? [];
  const flaggedSet = useMemo(
    () =>
      new Set(
        (draft?.self_check?.scenes ?? []).filter((s) => !s.grounded).map((s) => s.scene)
      ),
    [draft?.self_check?.scenes]
  );
  // v3 §5-4 — 면제 씬은 "검사해서 통과"가 아니라 "검사 대상 아님"이다. 초록으로만 두면
  // 운영자가 그 씬도 근거 대조를 받았다고 오해한다.
  const exemptSet = useMemo(
    () =>
      new Set(
        (draft?.self_check?.scenes ?? []).filter((s) => s.exempt).map((s) => s.scene)
      ),
    [draft?.self_check?.scenes]
  );

  async function recheck() {
    setRechecking(true);
    const res = await fetch("/api/report-compliance-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_id: reportId, script_md: script }),
    });
    setRechecking(false);
    if (res.ok) {
      setDirty(false);
      serverRef.current = script;
      // ★ 재검사는 워커가 한다(mode='recheck'). 라우트가 워크플로를 바로 디스패치하므로
      //   보통 1~3분이고, 디스패치가 막히면 하루 3번 도는 안전망 크론이 집어간다(몇 시간). 서버가 돌려준
      //   note 를 그대로 보여준다 — 어느 쪽인지 사람이 알아야 기다릴지 새로고침할지 정한다.
      const info = await res.json().catch(() => null);
      toast.show(`대본 저장 완료 · ${info?.note ?? "재검사 대기열에 넣었습니다"}`, "ok");
    } else {
      toast.show("재검사 요청 실패", "err");
    }
  }

  /** 대본(script_md)을 저장한다 — 통합 화면의 [변경사항 저장]. */
  async function saveScript(): Promise<boolean> {
    if (!dirty) return true;
    const up = await fetch("/api/report-draft-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_id: reportId, script_md: script }),
    });
    if (!up.ok) {
      toast.show("대본 저장 실패", "err");
      return false;
    }
    serverRef.current = script;
    setDirty(false);
    return true;
  }

  // 통합 화면에 손잡이를 내준다(lib/work/panes.ts). 렌더마다 갱신 — 결정 바가 dirty 를 본다.
  useEffect(() => {
    if (!paneRef) return;
    paneRef.current = {
      dirty,
      save: saveScript,
      getScript: () => script,
      flaggedScenes: flaggedSet.size,
      sceneCount: scenes.length,
    };
  });

  /**
   * 승인 뒤 ⑤ 지시서 생성까지 한 번에 발주할지. 예전에는 승인하고 → 긴 페이지를 끝까지
   * 내려 링크를 누르고 → ⑤ 에서 버전을 고르고 → 생성을 또 눌러야 했다(대기 2회·화면 2개).
   */
  async function approve(alsoDirective = false) {
    setApproving(true);
    // 대본 편집분 먼저 저장.
    if (dirty) {
      const up = await fetch("/api/report-draft-update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_id: reportId, script_md: script }),
      });
      if (!up.ok) {
        setApproving(false);
        toast.show("대본 저장 실패 — 승인 중단", "err");
        return;
      }
      setDirty(false);
    }
    const res = await fetch("/api/report-approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_id: reportId, final_script: script }),
    });
    setConfirmApprove(false);
    if (res.ok) {
      setPublished(true);
      if (alsoDirective) {
        // 승인과 같은 흐름에서 ⑤ 를 발주하고 그 화면으로 보낸다. 실패해도 승인은 유효하므로
        // 이동은 그대로 하고(⑤ 에서 다시 누를 수 있다) 사유만 알린다.
        const picked = [...versions];
        const gres = await fetch("/api/report-directive-generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ report_id: reportId, version_types: picked }),
        });
        setApproving(false);
        if (gres.ok)
          toast.show(
            `승인 완료 · ${picked.map(reportVersionLabel).join(", ")} 지시서를 만들고 있습니다`,
            "ok"
          );
        else {
          const e = await gres.json().catch(() => null);
          toast.show(apiErrorText(e, gres.status, "지시서 생성을 요청"), "err");
        }
        router.push(`/finance/review/${reportId}?step=5&v=${[...versions][0] ?? REPORT_DEFAULT_VERSION_KEY}`);
        return;
      }
      setApproving(false);
      toast.show("승인 완료 — 발행 이력에 기록", "ok");
      router.refresh();
    } else {
      setApproving(false);
      const e = await res.json().catch(() => null);
      toast.show(e?.blocked ? "컴플라이언스 차단 — 승인 불가" : apiErrorText(e, res.status, "대본을 승인"), "err");
    }
  }

  // 초안 미생성 상태.
  if (!draft) {
    // 통합 화면에서는 생성 버튼·진행 표시를 결정 바가 소유한다 — 여기서는 빈 칸만 알린다.
    if (pane) {
      return (
        <section className="section">
          <p className="muted">
            {gen.busy || pending ? "초안을 만드는 중입니다…" : "아직 초안이 없습니다. 위 결정 바에서 버전을 고르고 만드세요."}
          </p>
        </section>
      );
    }
    return (
      <section className="section">
        {gen.busy || pending ? (
          <div className="gen-progress">
            <span className="spinner" />{" "}
            {genPhaseLabel(gen.phase) || (pending === "processing" ? "생성 중…" : "대기 중…")}{" "}
            ({gen.elapsedSec}s)
            <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
              워커가 만드는 중입니다(보통 1~3분). 이 화면을 닫았다 열어도 이어집니다.
            </span>
          </div>
        ) : (
          <>
            <p className="muted">아직 초안이 없습니다. 생성을 요청하세요.</p>
            <textarea
              className="script"
              style={{ minHeight: 60 }}
              placeholder="세부 수정 요청(선택): 예) 리스크를 더 강조, 목표가는 사실 인용만"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
            />
            <div className="actions">
              <button
                className="btn pick"
                onClick={() => gen.run(instruction.trim() ? { instruction: instruction.trim() } : undefined)}
              >
                초안 생성 요청
              </button>
            </div>
          </>
        )}
      </section>
    );
  }

  return (
    <>
      {/* SAFE-01: 미저장 대본 편집 이탈 방지. */}
      <UnsavedGuard dirty={dirty} />
      {/* Fact Sheet */}
      {fs && (
        <section className="section factsheet">
          <h3>Fact Sheet {fs.company ? `· ${fs.company}` : ""}</h3>
          {fs.opinion && <p><b>투자의견:</b> {fs.opinion}</p>}
          {fs.what?.length > 0 && (<><div className="muted">핵심</div><ul>{fs.what.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
          {fs.numbers?.length > 0 && (<><div className="muted">수치</div><ul>{fs.numbers.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
          {fs.basis?.length > 0 && (<><div className="muted">논리·촉매</div><ul>{fs.basis.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
          {fs.risks?.length > 0 && (<><div className="muted">리스크</div><ul>{fs.risks.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
        </section>
      )}

      {/* ★ 검사 이후 대본이 수정됐는가(PR #94 후속 P1-3). 아래 근거·컴플라이언스 판정이
          지금 대본의 것이 아닐 수 있다는 사실을 **판정 위에** 놓는다 — 결과를 다 읽고 나서
          "그런데 이건 옛 대본 기준입니다"를 알려 주면 늦다. */}
      {(!validationCurrent || dirty) && (
        <div className="banner-warn" style={{ margin: "16px 0" }}>
          ⚠️ 아래 검사 결과는 <b>지금 대본의 것이 아닙니다</b>
          {dirty ? " (저장하지 않은 편집이 있습니다)" : " — 검사 이후 대본이 수정됐습니다"}.
          정확한 판정을 보려면 <b>[🔍 재검사]</b> 를 누르세요(1~3분).
          이 상태로 승인해도 막지는 않지만, 발행 기록에 “검사 이후 수정된 대본으로 승인함”이
          남습니다.
        </div>
      )}

      {/* 근거 게이트(§5·§6) — 화면의 숫자가 리포트에 실제로 있는가 */}
      <EvidencePanel evidence={draft?.evidence ?? null} storyPlan={draft?.story_plan ?? null} />

      {/* 컴플라이언스 게이트 */}
      <CompliancePanel compliance={compliance} />

      {/* 씬(나레이션) + 자기검증 */}
      <section className="section">
        <h3>씬 · 나레이션</h3>
        {scenes.map((s) => (
          <div key={s.scene} className={flaggedSet.has(s.scene) ? "scene flagged" : "scene"}>
            <div className="meta">씬 {s.scene}{s.title ? ` · ${s.title}` : ""} · {s.duration_sec}s · 근거 {s.source_facts.join(", ") || "(없음)"}</div>
            <p>{s.narration_ko}</p>
            {flaggedSet.has(s.scene) && <div className="unsupported">⚠️ 자기검증: 근거 불충분</div>}
            {exemptSet.has(s.scene) && (
              <div className="muted small">근거 대조 면제(훅·질문·마무리) — 검사 대상이 아닙니다</div>
            )}
          </div>
        ))}
      </section>

      {/* 대본(편집) */}
      <section className="section">
        <h3>대본 <SaveStatus state={dirty ? "dirty" : "saved"} /></h3>
        <textarea
          className="script"
          value={script}
          onChange={(e) => { setScript(e.target.value); setDirty(true); }}
        />
      </section>

      {/* ⑤ 로 넘어갈 때 만들 버전 — 예전에는 선택지가 없어 만화식 하나만 말없이 만들어졌다.
          체크한 버전만 지시서가 생성된다(렌더는 ⑤ 에서 승인해야 시작된다).
          이미 승인(발행)된 대본에는 [승인하고 ⑤…] 버튼이 없으므로 이 선택도 감춘다 —
          그 경우 버전은 ⑤ 화면의 버전 탭에서 고른다. */}
      {!pane && !published && (
      <section className="section">
        <h3>⑤ 지시서로 만들 버전</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
          체크한 버전의 <b>지시서만</b> 만듭니다. 여기서 렌더는 시작되지 않습니다 — 비용이 나가는
          것은 ⑤ 에서 [승인]할 때입니다. 버전을 늘리면 지시서 생성(LLM) 비용이 그만큼 늡니다.
        </p>
        <div className="toggle" style={{ flexWrap: "wrap", gap: 8 }}>
          {REPORT_VERSION_META.map((m) => (
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
            : `선택: ${[...versions].map(reportVersionLabel).join(", ")} (${versions.size}건)`}
        </p>
      </section>
      )}

      {/* 액션 바 — 재검사 / 승인(하드게이트). 통합 화면(pane)에서는 결정 바가 소유한다. */}
      {!pane && (
      <div className="action-bar">
        {gen.busy && <span className="gen-progress"><span className="spinner" /> {genPhaseLabel(gen.phase)}</span>}
        <span className="spacer" />
        <button className="btn" disabled={gen.busy} onClick={() => setConfirmRegen(true)}>초안 재생성</button>
        <button className="btn" disabled={rechecking} onClick={recheck}>
          {rechecking ? "재검사 중…" : "🔍 재검사"}
        </button>
        {published ? (
          <span className="status-pill badge-rendered">발행됨</span>
        ) : (
          <>
            <button
              className="btn"
              disabled={approving || gen.busy}
              onClick={() => setConfirmApprove(true)}
            >
              승인만
            </button>
            {/* 기본 동작 — 승인과 지시서 발주를 한 번에(화면 이동·대기 1회로). */}
            <button
              className="btn pick"
              disabled={approving || gen.busy || versions.size === 0}
              onClick={() => approve(true)}
              title={
                versions.size === 0
                  ? "위에서 만들 버전을 하나 이상 고르세요"
                  : `${[...versions].map(reportVersionLabel).join(", ")} 지시서를 만듭니다`
              }
            >
              {approving
                ? "처리 중…"
                : `승인하고 ⑤ 지시서 만들기 (${versions.size}건) →`}
            </button>
          </>
        )}
        {/* 승인 없이 지시서만 보고 싶을 때(지시서는 승인 없이도 만들 수 있다). */}
        <a className="btn" href={`/finance/review/${reportId}?step=5`} title="대본 → 영상 지시서">
          ⑤ 영상 지시서 →
        </a>
      </div>
      )}

      <ConfirmModal
        open={confirmApprove}
        title="발행 승인"
        message="이 대본을 발행 가능으로 승인합니다. 컴플라이언스 통과 상태인지 확인하세요."
        confirmLabel="승인"
        busy={approving}
        onConfirm={() => approve(false)}
        onCancel={() => setConfirmApprove(false)}
      />
      <ConfirmModal
        open={confirmRegen}
        title="초안 재생성"
        message="현재 초안을 새로 생성합니다. 편집한 대본은 덮어써질 수 있습니다."
        confirmLabel="재생성"
        danger
        busy={gen.busy}
        onConfirm={() => { setConfirmRegen(false); gen.run(); }}
        onCancel={() => setConfirmRegen(false)}
      />
    </>
  );
}
