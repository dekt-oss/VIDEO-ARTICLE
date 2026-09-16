// 홈 요약 타일 (개선 지시서 HOME-01: 5개 → 3개).
//
// 뺀 것: "발행" 누계 — 즉시 행동과 무관한 숫자다(보관함·성과 화면에서 본다).
// 합친 것: "초안 대기"·"렌더 진행중"·"렌더 완료" → 사람이 판단할 것(검수 필요) /
//          렌더가 막혔거나 올릴 것(렌더·업로드 필요). 진행 중인 것은 사람이 할 일이 없으므로
//          타일에서 뺐다(⑥ 화면의 "진행 중" 탭에서 본다).
import type { WorkSummaryCounts } from "@/lib/work/nextAction";
import type { WorkHrefs } from "@/lib/work/nextAction";

export default function WorkSummary({
  counts,
  hrefs,
}: {
  counts: WorkSummaryCounts;
  hrefs: WorkHrefs;
}) {
  const tiles = [
    { n: counts.undecided, k: "후보 미결정", href: hrefs.home },
    { n: counts.reviewNeeded, k: "검수 필요", href: hrefs.review },
    { n: counts.renderNeeded, k: "렌더·업로드 필요", href: hrefs.render },
  ];
  return (
    <div className="summary-strip">
      {tiles.map((t) => (
        <a
          key={t.k}
          className={t.n > 0 ? "summary-tile has-work" : "summary-tile"}
          href={t.href}
        >
          <div className="n">{t.n}</div>
          <div className="k">{t.k}</div>
        </a>
      ))}
    </div>
  );
}
