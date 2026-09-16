// POST /api/report-draft-update — 씬/대본 인라인 저장. api/draft-update(논문) 미러.
// body: { report_id, script_md?, scenes?, upload_title_ko?, upload_title_en? } (하나 이상 필요).
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

import { queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";
interface SceneIn {
  scene?: number;
  title?: string;
  narration_ko?: string;
  narration_en?: string;
  duration_sec?: number;
  image_prompt?: string;
  image_prompt_ko?: string;
  video_prompt?: string;
  video_prompt_ko?: string;
  source_facts?: string[];
}

function normScene(s: SceneIn, i: number) {
  return {
    scene: typeof s.scene === "number" ? s.scene : i + 1,
    title: String(s.title ?? ""),
    narration_ko: String(s.narration_ko ?? ""),
    narration_en: String(s.narration_en ?? ""),
    duration_sec: typeof s.duration_sec === "number" ? s.duration_sec : 0,
    image_prompt: String(s.image_prompt ?? ""),
    image_prompt_ko: String(s.image_prompt_ko ?? ""),
    video_prompt: String(s.video_prompt ?? ""),
    video_prompt_ko: String(s.video_prompt_ko ?? ""),
    source_facts: Array.isArray(s.source_facts) ? s.source_facts.map(String) : [],
  };
}

export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = await requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());
  const body = await request.json().catch(() => null);
  if (!body?.report_id) {
    return NextResponse.json({ error: "report_id required" }, { status: 400 });
  }

  const patch: Record<string, unknown> = {};
  if (Array.isArray(body.scenes)) patch.scenes = body.scenes.map(normScene);
  if (typeof body.script_md === "string") patch.script_md = body.script_md;
  if (typeof body.upload_title_ko === "string") patch.upload_title_ko = body.upload_title_ko;
  if (typeof body.upload_title_en === "string") patch.upload_title_en = body.upload_title_en;
  if (Object.keys(patch).length === 0) {
    return NextResponse.json({ error: "no fields to update" }, { status: 400 });
  }

  const { data: existing } = await supabase
    .from("report_drafts")
    .select("report_id")
    .eq("report_id", body.report_id)
    .maybeSingle();
  if (!existing) return NextResponse.json({ error: "draft not found" }, { status: 404 });

  const { error } = await supabase
    .from("report_drafts")
    .update(patch)
    .eq("report_id", body.report_id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ ok: true });
}
