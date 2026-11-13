// 발행안 캡션 자동 채움(2026-11-13, 운영자 지시 "캡션 자동으로 내용 넣어라").
// 승인된 글만 쓴다: 소재 제목 + 승인된 근거의 핵심 결론 + AI 표시 한 줄 + 술 종류 해시태그.
// 새 숫자·양·권고를 만들지 않아서 게시 직전 검사(drinks_script_check.check_caption)를 그대로 통과한다. 운영자는 고쳐 쓸 수 있다.
import type { Category } from "./model.ts";

const TAGS: Record<Category, string[]> = { sake: ["#사케", "#일본술"], traditional: ["#전통주", "#우리술"], whisky: ["#위스키"] };

export function autoCaption({ title, takeaway, categories, aiLabel }: {
  title: string; takeaway?: string | null; categories: readonly string[]; aiLabel?: string | null;
}): string {
  const tags = [...new Set(categories.flatMap((c) => TAGS[c as Category] ?? []))];
  return [title.trim(), takeaway?.trim(), aiLabel ? `※ ${aiLabel}` : null, tags.join(" ")].filter(Boolean).join("\n\n");
}
