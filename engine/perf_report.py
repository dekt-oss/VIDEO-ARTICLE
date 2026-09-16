"""유튜브 성과 리포트 생성 (P-V3 하이브리드) — docs/deviation-youtube-analytics.md.

하이브리드 = 규칙(코드)으로 근거 지표(facts)를 뽑고 → LLM 이 그 facts 만 보고 '잘된점/잘못된점/
개선방향'을 문장화한다. 대시보드 /analytics/report 가 결과를 읽는다.

환각 방지(프로젝트 P1 불변식과 동일): LLM 입력은 facts "만". "facts 에 없는 수치·주장 금지"를
프롬프트에 명시하고, LLM 실패 시 규칙 기반 요약(rule_summary)으로 폴백한다.

데이터 경로:
  ① db.fetch_latest_video_snapshot   — 최근 스냅샷(per-video, 상/하위 영상)
  ② db.fetch_youtube_analytics_daily  — 날짜별 시계열(주/월 집계)
  ③ compute_report_facts (순수)       — 규칙으로 근거 지표 산출
  ④ narrate                            — LLM 문장화(실패 시 rule_summary)
  ⑤ db.upsert_performance_report      — (period_type, period_start, lang) 멱등 저장

실행:
  python -m engine.perf_report          # 설정된 채널 전부, overall 리포트 1건씩
"""

from __future__ import annotations

import sys
from datetime import timedelta
from typing import Any

from . import analytics, config, db
from .util import log, today_local


# ─────────────────────────────────────────────────────────────
# 규칙 단계 (순수 함수 — 단위 테스트 대상)
# ─────────────────────────────────────────────────────────────
def compute_report_facts(
    video_rows: list[dict[str, Any]], daily_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """스냅샷 + 시계열에서 LLM 문장화의 근거가 될 지표(facts)를 계산(순수 함수)."""
    weekly = analytics.aggregate_by_period(daily_rows, "weekly")
    monthly = analytics.aggregate_by_period(daily_rows, "monthly")

    def _delta(buckets: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
        if len(buckets) < 2:
            return None
        cur, prev = buckets[-1], buckets[-2]
        return {
            "current_period": cur["period"], "previous_period": prev["period"],
            "current": cur[field], "previous": prev[field],
            "delta_pct": analytics.pct_delta(float(cur[field]), float(prev[field])),
        }

    total_views = sum(int(d.get("views", 0) or 0) for d in daily_rows)
    total_minutes = round(sum(float(d.get("estimated_minutes_watched", 0) or 0) for d in daily_rows), 1)
    total_subs = sum(int(d.get("subscribers_gained", 0) or 0) for d in daily_rows)
    wsum = sum(float(d.get("average_view_percentage", 0) or 0) * int(d.get("views", 0) or 0)
               for d in daily_rows)
    avg_ret = round(wsum / total_views, 1) if total_views else 0.0

    by_views = sorted(video_rows, key=lambda r: int(r.get("views", 0) or 0), reverse=True)
    n = config.PERF_TOP_N

    def _vid(r: dict[str, Any]) -> dict[str, Any]:
        return {"title": r.get("title") or r.get("video_id", ""),
                "views": int(r.get("views", 0) or 0),
                "average_view_percentage": float(r.get("average_view_percentage", 0) or 0),
                "subscribers_gained": int(r.get("subscribers_gained", 0) or 0)}

    low_ret = [_vid(r) for r in video_rows
               if float(r.get("average_view_percentage", 0) or 0) < config.PERF_LOW_RETENTION_PCT
               and int(r.get("views", 0) or 0) > 0]

    return {
        "shorts_count": len(video_rows),
        "days_covered": len(daily_rows),
        "totals": {"views": total_views, "minutes_watched": total_minutes,
                   "subscribers_gained": total_subs, "avg_view_percentage": avg_ret},
        "weekly": weekly[-8:],
        "monthly": monthly[-6:],
        "views_wow": _delta(weekly, "views"),
        "subs_wow": _delta(weekly, "subscribers_gained"),
        "views_mom": _delta(monthly, "views"),
        "best_videos": [_vid(r) for r in by_views[:n]],
        "worst_videos": [_vid(r) for r in by_views[-n:][::-1]] if len(by_views) > n else [],
        "low_retention_videos": low_ret[:5],
        "low_retention_threshold": config.PERF_LOW_RETENTION_PCT,
    }


def rule_summary(facts: dict[str, Any]) -> dict[str, list[str]]:
    """LLM 없이 facts 로부터 결정적 요약(폴백/테스트용). 한국어 문장 배열."""
    t = facts.get("totals", {})
    went_well: list[str] = []
    went_bad: list[str] = []
    improvements: list[str] = []

    wow = facts.get("views_wow")
    if wow and wow.get("delta_pct") is not None:
        d = wow["delta_pct"]
        (went_well if d >= 0 else went_bad).append(
            f"주간 조회수가 전주 대비 {d:+.1f}% ({wow['previous']}→{wow['current']}).")
    if t.get("subscribers_gained", 0) > 0:
        went_well.append(f"기간 구독 전환 +{t['subscribers_gained']}명.")
    if facts.get("best_videos"):
        b = facts["best_videos"][0]
        went_well.append(f"최고 성과 쇼츠 '{b['title']}' — 조회 {b['views']}, 시청지속 {b['average_view_percentage']:.0f}%.")

    avg = t.get("avg_view_percentage", 0)
    if avg and avg < facts.get("low_retention_threshold", 40):
        went_bad.append(f"평균 시청 지속률 {avg:.0f}% — 목표({facts.get('low_retention_threshold', 40):.0f}%) 미만.")
    low = facts.get("low_retention_videos") or []
    if low:
        went_bad.append(f"시청 지속률 낮은 쇼츠 {len(low)}편(도입부 이탈 추정).")

    if low:
        improvements.append("이탈 큰 쇼츠는 첫 3초 훅(질문·반전·자막)을 강화한다.")
    if wow and wow.get("delta_pct") is not None and wow["delta_pct"] < 0:
        improvements.append("잘된 쇼츠의 주제·포맷을 다음 편에 반복 적용한다.")
    if not improvements:
        improvements.append("상위 성과 포맷을 유지하고 업로드 빈도를 일정하게 가져간다.")

    return {"went_well": went_well or ["집계할 성과가 부족하다(데이터 누적 필요)."],
            "went_bad": went_bad or ["뚜렷한 약점은 없다(표본 부족일 수 있음)."],
            "improvements": improvements}


# ─────────────────────────────────────────────────────────────
# LLM 문장화 (하이브리드의 두 번째 단계)
# ─────────────────────────────────────────────────────────────
_SYSTEM = (
    "너는 유튜브 쇼츠 채널의 성과 분석가다. 주어진 지표(facts)만 근거로 한국어 리포트를 쓴다. "
    "facts 에 없는 수치·영상·주장은 절대 지어내지 마라. 각 항목은 짧고 구체적인 문장(수치 포함)으로. "
    'JSON 만 출력: {"went_well": [문장...], "went_bad": [문장...], "improvements": [문장...]}. '
    "went_well=잘된점, went_bad=잘못된점, improvements=개선방향. 각 3~5개."
)


def narrate(facts: dict[str, Any], *, model: str | None = None) -> dict[str, list[str]]:
    """facts 를 LLM 으로 문장화. 실패(파싱/네트워크) 시 rule_summary 폴백."""
    import json

    from .llm import call_json

    try:
        out = call_json(
            model=model or config.MODEL_PERF_REPORT,
            system=_SYSTEM,
            user="다음 지표로 리포트를 작성해줘(JSON only):\n" + json.dumps(facts, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001 — 파싱/네트워크 등 어떤 실패든 규칙 요약으로 발행 보장
        log.warning("성과 리포트 LLM 문장화 실패 → 규칙 폴백: %s", exc)
        return rule_summary(facts)

    def _list(key: str) -> list[str]:
        v = out.get(key)
        return [str(x) for x in v] if isinstance(v, list) else []

    result = {"went_well": _list("went_well"), "went_bad": _list("went_bad"),
              "improvements": _list("improvements")}
    # LLM 이 빈 배열만 준 경우에도 규칙 요약으로 보강.
    if not any(result.values()):
        return rule_summary(facts)
    return result


def generate(lang: str, days: int | None = None) -> dict[str, Any]:
    """한 채널의 overall 성과 리포트 1건 생성(네트워크). 반환은 upsert 행 형식."""
    days = days if days is not None else config.YOUTUBE_ANALYTICS_DAILY_LOOKBACK_DAYS
    start = today_local() - timedelta(days=max(0, days - 1))
    video_rows = db.fetch_latest_video_snapshot(lang)
    daily_rows = db.fetch_youtube_analytics_daily(lang, start.isoformat())
    facts = compute_report_facts(video_rows, daily_rows)
    narrative = narrate(facts)
    return {
        "period_type": "overall",
        "period_start": start.isoformat(),
        "period_end": today_local().isoformat(),
        "lang": lang,
        "went_well": narrative["went_well"],
        "went_bad": narrative["went_bad"],
        "improvements": narrative["improvements"],
        "facts": facts,
    }


def run(langs: list[str] | None = None) -> int:
    """설정된 채널마다 overall 리포트를 생성·저장. 반환: 저장한 리포트 수."""
    if not config.YOUTUBE_ANALYTICS_ENABLED:
        log.info("YOUTUBE_ANALYTICS_ENABLED=false — 성과 리포트 건너뜀")
        return 0
    langs = langs or list(config.YOUTUBE_ANALYTICS_TOKEN_SECRET_BY_LANG.keys())
    count = 0
    for lang in langs:
        try:
            report = generate(lang)
        except Exception as exc:  # noqa: BLE001 — 한 채널 실패가 다른 채널을 막지 않게
            log.exception("성과 리포트 생성 실패(%s): %s", lang, exc)
            continue
        db.upsert_performance_report(report)
        count += 1
    log.info("성과 리포트 완료: %d건", count)
    return count


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        log.exception("perf_report 실패: %s", exc)
        sys.exit(1)
