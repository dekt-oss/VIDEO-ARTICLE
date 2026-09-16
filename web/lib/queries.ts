// daily_batch + papers + scores + decisions 를 조합해 오늘의 후보를 만든다.
// scores/decisions 는 paper_id PK(1:1)지만 PostgREST 중첩 형태 편차를 피하려 JS 에서 조인한다.
import type { SupabaseClient } from "@supabase/supabase-js";
import type {
  Candidate,
  Directive,
  DirectiveStatus,
  Draft,
  DraftListItem,
  PickedPaper,
  PublishedItem,
  RawPaper,
  RenderJob,
  ScoredPaper,
  VersionType,
} from "./types";
import { sourceFrom, buildPublishCaption } from "./publishCaption";
// ★ id 목록 조회는 반드시 selectIn 을 쓴다 — 300개를 넘기면 응답 헤더 오버플로로 fetch 가
//   통째로 죽고, 호출부가 error 를 버리면 "데이터 없음"과 구별되지 않는다.
//   전체 목록 조회는 selectAll — PostgREST 가 1,000행에서 조용히 자른다.
//   근거·실측 임계치: web/lib/supabase/chunked.ts
import { selectIn, selectAll } from "./supabase/chunked";
import { PRODUCTION_LEGACY_SCORE_MAX } from "@/lib/blockLabels";

// paper_id → 버전별 최신 지시서 상태. 지시서 목록·탭 뱃지용.
export type DirectiveStatusMap = Partial<Record<VersionType, DirectiveStatus>>;

export async function getDirectiveStatusMap(
  supabase: SupabaseClient,
  paperIds: string[]
): Promise<Map<string, DirectiveStatusMap>> {
  const out = new Map<string, DirectiveStatusMap>();
  if (paperIds.length === 0) return out;
  // created_at 내림차순으로 받아 각 (paper, version) 의 첫 행(=최신)만 채택.
  // ★ 청크로 쪼개도 이 "정렬 후 첫 행" 규칙은 안전하다 — 묶는 키(paper_id)가 곧 청크 기준이라
  //   한 논문의 행들은 반드시 같은 청크 안에 있고, 그 안에서 정렬이 유지된다.
  const data = await selectIn<{ paper_id: string; version_type: string; status: string }>(
    paperIds,
    (c) => supabase
      .from("directives")
      .select("paper_id, version_type, status, created_at")
      .in("paper_id", c)
      .order("created_at", { ascending: false }),
    "directives.paper_id",
  );
  for (const d of data) {
    let m = out.get(d.paper_id);
    if (!m) {
      m = {};
      out.set(d.paper_id, m);
    }
    const v = d.version_type as VersionType;
    if (!m[v]) m[v] = d.status as DirectiveStatus; // 최신만
  }
  return out;
}

export async function getLatestBatchDate(supabase: SupabaseClient): Promise<string | null> {
  const { data } = await supabase
    .from("daily_batch")
    .select("batch_date")
    .order("batch_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  return data?.batch_date ?? null;
}

// 존재하는 배치 날짜(중복 제거, 최신순). 홈의 일자 네비게이션용.
export async function getBatchDates(supabase: SupabaseClient): Promise<string[]> {
  const { data } = await supabase
    .from("daily_batch")
    .select("batch_date")
    .order("batch_date", { ascending: false });
  const seen: string[] = [];
  for (const r of data ?? []) {
    if (!seen.includes(r.batch_date)) seen.push(r.batch_date);
  }
  return seen;
}

// 운영자가 "확인 완료"로 표시한 배치일 집합. 홈이 미확인 일자부터 보여주는 기준.
export async function getReviewedDates(supabase: SupabaseClient): Promise<Set<string>> {
  const { data } = await supabase.from("batch_review").select("batch_date");
  return new Set((data ?? []).map((r) => r.batch_date));
}

// 주어진 날짜 바로 이전(더 오래된) 배치의 논문 id 집합 — NEW 판정 기준선.
async function previousBatchPaperIds(
  supabase: SupabaseClient,
  batchDate: string
): Promise<Set<string>> {
  const { data: prev } = await supabase
    .from("daily_batch")
    .select("batch_date")
    .lt("batch_date", batchDate)
    .order("batch_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!prev?.batch_date) return new Set();
  const { data } = await supabase
    .from("daily_batch")
    .select("paper_id")
    .eq("batch_date", prev.batch_date);
  return new Set((data ?? []).map((b) => b.paper_id));
}

export async function getCandidates(
  supabase: SupabaseClient,
  batchDate: string
): Promise<Candidate[]> {
  const { data: batch } = await supabase
    .from("daily_batch")
    .select("paper_id, rank, sort_mode")
    .eq("batch_date", batchDate);

  if (!batch || batch.length === 0) return [];
  const ids = batch.map((b) => b.paper_id);

  const [papers, scores, decisions, prevIds] = await Promise.all([
    selectIn<{ id: string; external_id: string; title: string; url: string | null; venue: string | null }>(
      ids, (c) => supabase.from("papers").select("id, external_id, title, url, venue").in("id", c),
      "papers.id"),
    selectIn<{
      paper_id: string; title_ko: string | null; fun_index: number | null;
      importance_index: number | null; one_liner_ko: string | null;
      one_liner_en: string | null; red_flag: string | null;
    }>(
      ids, (c) => supabase
        .from("scores")
        .select("paper_id, title_ko, fun_index, importance_index, one_liner_ko, one_liner_en, red_flag")
        .in("paper_id", c),
      "scores.paper_id"),
    selectIn<{ paper_id: string; status: string }>(
      ids, (c) => supabase.from("decisions").select("paper_id, status").in("paper_id", c),
      "decisions.paper_id"),
    previousBatchPaperIds(supabase, batchDate),
  ]);

  const paperMap = new Map(papers.map((p) => [p.id, p]));
  const scoreMap = new Map(scores.map((s) => [s.paper_id, s]));
  const decMap = new Map(decisions.map((d) => [d.paper_id, d.status]));

  return batch
    .map((b): Candidate => {
      const p = paperMap.get(b.paper_id);
      const s = scoreMap.get(b.paper_id);
      return {
        paper_id: b.paper_id,
        external_id: p?.external_id ?? "",
        title: p?.title ?? "(제목 없음)",
        title_ko: s?.title_ko ?? null,
        url: p?.url ?? null,
        venue: p?.venue ?? null,
        one_liner_ko: s?.one_liner_ko ?? null,
        one_liner_en: s?.one_liner_en ?? null,
        fun_index: s?.fun_index ?? null,
        importance_index: s?.importance_index ?? null,
        red_flag: s?.red_flag ?? null,
        rank: b.rank,
        sort_mode: b.sort_mode,
        decision_status: (decMap.get(b.paper_id) as Candidate["decision_status"]) ?? null,
        // 직전 배치가 없으면(첫 배치) NEW 뱃지를 붙이지 않는다 — 온통 NEW 로 도배되는 것 방지.
        is_new: prevIds.size > 0 && !prevIds.has(b.paper_id),
      };
    })
    .sort((a, b) => a.rank - b.rank);
}

// 낙점(picked)된 논문 + 초안/요청 상태.
export async function getPicked(supabase: SupabaseClient): Promise<PickedPaper[]> {
  const { data: decisions } = await supabase
    .from("decisions")
    .select("paper_id, decided_at")
    .eq("status", "picked")
    .order("decided_at", { ascending: false });
  const ids = (decisions ?? []).map((d) => d.paper_id);
  if (ids.length === 0) return [];
  const decidedMap = new Map((decisions ?? []).map((d) => [d.paper_id, d.decided_at]));

  const [papers, scores, drafts, reqs] = await Promise.all([
    selectIn<{ id: string; title: string; external_id: string }>(
      ids, (c) => supabase.from("papers").select("id, title, external_id").in("id", c), "papers.id"),
    selectIn<{ paper_id: string; title_ko: string | null }>(
      ids, (c) => supabase.from("scores").select("paper_id, title_ko").in("paper_id", c),
      "scores.paper_id"),
    selectIn<{ paper_id: string }>(
      ids, (c) => supabase.from("drafts").select("paper_id").in("paper_id", c), "drafts.paper_id"),
    // 정렬 후 "논문별 첫 행"을 쓰지만, 묶는 키가 청크 기준이라 청크 분할에 안전하다.
    selectIn<{ paper_id: string; status: string }>(
      ids, (c) => supabase
        .from("draft_requests")
        .select("paper_id, status, requested_at")
        .in("paper_id", c)
        .order("requested_at", { ascending: false }),
      "draft_requests.paper_id"),
  ]);

  const paperMap = new Map(papers.map((p) => [p.id, p]));
  const koMap = new Map(scores.map((s) => [s.paper_id, s.title_ko]));
  const draftSet = new Set(drafts.map((d) => d.paper_id));
  const reqMap = new Map<string, string>();
  for (const r of reqs) if (!reqMap.has(r.paper_id)) reqMap.set(r.paper_id, r.status);

  // ids 는 decided_at 내림차순(위 쿼리 정렬)이므로 그대로 최신 낙점이 먼저 온다.
  return ids.map((id) => {
    const p = paperMap.get(id);
    return {
      paper_id: id,
      title: p?.title ?? "(제목 없음)",
      title_ko: koMap.get(id) ?? null,
      external_id: p?.external_id ?? "",
      has_draft: draftSet.has(id),
      request_status: reqMap.get(id) ?? null,
      decided_at: decidedMap.get(id) ?? null,
    };
  });
}

export async function getDraft(
  supabase: SupabaseClient,
  paperId: string
): Promise<Draft | null> {
  const { data } = await supabase
    .from("drafts")
    .select(
      "paper_id, fact_sheet, upload_title_ko, upload_title_en, script_md, video_flow, video_prompts, self_check, updated_at"
    )
    .eq("paper_id", paperId)
    .maybeSingle();
  return (data as Draft) ?? null;
}

// ① 수집 원자료(raw): 저장된 전체 papers + 채점 여부.
export async function getAllPapers(supabase: SupabaseClient): Promise<RawPaper[]> {
  // ★ 둘 다 1,000행을 넘는다(실측 papers 4,447 · scores 3,596). 예전에는 기본 상한에 잘려
  //   목록이 1,000편만 나오고, 채점 여부(scoredSet)도 1,000건만 알아서 "미채점"이 거짓으로 떴다.
  const [papers, scored] = await Promise.all([
    selectAll<{
      id: string; external_id: string | null; title: string | null; venue: string | null;
      published_date: string | null; lang: string | null; url: string | null;
      buzz_raw: { total?: number } | null;
    }>(
      (from, to) => supabase
        .from("papers")
        .select("id, external_id, title, venue, published_date, lang, url, buzz_raw")
        .order("published_date", { ascending: false })
        .range(from, to),
      "papers.all"),
    selectAll<{ paper_id: string }>(
      (from, to) => supabase.from("scores").select("paper_id").range(from, to), "scores.all"),
  ]);
  const scoredSet = new Set(scored.map((s) => s.paper_id));
  return papers.map((p) => ({
    paper_id: p.id,
    external_id: p.external_id ?? "",
    title: p.title ?? "(제목 없음)",
    venue: p.venue ?? null,
    published_date: p.published_date ?? null,
    lang: p.lang ?? null,
    url: p.url ?? null,
    buzz_total: Number(p.buzz_raw?.total ?? 0),
    scored: scoredSet.has(p.id),
  }));
}

// ② 분류(채점) 결과: scores + papers, 배치/결정 상태 포함.
export async function getScoredPapers(supabase: SupabaseClient): Promise<ScoredPaper[]> {
  // ★ 이 화면이 가장 크게 깨져 있었다: scores 3,596행을 그대로 .in() 에 넣어 papers 조회가
  //   헤더 오버플로로 죽고, 호출부가 error 를 버려 1,000행 전부 "(제목 없음)" 으로 나갔다
  //   (배치 편성·결정 상태도 같이 사라졌다). 프로덕션에서도 그랬다.
  const rows = await selectAll<Record<string, any> & { paper_id: string }>(
    (from, to) => supabase
      .from("scores")
      .select(
        "paper_id, title_ko, surprise, explainability, relatability, significance, buzz, fun_index, importance_index, one_liner_ko, red_flag, production"
      )
      .range(from, to),
    "scores.all");
  if (rows.length === 0) return [];
  const ids = rows.map((s) => s.paper_id);

  const [papers, batch, decisions] = await Promise.all([
    selectIn<{ id: string; title: string; venue: string | null; url: string | null }>(
      ids, (c) => supabase.from("papers").select("id, title, venue, url").in("id", c), "papers.id"),
    selectIn<{ paper_id: string }>(
      ids, (c) => supabase.from("daily_batch").select("paper_id").in("paper_id", c),
      "daily_batch.paper_id"),
    selectIn<{ paper_id: string; status: string }>(
      ids, (c) => supabase.from("decisions").select("paper_id, status").in("paper_id", c),
      "decisions.paper_id"),
  ]);
  const paperMap = new Map(papers.map((p) => [p.id, p]));
  const batchSet = new Set(batch.map((b) => b.paper_id));
  const decMap = new Map(decisions.map((d) => [d.paper_id, d.status]));

  return rows
    .map((s): ScoredPaper => {
      const p = paperMap.get(s.paper_id);
      return {
        paper_id: s.paper_id,
        title: p?.title ?? "(제목 없음)",
        title_ko: s.title_ko ?? null,
        venue: p?.venue ?? null,
        url: p?.url ?? null,
        surprise: s.surprise,
        explainability: s.explainability,
        relatability: s.relatability,
        significance: s.significance,
        buzz: s.buzz,
        fun_index: s.fun_index,
        importance_index: s.importance_index,
        one_liner_ko: s.one_liner_ko ?? null,
        red_flag: s.red_flag ?? null,
        production_gate: (s.production?.gate as string) ?? null,
        production_total: typeof s.production?.total === "number" ? s.production.total : null,
        // ★ 만점은 **그 행이 매겨진 자**를 쓴다(2026-09-04). mechanism 축이 붙어 만점이
        //   10 → 12 가 됐는데, 옛 행에 12 를 대면 "10/12" 로 보여 등급이 내려간 것처럼 읽힌다.
        //   engine/scoring.stored_scale 의 미러다.
        production_max:
          typeof s.production?.max === "number"
            ? s.production.max
            : PRODUCTION_LEGACY_SCORE_MAX,
        in_batch: batchSet.has(s.paper_id),
        decision_status: (decMap.get(s.paper_id) as ScoredPaper["decision_status"]) ?? null,
      };
    })
    .sort((a, b) => (b.importance_index ?? 0) - (a.importance_index ?? 0));
}

// 생성 완료된 초안 목록(승인 전 포함). 아카이브에서 조회용.
export async function getDraftList(supabase: SupabaseClient): Promise<DraftListItem[]> {
  const rows = await selectAll<{ paper_id: string; created_at: string }>(
    (from, to) => supabase
      .from("drafts")
      .select("paper_id, created_at")
      .order("created_at", { ascending: false })
      .range(from, to),
    "drafts.all");
  if (rows.length === 0) return [];
  const ids = rows.map((r) => r.paper_id);

  const [papers, scores, published] = await Promise.all([
    selectIn<{ id: string; title: string }>(
      ids, (c) => supabase.from("papers").select("id, title").in("id", c), "papers.id"),
    selectIn<{ paper_id: string; title_ko: string | null }>(
      ids, (c) => supabase.from("scores").select("paper_id, title_ko").in("paper_id", c),
      "scores.paper_id"),
    selectIn<{ paper_id: string }>(
      ids, (c) => supabase.from("published").select("paper_id").in("paper_id", c),
      "published.paper_id"),
  ]);
  const titleMap = new Map(papers.map((p) => [p.id, p.title]));
  const koMap = new Map(scores.map((s) => [s.paper_id, s.title_ko]));
  const pubSet = new Set(published.map((p) => p.paper_id));

  return rows.map((r) => ({
    paper_id: r.paper_id,
    title: titleMap.get(r.paper_id) ?? "(제목 없음)",
    title_ko: koMap.get(r.paper_id) ?? null,
    created_at: r.created_at,
    published: pubSet.has(r.paper_id),
  }));
}

// ⑤ 특정 논문·버전의 최신 지시서. 없으면 null(미생성 상태).
export async function getLatestDirective(
  supabase: SupabaseClient,
  paperId: string,
  versionType: VersionType
): Promise<Directive | null> {
  const { data } = await supabase
    .from("directives")
    .select("id, paper_id, version_type, header, cuts, status, created_at, approved_at")
    .eq("paper_id", paperId)
    .eq("version_type", versionType)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!data) return null;
  return { ...data, cuts: (data.cuts as Directive["cuts"]) ?? [] } as Directive;
}

// 렌더 잡 표시용 필드(directive→paper 제목/버전) 채우기. getRenderJobs/getSavedRenderJobs 공용.
const RENDER_JOB_COLS =
  "id, directive_id, lang, source_job_id, status, progress, cost_estimate, output_url, error_log, created_at, finished_at, deleted_at, saved_at, qa";

async function joinRenderMeta(
  supabase: SupabaseClient,
  rows: Record<string, unknown>[]
): Promise<RenderJob[]> {
  if (rows.length === 0) return [];
  const dirIds = rows.map((j) => j.directive_id as string);
  const directives = await selectIn<{ id: string; paper_id: string; version_type: string }>(
    dirIds,
    (c) => supabase.from("directives").select("id, paper_id, version_type").in("id", c),
    "directives.id");
  const dirMap = new Map(directives.map((d) => [d.id, d]));

  const paperIds = [...new Set(directives.map((d) => d.paper_id))];
  // 발행용 복붙(렌더결과)을 위해 캡션 조립에 필요한 메타를 함께 조회한다.
  const [papers, scores, drafts] = await Promise.all([
    selectIn<Record<string, unknown>>(
      paperIds,
      (c) => supabase
        .from("papers")
        .select("id, title, url, venue, authors, published_date")
        .in("id", c),
      "papers.id"),
    selectIn<Record<string, unknown>>(
      paperIds,
      (c) => supabase
        .from("scores")
        .select("paper_id, title_ko, one_liner_ko, one_liner_en")
        .in("paper_id", c),
      "scores.paper_id"),
    selectIn<Record<string, unknown>>(
      paperIds,
      (c) => supabase
        .from("drafts")
        .select("paper_id, fact_sheet, upload_title_ko, upload_title_en")
        .in("paper_id", c),
      "drafts.paper_id"),
  ]);
  // 각 소스를 paper_id 키 맵으로. 값은 unknown 으로 받아 아래에서 필요한 필드만 안전 추출.
  const paperMap = new Map<string, Record<string, unknown>>(
    papers.map((p) => [String((p as Record<string, unknown>).id), p as Record<string, unknown>])
  );
  const scoreMap = new Map<string, Record<string, unknown>>(
    scores.map((s) => [String((s as Record<string, unknown>).paper_id), s as Record<string, unknown>])
  );
  const draftMap = new Map<string, Record<string, unknown>>(
    drafts.map((d) => [String((d as Record<string, unknown>).paper_id), d as Record<string, unknown>])
  );

  // 논문별 표시·발행 필드(제목/캡션)를 서버에서 미리 조립(buildPublishCaption 은 순수 함수).
  interface PubMeta {
    title: string;
    titleKo: string | null;
    upKo: string | null;
    upEn: string | null;
    capKo: string;
    capEn: string;
  }
  const pub = new Map<string, PubMeta>();
  for (const pid of paperIds) {
    const paper = paperMap.get(pid) ?? {};
    const score = scoreMap.get(pid) ?? {};
    const draft = draftMap.get(pid) ?? {};
    const factSheet = draft.fact_sheet as { source?: Parameters<typeof sourceFrom>[1] } | null;
    const src = sourceFrom(
      paper as unknown as Parameters<typeof sourceFrom>[0],
      factSheet?.source ?? null
    );
    pub.set(pid, {
      title: (paper.title as string) ?? "(제목 없음)",
      titleKo: (score.title_ko as string | null) ?? null,
      upKo: (draft.upload_title_ko as string | null) ?? null,
      upEn: (draft.upload_title_en as string | null) ?? null,
      capKo: buildPublishCaption(src, (score.one_liner_ko as string) ?? "", "ko"),
      capEn: buildPublishCaption(src, (score.one_liner_en as string) ?? "", "en"),
    });
  }

  // 유튜브 업로드 상태(잡별). 활성/실패 요청을 render_job_id 로 조인해 버튼·링크를 표시한다.
  const jobIds = rows.map((j) => j.id as string);
  const uploads = await selectIn<Record<string, unknown>>(
    jobIds,
    (c) => supabase
      .from("upload_requests")
      .select("render_job_id, status, youtube_url, error")
      .in("render_job_id", c),
    "upload_requests.render_job_id");
  const uploadMap = new Map<string, Record<string, unknown>>(
    uploads.map((u) => [String((u as Record<string, unknown>).render_job_id), u as Record<string, unknown>])
  );

  return rows.map((j): RenderJob => {
    const d = dirMap.get(j.directive_id as string);
    const p = d ? pub.get(d.paper_id) : undefined;
    const up = uploadMap.get(j.id as string);
    return {
      ...(j as unknown as RenderJob),
      paper_id: d?.paper_id,
      title: d ? p?.title ?? "(제목 없음)" : "(지시서 없음)",
      title_ko: p?.titleKo ?? null,
      version_type: d?.version_type as VersionType | undefined,
      upload_title_ko: p?.upKo ?? null,
      upload_title_en: p?.upEn ?? null,
      caption_ko: p?.capKo ?? "",
      caption_en: p?.capEn ?? "",
      youtube_status: (up?.status as RenderJob["youtube_status"]) ?? null,
      youtube_url: (up?.youtube_url as string | null) ?? null,
      youtube_error: (up?.error as string | null) ?? null,
    };
  });
}

// ⑥ 렌더 잡 목록 + directive→paper 제목/버전 조인(표시용).
// scope: active(기본, 휴지통 제외) | trash(휴지통만) | all(전체).
export async function getRenderJobs(
  supabase: SupabaseClient,
  opts?: { scope?: "active" | "trash" | "all" }
): Promise<RenderJob[]> {
  const scope = opts?.scope ?? "active";
  let q = supabase.from("render_jobs").select(RENDER_JOB_COLS);
  if (scope === "active") q = q.is("deleted_at", null);
  else if (scope === "trash") q = q.not("deleted_at", "is", null);
  const { data: jobs } = await q.order("created_at", { ascending: false });
  return joinRenderMeta(supabase, jobs ?? []);
}

// 보관(저장)된 렌더 mp4 — 아카이브의 "보관된 영상" 섹션용. 휴지통 제외.
export async function getSavedRenderJobs(supabase: SupabaseClient): Promise<RenderJob[]> {
  const { data: jobs } = await supabase
    .from("render_jobs")
    .select(RENDER_JOB_COLS)
    .not("saved_at", "is", null)
    .is("deleted_at", null)
    .order("saved_at", { ascending: false });
  return joinRenderMeta(supabase, jobs ?? []);
}

export async function getPublished(supabase: SupabaseClient): Promise<PublishedItem[]> {
  const rows = await selectAll<{ paper_id: string; published_at: string }>(
    (from, to) => supabase
      .from("published")
      .select("paper_id, published_at")
      .order("published_at", { ascending: false })
      .range(from, to),
    "published.all");
  if (rows.length === 0) return [];
  const papers = await selectIn<{ id: string; title: string }>(
    rows.map((r) => r.paper_id),
    (c) => supabase.from("papers").select("id, title").in("id", c),
    "papers.id");
  const titleMap = new Map(papers.map((p) => [p.id, p.title]));
  return rows.map((r) => ({
    paper_id: r.paper_id,
    title: titleMap.get(r.paper_id) ?? "(제목 없음)",
    published_at: r.published_at,
  }));
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

/** ④ 논문 초안 — 지금 생성 대기 중인가. */
export async function getDraftPending(
  supabase: SupabaseClient,
  paperId: string
): Promise<PendingStatus> {
  const { data } = await supabase
    .from("draft_requests")
    .select("status, requested_at")
    .eq("paper_id", paperId)
    .in("status", ["queued", "processing"])
    .order("requested_at", { ascending: false })
    .limit(1);
  return latestPending(data);
}

/** ⑤ 논문 지시서 — 이 버전이 지금 생성 대기 중인가. */
export async function getDirectivePending(
  supabase: SupabaseClient,
  paperId: string,
  versionType: string
): Promise<PendingStatus> {
  const { data } = await supabase
    .from("directive_requests")
    .select("status, requested_at")
    .eq("paper_id", paperId)
    .eq("version_type", versionType)
    .in("status", ["queued", "processing"])
    .order("requested_at", { ascending: false })
    .limit(1);
  return latestPending(data);
}
