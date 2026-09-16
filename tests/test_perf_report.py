"""engine.perf_report + analytics 시계열 순수 로직 테스트.

네트워크·DB·LLM 없이 순수 함수만 검증한다(regel 단계 + 주/월 버킷팅).
"""

from engine import config
from engine.analytics import (
    aggregate_by_period,
    build_daily_rows,
    iso_week_key,
    month_key,
    pct_delta,
)
from engine.perf_report import compute_report_facts, rule_summary


# ── 주/월 키 ──
def test_iso_week_key():
    assert iso_week_key("2026-07-19") == "2026-W29"
    assert iso_week_key("2026-01-01") == "2026-W01"


def test_month_key():
    assert month_key("2026-07-19") == "2026-07"


# ── 증감률 ──
def test_pct_delta():
    assert pct_delta(120, 100) == 20.0
    assert pct_delta(80, 100) == -20.0
    assert pct_delta(100, 0) is None      # 0 분모 방지
    assert pct_delta(0, 0) is None


# ── build_daily_rows ──
def test_build_daily_rows_normalizes_and_skips_empty():
    api = [
        {"day": "2026-07-18", "views": 100, "estimatedMinutesWatched": 12.5,
         "averageViewPercentage": 55.0, "likes": 4, "comments": 1, "shares": 2, "subscribersGained": 3},
        {"day": "", "views": 999},  # day 없으면 스킵
    ]
    rows = build_daily_rows(api, "ko")
    assert len(rows) == 1
    r = rows[0]
    assert r["lang"] == "ko" and r["day"] == "2026-07-18"
    assert r["views"] == 100 and r["subscribers_gained"] == 3
    assert r["average_view_percentage"] == 55.0


# ── aggregate_by_period: 조회수 가중 평균 ──
def _daily(day, views, pct, subs=0):
    return {"day": day, "views": views, "estimated_minutes_watched": views / 10,
            "average_view_percentage": pct, "subscribers_gained": subs,
            "likes": 0, "comments": 0, "shares": 0}


def test_aggregate_weekly_weighted_average():
    # 같은 주(2026-W29: 7/13 월 ~ 7/19 일) 두 날: 조회 100@50%, 300@70% → 가중 평균 65%
    rows = [_daily("2026-07-14", 100, 50.0, subs=1), _daily("2026-07-15", 300, 70.0, subs=2)]
    weekly = aggregate_by_period(rows, "weekly")
    assert len(weekly) == 1
    w = weekly[0]
    assert w["period"] == "2026-W29"
    assert w["views"] == 400
    assert w["subscribers_gained"] == 3
    assert w["average_view_percentage"] == 65.0   # (100*50 + 300*70)/400


def test_aggregate_monthly_buckets_and_sorted():
    rows = [_daily("2026-06-30", 100, 40.0), _daily("2026-07-01", 200, 60.0)]
    monthly = aggregate_by_period(rows, "monthly")
    assert [m["period"] for m in monthly] == ["2026-06", "2026-07"]  # 오름차순
    assert monthly[1]["views"] == 200


def test_aggregate_empty():
    assert aggregate_by_period([], "weekly") == []


# ── compute_report_facts ──
def _video(title, views, pct, subs=0):
    return {"video_id": "v" + title, "title": title, "views": views,
            "average_view_percentage": pct, "subscribers_gained": subs,
            "likes": 0, "comments": 0}


def test_compute_facts_best_worst_and_low_retention():
    videos = [
        _video("A", 1000, 80.0, subs=5),
        _video("B", 500, 30.0),      # 저 지속률(<40 기본)
        _video("C", 10, 20.0),       # 저 지속률
    ]
    daily = [_daily("2026-07-14", 100, 50.0, subs=1), _daily("2026-07-15", 300, 70.0, subs=2)]
    facts = compute_report_facts(videos, daily)

    assert facts["shorts_count"] == 3
    assert facts["totals"]["views"] == 400
    assert facts["totals"]["subscribers_gained"] == 3
    assert facts["best_videos"][0]["title"] == "A"          # 조회 최다
    # 저 지속률: B, C (임계값 config.PERF_LOW_RETENTION_PCT 미만, 조회>0)
    low_titles = {v["title"] for v in facts["low_retention_videos"]}
    assert "B" in low_titles and "C" in low_titles and "A" not in low_titles
    assert facts["low_retention_threshold"] == config.PERF_LOW_RETENTION_PCT


def test_rule_summary_produces_nonempty_sections():
    videos = [_video("A", 1000, 80.0, subs=5), _video("B", 500, 30.0)]
    daily = [_daily("2026-07-06", 100, 50.0, subs=1),   # 이전 주(W28)
             _daily("2026-07-14", 300, 70.0, subs=2)]    # 현재 주(W29)
    facts = compute_report_facts(videos, daily)
    summary = rule_summary(facts)
    assert summary["went_well"] and summary["went_bad"] and summary["improvements"]
    assert all(isinstance(s, str) for s in summary["went_well"])
