// 소재 고르기(/drinks/topics) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
//   후보는 서버 쪽 페이지(range) + 서버 조건(형식 적합성)으로 읽는다 — 소재 발견함(discoveryQueries)의 "점수 높은 300건" 과 달리
//   전체 건수(count exact)와 이번 쪽만 받는다. 근거 수는 보이는 쪽만 센다(0064 RPC, 상한 EVIDENCE_MAX_CANDIDATES).
//   조회 실패 / 부분 조회(근거 수·결재를 못 읽음) / 수집 미실행 / 정상 0건을 화면이 가르도록 각각 다른 칸에 담는다.
import { createAdminClient } from "@/lib/supabase/admin";
import type { CandidateRow } from "@/lib/drinks/discovery";
import type { DevelopBudgetRow } from "@/lib/drinks/develop";
import { EVIDENCE_MAX_CANDIDATES } from "@/lib/drinks/formatRecommend";
import { FORMAT_FIT_MIN, type Loaded } from "@/lib/drinks/model";
import { withOfficialHits } from "@/lib/drinks/officialSources";
import { fetchAllIn } from "@/lib/drinks/paging";
import type { TopicRow } from "@/lib/drinks/types";

export const TOPICS_PAGE_SIZE = 20;
export type FitFilter = "" | "video" | "carousel";

export interface TopicsCandidatesView {
  candidates: CandidateRow[];
  /** 조건에 맞는 전체 건수(정확) */
  total: number;
  page: number;
  pageSize: number;
  /** 후보별 근거 수(보이는 쪽만). null = RPC 를 못 읽음(부분 조회) — 화면은 "모름"이라고 말한다 */
  evidence: Map<string, { count: number; chars: number }> | null;
  /** 쓸 수 있는 개발 결재. null = 못 읽음(부분 조회) */
  budgets: DevelopBudgetRow[] | null;
  /** 중복 후보 소재의 제목(링크용) */
  topics: Map<string, Pick<TopicRow, "id" | "title" | "status">>;
  /** 발견 수집이 한 번이라도 돌았는가. "never" 면 0건은 정상 0건이 아니라 수집 전이다 */
  collection: "ran" | "never" | "unknown";
  /** 부분 조회 사유(비어 있으면 완전 조회) */
  partial: string[];
}

export interface CandidateFilter {
  statuses: readonly string[];
  page: number;
  fit?: FitFilter;
}

export async function loadTopicCandidates(f: CandidateFilter): Promise<Loaded<TopicsCandidatesView>> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const page = Math.max(1, Math.floor(f.page) || 1);
  const from = (page - 1) * TOPICS_PAGE_SIZE;
  let q = db.from("drink_discovery_candidates").select("*", { count: "exact" }).in("status", [...f.statuses]);
  // 형식 필터는 서버 조건이다 — 화면에서 거르면 쪽수·전체 건수가 거짓이 된다.
  if (f.fit === "video") q = q.gte("fit_video", FORMAT_FIT_MIN);
  if (f.fit === "carousel") q = q.gte("fit_carousel", FORMAT_FIT_MIN);
  const c = await q.order("provisional_score", { ascending: false, nullsFirst: false }).order("id").range(from, from + TOPICS_PAGE_SIZE - 1);
  if (c.error || !c.data || typeof c.count !== "number") return { state: "failed", error: `후보: ${c.error?.message ?? "응답 없음"}` };
  const cands = c.data as CandidateRow[];
  const partial: string[] = [];

  const dupIds = cands.flatMap((x) => x.duplicate_topic_ids ?? []);
  const topics = new Map<string, Pick<TopicRow, "id" | "title" | "status">>();
  if (dupIds.length > 0) {
    const t = await fetchAllIn<Pick<TopicRow, "id" | "title" | "status">>(dupIds, (ids, a, b) => db.from("drink_topics")
      .select("id, title, status", { count: "exact" }).in("id", ids).order("id").range(a, b), "중복 소재");
    if (!t.ok) return { state: "failed", error: t.error };
    for (const r of t.rows) topics.set(r.id, r);
  }

  // 수집이 한 번도 안 돌았으면 0건은 "수집 전"이다. 발견 수집원이 없거나 그 실행 기록이 없으면 never.
  let collection: TopicsCandidatesView["collection"] = "unknown";
  const srcs = await db.from("drink_sources").select("id").eq("purpose", "discovery").range(0, 199);
  if (srcs.error || !srcs.data) partial.push(`발견 수집원: ${srcs.error?.message ?? "응답 없음"}`);
  else if (srcs.data.length === 0) collection = "never";
  else {
    const runs = await db.from("drink_collection_runs").select("id", { count: "exact", head: true })
      .in("source_id", (srcs.data as { id: string }[]).map((s) => s.id));
    if (runs.error || typeof runs.count !== "number") partial.push(`발견 실행 기록: ${runs.error?.message ?? "건수 없음"}`);
    else collection = runs.count > 0 ? "ran" : "never";
  }

  let evidence: TopicsCandidatesView["evidence"] = null;
  let budgets: TopicsCandidatesView["budgets"] = null;
  if (f.statuses.includes("suggested") && cands.length > 0) {
    const ev = await db.rpc("drinks_candidate_evidence_counts", { p: { candidate_ids: cands.slice(0, EVIDENCE_MAX_CANDIDATES).map((x) => x.id) } });
    if (ev.error || !ev.data || typeof ev.data !== "object") partial.push(`근거 수: ${ev.error?.message ?? "응답 없음"} — 추천 형식은 '모름'으로 보입니다`);
    else {
      evidence = new Map();
      for (const [k, v] of Object.entries(ev.data as Record<string, { count: number; chars: number }>)) {
        evidence.set(k, { count: Number(v.count), chars: Number(v.chars) });
      }
      for (const x of cands) {
        const merged = withOfficialHits(evidence.get(x.id), x.key_question);
        if (merged) evidence.set(x.id, merged);
      }
    }
  }
  if (f.statuses.includes("suggested")) {
    const bd = await db.from("drink_develop_budget_state").select("*").eq("status", "open").order("expires_at", { ascending: false }).limit(20);
    if (bd.error || !bd.data) partial.push(`개발 결재: ${bd.error?.message ?? "응답 없음"} — 결재 유무를 모릅니다`);
    else budgets = bd.data as DevelopBudgetRow[];
  }

  return { state: "ok", data: { candidates: cands, total: c.count, page, pageSize: TOPICS_PAGE_SIZE, evidence, budgets, topics, collection, partial } };
}

/** 홈 막힘 목록용: 열린 개발 결재. 못 읽으면 null(없는 것이 아니다). */
export async function loadOpenBudgets(): Promise<DevelopBudgetRow[] | null> {
  const db = createAdminClient();
  if (!db) return null;
  const r = await db.from("drink_develop_budget_state").select("*").eq("status", "open").order("expires_at", { ascending: false }).limit(20);
  return r.error || !r.data ? null : (r.data as DevelopBudgetRow[]);
}

/** 홈 타일용: 열린 후보 전체 건수만. 못 읽으면 null(0 이 아니다). */
export async function countOpenCandidates(): Promise<number | null> {
  const db = createAdminClient();
  if (!db) return null;
  const r = await db.from("drink_discovery_candidates").select("id", { count: "exact", head: true }).eq("status", "suggested");
  return r.error || typeof r.count !== "number" ? null : r.count;
}
