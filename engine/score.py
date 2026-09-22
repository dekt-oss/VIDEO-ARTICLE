"""채점 오케스트레이터 (명세 9-3). 로컬 수동 실행: ``python -m engine.score``.

채점 미완료 papers → 5축 LLM 채점 → 지수 계산 → scores 적재 → daily_batch 재생성.
"""

from __future__ import annotations

import os
import sys

import httpx

from . import batch, config, db, scoring, translate
from .llm import JSONParseError, call_json
from .util import log, today_local


class TransientScoringError(RuntimeError):
    """채점이 **모델의 판정이 아니라 사고**로 실패했다 — 저장하지 않는다.

    ★★ 왜 새로 가르나(2026-09-22 실측). 종전에는 429·타임아웃도 0점으로 **저장**했다.
      저장되는 순간 `fetch_papers_to_score` 가 "채점 완료"로 보기 때문에 그 논문은
      **다시는 채점되지 않는다.** 실측: 저장된 채점 4,650행 중 353행(7.6%)이 그 상태이고
      전부 `429 from gemini` 다. 0점은 후보 목록에 영영 못 오르는데 화면에서는 그냥
      점수 낮은 논문처럼 보인다 — 사장님이 그중 하나를 낙점한 기록이 남아 있다.

    ★ JSON 파싱 실패와는 **일부러 가른다.** 파싱 실패는 모델이 그 초록에 대해 계속
      같은 실수를 할 수 있어 0점 저장이 맞다(재시도는 이미 `call_json` 안에서 했다).
      429·5xx·타임아웃은 논문과 무관한 사고라 다음 실행이 다시 하면 된다.
    """


#: 논문 내용과 무관한 사고. 이 중 하나면 저장하지 않고 다음 실행에 넘긴다.
#: (429·5xx 는 `llm._gemini_create` 가 TransportError 로 바꿔 던지고, tenacity 가
#:  HTTP_MAX_RETRIES 회 백오프한 뒤에도 실패한 것만 여기 온다.)
_TRANSIENT = (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError)


def _score_one(paper: dict) -> dict:
    """논문 1편 채점 → scores 행 dict. 사고면 `TransientScoringError`."""
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
    except _TRANSIENT as exc:
        raise TransientScoringError(f"{type(exc).__name__}: {str(exc)[:80]}") from exc
    except Exception as exc:  # noqa: BLE001 — 설정 오류(401/404 등)는 0점으로 남겨 눈에 띄게 한다
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


def run(only_unscored: bool = True, limit: int | None = None,
        retry_failed: bool = False) -> int:
    log.info("=== score: 시작 ===")
    # SCORE_LIMIT 환경변수로 1회 채점량을 제한할 수 있다(비용 통제·스모크 테스트).
    if limit is None:
        env_limit = os.getenv("SCORE_LIMIT")
        limit = int(env_limit) if env_limit and env_limit.strip() else None
    today = today_local()
    papers = db.fetch_papers_to_score(only_unscored=only_unscored, retry_failed=retry_failed)
    # ★ 화면에 못 올라갈 나이의 논문은 **채점하지 않는다** — 그냥 돈이다.
    #   (limit 은 창을 적용한 뒤 건다. 먼저 자르면 창 밖 논문이 한도를 다 먹는다.)
    before = len(papers)
    papers = batch.within_window(papers, today)
    if before != len(papers):
        log.info("나이 창(%d일) 밖 %d편 제외", config.BATCH_MAX_AGE_DAYS, before - len(papers))
    if limit:
        papers = papers[:limit]
    log.info("채점 대상: %d papers%s%s", len(papers),
             f" (limit={limit})" if limit else "",
             " [실패분 재채점 포함]" if retry_failed else "")

    # ★ 사고로 실패한 것은 **행을 만들지 않는다** — 다음 실행이 다시 집어 간다.
    #   전부 사고면 그것대로 눈에 띄어야 한다(아래 경고).
    score_rows, transient = [], 0
    for p in papers:
        try:
            score_rows.append(_score_one(p))
        except TransientScoringError as exc:
            transient += 1
            log.warning("채점 보류(사고 — 저장 안 함) paper=%s: %s", p.get("external_id"), exc)
    if transient:
        log.warning("채점 보류 %d/%d편 — 다음 실행이 다시 시도한다.", transient, len(papers))
    db.upsert_scores(score_rows)

    # daily_batch 는 **창 안의** scores 기준으로 재생성(멱등).
    batch_date = today.isoformat()
    pool = batch.within_window(db.fetch_papers_to_score(only_unscored=False), today)
    all_scores = db.fetch_scores_for_papers([p["id"] for p in pool])
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
    import argparse

    ap = argparse.ArgumentParser(description="5축 채점 + daily_batch 재생성")
    ap.add_argument("--retry-failed", action="store_true",
                    help="채점이 사고로 실패해 0점으로 저장된 논문을 다시 채점한다(비용 발생)")
    ap.add_argument("--limit", type=int, default=None, help="이번 실행의 채점 상한")
    args = ap.parse_args()
    try:
        run(limit=args.limit, retry_failed=args.retry_failed)
    except Exception as exc:
        log.exception("score 실패: %s", exc)
        sys.exit(1)
