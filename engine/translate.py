"""제목 한국어 번역 백필 (환각 방지와 무관한 순수 표시용 번역).

배경: 한국어 제목(scores.title_ko)은 원래 5축 채점 단계 산출물이다(engine/scoring.py).
그런데 채점 실패(zero_axes → title_ko="")나 title_ko 컬럼 추가(0005) 이전 채점 행은
title_ko 가 비어, 대시보드가 영어 원제(title_ko || title)로 폴백해 목록에 영/한이 섞인다.

이 모듈은 배치(daily_batch)나 낙점(decisions)에 등장하는 논문 중 title_ko 가 빈 것을 찾아
제목만 저렴하게 번역(claude-sonnet-4-6)해 채워 넣는다. 멱등 — 재실행해도 이미 채운 건 건너뛴다.

실행: ``python -m engine.translate``
"""

from __future__ import annotations

import sys
from typing import Any

from . import config, db
from .llm import JSONParseError, call_json
from .util import log

TRANSLATE_SYSTEM = """너는 학술 논문 제목 번역가다. 주어진 영어(또는 비한국어) 논문 제목을
자연스러운 한국어로 번역한다. 전문용어는 통용 표기를 우선하고, 고유명사·모델명·수식은
원문을 유지해도 된다. 제목만 번역하고 설명·따옴표·주석을 붙이지 마라.
JSON only. 설명 문장·마크다운·코드펜스 금지.
{"title_ko": "<한국어 제목>"}"""


def translate_title(title: str) -> str:
    """제목 1건을 한국어로 번역. 실패 시 빈 문자열(호출자가 스킵)."""
    t = (title or "").strip()
    if not t:
        return ""
    try:
        obj = call_json(
            model=config.MODEL_SCORING,
            system=TRANSLATE_SYSTEM,
            user=f"제목: {t}",
            max_tokens=512,
        )
    except JSONParseError as exc:
        log.warning("제목 번역 실패(JSON 파싱): %s", exc)
        return ""
    except Exception as exc:  # noqa: BLE001 — API/네트워크 오류도 스킵(다음 실행에서 재시도)
        log.warning("제목 번역 실패(API/네트워크): %s", exc)
        return ""
    return str(obj.get("title_ko") or "").strip()


def run(limit: int | None = None) -> int:
    """title_ko 가 빈 대상 논문을 번역해 백필. 반환: 실제로 채운 건수."""
    log.info("=== translate: 시작 ===")
    targets = db.fetch_papers_needing_title_ko(limit=limit)
    log.info("번역 대상: %d papers", len(targets))

    rows: list[dict[str, Any]] = []
    for p in targets:
        ko = translate_title(p.get("title") or "")
        if ko:
            rows.append({"paper_id": p["id"], "title_ko": ko})
    filled = db.upsert_scores(rows)  # partial upsert(title_ko 만 갱신)
    log.info("=== translate 완료: %d/%d 채움 ===", filled, len(targets))
    return filled


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        log.exception("translate 실패: %s", exc)
        sys.exit(1)
