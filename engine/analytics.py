"""유튜브 쇼츠 성과 수집 (P-V3 승인 이탈) — docs/deviation-youtube-analytics.md.

채널에 최근 N일(config.YOUTUBE_ANALYTICS_WINDOW_DAYS) 올린 쇼츠의 성과를 끌어와
Supabase youtube_analytics 에 스냅샷 저장한다. 대시보드 /analytics 가 읽는다.

데이터 경로(읽기 전용):
  ① providers.youtube.list_channel_shorts  — Data API: 최근 업로드 중 쇼츠(길이≤180s) 메타
  ② providers.youtube.fetch_video_analytics — Analytics API: 영상별 지표(조회/시청/CTR 등)
  ③ merge_video_metrics                     — video_id 로 조인 + CTR·요약 계산(순수 함수)
  ④ db.upsert_youtube_analytics             — (video_id, snapshot_date) 멱등 upsert

순수 헬퍼(parse_iso8601_duration/is_short/chunked/merge_video_metrics/summarize)는 네트워크
없이 단위 테스트한다(tests/test_analytics.py). 업로드(engine.publish)와 완전 분리 — 쓰기 아님.

실행:
  python -m engine.analytics            # 설정된 모든 채널(언어) 1회 수집
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from typing import Any, Iterable, Iterator

from . import config, db
from .util import log, today_local

_ISO8601_DURATION = re.compile(
    r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def parse_iso8601_duration(duration: str) -> int:
    """ISO8601 기간(예: 'PT1M30S')을 초로 변환. 빈/이상값은 0. (Data API contentDetails.duration)"""
    if not duration:
        return 0
    m = _ISO8601_DURATION.fullmatch(duration.strip())
    if not m:
        return 0
    parts = {k: int(v) for k, v in m.groupdict(default="0").items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def is_short(duration_sec: int) -> bool:
    """쇼츠 판정: 길이가 config.YOUTUBE_SHORTS_MAX_SEC 이하이고 0보다 크면 쇼츠."""
    return 0 < duration_sec <= config.YOUTUBE_SHORTS_MAX_SEC


def chunked(items: Iterable[Any], size: int) -> Iterator[list[Any]]:
    """리스트를 size 개씩 끊어 순회. size≤0 이면 전체를 한 덩어리로."""
    seq = list(items)
    if size <= 0:
        if seq:
            yield seq
        return
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _ctr(views: float, impressions: float) -> float | None:
    """노출 클릭률(%) = 조회수/노출수. 노출수 없으면 None(Analytics 지표 미포함 시)."""
    if not impressions:
        return None
    return round(views / impressions * 100, 2)


def merge_video_metrics(
    videos: list[dict[str, Any]], metrics: dict[str, dict[str, float]], *, lang: str, snapshot_date: str,
) -> list[dict[str, Any]]:
    """쇼츠 메타(videos) + Analytics 지표(metrics)를 video_id 로 조인해 저장 행 리스트로.

    순수 함수(네트워크 없음). Analytics 에 없는 영상은 지표 0 으로 채운다(방금 올려 집계 전).
    """
    rows: list[dict[str, Any]] = []
    for v in videos:
        vid = v["video_id"]
        met = metrics.get(vid, {})
        views = float(met.get("views", v.get("view_count", 0)) or 0)
        impressions = float(met.get("impressions", 0) or 0)  # 있으면 사용(요청 지표에 따라 없을 수 있음)
        rows.append({
            "video_id": vid,
            "lang": lang,
            "snapshot_date": snapshot_date,
            "title": v.get("title", ""),
            "published_at": v.get("published_at") or None,
            "duration_sec": int(v.get("duration_sec", 0) or 0),
            "views": int(views),
            "estimated_minutes_watched": round(float(met.get("estimatedMinutesWatched", 0) or 0), 2),
            "average_view_duration_sec": round(float(met.get("averageViewDuration", 0) or 0), 2),
            "average_view_percentage": round(float(met.get("averageViewPercentage", 0) or 0), 2),
            "likes": int(met.get("likes", v.get("like_count", 0)) or 0),
            "comments": int(met.get("comments", v.get("comment_count", 0)) or 0),
            "shares": int(met.get("shares", 0) or 0),
            "subscribers_gained": int(met.get("subscribersGained", 0) or 0),
            "impressions": int(impressions),
            "ctr_percent": _ctr(views, impressions),
        })
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """수집 행들의 채널 합계·평균 요약(순수 함수) — 로그/리포트용."""
    n = len(rows)
    if n == 0:
        return {"shorts": 0, "total_views": 0, "total_minutes_watched": 0.0,
                "avg_view_percentage": 0.0, "total_likes": 0, "total_subscribers_gained": 0}
    return {
        "shorts": n,
        "total_views": sum(r["views"] for r in rows),
        "total_minutes_watched": round(sum(r["estimated_minutes_watched"] for r in rows), 1),
        "avg_view_percentage": round(sum(r["average_view_percentage"] for r in rows) / n, 1),
        "total_likes": sum(r["likes"] for r in rows),
        "total_subscribers_gained": sum(r["subscribers_gained"] for r in rows),
    }


# ─────────────────────────────────────────────────────────────
# 채널 날짜별 시계열 (일간/주간/월간)  — dimensions=day 수집
# ─────────────────────────────────────────────────────────────
def build_daily_rows(daily: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """fetch_channel_daily 응답을 youtube_analytics_daily 저장 행으로 정규화(순수 함수)."""
    rows: list[dict[str, Any]] = []
    for d in daily:
        if not d.get("day"):
            continue
        rows.append({
            "lang": lang,
            "day": str(d["day"]),
            "views": int(d.get("views", 0) or 0),
            "estimated_minutes_watched": round(float(d.get("estimatedMinutesWatched", 0) or 0), 2),
            "average_view_percentage": round(float(d.get("averageViewPercentage", 0) or 0), 2),
            "likes": int(d.get("likes", 0) or 0),
            "comments": int(d.get("comments", 0) or 0),
            "shares": int(d.get("shares", 0) or 0),
            "subscribers_gained": int(d.get("subscribersGained", 0) or 0),
        })
    return rows


def iso_week_key(date_str: str) -> str:
    """ISO 주 키(예: '2026-W29'). 주간 버킷팅용(순수 함수)."""
    y, w, _ = date.fromisoformat(date_str).isocalendar()
    return f"{y}-W{w:02d}"


def month_key(date_str: str) -> str:
    """월 키(예: '2026-07'). 월간 버킷팅용(순수 함수)."""
    return date_str[:7]


def pct_delta(cur: float, prev: float) -> float | None:
    """전기간 대비 증감률(%). 이전값 0/없음이면 None(0으로 나눔 방지)."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def aggregate_by_period(daily_rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """일별 행을 주/월 버킷으로 합산(순수 함수). 시청지속률은 조회수 가중 평균.

    period: 'weekly' | 'monthly'. 반환은 period 키 오름차순 정렬.
    """
    keyfn = iso_week_key if period == "weekly" else month_key
    buckets: dict[str, dict[str, Any]] = {}
    for r in daily_rows:
        k = keyfn(r["day"])
        b = buckets.get(k)
        if b is None:
            b = {"period": k, "views": 0, "estimated_minutes_watched": 0.0,
                 "subscribers_gained": 0, "likes": 0, "comments": 0, "shares": 0,
                 "days": 0, "_wsum": 0.0}
            buckets[k] = b
        views = int(r.get("views", 0) or 0)
        b["views"] += views
        b["estimated_minutes_watched"] += float(r.get("estimated_minutes_watched", 0) or 0)
        b["subscribers_gained"] += int(r.get("subscribers_gained", 0) or 0)
        b["likes"] += int(r.get("likes", 0) or 0)
        b["comments"] += int(r.get("comments", 0) or 0)
        b["shares"] += int(r.get("shares", 0) or 0)
        b["days"] += 1
        b["_wsum"] += float(r.get("average_view_percentage", 0) or 0) * views
    out: list[dict[str, Any]] = []
    for k in sorted(buckets):
        b = buckets[k]
        wsum = b.pop("_wsum")
        b["average_view_percentage"] = round(wsum / b["views"], 2) if b["views"] else 0.0
        b["estimated_minutes_watched"] = round(b["estimated_minutes_watched"], 2)
        out.append(b)
    return out


def collect_channel_daily(lang: str, days: int) -> list[dict[str, Any]]:
    """한 채널(언어)의 최근 days 일 날짜별 채널 지표 수집(네트워크). 저장은 하지 않는다."""
    from .providers import youtube  # 지연 임포트

    start = today_local() - timedelta(days=max(0, days - 1))
    end = today_local()
    daily = youtube.fetch_channel_daily(lang, start.isoformat(), end.isoformat())
    rows = build_daily_rows(daily, lang)
    log.info("일별 성과 수집(%s): %d일", lang, len(rows))
    return rows


def collect_channel(lang: str, days: int, snapshot_date: str) -> list[dict[str, Any]]:
    """한 채널(언어)의 최근 days 일 쇼츠 성과 행 수집(네트워크). 저장은 하지 않는다."""
    from .providers import youtube  # 지연 임포트(googleapiclient 는 이 워커에만 필요)

    start = today_local() - timedelta(days=max(0, days - 1))
    start_date = start.isoformat()
    videos = youtube.list_channel_shorts(lang, since_date=start_date)
    if not videos:
        log.info("성과 수집(%s): 최근 %d일 쇼츠 없음", lang, days)
        return []
    metrics = youtube.fetch_video_analytics(
        lang, [v["video_id"] for v in videos], start_date=start_date, end_date=snapshot_date)
    rows = merge_video_metrics(videos, metrics, lang=lang, snapshot_date=snapshot_date)
    log.info("성과 수집(%s): %s", lang, summarize(rows))
    return rows


def run(langs: list[str] | None = None, days: int | None = None) -> int:
    """설정된 채널들을 수집해 Supabase 에 upsert. 반환: 저장한 행 수."""
    if not config.YOUTUBE_ANALYTICS_ENABLED:
        log.info("YOUTUBE_ANALYTICS_ENABLED=false — 성과 수집 건너뜀")
        return 0
    langs = langs or list(config.YOUTUBE_ANALYTICS_TOKEN_SECRET_BY_LANG.keys())
    days = days if days is not None else config.YOUTUBE_ANALYTICS_WINDOW_DAYS
    snapshot_date = today_local().isoformat()

    daily_days = config.YOUTUBE_ANALYTICS_DAILY_LOOKBACK_DAYS
    total = 0
    for lang in langs:
        try:
            rows = collect_channel(lang, days, snapshot_date)
        except Exception as exc:  # noqa: BLE001 — 한 채널 실패가 다른 채널을 막지 않게
            log.exception("성과 수집 실패(%s): %s", lang, exc)
            continue
        if rows:
            db.upsert_youtube_analytics(rows)
            total += len(rows)
        # 날짜별 시계열(일간/주간/월간 리포트용) — 실패해도 스냅샷 수집은 유지.
        try:
            daily_rows = collect_channel_daily(lang, daily_days)
            if daily_rows:
                db.upsert_youtube_analytics_daily(daily_rows)
        except Exception as exc:  # noqa: BLE001
            log.exception("일별 성과 수집 실패(%s): %s", lang, exc)
    log.info("성과 수집 완료: %d행 (snapshot=%s)", total, snapshot_date)
    return total


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        log.exception("analytics 실패: %s", exc)
        sys.exit(1)
