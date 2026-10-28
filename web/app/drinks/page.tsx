// 주류 공장 선별 (/drinks) — 수동 등록, 후보 목록·필터, 조사·편성 상태와 다음 행동, 편성함.
// 명세 docs/주류공장_구조명세_v1_2026-10-21.md §9.1. B단계부터 승인한 수집원만 수집한다 — 수집 문서는 /drinks/collected 에서
// 사람이 소재 후보로 올린다(자동 후보·자동 편성 없음). 상단 수집 상태는 최근 24시간 실행 기록에서 센다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import RegisterForm from "@/components/drinks/RegisterForm";
import { todayInSeoul } from "@/lib/date";
import {
  CATEGORIES, CATEGORY_LABEL, FORMAT_LABEL, LANE_LABEL, SELECT_THRESHOLD, TOPIC_STATUS_LABEL, VERSION_STATUS_LABEL,
  deriveTopic, fitOk, originSummary, type Format, type TopicDerived,
} from "@/lib/drinks/model";
import { loadBoard, TOPIC_LIST_LIMIT, type DrinksBoard } from "@/lib/drinks/queries";
import { loadRunHealth } from "@/lib/drinks/collectQueries";
import type { TopicRow } from "@/lib/drinks/types";

export const dynamic = "force-dynamic";

const TABS = {
  all: { label: "전체 후보", statuses: ["inbox", "triaged", "researching", "ready", "selected"] },
  researching: { label: "조사 중", statuses: ["researching"] },
  ready: { label: "편성 가능", statuses: ["ready"] },
  selected: { label: "편성함", statuses: ["selected"] },
  held: { label: "보류·제외", statuses: ["on_hold", "rejected", "duplicate"] },
} as const;
type TabKey = keyof typeof TABS;

/** 편성함 목표(명세 §6.4: 주 3개 × 2주분). 운영 가설이며 확보를 보장하지 않는다. */
const READY_TARGET = 6;

type SP = { tab?: string; cat?: string; lane?: string; evidence?: string; fit?: string; from?: string; pub_from?: string; limit?: string };

export default async function DrinksHomePage(props: { searchParams: Promise<SP> }) {
  const sp = await props.searchParams;
  const tab: TabKey = sp.tab && sp.tab in TABS ? (sp.tab as TabKey) : "all";
  const limit = Math.min(5000, Math.max(TOPIC_LIST_LIMIT, Number(sp.limit) || TOPIC_LIST_LIMIT));
  const [board, health] = await Promise.all([loadBoard(limit), loadRunHealth()]);

  return (
    <main className="container">
      <div className="header">
        <h1>🍶 주류 공장 — 선별</h1>
        <span className="muted">사케·전통주·위스키</span>
      </div>
      <CollectHealth health={health} />
      <RegisterForm />
      {board.state !== "ok" ? (
        <LoadProblem state={board.state} error={board.state === "failed" ? board.error : undefined} />
      ) : (
        <Board board={board.data} truncated={Boolean(board.truncated)} tab={tab} sp={sp} limit={limit} health={health} />
      )}
    </main>
  );
}

type Health = Awaited<ReturnType<typeof loadRunHealth>>;

/** 수집 상태 한 줄. 실패·부분 성공·중단은 정상 0건과 다른 색으로, 조회 실패는 "0건"이 아니라 실패로. */
function CollectHealth({ health }: { health: Health }) {
  if (health.state !== "ok") {
    return (
      <p className="banner-warn" style={{ marginTop: 12 }}>
        수집 상태를 읽지 못했습니다{health.state === "failed" ? ` — ${health.error}` : ""} (0건이 아니라 조회 실패).
      </p>
    );
  }
  const h = health.data;
  if (h.active === 0) {
    return (
      <p className="banner-info" style={{ marginTop: 12 }}>
        <b>활성 수집원 없음.</b> 소재는 직접 등록한 것만 들어옵니다. <Link href="/drinks/sources">수집원</Link>에서 검증·활성화하면
        승인한 출처만 하루 한 번 수집합니다(URL 을 직접 등록해도 서버가 열지 않습니다).
      </p>
    );
  }
  const bad = h.failed + h.partial + h.aborted + h.stuck;
  return (
    <p className={bad > 0 ? "banner-warn" : "banner-info"} style={{ marginTop: 12 }}>
      활성 수집원 <b>{h.active}</b> · 최근 24시간 실행: 성공 {h.succeeded} · 정상 0건 {h.empty} · 부분 성공 {h.partial} · 실패 {h.failed} ·
      중단 {h.aborted}{h.stuck > 0 && <> · <b>응답 끊긴 실행 {h.stuck}</b></>} — <Link href={bad > 0 ? "/drinks/runs?status=failed" : "/drinks/runs"}>실행 기록</Link> ·{" "}
      <Link href="/drinks/collected?linked=no">아직 소재 없는 수집 문서</Link>
    </p>
  );
}

function Board({ board, truncated, tab, sp, limit, health }: {
  board: DrinksBoard; truncated: boolean; tab: TabKey; sp: SP; limit: number; health: Health;
}) {
  const derived = new Map<string, TopicDerived>(
    board.topics.map((t) => [t.id, deriveTopic(t, board.reviews, board.deliverables, board.plans)])
  );
  const dupKeys = new Map<string, number>();
  for (const t of board.topics) if (t.status !== "duplicate") dupKeys.set(t.dedupe_key, (dupKeys.get(t.dedupe_key) ?? 0) + 1);

  const researching = board.topics.filter((t) => t.status === "researching");
  const blocked = researching.filter((t) => {
    const d = derived.get(t.id)!;
    return !d.review || Boolean(d.review.revoked_at) || (d.review.readiness?.blockers?.length ?? 0) > 0
      || d.missingPointers.length > 0;
  });
  const readyCount = board.topics.filter((t) => t.status === "ready" && derived.get(t.id)!.approvalValid).length;
  // 승인 기록은 있지만 지금 쓸 수 없는 근거(사용 조건·유효 기한) — 편성 가능·편성함에 숨지 않게 따로 센다.
  const unusable = board.topics.filter((t) => {
    const d = derived.get(t.id)!;
    return (t.status === "ready" && !d.approvalValid) || (t.status === "selected" && !d.selectedValid)
      || (t.status === "selected" && (t.selected_formats ?? []).some((f) => d.plans[f] && !d.plans[f]!.blocked_at && d.planEvidenceValid[f] === false));
  });

  const statuses = TABS[tab].statuses as readonly string[];
  const pubFrom = sp.pub_from ?? "";
  const rows = board.topics.filter((t) => {
    if (!statuses.includes(t.status)) return false;
    if (sp.cat && !t.categories.includes(sp.cat as TopicRow["categories"][number])) return false;
    if (sp.lane && t.lane !== sp.lane) return false;
    const d = derived.get(t.id)!;
    if (sp.evidence === "approved" && !d.approvalValid) return false;
    if (sp.evidence === "blocked" && !(d.review && (d.review.readiness?.blockers?.length ?? 0) > 0)) return false;
    if (sp.evidence === "none" && d.review) return false;
    if (sp.fit && !fitOk(d.fitScores, sp.fit as Format)) return false;
    if (sp.from && t.created_at.slice(0, 10) < sp.from) return false;
    if (pubFrom && !(board.sources.get(t.id) ?? []).some((s) => s.published_at && s.published_at >= pubFrom)) return false;
    return true;
  });

  return (
    <>
      <section className="section">
        <div className="dk-row">
          <span className={blocked.length > 0 ? "pill dk-warn" : "pill"}>조사 막힘 {blocked.length}</span>
          <span className={unusable.length > 0 ? "pill dk-bad" : "pill"}>근거 지금 사용 불가 {unusable.length}</span>
          <span className={readyCount < READY_TARGET ? "pill dk-warn" : "pill"}>
            편성 가능 {readyCount} / 목표 {READY_TARGET}
          </span>
          {health.state === "ok" && (
            <span className={health.data.failed + health.data.partial + health.data.aborted + health.data.stuck > 0 ? "pill dk-warn" : "pill"}>
              수집 실패·부분·중단(24시간) {health.data.failed + health.data.partial + health.data.aborted + health.data.stuck}
            </span>
          )}
        </div>
        {readyCount < READY_TARGET && (
          <p className="muted">편성 가능 소재가 목표보다 적습니다. 상시 지식 소재를 조사해 보충하세요(근거 기준을 낮추지 않습니다).</p>
        )}
      </section>

      <nav className="dk-tabs" aria-label="후보 탭">
        {(Object.keys(TABS) as TabKey[]).map((k) => (
          <Link key={k} href={`/drinks?tab=${k}`} data-active={k === tab}>
            {TABS[k].label} ({board.topics.filter((t) => (TABS[k].statuses as readonly string[]).includes(t.status)).length})
          </Link>
        ))}
      </nav>

      <form className="dk-row" method="get" action="/drinks" style={{ marginBottom: 12 }}>
        <input type="hidden" name="tab" value={tab} />
        <select name="cat" defaultValue={sp.cat ?? ""} aria-label="주종">
          <option value="">주종 전체</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
        </select>
        <select name="lane" defaultValue={sp.lane ?? ""} aria-label="공급 경로">
          <option value="">공급 경로 전체</option>
          {Object.entries(LANE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <select name="evidence" defaultValue={sp.evidence ?? ""} aria-label="근거 준비">
          <option value="">근거 준비 전체</option>
          <option value="none">근거 버전 없음</option>
          <option value="blocked">필수 조건 미달</option>
          <option value="approved">근거·기획 승인</option>
        </select>
        <select name="fit" defaultValue={sp.fit ?? ""} aria-label="형식 적합성">
          <option value="">형식 적합성 전체</option>
          <option value="video">영상 적합</option>
          <option value="carousel">카드뉴스 적합</option>
        </select>
        <label className="muted">등록일부터 <input type="date" name="from" defaultValue={sp.from ?? ""} /></label>
        <label className="muted">자료 발행일부터 <input type="date" name="pub_from" defaultValue={pubFrom} /></label>
        <button className="btn" type="submit">적용</button>
        <Link className="btn" href={`/drinks?tab=${tab}`}>초기화</Link>
      </form>

      {truncated && (
        <p className="banner-warn">
          전체 {board.totalTopics}건 중 최근 {board.topics.length}건만 불러왔습니다 — 더 오래된 소재는 이 목록과 위 집계에 없습니다.{" "}
          {limit < 5000 && <Link href={`/drinks?tab=${tab}&limit=${limit + 1000}`}>더 불러오기 →</Link>}
        </p>
      )}

      {tab === "selected" ? (
        <WeekBox rows={rows} derived={derived} />
      ) : rows.length === 0 ? (
        <p className="muted">
          {board.topics.length === 0 ? "등록된 소재가 없습니다(정상 0건). 위에서 질문을 직접 등록하세요." : "조건에 맞는 소재가 없습니다."}
        </p>
      ) : (
        rows.map((t) => (
          <TopicCard key={t.id} t={t} d={derived.get(t.id)!} board={board} dup={(dupKeys.get(t.dedupe_key) ?? 0) > 1} />
        ))
      )}
    </>
  );
}

function TopicCard({ t, d, board, dup }: { t: TopicRow; d: TopicDerived; board: DrinksBoard; dup: boolean }) {
  const srcs = board.sources.get(t.id) ?? [];
  const evid = srcs.filter((s) => s.role === "evidence");
  const og = originSummary(evid);
  const metaOnly = evid.filter((s) => s.depth === "metadata_only").length;
  const blockers = d.review?.readiness?.blockers ?? [];
  const validUntil = (d.review?.evidence_pack?.claims ?? [])
    .map((c) => c.valid_until).filter(Boolean).sort()[0];
  return (
    <article className="card">
      <div className="dk-row">
        <span className="status-pill">{TOPIC_STATUS_LABEL[t.status]}</span>
        {t.categories.map((c) => <span key={c} className="pill">{CATEGORY_LABEL[c]}</span>)}
        <span className="pill">{LANE_LABEL[t.lane]}</span>
        {dup && <span className="pill dk-warn">중복 의심</span>}
      </div>
      <h2 style={{ marginTop: 8 }}>
        <Link href={`/drinks/review/${t.id}`}>{t.title}</Link>
      </h2>
      <p className="oneliner">Q. {t.question}</p>
      {t.reader_value && <p className="muted">효용: {t.reader_value}</p>}
      <p className="dk-kv">
        출처 <b>{srcs.length}</b> (근거 {evid.length} · 확인된 원출처 {og.confirmedGroups}묶음 · 묶음 미확인 {og.unconfirmed}
        {metaOnly > 0 ? ` · URL만 ${metaOnly}` : ""}) · 같은 질문{" "}
        <b>{t.reader_signal_count}</b>건
      </p>
      <p className="dk-kv">
        경량 점수 <b>{d.provisionalScore ?? "—"}</b> (임시) · 편성 평가 <b>{d.finalScore ?? "—"}</b>
        {d.finalScore !== null && d.finalScore < SELECT_THRESHOLD && " (기준 미만)"} · 영상{" "}
        <b className={fitOk(d.fitScores, "video") ? "dk-ok" : "dk-bad"}>{d.fitScores?.fit_video ?? "—"}</b> · 카드{" "}
        <b className={fitOk(d.fitScores, "carousel") ? "dk-ok" : "dk-bad"}>{d.fitScores?.fit_carousel ?? "—"}</b>
        {validUntil && <> · 유효 기한 <b>{validUntil}</b></>}
      </p>
      {d.review && (
        <p className="dk-kv">
          근거·기획 버전 {d.review.revision_no} · {d.review.revoked_at ? "승인 철회됨"
            : d.review.status === "approved" && d.review.currently_valid === false ? "승인 기록 있음 · 지금 사용 불가"
            : VERSION_STATUS_LABEL[d.review.status]}
          {blockers.length > 0 && <span className="dk-bad"> · 필수 조건 미달 {blockers.length}건</span>}
        </p>
      )}
      <div className="actions">
        <Link className="btn pick" href={`/drinks/review/${t.id}?tab=${d.action.tab}`}>
          {d.action.label}
        </Link>
        <span className="muted" style={{ alignSelf: "center" }}>{d.action.hint}</span>
      </div>
    </article>
  );
}

function WeekBox({ rows, derived }: { rows: TopicRow[]; derived: Map<string, TopicDerived> }) {
  if (rows.length === 0) return <p className="muted">편성된 소재가 없습니다.</p>;
  const weeks = new Map<string, TopicRow[]>();
  for (const t of rows) {
    const k = t.editorial_week ?? "주차 없음";
    weeks.set(k, [...(weeks.get(k) ?? []), t]);
  }
  const today = todayInSeoul();
  return (
    <>
      {[...weeks.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([week, list]) => (
        <section key={week} className="render-group">
          <h3 className="group-header">
            {week} 주 {week < today ? "(지난 주차)" : ""} — 소재 {list.length}개
          </h3>
          {list.map((t) => {
            const d = derived.get(t.id)!;
            return (
              <div key={t.id} className="list-row">
                <Link href={`/drinks/review/${t.id}`}>{t.title}</Link>
                <span className="list-row-meta">
                  {(t.selected_formats ?? []).map((f) => {
                    const p = d.plans[f];
                    const label = !d.selectedValid || (p && !p.blocked_at && d.planEvidenceValid[f] === false) ? "근거 사용 불가"
                      : !p ? "제작안 없음" : p.blocked_at ? "차단됨" : VERSION_STATUS_LABEL[p.plan_status];
                    return <span key={f} className="pill">{FORMAT_LABEL[f]}: {label}</span>;
                  })}
                </span>
              </div>
            );
          })}
        </section>
      ))}
      <p className="muted">형식별 제작안 승인은 파일 제작·발행이 아닙니다. 파일은 제작 화면에서 렌더·검수하고, 게시는 발행 화면에서 따로 승인합니다.</p>
    </>
  );
}
