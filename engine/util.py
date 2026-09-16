"""공통 유틸: HTTP(재시도/백오프), 타임존 윈도우, 식별자 추출·정규화, 로깅."""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("engine")


# ─────────────────────────────────────────────────────────────
# 타임존 / 수집 윈도우  (config.TIMEZONE 기준 통일)
# ─────────────────────────────────────────────────────────────
def tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def today_local() -> date:
    return datetime.now(tz()).date()


def collection_window(window_days: Optional[int] = None) -> tuple[date, date]:
    """수집 대상 [시작일, 종료일]. 종료일=오늘(local), 시작일=오늘-(N-1)."""
    n = window_days if window_days is not None else config.COLLECT_WINDOW_DAYS
    end = today_local()
    start = end - timedelta(days=max(0, n - 1))
    return start, end


# ─────────────────────────────────────────────────────────────
# HTTP (지수 백오프 재시도)
# ─────────────────────────────────────────────────────────────
_RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=config.HTTP_BACKOFF_BASE_SEC),
    retry=retry_if_exception_type(_RETRYABLE),
)
def http_get(url: str, *, params: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> httpx.Response:
    """GET + 재시도. 5xx 는 raise_for_status 로 예외화해 재시도 대상에 포함."""
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC, follow_redirects=True) as client:
        resp = client.get(url, params=params, headers=headers)
        if resp.status_code >= 500:
            raise httpx.TransportError(f"{resp.status_code} from {url}")
        resp.raise_for_status()
        return resp


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=config.HTTP_BACKOFF_BASE_SEC),
    retry=retry_if_exception_type(_RETRYABLE),
)
def http_post(url: str, *, json_body: Any = None,
              headers: dict[str, str] | None = None) -> httpx.Response:
    """JSON POST + 재시도. 307/308 리다이렉트는 메서드·본문을 보존해 따라간다(MCP 엔드포인트용)."""
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC, follow_redirects=True) as client:
        resp = client.post(url, json=json_body, headers=headers)
        if resp.status_code >= 500:
            raise httpx.TransportError(f"{resp.status_code} from {url}")
        resp.raise_for_status()
        return resp


def gemini_auth() -> dict[str, str]:
    """Gemini 인증 헤더. ★ 키를 **쿼리스트링에 싣지 않는다.**

    httpx 는 요청 URL 을 INFO 로그에 통째로 찍는다. `?key=…` 로 보내면 그 키가 로컬 로그·
    CI 로그·터미널 기록에 평문으로 남는다(실측: 실측 로그 한 개에 45번 찍혀 있었다).
    헤더로 보내면 같은 요청이 로그에 남아도 키는 남지 않는다.
    """
    return {"x-goog-api-key": config.SECRETS.gemini_api_key}


class RateLimiter:
    """요청 간 최소 간격 보장(예: arXiv 3초, Gemini 무료등급 4.5초).

    ★ 락이 있는 이유: 스레드 여러 개가 동시에 부르면 락 없이는 **셋 다 같은 `_last` 를 보고**
      동시에 통과한다 — 간격 보장이 통째로 무너져 무료등급 RPM 을 넘긴다. 지금까지 호출부가
      단일 스레드였을 뿐이고(수집·채점), 실측 러너처럼 병렬로 부르는 곳이 생기면 즉시 샌다.
      단일 스레드에서는 락 획득 비용만 들 뿐 동작이 같다.
    """

    def __init__(self, min_interval_sec: float) -> None:
        self.min_interval = min_interval_sec
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.monotonic()


# ─────────────────────────────────────────────────────────────
# 식별자 추출 / 정규화  (리뷰 2-2 — 소셜 글에서 DOI/arXiv 추출)
# ─────────────────────────────────────────────────────────────
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ARXIV_BARE_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)


def normalize_doi(doi: str) -> str:
    """DOI 정규화: 소문자, 접두 URL/doi: 제거, 트레일링 구두점 제거."""
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.rstrip(").,;")


def arxiv_external_id(arxiv_id: str) -> str:
    """arXiv ID → 'arxiv:2401.01234' (버전 접미사 제거)."""
    core = re.sub(r"v\d+$", "", arxiv_id.strip().lower())
    return f"arxiv:{core}"


def extract_external_ids(text: str) -> list[str]:
    """임의 텍스트/URL 에서 DOI·arXiv 식별자 추출(정규화·중복제거)."""
    found: list[str] = []
    for m in _ARXIV_RE.finditer(text):
        found.append(arxiv_external_id(m.group(1)))
    for m in _ARXIV_BARE_RE.finditer(text):
        found.append(arxiv_external_id(m.group(1)))
    for m in _DOI_RE.finditer(text):
        found.append(normalize_doi(m.group(0)))
    # 순서 보존 중복제거
    seen: set[str] = set()
    out: list[str] = []
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_title(title: str) -> str:
    """제목 정규화(소문자·구두점/공백 제거) — 보조 중복제거 키."""
    t = title.lower()
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()
