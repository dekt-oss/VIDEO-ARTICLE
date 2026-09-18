// 대시보드에서 쓰는 도메인 타입.

export type SortMode = "fun" | "importance" | "golden";

export interface Candidate {
  paper_id: string;
  external_id: string;
  title: string;
  title_ko: string | null;
  url: string | null;
  venue: string | null;
  one_liner_ko: string | null;
  one_liner_en: string | null;
  fun_index: number | null;
  importance_index: number | null;
  red_flag: string | null;
  rank: number;
  sort_mode: SortMode;
  decision_status: "shortlisted" | "picked" | "rejected" | null;
  is_new: boolean; // 직전 배치엔 없던, 이번 배치에 새로 등장한 논문
}

export type DecisionStatus = "shortlisted" | "picked" | "rejected";

export interface FactSheetSource {
  title: string;
  venue: string;
  year: string;
  authors: string[];
  institutions: string[];
  url: string;
}

export interface FactSheet {
  what_found: string[];
  how: string[];
  numbers: string[];
  limitations: string[];
  claim_strength: string;
  source?: Partial<FactSheetSource>; // 출처 블록(구체화·발행 캡션 근거). 재생성 후 존재
  claims?: Claim[]; // Claim Ledger(수정명세 §4). 원장 없는 과거 초안은 undefined
}

// ── 근거밀도·가변길이 개정 (docs/수정명세서_근거밀도_가변길이_v1.md) ──
// 전부 optional — 이 개정 이전 데이터가 그대로 렌더된다.
export type ClaimKind =
  | "main_result" | "method" | "scope" | "number" | "mechanism"
  | "moderator" | "subgroup" | "limitation" | "author_interpretation" | "background";
export type CausalStrength =
  | "descriptive" | "association_only" | "quasi_causal" | "causal" | "projection" | "speculation";
export type EvidenceGrade = "A" | "B" | "C" | "D";
export type EffectDirection = "increase" | "decrease" | "no_change" | "mixed" | "unspecified";
export type EvidenceRole =
  | "primary_result" | "scope" | "method" | "magnitude" | "mechanism"
  | "moderator" | "caveat" | "implication" | "connective" | "cta";
export type EvidenceDelivery = "spoken" | "visual" | "both" | "caption" | "omit";
export type ContentMode = "flash" | "standard" | "deep" | "extended" | "series_split";
export type MotionValue = "high" | "medium" | "low";
export type AssetStrategy =
  | "new_asset" | "reuse_crop" | "reuse_zoom" | "reuse_with_state_change"
  | "reuse_background_new_overlay" | "code_viz" | "text_only_transition";
export type Tristate = "pass" | "fail" | "not_applicable";
export type OverlayType =
  | "source_card" | "evidence_card" | "number_punch" | "caveat_tag" | "scope_tag"
  // 2026-09-18 기전 교육력: 색 범례 · 상하 분할 화면 캡션(engine/config.py OVERLAY_TYPES 미러)
  | "legend" | "label_pair"
  | "before_after" | "group_compare" | "timeline" | "mechanism_steps";

/** 화면으로 증명하는 근거 카드 1건. 자막과 같은 ASS 레이어에 얹혀 언어별로 렌더된다. */
export interface OverlayItem {
  type: OverlayType;
  text: string;
  /** legend: {items:[{color,label}]} · label_pair: {top,bottom}. 다른 유형은 없음. */
  payload?: Record<string, unknown>;
  claim_ids: string[];
  start_sec: number;
  duration_sec: number;
  priority: string;
}

/** 구조화 주장 1건. 확인되지 않은 값은 null(빈 문자열 아님 — "확인됨"으로 오독 방지). */
export interface Claim {
  claim_id: string;
  claim_kind: ClaimKind;
  claim_ko: string;
  population: string | null;
  sample_size: string | null;
  geography: string | null;
  study_period: string | null;
  study_design: string | null;
  treatment_or_exposure: string | null;
  comparison: string | null;
  outcome: string | null;
  outcome_definition: string | null;
  effect_direction: EffectDirection;
  effect_size: string | null;
  effect_unit: string | null;
  uncertainty: string | null;
  statistical_significance: string | null;
  causal_strength: CausalStrength;
  source_section: string;
  source_page: number | null;
  table_or_figure: string | null;
  source_quote: string | null;
  limitations: string[];
  evidence_grade: EvidenceGrade;
  missing_fields: string[]; // 코드가 재계산(LLM 신고값 아님)
}

/** 무엇을 몇 초에 담을지의 계획. 길이는 코드가 모드에서 재유도한다. */
export interface ContentPlan {
  primary_claim_id: string;
  supporting_claim_ids: string[];
  essential_evidence_units: string[];
  evidence_delivery?: Record<string, EvidenceDelivery>;
  complexity: string;
  visualizability: string;
  compression_risk: string;
  selected_mode: ContentMode;
  target_duration_min_sec: number;
  target_duration_max_sec: number;
  duration_reason: string;
  series_split_reason?: string;
  spoken_number_count?: number;
  mode_warnings: string[];
}

/** 훅 후보. eligible·disqualify_reasons 는 코드가 판정한다(§8-2 즉시탈락). */
export interface HookCandidate {
  hook_id: string;
  text_ko: string;
  angle: HookAngle;
  claim_ids: string[];
  scope_preserved: boolean;
  causal_calibrated: boolean;
  promise: string;
  risk: string;
  eligible: boolean;
  disqualify_reasons: string[];
}

export interface EvidenceCoverage {
  required_claim_ids: string[];
  spoken_claim_ids: string[];
  visual_claim_ids: string[];
  missing_claim_ids: string[];
  primary_claim_covered: boolean;
  scope_present?: boolean;
  method_present?: boolean;
  magnitude_present?: boolean;
  caveat_present?: boolean;
}

export interface RetentionPlan {
  novelty_interval_max_sec: number;
  payoff_start_ratio: number;
  open_loop: string;
  pattern_interrupt_cut_nos: number[];
}

/** 모드 예산(상한) + 이 지시서의 실사용량·예상 생성비. 전부 컷에서 코드가 계산한다. */
export interface CostPlan {
  content_mode: ContentMode;
  max_unique_assets: number;
  max_video_clips: number;
  max_video_generated_sec: number;
  max_video_cost_usd: number;
  preferred_code_viz_count?: number;
  asset_reuse_target?: number;
  cost_priority?: string;
  unique_asset_count: number;
  reuse_count: number;
  asset_reuse_ratio: number;
  code_viz_count: number;
  video_clip_count: number;
  video_generated_sec: number;
  estimated_image_cost_usd: number;
  estimated_video_cost_usd: number;
  estimated_total_generation_cost_usd: number;
  /** 장면별 내역(시퀀스 등급제 v2). 등급제 적용 버전에서만 채워진다. */
  sequences?: SequenceCostLine[];
  /** 등급 분포. 총액만으로는 "어디에 투자했는지"를 못 본다. */
  tiers?: Record<string, number>;
  /** 시퀀스가 없어 기본 등급으로 채운 컷 수 — 판정한 것과 구분한다. */
  tier_defaulted?: number;
}

/** ⑤ 확인 모달의 장면별 표 한 줄. 숫자는 전부 엔진(compute_cost_plan)이 계산한 값이다. */
export interface SequenceCostLine {
  sequence_id: string;
  role: string;
  tier: string;              // invest | standard | economy
  cuts: number;
  clips: number;             // 후보를 포함한 실제 생성 횟수
  video_sec: number;
  candidates: number;
  est_usd: number;
  tier_defaulted_count: number;
}

export interface Scene {
  scene: number;
  title?: string;
  narration_ko: string;
  narration_en: string;
  duration_sec: number;
  image_prompt?: string;        // 텍스트→이미지(스틸, 영문)
  image_prompt_ko?: string;     // 이미지 프롬프트 한국어 설명
  video_prompt?: string;        // 이미지→영상(모션, 영문)
  video_prompt_ko?: string;     // 영상 프롬프트 한국어 설명
  visual_prompt?: string;       // 레거시 구 초안 — video_prompt 폴백
  source_facts: string[];
  claim_ids?: string[];             // 이 씬이 지불하는 주장(원장에 있는 id 만)
  evidence_role?: EvidenceRole;
  evidence_delivery?: EvidenceDelivery;
}

export interface VideoFlowBeat {
  order: number;
  label: string;
  summary: string;
  transition: string;
}

export interface VideoFlow {
  logline: string;
  total_duration_sec: number;
  beats: VideoFlowBeat[];
  // 계획·훅은 여기 얹혀 있다(drafts 에 빈 컬럼이 없어 마이그레이션을 늘리지 않았다).
  content_plan?: ContentPlan;
  hook_candidates?: HookCandidate[];
  selected_hook_id?: string;
}

export interface SelfCheckScene {
  scene: number;
  grounded: boolean;
  unsupported: string[];
  matched_facts: string[];
  // 자기검증 v2(§14) — 범위·인과·숫자·수식어·편집적추론. 전부 LLM 판단이라 **경고**로만 쓴다.
  matched_claim_ids?: string[];
  scope_match?: boolean;
  causal_calibration?: Tristate;
  numeric_match?: Tristate;
  qualifier_preserved?: boolean;
  editorial_inference?: boolean;
  // 한국어 문장 축(2026-09-10). 사실 축과 섞이지 않는다 — 승인·커버리지에 안 닿고 경고뿐이다.
  korean_natural?: boolean;
  awkward_spans?: string[];
  fluency_issues?: string[];
  issues?: string[];
}

/** 대본 다듬기 결과(engine/script_polish). rejected 는 사실이 흔들려 코드가 되돌린 씬이다. */
export interface KoreanPolish {
  ran: boolean;
  reason?: string;
  targets?: number[];
  applied?: number[];
  rejected?: { scene: number; reason: string }[];
  unchanged?: number[];
  script_md_synced?: number;
}

export interface SelfCheck {
  scenes: SelfCheckScene[];
  all_grounded: boolean;
  coverage?: EvidenceCoverage;
  /** 코드가 데이터로 확정한 차단 사유만 담긴다(LLM 판단 축은 warnings 로). */
  block_reasons?: string[];
  warnings?: string[];
  approval_blocked?: boolean;
  korean_polish?: KoreanPolish;
}

export interface Draft {
  paper_id: string;
  fact_sheet: FactSheet | null;
  upload_title_ko: string | null; // 유튜브 업로드용 자극적 제목(한)
  upload_title_en: string | null; // 유튜브 업로드용 자극적 제목(영)
  script_md: string | null;
  video_flow: VideoFlow | null;
  video_prompts: Scene[] | null;
  self_check: SelfCheck | null;
  /** 마지막 수정 시각(0046 트리거). 지시서 created_at 보다 뒤면 그 지시서는 옛 대본 기준이다. */
  updated_at?: string | null;
}

export interface PickedPaper {
  paper_id: string;
  title: string;
  title_ko: string | null;
  external_id: string;
  has_draft: boolean;
  request_status: string | null; // queued | processing | done | error | null
  decided_at: string | null; // 낙점 시각(timestamptz). 일자별 그룹핑에 사용
}

export interface PublishedItem {
  paper_id: string;
  title: string;
  published_at: string;
}

// ⑤ 영상 지시서 (P-V0, 명세 §4)
export type VersionType =
  // editorial 은 2026-07-28 폐기(docs/deviation-webtoon-b1-removal.md). 저장된 옛 행이 있어 타입에는 남긴다.
  // explainer(설명판형)·photo(실사형)는 금융 리포트 라인 전용.
  | "comic" | "webtoon" | "image_sequence" | "explainer" | "photo"
  | "editorial" | "animation" | "hybrid";
export type DirectiveStatus =
  | "draft"
  | "approved"
  | "rendering"
  | "rendered"
  | "failed";

export interface DirectiveBgm {
  mood: string;
  track_ref: string;
}

// ③ 시각 다양성 래더(규격 v2 §2.2) — 컷별 씬 종류.
export type SceneKind =
  | "comic_panel"
  | "motion_graphic"
  | "kinetic_typography"
  | "data_viz"
  | "broll_stock";

// 훅·리텐션 개정 v2 — 훅 유형/앵글/CTA/근거강도 통제 어휘.
export type HookType = "H1" | "H2" | "H3" | "H4";
export type HookAngle =
  | "personal_cost" | "competition" | "daily_life" | "risk" | "counterintuition"
  | "mechanism" | "future_impact" | "human_scale" | "scientific_wonder";
export type CtaType =
  | "none" | "comment_question" | "save_prompt" | "subscribe_series" | "next_episode_bridge";

export interface HookPromiseCheck {
  pass: boolean;
  promise: string;
  payoff_cut_no: number[];
  reason: string;
}
export interface ScienceReliability {
  claim_type: "measured_result" | "author_interpretation" | "model_projection" | "speculation";
  evidence_strength: "high" | "medium" | "low";
  generalization_risk: "low" | "medium" | "high";
  required_caveat: string;
}

// ── 설명판형 explainer (개선명세 v3.3) — 금융 리포트 라인 전용 ──
// 값은 전부 engine/explainer.py 가 정규화·계산한다(웹은 표시만 한다).
export type ExplainerProfile = "NUMERIC" | "MECHANISM" | "EVENT";
export type ExplainerSourceMode = "FULL_REPORT" | "PARTIAL_REPORT" | "NEWS_ONLY";
export type ExplainerBoard =
  | "HOOK_BOARD" | "CLAIM_BOARD" | "NUMBER_BOARD" | "CHART_BOARD" | "EVIDENCE_BOARD"
  | "REPORT_REASON_BOARD" | "MECHANISM_BOARD" | "VALUATION_BOARD" | "COMPARISON_BOARD"
  | "WATCHPOINT_BOARD" | "CONTEXT_BOARD";
export type ExplainerBeatRole =
  | "HOOK" | "QUESTION" | "CLAIM" | "EVIDENCE" | "MECHANISM" | "RISK" | "WATCHPOINT";

/** §4-3 "누가 · 무엇을 근거로 · 무엇을 전망했다" 한 문장. 영상의 중심축. */
export interface ReportClaimSummary {
  speaker: string;
  statement: string;
  fact_refs: string[];
  page_refs: number[];
}

/** §6-1 숫자 주장. big_number_ok=false 면 대형 숫자 보드의 주인공으로 쓸 수 없다(§6-2). */
export interface NumberClaim {
  claim_no: number;
  value: string;
  unit: string;
  label: string;
  comparison_basis: string;
  comparison_value: string;
  why_significant: string;
  fact_refs: string[];
  page_refs: number[];
  qualifier_count: number;
  big_number_ok: boolean;
}

export interface ExplainerGate {
  /** 차단 사유(§9-1 Source Gate). 비어 있지 않으면 승인이 잠긴다. */
  block_reasons: string[];
  /** 깊이·시각 경고(§9-2·§9-3). 승인은 막지 않는다. */
  warnings: string[];
  blocked: boolean;
}

export interface ExplainerBlock {
  profile: ExplainerProfile;
  source_mode: ExplainerSourceMode;
  report_claim_summary: ReportClaimSummary;
  number_claims: NumberClaim[];
  insight_nuggets: string[];
  watchpoint: { text: string; metric: string };
  evidence_requirements: { min_evidence_boards: number; show_report_source_explicitly: boolean };
  board_counts: Record<string, number>;
  beat_counts: Record<string, number>;
  gate: ExplainerGate;
}

export interface DirectiveHeader {
  version_type: VersionType;
  aspect_ratio: string; // "9:16" | "16:9"
  global_style: string; // 전 컷 일관성 기준(화풍/톤 앵커)
  hook_ko?: string; // ⑤ 훅 트랜스크리에이션(언어별 독립, 직역 금지)
  hook_en?: string;
  cta_ko?: string;
  cta_en?: string;
  bgm: DirectiveBgm;
  total_estimated_sec: number;
  // 훅·리텐션 개정 v2(§4·§5) — 승인 화면에서 정합/근거강도를 배지로 검증.
  hook_type?: HookType;
  hook_reframe_angle?: HookAngle;
  hook_promise_check?: HookPromiseCheck;
  science_reliability?: ScienceReliability;
  cta_type?: CtaType;
  loop_match?: boolean;
  series_id?: string;
  // ── 근거밀도·가변길이 개정(수정명세 §4-4) ──
  content_mode?: ContentMode;
  primary_claim_id?: string;
  supporting_claim_ids?: string[];
  essential_evidence_units?: string[];
  target_duration_min_sec?: number;
  target_duration_max_sec?: number;
  duration_reason?: string;
  evidence_coverage?: EvidenceCoverage;
  retention_plan?: RetentionPlan;
  cost_plan?: CostPlan;
  mode_warnings?: string[];
  /** 코드가 데이터로 확정한 차단 사유만(길이·예산·커버리지). 승인 라우트가 서버에서 재검증한다. */
  block_reasons?: string[];
  approval_blocked?: boolean;
  media_policy?: string;
  /** 설명판형 전용(v3.3). version_type='explainer' 인 지시서에만 있다. */
  explainer?: ExplainerBlock;
  /** 렌더 워커가 하단 면책 자막 출처에 쓰는 증권사명(리포트 라인). */
  broker?: string;
}

export interface Cut {
  cut_no: number;
  scene_kind?: SceneKind; // ③ 다양성 래더(고효율=코드 클립, 그 외=스틸)
  narration_ko: string;
  narration_en: string;
  estimated_sec: number;
  visual_type: string; // comic_panel | image | animation (레거시, 버전에서 강제)
  visual_prompt: string;
  motion_prompt?: string; // 명세 §3-2: motion_source=video 컷의 모션 전용(Veo 프롬프트 합류). still 컷은 빈값
  style_anchor_ref: string;
  effects: string[]; // 통제 어휘 enum 토큰만
  transition: string; // cut | crossfade
  bgm_cue: string;
  source_facts: string[]; // 근거 매핑(환각 방지). 비면 승인 화면에 빨간 표시
  render_notes: string;
  motion_source?: "video" | "still"; // hybrid 버전: 이 컷을 I2V 영상(video)/스틸(still)로. 그 외 항상 still
  /** 실사형: 이 컷이 화면에서 하는 일. 승인 게이트가 검사한다(engine/photo_contract.py). */
  visual_role?: "MECHANISM" | "REALITY" | "";
  /** 실사형 MECHANISM 컷의 도해 구조. 없으면 승인이 막힌다(§5). */
  mechanism?: {
    subject?: string;
    components?: string[];
    relationship?: string;
    initial_state?: string;
    transformation?: string;
    final_state?: string;
    highlighted_element?: string;
    claim_ids?: string[];
  };
  loop_safe?: boolean;
  // ── 근거밀도·가변길이 개정(수정명세 §4-4) ──
  claim_ids?: string[];
  evidence_role?: EvidenceRole;
  novelty_event?: string;
  motion_value?: MotionValue;   // high 인 컷만 I2V 로 살아남는다
  asset_strategy?: AssetStrategy;
  visual_reuse_group?: string;
  base_asset_ref?: string;
  state_change?: string;
  overlay_plan?: OverlayItem[];
  // ── 설명판형(v3.3 §5·§7) — explainer 컷에만 붙는다 ──
  /** 이 컷이 어떤 설명판인가. 렌더 scene_kind 를 결정한다. */
  board?: ExplainerBoard;
  /** 길이를 초가 아니라 비트로 관리하기 위한 역할(§7-2). */
  beat_role?: ExplainerBeatRole;
  /** 이 컷이 화면에 쓰는 number_claims 의 1-based 번호. */
  number_claim_refs?: number[];
  // ── 장면 파생(웹툰 v1 §2) — 재사용 컷에서만 의미가 있다 ──
  // crop: 기준 컷 이미지에서 잘라낼 영역(비율 0~1 + 확대 배율). 렌더가 픽셀로 환산한다.
  crop?: CutCrop | null;
  tone_grade?: ToneGrade;
}

// 크롭 파생 — 카메라 이동을 이미지 생성이 아니라 잘라내기로 만든다. 생성 호출 0.
export interface CutCrop {
  cx: number;    // 0~1 가로 중심
  cy: number;    // 0~1 세로 중심
  scale: number; // 확대 배율(1.0 = 전체)
}

// 톤 그레이딩 — 시간·감정 변화만 필요한 컷에 새 이미지 대신 색을 입힌다.
export type ToneGrade = "none" | "warm" | "red" | "cool" | "desaturate";

export interface Directive {
  id: string;
  paper_id: string;
  version_type: VersionType;
  header: DirectiveHeader | null;
  cuts: Cut[];
  status: DirectiveStatus;
  created_at: string;
  approved_at: string | null;
}

// ⑥ 렌더 결과 (P-V1)
export type RenderStatus =
  | "queued"
  | "assets"
  | "tts"
  | "assembling"
  // 사람이 봐야 끝나는 상태(§8-3). 워치독이 건드리지 않는다 — lib/renderStatus.ts 참조.
  | "qa_pending"   // QA 판정 대기·경고 있음
  | "degraded"     // important 레이어 누락 — 승인해야 발행 가능
  | "done"
  | "failed";

// §7 렌더 QA — engine/render_qa.py evaluate_qa 결과.
export interface RenderQa {
  passed: boolean;
  hard_fail: string[];
  warnings: string[];
  signals?: Record<string, unknown>;
  // 길이 보정 QA(수정명세 v1 §3-6). 컷별 전략 선택이 사후 검증 가능하도록 렌더가 남긴다.
  // flags/warnings 는 위 warnings 에도 합쳐지므로 UI 는 별도 배선 없이도 경고를 본다.
  clip_fit?: {
    strategy_counts: Record<string, number>;
    flags: string[];
    warnings: string[];
    cuts: {
      cut_no: number;
      clip_sec: number;
      narration_sec: number;
      ratio: number;
      loop_safe: boolean;
      strategy: string;
      note?: string;
    }[];
  } | null;
}

export interface RenderJob {
  id: string;
  directive_id: string;
  status: RenderStatus;
  lang?: string; // ⑤ 렌더 언어(ko | en). 이중언어 운영 — 잡별 산출 언어
  source_job_id?: string | null; // 언어 추가 렌더 계보(수정명세 v1 §2) — 어느 잡에서 파생됐는지
  progress: number;
  cost_estimate: number;
  output_url: string | null;
  error_log: string | null;
  created_at: string;
  finished_at: string | null;
  deleted_at: string | null; // 휴지통(soft delete). null 이면 활성
  saved_at: string | null; // 보관(keep/pin). null 이면 미보관
  /** degraded 영상을 사람이 확인하고 발행을 승인한 시각(0037).
   *  null 이면 미승인 — 업로드 라우트가 막는다. status 를 덮지 않으므로
   *  "결함이 있었는데 승인했다"는 사실이 발행 후에도 기록에 남는다. */
  degraded_approved_at?: string | null;
  qa?: RenderQa | null; // §7 렌더 QA 결과(발행 전 실검). null 이면 미검(구 잡)
  // 조인으로 채우는 표시용 필드
  paper_id?: string;
  title?: string;
  title_ko?: string | null; // 한글 제목(scores.title_ko) — 렌더 결과 한/영 동시 표시
  version_type?: VersionType;
  // 발행용(유튜브 업로드) 복붙 필드 — 렌더결과에서 제목·설명란을 바로 복사(joinRenderMeta 조립).
  upload_title_ko?: string | null;
  upload_title_en?: string | null;
  caption_ko?: string; // buildPublishCaption 로 서버 조립한 설명란(한)
  caption_en?: string; // buildPublishCaption 로 서버 조립한 설명란(영)
  // 유튜브 업로드 상태(upload_requests 조인). 없으면 미요청.
  youtube_status?: "queued" | "processing" | "done" | "error" | null;
  youtube_url?: string | null;
  youtube_error?: string | null;
}

// 생성 완료된 초안(승인 전 포함) — 아카이브 조회용
export interface DraftListItem {
  paper_id: string;
  title: string;
  title_ko: string | null;
  created_at: string;
  published: boolean;
}

// ① 수집 원자료(raw)
export interface RawPaper {
  paper_id: string;
  external_id: string;
  title: string;
  venue: string | null;
  published_date: string | null;
  lang: string | null;
  url: string | null;
  buzz_total: number;
  scored: boolean;
}

// ② 분류(채점) 결과
export interface ScoredPaper {
  paper_id: string;
  title: string;
  title_ko: string | null;
  venue: string | null;
  url: string | null;
  surprise: number | null;
  explainability: number | null;
  relatability: number | null;
  significance: number | null;
  buzz: number | null;
  fun_index: number | null;
  importance_index: number | null;
  one_liner_ko: string | null;
  red_flag: string | null;
  production_gate: string | null; // §6 제작 게이트: make|redesign|backlog|hold (미채점 시 null)
  production_max: number; // 그 행이 매겨진 만점(옛 행 10 / mechanism 축 이후 12)
  production_total: number | null; // §6 제작 준비도 총점(0~10)
  in_batch: boolean;
  decision_status: DecisionStatus | null;
}
