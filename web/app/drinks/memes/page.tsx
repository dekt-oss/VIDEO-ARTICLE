// 밈 보드 (/drinks/memes) — 인스타에서 지금 도는 형식. 관찰 계정의 뜨는 릴스·오르는 음원·운영자 링크를 카드로 묶는다. 기획 v2 §6.
// ★ 신호일 뿐 사실 근거가 아니다. 음원 자리는 "인스타가 우리 계정에 준 추천 순서" 안의 자리다.
// ★ 관찰 범위·마지막 정상 관측일·최근 7일 정상 관측 수는 어떤 상태에서도 보인다(§6-2). 실패·미적용·수집 전을 0건처럼 보이지 않게 한다.
// ★ [쓰자]는 결정만 기록한다. 돈이 나가는 분석은 이 화면에서 시작되지 않는다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import {
  AddLinkForm, AddWatchAccountForm, CardDecisionButtons, CardFieldForm, WatchAccountAction,
} from "@/components/drinks/MemeBoardControls";
import {
  DECISION_LABEL, EVIDENCE_LABEL, FORMAT_FIELDS, LINK_STATUS_LABEL, PRECISION_LABEL, RISING_AUDIO_LABEL, RUN_STATUS_LABEL, SOURCE_LABEL, STATE_LABEL, STRUCTURE_LABEL,
  boardHealth, compactNum, failureText, groupCards, isoToday, latestRuns, positionLabel, reasonsText, sortAudio, tokenView, noteAfterUse,
  type BoardHealth, type IgAccountRow, type IgAudioRow, type IgCardRow, type IgRunRow, type TokenView,
} from "@/lib/drinks/igTrends";
import { loadIgBoard } from "@/lib/drinks/igTrendsQueries";
import { safeHref } from "@/lib/drinks/trends";

export const dynamic = "force-dynamic";

const ymd = (d: string | null | undefined): string => (d ?? "").slice(0, 10);
const KIND_LABEL: Record<IgAccountRow["kind"], string> = { meme: "밈", drinks: "술", explainer: "설명형", other: "기타" };
const CARD_KIND_LABEL: Record<IgCardRow["kind"], string> = { audio: "원본 소리", challenge: "챌린지", structure_hook: "구조·훅", single_reel: "뜨는 릴스" };

function ScopeLine({ h }: { h: BoardHealth | null }) {
  // 조회가 안 된 경우에도 줄을 없애지 않는다 - 0 이 아니라 "모름"이라고 적는다.
  const scope = h ? `계정 성공 ${h.scope.succeeded} / 목록 ${h.scope.listed}` : "모름";
  const last = h ? h.lastNormalDay ?? "없음" : "모름";
  const k = h ? `${h.normalLast7}일` : "모름";
  return (
    <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: "6px 22px" }}>
      <span>관찰 범위: <b>{scope}</b>{h?.scope.on && <span className="muted"> ({h.scope.on})</span>}</span>
      <span>마지막 정상 관측일: <b>{last}</b></span>
      <span>최근 7일 중 정상 관측: <b>{k}</b></span>
    </div>
  );
}

function Banners({ h, token }: { h: BoardHealth; token: TokenView }) {
  return (
    <>
      {h.frozen && (
        <div className="banner-block" role="alert">
          <b>관측 중단 — 상태 고정</b>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            정상 관측일이 {h.missingStreak}일째 끊겼습니다(마지막 정상 관측일 {h.lastNormalDay ?? "없음"}). 카드 상태 변화와 자동 보관을 멈췄습니다 — 카드가 식은 것이 아니라 못 본 것입니다.
          </p>
        </div>
      )}
      {token.level === "bad" && <div className="banner-block" role="alert"><b>{token.text}</b></div>}
      {token.level === "warn" && <div className="banner-warn" role="status">{token.text}</div>}
      {h.neverRun && (
        <div className="banner-warn" role="status">
          아직 한 번도 수집하지 않았습니다 — 0건이 아니라 수집 전입니다. 워크플로(drinks-trend-board)는 main 에 머지된 뒤 매일 KST 07:30 에 돕니다.
        </div>
      )}
      {!h.neverRun && h.noActiveAccounts && (
        <div className="banner-warn" role="status">
          활성 관찰 계정이 0개입니다 — 성공률을 말할 수 없어 정상 관측일이 생기지 않습니다. 아래 후보에서 체크하세요.
        </div>
      )}
    </>
  );
}

function RunTable({ runs }: { runs: IgRunRow[] }) {
  const latest = latestRuns(runs);
  const rows: ("t1" | "t2" | "t3")[] = ["t1", "t2", "t3"];
  return (
    <div className="table-scroll">
      <table className="grid">
        <thead><tr><th>수집원</th><th>날짜</th><th>상태</th><th>성공/시도</th><th>실패 사유·제외</th></tr></thead>
        <tbody>
          {rows.map((s) => {
            const r = latest[s];
            return (
              <tr key={s}>
                <td>{SOURCE_LABEL[s]}</td>
                <td className="muted">{r?.observed_on.slice(0, 10) ?? "기록 없음"}</td>
                <td><span className={r && (r.status === "failed" || r.status === "not_run") ? "pill reject" : r?.status === "partial" ? "pill dk-warn" : "pill"}>{r ? RUN_STATUS_LABEL[r.status] : "기록 없음"}</span></td>
                <td className="num">{r ? `${r.succeeded}/${r.attempted}` : "-"}</td>
                <td className="muted">
                  {r && reasonsText(r.failure_reasons)}
                  {r?.excluded_no_views ? ` 조회수 없어 판정에서 뺀 릴스 ${r.excluded_no_views}` : ""}
                </td>
              </tr>
            );
          })}
          <tr>
            <td>{SOURCE_LABEL.t4}</td>
            <td className="muted">-</td>
            <td><span className="pill">연결 안 함</span></td>
            <td className="num">-</td>
            <td className="muted">이 화면과 수집에 연결돼 있지 않습니다. 돈이 나가지 않습니다.</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function FormatFields({ c }: { c: IgCardRow }) {
  const filled = FORMAT_FIELDS.filter((f) => c.fields?.[f.key]);
  const empty = FORMAT_FIELDS.filter((f) => !c.fields?.[f.key] && !f.videoOnly).map((f) => f.label);
  const emptyVideo = FORMAT_FIELDS.filter((f) => !c.fields?.[f.key] && f.videoOnly).map((f) => f.label);
  return (
    <div className="dk-kv" style={{ margin: "6px 0" }}>
      {filled.map((f) => {
        const v = c.fields[f.key];
        const shown = f.key === "structure" ? STRUCTURE_LABEL[v.value] ?? v.value : v.value;
        return <span key={f.key} style={{ marginRight: 10 }}>{f.label}: <b>{shown}</b> <span className="muted">({EVIDENCE_LABEL[v.evidence] ?? v.evidence}, 확신도 {v.confidence === "high" ? "높음" : "낮음"})</span></span>;
      })}
      {empty.length > 0 && <div className="muted">비어 있음: {empty.join(" · ")}</div>}
      {emptyVideo.length > 0 && <div className="muted">영상을 봐야 채우는 칸(비어 있음): {emptyVideo.join(" · ")}</div>}
    </div>
  );
}

function MemeCard({ c, today }: { c: IgCardRow; today: string }) {
  return (
    <div className={c.decision === "use" ? "card picked" : c.decision === "pass" ? "card rejected" : "card"}>
      <div className="dk-row">
        <b>{c.name}</b>
        <span className={c.state === "rising" ? "pill on" : "pill"}>{STATE_LABEL[c.state]}</span>
        <span className="pill">{CARD_KIND_LABEL[c.kind]}</span>
        <span className={c.precision === "precise" ? "pill on" : "pill"}>{PRECISION_LABEL[c.precision]}</span>
        {c.decision && <span className="pill pick">{DECISION_LABEL[c.decision]}</span>}
      </div>
      <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>
        처음 묶인 날 {ymd(c.first_seen_on)} · 예시 {c.examples_count} · 관찰 계정 {c.accounts_count}
        {c.max_multiple !== null && ` · 평소의 ${c.max_multiple}배`}
        {c.audio_position !== null && c.audio_position_on && ` · ${positionLabel(c.audio_position, c.audio_position_on, today)}`}
        {c.same_audio_cards > 0 && ` · 같은 음원을 쓰는 다른 카드 ${c.same_audio_cards}장`}
        {` · 새 예시 없는 정상 관측일 ${c.quiet_normal_days}일`}
      </p>
      {c.decision === "use" && <p className={c.state === "cooled" ? "dk-warn" : "muted"} style={{ fontSize: 13, margin: "4px 0" }}>{noteAfterUse(c)}</p>}
      <FormatFields c={c} />
      {c.examples.length > 0 && (
        <div style={{ fontSize: 13 }}>
          {c.examples.map((e) => {
            const href = safeHref(e.permalink);
            const label = `@${e.username}`;
            return (
              <div key={e.media_id}>
                {href ? <a href={href} target="_blank" rel="noreferrer noopener">{label}</a> : label}
                <span className="muted"> · 조회 {compactNum(e.view_count)}{e.view_multiple !== null && ` · 평소의 ${e.view_multiple}배`}{e.origin === "operator_link" && " · 운영자 링크"}{e.hook && ` · ${e.hook}`}</span>
              </div>
            );
          })}
        </div>
      )}
      <CardDecisionButtons id={c.id} decision={c.decision} />
      <CardFieldForm card={c} />
    </div>
  );
}

function CardList({ rows, today, empty }: { rows: IgCardRow[]; today: string; empty?: string }) {
  if (rows.length === 0) return empty ? <p className="muted">{empty}</p> : null;
  return <>{rows.map((c) => <MemeCard key={c.id} c={c} today={today} />)}</>;
}

function AudioLine({ a, today }: { a: IgAudioRow; today: string }) {
  const href = safeHref(a.preview_url);
  return (
    <div className="list-row">
      <span>
        <span className="pill">{a.audio_type === "music" ? "노래" : "원본 소리"}</span>{" "}
        {a.rising_reason && <span className="pill on">{RISING_AUDIO_LABEL[a.rising_reason]}</span>}{" "}
        <b>{a.title || "(제목 없음)"}</b>
        <span className="muted"> · {a.display_artist ?? (a.ig_username ? `@${a.ig_username}` : "만든 이 미상")} · {positionLabel(a.list_position, a.observed_on, today)}</span>
        {href && <> · <a href={href} target="_blank" rel="noreferrer noopener">미리듣기</a></>}
      </span>
    </div>
  );
}

function AudioSection({ rows, today }: { rows: IgAudioRow[]; today: string }) {
  if (rows.length === 0) return <p className="muted">받아 둔 음원 목록이 없습니다(수집 전이거나, T1 이 실패한 날뿐입니다 — 위 표를 보세요).</p>;
  const sorted = sortAudio(rows);
  const rising = sorted.filter((a) => a.rising_reason);
  const rest = sorted.filter((a) => !a.rising_reason);
  return (
    <>
      {rising.length === 0 && <p className="muted">오늘 오르는 음원으로 판정된 것은 없습니다(첫 관측일에는 판정하지 않습니다).</p>}
      {rising.map((a) => <AudioLine key={a.audio_id} a={a} today={today} />)}
      {rest.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="muted">나머지 음원 {rest.length}개</summary>
          {rest.map((a) => <AudioLine key={a.audio_id} a={a} today={today} />)}
        </details>
      )}
    </>
  );
}

function AccountRow({ a }: { a: IgAccountRow }) {
  return (
    <div className="list-row">
      <span>
        <a href={`https://www.instagram.com/${encodeURIComponent(a.username)}/`} target="_blank" rel="noreferrer noopener">@{a.username}</a>{" "}
        <span className={a.status === "active" ? "pill on" : "pill"}>{a.status === "active" ? "관찰 중" : a.status === "paused" ? "뺌" : "후보"}</span>{" "}
        <span className="pill">{KIND_LABEL[a.kind]}</span>
        <span className="muted">
          {a.first_observed_on && ` · 첫 관측 ${ymd(a.first_observed_on)}`}
          {a.last_ok_on && ` · 마지막 성공 ${ymd(a.last_ok_on)}`}
          {a.followers_count !== null && ` · 팔로워 ${compactNum(a.followers_count)}`}
          {a.note && ` · ${a.note}`}
        </span>
        {a.last_error_code && <span className="dk-bad"> · {ymd(a.last_error_on)} 실패: {failureText(a.last_error_code)}</span>}
      </span>
      <WatchAccountAction username={a.username} status={a.status} />
    </div>
  );
}

export default async function DrinksMemesPage() {
  const v = await loadIgBoard();
  const nowMs = Date.now();
  const today = isoToday(nowMs);
  const header = (
    <div className="header">
      <h1>🍶 밈 보드</h1>
      <span className="muted">인스타에서 지금 도는 형식 — 사실 근거가 아닙니다 · <Link href="/drinks/trends">커뮤니티 동향</Link> · <Link href="/drinks/discover">소재 발견함</Link></span>
    </div>
  );
  if (v.state !== "ok") {
    return (
      <main className="container">
        {header}
        <ScopeLine h={null} />
        {v.state === "missing" ? (
          <div className="banner-block" role="alert">
            <b>0063 이 운영 DB 에 아직 없습니다.</b>
            <p className="muted" style={{ margin: "6px 0 0" }}>
              트렌드 보드 표(drink_ig_*)가 없어 이 화면을 채울 수 없습니다. 카드가 0장인 것이 아니라 적용 전입니다 — 운영자가 승인해 0063_drinks_ig_trend_board.sql 을 적용하면 보입니다.
            </p>
          </div>
        ) : (
          <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />
        )}
      </main>
    );
  }
  const { runs, token, accounts, cards, audio, links } = v.data;
  const active = accounts.filter((a) => a.status === "active").length;
  const health = boardHealth(runs, today, active);
  const tokenNow = tokenView(token, nowMs);
  const groups = groupCards(cards);
  const pendingCount = accounts.filter((a) => a.status !== "active").length;
  return (
    <main className="container">
      {header}
      <ScopeLine h={health} />
      <Banners h={health} token={tokenNow} />
      <section className="section">
        <h3>수집 상태</h3>
        <RunTable runs={runs} />
        <p className="muted" style={{ fontSize: 13 }}>정상 관측일은 T1 이 정상이고 T2 계정 성공률이 80% 이상인 날입니다. 카드 수명은 그런 날만 셉니다. {tokenNow.level === "ok" && tokenNow.text}</p>
      </section>
      <section className="section">
        <h3>결정할 카드 ({groups.undecided.length})</h3>
        <p className="muted" style={{ fontSize: 13 }}>
          [쓰자]는 결정만 기록합니다. 형식 분석이나 구매는 시작되지 않습니다. 표지·캡션만으로는 영상 칸을 채우지 않으며, 그 칸이 비면 참고 카드로 남습니다.
        </p>
        <CardList rows={groups.undecided} today={today} empty={health.neverRun ? "수집 전이라 카드가 없습니다." : "지금 결정할 카드가 없습니다. 첫 관측일의 릴스와 음원은 신호에 넣지 않으므로 처음 며칠은 비어 있는 것이 정상입니다."} />
      </section>
      {groups.use.length > 0 && <section className="section"><h3>쓰자 ({groups.use.length})</h3><CardList rows={groups.use} today={today} /></section>}
      {groups.later.length > 0 && <section className="section"><h3>나중에 ({groups.later.length})</h3><CardList rows={groups.later} today={today} /></section>}
      {(groups.pass.length > 0 || groups.archived.length > 0) && (
        <section className="section">
          <details>
            <summary className="muted">넘긴 카드 {groups.pass.length}장 · 식어서 보관된 카드 {groups.archived.length}장</summary>
            <CardList rows={groups.pass} today={today} />
            <CardList rows={groups.archived} today={today} />
          </details>
        </section>
      )}
      <section className="section">
        <h3>오르는 음원</h3>
        <p className="muted" style={{ fontSize: 13 }}>순서는 인스타가 우리 계정에 준 추천 순서입니다. 앱에서 보이는 것과 다를 수 있습니다. 목록에 처음 들어왔거나 3일 연속 남은 음원을 앞에 둡니다 — 자리가 바뀐 것만으로는 판정하지 않습니다.</p>
        <AudioSection rows={audio} today={today} />
      </section>
      <section className="section">
        <h3>운영자 링크</h3>
        <AddLinkForm />
        {links.slice(0, 20).map((l) => {
          const href = safeHref(l.canonical_url);
          return (
            <div key={l.id} className="list-row">
              <span>
                {href ? <a href={href} target="_blank" rel="noreferrer noopener">{l.shortcode}</a> : l.shortcode}
                <span className="muted"> · @{l.username} · {LINK_STATUS_LABEL[l.status]}{l.status === "pending" && l.error_code ? `(지난번 실패: ${failureText(l.error_code)})` : ""}{l.note && ` · ${l.note}`}</span>
              </span>
            </div>
          );
        })}
        {links.length > 20 && <p className="muted">최근 20건만 보여 줍니다(전체 {links.length}건).</p>}
      </section>
      <section className="section">
        <h3>관찰 계정 (관찰 중 {active} · 체크 대기·뺌 {pendingCount})</h3>
        <p className="muted" style={{ fontSize: 13 }}>
          후보는 문서에 실측 기록이 있는 계정만 넣어 뒀습니다. 체크해야 관찰이 시작되고, 체크한 날 처음 본 릴스는 신호에 넣지 않습니다. 실패하는 계정이 많으면 성공률이 80% 아래로 내려가 정상 관측일이 끊기니, 계속 실패하는 계정은 빼세요.
        </p>
        <AddWatchAccountForm />
        {accounts.length === 0 && <p className="muted">등록된 계정이 없습니다.</p>}
        {[...accounts].sort((a, b) => Number(b.status === "active") - Number(a.status === "active") || a.username.localeCompare(b.username)).map((a) => <AccountRow key={a.username} a={a} />)}
      </section>
    </main>
  );
}
