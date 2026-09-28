"""첫 3초 규칙 — 컷1 은 질문·역설 한마디(≈3초) (2026-09-28, 운영자 승인 벤치마크 1번).

벤치마크 첫 컷: "피일까요?" · "시화호죠." — 2~5글자 + 그 물건. 우리 첫 컷은 저장 지시서 56편 중앙값
26자(≈5초), 삼성전자 편은 50자(8.5초)였다. TTS 실측 초당 5.1자 → 16자 ≈ 3.1초.
"""

from __future__ import annotations

from engine import config, directive as dv, photo_contract as pc, report_directive as rd
from engine import report_scriptgen, scriptgen
from tests.test_photo_contract import _good_directive


def _eval(first_narration):
    header, cuts = _good_directive(10)
    cuts[0]["narration_ko"] = first_narration
    return pc.evaluate(header, cuts, None)


def _flag(got):
    return [w for w in got["warnings"] if w.startswith("photo_hook_cut_too_long")]


def test_a_long_first_cut_is_sent_back():
    """★ 실측 그 문장(삼성전자 컷1, 50자)."""
    got = _eval("삼성전자 목표주가가 63만 원까지 상향된 이유, 과열인 줄 알았더니 메모리 수급 구조의 변화 때문이었습니다.")
    assert _flag(got) and _flag(got)[0].endswith("자")
    assert not any(b.startswith("photo_hook_cut_too_long") for b in got["block_reasons"]), "경고이지 차단이 아니다"


def test_a_short_question_passes():
    assert _flag(_eval("나무도 목마르면 성장을 멈춘다?")) == []
    assert _flag(_eval("주가는 반토막인데 이익은 2배?")) == []


def test_spaces_do_not_count():
    """TTS 속도를 공백 제외로 쟀으므로 글자 수도 공백 제외다."""
    text = "가 " * config.HOOK_CUT_MAX_CHARS_KO
    assert _flag(_eval(text)) == []


def test_the_rule_reaches_both_factories_with_its_check_and_fix():
    paper = dv.directive_user_prompt({"script_md": "문장.", "fact_sheet": {}, "scenes": []}, "photo")
    report = rd.report_directive_user_prompt(
        {"script_md": "문장.", "fact_sheet": {}, "scenes": [], "financial_reasoning": None}, "photo")
    for p in (paper, report):
        assert "첫 3초" in p and "photo_hook_cut_too_long" in p
    assert "photo_hook_cut_too_long" in config.RETRYABLE_QUALITY_WARNINGS
    fix = pc.feedback_prompt([], ["photo_hook_cut_too_long:50자"])
    assert "컷2 로 옮겨라" in fix, "지운 사실을 버리지 말고 자리만 바꾸라고 해야 한다"


def test_titles_are_asked_as_riddles_in_both_factories():
    import inspect
    assert "수수께끼형" in inspect.getsource(scriptgen)
    assert "수수께끼형" in inspect.getsource(report_scriptgen)
