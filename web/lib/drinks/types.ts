// 주류 공장 표의 행 모양(0050_drinks_factory_phase_a.sql). 타입만 — 값 없음.
import type { Category, Format, Lane, Scores, TopicStatus, VersionStatus } from "./model";

export interface TopicRow {
  id: string;
  title: string;
  question: string;
  reader_value: string | null;
  categories: Category[];
  lane: Lane;
  target_subject: string | null;
  angle: string | null;
  dedupe_key: string;
  reader_signal_count: number;
  status: TopicStatus;
  provisional_scores: Scores | null;
  provisional_score: number | string | null;
  provisional_rubric: string | null;
  current_review_id: string | null;
  approved_review_id: string | null;
  selected_review_id: string | null;
  selected_formats: Format[] | null;
  editorial_week: string | null;
  score_exception_reason: string | null;
  format_exception_reasons: Partial<Record<Format, string>> | null;
  decision_reason_code: string | null;
  decision_reason: string | null;
  hold_until: string | null;
  canonical_topic_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SnapshotRow {
  id: string;
  url_raw?: string | null;
  canonical_url: string | null;
  title?: string | null;
  publisher?: string | null;
  source_kind: string;
  depth: "metadata_only" | "excerpt" | "full_text";
  body_text?: string | null;
  excerpt_locator?: string | null;
  content_hash?: string | null;
  original_language?: string | null;
  published_at: string | null;
  checked_at?: string | null;
  rights_status?: string;
  usage_terms?: string | null;
  origin_group: string | null;
  supersedes_id?: string | null;
  created_at?: string;
  /** loadBoard 가 붙이는 연결 역할 */
  role?: "discovery" | "evidence";
}

export interface TopicSourceRow {
  topic_id: string;
  snapshot_id: string;
  role: "discovery" | "evidence";
  relation_note: string | null;
  created_at: string;
}

export interface SourceRef {
  snapshot_id: string;
  locator: string | null;
  original_quote: string | null;
  translation: string | null;
  quote_check: "matched" | "unmatched" | "not_checked";
}

export interface Claim {
  claim_id: string;
  text: string;
  claim_type: "product_fact" | "process" | "comparison" | "opinion";
  attribution: string | null;
  scope: { product: string | null; region: string | null; lot: string | null; time: string | null };
  source_refs: SourceRef[];
  support_review: "supported" | "conflicting" | "insufficient" | "not_reviewed" | "not_applicable";
  limitations: string | null;
  time_sensitive: boolean;
  valid_until: string | null;
}

export interface Brief {
  audience_question: string | null;
  core_takeaway: string | null;
  selected_claim_ids: string[];
  exclusions: string | null;
  useful_action: string | null;
  proposed_formats: Format[];
  /** 형식별로 반드시 전달할 핵심 주장(승인과 함께 고정) */
  required_claims: Partial<Record<Format, string[]>>;
  followup_question: string | null;
}

export interface Readiness {
  blockers: string[];
  warnings: string[];
  /** 승인 시점에 근거로 쓴 출처의 사용 조건·마지막 정정 기록 */
  source_state?: Record<string, { rights: string; attestation: string | null }>;
  checked_at?: string;
}

export interface AttestationRow {
  id: string;
  snapshot_id: string;
  topic_id: string | null;
  kind: "rights_confirmed" | "recheck" | "correction" | "rights_revoked";
  fields: Record<string, string | null>;
  reason: string | null;
  impact: { topics?: { id: string; title: string }[]; approved_reviews?: unknown[]; plans?: unknown[] };
  /** 적용 순서(스냅샷 잠금 안에서 매긴 순번) */
  seq: number | string;
  created_at: string;
}

export interface ReviewRow {
  id: string;
  topic_id: string;
  revision_no: number;
  based_on_review_id: string | null;
  rubric_version: string;
  scores: Scores;
  score: number | string | null;
  evidence_pack: { claims: Claim[] };
  brief: Partial<Brief>;
  readiness: Readiness;
  input_hash: string;
  status: VersionStatus;
  submitted_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  approved_hash: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  /** drink_review_validity 에서 붙인다 — 승인 기록과 별개로 "지금 쓸 수 있는가"(정정 기록·유효 기한 반영) */
  current_blockers?: string[];
  currently_valid?: boolean;
}

export interface ValidityRow {
  review_id: string;
  topic_id: string;
  current_blockers: string[];
  currently_valid: boolean;
}

export interface DeliverableRow {
  id: string;
  topic_id: string;
  format: Format;
  locale: string;
  current_revision_id: string | null;
  archived_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface VideoScene {
  position?: number;
  narration: string;
  visual_role: "reality" | "mechanism" | "text_card" | "other";
  /** fact=사실 설명(주장 연결 필수) / transition=도입·전환·마무리 */
  content_kind?: "fact" | "transition";
  explanation: string | null;
  claim_ids: string[];
  timing_sec: number | null;
  continuity: string | null;
  overlays: string | null;
}

export interface CarouselPage {
  position: number;
  role: "cover" | "explain" | "compare" | "checklist" | "source";
  heading: string;
  body: string | null;
  graphic_spec: string | null;
  claim_ids: string[];
}

export interface PlanRow {
  id: string;
  deliverable_id: string;
  topic_id: string;
  format: Format;
  revision_no: number;
  topic_review_id: string;
  plan_json: { scenes?: VideoScene[]; pages?: CarouselPage[]; notes?: string | null; template_version?: string };
  visual_profile: string | null;
  brand_profile_version: string | null;
  schema_version: string;
  aspect_ratio: string;
  input_hash: string;
  plan_status: VersionStatus;
  submitted_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  approved_hash: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  blocked_at: string | null;
  blocked_reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface EventRow {
  id: number;
  topic_id: string | null;
  entity_type: string;
  entity_id: string;
  action: string;
  actor: string;
  before_status: string | null;
  after_status: string | null;
  version_ref: string | null;
  reason: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}
