"""리포트 daily_batch 산출 (명세 3-2).

관심순 / 스토리순 / 안전순 상위에서 라운드로빈으로 합쳐 중복 없는 상위 N.
ARIA 신호 강도(aria_priority)는 LLM 채점과 분리해 정렬 동점 보정에만 쓴다(명세 3-1).
"""

from __future__ import annotations

from typing import Any

from . import config


def build_report_batch_rows(
    batch_date: str,
    scores: list[dict[str, Any]],
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """3개 정렬 모드(관심/스토리/안전)의 상위를 라운드로빈으로 합쳐 중복 없는 상위 N.

    각 행: {batch_date, report_id, rank, sort_mode}. sort_mode 는 '선정 사유' 모드.
    exclude_ids: 이전 배치에 이미 등장한 리포트(신선도 위해 후보에서 제외).
    """
    if exclude_ids:
        scores = [s for s in scores if s.get("report_id") not in exclude_ids]

    def _prio(s: dict[str, Any]) -> float:
        # ARIA 신호 강도 = 동점 보정(2차 키). 없으면 0.
        return float(s.get("aria_priority") or 0)

    def key_interest(s: dict[str, Any]) -> tuple[float, float]:
        return (float(s.get("interest_index") or 0), _prio(s))

    def key_story(s: dict[str, Any]) -> tuple[float, float]:
        return (float(s.get("story_index") or 0), _prio(s))

    def key_safety(s: dict[str, Any]) -> tuple[float, float]:
        return (float(s.get("safety_index") or 0), _prio(s))

    ranked = {
        "interest": sorted(scores, key=key_interest, reverse=True),
        "story": sorted(scores, key=key_story, reverse=True),
        "safety": sorted(scores, key=key_safety, reverse=True),
    }

    chosen: list[tuple[str, str]] = []  # (report_id, sort_mode)
    seen: set[str] = set()
    ptr = {mode: 0 for mode in config.REPORT_SORT_MODES}
    # 라운드로빈: interest→story→safety 순으로 각 모드의 다음 미선정 후보를 한 건씩.
    while len(chosen) < config.REPORT_DAILY_BATCH_SIZE:
        progressed = False
        for mode in config.REPORT_SORT_MODES:
            lst = ranked[mode]
            while ptr[mode] < len(lst):
                rid = lst[ptr[mode]]["report_id"]
                ptr[mode] += 1
                if rid not in seen:
                    seen.add(rid)
                    chosen.append((rid, mode))
                    progressed = True
                    break
            if len(chosen) >= config.REPORT_DAILY_BATCH_SIZE:
                break
        if not progressed:  # 모든 모드 소진
            break

    return [
        {"batch_date": batch_date, "report_id": rid, "rank": rank + 1, "sort_mode": mode}
        for rank, (rid, mode) in enumerate(chosen)
    ]
