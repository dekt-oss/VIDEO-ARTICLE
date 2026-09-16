// ⑤ 지시서 상세 — 단계형 작업공간(/review/[id]?step=5)으로 통합됐다.
//
// 왜 넘기나: 같은 ⑤ 를 하는 화면이 둘이었다. 이 옛 화면에는 단계 표시줄도, 버전×언어를
// 한 번에 발주하는 바(VersionOrderBar)도 없다. 그런데 상단 메뉴의 "⑤ 영상 지시서" →
// 목록 → 상세 동선이 **기능이 적은 이쪽**으로 사람을 데려왔다.
// 라우트는 남긴다(북마크·기존 링크) — 대신 새 화면으로 넘긴다.
import { redirect } from "next/navigation";

export default function DirectiveDetailRedirect({
  params,
  searchParams,
}: {
  params: { paperId: string };
  searchParams: { v?: string };
}) {
  const v = searchParams.v ? `&v=${encodeURIComponent(searchParams.v)}` : "";
  redirect(`/review/${params.paperId}?step=5${v}`);
}
