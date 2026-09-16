// 승인 차단 사유를 **컷에서 다시 계산**한다 (수정명세 §14-3, 결정 D-E4).
//
// ★ 왜 저장된 header.block_reasons 를 그대로 믿으면 안 되는가:
//   지시서 생성 시점에 계산된 값인데, 그 뒤 운영자가 ⑤ 화면에서 컷을 편집한다.
//   `/api/directive-update` 는 total_estimated_sec 만 갱신하고 block_reasons 는 건드리지 않으므로,
//   60초짜리(차단 없음)를 95초로 늘려도 저장된 값은 여전히 빈 배열이다 → 80초 하드 상한이 샌다.
//   같은 이유로 claim_ids 를 지워 커버리지를 깨도 통과한다.
//   그래서 승인 순간에 컷에서 다시 센다.
//
// ★ 차단은 **코드가 데이터로 확정하는 사유만**이다(D-E4). 범위확대·인과과장 같은 자기검증 LLM 의
//   판단은 경고로만 노출하고 승인을 막지 않는다 — 리포트 컴플라이언스 하드차단을 제거한 것과 같은 방침.
//
// ★ 이중관리: engine/directive.py:directive_block_reasons 의 미러다. 한쪽을 고치면 다른 쪽도.

import type { Cut, DirectiveHeader } from "@/lib/types";

// engine/config.py 와 동기화.
const CONTENT_MODE_HARD_MAX_SEC = 80;
const VEO_CLIP_MAX_TIER_SEC = 4;

export function approvalBlockReasons(
  header: Partial<DirectiveHeader> | null | undefined,
  cuts: Cut[] | null | undefined,
): string[] {
  const h = header ?? {};
  const rows = Array.isArray(cuts) ? cuts : [];
  const out = new Set<string>();

  // 원장·계획이 없는 레거시 지시서에는 Claim·길이 축이 돌지 않는다(과거 지시서 소급 차단 금지).
  const hasPlan = Boolean(h.content_mode);

  const total = rows.reduce((acc, c) => acc + (Number(c.estimated_sec) || 0), 0);
  if (hasPlan && total > CONTENT_MODE_HARD_MAX_SEC) out.add("over_max_duration");
  // ★★ series_split 은 **차단하지 않는다**(2026-09-03). 명세가 "분할 권고까지만"이라고
  //   정했는데(수정명세서_근거밀도_가변길이_v1 §8-2) 코드가 승인 차단으로 만들어 뒀고,
  //   실측에서 원장 있는 초안 10건이 **100%** 여기 걸렸다. 화면에 푸는 길도 없다.
  //   근거·되돌리는 법은 engine/content_mode.block_reasons 의 주석에 있다(정본).
  //   신호 자체는 남는다 — content_mode 는 헤더에 그대로 있고 화면이 "시리즈 분할 권고"로 보여준다.

  // 영상 예산: 컷에서 다시 센다(편집으로 영상 컷을 늘렸을 수 있다).
  const cp = h.cost_plan;
  if (cp) {
    const videoCuts = rows.filter((c) => c.motion_source === "video").length;
    const videoSec = videoCuts * VEO_CLIP_MAX_TIER_SEC;
    if (videoSec > (cp.max_video_generated_sec ?? 0)) out.add("video_budget_exceeded");
  }

  // 근거 커버리지: 필수 주장을 지불하는 컷이 실제로 남아 있는가.
  if (hasPlan) {
    const required = [h.primary_claim_id ?? "", ...(h.supporting_claim_ids ?? [])].filter(Boolean);
    if (required.length) {
      const covered = new Set<string>();
      for (const c of rows) for (const id of c.claim_ids ?? []) covered.add(id);
      if (required.some((id) => !covered.has(id))) out.add("missing_required_claims");
      if (h.primary_claim_id && !covered.has(h.primary_claim_id)) {
        out.add("primary_claim_not_covered");
      }
    }
  }
  // ★ 실사형 화면 계약(2026-08-29 리뷰 §4). engine/photo_contract.py 의 미러 — **사유 코드가
  //   같아야 한다**(tests/test_prompt_sync.py 가 목록 일치를 검사한다).
  //   여기서 다시 세는 이유는 위와 같다: 저장된 값은 운영자가 컷을 편집하면 낡는다.
  //   판단이 섞이는 항목(도해가 장식적인가)은 **웹에서 재계산하지 않는다** — 오탐이 나면
  //   운영자가 게이트 전체를 불신하게 된다. 그건 엔진이 생성 시점에 판정해 저장한 값을 쓴다.
  if (h.version_type === "photo") {
    for (const code of photoBlockReasons(h, rows)) out.add(code);
  }
  return [...out].sort();
}

// engine/photo_contract.py 의 어휘와 같은 뜻을 담는다(대소문자·복수형·동의어).
const FORBIDDEN_SCREEN =
  /(bar\s*charts?|pie\s*charts?|line\s*charts?|charts?|graphs?|plots?|dashboards?|infographics?|data\s+visuali[sz]ations?|axis|axes|x-axis|y-axis|legends?|gridlines?|tick\s*marks?|labell?ed|labels?|captions?|subtitles?|percentage\s*signs?|percent\s*signs?|scoreboards?|tickers?|spreadsheets?)/i;
const FORBIDDEN_NUMBER_ON_SCREEN =
  /(\d+\s*%|percent|numbers?\s+(?:on\s+screen|displayed|shown)|text\s+overlay)/i;
const SPOKEN_NUMBER =
  /\d+(?:[.,]\d+)?\s*(?:%|퍼센트|프로|배|명|건|개|억|조|만|천|원|달러|초|분|시간|년|개월|일)/;
// ★ EN 도 본다 — KO 만 검사하면 영어 나레이션에만 숫자를 두어 게이트를 우회할 수 있다
//   (Fable Review 2026-08-29). EN 영상도 같은 화면으로 렌더된다.
const SPOKEN_NUMBER_EN =
  // ★ 단어 경계는 단어 단위에만 붙인다 - % 뒤에 붙이면 15% 를 못 잡는다(Python 정본과 동일).
  /\d+(?:[.,]\d+)?\s*(?:%|(?:percent|percentage\s+points?|times|fold|people|participants?|patients?|subjects?|cases?|dollars?|won|billion|million|trillion|seconds?|minutes?|hours?|days?|weeks?|months?)\b)/i;
const NUMBER_OVERLAY_TYPES = ["number_punch", "source_card", "evidence_card", "stat", "caption"];
const PHOTO_MIN_CUTS = 8;
const PHOTO_CUT_SEC_MAX = 5;

/** 실사형에서 **편집으로 깨질 수 있는** 계약만 다시 센다. 코드는 Python 정본과 동일. */
export function photoBlockReasons(
  header: Partial<DirectiveHeader> | null | undefined,
  cuts: Cut[] | null | undefined,
): string[] {
  const h = header ?? {};
  const rows = Array.isArray(cuts) ? cuts : [];
  const out: string[] = [];
  if (!rows.length) return out;

  if (!String(h.hook_ko ?? "").trim()) out.push("photo_hook_missing");

  const roleless = rows.filter((c) => !String(c.visual_role ?? "").trim()).map((c) => c.cut_no);
  if (roleless.length) out.push(`photo_visual_role_missing:${roleless.slice(0, 6).join(",")}`);

  if (!rows.some((c) => c.visual_role === "MECHANISM")) out.push("photo_mechanism_missing");

  const text = (c: Cut) => `${c.visual_prompt ?? ""} ${c.motion_prompt ?? ""}`;
  const bad = rows
    .filter((c) => FORBIDDEN_SCREEN.test(text(c)) || FORBIDDEN_NUMBER_ON_SCREEN.test(text(c)))
    .map((c) => c.cut_no);
  if (bad.length) out.push(`photo_forbidden_screen_request:${bad.slice(0, 6).join(",")}`);

  const missingOverlay = rows
    .filter(
      (c) =>
        (SPOKEN_NUMBER.test(String(c.narration_ko ?? "")) ||
          SPOKEN_NUMBER_EN.test(String(c.narration_en ?? ""))) &&
        !(c.overlay_plan ?? []).some((o) => NUMBER_OVERLAY_TYPES.includes(String(o?.type ?? ""))),
    )
    .map((c) => c.cut_no);
  if (missingOverlay.length) {
    out.push(`photo_number_without_overlay:${missingOverlay.slice(0, 6).join(",")}`);
  }

  const totalSec =
    Number(h.total_estimated_sec) || rows.reduce((a, c) => a + (Number(c.estimated_sec) || 0), 0);
  const lo = Math.max(PHOTO_MIN_CUTS, Math.round(totalSec / PHOTO_CUT_SEC_MAX));
  if (rows.length < lo) out.push(`photo_cut_count_low:${rows.length}<${lo}`);

  return out;
}
