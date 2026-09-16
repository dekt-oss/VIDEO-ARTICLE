"""P0 합격기준 자동 측정 (명세 8 / 합격기준).

합격: 상위 10편 중 "낙점 가능(shortlisted+picked)" ≥ MIN_PICKS_PER_DAY 편인 날이
최근 WINDOW 일 중 MIN_PASS_DAYS 일 이상.

순수 판정 로직(tally_pass)은 DB 와 무관하게 테스트 가능하다.
실행: ``python -m engine.measure``  (라이브 Supabase 필요)
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import db
from .util import log

# 합격기준 상수 (명세 8)
WINDOW_DAYS = 7
MIN_PICKS_PER_DAY = 3
MIN_PASS_DAYS = 5
ACCEPTABLE_STATUSES = ("shortlisted", "picked")


def day_pick_count(statuses: list[str]) -> int:
    """그날 배치에서 '낙점 가능' 상태 편수."""
    return sum(1 for s in statuses if s in ACCEPTABLE_STATUSES)


def tally_pass(per_day_counts: list[int]) -> dict[str, Any]:
    """일별 낙점가능 편수 리스트 → 합격 여부 판정."""
    pass_days = sum(1 for c in per_day_counts if c >= MIN_PICKS_PER_DAY)
    return {
        "window_days": len(per_day_counts),
        "min_picks_per_day": MIN_PICKS_PER_DAY,
        "min_pass_days": MIN_PASS_DAYS,
        "per_day_counts": per_day_counts,
        "pass_days": pass_days,
        "passed": pass_days >= MIN_PASS_DAYS and len(per_day_counts) >= 1,
    }


def measure() -> dict[str, Any]:
    """라이브 DB 에서 최근 7 배치일을 측정."""
    dates = db.recent_batch_dates(WINDOW_DAYS)
    detail = []
    counts = []
    for d in dates:
        pids = db.batch_paper_ids(d)
        decs = db.decisions_for(pids)
        statuses = [decs.get(p, "") for p in pids]
        c = day_pick_count(statuses)
        counts.append(c)
        detail.append({"date": d, "batch_size": len(pids), "acceptable": c})
    result = tally_pass(counts)
    result["dates"] = detail
    return result


if __name__ == "__main__":
    try:
        report = measure()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        log.info("P0 측정: %s (pass_days=%d/%d)",
                 "합격" if report["passed"] else "미달",
                 report["pass_days"], report["window_days"])
    except Exception as exc:
        log.exception("measure 실패: %s", exc)
        sys.exit(1)
