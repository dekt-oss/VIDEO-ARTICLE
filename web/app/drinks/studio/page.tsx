// 콘텐츠 스튜디오(/drinks/studio?topic=) — ① 소재 고르기 ② 초안 다듬기 ③ 버전·생성. 운영자 확정 목업(2026-11-07) 기준.
// 계약: docs/deviation-drinks-studio.md · supabase/migrations/0076_drinks_studio.sql. 규칙은 전부 DB 함수이고, 이 화면은 보여 주고 요청만 한다.
// ★ 실패를 빈 목록으로 바꾸지 않는다 — 읽기 실패는 그 칸에 이유를 적는다.
import "./studio.css";

import StudioClient, { type StudioCollectItem, type StudioProduction, type StudioPublish, type StudioResultFile } from "@/components/drinks/studio/StudioClient";
import { HeldTab, MineSection, STUDIO_TABS, StudioTabNav, type StudioTab } from "@/components/drinks/studio/StudioTabs";
import ManualEntry from "@/components/drinks/topics/ManualEntry";
import MemeCardsTab from "@/components/drinks/topics/MemeCardsTab";
import WeeklyBudgetCard from "@/components/drinks/topics/WeeklyBudgetCard";
import { pickDefaults } from "@/lib/drinks/pickModal";
import { loadPlanProduction } from "@/lib/drinks/productionQueries";
import { loadPublishBoard } from "@/lib/drinks/publishQueries";
import { INSUFFICIENT, activePlan, type StudioLane, type StudioStatus } from "@/lib/drinks/studio";
import { isStopped } from "@/lib/drinks/studioList";
import { loadStudioCandidates } from "@/lib/drinks/topicsQueries";
import { loadWeeklyBudget } from "@/lib/drinks/weeklyBudget";
import { PLATFORM_LABEL } from "@/lib/drinks/discovery";
import { CATEGORY_LABEL } from "@/lib/drinks/model";
import { createAdminClient } from "@/lib/supabase/admin";
import { selectIn } from "@/lib/supabase/chunked";

export const dynamic = "force-dynamic";

const ID = /^[0-9a-f-]{36}$/i;

/** "naver_cafe:온미르클럽 · naver_blog:…" → "네이버 카페 온미르클럽 · …"(앞 두 곳만). */
function pathLabel(path: string | null): string | null {
  if (!path) return null;
  const parts = path.split(" · ").map((x) => { const [p, ...rest] = x.split(":"); return `${PLATFORM_LABEL[p] ?? p}${rest.length ? ` ${rest.join(":")}` : ""}`; });
  return parts.slice(0, 2).join(" · ") + (parts.length > 2 ? ` 외 ${parts.length - 2}곳` : "");
}

const isTest = (title: string) => title.startsWith("[테스트]");

export default async function StudioPage(props: { searchParams: Promise<{ topic?: string; tab?: string; page?: string; lane?: string }> }) {
  const sp = await props.searchParams;
  const db = createAdminClient();
  if (!db) return <main className="container"><p className="banner-warn">서버에 SUPABASE_SERVICE_KEY 가 없어 읽을 수 없습니다.</p></main>;
  const topicId = sp.topic && ID.test(sp.topic) ? sp.topic : null;
  const lane: StudioLane | null = sp.lane === "card" || sp.lane === "explainer" ? sp.lane : null;
  const tab: StudioTab | null = !topicId && sp.tab && sp.tab in STUDIO_TABS ? (sp.tab as StudioTab) : null;
  if (tab) {
    return (
      <main className="container">
        <div className="dk-head"><p className="dk-eyebrow">CONTENT STUDIO</p><h1 className="dk-h1">{STUDIO_TABS[tab]}</h1></div>
        <StudioTabNav tab={tab} />
        {tab === "mine" && <MineSection />}
        {tab === "memes" && <MemeCardsTab />}
        {tab === "held" && <HeldTab page={Math.max(1, Number(sp.page) || 1)} />}
      </main>
    );
  }

  // 이번 주 한도 줄을 먼저 확보한다(없으면 DB 가 만든다).
  const wb = await loadWeeklyBudget();
  // 이미 있는 소재(제외·중복 처리 포함) — 같은 이야기를 후보로 다시 올리지 않는다. 시험 소재는 세지 않는다.
  const known = await db.from("drink_topics").select("id, title, question, status, categories, discovery_platforms, updated_at")
    .order("updated_at", { ascending: false }).range(0, 999);
  const knownRows = (known.data ?? []) as { id: string; title: string; question: string; status: string; categories: string[] | null; discovery_platforms: string[] | null }[];
  const mineRows = knownRows.filter((t) => ["researching", "ready", "selected"].includes(t.status) && !isTest(t.title)).slice(0, 15);
  const mineIds = mineRows.map((t) => t.id);
  const [cands, lastRes, planRes, statusRes] = await Promise.all([
    loadStudioCandidates(knownRows.filter((t) => !isTest(t.title)).map((t) => ({ id: t.id, text: `${t.title} ${t.question}`, categories: t.categories ?? [] }))),
    mineIds.length ? db.from("drink_develop_requests").select("topic_id, status, error_code, created_at").in("topic_id", mineIds).order("created_at", { ascending: false }).range(0, 999) : Promise.resolve({ data: [], error: null }),
    mineIds.length ? db.from("drink_plan_revisions").select("topic_id, format, plan_status").in("topic_id", mineIds).in("plan_status", ["draft", "approved"]).range(0, 999) : Promise.resolve({ data: [], error: null }),
    topicId ? db.rpc("drinks_studio_status", { p: { topic_id: topicId } }) : Promise.resolve(null),
  ]);

  const items: StudioCollectItem[] = [];
  const problems: string[] = [];
  if (known.error) problems.push(`만들고 있는 소재: ${known.error.message}`);
  if (lastRes.error) problems.push(`소재 진행 상태: ${lastRes.error.message} — 멈춘 소재가 섞여 보일 수 있어요`);
  if (planRes.error) problems.push(`초안 형식: ${planRes.error.message}`);
  const lastByTopic = new Map<string, { status: string; error_code: string | null }>();
  for (const r of (lastRes.data ?? []) as { topic_id: string; status: string; error_code: string | null }[]) if (!lastByTopic.has(r.topic_id)) lastByTopic.set(r.topic_id, r);
  const plans = (planRes.data ?? []) as { topic_id: string; format: string }[];
  let stopped = 0;
  for (const t of mineRows) {
    // 자료 부족 등으로 멈춘 소재는 다시 눌러도 같은 실패다 — 고를 목록에서 뺀다(내 소재 탭에는 남는다).
    if (isStopped(lastByTopic.get(t.id), INSUFFICIENT) && !plans.some((p) => p.topic_id === t.id)) { stopped += 1; continue; }
    const mine = plans.filter((p) => p.topic_id === t.id);
    items.push({ key: `t:${t.id}`, videoDraft: mine.length > 0 && !mine.some((p) => p.format === "carousel"), topicId: t.id, candidateId: null, title: t.title, question: t.question,
      kind: (t.categories ?? []).map((c) => CATEGORY_LABEL[c as keyof typeof CATEGORY_LABEL] ?? c).join(" · ") || "주제 미정",
      origin: (t.discovery_platforms ?? []).map((p) => PLATFORM_LABEL[p] ?? p).join(" · ") || "직접 등록한 소재",
      angle: null, inProgress: true, payload: {} });
  }
  let summary: string | undefined;
  if (cands.state !== "ok") problems.push(`수집함: ${cands.state === "failed" ? cands.error : "서버 키 없음"}`);
  else {
    if (cands.data.evidenceProblem) problems.push(`근거 수: ${cands.data.evidenceProblem} — 근거가 없는 후보가 섞여 보일 수 있어요`);
    summary = `수집한 질문 ${cands.data.total}개 중 자동으로 초안까지 만들 수 있는 것만 보여요. 비슷한 질문은 하나로 묶었어요.${stopped ? ` 자료가 부족해 멈춘 소재 ${stopped}개는 뺐어요.` : ""}`;
    for (const { candidate: c, merged } of cands.data.rows) {
      const d = pickDefaults(c.key_question);
      items.push({ key: `c:${c.id}`, topicId: c.promoted_topic_id, candidateId: c.promoted_topic_id ? null : c.id, title: d.title, question: d.question,
        kind: d.categories.map((x) => CATEGORY_LABEL[x]).join(" · ") || "주제 미정",
        origin: [pathLabel(c.discovery_path), c.interest?.items ? `글 ${c.interest.items}개에서 나온 질문` : null, merged ? `비슷한 질문 ${merged}개 합침` : null]
          .filter(Boolean).join(" · ") || "수집된 질문",
        angle: c.reader_value ?? c.first_scene ?? null, inProgress: false,
        payload: { candidate_id: c.id, title: d.title, question: d.question, categories: d.categories, ...(c.reader_value ? { reader_value: c.reader_value } : {}) } });
    }
  }

  let status: StudioStatus | null = null;
  let statusProblem: string | null = null;
  if (statusRes) {
    if (statusRes.error) statusProblem = statusRes.error.message;
    else status = statusRes.data as StudioStatus;
  }
  if (status && !items.some((x) => x.topicId === status!.topic.id)) {
    items.unshift({ key: `t:${status.topic.id}`, topicId: status.topic.id, candidateId: null, title: status.topic.title, question: status.topic.question,
      kind: "", origin: "", angle: null, inProgress: true, payload: {} });
  }

  // 이미 형식을 고른 소재는 서버가 그 형식을 따른다(drinks_studio_prepare) — 화면이 다른 형식을 고르게 해서 어긋나지 않게 표시해 둔다.
  const picks = await selectIn<{ topic_id: string; format_intent: string }>(items.flatMap((i) => (i.topicId ? [i.topicId] : [])),
    (ids) => db.from("drink_topic_format_picks").select("topic_id, format_intent").in("topic_id", ids), "drink_topic_format_picks.topic_id");
  for (const it of items) {
    const mine = picks.filter((p) => p.topic_id === it.topicId).map((p) => p.format_intent);
    it.cardPicked = mine.includes("card");
    if (mine.includes("explainer") && !it.cardPicked) it.videoDraft = true;   // 설명형으로 시작한 소재는 작업공간에서 잇는다
  }

  // 제작·검수·등록 상태: 승인된 초안의 최신 파일 묶음(서명 URL 1시간). 파일·검사 결과가 있는 것만 '완료'다.
  let files: StudioResultFile[] = [];
  let resultProblem: string | null = null;
  let production: StudioProduction | null = null;
  let publish: StudioPublish | null = null;
  const plan = activePlan(status, lane);
  if (plan && plan.plan_status === "approved") {
    const prod = await loadPlanProduction(plan.plan_revision_id);
    if (prod.state !== "ok") resultProblem = prod.state === "failed" ? prod.error : "제작 결과를 읽지 못했습니다";
    else {
      const latest = prod.data.manifests[0] ?? null;
      const active = prod.data.jobs.find((j) => j.status === "queued" || j.status === "running");
      files = latest ? latest.files.map((f) => ({ role: f.role, position: f.position, mime: f.mime, url: f.url, urlError: f.urlError,
        width: f.width, height: f.height, jobId: latest.manifest.job_id, reviewStatus: latest.review?.status ?? null,
        qa: (latest.review?.qa_summary as { ok?: boolean } | undefined)?.ok ?? null })) : [];
      production = {
        explainer: prod.data.explainer.is_explainer ? prod.data.explainer : null,
        activeJob: active ? { renderer: active.renderer, status: active.status } : null,
        outputReview: latest?.review ? { id: latest.review.id, version: latest.review.version, status: latest.review.status, hasReel: latest.files.some((f) => f.role === "final_video") } : null,
      };
      if (production.outputReview?.status === "approved") {
        const board = await loadPublishBoard();
        if (board.state === "ok") {
          const req = board.data.requests.filter((r) => r.plan_revision_id === plan.plan_revision_id && !["canceled"].includes(r.status))[0] ?? null;
          publish = {
            accounts: board.data.accounts.filter((a) => a.status !== "disabled" && a.publish_enabled).map((a) => ({ id: a.id, label: `${a.display_name} · ${a.external_account_id}`, postTypes: a.capabilities?.post_types ?? [] })),
            aiLabel: board.data.ai_label_text ?? null,
            request: req ? { id: req.id, version: req.version, status: req.status, approval_digest: req.approval_digest ?? null, caption: req.caption ?? null, publish_at: req.publish_at ?? null, external_url: req.external_url ?? null } : null,
          };
        }
      }
    }
  }

  return (
    <main className="container container--dw">
      <StudioClient items={items} problems={problems} status={status} statusProblem={statusProblem} files={files} resultProblem={resultProblem}
        selectedTopicId={topicId} lane={lane} production={production} publish={publish} summary={summary}
        header={<><StudioTabNav tab={null} /><WeeklyBudgetCard budget={wb.state === "ok" ? wb.data : null} error={wb.state === "error" ? wb.message : undefined} /></>}
        footer={<ManualEntry />} />
    </main>
  );
}
