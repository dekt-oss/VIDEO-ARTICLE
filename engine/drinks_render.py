"""주류 공장 C단계 — 영상·카드뉴스 렌더(로컬, 유료 호출 0). 2026-10-23. docs/deviation-drinks-production.md

영상: 승인된 영상 제작안(scenes[]) → 기존 영상 엔진의 지시서 모양(cuts[]) → `render.render_directive_local`
(엔진의 TTS → 컷 mp4(Ken Burns) → 자막 ASS → 조립·음량 정규화 경로를 그대로 탄다). 논문 전용 검증·표를 거치지 않는다:
directive_id 없이 부르므로 자산 캐시·논문 원장·논문 GC 경로에 닿지 않는다.

★ 기본 그림은 **대체 에셋**이다 — `IMAGE_PROVIDER=reuse` 로 이 모듈이 Pillow 로 그린 "장면 카드"를 쓴다(생성 0회·비용 0).
  목표 화풍(3D 도해·무광 CG)은 유료 생성으로만 나온다 — 그림은 engine/drinks_paid.py 가 **결재 안에서 미리 사 두고**
  (0054 drink_spend_holds), 여기는 그 그림을 `images` 로 받아 장면 유형 표기만 얹어 쓴다. 이 모듈 자체는 언제나 무료다.
  대체 카드 렌더로 검증되는 것: 제작안 → 장면·음성·자막·합성·세로 영상·커버·파일 묶음 흐름. 검증되지 **않는** 것: 그림 품질.
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


def _draw_role_badge(d, scene: dict[str, Any], idx: int, total: int, *, num_y: float = 0.105, tag_y: float = 0.15) -> str:
    """그림 위에 얹는 장면 유형 표기(배지) + 쪽 번호 + 브랜드. 반환 = 배지 문구.

    산 그림(label_image)과 카드뉴스 페이지(compose_card_page)가 같은 문구·같은 안전 영역을 쓴다(검수 scene_types_labeled).
    num_y·tag_y 는 화면 높이 비율 — 기본값은 그림 위(꽉 채운 배경), 카드 페이지는 위쪽 띠 안으로 올린다."""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    role = scene.get("visual_role") or "reality"
    tag = SCENE_LABEL.get(role, SCENE_LABEL["other"])
    f_tag, f_small = _font("small", 38), _font("small", 30)
    m = int(w * 0.14)   # 카메라 움직임이 가장자리를 잘라도 표기가 남는 안쪽
    ty, ny = int(h * tag_y), int(h * num_y)
    tw = d.textlength(tag, font=f_tag)
    d.rounded_rectangle([m, ty, m + tw + 48, ty + 64], radius=32, fill=BRAND["accent"] if role != "reality" else BRAND["warn"])
    d.text((m + 24, ty + 10), tag, font=f_tag, fill=BRAND["bg"])
    d.text((m, ny), f"{idx} / {total}", font=f_small, fill=BRAND["text"], stroke_width=2, stroke_fill=BRAND["bg"])
    d.text((w - m - d.textlength(BRAND["name"], font=f_small), ny), BRAND["name"], font=f_small, fill=BRAND["accent"],
           stroke_width=2, stroke_fill=BRAND["bg"])
    return tag


def label_image(src: str, scene: dict[str, Any], idx: int, total: int, out_path: str) -> dict[str, Any]:
    """산 그림(유료 생성) 위에 장면 유형 표기를 얹는다 — 대체 카드와 같은 문구·같은 안전 영역(검수 scene_types_labeled).

    그림은 9:16 으로 꽉 채워 자른다(엔진 조립과 같은 cover-crop). 글자는 그림에 굽지 않고 여기서만 얹는다."""
    from PIL import Image, ImageDraw, ImageOps

    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    with Image.open(src) as im:
        img = ImageOps.fit(im.convert("RGB"), (w, h), method=Image.LANCZOS)
    tag = _draw_role_badge(ImageDraw.Draw(img), scene, idx, total)
    img.save(out_path, "PNG")
    return {"truncated": False, "label": tag}


def card_page_of(scene: dict[str, Any]) -> Optional[int]:
    """장면의 card_page(1~20 정수) — 없거나 잘못되면 None(DB 가 이미 거른 값이지만 워커도 믿지 않는다)."""
    raw = scene.get("card_page")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != int(raw) or not 1 <= int(raw) <= 20:
        return None
    return int(raw)


def compose_card_page(src: str, scene: dict[str, Any], idx: int, total: int, out_path: str) -> dict[str, Any]:
    """카드뉴스 페이지(1080×1350)를 1080×1920 브랜드 배경 위 세로 가운데에 놓는다 — 자르지 않는다(cover-crop 없음).

    페이지가 다른 크기면 비율을 지킨 채 화면 안에 들어가게만 줄이거나 늘린다. 장면 유형 배지·쪽 번호는 위쪽 띠(페이지 위)에 얹는다.
    그림이 곧 페이지 글자라서 explanation 카드와 달리 글자 잘림 검사 대상이 아니다(페이지 자체는 카드 검수를 통과한 것)."""
    from PIL import Image, ImageDraw

    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    img = Image.new("RGB", (w, h), BRAND["bg"])
    with Image.open(src) as im:
        page = im.convert("RGB")
    scale = min(w / page.width, h / page.height)
    if scale != 1.0:
        page = page.resize((max(1, int(round(page.width * scale))), max(1, int(round(page.height * scale)))), Image.LANCZOS)
    img.paste(page, ((w - page.width) // 2, (h - page.height) // 2))
    # 위쪽 띠: 1920 에서 페이지(1350) 위가 285px — 번호·브랜드 줄(9%)과 배지(11%)가 그 안에 든다.
    tag = _draw_role_badge(ImageDraw.Draw(img), scene, idx, total, num_y=0.09, tag_y=0.111)
    img.save(out_path, "PNG")
    return {"truncated": False, "label": tag, "card_page": True}


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
    img.convert("RGB").save(out_path, "JPEG", quality=config.DRINKS_COVER_JPEG_QUALITY)   # 릴스 표지는 JPEG(규격) — docs/진단_주류릴스엔진_2026-10-28.md
    return {"truncated": cut1 or cut2}


def _probe(path: str) -> dict[str, Any]:
    out = subprocess.run(["ffprobe", "-v", "error",
                          "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate,r_frame_rate:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    return {"width": v.get("width"), "height": v.get("height"), "duration_sec": float(data["format"]["duration"]), "audio_streams": len(a),
            "video_codec": v.get("codec_name"), "audio_codec": a[0].get("codec_name") if a else None,
            "audio_sample_rate": int(a[0]["sample_rate"]) if a and a[0].get("sample_rate") else None,
            "fps": _parse_fps(v.get("r_frame_rate"))}


def _parse_fps(raw: Optional[str]) -> Optional[float]:
    """ffprobe r_frame_rate("30/1") → 30.0. 읽을 수 없으면 None."""
    try:
        num, _, den = str(raw).partition("/")
        return round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        return None


def moov_before_mdat(path: str) -> bool:
    """mp4 최상위 박스를 훑어 moov 가 mdat 보다 앞에 있으면 True(릴스 규격: moov 앞)."""
    import struct

    seen: dict[str, int] = {}
    size_total = os.path.getsize(path)
    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= size_total:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                break
            size, kind = struct.unpack(">I4s", head)
            name = kind.decode("latin-1")
            if size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    break
                size = struct.unpack(">Q", ext)[0]
            elif size == 0:
                size = size_total - pos
            seen.setdefault(name, pos)
            if "moov" in seen and "mdat" in seen:
                break
            if size < 8:
                break
            pos += size
    return "moov" in seen and ("mdat" not in seen or seen["moov"] < seen["mdat"])


def reel_spec_warnings(probe: dict[str, Any], file_bytes: int, moov_first: bool, cover_mime: str, cover_bytes: int) -> list[str]:
    """인스타 릴스 규격 위반 코드 목록(순수 함수). 경고일 뿐 작업을 막지 않는다 — config.DRINKS_REEL_SPEC 기준."""
    spec = config.DRINKS_REEL_SPEC
    out: list[str] = []
    rate = probe.get("audio_sample_rate")
    if rate is not None and rate > spec["audio_sample_rate_max"]:
        out.append("reel_audio_rate_over_48k")
    if not moov_first:
        out.append("reel_moov_not_first")
    dur = probe.get("duration_sec")
    if dur is None or not (spec["min_sec"] <= float(dur) <= spec["max_sec"]):
        out.append("reel_duration_out_of_range")
    if (probe.get("width") or 0) > spec["max_width"]:
        out.append("reel_width_over_1920")
    fps, (lo, hi) = probe.get("fps"), spec["fps_range"]
    if fps is None or not (lo <= fps <= hi):
        out.append("reel_fps_out_of_range")
    if probe.get("video_codec") not in spec["video_codecs"]:
        out.append("reel_video_codec")
    if probe.get("audio_codec") != spec["audio_codec"]:
        out.append("reel_audio_codec")
    if file_bytes > spec["max_bytes"]:
        out.append("reel_file_too_big")
    if cover_mime != spec["cover_mime"]:
        out.append("reel_cover_not_jpeg")
    if cover_bytes > spec["cover_max_bytes"]:
        out.append("reel_cover_too_big")
    return out


def _mean_volume_db(path: str) -> Optional[float]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr)
    return float(m.group(1)) if m else None


def count_syllables(narrations: list[str]) -> int:
    """나레이션 음절 수 — 공백·문장부호를 뺀 글자 수(한글은 한 글자 = 한 음절). 숫자도 글자로 센다."""
    return sum(1 for text in narrations for ch in (text or "") if ch.isalnum())


def speech_rate(narrations: list[str], final_sec: float, playback_speed: float, tts_rate: str) -> dict[str, Any]:
    """말 속도(최종 영상 기준 음절/초). 주류가 5.9 였다(2026-10-28 실측) — 경고는 호출쪽이 문턱과 비교한다."""
    syl = count_syllables(narrations)
    rate = round(syl / final_sec, 2) if final_sec and final_sec > 0 else 0.0
    return {"syllables": syl, "final_sec": round(float(final_sec), 2), "syl_per_sec": rate,
            "playback_speed": float(playback_speed), "tts_rate": tts_rate}


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
    # 주류 자막은 뜻 단위로 끊는다(2026-10-24 운영자 판정). 논문·리포트 렌더는 이 함수를 지나지 않는다.
    config.CAPTION_PHRASE_BREAKS = True
    # 속도는 TTS +10% 한 곳에서만 올린다 — 논문 라인의 조립 끝 1.2× 는 주류에서 겹쳐 5.9음절/초였다(config.DRINKS_PLAYBACK_SPEED 주석).
    config.RENDER_PLAYBACK_SPEED = config.DRINKS_PLAYBACK_SPEED
    if config.image_is_paid() or config.video_is_paid():
        raise RenderError("paid_disabled", "유료 이미지·영상 공급자가 켜져 있습니다")


def render_video(job: dict[str, Any], work_dir: str, *, tts: str = "edge", images: Optional[dict[int, str]] = None,
                 card_pages: Optional[dict[int, str]] = None) -> Rendered:
    """images = {장면 번호: 산 그림 경로}. 주어진 장면은 그 그림(+장면 유형 표기), 나머지는 로컬 대체 카드.
    card_pages = {카드뉴스 페이지 번호: 로컬 PNG 경로}. 장면이 card_page: N 이면 그 페이지가 장면 그림이다(0원, 자르지 않고 배경 위에 놓음).
      페이지가 없으면 대체 카드로 되돌리고 card_page_missing 경고를 남긴다. 산 그림(images)이 있는 장면은 그쪽이 우선.

    ★ 조립 자체는 언제나 무료 경로다 — 그림은 미리 사 두고(engine/drinks_paid.py) 여기서는 재사용(reuse)만 한다."""
    from . import render as engine_render   # 무거운 엔진 import 는 여기서만

    _guard_free(tts)
    plan, topic = job["plan"], job["topic"]
    scenes = plan.get("scenes") or []
    cards = os.path.join(work_dir, "cards")
    os.makedirs(cards, exist_ok=True)
    MISSING.clear()
    images = images or {}
    card_pages = card_pages or {}
    card_qa: list[dict[str, Any]] = []
    from_pages: list[int] = []      # 카드뉴스 페이지를 그림으로 쓴 장면
    page_missing: list[int] = []    # card_page 를 원했지만 페이지가 없어 대체 카드로 간 장면
    for i, sc in enumerate(scenes, 1):
        out_png = os.path.join(cards, f"{i:03d}.png")
        want = card_page_of(sc)
        if i in images:
            card_qa.append(label_image(images[i], sc, i, len(scenes), out_png))
        elif want is not None and want in card_pages:
            card_qa.append(compose_card_page(card_pages[want], sc, i, len(scenes), out_png))
            from_pages.append(i)
        else:
            if want is not None:
                page_missing.append(i)
            card_qa.append(draw_scene_card(sc, i, len(scenes), topic, out_png))
    generated = sorted(i for i in images if 1 <= i <= len(scenes))
    config.IMAGE_REUSE_DIR = cards
    directive = plan_to_directive(plan, topic)
    engine_render.take_placeholder_fallbacks()  # 앞 작업의 전역 기록을 비운다(엔진 규칙)
    out = os.path.join(work_dir, "final.mp4")
    engine_dir = os.path.join(work_dir, "engine")
    os.makedirs(engine_dir, exist_ok=True)   # 엔진은 작업 폴더를 만들지 않는다
    engine_render.render_directive_local(directive, out, work_dir=engine_dir, lang="ko", platform=config.DRINKS_CAPTION_PLATFORM)
    placeholders = engine_render.take_placeholder_fallbacks()
    if placeholders:
        raise RenderError("placeholder_cuts", f"빈 화면으로 대체된 장면이 있습니다: {placeholders}")
    cover = os.path.join(work_dir, "cover.jpg")
    cover_qa = draw_cover(topic, plan, cover)
    probe = _probe(out)
    vol = _mean_volume_db(out)
    warnings = []
    if (probe["width"], probe["height"]) != (config.RENDER_WIDTH, config.RENDER_HEIGHT):
        warnings.append("not_vertical_1080x1920")
    if probe["audio_streams"] == 0 or (vol is not None and vol < -60):
        warnings.append("narration_silent")   # TTS 실패는 엔진이 무음으로 넘긴다 — 여기서 드러낸다
    # 장면 하나만 무음이어도 잡는다(엔진은 실패한 장면만 조용히 무음으로 바꾼다 — 검토 지적).
    silent = []
    for i in range(len(scenes)):
        cut_audio = os.path.join(engine_dir, f"cut_{i}.m4a")
        if os.path.exists(cut_audio):
            v = _mean_volume_db(cut_audio)
            if v is None or v < -60:
                silent.append(i + 1)
        else:
            silent.append(i + 1)
    if silent and tts != "placeholder":
        warnings.append("narration_silent_scenes")
    if any(c["truncated"] for c in card_qa) or cover_qa["truncated"]:
        warnings.append("text_truncated")
    if MISSING:
        warnings.append("glyph_missing")
    cover_mime = "image/jpeg"
    moov_first = moov_before_mdat(out)
    warnings.extend(reel_spec_warnings(probe, os.path.getsize(out), moov_first, cover_mime, os.path.getsize(cover)))
    if page_missing:
        warnings.append("card_page_missing")
    rate = speech_rate([sc.get("narration") or "" for sc in scenes], probe["duration_sec"], config.RENDER_PLAYBACK_SPEED, config.EDGE_TTS_RATE)
    if rate["syl_per_sec"] > config.DRINKS_SPEECH_RATE_WARN_SYL_PER_SEC:
        warnings.append("speech_rate_fast")
    # 글자 카드(대체 이미지)로 나간 장면 — 정리 카드(text_card)는 원래 글자 카드라 뺀다. 원했던 카드 페이지가 없어 되돌아간 장면은 넣는다.
    stand_in = [i for i, sc in enumerate(scenes, 1) if i not in images and i not in from_pages
                and ((sc.get("visual_role") or "reality") != "text_card" or i in page_missing)]
    qa = {"probe": probe, "mean_volume_db": vol, "silent_scenes": silent, "missing_glyphs": sorted(set(MISSING)), "scenes": len(scenes), "scene_labels": [c["label"] for c in card_qa],
          "warnings": warnings, "stand_in_visuals": bool(stand_in), "stand_in_scenes": stand_in, "generated_scenes": generated,
          "card_page_scenes": from_pages,
          "visual_source": {"stand_in": stand_in, "card_pages": from_pages, "generated": generated},
          "speech_rate": rate,
          "tts": tts, "brand": BRAND["version"],
          "reel_spec": {"moov_first": moov_first, "audio_sample_rate": probe.get("audio_sample_rate"), "video_codec": probe.get("video_codec"),
                        "fps": probe.get("fps"), "cover_mime": cover_mime},
          "note": ("대체 이미지 렌더 — 흐름 검증용. 목표 화풍 품질 검증이 아니다" if not generated and not from_pages else
                   " · ".join(([f"생성 그림 장면 {','.join(map(str, generated))}"] if generated else []) +
                              ([f"카드뉴스 페이지 장면 {','.join(map(str, from_pages))}"] if from_pages else []) +
                              ([f"대체 카드 장면 {','.join(map(str, stand_in))}"] if stand_in else [])))}
    costs = [{"kind": "tts", "provider": tts, "model": config.EDGE_TTS_VOICE if tts == "edge" else None, "cost_usd": 0,
              "units": len(scenes), "note": "무료 TTS"},
             {"kind": "render", "provider": "local_ffmpeg", "cost_usd": 0,
              "note": "장면 카드(Pillow)·조립(ffmpeg)" + (" — 생성 그림은 미리 산 것을 재사용(비용은 그림 기록에)" if generated else "")}]
    files = [{"path": out, "role": "final_video", "position": 1, "mime": "video/mp4", "width": probe["width"],
              "height": probe["height"], "duration_ms": int(probe["duration_sec"] * 1000)},
             {"path": cover, "role": "cover", "position": 1, "mime": cover_mime, "width": 1080, "height": 1920}]
    return Rendered(files, qa, costs)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
