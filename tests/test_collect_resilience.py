"""collect 소스 격리 회귀 테스트 — 한 소스 실패가 전체 배치를 죽이지 않는지.

근거: arXiv 429 가 openalex+arxiv 이어붙이기를 크래시시켜 daily_batch 전체가 사라진 사고(engine.yml #23).
네트워크/LLM 없음(순수).
"""

import httpx
import pytest

from engine.collect import _safe_collect


def test_safe_collect_returns_result_on_success():
    assert _safe_collect("src", lambda a, b: ["p1", "p2"], 1, 2) == ["p1", "p2"]


def test_safe_collect_swallows_failure_returns_empty():
    def boom():
        raise httpx.HTTPStatusError("429", request=None, response=None)
    assert _safe_collect("arXiv", boom) == []


def test_safe_collect_none_coerced_to_list():
    assert _safe_collect("src", lambda: None) == []


def test_one_source_failure_does_not_abort_other():
    """run() 의 핵심 패턴 재현: arXiv 가 429 로 죽어도 OpenAlex 결과는 배치에 남는다."""
    def openalex_ok(s, e):
        return ["openalex_paper"]

    def arxiv_429(s, e):
        raise httpx.HTTPStatusError("429 Too Many Requests", request=None, response=None)

    papers = _safe_collect("OpenAlex", openalex_ok, "s", "e") + \
        _safe_collect("arXiv", arxiv_429, "s", "e")
    assert papers == ["openalex_paper"]     # 배치 유지(예전엔 전체 크래시 → [])
