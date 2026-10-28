// 주류 공장 B단계 읽기 — 수집원·실행 기록·수집 문서. 서버 컴포넌트 전용(service key). 2026-10-22.
// ★ 실패를 빈 목록으로 바꾸지 않는다(Loaded). "정상 0건"은 ok + 빈 배열, 조회 실패는 failed 다.
import type { SupabaseClient } from "@supabase/supabase-js";

import { createAdminClient } from "@/lib/supabase/admin";
import type { Loaded } from "@/lib/drinks/model";
import { fetchAllIn, fetchAllPages, missingIds } from "@/lib/drinks/paging";
import type { ItemRow, RunRow, SnapshotRow, SourceRow, TopicRow } from "@/lib/drinks/types";

export const RUN_LIST_LIMIT = 200;
export const COLLECTED_LIMIT = 300;

const fail = (r: { ok: false; error: string }): Loaded<never> => ({ state: "failed", error: r.error });

async function recentRuns(db: SupabaseClient, limit: number, sourceId?: string) {
  let q = db.from("drink_collection_runs").select("*", { count: "exact" });
  if (sourceId) q = q.eq("source_id", sourceId);
  const r = await q.order("created_at", { ascending: false }).order("id").range(0, limit - 1);
  if (r.error) return { ok: false as const, error: `실행 기록: ${r.error.message}` };
  if (!r.data || typeof r.count !== "number") return { ok: false as const, error: "실행 기록: 응답이 비었습니다" };
  return { ok: true as const, rows: r.data as RunRow[], total: r.count };
}

export interface SourcesView {
  sources: SourceRow[];
  /** source_id → 최근 실행(최신순, 최대 5) */
  runs: Map<string, RunRow[]>;
  /** source_id → 마지막 검증 실행 결과 */
  lastValidation: Map<string, RunRow>;
  limits: Record<string, number>;
  activeCount: number;
}

export async function loadSources(): Promise<Loaded<SourcesView>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const [src, lim] = await Promise.all([
    fetchAllPages<SourceRow>((f, to) => db.from("drink_sources").select("*", { count: "exact" })
      .order("created_at").order("id").range(f, to), "수집원"),
    db.rpc("drinks_collect_limits"),
  ]);
  if (!src.ok) return fail(src);
  if (lim.error) return { state: "failed", error: `수집 상한: ${lim.error.message}` };
  const ids = src.rows.map((s) => s.id);
  // 수집원마다 최근 실행 5건: 수집원 수(≤ 수십)만큼 작은 조회. 화면이 오래된 실행까지 다 읽지 않게 한다.
  const per = await Promise.all(ids.map((id) => recentRuns(db, 5, id)));
  const runs = new Map<string, RunRow[]>();
  for (let i = 0; i < ids.length; i++) {
    const r = per[i];
    if (!r.ok) return fail(r);
    runs.set(ids[i], r.rows);
  }
  const latestVal = await Promise.all(ids.map((id) => db.from("drink_collection_runs").select("*")
    .eq("source_id", id).eq("mode", "validate").not("status", "in", "(queued,running)")
    .order("created_at", { ascending: false }).limit(1).maybeSingle()));
  const lastValidation = new Map<string, RunRow>();
  for (let i = 0; i < ids.length; i++) {
    const r = latestVal[i];
    if (r.error) return { state: "failed", error: `검증 실행: ${r.error.message}` };
    if (r.data) lastValidation.set(ids[i], r.data as RunRow);
  }
  return {
    state: "ok",
    data: {
      sources: src.rows, runs, lastValidation, limits: (lim.data ?? {}) as Record<string, number>,
      activeCount: src.rows.filter((s) => s.state === "active").length,
    },
  };
}

export interface RunsView {
  runs: RunRow[];
  total: number;
  sources: Map<string, SourceRow>;
}

export async function loadRuns(limit: number = RUN_LIST_LIMIT, sourceId?: string): Promise<Loaded<RunsView>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const r = await recentRuns(db, limit, sourceId);
  if (!r.ok) return fail(r);
  const s = await fetchAllIn<SourceRow>(r.rows.map((x) => x.source_id), (c, f, to) => db.from("drink_sources")
    .select("*", { count: "exact" }).in("id", c).order("id").range(f, to), "수집원");
  if (!s.ok) return fail(s);
  const lost = missingIds(r.rows.map((x) => x.source_id), s.rows.map((x) => x.id));
  if (lost.length) return { state: "failed", error: `수집원 조회 누락 ${lost.length}건` };
  return {
    state: "ok", truncated: r.total > r.rows.length,
    data: { runs: r.rows, total: r.total, sources: new Map(s.rows.map((x) => [x.id, x])) },
  };
}

export interface RunDetail {
  run: RunRow;
  source: SourceRow;
  items: ItemRow[];
  retryOf: RunRow | null;
}

export async function loadRun(id: string): Promise<Loaded<RunDetail> | { state: "not_found" }> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  if (!/^[0-9a-f-]{36}$/i.test(id)) return { state: "not_found" };
  const r = await db.from("drink_collection_runs").select("*").eq("id", id).maybeSingle();
  if (r.error) return { state: "failed", error: `실행: ${r.error.message}` };
  if (!r.data) return { state: "not_found" };
  const run = r.data as RunRow;
  const [s, items, prev] = await Promise.all([
    db.from("drink_sources").select("*").eq("id", run.source_id).maybeSingle(),
    fetchAllPages<ItemRow>((f, to) => db.from("drink_collection_items").select("*", { count: "exact" })
      .eq("run_id", id).order("id").range(f, to), "실행 문서"),
    run.retry_of ? db.from("drink_collection_runs").select("*").eq("id", run.retry_of).maybeSingle() : null,
  ]);
  if (s.error || !s.data) return { state: "failed", error: `수집원: ${s.error?.message ?? "없음"}` };
  if (!items.ok) return fail(items);
  if (prev && prev.error) return { state: "failed", error: `재시도 대상 실행: ${prev.error.message}` };
  return { state: "ok", data: { run, source: s.data as SourceRow, items: items.rows, retryOf: (prev?.data as RunRow) ?? null } };
}

export interface CollectedDoc {
  snapshot: SnapshotRow;
  source: SourceRow | null;
  /** 이 문서를 연결한 소재(역할 포함) */
  linked: { topic_id: string; role: string }[];
  /** 같은 본문의 다른 URL 수(원출처 후보) */
  sameBody: number;
  summary: string | null;
}

export interface CollectedView {
  docs: CollectedDoc[];
  total: number;
  sources: SourceRow[];
  /** 비슷한 소재 후보 계산과 [기존 소재에 연결] 선택지용 — 열린 소재만 */
  topics: Pick<TopicRow, "id" | "title" | "question" | "status" | "categories">[];
}

export async function loadCollected(limit: number, sourceId?: string): Promise<Loaded<CollectedView>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  let q = db.from("drink_source_snapshots")
    .select("id, url_raw, canonical_url, title, publisher, source_kind, depth, content_hash, original_language, published_at, checked_at, rights_status, usage_terms, origin_group, supersedes_id, created_at, capture_method, collected_source_id, collected_run_id",
      { count: "exact" })
    .eq("capture_method", "collected");
  if (sourceId) q = q.eq("collected_source_id", sourceId);
  const sn = await q.order("created_at", { ascending: false }).order("id").range(0, limit - 1);
  if (sn.error) return { state: "failed", error: `수집 문서: ${sn.error.message}` };
  if (!sn.data || typeof sn.count !== "number") return { state: "failed", error: "수집 문서: 응답이 비었습니다" };
  const snaps = sn.data as SnapshotRow[];
  const ids = snaps.map((s) => s.id);
  const hashes = snaps.map((s) => s.content_hash);
  const [src, links, same, items, tp] = await Promise.all([
    fetchAllPages<SourceRow>((f, to) => db.from("drink_sources").select("*", { count: "exact" }).order("id").range(f, to), "수집원"),
    fetchAllIn<{ topic_id: string; snapshot_id: string; role: string }>(ids, (c, f, to) => db.from("drink_topic_sources")
      .select("topic_id, snapshot_id, role", { count: "exact" }).in("snapshot_id", c).order("topic_id").order("snapshot_id").range(f, to), "소재 연결"),
    fetchAllIn<{ id: string; content_hash: string; canonical_url: string | null }>(hashes, (c, f, to) => db.from("drink_source_snapshots")
      .select("id, content_hash, canonical_url", { count: "exact" }).in("content_hash", c).order("id").range(f, to), "같은 본문"),
    fetchAllIn<{ snapshot_id: string; summary: string | null; id: number }>(ids, (c, f, to) => db.from("drink_collection_items")
      .select("id, snapshot_id, summary", { count: "exact" }).in("snapshot_id", c).not("summary", "is", null).order("id").range(f, to), "수집 요약"),
    fetchAllPages<Pick<TopicRow, "id" | "title" | "question" | "status" | "categories">>((f, to) => db.from("drink_topics")
      .select("id, title, question, status, categories", { count: "exact" })
      .in("status", ["inbox", "triaged", "researching", "ready", "selected", "on_hold"]).order("id").range(f, to), "소재"),
  ]);
  for (const r of [src, links, same, items, tp]) if (!r.ok) return fail(r as { ok: false; error: string });
  const srcRows = (src as { ok: true; rows: SourceRow[] }).rows;
  const srcById = new Map(srcRows.map((s) => [s.id, s]));
  const linkBy = new Map<string, { topic_id: string; role: string }[]>();
  for (const l of (links as { ok: true; rows: { topic_id: string; snapshot_id: string; role: string }[] }).rows) {
    linkBy.set(l.snapshot_id, [...(linkBy.get(l.snapshot_id) ?? []), { topic_id: l.topic_id, role: l.role }]);
  }
  const sameRows = (same as { ok: true; rows: { id: string; content_hash: string; canonical_url: string | null }[] }).rows;
  const summaryBy = new Map<string, string>();
  for (const it of (items as { ok: true; rows: { snapshot_id: string; summary: string | null }[] }).rows) {
    if (it.summary) summaryBy.set(it.snapshot_id, it.summary);
  }
  const docs = snaps.map((s) => ({
    snapshot: s,
    source: s.collected_source_id ? srcById.get(s.collected_source_id) ?? null : null,
    linked: linkBy.get(s.id) ?? [],
    sameBody: s.content_hash
      ? new Set(sameRows.filter((x) => x.content_hash === s.content_hash && x.canonical_url !== s.canonical_url)
        .map((x) => x.canonical_url)).size
      : 0,
    summary: summaryBy.get(s.id) ?? null,
  }));
  return {
    state: "ok", truncated: sn.count > snaps.length,
    data: { docs, total: sn.count, sources: srcRows, topics: (tp as { ok: true; rows: CollectedView["topics"] }).rows },
  };
}

/** 선별 화면 상단 — 최근 24시간 실행 상태 수. "수집 실패"를 정상 0건과 섞지 않는다. */
export async function loadRunHealth(): Promise<Loaded<{ failed: number; partial: number; aborted: number; empty: number; succeeded: number; active: number; stuck: number }>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const [runs, act, stuck] = await Promise.all([
    fetchAllPages<{ id: string; status: string }>((f, to) => db.from("drink_collection_runs").select("id, status", { count: "exact" })
      .gte("created_at", since).order("id").range(f, to), "최근 실행"),
    db.from("drink_sources").select("id", { count: "exact", head: true }).eq("state", "active"),
    // 24시간보다 오래된 것도 센다 — 워커가 죽은 실행은 날짜와 상관없이 문제다.
    db.from("drink_collection_runs").select("id", { count: "exact", head: true }).eq("status", "running")
      .lt("lease_expires_at", new Date().toISOString()),
  ]);
  if (!runs.ok) return fail(runs);
  if (act.error || typeof act.count !== "number") return { state: "failed", error: `활성 수집원: ${act.error?.message ?? "건수 없음"}` };
  if (stuck.error || typeof stuck.count !== "number") return { state: "failed", error: `멈춘 실행: ${stuck.error?.message ?? "건수 없음"}` };
  const n = (s: string) => runs.rows.filter((r) => r.status === s).length;
  return { state: "ok", data: { failed: n("failed"), partial: n("partial"), aborted: n("aborted"), empty: n("empty"), succeeded: n("succeeded"), active: act.count, stuck: stuck.count } };
}
