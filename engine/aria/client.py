"""ARIA 클라이언트 — 전송방식 추상화 (PFD3).

로컬/크론 엔진은 이 세션의 MCP 를 못 쓴다. 세 구현을 제공한다:
- McpAriaClient  : ARIA MCP 서버 직접 호출(streamable HTTP/JSON-RPC). ★ 프로덕션 경로.
- HttpAriaClient : 순수 REST API 직접 호출(레거시/대안).
- FixtureAriaClient : engine/aria/fixtures/*.json 재생(로컬·테스트, 오프라인).

get_client() 가 config.ARIA_MCP_URL → ARIA_BASE → fixture 순으로 자동 선택한다.
사용자의 ARIA 는 REST 가 아니라 MCP 서버라, 프로덕션은 McpAriaClient 를 쓴다.

도구 계약(세 구현 공통):
- list_signals(limit, pass_only, today) -> {"items": [ {id, theme_name, signal_level,
    total_score, is_risk, matched_keywords, message_text, ...} ]}
- get_signal(signal_id) -> {id, channel, raw_content, source_url, ...}
- broker_targets(query, days) -> {"groups": [ {stock_name, stock_code, items:[...]} ]}
- list_briefings(limit) -> {"items": [ {title, preview, ...} ]}
- search_research(query, status, broker, limit) -> {"items": [ {id, broker, report_title,
    report_date, portal_category, status, signal_level, theme_name, preview} ]}
- get_research(research_id) -> {id, broker, report_title, source_url, content_raw, ...}

★ search_research/get_research 는 Phase 0 에서 뒤늦게 배선했다(docs/phase0-영상엔진품질_v3.md §1-3).
  그 전까지 이 저장소는 list_signals 의 **미리보기(message_text)** 만 보고 영상을 만들었다 —
  ARIA 는 같은 리포트의 전문을 이미 갖고 있었는데도. get_research(id).content_raw 는 증권사
  정식 리포트의 PDF 추출 전문(본문+표+재무제표)이라 인용·페이지·근거 추적의 유일한 입력이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .. import config
from ..util import http_get, http_post, log

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _parse_sse_json(text: str) -> dict[str, Any]:
    """SSE(text/event-stream) 본문에서 JSON-RPC 응답 메시지(dict)를 추출.

    MCP streamable HTTP 응답은 'event: message\\ndata: {json}' 형태의 SSE 로 온다.
    result/error 를 담은 첫 data 줄을 파싱한다. 비-SSE(application/json)면 통째로 파싱.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                msg = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                return msg
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


class McpAriaClient:
    """ARIA MCP(streamable HTTP/JSON-RPC) 직접 호출. config.ARIA_MCP_URL 로 설정.

    사용자의 ARIA 는 REST 가 아니라 MCP 서버다. 인증 토큰이 엔드포인트 URL 경로에 포함돼
    별도 헤더 인증이 없고, 세션(핸드셰이크) 없이 tools/call 단건 POST 로 동작한다(stateless).
    응답은 SSE 로 오며 result.content[0].text 가 도구 반환 JSON 문자열 — 파싱해 dict 로 돌려준다
    (HTTP/fixture 클라이언트와 동일 계약).
    """

    def __init__(self, url: str) -> None:
        # MCP 는 트레일링 슬래시 경로에서 응답한다(그 외엔 307 리다이렉트). 미리 붙여 왕복 절감.
        self.url = url if url.endswith("/") else url + "/"

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        resp = http_post(
            self.url, json_body=payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        msg = _parse_sse_json(resp.text)
        if "error" in msg:
            raise RuntimeError(f"ARIA MCP {tool} 오류: {msg['error']}")
        result = msg.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(f"ARIA MCP {tool} isError: {result}")
        for block in result.get("content") or []:
            if block.get("type") == "text":
                txt = block.get("text") or ""
                try:
                    parsed = json.loads(txt)
                except json.JSONDecodeError:
                    return {"text": txt}
                return parsed if isinstance(parsed, dict) else {"items": parsed}
        return {}

    def list_signals(self, *, limit: int, pass_only: bool, today: bool) -> dict[str, Any]:
        return self._call("list_signals", {"limit": limit, "pass_only": pass_only, "today": today})

    def get_signal(self, signal_id: int) -> dict[str, Any]:
        return self._call("get_signal", {"signal_id": signal_id})

    def broker_targets(self, *, query: str = "", days: int = 30) -> dict[str, Any]:
        return self._call("broker_targets", {"query": query, "days": days})

    def list_briefings(self, *, limit: int = 50) -> dict[str, Any]:
        return self._call("list_briefings", {"limit": limit})

    def search_research(self, *, query: str = "", status: str = "", broker: str = "",
                        limit: int = 50) -> dict[str, Any]:
        return self._call("search_research",
                          {"query": query, "status": status, "broker": broker, "limit": limit})

    def get_research(self, research_id: int) -> dict[str, Any]:
        return self._call("get_research", {"research_id": research_id})


class AriaClient(Protocol):
    """리포트 수집이 의존하는 ARIA 인터페이스(전송방식 무관)."""

    def list_signals(self, *, limit: int, pass_only: bool, today: bool) -> dict[str, Any]: ...
    def get_signal(self, signal_id: int) -> dict[str, Any]: ...
    def broker_targets(self, *, query: str = "", days: int = 30) -> dict[str, Any]: ...
    def list_briefings(self, *, limit: int = 50) -> dict[str, Any]: ...
    def search_research(self, *, query: str = "", status: str = "", broker: str = "",
                        limit: int = 50) -> dict[str, Any]: ...
    def get_research(self, research_id: int) -> dict[str, Any]: ...


class HttpAriaClient:
    """ARIA HTTP API 직접 호출. ARIA_BASE / ARIA_API_KEY 로 설정.

    ★ 엔드포인트 경로·인증 헤더는 ARIA HTTP 규격 확정 시 맞춘다(PFD3). 현재는 합리적 기본값.
    """

    def __init__(self, base: str, api_key: str = "") -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def list_signals(self, *, limit: int, pass_only: bool, today: bool) -> dict[str, Any]:
        resp = http_get(
            f"{self.base}/list_signals",
            params={"limit": limit, "pass_only": str(pass_only).lower(), "today": str(today).lower()},
            headers=self._headers(),
        )
        return resp.json()

    def get_signal(self, signal_id: int) -> dict[str, Any]:
        resp = http_get(f"{self.base}/get_signal", params={"signal_id": signal_id},
                        headers=self._headers())
        return resp.json()

    def broker_targets(self, *, query: str = "", days: int = 30) -> dict[str, Any]:
        resp = http_get(f"{self.base}/broker_targets", params={"query": query, "days": days},
                        headers=self._headers())
        return resp.json()

    def list_briefings(self, *, limit: int = 50) -> dict[str, Any]:
        resp = http_get(f"{self.base}/list_briefings", params={"limit": limit},
                        headers=self._headers())
        return resp.json()

    def search_research(self, *, query: str = "", status: str = "", broker: str = "",
                        limit: int = 50) -> dict[str, Any]:
        resp = http_get(f"{self.base}/search_research",
                        params={"query": query, "status": status, "broker": broker, "limit": limit},
                        headers=self._headers())
        return resp.json()

    def get_research(self, research_id: int) -> dict[str, Any]:
        resp = http_get(f"{self.base}/get_research", params={"research_id": research_id},
                        headers=self._headers())
        return resp.json()


class FixtureAriaClient:
    """fixtures/*.json 재생(오프라인 로컬·테스트). 실제 ARIA 응답 형태를 그대로 캡처했다."""

    def __init__(self, fixtures_dir: Path = _FIXTURES_DIR) -> None:
        self.dir = fixtures_dir

    def _load(self, name: str) -> Any:
        path = self.dir / name
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def list_signals(self, *, limit: int, pass_only: bool, today: bool) -> dict[str, Any]:
        data = self._load("signals.json")
        items = list(data.get("items", []))
        if pass_only:
            items = [s for s in items if s.get("signal_level") in ("HIGH", "MID")]
        return {"count": min(limit, len(items)), "items": items[:limit]}

    def get_signal(self, signal_id: int) -> dict[str, Any]:
        details = self._load("signal_details.json")
        return details.get(str(signal_id), {})

    def broker_targets(self, *, query: str = "", days: int = 30) -> dict[str, Any]:
        data = self._load("broker_targets.json")
        groups = data.get("groups", [])
        if query:
            q = query.strip()
            groups = [g for g in groups if q in (g.get("stock_name") or "")]
        return {"count": len(groups), "groups": groups}

    def list_briefings(self, *, limit: int = 50) -> dict[str, Any]:
        data = self._load("briefings.json")
        return {"items": list(data.get("items", []))[:limit]}

    def search_research(self, *, query: str = "", status: str = "", broker: str = "",
                        limit: int = 50) -> dict[str, Any]:
        items = list(self._load("research.json").get("items", []))
        if status:
            items = [r for r in items if r.get("status") == status]
        if broker:
            items = [r for r in items if broker in (r.get("broker") or "")]
        if query:
            q = query.strip()
            items = [r for r in items
                     if q in (r.get("report_title") or "") or q in (r.get("preview") or "")]
        return {"count": min(limit, len(items)), "limit": limit, "items": items[:limit]}

    def get_research(self, research_id: int) -> dict[str, Any]:
        return self._load("research_details.json").get(str(research_id), {})


def get_client() -> AriaClient:
    """전송방식 자동 선택: ARIA_MCP_URL(MCP) → ARIA_BASE(REST) → fixture."""
    if config.ARIA_MCP_URL:
        log.info("ARIA: MCP 클라이언트 (streamable HTTP)")
        return McpAriaClient(config.ARIA_MCP_URL)
    if config.ARIA_BASE:
        log.info("ARIA: HTTP 클라이언트 (base=%s)", config.ARIA_BASE)
        return HttpAriaClient(config.ARIA_BASE, config.SECRETS.aria_api_key)
    log.info("ARIA: fixture 모드(ARIA_MCP_URL·ARIA_BASE 미설정) — 로컬/테스트 데이터")
    return FixtureAriaClient()
