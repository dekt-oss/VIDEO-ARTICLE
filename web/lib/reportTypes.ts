// 리포트 팩토리(하루 한 리포트) 도메인 타입. 논문 공장의 lib/types.ts 를 report 로 미러링.

export type ReportSortMode = "interest" | "story" | "safety";

export const REPORT_SORT_LABELS: Record<ReportSortMode, string> = {
  interest: "관심순",
  story: "스토리순",
  safety: "안전순",
};

export type ReportDecisionStatus = "shortlisted" | "picked" | "rejected";

// ③ 오늘의 후보(종목/테마 카드) — daily_batch + reports + report_scores + report_decisions 조합.
export interface ReportCandidate {
  report_id: string;
  external_id: string;
  title: string;
  title_ko: string | null;
  theme: string | null;
  company: string | null;
  ticker: string | null;
  broker: string | null;
  target_price: number | null;
  opinion: string | null;
  report_url: string | null;
  signal_level: string | null; // HIGH | MID | LOW
  is_risk: boolean;
  aria_priority: number | null; // ARIA 신호 강도(정렬 보정)
  one_liner_ko: string | null;
  angle: string | null; // 대중용 핵심 앵글 한 줄
  risk_note: string | null; // 컴플라이언스/편향 주의점
  interest_index: number | null;
  story_index: number | null;
  safety_index: number | null;
  timeliness: number | null;
  story: number | null;
  safety: number | null;
  rank: number;
  sort_mode: ReportSortMode;
  decision_status: ReportDecisionStatus | null;
  is_new: boolean; // 직전 배치엔 없던, 이번 배치에 새로 등장
}

// ── PF1: 초안 + 컴플라이언스 (논문 lib/types.ts P1 미러) ──

export interface ReportSource {
  broker: string;
  analyst: string;
  company: string;
  opinion: string;
  target_price: number | null;
  url: string;
  disclaimer: string;
}

export interface ReportFactSheet {
  company: string;
  what: string[];
  numbers: string[];
  opinion: string;
  basis: string[];
  risks: string[];
  source?: Partial<ReportSource> | string;
}

export interface ReportScene {
  scene: number;
  title?: string;
  narration_ko: string;
  narration_en: string;
  duration_sec: number;
  image_prompt?: string;
  image_prompt_ko?: string;
  video_prompt?: string;
  video_prompt_ko?: string;
  source_facts: string[];
}

export interface ReportSelfCheckScene {
  scene: number;
  grounded: boolean;
  /** v3 §5-4 — 근거 대조 **면제** 씬(훅·질문·마무리). "검사해서 통과"와 구분해 보여준다.
   *  구버전 행에는 없으므로 optional. */
  exempt?: boolean;
  unsupported: string[];
  matched_facts: string[];
}
export interface ReportSelfCheck {
  scenes: ReportSelfCheckScene[];
  all_grounded: boolean;
}

// 🆕 컴플라이언스 게이트 결과 — CompliancePanel 이 렌더, blocked 로 승인 잠금.
export interface ComplianceRuleFlag {
  category: string; // 투자권유 | 미실현수익률 | 단정예측 | 출처누락 | 면책누락 | 과열소재
  severity: "block" | "warn";
  hit: string;
}
export interface ComplianceVerdict {
  권유: "yes" | "no";
  수익률광고: "yes" | "no";
  단정: "yes" | "no";
  출처: "ok" | "missing";
  면책: "ok" | "missing";
  근거: string;
}
export interface ComplianceHallucinationFlag {
  scene: number | null;
  unsupported: string[];
}
export interface ReportCompliance {
  rule_flags: ComplianceRuleFlag[];
  llm_verdict: ComplianceVerdict | null;
  hallucination_flags: ComplianceHallucinationFlag[];
  blocked: boolean;
}

export interface ReportDraft {
  report_id: string;
  /** 마지막 검증(초안 생성·재검사)을 통과한 대본의 지문. 없으면 옛 초안(경고하지 않는다). */
  validated_script_hash?: string | null;
  fact_sheet: ReportFactSheet | null;
  upload_title_ko: string | null;
  upload_title_en: string | null;
  script_md: string | null;
  scenes: ReportScene[] | null;
  self_check: ReportSelfCheck | null;
  compliance: ReportCompliance | null;
  // v3 §5·§6 — 근거 게이트와 논증 설계. 워커가 채운다(엣지 초안은 null).
  story_plan: ReportStoryPlan | null;
  evidence: ReportEvidence | null;
  /** 마지막 수정 시각(0046 트리거). 지시서 created_at 보다 뒤면 그 지시서는 옛 대본 기준이다. */
  updated_at?: string | null;
}

/** §6 논증 설계 — 대본 출력의 필드(독립 스테이지 아님). */
export interface ReportStoryPlan {
  thesis: string;
  content_profile: string;
  audience_question: string;
  claim_chain: { order: number; role: string; claim: string; evidence_refs: string[] }[];
  excluded_evidence: { evidence_ref: string; reason: string }[];
}

/** §5 근거 게이트 결과. blocked 는 하드 차단 스위치가 켜졌을 때만 true. */
export interface ReportEvidence {
  content_profile: string;
  source_depth: string;
  block_reasons: string[];
  warnings: string[];
  story_warnings: string[];
  density_warnings: string[];
  blocked: boolean;
}

export interface PickedReport {
  report_id: string;
  title: string;
  title_ko: string | null;
  external_id: string;
  company: string | null;
  theme: string | null;
  has_draft: boolean;
  blocked: boolean | null; // 컴플라이언스 차단 여부(초안 있을 때)
  request_status: string | null; // queued | processing | done | error | null
  decided_at: string | null;
}

export interface ReportDraftListItem {
  report_id: string;
  title: string;
  title_ko: string | null;
  created_at: string;
  published: boolean;
  blocked: boolean;
}

export interface PublishedReport {
  report_id: string;
  title: string;
  published_at: string;
}

// ⑥ 리포트 렌더 잡 (논문 RenderJob 미러 — 유튜브 업로드 필드 포함)
export type ReportRenderStatus =
  | "queued" | "assets" | "tts" | "assembling"
  // 사람이 봐야 끝나는 상태(§8-3) — lib/renderStatus.ts 참조.
  | "qa_pending" | "degraded"
  | "done" | "failed";

export interface ReportRenderJob {
  id: string;
  directive_id: string;
  lang?: string;
  status: ReportRenderStatus;
  progress: number;
  cost_estimate: number;
  output_url: string | null;
  error_log: string | null;
  created_at: string;
  finished_at: string | null;
  deleted_at: string | null;
  saved_at: string | null;
  /** degraded 영상을 사람이 확인하고 발행을 승인한 시각(0037).
   *  null 이면 미승인 — 업로드 라우트가 막는다. status 를 덮지 않으므로
   *  "결함이 있었는데 승인했다"는 사실이 발행 후에도 기록에 남는다. */
  degraded_approved_at?: string | null;
  // 조인으로 채우는 표시용
  report_id?: string;
  title?: string;
  title_ko?: string | null;
  /** report_directives 조인. report_render_jobs 에 버전 컬럼이 없어 여기서 채운다 —
   *  없으면 ⑥ 화면의 버전 뱃지가 전부 "?" 로 떠서 만화식·설명판형을 구분할 수 없다. */
  version_type?: string;
  // report_upload_requests 조인(유튜브 업로드 상태)
  youtube_status?: "queued" | "processing" | "done" | "error" | null;
  youtube_url?: string | null;
  youtube_error?: string | null;
}

// ① 수집 원자료(raw)
export interface RawReport {
  report_id: string;
  external_id: string;
  title: string;
  theme: string | null;
  company: string | null;
  broker: string | null;
  signal_level: string | null;
  aria_priority: number | null;
  is_risk: boolean;
  report_url: string | null;
  scored: boolean;
}

// ② 채점 결과 (4축)
export interface ScoredReport {
  report_id: string;
  title: string;
  title_ko: string | null;
  theme: string | null;
  company: string | null;
  timeliness: number | null;
  explainability: number | null;
  story: number | null;
  safety: number | null;
  interest_index: number | null;
  story_index: number | null;
  safety_index: number | null;
  angle: string | null;
  risk_note: string | null;
  in_batch: boolean;
  decision_status: ReportDecisionStatus | null;
}
