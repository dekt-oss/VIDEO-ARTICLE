// 주류 공장 읽기 — 서버 컴포넌트 전용(service key). 절대 클라이언트 컴포넌트에서 import 하지 말 것.
//
// ★ 주류 표(0050)는 anon 에게 읽기 권한도 없다(명세 §12.2). 운영자 게이트(middleware) 뒤 서버 컴포넌트가
//   service key 로 읽는다.
// ★ 실패를 빈 목록으로 바꾸지 않는다 — 모든 조회는 Loaded(ok / failed / unconfigured).
// ★ 조회 상한 2종(요청 크기·응답 행 상한)은 ./paging.ts 가 다룬다. 목록 화면은 현재 포인터
//   (current/approved/selected 버전, 결과물의 현재 제작안)만 읽고, 포인터가 가리키는 행이 응답에 없으면
//   "초안 없음·미승인"이 아니라 조회 실패로 돌려준다.
import type { SupabaseClient } from "@supabase/supabase-js";

import { createAdminClient } from "@/lib/supabase/admin";
import { isSchemaMissing, type DevelopBudgetRow, type DevelopRequestRow } from "@/lib/drinks/develop";
import type { Loaded } from "@/lib/drinks/model";
import { fetchAllIn, fetchAllPages, missingIds, PAGE_SIZE, type PageResult } from "@/lib/drinks/paging";
import type {
  AttestationRow,
  DeliverableRow,
  EventRow,
  PlanRow,
  ReviewRow,
  SnapshotRow,
  TopicRow,
  TopicSourceRow,
  ValidityRow,
} from "@/lib/drinks/types";

/** 목록 기본 상한. 넘으면 truncated 로 표시하고 [더 보기](?limit=)로 늘린다. */
export const TOPIC_LIST_LIMIT = 500;
export const EVENTS_LIMIT = 200;

const fail = (r: { ok: false; error: string }): Loaded<never> => ({ state: "failed", error: r.error });

/** 승인 기록에 "지금 쓸 수 있는가"를 붙인다. 판정 행이 빠지면 쓸 수 있다고 가정하지 않고 실패로 돌려준다. */
async function attachValidity(db: SupabaseClient, reviews: ReviewRow[]): Promise<{ ok: true } | { ok: false; error: string }> {
  const ids = reviews.map((r) => r.id);
  const v = await fetchAllIn<ValidityRow>(ids, (c, f, to) => db.from("drink_review_validity").select("*", { count: "exact" })
    .in("review_id", c).order("review_id").range(f, to), "현재 유효성");
  if (!v.ok) return v;
  const byId = new Map(v.rows.map((x) => [x.review_id, x]));
  const lost = missingIds(ids, byId.keys());
  if (lost.length > 0) return { ok: false, error: `현재 유효성 조회 누락 ${lost.length}건` };
  for (const r of reviews) {
    const x = byId.get(r.id)!;
    r.current_blockers = x.current_blockers ?? [];
    r.currently_valid = x.currently_valid === true;
  }
  return { ok: true };
}

export interface DrinksBoard {
  topics: TopicRow[];
  reviews: Map<string, ReviewRow>;
  deliverables: DeliverableRow[];
  plans: Map<string, PlanRow>;
  /** topic_id → 연결된 스냅샷(발행일 필터·원출처 수 표시용) */
  sources: Map<string, SnapshotRow[]>;
  totalTopics: number;
}

/** 소재 목록을 최신순으로 limit 건까지(쪽 단위로) 읽는다. 전체 건수도 함께 돌려준다. */
async function loadTopics(db: SupabaseClient, limit: number): Promise<PageResult<TopicRow> | { ok: false; error: string }> {
  const rows: TopicRow[] = [];
  let total = 0;
  while (rows.length < limit) {
    const from = rows.length;
    const to = Math.min(limit, from + PAGE_SIZE) - 1;
    const r = await db.from("drink_topics").select("*", { count: "exact" })
      .order("created_at", { ascending: false }).order("id").range(from, to);
    if (r.error) return { ok: false, error: `소재: ${r.error.message}` };
    if (!r.data || typeof r.count !== "number") return { ok: false, error: "소재: 응답·전체 건수가 비었습니다" };
    total = r.count;
    rows.push(...(r.data as TopicRow[]));
    if (rows.length >= total || r.data.length === 0) break;
  }
  if (rows.length < Math.min(limit, total)) {
    return { ok: false, error: `소재: ${Math.min(limit, total)}건 중 ${rows.length}건만 받았습니다` };
  }
  return { ok: true, rows, total };
}

/** 선별·작업함·제작 화면 공용. 현재 포인터만 읽는다(옛 버전은 상세 화면에서). */
export async function loadBoard(limit: number = TOPIC_LIST_LIMIT): Promise<Loaded<DrinksBoard>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const tr = await loadTopics(db, limit);
  if (!tr.ok) return fail(tr);
  const topics = tr.rows;
  const ids = topics.map((t) => t.id);
  const reviewIds = topics.flatMap((t) => [t.current_review_id, t.approved_review_id, t.selected_review_id]);
  const [rv, dl, ts] = await Promise.all([
    fetchAllIn<ReviewRow>(reviewIds, (c, f, to) => db.from("drink_topic_reviews").select("*", { count: "exact" })
      .in("id", c).order("id").range(f, to), "근거·기획 버전"),
    fetchAllIn<DeliverableRow>(ids, (c, f, to) => db.from("drink_deliverables").select("*", { count: "exact" })
      .in("topic_id", c).order("id").range(f, to), "결과물"),
    fetchAllIn<TopicSourceRow>(ids, (c, f, to) => db.from("drink_topic_sources").select("*", { count: "exact" })
      .in("topic_id", c).order("topic_id").order("snapshot_id").range(f, to), "소재·출처 연결"),
  ]);
  if (!rv.ok) return fail(rv);
  if (!dl.ok) return fail(dl);
  if (!ts.ok) return fail(ts);
  const planIds = dl.rows.map((d) => d.current_revision_id);
  const [pl, sn] = await Promise.all([
    fetchAllIn<PlanRow>(planIds, (c, f, to) => db.from("drink_plan_revisions").select("*", { count: "exact" })
      .in("id", c).order("id").range(f, to), "제작안"),
    fetchAllIn<SnapshotRow>(ts.rows.map((x) => x.snapshot_id), (c, f, to) => db.from("drink_source_snapshots")
      .select("id, canonical_url, published_at, origin_group, depth, source_kind, content_hash", { count: "exact" })
      .in("id", c).order("id").range(f, to), "출처"),
  ]);
  if (!pl.ok) return fail(pl);
  if (!sn.ok) return fail(sn);
  // 제작안이 쓴 근거 버전이 포인터(현재·승인·편성)에 없으면 따로 읽는다 — 제작 화면이 그 근거의 현재 유효성을 본다.
  const extraReviewIds = missingIds(pl.rows.map((p) => p.topic_review_id), rv.rows.map((r) => r.id));
  if (extraReviewIds.length > 0) {
    const ex = await fetchAllIn<ReviewRow>(extraReviewIds, (c, f, to) => db.from("drink_topic_reviews").select("*", { count: "exact" })
      .in("id", c).order("id").range(f, to), "제작안 근거 버전");
    if (!ex.ok) return fail(ex);
    rv.rows.push(...ex.rows);
  }
  const va = await attachValidity(db, rv.rows);
  if (!va.ok) return fail(va);
  // 포인터가 가리키는 행이 하나라도 없으면 화면이 "초안 없음·미승인"으로 오판한다 → 실패로 돌려준다.
  // 포인터 + 각 제작안이 참조하는 근거 버전까지 — 하나라도 없으면 유효성을 추정하지 않는다.
  const lostReviews = missingIds([...reviewIds, ...pl.rows.map((p) => p.topic_review_id)], rv.rows.map((r) => r.id));
  const lostPlans = missingIds(planIds, pl.rows.map((p) => p.id));
  const lostSnaps = missingIds(ts.rows.map((x) => x.snapshot_id), sn.rows.map((s) => s.id));
  if (lostReviews.length + lostPlans.length + lostSnaps.length > 0) {
    return {
      state: "failed",
      error: `현재 버전 조회 누락 — 근거·기획 ${lostReviews.length}건, 제작안 ${lostPlans.length}건, 출처 ${lostSnaps.length}건`,
    };
  }
  const snapById = new Map(sn.rows.map((s) => [s.id, s]));
  const sources = new Map<string, SnapshotRow[]>();
  for (const link of ts.rows) {
    const list = sources.get(link.topic_id) ?? [];
    list.push({ ...snapById.get(link.snapshot_id)!, role: link.role });
    sources.set(link.topic_id, list);
  }
  return {
    state: "ok",
    truncated: tr.total > topics.length,
    data: {
      topics,
      reviews: new Map(rv.rows.map((r) => [r.id, r])),
      deliverables: dl.rows,
      plans: new Map(pl.rows.map((p) => [p.id, p])),
      sources,
      totalTopics: tr.total,
    },
  };
}

export interface SameBodyCandidate {
  id: string;
  canonical_url: string | null;
  origin_group: string | null;
  linkedHere: boolean;
}

export interface TopicDetail {
  topic: TopicRow;
  sources: (TopicSourceRow & { snapshot: SnapshotRow })[];
  reviews: ReviewRow[];
  deliverables: DeliverableRow[];
  plans: PlanRow[];
  events: EventRow[];
  eventsTotal: number;
  canonical: Pick<TopicRow, "id" | "title" | "status"> | null;
  /** snapshot_id → 정정·재확인 기록(시간순) */
  attestations: Map<string, AttestationRow[]>;
  /** snapshot_id → 같은 본문의 다른 스냅샷(전재 의심 — 정책 ②, 운영자가 확인 후 묶는다) */
  sameBody: Map<string, SameBodyCandidate[]>;
  /** snapshot_id → 이 출처를 함께 쓰는 다른 소재 수 */
  sharedWith: Map<string, number>;
}

export async function loadTopic(
  id: string,
  eventsLimit: number = EVENTS_LIMIT
): Promise<Loaded<TopicDetail> | { state: "not_found" }> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  if (!/^[0-9a-f-]{36}$/i.test(id)) return { state: "not_found" };
  const t = await db.from("drink_topics").select("*").eq("id", id).maybeSingle();
  if (t.error) return { state: "failed", error: `소재: ${t.error.message}` };
  if (!t.data) return { state: "not_found" };
  const topic = t.data as TopicRow;
  const [links, reviews, deliverables, plans] = await Promise.all([
    fetchAllPages<TopicSourceRow>((f, to) => db.from("drink_topic_sources").select("*", { count: "exact" })
      .eq("topic_id", id).order("created_at").order("snapshot_id").range(f, to), "출처 연결"),
    fetchAllPages<ReviewRow>((f, to) => db.from("drink_topic_reviews").select("*", { count: "exact" })
      .eq("topic_id", id).order("revision_no", { ascending: false }).range(f, to), "근거·기획 버전"),
    fetchAllPages<DeliverableRow>((f, to) => db.from("drink_deliverables").select("*", { count: "exact" })
      .eq("topic_id", id).order("id").range(f, to), "결과물"),
    fetchAllPages<PlanRow>((f, to) => db.from("drink_plan_revisions").select("*", { count: "exact" })
      .eq("topic_id", id).order("format").order("revision_no", { ascending: false }).range(f, to), "제작안"),
  ]);
  for (const r of [links, reviews, deliverables, plans]) if (!r.ok) return fail(r);
  const linkRows = (links as { ok: true; rows: TopicSourceRow[] }).rows;
  const snapIds = linkRows.map((l) => l.snapshot_id);
  const [snaps, attests, shared] = await Promise.all([
    fetchAllIn<SnapshotRow>(snapIds, (c, f, to) => db.from("drink_source_snapshots").select("*", { count: "exact" })
      .in("id", c).order("id").range(f, to), "출처"),
    fetchAllIn<AttestationRow>(snapIds, (c, f, to) => db.from("drink_snapshot_attestations").select("*", { count: "exact" })
      .in("snapshot_id", c).order("seq").range(f, to), "출처 정정 기록"),
    fetchAllIn<Pick<TopicSourceRow, "topic_id" | "snapshot_id">>(snapIds, (c, f, to) => db.from("drink_topic_sources").select("topic_id, snapshot_id", { count: "exact" })
      .in("snapshot_id", c).order("snapshot_id").order("topic_id").range(f, to), "공유 출처"),
  ]);
  if (!snaps.ok) return fail(snaps);
  if (!attests.ok) return fail(attests);
  if (!shared.ok) return fail(shared);
  const lostSnaps = missingIds(snapIds, snaps.rows.map((s) => s.id));
  const rv = (reviews as { ok: true; rows: ReviewRow[] }).rows;
  const va = await attachValidity(db, rv);
  if (!va.ok) return fail(va);
  const pl = (plans as { ok: true; rows: PlanRow[] }).rows;
  const dl = (deliverables as { ok: true; rows: DeliverableRow[] }).rows;
  const lostReviews = missingIds([topic.current_review_id, topic.approved_review_id, topic.selected_review_id,
    ...pl.map((p) => p.topic_review_id)], rv.map((r) => r.id));
  const lostPlans = missingIds(dl.map((d) => d.current_revision_id), pl.map((p) => p.id));
  if (lostSnaps.length + lostReviews.length + lostPlans.length > 0) {
    return { state: "failed", error: `조회 누락 — 출처 ${lostSnaps.length}건, 근거·기획 ${lostReviews.length}건, 제작안 ${lostPlans.length}건` };
  }
  const hashes = snaps.rows.map((s) => s.content_hash).filter((h): h is string => Boolean(h));
  const same = await fetchAllIn<Pick<SnapshotRow, "id" | "canonical_url" | "origin_group" | "content_hash">>(hashes, (c, f, to) => db.from("drink_source_snapshots")
    .select("id, canonical_url, origin_group, content_hash", { count: "exact" }).in("content_hash", c).order("id").range(f, to),
    "같은 본문 후보");
  if (!same.ok) return fail(same);
  // 이력: 의도적 상한. 전체 건수를 같이 받아 잘림을 표시한다.
  const ev = await db.from("drink_workflow_events").select("*", { count: "exact" }).eq("topic_id", id)
    .order("id", { ascending: false }).range(0, Math.min(eventsLimit, PAGE_SIZE) - 1);
  if (ev.error || !ev.data || typeof ev.count !== "number") {
    return { state: "failed", error: `이력: ${ev.error?.message ?? "응답·전체 건수가 비었습니다"}` };
  }
  let canonical: TopicDetail["canonical"] = null;
  if (topic.canonical_topic_id) {
    const c = await db.from("drink_topics").select("id, title, status").eq("id", topic.canonical_topic_id).maybeSingle();
    if (c.error) return { state: "failed", error: `기준 소재: ${c.error.message}` };
    canonical = c.data as TopicDetail["canonical"];
  }
  const byId = new Map(snaps.rows.map((s) => [s.id, s]));
  const linkedHere = new Set(snapIds);
  const attestations = new Map<string, AttestationRow[]>();
  for (const a of attests.rows) attestations.set(a.snapshot_id, [...(attestations.get(a.snapshot_id) ?? []), a]);
  const sameBody = new Map<string, SameBodyCandidate[]>();
  for (const s of snaps.rows) {
    if (!s.content_hash) continue;
    const others = same.rows.filter((x) => x.content_hash === s.content_hash && x.id !== s.id)
      .map((x) => ({ id: x.id, canonical_url: x.canonical_url, origin_group: x.origin_group, linkedHere: linkedHere.has(x.id) }));
    if (others.length > 0) sameBody.set(s.id, others);
  }
  const sharedWith = new Map<string, number>();
  for (const x of shared.rows) if (x.topic_id !== id) sharedWith.set(x.snapshot_id, (sharedWith.get(x.snapshot_id) ?? 0) + 1);
  return {
    state: "ok",
    truncated: ev.count > ev.data.length,
    data: {
      topic,
      sources: linkRows.map((l) => ({ ...l, snapshot: byId.get(l.snapshot_id)! })),
      reviews: rv,
      deliverables: dl,
      plans: pl,
      events: ev.data as EventRow[],
      eventsTotal: ev.count,
      canonical,
      attestations,
      sameBody,
      sharedWith,
    },
  };
}

// ── 소재 개발(0060) 읽기 ──
// 0060 이 아직 운영 DB 에 없으면 화면을 죽이지 않고 "missing" 으로 돌려준다(카드가 그 사실을 말한다).
// 그 밖의 실패는 failed — "요청 0건"으로 바꾸지 않는다.
export type DevelopLoad =
  | { state: "ok"; requests: DevelopRequestRow[]; budgets: DevelopBudgetRow[] }
  | { state: "missing" }
  | { state: "failed"; error: string }
  | { state: "unconfigured" };

export async function loadDevelop(topicId: string): Promise<DevelopLoad> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const [st, bd] = await Promise.all([
    db.rpc("drinks_develop_status", { p: { topic_id: topicId } }),
    fetchAllPages<DevelopBudgetRow>((f, to) => db.from("drink_develop_budget_state").select("*", { count: "exact" })
      .eq("status", "open").order("expires_at", { ascending: false }).order("budget_id").range(f, to), "개발 결재"),
  ]);
  if (st.error) return isSchemaMissing(st.error) ? { state: "missing" } : { state: "failed", error: `개발 요청: ${st.error.message}` };
  if (!bd.ok) return isSchemaMissing({ message: bd.error }) ? { state: "missing" } : { state: "failed", error: bd.error };
  const raw = st.data as unknown;
  const list = Array.isArray(raw) ? raw : (raw as { requests?: unknown } | null)?.requests;
  if (!Array.isArray(list)) return { state: "failed", error: "개발 요청: 응답 모양이 배열이 아닙니다" };
  return { state: "ok", requests: list as DevelopRequestRow[], budgets: bd.rows };
}
