"""엔진 공통 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class Paper:
    """정규화된 논문 메타데이터(소스 무관 공통 스키마)."""

    external_id: str                 # 중복제거 키: DOI(소문자) 또는 'arxiv:ID'
    source: str                      # 'openalex' | 'arxiv'
    title: str
    abstract: str
    authors: list[dict[str, Any]] = field(default_factory=list)
    venue: Optional[str] = None
    published_date: Optional[date] = None
    url: Optional[str] = None
    lang: Optional[str] = None
    buzz_raw: Optional[dict[str, Any]] = None
    # 수집 커버리지 v2 — 플래그십/진단/발견 보강용(가시성·바이패스 판정).
    doi: Optional[str] = None                 # 정규화 DOI(external_id 와 동일하나 명시 컬럼)
    work_type: Optional[str] = None           # OpenAlex type(article|review|editorial…)
    openalex_id: Optional[str] = None         # OpenAlex work id(진단·역참조)
    source_id: Optional[str] = None           # OpenAlex primary_location.source.id(플래그십 판정)
    source_created_date: Optional[date] = None  # OpenAlex 등록일(created_date, 지연 진단)
    is_flagship: bool = False                 # 플래그십 저널 여부(프리스티지 바이패스)

    def to_row(self) -> dict[str, Any]:
        """Supabase papers 테이블 upsert 용 dict."""
        return {
            "external_id": self.external_id,
            "source": self.source,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "venue": self.venue,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "url": self.url,
            "lang": self.lang,
            "buzz_raw": self.buzz_raw,
            "doi": self.doi,
            "work_type": self.work_type,
            "openalex_id": self.openalex_id,
            "source_created_date": self.source_created_date.isoformat() if self.source_created_date else None,
        }


@dataclass
class Report:
    """정규화된 증권사 리포트/신호 메타데이터(ARIA 신호 → reports 공통 스키마).

    저작권 안전장치(명세 §2): 원문 전문(raw_content)은 저장하지 않는다 —
    summary 는 Fact Sheet 추출용 요약만, 산출물(자막·나레이션)은 자체 표현만 쓴다.
    """

    external_id: str                 # 중복제거 키: 'aria_signal:{id}' 또는 'aria_research:{id}'
    source: str                      # 'aria_signal' | 'aria_research'
    title: str
    summary: str                     # 핵심요약(원문 전문 아님) — REPORT_SUMMARY_MAX_CHARS 로 제한
    theme: Optional[str] = None      # ARIA 테마(예: '메모리반도체')
    company: Optional[str] = None    # 종목/테마명(있으면)
    ticker: Optional[str] = None     # 종목코드(있으면, 예: '000660')
    broker: Optional[str] = None     # 증권사/채널(출처)
    analyst: Optional[str] = None    # 애널리스트(출처)
    target_price: Optional[float] = None  # broker_targets 목표가
    opinion: Optional[str] = None    # 투자의견(매수/중립 등, 사실 인용용)
    report_url: Optional[str] = None      # 원문 링크(본문은 여기 두고 안 옮김)
    aria_priority: float = 0.0       # ARIA 신호 강도(total_score) — 정렬 보정용
    signal_level: Optional[str] = None    # HIGH | MID | LOW
    is_risk: bool = False            # ARIA is_risk(위험 신호) — 안전도 채점 보조
    matched_keywords: Optional[dict[str, Any]] = None  # 매칭 근거
    macro_context: Optional[str] = None   # list_briefings 맥락 한 줄

    def to_row(self) -> dict[str, Any]:
        """Supabase reports 테이블 upsert 용 dict."""
        return {
            "external_id": self.external_id,
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "theme": self.theme,
            "company": self.company,
            "ticker": self.ticker,
            "broker": self.broker,
            "analyst": self.analyst,
            "target_price": self.target_price,
            "opinion": self.opinion,
            "report_url": self.report_url,
            "aria_priority": self.aria_priority,
            "signal_level": self.signal_level,
            "is_risk": self.is_risk,
            "matched_keywords": self.matched_keywords,
            "macro_context": self.macro_context,
        }


@dataclass
class BuzzSignal:
    """소셜에서 추출한 화제성 신호(논문 식별자로 매칭)."""

    external_id: str                 # 정규화된 DOI 또는 'arxiv:ID'
    source: str                      # 'hn' | 'reddit'
    score: int                       # HN points 또는 Reddit score
    num_comments: int = 0
    permalink: Optional[str] = None
