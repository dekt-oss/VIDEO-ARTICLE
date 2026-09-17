// POST /api/directive-update — 검수 화면에서 편집한 컷 배열 저장. body: { directive_id, cuts }
// total_estimated_sec 은 서버에서 컷 합으로 재계산해 header 를 갱신한다(원본 신뢰 안 함).
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

import { queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";
export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = await requireOperator();
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
  // ★ 시퀀스 편집(2026-09-17). 화면이 시퀀스 → 단계 → 컷 으로 바뀌면서 운영자가 세계 설정·
  //   단계 설명·컷 묶음을 그 자리에서 고친다. **보낸 경우에만** 덮어쓴다 — 안 보내면 그대로 둔다
  //   (옛 화면이나 다른 호출이 시퀀스를 지워 버리지 않게).
  //   ★★ 배열이 아니면 무시한다. 여기서 header 를 망가뜨리면 승인 게이트가 읽을 것을 잃는다.
  const header: Record<string, unknown> = { ...(current.header ?? {}), total_estimated_sec: total };
  if (Array.isArray(body.visual_sequences)) {
    header.visual_sequences = body.visual_sequences;
  }

  const { error } = await supabase
    .from("directives")
    .update({ cuts: body.cuts, header })
    .eq("id", body.directive_id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ ok: true, total_estimated_sec: total });
}
