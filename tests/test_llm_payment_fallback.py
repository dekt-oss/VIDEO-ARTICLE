"""Gemini 402(결제 필요) → deepseek 대체 (2026-10-08 운영자 지시). 네트워크 없음."""

from __future__ import annotations

import httpx
import pytest

from engine import config, llm


def _status(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://example.invalid")
    return httpx.HTTPStatusError(f"{code}", request=req, response=httpx.Response(code, request=req))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    llm._PAYMENT_FAILED.clear()
    monkeypatch.setattr(config, "LLM_PAYMENT_FALLBACK_MODEL", "deepseek-v4-pro")
    yield
    llm._PAYMENT_FAILED.clear()


def test_402_switches_to_deepseek_and_remembers(monkeypatch):
    gem, ds = [], []

    def gemini(**kw):
        gem.append(kw["model"])
        raise _status(402)

    monkeypatch.setattr(llm, "_gemini_text", gemini)
    monkeypatch.setattr(llm, "_deepseek_create", lambda **kw: ds.append(kw) or '{"ok": 1}')
    assert llm.call_json(model="gemini-3.8-flash", system="s", user="u", max_tokens=8000) == {"ok": 1}
    assert llm.call_json(model="gemini-3.8-flash", system="s", user="u", max_tokens=8000) == {"ok": 1}
    assert gem == ["gemini-3.8-flash"]                      # 두 번째는 Gemini 를 다시 부르지 않는다
    assert [d["model"] for d in ds] == ["deepseek-v4-pro"] * 2
    assert ds[0]["max_tokens"] > 8000                        # deepseek 는 토큰을 더 쓴다 — 상한도 키운다


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_other_4xx_still_fail_loudly(monkeypatch, code):
    def gemini(**kw):
        raise _status(code)

    monkeypatch.setattr(llm, "_gemini_text", gemini)
    monkeypatch.setattr(llm, "_deepseek_create", lambda **kw: pytest.fail("설정 오류를 대체로 덮으면 안 된다"))
    with pytest.raises(httpx.HTTPStatusError):
        llm.call_json(model="gemini-3.8-flash", system="s", user="u")


def test_fallback_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(config, "LLM_PAYMENT_FALLBACK_MODEL", "")

    def gemini(**kw):
        raise _status(402)

    monkeypatch.setattr(llm, "_gemini_text", gemini)
    with pytest.raises(httpx.HTTPStatusError):
        llm.call_json(model="gemini-3.8-flash", system="s", user="u")
