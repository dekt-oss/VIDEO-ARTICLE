"""Anthropic 경로 차단 (2026-08-29 운영자 지시: "앤트로픽 경로 전부 코드에서 막아").

★ 왜 이 파일이 있나 — 실측 사고:
  세션 초반에 운영자가 "제미나이로 해야지"라고 했는데 나는 **그 실행만** 바꾸고
  기본값(MODEL_DIRECTIVE·MODEL_SCRIPT)과 폴백은 Anthropic 그대로 뒀다. 그래서 그날
  지시서 생성이 Anthropic 으로 나갔고, Gemini 가 429 를 낼 때마다 자동으로 그쪽으로
  넘어갔다. 잔액이 0이라 400 으로 거절돼 과금은 안 됐지만 **막은 것이 아니라 운이 좋았다.**

  "설정 한 곳을 고쳤다"로는 부족하다는 것이 그날의 교훈이다. 그래서 검사한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine import config, llm

ROOT = Path(__file__).resolve().parents[1]


def test_client_factory_refuses_to_open():
    """클라이언트를 만드는 **단 하나의 지점**에서 막힌다 — 모델 ID·폴백·키와 무관하게."""
    assert config.ANTHROPIC_DISABLED is True
    with pytest.raises(llm.AnthropicDisabledError):
        llm._client()


def test_fallback_is_not_even_considered_while_blocked():
    """막혀 있으면 폴백을 후보로 두지 않는다.

    후보로 두면 Gemini 재시도가 GEMINI_ATTEMPTS_WITH_FALLBACK 로 **짧게 끊긴다** —
    오늘 429 에 폴백이 발동해 Gemini 를 2번만 시도하고 죽은 Anthropic 으로 30분을 버린
    것이 그 사고다. 진짜 원인(Gemini 크레딧 소진)은 로그 어디에도 남지 않았다.
    """
    import inspect

    src = inspect.getsource(llm._gemini_text)
    assert "not config.ANTHROPIC_DISABLED" in src


def test_no_model_default_points_at_anthropic():
    """기본값이 하나라도 claude 를 가리키면 아무도 모르는 사이에 그쪽으로 나간다."""
    src = (ROOT / "engine" / "config.py").read_text(encoding="utf-8")
    leaks = re.findall(r'^(MODEL_[A-Z_]+): str = os\.getenv\("[A-Z_]+", "(claude-[^"]+)"\)',
                       src, re.M)
    assert leaks == [], f"기본값이 Anthropic 을 가리킨다: {leaks}"


def test_fallback_default_is_off():
    assert config.LLM_ANTHROPIC_FALLBACK_MODEL == ""
