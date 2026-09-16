"""연속성 판정 호출은 gemini-2.5 flash 의 사고를 끈다 (2026-09-11 실측).

성격 유전 전반부 렌더에서 CONTINUITY_QA_MAX_TOKENS(200)를 사고 토큰이 다 써서 본문이 비었고,
`json.loads("")` 로 판정 5회가 전부 "판정 불가"로 건너뛰어졌다. llm._gemini_create 와 같은 규칙.
"""
import json

import pytest

from engine import config, continuity_qa


class _Resp:
    def __init__(self, text: str):
        self._text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


@pytest.fixture
def captured(monkeypatch):
    import httpx

    seen: dict = {}

    def _post(url, json=None, **kw):  # noqa: A002 — httpx 시그니처
        seen["url"] = url
        seen["body"] = json
        return _Resp('{"same": true}')

    monkeypatch.setattr(httpx, "post", _post)
    # SECRETS 는 frozen dataclass 라 속성을 못 바꾼다 — 사본을 통째로 끼운다.
    import dataclasses
    monkeypatch.setattr(config, "SECRETS", dataclasses.replace(config.SECRETS, gemini_api_key="test-key"))
    return seen


def test_flash_turns_thinking_off(monkeypatch, captured):
    monkeypatch.setattr(config, "CONTINUITY_QA_MODEL", "gemini-2.5-flash")
    assert continuity_qa.ask("sys", "user", []) == {"same": True}
    gen = captured["body"]["generationConfig"]
    assert gen["thinkingConfig"] == {"thinkingBudget": config.GEMINI_THINKING_BUDGET}
    assert gen["maxOutputTokens"] == config.CONTINUITY_QA_MAX_TOKENS


def test_pro_cannot_turn_thinking_off_so_budget_grows(monkeypatch, captured):
    monkeypatch.setattr(config, "CONTINUITY_QA_MODEL", "gemini-2.5-pro")
    continuity_qa.ask("sys", "user", [])
    gen = captured["body"]["generationConfig"]
    assert "thinkingConfig" not in gen
    assert gen["maxOutputTokens"] >= config.GEMINI_PRO_MAX_OUTPUT_TOKENS


def test_non_thinking_model_is_untouched(monkeypatch, captured):
    monkeypatch.setattr(config, "CONTINUITY_QA_MODEL", "gemini-2.0-flash")
    continuity_qa.ask("sys", "user", [])
    gen = captured["body"]["generationConfig"]
    assert gen == {"maxOutputTokens": config.CONTINUITY_QA_MAX_TOKENS}, json.dumps(gen)
