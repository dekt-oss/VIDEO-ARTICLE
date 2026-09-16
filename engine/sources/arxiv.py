"""arXiv 수집 (명세 2-1).

Atom API. 키 불필요. 요청 간 3초 간격 + User-Agent 연락처.
arXiv API 는 submittedDate 범위 쿼리를 지원하므로 최신순 정렬로 받아 윈도우로 필터한다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

try:
    import feedparser  # type: ignore
except Exception:  # 일부 환경에서 sdist 빌드 불가 — arXiv 수집만 비활성화하고 OpenAlex 는 계속
    feedparser = None  # type: ignore

from .. import config
from ..models import Paper
from ..util import RateLimiter, arxiv_external_id, http_get, log

_limiter = RateLimiter(config.ARXIV_REQUEST_INTERVAL_SEC)


def _search_query() -> str:
    if config.ARXIV_CATEGORIES:
        return " OR ".join(f"cat:{c}" for c in config.ARXIV_CATEGORIES)
    # 카테고리 미지정 시 전체. all 검색은 무의미하므로 광범위 cat 으로 대체.
    return "cat:cs.* OR cat:stat.* OR cat:q-bio.* OR cat:physics.*"


def _parse_published(entry) -> Optional[date]:
    val = getattr(entry, "published_parsed", None)
    if not val:
        return None
    return datetime(*val[:6], tzinfo=timezone.utc).date()


def collect(start: date, end: date, *, max_results: int = 2000) -> list[Paper]:
    """submittedDate 최신순으로 받아 [start, end] 범위만 채택."""
    if feedparser is None:
        log.warning("feedparser 미설치 — arXiv 수집 건너뜀(OpenAlex 만 사용)")
        return []
    papers: list[Paper] = []
    headers = {"User-Agent": f"video-article/0.1 (mailto:{config.SECRETS.arxiv_contact})"}
    step = 100
    for offset in range(0, max_results, step):
        _limiter.wait()
        params = {
            "search_query": _search_query(),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": offset,
            "max_results": step,
        }
        resp = http_get(config.ARXIV_BASE, params=params, headers=headers)
        feed = feedparser.parse(resp.text)
        if not feed.entries:
            break
        stop = False
        for e in feed.entries:
            pub = _parse_published(e)
            if pub is None:
                continue
            if pub < start:
                stop = True  # 최신순이므로 윈도우 이전이면 이후도 더 과거
                continue
            if pub > end:
                continue
            arxiv_id = (getattr(e, "id", "") or "").split("/abs/")[-1]
            papers.append(Paper(
                external_id=arxiv_external_id(arxiv_id),
                source="arxiv",
                title=(getattr(e, "title", "") or "").replace("\n", " ").strip(),
                abstract=(getattr(e, "summary", "") or "").replace("\n", " ").strip(),
                authors=[{"name": a.get("name")} for a in getattr(e, "authors", []) or []],
                venue="arXiv",
                published_date=pub,
                url=getattr(e, "link", None),
            ))
        if stop:
            break
    log.info("arXiv: %d papers (%s~%s)", len(papers), start, end)
    return papers
