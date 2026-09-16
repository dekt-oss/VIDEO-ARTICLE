"""daily_batch 산출 (명세 3-4).

재미순 / 중요순 / 황금순(두 지수 곱) 상위에서 합쳐 중복 없는 DAILY_BATCH_SIZE 편.
"""

from __future__ import annotations

from typing import Any

from . import config


def build_batch_rows(
    batch_date: str,
    scores: list[dict[str, Any]],
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """3개 정렬 모드의 상위를 라운드로빈으로 합쳐 중복 없는 상위 N 선정.

    각 행: {batch_date, paper_id, rank, sort_mode}. sort_mode 는 '선정 사유' 모드.
    exclude_ids: 이전 배치에 이미 등장한 논문(신선도 위해 후보에서 제외).
    """
    if exclude_ids:
        scores = [s for s in scores if s.get("paper_id") not in exclude_ids]

    def key_fun(s: dict[str, Any]) -> float:
        return float(s.get("fun_index") or 0)

    def key_imp(s: dict[str, Any]) -> float:
        return float(s.get("importance_index") or 0)

    def key_golden(s: dict[str, Any]) -> float:
        return float(s.get("fun_index") or 0) * float(s.get("importance_index") or 0)

    ranked = {
        "fun": sorted(scores, key=key_fun, reverse=True),
        "importance": sorted(scores, key=key_imp, reverse=True),
        "golden": sorted(scores, key=key_golden, reverse=True),
    }

    chosen: list[tuple[str, str]] = []  # (paper_id, sort_mode)
    seen: set[str] = set()
    ptr = {mode: 0 for mode in config.SORT_MODES}  # 모드별 독립 포인터
    # 라운드로빈: fun→importance→golden 순으로 각 모드의 다음 미선정 후보를 한 편씩.
    while len(chosen) < config.DAILY_BATCH_SIZE:
        progressed = False
        for mode in config.SORT_MODES:
            lst = ranked[mode]
            while ptr[mode] < len(lst):
                pid = lst[ptr[mode]]["paper_id"]
                ptr[mode] += 1
                if pid not in seen:
                    seen.add(pid)
                    chosen.append((pid, mode))
                    progressed = True
                    break
            if len(chosen) >= config.DAILY_BATCH_SIZE:
                break
        if not progressed:  # 모든 모드 소진
            break

    return [
        {"batch_date": batch_date, "paper_id": pid, "rank": rank + 1, "sort_mode": mode}
        for rank, (pid, mode) in enumerate(chosen)
    ]
