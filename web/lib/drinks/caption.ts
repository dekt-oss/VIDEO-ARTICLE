// 발행안 캡션 자동 채움(2026-11-13, 운영자 지시 "캡션 자동으로 내용 넣어라").
// 2026-11-18 운영자: "캡션 내용이 부실하고 술째리고 홍보 내용이 들어가야 할 듯" · "AI 생성 내용 왜 필수임?"
//   → 첫 질문(훅) + 답 + 술째리고 소개 + 해시태그. 'AI 생성 영상' 줄은 빼고(0088, 영상 화면에 AI 표시가 이미 나간다).
// 승인된 글만 쓴다. 소개 문구에는 숫자·양·권고(~해 보세요)를 넣지 않는다 — 게시 직전 검사(drinks_script_check.check_caption)를 그대로 통과해야 한다.
import type { Category } from "./model.ts";

const TAGS: Record<Category, string[]> = { sake: ["#사케", "#일본술"], traditional: ["#전통주", "#우리술", "#막걸리"], whisky: ["#위스키", "#싱글몰트"] };
const BRAND_TAGS = ["#술째리고", "#술추천", "#술정보"];

/** 술째리고 소개(모든 캡션 끝). 권고형 끝맺음(~세요)을 쓰지 않는다 — 게시 검사가 근거 없는 권고로 막는다. */
export const PROMO_LINES = [
  "🍶 술 고를 때 궁금한 이야기, 술째리고가 쉽게 풀어 드려요.",
  "🔎 같은 술 판매처별 가격 비교는 '술째리고' 앱에서 한눈에!",
  "📲 앱은 프로필 링크에서",
] as const;

/** title: 첫 줄(릴스는 첫 장면 질문, 카드는 제목) · takeaway: 답(릴스는 마지막 장면, 없으면 근거의 핵심 결론). */
export function autoCaption({ title, takeaway, categories }: { title: string; takeaway?: string | null; categories: readonly string[] }): string {
  const tags = [...new Set([...categories.flatMap((c) => TAGS[c as Category] ?? []), ...BRAND_TAGS])];
  const head = [title.trim(), takeaway?.trim()].filter(Boolean).join("\n");
  return [head, PROMO_LINES.join("\n"), tags.join(" ")].filter(Boolean).join("\n\n");
}
