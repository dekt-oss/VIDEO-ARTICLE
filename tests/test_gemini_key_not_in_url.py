"""Gemini API 키가 URL 쿼리에 실리지 않는지 (2026-08-28 실측 사고).

무슨 일이 있었나: `?key=…` 로 보내던 동안 httpx 가 요청 URL 을 INFO 로그로 통째로 찍었고,
실측 로그 한 개에만 키가 **45번** 평문으로 남았다. 로컬 로그·CI 로그·터미널 기록·모니터
알림이 전부 같은 줄을 실어 나른다. 헤더(x-goog-api-key)로 보내면 같은 요청이 로그에 남아도
키는 남지 않는다.

이 검사는 "고쳤다"가 아니라 "다시 그렇게 쓰지 못한다"를 지킨다 — 새 Gemini 호출부를
추가하는 사람이 옛 예제를 복사해 오는 것이 이 사고의 재발 경로다.
"""

from __future__ import annotations

import pathlib
import re

from engine.util import gemini_auth

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"
# `params={"key": …}` 형태. 다른 params 사용(alt=media, mailto 등)은 건드리지 않는다.
KEY_IN_QUERY = re.compile(r"params\s*=\s*\{[^}]*[\"']key[\"']\s*:")


def test_no_gemini_key_in_query_string():
    offenders = [str(p.relative_to(ENGINE.parent))
                 for p in ENGINE.rglob("*.py")
                 if KEY_IN_QUERY.search(p.read_text(encoding="utf-8"))]
    assert not offenders, (
        "Gemini 키를 쿼리스트링으로 보내고 있다 — httpx 가 URL 을 로그에 찍어 키가 평문으로 "
        f"남는다. engine.util.gemini_auth() 를 headers 로 쓸 것: {offenders}")


def test_gemini_auth_uses_header():
    assert list(gemini_auth()) == ["x-goog-api-key"]
