// [밈 카드] — 밈 보드의 상태 줄(관찰 범위·마지막 정상 관측일·최근 7일 정상 관측)과 결정할 카드. 카드마다 [쓰자 ▾].
//   밈 보드(/drinks/memes)의 상태 블록과 같은 규칙(boardHealth·tokenView)을 쓴다. 수집 전·조회 실패·0063 미적용을 0장과 다르게 말한다.
//   카드를 소재에 잇지 않는다(G5). 음원·운영자 링크·제작안은 밈 보드에 그대로 있다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import { loadApifyBoard } from "@/lib/drinks/apifyQueries";
import {
  DECISION_LABEL, PRECISION_LABEL, STATE_LABEL, STRUCTURE_LABEL, boardHealth, compactNum, groupCards, isoToday, noteAfterUse, tokenView,
  type BoardHealth, type IgCardRow,
} from "@/lib/drinks/igTrends";
import { loadIgBoard } from "@/lib/drinks/igTrendsQueries";
import MemeUseMenu from "./MemeUseMenu";

const ymd = (d: string | null | undefined): string => (d ?? "").slice(0, 10);
const CARD_KIND_LABEL: Record<IgCardRow["kind"], string> = { audio: "원본 소리", challenge: "챌린지", structure_hook: "구조·훅", single_reel: "뜨는 릴스" };

function ScopeLine({ h }: { h: BoardHealth | null }) {
  // 조회가 안 된 경우에도 줄을 없애지 않는다 — 0 이 아니라 "모름"이라고 적는다.
  const scope = h ? `계정 성공 ${h.scope.succeeded} / 목록 ${h.scope.listed}` : "모름";
  return (
    <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: "6px 22px" }}>
      <span>관찰 범위: <b>{scope}</b>{h?.scope.on && <span className="muted"> ({h.scope.on})</span>}</span>
      <span>마지막 정상 관측일: <b>{h ? h.lastNormalDay ?? "없음" : "모름"}</b></span>
      <span>최근 7일 중 정상 관측: <b>{h ? `${h.normalLast7}일` : "모름"}</b></span>
      <Link href="/drinks/memes">밈 보드 전체 →</Link>
    </div>
  );
}

function Card({ c, today, month, apifyReady }: { c: IgCardRow; today: string; month: Parameters<typeof MemeUseMenu>[0]["month"]; apifyReady: boolean }) {
  const structure = c.fields?.structure?.value;
  return (
    <article className={c.decision === "use" ? "card picked" : "card"}>
      <div className="dk-row">
        <b>{c.name}</b>
        <span className={c.state === "rising" ? "pill on" : "pill"}>{STATE_LABEL[c.state]}</span>
        <span className="pill">{CARD_KIND_LABEL[c.kind]}</span>
        <span className={c.precision === "precise" ? "pill on" : "pill"}>{PRECISION_LABEL[c.precision]}</span>
        {c.decision && <span className="pill pick">{DECISION_LABEL[c.decision]}</span>}
        {structure && <span className="pill">{STRUCTURE_LABEL[structure] ?? structure}</span>}
      </div>
      <p className="dk-kv" style={{ margin: "4px 0" }}>
        처음 묶인 날 {ymd(c.first_seen_on)} · 예시 {c.examples_count} · 관찰 계정 {c.accounts_count}
        {c.max_multiple !== null && ` · 평소의 ${c.max_multiple}배`}
        {c.examples[0] && ` · 예시 조회 ${compactNum(c.examples[0].view_count)}`}
        {` · 새 예시 없는 정상 관측일 ${c.quiet_normal_days}일`}
      </p>
      {c.decision === "use" && <p className={c.state === "cooled" ? "dk-warn" : "muted"} style={{ fontSize: 13, margin: "4px 0" }}>{noteAfterUse(c)}</p>}
      <MemeUseMenu card={c} month={month} apifyReady={apifyReady} />
    </article>
  );
}

export default async function MemeCardsTab() {
  const [v, apify] = await Promise.all([loadIgBoard(), loadApifyBoard()]);
  const nowMs = Date.now();
  const today = isoToday(nowMs);
  if (v.state !== "ok") {
    return (
      <>
        <ScopeLine h={null} />
        {v.state === "missing"
          ? <div className="banner-block" role="alert"><b>0063 이 운영 DB 에 아직 없습니다.</b><p className="muted" style={{ margin: "6px 0 0" }}>카드가 0장인 것이 아니라 적용 전입니다.</p></div>
          : <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />}
      </>
    );
  }
  const { runs, token, accounts, cards } = v.data;
  const health = boardHealth(runs, today, accounts.filter((a) => a.status === "active").length);
  const tk = tokenView(token, nowMs);
  const groups = groupCards(cards);
  const month = apify.state === "ok" ? apify.data.month : null;
  const apifyReady = apify.state === "ok";
  return (
    <>
      <ScopeLine h={health} />
      {health.frozen && <div className="banner-block" role="alert"><b>관측 중단 — 상태 고정</b><p className="muted" style={{ margin: "6px 0 0" }}>정상 관측일이 {health.missingStreak}일째 끊겼습니다. 카드가 식은 것이 아니라 못 본 것입니다.</p></div>}
      {tk.level === "bad" && <div className="banner-block" role="alert"><b>{tk.text}</b></div>}
      {tk.level === "warn" && <div className="banner-warn" role="status">{tk.text}</div>}
      {health.neverRun && <div className="banner-warn" role="status">아직 한 번도 수집하지 않았습니다 — 0장이 아니라 수집 전입니다.</div>}
      {apify.state === "missing" && <p className="muted">0070 미적용 — [정밀화 포함]은 쓸 수 없고 [정밀화 없이]만 됩니다(돈이 나가지 않습니다).</p>}
      {apify.state === "failed" && <p className="banner-warn">정밀화 요청 표를 읽지 못했습니다: {apify.error} — [정밀화 없이]만 됩니다.</p>}
      <section className="section">
        <h3>결정할 카드 ({groups.undecided.length})</h3>
        {groups.undecided.length === 0 && (
          <p className="muted">{health.neverRun ? "수집 전이라 카드가 없습니다." : "지금 결정할 카드가 없습니다(정상 0장). 첫 관측일의 릴스는 신호에 넣지 않습니다."}</p>
        )}
        {groups.undecided.map((c) => <Card key={c.id} c={c} today={today} month={month} apifyReady={apifyReady} />)}
      </section>
      {groups.use.length > 0 && (
        <section className="section">
          <h3>쓰자 ({groups.use.length})</h3>
          <p className="muted" style={{ fontSize: 13 }}>제작안은 <Link href="/drinks/memes">밈 보드의 [밈 제작]</Link> 칸에서 씁니다. 카드는 소재에 잇지 않습니다.</p>
          {groups.use.map((c) => <Card key={c.id} c={c} today={today} month={month} apifyReady={apifyReady} />)}
        </section>
      )}
      {groups.later.length > 0 && <section className="section"><h3>나중에 ({groups.later.length})</h3>{groups.later.map((c) => <Card key={c.id} c={c} today={today} month={month} apifyReady={apifyReady} />)}</section>}
    </>
  );
}
