"""주류 공장 — 카드뉴스 사진형 배치("생존주의형", 운영자 승인 2026-10-27). docs/deviation-drinks-production.md

사진 전면 + 아래쪽을 어둡게 + 제목(핵심어 강조) + 근거 2줄. 시제품(Node/sharp)을 Pillow 로 옮긴 것이다.
고르는 법: plan["layout"] == "photo" 또는 plan["template_version"] == "card-photo-v1". 그 밖은 card-v1 그대로(drinks_cards.py).

· 배경 사진은 호출자가 넘긴다(images = {쪽 번호: 로컬 경로}). 유료 생성은 engine/drinks_paid.py·drinks_produce.py 몫이고
  여기는 언제나 무료 렌더다. 사진이 없는 쪽은 실패하지 않고 어두운 바탕 + 경고(photo_missing).
· 글자 안의 [대괄호] 는 강조색. 줄바꿈은 낱말(띄어쓰기) 단위 — 한국어 낱말 한가운데서 끊지 않는다.
  낱말 하나가 한 줄보다 길 때만 글자로 자른다(넘치는 것보다 낫다).
· 줄 수 상한·없는 글자 검사는 card-v1 과 같은 통로(drinks_render.MISSING·qa 경고)로 올린다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from . import config
from .drinks_render import BRAND, MISSING, _font, font_for, missing_glyphs

W, H = 1080, 1350
X = 64                      # 좌우 여백
LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "brand", "sooljjerigo-logo-dark.png")
LOGO_H, LOGO_X, CHROME_TOP = 42, X - 6, 54          # 로고 높이·왼쪽 위치·위쪽 위치(쪽 번호는 로고 세로 중앙에 맞춘다)

# 색 — 승인 시제품 값. 강조색은 BRAND["key"] 하나만 쓴다.
WHITE = (255, 255, 255)
BODY = (214, 210, 204)       # #D6D2CC
MUTED = (156, 150, 142)      # #9C968E
RULE = (138, 132, 124)       # #8A847C
SOURCE_BG = (18, 17, 16)     # #121110 — 출처 장의 바탕
SEPARATOR = (58, 54, 49)     # #3A3631 — 팔로우 블록 위의 가는 줄

# 아래 그림자: 시작 높이(비율) → +0.22 지점에서 72% → 맨 아래 94% 검정
SHADE_INNER, SHADE_COVER, SHADE_SPAN = 0.38, 0.42, 0.22
SHADE_MID_ALPHA, SHADE_END_ALPHA = 0.72, 0.94

HEAD_SIZE, HEAD_GAP, HEAD_MAX_LINES = 70, 16, 3
BODY_SIZE, BODY_GAP, BODY_MAX_LINES, BODY_INDENT = 31, 12, 2, 26
BODY_BOTTOM, BODY_HEAD_GAP, RULE_W = 104, 46, 3
COVER_TITLE_SIZE, COVER_TITLE_GAP, COVER_TITLE_MAX_LINES = 82, 22, 3
COVER_SUB_SIZE, COVER_CAT_SIZE, COVER_KICKER_SIZE, COVER_KICKER_TOP = 32, 26, 24, 56
COVER_BOTTOM, COVER_SUB_GAP, COVER_CAT_GAP, COVER_CAT_RULE_GAP = 110, 40, 44, 28
SRC_TITLE_SIZE, SRC_TITLE_TOP, SRC_TITLE_GAP = 50, 190, 48
SRC_REF_SIZE, SRC_REF_GAP, SRC_REF_MAX_LINES, SRC_REF_AFTER = 28, 10, 8, 80
FOLLOW1_SIZE, FOLLOW2_SIZE, FOLLOW3_SIZE, FOLLOW_GAP, FOLLOW_RULE_UP = 34, 64, 30, 22, 70
FOOT_SIZE, FOOT_GAP, FOOT_BOTTOM, FOOT_PAD = 22, 10, 96, 60
PAGE_NO_SIZE = 24

_HOT = re.compile(r"\[([^\[\]]+)\]")


def is_photo_plan(plan: Optional[dict[str, Any]]) -> bool:
    p = plan or {}
    return p.get("layout") == "photo" or p.get("template_version") == config.DRINKS_CARD_PHOTO_TEMPLATE


# ─────────────────────────────────────────────────────────────
# 글자 배치 — 강조 구간을 낱말·줄 경계 너머로 들고 가는 작은 조판기
# ─────────────────────────────────────────────────────────────

Seg = tuple[str, bool]          # (글자, 강조 여부)
Line = list[Seg]


def parse_hot(text: str) -> list[tuple[str, bool]]:
    """'[핵심어]' 를 벗겨 (글자, 강조) 목록으로. 짝이 안 맞는 대괄호는 글자 그대로 둔다."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _HOT.finditer(text or ""):
        out += [(c, False) for c in text[pos:m.start()]]
        out += [(c, True) for c in m.group(1)]
        pos = m.end()
    out += [(c, False) for c in (text or "")[pos:]]
    return out


def _paragraphs(chars: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]:
    """명시한 줄바꿈(\n)에서 문단을 가른다."""
    paras: list[list[tuple[str, bool]]] = [[]]
    for ch in chars:
        if ch[0] == "\n":
            paras.append([])
        else:
            paras[-1].append(ch)
    return paras


def _runs(line: list[tuple[str, bool]]) -> Line:
    """글자별 강조 표시를 같은 값끼리 묶는다."""
    segs: Line = []
    for ch, hot in line:
        if segs and segs[-1][1] == hot:
            segs[-1] = (segs[-1][0] + ch, hot)
        else:
            segs.append((ch, hot))
    return segs


def _plain(line: list[tuple[str, bool]]) -> str:
    return "".join(c for c, _ in line)


def layout_lines(draw, text: str, font, width: int, *, highlight: bool = True) -> list[Line]:
    """글자 → 줄 목록. 명시한 줄바꿈은 지키고, 넘치면 낱말 경계에서 접는다."""
    chars = parse_hot(text) if highlight else [(c, False) for c in (text or "")]
    lines: list[list[tuple[str, bool]]] = []
    for para in _paragraphs(chars):
        # 띄어쓰기로 낱말 나누기(연속 공백은 하나로 접는다)
        words: list[list[tuple[str, bool]]] = [[]]
        for ch in para:
            if ch[0] == " ":
                if words[-1]:
                    words.append([])
            else:
                words[-1].append(ch)
        words = [w for w in words if w]
        cur: list[tuple[str, bool]] = []
        for w in words:
            cand = cur + ([(" ", cur[-1][1] and w[0][1])] if cur else []) + w   # 강조 낱말 사이 공백은 강조로 잇는다
            if draw.textlength(_plain(cand), font=font) <= width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = []
            if draw.textlength(_plain(w), font=font) <= width:
                cur = list(w)
                continue
            for ch in w:     # 낱말 하나가 한 줄보다 길다 — 마지막 수단으로 글자 단위
                if cur and draw.textlength(_plain(cur + [ch]), font=font) > width:
                    lines.append(cur)
                    cur = []
                cur.append(ch)
        lines.append(cur)
    while lines and not lines[-1]:
        lines.pop()
    return [_runs(l) for l in lines]


_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")
HANGUL_TEXT_RATIO = 0.3
_REF_GLYPHS = "가한"          # 글자 위·아래 끝을 재는 기준 글자(받침 없는 낱말 높이 — 줄 상자의 보이는 높이)


def _is_hangul_text(text: str, role: str) -> bool:
    """보정 배율을 쓸 글인가 — 제목체(head)는 늘, 그 밖은 글자의 3할 이상이 한글일 때(영문 출처 줄은 승인본과 폭이 같다)."""
    if role == "head":
        return True
    letters = [c for c in (text or "") if not c.isspace()]
    return bool(letters) and len(_HANGUL.findall(text or "")) / len(letters) >= HANGUL_TEXT_RATIO


@dataclass
class Block:
    """접힌 글 덩어리. 높이는 '보이는 높이'(첫 줄 글자 위끝 ~ 마지막 줄 글자 아래끝)로 잰다 — 시제품과 같은 배치가 나온다."""
    lines: list[Line]
    font: Any
    pitch: int          # 줄 간격(글꼴 줄 상자 + 줄 사이 여백)
    ink_top: int        # 앵커(la) 기준 글자 위끝
    ink_h: int          # 한 줄 글자 높이
    cut: bool

    @property
    def height(self) -> int:
        return (len(self.lines) - 1) * self.pitch + self.ink_h if self.lines else 0

    def width_of(self, draw, i: int) -> float:
        return draw.textlength("".join(t for t, _ in self.lines[i]), font=self.font)


def make_block(draw, text: str, role: str, size: int, width: int, *, gap: int, max_lines: Optional[int] = None,
               highlight: bool = True) -> Block:
    """글자 한 덩어리를 줄로 접고, 줄 수 상한·없는 글자를 검사한다(조용히 넘기지 않는다).

    한글 글·제목체는 글꼴 크기를 DRINKS_CARD_PHOTO_HANGUL_SCALE 배로 그린다(시제품 글꼴 빌드가 이 저장소의 Pretendard 보다
    한글이 약 6% 크다 — 승인본과 같은 폭을 맞추는 보정). 줄 간격은 보정 전 크기로 잰다."""
    nominal = font_for(text, role, size)
    scale = config.DRINKS_CARD_PHOTO_HANGUL_SCALE if _is_hangul_text(text, role) else 1.0
    font = font_for(text, role, round(size * scale)) if scale != 1.0 else nominal
    MISSING.extend(missing_glyphs(font, _plain(parse_hot(text)) if highlight else text))
    lines = layout_lines(draw, text, font, width, highlight=highlight)
    cut = bool(max_lines) and len(lines) > max_lines
    if cut:
        lines = lines[:max_lines]
        last = lines[-1]
        if last:
            t, hot = last[-1]
            last[-1] = (t[:-1] + "…", hot) if len(t) > 1 else ("…", hot)
    asc, desc = nominal.getmetrics()
    _, top, _, bot = font.getbbox(_REF_GLYPHS, anchor="la")
    return Block(lines, font, asc + desc + gap, top, bot - top, cut)


def draw_block(draw, blk: Block, x: float, y: float, base, *, center: bool = False, hot=None) -> None:
    """줄마다 강조 구간 색을 바꿔 그린다. y 는 첫 줄 글자 위끝. center=True 면 x 를 가운데 축으로 본다."""
    hot = hot or BRAND["key"]
    for i, line in enumerate(blk.lines):
        full = "".join(t for t, _ in line)
        x0 = x - draw.textlength(full, font=blk.font) / 2 if center else x
        done = ""
        for t, is_hot in line:
            # 앞 글자 폭을 합쳐서 잰다 — 조각마다 따로 재면 자간(커닝)이 어긋난다
            draw.text((x0 + draw.textlength(done, font=blk.font), y - blk.ink_top + i * blk.pitch), t, font=blk.font,
                      fill=hot if is_hot else base)
            done += t


# ─────────────────────────────────────────────────────────────
# 그림 층
# ─────────────────────────────────────────────────────────────

def _cover_fit(im, shift: int):
    """폭 1080 에 맞추고 높이 1350 으로 자른다. 위로 더 보이게 하려면 shift 를 음수로(시제품: 표지 -110)."""
    from PIL import Image

    im = im.convert("RGB")
    scale = max(W / im.width, H / im.height)    # 4:5 그림이면 정확히 폭 맞춤. 더 납작한 그림은 높이를 채운다
    sw, sh = round(im.width * scale), round(im.height * scale)
    im = im.resize((sw, sh), Image.LANCZOS)
    top = max(0, min(sh - H, -int(shift)))
    return im.crop((0, top, W, top + H))


def _shade(img, start: float) -> None:
    """아래쪽을 어둡게(투명 → 72% → 94% 검정)."""
    from PIL import Image

    y0, y1 = start * H, (start + SHADE_SPAN) * H
    col = []
    for y in range(H):
        if y <= y0:
            a = 0.0
        elif y <= y1:
            a = SHADE_MID_ALPHA * (y - y0) / (y1 - y0)
        else:
            a = SHADE_MID_ALPHA + (SHADE_END_ALPHA - SHADE_MID_ALPHA) * (y - y1) / (H - y1)
        col.append(round(a * 255))
    mask = Image.new("L", (1, H))
    mask.putdata(col)
    img.paste((0, 0, 0), mask=mask.resize((W, H)))


def _chrome(img, d, pos: int) -> None:
    """위쪽 로고(왼쪽)와 두 자리 쪽 번호(오른쪽)."""
    from PIL import Image

    with Image.open(LOGO_PATH) as lg:
        lg = lg.convert("RGBA")
        lg = lg.resize((round(lg.width * LOGO_H / lg.height), LOGO_H), Image.LANCZOS)
    img.paste(lg, (LOGO_X, CHROME_TOP), lg)
    f = font_for("00", "small", PAGE_NO_SIZE)
    txt = f"{pos:02d}"
    _, top, _, bot = f.getbbox(txt, anchor="la")
    d.text((W - X - d.textlength(txt, font=f), CHROME_TOP + (LOGO_H - (bot - top)) / 2 - top), txt, font=f, fill=MUTED)


def _rule(d, x: int, y: float, h: int) -> None:
    d.rectangle([x, round(y), x + RULE_W - 1, round(y) + h - 1], fill=RULE)


# ─────────────────────────────────────────────────────────────
# 쪽
# ─────────────────────────────────────────────────────────────

def _background(page: dict[str, Any], photo: Optional[str], shade: float):
    from PIL import Image

    if not photo:
        return Image.new("RGB", (W, H), BRAND["bg"])
    with Image.open(photo) as im:
        img = _cover_fit(im, int(page.get("photo_shift") or 0))
    _shade(img, shade)
    return img


def _draw_cover(page, photo):
    from PIL import ImageDraw

    img = _background(page, photo, SHADE_COVER)
    d = ImageDraw.Draw(img)
    cut = False
    kicker = page.get("kicker") or config.DRINKS_CARD_KICKER_DEFAULT
    k = make_block(d, kicker, "small", COVER_KICKER_SIZE, W - 2 * X, gap=0, max_lines=1, highlight=False)
    draw_block(d, k, W / 2, COVER_KICKER_TOP, MUTED, center=True)
    title = make_block(d, page.get("heading") or "", "head", COVER_TITLE_SIZE, W - 2 * X, gap=COVER_TITLE_GAP,
                       max_lines=COVER_TITLE_MAX_LINES)
    sub = make_block(d, page.get("body") or "", "small", COVER_SUB_SIZE, W - 2 * X, gap=12, max_lines=2, highlight=False)
    cat = make_block(d, page.get("category") or "", "small", COVER_CAT_SIZE, 400, gap=0, max_lines=1, highlight=False)
    cut = k.cut or title.cut or sub.cut or cat.cut
    y = H - COVER_BOTTOM - sub.height - COVER_SUB_GAP - title.height - COVER_CAT_GAP - cat.height
    if cat.lines:
        cw = cat.width_of(d, 0)
        mid = round(y + cat.height / 2)
        d.line([(X, mid), ((W - cw) / 2 - COVER_CAT_RULE_GAP, mid)], fill=RULE, width=2)
        d.line([((W + cw) / 2 + COVER_CAT_RULE_GAP, mid), (W - X, mid)], fill=RULE, width=2)
        draw_block(d, cat, W / 2, y, BRAND["key"], center=True)
    y += cat.height + COVER_CAT_GAP
    draw_block(d, title, W / 2, y, WHITE, center=True)
    y += title.height + COVER_SUB_GAP
    draw_block(d, sub, W / 2, y, BODY, center=True)
    return img, cut


def _draw_inner(page, photo, pos):
    from PIL import ImageDraw

    img = _background(page, photo, SHADE_INNER)
    d = ImageDraw.Draw(img)
    head = make_block(d, page.get("heading") or "", "head", HEAD_SIZE, W - 2 * X, gap=HEAD_GAP, max_lines=HEAD_MAX_LINES)
    body = make_block(d, page.get("body") or "", "small", BODY_SIZE, W - 2 * X - 28, gap=BODY_GAP, max_lines=BODY_MAX_LINES,
                      highlight=False)
    by = H - BODY_BOTTOM - body.height
    hy = by - BODY_HEAD_GAP - head.height
    draw_block(d, head, X, hy, WHITE)
    if body.lines:
        _rule(d, X, by, body.height)
        draw_block(d, body, X + BODY_INDENT, by, BODY)
    _chrome(img, d, pos)
    return img, head.cut or body.cut


def _source_lines(page: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    if page.get("body"):
        return page["body"]
    refs = []
    for s in sources or []:
        head = f"{s.get('publisher') or ''} {s.get('title') or ''}".strip()
        if s.get("url"):
            head += f"\n{s['url']}"
        if head:
            refs.append(head)
    return "\n".join(refs)


def _draw_source(page, pos, sources, ai_images: bool):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), SOURCE_BG)
    d = ImageDraw.Draw(img)
    _chrome(img, d, pos)
    title = make_block(d, config.DRINKS_CARD_SOURCE_TITLE, "head", SRC_TITLE_SIZE, W - 2 * X, gap=0, max_lines=1, highlight=False)
    refs = make_block(d, _source_lines(page, sources), "small", SRC_REF_SIZE, W - 2 * X - 28, gap=SRC_REF_GAP,
                      max_lines=SRC_REF_MAX_LINES, highlight=False)
    foot_text = (config.DRINKS_CARD_AI_NOTICE + "\n" if ai_images else "") + config.DRINKS_CARD_WARNING
    foot = make_block(d, foot_text, "small", FOOT_SIZE, W - 2 * X, gap=FOOT_GAP, highlight=False)
    y = SRC_TITLE_TOP
    draw_block(d, title, X, y, WHITE)
    y += title.height + SRC_TITLE_GAP
    if refs.lines:
        _rule(d, X, y, refs.height)
        draw_block(d, refs, X + BODY_INDENT, y, BODY)
        y += refs.height
    y += SRC_REF_AFTER
    # 팔로우 유도 — 참조자료와 아래 고지 사이, 가운데
    c1 = make_block(d, config.DRINKS_CARD_FOLLOW_LINE1, "body", FOLLOW1_SIZE, W - 2 * X, gap=0, max_lines=1, highlight=False)
    c2 = make_block(d, "@" + config.DRINKS_IG_HANDLE, "head", FOLLOW2_SIZE, W - 2 * X, gap=0, max_lines=1, highlight=False)
    c3 = make_block(d, config.DRINKS_CARD_FOLLOW_LINE3, "small", FOLLOW3_SIZE, W - 2 * X, gap=0, max_lines=1, highlight=False)
    ch = c1.height + FOLLOW_GAP + c2.height + FOLLOW_GAP + c3.height
    cy = round((y + (H - FOOT_BOTTOM - foot.height - FOOT_PAD)) / 2 - ch / 2)
    d.rectangle([X, cy - FOLLOW_RULE_UP, W - X - 1, cy - FOLLOW_RULE_UP + 1], fill=SEPARATOR)
    for blk, color in ((c1, BODY), (c2, BRAND["key"]), (c3, MUTED)):
        draw_block(d, blk, W / 2, cy, color, center=True)
        cy += blk.height + FOLLOW_GAP
    draw_block(d, foot, X, H - FOOT_BOTTOM - foot.height, MUTED)
    return img, title.cut or refs.cut or c1.cut or c2.cut or c3.cut or foot.cut


def draw_photo_page(page: dict[str, Any], sources: list[dict[str, Any]], photo: Optional[str], out_path: str, *,
                    ai_images: bool = False) -> dict[str, Any]:
    """쪽 하나를 그려 PNG 로 저장. 반환: {position, truncated, photo_missing}."""
    role = page["role"]
    pos = int(page["position"])
    if role == "source":
        img, cut = _draw_source(page, pos, sources, ai_images)
    elif role == "cover":
        img, cut = _draw_cover(page, photo)
    else:
        img, cut = _draw_inner(page, photo, pos)
    img.save(out_path, "PNG")
    return {"position": pos, "truncated": cut, "photo_missing": role != "source" and not photo}
