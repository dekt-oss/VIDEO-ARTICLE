// POST /api/review-date — 배치일 확인 상태 토글. body: { batch_date | batch_dates[], reviewed }
// reviewed=true 면 batch_review 에 upsert(확인 완료), false 면 삭제(미확인으로 되돌림).
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
  const reviewed = body?.reviewed !== false; // 기본 true
  const isDate = (v: unknown): v is string =>
    typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);

  // batch_dates(여러 날) 우선, 없으면 batch_date(한 날) — 기존 호출부와 호환.
  const many: unknown = body?.batch_dates;
  const dates: string[] = Array.isArray(many)
    ? many.filter(isDate)
    : isDate(body?.batch_date)
      ? [body.batch_date]
      : [];
  if (dates.length === 0) {
    return NextResponse.json({ error: "invalid batch_date" }, { status: 400 });
  }
  const batchDate = dates[0];

  if (reviewed) {
    const { error } = await supabase
      .from("batch_review")
      .upsert(dates.map((d) => ({ batch_date: d })), { onConflict: "batch_date" });
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  } else {
    const { error } = await supabase
      .from("batch_review")
      .delete()
      .in("batch_date", dates);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, batch_date: batchDate, batch_dates: dates, count: dates.length, reviewed });
}
