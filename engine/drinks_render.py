"""주류 공장 C단계 — 영상·카드뉴스 렌더(로컬, 유료 호출 0). 2026-10-23. docs/deviation-drinks-production.md

영상: 승인된 영상 제작안(scenes[]) → 기존 영상 엔진의 지시서 모양(cuts[]) → `render.render_directive_local`
(엔진의 TTS → 컷 mp4(Ken Burns) → 자막 ASS → 조립·음량 정규화 경로를 그대로 탄다). 논문 전용 검증·표를 거치지 않는다:
directive_id 없이 부르므로 자산 캐시·논문 원장·논문 GC 경로에 닿지 않는다.

★ 지금 그림은 **대체 에셋**이다 — `IMAGE_PROVIDER=reuse` 로 이 모듈이 Pillow 로 그린 "장면 카드"를 쓴다(생성 0회·비용 0).
  목표 화풍(3D 도해·실사감·시네마틱)은 유료 이미지·영상 생성이 있어야 나오고, 예산이 정해지기 전에는 꺼져 있다.
  이 렌더로 검증되는 것: 제작안 → 장면·음성·자막·합성·세로 영상·커버·파일 묶음 흐름. 검증되지 **않는** 것: 그림 품질.
★ 장면 카드마다 장면 유형을 박는다(연출 장면·실제 제품 아님 / 설명용 도해). 생성 영상이 실제 촬영·정확한 제조 과정으로
  오해되지 않게 — 유료 그림으로 바꿔도 같은 표기를 오버레이로 유지한다(검수 체크리스트 scene_types_labeled).

카드뉴스는 engine/drinks_cards.py(같은 브랜드·글꼴·잘림/없는 글자 검사를 공유).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

from . import config

BRAND = {
    "name": "술째리고",
    "version": "drinks-brand-v1",
    "bg": (24, 20, 16), "panel": (40, 33, 26), "accent": (232, 168, 64), "text": (246, 240, 230), "muted": (178, 166, 150),
    "warn": (240, 120, 90),
}
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
FONTS = {"head": "Pretendard-ExtraBold.otf", "body": "Pretendard-Bold.otf", "small": "Pretendard-Medium.otf"}
# Pretendard 에는 가나·한자가 없다(일본 출처 제목이 두부 글자로 나온 실측 2026-10-23). 일본어·중국어 글자가 든 줄만 이 글꼴로.
CJK_FONT_CANDIDATES = [
    os.getenv("DRINKS_CJK_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # CI(fonts-noto-cjk)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/msgothic.ttc",
]
_KANA_HAN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")

# 장면 유형 표기 — 화면에 그대로 나간다(오인 방지). 제작안 visual_role 기준.
SCENE_LABEL = {
    "reality": "연출 장면 · 실제 제품·시설 촬영 아님",
    "mechanism": "설명용 도해 · 실제 공정을 단순화함",
    "text_card": "정리 카드",
    "other": "설명 장면",
}
VIDEO_EFFECTS = ["ken_burns_zoom_in", "pan_right", "ken_burns_zoom_out", "pan_left"]


class RenderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def _font(role: str, size: int):
    from PIL import ImageFont

    path = os.path.join(FONT_DIR, FONTS[role])
    if not os.path.exists(path):
        raise RenderError("font_missing", f"글꼴 파일이 없습니다: {path}")   # 기본 글꼴로 조용히 바꾸지 않는다
    return ImageFont.truetype(path, size)


def _cjk_font(size: int):
    from PIL import ImageFont

    for path in CJK_FONT_CANDIDATES:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    return None


def font_for(text: str, role: str, size: int):
    """글에 가나·한자가 있으면 CJK 글꼴(있을 때), 아니면 브랜드 글꼴."""
    if _KANA_HAN.search(text or ""):
        f = _cjk_font(size)
        if f is not None:
            return f
    return _font(role, size)


def missing_glyphs(font, text: str) -> list[str]:
    """글꼴에 없는 글자(두부 □ 로 찍히는 것). 없는 글자 모양 = 'notdef' 모양과 같다는 점으로 잰다."""
    from PIL import Image, ImageDraw

    def shape(ch: str) -> bytes:
        im = Image.new("L", (font.size * 2, font.size * 2))
        ImageDraw.Draw(im).text((0, 0), ch, font=font, fill=255)
        return im.tobytes()

    notdef = shape("\uffff")
    return [ch for ch in sorted(set(text or "")) if not ch.isspace() and shape(ch) == notdef]


def wrap(draw, text: str, font, width: int) -> list[str]:
    """글자 단위로 줄바꿈(한국어는 띄어쓰기가 없어도 넘치지 않게). 낱말 경계를 먼저 쓴다."""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        line = ""
        for token in re.findall(r"\S+\s*|\s+", para):
            cand = line + token
            if draw.textlength(cand.rstrip(), font=font) <= width:
                line = cand
                continue
            if line.strip():
                lines.append(line.rstrip())
                line = ""
            for ch in token:   # 낱말 하나가 한 줄보다 길면 글자로 자른다
                if draw.textlength((line + ch).rstrip(), font=font) <= width:
                    line += ch
                else:
                    lines.append(line.rstrip())
                    line = ch
        if line.strip():
            lines.append(line.rstrip())
    return lines


MISSING: list[str] = []   # 이번 렌더에서 두부로 찍힌 글자(렌더마다 비운다 — qa 로 올린다)


def _block(draw, xy, text, font, width, fill, line_gap=1.28, max_lines=None, role: str = "", size: int = 0) -> tuple[int, bool]:
    """여러 줄 글. (끝 y, 잘렸는가) — 잘림·없는 글자는 검수 qa 로 올린다(조용히 넘기지 않는다)."""
    x, y = xy
    if role and size:
        font = font_for(text, role, size)
    MISSING.extend(missing_glyphs(font, text))
    lines = wrap(draw, text, font, width)
    cut = bool(max_lines) and len(lines) > max_lines
    if cut:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…" if lines[-1] else "…"
    size = font.size
    for ln in lines:
        draw.text((x, y), ln, font=font, fill=fill)
        y += int(size * line_gap)
    return y, cut


# ─────────────────────────────────────────────────────────────
# 영상
# ─────────────────────────────────────────────────────────────

def plan_to_directive(plan: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    """승인된 영상 제작안 → 엔진 지시서(이미지 나열식). 엔진이 실제로 받는 필드만 만든다."""
    scenes = plan.get("scenes") or []
    if not scenes:
        raise RenderError("invalid_plan", "장면이 없습니다")
    cuts = []
    for i, sc in enumerate(scenes, start=1):
        role = sc.get("visual_role") or "reality"
        cuts.append({
            "cut_no": i, "scene_kind": "broll_stock", "visual_type": "image",
            "estimated_sec": max(2, min(20, int(round(float(sc.get("timing_sec") or 4))))),
            # 유료 그림으로 바꿀 때 쓸 문장(지금은 쓰이지 않는다 — 장면 카드를 재사용한다).
            "visual_prompt": f"[{role}] {sc.get('explanation') or sc.get('narration')}",
            "effects": [VIDEO_EFFECTS[(i - 1) % len(VIDEO_EFFECTS)]],
            "narration_ko": sc["narration"], "narration_en": "",
            "source_facts": list(sc.get("claim_ids") or []),
            "drinks_visual_role": role,
        })
    return {"version_type": "image_sequence",
            "header": {"version_type": "image_sequence", "aspect_ratio": "9:16", "global_style": "drinks local stand-in cards",
                       "hook_ko": topic.get("question") or "", "total_estimated_sec": sum(c["estimated_sec"] for c in cuts)},
            "cuts": cuts}


def draw_scene_card(scene: dict[str, Any], idx: int, total: int, topic: dict[str, Any], out_path: str) -> dict[str, Any]:
    """세로 장면 카드(대체 에셋). 아래 30% 는 자막 자리라 비운다."""
    from PIL import Image, ImageDraw

    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    role = scene.get("visual_role") or "reality"
    img = Image.new("RGB", (w, h), BRAND["bg"])
    d = ImageDraw.Draw(img)
    # 배경 띠(역할마다 다른 패널) — 같은 편 안에서 장면 종류가 눈에 보이게
    d.rectangle([0, int(h * 0.12), w, int(h * 0.66)], fill=BRAND["panel"])
    tag = SCENE_LABEL.get(role, SCENE_LABEL["other"])
    f_tag, f_main, f_small = _font("small", 38), _font("head", 76), _font("small", 30)
    # 카메라 움직임(Ken Burns·패닝)이 가장자리를 최대 ~12% 잘라낸다 — 표기는 안쪽 안전 영역에만 둔다.
    m = int(w * 0.14)
    tw = d.textlength(tag, font=f_tag)
    d.rounded_rectangle([m, int(h * 0.15), m + tw + 48, int(h * 0.15) + 64], radius=32,
                        fill=BRAND["accent"] if role != "reality" else BRAND["warn"])
    d.text((m + 24, int(h * 0.15) + 10), tag, font=f_tag, fill=BRAND["bg"])
    d.text((m, int(h * 0.15) + 84), "대체 이미지(로컬 초안) — 최종 그림 아님", font=f_small, fill=BRAND["muted"])
    main = scene.get("explanation") or scene.get("narration") or ""
    _, cut = _block(d, (m, int(h * 0.25)), main, f_main, w - 2 * m, BRAND["text"], max_lines=6, role="head", size=76)
    # 쪽 번호·브랜드는 위쪽에 — 엔진 자막이 화면 중간 아래(약 60%)에 얹힌다.
    d.text((m, int(h * 0.105)), f"{idx} / {total}", font=f_small, fill=BRAND["muted"])
    d.text((w - m - d.textlength(BRAND["name"], font=f_small), int(h * 0.105)), BRAND["name"], font=f_small, fill=BRAND["accent"])
    img.save(out_path, "PNG")
    return {"truncated": cut, "label": tag}


def draw_cover(topic: dict[str, Any], plan: dict[str, Any], out_path: str, size=(1080, 1920)) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGB", (w, h), BRAND["bg"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 18], fill=BRAND["accent"])
    f_brand, f_title, f_q = _font("small", 40), _font("head", 92), _font("body", 50)
    d.text((80, 120), BRAND["name"], font=f_brand, fill=BRAND["accent"])
    y, cut1 = _block(d, (80, int(h * 0.28)), topic.get("title") or "", f_title, w - 160, BRAND["text"], max_lines=5, role="head", size=92)
    _, cut2 = _block(d, (80, y + 40), f"Q. {topic.get('question') or ''}", f_q, w - 160, BRAND["muted"], max_lines=4, role="body", size=50)
    img.save(out_path, "PNG")
    return {"truncated": cut1 or cut2}


def _probe(path: str) -> dict[str, Any]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    return {"width": v.get("width"), "height": v.get("height"), "duration_sec": float(data["format"]["duration"]), "audio_streams": len(a)}


def _mean_volume_db(path: str) -> Optional[float]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr)
    return float(m.group(1)) if m else None


@dataclass
class Rendered:
    files: list[dict[str, Any]]     # {path, role, position, mime, width?, height?, duration_ms?}
    qa: dict[str, Any]
    costs: list[dict[str, Any]]


def _guard_free(tts: str) -> None:
    """유료 공급자가 하나라도 켜져 있으면 렌더하지 않는다(예산 미설정 — 유료 생성 비활성)."""
    if tts not in ("edge", "placeholder"):
        raise RenderError("paid_disabled", f"유료 TTS({tts})는 예산이 정해지지 않아 꺼져 있습니다")
    config.IMAGE_PROVIDER = "reuse"
    config.VIDEO_PROVIDER = "placeholder"
    config.TTS_PROVIDER = tts
    if config.image_is_paid() or config.video_is_paid():
        raise RenderError("paid_disabled", "유료 이미지·영상 공급자가 켜져 있습니다")


def render_video(job: dict[str, Any], work_dir: str, *, tts: str = "edge") -> Rendered:
    from . import render as engine_render   # 무거운 엔진 import 는 여기서만

    _guard_free(tts)
    plan, topic = job["plan"], job["topic"]
    scenes = plan.get("scenes") or []
    cards = os.path.join(work_dir, "cards")
    os.makedirs(cards, exist_ok=True)
    MISSING.clear()
    card_qa = [draw_scene_card(sc, i, len(scenes), topic, os.path.join(cards, f"{i:03d}.png")) for i, sc in enumerate(scenes, 1)]
    config.IMAGE_REUSE_DIR = cards
    directive = plan_to_directive(plan, topic)
    engine_render.take_placeholder_fallbacks()  # 앞 작업의 전역 기록을 비운다(엔진 규칙)
    out = os.path.join(work_dir, "final.mp4")
    engine_dir = os.path.join(work_dir, "engine")
    os.makedirs(engine_dir, exist_ok=True)   # 엔진은 작업 폴더를 만들지 않는다
    engine_render.render_directive_local(directive, out, work_dir=engine_dir, lang="ko")
    placeholders = engine_render.take_placeholder_fallbacks()
    if placeholders:
        raise RenderError("placeholder_cuts", f"빈 화면으로 대체된 장면이 있습니다: {placeholders}")
    cover = os.path.join(work_dir, "cover.png")
    cover_qa = draw_cover(topic, plan, cover)
    probe = _probe(out)
    vol = _mean_volume_db(out)
    warnings = []
    if (probe["width"], probe["height"]) != (config.RENDER_WIDTH, config.RENDER_HEIGHT):
        warnings.append("not_vertical_1080x1920")
    if probe["audio_streams"] == 0 or (vol is not None and vol < -60):
        warnings.append("narration_silent")   # TTS 실패는 엔진이 무음으로 넘긴다 — 여기서 드러낸다
    if any(c["truncated"] for c in card_qa) or cover_qa["truncated"]:
        warnings.append("text_truncated")
    if MISSING:
        warnings.append("glyph_missing")
    qa = {"probe": probe, "mean_volume_db": vol, "missing_glyphs": sorted(set(MISSING)), "scenes": len(scenes), "scene_labels": [c["label"] for c in card_qa],
          "warnings": warnings, "stand_in_visuals": True, "tts": tts, "brand": BRAND["version"],
          "note": "대체 이미지 렌더 — 흐름 검증용. 목표 화풍 품질 검증이 아니다"}
    costs = [{"kind": "tts", "provider": tts, "model": config.EDGE_TTS_VOICE if tts == "edge" else None, "cost_usd": 0,
              "units": len(scenes), "note": "무료 TTS"},
             {"kind": "render", "provider": "local_ffmpeg", "cost_usd": 0, "note": "장면 카드(Pillow)·조립(ffmpeg)"}]
    files = [{"path": out, "role": "final_video", "position": 1, "mime": "video/mp4", "width": probe["width"],
              "height": probe["height"], "duration_ms": int(probe["duration_sec"] * 1000)},
             {"path": cover, "role": "cover", "position": 1, "mime": "image/png", "width": 1080, "height": 1920}]
    return Rendered(files, qa, costs)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
