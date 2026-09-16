"""Phase 0 §2-D — 코스피 실패작(0bceb278) 컷 2/3/7 보드 렌더 재현.

DB 에 저장된 지시서 필드를 그대로 넣고 board_render.render_board 를 돌려
빈 화면의 계층(에셋 누락 / 렌더 예외 / bbox / 미구현)을 확정한다.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import board_render  # noqa: E402

HEADER = {
    "version_type": "explainer",
    "aspect_ratio": "9:16",
    "hook_ko": "코스피, 하루 만에 18% 급등의 진실",
    "broker": "대신 전략. 돌직구",
    "explainer": {
        "profile": "EVENT",
        "source_mode": "PARTIAL_REPORT",
        "report_claim_summary": {
            "speaker": "대신증권",
            "statement": "빅테크의 설비 투자와 디레버리징이 막바지에 이르렀다는 인식 확산으로 "
                         "외국인과 기관의 순매수가 유입되며 코스피가 급등했습니다.",
        },
        "watchpoint": {
            "text": "향후 빅테크 기업들의 실제 설비 투자(CapEx) 계획과 분기별 실적을 통해 "
                    "투자 사이클 변화가 확인되는지 주목해야 합니다.",
            "metric": "빅테크 CapEx 계획 및 실적",
        },
        "number_claims": [
            {"claim_no": 1, "value": "18.50", "unit": "%", "label": "코스피 일일 상승률",
             "comparison_basis": "당일 종가", "comparison_value": "6,628.20pt",
             "why_significant": "이례적인 수준의 일일 급등으로 시장의 강한 매수세를 나타냄",
             "big_number_ok": True},
            {"claim_no": 2, "value": "7.6", "unit": "조원", "label": "외국인 순매수",
             "comparison_basis": "당일 집계", "comparison_value": "기관 1.1조원",
             "why_significant": "지수 상승을 견인한 핵심 주체임을 명확히 보여줌",
             "big_number_ok": True},
            {"claim_no": 3, "value": "27.48", "unit": "%", "label": "전기·전자 업종 상승률",
             "comparison_basis": "코스피 상승률", "comparison_value": "18.50%",
             "why_significant": "전체 시장 상승을 주도한 핵심 섹터임을 증명함",
             "big_number_ok": True},
        ],
    },
}

CUTS = {
    2: {"cut_no": 2, "board": "NUMBER_BOARD", "beat_role": "EVIDENCE",
        "scene_kind": "kinetic_typography", "number_claim_refs": [2],
        "narration_ko": "특히 외국인이 7조 6천억 원 이상을 순매수하며 이례적인 상승을 이끌었습니다.",
        "overlay_plan": [{"type": "number_punch", "text": "외국인 순매수\n+7.6조원",
                          "start_sec": 1, "duration_sec": 4}]},
    3: {"cut_no": 3, "board": "NUMBER_BOARD", "beat_role": "EVIDENCE",
        "scene_kind": "kinetic_typography", "number_claim_refs": [3],
        "narration_ko": "자금은 전기·전자 업종으로 집중됐는데요. 이 섹터는 무려 27% 넘게 올랐습니다.",
        "overlay_plan": [{"type": "number_punch", "text": "전기·전자 업종\n+27.48%",
                          "start_sec": 1, "duration_sec": 4}]},
    7: {"cut_no": 7, "board": "WATCHPOINT_BOARD", "beat_role": "WATCHPOINT",
        "scene_kind": "kinetic_typography", "number_claim_refs": [],
        "narration_ko": "결국 시장의 관심은 다시 빅테크의 실제 투자 계획으로 향하고 있습니다. "
                        "향후 발표될 설비 투자 규모를 확인하는 것이 중요해 보입니다.",
        "overlay_plan": [{"type": "evidence_card",
                          "text": "Watch Point:\n향후 빅테크 기업들의 실제 설비 투자(CapEx) 계획",
                          "start_sec": 0.5, "duration_sec": 4}]},
}

SECS = {2: 6.0, 3: 6.5, 7: 8.0}
work = os.path.join(tempfile.gettempdir(), "phase0_repro_board")
os.makedirs(work, exist_ok=True)
print("작업 디렉터리:", work)

for no, cut in CUTS.items():
    pay = board_render.board_payload(cut, HEADER, None, "ko")
    print(f"\n=== cut {no} ({cut['board']}) ===")
    print("  payload.number      =", repr(pay["number"]))
    print("  payload.title       =", repr(pay["title"])[:80])
    print("  payload.number_label=", repr(pay["number_label"]))
    print("  payload.watchpoint  =", repr(pay["watchpoint"])[:80])
    try:
        res = board_render.render_board(cut, HEADER, None, work, no, total_sec=SECS[no], lang="ko")
        print("  frames              =", len(res.frame_paths), "core_fill=", round(res.core_fill, 3))
        print("  layout_qa           =", json.dumps(res.layout_qa, ensure_ascii=False)[:400])
        print("  frame_qa            =", json.dumps(res.frame_qa, ensure_ascii=False)[:400])
        print("  placements          =", len(res.placements))
        mid = res.frame_paths[len(res.frame_paths) // 2]
        os.replace(mid, os.path.join(work, f"mid_cut{no}.png"))
        print("  mid frame           =", f"mid_cut{no}.png")
    except Exception as exc:  # noqa: BLE001
        print(f"  RAISED {type(exc).__name__}: {exc}")

# ── 배치 겹침 측정(§9 Q2 예고) ──
res = board_render.render_board(CUTS[3], HEADER, None, work, 33, total_sec=6.5, lang="ko")
print("\n=== cut 3 placements ===")
for p in res.placements:
    print(f"  {p.kind:8} band={p.band:10} text={p.text[:18]!r:22} box=({p.box.x1},{p.box.y1})-({p.box.x2},{p.box.y2})")
ps = [p for p in res.placements if p.kind in ("text", "number", "bar", "card")]
for i in range(len(ps)):
    for j in range(i + 1, len(ps)):
        a, b = ps[i].box, ps[j].box
        ox = min(a.x2, b.x2) - max(a.x1, b.x1)
        oy = min(a.y2, b.y2) - max(a.y1, b.y1)
        if ox > 0 and oy > 0:
            print(f"  OVERLAP {ps[i].kind}:{ps[i].text[:14]!r} x {ps[j].kind}:{ps[j].text[:14]!r}: {ox}x{oy}px")
