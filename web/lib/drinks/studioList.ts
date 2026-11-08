// 스튜디오 소재 목록 규칙(2026-11-08 운영자: "자동생성이 안 되는 건 리스트에 없어야", "중복소재가 왜 이렇게 많아").
//   돈이 들지 않는 규칙 처리다(모델 호출 없음). 후보를 지우지 않는다 — 목록에서만 뺀다.
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다.

/** 비슷한 질문으로 묶는 문턱(희귀 낱말 가중 겹침). 운영 후보 524건에 대어 정했다 — 낮추면 다른 질문까지 묶인다. */
export const SIMILAR_MIN = 0.24;

export interface GroupRow { id: string; text: string; categories: readonly string[] }
export interface Group<T> { lead: T; merged: number }

function grams(text: string): Set<string> {
  const s = text.replace(/\[[^\]]*\]|\([^)]*\)/g, "").replace(/[^0-9A-Za-z가-힣]/g, "");
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i += 1) out.add(s.slice(i, i + 2));
  return out;
}

// 글자가 달라도 같은 이야기인 주제 — 주종이 같고 이 주제가 같으면 한 소재로 본다(글자 비교로는 "1년 된 막걸리"와 "개봉한 막걸리 언제까지"가 안 묶인다).
// shortcut: 손으로 적은 목록이라 새 주제는 못 잡는다, 중복이 다시 눈에 띄면 여기에 더하거나 모델 판정으로 바꾼다.
const THEMES: [string, RegExp][] = [
  ["storage", /유통\s*기한|보관|개봉|오픈\s*후|오래\s*(된|두)|상온|냉장|상할|상하나|언제까지|년\s*(다\s*)?(된|지난|전)/],
  ["rain", /비\s*(가\s*)?(오|내리)|비오는|파전/],
  ["aspartame", /아스파탐/], ["hangover", /숙취/], ["diet", /살찌|다이어트|칼로리/],
  ["bourbon_scotch", /버번.*스카치|스카치.*버번/], ["raw_pasteurized", /생\s*막걸리.*살균|살균.*생\s*막걸리/],
  ["single_blended", /싱글\s*몰트.*블렌디드|블렌디드.*싱글\s*몰트/], ["cheongju", /청주.*(약주|탁주)|(약주|탁주).*청주/],
  ["how_to_drink", /니트|온더락|하이볼/], ["cask_strength", /캐스크\s*스트렝스/], ["warm", /데워|따뜻|아츠캉/],
  ["pairing", /안주|어울리/], ["sake_grade", /준마이|다이긴[조죠]|긴[조죠]/], ["polish", /정미율|정미보합|깎/],
];
export function themeOf(text: string): string | null {
  return THEMES.find(([, re]) => re.test(text))?.[0] ?? null;
}

/** 주종이 겹치지 않으면 같은 질문이 아니다(사케 보관 ≠ 위스키 보관). 주종을 모르는 글은 묶지 않는다. */
const sameDrink = (a: readonly string[], b: readonly string[]) => a.some((x) => b.includes(x));

/**
 * 비슷한 질문을 묶고 묶음마다 맨 앞 하나만 남긴다. rows 는 점수 높은 순이어야 한다(그 순서로 대표가 정해진다).
 * existing(이미 있는 소재)과 비슷한 후보는 대표로도 남기지 않는다 — 같은 이야기를 두 번 만들지 않게.
 */
export function groupSimilar<T extends GroupRow>(rows: readonly T[], existing: readonly GroupRow[] = []): { groups: Group<T>[]; droppedAsExisting: number } {
  const all = [...rows, ...existing].map((r) => grams(r.text));
  const df = new Map<string, number>();
  for (const g of all) for (const x of g) df.set(x, (df.get(x) ?? 0) + 1);
  const n = Math.max(all.length, 1);
  const weight = (s: Iterable<string>) => { let w = 0; for (const x of s) w += Math.log(n / (df.get(x) ?? 1)); return w; };
  const score = (a: Set<string>, b: Set<string>) => {
    const both = [...a].filter((x) => b.has(x));
    if (both.length === 0) return 0;
    const w = weight(new Set([...a, ...b]));
    return w > 0 ? weight(both) / w : 0;
  };

  const existingGrams = existing.map((e) => ({ e, g: grams(e.text), theme: themeOf(e.text) }));
  const clusters: { group: Group<T>; members: { g: Set<string>; categories: readonly string[]; theme: string | null }[] }[] = [];
  let droppedAsExisting = 0;
  for (const r of rows) {
    const g = grams(r.text);
    const theme = themeOf(r.text);
    const same = (o: { g: Set<string>; theme: string | null }) => (theme !== null && o.theme === theme) || score(g, o.g) >= SIMILAR_MIN;
    if (existingGrams.some((x) => sameDrink(r.categories, x.e.categories) && same(x))) { droppedAsExisting += 1; continue; }
    const hit = clusters.find((c) => c.members.some((m) => sameDrink(r.categories, m.categories) && same(m)));
    if (hit) { hit.group.merged += 1; hit.members.push({ g, categories: r.categories, theme }); }
    else clusters.push({ group: { lead: r, merged: 0 }, members: [{ g, categories: r.categories, theme }] });
  }
  return { groups: clusters.map((c) => c.group), droppedAsExisting };
}

/** 근거 자료로 답할 수 없는 질문(취향 묻기·추천 부탁·안부). 자료 확인이 실패할 것이 뻔하니 목록에 올리지 않는다. */
const OPINION = /(여러분|회원님|다들|님들|제일 좋아하|최애|추천\s*(부탁|해\s*주|있을까|좀)|뭐\s*마시지|시켜요|사올만한|어떤\s*점을\s*좋아|있으신가요|있으시죠|당신의\s*선택|어떻게\s*정리|어떤게\s*있을까요|사야\s*하나요)/;
export function isAnswerable(question: string): boolean {
  return !OPINION.test(question);
}

/** 자동 복구 대상이 아닌 이유로 멈춘 소재인가 — 다시 눌러도 같은 실패라 목록에 두지 않는다. */
export function isStopped(last: { status: string; error_code: string | null } | null | undefined, recoverable: readonly string[]): boolean {
  if (!last) return false;
  if (last.status === "blocked") return true;
  return last.status === "failed" && !recoverable.includes(last.error_code ?? "");
}
