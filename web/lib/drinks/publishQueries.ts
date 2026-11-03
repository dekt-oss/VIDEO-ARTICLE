// 주류 발행·성과(0055) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 두 화면이 각각 DB 함수 하나(drinks_publish_board / drinks_analytics_board)로 읽는다 — 상한을 넘으면 truncated.
import { createAdminClient } from "@/lib/supabase/admin";
import { fromQuery, type Loaded } from "@/lib/drinks/model";
import type { AudioBundle, AudioOption } from "@/lib/drinks/audio";

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

/** 0068: 콘텐츠 형식. 카드뉴스(캐러셀·카드 릴스)·설명형·밈형. 성과·전략이 이 값으로 묶인다. */
export type ContentFormat = "card" | "explainer" | "meme";
export const CONTENT_FORMAT_LABEL: Record<ContentFormat, string> = { card: "카드뉴스", explainer: "설명형", meme: "밈형" };

export interface RequestView {
  id: string; topic_id: string | null; topic_title: string; categories: string[]; plan_revision_id: string | null; post_type: "carousel" | "reel";
  /** 0068. 0068 전 DB 는 이 칸을 주지 않는다 → 카드로 본다 */
  content_format?: ContentFormat; meme_draft_id?: string | null;
  account_id: string; target_external_account_id: string; caption: string; publish_at: string | null; display_timezone: string;
  status: PubStatus; approval_digest: string | null; current_digest: string; block: string | null; approved_at: string | null;
  pause_code: string | null; pause_reason: string | null; cancel_requested: boolean; external_post_id: string | null;
  external_url: string | null; reconcile_state: string; attempt_count: number; error_code: string | null; error_message: string | null;
  published_at: string | null; version: number; updated_at: string;
  files: { role: string; position: number; storage_key: string; width: number | null; height: number | null; state: string }[] | null;
  /** 0065 음원 묶음. 없으면 null */
  audio?: AudioBundle | null; audio_verified_at?: string | null; audio_required?: boolean;
}

export interface ReadyOutput {
  output_review_id: string; manifest_id: string; plan_revision_id: string; format: "video" | "carousel"; topic_title: string;
  reviewed_at: string | null; pages: number;
  /** 0065: 이 묶음으로 아직 만들 수 있는 게시 형식 */
  post_types?: ("carousel" | "reel")[];
  /** 0068: 설명형 소재의 영상이면 explainer — 캡션에 'AI 생성 영상' 한 줄이 필수다 */
  content_format?: ContentFormat;
}

/** 0068: 게시 대기 중인 밈 제작안(박자 무관만). 발행안을 만들면 목록에서 빠진다. */
export interface ReadyMeme {
  draft_id: string; owner_name: string; card_id: string | null; topic_id: string | null; frame: string | null; top_line: string | null;
  caption: string | null; audio_mode: string | null; audio_id: string | null; bought_scene: boolean | null; duration_ms: number | null;
  approved_at: string | null; updated_at: string;
}

export interface PublishBoard {
  limits: Record<string, unknown>;
  accounts: AccountView[];
  requests: RequestView[];
  requests_truncated: boolean;
  ready_outputs: ReadyOutput[];
  /** 0068: 게시 대기 밈 제작안. 0068 전 DB 는 이 칸을 주지 않는다 */
  ready_memes?: ReadyMeme[];
  /** 0065: 고를 수 있는 음원(가장 최근 수집일 목록) */
  audio_options?: AudioOption[];
  slot_weights: Record<string, number> | null;
  /** 0068: 설명형 캡션 필수 한 줄(서버 값) */
  ai_label_text?: string;
}

export interface SnapshotView {
  bucket: string; hours: number; values: Record<string, number>; unavailable: Record<string, string>; status: string;
  error_code: string | null; observed_at: string;
}

export interface PostView {
  request_id: string; topic_title: string; categories: string[]; lane: string | null; post_type: string; account: string; is_test: boolean;
  external_url: string | null; published_at: string; slot: string; snapshots: SnapshotView[];
  /** 0068 */
  format?: ContentFormat;
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
  /** 0068: 형식별 게시 편수 */
  format_counts?: Partial<Record<ContentFormat, number>>;
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
