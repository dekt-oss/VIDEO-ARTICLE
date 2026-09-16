// POST /api/render-add-language — ⑥ 렌더 결과 화면의 "다른 언어 버전 추가 생성"(수정명세 v1 §2).
// body: { source_job_id: string, lang: 'ko' | 'en', force?: boolean }
//
// 같은 지시서(directive_id)로 언어만 다른 render_jobs 를 하나 더 만든다. 이미지·클립은
// render_assets 의 content_hash 캐시가 언어 독립이라 그대로 재사용되고(생성 API 호출 0),
// TTS·자막·타임라인만 언어별로 다시 계산된다(MODE A asset_reuse).
//
// ★ 두 언어의 총 길이는 다를 수 있다 — 컷 화면 시간이 나레이션 실측 길이이기 때문이다. 결함이 아니다.
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { triggerRender } from "@/lib/trigger-render";
import { requireOperator } from "@/lib/apiGuard";
import { queueWriter } from "@/lib/supabase/admin";

const LANGS = ["ko", "en"] as const;

export async function POST(request: Request) {
  // 비용·발행 라우트 — 운영자 키 게이트(web/lib/apiGuard.ts).
  const denied = await requireOperator();
  if (denied) return denied;

  const supabase = queueWriter(createClient());

  const body = await request.json().catch(() => null);
  const sourceJobId = body?.source_job_id;
  const lang = body?.lang;
  if (!sourceJobId || !LANGS.includes(lang)) {
    return NextResponse.json({ error: "invalid payload" }, { status: 400 });
  }

  const { data: source, error: sourceErr } = await supabase
    .from("render_jobs")
    .select("id, directive_id, status, lang")
    .eq("id", sourceJobId)
    .maybeSingle();
  // ★ 조회 **오류**와 **행 없음**을 구분해서 말한다. 예전에는 error 를 버리고
  //   무조건 "없음"이라고 답했다 — 마이그레이션 0037 이 안 올라간 DB 에서 이 select 가
  //   `degraded_approved_at` 컬럼 부재로 실패했는데, 화면에는 "잡 없음"이 떴다(실측
  //   2026-08-04, 유튜브 업로드 불가). 운영자가 존재하는 잡을 없다고 듣는 셈이라
  //   원인을 영원히 못 찾는다. 스키마·권한 오류는 그대로 드러낸다.
  if (sourceErr) {
    return NextResponse.json(
      { error: `렌더 잡 조회 실패: ${sourceErr.message}` },
      { status: 500 },
    );
  }
  if (!source) return NextResponse.json({ error: "render job 없음" }, { status: 404 });

  // 가드 1: 원본이 완료 상태여야 한다 — 미완료면 에셋 캐시가 불완전해 재생성 비용이 발생한다.
  if (source.status !== "done") {
    return NextResponse.json(
      { error: "원본 렌더가 완료(done)된 뒤에만 다른 언어를 추가할 수 있습니다(에셋 캐시 불완전)." },
      { status: 409 },
    );
  }
  if (source.lang === lang) {
    return NextResponse.json({ error: "원본과 같은 언어입니다." }, { status: 400 });
  }

  // 가드 2: 같은 (directive_id, lang) 조합에 완료된 잡이 이미 있으면 확인을 받는다.
  const { data: existing } = await supabase
    .from("render_jobs")
    .select("id")
    .eq("directive_id", source.directive_id)
    .eq("lang", lang)
    .eq("status", "done")
    .is("deleted_at", null)
    .limit(1);
  if (existing?.length && !body?.force) {
    return NextResponse.json(
      { error: "exists", message: `${lang.toUpperCase()} 버전이 이미 존재합니다. 재생성하시겠습니까?` },
      { status: 409 },
    );
  }

  const { data: created, error } = await queueWriter(supabase)
    .from("render_jobs")
    .insert({
      directive_id: source.directive_id,
      lang,
      source_job_id: source.id,
      status: "queued",
      progress: 0,
    })
    .select("id")
    .maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const trig = await triggerRender();
  return NextResponse.json({ ok: true, job_id: created?.id ?? null, rendering: trig.triggered });
}
