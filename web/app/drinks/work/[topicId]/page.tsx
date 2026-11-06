// 작업공간 (/drinks/work/[topicId]?lane=&panel=&plan=&meme=) — 한 소재의 형식(릴스·카드·밈)마다 끝까지(기획 v2 §6-3,
// docs/deviation-drinks-multi-format.md §3-5). 데이터는 기존 로더로 읽고, 섹션은 기존 컴포넌트를 그대로 쓴다. 결정(주 버튼 하나)은
// web/lib/drinks/work/decision.ts(담당 B) 가 하고, 작업 단위 행은 queries.ts::loadTopicWork(담당 B)·뷰 drink_work_items(0072, 담당 A) 가 준다.
//
// ★ ?lane= 이 정본이다. 없으면 이 소재의 첫 형식. `/drinks/work/meme?meme=<draftId>` 는 카드 소유 밈(소재 없음).
// ★ 승인·결재·제작·게시의 규칙은 전부 서버(DB)다. 이 화면은 보여 주고 요청할 뿐이다.
import Link from "next/link";

import DrinksWorkspace, { type FormatCardView } from "@/components/drinks/work/DrinksWorkspace";
import { HistoryPanel, buildMemeLane, buildTopicLane, PLAN_FORMAT_OF } from "@/components/drinks/work/laneSections";
import LoadProblem from "@/components/drinks/LoadProblem";
import { todayInSeoul } from "@/lib/date";
import type { MemeDraftRow } from "@/lib/drinks/meme";
import { loadMemeWork } from "@/lib/drinks/memeQueries";
import { loadPlanProduction } from "@/lib/drinks/productionQueries";
import { loadPublishBoard } from "@/lib/drinks/publishQueries";
import { loadDevelop, loadTopic } from "@/lib/drinks/queries";
import { loadWeeklyBudget } from "@/lib/drinks/weeklyBudget";
import { decide } from "@/lib/drinks/work/decision";
import { draftStorageKey, isFormatIntent, openSection, orderLanes, primarySectionOf } from "@/lib/drinks/work/lanes";
import { loadTopicWork, loadWorkItems } from "@/lib/drinks/work/queries";
import { FORMAT_LABEL, workHref, type Decision, type FormatIntent, type WorkItem } from "@/lib/drinks/work/types";

export const dynamic = "force-dynamic";

const MEME_LIVE = (d: MemeDraftRow) => !["rejected", "stopped", "failed", "posted_manual"].includes(d.status);
const PUB_FINISHED = new Set(["published", "failed", "canceled", "unknown"]);
const hasLivePub = (it: WorkItem | null) => Boolean(it?.pub_request_id && it.pub_status && !PUB_FINISHED.has(it.pub_status));

/** 담당 B 의 loadTopicWork/loadWorkItems 결과에서 작업 단위 행을 꺼낸다. 모양은 계약(§3-3 행 목록)이고, 실패는 이유 문자열로 돌려준다. */
function unpackItems(res: unknown): { items: WorkItem[]; problem: string | null } {
  if (Array.isArray(res)) return { items: res as WorkItem[], problem: null };
  const r = res as { state?: string; error?: string; data?: unknown; items?: unknown } | null;
  if (!r || typeof r !== "object") return { items: [], problem: "작업 단위 조회 결과가 비었습니다." };
  if (r.state && r.state !== "ok") return { items: [], problem: r.state === "failed" ? (r.error ?? "조회 실패") : r.state === "not_found" ? "소재 없음" : "서버 키 없음(unconfigured)" };
  const d = (r.data ?? r) as { items?: unknown } | unknown[];
  const list = Array.isArray(d) ? d : Array.isArray((d as { items?: unknown }).items) ? (d as { items: unknown[] }).items : null;
  if (!list) return { items: [], problem: "작업 단위 행 모양을 알 수 없습니다(items 배열 없음)." };
  return { items: list as WorkItem[], problem: null };
}

function safeDecide(item: WorkItem | null, explainer: unknown): { decision: Decision | null; problem: string | null } {
  if (!item) return { decision: null, problem: null };
  try {
    return { decision: decide(item, explainer as Parameters<typeof decide>[1]), problem: null };
  } catch (e) {
    return { decision: null, problem: e instanceof Error ? e.message : String(e) };
  }
}

export default async function DrinksWorkspacePage(props: {
  params: Promise<{ topicId: string }>;
  searchParams: Promise<{ lane?: string; panel?: string; plan?: string; meme?: string }>;
}) {
  const { topicId } = await props.params;
  const sp = await props.searchParams;
  if (topicId === "meme") return <CardMemeWorkspace memeDraftId={sp.meme ?? null} panel={sp.panel ?? null} />;

  // 이번 주 AI 초안 한도(0073)를 먼저 만든다 — 소재 고르기 화면을 거치지 않고 바로 들어와도 아래 개발 상태가 이번 주 한도를 본다.
  // 실패해도 화면은 세운다(한도 칸이 '없음'으로 보이고, 버튼이 그 이유를 말한다). 소재 고르기 화면(topics/page.tsx)과 같은 순서다.
  await loadWeeklyBudget();

  // loadTopicWork 가 소재 상세·개발 상태·작업 단위를 한 번에 준다. 0072 전(또는 rpc 실패)이면 작업 단위 없이 옛 로더로 화면을 세운다 —
  // 조회 실패를 "할 일 없음"으로 바꾸지 않고 결정 바에 그 이유를 적는다.
  const workRes = await loadTopicWork(topicId).catch((e: unknown) => ({ state: "failed" as const, error: e instanceof Error ? e.message : String(e) }));
  if (workRes.state === "not_found") return <NotFound what="소재" />;
  const res = workRes.state === "ok" ? { state: "ok" as const, data: workRes.data.topic } : await loadTopic(topicId);
  if (res.state === "not_found") return <NotFound what="소재" />;
  if (res.state !== "ok") return <main className="container"><LoadProblem state={res.state} error={res.state === "failed" ? res.error : undefined} /></main>;
  const detail = res.data;
  const { topic } = detail;
  const { items: allItems, problem: itemsProblem } = unpackItems(workRes);
  const items = allItems.filter((i) => i.topic_id === topicId);
  // 레인 = 이 소재가 고른 형식들. 작업 단위를 못 읽었으면 옛 선택(pick·selected_formats)으로 대신 세운다.
  const fallbackLanes: FormatIntent[] = [
    ...(detail.pick ? [detail.pick.format_intent] : []),
    ...((topic.selected_formats ?? []).map((f) => (f === "carousel" ? "card" : "explainer")) as FormatIntent[]),
  ];
  const lanes = orderLanes(items.length ? items.map((i) => i.format_intent) : fallbackLanes);
  const lane: FormatIntent = isFormatIntent(sp.lane) ? sp.lane : lanes[0] ?? "explainer";
  const laneList = lanes.includes(lane) ? lanes : orderLanes([...lanes, lane]);
  const item = items.find((i) => i.format_intent === lane && i.source === "topic") ?? items.find((i) => i.format_intent === lane) ?? null;

  const today = todayInSeoul();
  const legacyHref = `/drinks/review/${topic.id}?legacy=1`;
  const [develop, publish] = await Promise.all([workRes.state === "ok" ? workRes.data.develop : loadDevelop(topic.id), loadPublishBoard()]);

  let sections;
  let decision: Decision | null = null;
  let decisionProblem = itemsProblem;
  let published = false;
  let storageKey = draftStorageKey(topic.id, lane);

  if (lane === "meme") {
    const memeWork = await loadMemeWork();
    const drafts = memeWork.state === "ok" ? memeWork.data.drafts.filter((d) => d.topic_id === topic.id) : [];
    const draft = drafts.find(MEME_LIVE) ?? drafts[0] ?? null;
    const dec = safeDecide(item, null);
    decision = dec.decision;
    decisionProblem = decisionProblem ?? dec.problem;
    published = draft?.status === "published" || draft?.status === "posted_manual";
    storageKey = draftStorageKey(topic.id, lane, draft?.id);
    sections = buildMemeLane({ memeWork, draft, owner: { topicId: topic.id }, publish });
  } else {
    const planFormat = PLAN_FORMAT_OF[lane];
    const deliverable = detail.deliverables.find((x) => x.format === planFormat) ?? null;
    const currentPlanId = deliverable?.current_revision_id ?? item?.plan_revision_id ?? null;
    const planId = sp.plan ?? currentPlanId;
    const production = planId ? await loadPlanProduction(planId) : null;
    const explainer = production && production.state === "ok" ? production.data.explainer : null;
    const dec = safeDecide(item, explainer);
    decision = dec.decision;
    decisionProblem = decisionProblem ?? dec.problem;
    published = item?.pub_status === "published";
    sections = buildTopicLane({ lane, detail, develop, item, production, planRequested: sp.plan ?? null, publish, today });
  }

  const formats: FormatCardView[] = laneList.map((f) => {
    const it = items.find((i) => i.format_intent === f && i.source === "topic") ?? items.find((i) => i.format_intent === f) ?? null;
    const d = f === lane ? decision : safeDecide(it, null).decision;
    return {
      lane: f,
      stage: d ? d.primary.label : it ? "상태 모름" : "작업 단위 없음",
      href: workHref({ topic_id: topic.id, format_intent: f, meme_draft_id: null, source: "topic" }),
      current: f === lane,
      blocked: Boolean(d && d.blocks.length > 0),
    };
  });

  const primarySection = primarySectionOf(lane, decision?.primary.panel ?? null, hasLivePub(item));
  const openKey = openSection(lane, sp.panel ?? null, decision?.primary.panel ?? null, published, hasLivePub(item));

  return (
    <main className="container container--dw">
      <p className="muted"><Link href="/drinks/work">← 만들기</Link> · <Link href="/drinks">오늘 할 일</Link></p>
      <DrinksWorkspace
        topicId={topic.id}
        lane={lane}
        title={topic.title}
        question={topic.question}
        formats={formats}
        decision={decision}
        decisionProblem={decisionProblem}
        sections={sections}
        openKey={openKey}
        primarySection={primarySection}
        history={<HistoryPanel events={detail.events} total={detail.eventsTotal} legacyHref={`${legacyHref}&tab=history`} />}
        hold={["inbox", "triaged", "researching", "ready", "selected"].includes(topic.status) ? { topicId: topic.id, version: topic.version } : null}
        storageKey={storageKey}
        legacyHref={legacyHref}
        editorialWeek={item?.editorial_week ?? null}
      />
    </main>
  );
}

/** 카드 소유 밈(/drinks/work/meme?meme=) — 소재가 없으니 형식 카드는 밈 하나, 보류 없음. */
async function CardMemeWorkspace({ memeDraftId, panel }: { memeDraftId: string | null; panel: string | null }) {
  if (!memeDraftId) return <NotFound what="밈 제작안(?meme= 없음)" />;
  const [memeWork, publish, workRes] = await Promise.all([
    loadMemeWork(),
    loadPublishBoard(),
    loadWorkItems("all").catch((e: unknown) => ({ state: "failed", error: e instanceof Error ? e.message : String(e) })),
  ]);
  if (memeWork.state === "failed" || memeWork.state === "unconfigured") {
    return <main className="container"><LoadProblem state={memeWork.state} error={memeWork.state === "failed" ? memeWork.error : undefined} /></main>;
  }
  const draft = memeWork.state === "ok" ? memeWork.data.drafts.find((d) => d.id === memeDraftId) ?? null : null;
  if (memeWork.state === "ok" && !draft) return <NotFound what="밈 제작안" />;
  const { items, problem } = unpackItems(workRes);
  const item = items.find((i) => i.unit_id === `meme_card:${memeDraftId}` || i.meme_draft_id === memeDraftId) ?? null;
  const dec = safeDecide(item, null);
  const title = draft?.owner_name ?? "(카드 이름 없음)";
  const published = draft?.status === "published" || draft?.status === "posted_manual";
  const sections = buildMemeLane({ memeWork, draft, owner: { cardId: draft?.card_id ?? undefined }, publish });
  return (
    <main className="container container--dw">
      <p className="muted"><Link href="/drinks/work">← 만들기</Link> · <Link href="/drinks/memes?legacy=1">밈 보드</Link></p>
      <DrinksWorkspace
        topicId="meme"
        lane="meme"
        title={title}
        question={null}
        formats={[{ lane: "meme", stage: dec.decision?.primary.label ?? (item ? "상태 모름" : `${FORMAT_LABEL.meme} · 작업 단위 없음`), href: workHref({ topic_id: null, format_intent: "meme", meme_draft_id: memeDraftId, source: "card" }), current: true, blocked: Boolean(dec.decision?.blocks.length) }]}
        decision={dec.decision}
        decisionProblem={problem ?? dec.problem}
        sections={sections}
        openKey={openSection("meme", panel, dec.decision?.primary.panel ?? null, published, hasLivePub(item))}
        primarySection={primarySectionOf("meme", dec.decision?.primary.panel ?? null, hasLivePub(item))}
        history={<p className="muted">카드 밈은 소재 이력이 없습니다. 제작안 상태 변화는 밈 보드에서 봅니다.</p>}
        hold={null}
        storageKey={draftStorageKey("meme", "meme", memeDraftId)}
        legacyHref="/drinks/memes?legacy=1"
        editorialWeek={item?.editorial_week ?? null}
      />
    </main>
  );
}

function NotFound({ what }: { what: string }) {
  return (
    <main className="container">
      <h1 style={{ fontSize: 20 }}>찾지 못했습니다</h1>
      <p>{what}을(를) 찾지 못했습니다. 주소가 옛것이거나 지워졌을 수 있습니다.</p>
      <p><Link href="/drinks/work">만들기 목록으로 →</Link></p>
    </main>
  );
}
