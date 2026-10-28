// 주류 발행·성과(0055) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 두 화면이 각각 DB 함수 하나(drinks_publish_board / drinks_analytics_board)로 읽는다 — 상한을 넘으면 truncated.
import { createAdminClient } from "@/lib/supabase/admin";
import { fromQuery, type Loaded } from "@/lib/drinks/model";

export type PubStatus = "draft" | "awaiting_approval" | "approved" | "scheduled" | "publishing" | "published" | "failed"
  | "unknown" | "paused" | "canceled";

export const PUB_STATUS_LABEL: Record<PubStatus, string> = {
  draft: "작성 중", awaiting_approval: "승인 대기", approved: "승인됨(예약 전)", scheduled: "예약됨", publishing: "게시 중",
  published: "게시됨", failed: "실패(미게시 확인)", unknown: "게시 여부 확인 필요", paused: "멈춤", canceled: "취소",
};

export const ACCOUNT_STATUS_LABEL: Record<string, string> = {
  pending_verification: "연결 확인 대기", active: "연결 확인됨", reauth_required: "재인증 필요", mismatch: "계정 불일치", disabled: "사용 중지",
};

export const CONNECTION_LABEL: Record<string, string> = {
  instagram_login: "Instagram 로그인", facebook_login: "Facebook 로그인(페이지 연결)", fake: "시험용 가짜 계정",
};

export interface AccountView {
  id: string; platform: string; external_account_id: string; display_name: string; account_type: string; connection: string;
  capabilities: { post_types?: string[] } & Record<string, unknown>; status: string; status_reason: string | null;
  publish_enabled: boolean; credential_ref: string | null; verified_at: string | null; verified_username: string | null; version: number;
}

export interface RequestView {
  id: string; topic_id: string; topic_title: string; categories: string[]; plan_revision_id: string; post_type: "carousel" | "reel";
  account_id: string; target_external_account_id: string; caption: string; publish_at: string | null; display_timezone: string;
  status: PubStatus; approval_digest: string | null; current_digest: string; block: string | null; approved_at: string | null;
  pause_code: string | null; pause_reason: string | null; cancel_requested: boolean; external_post_id: string | null;
  external_url: string | null; reconcile_state: string; attempt_count: number; error_code: string | null; error_message: string | null;
  published_at: string | null; version: number; updated_at: string;
  files: { role: string; position: number; storage_key: string; width: number | null; height: number | null; state: string }[] | null;
}

export interface ReadyOutput {
  output_review_id: string; manifest_id: string; plan_revision_id: string; format: "video" | "carousel"; topic_title: string;
  reviewed_at: string | null; pages: number;
}

export interface PublishBoard {
  limits: Record<string, unknown>;
  accounts: AccountView[];
  requests: RequestView[];
  requests_truncated: boolean;
  ready_outputs: ReadyOutput[];
  slot_weights: Record<string, number> | null;
}

export interface SnapshotView {
  bucket: string; hours: number; values: Record<string, number>; unavailable: Record<string, string>; status: string;
  error_code: string | null; observed_at: string;
}

export interface PostView {
  request_id: string; topic_title: string; categories: string[]; lane: string; post_type: string; account: string; is_test: boolean;
  external_url: string | null; published_at: string; slot: string; snapshots: SnapshotView[];
}

export interface ProposalView {
  id: string; status: "proposed" | "accepted" | "rejected" | "superseded"; weights: Record<string, Record<string, number>>;
  basis: { overall?: number | null; sample_total?: number; excluded?: number; metric?: string; bucket?: string;
    groups?: Record<string, Record<string, { n: number; mean: number; target: number; enough: boolean }>> };
  sample_total: number; sufficient: boolean; summary_ko: string | null; created_at: string; decided_at: string | null; reason: string | null;
  base_version_id: string;
}

export interface AnalyticsBoard {
  limits: Record<string, unknown>;
  accounts: number;
  active_accounts: number;
  real_active_accounts: number;
  posts: PostView[];
  posts_truncated: boolean;
  active_strategy: { id: string; label: string; weights: Record<string, Record<string, number>>; created_at: string } | null;
  proposals: ProposalView[];
  rank: { strategy: string; topics: { topic_id: string; title: string; status: string; categories: string[]; lane: string;
    provisional_score: number | null; lift: number; adjusted_score: number | null }[] };
}

export async function loadPublishBoard(): Promise<Loaded<PublishBoard>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  return fromQuery(await db.rpc("drinks_publish_board", { p: {} }), "발행 화면") as Loaded<PublishBoard>;
}

export async function loadAnalyticsBoard(): Promise<Loaded<AnalyticsBoard>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  return fromQuery(await db.rpc("drinks_analytics_board", { p: {} }), "성과 화면") as Loaded<AnalyticsBoard>;
}

/** 한국 시각 표시(저장은 UTC). */
export function kst(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit" });
}

/** 발행 탭: unknown 은 실패 탭에 숨기지 않고 맨 앞 '확인 필요'에 둔다(§9.3). */
export const PUB_TABS = {
  attention: "확인 필요",
  approval: "작성·승인 대기",
  scheduled: "예약·게시 중",
  done: "게시됨",
  closed: "취소",
} as const;
export type PubTab = keyof typeof PUB_TABS;

export function pubTab(s: PubStatus): PubTab {
  if (s === "unknown" || s === "paused" || s === "failed") return "attention";
  if (s === "draft" || s === "awaiting_approval") return "approval";
  if (s === "approved" || s === "scheduled" || s === "publishing") return "scheduled";
  if (s === "published") return "done";
  return "closed";
}
