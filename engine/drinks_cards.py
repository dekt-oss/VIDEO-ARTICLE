"""주류 공장 C단계 — 카드뉴스 렌더(정적 PNG 묶음, 로컬·무료). 2026-10-23. docs/deviation-drinks-production.md

승인된 카드 제작안(pages[]: cover·explain·compare·checklist·source) → 1080×1350 PNG 묶음.
영상 화면을 캡처하지 않는다. 브랜드·글꼴·줄바꿈·잘림·없는 글자 검사는 engine/drinks_render.py 와 공유한다.
페이지 순서는 제작안 position 그대로(1..n) — 묶음 규칙은 DB(drinks_finish_render)가 다시 잰다.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from . import config
from .drinks_cards_photo import draw_photo_page, is_photo_plan
from .drinks_render import BRAND, MISSING, Rendered, RenderError, _block, _font

CARD_W, CARD_H = 1080, 1350

PAGE_ROLE_LABEL = {"cover": "", "explain": "설명", "compare": "비교", "checklist": "체크리스트", "source": "출처"}


def draw_card_page(page: dict[str, Any], total: int, topic: dict[str, Any], sources: list[dict[str, Any]],
                   claims: dict[str, dict[str, Any]], out_path: str) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    w, h = CARD_W, CARD_H
    img = Image.new("RGB", (w, h), BRAND["bg"])
    d = ImageDraw.Draw(img)
    role = page["role"]
    pos = int(page["position"])
    f_brand, f_head, f_body, f_small = _font("small", 30), _font("head", 70 if role == "cover" else 58), _font("body", 40), _font("small", 28)
    d.rectangle([0, 0, w, 12], fill=BRAND["accent"])
    d.text((70, 52), BRAND["name"], font=f_brand, fill=BRAND["accent"])
    label = PAGE_ROLE_LABEL.get(role, "")
    if label:
        lw = d.textlength(label, font=f_small)
        d.rounded_rectangle([w - 70 - lw - 40, 46, w - 70, 46 + 50], radius=25, outline=BRAND["accent"], width=3)
        d.text((w - 70 - lw - 20, 54), label, font=f_small, fill=BRAND["accent"])
    top = int(h * (0.30 if role == "cover" else 0.14))
    y, cut_h = _block(d, (70, top), page["heading"], f_head, w - 140, BRAND["text"], max_lines=4, role="head",
                      size=70 if role == "cover" else 58)
    body = page.get("body") or ""
    if role == "source":
        refs = [f"· {s.get('publisher') or ''} {s.get('title') or ''}".strip() + (f" ({s['url']})" if s.get("url") else "")
                for s in sources]
        body = (body + "\n" if body else "") + "\n".join(refs)
    cut_b = False
    if role == "checklist" and body:
        # 체크 상자는 글자(☐)가 아니라 도형으로 — 글꼴에 없으면 두부가 된다(실측)
        yy = y + 50
        for ln in [x.lstrip("-•☐ ").strip() for x in body.split("\n") if x.strip()][:10]:
            d.rounded_rectangle([70, yy + 6, 70 + 34, yy + 40], radius=6, outline=BRAND["accent"], width=4)
            yy, c = _block(d, (124, yy), ln, f_body, w - 194, BRAND["text"], max_lines=2, role="body", size=40)
            cut_b = cut_b or c
            yy += 10
        body = ""
    if body:
        _, cut_b = _block(d, (70, y + 50), body, f_body if role != "source" else f_small, w - 140, BRAND["text"] if role != "source" else BRAND["muted"],
                          max_lines=12 if role != "source" else 16, role="body" if role != "source" else "small", size=40 if role != "source" else 28)
    d.text((70, h - 80), f"{pos} / {total}", font=f_small, fill=BRAND["muted"])
    cites = [cid for cid in page.get("claim_ids") or [] if cid in claims]
    if cites:
        t = "근거: " + ", ".join(cites)
        d.text((w - 70 - d.textlength(t, font=f_small), h - 80), t, font=f_small, fill=BRAND["muted"])
    img.save(out_path, "PNG")
    return {"position": pos, "truncated": cut_h or cut_b}


def render_carousel(job: dict[str, Any], work_dir: str, images: Optional[dict[int, str]] = None) -> Rendered:
    """images = {쪽 번호: 배경 사진 경로} — 사진형(layout=photo)에서만 쓴다. card-v1 은 사진 없이 글자 카드(예전 그대로)."""
    plan = job["plan"] or {}
    pages = plan.get("pages") or []
    if not pages:
        raise RenderError("invalid_plan", "페이지가 없습니다")
    if len(pages) > 12:
        raise RenderError("invalid_plan", "카드뉴스는 12장까지입니다")
    photo = is_photo_plan(plan)
    claims = {c["claim_id"]: c for c in job.get("claims") or [] if c.get("claim_id")}
    os.makedirs(work_dir, exist_ok=True)
    MISSING.clear()
    # 사진형: 실제로 있는 파일만 쓴다(경로만 있고 파일이 없으면 '없는 쪽'으로 — photo_missing 경고)
    used = {int(k): v for k, v in (images or {}).items() if photo and v and os.path.exists(v)} if images else {}
    files, page_qa = [], []
    for pg in sorted(pages, key=lambda p: int(p["position"])):
        pos = int(pg["position"])
        path = os.path.join(work_dir, f"page_{pos:02d}.png")
        if photo:
            page_qa.append(draw_photo_page(pg, job.get("sources") or [], used.get(pos), path, ai_images=bool(used)))
        else:
            page_qa.append(draw_card_page(pg, len(pages), job["topic"], job.get("sources") or [], claims, path))
        files.append({"path": path, "role": "page", "position": pos, "mime": "image/png", "width": CARD_W, "height": CARD_H})
    positions = [f["position"] for f in files]
    warnings = []
    if positions != list(range(1, len(files) + 1)):
        warnings.append("page_order_gap")
    if any(q["truncated"] for q in page_qa):
        warnings.append("text_truncated")
    if MISSING:
        warnings.append("glyph_missing")
    no_photo = [q["position"] for q in page_qa if q.get("photo_missing")]
    if no_photo:
        warnings.append("photo_missing")
    qa = {"pages": len(files), "missing_glyphs": sorted(set(MISSING)), "truncated_pages": [q["position"] for q in page_qa if q["truncated"]], "warnings": warnings,
          "size": [CARD_W, CARD_H], "brand": BRAND["version"],
          "template_version": config.DRINKS_CARD_PHOTO_TEMPLATE if photo else plan.get("template_version", "card-v1")}
    if photo:
        # ai_images: 소스 장 고지·캡션의 '생성형 AI 이미지 포함' 줄이 이 값을 따른다(호출자가 넘긴 사진 = 생성 그림)
        qa.update({"photo_missing_pages": no_photo, "generated_pages": sorted(used), "ai_images": bool(used)})
    return Rendered(files, qa, [{"kind": "card", "provider": "local_pillow", "cost_usd": 0, "units": len(files)}])
