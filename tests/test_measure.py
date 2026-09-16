"""P0 합격 판정 순수 로직 테스트."""

from engine.measure import day_pick_count, tally_pass


def test_day_pick_count_counts_acceptable():
    statuses = ["picked", "shortlisted", "rejected", "", "picked"]
    assert day_pick_count(statuses) == 3  # picked 2 + shortlisted 1


def test_tally_pass_passes_with_5_of_7():
    counts = [3, 4, 2, 5, 3, 1, 3]  # ≥3 인 날: 5일
    r = tally_pass(counts)
    assert r["pass_days"] == 5
    assert r["passed"] is True


def test_tally_pass_fails_with_4_of_7():
    counts = [3, 3, 3, 3, 2, 1, 0]  # ≥3 인 날: 4일
    r = tally_pass(counts)
    assert r["pass_days"] == 4
    assert r["passed"] is False


def test_tally_pass_empty():
    r = tally_pass([])
    assert r["passed"] is False
