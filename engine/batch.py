"""daily_batch 산출 (명세 3-4).

재미순 / 중요순 / 황금순(두 지수 곱) 상위에서 합쳐 중복 없는 DAILY_BATCH_SIZE 편.
"""

from __future__ import annotations

from datetime import date, timedelta
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
    # 라운드로빈: 한 바퀴에 각 모드가 config.BATCH_MODE_SLOTS 만큼 가져간다.
    # ★ 균등(1:1:1)이 아니다 — 황금이 2자리다. 근거는 그 상수의 주석(실측 낙점률).
    #   슬롯 수가 0 이면 그 정렬은 자리를 안 받는다(끄고 싶을 때 쓰는 문).
    while len(chosen) < config.DAILY_BATCH_SIZE:
        progressed = False
        for mode in config.SORT_MODES:
            lst = ranked[mode]
            for _ in range(max(0, int(config.BATCH_MODE_SLOTS.get(mode, 1)))):
                if len(chosen) >= config.DAILY_BATCH_SIZE:
                    break
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


def within_window(papers: list[dict[str, Any]], today: date,
                  max_age_days: int | None = None) -> list[dict[str, Any]]:
    """나이 상한 안에 드는 논문만. 순수 함수.

    ★ 왜 필요한가: 이 창은 원래 **코드에 없었다.** `fetch_papers_to_score` 의 조건 없는
      select 가 1,000행에서 잘리면서 "가장 최근 1,000편"(≈21일)이 우연히 창 노릇을 했다.
      잘림을 고치는 순간 후보 풀이 2007년까지 열리므로, 같은 창을 명시로 세운다
      (`config.BATCH_MAX_AGE_DAYS`). 근거는 그 상수의 주석에 있다.

    ★ 날짜가 없는 행은 **남긴다.** 버리면 수집 경로가 발행일을 못 채운 논문이 조용히
      사라진다 — 없는 값을 "오래됐다"로 읽지 않는다.
    """
    n = config.BATCH_MAX_AGE_DAYS if max_age_days is None else max_age_days
    if n <= 0:
        return list(papers)
    floor = today - timedelta(days=n)
    out = []
    for p in papers:
        raw = str(p.get("published_date") or "")[:10]
        if not raw:
            out.append(p)
            continue
        try:
            if date.fromisoformat(raw) >= floor:
                out.append(p)
        except ValueError:
            out.append(p)        # 읽을 수 없는 값도 버리지 않는다
    return out
