"""첫 질문만 다시 쓰기 — 지금 질문보다 확실히 나을 때만 바꾼다(2026-10-08). 가짜 모델·가짜 Jev 만."""

from __future__ import annotations

from engine import hook_rewrite


def _row(text, jargon, spoiler, unsupported=0.1):
    return {"text": text, "jargon": jargon, "spoiler": spoiler, "unsupported": unsupported}


NOW = _row("잠은 뇌 깊은 곳이 시킨다고요? 그런데 뇌 겉면의 아주 적은 세포가 스스로 잠을 켠다면요?", 0.12, 0.72)


def test_keeps_the_current_hook_when_no_candidate_is_clearly_better():
    out = hook_rewrite.choose(NOW, [_row("a", 0.10, 0.70), _row("b", 0.9, 0.1), _row("c", 0.1, 0.2, 0.8)])
    assert out["changed"] is False and out["text"] == NOW["text"]


def test_swaps_to_the_best_candidate_that_passes_everything():
    out = hook_rewrite.choose(NOW, [_row("a", 0.15, 0.30), _row("b", 0.10, 0.20), _row("c", 0.05, 0.10, 0.7)])
    assert out["changed"] is True and out["text"] == "b"


def test_jev_silence_never_wins():
    out = hook_rewrite.choose(NOW, [{"text": "x", "jargon": None, "spoiler": 0.0, "unsupported": 0.0}])
    assert out["changed"] is False


def test_propose_drops_malformed_and_unchanged_candidates():
    rows = [{"text": "뇌세포의 1%도 안 되는 세포가 잠을 부른다면요?", "angle": "숫자 충격", "fact_refs": ["numbers[0]"]},
            {"text": NOW["text"]}, {"angle": "빈 문장"}, "문자열"]
    got = hook_rewrite.propose({}, NOW["text"], "다음", "q", caller=lambda **kw: {"candidates": rows})
    assert [g["text"] for g in got] == ["뇌세포의 1%도 안 되는 세포가 잠을 부른다면요?"]


def test_prompt_keeps_the_hooking_and_fact_rules():
    text = hook_rewrite.HOOK_SYSTEM
    assert "답(연구 결과·원리)은 숨겨라" in text and "전문용어 금지" in text and "Fact Sheet 에 있는 것만" in text


def test_score_feeds_fact_sheet_to_the_grounding_judge():
    seen = []
    rows = hook_rewrite.score(["x"], {"numbers": ["less than 1%"]}, hook_judge=lambda t: {"jargon": 0.1, "spoiler": 0.2},
                              fact_judge=lambda t, s: seen.append(s) or 0.1)
    assert rows == [_row("x", 0.1, 0.2, 0.1)] and "less than 1%" in seen[0]
