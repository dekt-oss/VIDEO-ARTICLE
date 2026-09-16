// ⑤ 리포트 영상 지시서 — 단계형 작업공간(/finance/review/[id]?step=5)으로 통합됐다.
//
// 라우트는 없애지 않는다(북마크·목록 링크·기존 문서가 이 주소를 가리킨다). 대신 같은 편의
// ⑤ 단계로 넘긴다 — 화면이 둘로 나뉘어 있으면 "메뉴로 들어가 다음으로 넘어가는" 동선이
// 계속 남는다.
import { redirect } from "next/navigation";

export default async function FinanceDirectiveRedirect(props: {
  params: Promise<{ reportId: string }>;
  searchParams: Promise<{ v?: string }>;
}) {
  // ★ Next 15: params·searchParams 가 Promise 다. 본문을 건드리지 않으려고
  //   props 로 받아 맨 앞에서 await 해 같은 이름에 다시 묶는다.
  const [params, searchParams] = await Promise.all([props.params, props.searchParams]);
  const v = searchParams.v ? `&v=${encodeURIComponent(searchParams.v)}` : "";
  redirect(`/finance/review/${params.reportId}?step=5${v}`);
}
