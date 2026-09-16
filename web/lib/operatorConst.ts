// 운영자 게이트의 **단일 진실원**. 런타임 중립(Node·Edge 양쪽에서 import 가능).
//
// ★ 왜 별도 파일인가: 토큰 파생 규칙이 두 런타임에 각각 구현돼 있다 —
//   lib/apiGuard.ts 는 Node 의 `node:crypto`, middleware.ts 는 Edge 의 Web Crypto.
//   둘이 **같은 값**을 내야 쿠키가 양쪽에서 통한다. 입력 문자열이 한쪽만 바뀌면
//   게이트가 조용히 깨지므로(잠금해제해도 계속 막힘), 그 문자열을 여기 한 곳에 둔다.
//   규칙을 바꾸려면 이 파일만 고치고, tests/operator-token.test.mjs 가 두 구현의
//   일치를 감시한다.

export const OPERATOR_COOKIE = "va_op";
export const OPERATOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 180; // 180일 — 기기당 1회 입력

/** 파생 토큰의 입력 접두사. 쿠키에 원본 키를 담지 않기 위한 것이다. */
export const OPERATOR_TOKEN_PREFIX = "va_op/v1:";

/** 게이트를 통과시키는 경로(잠금해제 자체와 정적 자산). 여기 없으면 전부 막힌다. */
export const OPERATOR_PUBLIC_PATHS = ["/unlock", "/api/unlock"];

/** 타이밍 공격 방어용 상수시간 비교(길이 차이는 비밀이 아니라 즉시 false). */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
