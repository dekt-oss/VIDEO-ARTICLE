// 주류 동향(0059) — 화면 규칙·타입(순수). 값 import 없음(node --test).
// ★ 커뮤니티 언급은 사람들이 무엇을 말하나의 신호일 뿐 사실 근거가 아니다. 반응 점수(-1~1) = p_good - p_bad 는 Jev 가 검색 요약을 보고
//   '좋게 평가하나'·'나쁘게 평가하나' 두 질문으로 낸 판정이다. 의견 없는 글(질문·구매글)은 둘 다 낮아 '중립'이고,
//   Jev 를 못 쓴 언급만 null('판정 없음')이다 — 추측해 채우지 않는다.

/** engine/config.py DRINKS_TRENDS_POSITIVE_ABOVE·NEGATIVE_BELOW 및 0059 보기와 같아야 한다(tests/test_drinks_trends.py 가 SQL 쪽을 대조). */
export const POSITIVE_ABOVE = 0.2;
export const NEGATIVE_BELOW = -0.2;

export interface TrendProductRow {
  product: string;
  category: "sake" | "traditional" | "whisky";
  posts: number;
  mentions: number;
  judged: number;
  avg_sentiment: number | null;
  positive: number;
  negative: number;
  neutral?: number;
  last_seen: string;
  sample_urls: string[] | null;
  sample_titles: string[] | null;
}

export interface TrendIssueRow {
  id: string;
  title: string;
  summary: string | null;
  canonical_url: string;
  channel_name: string | null;
  posted_at: string | null;
  query: string | null;
  collected_at: string;
}

/** 판정이 없으면 null → '판정 없음'. 있으면 문턱으로 긍정/중립/부정. */
export function sentimentLabel(score: number | null | undefined): "긍정" | "중립" | "부정" | "판정 없음" {
  if (typeof score !== "number" || Number.isNaN(score)) return "판정 없음";
  if (score > POSITIVE_ABOVE) return "긍정";
  if (score < NEGATIVE_BELOW) return "부정";
  return "중립";
}

/** 언급 수 순(같으면 판정된 수, 그다음 이름). 보기가 정렬을 보장하지 않으므로 화면에서 정한다. */
export function rankProducts<T extends Pick<TrendProductRow, "product" | "posts" | "judged">>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.posts - a.posts || b.judged - a.judged || a.product.localeCompare(b.product, "ko"));
}

export interface SentimentBar {
  /** 막대 폭(%) — 판정된 언급 중 긍정·중립·부정 비율. 판정이 하나도 없으면 전부 0. */
  positivePct: number;
  neutralPct: number;
  negativePct: number;
  /** 판정된 언급이 하나도 없다 */
  none: boolean;
}

export function sentimentBar(r: Pick<TrendProductRow, "judged" | "positive" | "negative"> & { neutral?: number }): SentimentBar {
  if (!r.judged || r.judged <= 0) return { positivePct: 0, neutralPct: 0, negativePct: 0, none: true };
  const pos = Math.min(100, Math.round((r.positive / r.judged) * 100));
  const neg = Math.min(100 - pos, Math.round((r.negative / r.judged) * 100));
  return { positivePct: pos, neutralPct: 100 - pos - neg, negativePct: neg, none: false };   // 중립 = 나머지(= neutral 개수 비율)
}

/** 점수 표시: +0.42 / -0.31 / 판정 없음. */
export function scoreText(score: number | null | undefined): string {
  if (typeof score !== "number" || Number.isNaN(score)) return "판정 없음";
  return `${score > 0 ? "+" : ""}${score.toFixed(2)}`;
}

/** 읽기에서 0059 가 아직 적용되지 않은 오류인가(표/보기가 없다). */
export function isMissingTrendTables(message: string | null | undefined): boolean {
  return /drink_trend_(products|issues|posts|mentions)/.test(message ?? "") && /does not exist|schema cache|not found|Could not find/i.test(message ?? "");
}

/** 같은 주소만 http(s) 로 링크한다 — 외부 글 링크에 javascript: 등이 새지 않게. */
export function safeHref(url: string | null | undefined): string | null {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

// ── 이슈 묶기 ── 같은 이야기를 쓴 기사 여러 건(예: "생맥주 주세 20% 경감 3년 연장" 6건+)을 한 줄로.
//   엔진 소재 발견의 낱말 Jaccard(`drinks_discover.similarity`)와 같은 생각 - 글자 2개짜리(bigram) 집합의 Jaccard,
//   겹친 조각이 2개 미만이면 0(짧은 제목끼리 우연히 묶이지 않게). 판정이 아니라 보기 편하게 묶는 규칙이다.

export const ISSUE_SIMILAR_MIN = 0.5;

function bigrams(title: string): Set<string> {
  const out = new Set<string>();
  for (const run of title.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []) {
    for (let i = 0; i < run.length - 1; i++) out.add(run.slice(i, i + 2));
  }
  return out;
}

export function titleSimilarity(a: string, b: string): number {
  const x = bigrams(a);
  const y = bigrams(b);
  let both = 0;
  for (const g of x) if (y.has(g)) both += 1;
  if (both < 2) return 0;
  return both / (x.size + y.size - both);
}

export interface IssueCluster {
  /** 가장 최근 기사 - 대표 제목 */
  representative: TrendIssueRow;
  /** 묶인 기사 수(대표 포함) */
  count: number;
  /** 최근순 최대 3개 링크(대표 포함) */
  links: { url: string; title: string; channel: string | null }[];
  newest: string;
}

const when = (r: TrendIssueRow) => r.posted_at ?? r.collected_at;

/** 제목 유사도 ≥ 0.5 인 기사를 한 묶음으로(묶음 안 아무 기사와 닿으면 합류). 기사 수 많은 순, 같으면 최근 순. */
export function clusterIssues(rows: TrendIssueRow[], threshold: number = ISSUE_SIMILAR_MIN): IssueCluster[] {
  const sorted = [...rows].sort((a, b) => when(b).localeCompare(when(a)) || a.id.localeCompare(b.id));
  const groups: { rows: TrendIssueRow[]; grams: string[] }[] = [];
  for (const r of sorted) {
    const hit = groups.find((g) => g.grams.some((t) => titleSimilarity(t, r.title) >= threshold));
    if (hit) {
      hit.rows.push(r);
      hit.grams.push(r.title);
    } else {
      groups.push({ rows: [r], grams: [r.title] });
    }
  }
  return groups
    .map((g): IssueCluster => ({
      representative: g.rows[0],
      count: g.rows.length,
      links: g.rows.slice(0, 3).map((r) => ({ url: r.canonical_url, title: r.title, channel: r.channel_name })),
      newest: when(g.rows[0]),
    }))
    .sort((a, b) => b.count - a.count || b.newest.localeCompare(a.newest) || a.representative.id.localeCompare(b.representative.id));
}
