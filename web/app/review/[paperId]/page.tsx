// 논문 1편의 **통합 작업 화면** (docs/설계안_초안지시서_통합발주_v2.md, 2026-09-11).
//
// 이력: 처음엔 ④ 초안 검수와 ⑤ 지시서가 한 화면에 세로로 붙어 있었고(페이지가 길어져 버튼이
// 사라졌다), 2026-08-19 에 `?step=4|5|6` 으로 나눴다(FLOW-01). 이제 운영자 결정으로 다시
// 한 화면이다 — 다만 세로로 붙이는 것이 아니라 **결정 바 하나 + 두 칸(대본 | 지시서)** 이고,
// 결정 바는 스크롤과 무관하게 화면 위에 붙어 있다. 옛 `?step=` 주소는 그대로 열린다
// (6 이면 렌더 패널을 펼치고, 5 면 좁은 화면에서 지시서 칸을 먼저 보인다).
import { createClient } from "@/lib/supabase/server";
import {
  getDraft,
  getLatestDirective,
  getDirectiveStatusMap,
  getRenderJobs,
  getDraftPending,
  getDirectivePending,
} from "@/lib/queries";
import PublishCaption from "@/components/PublishCaption";
import PublishTitles from "@/components/PublishTitles";
import WorkspaceClient from "@/components/WorkspaceClient";
import StageStepper, { type StepNo } from "@/components/StageStepper";
import { sourceFrom, buildPublishCaption } from "@/lib/publishCaption";
import { buildStages } from "@/lib/work/steps";
import { renderProgress } from "@/lib/work/renderQueue";
import { DEFAULT_VERSION_KEY, VERSION_KEYS, VERSION_META, isOfferedVersion } from "@/lib/versions";
import type { VersionType } from "@/lib/types";
import type { PendingStatus } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function ReviewDetailPage(props: {
  params: Promise<{ paperId: string }>;
  searchParams: Promise<{ step?: string; v?: string }>;
}) {
  // ★ Next 15: params·searchParams 가 Promise 다. 본문을 건드리지 않으려고
  //   props 로 받아 맨 앞에서 await 해 같은 이름에 다시 묶는다.
  const [params, searchParams] = await Promise.all([props.params, props.searchParams]);
  const supabase = createClient();
  const draft = await getDraft(supabase, params.paperId);

  const [{ data: paper }, { data: score }, { data: published }, directives, statusMaps, allJobs, draftPending, pendings] =
    await Promise.all([
      supabase
        .from("papers")
        .select("title, url, abstract, venue, authors, published_date")
        .eq("id", params.paperId)
        .maybeSingle(),
      supabase
        .from("scores")
        .select("title_ko, one_liner_ko, one_liner_en")
        .eq("paper_id", params.paperId)
        .maybeSingle(),
      supabase.from("published").select("paper_id").eq("paper_id", params.paperId).maybeSingle(),
      // 제공 버전 전부 — 만화식·3D 그래픽을 나란히 만들어 비교하는 것이 이 화면의 목적이다.
      Promise.all(VERSION_KEYS.map((v) => getLatestDirective(supabase, params.paperId, v))),
      getDirectiveStatusMap(supabase, [params.paperId]),
      getRenderJobs(supabase),
      getDraftPending(supabase, params.paperId),
      // 버전별 지시서 생성 요청(0046 연쇄 포함) — 화면이 "만드는 중"을 이어서 보여준다.
      Promise.all(VERSION_KEYS.map((v) => getDirectivePending(supabase, params.paperId, v))),
    ]);
  const directiveStatusMap = statusMaps.get(params.paperId) ?? {};
  const slots = VERSION_KEYS.map((key, i) => ({ key, directive: directives[i] }));
  const directivePending: Partial<Record<VersionType, PendingStatus>> = {};
  VERSION_KEYS.forEach((key, i) => { directivePending[key] = pendings[i]; });

  // 오른쪽 칸의 버전: ?v= 가 있으면 그것, 없으면 지시서가 있는 첫 버전, 그것도 없으면 기본.
  const activeVersion: VersionType = isOfferedVersion(searchParams.v)
    ? searchParams.v
    : (slots.find((s) => s.directive)?.key ?? DEFAULT_VERSION_KEY);

  const jobs = allJobs.filter((j) => j.paper_id === params.paperId);

  const { steps, defaultStep } = buildStages({
    hasDraft: !!draft,
    scriptApproved: !!published,
    directiveStatus: directiveStatusMap,
    render: renderProgress(jobs),
  });
  const requested = Number(searchParams.step);
  const step: StepNo = ([4, 5, 6] as number[]).includes(requested)
    ? (requested as StepNo)
    : defaultStep;

  const abstractPreview =
    paper?.abstract && paper.abstract.length > 240
      ? `${paper.abstract.slice(0, 240).trimEnd()}…`
      : paper?.abstract ?? null;
  const summary = score?.one_liner_ko || abstractPreview;

  const fsSource = draft?.fact_sheet?.source ?? null;
  const src = sourceFrom(paper, fsSource);
  const captionKo = buildPublishCaption(src, score?.one_liner_ko ?? "", "ko");
  const captionEn = buildPublishCaption(src, score?.one_liner_en ?? "", "en");

  // 상태 띠 요약 — 근거 없는 씬/컷 수를 항상 보여준다(접어 숨기지 않는다).
  const unsupportedScenes = (draft?.self_check?.scenes ?? []).filter((s) => s.unsupported.length > 0).length;
  const ungroundedByVersion = slots
    .filter((s) => s.directive)
    .map((s) => ({
      key: s.key,
      count: (s.directive?.cuts ?? []).filter((c) => (c.source_facts?.length ?? 0) === 0).length,
    }));
  const ungroundedTotal = ungroundedByVersion.reduce((n, v) => n + v.count, 0);
  const hasAnyDirective = slots.some((s) => s.directive);
  const stepperSummary =
    draft || hasAnyDirective
      ? [
          unsupportedScenes > 0 ? `⛔ 근거 없는 씬 ${unsupportedScenes}개` : "근거 없는 씬 0",
          ungroundedTotal > 0
            ? `⛔ 근거 없는 컷 ${ungroundedByVersion
                .filter((v) => v.count > 0)
                .map((v) => `${VERSION_META.find((m) => m.key === v.key)?.label ?? v.key} ${v.count}개`)
                .join(" · ")}`
            : "근거 없는 컷 0",
        ].join(" · ")
      : null;

  return (
    <main className="container container--work">
      <div className="header">
        <h1>{score?.title_ko || paper?.title || "검수"}</h1>
        <a className="muted" href="/review">← 목록</a>
      </div>

      {/* 상태 띠 — 단계 이동이 아니라 "어디까지 왔나"를 보여준다. 링크는 같은 화면으로 온다. */}
      <StageStepper steps={steps} current={step} basePath={`/review/${params.paperId}`} summary={stepperSummary} />

      <WorkspaceClient
        factory="paper"
        id={params.paperId}
        draft={draft}
        published={!!published}
        slots={slots}
        jobs={jobs}
        draftPending={draftPending}
        directivePending={directivePending}
        activeVersion={activeVersion}
        initialStep={step}
        leftExtras={
          <>
            {/* 논문 메타는 원문 대조에 늘 필요하다 — 접어 둔다. */}
            <details className="aux-panel">
              <summary>논문 정보 · 원문</summary>
              {score?.title_ko && paper?.title && <div className="title-en">{paper.title}</div>}
              <div className="muted">{paper?.venue ?? "게재처 미상"}</div>
              {summary && <p className="oneliner" style={{ marginTop: 8 }}>📄 {summary}</p>}
              {paper?.url && (
                <p>
                  <a className="btn" href={paper.url} target="_blank" rel="noreferrer">원문 보기 ↗</a>
                </p>
              )}
              {paper?.abstract && (
                <details>
                  <summary className="muted" style={{ cursor: "pointer" }}>원문 초록 (빨간 표시 문장을 여기와 대조)</summary>
                  <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{paper.abstract}</p>
                </details>
              )}
            </details>
            {draft && (
              <PublishTitles
                paperId={params.paperId}
                initialKo={draft.upload_title_ko}
                initialEn={draft.upload_title_en}
                fallback={score?.title_ko || paper?.title || null}
              />
            )}
            <PublishCaption captionKo={captionKo} captionEn={captionEn} />
          </>
        }
      />
    </main>
  );
}
