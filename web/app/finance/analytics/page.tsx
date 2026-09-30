// 리포트 공장의 [성과] — 논문 공장과 같은 화면(두 공장 영상이 한 표에 나온다)을 /finance 주소로 연다.
// ★ 왜 따로 두나(2026-09-30): 공장 표시는 주소로 정한다(AppShell.factoryOf — /finance 면 리포트). 리포트 공장에서
//   /analytics 로 가면 위쪽이 "논문 공장"으로 바뀌어, 공장을 옮긴 것처럼 보였다. 화면은 그대로 다시 쓴다.
// ★ 세그먼트 설정(dynamic)은 Next 가 정적으로 읽으므로 다시 내보내지 않고 이 파일에 직접 적는다.
export const dynamic = "force-dynamic";
export { default } from "../../analytics/page";
