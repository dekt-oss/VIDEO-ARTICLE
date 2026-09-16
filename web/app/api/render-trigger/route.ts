// POST /api/render-trigger — ⑥ "지금 렌더" 버튼. 큐에 쌓인 render_jobs 를 처리하도록
// 렌더 워커(GitHub Actions render.yml)를 즉시 트리거한다. 토큰 없으면 안내 메시지.
import { NextResponse } from "next/server";
import { triggerRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";

export async function POST() {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = requireOperator();
  if (denied) return denied;

  const trig = await triggerRender();
  if (trig.triggered) return NextResponse.json({ ok: true });
  const msg =
    trig.reason === "no_token"
      ? "렌더 자동 트리거 토큰(GITHUB_DISPATCH_TOKEN)이 설정되지 않았습니다. Vercel 환경변수에 추가하세요."
      : `트리거 실패: ${trig.reason ?? "unknown"}`;
  return NextResponse.json({ ok: false, error: msg }, { status: 503 });
}
