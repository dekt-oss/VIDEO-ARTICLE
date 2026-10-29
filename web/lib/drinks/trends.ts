// 주류 동향(0059) — 화면 규칙·타입(순수). 값 import 없음(node --test).
// ★ 커뮤니티 언급은 사람들이 무엇을 말하나의 신호일 뿐 사실 근거가 아니다. 반응 점수(-1~1)는 Jev 가 검색 요약을 보고 낸 판정이며,
//   판정을 못 한 언급은 null('판정 없음')이다 — 추측해 채우지 않는다.

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

export function sentimentBar(r: Pick<TrendProductRow, "judged" | "positive" | "negative">): SentimentBar {
  if (!r.judged || r.judged <= 0) return { positivePct: 0, neutralPct: 0, negativePct: 0, none: true };
  const pos = Math.min(100, Math.round((r.positive / r.judged) * 100));
  const neg = Math.min(100 - pos, Math.round((r.negative / r.judged) * 100));
  return { positivePct: pos, neutralPct: 100 - pos - neg, negativePct: neg, none: false };
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
