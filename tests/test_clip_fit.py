"""클립 길이 보정 판정 — 계약(clip_fit_types)의 경계값을 못박는다.

★ 이 파일이 지키는 것은 `engine/clip_fit_types.py` 머리말의 **동결된 계약**이다.
  경계는 하한 배타·상한 포함이고, `target_sec` 는 모든 kind 에서 나레이션 길이다.
"""

from __future__ import annotations

from engine import config
from engine.clip_fit import decide_strategy
from engine.clip_fit_types import STRATEGY_KINDS


def test_a_longer_clip_is_trimmed_with_a_fade():
    got = decide_strategy(clip_sec=6.0, narration_sec=4.0)
    assert got.kind == "trim"
    assert got.target_sec == 4.0
    assert got.fade_out_sec == config.CLIP_FIT_TRIM_FADE_SEC


def test_an_exactly_matching_clip_gets_no_fade():
    """★ 계약이 명시적으로 금지하는 지점: 자를 것이 없으면 페이드도 없다.

    Manim 클립은 나레이션 실측으로 렌더되므로 **항상 이 경우**다. 여기에 페이드를 넣으면
    컷마다 끝이 0.2s 검게 죽어 경계가 번쩍인다.
    """
    got = decide_strategy(clip_sec=4.0, narration_sec=4.0)
    assert got.kind == "trim" and got.fade_out_sec == 0.0


def test_a_slightly_short_clip_holds_the_last_frame():
    got = decide_strategy(clip_sec=3.7, narration_sec=4.0)      # ratio 0.075
    assert got.kind == "hold"
    assert round(got.hold_sec, 3) == 0.3
    assert got.ken_burns is True                                 # 정지 티를 줄인다


def test_the_hold_boundary_is_inclusive():
    """★ ratio 가 정확히 HOLD_RATIO_MAX 면 **hold** 다(상한 포함). 계약이 못박은 경계."""
    n = 4.0
    c = n * (1 - config.CLIP_FIT_HOLD_RATIO_MAX)
    assert decide_strategy(clip_sec=c, narration_sec=n).kind == "hold"


def test_a_clearly_short_clip_pingpongs_when_looping_is_safe():
    got = decide_strategy(clip_sec=2.0, narration_sec=4.0, loop_safe=True)   # ratio 0.5
    assert got.kind == "pingpong"
    assert got.loops >= 1


def test_the_same_gap_holds_when_looping_is_not_safe():
    """★ 안전측 기본값. 역재생은 사람이 뒤로 걷고 액체가 거꾸로 흐르게 만든다 —
    지시서가 컷 단위로 loop_safe 를 선언하지 않았으면 홀드다."""
    got = decide_strategy(clip_sec=2.0, narration_sec=4.0, loop_safe=False)
    assert got.kind == "hold" and got.ken_burns is True


def test_the_pingpong_boundary_is_inclusive():
    n = 4.0
    c = n * (1 - config.CLIP_FIT_PINGPONG_RATIO_MAX)
    assert decide_strategy(clip_sec=c, narration_sec=n, loop_safe=True).kind == "pingpong"


def test_a_far_too_short_clip_is_flagged_but_still_fills_the_slot():
    """★ 플래그는 **사람에게 보이는 신호**다. 그래도 화면 시간은 나레이션 길이다 —
    조용히 늘려 놓으면 그 컷이 왜 어색한지 아무도 모른다."""
    got = decide_strategy(clip_sec=1.0, narration_sec=10.0)      # ratio 0.9
    assert got.kind == "flagged"
    assert got.target_sec == 10.0                                # 불변식
    assert got.hold_sec > 0                                      # 뒤가 검게 남지 않는다


def test_every_kind_keeps_narration_as_the_owner_of_the_timeline():
    """★ 계약 불변식: target_sec == narration_sec, 모든 kind 공통."""
    cases = [(6.0, 4.0, False), (3.7, 4.0, False), (2.0, 4.0, True),
             (2.0, 4.0, False), (1.0, 10.0, False)]
    for c, n, safe in cases:
        got = decide_strategy(clip_sec=c, narration_sec=n, loop_safe=safe)
        assert got.target_sec == n, got
        assert got.kind in STRATEGY_KINDS


def test_a_zero_length_narration_does_not_kill_the_render():
    """★ 호출측 결함이다. 계약이 방어적 처리를 허용하므로 **편 전체를 멈추지 않는** 쪽을 고른다."""
    got = decide_strategy(clip_sec=4.0, narration_sec=0.0)
    assert got.kind == "trim" and got.target_sec == 4.0


def test_the_consumer_now_uses_the_real_module_not_the_fallback():
    """★★ 이 저장소의 반복 결함: **만들어 놓고 아무도 안 부른다.**
    clip_fit_types.decide 가 폴백이 아니라 진짜 구현을 잡는지 확인한다."""
    from engine import clip_fit_types
    got = clip_fit_types.decide(clip_sec=2.0, narration_sec=4.0, loop_safe=True)
    assert got.kind == "pingpong", "폴백이 여전히 쓰이고 있다(핑퐁 판정이 없다)"
    assert "미배선" not in got.note
