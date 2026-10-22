// POST /api/drinks — 주류 공장 A단계의 모든 쓰기. body: { action, payload }
//
// 동작 목록·URL 정규화·오류 변환은 lib/drinks/actions.ts, 상태 전이·소유 관계·동시 수정 검사는
// DB 함수(0050)가 한다. 이 라우트는 운영자 게이트 → service key rpc 연결만 한다.
// ★ 렌더·업로드·발행 큐(trigger-render / trigger-publish)를 import 하지 않는다 — 주류는 A단계에서
//   유료 생성·외부 발행 경로로 이어질 길이 없어야 한다(tests/test_drinks_phase_a_guards.py 가 감시).
import { NextResponse } from "next/server";

import { requireOperator } from "@/lib/apiGuard";
import { createAdminClient } from "@/lib/supabase/admin";
import { runDrinksAction } from "@/lib/drinks/actions";

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
  return NextResponse.json(res.body, { status: res.status });
}
