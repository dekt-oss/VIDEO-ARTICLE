"""ARIA 어댑터 — 리포트 팩토리의 수집 블록(명세 §2).

논문의 OpenAlex/arXiv/HN/Reddit 4종 수집이 ARIA 호출 몇 개로 압축된다.
전송방식(PFD3)은 client.get_client() 뒤로 추상화: ARIA_BASE 설정 시 HTTP, 없으면 fixture.
"""

from .client import AriaClient, FixtureAriaClient, HttpAriaClient, get_client

__all__ = ["AriaClient", "FixtureAriaClient", "HttpAriaClient", "get_client"]
