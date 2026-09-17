// 리포트 1편의 **통합 작업 화면** — 논문 /review/[paperId] 와 같은 구조(WorkspaceClient factory="report").
// docs/설계안_초안지시서_통합발주_v2.md §5. 옛 `?step=` 주소는 그대로 열린다.
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import {
  getReportDraft,
  getReportDirective,
  getReportDirectiveStatusMap,
  getReportRenderJobs,
  getReportDraftPending,
  getReportDirectivePending,
} from "@/lib/reportQueries";
import WorkspaceClient from "@/components/WorkspaceClient";
import StageStepper, { type StepNo } from "@/components/StageStepper";
import { reportStages } from "@/lib/work/steps";
import { renderProgress } from "@/lib/work/renderQueue";
import { REPORT_DEFAULT_VERSION_KEY, REPORT_VERSION_KEYS, isOfferedReportVersion } from "@/lib/versions";
import { isValidationCurrent } from "@/lib/scriptRevision";
import type { VersionType } from "@/lib/types";
import type { PendingStatus } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function ReportReviewDetailPage(props: {
  params: Promise<{ reportId: string }>;
  searchParams: Promise<{ step?: string; v?: string }>;
}) {
  // ★ Next 15: params·searchParams 가 Promise 다. 본문을 건드리지 않으려고
  //   props 로 받아 맨 앞에서 await 해 같은 이름에 다시 묶는다.
  const [params, searchParams] = await Promise.all([props.params, props.searchParams]);
  const supabase = createClient();
  const reportId = params.reportId;

  const [
    draft,
    { data: report },
    { data: score },
    { data: published },
    directiveMap,
    allJobs,
    directives,
    draftPending,
    pendings,
  ] = await Promise.all([
    getReportDraft(supabase, reportId),
    supabase
      .from("reports")
      .select("title, company, theme, broker, target_price, opinion, report_url, summary")
      .eq("id", reportId)
      .maybeSingle(),
    supabase.from("report_scores").select("title_ko, one_liner_ko, angle").eq("report_id", reportId).maybeSingle(),
    supabase.from("report_published").select("report_id").eq("report_id", reportId).maybeSingle(),
    getReportDirectiveStatusMap(supabase, [reportId]),
    getReportRenderJobs(supabase),
    Promise.all(REPORT_VERSION_KEYS.map((v) => getReportDirective(supabase, reportId, v))),
    getReportDraftPending(supabase, reportId),
    Promise.all(REPORT_VERSION_KEYS.map((v) => getReportDirectivePending(supabase, reportId, v))),
  ]);

  const slots = REPORT_VERSION_KEYS.map((key, i) => ({ key, directive: directives[i] }));
  const directivePending: Partial<Record<VersionType, PendingStatus>> = {};
  REPORT_VERSION_KEYS.forEach((key, i) => { directivePending[key] = pendings[i]; });
  const activeVersion: VersionType = isOfferedReportVersion(searchParams.v)
    ? searchParams.v
    : (slots.find((s) => s.directive)?.key ?? REPORT_DEFAULT_VERSION_KEY);

  const jobs = allJobs.filter((j) => j.report_id === reportId);
  const { steps, defaultStep } = reportStages(reportId, {
    hasDraft: !!draft,
    scriptApproved: !!published,
    directiveStatus: directiveMap.get(reportId) ?? {},
    render: renderProgress(jobs),
  });
  const requested = Number(searchParams.step);
  const step: StepNo = ([4, 5, 6] as number[]).includes(requested)
    ? (requested as StepNo)
    : defaultStep;

  const title = score?.title_ko || report?.title || "리포트";
  // ★ 화면에 뜬 검사 결과가 지금 대본의 것인가(PR #94 후속 리뷰 P1-3). 승인을 막지는 않는다.
  const validationCurrent = isValidationCurrent(
    draft?.script_md, (draft as { validated_script_hash?: string } | null)?.validated_script_hash);

  return (
    <main className="container container--work">
      <div className="header">
        <h1>{title}</h1>
        <Link className="muted" href="/finance/review">← 검수 목록</Link>
      </div>

      <StageStepper steps={steps} current={step} basePath={`/finance/review/${reportId}`} />

      {/* ★ key 로 리포트이 바뀌면 통째로 새로 마운트한다. 이 컴포넌트는 서버 props 를
          useState 초기값으로 잡는데, 초기값은 **첫 마운트에서만** 쓰인다 — key 가 없으면
          소프트 내비게이션으로 다른 리포트에 가도 앞 리포트의 상태가 그대로 남는다
          (CandidateList 가 배치일에서 이미 낸 사고와 같은 것이다). */}
      <WorkspaceClient
        key={reportId}
        factory="report"
        id={reportId}
        draft={draft}
        published={!!published}
        slots={slots}
        jobs={jobs}
        draftPending={draftPending}
        directivePending={directivePending}
        activeVersion={activeVersion}
        initialStep={step}
        validationCurrent={validationCurrent}
        leftExtras={
          <details className="aux-panel">
            <summary>리포트 정보 · 원문</summary>
            <div className="muted">
              {[report?.company, report?.theme].filter(Boolean).join(" · ")}
              {report?.broker ? ` · 출처 ${report.broker}` : ""}
            </div>
            {score?.one_liner_ko && <p className="oneliner">{score.one_liner_ko}</p>}
            {score?.angle && <p className="angle">앵글: {score.angle}</p>}
            {(report?.opinion || report?.target_price != null) && (
              <div className="broker-facts">
                {report?.opinion && <span className="pill">{report.opinion}</span>}
                {report?.target_price != null && <span>목표가 <b>{Number(report.target_price).toLocaleString()}</b></span>}
              </div>
            )}
            {report?.summary && (
              <details><summary className="muted">리포트 요약</summary><p style={{ whiteSpace: "pre-wrap" }}>{report.summary}</p></details>
            )}
            {report?.report_url && <a className="btn" href={report.report_url} target="_blank" rel="noreferrer">원문 ↗</a>}
          </details>
        }
      />
    </main>
  );
}
