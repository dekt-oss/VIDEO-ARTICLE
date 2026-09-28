"""대본 4막 — 문제 제기 → 오해 또는 문제 상황 → 반전 또는 원리 → 결과/결론 (2026-09-28 운영자 지시).

논문·리포트가 **같은 뼈대**를 쓴다. 종전엔 논문은 "강한 결과 → 연구 범위 공개", 리포트는
"후크 → 맥락 → 팩트 비트 → 리스크 턴 → 페이오프"였고, 리포트 대본은 "유안타증권은 …분석했습니다 /
…추정했습니다"가 이어지는 요약문이 됐다(삼성전자 편).
"""

from __future__ import annotations

from engine import directive as dv, narrative, report_directive as rd
from engine import report_scriptgen, scriptgen


def test_both_factories_share_the_same_arc_text():
    assert narrative.NARRATIVE_ARC in scriptgen.SCRIPT_SYSTEM
    assert narrative.NARRATIVE_ARC in report_scriptgen.SCRIPT_SYSTEM


def test_the_arc_tells_the_model_not_to_invent_a_misconception():
    assert "오해를 지어내지 마라" in narrative.NARRATIVE_ARC


def test_it_limits_repeating_the_source_name():
    assert "한두 번" in narrative.NARRATIVE_ARC and "매 씬" in narrative.NARRATIVE_ARC


def test_arc_stage_is_kept_on_scenes_in_both_factories():
    """정규화가 모르는 필드를 버리므로, 두 정규화기가 arc_stage 를 **명시적으로** 남겨야 한다."""
    import inspect
    assert 'narrative.arc_stage(s.get("arc_stage"))' in inspect.getsource(scriptgen)
    assert 'narrative.arc_stage(s.get("arc_stage"))' in inspect.getsource(report_scriptgen)


def test_arc_stage_enum():
    assert narrative.arc_stage(" Turn ") == "turn"
    assert narrative.arc_stage("climax") == ""


def test_arc_problems():
    ok = [{"arc_stage": x} for x in ("problem", "situation", "turn", "turn", "result")]
    assert narrative.arc_problems(ok) == []
    no_turn = [{"arc_stage": x} for x in ("problem", "situation", "result")]
    assert narrative.arc_problems(no_turn) == ["script_arc_missing:turn"]
    back = [{"arc_stage": x} for x in ("problem", "turn", "situation", "result")]
    assert "script_arc_out_of_order" in narrative.arc_problems(back)
    assert narrative.arc_problems([{"scene": 1}]) == [], "arc_stage 없는 옛 초안은 판정하지 않는다"


def test_the_directive_keeps_the_script_order():
    assert "4막 순서" in dv.HOOK_CUT_RULE
    assert "대본의 4막" in rd.PHOTO_CONTRACT   # 리포트 실사형 프롬프트에도 같은 규칙이 실린다
