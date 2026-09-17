"use client";

// 시퀀스 중심 작업 화면 (2026-09-17 운영자 요청).
//
// ★ 무엇이 바뀌었나: 종전 화면은 [대본 | 지시서] 가로 2분할이었다. 운영자 지적 —
//   "초안생성 → 지시서생성 이 과정을 하나로 통합하자 한 거였는데 그냥 화면만 가로 분할해서
//   이분만 되어 있다." 맞는 지적이다. 두 칸은 **같은 영상의 두 표현**인데 따로 놓여 있어서,
//   어느 나레이션이 어느 화면에 붙는지 눈으로 이어 붙여야 했다.
//
// ★ 그래서 한 장으로 합친다. 지시서 데이터가 이미 담고 있는 구조 그대로:
//     시퀀스(어디서 벌어지나) → 단계(무엇이 어떻게 변하나) → 컷(한글 나레이션 + 시각 지시)
//   한글과 시각 지시가 **같은 줄에 나란히** 있어서 둘을 함께 읽고 함께 고친다.
//
// ★ 시퀀스가 없는 지시서(comic·image_sequence·옛 photo)는 loose 로 떨어져 평평한 목록이
//   된다 — 화면에 분기를 두지 않는다(lib/work/sequenceView 가 그 계약을 진다).
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import type { Cut, Directive } from "@/lib/types";
import type { CutsPaneHandle } from "@/lib/work/panes";
import {
  buildSequenceLayout, sequenceRoleLabel,
  type VisualSequence, type SeqStage,
} from "@/lib/work/sequenceView";
import { useToast } from "@/components/Toast";
import { apiErrorText } from "@/lib/apiError";

export default function SequenceEditor({
  directive,
  updateUrl,
  paneRef,
  readOnly = false,
}: {
  directive: Directive | null;
  /** 논문 /api/directive-update · 리포트 /api/report-directive-update. */
  updateUrl: string;
  paneRef?: MutableRefObject<CutsPaneHandle | null>;
  readOnly?: boolean;
}) {
  const toast = useToast();
  const [cuts, setCuts] = useState<Cut[]>(directive?.cuts ?? []);
  const [seqs, setSeqs] = useState<VisualSequence[]>(
    (directive?.header as { visual_sequences?: VisualSequence[] } | null)?.visual_sequences ?? []);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  // 지시서를 새로 만들면 id 가 바뀐다 — 그때만 전면 교체한다(승인 시 status 만 바뀌므로
  // 편집이 날아가지 않는다. DirectiveClient 가 배운 것과 같은 규칙).
  const idRef = useRef(directive?.id);
  useEffect(() => {
    if (directive && directive.id !== idRef.current) {
      idRef.current = directive.id;
      setCuts(directive.cuts ?? []);
      setSeqs((directive.header as { visual_sequences?: VisualSequence[] } | null)?.visual_sequences ?? []);
      setDirty(false);
    }
  }, [directive]);

  const byNo = useMemo(() => new Map(cuts.map((c) => [c.cut_no, c])), [cuts]);
  const layout = useMemo(
    () => buildSequenceLayout(cuts.map((c) => c.cut_no), seqs), [cuts, seqs]);

  const patchCut = useCallback((cutNo: number, patch: Partial<Cut>) => {
    setCuts((prev) => prev.map((c) => (c.cut_no === cutNo ? { ...c, ...patch } : c)));
    setDirty(true);
  }, []);

  const patchStage = useCallback((si: number, ti: number, patch: Partial<SeqStage>) => {
    setSeqs((prev) => prev.map((s, i) => i !== si ? s : {
      ...s,
      stages: (s.stages ?? []).map((st, j) => (j === ti ? { ...st, ...patch } : st)),
    }));
    setDirty(true);
  }, []);

  const patchWorld = useCallback((si: number, patch: Record<string, string>) => {
    setSeqs((prev) => prev.map((s, i) => (i === si ? { ...s, world: { ...(s.world ?? {}), ...patch } } : s)));
    setDirty(true);
  }, []);

  const patchEntity = useCallback((si: number, ei: number, identity: string) => {
    setSeqs((prev) => prev.map((s, i) => i !== si ? s : {
      ...s,
      entities: (s.entities ?? []).map((e, j) => (j === ei ? { ...e, visual_identity: identity } : e)),
    }));
    setDirty(true);
  }, []);

  /** 컷을 다른 단계로 옮긴다(묶음 변경). 모든 단계의 cut_refs 에서 빼고 목표 단계에만 넣는다. */
  const moveCutToStage = useCallback((cutNo: number, targetSeq: number, targetStage: number) => {
    setSeqs((prev) => prev.map((s, si) => ({
      ...s,
      stages: (s.stages ?? []).map((st, ti) => {
        const refs = (st.cut_refs ?? []).filter((n) => n !== cutNo);
        if (si === targetSeq && ti === targetStage) refs.push(cutNo);
        return { ...st, cut_refs: refs };
      }),
    })));
    setDirty(true);
  }, []);

  const save = useCallback(async (): Promise<boolean> => {
    if (!directive) return true;              // 저장할 것이 없다 — 결정 바가 실패로 읽지 않게
    setSaving(true);
    const res = await fetch(updateUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // ★ 시퀀스가 원래 없던 지시서에는 보내지 않는다. 빈 배열을 보내면 header 에
      //   visual_sequences: [] 가 새로 생겨 "시퀀스가 있는데 비었다"로 읽힌다.
      body: JSON.stringify(seqs.length
        ? { directive_id: directive.id, cuts, visual_sequences: seqs }
        : { directive_id: directive.id, cuts }),
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
  }, [directive, updateUrl, cuts, seqs, toast]);

  // 결정 바에 손잡이를 내준다(다른 칸들과 같은 계약).
  useEffect(() => {
    if (!paneRef) return;
    paneRef.current = {
      dirty,
      save,
      directiveId: directive?.id ?? null,
      cutCount: cuts.length,
      ungrounded: cuts.filter((c) => (c.source_facts?.length ?? 0) === 0).length,
    };
  }, [paneRef, dirty, save, directive?.id, cuts]);

  if (!directive) {
    return <p className="muted">아직 지시서가 없습니다. 위 버튼으로 만듭니다.</p>;
  }

  const stageOptions = layout.sequences.flatMap((s, si) =>
    s.stages.map((st, ti) => ({ si, ti, label: `${s.sequenceId} · ${st.stageId}` })));

  function cutRow(cutNo: number, place?: { si: number; ti: number }) {
    const c = byNo.get(cutNo);
    if (!c) return null;
    const ungrounded = (c.source_facts?.length ?? 0) === 0;
    return (
      <div className="seq-cut" key={cutNo}>
        <div className="seq-cut-head">
          <b>컷 {c.cut_no}</b>
          <span className="muted">{c.estimated_sec}초</span>
          {c.visual_role && (
            <span className="chip">{c.visual_role === "MECHANISM" ? "기전 도해" : "실사"}</span>
          )}
          {ungrounded && <span className="flag">⛔ 근거 없음</span>}
          {stageOptions.length > 1 && place && !readOnly && (
            <label className="seq-move">
              묶음
              <select
                value={`${place.si}:${place.ti}`}
                onChange={(ev) => {
                  const [si, ti] = ev.target.value.split(":").map(Number);
                  moveCutToStage(cutNo, si, ti);
                }}
              >
                {stageOptions.map((o) => (
                  <option key={`${o.si}:${o.ti}`} value={`${o.si}:${o.ti}`}>{o.label}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="seq-cut-body">
          <label>
            <span className="seq-label">한글 나레이션 — 음성으로 나갈 말</span>
            <textarea
              rows={3} value={c.narration_ko ?? ""} readOnly={readOnly}
              onChange={(ev) => patchCut(cutNo, { narration_ko: ev.target.value })}
            />
          </label>
          <label>
            <span className="seq-label">이 컷의 화면 — 무엇이 보이나</span>
            <textarea
              rows={3} value={c.visual_prompt ?? ""} readOnly={readOnly}
              onChange={(ev) => patchCut(cutNo, { visual_prompt: ev.target.value })}
            />
          </label>
        </div>
      </div>
    );
  }

  return (
    <div className="seq-wrap">
      {saving && <p className="muted">저장 중…</p>}

      {layout.sequences.map((s, si) => (
        <section className="seq-card" key={`${s.sequenceId}-${si}`}>
          <header className="seq-head">
            <h3>{s.sequenceId} · {sequenceRoleLabel(s.role)}</h3>
            <span className="muted">컷 {s.cutCount}개</span>
          </header>

          <details className="seq-world">
            <summary>
              세계 설정 — 어디서 벌어지나{s.world.world_id ? ` (${s.world.world_id})` : ""}
            </summary>
            <label><span className="seq-label">장소·분위기</span>
              <textarea rows={2} value={s.world.style ?? ""} readOnly={readOnly}
                onChange={(ev) => patchWorld(si, { style: ev.target.value })} /></label>
            <label><span className="seq-label">조명</span>
              <textarea rows={1} value={s.world.lighting ?? ""} readOnly={readOnly}
                onChange={(ev) => patchWorld(si, { lighting: ev.target.value })} /></label>
            <label><span className="seq-label">배경</span>
              <textarea rows={1} value={s.world.background ?? ""} readOnly={readOnly}
                onChange={(ev) => patchWorld(si, { background: ev.target.value })} /></label>
            {s.entities.length > 0 && (
              <div className="seq-entities">
                <span className="seq-label">등장하는 것 — 시퀀스 내내 같은 모습으로 유지된다</span>
                {s.entities.map((e, ei) => (
                  <label key={e.entity_id ?? ei}>
                    <span className="muted">{e.entity_id}</span>
                    <textarea rows={2} value={e.visual_identity ?? ""} readOnly={readOnly}
                      onChange={(ev) => patchEntity(si, ei, ev.target.value)} />
                  </label>
                ))}
              </div>
            )}
          </details>

          {s.stages.map((st, ti) => (
            <div className="seq-stage" key={`${st.stageId}-${ti}`}>
              <div className="seq-stage-head">
                <b>{st.stageId}</b>
                {st.stage.camera_operation && (
                  <span className="chip">{String(st.stage.camera_operation)}</span>
                )}
                {st.missingCutNos.length > 0 && (
                  <span className="flag">⚠ 없는 컷을 가리킴: {st.missingCutNos.join(", ")}</span>
                )}
              </div>
              <label>
                <span className="seq-label">이 단계에서 무엇이 어떻게 변하나</span>
                <textarea
                  rows={2} value={String(st.stage.observable_change ?? "")} readOnly={readOnly}
                  onChange={(ev) => patchStage(si, ti, { observable_change: ev.target.value })}
                />
              </label>
              {st.cutNos.length === 0
                ? <p className="muted">이 단계에 컷이 없습니다.</p>
                : st.cutNos.map((n) => cutRow(n, { si, ti }))}
            </div>
          ))}
        </section>
      ))}

      {layout.loose.length > 0 && (
        <section className="seq-card">
          <header className="seq-head">
            <h3>{layout.hasSequences ? "묶이지 않은 컷" : "컷 목록"}</h3>
            <span className="muted">컷 {layout.loose.length}개</span>
          </header>
          {layout.hasSequences && (
            <p className="muted">어느 시퀀스에도 안 들어간 컷입니다. 렌더에는 그대로 나갑니다.</p>
          )}
          {layout.loose.map((n) => cutRow(n))}
        </section>
      )}
    </div>
  );
}
