"""출처(attribution) 유틸 — 논문 메타데이터를 검증 가능한 형태로 다룬다(LLM 아님).

두 용도:
- `build_source(paper)`: 나레이션 구체화용 source 블록. Fact Sheet에 부착돼 대본이 기관/저자를
  구체적으로 지칭하게 한다(환각 방지: source에 있는 것만 쓰라는 프롬프트 규칙과 짝).
- `build_publish_caption(...)`: 숏츠 발행 캡션(설명란). 논문 상세정보 + 링크 + 해시태그.

★ 이 모듈은 supabase/functions/generate-draft(buildSource)·web/lib/publishCaption.ts 와 동기화되는
  이중관리 지점이다. 규칙을 고치면 함께 갱신한다.

순수 로직(네트워크 없음) — 단위 테스트 대상.
"""

from __future__ import annotations

import re
from typing import Any

_MARKUP_RE = re.compile(r"<[^>]*>")


def strip_markup(text: str) -> str:
    """YouTube 는 제목/설명에 '<' '>' 를 허용하지 않는다(invalidDescription 400). OpenAlex 제목의
    <i>..</i>·<sub>..</sub> 같은 HTML 태그를 제거하고, 남은 홑화살괄호도 없앤다(발행 안전)."""
    t = _MARKUP_RE.sub("", text or "")
    return t.replace("<", "").replace(">", "")


def _year(published_date: Any) -> str:
    s = str(published_date or "")
    return s[:4] if len(s) >= 4 and s[:4].isdigit() else ""


def build_source(paper: dict[str, Any]) -> dict[str, Any]:
    """논문 행 → source 블록(검증 가능 메타). authors=[{name, institution}]."""
    authors = paper.get("authors") if isinstance(paper.get("authors"), list) else []
    names = [a.get("name") for a in authors if isinstance(a, dict) and a.get("name")][:3]
    seen: list[str] = []
    for a in authors:
        inst = a.get("institution") if isinstance(a, dict) else None
        if inst and inst not in seen:
            seen.append(inst)
    return {
        "title": paper.get("title") or "",
        "venue": paper.get("venue") or "",
        "year": _year(paper.get("published_date")),
        "authors": names,
        "institutions": seen[:3],
        "url": paper.get("url") or "",
    }


def _who(source: dict[str, Any]) -> str:
    """'누가/어디' 한 줄 — 기관 우선, 없으면 저자, 없으면 게재처. 지어내지 않음(있는 것만)."""
    insts = source.get("institutions") or []
    if insts:
        return " · ".join(insts)
    authors = source.get("authors") or []
    if authors:
        return authors[0] + (" 외" if len(authors) > 1 else "")
    return source.get("venue") or ""


def build_publish_caption(source: dict[str, Any], teaser: str = "", lang: str = "ko",
                          hashtags: list[str] | None = None) -> str:
    """발행 캡션(설명란) 텍스트. teaser(한 줄 요약) + 출처 라인 + 링크 + 해시태그.

    출처는 source의 값만 사용(빈 항목은 생략). 해시태그 미지정 시 언어별 기본 세트.
    """
    venue = source.get("venue") or ""
    year = source.get("year") or ""
    title = source.get("title") or ""
    url = source.get("url") or ""
    who = _who(source)
    vy = ", ".join([x for x in (venue, year) if x])
    lines: list[str] = []
    if teaser:
        lines.append(teaser.strip())
        lines.append("")
    if lang == "en":
        if title:
            lines.append(f"📄 Paper: {title}" + (f" ({vy})" if vy else ""))
        if who:
            lines.append(f"🏛️ {who}")
        if url:
            lines.append(f"🔗 {url}")
        tags = hashtags or ["#research", "#science", "#paper", "#AI", "#shorts"]
    else:
        if title:
            lines.append(f"📄 원논문: {title}" + (f" ({vy})" if vy else ""))
        if who:
            lines.append(f"🏛️ {who}")
        if url:
            lines.append(f"🔗 {url}")
        tags = hashtags or ["#논문", "#연구", "#과학", "#지식", "#쇼츠"]
    if lines and (title or url):
        lines.append("")
    lines.append(" ".join(tags))
    # YouTube 발행 안전: 논문 제목 등에 섞인 HTML 태그/홑화살괄호 제거(invalidDescription 방지).
    return strip_markup("\n".join(lines).strip())
