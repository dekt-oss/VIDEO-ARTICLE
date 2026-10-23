// 주류 소재 발견(B 보완, 0052) — 화면 규칙·타입(순수). 값 import 없음(node --test).
// ★ 발견 자료는 사실 근거가 아니다. 후보 점수(discovery-v1)는 임시이고, 승인·편성은 A단계 흐름에서 사람이 한다.

export interface DiscoveryItemRow {
  id: string;
  platform: string;
  canonical_url: string;
  source_id: string | null;
  channel_name: string | null;
  title: string | null;
  summary: string | null;
  posted_at: string | null;
  discovered_at: string;
  coverage: "link_only" | "title_only" | "title_summary" | "title_summary_comments";
  collection_status: "collected" | "manual";
  rights_status: string;
  questions: string[];
  signals: string[];
  operator_note: string | null;
  origin_group: string | null;
  latest_metrics: Record<string, number> | null;
  metrics_observed_at: string | null;
  version: number;
}

export interface CandidateRow {
  id: string;
  status: "suggested" | "dismissed" | "promoted" | "merged";
  key_question: string;
  reader_value: string | null;
  discovery_path: string | null;
  signals: string[];
  interest: { independent_sources?: number; items?: number; by_platform?: Record<string, Record<string, number>>; note?: string };
  first_scene: string | null;
  fit_video: number | null;
  fit_carousel: number | null;
  facts_to_check: string[];
  duplicate_topic_ids: string[];
  provisional_score: number | string | null;
  rubric: string;
  score_reason: string | null;
  promoted_topic_id: string | null;
  merged_into: string | null;
  decision_reason: string | null;
  version: number;
  created_at: string;
}

export const PLATFORM_LABEL: Record<string, string> = {
  stackexchange: "Stack Exchange", youtube: "유튜브", naver_cafe: "네이버 카페", naver_blog: "네이버 블로그",
  instagram: "인스타그램", reddit: "레딧", community: "커뮤니티", web: "웹",
};
export const SIGNAL_LABEL: Record<string, string> = {
  question: "질문", debate: "논쟁", misconception: "오해", selection: "선택 고민", storage: "보관", new_product: "신제품", event: "행사",
};
export const COVERAGE_LABEL: Record<DiscoveryItemRow["coverage"], string> = {
  link_only: "링크만", title_only: "제목만", title_summary: "제목·요약", title_summary_comments: "제목·요약·댓글 질문",
};
export const METRIC_LABEL: Record<string, string> = {
  views: "조회", likes: "좋아요", comments: "댓글", answers: "답변", score: "점수", favorites: "즐겨찾기",
};

export type ChannelState = "live" | "needs_key" | "manual_only";

/** 채널별 연결 상태. 실제로 연결된 것·키가 있어야 되는 것·수동 링크만 되는 것을 갈라 보여준다(근거: 공식 문서 확인 2026-10-22). */
export const CHANNELS: { platform: string; how: string; state: ChannelState; coverage: string; why: string }[] = [
  { platform: "stackexchange", how: "Stack Exchange API(키 없이 하루 300회)", state: "live", coverage: "질문 제목·본문 요약·조회·점수·답변 수",
    why: "Beer, Wine & Spirits 커뮤니티. 글은 CC BY-SA 4.0 — 작성자·링크 표기" },
  { platform: "youtube", how: "YouTube Data API v3(search·videos·commentThreads)", state: "needs_key",
    coverage: "제목·설명·조회/좋아요/댓글 수(공개된 것만)·댓글의 질문 문장", why: "YOUTUBE_DATA_API_KEY 가 없으면 실행이 '키 필요'로 실패한다. 검색 1회 = 쿼터 100" },
  { platform: "naver", how: "네이버 클라우드 API HUB 검색(카페글·블로그)", state: "needs_key", coverage: "검색 결과 제목·요약만(회원 전용 카페 본문 아님)",
    why: "NAVER_CLIENT_ID/SECRET 필요(술째리고와 같은 API HUB 키). 한시 무료 · 월 775,000건(같은 키 합산) 넘으면 자동 차단" },
  { platform: "instagram", how: "수동 링크", state: "manual_only", coverage: "운영자가 적은 메모·질문만",
    why: "해시태그 검색은 Meta 앱 검수 + 비즈니스 인증 + 비즈니스 계정 로그인이 필요(D단계 OAuth 범위)" },
  { platform: "reddit", how: "수동 링크", state: "manual_only", coverage: "운영자가 적은 메모·질문만",
    why: "robots.txt 가 일반 수집기를 막고, 데이터 API 키가 없다" },
  { platform: "web", how: "수동 링크", state: "manual_only", coverage: "운영자가 적은 메모·질문만", why: "그 밖의 커뮤니티·게시판 — 서버가 URL 을 열지 않는다" },
];
export const CHANNEL_STATE_LABEL: Record<ChannelState, string> = { live: "실제 연결", needs_key: "키 설정 필요", manual_only: "수동 링크만" };

/** 지표 표시: 제공된 것만, 관측 시각과 함께. 미제공은 "미제공"(0 이 아님). */
export function metricText(m: Record<string, number> | null | undefined, observedAt: string | null | undefined): string {
  if (!m || Object.keys(m).length === 0) return "공개 지표 미제공";
  const parts = Object.entries(m).map(([k, v]) => `${METRIC_LABEL[k] ?? k} ${v.toLocaleString()}`);
  return `${parts.join(" · ")}${observedAt ? ` (관측 ${observedAt.slice(0, 16).replace("T", " ")})` : ""}`;
}

/** 후보 관심 신호 한 줄 — 플랫폼별로 따로, 합산하지 않는다. */
export function interestText(i: CandidateRow["interest"]): string {
  const by = Object.entries(i.by_platform ?? {}).map(([p, v]) => {
    const metrics = Object.entries(v).filter(([k]) => k.startsWith("max_")).map(([k, n]) => `${METRIC_LABEL[k.slice(4)] ?? k} 최대 ${n.toLocaleString()}`);
    return `${PLATFORM_LABEL[p] ?? p} ${v.items ?? 0}건${metrics.length ? `(${metrics.join(", ")})` : ""}`;
  });
  return `독립 출처 ${i.independent_sources ?? 0}곳 · ${by.join(" / ") || "자료 없음"}`;
}
