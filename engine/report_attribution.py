"""리포트 출처(attribution) 유틸 — 증권사 리포트 메타를 검증 가능한 형태로 (LLM 아님).

논문 attribution.py 의 report 미러. 산출물 자막의 **출처 고정 표기 + 엔딩 면책**에 직결(명세 §6).
증권사·애널리스트 귀속을 강제해 "내 분석인 척" 금지(명세 5-2)를 뒷받침한다.

★ 이중관리 지점: supabase/functions/generate-report-draft(buildSource)·web/lib/reportPublishCaption.ts
  와 동기화. 순수 로직(네트워크 없음) — 단위 테스트 대상.
"""

from __future__ import annotations

from typing import Any

from . import config


def build_source(report: dict[str, Any]) -> dict[str, Any]:
    """reports 행 → source 블록(검증 가능 메타). 대본이 출처를 구체적으로 지칭하게 한다."""
    return {
        "broker": report.get("broker") or "",       # 증권사/채널(출처)
        "analyst": report.get("analyst") or "",      # 애널리스트(있으면)
        "company": report.get("company") or report.get("theme") or "",
        "opinion": report.get("opinion") or "",
        "target_price": report.get("target_price"),
        "url": report.get("report_url") or "",
        "disclaimer": config.REPORT_DISCLAIMER_TEXT,  # 엔딩 면책(고정)
    }


def source_line(source: dict[str, Any]) -> str:
    """'출처: OO증권 (종목)' 한 줄 — 자막 고정 표기용. 있는 값만 사용(지어내지 않음)."""
    broker = source.get("broker") or ""
    analyst = source.get("analyst") or ""
    who = broker + (f" {analyst}" if analyst else "")
    if not who:
        return ""
    return f"출처: {who}".strip()


def build_publish_caption(source: dict[str, Any], teaser: str = "", lang: str = "ko",
                          hashtags: list[str] | None = None) -> str:
    """발행 캡션(설명란). teaser + 출처 라인 + 링크 + **면책 고정** + 해시태그.

    ★ 면책은 항상 포함(명세 §6 출처·면책 고정 레이어). 있는 값만 사용.
    """
    who = (source.get("broker") or "")
    if source.get("analyst"):
        who = f"{who} {source['analyst']}".strip()
    company = source.get("company") or ""
    url = source.get("url") or ""
    disclaimer = source.get("disclaimer") or config.REPORT_DISCLAIMER_TEXT
    lines: list[str] = []
    if teaser:
        lines.append(teaser.strip())
        lines.append("")
    if lang == "en":
        if company:
            lines.append(f"📊 {company}")
        if who:
            lines.append(f"🏛️ Source: {who}")
        if url:
            lines.append(f"🔗 {url}")
        lines.append("⚠️ For information only. Not investment advice.")
        tags = hashtags or ["#stocks", "#investing", "#finance", "#shorts"]
    else:
        if company:
            lines.append(f"📊 {company}")
        if who:
            lines.append(f"🏛️ 출처: {who}")
        if url:
            lines.append(f"🔗 {url}")
        lines.append(f"⚠️ {disclaimer}")
        tags = hashtags or ["#증권", "#리포트", "#주식", "#투자", "#쇼츠"]
    lines.append("")
    lines.append(" ".join(tags))
    return "\n".join(lines).strip()
