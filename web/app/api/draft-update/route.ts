// POST /api/draft-update — 검수 화면에서 인라인 편집한 장면(scenes)을 drafts.video_prompts 에 저장.
// 표현·프롬프트만 사용자가 고치고, source_facts(근거 매핑)는 클라이언트가 그대로 되돌려보내 보존한다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

import { queueWriter } from "@/lib/supabase/admin";
import { requireOperator } from "@/lib/apiGuard";
interface SceneIn {
  scene?: unknown;
  title?: unknown;
  narration_ko?: unknown;
  narration_en?: unknown;
  duration_sec?: unknown;
  image_prompt?: unknown;
  image_prompt_ko?: unknown;
  video_prompt?: unknown;
  video_prompt_ko?: unknown;
  source_facts?: unknown;
}

export async function POST(request: Request) {
  // 공개 저장소 대비(2026-09-15): 쓰기 라우트는 전부 운영자 게이트를 맨 앞에서 통과한다.
  const denied = await requireOperator();
  if (denied) return denied;
  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  // 장면 편집(video_prompts 배열) 또는 발행 제목(upload_title_ko/en) 중 하나 이상이 있어야 한다.
  // 제목만 오는 단독 저장도 허용(발행 제목 인라인 편집).
  const hasScenes = Array.isArray(body?.video_prompts);
  const hasTitleKo = typeof body?.upload_title_ko === "string";
  const hasTitleEn = typeof body?.upload_title_en === "string";
  // ★ script_md 도 저장한다(2026-09-11, 통합 작업 화면). 예전에는 대본 편집이 승인 때
  //   published.final_script 로만 갔고 drafts.script_md 는 그대로였다 — 그래서 ④ 에서 고친
  //   문장이 ⑤ 지시서 생성기(drafts.script_md 를 읽는다)에 **한 번도 닿지 않았다.**
  const hasScript = typeof body?.script_md === "string";
  if (!body?.paper_id || (!hasScenes && !hasTitleKo && !hasTitleEn && !hasScript)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const { data: current } = await supabase
    .from("drafts")
    .select("paper_id")
    .eq("paper_id", body.paper_id)
    .maybeSingle();
  if (!current) return NextResponse.json({ error: "draft 없음" }, { status: 404 });

  // 온 필드만 부분 업데이트한다. 알려진 필드로만 정규화(임의 키로 스키마 오염 방지).
  const patch: Record<string, unknown> = {};
  let count: number | undefined;
  if (hasScenes) {
    const scenes = (body.video_prompts as SceneIn[]).map((s, i) => ({
      scene: Number(s?.scene) || i + 1,
      title: String(s?.title ?? ""),
      narration_ko: String(s?.narration_ko ?? ""),
      narration_en: String(s?.narration_en ?? ""),
      duration_sec: Number(s?.duration_sec) || 0,
      image_prompt: String(s?.image_prompt ?? ""),
      image_prompt_ko: String(s?.image_prompt_ko ?? ""),
      video_prompt: String(s?.video_prompt ?? ""),
      video_prompt_ko: String(s?.video_prompt_ko ?? ""),
      source_facts: Array.isArray(s?.source_facts) ? s.source_facts.map(String) : [],
    }));
    patch.video_prompts = scenes;
    count = scenes.length;
  }
  if (hasTitleKo) patch.upload_title_ko = String(body.upload_title_ko);
  if (hasTitleEn) patch.upload_title_en = String(body.upload_title_en);
  if (hasScript) patch.script_md = String(body.script_md);

  const { error } = await supabase
    .from("drafts")
    .update(patch)
    .eq("paper_id", body.paper_id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ ok: true, count });
}
