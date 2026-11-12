// 오늘 할 일 화면의 몸통(표시만) — app/drinks/page.tsx 가 데이터를 읽고 집계해 넘긴다(2026-11-06 목업 개편 때 분리).
//   모양은 승인 목업 docs/mockups/drinks/preview-home-*.png: [지금 할 일 하나] 큰 카드 · 타일 3개 · 이번 주 진행표 | 막힘 + 수집 상태.
//   집계 규칙은 lib/drinks/home.ts(순수)이고 여기서는 숫자를 만들지 않는다 — 조회 실패는 "모름"으로.
import Link from "next/link";
import type { ReactNode } from "react";

import NextActionCard from "@/components/drinks/home/NextActionCard";
import type { loadRunHealth } from "@/lib/drinks/collectQueries";
import type { Blocker, HomeCounts, HomeState, WeeklyRow } from "@/lib/drinks/home";
import { FORMAT_LABEL, type Decision, type WorkItem } from "@/lib/drinks/work/types";
import { mondayOf, todayInSeoul } from "@/lib/date";


export default function DrinksHomeView({ header, state, items, decisions, candTotal, todayCands, counts, weekly, blockers, health }: {
  header: ReactNode; state: HomeState; items: WorkItem[]; decisions: Decision[]; candTotal: number | null;
  /** 오늘(KST) 새로 수집한 질문. null = 조회 실패 */
  todayCands: { count: number; top: { id: string; question: string }[] } | null;
  counts: HomeCounts; weekly: WeeklyRow[]; blockers: Blocker[]; health: Health;
}) {
  const today = todayInSeoul();
  return (
    <main className="container">
      {header}
      {state === "no_candidates_no_work" && (
        <section className="next-action done">
          <div className="next-action-body">
            <div className="next-action-kicker">시작</div>
            <div className="next-action-headline">후보도 소재도 아직 없습니다.</div>
            <p className="muted" style={{ margin: "4px 0 0" }}>발견 수집이 돌면 후보가 쌓이고, 질문을 직접 등록할 수도 있습니다.</p>
            <div className="next-action-cta dk-hero-cta"><Link className="btn pick" href="/drinks/studio">소재 고르기 →</Link></div>
          </div>
          <div className="next-action-art" aria-hidden>01<small>첫 소재 고르기</small></div>
        </section>
      )}
      {state === "no_work" && (
        <section className="next-action done">
          <div className="next-action-body">
            <div className="next-action-kicker">시작</div>
            <div className="next-action-headline">고른 소재가 없습니다 — 수집한 질문 {candTotal ?? "?"}개가 있습니다.</div>
            <p className="muted" style={{ margin: "4px 0 0" }}>콘텐츠 스튜디오에서 [이 소재로 초안 만들기]를 누르면 첫 결정이 여기에 올라옵니다.</p>
            <div className="next-action-cta dk-hero-cta"><Link className="btn pick" href="/drinks/studio">소재 고르기 →</Link></div>
          </div>
          <div className="next-action-art" aria-hidden>01<small>첫 소재 고르기</small></div>
        </section>
      )}
      {(state === "work" || state === "all_done") && <NextActionCard items={items} decisions={decisions} />}

      <div className="summary-strip">
        <Link className={`summary-tile${candTotal ? " has-work" : ""}`} href="/drinks/studio">
          <div className="k">수집한 질문</div>
          <div className="n">{candTotal ?? "모름"}</div>
          <div className="s">{candTotal === null ? "조회 실패" : `오늘 새로 ${todayCands?.count ?? "?"}개 · 만들 수 있는 것만 스튜디오에 보여요`}</div>
        </Link>
        <Link className={`summary-tile${counts.approve ? " has-work" : ""}`} href="/drinks/work?filter=approve">
          <div className="k">판단 기다리는 작업</div>
          <div className="n">{counts.approve}</div>
          <div className="s">작업 단위 기준</div>
        </Link>
        <Link className={`summary-tile${counts.publish ? " has-work" : ""}`} href="/drinks/work?filter=publish">
          <div className="k">게시·확인 필요</div>
          <div className="n">{counts.publish}</div>
          <div className="s">작업 단위 기준</div>
        </Link>
      </div>

      <section className="dk-panel" aria-labelledby="dk-today-h">
        <h2 id="dk-today-h">오늘 수집한 질문 {todayCands ? `${todayCands.count}개` : ""}</h2>
        {todayCands === null ? <p className="dk-note warn">오늘 수집 내역을 읽지 못했습니다(0개가 아니라 조회 실패).</p>
          : todayCands.count === 0 ? <p className="muted">오늘(KST 06:30 수집) 새로 들어온 질문이 아직 없습니다.</p> : <>
            <p className="dk-panel-lead">매일 아침 KST 06:30 에 모아요. 아직 고르지 않은 것 중 점수 높은 순{todayCands.top.length === 0 ? " — 오늘 것은 모두 골랐거나 정리했어요" : ` ${todayCands.top.length}개`}.</p>
            <ul>{todayCands.top.map((c) => <li key={c.id}>{c.question}</li>)}</ul>
          </>}
        <Link className="dk-text-link" href="/drinks/studio">스튜디오에서 날짜별로 보기 →</Link>
      </section>

      <div className="dk-grid2">
        <section className="dk-panel" aria-labelledby="dk-weekly-h">
          <h2 id="dk-weekly-h">이번 주, 이만큼 만들었어요</h2>
          <p className="dk-panel-lead">{mondayOf(today)} 주 · 게시 완료 기준(앱에서 직접 올린 밈 포함)</p>
          {weekly.map((w) => {
            const goal = w.target.min === w.target.max ? `${w.target.max}` : `${w.target.min}~${w.target.max}`;
            const pct = Math.min(100, Math.round((w.done / w.target.max) * 100));
            return (
              <div key={w.format} className="dk-weekly">
                <b>{FORMAT_LABEL[w.format]}<small>진행 중 {w.inProgress}</small></b>
                <span className="dk-track" aria-hidden><i style={{ width: `${pct}%` }} /></span>
                <span>{w.done} / {goal}</span>
              </div>
            );
          })}
          <p className="muted" style={{ fontSize: 12 }}>주간 목표는 운영 가설입니다(설명형은 영상 구매 결재에 묶여 1~2편).</p>
          <Link className="dk-text-link" href="/drinks/studio">다음 소재 고르기 →</Link>
        </section>

        <section className="dk-panel" aria-labelledby="dk-block-h">
          <h2 id="dk-block-h">막힘 {blockers.length > 0 ? `(${blockers.length})` : ""}</h2>
          {blockers.length === 0 ? <p className="muted">지금 막힌 것이 없습니다.</p> : blockers.map((b) => {
            const unknown = b.code.endsWith("unknown");
            return (
              <div key={b.code} className={`dk-follow ${unknown ? "warn" : "block"}`} role="status">
                <span className="num" aria-hidden>{unknown ? "?" : "!"}</span>
                <p>{b.text}{b.href && <> — <Link href={b.href}>열기</Link></>}</p>
              </div>
            );
          })}
          <CollectHealth health={health} />
        </section>
      </div>
    </main>
  );
}

type Health = Awaited<ReturnType<typeof loadRunHealth>>;

/** 수집 상태 한 줄(옛 보드와 같은 규칙). 조회 실패는 "0건"이 아니라 실패로. */
export function CollectHealth({ health }: { health: Health }) {
  if (health.state !== "ok") {
    return <p className="dk-note warn">수집 상태를 읽지 못했습니다{health.state === "failed" ? ` — ${health.error}` : ""} (0건이 아니라 조회 실패).</p>;
  }
  const h = health.data;
  if (h.active === 0) {
    return <p className="dk-note"><b>활성 수집원 없음.</b> 소재는 직접 등록한 것만 들어옵니다. <Link href="/drinks/sources">수집원</Link>에서 검증·활성화하세요.</p>;
  }
  const bad = h.failed + h.partial + h.aborted + h.stuck;
  return (
    <p className={bad > 0 ? "dk-note warn" : "dk-note"}>
      수집: 활성 수집원 <b>{h.active}</b> · 최근 24시간 성공 {h.succeeded} · 정상 0건 {h.empty} · 부분 {h.partial} · 실패 {h.failed} · 중단 {h.aborted}
      {h.stuck > 0 && <> · <b>응답 끊긴 실행 {h.stuck}</b></>} — <Link href={bad > 0 ? "/drinks/runs?status=failed" : "/drinks/runs"}>실행 기록</Link>
    </p>
  );
}
