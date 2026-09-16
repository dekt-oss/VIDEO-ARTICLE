// 비용·발행 라우트 게이트 (운영자 키). GPT 개선 지시서 SEC-01 의 대체안.
//
// ★ 왜 로그인이 아닌가: 0007_public_access.sql 이 "로그인 제거(운영자 요청)"으로 대시보드를
//   공개로 전환했다. 그 결정은 유지한다 — 매일 쓰는 흐름(낙점·검수·승인)에는 인증을 요구하지 않는다.
//   대신 **돈이 나가거나 외부로 발행되는 라우트만** 막는다:
//     - GitHub workflow_dispatch → 렌더 워커 → Veo/Gemini 유료 호출
//     - upload_requests 적재 → publish 워커(안전망 크론 하루 3번 + 버튼 디스패치) → 유튜브 업로드
//   0007 은 "데이터는 비민감"을 근거로 삼았지만, 그 뒤 비용 지출과 외부 발행이 anon 표면에 들어왔다.
//
// 동작: httpOnly 쿠키 va_op 의 토큰을 OPERATOR_KEY 파생 토큰과 상수시간 비교한다.
//   쿠키에 원본 키를 담지 않는다(파생 토큰만). 브라우저 JS 는 httpOnly 라 읽지 못한다.
//   OPERATOR_KEY 미설정이면 로컬 개발만 통과, 그 외엔 503(2026-09-15 fail-closed 로 전환).
import { createHash } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import {
  OPERATOR_COOKIE,
  OPERATOR_COOKIE_MAX_AGE,
  OPERATOR_TOKEN_PREFIX,
  safeEqual,
} from "./operatorConst";

// 상수는 lib/operatorConst.ts 가 단일 진실원이다(Edge 의 middleware.ts 와 공유).
// 기존 호출부가 여기서 import 하고 있으므로 그대로 re-export 한다.
export { OPERATOR_COOKIE, OPERATOR_COOKIE_MAX_AGE };

/**
 * 쿠키에 저장할 토큰. 원본 키가 쿠키·로그에 남지 않게 파생값만 쓴다.
 *
 * ★ middleware.ts 의 edgeOperatorToken() 과 **같은 값**을 내야 한다(런타임이 달라
 *   구현이 둘이다). 입력 규칙은 OPERATOR_TOKEN_PREFIX 한 곳에 있고,
 *   tests/operator-token.test.mjs 가 두 구현의 일치를 감시한다.
 */
export function operatorToken(key: string): string {
  return createHash("sha256").update(`${OPERATOR_TOKEN_PREFIX}${key}`).digest("hex");
}

/**
 * 현재 요청이 운영자 잠금해제 상태인지.
 *
 * ★ Next 15 (2026-09-16): `cookies()` 가 async 라 이 함수도 async 가 됐다.
 *   호출부(라우트 24곳)는 전부 async 핸들러라 `await` 한 단어만 붙는다.
 *   **await 를 빠뜨리면 Promise 가 truthy 라 게이트가 항상 통과한다** —
 *   그래서 tests/test_public_repo_guards.py 가 `await requireOperator()` 형태를 강제한다.
 */
export async function isOperator(): Promise<boolean> {
  const key = process.env.OPERATOR_KEY;
  // ★ 공개 저장소 대비(2026-09-15): 미설정이면 **막는다**(middleware.ts 와 같은 fail-closed).
  //   로컬 개발만 예외다. 종전엔 미설정 = 통과였고 middleware 와 반대라 한쪽이 빠지면 열렸다.
  if (!key) return process.env.NODE_ENV === "development";
  const got = (await cookies()).get(OPERATOR_COOKIE)?.value ?? "";
  return got.length > 0 && safeEqual(got, operatorToken(key));
}

/**
 * 비용·발행 라우트 맨 앞에서 호출한다. 통과면 null, 막히면 그대로 반환할 401 응답.
 *
 *   const denied = await requireOperator();
 *   if (denied) return denied;
 *
 * error 는 한국어 문장으로 준다 — 기존 호출부가 `e?.error` 를 토스트에 그대로 띄우므로
 * 클라이언트를 고치지 않아도 사용자가 다음 행동을 알 수 있다. code 는 UI 분기용.
 *
 * ★ `await` 필수(Next 15). 빠뜨리면 Promise 객체가 truthy 라 "항상 막힘"으로 보이고,
 *   반대로 isOperator() 를 await 없이 쓰면 "항상 통과"가 된다. 테스트가 형태를 감시한다.
 */
export async function requireOperator(): Promise<NextResponse | null> {
  if (!process.env.OPERATOR_KEY) {
    if (process.env.NODE_ENV === "development") return null;
    console.error("[apiGuard] OPERATOR_KEY 미설정 — 쓰기·비용·발행 라우트를 전부 막습니다(fail-closed).");
    return NextResponse.json(
      { error: "서버에 운영자 키가 설정돼 있지 않습니다.", code: "operator_unconfigured" },
      { status: 503 }
    );
  }
  if (await isOperator()) return null;
  return NextResponse.json(
    {
      error: "잠금 해제가 필요합니다 — /unlock 에서 운영자 키를 한 번 입력하세요(기기당 1회).",
      code: "operator_required",
    },
    { status: 401 }
  );
}
