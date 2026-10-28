// 주류 공장 화면 모델 — 이름표·점수·다음 행동 (2026-10-22, 명세 docs/주류공장_구조명세_v1_2026-10-21.md).
//
// ★ 논문·리포트의 lib/work/* 를 재사용하지 않는다. 그쪽은 paperId·대본·영상지시서를 전제로 해서
//   주류의 "근거 → 공통 기획 → 형식별 제작안" 흐름에 그대로 넣으면 틀린 버튼이 나온다(§3).
// ★ 판정의 정본은 DB(0050)다. 여기 있는 계산은 화면 표시용이고, 서버가 같은 조건을 다시 검사한다.
//   weightedScore 는 SQL drinks_weighted_score 와 같은 값을 내야 한다(supabase/tests/drinks_phase_a.test.mjs).
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다.
import type { DeliverableRow, PlanRow, ReviewRow, TopicRow } from "./types";

export const CATEGORY_LABEL = { sake: "사케", traditional: "전통주", whisky: "위스키" } as const;
export type Category = keyof typeof CATEGORY_LABEL;
export const CATEGORIES = Object.keys(CATEGORY_LABEL) as Category[];

export const LANE_LABEL = { evergreen: "상시 지식", timely: "시의성", reader_question: "독자 질문" } as const;
export type Lane = keyof typeof LANE_LABEL;

// 질문 유형(0058 drink_topics.question_kind). 파이썬 설정 engine/config.py DRINKS_QUESTION_KINDS 와 같은 목록이어야 한다
// (tests/test_drinks_bootstrap.py 가 SQL 과 대조). general 은 "아직 모름/일반" - 전략이 따로 배우지 못하는 기본값.
export const QUESTION_KIND_LABEL = {
  storage: "보관", misconception: "오해", selection: "선택", debate: "논쟁", pairing: "페어링", howto: "방법", general: "일반",
} as const;
export type QuestionKind = keyof typeof QUESTION_KIND_LABEL;
export const QUESTION_KINDS = Object.keys(QUESTION_KIND_LABEL) as QuestionKind[];

export const TOPIC_STATUS_LABEL = {
  inbox: "등록됨",
  triaged: "경량 평가 완료",
  researching: "조사 중",
  ready: "편성 가능",
  selected: "편성됨",
  on_hold: "보류",
  rejected: "제외",
  duplicate: "중복",
} as const;
export type TopicStatus = keyof typeof TOPIC_STATUS_LABEL;

export const VERSION_STATUS_LABEL = {
  draft: "작성 중",
  in_review: "검토 중",
  approved: "승인",
  changes_requested: "변경 요청",
} as const;
export type VersionStatus = keyof typeof VERSION_STATUS_LABEL;

export const FORMAT_LABEL = { video: "영상", carousel: "카드뉴스" } as const;
export type Format = keyof typeof FORMAT_LABEL;
export const FORMATS = Object.keys(FORMAT_LABEL) as Format[];

export const SOURCE_KIND_LABEL = {
  official: "공식 기관",
  expert: "전문 자료",
  manufacturer: "제조사",
  importer: "수입사",
  media: "언론",
  retailer: "판매처",
  community: "커뮤니티",
  reader: "독자 질문·댓글",
  other: "기타",
} as const;

export const DEPTH_LABEL = {
  metadata_only: "URL만 — 본문 미확보(근거로 쓸 수 없음)",
  excerpt: "발췌 직접 입력",
  full_text: "원문 전문 직접 입력",
} as const;

/** 수집 문서(B단계)는 "직접 입력"이 아니다 — 같은 깊이라도 출처에 맞게 부른다. */
export function depthLabel(depth: keyof typeof DEPTH_LABEL, capture?: "manual" | "collected"): string {
  if (capture !== "collected") return DEPTH_LABEL[depth];
  return depth === "metadata_only" ? "제목·요약만 — 본문 미확보(근거로 쓸 수 없음)" : "수집한 본문";
}

export const RIGHTS_LABEL = {
  unknown: "사용 조건 미확인",
  quote_ok: "인용 가능",
  summary_only: "요약·출처 표기만",
  restricted: "사용 불가",
} as const;

export const ROLE_LABEL = { discovery: "질문·인기 신호", evidence: "사실 근거" } as const;

export const DEDUP_LABEL: Record<string, string> = {
  new: "새 출처로 저장했습니다.",
  same_url_same_body: "같은 URL·같은 본문이 이미 있어 새로 만들지 않고 연결만 했습니다.",
  changed_version: "같은 URL 의 본문이 달라 새 버전으로 보관했습니다(옛 버전은 그대로 남습니다).",
  same_body_other_url: "다른 URL 에 글자 그대로 같은 본문이 있어 같은 원출처로 묶었습니다.",
  same_body: "같은 본문이 이미 있어 연결만 했습니다.",
};

export const CLAIM_TYPE_LABEL = {
  product_fact: "제품 사실",
  process: "공정·원리",
  comparison: "비교",
  opinion: "취향·평가(주관)",
} as const;

export const SUPPORT_LABEL = {
  supported: "주장을 뒷받침함",
  conflicting: "출처끼리 충돌",
  insufficient: "뒷받침 부족",
  not_reviewed: "아직 안 봄",
  not_applicable: "해당 없음(주관 평가)",
} as const;

export const QUOTE_LABEL = {
  matched: "원문에 발췌 있음",
  unmatched: "원문에서 발췌를 못 찾음",
  not_checked: "대조 불가(본문 없음)",
} as const;

export const REASON_CODE_LABEL = {
  duplicate: "중복",
  insufficient_evidence: "근거 부족",
  audience_mismatch: "독자 불일치",
  hard_to_visualize: "화면화 어려움",
  expired: "시기 만료",
  cost: "비용",
  other: "기타",
} as const;

export const VISUAL_ROLE_LABEL = {
  reality: "실사 장면",
  mechanism: "원리 도해",
  text_card: "글자 카드",
  other: "기타",
} as const;

export const PAGE_ROLE_LABEL = {
  cover: "표지",
  explain: "설명",
  compare: "비교",
  checklist: "체크리스트",
  source: "출처",
} as const;

// ── 점수(명세 §6.3, rubric drinks-v1) ──

export const RUBRIC_VERSION = "drinks-v1";
/** 편성 후보 표시 기준. 자동 발주·발행 문턱이 아니다. 미만은 예외 사유가 있어야 편성된다(DB 가 검사). */
export const SELECT_THRESHOLD = 65;
/** 형식별 적합성이 이 값 미만이면 경고 — 그 형식으로 편성하려면 형식 예외 사유가 필요하다(정책 ①, DB drinks_select). */
export const FORMAT_FIT_MIN = 2;

export const SCORE_AXES = [
  { key: "relevance", label: "애호가 관련성", weight: 25, low: "분야와 동떨어짐", high: "실제 선택·이해·경험에 직접 연결" },
  { key: "utility", label: "저장할 효용", weight: 25, low: "감상만 남음", high: "반복해서 쓸 판단 기준 제공" },
  { key: "curiosity", label: "발견·궁금증", weight: 20, low: "질문과 발견 없음", high: "익숙한 대상에 구체적인 새 관점" },
  { key: "fit_video", label: "영상 적합성", weight: 0, low: "영상으로 설명 불가", high: "영상으로 명확히 설명" },
  { key: "fit_carousel", label: "카드뉴스 적합성", weight: 0, low: "카드로 설명 불가", high: "카드로 명확히 설명" },
  { key: "timeliness", label: "지금 다룰 이유", weight: 10, low: "현재 편성과 연결 약함", high: "시기·질문 수요·연재 공백에 적합" },
] as const;
export type ScoreKey = (typeof SCORE_AXES)[number]["key"];
export type Scores = Partial<Record<ScoreKey, number>>;
/** 형식 적합성 축(두 형식 중 높은 값)의 비중. */
export const FORMAT_FIT_WEIGHT = 20;

/** 0~100. 축이 하나라도 비거나 숫자가 아니면 null(0점으로 채우지 않는다). */
export function weightedScore(s: Record<string, unknown> | null | undefined): number | null {
  if (!s) return null;
  for (const a of SCORE_AXES) if (typeof s[a.key] !== "number") return null;
  const n = (k: ScoreKey) => s[k] as number;
  const total =
    (25 * n("relevance")) / 4 +
    (25 * n("utility")) / 4 +
    (20 * n("curiosity")) / 4 +
    (FORMAT_FIT_WEIGHT * Math.max(n("fit_video"), n("fit_carousel"))) / 4 +
    (10 * n("timeliness")) / 4;
  return Math.round(total * 100) / 100;
}

export function fitOk(scores: Scores | null | undefined, f: Format): boolean {
  const v = scores?.[f === "video" ? "fit_video" : "fit_carousel"];
  return typeof v === "number" && v >= FORMAT_FIT_MIN;
}

// ── 차단 사유·경고(DB drinks_review_blockers 의 코드) ──

const BLOCKER_TEXT: Record<string, string> = {
  scores_incomplete: "5축 점수가 다 채워지지 않았습니다",
  brief_question_missing: "공통 기획에 독자 질문이 없습니다",
  brief_takeaway_missing: "공통 기획에 핵심 결론이 없습니다",
  no_core_claims: "핵심 주장을 하나 이상 고르세요",
  unknown_claim: "핵심 주장 목록에 없는 주장이 들어 있습니다",
  no_proposed_format: "제안 형식(영상·카드뉴스)을 하나 이상 고르세요",
  required_claims_missing: "이 형식이 반드시 전달할 필수 주장을 고르지 않았습니다",
  required_claim_not_core: "필수 주장에 핵심 주장이 아닌 것이 들어 있습니다",
  opinion_unattributed: "주관 평가에 누구의 평가인지(귀속)가 없습니다",
  claim_no_source: "근거 출처가 연결되지 않았습니다",
  claim_metadata_only: "URL만 있고 본문·발췌가 없는 출처뿐입니다",
  claim_quote_unmatched: "발췌가 원문에서 확인되지 않았습니다",
  claim_rights_unconfirmed: "발췌를 쓸 수 있는지(사용 조건) 확인되지 않았거나 권리가 철회됐습니다",
  claim_conflicting: "출처끼리 충돌합니다",
  claim_insufficient: "발췌가 주장을 충분히 뒷받침하지 못합니다",
  claim_support_not_reviewed: "발췌가 주장을 뒷받침하는지 아직 검토하지 않았습니다",
  claim_time_scope_missing: "가격·재고·행사 정보에 유효 기한·시장(지역)이 없습니다",
  claim_expired: "유효 기한이 지났습니다 — 원문을 다시 확인하세요",
  // 경고(차단 아님)
  format_fit_low: "형식 적합성이 2점 미만입니다 — 편성하려면 형식 예외 사유가 필요합니다",
  comparison_origin_unconfirmed: "비교 주장의 독립 원출처가 확인되지 않았습니다(운영자가 묶음을 확인한 원출처 2개 미만)",
};

const FORMAT_CODES = new Set(["required_claims_missing", "required_claim_not_core", "format_fit_low"]);

export function blockerLabel(code: string): string {
  const i = code.indexOf(":");
  const base = i < 0 ? code : code.slice(0, i);
  const arg = i < 0 ? "" : code.slice(i + 1);
  const text = BLOCKER_TEXT[base] ?? base;
  if (!arg) return text;
  if (FORMAT_CODES.has(base)) return `[${FORMAT_LABEL[arg as Format] ?? arg}] ${text}`;
  return `[${arg}] ${text}`;
}

/**
 * 출처 수 / 확인된 독립 원출처 수 / 묶음 미확인 수(정책 ②). 독립 원출처는 운영자가 묶음(origin_group)을
 * 정한 것만 센다 — 묶음이 없는 출처는 "독립인지 모름"이지 독립이 아니다.
 */
export function originSummary(snaps: { id: string; origin_group: string | null }[]) {
  const grouped = snaps.filter((s) => s.origin_group);
  return {
    total: snaps.length,
    confirmedGroups: new Set(grouped.map((s) => s.origin_group)).size,
    unconfirmed: snaps.length - grouped.length,
  };
}

export const ATTEST_KIND_LABEL = {
  rights_confirmed: "사용 조건 확인",
  recheck: "원문 재확인(변경 없음)",
  correction: "정보 정정",
  rights_revoked: "권리 철회·사용 불가",
} as const;
export type AttestKind = keyof typeof ATTEST_KIND_LABEL;

/** 기록 종류별로 바꿀 수 있는 칸(DB drinks_attest_source 와 같은 목록). */
export const ATTEST_FIELDS: Record<AttestKind, string[]> = {
  rights_confirmed: ["rights_status", "usage_terms", "checked_at"],
  recheck: ["checked_at"],
  correction: ["title", "publisher", "published_at", "original_language", "excerpt_locator", "usage_terms", "checked_at"],
  rights_revoked: ["rights_status", "usage_terms"],
};

const META_KEYS = ["title", "publisher", "published_at", "checked_at", "original_language", "excerpt_locator",
  "rights_status", "usage_terms"] as const;

/** 스냅샷 값 위에 정정·재확인 기록을 시간순으로 덮은 유효 정보(SQL drinks_snapshot_meta 와 같은 규칙). */
export function effectiveMeta(
  snap: Partial<Record<(typeof META_KEYS)[number], string | null | undefined>>,
  attestations: { fields: Record<string, string | null>; seq: number | string }[]
): Record<(typeof META_KEYS)[number], string | null> & { attestationCount: number } {
  const out = Object.fromEntries(META_KEYS.map((k) => [k, snap[k] ?? null])) as Record<(typeof META_KEYS)[number], string | null>;
  // 적용 순서는 기록 순번(seq) — 시각·UUID 는 같은 트랜잭션 안에서 순서를 보장하지 못한다(SQL 과 같은 규칙).
  const sorted = [...attestations].sort((a, b) => Number(a.seq) - Number(b.seq));
  for (const a of sorted) for (const k of META_KEYS) if (k in a.fields) out[k] = a.fields[k] ?? null;
  return { ...out, attestationCount: sorted.length };
}

// ── 제작안의 근거 전달(DB drinks_plan_item_is_fact / drinks_plan_coverage 와 같은 규칙) ──
// ★ 주장이 연결됐다는 것은 "근거 범위 안에서 말한다"는 표시일 뿐이다. 문장이 사실과 맞는지는 사람이 검토한다.

export function isFactItem(format: Format, item: { role?: string; content_kind?: string }): boolean {
  if (format === "carousel") return ["explain", "compare", "checklist"].includes(item.role ?? "");
  return (item.content_kind ?? "fact") === "fact";
}

export interface Coverage {
  required: string[];
  /** 사실 항목에 연결된 주장 — 필수 주장 "전달"은 이것으로만 센다 */
  covered: string[];
  /** 표지·출처·전환에만 붙은 주장(참고 연결, 전달로 치지 않음) */
  reference_only: string[];
  missing_required: string[];
  facts_without_claims: number[];
  required_defined: boolean;
  ok: boolean;
}

export function planCoverage(
  format: Format,
  items: { role?: string; content_kind?: string; claim_ids?: string[] }[],
  required: string[]
): Coverage {
  const used = new Set<string>();
  const ref = new Set<string>();
  const noClaim: number[] = [];
  items.forEach((it, i) => {
    const ids = (it.claim_ids ?? []).filter(Boolean);
    if (isFactItem(format, it)) {
      if (ids.length === 0) noClaim.push(i + 1);
      ids.forEach((x) => used.add(x));
    } else {
      // 표지·출처·전환에 붙은 주장은 참고 연결 — 필수 주장 전달로 세지 않는다(SQL drinks_plan_coverage 와 같은 규칙)
      ids.forEach((x) => ref.add(x));
    }
  });
  const req = [...new Set(required)].sort();
  const missing = req.filter((x) => !used.has(x));
  return {
    required: req,
    covered: [...used].sort(),
    reference_only: [...ref].filter((x) => !used.has(x)).sort(),
    missing_required: missing,
    facts_without_claims: noClaim,
    required_defined: req.length > 0,
    ok: req.length > 0 && missing.length === 0 && noClaim.length === 0,
  };
}

// ── 조회 결과: 실패와 정상 0건을 구별한다(§10 completeness) ──

export type Loaded<T> =
  | { state: "ok"; data: T; truncated?: boolean }
  | { state: "failed"; error: string }
  | { state: "unconfigured" };

export function fromQuery<T>(
  res: { data: T | null; error: { message: string } | null },
  label: string
): Loaded<T> {
  if (res.error) return { state: "failed", error: `${label}: ${res.error.message}` };
  if (res.data === null) return { state: "failed", error: `${label}: 응답이 비었습니다` };
  return { state: "ok", data: res.data };
}

// ── 다음 행동(명세 §9.2: 주 버튼은 상태에서 계산하는 하나) ──

export interface NextActionInput {
  status: TopicStatus;
  /** 작업 중인 최신 버전(초안일 수 있다) */
  reviewStatus: VersionStatus | null;
  reviewRevoked: boolean;
  reviewBlockers: number;
  /** 가장 최근 승인 버전을 **지금** 쓸 수 있는가(철회 안 됨 + 현재 필수 조건 통과). 정책 ③: 새 초안이 있어도 이 승인으로 편성할 수 있다. */
  approvalValid: boolean;
  /** 편성에 쓴 근거 버전을 지금 쓸 수 있는가(편성된 소재만 의미 있음). */
  selectedValid?: boolean;
  selectedFormats: Format[];
  /**
   * 형식별 현재 제작안 상태. 없으면 null. blocked=근거 철회·사용 불가로 차단됨.
   * evidenceValid = 그 제작안 **자신이 참조하는** 근거 버전을 지금 쓸 수 있는가(편성 버전과 다를 수 있다 — 정책 ③).
   */
  plans: Partial<Record<Format, { status: VersionStatus; blocked: boolean; evidenceValid: boolean } | null>>;
}

export interface NextAction {
  label: string;
  tab: "overview" | "evidence" | "brief" | Format | "history";
  hint: string;
  /** 지금 실행할 수 없는 행동. 화면은 버튼을 잠그고 이유를 보여준다(2026-10-28 기준 해당 행동 없음 — 제작이 연결됐다). */
  unavailable?: boolean;
}

export function nextAction(v: NextActionInput): NextAction {
  switch (v.status) {
    case "inbox":
      return { label: "경량 평가", tab: "overview", hint: "5축 점수로 조사할 가치가 있는지 먼저 매깁니다(근거 검증과 무관한 임시 점수)." };
    case "triaged":
      return { label: "조사하기", tab: "overview", hint: "조사 후보로 고르면 근거·기획을 작성할 수 있습니다." };
    case "on_hold":
    case "rejected":
    case "duplicate":
      return { label: "다시 열기", tab: "overview", hint: "보류·제외·중복 처리된 소재입니다. 다시 열면 이전 단계로 돌아갑니다." };
    case "researching":
    case "ready": {
      const also = v.status === "ready" ? " (지금 승인된 버전으로 편성할 수도 있습니다)" : "";
      if (v.reviewStatus === "draft") {
        return v.reviewBlockers > 0
          ? { label: "근거 검토", tab: "evidence", hint: `편성 전 필수 조건 ${v.reviewBlockers}개가 남았습니다.${also}` }
          : { label: "기획 검토 요청", tab: "brief", hint: `근거·공통 기획을 검토에 올립니다.${also}` };
      }
      if (v.reviewStatus === "in_review") return { label: "기획 승인", tab: "brief", hint: `서버가 필수 조건을 다시 검사한 뒤 승인합니다.${also}` };
      if (v.status === "ready" && v.approvalValid) {
        return { label: "편성", tab: "brief", hint: "형식(영상·카드뉴스)과 편성 주차를 정합니다. 편성은 제작을 시작하지 않습니다." };
      }
      if (v.reviewStatus === "changes_requested") return { label: "새 버전 작성", tab: "evidence", hint: "변경 요청을 반영해 새 버전을 만듭니다." };
      if (!v.reviewStatus) return { label: "근거 작성", tab: "evidence", hint: "출처를 붙이고 핵심 주장마다 발췌와 지지 여부를 기록합니다." };
      return { label: "새 버전 작성", tab: "evidence", hint: "승인이 철회됐거나 필수 조건이 다시 깨졌습니다 — 유효한 근거로 새 버전을 만드세요." };
    }
    case "selected": {
      if (v.selectedValid === false) {
        return { label: "근거 재확인", tab: "evidence", hint: "편성에 쓴 근거가 지금 필수 조건을 만족하지 않습니다(사용 조건·유효 기한) — 제작안 승인이 막힙니다. 근거를 고쳐 새 버전으로 검토하세요." };
      }
      for (const f of v.selectedFormats) {
        const p = v.plans[f];
        const name = FORMAT_LABEL[f];
        if (!p || p.blocked) return { label: `${name} 제작안 작성`, tab: f, hint: p?.blocked ? "근거 철회로 차단됐습니다 — 유효한 근거로 새 버전을 만드세요." : "대본·장면 또는 페이지 구성을 입력합니다." };
        // 승인됐더라도 그 제작안이 쓴 근거를 지금 쓸 수 없으면(기간 만료 등) "모두 승인"으로 안내하지 않는다.
        if (!p.evidenceValid) return { label: `${name} 근거 재확인`, tab: f, hint: "이 제작안이 쓴 근거 버전을 지금은 쓸 수 없습니다(사용 조건·유효 기한) — 유효한 근거로 새 제작안 버전을 만드세요." };
        if (p.status === "draft") return { label: `${name} 제작안 검수`, tab: f, hint: "작성한 제작안을 검토에 올립니다." };
        if (p.status === "in_review") return { label: `${name} 제작안 승인`, tab: f, hint: "근거 버전·필수 주장 전달을 서버가 다시 확인합니다." };
        if (p.status === "changes_requested") return { label: `${name} 새 제작안`, tab: f, hint: "변경 요청을 반영해 새 버전을 만듭니다." };
      }
      // 제작안이 모두 승인되면 다음은 제작 화면(로컬 렌더 → 파일 검수 → 발행안). 렌더·검수 진행 상황은 그 화면이 보여 준다.
      return {
        label: "렌더·검수",
        tab: v.selectedFormats[0] ?? "brief",
        hint: "제작안이 모두 승인됐습니다. 제작 화면에서 로컬 렌더(무료) → 파일 검수 → 발행안 작성으로 이어 갑니다.",
      };
    }
  }
}

/** 작업함 정렬: 사람이 지금 할 수 있는 일이 앞, 막힌 일·끝난 일이 뒤. */
export function actionRank(a: NextAction, status: TopicStatus): number {
  if (a.unavailable) return 6;
  if (a.label.endsWith("근거 재확인")) return 0;
  if (status === "on_hold" || status === "rejected" || status === "duplicate") return 7;
  if (a.label.endsWith("승인")) return 0;
  if (a.label.endsWith("검수") || a.label === "기획 검토 요청") return 1;
  if (status === "selected") return 2;
  if (status === "ready") return 3;
  if (status === "researching") return 4;
  return 5;
}

export interface TopicDerived {
  /** 작업 중인 최신 버전 */
  review: ReviewRow | null;
  /** 가장 최근 승인 버전(철회됐을 수 있다) */
  approvedReview: ReviewRow | null;
  approvalValid: boolean;
  /** 편성에 쓴 버전을 지금 쓸 수 있는가 */
  selectedValid: boolean;
  selectedReview: ReviewRow | null;
  plans: Partial<Record<Format, PlanRow | null>>;
  action: NextAction;
  rank: number;
  /** 편성 평가 점수: 승인 버전 → 없으면 작업 중 버전. 없으면 null — provisional 과 섞지 않는다. */
  finalScore: number | null;
  provisionalScore: number | null;
  /** 형식 적합성 표시에 쓸 점수: 승인 → 작업 중 → 경량 평가 */
  fitScores: Scores | null;
  /** 포인터는 있는데 조회 결과에 그 행이 없다 — "없음"이 아니라 조회 누락 */
  missingPointers: string[];
  /** 형식별 현재 제작안이 **자신이 참조하는** 근거를 지금 쓸 수 있는가(제작안 없으면 키 없음). 모든 화면이 이 판정 하나를 쓴다. */
  planEvidenceValid: Partial<Record<Format, boolean>>;
}

const num = (v: number | string | null | undefined): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

const hasScores = (r: ReviewRow | null) => Boolean(r?.scores && Object.keys(r.scores).length > 0);

export function deriveTopic(
  t: TopicRow,
  reviews: Map<string, ReviewRow>,
  deliverables: DeliverableRow[],
  plans: Map<string, PlanRow>
): TopicDerived {
  const missing: string[] = [];
  const pick = <T,>(id: string | null, m: Map<string, T>, label: string): T | null => {
    if (!id) return null;
    const v = m.get(id);
    if (!v) missing.push(label);
    return v ?? null;
  };
  const review = pick(t.current_review_id, reviews, "현재 근거·기획 버전");
  const approvedReview = pick(t.approved_review_id, reviews, "승인 버전");
  const selectedReview = pick(t.selected_review_id, reviews, "편성 버전");
  const fmtPlans: Partial<Record<Format, PlanRow | null>> = {};
  for (const d of deliverables) {
    if (d.topic_id !== t.id) continue;
    fmtPlans[d.format] = pick(d.current_revision_id, plans, `${FORMAT_LABEL[d.format]} 현재 제작안`);
  }
  // 승인 기록(status·revoked_at)만 보지 않는다 — 지금 판정(currently_valid, DB 뷰 drink_review_validity)을 쓴다.
  const nowValid = (r: ReviewRow | null) =>
    Boolean(r && r.status === "approved" && !r.revoked_at && r.currently_valid === true);
  const approvalValid = nowValid(approvedReview);
  const selectedValid = nowValid(selectedReview);
  const selectedFormats = t.status === "selected" ? t.selected_formats ?? [] : [];
  const action = nextAction({
    status: t.status,
    reviewStatus: review?.status ?? null,
    reviewRevoked: Boolean(review?.revoked_at),
    reviewBlockers: review?.readiness?.blockers?.length ?? 0,
    approvalValid,
    selectedValid: t.status === "selected" ? selectedValid : undefined,
    selectedFormats,
    plans: Object.fromEntries(
      selectedFormats.map((f) => {
        const p = fmtPlans[f];
        if (!p) return [f, null];
        // 제작안이 참조하는 근거 행이 없으면 유효하다고 추정하지 않는다 — 조회 누락으로 센다.
        const pr = reviews.get(p.topic_review_id);
        if (!pr) missing.push(`${FORMAT_LABEL[f]} 제작안의 근거 버전`);
        return [f, { status: p.plan_status, blocked: Boolean(p.blocked_at), evidenceValid: nowValid(pr ?? null) }];
      })
    ),
  });
  const scoreSource = approvalValid ? approvedReview : review;
  return {
    review,
    approvedReview,
    approvalValid,
    selectedValid,
    selectedReview,
    plans: fmtPlans,
    action,
    rank: actionRank(action, t.status),
    finalScore: num(scoreSource?.score),
    provisionalScore: num(t.provisional_score),
    fitScores: hasScores(scoreSource) ? scoreSource!.scores : hasScores(review) ? review!.scores : t.provisional_scores,
    missingPointers: missing,
    planEvidenceValid: Object.fromEntries(
      (Object.keys(fmtPlans) as Format[]).filter((f) => fmtPlans[f]).map((f) => [f, nowValid(reviews.get(fmtPlans[f]!.topic_review_id) ?? null)])
    ),
  };
}

/** 편성 주차 기본값: 다음 주 월요일(YYYY-MM-DD). today 는 Asia/Seoul 기준 날짜 문자열. */
export function nextMonday(today: string): string {
  const [y, m, d] = today.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const dow = dt.getUTCDay() || 7;
  dt.setUTCDate(dt.getUTCDate() + (8 - dow));
  return dt.toISOString().slice(0, 10);
}

// ── 기계 검사(qa_summary) 표시 ────────────────────────────────────────────────
// 릴스 규격 문턱 — engine/config.py DRINKS_REEL_SPEC 와 같은 값이다(바꾸면 양쪽을 함께 바꾼다).
export const DRINKS_REEL_SPEC = {
  audio_sample_rate_max: 48000, min_sec: 3, max_sec: 900, max_width: 1920,
  fps_range: [23, 60] as readonly [number, number], video_codecs: ["h264", "hevc"] as readonly string[], audio_codec: "aac",
  cover_mime: "image/jpeg",
} as const;

/** 기계 검사 경고 코드 → 쉬운 한국어 한 줄. 모르는 코드는 코드 그대로 보인다(qaWarningLabel). */
export const QA_WARNING_KO: Record<string, string> = {
  not_vertical_1080x1920: "화면이 세로 1080×1920 이 아님",
  narration_silent: "나레이션 소리가 거의 없음",
  narration_silent_scenes: "나레이션이 비어 있는 장면이 있음",
  text_truncated: "화면 글자가 잘렸음",
  glyph_missing: "폰트에 없는 글자가 있어 네모(□)로 보일 수 있음",
  reel_audio_rate_over_48k: "소리 샘플링이 48 kHz 를 넘어 인스타가 거부할 수 있음",
  reel_moov_not_first: "파일 앞부분에 재생 정보(moov)가 없어 인스타 업로드가 실패할 수 있음",
  reel_duration_out_of_range: "영상 길이가 릴스 허용 범위(3~900초) 밖",
  reel_width_over_1920: "가로 해상도가 1920 을 넘음",
  reel_fps_out_of_range: "초당 프레임 수가 23~60 범위 밖",
  reel_video_codec: "영상 코덱이 H.264/HEVC 가 아님",
  reel_audio_codec: "소리 코덱이 AAC 가 아님",
  reel_file_too_big: "파일이 너무 커서 업로드가 거부될 수 있음",
  reel_cover_not_jpeg: "표지 이미지가 JPEG 가 아님",
  reel_cover_too_big: "표지 이미지 용량이 너무 큼",
  script_check_blocked: "대본 검사에서 막힌 문장이 있음",
  script_check_warned: "대본 검사에서 확인할 문장이 있음",
  speech_rate_fast: "말이 너무 빨라 알아듣기 어려울 수 있음",
  card_page_missing: "지정한 카드 페이지를 찾지 못해 대체 카드가 쓰임",
};

export function qaWarningLabel(code: string): string {
  return QA_WARNING_KO[code] ?? code;
}

export interface QaRow { label: string; value: string; ok: boolean | null }

const rec = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const strOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** 릴스 규격 표. 값이 없는 항목은 빼고(옛 행), 있는 항목만 ✔/✖(ok) 판정한다. */
export function reelSpecRows(qa: unknown): QaRow[] {
  const q = rec(qa);
  if (!q) return [];
  const probe = rec(q.probe);
  const spec = rec(q.reel_spec);
  const S = DRINKS_REEL_SPEC;
  const rows: QaRow[] = [];
  const w = numOrNull(probe?.width), h = numOrNull(probe?.height);
  if (w != null && h != null) rows.push({ label: "해상도", value: `${w}×${h}`, ok: w <= S.max_width && w === 1080 && h === 1920 });
  const dur = numOrNull(probe?.duration_sec);
  if (dur != null) rows.push({ label: "길이", value: `${dur.toFixed(1)}초`, ok: dur >= S.min_sec && dur <= S.max_sec });
  const fps = numOrNull(spec?.fps);
  if (fps != null) rows.push({ label: "프레임(fps)", value: String(Math.round(fps * 100) / 100), ok: fps >= S.fps_range[0] && fps <= S.fps_range[1] });
  const vc = strOrNull(spec?.video_codec);
  if (vc) rows.push({ label: "영상 코덱", value: vc, ok: S.video_codecs.includes(vc.toLowerCase()) });
  const ac = strOrNull(probe?.audio_codec) ?? strOrNull(spec?.audio_codec);
  if (ac) rows.push({ label: "소리 코덱", value: ac, ok: ac.toLowerCase() === S.audio_codec });
  const sr = numOrNull(spec?.audio_sample_rate);
  if (sr != null) rows.push({ label: "소리 샘플링", value: `${sr} Hz`, ok: sr <= S.audio_sample_rate_max });
  if (typeof spec?.moov_first === "boolean") rows.push({ label: "재생 정보(moov) 위치", value: spec.moov_first ? "파일 앞" : "파일 뒤", ok: spec.moov_first });
  const cm = strOrNull(spec?.cover_mime);
  if (cm) rows.push({ label: "표지 형식", value: cm, ok: cm === S.cover_mime });
  return rows;
}

export interface QaScriptIssue { code: string; scene: number | null; message: string }
const issues = (v: unknown): QaScriptIssue[] =>
  (Array.isArray(v) ? v : []).map(rec).filter((x): x is Record<string, unknown> => !!x)
    .map((x) => ({ code: String(x.code ?? ""), scene: numOrNull(x.scene), message: String(x.message ?? x.code ?? "") }));

export interface QaView {
  warnings: string[];
  reel: QaRow[];
  script: { ok: boolean | null; blocks: QaScriptIssue[]; warns: QaScriptIssue[] } | null;
  speech: { text: string; fast: boolean } | null;
  visual: { standIn: number[]; cardPages: number[]; generated: number[] } | null;
}

/** qa_summary(jsonb) → 화면용. 옛 행에는 새 키가 없으니 있는 것만 채운다. */
export function qaView(qa: unknown): QaView {
  const q = rec(qa) ?? {};
  const warnings = Array.isArray(q.warnings) ? q.warnings.filter((x): x is string => typeof x === "string") : [];
  const sc = rec(q.script_check);
  const sp = rec(q.speech_rate);
  const vs = rec(q.visual_source);
  const ints = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is number => typeof x === "number") : []);
  let speech: QaView["speech"] = null;
  const sps = numOrNull(sp?.syl_per_sec);
  if (sp && sps != null) {
    const speed = numOrNull(sp.playback_speed), rate = numOrNull(sp.tts_rate);
    const parts = [speed != null ? `재생 ${speed}×` : null, rate != null ? `TTS ${rate > 0 ? "+" : ""}${rate}%` : null].filter(Boolean);
    speech = { text: `${sps.toFixed(1)}음절/초${parts.length ? ` (${parts.join(", ")})` : ""}`, fast: warnings.includes("speech_rate_fast") };
  }
  return {
    warnings,
    reel: reelSpecRows(q),
    script: sc ? { ok: typeof sc.ok === "boolean" ? sc.ok : null, blocks: issues(sc.blocks), warns: issues(sc.warns) } : null,
    speech,
    visual: vs ? { standIn: ints(vs.stand_in), cardPages: ints(vs.card_pages), generated: ints(vs.generated) } : null,
  };
}
