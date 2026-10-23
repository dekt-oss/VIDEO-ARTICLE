// 주류 제작(0053) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 미리보기: Supabase 비공개 버킷 'drinks' 의 파일은 서버가 1시간짜리 서명 URL 을 만든다.
//   로컬 검증 저장(local:…)은 브라우저로 열 수 없다 — 화면이 그 사실을 말한다.
import { createAdminClient } from "@/lib/supabase/admin";
import type { Loaded } from "@/lib/drinks/model";
import { fetchAllIn, fetchAllPages } from "@/lib/drinks/paging";
import type { PlanRow, ReviewRow, TopicRow } from "@/lib/drinks/types";

export interface ProdJobRow {
  id: string; format: "video" | "carousel"; status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  attempt_no: number; retry_of: string | null; input_hash: string; renderer: string; renderer_version: string;
  lease_expires_at: string | null; cancel_requested: boolean; error_code: string | null; error_message: string | null;
  result_manifest_id: string | null; created_at: string; started_at: string | null; finished_at: string | null;
}
export interface ManifestRow { id: string; job_id: string; format: string; manifest_hash: string; input_hash: string; created_at: string }
export interface MediaRow {
  id: string; storage_key: string; sha256: string; mime: string; bytes: number; width: number | null; height: number | null;
  duration_ms: number | null; rights: string; provenance: Record<string, unknown>; state: string;
}
export interface OutputReviewRow {
  id: string; manifest_id: string; status: "pending" | "approved" | "changes_requested" | "blocked"; qa_summary: Record<string, unknown>;
  checklist: Record<string, boolean> | null; reviewer: string | null; reviewed_at: string | null; reason: string | null; version: number;
}
export interface CostRow { id: number; job_id: string; kind: string; provider: string; model: string | null; cost_usd: string | number; estimated: boolean }

export interface ManifestView {
  manifest: ManifestRow;
  files: (MediaRow & { role: string; position: number; url: string | null; urlError: string | null })[];
  review: OutputReviewRow | null;
  currentBlock: string | null;
  currentlyUsable: boolean;
}

export interface PlanProduction {
  plan: PlanRow;
  topic: Pick<TopicRow, "id" | "title" | "question" | "status">;
  review: Pick<ReviewRow, "id" | "revision_no" | "status" | "revoked_at"> & { currently_valid?: boolean };
  renderable: string | null;
  jobs: ProdJobRow[];
  manifests: ManifestView[];
  costs: CostRow[];
}

export async function loadPlanProduction(planId: string): Promise<Loaded<PlanProduction> | { state: "not_found" }> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  if (!/^[0-9a-f-]{36}$/i.test(planId)) return { state: "not_found" };
  const p = await db.from("drink_plan_revisions").select("*").eq("id", planId).maybeSingle();
  if (p.error) return { state: "failed", error: `제작안: ${p.error.message}` };
  if (!p.data) return { state: "not_found" };
  const plan = p.data as PlanRow;
  const [t, rv, va, ren, jobs, mans] = await Promise.all([
    db.from("drink_topics").select("id, title, question, status").eq("id", plan.topic_id).maybeSingle(),
    db.from("drink_topic_reviews").select("id, revision_no, status, revoked_at").eq("id", plan.topic_review_id).maybeSingle(),
    db.from("drink_review_validity").select("currently_valid").eq("review_id", plan.topic_review_id).maybeSingle(),
    db.rpc("drinks_plan_render_state", { p: { plan_revision_id: planId } }),
    fetchAllPages<ProdJobRow>((f, to) => db.from("drink_production_jobs").select("*", { count: "exact" }).eq("plan_revision_id", planId)
      .order("created_at", { ascending: false }).order("id").range(f, to), "제작 작업"),
    fetchAllPages<ManifestRow>((f, to) => db.from("drink_asset_manifests").select("*", { count: "exact" }).eq("plan_revision_id", planId)
      .order("created_at", { ascending: false }).order("id").range(f, to), "파일 묶음"),
  ]);
  for (const r of [t, rv, va, ren]) if (r.error) return { state: "failed", error: r.error.message };
  if (!t.data || !rv.data) return { state: "failed", error: "소재·근거 버전 조회 누락" };
  if (!jobs.ok) return { state: "failed", error: jobs.error };
  if (!mans.ok) return { state: "failed", error: mans.error };
  const mids = mans.rows.map((m) => m.id);
  const [links, reviews, validity, costs] = await Promise.all([
    fetchAllIn<{ manifest_id: string; asset_id: string; role: string; position: number }>(mids, (c, f, to) => db.from("drink_manifest_assets")
      .select("*", { count: "exact" }).in("manifest_id", c).order("manifest_id").order("role").order("position").range(f, to), "묶음 파일"),
    fetchAllIn<OutputReviewRow>(mids, (c, f, to) => db.from("drink_output_reviews").select("*", { count: "exact" }).in("manifest_id", c)
      .order("id").range(f, to), "검수"),
    fetchAllIn<{ manifest_id: string; current_block: string | null; currently_usable: boolean }>(mids, (c, f, to) => db.from("drink_output_validity")
      .select("manifest_id, current_block, currently_usable", { count: "exact" }).in("manifest_id", c).order("manifest_id").range(f, to), "현재 사용 가능"),
    fetchAllIn<CostRow>(jobs.rows.map((j) => j.id), (c, f, to) => db.from("drink_cost_entries").select("*", { count: "exact" }).in("job_id", c)
      .order("id").range(f, to), "비용"),
  ]);
  for (const r of [links, reviews, validity, costs]) if (!r.ok) return { state: "failed", error: (r as { error: string }).error };
  const linkRows = (links as { ok: true; rows: { manifest_id: string; asset_id: string; role: string; position: number }[] }).rows;
  const media = await fetchAllIn<MediaRow>(linkRows.map((l) => l.asset_id), (c, f, to) => db.from("drink_media_assets")
    .select("*", { count: "exact" }).in("id", c).order("id").range(f, to), "파일");
  if (!media.ok) return { state: "failed", error: media.error };
  const mediaById = new Map(media.rows.map((m) => [m.id, m]));
  const urls = new Map<string, string | null>();
  const urlErrors = new Map<string, string>();
  for (const m of media.rows) {
    if (m.storage_key.startsWith("local:") || m.state !== "stored") { urls.set(m.id, null); continue; }
    const s = await db.storage.from("drinks").createSignedUrl(m.storage_key, 3600);
    urls.set(m.id, s.error ? null : s.data?.signedUrl ?? null);
    if (s.error || !s.data?.signedUrl) urlErrors.set(m.id, s.error?.message ?? "서명 URL 없음");
  }
  const revBy = new Map((reviews as { ok: true; rows: OutputReviewRow[] }).rows.map((r) => [r.manifest_id, r]));
  const valBy = new Map((validity as { ok: true; rows: { manifest_id: string; current_block: string | null; currently_usable: boolean }[] }).rows
    .map((v) => [v.manifest_id, v]));
  const manifests: ManifestView[] = mans.rows.map((m) => ({
    manifest: m,
    files: linkRows.filter((l) => l.manifest_id === m.id).map((l) => ({ ...mediaById.get(l.asset_id)!, role: l.role, position: l.position,
      url: urls.get(l.asset_id) ?? null, urlError: urlErrors.get(l.asset_id) ?? null })).sort((a, b) => (a.role === b.role ? a.position - b.position : a.role.localeCompare(b.role))),
    review: revBy.get(m.id) ?? null,
    currentBlock: valBy.get(m.id)?.current_block ?? null,
    currentlyUsable: valBy.get(m.id)?.currently_usable === true,
  }));
  return {
    state: "ok",
    data: {
      plan, topic: t.data as PlanProduction["topic"],
      review: { ...(rv.data as PlanProduction["review"]), currently_valid: (va.data as { currently_valid?: boolean } | null)?.currently_valid },
      renderable: (ren.data as { block: string | null } | null)?.block ?? null, jobs: jobs.rows, manifests, costs: (costs as { ok: true; rows: CostRow[] }).rows,
    },
  };
}
