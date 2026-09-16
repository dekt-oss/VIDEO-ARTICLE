// POST /api/directive-update — 검수 화면에서 편집한 컷 배열 저장. body: { directive_id, cuts }
// total_estimated_sec 은 서버에서 컷 합으로 재계산해 header 를 갱신한다(원본 신뢰 안 함).
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

import { queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";
export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  if (!body?.directive_id || !Array.isArray(body.cuts)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const { data: current } = await supabase
    .from("directives")
    .select("header, status")
    .eq("id", body.directive_id)
    .maybeSingle();
  if (!current) return NextResponse.json({ error: "directive 없음" }, { status: 404 });
  if (current.status !== "draft") {
    return NextResponse.json({ error: "승인/렌더된 지시서는 편집 불가" }, { status: 409 });
  }

  const total = body.cuts.reduce(
    (acc: number, c: { estimated_sec?: number }) => acc + (Number(c.estimated_sec) || 0),
    0,
  );
  const header = { ...(current.header ?? {}), total_estimated_sec: total };

  const { error } = await supabase
    .from("directives")
    .update({ cuts: body.cuts, header })
    .eq("id", body.directive_id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ ok: true, total_estimated_sec: total });
}
