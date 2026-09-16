"""채점·지수·배치 순수 로직 테스트."""

import math

from engine import config
from engine.batch import build_batch_rows
from engine.scoring import (
    fun_index,
    golden_index,
    importance_index,
    normalize_buzz,
    parse_axes,
    significance_with_boost,
    zero_axes,
)


def test_parse_axes_clamps_and_defaults():
    axes = parse_axes({"surprise": 12, "explainability": -3, "relatability": "7",
                       "significance": None, "one_liner_ko": "안녕"})
    assert axes["surprise"] == 10      # 상한 클램프
    assert axes["explainability"] == 0  # 하한 클램프
    assert axes["relatability"] == 7    # 문자열 숫자 허용
    assert axes["significance"] == 0    # None → 0
    assert axes["one_liner_ko"] == "안녕"


def test_zero_axes_has_red_flag():
    z = zero_axes()
    assert z["surprise"] == 0
    assert "실패" in z["red_flag"]


def test_normalize_buzz_log_scale():
    assert normalize_buzz(None) == 0.0
    assert normalize_buzz({"total": 0}) == 0.0
    expected = round(min(config.BUZZ_SCORE_MAX, config.BUZZ_LOG_COEFF * math.log1p(100)), 3)
    assert normalize_buzz({"total": 100}) == expected
    assert normalize_buzz({"total": 10**9}) == config.BUZZ_SCORE_MAX  # 상한


def test_significance_boost_off_by_default():
    assert config.ENABLE_SIGNIFICANCE_BOOST is False
    assert significance_with_boost(7, "Nature") == 7.0  # off 면 원점수


def test_indices():
    axes = {"surprise": 10, "explainability": 10, "relatability": 10}
    assert fun_index(axes) == 10.0
    assert importance_index(10.0, 10.0) == 10.0
    assert golden_index(10.0, 10.0) == 100.0


def test_build_batch_dedups_and_caps():
    # 충분히 많은 편수로 상한(DAILY_BATCH_SIZE) 검증
    n = config.DAILY_BATCH_SIZE + 5
    scores = []
    for i in range(n):
        scores.append({
            "paper_id": f"p{i}",
            "fun_index": float(i),                  # fun 1등 = 마지막
            "importance_index": float(n - i),       # importance 1등 = p0
        })
    rows = build_batch_rows("2026-06-29", scores)
    assert len(rows) == config.DAILY_BATCH_SIZE      # 상한
    pids = [r["paper_id"] for r in rows]
    assert len(pids) == len(set(pids))               # 중복 없음
    assert all(r["batch_date"] == "2026-06-29" for r in rows)
    assert {r["sort_mode"] for r in rows} <= set(config.SORT_MODES)


def test_build_batch_handles_fewer_than_n():
    scores = [{"paper_id": "a", "fun_index": 1, "importance_index": 1}]
    rows = build_batch_rows("2026-06-29", scores)
    assert len(rows) == 1
