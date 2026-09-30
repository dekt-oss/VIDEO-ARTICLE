// 옛 ⑤ 리포트 지시서 목록 → 작업함의 [지시서 검수](2026-09-30 운영자 결정 2-1). 상세 /finance/directive/[id] 는 그대로.
import { redirect } from "next/navigation";

export default function FinanceDirectiveListRedirect() {
  redirect("/finance/review?stage=directive");
}
