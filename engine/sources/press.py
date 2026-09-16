"""과학 언론 RSS 수집 (수집지시서 v2 §6, P2) — 발견 + 화제성 신호 전용.

역할은 "품질 평가"가 아니라 "DOI/논문 발견 + 화제성 신호"로 한정한다. 언론 본문은 저장·복제하지
않고(저작권 §11), 링크/DOI 추출과 화제성 카운트에만 쓴다. 파서 실패는 로그+무시(전체 중단 금지).

다단계 DOI 매칭(§6): ① DOI 직접 → ② 퍼블리셔 URL 추출 → ③ arXiv ID (①~③은 extract_external_ids
로 커버) → ④⑤ 제목 유사도(수집된 논문과 대조). 자동 연결 조건: title_similarity ≥ 0.94 AND 연도 일치
AND 제1저자 일치. 미달은 unresolved_buzz_items 큐로.

순수 헬퍼(normalize_title_for_match/title_similarity/resolve_press_item/match_to_paper)는 네트워크
없이 단위 테스트한다. collect() 만 feedparser 네트워크를 탄다.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

from .. import config
from ..util import extract_external_ids, log


def normalize_title_for_match(title: str) -> str:
    """제목 유사도 비교용 정규화: 소문자·영숫자만·공백 단일화(구두점/기호 제거)."""
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9가-힣 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_similarity(a: str, b: str) -> float:
    """두 제목의 유사도 0~1(정규화 후 SequenceMatcher). 순수 함수."""
    na, nb = normalize_title_for_match(a), normalize_title_for_match(b)
    if not na or not nb:
        return 0.0
    return round(SequenceMatcher(None, na, nb).ratio(), 4)


def resolve_press_item(item: dict[str, Any]) -> tuple[Optional[str], str]:
    """언론 항목 → (external_id, match_method). ①~③ DOI/arXiv 직접 추출.

    item: {title, url, summary, ...}. url+title+summary 에서 식별자를 뽑는다(순수 함수).
    """
    text = " ".join(str(item.get(k) or "") for k in ("url", "title", "summary"))
    ids = extract_external_ids(text)
    if not ids:
        return None, "none"
    ext = ids[0]
    method = "arxiv" if ext.startswith("arxiv:") else ("url_extract" if "http" in text.lower() else "doi_direct")
    return ext, method


def match_to_paper(item: dict[str, Any], papers: list) -> tuple[Optional[str], float]:
    """④⑤ 제목 유사도로 이미 수집된 논문과 대조(순수 함수). 반환: (external_id or None, best_sim).

    자동 연결: title_similarity ≥ 임계 AND 연도 일치 AND 제1저자 성 일치. 하나라도 미달이면 None.
    """
    title = str(item.get("title") or "")
    year = str(item.get("year") or "")
    first_author = normalize_title_for_match(str(item.get("first_author") or ""))
    best_sim = 0.0
    best_ext: Optional[str] = None
    for p in papers:
        sim = title_similarity(title, getattr(p, "title", "") or "")
        if sim <= best_sim:
            continue
        best_sim = sim
        pub = getattr(p, "published_date", None)
        p_year = str(pub.year) if pub else ""
        authors = getattr(p, "authors", None) or []
        p_first = normalize_title_for_match(str((authors[0] or {}).get("name") or "")) if authors else ""
        year_ok = (not year) or (not p_year) or (year == p_year)
        author_ok = (not first_author) or (first_author and first_author in p_first) or (p_first and p_first in first_author)
        best_ext = getattr(p, "external_id", None) if (
            sim >= config.PRESS_TITLE_SIMILARITY_MIN and year_ok and author_ok) else None
    if best_ext and best_sim >= config.PRESS_TITLE_SIMILARITY_MIN:
        return best_ext, best_sim
    return None, best_sim


def collect() -> list[dict[str, Any]]:
    """설정된 RSS 피드를 파싱해 발견 항목 리스트로. 각 항목: {route, title, url, summary, external_id, method}."""
    if not config.PRESS_ENABLED:
        return []
    import feedparser  # 지연 임포트(이 소스에서만 필요)

    items: list[dict[str, Any]] = []
    for feed in config.PRESS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
        except Exception as exc:  # noqa: BLE001 — 한 피드 실패가 전체를 막지 않게(§6)
            log.warning("RSS 파싱 실패(%s): %s", feed["feed_id"], exc)
            continue
        for e in getattr(parsed, "entries", []) or []:
            item = {
                "route": feed["feed_id"],
                "title": getattr(e, "title", "") or "",
                "url": getattr(e, "link", "") or "",
                "summary": getattr(e, "summary", "") or "",
                "published": getattr(e, "published", "") or "",
            }
            ext, method = resolve_press_item(item)
            item["external_id"] = ext
            item["method"] = method
            items.append(item)
        log.info("RSS[%s]: %d entries", feed["feed_id"], len(getattr(parsed, "entries", []) or []))
    return items
