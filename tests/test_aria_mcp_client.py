"""ARIA MCP 클라이언트 순수 로직 테스트 — SSE 파싱 + tools/call 매핑. 네트워크 없음.

http_post 를 가짜로 갈아끼워 실제 ARIA MCP 응답 형태(SSE, result.content[0].text=JSON 문자열)를
그대로 재현한다. 도구 인자 이름·전송 페이로드가 ARIA MCP 계약과 맞는지 검증한다.
"""

import json

from engine.aria import client as aria_client
from engine.aria.client import McpAriaClient, _parse_sse_json


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


def _sse(result_obj: dict) -> str:
    """ARIA MCP 가 돌려주는 SSE 프레임 재현."""
    msg = {"jsonrpc": "2.0", "id": 1, "result": result_obj}
    return f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"


def _tool_result(payload: dict) -> dict:
    """도구 반환값은 content[0].text 에 JSON 문자열로 들어온다."""
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": False}


def test_parse_sse_json_extracts_result():
    text = _sse({"content": [{"type": "text", "text": "{\"ok\":1}"}]})
    msg = _parse_sse_json(text)
    assert "result" in msg and msg["result"]["content"][0]["text"] == '{"ok":1}'


def test_parse_sse_json_plain_json_fallback():
    # 비-SSE(application/json) 응답도 파싱된다.
    msg = _parse_sse_json('{"jsonrpc":"2.0","id":1,"result":{"x":1}}')
    assert msg["result"]["x"] == 1


def test_url_gets_trailing_slash():
    assert McpAriaClient("https://h/mcp-TOKEN").url == "https://h/mcp-TOKEN/"
    assert McpAriaClient("https://h/mcp-TOKEN/").url == "https://h/mcp-TOKEN/"


def test_list_signals_maps_args_and_unwraps(monkeypatch):
    captured = {}

    def fake_post(url, *, json_body=None, headers=None):
        captured["url"] = url
        captured["body"] = json_body
        captured["accept"] = (headers or {}).get("Accept")
        return _FakeResp(_sse(_tool_result({"count": 1, "items": [{"id": 42}]})))

    monkeypatch.setattr(aria_client, "http_post", fake_post)
    c = McpAriaClient("https://h/mcp-TOK")
    out = c.list_signals(limit=3, pass_only=True, today=False)

    assert out["items"] == [{"id": 42}]                  # content[0].text JSON 언랩
    assert captured["url"] == "https://h/mcp-TOK/"       # 트레일링 슬래시
    assert "text/event-stream" in captured["accept"]     # SSE 수락 헤더
    p = captured["body"]["params"]
    assert p["name"] == "list_signals"
    assert p["arguments"] == {"limit": 3, "pass_only": True, "today": False}


def test_get_signal_and_broker_targets_arg_names(monkeypatch):
    seen = []

    def fake_post(url, *, json_body=None, headers=None):
        seen.append(json_body["params"])
        return _FakeResp(_sse(_tool_result({"ok": True})))

    monkeypatch.setattr(aria_client, "http_post", fake_post)
    c = McpAriaClient("https://h/mcp-TOK")
    c.get_signal(3064)
    c.broker_targets(query="SK", days=14)

    assert seen[0] == {"name": "get_signal", "arguments": {"signal_id": 3064}}
    assert seen[1] == {"name": "broker_targets", "arguments": {"query": "SK", "days": 14}}


def test_tool_error_raises(monkeypatch):
    def fake_post(url, *, json_body=None, headers=None):
        return _FakeResp(_sse({"content": [{"type": "text", "text": "boom"}], "isError": True}))

    monkeypatch.setattr(aria_client, "http_post", fake_post)
    c = McpAriaClient("https://h/mcp-TOK")
    try:
        c.list_signals(limit=1, pass_only=True, today=True)
        assert False, "isError 인데 예외가 안 났다"
    except RuntimeError as exc:
        assert "isError" in str(exc)
