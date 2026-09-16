"""LLM 응답 JSON 추출의 관용 파싱 테스트(네트워크 불필요)."""

import dataclasses

import httpx
import pytest

from engine import config
from engine import llm as llm_mod
from engine.llm import JSONParseError, _extract_json


def test_extract_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_code_fenced_json():
    raw = '```json\n{"surprise": 5, "red_flag": ""}\n```'
    assert _extract_json(raw) == {"surprise": 5, "red_flag": ""}


def test_extract_json_with_surrounding_text():
    raw = 'Here you go: {"x": [1,2]} done.'
    assert _extract_json(raw) == {"x": [1, 2]}


def test_extract_invalid_raises():
    with pytest.raises(JSONParseError):
        _extract_json("no json here")


# ── Gemini 5xx → Anthropic 폴백 (엣지 llmText 트윈) ─────────────────────────
# 실측 배경: 2026-08-04 gemini-2.5-pro 가 503 을 계속 내면서 설명판형 지시서 요청
# 2건이 "503 from gemini" 로 죽었다. 엣지 함수는 폴백이 있었고 워커에만 없었다.

def _set_anthropic_key(monkeypatch, key):
    """SECRETS 는 frozen dataclass 라 필드 대입이 막힌다 — 통째로 갈아 끼운다."""
    monkeypatch.setattr(
        config, "SECRETS", dataclasses.replace(config.SECRETS, anthropic_api_key=key))


def _patch_gemini(monkeypatch, exc):
    calls: list[str] = []

    def fake_gemini(**kwargs):
        calls.append("gemini")
        raise exc

    def fake_create(_client, *, model, **kwargs):
        calls.append(f"anthropic:{model}")
        return '{"ok": 1}'

    monkeypatch.setattr(llm_mod, "_gemini_create", fake_gemini)
    monkeypatch.setattr(llm_mod, "_create", fake_create)
    monkeypatch.setattr(llm_mod, "_client", lambda: object())
    return calls


def test_gemini_5xx_falls_back_to_anthropic(monkeypatch):
    # ★ 폴백은 2026-08-29 부터 **기본 꺼짐**이다(운영자: 앤트로픽 연결 없음). 기능 자체를
    #   검사하는 테스트는 자기가 켠다 — 기본값을 되돌리면 그날의 사고가 되돌아온다:
    #   Gemini 크레딧 소진 429 에 폴백이 발동해 30분을 버리고 진짜 원인을 가렸다.
    monkeypatch.setattr(config, "LLM_ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(config, "ANTHROPIC_DISABLED", False)   # 차단 스위치도 함께 끈다
    calls = _patch_gemini(monkeypatch, httpx.TransportError("503 from gemini"))
    _set_anthropic_key(monkeypatch, "sk-test")

    out = llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u")

    assert out == {"ok": 1}
    assert calls == ["gemini", f"anthropic:{config.LLM_ANTHROPIC_FALLBACK_MODEL}"]


def test_gemini_5xx_without_anthropic_key_reraises(monkeypatch):
    """키가 없으면 폴백이 원인을 가리지 않고 그대로 올라간다."""
    calls = _patch_gemini(monkeypatch, httpx.TransportError("503 from gemini"))
    _set_anthropic_key(monkeypatch, "")

    with pytest.raises(httpx.TransportError, match="503 from gemini"):
        llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u")
    assert calls == ["gemini"]


def test_truncation_does_not_fall_back(monkeypatch):
    """절단은 모델을 바꿔도 같은 자리에서 잘린다 — 폴백은 낭비이자 오진 유발이다."""
    calls = _patch_gemini(monkeypatch, llm_mod.OutputTruncatedError("잘림"))
    _set_anthropic_key(monkeypatch, "sk-test")

    with pytest.raises(llm_mod.OutputTruncatedError):
        llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u")
    assert calls == ["gemini"]
