// POST /api/drinks — 주류 공장의 모든 쓰기. body: { action, payload }
//
// 동작 목록·URL 정규화·오류 변환은 lib/drinks/actions.ts, 상태 전이·소유 관계·동시 수정 검사는
// DB 함수(0050)가 한다. 이 라우트는 운영자 게이트 → service key rpc 연결만 한다.
// ★ 렌더·업로드·발행 큐(triggerRender·triggerDraft·trigger-publish)를 쓰지 않는다 — 주류는 유료 생성·외부 발행
//   경로로 이어질 길이 없어야 한다. 깨우는 워크플로는 수집 워커(drinks-collect.yml)·로컬·무료 제작 워커
//   (drinks-produce.yml)·소재 개발 워커(drinks-develop.yml) 셋뿐이다(tests/test_drinks_phase_a_guards.py 가 감시).
import { NextResponse } from "next/server";

import { requireOperator } from "@/lib/apiGuard";
import { createAdminClient } from "@/lib/supabase/admin";
import { runDrinksAction } from "@/lib/drinks/actions";
import { triggerWorkflow } from "@/lib/trigger-render";

export async function POST(request: Request) {
  const denied = await requireOperator();
  if (denied) return denied;
  // anon 폴백 없음: 주류 표는 anon 권한이 아예 없어서 폴백하면 엉뚱한 권한 오류만 난다.
  const admin = createAdminClient();
  if (!admin) {
    return NextResponse.json(
      { error: "서버에 SUPABASE_SERVICE_KEY 가 없어 저장할 수 없습니다.", code: "service_key_missing" },
      { status: 503 }
    );
  }
  const body = await request.json().catch(() => null);
  const res = await runDrinksAction((fn, p) => admin.rpc(fn, { p }), body);
  if (res.status === 200 && (body as { action?: unknown } | null)?.action === "request_run") {
    // 실행은 큐에 들어갔다. 토큰이 없으면 다음 일일 실행(KST 06:30)이 가져간다 — 화면이 그 사실을 보여준다.
    res.body.dispatch = await triggerWorkflow("drinks-collect.yml", null);
  }
  if (res.status === 200 && (body as { action?: unknown } | null)?.action === "request_render"
      && (res.body.result as { existing?: boolean } | undefined)?.existing !== true) {
    res.body.dispatch = await triggerWorkflow("drinks-produce.yml", null);
  }
  if (res.status === 200 && (body as { action?: unknown } | null)?.action === "request_develop"
      && (res.body.result as { existing?: boolean } | undefined)?.existing !== true) {
    // 소재 개발 워커(근거 초안·대본 초안). 토큰이 없으면 큐에만 남고 화면이 그 사실을 보여준다.
    res.body.dispatch = await triggerWorkflow("drinks-develop.yml", null);
  }
  return NextResponse.json(res.body, { status: res.status });
}
