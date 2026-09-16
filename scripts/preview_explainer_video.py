"""설명판형 예시 영상 — 외부 API 호출 0으로 mp4 를 끝까지 만든다.

왜 필요한가: 보드 PNG 만 봐서는 "실제 영상에서 검은 바가 사라졌는지 / 자막이 CORE 를 침범하지
않는지 / 단계 등장이 나레이션 길이에 맞는지"를 알 수 없다. 이 스크립트는 데모 지시서 하나로
전체 렌더 경로(_render_cut_clips → build_ass → assemble_full)를 그대로 태워 mp4 를 낸다.

★ 비용 0: 보드는 코드 렌더($0), TTS 는 placeholder(무음), 이미지·Veo 호출 없음.
  실제 운영과 다른 것은 나레이션 음성뿐이고, 화면·자막·레이아웃은 동일한 코드가 만든다.

실행:
    python -m scripts.preview_explainer_video            # ./out/explainer_demo.mp4
    python -m scripts.preview_explainer_video out.mp4
"""

from __future__ import annotations

import os
import sys
import tempfile

from engine import assemble, config, report_render, subtitles
from engine import render
from scripts.preview_board import DEMO_CUTS, DEMO_HEADER

# 실제 지시서와 같은 모양 — 보드 컷 + 나레이션. visual_prompt 는 보드 컷에서 쓰이지 않는다.
NARRATION = {
    1: "마이크로소프트가 AI로 날아올랐습니다. 진짜 이유가 궁금하지 않으세요?",
    2: "메리츠증권은 이번 분기 매출액 900.1억 달러를 핵심 근거로 제시했습니다.",
    3: "애저의 연간 성장률은 43퍼센트, 직전 네 개 분기보다 오히려 빨라졌습니다.",
    4: "이건 제 해석이 아니라 메리츠증권 리서치센터 리포트의 주장입니다.",
    5: "다음 분기에도 애저 성장률이 유지되는지 확인해야 합니다.",
}


def build_directive() -> dict:
    cuts = []
    for c in DEMO_CUTS:
        cut = dict(c)
        cut["narration_ko"] = NARRATION[c["cut_no"]]
        cut["narration_en"] = ""
        cut["estimated_sec"] = 5
        cut["visual_type"] = "image"
        cut["visual_prompt"] = ""
        cut["effects"] = []
        cut["transition"] = "cut"
        cut["source_facts"] = ["what[0]"]
        cuts.append(cut)
    header = dict(DEMO_HEADER)
    header["aspect_ratio"] = config.ASPECT_RATIO
    header["hook_ko"] = "MS, AI로 날아오르다"
    header["broker"] = "메리츠증권 리서치센터"
    header["total_estimated_sec"] = sum(c["estimated_sec"] for c in cuts)
    return {"version_type": "explainer", "header": header, "cuts": cuts}


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "out/explainer_demo.mp4"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    directive = build_directive()
    work = tempfile.mkdtemp(prefix="explainer_demo_")
    lang = config.DEFAULT_LANG

    overlays: list[tuple[float, float, str, str]] = []
    spent = {"cost": 0.0}
    with report_render._explainer_layout("explainer"):
        print(f"레이아웃: {config.LAYOUT_MODE} (레터박스 {'해제' if config.LAYOUT_MODE == 'full_bleed' else '적용'})")
        cut_files, cues, total, duck = render._render_cut_clips(
            directive, work, on_cost=lambda c: spent.__setitem__("cost", spent["cost"] + c),
            directive_id=None, lang=lang, overlay_out=overlays)

    footer = report_render._disclaimer_footer("메리츠증권 리서치센터", lang)
    ass = subtitles.build_ass(
        cues, header_title=config.REPORT_SERIES_TITLE_BY_LANG.get(lang, ""),
        header_hook=directive["header"]["hook_ko"], total_sec=total, lang=lang,
        platform=config.DEFAULT_PLATFORM, footer_text=footer, overlays=overlays,
        caption_margin_v=config.EXPLAINER_CAPTION_MARGIN_V,
        footer_margin_v=config.EXPLAINER_SOURCE_MARGIN_V)
    assemble.assemble_full(cut_files, work, out, ass_text=ass, total_sec=total, duck_spans=duck)

    print(f"컷 {len(cut_files)}개 · 총 {total:.1f}초 · 생성비 ${spent['cost']:.3f}")
    print(f"오버레이 카드 {len(overlays)}개")
    print(f"출력: {os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
