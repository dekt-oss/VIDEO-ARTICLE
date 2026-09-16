// Supabase 조회의 두 가지 조용한 상한을 넘기는 헬퍼 (2026-08-21).
//
// ─────────────────────────────────────────────────────────────
// 왜 필요한가 — 화면이 "데이터가 없다"고 거짓말을 하고 있었다
// ─────────────────────────────────────────────────────────────
// ① `.in("id", ids)` 의 **응답 헤더 오버플로**
//    PostgREST 는 응답에 `Content-Location` 헤더로 **요청 URL 전체를 되돌려준다.** id 를 500개
//    넘기면 그 헤더 하나가 25KB 가 되고, Node(undici)의 기본 헤더 상한 16KB 를 넘겨
//    `HeadersOverflowError` 로 fetch 자체가 실패한다. 실측 임계치는 **350~400개 사이**
//    (350 성공 87ms / 400 실패 8.5초). 로컬 Node 와 Vercel 런타임의 상한이 달라서
//    "로컬만 깨지는 것처럼" 보였다 — 실제로는 id 3,596개인 /scored 가 프로덕션에서도 깨져
//    1,000행 전부 "(제목 없음)" 으로 나가고 있었다.
//
// ② `select()` 의 **기본 1,000행 상한**
//    PostgREST 는 요청하지 않아도 1,000행에서 자른다. papers 4,447행·scores 3,596행이
//    1,000행으로 잘린 채 "전부"인 척 화면에 나갔다. 잘렸다는 표시도 없었다.
//
// 그리고 두 경우 모두 호출부가 `const { data } = await …` 로 **error 를 통째로 버려서**,
// 실패가 "빈 배열"과 구별되지 않았다. 그래서 화면은 "채점 결과가 없습니다 — 엔진을
// 실행하세요" 같은 **틀린 안내**까지 했다.
//
// ─────────────────────────────────────────────────────────────
// 왜 이렇게 고치나
// ─────────────────────────────────────────────────────────────
// · 조인(PostgREST embedded resource)으로 2차 조회를 아예 없애는 방법도 있다. 더 빠르지만
//   FK 관계·RLS 에 의존하고 반환 모양이 바뀌어 호출부를 전부 다시 써야 한다. 지금 필요한 것은
//   **기계적이고 되돌리기 쉬운 수리**라 청크 분할을 택했다. 조인 전환은 나중에 따로.
// · `NODE_OPTIONS=--max-http-header-size` 로 상한을 올리는 방법은 천장을 옮길 뿐이고
//   Vercel 런타임에서 확실히 먹는다는 보장이 없다 — 근본 수리가 아니다.
// · **에러를 던지지 않는다.** 던지면 조회 한 번 실패로 대시보드 전체가 에러 화면이 된다.
//   대신 `console.error` 로 크게 남기고 받은 만큼 돌려준다. 청크 분할로 원인 자체가
//   사라졌으므로, 이제 이 로그가 뜨면 그건 진짜 사고다(Vercel 로그에서 보인다).

/** `.in()` 한 번에 넣을 id 개수. 실측 임계치(350~400)의 절반 이하로 잡아 여유를 둔다. */
export const IN_CHUNK_SIZE = 150;

/** PostgREST 가 요청 없이 자르는 기본 행 수. `selectAll` 의 페이지 크기이기도 하다. */
export const PAGE_SIZE = 1000;

/**
 * 페이징 폭주 방지 상한(= 최대 50,000행). 여기 걸리면 데이터가 예상 규모를 벗어난 것이므로
 * 조용히 자르지 않고 로그를 남긴다 — 잘린 줄 모르고 보는 것이 이 파일이 고치려는 병이다.
 */
export const MAX_PAGES = 50;

/** 배열을 size 개씩 자른다. 순수 함수 — 테스트: web/lib/supabase/chunked.test.ts */
export function chunk<T>(arr: readonly T[], size: number): T[][] {
  const n = Math.max(1, Math.trunc(size));
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
  return out;
}

/** Supabase 쿼리 빌더가 resolve 되는 모양(성공/실패 공통). */
interface QueryResult<T> {
  data: T[] | null;
  error: { message: string } | null;
}

/**
 * id 목록을 청크로 나눠 조회하고 결과를 이어 붙인다.
 *
 * 반환 순서는 **보장하지 않는다**(청크 경계로 섞인다). 호출부는 이미 전부 Map/Set 으로
 * 인덱싱해 쓰고 있어 무관하다 — 순서가 필요하면 호출부에서 정렬한다.
 *
 * @param ids   조회할 id 들. 중복은 접는다(같은 값을 두 번 보내면 헤더만 길어진다).
 * @param run   한 청크를 조회하는 함수. 보통 `(c) => supabase.from(…).select(…).in("id", c)`.
 * @param label 실패 로그에 찍을 이름(예: "papers.id"). 어느 조회가 죽었는지 알아야 고친다.
 */
export async function selectIn<T>(
  ids: readonly string[],
  run: (chunk: string[]) => PromiseLike<QueryResult<T>>,
  label: string,
  chunkSize: number = IN_CHUNK_SIZE,
): Promise<T[]> {
  const unique = [...new Set(ids.filter(Boolean))];
  if (unique.length === 0) return [];

  const groups = chunk(unique, chunkSize);
  // 청크끼리는 독립이라 동시에 보낸다. 청크 하나가 죽어도 나머지는 살린다.
  const settled = await Promise.all(
    groups.map(async (g) => {
      try {
        const { data, error } = await run(g);
        if (error) {
          console.error(`[supabase] selectIn(${label}) 청크 실패 — ${error.message}`);
          return [] as T[];
        }
        return data ?? [];
      } catch (e) {
        // fetch 자체가 죽는 경우(헤더 오버플로·네트워크). 여기 걸리면 청크가 아직 크다는 뜻이다.
        console.error(`[supabase] selectIn(${label}) 청크 예외 — ${String(e)}`);
        return [] as T[];
      }
    }),
  );
  return settled.flat();
}

/**
 * 1,000행 상한을 넘겨 **전부** 읽는다(range 페이징).
 *
 * @param run   `(from, to) => supabase.from(…).select(…).range(from, to)`
 * @param label 실패 로그용 이름.
 */
export async function selectAll<T>(
  run: (from: number, to: number) => PromiseLike<QueryResult<T>>,
  label: string,
  pageSize: number = PAGE_SIZE,
): Promise<T[]> {
  const size = Math.max(1, Math.trunc(pageSize));
  const out: T[] = [];
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const from = page * size;
    let rows: T[];
    try {
      const { data, error } = await run(from, from + size - 1);
      if (error) {
        console.error(`[supabase] selectAll(${label}) ${from}~ 실패 — ${error.message}`);
        return out;
      }
      rows = data ?? [];
    } catch (e) {
      console.error(`[supabase] selectAll(${label}) ${from}~ 예외 — ${String(e)}`);
      return out;
    }
    out.push(...rows);
    if (rows.length < size) return out; // 마지막 페이지
  }
  console.error(
    `[supabase] selectAll(${label}) 페이지 상한(${MAX_PAGES}×${size}행) 도달 — 뒤쪽이 잘렸다`,
  );
  return out;
}
