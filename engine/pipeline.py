"""병합·중복제거 → 1차 필터 (명세 2-3, 2-4 / 리뷰 2-1).

- 중복 키 우선순위: DOI > arXiv ID > (제목 정규화 + 첫 저자).
- 1차 필터: 초록 존재 + 언어(영/한). buzz 는 통과조건이 아니라 정렬 가점.
- 컷오프: 발행 최신순 + buzz 가점으로 상위 N 편만 2차 채점에 넘김.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import config
from .models import Paper
from .util import log, normalize_title

try:
    from langdetect import detect as _detect  # type: ignore
except Exception:  # 라이브러리 미설치 시에도 모듈 임포트는 되게
    _detect = None


def _detect_lang(text: str) -> str | None:
    if not text or _detect is None:
        return None
    try:
        return _detect(text[:1000])
    except Exception:
        return None


def dedupe(papers: list[Paper]) -> list[Paper]:
    """DOI > arXiv > (제목+첫저자) 우선순위로 중복 제거."""
    by_key: dict[str, Paper] = {}
    title_keys: dict[str, str] = {}  # 제목키 → external_id (보조 매칭)

    def first_author(p: Paper) -> str:
        return (p.authors[0].get("name") or "").lower() if p.authors else ""

    for p in papers:
        # external_id(DOI 또는 arxiv:) 기준 1차
        if p.external_id in by_key:
            _merge_into(by_key[p.external_id], p)
            continue
        # 제목+첫저자 보조 중복 판정
        tkey = f"{normalize_title(p.title)}|{first_author(p)}"
        if tkey in title_keys:
            existing = by_key[title_keys[tkey]]
            _merge_into(existing, p)
            continue
        by_key[p.external_id] = p
        if tkey.strip("|"):
            title_keys[tkey] = p.external_id
    out = list(by_key.values())
    log.info("dedupe: %d → %d", len(papers), len(out))
    return out


def _merge_into(keep: Paper, other: Paper) -> None:
    """중복 병합: 더 긴 초록·venue·buzz 를 보존(DOI 소스를 우선 신뢰)."""
    if len(other.abstract or "") > len(keep.abstract or ""):
        keep.abstract = other.abstract
    if not keep.venue and other.venue:
        keep.venue = other.venue
    if other.buzz_raw and not keep.buzz_raw:
        keep.buzz_raw = other.buzz_raw


def attach_buzz(papers: list[Paper], buzz: dict[str, dict[str, Any]]) -> None:
    """external_id 로 buzz_raw 부착(in-place)."""
    matched = 0
    for p in papers:
        b = buzz.get(p.external_id)
        if b:
            p.buzz_raw = b
            matched += 1
    log.info("attach_buzz: %d/%d papers matched", matched, len(papers))


def primary_filter(papers: list[Paper]) -> list[Paper]:
    """초록 존재 + 언어(영/한) 통과. buzz 가점으로 정렬 후 상위 N 컷오프."""
    passed: list[Paper] = []
    for p in papers:
        if len(p.abstract or "") < config.PRIMARY_FILTER_MIN_ABSTRACT_CHARS:
            continue
        lang = _detect_lang(p.abstract) or _detect_lang(p.title)
        p.lang = lang
        # 언어 판별 불가 시 보수적으로 통과시키되, 명확히 비대상 언어면 제외
        if lang is not None and lang not in config.PRIMARY_FILTER_LANGS:
            continue
        passed.append(p)

    def sort_key(p: Paper) -> tuple[float, str]:
        buzz_total = float((p.buzz_raw or {}).get("total", 0))
        pub = p.published_date.isoformat() if p.published_date else ""
        return (buzz_total, pub)  # buzz 가점 우선, 그다음 최신순

    # 프리스티지 바이패스(수집지시서 v2 §4-2): 플래그십은 화제성 없어도 2차 채점 진입을 보장한다.
    # 컷오프(상위 N)는 비플래그십에만 적용 — 플래그십이 buzz=0 으로 컷 밖으로 밀려나는 것을 방지.
    # (바이패스=진입 보장이지 최종 선정 보장 아님. 진입 후엔 기존 5축 채점이 정상 심사.)
    flagship = [p for p in passed if getattr(p, "is_flagship", False)]
    rest = [p for p in passed if not getattr(p, "is_flagship", False)]
    rest.sort(key=sort_key, reverse=True)
    flagship.sort(key=sort_key, reverse=True)
    cut = flagship + rest[: config.SCORE_CUTOFF_N]
    log.info("primary_filter: %d passed → %d after cutoff(N=%d, flagship bypass=%d)",
             len(passed), len(cut), config.SCORE_CUTOFF_N, len(flagship))
    return cut
