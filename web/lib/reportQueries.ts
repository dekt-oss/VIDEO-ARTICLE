// 리포트 팩토리 읽기 쿼리. lib/queries.ts(논문)의 report_* 미러.
// report_scores/report_decisions 는 report_id PK(1:1)지만 PostgREST 중첩 편차를 피해 JS 조인.
import type { SupabaseClient } from "@supabase/supabase-js";
// ★ id 목록 조회는 selectIn, 전체 목록은 selectAll. 이유·실측 임계치는
//   web/lib/supabase/chunked.ts (헤더 오버플로 + 1,000행 상한).
import { selectIn, selectAll } from "./supabase/chunked";
import type { Directive, DirectiveStatus, VersionType } from "./types";
import type { DirectiveStatusMap } from "./queries";
import type {
  ReportCandidate,
  ReportSortMode,
  PickedReport,
  ReportDraft,
  ReportDraftListItem,
  PublishedReport,
  RawReport,
  ScoredReport,
  ReportRenderJob,
} from "./reportTypes";

// 존재하는 배치 날짜(중복 제거, 최신순). /finance 일자 네비게이션용.
export async function getReportBatchDates(supabase: SupabaseClient): Promise<string[]> {
  const { data } = await supabase
    .from("report_daily_batch")
    .select("batch_date")
    .order("batch_date", { ascending: false });
  const seen: string[] = [];
  for (const r of data ?? []) {
    if (!seen.includes(r.batch_date)) seen.push(r.batch_date);
  }
  return seen;
}

// 운영자가 "확인 완료"로 표시한 리포트 배치일 집합. 홈이 미확인 일자부터 보여주는 기준.
export async function getReportReviewedDates(supabase: SupabaseClient): Promise<Set<string>> {
  const { data } = await supabase.from("report_batch_review").select("batch_date");
  return new Set((data ?? []).map((r) => r.batch_date));
}

// 주어진 날짜 바로 이전(더 오래된) 배치의 report id 집합 — NEW 판정 기준선.
async function previousReportBatchIds(
  supabase: SupabaseClient,
  batchDate: string
): Promise<Set<string>> {
  const { data: prev } = await supabase
    .from("report_daily_batch")
    .select("batch_date")
    .lt("batch_date", batchDate)
    .order("batch_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!prev?.batch_date) return new Set();
  const { data } = await supabase
    .from("report_daily_batch")
    .select("report_id")
    .eq("batch_date", prev.batch_date);
  return new Set((data ?? []).map((b) => b.report_id));
}

export async function getReportCandidates(
  supabase: SupabaseClient,
  batchDate: string
): Promise<ReportCandidate[]> {
  const { data: batch } = await supabase
    .from("report_daily_batch")
    .select("report_id, rank, sort_mode")
    .eq("batch_date", batchDate);

  if (!batch || batch.length === 0) return [];
  const ids = batch.map((b) => b.report_id);

  const [reports, scores, decisions, prevIds] = await Promise.all([
    selectIn<Record<string, any> & { id: string }>(
      ids,
      (c) => supabase
        .from("reports")
        .select(
          "id, external_id, title, theme, company, ticker, broker, target_price, opinion, report_url, signal_level, is_risk, aria_priority"
        )
        .in("id", c),
      "reports.id"),
    selectIn<Record<string, any> & { report_id: string }>(
      ids,
      (c) => supabase
        .from("report_scores")
        .select(
          "report_id, title_ko, one_liner_ko, angle, risk_note, interest_index, story_index, safety_index, timeliness, story, safety"
        )
        .in("report_id", c),
      "report_scores.report_id"),
    selectIn<{ report_id: string; status: string }>(
      ids, (c) => supabase.from("report_decisions").select("report_id, status").in("report_id", c),
      "report_decisions.report_id"),
    previousReportBatchIds(supabase, batchDate),
  ]);

  const reportMap = new Map(reports.map((r) => [r.id, r]));
  const scoreMap = new Map(scores.map((s) => [s.report_id, s]));
  const decMap = new Map(decisions.map((d) => [d.report_id, d.status]));

  return batch
    .map((b): ReportCandidate | null => {
      const r = reportMap.get(b.report_id);
      if (!r) return null;
      const s = scoreMap.get(b.report_id);
      return {
        report_id: b.report_id,
        external_id: r.external_id,
        title: r.title,
        title_ko: s?.title_ko ?? null,
        theme: r.theme ?? null,
        company: r.company ?? null,
        ticker: r.ticker ?? null,
        broker: r.broker ?? null,
        target_price: r.target_price ?? null,
        opinion: r.opinion ?? null,
        report_url: r.report_url ?? null,
        signal_level: r.signal_level ?? null,
        is_risk: !!r.is_risk,
        aria_priority: r.aria_priority ?? null,
        one_liner_ko: s?.one_liner_ko ?? null,
        angle: s?.angle ?? null,
        risk_note: s?.risk_note ?? null,
        interest_index: s?.interest_index ?? null,
        story_index: s?.story_index ?? null,
        safety_index: s?.safety_index ?? null,
        timeliness: s?.timeliness ?? null,
        story: s?.story ?? null,
        safety: s?.safety ?? null,
        rank: b.rank,
        sort_mode: b.sort_mode as ReportSortMode,
        decision_status: (decMap.get(b.report_id) as ReportCandidate["decision_status"]) ?? null,
        is_new: !prevIds.has(b.report_id),
      };
    })
    .filter((c): c is ReportCandidate => c !== null);
}

// ── PF1 / 데이터 화면 쿼리 (논문 queries.ts P1 미러) ──

// ④ 검수 목록: 낙점된 리포트 + 초안/요청 상태 + 컴플라이언스 차단 여부.
export async function getPickedReports(supabase: SupabaseClient): Promise<PickedReport[]> {
  const { data: decisions } = await supabase
    .from("report_decisions")
    .select("report_id, decided_at")
    .eq("status", "picked")
    .order("decided_at", { ascending: false });
  const ids = (decisions ?? []).map((d) => d.report_id);
  if (ids.length === 0) return [];

  const [reports, drafts, reqs] = await Promise.all([
    selectIn<Record<string, any> & { id: string }>(
      ids, (c) => supabase.from("reports").select("id, external_id, title, company, theme").in("id", c),
      "reports.id"),
    selectIn<{ report_id: string; compliance: { blocked?: boolean } | null }>(
      ids, (c) => supabase.from("report_drafts").select("report_id, compliance").in("report_id", c),
      "report_drafts.report_id"),
    selectIn<{ report_id: string; status: string; requested_at: string }>(
      ids,
      (c) => supabase.from("report_draft_requests").select("report_id, status, requested_at").in("report_id", c),
      "report_draft_requests.report_id"),
  ]);
  const repMap = new Map(reports.map((r) => [r.id, r]));
  const scoreMap = new Map<string, string | null>();
  // title_ko 는 report_scores 에서.
  const scores = await selectIn<{ report_id: string; title_ko: string | null }>(
    ids, (c) => supabase.from("report_scores").select("report_id, title_ko").in("report_id", c),
    "report_scores.report_id");
  for (const s of scores) scoreMap.set(s.report_id, s.title_ko ?? null);
  const draftMap = new Map(drafts.map((d) => [d.report_id, d]));
  // 최신 요청 상태만.
  const reqMap = new Map<string, string>();
  for (const q of [...reqs].sort((a, b) => (a.requested_at < b.requested_at ? 1 : -1))) {
    if (!reqMap.has(q.report_id)) reqMap.set(q.report_id, q.status);
  }

  return (decisions ?? [])
    .map((d): PickedReport | null => {
      const r = repMap.get(d.report_id);
      if (!r) return null;
      const draft = draftMap.get(d.report_id);
      return {
        report_id: d.report_id,
        title: r.title,
        title_ko: scoreMap.get(d.report_id) ?? null,
        external_id: r.external_id,
        company: r.company ?? null,
        theme: r.theme ?? null,
        has_draft: !!draft,
        blocked: draft ? !!draft.compliance?.blocked : null,
        request_status: reqMap.get(d.report_id) ?? null,
        decided_at: d.decided_at ?? null,
      };
    })
    .filter((p): p is PickedReport => p !== null);
}

export async function getReportDraft(
  supabase: SupabaseClient,
  reportId: string
): Promise<ReportDraft | null> {
  const { data } = await supabase
    .from("report_drafts")
    .select("report_id, fact_sheet, upload_title_ko, upload_title_en, script_md, scenes, self_check, compliance, story_plan, evidence, validated_script_hash, updated_at")
    .eq("report_id", reportId)
    .maybeSingle();
  return (data as ReportDraft | null) ?? null;
}

export async function getReportDraftList(supabase: SupabaseClient): Promise<ReportDraftListItem[]> {
  const drafts = await selectAll<{ report_id: string; compliance: { blocked?: boolean } | null; created_at: string }>(
    (from, to) => supabase
      .from("report_drafts")
      .select("report_id, compliance, created_at")
      .order("created_at", { ascending: false })
      .range(from, to),
    "report_drafts.all");
  const ids = drafts.map((d) => d.report_id);
  if (ids.length === 0) return [];
  const [reports, scores, published] = await Promise.all([
    selectIn<{ id: string; title: string }>(
      ids, (c) => supabase.from("reports").select("id, title").in("id", c), "reports.id"),
    selectIn<{ report_id: string; title_ko: string | null }>(
      ids, (c) => supabase.from("report_scores").select("report_id, title_ko").in("report_id", c),
      "report_scores.report_id"),
    selectIn<{ report_id: string }>(
      ids, (c) => supabase.from("report_published").select("report_id").in("report_id", c),
      "report_published.report_id"),
  ]);
  const repMap = new Map(reports.map((r) => [r.id, r.title]));
  const koMap = new Map(scores.map((s) => [s.report_id, s.title_ko]));
  const pubSet = new Set(published.map((p) => p.report_id));
  return drafts.map((d) => ({
    report_id: d.report_id,
    title: repMap.get(d.report_id) ?? "(제목 없음)",
    title_ko: koMap.get(d.report_id) ?? null,
    created_at: d.created_at,
    published: pubSet.has(d.report_id),
    blocked: !!d.compliance?.blocked,
  }));
}

export async function getPublishedReports(supabase: SupabaseClient): Promise<PublishedReport[]> {
  const pub = await selectAll<{ report_id: string; published_at: string }>(
    (from, to) => supabase
      .from("report_published")
      .select("report_id, published_at")
      .order("published_at", { ascending: false })
      .range(from, to),
    "report_published.all");
  const ids = pub.map((p) => p.report_id);
  if (ids.length === 0) return [];
  const reports = await selectIn<{ id: string; title: string }>(
    ids, (c) => supabase.from("reports").select("id, title").in("id", c), "reports.id");
  const repMap = new Map(reports.map((r) => [r.id, r.title]));
  return pub.map((p) => ({
    report_id: p.report_id,
    title: repMap.get(p.report_id) ?? "(제목 없음)",
    published_at: p.published_at,
  }));
}

// ① 수집 원자료: 전체 reports + 채점 여부.
export async function getAllReports(supabase: SupabaseClient): Promise<RawReport[]> {
  const reports = await selectAll<Record<string, any> & { id: string }>(
    (from, to) => supabase
      .from("reports")
      .select("id, external_id, title, theme, company, broker, signal_level, aria_priority, is_risk, report_url")
      .order("collected_at", { ascending: false })
      .range(from, to),
    "reports.all");
  const ids = reports.map((r) => r.id);
  // ★ 예전에는 이 조회가 통째로 죽어(헤더 오버플로) 전 리포트가 "미채점"으로 나갔다.
  const scores = await selectIn<{ report_id: string }>(
    ids, (c) => supabase.from("report_scores").select("report_id").in("report_id", c),
    "report_scores.report_id");
  const scoredSet = new Set(scores.map((s) => s.report_id));
  return reports.map((r) => ({
    report_id: r.id,
    external_id: r.external_id,
    title: r.title,
    theme: r.theme ?? null,
    company: r.company ?? null,
    broker: r.broker ?? null,
    signal_level: r.signal_level ?? null,
    aria_priority: r.aria_priority ?? null,
    is_risk: !!r.is_risk,
    report_url: r.report_url ?? null,
    scored: scoredSet.has(r.id),
  }));
}

// ② 채점 결과: report_scores + reports + 배치 편성 + 결정 상태.
export async function getScoredReports(supabase: SupabaseClient): Promise<ScoredReport[]> {
  // ★ 이 화면이 로컬에서 "채점 결과가 없습니다" 로 나오던 자리다 — reports 조회가 헤더
  //   오버플로로 죽으면 repMap 이 비고, 아래 `if (!r) return null` 이 **전 행을 버린다**.
  //   화면은 그것을 "엔진을 실행하세요" 로 안내했다(정반대의 지시).
  const scores = await selectAll<Record<string, any> & { report_id: string }>(
    (from, to) => supabase
      .from("report_scores")
      .select("report_id, title_ko, timeliness, explainability, story, safety, interest_index, story_index, safety_index, angle, risk_note")
      .order("interest_index", { ascending: false })
      .range(from, to),
    "report_scores.all");
  const ids = scores.map((s) => s.report_id);
  if (ids.length === 0) return [];
  const [reports, batch, decisions] = await Promise.all([
    selectIn<Record<string, any> & { id: string }>(
      ids, (c) => supabase.from("reports").select("id, title, theme, company").in("id", c),
      "reports.id"),
    selectIn<{ report_id: string }>(
      ids, (c) => supabase.from("report_daily_batch").select("report_id").in("report_id", c),
      "report_daily_batch.report_id"),
    selectIn<{ report_id: string; status: string }>(
      ids, (c) => supabase.from("report_decisions").select("report_id, status").in("report_id", c),
      "report_decisions.report_id"),
  ]);
  const repMap = new Map(reports.map((r) => [r.id, r]));
  const batchSet = new Set(batch.map((b) => b.report_id));
  const decMap = new Map(decisions.map((d) => [d.report_id, d.status]));
  return scores
    .map((s): ScoredReport | null => {
      const r = repMap.get(s.report_id);
      if (!r) return null;
      return {
        report_id: s.report_id,
        title: r.title,
        title_ko: s.title_ko ?? null,
        theme: r.theme ?? null,
        company: r.company ?? null,
        timeliness: s.timeliness ?? null,
        explainability: s.explainability ?? null,
        story: s.story ?? null,
        safety: s.safety ?? null,
        interest_index: s.interest_index ?? null,
        story_index: s.story_index ?? null,
        safety_index: s.safety_index ?? null,
        angle: s.angle ?? null,
        risk_note: s.risk_note ?? null,
        in_batch: batchSet.has(s.report_id),
        decision_status: (decMap.get(s.report_id) as ScoredReport["decision_status"]) ?? null,
      };
    })
    .filter((s): s is ScoredReport => s !== null);
}

// ── PF2 영상화 쿼리 (지시서/렌더) ──

// ⑤ 리포트의 최신 지시서(단일 comic). 없으면 null.
/** 리포트별 최신 지시서 상태맵 — 홈 "다음 작업" 판정용(queries.getDirectiveStatusMap 미러). */
export async function getReportDirectiveStatusMap(
  supabase: SupabaseClient,
  reportIds: string[]
): Promise<Map<string, DirectiveStatusMap>> {
  const out = new Map<string, DirectiveStatusMap>();
  if (reportIds.length === 0) return out;
  // 청크로 쪼개도 "정렬 후 리포트별 첫 행" 규칙은 안전하다 — 묶는 키가 곧 청크 기준이다.
  const data = await selectIn<{ report_id: string; version_type: string; status: string }>(
    reportIds,
    (c) => supabase
      .from("report_directives")
      .select("report_id, version_type, status, created_at")
      .in("report_id", c)
      .order("created_at", { ascending: false }),
    "report_directives.report_id");
  for (const d of data) {
    let m = out.get(d.report_id);
    if (!m) {
      m = {};
      out.set(d.report_id, m);
    }
    const v = d.version_type as VersionType;
    if (!m[v]) m[v] = d.status as DirectiveStatus; // 최신만
  }
  return out;
}

/** 리포트 지시서 1건. `versionType` 을 주면 **그 버전의** 최신 지시서를 가져온다.
 *
 * ★ 버전을 안 주면 버전 무관 최신 1건이 온다 — 그러면 만화식과 설명판형을 나란히 만들 수 없다
 *   (설명판형을 만든 뒤 화면이 늘 설명판형만 보여줘 만화식 발주 경로가 사라진다). 논문 라인의
 *   `getLatestDirective(paperId, version)` 과 같은 계약으로 맞춘다.
 */
export async function getReportDirective(
  supabase: SupabaseClient,
  reportId: string,
  versionType?: string
): Promise<Directive | null> {
  let q = supabase
    .from("report_directives")
    .select("id, report_id, version_type, header, cuts, status, created_at, approved_at")
    .eq("report_id", reportId);
  if (versionType) q = q.eq("version_type", versionType);
  const { data } = await q
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!data) return null;
  return {
    id: data.id,
    paper_id: data.report_id, // Directive 타입 호환(리포트는 report_id 를 담음)
    version_type: data.version_type,
    header: data.header ?? null,
    cuts: data.cuts ?? [],
    status: data.status,
    created_at: data.created_at,
    approved_at: data.approved_at ?? null,
  };
}

const REPORT_RENDER_JOB_COLS =
  "id, directive_id, lang, status, progress, cost_estimate, output_url, error_log, created_at, finished_at, deleted_at, saved_at";

async function reportJoinRenderMeta(
  supabase: SupabaseClient,
  rows: Record<string, unknown>[]
): Promise<ReportRenderJob[]> {
  if (rows.length === 0) return [];
  const dirIds = rows.map((j) => j.directive_id as string);
  // ★ version_type 을 함께 가져온다. report_render_jobs 에는 버전 컬럼이 없어서, 이걸 빼면
  //   ⑥ 렌더 결과의 버전 뱃지가 전부 "?" 로 뜬다 — 만화식과 설명판형을 각각 렌더해 놓고도
  //   어느 영상이 어느 버전인지 화면에서 구분할 수 없다(비교가 불가능해진다).
  const directives = await selectIn<{ id: string; report_id: string; version_type: string }>(
    dirIds,
    (c) => supabase.from("report_directives").select("id, report_id, version_type").in("id", c),
    "report_directives.id");
  const dirMap = new Map(directives.map((d) => [d.id, d.report_id]));
  const versionMap = new Map(directives.map((d) => [d.id, d.version_type]));

  const reportIds = [...new Set(directives.map((d) => d.report_id))];
  const [reports, scores] = await Promise.all([
    selectIn<{ id: string; title: string }>(
      reportIds, (c) => supabase.from("reports").select("id, title").in("id", c), "reports.id"),
    selectIn<{ report_id: string; title_ko: string | null }>(
      reportIds, (c) => supabase.from("report_scores").select("report_id, title_ko").in("report_id", c),
      "report_scores.report_id"),
  ]);
  const titleMap = new Map(reports.map((r) => [r.id, r.title]));
  const koMap = new Map(scores.map((s) => [s.report_id, s.title_ko]));

  // 유튜브 업로드 상태(잡별). report_upload_requests 를 render_job_id 로 조인해 버튼·링크를 표시(논문 미러).
  const jobIds = rows.map((j) => j.id as string);
  const uploads = await selectIn<Record<string, unknown>>(
    jobIds,
    (c) => supabase
      .from("report_upload_requests")
      .select("render_job_id, status, youtube_url, error")
      .in("render_job_id", c),
    "report_upload_requests.render_job_id");
  const uploadMap = new Map<string, Record<string, unknown>>(
    uploads.map((u) => [String((u as Record<string, unknown>).render_job_id), u as Record<string, unknown>])
  );

  return rows.map((j): ReportRenderJob => {
    const rid = dirMap.get(j.directive_id as string);
    const up = uploadMap.get(j.id as string);
    return {
      ...(j as unknown as ReportRenderJob),
      version_type: versionMap.get(j.directive_id as string) ?? undefined,
      report_id: rid,
      title: rid ? titleMap.get(rid) ?? "(제목 없음)" : "(지시서 없음)",
      title_ko: rid ? koMap.get(rid) ?? null : null,
      youtube_status: (up?.status as ReportRenderJob["youtube_status"]) ?? null,
      youtube_url: (up?.youtube_url as string | null) ?? null,
      youtube_error: (up?.error as string | null) ?? null,
    };
  });
}

// ⑥ 리포트 렌더 잡 목록. scope: active(기본) | trash | all.
export async function getReportRenderJobs(
  supabase: SupabaseClient,
  opts?: { scope?: "active" | "trash" | "all" }
): Promise<ReportRenderJob[]> {
  const scope = opts?.scope ?? "active";
  let q = supabase.from("report_render_jobs").select(REPORT_RENDER_JOB_COLS);
  if (scope === "active") q = q.is("deleted_at", null);
  else if (scope === "trash") q = q.not("deleted_at", "is", null);
  const { data: jobs } = await q.order("created_at", { ascending: false });
  return reportJoinRenderMeta(supabase, jobs ?? []);
}

/**
 * 지금 워커에 걸려 있는 요청 상태("queued" | "processing" | null).
 *
 * ★ 왜 서버에서 읽나: 예전에는 진행 상태가 브라우저 메모리(useGeneration)에만 있었다.
 *   생성을 눌러 두고 새로고침하거나 다른 메뉴를 다녀오면 상세 화면이 "아직 초안이 없습니다"로
 *   돌아가, 운영자가 또 눌렀다. 목록 화면은 이미 이 값을 보여주고 있었는데 상세만 몰랐다.
 */
export type PendingStatus = "queued" | "processing" | null;

function latestPending(rows: { status: string | null }[] | null): PendingStatus {
  const s = rows?.[0]?.status ?? null;
  return s === "queued" || s === "processing" ? s : null;
}

/** ④ 리포트 초안 — 지금 생성/재검사 대기 중인가. */
export async function getReportDraftPending(
  supabase: SupabaseClient,
  reportId: string
): Promise<PendingStatus> {
  const { data } = await supabase
    .from("report_draft_requests")
    .select("status, requested_at")
    .eq("report_id", reportId)
    .in("status", ["queued", "processing"])
    .order("requested_at", { ascending: false })
    .limit(1);
  return latestPending(data);
}

/** ⑤ 리포트 지시서 — 이 버전이 지금 생성 대기 중인가. */
export async function getReportDirectivePending(
  supabase: SupabaseClient,
  reportId: string,
  versionType: string
): Promise<PendingStatus> {
  const { data } = await supabase
    .from("report_directive_requests")
    .select("status, requested_at")
    .eq("report_id", reportId)
    .eq("version_type", versionType)
    .in("status", ["queued", "processing"])
    .order("requested_at", { ascending: false })
    .limit(1);
  return latestPending(data);
}
