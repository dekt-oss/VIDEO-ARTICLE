"""초안(drafts.video_prompts) → 지시서 매핑 → 로컬 mp4.

리뷰 페이지에서 확인한 장면 프롬프트를 LLM 재연출 없이 "있는 그대로" 렌더한다.
engine.directive(LLM 지시서 생성)와 달리 이 도구는 초안 scenes 를 결정론적으로 컷에 매핑만 한다
(프롬프트/나레이션/컷길이 = 초안 값 그대로). 빠른 확인·테스트용.

실행:
  IMAGE_PROVIDER=gemini TTS_PROVIDER=edge python -m engine.render_draft <paper_id> [ko|en]

필요:
  .env — SUPABASE_URL / SUPABASE_SERVICE_KEY (초안 조회), GEMINI_API_KEY (nano banana 이미지).
  IMAGE_PROVIDER=gemini 로 실제 이미지, 미설정(placeholder)이면 회색 스틸로 조립만 확인.
"""

from __future__ import annotations

import sys
from typing import Any

from . import config, db, render
from . import directive as dv
from .util import log

# 컷마다 다른 Ken Burns 로 정적 스틸에 모션을 준다(초안 video_prompt 의 카메라 의도 근사).
_KEN_BURNS = ["ken_burns_zoom_in", "pan_right", "ken_burns_zoom_out", "pan_left"]


def draft_to_directive(draft: dict[str, Any], version_type: str = "image_sequence") -> dict[str, Any]:
    """초안 scenes → 정규화된 지시서 dict. 프롬프트/나레이션/길이는 초안 값을 그대로 계승."""
    scenes = draft.get("video_prompts") or []
    cuts: list[dict[str, Any]] = []
    for i, s in enumerate(scenes if isinstance(scenes, list) else []):
        cuts.append({
            "cut_no": int(s.get("scene") or (i + 1)),
            "scene_kind": "broll_stock",
            "narration_ko": str(s.get("narration_ko") or ""),
            "narration_en": str(s.get("narration_en") or ""),
            "estimated_sec": int(s.get("duration_sec") or config.CUT_MIN_SEC),
            "visual_prompt": str(s.get("image_prompt") or ""),  # 리뷰 페이지의 그 프롬프트
            "effects": [_KEN_BURNS[i % len(_KEN_BURNS)]],
            "transition": "crossfade",
            "source_facts": s.get("source_facts") or [],
        })
    flow = draft.get("video_flow") or {}
    header = {
        "aspect_ratio": config.ASPECT_RATIO,
        "global_style": "",
        "hook_ko": str(flow.get("logline") or ""),
        "total_estimated_sec": sum(c["estimated_sec"] for c in cuts),
    }
    return dv.normalize_directive(
        {"version_type": version_type, "header": header, "cuts": cuts}, version_type)


def render_paper(paper_id: str, lang: str = "ko") -> str:
    draft = db.get_draft_full(paper_id)
    if not draft:
        raise SystemExit(f"draft 없음(먼저 초안 생성): {paper_id}")
    directive = draft_to_directive(draft)
    if not directive["cuts"]:
        raise SystemExit(f"초안에 장면(video_prompts)이 없음: {paper_id}")
    out = f"render_{paper_id[:8]}_{lang}.mp4"
    render.render_directive_local(directive, out, lang=lang)
    log.info("완료: %s (컷 %d, IMAGE_PROVIDER=%s)", out, len(directive["cuts"]), config.IMAGE_PROVIDER)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m engine.render_draft <paper_id> [ko|en]")
        sys.exit(2)
    _lang = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in config.LANGUAGES else config.DEFAULT_LANG
    print("DONE", render_paper(sys.argv[1], _lang))
