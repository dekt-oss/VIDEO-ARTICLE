"""리포트 라인 자기검증에도 한국어 문장 축이 붙어 있는가 (2026-09-11 리뷰).

운영자 지시("대본 리뷰")는 논문 라인만이 아니다. 리포트 라인(`report_selfcheck.py`)은
자기검증을 따로 들고 있어 한쪽에만 넣으면 **인접 경로가 빠진다**.
"""

from __future__ import annotations

from engine import report_selfcheck as rs


def test_korean_axis_is_carried_and_closed_list_is_enforced():
    out = rs.normalize_selfcheck({"scenes": [
        {"scene": 1, "grounded": True, "korean_natural": False,
         "awkward_spans": "연구에 대한", "fluency_issues": ["translationese", "없는종류"]},
        {"scene": 2, "grounded": True},
    ]})
    s1, s2 = out["scenes"]
    assert s1["korean_natural"] is False
    assert s1["awkward_spans"] == ["연구에 대한"]          # 문자열 하나도 목록으로
    assert s1["fluency_issues"] == ["translationese"]      # 닫힌 목록 바깥은 버린다
    assert s2["korean_natural"] is True                    # 축이 없으면 자연스러운 것으로


def test_korean_axis_survives_exemption():
    """★ 면제(훅·마무리)는 **사실 검증**을 면제하는 것이지 문장을 면제하는 것이 아니다 —
    훅도 소리 내어 읽힌다."""
    out = rs.normalize_selfcheck(
        {"scenes": [{"scene": 1, "grounded": False, "unsupported": ["x"],
                     "korean_natural": False, "awkward_spans": ["에 있어서"]}]},
        roles_by_scene={1: "HOOK"}, exempt={1})
    s = out["scenes"][0]
    assert s["exempt"] is True and s["grounded"] is True    # 사실 축은 면제됐다
    assert s["korean_natural"] is False                     # 문장 축은 그대로 남는다
    assert out["all_grounded"] is True                      # 그리고 승인 판정에 안 닿는다
