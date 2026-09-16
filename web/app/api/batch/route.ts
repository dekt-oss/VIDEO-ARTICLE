// GET /api/batch — 오늘(최신) daily_batch 후보 목록.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getCandidates, getLatestBatchDate } from "@/lib/queries";

export async function GET() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const batchDate = await getLatestBatchDate(supabase);
  if (!batchDate) return NextResponse.json({ batch_date: null, candidates: [] });

  const candidates = await getCandidates(supabase, batchDate);
  return NextResponse.json({ batch_date: batchDate, candidates });
}
