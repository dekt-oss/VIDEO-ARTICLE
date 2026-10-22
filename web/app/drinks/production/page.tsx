// 주류 제작 (/drinks/production) — 편성된 소재의 형식별 제작안 승인 상태.
// ★ A단계에는 렌더·파일 검수·발행이 없다. "제작안 승인"은 사람이 쓴 대본·페이지 구성을 승인한 것뿐이고,
//   실제 파일이 만들어졌다는 뜻이 아니다. 렌더 완료·파일 승인·발행 완료로 바꾸는 수동 우회도 없다.
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
  approved: "제작안 승인(제작 미연결)",
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
      <p className="banner-warn" style={{ marginTop: 12 }}>
        <b>실제 제작 미연결.</b> 영상 렌더·카드 이미지 생성·파일 검수·Instagram 발행은 아직 연결되지 않았습니다(B~D단계).
        여기서 보이는 승인은 제작안(대본·장면 / 페이지 구성) 승인입니다.
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
                      {bucket(p, unselected, evidenceUnusable) === "approved" && <span className="pill">실제 제작 미연결</span>}
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
