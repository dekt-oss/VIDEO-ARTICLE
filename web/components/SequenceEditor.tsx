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
  buildSequenceLayout,
  type VisualSequence, type SeqStage,
} from "@/lib/work/sequenceView";
import { seqLabel, seqTitle, sequenceRoleLabel } from "@/lib/work/seqLabels";
import { effectLabel, transitionLabel } from "@/lib/effectLabels";
import { useToast } from "@/components/Toast";
import { apiErrorText } from "@/lib/apiError";


/** 영어 문장 위에 붙는 **한글 설명**.
 *
 * ★ 운영자 지시(2026-09-17): "영어로 되어있는건 한글로도 같이 입력해줘. 실제 작업은 영어로
 *   하더라도 내가 이해할 수 있게." 그래서 **영어 칸이 정본**이고(렌더·게이트가 쓰는 값),
 *   한글은 그 위에 읽기용으로 붙는다. 한글을 고쳐도 영상은 안 바뀌므로 입력칸으로 두지 않는다.
 * ★ 한글이 없으면(옛 지시서) 아무것도 그리지 않는다 — 빈 상자가 늘어나면 화면만 길어진다.
 *   그때는 [지시서 재생성]을 하면 한글이 함께 만들어진다.
 */
function KoNote({ text }: { text?: string | null }) {
  const t = String(text ?? "").trim();
  if (!t) return null;
  return <p className="seq-ko" title="만들 때 붙인 한국어 설명 — 영어를 고쳐도 자동으로 바뀌지 않습니다">{t}</p>;
}

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
          {/* ★ 아래에 따로 있던 "컷 목록"의 정보를 여기로 들여왔다(2026-09-17 운영자 지시:
              "이런 컷들도 위에 시퀀스랑 합쳐서 하나로 만들어줘"). 같은 컷이 두 군데 있으면
              어느 쪽을 고쳐야 하는지 매번 헷갈린다. */}
          {c.motion_source === "video"
            ? <span className="chip" title="영상으로 생성(I2V)">🎬 영상</span>
            : <span className="chip" title="스틸 이미지">🖼 스틸</span>}
          {c.visual_role && (
            <span className="chip" title={seqTitle("visual_role", c.visual_role)}>{seqLabel("visual_role", c.visual_role)}</span>
          )}
          {c.evidence_role && (
            <span className="chip" title={seqTitle("evidence_role", c.evidence_role)}>
              {seqLabel("evidence_role", c.evidence_role)}
            </span>
          )}
          {(c.claim_ids?.length ?? 0) > 0 && (
            <span className="muted" title="이 컷이 말하는 주장">주장 {c.claim_ids!.join("·")}</span>
          )}
          {ungrounded
            ? <span className="flag">⛔ 근거 없음</span>
            : <span className="muted">✓ 근거 {c.source_facts.length}</span>}
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
            <KoNote text={(c as unknown as { visual_prompt_ko?: string }).visual_prompt_ko} />
            <textarea
              rows={3} value={c.visual_prompt ?? ""} readOnly={readOnly}
              onChange={(ev) => patchCut(cutNo, { visual_prompt: ev.target.value })}
            />
          </label>
        </div>
        <details className="seq-more">
          <summary>이 컷 더 보기 — 움직임 · 효과 · 전환</summary>
          {c.motion_source === "video" && (
            <label>
              <span className="seq-label">움직임 — 영상으로 어떻게 움직이나</span>
              <KoNote text={(c as unknown as { motion_prompt_ko?: string }).motion_prompt_ko} />
              <textarea rows={2} value={c.motion_prompt ?? ""} readOnly={readOnly}
                onChange={(ev) => patchCut(cutNo, { motion_prompt: ev.target.value })} />
            </label>
          )}
          <div className="seq-fx">
            <span className="seq-label">효과</span>
            {(c.effects ?? []).length === 0 && <span className="muted">없음</span>}
            {(c.effects ?? []).map((t) => (
              <span className="chip" key={t} title={t}>
                {effectLabel(t)}
                {!readOnly && (
                  <button type="button" aria-label={`${effectLabel(t)} 빼기`}
                    onClick={() => patchCut(cutNo, { effects: (c.effects ?? []).filter((x) => x !== t) })}>×</button>
                )}
              </span>
            ))}
            {!readOnly && (
              <select value="" onChange={(ev) => {
                const v = ev.target.value;
                if (!v) return;
                const cur = c.effects ?? [];
                if (!cur.includes(v)) patchCut(cutNo, { effects: [...cur, v] });
              }}>
                <option value="">+ 효과 추가</option>
                {["ken_burns_zoom_in", "ken_burns_zoom_out", "pan_left", "pan_right", "highlight"]
                  .filter((t) => !(c.effects ?? []).includes(t))
                  .map((t) => <option key={t} value={t}>{effectLabel(t)}</option>)}
              </select>
            )}
          </div>
          <div className="seq-fx">
            <span className="seq-label">전환</span>
            <select value={c.transition ?? "cut"} disabled={readOnly}
              onChange={(ev) => patchCut(cutNo, { transition: ev.target.value })}>
              {["cut", "crossfade"].map((t) => <option key={t} value={t}>{transitionLabel(t)}</option>)}
            </select>
          </div>
        </details>
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
              {s.world.camera_base && (
                <span className="muted" title={seqTitle("camera_base", s.world.camera_base)}>
                  {" · 기본 카메라: "}{seqLabel("camera_base", s.world.camera_base)}
                </span>
              )}
            </summary>
            <label><span className="seq-label">장소·분위기</span>
              <KoNote text={s.world.style_ko} />
              <textarea rows={2} value={s.world.style ?? ""} readOnly={readOnly}
                onChange={(ev) => patchWorld(si, { style: ev.target.value })} /></label>
            <label><span className="seq-label">조명</span>
              <KoNote text={s.world.lighting_ko} />
              <textarea rows={1} value={s.world.lighting ?? ""} readOnly={readOnly}
                onChange={(ev) => patchWorld(si, { lighting: ev.target.value })} /></label>
            <label><span className="seq-label">배경</span>
              <KoNote text={s.world.background_ko} />
              <textarea rows={1} value={s.world.background ?? ""} readOnly={readOnly}
                onChange={(ev) => patchWorld(si, { background: ev.target.value })} /></label>
            {s.entities.length > 0 && (
              <div className="seq-entities">
                <span className="seq-label">등장하는 것 — 시퀀스 내내 같은 모습으로 유지된다</span>
                {s.entities.map((e, ei) => (
                  <label key={e.entity_id ?? ei}>
                    <span className="muted">{e.entity_id}</span>
                    <KoNote text={e.visual_identity_ko} />
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
                {/* ★ 코드 어휘는 한글로 보여 주고 원값은 툴팁에 남긴다 — 렌더가 쓰는 것은 원값이다. */}
                {["operation", "camera_operation", "continuity_mode", "representation_mode"]
                  .map((k) => [k, String((st.stage as Record<string, unknown>)[k] ?? "")] as const)
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <span className="chip" key={k} title={seqTitle(k, v)}>{seqLabel(k, v)}</span>
                  ))}
                {st.missingCutNos.length > 0 && (
                  <span className="flag">⚠ 없는 컷을 가리킴: {st.missingCutNos.join(", ")}</span>
                )}
              </div>
              <label>
                <span className="seq-label">이 단계에서 무엇이 어떻게 변하나</span>
                <KoNote text={String(st.stage.observable_change_ko ?? "")} />
                <textarea
                  rows={2} value={String(st.stage.observable_change ?? "")} readOnly={readOnly}
                  onChange={(ev) => patchStage(si, ti, { observable_change: ev.target.value })}
                />
              </label>
              {/* 무엇이 어떻게 바뀌는지 항목별로 — 전부 코드 어휘라 한글 표로 끝난다(비용 0). */}
              {Array.isArray(st.stage.mutations) && st.stage.mutations.length > 0 && (
                <ul className="seq-mut">
                  {(st.stage.mutations as Record<string, unknown>[]).map((m, mi) => (
                    <li key={mi}>
                      <b>{String(m.entity_id ?? "")}</b>
                      <span title={seqTitle("mutation_operation", String(m.operation ?? ""))}>
                        {" "}{seqLabel("mutation_operation", String(m.operation ?? ""))}
                      </span>
                      {m.result_state ? <span className="muted"> — {String(m.result_state)}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
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
