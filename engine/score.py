"""채점 오케스트레이터 (명세 9-3). 로컬 수동 실행: ``python -m engine.score``.

채점 미완료 papers → 5축 LLM 채점 → 지수 계산 → scores 적재 → daily_batch 재생성.
"""

from __future__ import annotations

import os
import sys

from . import batch, config, db, scoring, translate
from .llm import JSONParseError, call_json
from .util import log, today_local


def _score_one(paper: dict) -> dict:
    """논문 1편 채점 → scores 행 dict."""
    try:
        obj = call_json(
            model=config.MODEL_SCORING,
            system=scoring.SCORING_SYSTEM,
            user=scoring.scoring_user_prompt(
                paper.get("title") or "", paper.get("venue"), paper.get("abstract") or ""
            ),
        )
        axes = scoring.parse_axes(obj)
    except JSONParseError as exc:
        log.warning("채점 실패(JSON 파싱) paper=%s: %s", paper.get("external_id"), exc)
        axes = scoring.zero_axes("JSON 파싱 불가")
    except Exception as exc:  # noqa: BLE001 — API/네트워크 오류도 0점 처리하되 원인을 구분해 남긴다
        log.warning("채점 실패(API/네트워크) paper=%s: %s", paper.get("external_id"), exc)
        axes = scoring.zero_axes(f"API 오류: {str(exc)[:80]}")

    # 채점이 title_ko 를 못 만든 경우(파싱/API 실패 등) 제목만 별도 번역해 폴백.
    # 대시보드가 영어 원제로 폴백해 목록에 영/한이 섞이는 것을 신규 채점부터 방지.
    if not (axes.get("title_ko") or "").strip():
        axes["title_ko"] = translate.translate_title(paper.get("title") or "")

    buzz_norm = scoring.normalize_buzz(paper.get("buzz_raw"))
    sig_eff = scoring.significance_with_boost(axes["significance"], paper.get("venue"))
    fun = scoring.fun_index(axes)
    imp = scoring.importance_index(sig_eff, buzz_norm)

    return {
        "paper_id": paper["id"],
        **{k: axes[k] for k in ("surprise", "explainability", "relatability", "significance")},
        "buzz": buzz_norm,
        "fun_index": fun,
        "importance_index": imp,
        "title_ko": axes["title_ko"],
        "one_liner_ko": axes["one_liner_ko"],
        "one_liner_en": axes["one_liner_en"],
        "rationale": axes["rationale"],
        "red_flag": axes["red_flag"],
        # §6 제작 준비도 5축(0~2)+게이트. 정렬용 지수와 별개(제작 여부 게이트). jsonb 로 저장.
        "production": axes["production"],
        "model": config.MODEL_SCORING,
    }


def run(only_unscored: bool = True, limit: int | None = None) -> int:
    log.info("=== score: 시작 ===")
    # SCORE_LIMIT 환경변수로 1회 채점량을 제한할 수 있다(비용 통제·스모크 테스트).
    if limit is None:
        env_limit = os.getenv("SCORE_LIMIT")
        limit = int(env_limit) if env_limit and env_limit.strip() else None
    papers = db.fetch_papers_to_score(only_unscored=only_unscored, limit=limit)
    log.info("채점 대상: %d papers%s", len(papers), f" (limit={limit})" if limit else "")

    score_rows = [_score_one(p) for p in papers]
    db.upsert_scores(score_rows)

    # daily_batch 는 그날의 전체 scores 기준으로 재생성(멱등).
    batch_date = today_local().isoformat()
    all_scores = db.fetch_scores_for_papers([p["id"] for p in db.fetch_papers_to_score(only_unscored=False)])
    # 신선도: 이전(오늘 이전) 배치에 이미 오른 논문은 후보에서 제외 → 날마다 반복 등장 방지.
    exclude = db.fetch_prior_batch_paper_ids(batch_date) if config.BATCH_EXCLUDE_PRIOR else None
    rows = batch.build_batch_rows(batch_date, all_scores, exclude_ids=exclude)
    db.replace_daily_batch(batch_date, rows)
    if exclude:
        log.info("배치 신선도 필터: 이전 등장 %d편 제외", len(exclude))

    log.info("=== score 완료: %d 채점, daily_batch[%s] %d 편 ===",
             len(score_rows), batch_date, len(rows))
    return len(score_rows)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        log.exception("score 실패: %s", exc)
        sys.exit(1)
