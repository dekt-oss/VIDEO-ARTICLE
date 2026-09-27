"""논문 지시서의 훅은 **상단 고정 부제**다 — 1컷 나레이션의 복사본이 아니다 (2026-09-27 실측).

저장 논문 실사형 지시서 36건이 **전부** 재생성을 탔고, 그중 21건의 1차 사유가 photo_hook_missing,
7건은 재생성 뒤에도 그 사유로 승인이 잠겼다. 리포트는 0건이었다. 차이는 스키마 한 줄이었다 —
리포트는 "상단 고정 부제 — 1컷 나레이션과 다른 문장, 20자 내외", 논문은 "한국어 훅 — 관용적
재작성". 모델이 첫 문장을 훅에 옮기고, 코드가 중복이라 지우고(_drop_hook_duplicating_first_cut),
게이트가 빈 훅을 막았다.
"""

from __future__ import annotations

from engine import directive as dv, photo_contract as pc, report_directive as rd


def test_the_paper_schema_defines_the_hook_like_the_report_does():
    """스키마는 시스템 프롬프트에 있다(두 공장 모두)."""
    for p in (dv.DIRECTIVE_SYSTEM_BASE, rd.REPORT_DIRECTIVE_SYSTEM):
        assert "상단 고정 부제" in p and "다른 문장" in p
    assert "관용적 재작성>" not in dv.DIRECTIVE_SYSTEM_BASE, "옛 정의가 남으면 모델이 첫 문장을 옮긴다"


def test_the_retry_says_why_the_hook_disappeared():
    fix = pc.feedback_prompt(["photo_hook_missing"], [])
    assert "코드가 지운다" in fix and "20자" in fix


def test_a_copied_hook_is_still_dropped():
    """회귀 방지 — 스키마를 고쳤다고 중복 제거를 끄지 않는다(화면에 같은 문장 두 번)."""
    header = {"hook_ko": "나무도 목마르면 성장을 멈춘다?", "hook_en": ""}
    cuts = [{"cut_no": 1, "narration_ko": "나무도 목마르면 성장을 멈춘다?", "narration_en": ""}]
    dv._drop_hook_duplicating_first_cut(header, cuts)
    assert header["hook_ko"] == ""
