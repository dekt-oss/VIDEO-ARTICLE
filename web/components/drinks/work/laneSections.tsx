// 작업공간 레인 본문(서버) — 기존 컴포넌트를 섹션 순서대로 **그대로** 배치한다. 새 쓰기 경로·새 판단은 없다.
// 설명형/카드: 초안(DevelopCard) → 근거(EvidenceTab) → 내용 승인(ContentApprovalTab) → 제작(ExplainerProduction / RenderRequest)
//              → 산출물 승인(파일 묶음 + OutputReview) → 발행안(CreatePublication) → 게시 승인(RequestActions) → 게시 뒤.
// 밈: 글·제작안(MemeDraftForm/Actions) → 발행안(CreateMemePublication 또는 앱 안내 + [게시했음]) → 게시 승인 → 게시 뒤.
// 결정 바가 가져갈 수 있는 주 버튼은 `hidePrimary` 로 다리를 놓는다(primaryBridge) — 바가 다른 일을 가리키면 버튼은 그대로 남는다.
import Link from "next/link";
import type { ReactNode } from "react";

import BriefTab from "@/components/drinks/BriefTab";
import ContentApprovalTab from "@/components/drinks/ContentApprovalTab";
import DevelopCard from "@/components/drinks/DevelopCard";
import EvidenceTab from "@/components/drinks/EvidenceTab";
import ExplainerProduction from "@/components/drinks/ExplainerProduction";
import LoadProblem from "@/components/drinks/LoadProblem";
import { MemeDraftActions, MemeDraftForm } from "@/components/drinks/MemeDraftControls";
import PlanTab from "@/components/drinks/PlanTab";
import { CancelRender, OutputReview, RenderRequest } from "@/components/drinks/ProductionControls";
import { AudioControl, CreateMemePublication, CreatePublication, RequestActions } from "@/components/drinks/PublishControls";
import { fmtTime } from "@/components/drinks/RunPill";
import QaPanel from "@/app/drinks/production/[planId]/QaPanel";
import { seoulDateTimeLabel } from "@/lib/date";
import { audioSummary, pubBlockLabel } from "@/lib/drinks/audio";
import { pickBudget } from "@/lib/drinks/develop";
import { MEME_STATUS_LABEL, memeNextStep, type MemeDraftRow } from "@/lib/drinks/meme";
import type { MemeWorkLoaded } from "@/lib/drinks/memeQueries";
import { VERSION_STATUS_LABEL, deriveTopic, type Format, type Loaded } from "@/lib/drinks/model";
import type { PlanProduction } from "@/lib/drinks/productionQueries";
import { CONTENT_FORMAT_LABEL, PUB_STATUS_LABEL, kst, type PublishBoard, type RequestView } from "@/lib/drinks/publishQueries";
import type { DevelopLoad, TopicDetail } from "@/lib/drinks/queries";
import { safeHref } from "@/lib/drinks/trends";
import type { EventRow } from "@/lib/drinks/types";
import { laneSections, type SectionKey } from "@/lib/drinks/work/lanes";
import type { FormatIntent, WorkItem } from "@/lib/drinks/work/types";
import type { SectionView } from "./DrinksWorkspace";

const JOB_LABEL: Record<string, string> = { queued: "대기", running: "렌더 중", succeeded: "파일 생성됨", failed: "실패", canceled: "취소" };
const JOB_DONE_LABEL: Record<string, string> = { explainer_plan: "지시서 완료", explainer_buy: "구매 단계 끝" };
const REVIEW_LABEL: Record<string, string> = { pending: "검수 대기", approved: "파일 승인", changes_requested: "고칠 점 있음", blocked: "차단" };
const BLOCK_TEXT: Record<string, string> = {
  plan_not_approved: "제작안이 승인 상태가 아님", plan_blocked: "제작안 차단(근거 철회·권리 변경)", evidence_invalid: "근거를 지금 쓸 수 없음",
  not_found: "제작안 없음", explainer_engine_not_wired: "설명형은 전부 영상이어야 해서 옛 그림 나열식으로 만들지 않습니다(0067 적용 전)",
};
const SLOT_LABEL: Record<string, string> = { morning: "아침(06–11시)", afternoon: "낮(11–17시)", evening: "저녁(17–22시)", night: "밤(22–06시)" };
const FINISHED = new Set(["published", "failed", "canceled", "unknown"]);

export const PLAN_FORMAT_OF: Record<"explainer" | "card", Format> = { explainer: "video", card: "carousel" };

type ProductionLoad = Loaded<PlanProduction> | { state: "not_found" } | null;

export interface TopicLaneInput {
  lane: "explainer" | "card";
  detail: TopicDetail;
  develop: DevelopLoad;
  item: WorkItem | null;
  /** ?plan= 또는 현재 제작안의 제작 상태. 제작안이 없으면 null */
  production: ProductionLoad;
  /** ?plan= 으로 과거 버전을 열었는가 */
  planRequested: string | null;
  publish: Loaded<PublishBoard>;
  today: string;
}

function publishable(board: PublishBoard) {
  return board.accounts.filter((a) => a.status !== "disabled").map((a) => ({
    id: a.id,
    label: `${a.display_name} · ${a.external_account_id}${a.connection === "fake" ? " · 시험" : ""}${a.publish_enabled ? "" : " · 발행 꺼짐"}`,
    postTypes: a.capabilities?.post_types ?? [],
  }));
}
function slotHintOf(board: PublishBoard): string | null {
  const slots = board.slot_weights;
  const best = slots && Object.keys(slots).length ? Object.entries(slots).sort((x, y) => y[1] - x[1])[0] : null;
  return best && best[1] > 0 ? SLOT_LABEL[best[0]] ?? best[0] : null;
}

/** 발행 요청 한 건 — /drinks/publish 의 행과 같은 정보. 승인은 지문을 보고 누르므로 RequestActions 가 그 자리에 남는다. */
function RequestBlock({ r, board, hidePrimary }: { r: RequestView; board: PublishBoard; hidePrimary: boolean }) {
  const accLabel = new Map(board.accounts.map((a) => [a.id, `${a.display_name} (${a.external_account_id})`]));
  const pages = (r.files ?? []).filter((f) => f.role === "page").length;
  const fmt = r.content_format ?? "card";
  const what = r.post_type === "carousel" ? `카드뉴스 ${pages}장` : `${fmt === "card" ? "" : CONTENT_FORMAT_LABEL[fmt] + " "}릴스(영상 + 커버)`;
  const audioText = audioSummary(r.audio);
  const summary = `계정: ${accLabel.get(r.account_id) ?? r.target_external_account_id}\n파일: ${what}\n시각: ${kst(r.publish_at)} (한국)\n캡션: ${r.caption || "(없음)"}${r.post_type === "reel" ? `\n음원: ${audioText}` : ""}`;
  return (
    <div className="list-row" style={{ alignItems: "flex-start" }}>
      <span style={{ maxWidth: 640 }}>
        <span className="pill">{what}</span>{" "}
        <span className="pill" data-tone={r.status === "unknown" ? "warn" : undefined}>{PUB_STATUS_LABEL[r.status]}</span>
        <div className="muted">{accLabel.get(r.account_id) ?? r.target_external_account_id} · 게시 시각 {kst(r.publish_at)} (한국)
          {r.published_at && <> · 게시됨 {kst(r.published_at)}</>}</div>
        <div style={{ whiteSpace: "pre-wrap" }}>{r.caption || <span className="muted">(캡션 없음)</span>}</div>
        {r.post_type === "reel" && (r.audio_required || r.audio) && (
          <AudioControl id={r.id} version={r.version} status={r.status} audio={r.audio} options={board.audio_options ?? []} summary={audioText} />
        )}
        {r.status === "awaiting_approval" && r.pause_code === "needs_reconfirm" && <div className="banner-info">{r.pause_reason}</div>}
        {r.status === "paused" && r.pause_code === "audio_failed" && <div className="banner-info">음원 없이 올리지 않았습니다. 다른 음원을 고르거나(다시 승인), 앱에서 직접 붙이거나, 취소하세요.</div>}
        {r.status === "unknown" && <div className="banner-block">게시 여부 확인 필요 — 응답이 끊겨 게시됐는지 모릅니다. 다시 게시하지 않고, 다음 워커 실행이 인스타 조회로 대조합니다.{r.cancel_requested && " (취소 요청 있음 — 이미 게시됐으면 취소되지 않습니다)"}</div>}
        {r.status === "paused" && <div className="banner-info">멈춤: {r.pause_reason ?? r.pause_code}</div>}
        {r.status === "failed" && <div className="banner-info">실패(게시 안 됨 확인): {r.error_message ?? r.error_code}</div>}
        {r.block && r.status !== "paused" && <div className="muted">지금 게시 조건: {pubBlockLabel(r.block)}</div>}
        {r.reconcile_state === "cancel_not_applied" && <div className="banner-info">취소 요청 전에 이미 게시돼 취소되지 않았습니다.</div>}
        {r.external_url && <div><a href={r.external_url} target="_blank" rel="noreferrer">게시물 보기</a></div>}
        {r.approval_digest && <div className="muted">승인 지문 {r.approval_digest.slice(0, 12)}…{r.approval_digest !== r.current_digest && " ⚠ 지금 내용과 다름"}</div>}
      </span>
      <RequestActions id={r.id} version={r.version} status={r.status} digest={r.approval_digest} summary={summary} hidePrimary={hidePrimary} />
    </div>
  );
}

function PostSections(requests: RequestView[], board: PublishBoard, hidePrimary: boolean): { post: ReactNode; after: ReactNode } {
  const live = requests.filter((r) => !FINISHED.has(r.status));
  const done = requests.filter((r) => FINISHED.has(r.status));
  const post = live.length === 0
    ? <p className="muted">진행 중인 게시 요청이 없습니다. 발행안을 만들면 여기서 승인 요청 → 승인(지문 확인) → 예약 순으로 갑니다.</p>
    : live.map((r) => <RequestBlock key={r.id} r={r} board={board} hidePrimary={hidePrimary} />);
  const after = (
    <>
      {done.length === 0 ? <p className="muted">아직 게시된 것이 없습니다.</p> : done.map((r) => <RequestBlock key={r.id} r={r} board={board} hidePrimary={false} />)}
      <p className="muted">성과(24h/72h/7d)는 <Link href="/drinks/analytics">성과·전략</Link>에서 봅니다. 실패한 요청은 위 [다시 시도]로 다시 예약합니다.</p>
    </>
  );
  return { post, after };
}

function PublishProblem({ publish }: { publish: Loaded<PublishBoard> }) {
  if (publish.state === "ok") return null;
  return <LoadProblem state={publish.state} error={publish.state === "failed" ? publish.error : undefined} />;
}

/** 설명형·카드 레인의 섹션 전부. 섹션 키는 lanes.ts 의 순서를 따른다. */
export function buildTopicLane(input: TopicLaneInput): SectionView[] {
  const { lane, detail, develop, production, planRequested, publish, today } = input;
  const { topic, sources, reviews, deliverables, plans, canonical, pick } = detail;
  const planFormat = PLAN_FORMAT_OF[lane];
  const attestations = Object.fromEntries(detail.attestations);
  const sameBody = Object.fromEntries(detail.sameBody);
  const sharedWith = Object.fromEntries(detail.sharedWith);
  const d = deriveTopic(topic, new Map(reviews.map((r) => [r.id, r])), deliverables, new Map(plans.map((p) => [p.id, p])), pick);
  const review = d.review;
  const reviewKey = `${review?.id ?? "none"}-${review?.version ?? 0}-${topic.version}`;
  const deliverable = deliverables.find((x) => x.format === planFormat) ?? null;
  const lanePlans = plans.filter((p) => p.format === planFormat);
  const currentPlan = lanePlans.find((p) => p.id === deliverable?.current_revision_id) ?? d.plans[planFormat] ?? null;
  const developOk = develop.state === "ok" ? develop : null;
  const prod = production && production.state === "ok" ? production.data : null;
  const isExplainer = Boolean(prod?.explainer.is_explainer);
  const laneLabel = lane === "explainer" ? "릴스(설명형)" : "카드뉴스";
  const pastVersion = Boolean(planRequested && currentPlan && planRequested !== currentPlan.id);

  const nodes: Partial<Record<SectionKey, ReactNode>> = {};

  nodes.draft = (
    <>
      <DevelopCard topicId={topic.id} topicStatus={topic.status} approvedEvidence={d.approvalValid} plans={plans.map((p) => ({ id: p.id, format: p.format }))} develop={develop} />
      <p className="dk-kv" style={{ marginTop: 10 }}>
        {laneLabel} 제작안 {currentPlan ? <>버전 <b>{currentPlan.revision_no}</b> · {VERSION_STATUS_LABEL[currentPlan.plan_status]}{currentPlan.blocked_at ? " · 차단" : ""}</> : <b>없음</b>}
        {currentPlan && ` · ${lane === "card" ? `카드 ${(currentPlan.plan_json.pages ?? []).length}장${currentPlan.plan_json.reel ? " + 릴스 훅" : ""}` : `장면 ${(currentPlan.plan_json.scenes ?? []).length}개`}`}
      </p>
      <details className="dk-sub">
        <summary className="muted">제작안 직접 보기·고치기 (옛 {lane === "card" ? "카드뉴스" : "영상"} 탭)</summary>
        <PlanTab key={`${planFormat}-${deliverable?.version ?? 0}-${topic.version}`} format={planFormat} topic={topic} reviews={reviews} deliverable={deliverable} plans={lanePlans} />
      </details>
    </>
  );

  nodes.evidence = (
    <>
      <EvidenceTab key={reviewKey} topic={topic} review={review} sources={sources} attestations={attestations} sameBody={sameBody} sharedWith={sharedWith}
        developRequests={developOk?.requests ?? []} />
      <details className="dk-sub">
        <summary className="muted">공통 기획 (옛 경로)</summary>
        <BriefTab key={`brief-${reviewKey}`} topic={topic} review={review} reviews={reviews} plans={plans} today={today} />
      </details>
      {canonical && <p className="muted">기준 소재: <Link href={`/drinks/work/${canonical.id}`}>{canonical.title}</Link></p>}
    </>
  );

  nodes.approve = (
    <ContentApprovalTab
      key={`${review?.id ?? "none"}-${review?.version ?? 0}-${currentPlan?.id ?? "none"}-${currentPlan?.version ?? 0}-${topic.version}-${lane}`}
      topic={topic}
      review={review}
      plan={currentPlan}
      pick={pick}
      formatIntent={lane}
      hidePrimary
      requests={developOk?.requests ?? []}
      budget={developOk ? pickBudget(developOk.budgets, Date.now()) : null}
      snapshots={Object.fromEntries(sources.map(({ snapshot: s }) => [s.id, { title: s.title, canonical_url: s.canonical_url, publisher: s.publisher, rights_status: s.rights_status }]))}
      developProblem={develop.state !== "ok" && develop.state !== "missing" ? (develop.state === "failed" ? `개발 상태를 불러오지 못했습니다 — 요청 0건이 아닙니다. ${develop.error}` : "개발 상태를 읽을 수 없습니다(DB 미적용 또는 서버 키 없음).") : null}
      today={today}
    />
  );

  // 제작
  if (!production) {
    nodes.produce = <p className="muted">아직 제작안이 없습니다 — 내용 승인이 끝나면 제작안이 생기고 여기서 제작을 시작합니다.</p>;
    nodes.output = <p className="muted">제작이 끝나면 파일 묶음이 여기 들어옵니다.</p>;
  } else if (production.state === "not_found") {
    nodes.produce = <p className="banner-warn">제작안({planRequested ?? "현재"})을 찾지 못했습니다.</p>;
    nodes.output = null;
  } else if (production.state !== "ok") {
    nodes.produce = <LoadProblem state={production.state} error={production.state === "failed" ? production.error : undefined} />;
    nodes.output = null;
  } else {
    const { plan, review: prReview, renderable, jobs, manifests, costs, explainer } = production.data;
    const active = jobs.find((j) => j.status === "queued" || j.status === "running");
    const lastFailed = jobs.find((j) => j.status === "failed" || j.status === "canceled");
    const total = costs.reduce((s, c) => s + Number(c.cost_usd), 0);
    const legacyVideo = plan.format === "video" && !isExplainer;
    nodes.produce = (
      <>
        {pastVersion && <p className="banner-warn">과거 버전 제작안(버전 {plan.revision_no})을 열었습니다. 현재 버전은 <Link href={`/drinks/work/${topic.id}?lane=${lane}&panel=produce`}>여기</Link>.</p>}
        <p className="dk-kv">제작안 버전 <b>{plan.revision_no}</b> ({VERSION_STATUS_LABEL[plan.plan_status]}) · 근거 버전 <b>{prReview.revision_no}</b>{" "}
          {prReview.currently_valid === false ? <span className="dk-bad">· 근거 지금 사용 불가</span> : <span className="dk-ok">· 근거 유효</span>}</p>
        {renderable ? (
          <p className="banner-block">렌더할 수 없습니다 — {BLOCK_TEXT[renderable] ?? renderable}</p>
        ) : active ? (
          <p className="dk-kv">진행 중: {JOB_LABEL[active.status]} (시도 {active.attempt_no}) <CancelRender jobId={active.id} />
            {active.cancel_requested && <span className="muted"> · 취소 요청됨(워커가 다음 확인 때 멈춥니다)</span>}</p>
        ) : isExplainer ? null : legacyVideo ? (
          <p className="banner-info">옛 그림 나열식 영상 제작안입니다 — 유료 그림 결재는 <Link href={`/drinks/production/${plan.id}?legacy=1`}>옛 제작 화면</Link>에서 합니다.</p>
        ) : (
          <div className="actions">
            <RenderRequest planId={plan.id} label={manifests.length ? "다시 렌더" : "제작 시작 (0원)"} hidePrimary />
            {lastFailed && <RenderRequest planId={plan.id} retryOf={lastFailed.id} label="실패한 작업 재시도" />}
            <span className="muted">카드와 릴스 영상이 함께 나옵니다(로컬·0원).</span>
          </div>
        )}
        {isExplainer && !renderable && (
          <ExplainerProduction planId={plan.id} status={explainer} activeJob={active ? { renderer: active.renderer, status: active.status } : null} hidePrimary />
        )}
        <p className="muted">비용 합계(이 제작안): ${total.toFixed(4)} — 공급자·모델별 기록 {costs.length}건</p>
        <details className="dk-sub">
          <summary className="muted">제작 작업 {jobs.length}건</summary>
          {jobs.length === 0 ? <p className="muted">아직 요청한 렌더가 없습니다.</p> : jobs.map((j) => (
            <div key={j.id} className="list-row">
              <span>
                <span className={j.status === "failed" ? "pill dk-bad" : j.status === "succeeded" ? "pill dk-ok" : "pill"}>{j.status === "succeeded" ? (JOB_DONE_LABEL[j.renderer] ?? JOB_LABEL[j.status]) : JOB_LABEL[j.status]}</span>{" "}
                시도 {j.attempt_no} · {j.renderer}({j.renderer_version}) · 요청 {fmtTime(j.created_at)} · 끝 {fmtTime(j.finished_at)}
                {j.error_code && <span className="muted"> · {j.error_code}: {j.error_message}</span>}
              </span>
            </div>
          ))}
        </details>
      </>
    );
    const f = plan.format as Format;
    nodes.output = (
      <>
        <p className="muted">다시 렌더해 파일이 달라지면 새 묶음이 생기고 옛 묶음·판정은 그대로 남습니다. 고칠 점이 있으면 제작안을 새 버전으로 고친 뒤 렌더하세요.</p>
        {manifests.length === 0 && <p className="muted">아직 만들어진 파일이 없습니다.</p>}
        {manifests.map((m) => (
          <article key={m.manifest.id} className="card">
            <div className="dk-row">
              {m.review && <span className={m.review.status === "approved" ? "pill dk-ok" : m.review.status === "blocked" ? "pill dk-bad" : "pill dk-warn"}>{REVIEW_LABEL[m.review.status]}</span>}
              {m.review?.status === "approved" && !m.currentlyUsable && <span className="pill dk-bad">지금 사용 불가 — {BLOCK_TEXT[m.currentBlock ?? ""] ?? m.currentBlock}</span>}
              <span className="pill">묶음 {m.manifest.manifest_hash.slice(0, 10)}</span>
              <span className="muted">{fmtTime(m.manifest.created_at)}</span>
            </div>
            {m.review?.reason && <p className="muted">{m.review.reason}</p>}
            {m.review && <QaPanel qa={m.review.qa_summary} />}
            <div className="dk-row" style={{ alignItems: "flex-start" }}>
              {m.files.map((file) => (
                <div key={file.id} style={{ maxWidth: f === "video" ? 260 : 200 }}>
                  <div className="muted">{file.role === "page" ? `${file.position}쪽` : file.role === "final_video" ? "최종 영상" : "커버"}
                    {file.width ? ` · ${file.width}×${file.height}` : ""}{file.duration_ms ? ` · ${(file.duration_ms / 1000).toFixed(1)}초` : ""}</div>
                  {file.url ? (
                    file.mime === "video/mp4"
                      ? <video src={file.url} controls style={{ width: "100%" }} />
                      // eslint-disable-next-line @next/next/no-img-element
                      : <img src={file.url} alt={`${file.role} ${file.position}`} style={{ width: "100%" }} />
                  ) : file.state !== "stored" ? (
                    <p className="dk-bad">파일 상태: {file.state}</p>
                  ) : file.storage_key.startsWith("local:") ? (
                    <p className="muted">로컬 저장({file.storage_key.replace(/^local:/, "")}) — 브라우저 미리보기 불가</p>
                  ) : (
                    <p className="dk-bad">미리보기 링크를 만들지 못했습니다 — {file.urlError}</p>
                  )}
                  {file.url && <a href={file.url} download>다운로드</a>}
                </div>
              ))}
            </div>
            {m.review && (!isExplainer || ["quality_review_pass", "ready_to_publish"].includes(explainer.episode?.state ?? "")) && (
              <OutputReview review={m.review} format={f} usableNow={!m.currentBlock} hasReel={f === "carousel" && m.files.some((x) => x.role === "final_video")} hidePrimary />
            )}
          </article>
        ))}
      </>
    );
  }

  // 발행안 · 게시 승인 · 게시 뒤
  if (publish.state !== "ok") {
    nodes.publish = <PublishProblem publish={publish} />;
    nodes.post = <PublishProblem publish={publish} />;
    nodes.after = <PublishProblem publish={publish} />;
  } else {
    const board = publish.data;
    const planIds = new Set(lanePlans.map((p) => p.id));
    const ready = board.ready_outputs.filter((o) => planIds.has(o.plan_revision_id));
    const accounts = publishable(board);
    const slotHint = slotHintOf(board);
    const aiLabel = board.ai_label_text ?? "AI 생성 영상";
    nodes.publish = ready.length === 0 ? (
      <p className="muted">발행안을 만들 수 있는 파일 묶음이 없습니다 — 산출물 승인이 끝나고 근거가 유효해야 합니다. 이미 발행안을 만든 묶음은 아래 게시 승인 칸에 있습니다.</p>
    ) : ready.map((o) => {
      const types = o.post_types ?? [o.format === "carousel" ? "carousel" : "reel"];
      const primaryType = lane === "card" ? (types.includes("carousel") ? "carousel" : types[0]) : "reel";
      const rest = types.filter((t) => t !== primaryType);
      return (
        <div key={o.output_review_id} className="dk-sub">
          <div className="dk-row"><b>{primaryType === "carousel" ? `카드뉴스 ${o.pages}장` : lane === "explainer" ? "설명형 릴스" : "카드뉴스 릴스"}</b><span className="muted">검수 {kst(o.reviewed_at)}</span></div>
          {lane === "explainer" && <p className="muted">설명형은 캡션에 &apos;{aiLabel}&apos; 한 줄이 있어야 발행안을 만들 수 있습니다(기획 v2 §3-4).</p>}
          {types.includes(primaryType) && (
            <CreatePublication outputReviewId={o.output_review_id} accounts={accounts} postType={primaryType} slotHint={slotHint}
              audioOptions={board.audio_options} audioRequired={primaryType === "reel" && o.format === "carousel"} hidePrimary />
          )}
          {rest.map((t) => (
            <details key={t} className="dk-sub">
              <summary className="muted">{t === "reel" ? "릴스로도 올리기 — 음원 필수" : "카드뉴스로 올리기"}</summary>
              <CreatePublication outputReviewId={o.output_review_id} accounts={accounts} postType={t} slotHint={slotHint}
                audioOptions={board.audio_options} audioRequired={t === "reel" && o.format === "carousel"} />
            </details>
          ))}
        </div>
      );
    });
    const requests = board.requests.filter((r) => (r.plan_revision_id ? planIds.has(r.plan_revision_id) : r.topic_id === topic.id && (r.content_format ?? "card") === lane));
    const { post, after } = PostSections(requests, board, true);
    nodes.post = post;
    nodes.after = after;
  }

  return laneSections(lane).map((s) => ({ key: s.key, label: s.label, node: nodes[s.key] ?? <p className="muted">—</p> }));
}

export interface MemeLaneInput {
  memeWork: MemeWorkLoaded;
  draft: MemeDraftRow | null;
  /** 제작안이 아직 없을 때 어디서 만들지 */
  owner: { topicId?: string; cardId?: string };
  publish: Loaded<PublishBoard>;
}

/** 밈 레인(소재 밈·카드 밈 공통). */
export function buildMemeLane(input: MemeLaneInput): SectionView[] {
  const { memeWork, draft, owner, publish } = input;
  const nodes: Partial<Record<SectionKey, ReactNode>> = {};

  if (memeWork.state === "missing") {
    nodes.meme = <div className="banner-warn" role="status">0066 이 운영 DB 에 아직 없습니다 — 제작안이 0건인 것이 아니라 적용 전입니다.</div>;
  } else if (memeWork.state !== "ok") {
    nodes.meme = <LoadProblem state={memeWork.state} error={memeWork.state === "failed" ? memeWork.error : undefined} />;
  } else if (!draft) {
    nodes.meme = (
      <>
        <p className="muted">아직 밈 제작안이 없습니다. 글(윗줄·비트·반전)을 적어 초안을 만듭니다 — 글 초안을 모델에 맡기려면 결재 안에서만 됩니다.</p>
        <MemeDraftForm topicId={owner.topicId} cardId={owner.cardId} budgets={memeWork.data.budgets} reviews={memeWork.data.reviews} />
      </>
    );
  } else {
    const urls = memeWork.data.urls[draft.id] ?? {};
    const manual = draft.status === "manual_audio";
    nodes.meme = (
      <>
        <div className="dk-row">
          <span className={draft.status === "publish_waiting" ? "pill on" : draft.status === "stopped" || draft.status === "failed" ? "pill reject" : "pill"}>{MEME_STATUS_LABEL[draft.status]}</span>
          {draft.sync_grade === "sync_required" && <span className="pill dk-warn">박자 맞춤 — 자동 게시 안 함</span>}
        </div>
        {draft.spec.top_line && <p style={{ margin: "4px 0" }}><b>{draft.spec.top_line}</b> <span className="muted">· {(draft.spec.beats ?? []).map((b) => b.text).join(" / ")}</span></p>}
        {memeNextStep(draft.status) && <p className="muted" style={{ fontSize: 13 }}>{memeNextStep(draft.status)}</p>}
        {draft.error_message && <p className="dk-bad" style={{ fontSize: 13 }}>{draft.error_code}: {draft.error_message}</p>}
        {draft.status === "draft" && draft.blockers.map((b, i) => <p key={i} className="dk-bad" style={{ fontSize: 13, margin: "2px 0" }}>{b.message}</p>)}
        {urls.final_video && <video src={urls.final_video} controls preload="metadata" style={{ width: 220, display: "block", marginTop: 6 }} />}
        {!manual && <MemeDraftActions draft={draft} hidePrimary />}
        {draft.status === "draft" && <details className="dk-sub"><summary className="muted">제작안 고치기</summary><MemeDraftForm draft={draft} budgets={memeWork.data.budgets} reviews={memeWork.data.reviews} /></details>}
      </>
    );
  }

  if (publish.state !== "ok") {
    nodes.publish = <PublishProblem publish={publish} />;
    nodes.post = <PublishProblem publish={publish} />;
    nodes.after = <PublishProblem publish={publish} />;
  } else {
    const board = publish.data;
    const requests = draft ? board.requests.filter((r) => r.meme_draft_id === draft.id) : [];
    const readyMeme = draft ? (board.ready_memes ?? []).find((m) => m.draft_id === draft.id) ?? null : null;
    if (!draft) {
      nodes.publish = <p className="muted">제작안을 승인하고 렌더가 끝나면 여기서 발행안을 만듭니다.</p>;
    } else if (draft.status === "manual_audio") {
      nodes.publish = <p className="muted">박자 맞춤 밈은 웹 발행안을 만들지 않습니다 — 아래 게시 승인 칸의 안내대로 앱에서 올립니다.</p>;
    } else if (readyMeme) {
      nodes.publish = (
        <>
          {readyMeme.audio_mode === "ig_audio" && <p className="muted">제작안이 정한 인스타 음원({readyMeme.audio_id})을 붙여야 합니다 — Facebook 로그인 계정으로만.</p>}
          <CreateMemePublication draftId={readyMeme.draft_id} accounts={publishable(board)} defaultCaption={readyMeme.caption ?? ""} slotHint={slotHintOf(board)}
            audioOptions={board.audio_options} audioRequired={readyMeme.audio_mode === "ig_audio"} boughtScene={!!readyMeme.bought_scene} hidePrimary />
        </>
      );
    } else {
      nodes.publish = <p className="muted">{draft.status === "publish_waiting" ? "이 제작안의 발행안은 이미 만들어졌습니다 — 아래 게시 승인 칸에서 이어집니다." : "게시 대기(publish_waiting)가 되면 여기서 발행안을 만듭니다."}</p>;
    }
    const { post, after } = PostSections(requests, board, true);
    nodes.post = draft?.status === "manual_audio" ? (
      <>
        <p className="banner-info"><b>앱에서 붙여 올리기</b> — 박자 맞춤 밈은 웹에서 자동 게시하지 않습니다. 완성 영상을 받아 인스타 앱에서 지정 음원을 고르고 반전 장면을 박자에 맞춰 직접 게시한 뒤, 아래에 주소를 적고 [게시했음]을 누르세요.</p>
        {draft.guide && <pre style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{draft.guide}</pre>}
        <MemeDraftActions draft={draft} hidePrimary />
      </>
    ) : post;
    nodes.after = (
      <>
        {draft?.status === "posted_manual" && draft.external_url && safeHref(draft.external_url) && (
          <p><span className="pill on">앱에서 게시함</span> <a href={safeHref(draft.external_url)!} target="_blank" rel="noreferrer noopener">앱으로 올린 릴스</a></p>
        )}
        {after}
      </>
    );
  }

  return laneSections("meme").map((s) => ({ key: s.key, label: s.label, node: nodes[s.key] ?? <p className="muted">—</p> }));
}

/** ▾ 이력 — drink_workflow_events(추가만 가능). 더 보려면 옛 화면의 이력 탭. */
export function HistoryPanel({ events, total, legacyHref }: { events: EventRow[]; total: number; legacyHref: string | null }) {
  if (events.length === 0) return <p className="muted">이력이 없습니다(정상 0건).</p>;
  return (
    <>
      <h3 style={{ marginTop: 0 }}>이력 — 전체 {total}건 중 최근 {events.length}건</h3>
      {total > events.length && legacyHref && <p className="muted">오래된 이력은 <Link href={legacyHref}>옛 화면의 이력 탭</Link>에서 더 봅니다.</p>}
      {events.map((e) => (
        <div key={e.id} className="list-row">
          <span>
            <b>{e.action}</b> <span className="muted">{e.entity_type}</span>
            {e.before_status || e.after_status ? ` · ${e.before_status ?? "—"} → ${e.after_status ?? "—"}` : ""}
            {e.reason && <span className="muted"> · {e.reason}</span>}
          </span>
          <span className="muted">{seoulDateTimeLabel(e.created_at)}</span>
        </div>
      ))}
    </>
  );
}

export function formatOfLane(lane: FormatIntent): Format | null {
  return lane === "meme" ? null : PLAN_FORMAT_OF[lane];
}
