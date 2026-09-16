// POST /api/approve — 검수 완료 대본을 published 에 기록. body: { paper_id, final_script, platforms? }
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
  if (!body?.paper_id || typeof body.final_script !== "string") {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const { error } = await supabase.from("published").upsert(
    {
      paper_id: body.paper_id,
      final_script: body.final_script,
      platforms: body.platforms ?? null,
    },
    { onConflict: "paper_id" }
  );
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ ok: true });
}
