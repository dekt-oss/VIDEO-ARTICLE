// 주류 제작 (/drinks/production) — 편성된 소재의 형식별 제작안 승인 상태.
// ★ "제작안 승인"은 대본·페이지 구성 승인일 뿐이다. 파일은 /drinks/production/[planId] 에서 렌더하고 따로 검수한다(C단계).
//   검수 승인된 파일은 /drinks/publish 에서 발행안 → 승인 → 예약으로 이어진다(D단계, 2026-10-27).
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import { FORMAT_LABEL, VERSION_STATUS_LABEL, deriveTopic, type Format } from "@/lib/drinks/model";
import { loadBoard } from "@/lib/drinks/queries";
import type { PlanRow } from "@/lib/drinks/types";

export const dynamic = "force-dynamic";

const TABS = {
  action: "조치 필요",
  drafting: "작성 중",
  review: "검수 대기",
  approved: "제작안 승인 — 렌더·파일 검수",
} as const;
type TabKey = keyof typeof TABS;

function bucket(p: PlanRow | null | undefined, unselected = false, evidenceUnusable = false): TabKey {
  if (!p || unselected || evidenceUnusable || p.blocked_at || p.plan_status === "changes_requested") return "action";
  if (p.plan_status === "draft") return "drafting";
  if (p.plan_status === "in_review") return "review";
  return "approved";
}

export default async function DrinksProductionPage(props: { searchParams: Promise<{ tab?: string }> }) {
  const { tab: raw } = await props.searchParams;
  const tab: TabKey = raw && raw in TABS ? (raw as TabKey) : "action";
  const board = await loadBoard();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 제작</h1>
        <span className="muted">형식별 제작안</span>
      </div>
      <p className="banner-info" style={{ marginTop: 12 }}>
        승인된 제작안은 [렌더·검수]에서 <b>로컬·무료 렌더</b>(대체 이미지 + 무료 TTS)로 파일을 만들고 최종 파일을 검수합니다.
        유료 그림은 결재한 금액 안에서만 삽니다. 검수 승인한 파일은 <Link href="/drinks/publish">발행</Link>에서 인스타 게시를 승인·예약합니다.
      </p>
      {board.state !== "ok" ? (
        <LoadProblem state={board.state} error={board.state === "failed" ? board.error : undefined} />
      ) : (
        (() => {
          // 편성된 형식 + 편성이 풀렸어도(근거 철회 등) 이미 제작안이 있는 형식. 차단된 제작안을 목록에서 숨기지 않는다.
          const items = board.data.topics.flatMap((t) => {
            const d = deriveTopic(t, board.data.reviews, board.data.deliverables, board.data.plans);
            const fmts = new Set<Format>(t.status === "selected" ? t.selected_formats ?? [] : []);
            for (const f of Object.keys(d.plans) as Format[]) if (d.plans[f]) fmts.add(f);
            return [...fmts].map((f) => {
              const p = d.plans[f] ?? null;
              const rv = p ? board.data.reviews.get(p.topic_review_id) : undefined;
              // 승인 기록이 있어도 그 근거를 지금 쓸 수 없으면 "제작안 승인"이 아니라 조치 필요다.
              const evidenceUnusable = Boolean(p && !p.blocked_at && rv && rv.currently_valid !== true);
              return { t, f, p, unselected: t.status !== "selected", evidenceUnusable };
            });
          });
          const counts = Object.fromEntries((Object.keys(TABS) as TabKey[]).map((k) => [k, items.filter((i) => bucket(i.p, i.unselected, i.evidenceUnusable) === k).length]));
          const rows = items.filter((i) => bucket(i.p, i.unselected, i.evidenceUnusable) === tab);
          return (
            <>
              <nav className="dk-tabs" aria-label="제작 탭">
                {(Object.keys(TABS) as TabKey[]).map((k) => (
                  <Link key={k} href={`/drinks/production?tab=${k}`} data-active={k === tab}>
                    {TABS[k]} ({counts[k]})
                  </Link>
                ))}
              </nav>
              {rows.length === 0 ? (
                <p className="muted">{items.length === 0 ? "편성된 소재가 없습니다(정상 0건)." : "이 탭에 해당하는 제작안이 없습니다."}</p>
              ) : (
                rows.map(({ t, f, p, unselected, evidenceUnusable }) => (
                  <div key={`${t.id}-${f}`} className="list-row">
                    <span>
                      <Link href={`/drinks/review/${t.id}?tab=${f}`}>{t.title}</Link>{" "}
                      <span className="pill">{FORMAT_LABEL[f]}</span>
                    </span>
                    <span className="list-row-meta">
                      {!p ? "제작안 없음" : (
                        <>
                          버전 {p.revision_no} · {p.blocked_at ? <span className="dk-bad">근거 철회·사용 불가로 차단</span> : VERSION_STATUS_LABEL[p.plan_status]}
                          {p.topic_review_id !== t.selected_review_id && <span className="dk-warn"> · 편성 근거와 다른 버전</span>}
                        </>
                      )}
                      {unselected && <span className="dk-warn"> · 소재가 편성 해제됨</span>}
                      {evidenceUnusable && <span className="dk-bad"> · 근거 현재 사용 불가</span>}
                      {bucket(p, unselected, evidenceUnusable) === "approved" && p && <Link className="pill" href={`/drinks/production/${p.id}`}>렌더·검수 →</Link>}
                    </span>
                  </div>
                ))
              )}
            </>
          );
        })()
      )}
    </main>
  );
}
