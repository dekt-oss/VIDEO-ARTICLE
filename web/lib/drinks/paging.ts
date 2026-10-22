// 주류 조회의 두 상한을 따로 다룬다 (검토 보완 2026-10-22).
//   ① 요청 크기: `.in()` id 가 많으면 응답 헤더가 넘쳐 fetch 가 통째로 죽는다 → id 150개씩 청크(web/lib/supabase/chunked.ts 와 같은 이유)
//   ② 응답 행 상한: PostgREST 는 요청하지 않아도 max_rows(Supabase 기본 1000)에서 **조용히** 자른다
//      → 매 쪽 `count: "exact"` 로 전체 건수를 받아, 받은 행이 전체에 못 미치면 다음 쪽을 더 읽는다.
//   서버 상한이 1000 이 아니어도(500 등) 전체 건수로 판정하므로 잘림을 놓치지 않는다.
//   다 못 읽으면 "실패"를 돌려준다 — 받은 만큼을 정상 목록처럼 내보내지 않는다.
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다.

export const PAGE_SIZE = 1000;
export const IN_CHUNK = 150;
/** 폭주 방지. 넘으면 실패로 본다(예상 규모를 벗어났다). */
export const MAX_ROWS = 50_000;

export interface PageResponse<T> {
  data: T[] | null;
  error: { message: string } | null;
  count?: number | null;
}

export type PageResult<T> = { ok: true; rows: T[]; total: number } | { ok: false; error: string };

/**
 * 한 조회를 끝까지 읽는다. page(from, to) 는 `.select(cols, { count: "exact" }).order(키).range(from, to)` 여야 한다
 * (정렬 키가 없으면 쪽끼리 겹치거나 빠질 수 있다).
 */
export async function fetchAllPages<T>(
  page: (from: number, to: number) => PromiseLike<PageResponse<T>>,
  label: string,
  pageSize: number = PAGE_SIZE
): Promise<PageResult<T>> {
  const rows: T[] = [];
  let total: number | null = null;
  for (;;) {
    const from = rows.length;
    const r = await page(from, from + pageSize - 1);
    if (r.error) return { ok: false, error: `${label}: ${r.error.message}` };
    if (!r.data) return { ok: false, error: `${label}: 응답이 비었습니다` };
    if (typeof r.count !== "number") {
      return { ok: false, error: `${label}: 전체 건수를 받지 못해 잘렸는지 확인할 수 없습니다` };
    }
    total = r.count;
    rows.push(...r.data);
    if (rows.length >= total) break;
    if (r.data.length === 0) return { ok: false, error: `${label}: 전체 ${total}건 중 ${rows.length}건만 받았습니다` };
    if (rows.length > MAX_ROWS) return { ok: false, error: `${label}: ${MAX_ROWS}건을 넘어 읽기를 멈췄습니다` };
  }
  return { ok: true, rows, total: total ?? rows.length };
}

/** id 목록을 청크로 나누고, 청크마다 끝까지 읽는다. 청크 하나라도 실패하면 전체 실패. */
export async function fetchAllIn<T>(
  ids: readonly (string | null | undefined)[],
  page: (chunk: string[], from: number, to: number) => PromiseLike<PageResponse<T>>,
  label: string,
  chunkSize: number = IN_CHUNK,
  pageSize: number = PAGE_SIZE
): Promise<PageResult<T>> {
  const unique = [...new Set(ids.filter((x): x is string => Boolean(x)))];
  const out: T[] = [];
  for (let i = 0; i < unique.length; i += chunkSize) {
    const c = unique.slice(i, i + chunkSize);
    const r = await fetchAllPages((from, to) => page(c, from, to), label, pageSize);
    if (!r.ok) return r;
    out.push(...r.rows);
  }
  return { ok: true, rows: out, total: out.length };
}

/** 포인터가 가리키는데 결과에 없는 id. 비어 있지 않으면 "없음"이 아니라 "조회 누락"이다. */
export function missingIds(wanted: readonly (string | null | undefined)[], got: Iterable<string>): string[] {
  const have = new Set(got);
  return [...new Set(wanted.filter((x): x is string => Boolean(x)))].filter((x) => !have.has(x));
}
