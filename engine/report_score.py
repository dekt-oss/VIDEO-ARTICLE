"""리포트 채점 오케스트레이터 (명세 §3). 로컬 수동 실행: ``python -m engine.report_score``.

채점 미완료 reports → 4축 LLM 채점 → 정렬 지수 계산 → report_scores 적재 → report_daily_batch 재생성.
"""

from __future__ import annotations

import os
import sys

from . import config, report_batch, report_db, report_scoring
from .llm import JSONParseError, call_json
from .util import log, today_local


def _score_one(report: dict) -> dict:
    """리포트 1건 채점 → report_scores 행 dict."""
    try:
        obj = call_json(
            model=config.MODEL_REPORT_SCORING,
            system=report_scoring.REPORT_SCORING_SYSTEM,
            user=report_scoring.scoring_user_prompt(report),
        )
        axes = report_scoring.parse_axes(obj)
    except JSONParseError as exc:
        log.warning("리포트 채점 실패(JSON 파싱) report=%s: %s", report.get("external_id"), exc)
        axes = report_scoring.zero_axes("JSON 파싱 불가")
    except Exception as exc:  # noqa: BLE001 — API/네트워크 오류도 0점 처리하되 원인 구분해 남긴다
        log.warning("리포트 채점 실패(API/네트워크) report=%s: %s", report.get("external_id"), exc)
        axes = report_scoring.zero_axes(f"API 오류: {str(exc)[:80]}")

    # 채점이 title_ko 를 못 만든 경우 원 제목으로 폴백(대시보드 한/영 혼재 방지).
    if not (axes.get("title_ko") or "").strip():
        axes["title_ko"] = report.get("title") or ""

    return {
        "report_id": report["id"],
        **{k: axes[k] for k in ("timeliness", "explainability", "story", "safety")},
        "interest_index": report_scoring.interest_index(axes),
        "story_index": report_scoring.story_index(axes),
        "safety_index": report_scoring.safety_index(axes),
        "title_ko": axes["title_ko"],
        "one_liner_ko": axes["one_liner_ko"],
        "one_liner_en": axes["one_liner_en"],
        "angle": axes["angle"],
        "risk_note": axes["risk_note"],
        "model": config.MODEL_REPORT_SCORING,
    }


def run(only_unscored: bool = True, limit: int | None = None) -> int:
    log.info("=== report_score: 시작 ===")
    if limit is None:
        env_limit = os.getenv("REPORT_SCORE_LIMIT")
        limit = int(env_limit) if env_limit and env_limit.strip() else None
    reports = report_db.fetch_reports_to_score(only_unscored=only_unscored, limit=limit)
    log.info("채점 대상: %d reports%s", len(reports), f" (limit={limit})" if limit else "")

    score_rows = [_score_one(r) for r in reports]
    report_db.upsert_report_scores(score_rows)

    # report_daily_batch 는 그날의 전체 report_scores 기준으로 재생성(멱등).
    batch_date = today_local().isoformat()
    all_ids = report_db.fetch_report_ids_all()
    all_scores = report_db.fetch_report_scores_for(all_ids)
    # 채점이 안 된 리포트도 지수 0 행으로 배치 후보에 포함한다 — LLM 쿼터 소진·부분 채점(limit)
    # 날에도 aria_priority(2차 키) 순으로 후보가 차게 하는 폴백. 채점되면 다음 재생성에서 대체.
    scored_ids = {s["report_id"] for s in all_scores}
    all_scores += [
        {"report_id": rid, "interest_index": 0.0, "story_index": 0.0, "safety_index": 0.0}
        for rid in all_ids if rid not in scored_ids
    ]
    # ARIA 신호 강도를 정렬 동점 보정용으로 각 점수 행에 병합.
    prio = report_db.fetch_reports_aria_priority([s["report_id"] for s in all_scores])
    for s in all_scores:
        s["aria_priority"] = prio.get(s["report_id"], 0.0)

    exclude = (report_db.fetch_prior_report_batch_ids(batch_date)
               if config.REPORT_BATCH_EXCLUDE_PRIOR else None)
    rows = report_batch.build_report_batch_rows(batch_date, all_scores, exclude_ids=exclude)
    report_db.replace_report_daily_batch(batch_date, rows)
    if exclude:
        log.info("배치 신선도 필터: 이전 등장 %d건 제외", len(exclude))

    log.info("=== report_score 완료: %d 채점, report_daily_batch[%s] %d 건 ===",
             len(score_rows), batch_date, len(rows))
    return len(score_rows)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        log.exception("report_score 실패: %s", exc)
        sys.exit(1)
