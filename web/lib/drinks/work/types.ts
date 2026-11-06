// 한 소재 · 여러 형식(2026-11-05) — 작업 단위 행과 결정 함수의 공용 타입. 계약: docs/deviation-drinks-multi-format.md §3-3·§3-4.
// 행 하나 = (소재 × 형식 의도) 또는 (카드 소유 밈 제작안). 뷰 drink_work_items(0072) 의 열과 이름이 같아야 한다(multiFormat.db.test.ts 가 대조).

export type FormatIntent = "explainer" | "card" | "meme";
export type WorkSource = "topic" | "card";

export type WorkItem = {
  unit_id: string;                        // topic:<uuid>:<intent> | meme_card:<draft uuid>
  topic_id: string | null;
  title: string;
  question: string | null;
  topic_status: string | null;
  topic_version: number | null;
  format_intent: FormatIntent;
  source: WorkSource;
  editorial_week: string | null;          // YYYY-MM-DD(월요일)
  pick_approved_at: string | null;
  pick_amount_usd: number | null;
  review_id: string | null;
  review_status: string | null;           // draft | in_review | approved | changes_requested
  review_valid: boolean | null;           // drink_review_validity.currently_valid
  review_version: number | null;
  develop_kind: "evidence" | "plan" | null;
  develop_status: string | null;          // queued | running | succeeded | failed | canceled | blocked
  develop_request_id: string | null;
  develop_error_code: string | null;
  plan_revision_id: string | null;
  plan_status: string | null;             // draft | in_review | approved | changes_requested
  plan_blocked: boolean | null;
  plan_version: number | null;
  plan_format: "video" | "carousel" | null;
  job_id: string | null;
  job_status: string | null;              // queued | running | succeeded | failed | canceled
  job_error_code: string | null;
  explainer_state: string | null;         // drink_explainer_episodes.state
  output_review_id: string | null;
  output_review_status: string | null;    // pending | approved | changes_requested | blocked
  output_usable: boolean | null;
  meme_draft_id: string | null;
  meme_status: string | null;
  meme_sync_grade: string | null;
  meme_external_url: string | null;
  pub_request_id: string | null;
  pub_status: string | null;
  pub_pause_code: string | null;
  pub_publish_at: string | null;
  pub_external_url: string | null;
  pub_version: number | null;
  unknown_billed: boolean;
  orphan_hold: boolean;
  updated_at: string | null;
};

export type BlockCode =
  | "publish_unknown" | "spend_unknown" | "evidence_invalid" | "digest_mismatch"
  | "publish_blocked" | "budget_blocked" | "no_pass" | "develop_blocked";

export type Block = { code: BlockCode; message: string; href?: string };

export type Panel = "evidence" | "plan" | "approve" | "spend" | "buy" | "produce" | "review" | "publish" | "post" | "meme" | "none";

export type Primary = {
  code: string;                           // S1..S24 | B1..B8 | needs_review
  label: string;
  busy?: boolean;                         // 진행 중(비활성)
  action?: { name: string; payload: Record<string, unknown> } | null;
  href?: string;
  panel: Panel;
};

export type Decision = {
  unitId: string;
  lane: FormatIntent;
  blocks: Block[];
  primary: Primary;
  warnings: string[];
};

export const FORMAT_LABEL: Record<FormatIntent, string> = { explainer: "릴스(설명형)", card: "카드뉴스", meme: "밈" };
export const FORMAT_SHORT: Record<FormatIntent, string> = { explainer: "릴스", card: "카드", meme: "밈" };

/** 작업공간 주소. `lane` 이 상태의 정본이다(새로고침·탭 이동에도 유지). */
export function workHref(item: Pick<WorkItem, "topic_id" | "format_intent" | "meme_draft_id" | "source">, panel?: Panel): string {
  const q = new URLSearchParams();
  q.set("lane", item.format_intent);
  if (panel && panel !== "none") q.set("panel", panel);
  if (item.source === "card" && item.meme_draft_id) q.set("meme", item.meme_draft_id);
  const base = item.topic_id ? `/drinks/work/${item.topic_id}` : `/drinks/work/meme`;
  return `${base}?${q.toString()}`;
}
