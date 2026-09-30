// 옛 ⑤ 영상 지시서 목록 → 작업함의 [지시서 검수](2026-09-30 운영자 결정 2-1).
// ④⑤ 목록을 하나로 합쳤다. 옛 주소·북마크는 그대로 열리도록 넘기기만 한다(상세 /directive/[id] 는 그대로).
import { redirect } from "next/navigation";

export default function DirectiveListRedirect() {
  redirect("/review?stage=directive");
}
