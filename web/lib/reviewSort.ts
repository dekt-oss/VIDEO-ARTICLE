// ④ 초안 검수 목록 정렬(2026-09-30 운영자 요청: "초안 작성된 날짜순으로 정렬할 수 있게").
// 기본은 낙점일로 묶는다. 초안 생성순은 **초안을 만든 날(KST)**로 묶고, 초안이 없는 것은 맨 아래 한 묶음.
// 논문·리포트 목록이 같은 규칙을 쓰도록 순수 함수로 둔다(web/lib/reviewSort.test.ts).
// ★ import 없이 둔다 — node --test 는 "./date.ts" 확장자가 있어야 하고 Next 타입 검사는 그것을 막는다.
//   date.ts 의 seoulDateOf 와 같은 계산(Asia/Seoul 달력일, YYYY-MM-DD).
const seoulDateOf = (ts: string): string =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(ts));

export type ReviewSort = "decided" | "draft";

export function parseReviewSort(v: string | string[] | undefined): ReviewSort {
  return v === "draft" ? "draft" : "decided";
}

export interface ReviewGroup<T> {
  /** YYYY-MM-DD(KST). null 이면 그 기준 날짜가 없는 묶음(날짜 미상 · 초안 없음). */
  date: string | null;
  items: T[];
}

type Row = { decided_at: string | null; draft_created_at?: string | null };

/** 입력 순서를 지키며 key 별로 묶는다(key 가 null 이면 맨 뒤 한 묶음). */
function groupBy<T>(rows: T[], key: (r: T) => string | null): ReviewGroup<T>[] {
  const groups: ReviewGroup<T>[] = [];
  const idx = new Map<string, number>();
  const none: T[] = [];
  for (const r of rows) {
    const k = key(r);
    if (k === null) {
      none.push(r);
      continue;
    }
    if (!idx.has(k)) {
      idx.set(k, groups.length);
      groups.push({ date: k, items: [] });
    }
    groups[idx.get(k)!].items.push(r);
  }
  if (none.length) groups.push({ date: null, items: none });
  return groups;
}

const desc = (a: string | null | undefined, b: string | null | undefined) =>
  (b ?? "").localeCompare(a ?? "");

export function groupForReview<T extends Row>(rows: T[], sort: ReviewSort): ReviewGroup<T>[] {
  if (sort === "draft") {
    // 초안 있는 것: 생성 시각 최신순. 없는 것: 낙점 최신순으로 맨 아래.
    const sorted = [...rows].sort((a, b) =>
      a.draft_created_at && b.draft_created_at ? desc(a.draft_created_at, b.draft_created_at)
        : a.draft_created_at ? -1 : b.draft_created_at ? 1 : desc(a.decided_at, b.decided_at));
    return groupBy(sorted, (r) => (r.draft_created_at ? seoulDateOf(r.draft_created_at) : null));
  }
  const sorted = [...rows].sort((a, b) => desc(a.decided_at, b.decided_at));
  return groupBy(sorted, (r) => (r.decided_at ? seoulDateOf(r.decided_at) : null));
}
