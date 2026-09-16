"""설명판 미리보기 — DB·ffmpeg·TTS 없이 보드 PNG 를 뽑아 눈으로 확인한다.

왜 필요한가: 보드가 제대로 그려지는지 확인하려고 매번 전체 렌더(TTS+ffmpeg+업로드)를 돌릴 수는
없다. 이 스크립트는 지시서 dict 하나만 있으면 PNG 를 내놓는다 — 폰트·밴드·밀도 문제가 여기서
바로 드러난다.

실행:
    python -m scripts.preview_board            # 데모 지시서로 보드 5종
    python -m scripts.preview_board out_dir    # 출력 경로 지정
"""

from __future__ import annotations

import json
import os
import sys

from engine import board_render, config, visual_contract

# 실제 지시서와 같은 모양의 데모(§21 검수용 — 값은 전부 '지시서에 있는 것'을 흉내낸다).
DEMO_HEADER = {
    "version_type": "explainer",
    "broker": "메리츠증권 리서치센터",
    "explainer": {
        "profile": "NUMERIC",
        "source_mode": "NEWS_ONLY",
        "report_claim_summary": {
            "speaker": "메리츠증권 리서치센터",
            "statement": "AI 부문의 폭발적 성장이 소비자 부문 부진을 상쇄하고 있다.",
            "fact_refs": ["basis[0]"], "page_refs": [],
        },
        "number_claims": [
            {"claim_no": 1, "value": "900.1", "unit": "억 달러", "label": "FY4Q26 매출액",
             "comparison_basis": "컨센서스", "comparison_value": "877.0",
             "why_significant": "시장 기대를 뛰어넘는 실적을 달성했음을 의미합니다.",
             "fact_refs": ["what[0]"], "page_refs": [], "qualifier_count": 4,
             "big_number_ok": True},
            {"claim_no": 2, "value": "43", "unit": "%", "label": "Azure 연간 성장률",
             "comparison_basis": "직전 4개 분기", "comparison_value": "39",
             "why_significant": "클라우드 성장이 둔화되지 않고 오히려 가속화되고 있습니다.",
             "fact_refs": ["what[5]"], "page_refs": [], "qualifier_count": 4,
             "big_number_ok": True},
        ],
        "watchpoint": {"text": "다음 분기 Azure 성장률의 지속 여부와 Copilot 의 수익 기여도",
                       "metric": "Azure 성장률, M365 Copilot 유료 좌석 수"},
    },
}

DEMO_CUTS = [
    {"cut_no": 1, "board": "HOOK_BOARD", "beat_role": "HOOK",
     "narration_ko": "마이크로소프트의 AI 성장, 진짜 이유가 궁금하지 않으세요?",
     "overlay_plan": [{"type": "evidence_card", "text": "MS, AI로 날아오르다"}]},
    {"cut_no": 2, "board": "NUMBER_BOARD", "beat_role": "EVIDENCE", "number_claim_refs": [1],
     "overlay_plan": [{"type": "source_card", "text": "메리츠증권 리서치센터 리포트"}]},
    {"cut_no": 3, "board": "CHART_BOARD", "beat_role": "EVIDENCE", "number_claim_refs": [2],
     "overlay_plan": [{"type": "source_card", "text": "메리츠증권 리서치센터 리포트"}]},
    {"cut_no": 4, "board": "EVIDENCE_BOARD", "beat_role": "EVIDENCE",
     "overlay_plan": [
         {"type": "source_card", "text": "메리츠증권 리서치센터 · MS FY4Q26 실적 리뷰"},
         {"type": "evidence_card", "text": "클라우드 부문이 폭발적인 성장을 주도하고 있다"}]},
    {"cut_no": 5, "board": "WATCHPOINT_BOARD", "beat_role": "WATCHPOINT",
     "overlay_plan": [{"type": "source_card", "text": "메리츠증권 리서치센터 리포트"}]},
]


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "out/boards"
    os.makedirs(out_dir, exist_ok=True)
    # v3.4 §22-7 착수 순서: ① 폰트 자산 → ② smoke_test → ③ 보드. 순서를 지켜야 "폰트가 없어서
    # 이상하게 나온 것"과 "레이아웃이 틀린 것"을 헷갈리지 않는다.
    try:
        visual_contract.smoke_test()
    except (visual_contract.FontContractError, AssertionError, ValueError) as exc:
        print(f"✗ 시각 계약 스모크 실패: {exc}")
        return 1

    print(f"폰트: {visual_contract.FONT_DIR} · {visual_contract.FONT_FILES}")
    print(f"캔버스: {config.RENDER_WIDTH}×{config.RENDER_HEIGHT} · "
          f"CORE {config.EXPLAINER_BANDS['CORE']}")
    fails = 0
    for i, cut in enumerate(DEMO_CUTS):
        res = board_render.render_board(cut, DEMO_HEADER, None, out_dir, i, total_sec=5.0)
        qa = res.layout_qa
        mark = "✗" if qa["fail"] else ("△" if qa["warn"] else "✓")
        print(f"{mark} #{cut['cut_no']} {cut['board']:<18} "
              f"{len(res.frame_paths)}프레임/{res.duration:.1f}s · CORE 밀도 {res.core_fill:.0%} "
              f"· {os.path.basename(res.frame_paths[-1])}")
        if qa["fail"]:
            fails += 1
            for f in qa["fail"]:
                print(f"    fail: {f}")
        for w in qa["warn"]:
            print(f"    warn: {w}")
    print(f"\n출력: {os.path.abspath(out_dir)}")
    if fails:
        print(f"※ 밴드 위반 보드 {fails}개 — §20-7 기준 렌더 차단 대상입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
