"""Anthropic 경로 스위치.

2026-08-29 운영자 지시("앤트로픽 경로 전부 코드에서 막아")로 기본 차단했다 — 잔액 0인 Anthropic 으로
기본값·폴백이 몰래 새던 사고 때문이다. 2026-11-26 운영자 결정("Claude Haiku 5.5 로 작업합시다")으로
Anthropic 이 **기본 경로**가 됐다. 스위치는 남긴다: 다시 막아야 하면 ANTHROPIC_DISABLED=true.

이제 지킬 것: (1) 스위치를 켜면 여전히 클라이언트 한 지점에서 막힌다, (2) 텍스트 기본값이 한 곳
(MODEL_TEXT_DEFAULT)을 따른다, (3) DeepSeek 은 운영자 지시로 어떤 기본값에도 없다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine import config, llm

ROOT = Path(__file__).resolve().parents[1]


def test_switch_still_blocks_at_the_single_client_factory(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_DISABLED", True)
    with pytest.raises(llm.AnthropicDisabledError):
        llm._client()


def test_anthropic_is_open_by_default_and_text_default_is_haiku():
    assert config.ANTHROPIC_DISABLED is False
    assert config.MODEL_TEXT_DEFAULT == "claude-haiku-5-5"
    assert "claude-haiku-5-5" in config.TEXT_PRICING   # 단가가 없으면 원장이 0원으로 적는다


def test_fallback_is_not_even_considered_while_blocked():
    import inspect

    assert "not config.ANTHROPIC_DISABLED" in inspect.getsource(llm._gemini_text)


def test_no_report_or_paper_model_default_points_at_deepseek_or_gemini():
    """2026-11-26 운영자 "딥식은 이제 쓰지말고" — 리포트·논문 텍스트 기본값은 전부 MODEL_TEXT_DEFAULT.
    주류(DRINKS_*)는 DB 비용 예상 함수와 묶여 있어 따로 옮긴다."""
    src = (ROOT / "engine" / "config.py").read_text(encoding="utf-8")
    leaks = re.findall(r'^(MODEL_[A-Z_]+): str = os\.getenv\("[A-Z_]+", "((?:deepseek|gemini)-[^"]+)"\)', src, re.M)
    assert leaks == [], f"리포트·논문 기본값이 옛 모델을 가리킨다: {leaks}"


def test_fallback_default_is_off():
    assert config.LLM_ANTHROPIC_FALLBACK_MODEL == ""
