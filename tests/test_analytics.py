"""engine.analytics 순수 로직 테스트 (길이 파싱 · 쇼츠 판정 · 조인 · 요약).

네트워크·DB 없이 순수 함수만 검증한다(providers.youtube·db 는 대상 아님).
"""

from engine import config
from engine.analytics import (
    chunked,
    is_short,
    merge_video_metrics,
    parse_iso8601_duration,
    summarize,
)


def test_parse_duration_basic():
    assert parse_iso8601_duration("PT30S") == 30
    assert parse_iso8601_duration("PT1M30S") == 90
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT3M") == 180


def test_parse_duration_edges():
    assert parse_iso8601_duration("") == 0
    assert parse_iso8601_duration("garbage") == 0
    assert parse_iso8601_duration("P1DT1S") == 86401


def test_is_short_boundary():
    # 기본 상한 180초: 이하이면 쇼츠, 초과·0 이하는 아님.
    assert is_short(1) is True
    assert is_short(config.YOUTUBE_SHORTS_MAX_SEC) is True
    assert is_short(config.YOUTUBE_SHORTS_MAX_SEC + 1) is False
    assert is_short(0) is False
    assert is_short(-5) is False


def test_chunked_splits_and_handles_zero():
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunked([], 3)) == []
    # size<=0 이면 전체 한 덩어리(빈 입력은 아무것도 내지 않음).
    assert list(chunked([1, 2], 0)) == [[1, 2]]
    assert list(chunked([], 0)) == []


def _video(vid="v1", **kw):
    base = {
        "video_id": vid, "title": "쇼츠 제목", "published_at": "2026-07-15T09:00:00Z",
        "duration_sec": 45, "view_count": 10, "like_count": 2, "comment_count": 1,
    }
    base.update(kw)
    return base


def test_merge_prefers_analytics_metrics_over_data_stats():
    videos = [_video("v1", view_count=10, like_count=2)]
    metrics = {"v1": {
        "views": 1000, "estimatedMinutesWatched": 50.5, "averageViewDuration": 25.0,
        "averageViewPercentage": 55.5, "likes": 40, "comments": 5, "shares": 3,
        "subscribersGained": 7, "impressions": 8000,
    }}
    rows = merge_video_metrics(videos, metrics, lang="ko", snapshot_date="2026-07-18")
    assert len(rows) == 1
    r = rows[0]
    assert r["views"] == 1000            # Analytics 우선(Data API statistics 아님)
    assert r["likes"] == 40
    assert r["subscribers_gained"] == 7
    assert r["average_view_percentage"] == 55.5
    assert r["ctr_percent"] == 12.5      # 1000/8000*100
    assert r["lang"] == "ko" and r["snapshot_date"] == "2026-07-18"


def test_merge_falls_back_to_data_stats_when_analytics_missing():
    # 방금 올려 Analytics 집계 전 → Data API statistics 로 채우고 CTR 은 None.
    rows = merge_video_metrics([_video("v2", view_count=8, like_count=1)], {},
                               lang="en", snapshot_date="2026-07-18")
    r = rows[0]
    assert r["views"] == 8
    assert r["likes"] == 1
    assert r["impressions"] == 0
    assert r["ctr_percent"] is None      # 노출수 없으면 CTR 없음


def test_summarize_totals_and_average():
    rows = merge_video_metrics(
        [_video("a"), _video("b")],
        {"a": {"views": 100, "averageViewPercentage": 50, "likes": 5, "subscribersGained": 2,
               "estimatedMinutesWatched": 10},
         "b": {"views": 300, "averageViewPercentage": 70, "likes": 9, "subscribersGained": 4,
               "estimatedMinutesWatched": 20}},
        lang="ko", snapshot_date="2026-07-18",
    )
    s = summarize(rows)
    assert s["shorts"] == 2
    assert s["total_views"] == 400
    assert s["avg_view_percentage"] == 60.0    # (50+70)/2
    assert s["total_likes"] == 14
    assert s["total_subscribers_gained"] == 6
    assert s["total_minutes_watched"] == 30.0


def test_summarize_empty():
    assert summarize([])["shorts"] == 0
