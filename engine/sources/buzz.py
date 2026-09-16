"""화제성 신호 수집 (명세 2-2, 리뷰 2-2 역방향 매칭).

순서: 소셜(HN/Reddit) 최신 글을 먼저 수집 → 글의 링크/본문에서 DOI·arXiv ID 추출
→ 정규화된 external_id 별로 점수 집계. papers 와의 조인은 merge 단계에서 수행한다.
"""

from __future__ import annotations

import time
from typing import Any

import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from .. import config
from ..models import BuzzSignal, Paper
from ..util import RateLimiter, extract_external_ids, http_get, log
from . import openalex

_arxiv_limiter = RateLimiter(config.ARXIV_REQUEST_INTERVAL_SEC)


def _from_hn(window_days: int) -> list[BuzzSignal]:
    since = int(time.time()) - window_days * 86400
    signals: list[BuzzSignal] = []
    for domain in config.PAPER_LINK_DOMAINS:
        params = {
            "query": domain,
            "tags": "story",
            "numericFilters": f"created_at_i>{since}",
            "hitsPerPage": 200,
        }
        try:
            resp = http_get(config.HN_ALGOLIA_BASE, params=params)
        except Exception as exc:  # 한 도메인 실패가 전체를 죽이지 않게
            log.warning("HN fetch 실패(%s): %s", domain, exc)
            continue
        for hit in resp.json().get("hits", []):
            text = " ".join(filter(None, [hit.get("url"), hit.get("title"), hit.get("story_text")]))
            for ext in extract_external_ids(text or ""):
                signals.append(BuzzSignal(
                    external_id=ext,
                    source="hn",
                    score=int(hit.get("points") or 0),
                    num_comments=int(hit.get("num_comments") or 0),
                    permalink=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                ))
    return signals


def _reddit_token() -> str | None:
    s = config.SECRETS
    if not (s.reddit_client_id and s.reddit_client_secret):
        return None
    import httpx
    try:
        resp = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(s.reddit_client_id, s.reddit_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": s.reddit_user_agent},
            timeout=config.HTTP_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as exc:
        log.warning("Reddit 토큰 실패: %s", exc)
        return None


def _from_reddit() -> list[BuzzSignal]:
    s = config.SECRETS
    token = _reddit_token()
    headers = {"User-Agent": s.reddit_user_agent}
    if token:
        headers["Authorization"] = f"bearer {token}"
        host = "https://oauth.reddit.com"
    else:
        host = "https://www.reddit.com"  # 공개 JSON 폴백
    signals: list[BuzzSignal] = []
    for sub in config.REDDIT_SUBREDDITS:
        url = f"{host}/r/{sub}/new.json"
        try:
            resp = http_get(url, params={"limit": 100}, headers=headers)
        except Exception as exc:
            log.warning("Reddit fetch 실패(%s): %s", sub, exc)
            continue
        for child in resp.json().get("data", {}).get("children", []):
            d: dict[str, Any] = child.get("data", {})
            text = " ".join(filter(None, [d.get("url"), d.get("title"), d.get("selftext")]))
            for ext in extract_external_ids(text or ""):
                signals.append(BuzzSignal(
                    external_id=ext,
                    source="reddit",
                    score=int(d.get("score") or 0),
                    num_comments=int(d.get("num_comments") or 0),
                    permalink=f"https://reddit.com{d.get('permalink', '')}",
                ))
    return signals


def collect(window_days: int | None = None) -> dict[str, dict[str, Any]]:
    """external_id → buzz_raw dict 집계.

    buzz_raw = {"hn_points","hn_comments","reddit_score","reddit_comments","total","links":[...]}
    """
    n = window_days if window_days is not None else config.COLLECT_WINDOW_DAYS
    signals = _from_hn(n) + _from_reddit()
    agg: dict[str, dict[str, Any]] = {}
    for sig in signals:
        a = agg.setdefault(sig.external_id, {
            "hn_points": 0, "hn_comments": 0,
            "reddit_score": 0, "reddit_comments": 0,
            "total": 0, "links": [],
        })
        if sig.source == "hn":
            a["hn_points"] += sig.score
            a["hn_comments"] += sig.num_comments
        else:
            a["reddit_score"] += sig.score
            a["reddit_comments"] += sig.num_comments
        a["total"] = a["hn_points"] + a["reddit_score"]
        if sig.permalink:
            a["links"].append(sig.permalink)
    log.info("buzz: %d signals → %d papers matched", len(signals), len(agg))
    return agg


# ─────────────────────────────────────────────────────────────
# HN-우선 인테이크 (리뷰 #3): buzz 매칭된 식별자의 메타데이터를 채워 Paper 로.
# 동료리뷰 필터를 거치지 않으므로 프리프린트(arXiv)도 포함된다 — HN 화제 반영용.
# ─────────────────────────────────────────────────────────────
def _fetch_doi_paper(doi: str, buzz_raw: dict[str, Any]) -> Paper | None:
    try:
        resp = http_get(f"{config.OPENALEX_BASE}/doi:{doi}",
                        params={"mailto": config.SECRETS.openalex_mailto})
        w = resp.json()
    except Exception as exc:
        log.warning("buzz DOI 메타 실패(%s): %s", doi, exc)
        return None
    abstract = openalex.reconstruct_abstract(w.get("abstract_inverted_index"))
    if not abstract:
        return None
    return Paper(
        external_id=doi, source="openalex",
        title=w.get("title") or "", abstract=abstract,
        authors=openalex._authors(w), venue=openalex._venue(w),
        published_date=openalex._parse_date(w.get("publication_date")),
        url=w.get("doi"), buzz_raw=buzz_raw,
    )


def _fetch_arxiv_paper(arxiv_id: str, buzz_raw: dict[str, Any]) -> Paper | None:
    bare = arxiv_id.replace("arxiv:", "")
    _arxiv_limiter.wait()
    headers = {"User-Agent": f"video-article/0.1 (mailto:{config.SECRETS.arxiv_contact})"}
    try:
        resp = http_get(config.ARXIV_BASE, params={"id_list": bare, "max_results": 1},
                        headers=headers)
        root = ET.fromstring(resp.text)
    except Exception as exc:
        log.warning("buzz arXiv 메타 실패(%s): %s", arxiv_id, exc)
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    title = (entry.findtext("a:title", default="", namespaces=ns) or "").replace("\n", " ").strip()
    summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").replace("\n", " ").strip()
    if not summary:
        return None
    published = entry.findtext("a:published", default="", namespaces=ns)
    pub: date | None = None
    if published:
        try:
            pub = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(timezone.utc).date()
        except ValueError:
            pub = None
    link = entry.findtext("a:id", default=None, namespaces=ns)
    return Paper(
        external_id=arxiv_id, source="arxiv", title=title, abstract=summary,
        authors=[], venue="arXiv", published_date=pub, url=link, buzz_raw=buzz_raw,
    )


def fetch_buzz_papers(buzz_map: dict[str, dict[str, Any]]) -> list[Paper]:
    """buzz 매칭 식별자 → 메타데이터 채운 Paper 목록(buzz_raw 부착)."""
    papers: list[Paper] = []
    for ext, raw in buzz_map.items():
        if ext.startswith("arxiv:"):
            p = _fetch_arxiv_paper(ext, raw)
        else:
            p = _fetch_doi_paper(ext, raw)
        if p:
            papers.append(p)
    log.info("HN-우선 인테이크: %d/%d papers 메타데이터 확보", len(papers), len(buzz_map))
    return papers
