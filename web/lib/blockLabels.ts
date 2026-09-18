// 승인 차단 사유 코드 → 운영자가 읽는 말.
//
// ★ 차단 사유는 전부 **코드가 데이터로 확정한 것**이다(결정 D-E4). LLM 판단(범위확대·인과과장 등)은
//   경고로만 뜨고 승인을 막지 않는다.
// ★ 사유 코드의 정본은 engine/directive.directive_block_reasons + engine/content_mode.block_reasons 이고
//   web/lib/approvalGate.ts 가 그 미러다(tests/test_prompt_sync.py 가 어긋남을 잡는다).
//   여기 있는 것은 **표시 문자열**뿐 — 판정 로직이 아니다.
// 시퀀스 등급(engine/config.SEQUENCE_TIERS) → 운영자가 읽는 말.
//   ★ 판정은 engine/sequence_tier.effective_tier 가 한다. 여기는 표시 문자열뿐이다.
// 제작 준비도 만점. engine/config.PRODUCTION_SCORE_MAX 의 미러.
// ★ 종전에는 화면에 10 이 하드코딩돼 있었다 — 2026-09-04 에 mechanism 축이 붙어
//   만점이 12가 되면서 "10/10" 이 아니라 "12/10" 이 나갈 뻔했다.
//   tests/test_prompt_sync.py 가 파이썬 값과의 어긋남을 잡는다.
export const PRODUCTION_SCORE_MAX = 12;
// mechanism 축이 붙기 전(2026-09-04 이전)에 매겨진 행의 만점. 그 행들은 이 자로 읽는다.
export const PRODUCTION_LEGACY_SCORE_MAX = 10;

export const TIER_LABEL: Record<string, string> = {
  invest: "투자",      // 기전을 설명하는 컷 — 긴 클립 + 연출 계약 + 후보 선택
  standard: "표준",
  economy: "절약",
};

export const BLOCK_LABEL: Record<string, string> = {
  over_max_duration: "80초 초과",
  series_split_required: "독립 핵심 주장 2개 — 시리즈로 분할",
  video_budget_exceeded: "영상 초수 예산 초과",
  video_cost_exceeded: "영상 금액 예산 초과",
  missing_required_claims: "필수 주장을 지불한 컷이 없음",
  primary_claim_not_covered: "핵심 주장을 지불한 컷이 없음",
  claim_evidence_not_run: "주장↔원문 대조가 돌지 않은 초안입니다(엣지 경로). 검증 통과가 아니라 미검증입니다",
  cut_claim_not_in_source: "이 컷이 지불하는 주장의 인용이 원문에 없음(지어낸 인용)",
  claim_quote_not_in_source: "주장의 인용문이 원문에 없음(지어낸 인용)",
  claim_without_quote: "원문이 있는데 주장에 인용을 안 붙임",
  // ── 실사형 화면 계약(engine/photo_contract.py BLOCK_REASONS 의 표시 문자열) ──
  photo_hook_missing: "상단 고정 부제(훅)가 비었음",
  photo_visual_role_missing: "역할(MECHANISM/REALITY) 선언이 없는 컷",
  photo_forbidden_screen_request: "이미지에 차트·라벨·숫자를 요구함(가짜 숫자 위험)",
  photo_number_without_overlay: "숫자를 말하는데 화면 카드(오버레이)가 없음",
  photo_cut_count_low: "목표 길이에 비해 컷이 너무 적음(슬라이드쇼가 된다)",
  photo_mechanism_missing: "3D 도해 컷이 하나도 없음",
  photo_mechanism_spec_missing: "도해 컷에 구조(무엇→무엇) 서술이 없음",
  photo_mechanism_decorative: "도해가 배경·장식에 그침",
  photo_skeleton_shortfall: "컷 골격보다 컷이 적음(모델이 칸을 합쳤다)",
  photo_role_name_in_prompt: "프롬프트에 역할명(MECHANISM/REALITY)이 남아 그림에 글자로 박힘",
  photo_overlay_year_unverified: "화면 카드의 연도가 Fact Sheet 에 없음(지어낸 연도)",
  photo_reuse_without_state_change: "재사용 컷인데 화면에서 무엇이 변하는지 안 밝힘",
  photo_reuse_identical_render: "재사용 컷이 기준 컷과 사실상 같은 그림(진행 없는 반복)",
  // ── 시각 시퀀스 계약(engine/visual_sequence_contract.py BLOCK_REASONS) ──
  vseq_too_few_stages: "시퀀스인데 단계가 1개뿐(한 장면으로 끝나는 설명)",
  vseq_no_progression: "단계에 상태 변화가 없음(화면이 멈춰 있다)",
  vseq_dangling_continuity: "이어받을 단계를 가리켰는데 그 단계가 없음",
  vseq_missing_entity: "참조한 개체가 선언 목록에 없음",
  vseq_quantitative_visual: "정확한 수치를 화면 물체 개수로 표현하려 함(생성 모델은 개수를 못 지킨다)",
  vseq_spec_token_in_prompt: "카메라 각도·렌즈 규격이 프롬프트에 남음(화면에 글자로 그려진다)",
  vseq_state_lineage_mismatch: "앞 단계에 없던 개체 상태를 물려받았다고 적음(있지도 않던 것을 이어받을 수 없다)",
  vseq_state_entity_undeclared: "선언하지 않은 개체가 상태·변화에 등장(단계마다 다른 모습으로 그려진다)",
  vseq_no_actual_mutation: "진행하는 시퀀스인데 변화 선언이 없음(달라졌다는 말이 모델 자기보고뿐)",
  vseq_literal_without_source: "실제 관측 장면이라고 선언했는데 확보한 근거가 관측 방식을 말하지 않음",
  photo_text_request_conflict: "프롬프트가 글자를 그리라고 하면서 같은 문장에서 글자를 금지함(모순)",
  photo_quoted_label_in_prompt:
    "따옴표로 이름을 붙임 — 생성 모델이 그 이름을 글자로 그려 넣습니다(언어 공유가 깨짐)",
  photo_style_word_in_prompt:
    "장면 묘사가 화풍·렌즈 기법을 지시함 — 화풍은 코드가 정하는데 여기가 이깁니다",
  photo_mechanism_prompt_detached:
    "도해 구조(components)와 장면(visual_prompt)이 서로 딴 것을 말함 — 구조가 그림에 닿지 않습니다",
  cut_detail_not_in_source: "확보한 원문이 지불하지 않는 구체 절차·장비·경로를 화면에 그리려 함",
};

// 경고 사유 코드 → 운영자가 읽는 말.
//
// ★ 왜 따로 두는가: 경고는 **승인을 막지 않는다.** 차단과 같은 맵에 섞으면 화면에서
//   "막힌 것"과 "봐 두라는 것"이 구분되지 않는다.
// ★ 왜 이제야 생겼나(2026-09-04): mode_warnings 가 화면에 **코드 이름 그대로** 나가고
//   있었다(`photo_world_churn:3.38/분`). 감지는 하는데 운영자가 읽을 수 없으면
//   그 신호는 없는 것과 같다 — 이 저장소가 차단 쪽에서 이미 겪은 실패다.
// ★ 정본은 engine/photo_contract.WARNING_REASONS. 여기는 표시 문자열뿐이다.
export const WARNING_LABEL: Record<string, string> = {
  // 벤치마크(발행된 설명 영상 105초) 실측에서 나온 것들
  photo_narrative_no_mechanism:
    "대본이 원리를 설명하는 컷이 부족함 — 그림만 도해라 화면이 겉돕니다",
  photo_world_churn:
    "시퀀스마다 새 장소를 만듦(분당 세계 수) — 한 곳에 머물며 축척만 바꾸는 편이 낫습니다",
  photo_no_close_scale: "근접 시점이 없음 — 크기 대비가 안 생겨 실감이 떨어집니다",
  photo_subject_dominates:
    "연구 대상(동물·장비)이 화면을 너무 오래 차지 — 원리·맥락·의미 컷으로 옮기세요",
  photo_hook_visual_repeated:
    "훅 두 컷이 같은 그림 — 대비를 넓게 보여준 뒤 한쪽으로 밀고 들어가야 합니다",
  photo_video_camera_repaired:
    "영상 컷이 고정이라 마지막 구간에 푸시인을 넣었습니다(코드 보정)",
  photo_video_cut_never_moves:
    "영상 컷인데 카메라가 고정 — 영상비를 내고 정지 화면을 받습니다",
  photo_visual_role_backfilled:
    "화면 역할이 비어 있어 실사(REALITY)로 채웠습니다 — 의도한 것인지 확인하세요",
  photo_source_has_no_mechanism:
    "이 논문은 '왜 그런지'를 말하지 않음 — 원리 설명형으로 만들 소재가 아닙니다(선별 단계 문제)",
  photo_number_punch_is_a_sentence:
    "화면 수치 카드에 문장이 들어감 — 수치·단위만 남기고 설명은 근거 카드로",
  // 기존 경고들
  photo_role_balance_off: "도해/실사 비율이 권장에서 벗어남",
  photo_video_cut_count_off: "영상 컷 수가 권장 범위 밖",
  photo_video_cuts_not_adjacent: "영상 컷이 흩어져 이어지는 맛이 끊김",
  photo_cut_too_long: "한 컷이 권장 상한보다 김",
  photo_mechanism_thin: "도해가 장식적일 수 있음(근거 1개)",
  photo_mechanism_spec_inherited: "재사용 컷이 기준 컷의 구조를 물려받음(면제)",
  photo_mechanism_structured: "어휘는 장식적이나 단계가 진행을 구조로 선언함",
  photo_mechanism_unlabeled: "기전 시퀀스에 범례·캡션이 없음(어느 쪽이 무엇인지 화면이 말하지 않는다)",
  photo_keyword_is_a_sentence: "키워드 카드가 문장임(카드는 낱말 하나여야 한다)",
  photo_keyword_repeats_narration: "키워드 카드가 나레이션을 그대로 옮겨 적음(같은 말을 두 번)",
  photo_pointer_zone_unknown: "화살표가 가리킬 구역 이름이 틀림(화살표가 사라진다)",
  photo_reuse_base_overused: "한 기준 컷에서 파생이 너무 많음(그 대상이 화면을 지배)",
  photo_undrawable_difference:
    "차이를 판정 어휘로 적음(healthier·improved 등) — 모델은 그것을 못 그려 두 화면이 같아집니다",
  photo_mechanism_starts_late:
    "원리 설명이 너무 늦게 시작함 — 전반부가 통째로 연구 소개가 됩니다",
  photo_role_claim_mismatch:
    "컷의 역할 라벨이 가리키는 근거와 맞지 않음 — 라벨만 바뀌었을 수 있습니다",
  photo_world_lead_disagrees:
    "세계를 여는 컷이 그 세계를 안 그림 — 뒤 컷들이 그 오해를 물려받습니다",
  photo_lead_cut_missing_entity:
    "여는 컷이 뒤에서 움직일 물체를 안 그림 — 없는 것은 줄일 수 없어 컷들이 같은 화면이 됩니다",
  // 대본 자기검증(engine/selfcheck) 축 — 씬 번호가 `#N` 으로 붙는다.
  korean_awkward: "한국어가 어색함(번역투·조사·문체 혼용) — 다듬기가 한 번 다시 썼거나, 사실이 흔들려 원문을 뒀습니다",
  scope_expanded: "대본이 논문 범위를 넓힘(일부 → 전체)",
  qualifier_dropped: "논문의 단서(평균적으로·특정 조건에서)가 대본에서 빠짐",
  causal_overreach: "연관을 인과로 말함",
  numeric_mismatch: "대본의 숫자·단위·방향이 Fact Sheet 와 다름",
  editorial_inference: "논문이 지지하지 않는 해석·교훈을 덧붙임",
  photo_glow_normalized:
    "발광 어휘를 코드가 앰버 강조로 옮김(화풍이 금지하는 빛남입니다)",
  photo_optics_normalized:
    "렌즈 어휘(blurred·depth of field)를 코드가 배치 표현으로 바꿨음 — 화풍은 코드가 정합니다",
  photo_prompt_number_removed:
    "이미지 프롬프트의 퍼센트 수치를 코드가 지웠음 — 같은 숫자를 화면 카드가 그립니다",
  vseq_lineage_appear_inserted:
    "앞 단계에 없던 개체를 코드가 이 단계에서 등장(APPEAR)시켰음 — 새로 나타나는 장면이 됩니다",
};

// 접미사가 컷 번호 목록인가("3,5") — 아니면 값이다("3.38/분", "0<2").
// ★ 이 구분이 없으면 `photo_world_churn:3.38/분` 이 "(컷 3.38/분)" 으로 나간다.
const CUT_LIST = /^\d+(,\d+)*$/;

function decorate(label: string, detail: string | undefined): string {
  if (!detail) return label;
  return CUT_LIST.test(detail) ? `${label} (컷 ${detail})` : `${label} — ${detail}`;
}

export function blockLabel(code: string): string {
  // claim_id_invalid#3 처럼 접미사가 붙는 사유가 있어 접두 매칭도 본다.
  if (BLOCK_LABEL[code]) return BLOCK_LABEL[code];
  if (code.startsWith("claim_id_invalid")) return `존재하지 않는 주장 참조(${code})`;
  // 실사형 사유는 `photo_x:3,5` 처럼 컷 번호가 붙는다 — 접두로 찾고 번호를 덧붙인다.
  const [head, detail] = code.split(":", 2);
  if (BLOCK_LABEL[head]) return decorate(BLOCK_LABEL[head], detail);
  // ★ 경고 라벨도 본다 — warningLabel 이 BLOCK_LABEL 을 보는 것과 대칭이다.
  //   경고에서 차단으로 승격되는 사유가 있다(photo_undrawable_difference 는
  //   config.PHOTO_UNDRAWABLE_BLOCKS 로 올라간다). 한쪽만 폴백을 두면 그날 코드가 그대로 나간다.
  if (WARNING_LABEL[head]) return decorate(WARNING_LABEL[head], detail);
  return code;
}

/** 경고 사유 코드 → 읽는 말. 라벨이 없으면 코드를 그대로 돌려준다(숨기지 않는다). */
export function warningLabel(code: string): string {
  if (WARNING_LABEL[code]) return WARNING_LABEL[code];
  // 자기검증 축은 `scope_expanded#3` 처럼 씬 번호를 `#` 로 붙인다 — 그것도 접두로 찾는다.
  const hash = code.indexOf("#");
  if (hash > 0 && WARNING_LABEL[code.slice(0, hash)]) {
    return `${WARNING_LABEL[code.slice(0, hash)]} (씬 ${code.slice(hash + 1)})`;
  }
  const [head, detail] = code.split(":", 2);
  if (WARNING_LABEL[head]) return decorate(WARNING_LABEL[head], detail);
  if (BLOCK_LABEL[head]) return decorate(BLOCK_LABEL[head], detail);
  return code;
}
