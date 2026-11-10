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


def test_deepseek_402_switches_to_gemini_and_remembers(monkeypatch):
    """2026-11-10 운영자 "딥시크 멈췄으면 제미나이로 이어지도록" — 주류 초안이 DeepSeek 잔액 부족으로 멈춘 실측."""
    monkeypatch.setattr(config, "LLM_DEEPSEEK_PAYMENT_FALLBACK_MODEL", "gemini-3.8-flash")
    ds, gem = [], []

    def deepseek(**kw):
        ds.append(kw["model"])
        raise _status(402)

    monkeypatch.setattr(llm, "_deepseek_create", deepseek)
    monkeypatch.setattr(llm, "_gemini_text", lambda **kw: gem.append(kw["model"]) or '{"ok": 2}')
    assert llm.call_json(model="deepseek-v4-pro", system="s", user="u", max_tokens=16000) == {"ok": 2}
    assert llm.call_json(model="deepseek-v4-pro", system="s", user="u", max_tokens=16000) == {"ok": 2}
    assert ds == ["deepseek-v4-pro"], "두 번째는 DeepSeek 를 다시 부르지 않는다"
    assert gem == ["gemini-3.8-flash"] * 2


def test_deepseek_other_errors_and_both_unpaid_still_fail(monkeypatch):
    monkeypatch.setattr(config, "LLM_DEEPSEEK_PAYMENT_FALLBACK_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(llm, "_deepseek_create", lambda **kw: (_ for _ in ()).throw(_status(401)))
    monkeypatch.setattr(llm, "_gemini_text", lambda **kw: pytest.fail("키 오류를 대체로 덮으면 안 된다"))
    with pytest.raises(httpx.HTTPStatusError):
        llm.call_json(model="deepseek-v4-pro", system="s", user="u")
    # 둘 다 잔액이 없으면 402 가 그대로 올라간다(서로 넘기는 고리 없음)
    monkeypatch.setattr(llm, "_deepseek_create", lambda **kw: (_ for _ in ()).throw(_status(402)))
    calls = []
    monkeypatch.setattr(llm, "_gemini_text", lambda **kw: calls.append(1) or (_ for _ in ()).throw(_status(402)))
    with pytest.raises(httpx.HTTPStatusError):
        llm.call_json(model="deepseek-v4-pro", system="s", user="u")
    assert len(calls) == 1


def test_drinks_hold_covers_the_pricier_fallback_and_unpaid_is_named():
    from engine import drinks_develop as dd

    est = dd.estimate_usd("deepseek-v4-pro", 20_000, 16_000)
    p = dd._price(config.LLM_DEEPSEEK_PAYMENT_FALLBACK_MODEL)
    assert est >= round(10_000 * p["text_input_per_token"] + 16_000 * p["text_output_per_token"], 4), "가잡기가 대체 모델 단가도 덮는다"
    assert dd.payment_required(_status(402)) and not dd.payment_required(_status(401)) and not dd.payment_required(ValueError())


def test_fallback_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(config, "LLM_PAYMENT_FALLBACK_MODEL", "")

    def gemini(**kw):
        raise _status(402)

    monkeypatch.setattr(llm, "_gemini_text", gemini)
    with pytest.raises(httpx.HTTPStatusError):
        llm.call_json(model="gemini-3.8-flash", system="s", user="u")
