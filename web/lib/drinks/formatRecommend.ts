// 소재 후보의 형식 추천(0원 규칙) — 총괄계획 §2. 순수 함수. 값 import 없음(node --test).
//
// ★ 추천일 뿐이다. 운영자가 [이걸로]에서 바꿀 수 있고, 저장되는 것은 "의도"뿐이다(돈이 나가지 않는다). 막는 것은 DB 다.
// ★ 있는 자료로만 판단한다. 필요한 값을 못 읽었으면 추측하지 않고 unknown 과 그 이유를 돌려준다.
// ★ 근거 개수·글자 수는 "질문 낱말이 걸린 승인 수집원 글"을 대강 센 값이다(0064 drinks_candidate_evidence_counts). 진짜 판정은 근거 초안 단계의
//   글자 단위 인용 대조다 — 거기서 모자라면 evidence_insufficient 로 멈춘다.

/** engine/config.py DRINKS_FORMAT_* 와 같아야 한다(tests/test_drinks_develop.py 가 대조). 첫 값이고 운영자 선택 기록으로 고친다(§2). */
export const EXPLAINER_MIN_EVIDENCE = 2;
export const CARD_MIN_EVIDENCE = 1;
export const EXPLAINER_MIN_EVIDENCE_CHARS = 1200;
export const EVIDENCE_MAX_CANDIDATES = 50;
/** 스튜디오 목록이 근거를 찾아 넘겨 보는 최대 쪽 수(쪽마다 RPC 1회) — 후보가 쌓여도 페이지가 느려지지 않게. */
export const EVIDENCE_MAX_PAGES = 4;

export type FormatIntent = "explainer" | "card" | "meme";
export type Recommended = FormatIntent | "unknown";

export const FORMAT_INTENT_LABEL: Record<FormatIntent, string> = { explainer: "설명형", card: "카드뉴스", meme: "밈형" };
export const RECOMMENDED_LABEL: Record<Recommended, string> = { ...FORMAT_INTENT_LABEL, unknown: "추천 없음" };

export interface FormatInput {
  /** 어디서 온 후보인가. 소재 발견함 후보는 discovery, 트렌드 보드의 밈 카드는 meme_board */
  origin: "discovery" | "meme_board";
  /** 후보·소재의 질문 문장. 없으면 null */
  question: string | null;
  /** 후보 신호(0052): question·debate·misconception·selection·storage·new_product·event */
  signals: readonly string[] | null;
  /** 승인된 출처(수집원 + 공식 출처 목록)에서 걸린 글 수. 못 읽었으면 null */
  evidenceCount: number | null;
  /** 그 글들의 글자 수 합. 못 읽었으면 null */
  evidenceChars: number | null;
}

export interface Recommendation {
  format: Recommended;
  /** 운영자에게 보이는 쉬운 한국어 이유 */
  reason: string;
}

// 도수 높은 술은 "왜" 안 상하나, 트림이 나는 "원리" — 이유를 묻는 말. 영어는 발견 자료 원문이 영어일 때(Stack Exchange).
const WHY_PATTERN = /왜|이유|원리|어째서|why\b|how come|what causes|what makes/i;
// 저장해 둘 정보: 비교·보관·선택·이슈(§2 카드뉴스).
const CARD_SIGNALS = new Set(["selection", "storage", "new_product", "event"]);
const CARD_PATTERN = /차이|비교|보관|고르|추천|체크리스트|세금|규제|신제품|difference|compare|store|storage|which|recommend/i;

export type QuestionShape = "why" | "card" | "other" | "unknown";

/** 질문 유형. 문장과 신호가 모두 없으면 unknown. 왜·원리가 먼저다("고도주는 왜 안 상하나"는 보관 신호가 붙어도 원리를 묻는다). */
export function questionShape(question: string | null, signals: readonly string[] | null): QuestionShape {
  const q = question?.trim() ?? "";
  const sig = signals ?? [];
  if (!q && sig.length === 0) return "unknown";
  if (q && WHY_PATTERN.test(q)) return "why";
  if (sig.some((s) => CARD_SIGNALS.has(s)) || (q && CARD_PATTERN.test(q))) return "card";
  return "other";
}

export function recommendFormat(i: FormatInput): Recommendation {
  if (i.origin === "meme_board") {
    return { format: "meme", reason: "트렌드 보드의 밈 카드입니다. 농담이 기본이라 근거가 필요 없고, 정보를 말하면 근거 규칙을 그대로 탑니다." };
  }
  const shape = questionShape(i.question, i.signals);
  if (shape === "unknown") {
    return { format: "unknown", reason: "질문 문장과 신호가 없어 유형을 판단하지 못했습니다 — 형식을 직접 고르세요." };
  }
  if (shape === "other") {
    return { format: "unknown", reason: "왜·원리도, 비교·보관·선택·이슈도 잡히지 않았습니다 — 형식을 직접 고르세요." };
  }
  const what = shape === "why" ? "왜·원리를 묻는 질문입니다" : "저장해 둘 정보(비교·보관·선택·이슈)입니다";
  if (i.evidenceCount === null) {
    return { format: "unknown", reason: `${what}. 다만 근거 개수를 읽지 못해 추천하지 않습니다 — 형식을 직접 고르세요.` };
  }
  if (i.evidenceCount < CARD_MIN_EVIDENCE) {
    return {
      format: "unknown",
      reason: `${what}. 승인된 출처에서 걸린 글이 없어 어느 형식도 추천하지 않습니다 — 고르면 근거 초안 단계에서 부족 여부를 다시 잽니다.`,
    };
  }
  if (shape === "card") {
    return { format: "card", reason: `${what}. 승인된 출처에서 글 ${i.evidenceCount}개가 걸렸습니다.` };
  }
  if (i.evidenceCount < EXPLAINER_MIN_EVIDENCE) {
    return { format: "card", reason: `${what}. 그런데 걸린 글이 ${i.evidenceCount}개뿐이라(설명형은 ${EXPLAINER_MIN_EVIDENCE}개 이상) 카드뉴스로 내립니다.` };
  }
  if (i.evidenceChars === null) {
    return { format: "unknown", reason: `${what}. 걸린 글은 ${i.evidenceCount}개인데 분량을 읽지 못해 40초를 채울지 모릅니다 — 형식을 직접 고르세요.` };
  }
  if (i.evidenceChars < EXPLAINER_MIN_EVIDENCE_CHARS) {
    return {
      format: "card",
      reason: `${what}. 걸린 글 ${i.evidenceCount}개를 합쳐 ${i.evidenceChars.toLocaleString()}자라 40초 분량에 못 미칠 것 같아 카드뉴스로 내립니다.`,
    };
  }
  return { format: "explainer", reason: `${what}. 승인된 출처에서 글 ${i.evidenceCount}개(${i.evidenceChars.toLocaleString()}자)가 걸렸습니다.` };
}
