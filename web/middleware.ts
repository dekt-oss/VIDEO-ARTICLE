// 사이트 전체 비밀번호 게이트 (운영자 키).
//
// ★ 왜 필요한가: 0007_public_access.sql 이 로그인을 제거해 대시보드가 인터넷에 열려 있다.
//   지금까지는 주소를 아무도 몰라서 사실상 가려져 있었지만, 저장소를 public 으로 전환하면
//   주소가 문서·커밋에서 드러난다(docs/기획_레포_공개전환_v3.md A1).
//   lib/apiGuard.ts 는 **비용·발행 API 14개만** 막는다 — 페이지는 무방비였다.
//   이 미들웨어가 그 구멍을 덮는다.
//
// ★ 로그인이 아니다. 계정·이메일·매직링크가 없고, 키 하나를 기기당 1회 입력한다.
//   기존 /unlock 화면과 va_op 쿠키를 그대로 재사용하므로 이미 해제한 기기는 계속 통과한다.
//
// ★ Edge 런타임이라 node:crypto 를 못 쓴다. Web Crypto 로 apiGuard 와 **같은** 토큰을
//   만든다. 입력 규칙은 lib/operatorConst.ts 한 곳에 있고 테스트가 일치를 감시한다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  OPERATOR_COOKIE,
  OPERATOR_PUBLIC_PATHS,
  OPERATOR_TOKEN_PREFIX,
  safeEqual,
} from "@/lib/operatorConst";

/** apiGuard.operatorToken() 의 Edge 판. 같은 입력 → 같은 hex 를 내야 한다. */
async function edgeOperatorToken(key: string): Promise<string> {
  const data = new TextEncoder().encode(`${OPERATOR_TOKEN_PREFIX}${key}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // 잠금해제 화면과 그 API 는 열어 둔다 — 막으면 해제 자체가 불가능해진다.
  if (OPERATOR_PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }

  // 로컬 개발은 통과. 키 없이 npm run dev 가 막히면 개발이 불가능하다.
  if (process.env.NODE_ENV === "development") return NextResponse.next();

  const key = process.env.OPERATOR_KEY;

  // ★ fail-closed: 키가 없으면 막는다.
  //   apiGuard 는 점진 도입을 위해 미설정 시 통과시키지만, 여기는 반대다 —
  //   저장소가 public 이 된 뒤 키를 깜빡하면 대시보드가 통째로 공개되기 때문이다.
  //   이때 사용자는 /unlock 으로 가고, 그 화면이 GET /api/unlock 의 enabled:false 를
  //   읽어 "키 미설정" 상태를 그대로 보여준다(무한 루프 없음 — /unlock 은 위에서 통과).
  if (!key) return denied(request, pathname, search, "unconfigured");

  const got = request.cookies.get(OPERATOR_COOKIE)?.value ?? "";
  if (got.length > 0 && safeEqual(got, await edgeOperatorToken(key))) {
    return NextResponse.next();
  }
  return denied(request, pathname, search, "locked");
}

function denied(request: NextRequest, pathname: string, search: string, reason: string) {
  // API 는 리다이렉트하면 호출부가 HTML 을 JSON 으로 파싱하다 죽는다 — 401 을 준다.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      {
        error:
          reason === "unconfigured"
            ? "서버에 OPERATOR_KEY 가 설정돼 있지 않습니다. 배포 환경변수를 확인하세요."
            : "잠금 해제가 필요합니다 — /unlock 에서 운영자 키를 입력하세요(기기당 1회).",
        code: "operator_locked",
      },
      { status: 401 }
    );
  }
  const url = request.nextUrl.clone();
  url.pathname = "/unlock";
  url.search = `?next=${encodeURIComponent(`${pathname}${search}`)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // 정적 자산은 제외한다. 여기에 걸면 잠금 화면 자체의 CSS·폰트도 막혀 흰 화면이 된다.
  // ★ 공개 저장소 대비(2026-09-15): 확장자 제외(`.*\.(png|jpg…)$`)를 뺐다. 동적 페이지
  //   (`/review/[paperId]` 등)가 `/review/x.png` 로 들어오면 게이트를 건너뛰었다. 이 앱에는
  //   public/ 폴더가 없어 확장자로 서빙할 정적 파일이 없다 — CSS·폰트는 전부 _next/static 이다.
  //   제외 항목은 경로 경계까지 고정한다(`favicon.icoX` 같은 접두 우회 방지).
  matcher: ["/((?!_next/static/|_next/image$|favicon\\.ico$|robots\\.txt$).*)"],
};
