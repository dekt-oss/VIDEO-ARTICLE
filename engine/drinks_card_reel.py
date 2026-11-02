"""주류 카드뉴스 릴스 — 같은 페이지를 15~30초 세로 영상으로(로컬 ffmpeg·0원). 2026-11-02. docs/deviation-drinks-card-reels.md

승인된 카드 제작안에 reel 묶음(훅 제목·저장/보내기 한 줄)이 있을 때 engine/drinks_cards.py 가 부른다.

같은 글, 다른 판: 4:5 카드를 세로 화면에 그대로 붙이면 오른쪽 글자가 인스타 버튼에 가린다. 그래서 같은 페이지 글을 안전 영역에 맞춰 다시 그린다.
  · 첫 페이지 = 큰 훅 제목(위 20~25% 높이에서 시작). 마지막 페이지 = 저장/보내기 한 줄.
  · 페이지 전환 = 밀어 넘기기(ffmpeg xfade). 글자 위 확대는 떨림이 나서 쓰지 않는다.
  · 말 자막·나레이션 없음(기획 v2 §2-2). 소리는 무음 트랙뿐이다 — 음원은 게시 때 인스타가 붙인다(§7).
  · 글자 상자를 재서 안전 영역(§2-3 설계값)을 벗어나면 만들지 않는다. 길이가 15~30초 밖이어도 만들지 않는다.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

from . import config, subtitles
from .drinks_render import BRAND, MISSING, RenderError, _font, _probe, font_for, missing_glyphs, moov_before_mdat, reel_spec_warnings, wrap

W, H = config.RENDER_WIDTH, config.RENDER_HEIGHT
LEFT = 80
RIGHT_LIMIT = W - config.DRINKS_REEL_SAFE_RIGHT_PX
TEXT_W = RIGHT_LIMIT - LEFT
BOTTOM_LIMIT = H - config.DRINKS_REEL_SAFE_BOTTOM_PX
TOP_ROW_Y = 170       # 브랜드·쪽 번호 줄. 인스타 위쪽 글자(릴스·카메라)를 피한 값 — 앱 확인 전 가설이다
CONTENT_TOP = 300

ROLE_LABEL = {"explain": "", "compare": "비교", "checklist": "체크리스트", "source": "출처"}


def page_timings(pages: list[dict[str, Any]]) -> list[float]:
    """페이지마다 화면에 머무는 초. 글 길이에 비례시키되 한 장 2.5~4초, 합계 15~30초 안으로 맞춘다. 못 맞추면 멈춘다."""
    (lo, hi), (tlo, thi) = config.DRINKS_CARD_REEL_PAGE_SECONDS, config.DRINKS_CARD_REEL_SECONDS
    n = len(pages)
    if n * hi < tlo or n * lo > thi:
        raise RenderError("card_reel_duration", f"{n}장으로는 {tlo:g}~{thi:g}초를 만들 수 없습니다(한 장 {lo:g}~{hi:g}초)")
    raw = []
    for p in pages:
        chars = len(f"{p.get('heading') or ''}{p.get('body') or ''}".replace(" ", "").replace("\n", ""))
        raw.append(min(hi, max(lo, chars / config.DRINKS_CARD_REEL_READ_CHARS_PER_SEC)))
    total = sum(raw)
    if total < tlo:   # 모자라면 한 장 상한 안에서 똑같이 늘린다
        room = tlo - total
        while room > 1e-6:
            open_idx = [i for i, v in enumerate(raw) if v < hi - 1e-9]
            add = room / len(open_idx)
            for i in open_idx:
                d = min(add, hi - raw[i])
                raw[i] += d
                room -= d
    elif total > thi:  # 넘치면 한 장 하한 안에서 똑같이 줄인다
        over = total - thi
        while over > 1e-6:
            open_idx = [i for i, v in enumerate(raw) if v > lo + 1e-9]
            cut = over / len(open_idx)
            for i in open_idx:
                d = min(cut, raw[i] - lo)
                raw[i] -= d
                over -= d
    return [round(v, 3) for v in raw]


def meaning_lines(draw, text: str, font, width: int) -> list[str]:
    """줄바꿈(뜻 단위)은 쓴 사람의 것을 지키고, 한 줄이 넘치면 뜻이 닫히는 자리에서 끊는다.
    자막과 같은 끊는 자리 점수(subtitles._break_score)에 줄 길이 고르기를 더한 동적 계획이다. 낱말 하나가 한 줄보다 길 때만 글자로 자른다."""
    out: list[str] = []
    for para in (text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        if draw.textlength(para, font=font) <= width:
            out.append(para)
            continue
        toks = para.split()
        n = len(toks)
        best = [0.0] + [float("inf")] * n
        back = [0] * (n + 1)
        for j in range(1, n + 1):
            for i in range(j - 1, -1, -1):
                w = draw.textlength(" ".join(toks[i:j]), font=font)
                if w > width and j - i > 1:
                    break
                slack = max(0.0, 1.0 - w / width)
                cost = 6.0 * slack * slack - (subtitles._break_score(toks[j - 1], toks[j]) if j < n else 0.0)
                if best[i] + cost < best[j]:
                    best[j], back[j] = best[i] + cost, i
        lines, j = [], n
        while j > 0:
            lines.append(" ".join(toks[back[j]:j]))
            j = back[j]
        for ln in reversed(lines):
            out.extend(wrap(draw, ln, font, width) if draw.textlength(ln, font=font) > width else [ln])
    return out


@dataclass
class Block:
    text: str
    role: str
    size: int
    fill: tuple[int, int, int]
    max_lines: int
    gap_before: int = 0
    line_gap: float = 1.32
    bullet: bool = False
    lines: list[str] = field(default_factory=list)
    cut: bool = False


class Frame:
    def __init__(self) -> None:
        from PIL import Image, ImageDraw

        self.img = Image.new("RGB", (W, H), BRAND["bg"])
        self.d = ImageDraw.Draw(self.img)
        self.boxes: list[tuple[int, int, int, int]] = []
        self.d.rectangle([0, 0, W, 12], fill=BRAND["accent"])

    def text(self, xy: tuple[int, int], s: str, font, fill) -> None:
        MISSING.extend(missing_glyphs(font, s))
        self.d.text(xy, s, font=font, fill=fill)
        self.boxes.append(tuple(self.d.textbbox(xy, s, font=font)))

    def layout(self, blocks: list[Block]) -> int:
        """줄을 나누고 전체 높이를 잰다(그리기 전)."""
        total = 0
        for b in blocks:
            font = font_for(b.text, b.role, b.size)
            lines = meaning_lines(self.d, b.text, font, TEXT_W - (54 if b.bullet else 0))
            b.cut = len(lines) > b.max_lines
            b.lines = lines[: b.max_lines]
            if b.cut and b.lines:
                b.lines[-1] = b.lines[-1][:-1] + "…"
            total += b.gap_before + int(b.size * b.line_gap) * len(b.lines)
        return total

    def draw_blocks(self, blocks: list[Block], y: int) -> int:
        for b in blocks:
            y += b.gap_before
            font = font_for(b.text, b.role, b.size)
            for ln in b.lines:
                x = LEFT
                if b.bullet:   # 체크 상자는 글자가 아니라 도형(글꼴에 없으면 두부가 된다 — drinks_cards 와 같다)
                    self.d.rounded_rectangle([LEFT, y + 10, LEFT + 36, y + 46], radius=6, outline=BRAND["accent"], width=4)
                    x = LEFT + 54
                self.text((x, y), ln, font, b.fill)
                y += int(b.size * b.line_gap)
        return y

    def safe_area_violations(self) -> list[list[int]]:
        return [list(b) for b in self.boxes if b[2] > RIGHT_LIMIT or b[3] > BOTTOM_LIMIT or b[0] < 0 or b[1] < 0]


def _top_row(fr: Frame, pos: int, total: int) -> None:
    f = _font("small", 34)
    fr.text((LEFT, TOP_ROW_Y), BRAND["name"], f, BRAND["accent"])
    s = f"{pos} / {total}"
    fr.text((int(RIGHT_LIMIT - fr.d.textlength(s, font=f)), TOP_ROW_Y), s, f, BRAND["muted"])


def _source_lines(sources: list[dict[str, Any]]) -> str:
    """출처 목록. 주소는 뺀다 — 세로 화면에서 읽히지 않고, 주소는 카드뉴스 출처 페이지에 있다."""
    seen: list[str] = []
    for s in sources or []:
        line = f"{s.get('publisher') or ''} {s.get('title') or ''}".strip()
        if line and line not in seen:
            seen.append(line)
    return "\n".join(seen)


def draw_frame(page: dict[str, Any], pos: int, total: int, reel: dict[str, Any], sources: list[dict[str, Any]], out_path: str) -> dict[str, Any]:
    fr = Frame()
    _top_row(fr, pos, total)
    role = str(page.get("role") or "explain")
    heading = str(page.get("heading") or "").strip()
    body = str(page.get("body") or "").strip()
    is_first, is_last = pos == 1, pos == total
    cut = False
    if is_first:
        # 첫 페이지 큰 훅: 위 20~25% 높이에서 시작한다(§2-3). 제작안의 표지 제목이 훅과 다르면 아래에 작게 잇는다.
        hook = str(reel.get("hook_title") or heading).strip()
        blocks = [Block(hook, "head", 128, BRAND["text"], 5, line_gap=1.22)]
        if heading and heading != hook:
            blocks.append(Block(heading, "body", 54, BRAND["muted"], 3, gap_before=44))
        if body:
            blocks.append(Block(body, "body", 50, BRAND["muted"], 5, gap_before=44))
        fr.layout(blocks)
        y = int(H * config.DRINKS_CARD_REEL_HOOK_TOP_RATIO)
        fr.d.rectangle([LEFT, y - 34, LEFT + 120, y - 24], fill=BRAND["accent"])
        fr.draw_blocks(blocks, y)
        cut = any(b.cut for b in blocks)
    else:
        share_h = 0
        share = str(reel.get("share_line") or "").strip() if is_last else ""
        share_block = Block(share, "head", 50, BRAND["bg"], 3, line_gap=1.3) if share else None
        if share_block:
            share_h = fr.layout([share_block]) + 72
        blocks = []
        label = ROLE_LABEL.get(role, "") if role != "source" else ""   # 출처는 제목이 곧 표기다
        if role == "source":
            blocks.append(Block(heading or "출처", "head", 64, BRAND["text"], 2))
            if body:
                blocks.append(Block(body, "body", 40, BRAND["muted"], 4, gap_before=30))
            src = _source_lines(sources)
            if src:
                blocks.append(Block(src, "small", 36, BRAND["muted"], 12 if not share else 9, gap_before=30, line_gap=1.34))
        else:
            blocks.append(Block(heading, "head", 80, BRAND["text"], 3, line_gap=1.26))
            if role == "checklist":
                for i, ln in enumerate(x.lstrip("-•☐ ").strip() for x in body.split("\n") if x.strip()):
                    blocks.append(Block(ln, "body", 52, BRAND["text"], 2, gap_before=44 if i == 0 else 16, bullet=True))
            elif body:
                blocks.append(Block(body, "body", 56, BRAND["text"], 9, gap_before=48, line_gap=1.4))
        height = fr.layout(blocks)
        floor = BOTTOM_LIMIT - share_h - (40 if share_h else 0)
        y = max(CONTENT_TOP, CONTENT_TOP + (floor - CONTENT_TOP - height) // 2)
        if label:
            fl = _font("small", 34)
            lw = int(fr.d.textlength(label, font=fl))
            fr.d.rounded_rectangle([LEFT, y - 84, LEFT + lw + 44, y - 28], radius=28, outline=BRAND["accent"], width=3)
            fr.text((LEFT + 22, y - 76), label, fl, BRAND["accent"])
        fr.draw_blocks(blocks, y)
        cut = any(b.cut for b in blocks)
        if share_block:
            top = BOTTOM_LIMIT - share_h
            fr.d.rounded_rectangle([LEFT - 24, top, RIGHT_LIMIT, BOTTOM_LIMIT], radius=26, fill=BRAND["accent"])
            fr.draw_blocks([share_block], top + 36)
            cut = cut or share_block.cut
    fr.img.save(out_path, "PNG")
    return {"position": pos, "truncated": cut, "safe_area_violations": fr.safe_area_violations()}


def assemble(frames: list[str], timings: list[float], out_path: str) -> None:
    """정지 그림을 밀어 넘기며 잇는다. 합계 길이 = 페이지 시간의 합(겹치는 만큼 입력을 늘려 둔다). 소리는 무음 AAC — 음원은 게시 때 붙는다."""
    t = config.DRINKS_CARD_REEL_TRANSITION_SEC
    fps = config.DRINKS_CARD_REEL_FPS
    args: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    n = len(frames)
    for i, (f, d) in enumerate(zip(frames, timings)):
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{d + (t if i < n - 1 else 0):.3f}", "-i", f]
    args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    parts = [f"[{i}:v]format=yuv420p,setsar=1,fps={fps}[v{i}]" for i in range(n)]
    prev, offset = "v0", 0.0
    for i in range(1, n):
        offset += timings[i - 1]
        parts.append(f"[{prev}][v{i}]xfade=transition={config.DRINKS_CARD_REEL_TRANSITION}:duration={t}:offset={offset:.3f}[x{i}]")
        prev = f"x{i}"
    total = sum(timings)
    args += ["-filter_complex", ";".join(parts), "-map", f"[{prev}]", "-map", f"{n}:a", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-movflags", "+faststart", out_path]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise RenderError("ffmpeg_missing", "ffmpeg 이 없어 릴스를 만들지 못했습니다") from exc
    if p.returncode != 0 or not os.path.exists(out_path):
        raise RenderError("card_reel_ffmpeg", f"릴스 조립 실패: {(p.stderr or '')[-400:]}")


def render_card_reel(job: dict[str, Any], work_dir: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(파일 목록[최종 영상·표지], qa). 제작안에 reel 이 있을 때만 부른다. 카드뉴스 페이지는 render_carousel 이 따로 만든다."""
    from PIL import Image

    plan = job.get("plan") or {}
    reel = plan.get("reel") or {}
    pages = sorted(plan.get("pages") or [], key=lambda p: int(p["position"]))
    lim = config.DRINKS_CARD_REEL_LIMITS
    if not lim["min_pages"] <= len(pages) <= lim["max_pages"]:
        raise RenderError("invalid_plan", f"릴스로 만드는 카드는 {lim['min_pages']}~{lim['max_pages']}장입니다(지금 {len(pages)}장)")
    if not str(reel.get("hook_title") or "").strip() or not str(reel.get("share_line") or "").strip():
        raise RenderError("invalid_plan", "릴스 묶음에 훅 제목·저장/보내기 한 줄이 없습니다")
    os.makedirs(work_dir, exist_ok=True)
    timings = page_timings(pages)
    frames: list[str] = []
    frame_qa: list[dict[str, Any]] = []
    for i, pg in enumerate(pages, 1):
        path = os.path.join(work_dir, f"frame_{i:02d}.png")
        frame_qa.append(draw_frame(pg, i, len(pages), reel, job.get("sources") or [], path))
        frames.append(path)
    outside = {q["position"]: q["safe_area_violations"] for q in frame_qa if q["safe_area_violations"]}
    if outside:
        raise RenderError("reel_safe_area", f"글자가 안전 영역(아래 {config.DRINKS_REEL_SAFE_BOTTOM_PX}px·오른쪽 {config.DRINKS_REEL_SAFE_RIGHT_PX}px)을 벗어났습니다: {sorted(outside)}쪽")
    out = os.path.join(work_dir, "reel.mp4")
    assemble(frames, timings, out)
    cover = os.path.join(work_dir, "reel_cover.jpg")
    with Image.open(frames[0]) as im:
        im.convert("RGB").save(cover, "JPEG", quality=config.DRINKS_COVER_JPEG_QUALITY)
    probe = _probe(out)
    tlo, thi = config.DRINKS_CARD_REEL_SECONDS
    if not tlo - 0.2 <= probe["duration_sec"] <= thi + 0.2:   # 인코더 반올림 여유만 둔다
        raise RenderError("card_reel_duration", f"만든 영상이 {probe['duration_sec']:.2f}초입니다({tlo:g}~{thi:g}초여야 합니다)")
    moov_first = moov_before_mdat(out)
    warnings = reel_spec_warnings(probe, os.path.getsize(out), moov_first, "image/jpeg", os.path.getsize(cover))
    if (probe["width"], probe["height"]) != (W, H):
        warnings.append("not_vertical_1080x1920")
    if any(q["truncated"] for q in frame_qa):
        warnings.append("text_truncated")
    qa = {"probe": probe, "warnings": warnings,
          "reel_spec": {"moov_first": moov_first, "audio_sample_rate": probe.get("audio_sample_rate"), "video_codec": probe.get("video_codec"),
                        "fps": probe.get("fps"), "cover_mime": "image/jpeg"},
          "card_reel": {"timings_sec": timings, "transition": config.DRINKS_CARD_REEL_TRANSITION, "transition_sec": config.DRINKS_CARD_REEL_TRANSITION_SEC,
                        "hook_title": reel.get("hook_title"), "share_line": reel.get("share_line"), "narration": False, "audio_track": "silent",
                        "truncated_frames": [q["position"] for q in frame_qa if q["truncated"]],
                        "page_claims": {str(i): list(p.get("claim_ids") or []) for i, p in enumerate(pages, 1)},
                        "safe_area": {"bottom_px": config.DRINKS_REEL_SAFE_BOTTOM_PX, "right_px": config.DRINKS_REEL_SAFE_RIGHT_PX, "app_checked": False}}}
    files = [{"path": out, "role": "final_video", "position": 1, "mime": "video/mp4", "width": probe["width"], "height": probe["height"],
              "duration_ms": int(probe["duration_sec"] * 1000)},
             {"path": cover, "role": "cover", "position": 1, "mime": "image/jpeg", "width": W, "height": H}]
    return files, qa
