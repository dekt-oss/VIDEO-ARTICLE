// 지시서를 **시퀀스 → 단계 → 컷** 으로 묶어 주는 순수 함수 (2026-09-17 운영자 요청).
//
// ★ 왜 필요한가: 지시서 데이터는 이미 시퀀스 구조를 담고 있다(`header.visual_sequences`).
//   한 시퀀스는 하나의 "세계"(어디서 벌어지나)를 갖고, 그 안의 단계(stage)가 무엇이 어떻게
//   변하는지를 적고, 단계가 컷 번호를 가리킨다. 그런데 화면은 그 구조를 버리고 **컷을 한 줄로
//   늘어놓기만** 했다. 그래서 운영자가 "시퀀스별로 영상 구성이 보이게 해달라"고 했다.
//
// ★ 시퀀스가 **없는** 지시서도 있다(comic·image_sequence, 그리고 옛 photo). 그때는 모든 컷이
//   `loose` 로 떨어진다 — 화면은 같은 코드로 평평한 목록을 그린다. 분기를 화면에 두지 않는다.
//
// ★ 여기서 **컷을 잃어버리지 않는 것**이 제일 중요하다. 단계가 안 가리키는 컷, 없는 컷을
//   가리키는 단계, 두 단계가 같은 컷을 가리키는 경우가 전부 실제 데이터에 있다.

export interface SeqEntity {
  entity_id?: string;
  entity_type?: string;
  visual_identity?: string;
  /** 한글 쌍둥이 — 화면에서 읽는 용도. 렌더·게이트는 영어 원문만 쓴다(2026-09-17). */
  visual_identity_ko?: string;
  continuity?: string;
}

export interface SeqWorld {
  world_id?: string;
  style?: string;
  lighting?: string;
  background?: string;
  camera_base?: string;
  /** 한글 쌍둥이 — 화면에서 읽는 용도. 렌더·게이트는 영어 원문만 쓴다(2026-09-17). */
  style_ko?: string;
  lighting_ko?: string;
  background_ko?: string;
}

export interface SeqStage {
  stage_id?: string;
  cut_refs?: number[];
  observable_change?: string;
  /** 한글 쌍둥이 — 화면에서 읽는 용도. */
  observable_change_ko?: string;
  operation?: string;
  camera_operation?: string;
  continuity_mode?: string;
  representation_mode?: string;
  [k: string]: unknown;
}

export interface VisualSequence {
  sequence_id?: string;
  sequence_role?: string;
  world?: SeqWorld;
  entities?: SeqEntity[];
  stages?: SeqStage[];
  [k: string]: unknown;
}

export interface StageView {
  sequenceId: string;
  stageId: string;
  /** 이 단계에 실제로 존재하는 컷 번호(중복·유령 제거, 컷 순서대로). */
  cutNos: number[];
  /** 단계가 가리켰지만 지시서에 없는 컷 번호 — 화면이 경고로 보여 준다. */
  missingCutNos: number[];
  stage: SeqStage;
}

export interface SequenceView {
  sequenceId: string;
  role: string;
  world: SeqWorld;
  entities: SeqEntity[];
  stages: StageView[];
  /** 이 시퀀스가 담는 컷 수(단계 합). */
  cutCount: number;
}

export interface SequenceLayout {
  sequences: SequenceView[];
  /** 어느 단계도 가리키지 않은 컷 번호. 시퀀스가 아예 없으면 전부 여기로 온다. */
  loose: number[];
  /** 시퀀스 구조가 있는 지시서인가. */
  hasSequences: boolean;
}

/**
 * 컷 목록과 시퀀스 선언을 묶어 화면이 그릴 모양으로 만든다.
 *
 * 규칙:
 *  · 컷 번호는 `cut_no` 를 쓴다. 같은 컷을 두 단계가 가리키면 **앞 단계에만** 넣는다
 *    (그러지 않으면 같은 나레이션이 두 번 보이고, 고치면 어느 쪽이 정본인지 알 수 없다).
 *  · 단계 안의 컷은 지시서의 컷 순서대로 정렬한다 — `cut_refs` 의 적힌 순서는 믿지 않는다.
 *  · 어디에도 안 잡힌 컷은 `loose` 로 내보낸다. **버리지 않는다.**
 */
export function buildSequenceLayout(
  cutNos: readonly number[],
  sequences: readonly VisualSequence[] | null | undefined,
): SequenceLayout {
  const order = new Map(cutNos.map((n, i) => [n, i]));
  const known = new Set(cutNos);
  const taken = new Set<number>();
  const seqs = Array.isArray(sequences) ? sequences : [];

  const out: SequenceView[] = seqs.map((s, si) => {
    const rawStages: SeqStage[] = Array.isArray(s.stages) ? s.stages : [];
    const stages: StageView[] = rawStages.map((st: SeqStage, ti: number) => {
      const refs = Array.isArray(st.cut_refs) ? st.cut_refs.map(Number) : [];
      const mine: number[] = [];
      const missing: number[] = [];
      for (const n of refs) {
        if (!known.has(n)) { if (!missing.includes(n)) missing.push(n); continue; }
        if (taken.has(n)) continue;          // 앞 단계가 이미 가져갔다
        taken.add(n);
        mine.push(n);
      }
      mine.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
      return {
        sequenceId: String(s.sequence_id ?? `SEQ${si + 1}`),
        stageId: String(st.stage_id ?? `S${ti + 1}`),
        cutNos: mine,
        missingCutNos: missing,
        stage: st,
      };
    });
    return {
      sequenceId: String(s.sequence_id ?? `SEQ${si + 1}`),
      role: String(s.sequence_role ?? ""),
      world: (s.world ?? {}) as SeqWorld,
      entities: Array.isArray(s.entities) ? s.entities : [],
      stages,
      cutCount: stages.reduce((a, st) => a + st.cutNos.length, 0),
    };
  });

  return {
    sequences: out,
    loose: cutNos.filter((n) => !taken.has(n)),
    hasSequences: seqs.length > 0,
  };
}
