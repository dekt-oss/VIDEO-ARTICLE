// 밈 제작(0066) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 0066 이 운영 DB 에 아직 없으면 'missing' — 밈 보드 나머지는 그대로 보이고, 이 칸만 "적용 전"이라고 말한다.
import { createAdminClient } from "@/lib/supabase/admin";
import { fetchAllPages } from "@/lib/drinks/paging";
import { isMissingMemeTables, type MemeBudgetRow, type MemeDraftRow, type MemePickRow, type MemeReviewOption } from "@/lib/drinks/meme";

export interface MemeWork {
  drafts: MemeDraftRow[];
  picks: MemePickRow[];
  budgets: MemeBudgetRow[];
  reviews: MemeReviewOption[];
  /** 파일 role → 서명 주소. 만들지 못하면 그 파일 항목이 없다. */
  urls: Record<string, Record<string, string>>;
}
export type MemeWorkLoaded = { state: "ok"; data: MemeWork } | { state: "missing" } | { state: "failed"; error: string } | { state: "unconfigured" };

interface PickJoin { topic_id: string; drink_topics: { title: string | null; question: string | null } | { title: string | null; question: string | null }[] | null }
interface ReviewJoin { id: string; evidence_pack: { claims?: { claim_id: string; text?: string }[] } | null; drink_topics: { title: string | null } | { title: string | null }[] | null }

const one = <T,>(x: T | T[] | null): T | null => (Array.isArray(x) ? x[0] ?? null : x);

export async function loadMemeWork(): Promise<MemeWorkLoaded> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const drafts = await fetchAllPages<MemeDraftRow>((f, to) => db.from("drink_meme_board").select("*", { count: "exact" })
    .order("created_at", { ascending: false }).order("id").range(f, to), "밈 제작안");
  if (!drafts.ok) return isMissingMemeTables(drafts.error) ? { state: "missing" } : { state: "failed", error: drafts.error };
  const [picks, budgets, reviews] = await Promise.all([
    fetchAllPages<PickJoin>((f, to) => db.from("drink_topic_picks").select("topic_id, drink_topics(title, question)", { count: "exact" })
      .eq("format_intent", "meme").order("topic_id").range(f, to), "밈 소재"),
    fetchAllPages<MemeBudgetRow>((f, to) => db.from("drink_develop_budget_state").select("budget_id, stage, remaining_usd", { count: "exact" })
      .eq("status", "open").eq("expired", false).order("budget_id").range(f, to), "개발 결재"),
    fetchAllPages<ReviewJoin>((f, to) => db.from("drink_topic_reviews").select("id, evidence_pack, drink_topics!drink_topic_reviews_topic_id_fkey(title)", { count: "exact" })
      .eq("status", "approved").is("revoked_at", null).order("id").range(f, to), "승인된 근거"),
  ]);
  if (!picks.ok) return { state: "failed", error: picks.error };
  if (!budgets.ok) return { state: "failed", error: budgets.error };
  if (!reviews.ok) return { state: "failed", error: reviews.error };
  const urls: Record<string, Record<string, string>> = {};
  for (const d of drafts.rows) {
    for (const file of d.files ?? []) {
      if (file.role === "guide" || file.storage_key.startsWith("local:")) continue;
      const s = await db.storage.from("drinks").createSignedUrl(file.storage_key, 3600);
      if (!s.error && s.data?.signedUrl) (urls[d.id] ??= {})[file.role] = s.data.signedUrl;
    }
  }
  return {
    state: "ok",
    data: {
      drafts: drafts.rows.map((d) => ({ ...d, files: d.files ?? [], blockers: d.blockers ?? [], version: Number(d.version) })),
      picks: picks.rows.map((p) => ({ topic_id: p.topic_id, title: one(p.drink_topics)?.title ?? null, question: one(p.drink_topics)?.question ?? null })),
      budgets: budgets.rows.map((b) => ({ ...b, remaining_usd: Number(b.remaining_usd) })),
      reviews: reviews.rows.map((r) => ({
        review_id: r.id, title: one(r.drink_topics)?.title ?? null,
        claims: (r.evidence_pack?.claims ?? []).map((c) => ({ claim_id: c.claim_id, text: c.text ?? "" })),
      })),
      urls,
    },
  };
}
