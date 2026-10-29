// 주류 동향(0059) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 0059 가 운영 DB 에 아직 없으면 'missing' — 0건이 아니라 "적용 전"이라고 따로 보여주기 위해 구분한다.
import { createAdminClient } from "@/lib/supabase/admin";
import { fetchAllPages } from "@/lib/drinks/paging";
import { isMissingTrendTables, rankProducts, type TrendIssueRow, type TrendProductRow } from "@/lib/drinks/trends";

export interface TrendsView {
  products: TrendProductRow[];
  issues: TrendIssueRow[];
}

export type TrendsLoaded =
  | { state: "ok"; data: TrendsView }
  | { state: "missing" }
  | { state: "failed"; error: string }
  | { state: "unconfigured" };

const num = (x: unknown): number => (typeof x === "number" ? x : Number(x ?? 0));

export async function loadTrends(): Promise<TrendsLoaded> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const [pr, is] = await Promise.all([
    fetchAllPages<TrendProductRow>((f, to) => db.from("drink_trend_products").select("*", { count: "exact" })
      .order("product").range(f, to), "언급 제품"),
    fetchAllPages<TrendIssueRow>((f, to) => db.from("drink_trend_issues").select("*", { count: "exact" })
      .order("collected_at", { ascending: false }).order("id").range(f, to), "주류 이슈"),
  ]);
  for (const r of [pr, is]) {
    if (!r.ok) return isMissingTrendTables(r.error) ? { state: "missing" } : { state: "failed", error: r.error };
  }
  const products = (pr as { ok: true; rows: TrendProductRow[] }).rows.map((r) => ({
    ...r, posts: num(r.posts), mentions: num(r.mentions), judged: num(r.judged), positive: num(r.positive), negative: num(r.negative),
    avg_sentiment: r.avg_sentiment === null || r.avg_sentiment === undefined ? null : num(r.avg_sentiment),
  }));
  const issues = (is as { ok: true; rows: TrendIssueRow[] }).rows
    .sort((a, b) => (b.posted_at ?? b.collected_at).localeCompare(a.posted_at ?? a.collected_at));
  return { state: "ok", data: { products: rankProducts(products), issues } };
}
