// 주류 소재 발견 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
import { createAdminClient } from "@/lib/supabase/admin";
import type { Loaded } from "@/lib/drinks/model";
import type { CandidateRow, DiscoveryItemRow } from "@/lib/drinks/discovery";
import { fetchAllIn, fetchAllPages } from "@/lib/drinks/paging";
import type { RunRow, SourceRow, TopicRow } from "@/lib/drinks/types";

export const DISCOVERY_LIMIT = 300;

export interface DiscoveryView {
  candidates: CandidateRow[];
  candidateTotal: number;
  /** candidate_id → 자료 */
  itemsByCandidate: Map<string, DiscoveryItemRow[]>;
  /** 아직 후보에 안 묶인 자료(최근순) */
  loose: DiscoveryItemRow[];
  sources: SourceRow[];
  /** source_id → 최근 실행 */
  lastRun: Map<string, RunRow>;
  topics: Pick<TopicRow, "id" | "title" | "status">[];
}

export async function loadDiscovery(status: string): Promise<Loaded<DiscoveryView>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const c = await db.from("drink_discovery_candidates").select("*", { count: "exact" }).eq("status", status)
    .order("provisional_score", { ascending: false, nullsFirst: false }).order("id").range(0, DISCOVERY_LIMIT - 1);
  if (c.error || !c.data || typeof c.count !== "number") return { state: "failed", error: `후보: ${c.error?.message ?? "응답 없음"}` };
  const cands = c.data as CandidateRow[];
  const [links, srcs, topics, assigned] = await Promise.all([
    fetchAllIn<{ item_id: string; candidate_id: string }>(cands.map((x) => x.id), (ids, f, to) => db.from("drink_candidate_items")
      .select("item_id, candidate_id", { count: "exact" }).in("candidate_id", ids).order("item_id").range(f, to), "후보 자료"),
    fetchAllPages<SourceRow>((f, to) => db.from("drink_sources").select("*", { count: "exact" }).eq("purpose", "discovery")
      .order("created_at").order("id").range(f, to), "발견 수집원"),
    fetchAllPages<Pick<TopicRow, "id" | "title" | "status">>((f, to) => db.from("drink_topics").select("id, title, status", { count: "exact" })
      .not("status", "in", "(duplicate,rejected)").order("id").range(f, to), "소재"),
    fetchAllPages<{ item_id: string }>((f, to) => db.from("drink_candidate_items").select("item_id", { count: "exact" })
      .order("item_id").range(f, to), "묶인 자료"),
  ]);
  for (const r of [links, srcs, topics, assigned]) if (!r.ok) return { state: "failed", error: (r as { error: string }).error };
  const linkRows = (links as { ok: true; rows: { item_id: string; candidate_id: string }[] }).rows;
  const items = await fetchAllIn<DiscoveryItemRow>(linkRows.map((l) => l.item_id), (ids, f, to) => db.from("drink_discovery_items")
    .select("*", { count: "exact" }).in("id", ids).order("id").range(f, to), "발견 자료");
  if (!items.ok) return { state: "failed", error: items.error };
  const byId = new Map(items.rows.map((i) => [i.id, i]));
  const itemsByCandidate = new Map<string, DiscoveryItemRow[]>();
  for (const l of linkRows) {
    const it = byId.get(l.item_id);
    if (!it) return { state: "failed", error: "후보 자료 조회 누락" };
    itemsByCandidate.set(l.candidate_id, [...(itemsByCandidate.get(l.candidate_id) ?? []), it]);
  }
  const assignedIds = new Set((assigned as { ok: true; rows: { item_id: string }[] }).rows.map((r) => r.item_id));
  const recent = await db.from("drink_discovery_items").select("*").order("discovered_at", { ascending: false }).order("id").range(0, 499);
  if (recent.error || !recent.data) return { state: "failed", error: `발견 자료: ${recent.error?.message ?? "응답 없음"}` };
  const loose = (recent.data as DiscoveryItemRow[]).filter((i) => !assignedIds.has(i.id));
  const srcRows = (srcs as { ok: true; rows: SourceRow[] }).rows;
  const lastRun = new Map<string, RunRow>();
  for (const s of srcRows) {
    const r = await db.from("drink_collection_runs").select("*").eq("source_id", s.id).not("status", "in", "(queued,running)")
      .order("created_at", { ascending: false }).limit(1).maybeSingle();
    if (r.error) return { state: "failed", error: `실행: ${r.error.message}` };
    if (r.data) lastRun.set(s.id, r.data as RunRow);
  }
  return {
    state: "ok", truncated: c.count > cands.length,
    data: { candidates: cands, candidateTotal: c.count, itemsByCandidate, loose, sources: srcRows, lastRun,
      topics: (topics as { ok: true; rows: Pick<TopicRow, "id" | "title" | "status">[] }).rows },
  };
}
