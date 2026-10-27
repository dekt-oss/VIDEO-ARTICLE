"""주류 공장 — 카드뉴스 인스타 캡션 조립(운영자 승인 형태, 2026-10-27). docs/deviation-drinks-production.md "사진형 카드"

승인된 제작안의 plan["caption"](title·intro·points·limit·share_target·hashtags …)를 정해진 모양으로 이어 붙인다.
· 요점(points)은 **제작안에 적힌 문장만** 쓴다 — 없는 내용을 지어내지 않는다(비어 있으면 설명 쪽 제목을 그대로 쓴다).
· 주류 경고 문구는 캡션에 넣지 않는다(운영자 결정 2026-10-27) — 출처 장에는 항상 있다(engine/drinks_cards_photo.py).
· 발행 직전 검사(drinks_script_check.check_caption)와 DB 상한(0055: 글자 2200·해시태그 30)을 지킨다. DB 에는 쓰지 않는다 — 함수만.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import config

_BRACKET = re.compile(r"[\[\]]")
_TAG_JUNK = re.compile(r"[^0-9A-Za-z_가-힣]")


def _flat(text: str) -> str:
    """강조 대괄호를 벗기고 줄바꿈을 공백으로 — 카드 글을 캡션 한 줄로."""
    return re.sub(r"\s+", " ", _BRACKET.sub("", text or "")).strip()


def _pages(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((plan.get("pages") or []), key=lambda p: int(p.get("position") or 0))


def _clean_tag(raw: Any) -> str:
    return _TAG_JUNK.sub("", str(raw or "").lstrip("#"))


def hashtags(raw: Any) -> list[str]:
    """plan 의 해시태그 → 최대 DRINKS_CAPTION_MAX_HASHTAGS 개, 마지막은 항상 브랜드 태그. 중복·빈 것은 뺀다."""
    brand = _clean_tag(config.DRINKS_CAPTION_BRAND_TAG)
    seen: list[str] = []
    for t in (raw if isinstance(raw, (list, tuple)) else []):
        c = _clean_tag(t)
        if c and c != brand and c not in seen:
            seen.append(c)
    return [f"#{t}" for t in seen[:config.DRINKS_CAPTION_MAX_HASHTAGS - 1]] + [f"#{brand}"]


_END = ("." , "!", "?", "…", "。", "~")


def _sentence(text: str) -> str:
    return text if text.endswith(_END) else text + "."


def _body(cap: dict[str, Any], pages: list[dict[str, Any]], points: list[str]) -> str:
    """본문. 기본은 문단(운영자 결정 2026-10-27 — 번호 목록은 행동·체크리스트 글에만 쓴다).
    · caption.body(완성된 문단 글)가 있으면 그대로.
    · caption.style == "list" 이거나 쪽 역할에 checklist 가 있으면 번호 목록.
    · 그 밖에는 요점을 문장으로 만들어(끝 문장부호만 보충) 공백으로 이어 한 문단으로."""
    ready = str(cap.get("body") or "").strip()
    if ready:
        return ready
    if str(cap.get("style") or "").strip().lower() == "list" or any(p.get("role") == "checklist" for p in pages):
        return "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    return " ".join(_sentence(p) for p in points)


def build_caption(plan: dict[str, Any], topic: dict[str, Any], *, handle: str, ai_images: bool) -> str:
    """승인된 제작안 → 인스타 캡션.

    handle = 인스타 계정(@ 없이), ai_images = 이 묶음에 생성형 AI 이미지가 들어갔는가(렌더 qa["ai_images"])."""
    cap = (plan or {}).get("caption") or {}
    pages = _pages(plan or {})
    cover = next((p for p in pages if p.get("role") == "cover"), {})
    inner = [p for p in pages if p.get("role") not in ("cover", "source")]

    title = _flat(cap.get("title") or "") or _flat(cover.get("heading") or "") or _flat((topic or {}).get("title") or "")
    emoji = (cap.get("emoji") or "").strip()
    head = f"{title} {emoji}".strip()

    intro = _flat(cap.get("intro") or "") or _flat(cover.get("body") or "")

    raw_points = cap.get("points")
    points = [_flat(str(p)) for p in (raw_points if isinstance(raw_points, (list, tuple)) else [])]
    points = [p for p in points if p]
    if not points:   # 제작안에 요점이 없으면 설명 쪽 제목(승인된 글)을 그대로
        points = [h for h in (_flat(p.get("heading") or "") for p in inner) if h]
    points = points[:config.DRINKS_CAPTION_MAX_POINTS]
    body_text = _body(cap, pages, points)

    limit = _flat(cap.get("limit") or "")
    note = f"※ {limit} {config.DRINKS_CAPTION_SOURCE_NOTE}" if limit else f"※ {config.DRINKS_CAPTION_SOURCE_NOTE}"

    share = _flat(cap.get("share_target") or "") or config.DRINKS_CAPTION_SHARE_DEFAULT
    cta = _flat(cap.get("cta") or "") or config.DRINKS_CAPTION_CTA_DEFAULT
    at = (handle or config.DRINKS_IG_HANDLE).lstrip("@")
    ask = f"📌 저장해 두고, {share} 좋아하는 친구에게 공유해 주세요\n🥃 {cta} → @{at} 팔로우"

    sections: list[Optional[str]] = [
        head, intro or None, body_text or None, note, ask,
        f"*{config.DRINKS_CARD_AI_NOTICE}" if ai_images else None,
        " ".join(hashtags(cap.get("hashtags"))),
    ]
    out = "\n\n".join(s for s in sections if s)
    if len(out) > config.DRINKS_CAPTION_MAX_CHARS:
        raise ValueError(f"캡션이 {config.DRINKS_CAPTION_MAX_CHARS}자를 넘습니다({len(out)}자)")
    return out
