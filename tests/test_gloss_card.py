"""풀이 카드 — 약어·어려운 개념을 용어 + 쉬운 풀이로 (2026-09-28 운영자 지시).

원문: "파란색 bottleneck 이건 왜 들어가는거야?? 약어라던지 어려운 개념이라던지 나레이션으로 다 표현하기
애매한 것들을 추가 자막으로 잘 보이게 넣어야 할 거 같은데". 종전 규칙("컷마다 대문자 영어 낱말 하나")은
모든 컷에 GRID BOTTLENECK 같은 영어 요약어를 붙였다.
"""

from __future__ import annotations

from engine import config, evidence_overlay as eo, photo_contract as pc
from engine import directive as dv, report_directive as rd
from engine.overlay_motion import strip_entrance

GLOSS = {"type": "keyword", "term": "HBM", "gloss_ko": "고대역폭 메모리", "gloss_en": "high-bandwidth memory"}


def _cues(plan, lang="ko"):
    return eo.build_overlay_cues([{"cut_no": 1, "overlay_plan": plan}], [0.0], [4.0], lang=lang)


def test_term_on_top_gloss_below_in_the_viewers_language():
    plan = eo.normalize_overlay_plan([GLOSS])
    ko, en = _cues(plan, "ko")[0][2], _cues(plan, "en")[0][2]
    # "용어: 풀이" 한 줄(운영자 2026-09-28: "중속엔진: 발전소용 중형엔진 이런 식으로 확실하게")
    assert ko.endswith("HBM: 고대역폭 메모리")
    assert en.endswith("high-bandwidth memory")


def test_it_survives_the_second_normalization():
    """★ 실측(2026-09-28): 저장 때 한 번, 렌더 때 한 번 정리된다 — 두 번째에 풀이를 잃어 한 줄 요약이 됐다."""
    twice = eo.normalize_overlay_plan(eo.normalize_overlay_plan([GLOSS]))
    assert twice[0]["payload"]["term"] == "HBM"
    assert _cues(twice)[0][2].endswith("HBM: 고대역폭 메모리")


def test_an_old_english_word_card_does_not_show_in_korean_videos():
    old = eo.normalize_overlay_plan([{"type": "keyword", "text": "GRID BOTTLENECK"}])
    assert _cues(old, "ko") == []
    assert strip_entrance(_cues(old, "en")[0][2]) == "GRID BOTTLENECK", "영어 영상에는 그대로 둔다"


def test_an_old_korean_word_card_still_shows():
    old = eo.normalize_overlay_plan([{"type": "keyword", "text": "미오글로빈"}])
    assert strip_entrance(_cues(old, "ko")[0][2]) == "미오글로빈"


def test_the_gate_asks_to_turn_old_cards_into_glosses_or_drop_them():
    got = pc.evaluate({"hook_ko": "훅"}, [{"cut_no": 1, "visual_role": "REALITY", "narration_ko": "문장",
                                           "visual_prompt": "x", "overlay_plan": [{"type": "keyword",
                                                                                "text": "GRID BOTTLENECK"}]}])
    assert any(w.startswith("photo_keyword_without_gloss") for w in got["warnings"])
    assert "photo_keyword_without_gloss" in config.RETRYABLE_QUALITY_WARNINGS
    fix = pc.feedback_prompt([], ["photo_keyword_without_gloss:1"])
    assert "gloss_ko" in fix and "지워라" in fix


def test_both_prompts_ask_for_glosses_only_where_needed():
    import inspect
    from engine import photo_prompt   # 2026-09-28 실사형 계약은 한 자리(두 공장 공용)
    for src in (inspect.getsource(photo_prompt),):
        assert "gloss_ko" in src and "붙이지 마라" in src
    assert "컷마다 낱말 하나를 붙여라" not in inspect.getsource(dv)
