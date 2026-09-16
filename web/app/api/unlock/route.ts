// POST /api/unlock — 운영자 키 1회 입력 → va_op 쿠키(180일) 설정. 비용·발행 라우트 게이트 해제.
// GET  /api/unlock — 현재 잠금해제 상태 조회(키 노출 없음).
// 근거·범위는 web/lib/apiGuard.ts 주석과 docs/deviation-cost-surface-guard.md.
import { NextResponse } from "next/server";
import {
  OPERATOR_COOKIE,
  OPERATOR_COOKIE_MAX_AGE,
  isOperator,
  operatorToken,
} from "@/lib/apiGuard";
import { safeEqual } from "@/lib/operatorConst";

// 오답 1회당 지연(ms). 서버리스 인스턴스마다 따로 걸리므로 병렬 대입을 완전히 막지는 못한다.
const UNLOCK_FAIL_DELAY_MS = 1500;

export async function GET() {
  return NextResponse.json({
    unlocked: await isOperator(),
    enabled: !!process.env.OPERATOR_KEY,
  });
}

export async function POST(request: Request) {
  const key = process.env.OPERATOR_KEY;
  if (!key) {
    // ★ 2026-09-15: 미설정은 "잠금해제 불필요"가 아니라 "설정 오류"다(fail-closed, middleware 와 같다).
    return NextResponse.json(
      { error: "서버에 운영자 키가 설정돼 있지 않습니다.", code: "operator_unconfigured" },
      { status: 503 }
    );
  }

  const body = await request.json().catch(() => null);
  const given = String(body?.key ?? "");
  if (!given) return NextResponse.json({ error: "키를 입력하세요." }, { status: 400 });
  // ★ 상수시간 비교(파생 토큰끼리) + 오답 지연. 레이트리밋 저장소가 없는 서버리스라
  //   완전한 차단은 아니다 — 무차별 대입의 속도를 늦추는 장치이고, 실제 방어는 긴 무작위 키다.
  if (!safeEqual(operatorToken(given), operatorToken(key))) {
    await new Promise((r) => setTimeout(r, UNLOCK_FAIL_DELAY_MS));
    // 오답을 구별해주지 않는다(길이·부분일치 힌트 없음).
    return NextResponse.json({ error: "키가 맞지 않습니다." }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true, unlocked: true });
  res.cookies.set(OPERATOR_COOKIE, operatorToken(key), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: OPERATOR_COOKIE_MAX_AGE,
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true, unlocked: false });
  res.cookies.set(OPERATOR_COOKIE, "", { path: "/", maxAge: 0 });
  return res;
}
