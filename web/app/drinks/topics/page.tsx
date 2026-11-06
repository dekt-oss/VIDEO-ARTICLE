// 소재 고르기 (/drinks/topics) — 고를 것은 모두 여기에(2026-11-05, docs/deviation-drinks-multi-format.md §3-5 G10).
//   탭: 후보(기본) / 내 소재 / 밈 카드 / 보류·제외 (?tab=). 후보는 서버 페이지(?page=) + 서버 조건(형식 적합성 ?fit=).
//   머리 숫자: 전체 N(정확) · 표시 M(이번 쪽) · 지금 고를 수 있음 K(카드마다 계산). 조회 실패 / 부분 조회 / 수집 미실행 / 정상 0건을 가른다.
//   [이걸로 ▾] 는 형식을 여러 개 골라 pick_topic(formats) 하나로 보낸다. 옛 /drinks/discover · /drinks/memes 는 그대로 있다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import CandidateCard from "@/components/drinks/topics/CandidateCard";
import ManualEntry from "@/components/drinks/topics/ManualEntry";
import WeeklyBudgetCard from "@/components/drinks/topics/WeeklyBudgetCard";
import MemeCardsTab from "@/components/drinks/topics/MemeCardsTab";
import MineTab from "@/components/drinks/topics/MineTab";
import { todayInSeoul } from "@/lib/date";
import { pickBudget } from "@/lib/drinks/develop";
import { recommendFormat } from "@/lib/drinks/formatRecommend";
import { UNKNOWN_ESTIMATE, normalizeEstimate, pickability, weekOptions, type EstimateMap } from "@/lib/drinks/pickModal";
import { loadWeeklyBudget } from "@/lib/drinks/weeklyBudget";
import { loadTopicCandidates, type FitFilter, type TopicsCandidatesView } from "@/lib/drinks/topicsQueries";
import { decide, rankForHome } from "@/lib/drinks/work/decision";
import { loadDevelopEstimate, loadWorkItems } from "@/lib/drinks/work/queries";
import type { Decision, WorkItem } from "@/lib/drinks/work/types";

export const dynamic = "force-dynamic";

const TABS = { candidates: "후보", mine: "내 소재", memes: "밈 카드", held: "보류·제외" } as const;
type Tab = keyof typeof TABS;
const FIT_OPTIONS: { value: FitFilter; label: string }[] = [{ value: "", label: "형식 전체" }, { value: "video", label: "영상(릴스) 적합" }, { value: "carousel", label: "카드뉴스 적합" }];

type SP = { tab?: string; page?: string; fit?: string };

export default async function DrinksTopicsPage(props: { searchParams: Promise<SP> }) {
  const sp = await props.searchParams;
  const tab: Tab = sp.tab && sp.tab in TABS ? (sp.tab as Tab) : "candidates";
  const page = Math.max(1, Number(sp.page) || 1);
  const fit: FitFilter = sp.fit === "video" || sp.fit === "carousel" ? sp.fit : "";
  return (
    <main className="container">
      <div className="dk-head">
        <p className="dk-eyebrow">PICK A TOPIC</p>
        <h1 className="dk-h1">어떤 이야기를 만들까요?</h1>
        <p className="dk-lead">고를 것은 모두 여기에 있습니다. 고른 뒤에는 <Link href="/drinks/work">작업공간</Link>에서 이어집니다.</p>
      </div>
      <nav className="dk-tabs" aria-label="소재 탭">
        {(Object.keys(TABS) as Tab[]).map((k) => <Link key={k} href={`/drinks/topics?tab=${k}`} data-active={k === tab}>{TABS[k]}</Link>)}
      </nav>
      {tab === "candidates" && <CandidatesTab page={page} fit={fit} />}
      {tab === "held" && <HeldTab page={page} />}
      {tab === "mine" && <MineSection />}
      {tab === "memes" && <MemeCardsTab />}
      <ManualEntry />
    </main>
  );
}

/** 머리 숫자와 빈 상태. 조회 실패는 LoadProblem 이, 여기서는 부분 조회·수집 미실행·정상 0건을 가른다. */
function Header({ v, pickable }: { v: TopicsCandidatesView; pickable: number | null }) {
  const from = v.total === 0 ? 0 : (v.page - 1) * v.pageSize + 1;
  const to = Math.min(v.total, v.page * v.pageSize);
  return (
    <>
      <div>
        <p className="dk-counts">
          전체 <b>{v.total}</b>건{pickable !== null && <> · 지금 고를 수 있는 <b>{pickable}</b>건</>}
        </p>
        <p className="dk-counts-sub">
          이번 쪽 {v.candidates.length}건 표시{v.total > 0 && <> ({from}–{to})</>}{pickable !== null && " · 고를 수 있는 수는 이번 쪽 기준"}
        </p>
      </div>
      {v.partial.length > 0 && (
        <p className="banner-warn" role="status"><b>부분 조회</b> — 목록은 맞지만 일부 값을 못 읽었습니다: {v.partial.join(" · ")}</p>
      )}
      {v.total === 0 && v.collection === "never" && (
        <p className="banner-warn" role="status">아직 발견 수집이 한 번도 돌지 않았습니다 — 0건이 아니라 수집 전입니다. <Link href="/drinks/sources">수집원</Link>에서 발견 채널을 활성화하세요. 아래 [손으로 넣기]로 직접 등록할 수 있습니다.</p>
      )}
      {v.total === 0 && v.collection === "ran" && <p className="muted">이 조건의 후보가 없습니다(정상 0건).</p>}
      {v.total === 0 && v.collection === "unknown" && <p className="banner-warn" role="status">후보가 0건인데 수집이 돌았는지 확인하지 못했습니다(정상 0건인지 수집 전인지 모름).</p>}
    </>
  );
}

function Pager({ v, tab, fit }: { v: TopicsCandidatesView; tab: Tab; fit: FitFilter }) {
  const last = Math.max(1, Math.ceil(v.total / v.pageSize));
  if (last <= 1) return null;
  const href = (p: number) => `/drinks/topics?tab=${tab}&page=${p}${fit ? `&fit=${fit}` : ""}`;
  return (
    <div className="dk-pager">
      {v.page > 1 ? <Link className="btn" href={href(v.page - 1)}>← 앞 페이지</Link> : <span className="btn" aria-disabled="true">← 앞 페이지</span>}
      <span className="muted">{v.page} / {last}</span>
      {v.page < last ? <Link className="btn" href={href(v.page + 1)}>다음 페이지 →</Link> : <span className="btn" aria-disabled="true">다음 페이지 →</span>}
    </div>
  );
}

async function CandidatesTab({ page, fit }: { page: number; fit: FitFilter }) {
  // 이번 주 한도 줄을 먼저 확보한다(없으면 DB 가 $5 로 만든다) — 그래야 아래 결재 목록에 잡혀 [이걸로]가 열린다.
  const wb = await loadWeeklyBudget();
  const [v, est] = await Promise.all([
    loadTopicCandidates({ statuses: ["suggested"], page, fit }),
    loadDevelopEstimate(["explainer", "card", "meme"]),
  ]);
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const d = v.data;
  const estimate: EstimateMap = est.state === "ok" ? normalizeEstimate(est.data) : UNKNOWN_ESTIMATE;
  const budget = d.budgets ? pickBudget(d.budgets, Date.now()) : null;
  const weeks = weekOptions(todayInSeoul());
  const cards = d.candidates.map((c) => {
    const ev = d.evidence?.get(c.id);
    const rec = recommendFormat({ origin: "discovery", question: c.key_question, signals: c.signals, evidenceCount: d.evidence ? (ev?.count ?? 0) : null, evidenceChars: d.evidence ? (ev?.chars ?? 0) : null });
    const pick = pickability(c, Boolean(budget));
    return { c, rec, ev, pick };
  });
  const pickable = cards.filter((x) => x.pick.ok).length;
  return (
    <>
      <WeeklyBudgetCard budget={wb.state === "ok" ? wb.data : null} error={wb.state === "error" ? wb.message : undefined} />
      <div className="dk-toolbar">
        <Header v={d} pickable={pickable} />
        <form method="get" action="/drinks/topics" className="dk-row">
          <input type="hidden" name="tab" value="candidates" />
          <select name="fit" defaultValue={fit} aria-label="형식 적합성">
            {FIT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button className="btn" type="submit">적용</button>
        </form>
      </div>
      {est.state !== "ok" && d.candidates.length > 0 && <p className="muted" style={{ fontSize: 12 }}>형식별 예상 비용을 읽지 못해 모달에 &ldquo;모름&rdquo;으로 보입니다(0원이 아닙니다).</p>}
      <div className="dk-topic-grid">
        {cards.map(({ c, rec, ev, pick }) => (
          <CandidateCard key={c.id} c={c} rec={rec} evidence={ev} evidenceLoaded={d.evidence !== null}
            dupTopics={c.duplicate_topic_ids.map((id) => ({ id, title: d.topics.get(id)?.title ?? "소재" }))}
            pick={pick} weeks={weeks} budget={budget} estimate={estimate} />
        ))}
      </div>
      <Pager v={d} tab="candidates" fit={fit} />
    </>
  );
}

async function HeldTab({ page }: { page: number }) {
  const v = await loadTopicCandidates({ statuses: ["dismissed", "merged"], page });
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const d = v.data;
  const weeks = weekOptions(todayInSeoul());
  return (
    <>
      <Header v={d} pickable={null} />
      <p className="muted" style={{ fontSize: 13 }}>기각·합쳐진 후보. 보류·제외된 <b>소재</b>는 <Link href="/drinks/board?tab=held">옛 선별 화면의 보류·제외 탭</Link>에 있습니다.</p>
      <div className="dk-topic-grid">
        {d.candidates.map((c) => (
          <CandidateCard key={c.id} c={c} rec={{ format: "unknown", reason: "기각·합쳐진 후보는 추천하지 않습니다" }} evidence={undefined} evidenceLoaded={false}
            dupTopics={c.duplicate_topic_ids.map((id) => ({ id, title: d.topics.get(id)?.title ?? "소재" }))}
            pick={{ ok: false, code: "promoted", reason: "다시 열어야 고를 수 있습니다" }} weeks={weeks} budget={null} estimate={UNKNOWN_ESTIMATE} />
        ))}
      </div>
      <Pager v={d} tab="held" fit="" />
    </>
  );
}

async function MineSection() {
  const v = await loadWorkItems("all");
  if (v.state !== "ok") return <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />;
  const items: WorkItem[] = v.data;
  const decisions: Decision[] = items.map((it) => decide(it));
  // rankForHome 은 홈이 쓰지만, 여기서도 막힌 것이 위로 오도록 같은 순서를 쓴다(스누즈 없음).
  const updatedAt = new Map(items.map((i) => [i.unit_id, i.updated_at]));
  const order = new Map(rankForHome(decisions, new Set<string>(), updatedAt).map((d, i) => [d.unitId, i]));
  const sorted = [...items].sort((a, b) => (order.get(a.unit_id) ?? 9e9) - (order.get(b.unit_id) ?? 9e9));
  return (
    <>
      <p style={{ margin: "4px 0" }}>작업 단위 <b>{items.length}</b>개 · 소재 <b>{new Set(items.map((i) => i.topic_id ?? "meme_card")).size}</b>개</p>
      <MineTab items={sorted} decisions={decisions} />
    </>
  );
}
