"""주류 설명형 — 사진클레이 버전(2026-11-10). docs/deviation-drinks-explainer-clay.md

운영자 지시: "이건 일단 우리 엔진에는 새로운 버전으로 추가해서 넣자. 설명형 릴스-사진클레이 이런식으로".
같은 날 샘플(준마이·긴조·다이긴조, 49초)에서 운영자가 하나씩 고른 것을 그대로 옮겼다:
  · 장면마다 점토(클레이) 그림 1장 — 클립을 사지 않는다. 그림 안 글자는 전부 막는다(모델이 엉터리 한자를 그린다).
  · 째리(로고 병뚜껑)가 첫·끝 장면 그림 속에 나오고, 나머지 장면은 그림 모서리 스티커로 나온다.
  · 화면 = 크림 바탕 + 맨 위 제목 + 둥근 그림 카드 + 아래 자막(나레이션 전문) + 로고.
  · 목소리 = Edge Hyunsu 1.45배, **장면 통째로** 읽힌다. 자막 줄마다 따로 읽히면 반쪽 문장 억양이 떨어져 AI 같다(운영자 지적).
    자막은 단어 시각(WordBoundary)에 맞춰 넘긴다.

이 모듈은 **돈을 쓰지 않는다**: 그림 주문 항목을 만들 뿐이고, 사는 것은 drinks_explainer_queue 가 결재 원장(drinks_paid.buy)으로 한다.
"""

from __future__ import annotations

import asyncio
import functools
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import config
from . import drinks_paid as dpaid

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
W, H = 1080, 1920
BG = (255, 247, 236)        # 째리 크림
INK = (28, 28, 30)
ORANGE = (194, 65, 12)      # 째리 주황
NAVY = (30, 42, 70)
MASCOT_REF_ID = "jjeri-v1"  # 1번 그림 주문 해시에 넣는 참조 이름(째리 그림을 바꾸면 올린다 — 옛 그림을 재사용하지 않게)
TtsFn = Callable[[str, str], None]


# ─────────────────────────────────────────────────────────────
# 대본 → 자막 줄 (순수)
# ─────────────────────────────────────────────────────────────

SHORT_PIECE = 8   # 이보다 짧은 조각("다음, 알코올.")만 이웃 조각과 한 줄로 합친다


def _halve(s: str, max_chars: int) -> list[str]:
    """긴 덩어리는 가운데에 가장 가까운 띄어쓰기에서 둘로(앞만 꽉 채우고 뒤에 한 단어 남기지 않게)."""
    if len(s) <= max_chars or " " not in s:
        return [s]
    mid = len(s) // 2
    cut = min((i for i, ch in enumerate(s) if ch == " "), key=lambda i: abs(i - mid))
    return _halve(s[:cut], max_chars) + _halve(s[cut + 1:], max_chars)


def split_lines(text: str, max_chars: int = config.DRINKS_CLAY_LINE_MAX_CHARS) -> list[str]:
    """나레이션 → 화면 자막 줄(뜻 단위, 메모리 규칙). 문장 → 쉼표 덩어리 → 가운데 띄어쓰기 순으로 끊는다.
    쉼표 덩어리끼리는 합치지 않는다 — 아주 짧은 조각만 이웃과 합친다."""
    pieces: list[str] = []
    for sent in re.split(r"(?<=[.?!])\s+", (text or "").strip()):
        if not sent:
            continue
        if len(sent) <= max_chars:
            pieces.append(sent)
        else:
            pieces.extend(h for p in re.split(r"(?<=,)\s+", sent) if p for h in _halve(p, max_chars))
    out: list[str] = []
    for p in pieces:   # "땡." 같은 짧은 조각은 이웃과 한 줄로
        if out and (len(p) < SHORT_PIECE or len(out[-1]) < SHORT_PIECE) and len(out[-1]) + 1 + len(p) <= max_chars:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def mascot_in_scene(n: int, total: int) -> bool:
    return config.DRINKS_CLAY_MASCOT_SCENES == "first_last" and n in (1, total)


def norm(t: str) -> str:
    return "".join(ch for ch in t if ch.isalnum())


def line_starts(lines: list[str], words: list[tuple[str, float, float]], total_sec: float) -> list[float]:
    """자막 줄마다 시작 시각(장면 오디오 기준). 단어 시각이 있으면 그 줄 첫 글자를 말하는 단어에, 없으면 글자 수 비례로."""
    if not words:
        lens = [max(1, len(norm(x))) for x in lines]
        tot, acc, out = sum(lens), 0, []
        for n in lens:
            out.append(total_sec * acc / tot); acc += n
        return out
    starts, acc, i, done = [], 0, 0, 0
    for line in lines:
        while i < len(words) and done < acc:
            done += len(norm(words[i][0])); i += 1
        starts.append(words[min(i, len(words) - 1)][1])
        acc += len(norm(line))
    return starts


# ─────────────────────────────────────────────────────────────
# 그림 주문 항목 (순수) — 사는 것은 drinks_paid.buy
# ─────────────────────────────────────────────────────────────

def image_prompt(visual_prompt: str, n: int, total: int) -> str:
    """째리가 나오는 장면만 째리를 참조로 준다. 2026-11-10 버번 실측: 모든 장면에 '1번 + 째리' 를 주자 중간 장면에도
    째리가 그려져 모서리 스티커와 두 번 나왔다 → 째리 없는 장면은 1번 그림만 주고 그리지 말라고 쓴다."""
    mascot = mascot_in_scene(n, total)
    if n == 1:
        ref = "The reference image shows our mascot. "
    elif mascot:
        ref = ("Reference image: the left half shows the main character and the art style, the right half shows our mascot. "
               "Keep the same character look and clay style, and draw a new scene: ")
    else:
        ref = ("The reference image shows the main character and the art style. Keep the same character look and clay style, "
               "and draw a new scene. Do not draw any bottle-cap mascot in this scene: ")
    tail = f" Somewhere in the scene, {config.DRINKS_CLAY_MASCOT_TEXT} sits small and glares." if mascot else ""
    return f"{ref}{visual_prompt.strip()}{tail} {config.DRINKS_CLAY_STYLE}"


def image_item(n: int, total: int, visual_prompt: str, ref_id: str, prompt: Optional[str] = None) -> dpaid.OrderItem:
    """그림 1장. ref_id = 참조 그림 이름(1번은 째리 그림, 나머지는 1번 그림 sha256) — 해시에 들어가 1번이 바뀌면 다른 그림이다.
    prompt 를 주면 그 문장을 쓴다(지시서에 저장된 문장이 정본 — 코드 문장이 바뀌어도 이미 산 그림을 찾는다)."""
    vp = (visual_prompt or "").strip()
    if not vp:
        raise dpaid.PaidError("visual_prompt_missing", f"{n}번 장면에 영어 그림 지시문(visual_prompt)이 없습니다")
    prompt = prompt or image_prompt(vp, n, total)
    model = config.DRINKS_CLAY_IMAGE_MODEL
    price = float(config.PRICING.get(model, {}).get("image_standard", 0)) or config.DRINKS_CLAY_IMAGE_USD
    return dpaid.OrderItem(item_key=f"clay-{n:02d}", position=n, role="reality", kind="image", model=model, est_usd=price, prompt=prompt,
                           prompt_hash=dpaid._image_hash(model, prompt, ref_id, config.DRINKS_CLAY_ASPECT),
                           ref_item="jjeri" if n == 1 else "clay-01", aspect=config.DRINKS_CLAY_ASPECT,
                           cut={"cut_no": n, "visual_role": "REALITY", "raw_prompt": prompt})


class ClayAdapter:
    """실제 그림 공급자. 설명형 클립과 같은 스위치(DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED)와 열린 결재가 있어야 움직인다."""

    live = True

    def check_ready(self, approval: Optional[dict[str, Any]]) -> None:
        if not config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED:
            raise dpaid.PaidError("provider_send_disabled", "실호출 스위치(DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED)가 꺼져 있습니다 — 아무것도 사지 않았습니다")
        a = approval or {}
        if a.get("status") != "open" or a.get("expired") is not False:
            raise dpaid.PaidError("approval_closed", "열린 결재가 아닙니다 — 아무것도 사지 않았습니다")
        if not config.SECRETS.gemini_api_key:
            raise dpaid.PaidError("api_key_missing", "GEMINI_API_KEY 가 없습니다 — 아무것도 사지 않았습니다")

    def image(self, item: dpaid.OrderItem, out: str, ref_path: Optional[str]) -> float:
        if not config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED:
            raise dpaid.PaidError("provider_send_disabled", "실호출 스위치가 꺼져 있습니다")
        return dpaid._generate(item, out, ref_path)


# ─────────────────────────────────────────────────────────────
# 째리·참조 그림·화면 (Pillow, 0원)
# ─────────────────────────────────────────────────────────────

# 운영자가 보내 준 원본(1024px, 2026-11-10)의 좌표: (윗선 왼쪽, 윗선 오른쪽, 원 중심, 반지름, 눈동자 중심, 반지름, 하이라이트 중심, 반지름)
_EYES = [((257, 452), (478, 482), (367, 480), 112, (418, 523), 45, (440, 510), 12),
         ((531, 490), (762, 506), (646, 512), 116, (700, 562), 45, (721, 538), 12)]


@functools.lru_cache(maxsize=16)   # 프레임마다 다시 그리지 않는다(붙여 넣기만 하고 고치지 않는다)
def jjeri(size: int = 300, tile: bool = True, outline: bool = False):
    """째리 — 물결 가장자리 크림 병뚜껑 + 윗선이 기운 주황 반원 눈 둘(오른쪽이 낮다) + 남색 눈동자."""
    from PIL import Image, ImageChops, ImageDraw

    S, k = 2048, 2.0
    im = Image.new("RGBA", (S, S), ORANGE + (255,) if tile else (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def cap(r0: float, amp: float) -> list[tuple[float, float]]:
        pts = []
        for i in range(720):
            t = i * 2 * math.pi / 720
            r = r0 + amp * math.cos(24 * t)
            pts.append((1024 + r * math.cos(t - math.pi / 2), 1024 + r * math.sin(t - math.pi / 2)))
        return pts

    if outline:
        d.polygon(cap(830, 50), fill=ORANGE)
    d.polygon(cap(790, 50), fill=BG)
    for (l, r, c, rad, pc, pr, hc, hr) in _EYES:
        disk = Image.new("L", (S, S), 0)
        ImageDraw.Draw(disk).ellipse([(c[0] - rad) * k, (c[1] - rad) * k, (c[0] + rad) * k, (c[1] + rad) * k], fill=255)
        m = (r[1] - l[1]) / (r[0] - l[0])   # 기운 윗선 아래만 남긴다 = 반쯤 감은 눈
        below = Image.new("L", (S, S), 0)
        ImageDraw.Draw(below).polygon([(0, (l[1] - m * l[0]) * k), (S, (l[1] + m * (1024 - l[0])) * k), (S, S), (0, S)], fill=255)
        im.paste(ORANGE, mask=ImageChops.multiply(disk, below))
        d.ellipse([(pc[0] - pr) * k, (pc[1] - pr) * k, (pc[0] + pr) * k, (pc[1] + pr) * k], fill=NAVY)
        d.ellipse([(hc[0] - hr) * k, (hc[1] - hr) * k, (hc[0] + hr) * k, (hc[1] + hr) * k], fill=(255, 255, 255))
    return im.resize((size, size), Image.LANCZOS)


def mascot_ref(out: str) -> str:
    jjeri(1024).convert("RGB").save(out)
    return out


def reference_sheet(scene1_path: str, out: str) -> str:
    """공급자는 참조 그림을 한 장만 받는다 → 왼쪽 1번 그림(주인공·화풍) + 오른쪽 째리를 한 장으로."""
    from PIL import Image

    sheet = Image.new("RGB", (2048, 1024), BG)
    sheet.paste(Image.open(scene1_path).convert("RGB").resize((1024, 1024)), (0, 0))
    sheet.paste(jjeri(1024).convert("RGB"), (1024, 0))
    sheet.save(out)
    return out


def _font(name: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def _wrap(d: Any, text: str, f: Any, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split(" "):
        test = (cur + " " + word).strip()
        if d.textlength(test, font=f) <= width or not cur:
            cur = test
        else:
            lines.append(cur); cur = word
    return lines + [cur]


def _fit(picture: Any) -> Any:
    """그림 둘레 빈 여백을 잘라 1000×960 안에 크게 앉힌다(모델이 아이콘처럼 작게 그리는 경우, 샘플 실측)."""
    from PIL import Image, ImageChops

    w, h = picture.size
    corners = [picture.getpixel(p) for p in [(5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)]]
    bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))
    diff = ImageChops.difference(picture, Image.new("RGB", picture.size, bg)).convert("L").point(lambda v: 255 if v > 28 else 0)
    box = diff.getbbox() or (0, 0, w, h)
    box = (max(box[0] - 24, 0), max(box[1] - 24, 0), min(box[2] + 24, w), min(box[3] + 24, h))
    pic = picture.crop(box)
    s = min(1000 / pic.width, 960 / pic.height)
    return pic.resize((round(pic.width * s), round(pic.height * s)))


def title_layout(title: str) -> tuple[int, list[str]]:
    """제목: 한 줄에 들어가는 가장 큰 크기(64→44), 안 되면 52 로 두 줄."""
    from PIL import Image, ImageDraw

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for size in range(64, 43, -4):
        if d.textlength(title, font=_font("Pretendard-Black.otf", size)) <= 980:
            return size, [title]
    return 52, _wrap(d, title, _font("Pretendard-Black.otf", 52), 980)[:2]


def draw_frame(title: str, picture: Any, line: str, out: str, *, corner: bool) -> None:
    from PIL import Image, ImageDraw

    pic = _fit(picture)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    size, tl = title_layout(title)
    y = 190 - (len(tl) - 1) * 34
    for t in tl:
        d.text((W / 2, y), t, font=_font("Pretendard-Black.otf", size), fill=INK, anchor="mm"); y += size + 8
    d.rounded_rectangle((W / 2 - 60, 238, W / 2 + 60, 246), radius=4, fill=ORANGE)
    x, y0 = (W - pic.width) // 2, 300 + (960 - pic.height) // 2
    mask = Image.new("L", pic.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), radius=36, fill=255)
    im.paste(pic, (x, y0), mask)
    if corner:   # 그림 속에 째리가 없는 장면은 모서리에서 그림을 째려본다
        cap = jjeri(170, tile=False, outline=True).rotate(12, resample=Image.BICUBIC, expand=True)
        im.paste(cap, (x + pic.width - cap.width + 40, y0 + pic.height - cap.height + 60), cap)
    sf = _font("Pretendard-Bold.otf", 50)
    y = 1360
    for ln in _wrap(d, line, sf, 900):
        d.text((W / 2, y), ln, font=sf, fill=INK, anchor="mt"); y += 70
    bf = _font("Pretendard-Bold.otf", 30)
    tile = jjeri(44)
    im.paste(tile, (W - 50 - 44 - 8 - int(d.textlength("술째리고", font=bf)), H - 92), tile)
    d.text((W - 50, H - 70), "술째리고", font=bf, fill=INK, anchor="rm")
    d.text((50, H - 70), config.DRINKS_CARD_AI_NOTICE, font=_font("Pretendard-Medium.otf", 26), fill=(120, 110, 100), anchor="lm")
    im.save(out)


# ─────────────────────────────────────────────────────────────
# 목소리 (무료 Edge)
# ─────────────────────────────────────────────────────────────

def speak(text: str, path: str, tts_fn: Optional[TtsFn] = None) -> list[tuple[str, float, float]]:
    """장면 하나를 통째로 읽힌다. 반환: 단어별 (글자, 시작초, 끝초). 시험용 tts_fn 은 단어 시각이 없다(빈 목록)."""
    if tts_fn is not None:
        tts_fn(text, path)
        return []
    import edge_tts

    async def run() -> tuple[bytes, list[tuple[str, float, float]]]:
        audio, words = b"", []
        comm = edge_tts.Communicate(text, config.DRINKS_CLAY_TTS_VOICE, rate=config.DRINKS_CLAY_TTS_RATE, boundary="WordBoundary")
        async for ch in comm.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] == "WordBoundary":
                st = ch["offset"] / 1e7
                words.append((ch["text"], st, st + ch["duration"] / 1e7))
        return audio, words

    last: Exception | None = None
    for _ in range(3):   # 무료 서버가 가끔 빈 응답을 준다(샘플 실측)
        try:
            audio, words = asyncio.run(asyncio.wait_for(run(), timeout=config.TTS_TIMEOUT_SEC))
            if audio and words:
                with open(path, "wb") as f:
                    f.write(audio)
                return words
            last = RuntimeError("빈 응답")
        except Exception as exc:  # noqa: BLE001 — 세 번까지 다시 묻고, 그래도 안 되면 위로 올린다
            last = exc
    raise RuntimeError(f"목소리 합성 실패: {type(last).__name__}")


def media_sec(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return float(out.strip() or 0)


def spoken_window(path: str, words: list[tuple[str, float, float]]) -> tuple[float, float]:
    """쓸 구간. Edge 는 앞뒤에 0.5~0.8초 빈 소리를 붙인다 — 첫 단어 직전부터 마지막 단어 직후까지만 쓴다."""
    if words:
        return max(words[0][1] - 0.05, 0.0), words[-1][2] + 0.12
    return 0.0, media_sec(path)


# ─────────────────────────────────────────────────────────────
# 조립 + 자동 검사 (0원)
# ─────────────────────────────────────────────────────────────

@dataclass
class ClayScene:
    n: int
    narration: str
    lines: list[str]
    picture: str             # 그림 파일 경로
    mascot: bool             # 그림 속에 째리가 있나(있으면 모서리 째리를 빼서 두 번 안 나온다)


def render(title: str, scenes: list[ClayScene], out_path: str, work: str, tts_fn: Optional[TtsFn] = None) -> dict[str, Any]:
    from PIL import Image

    os.makedirs(work, exist_ok=True)
    frames: list[tuple[str, float]] = []
    audios: list[str] = []
    per: dict[int, float] = {}
    k = 0
    for sc in scenes:
        raw = os.path.join(work, f"s{sc.n:02d}" + (".wav" if tts_fn else ".mp3"))
        words = speak(sc.narration, raw, tts_fn)
        a0, a1 = spoken_window(raw, words)
        wav = os.path.join(work, f"s{sc.n:02d}.cut.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af", f"atrim={a0:.3f}:{a1:.3f},asetpts=PTS-STARTPTS,apad=pad_dur={config.DRINKS_CLAY_SCENE_GAP_SEC}",
                        "-ar", "44100", "-ac", "1", wav], check=True)
        total = a1 - a0 + config.DRINKS_CLAY_SCENE_GAP_SEC
        st = [max(t - a0, 0.0) for t in line_starts(sc.lines, words, a1 - a0)]
        st[0] = 0.0
        pic = Image.open(sc.picture).convert("RGB")
        for j, line in enumerate(sc.lines):
            k += 1
            png = os.path.join(work, f"l{k:03d}.png")
            draw_frame(title, pic, line, png, corner=not sc.mascot)
            end = st[j + 1] if j + 1 < len(st) else total
            frames.append((png, max(end - st[j], 0.05)))
        audios.append(wav)
        per[sc.n] = round(total, 2)
    vlist, alist = os.path.join(work, "v.txt"), os.path.join(work, "a.txt")
    with open(vlist, "w", encoding="utf-8") as f:
        f.write("".join(f"file '{os.path.basename(p)}'\nduration {d:.3f}\n" for p, d in frames) + f"file '{os.path.basename(frames[-1][0])}'\n")
    with open(alist, "w", encoding="utf-8") as f:
        f.write("".join(f"file '{os.path.basename(a)}'\n" for a in audios))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "v.txt", "-f", "concat", "-safe", "0", "-i", "a.txt",
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-ar", "44100", "-movflags", "+faststart", "-shortest", os.path.abspath(out_path)], check=True, cwd=work)
    return {"per_scene_sec": per, "total_sec": round(sum(per.values()), 2), "caption_lines": len(frames),
            "shortest_line_sec": round(min(d for _, d in frames), 2)}


def probe(path: str) -> dict[str, Any]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", path],
                         capture_output=True, text=True).stdout
    data = json.loads(out or "{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"video_codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height"), "audio_codec": a.get("codec_name"),
            "duration_sec": float((data.get("format") or {}).get("duration") or 0)}


def auto_qa(path: str, render_summary: dict[str, Any]) -> dict[str, Any]:
    """돌아가는지만 본다(품질은 사람 검수). 정지 화면 검사는 하지 않는다 — 이 버전은 원래 정지 그림이다."""
    from .drinks_explainer import moov_before_mdat

    p = probe(path)
    lo, hi = config.DRINKS_CLAY_FINAL_SEC
    blocks: list[str] = []
    if p["video_codec"] != "h264" or (p["width"], p["height"]) != (W, H):
        blocks.append("reel_spec")
    if p["audio_codec"] != "aac":
        blocks.append("no_audio")
    if not lo <= p["duration_sec"] <= hi:
        blocks.append("duration_out_of_range")
    if not moov_before_mdat(path):
        blocks.append("moov_not_first")
    warns = ["short_caption_line"] if render_summary.get("shortest_line_sec", 9) < 0.8 else []
    return {"ok": not blocks, "blocks": blocks, "warns": warns, "probe": p}


def directive_slots(plan_id: str, scenes: list[dict[str, Any]], scene_sec: dict[int, float]) -> tuple[list[dict[str, Any]], float]:
    """장면별 지시서 줄 + 그림값 합계. 화면 표(Directive 타입)와 같은 칸을 채운다 — 클립 칸은 0/빈 값."""
    from .drinks_explainer import slot_id

    total = len(scenes)
    slots, usd = [], 0.0
    for i, sc in enumerate(scenes, 1):
        item = image_item(i, total, str(sc.get("visual_prompt") or ""), MASCOT_REF_ID)
        usd += item.est_usd
        slots.append({"n": i, "scene": i, "slot_id": slot_id(plan_id, i), "role": "reality", "narration": sc.get("narration"),
                      "lines": split_lines(str(sc.get("narration") or "")), "tts_ms": int(round(scene_sec[i] * 1000)), "last_src_ms": 0, "min_src_ms": 0,
                      "clip_sec": 0, "candidates_planned": 0, "boundary_in": "cut", "boundary_out": "cut", "continuity_ref": None,
                      "visual_prompt": sc.get("visual_prompt"), "image_prompt": item.prompt, "image_model": item.model, "image_item_key": item.item_key,
                      "image_est_usd": item.est_usd, "motion_prompt": "", "clip_prompt": "", "clip_model": "", "clip_est_usd": 0,
                      "mascot_in_scene": mascot_in_scene(i, total), "claim_ids": list(sc.get("claim_ids") or []), "visual_claim_ko": sc.get("visual_claim_ko"),
                      "allowed_simplification": sc.get("allowed_simplification"), "forbidden_misreading": sc.get("forbidden_misreading"),
                      "depiction_label": sc.get("depiction_label"), "overlays": None})
    return slots, round(usd, 4)
