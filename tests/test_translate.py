"""제목 번역 백필 로직 테스트 — 네트워크/LLM 불필요(call_json monkeypatch)."""

import engine.translate as translate
from engine.llm import JSONParseError


def test_empty_title_short_circuits(monkeypatch):
    # 빈 제목은 LLM 을 호출하지 않고 즉시 "" 반환.
    called = {"n": 0}

    def fake_call_json(**kwargs):
        called["n"] += 1
        return {"title_ko": "should-not-happen"}

    monkeypatch.setattr(translate, "call_json", fake_call_json)
    assert translate.translate_title("   ") == ""
    assert called["n"] == 0


def test_translates_title(monkeypatch):
    monkeypatch.setattr(
        translate, "call_json",
        lambda **kwargs: {"title_ko": "  스스로 개선하는 하네스 "},
    )
    assert translate.translate_title("Self-Harness") == "스스로 개선하는 하네스"


def test_json_parse_failure_returns_empty(monkeypatch):
    def boom(**kwargs):
        raise JSONParseError("bad json")

    monkeypatch.setattr(translate, "call_json", boom)
    assert translate.translate_title("Some Paper") == ""


def test_api_error_returns_empty(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("503 from anthropic")

    monkeypatch.setattr(translate, "call_json", boom)
    assert translate.translate_title("Some Paper") == ""
