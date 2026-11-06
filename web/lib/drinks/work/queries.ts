// 주류 작업 단위 읽기(2026-11-05) — 서버 컴포넌트 전용(service key). 클라이언트 컴포넌트에서 import 하지 말 것.
// 계약: docs/deviation-drinks-multi-format.md §3-3(뷰 drink_work_items) · §3-5(읽기 rpc 셋).
//
// ★ 실패를 빈 목록으로 바꾸지 않는다 — 모든 조회는 Loaded(ok / failed / unconfigured). rpc 가 아직 없으면(0072 미적용)
//   그것도 failed 로 돌려주고 사유를 글자로 남긴다 — "작업 0건"으로 보이면 운영자가 하루 종일 모른다(error-vs-empty).
// ★ 얇게 둔다: 화면(담당 D)이 loadTopic/loadDevelop/loadPlanProduction 과 합친다.
import { createAdminClient } from "@/lib/supabase/admin";
import { fromQuery, type Loaded } from "@/lib/drinks/model";
import { loadDevelop, loadTopic, type DevelopLoad, type TopicDetail } from "@/lib/drinks/queries";
import type { FormatIntent, WorkItem } from "@/lib/drinks/work/types";

export type WorkFilter = "approve" | "publish" | "all";

/** 배열 응답인지 확인한다. 함수가 객체 하나({items:[…]})로 싸서 돌려줘도 받는다. */
function asRows<T>(raw: unknown, label: string): Loaded<T[]> {
  const list = Array.isArray(raw) ? raw : (raw as { items?: unknown; rows?: unknown } | null)?.items ?? (raw as { rows?: unknown } | null)?.rows;
  if (!Array.isArray(list)) return { state: "failed", error: `${label}: 응답 모양이 배열이 아닙니다` };
  return { state: "ok", data: list as T[] };
}

/** 작업 단위 전부(또는 승인 대기·발행 대기만). 행 수 = 작업 단위 수(§3-3). */
export async function loadWorkItems(filter: WorkFilter = "all"): Promise<Loaded<WorkItem[]>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const r = fromQuery(await db.rpc("drinks_work_items", { p: { filter } }), "작업 목록");
  if (r.state !== "ok") return r;
  return asRows<WorkItem>(r.data, "작업 목록");
}

export interface TopicWork {
  topic: TopicDetail;
  develop: DevelopLoad;
  /** 이 소재의 작업 단위(형식별 한 행). 형식을 고르지 않았으면 빈 배열이 **정상**이다(조회 실패와 구별된다). */
  items: WorkItem[];
  /** 0072 drinks_topic_formats 가 함께 주는 것: 대표 형식·형식별 pick 행·편성 형식. 모양은 함수가 정한다. */
  representative: FormatIntent | null;
  picks: Record<string, unknown>[];
  selected_formats: string[] | null;
}

/** 한 소재의 형식별 작업 단위 + 기존 소재 상세·개발 상태. 제작·설명형 상세는 화면이 plan_revision_id 로 loadPlanProduction 을 따로 부른다. */
export async function loadTopicWork(topicId: string): Promise<Loaded<TopicWork> | { state: "not_found" }> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  if (!/^[0-9a-f-]{36}$/i.test(topicId)) return { state: "not_found" };
  const [topic, develop, formats] = await Promise.all([
    loadTopic(topicId),
    loadDevelop(topicId),
    db.rpc("drinks_topic_formats", { p: { topic_id: topicId } }),
  ]);
  if (topic.state !== "ok") return topic;
  if (develop.state === "failed" || develop.state === "unconfigured") return develop;
  const f = fromQuery(formats, "소재 형식");
  if (f.state !== "ok") return f;
  const body = (f.data ?? {}) as { items?: unknown; picks?: unknown; representative?: unknown; selected_formats?: unknown };
  const items = asRows<WorkItem>(body, "소재 형식");
  if (items.state !== "ok") return items;
  const wrong = items.data.filter((x) => x.topic_id !== topicId);
  if (wrong.length > 0) return { state: "failed", error: `소재 형식: 다른 소재의 행 ${wrong.length}건이 섞여 왔습니다` };
  const rep = body.representative;
  return { state: "ok", data: {
    topic: topic.data, develop, items: items.data,
    representative: rep === "explainer" || rep === "card" || rep === "meme" ? rep : null,
    picks: Array.isArray(body.picks) ? (body.picks as Record<string, unknown>[]) : [],
    selected_formats: Array.isArray(body.selected_formats) ? (body.selected_formats as string[]) : null,
  } };
}

/** 개발 비용 견적(rpc drinks_develop_estimate, 0072). 근거 초안은 형식 무관 공유라 한 번만 센다(shared). known=false 는 "모름"이지 0원이 아니다. */
export interface DevelopEstimateItem {
  kind: "evidence" | "plan" | "meme";
  format_intent: FormatIntent | null;
  est_usd: number | string | null;
  known: boolean;
  model?: string | null;
  shared?: boolean;
  [k: string]: unknown;
}
export interface DevelopEstimate {
  topic_id: string | null;
  formats: FormatIntent[];
  items: DevelopEstimateItem[];
  total_est_usd: number;
  /** 모든 항목의 금액을 알 때만 true. false 면 총액은 **하한**이다 — 화면은 "이상"으로 쓴다. */
  all_known: boolean;
  per_request_cap_usd: number | string | null;
  budget_remaining_usd: number | string | null;
  budget_id: string | null;
  params?: Record<string, unknown>;
}

export async function loadDevelopEstimate(formats: FormatIntent[], topicId?: string | null, budgetId?: string | null): Promise<Loaded<DevelopEstimate>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  if (formats.length === 0) return { state: "failed", error: "견적: 형식을 하나 이상 골라야 합니다" };
  const r = fromQuery(await db.rpc("drinks_develop_estimate", { p: { formats, ...(topicId ? { topic_id: topicId } : {}), ...(budgetId ? { budget_id: budgetId } : {}) } }), "견적");
  if (r.state !== "ok") return r;
  const est = r.data as Partial<DevelopEstimate> | null;
  if (!est || typeof est !== "object" || !Array.isArray(est.items) || !Number.isFinite(Number(est.total_est_usd))) {
    return { state: "failed", error: "견적: 응답에 항목(items)·총액(total_est_usd)이 없습니다" };
  }
  return { state: "ok", data: { ...(est as DevelopEstimate), total_est_usd: Number(est.total_est_usd), all_known: est.all_known === true } };
}
