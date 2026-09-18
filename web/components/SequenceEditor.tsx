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
  buildFlowLayout,
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
/** 한글을 앞에 세우고 **영문 원문은 접어 둔다** (2026-09-17 운영자 지시).
 *
 * ★ 지시: "실제로 구현하는 영문 지시서는 숨기고 한글 위주로 보여줘. 내가 판단하고 수정하고
 *   지시하는 건 한글이 될 테니까."
 * ★ 그래도 **영문이 정본**이다 — 렌더·게이트가 읽는 것은 영문이고, 한글은 그것을 설명한 것이다.
 *   그래서 영문을 지우지 않고 접어 두고, 그 안에서는 그대로 고칠 수 있게 남긴다.
 * ★ 한글이 아직 없는 옛 지시서는 영문을 **펼친 채로** 보여 준다 — 접어 버리면 화면이 텅 빈다.
 */
function KoBox({
  label, koText, enText, onEn, readOnly, rows = 2,
}: {
  label: string;
  koText?: string | null;
  enText: string;
  onEn: (v: string) => void;
  readOnly?: boolean;
  rows?: number;
}) {
  const ko = String(koText ?? "").trim();
  return (
    <div className="seq-field">
      <span className="seq-label">{label}</span>
      {ko ? <p className="seq-ko">{ko}</p> : null}
      {/* ★ 영문은 **언제나 접어 둔다**(2026-09-17 운영자 지시: "실제로 구현하는 영문 지시서는
          숨기고 한글 위주로 보여줘"). 한글이 없을 때도 영문을 펼쳐 두지 않는다 — 그러면
          화면이 다시 영어로 뒤덮인다. 대신 한 줄로 "한글 설명이 없다"고 알리고,
          고치거나 대조할 사람만 펼친다. 렌더가 읽는 정본은 여전히 이 영문이다. */}
      <details className="seq-en">
        <summary>
          {ko ? "영문 원문 보기 (실제 발주 문장)" : "⚠ 한글 설명 없음 — 영문 보기"}
        </summary>
        {!ko && (
          <p className="muted">
            이 지시서는 한글 설명이 붙기 전에 만들어졌습니다. [지시서 재생성]을 하면 함께 만들어집니다.
          </p>
        )}
        <textarea rows={rows} value={enText} readOnly={readOnly}
          onChange={(ev) => onEn(ev.target.value)} />
      </details>
    </div>
  );
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
  // ★ 재생 순서를 축으로 삼는다(2026-09-17). 시퀀스로 묶으면 화면 순서와 영상 순서가 어긋난다.
  const blocks = useMemo(
    () => buildFlowLayout(cuts.map((c) => c.cut_no), seqs), [cuts, seqs]);

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

  const stageOptions = seqs.flatMap((s, si) =>
    (s.stages ?? []).map((st, ti) => ({
      si, ti, label: `${s.sequence_id ?? `SEQ${si + 1}`} · ${st.stage_id ?? `S${ti + 1}`}`,
    })));

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
          <label className="seq-field">
            {/* ★ 나레이션은 한글이 **정본**이다 — 이 문장이 그대로 음성으로 나간다.
                그래서 여기만은 접지 않고 늘 펼쳐 둔다. */}
            <span className="seq-label">한글 나레이션 — 이 문장이 그대로 음성으로 나갑니다</span>
            <textarea
              rows={3} value={c.narration_ko ?? ""} readOnly={readOnly}
              onChange={(ev) => patchCut(cutNo, { narration_ko: ev.target.value })}
            />
          </label>
          <KoBox label="이 컷의 화면 — 무엇이 보이나" rows={3}
            koText={(c as unknown as { visual_prompt_ko?: string }).visual_prompt_ko}
            enText={c.visual_prompt ?? ""}
            onEn={(v) => patchCut(cutNo, { visual_prompt: v })} readOnly={readOnly} />
        </div>
        <details className="seq-more">
          <summary>이 컷 더 보기 — 움직임 · 효과 · 전환</summary>
          {/* 도해 구조의 한글 요약(2026-09-18). 구조 필드 자체는 영어(그림용)라 여기엔 한 줄만. */}
          {Boolean((c as unknown as { mechanism_ko?: string }).mechanism_ko) && (
            <p className="seq-mech-ko">
              <span className="seq-label">도해가 보여주는 원리</span>{" "}
              {(c as unknown as { mechanism_ko?: string }).mechanism_ko}
            </p>
          )}
          {c.motion_source === "video" && (
            <KoBox label="움직임 — 영상으로 어떻게 움직이나"
              koText={(c as unknown as { motion_prompt_ko?: string }).motion_prompt_ko}
              enText={c.motion_prompt ?? ""}
              onEn={(v) => patchCut(cutNo, { motion_prompt: v })} readOnly={readOnly} />
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

      {blocks.map((b, bi) => (
        <section className="seq-card" key={`${b.sequenceId}-${b.stageId}-${bi}`}>
          <header className="seq-head">
            {b.seqIndex < 0 ? (
              <h3>컷 {b.cutNos.join(", ")}</h3>
            ) : (
              <h3>
                {b.sequenceId} · {b.stageId} — {sequenceRoleLabel(b.role)}
              </h3>
            )}
            <span className="muted">컷 {b.cutNos.join(", ")}</span>
          </header>

          {/* 세계 설정은 그 시퀀스가 **처음 나올 때만** 보여 준다 — 같은 세계를 오갈 때마다
              같은 상자가 반복되면 화면만 길어진다. */}
          {b.firstOfSequence && b.seqIndex >= 0 && (
            <details className="seq-world">
              <summary>
                세계 설정 — 어디서 벌어지나{b.world.world_id ? ` (${b.world.world_id})` : ""}
                {b.world.camera_base && (
                  <span className="muted" title={seqTitle("camera_base", b.world.camera_base)}>
                    {" · 기본 카메라: "}{seqLabel("camera_base", b.world.camera_base)}
                  </span>
                )}
              </summary>
              <KoBox koText={b.world.style_ko} enText={b.world.style ?? ""} label="장소·분위기"
                onEn={(v) => patchWorld(b.seqIndex, { style: v })} readOnly={readOnly} rows={2} />
              <KoBox koText={b.world.lighting_ko} enText={b.world.lighting ?? ""} label="조명"
                onEn={(v) => patchWorld(b.seqIndex, { lighting: v })} readOnly={readOnly} rows={1} />
              <KoBox koText={b.world.background_ko} enText={b.world.background ?? ""} label="배경"
                onEn={(v) => patchWorld(b.seqIndex, { background: v })} readOnly={readOnly} rows={1} />
              {b.entities.length > 0 && (
                <div className="seq-entities">
                  <span className="seq-label">등장하는 것 — 시퀀스 내내 같은 모습으로 유지된다</span>
                  {b.entities.map((e, ei) => (
                    <KoBox key={e.entity_id ?? ei} label={e.entity_id ?? `등장물 ${ei + 1}`}
                      koText={e.visual_identity_ko} enText={e.visual_identity ?? ""}
                      onEn={(v) => patchEntity(b.seqIndex, ei, v)} readOnly={readOnly} rows={2} />
                  ))}
                </div>
              )}
            </details>
          )}

          {b.seqIndex >= 0 && (
            <>
              <div className="seq-stage-head">
                {["operation", "camera_operation", "continuity_mode", "representation_mode"]
                  .map((k) => [k, String((b.stage as Record<string, unknown>)[k] ?? "")] as const)
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <span className="chip" key={k} title={seqTitle(k, v)}>{seqLabel(k, v)}</span>
                  ))}
              </div>
              <KoBox label="이 단계에서 무엇이 어떻게 변하나"
                koText={String(b.stage.observable_change_ko ?? "")}
                enText={String(b.stage.observable_change ?? "")}
                onEn={(v) => patchStage(b.seqIndex, b.stageIndex, { observable_change: v })}
                readOnly={readOnly} rows={2} />
              {Array.isArray(b.stage.mutations) && b.stage.mutations.length > 0 && (
                <ul className="seq-mut">
                  {(b.stage.mutations as Record<string, unknown>[]).map((m, mi) => (
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
            </>
          )}

          {b.cutNos.map((n) => cutRow(n, b.seqIndex >= 0 ? { si: b.seqIndex, ti: b.stageIndex } : undefined))}
        </section>
      ))}

    </div>
  );
}
