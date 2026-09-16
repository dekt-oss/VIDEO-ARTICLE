"""클립 계획은 **덮을 수 있는 가장 작은 합**을 산다 (2026-09-13 운영자 지시 "자투리도 잡아줘").

종전에는 상한(8초)부터 채우고 남은 것을 올렸다 — 9.4초 stage 가 8+4=**12초**였다.
6+4=10 이면 되는데 2초를 더 샀고, 영상은 초당 과금이라 그 2초가 그대로 돈이다.
실측(첫 실물 렌더 전반부): 나레이션 55.6초에 62초를 사서 6.4초($0.32)를 버렸다.
"""
import pytest

from engine import config
from engine import stage_render as sr

CAP = 8


@pytest.mark.parametrize("need, want_sum", [
    (9.4, 10),    # 예전 12 — 이 커밋의 계기
    (5.1, 6),
    (13.6, 14),
    (17.0, 18),
    (20.0, 20),
])
def test_it_buys_the_smallest_sum_that_covers(need: float, want_sum: int):
    assert sum(sr.plan_clips(need, max_clip_sec=CAP)) == want_sum


def test_never_short():
    """짧게 사면 나레이션이 잘린다 — 말이 잘리는 것이 화면이 멈추는 것보다 나쁘다."""
    for tenth in range(5, 400):
        need = tenth / 10
        assert sum(sr.plan_clips(need, max_clip_sec=CAP)) >= need - 0.05, need


def test_waste_stays_under_one_tier_step():
    """티어가 4·6·8 이라 도달 가능한 합은 4 이상의 짝수다 — 낭비는 2초를 넘을 수 없다."""
    for tenth in range(40, 400):
        need = tenth / 10
        assert sum(sr.plan_clips(need, max_clip_sec=CAP)) - need < 2.0, need


def test_same_sum_prefers_fewer_clips():
    """합이 같으면 클립이 적은 쪽 — 연쇄가 깊어질수록 정체성이 흐려진다(MAX_CHAIN_DEPTH)."""
    assert sr.plan_clips(14.0, max_clip_sec=CAP) == [8.0, 6.0]   # 4+4+6 아님


def test_every_clip_respects_the_cap():
    for cap in (4, 6, 8):
        for need in (3.0, 7.0, 11.0, 25.0):
            assert max(sr.plan_clips(need, max_clip_sec=cap)) <= cap


def test_invest_candidates_are_one_until_measured():
    """2발은 그 컷의 영상비가 두 배다. 더 낫다는 실측이 나오기 전에는 1발(운영자 지시)."""
    assert config.TIER_PROFILE["invest"]["candidates"] == 1
