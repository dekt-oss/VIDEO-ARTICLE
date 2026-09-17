// 지시서의 **코드 어휘**를 한국어로 (2026-09-17 운영자 지시).
//
// ★ 운영자 요청: "지시서에 영어로 되어있는건 한글로도 같이 입력해줘. 실제 작업은 영어로
//   하더라도 내가 이해할 수 있게 해줘."
//
// ★ 여기서 다루는 것은 **enum(코드 어휘)** 뿐이다. `DOLLY_IN`·`MUTATE_STATE` 처럼 값이 정해져
//   있는 것들이라 표 하나로 끝나고 **비용이 0이다**. 자유 문장(세계 묘사·화면 프롬프트)은
//   번역이 필요하므로 지시서를 만들 때 한글을 함께 받는다(engine/visual_sequence.py 의 `*_ko`).
//
// ★★ 영어 원값은 **버리지 않는다.** 화면은 한글을 보여주고 원값은 툴팁(title)에 남긴다 —
//   렌더·게이트·프롬프트가 쓰는 것은 영어 원값이고, 둘을 대조할 수 있어야 한다
//   (effectLabels.ts 가 이미 쓰는 규칙과 같다).
//
// ★★★ 엔진 목록(engine/config.py)과 갈리면 tests/test_seq_labels_cover_engine_vocab.py 가
//   잡는다. 새 enum 이 엔진에 생기면 여기도 채워야 한다 — 빠지면 화면에 영어가 다시 샌다.

const CAMERA_OPERATION: Record<string, string> = {
  ORBIT: "둘레를 돌며 본다",
  DOLLY_IN: "천천히 다가간다",
  DOLLY_OUT: "천천히 물러난다",
  TRACK: "옆으로 따라간다",
  TOP_DOWN: "위에서 내려다본다",
  SECTION_DIVE: "단면 속으로 파고든다",
  FOLLOW_OBJECT: "대상을 따라간다",
  HOLD: "고정 — 카메라는 그대로",
};

const CAMERA_BASE: Record<string, string> = {
  elevated_three_quarter: "약간 위에서 비스듬히",
  eye_level_front: "눈높이 정면",
  top_down: "바로 위에서",
  low_angle: "아래에서 올려다보며",
  side_profile: "옆에서",
  close_detail: "가까이 클로즈업",
};

const CONTINUITY_MODE: Record<string, string> = {
  NEW_WORLD: "새 장소에서 새로 시작",
  CONTINUE_WORLD: "같은 장소·같은 카메라로 이어서",
  MUTATE_STATE: "같은 화면에서 대상만 변한다",
  CAMERA_REVEAL: "화면은 그대로, 카메라만 움직인다",
  RETURN_WORLD: "앞서 떠난 장소로 되돌아온다",
  REFERENCE_CONDITIONED_NEW_STATE: "앞 화면을 참고하되 새로 배치",
};

const REPRESENTATION_MODE: Record<string, string> = {
  LITERAL_OBSERVATION: "실제로 관측한 장면",
  SCHEMATIC_PRINCIPLE: "원리를 나타낸 도해 (실제 장면 아님)",
  METAPHOR: "비유 — 사실로 오인되면 안 됨",
};

const SEQUENCE_ROLE: Record<string, string> = {
  MECHANISM_SEQUENCE: "기전 — 원리가 단계로 진행한다",
  REALITY_ANCHOR: "현실 — 실제 현장·사람으로 붙잡는다",
  RESULT_SEQUENCE: "결과 — 숫자·결과가 갱신된다",
  FRAMING: "틀 — 후크와 마무리",
};

const VISUAL_OPERATION: Record<string, string> = {
  REVEAL: "드러낸다", CUTAWAY: "잘라 속을 보인다", EXPLODE: "분해해 펼친다",
  ASSEMBLE: "조립한다", SPLIT: "쪼갠다", MERGE: "합친다",
  TRANSFER: "옮긴다", FLOW: "흐른다", ACCUMULATE: "쌓인다",
  TRANSFORM: "모양이 바뀐다", ISOLATE: "하나만 남긴다", ZOOM_INTO: "안으로 파고든다",
};

const MUTATION_OPERATION: Record<string, string> = {
  APPEAR: "나타난다",
  DISAPPEAR: "사라진다",
  MOVE: "이동한다",
  GROW: "커진다·늘어난다",
  SHRINK: "작아진다·줄어든다",
  ROTATE: "회전한다",
  TRANSFORM: "모양이 바뀐다",
  SPLIT_OFF: "떨어져 나온다",
  MERGE_INTO: "합쳐져 들어간다",
  HIGHLIGHT: "강조된다",
  DIM: "흐려진다",
  REVERSE_TRACE: "거꾸로 되짚는다",
  IMPACT: "부딪힌다·충격이 온다",
};

const EVIDENCE_ROLE: Record<string, string> = {
  primary_result: "핵심 결과",
  mechanism: "원리·이유",
  scope: "범위·표본",
  caveat: "단서·한계",
  implication: "의미·시사점",
  connective: "이음말",
  hook: "후크",
};

const VISUAL_ROLE: Record<string, string> = {
  MECHANISM: "기전 도해",
  REALITY: "실사 장면",
};

const TABLES: Record<string, Record<string, string>> = {
  camera_operation: CAMERA_OPERATION,
  camera_base: CAMERA_BASE,
  continuity_mode: CONTINUITY_MODE,
  representation_mode: REPRESENTATION_MODE,
  sequence_role: SEQUENCE_ROLE,
  operation: VISUAL_OPERATION,
  mutation_operation: MUTATION_OPERATION,
  evidence_role: EVIDENCE_ROLE,
  visual_role: VISUAL_ROLE,
};

/**
 * 코드 어휘 한 개를 한국어로. 모르는 값은 **원값을 그대로** 돌려준다.
 *
 * ★ 숨기지 않는 이유: 엔진에 새 enum 이 생겼는데 이 표에 없으면, 빈칸이 뜨는 대신 영어가 보여야
 *   "표에 빠진 게 있다"를 알 수 있다. 조용히 사라지면 영원히 모른다(effectLabels 와 같은 규칙).
 */
export function seqLabel(kind: keyof typeof TABLES | string, value: string | null | undefined): string {
  const v = String(value ?? "").trim();
  if (!v) return "";
  return TABLES[kind]?.[v] ?? v;
}

/** 화면에 "한글 (원값)" 으로 보여줄 때 쓸 툴팁 문자열. 원값을 잃지 않기 위한 것. */
export function seqTitle(kind: string, value: string | null | undefined): string {
  const v = String(value ?? "").trim();
  const ko = seqLabel(kind, v);
  return ko && ko !== v ? `${v} — ${ko}` : v;
}

export const SEQ_LABEL_TABLES = TABLES;

/** 시퀀스 역할을 사람 말로. 값이 비면 "묶음". 모르는 값은 원값 그대로(숨기지 않는다). */
export function sequenceRoleLabel(role: string | null | undefined): string {
  return seqLabel("sequence_role", role) || "묶음";
}
