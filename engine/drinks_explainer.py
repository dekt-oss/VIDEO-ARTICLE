"""주류 설명형 릴스 — 산 영상 클립만 잘라 잇는 렌더(무료 부분). 2026-11-02. docs/deviation-drinks-explainer-stage1.md

기획 v2(docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md) §3 의 무료 부분이다. 운영자 원칙: "사진에 설명 하는건 안돼."

  E1 모든 화면은 산 영상 클립의 한 구간이다 — 편집 컷은 asset_id + 원본 구간(ms)을 가진다.
  E2 길이 보정 금지 — 원본 구간을 잘라 쓰는 것뿐이다. 정지·왕복·느리게 재생으로 메우는 길이 이 파일에 없다. 모자라면 clip_short 로 멈춘다.
  E3 렌더는 사지 않는다 — 공급자를 무료로 고정하고, 이 모듈은 공급자 코드를 import 하지 않는다. 없으면 clip_missing, 깨졌으면 clip_corrupt.
  E4 사진 대체 0회 — 위 셋 중 하나면 편 전체가 blocked_assets. 출력 파일을 남기지 않는다.
  E5 길이는 잰다 — probe_clip 이 ffprobe 로 실제 길이·해상도·프레임을 잰다(요청 길이를 믿지 않는다).
  E6 디지털 확대는 움직이는 영상 위에서만, 최대 config.DRINKS_EXPLAINER_ZOOM_MAX.

★ 시간 계산(§3-6): 편집표의 시간은 전부 **배속 전 정수 ms** 다. 최종 시간 = 배속 전 ÷ 재생 속도. 배속이 클립에도 걸리므로
  클립 원본에서 필요한 길이 = 배속 전 시간이다(위험 2 — config.DRINKS_EXPLAINER_PLAYBACK_SPEED 주석).
★ 이 모듈은 대본·근거를 만들지 않는다. 품질 합격도 아니다 — 자동 검사 통과는 "돌아간다"일 뿐이고 사람 판정(§3-8 B)이 따로 있다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from . import assemble, config, subtitles
from .drinks_render import FONT_DIR, moov_before_mdat, reel_spec_warnings, sha256_file, wrap
from .render_qa import parse_freeze_spans

# ─────────────────────────────────────────────────────────────
# 상태(§3-9)
# ─────────────────────────────────────────────────────────────

EPISODE_FLOW: tuple[str, ...] = ("plan_draft", "directive_ready", "approved", "buying", "assets_complete", "rehearsal", "rendered",
                                 "auto_qa_pass", "process_review_pass", "quality_review_pass", "ready_to_publish")
SLOT_FLOW: tuple[str, ...] = ("pending", "requested", "received", "probed", "auto_checked", "human_checked", "selected")
ATTEMPT_FLOW: tuple[str, ...] = ("requested", "generating", "received", "probed", "stored")
ATTEMPT_FAILURES: tuple[str, ...] = ("failed_unbilled", "failed_billed", "unknown_billed")
# 실패 상태 → 들어가는 조건·나가는 방법. 자동 재구매는 어디에도 없다.
FAILURE_STATES: dict[str, dict[str, str]] = {
    "blocked_assets": {"enter": "clip_missing / clip_corrupt / clip_short", "exit": "운영자: 저장된 자산 복구, 또는 새 결재로 재구매"},
    "blocked_no_pass": {"enter": "슬롯의 후보가 모두 불합격", "exit": "운영자: 새 결재 재촬영, 또는 계획 변경"},
    "blocked_budget": {"enter": "다음 시도가 결재 잔액을 넘음", "exit": "운영자: 추가 결재, 또는 중단"},
    "unknown_billed": {"enter": "호출 후 결과 불명", "exit": "조회 정정, 또는 운영자가 billed/void 로 닫기"},
    "auto_qa_fail": {"enter": "자동 검사 실패", "exit": "원인별로 고쳐 다시 렌더(돈 0)"},
    "review_fail": {"enter": "사람 검수 불합격", "exit": "운영자 지시대로(재렌더 / 재촬영 결재 / 폐기)"},
}
AUTO_REBUY: bool = False   # 상태 표의 '자동 재구매: 없음'. 켜는 코드를 만들지 않는다.
BLOCKED_ASSET_CODES: tuple[str, ...] = ("clip_missing", "clip_corrupt", "clip_short")


def can_transition(frm: str, to: str) -> bool:
    """정상 흐름은 한 칸씩만 앞으로. 실패 상태는 어느 진행 단계에서든 들어간다. 나갈 때는 운영자가 정해 다시 시작하는 단계로만."""
    if frm in EPISODE_FLOW and to in EPISODE_FLOW:
        return EPISODE_FLOW.index(to) == EPISODE_FLOW.index(frm) + 1
    if frm in EPISODE_FLOW and to in FAILURE_STATES:
        return True
    if frm in ("blocked_assets", "blocked_no_pass", "blocked_budget"):
        return to in ("approved", "plan_draft")   # 새 결재 또는 계획 변경
    if frm == "unknown_billed":
        return to == "buying"
    if frm in ("auto_qa_fail", "review_fail"):
        return to in ("rehearsal", "approved", "plan_draft")
    return False


class ExplainerStop(Exception):
    """렌더를 멈춘다. blocked_assets 코드 셋은 편 전체를 막는다 — 대체 경로가 없다."""

    def __init__(self, code: str, message: str, *, asset_id: Optional[str] = None, cut_id: Optional[str] = None,
                 problems: Optional[list[dict[str, Any]]] = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.asset_id, self.cut_id = code, message, asset_id, cut_id
        self.problems = problems or []
        self.state = "blocked_assets" if code in BLOCKED_ASSET_CODES else "auto_qa_fail"


# ─────────────────────────────────────────────────────────────
# 슬롯·후보·시도 키(§3-3). 0062 와 같은 공식이다(tests 와 PGlite 시험이 대조).
# ─────────────────────────────────────────────────────────────

def slot_id(plan_id: str, n: int) -> str:
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"자산 번호는 1 이상 정수입니다: {n}")
    return f"{plan_id}:A{n}"


def candidate_id(slot: str, k: int) -> str:
    if k not in range(1, config.DRINKS_EXPLAINER_MAX_CANDIDATES_PER_SLOT + 1):
        raise ValueError(f"후보 번호는 1~{config.DRINKS_EXPLAINER_MAX_CANDIDATES_PER_SLOT} 입니다: {k}")
    return f"{slot}#c{k}"


def attempt_id(candidate: str, m: int) -> str:
    if m not in range(1, config.DRINKS_EXPLAINER_MAX_ATTEMPTS_PER_CANDIDATE + 1):
        raise ValueError(f"시도 번호는 1~{config.DRINKS_EXPLAINER_MAX_ATTEMPTS_PER_CANDIDATE} 입니다: {m}")
    return f"{candidate}#a{m}"


def spec_hash(*, model: str, prompt: str, start_image_sha256: str, clip_sec: int, resolution: str) -> str:
    """슬롯 사양 해시 — 모델·문장·시작 그림 해시·길이·해상도(§3-3). 하나라도 바뀌면 다른 슬롯이다."""
    payload = {"model": model, "prompt": prompt, "start_image_sha256": start_image_sha256, "clip_sec": int(clip_sec), "resolution": resolution}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def idempotency_key(attempt: str, spec: str) -> str:
    """시도 멱등키 = sha256(attempt_id + spec_hash). 공급자 호출 **전에** 이 키로 행을 만든다."""
    return hashlib.sha256((attempt + spec).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# 편집표(§3-6). 이미지 나열식 지시서(정수 초)와 무관한 별도 표다 — 정수 ms, 1.5초 훅도 표현된다.
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Asset:
    asset_id: str
    path: str
    sha256: str
    role: str                     # reality | mechanism
    planned_ms: int = 0           # 계획 길이(참고). 판정은 실측으로 한다.


@dataclass(frozen=True)
class Shot:
    """비트 안의 한 묶음 — 한 자산의 연속 구간. raw_ms=None 이면 비트의 남은 시간을 쓴다."""
    asset_id: str
    boundary: str
    raw_ms: Optional[int] = None
    src_start_ms: Optional[int] = None   # None 이면 이 자산을 쓴 지점에서 이어 간다(앞당겨 보여 주기는 명시한다)


@dataclass(frozen=True)
class Beat:
    beat_id: str
    tts_ms: int                   # 나레이션 실측(배속 전)
    shots: tuple[Shot, ...]
    narration: str = ""
    keyword: str = ""             # 하단 자막에서 강조색으로 칠할 낱말
    tail_ms: int = 0              # 말 없는 꼬리
    tail_text: str = ""           # 꼬리 동안 나오는 한 줄
    card_text: str = ""           # 코드가 영상 위에 얹는 글자 카드(§3-6-2 B6)
    narration_path: str = ""


@dataclass(frozen=True)
class CaptionLayer:
    kind: str                     # hook | phrase | tail | card | depiction
    text: str
    start_ms: int
    end_ms: int
    accent: str = ""
    font_size: int = 0
    lines: tuple[str, ...] = ()
    box: tuple[int, int, int, int] = (0, 0, 0, 0)    # 그림 위 픽셀 상자 (x0, y0, x1, y1) — ASS 위치에서 계산
    pos: tuple[int, int] = (0, 0)
    anchor: int = 2
    overflow: bool = False


@dataclass(frozen=True)
class EditCut:
    cut_id: str
    beat_id: str
    asset_id: str
    src_start_ms: int
    src_end_ms: int
    timeline_start_ms: int
    timeline_end_ms: int
    boundary: str
    zoom: float = 1.0
    subtitle_layers: tuple[CaptionLayer, ...] = ()


@dataclass
class Timeline:
    cuts: list[EditCut]
    raw_ms: int
    final_ms: int
    speed: float
    warnings: list[str] = field(default_factory=list)


def playback_speed() -> float:
    speed = float(config.DRINKS_EXPLAINER_PLAYBACK_SPEED)
    if speed < 1.0:
        raise ExplainerStop("edit_cut_invalid", f"느리게 재생은 금지입니다(E2): 재생 속도 {speed}")
    return speed


def raw_to_final_ms(raw_ms: int, speed: Optional[float] = None) -> int:
    return int(round(raw_ms / (playback_speed() if speed is None else speed)))


def final_to_raw_ms(final_ms: int, speed: Optional[float] = None) -> int:
    return int(round(final_ms * (playback_speed() if speed is None else speed)))


def _split_ms(total: int, parts: int) -> list[int]:
    base, rest = divmod(total, parts)
    return [base + (1 if i < rest else 0) for i in range(parts)]


def build_timeline(beats: list[Beat], roles: dict[str, str], *, hook_text: str = "", speed: Optional[float] = None) -> Timeline:
    """TTS 실측 + 자산 계획 → 편집표. 비트의 시간(말 + 꼬리)을 묶음에 나누고, 묶음을 목표 길이의 컷으로 나눈다.

    같은 클립을 이어 자르는 컷은 확대를 번갈아 걸어 컷이 보이게 한다(E6, 움직이는 영상 위의 고정 배율)."""
    speed = playback_speed() if speed is None else float(speed)
    target_raw = final_to_raw_ms(config.DRINKS_EXPLAINER_CUT_TARGET_FINAL_MS, speed)
    cursor: dict[str, int] = {}
    pieces: list[EditCut] = []
    t = 0
    if not beats:
        raise ExplainerStop("edit_cut_invalid", "비트가 없습니다")
    for beat in beats:
        total = int(beat.tts_ms) + int(beat.tail_ms)
        fixed = sum(int(s.raw_ms) for s in beat.shots if s.raw_ms is not None)
        open_shots = [s for s in beat.shots if s.raw_ms is None]
        if len(open_shots) > 1 or (not open_shots and fixed != total) or fixed > total:
            raise ExplainerStop("edit_cut_invalid", f"{beat.beat_id}: 묶음 시간의 합({fixed}ms)이 비트 시간({total}ms)과 맞지 않습니다")
        for shot in beat.shots:
            raw = int(shot.raw_ms) if shot.raw_ms is not None else total - fixed
            if raw <= 0:
                raise ExplainerStop("edit_cut_invalid", f"{beat.beat_id}: 길이가 0 인 묶음입니다")
            explicit = shot.src_start_ms is not None
            src = int(shot.src_start_ms) if explicit else cursor.get(shot.asset_id, 0)
            for i, part in enumerate(_split_ms(raw, max(1, int(math.ceil(raw / target_raw))))):
                pieces.append(EditCut(
                    cut_id=f"E{len(pieces) + 1}", beat_id=beat.beat_id, asset_id=shot.asset_id, src_start_ms=src, src_end_ms=src + part,
                    timeline_start_ms=t, timeline_end_ms=t + part, boundary=shot.boundary if i == 0 else "same_clip",
                    zoom=config.DRINKS_EXPLAINER_ZOOM_MAX if i % 2 else 1.0))
                src += part
                t += part
            if not explicit:
                cursor[shot.asset_id] = src
    cuts, warnings = _attach_layers(pieces, beats, roles, hook_text=hook_text, speed=speed)
    tl = Timeline(cuts=cuts, raw_ms=t, final_ms=raw_to_final_ms(t, speed), speed=speed, warnings=warnings)
    validate_edit_cuts(tl.cuts)
    return tl


def slot_min_src_ms(cuts: list[EditCut]) -> dict[str, int]:
    """슬롯 min_src_ms = 편집 컷들이 이 자산에서 쓰는 가장 늦은 끝 지점 + 여유(§3-3)."""
    out: dict[str, int] = {}
    for c in cuts:
        out[c.asset_id] = max(out.get(c.asset_id, 0), c.src_end_ms + config.DRINKS_EXPLAINER_MIN_SRC_MARGIN_MS)
    return out


def plan_margin_problems(cuts: list[EditCut], planned_ms: dict[str, int]) -> list[str]:
    """계획 규칙 '사용 길이 ≤ 자산 길이 − 0.5초'(§3-6-2)를 어긴 자산. 렌더를 막지는 않는다(실제 판정은 clip_short)."""
    last: dict[str, int] = {}
    for c in cuts:
        last[c.asset_id] = max(last.get(c.asset_id, 0), c.src_end_ms)
    return [a for a, end in last.items() if end > planned_ms.get(a, 0) - config.DRINKS_EXPLAINER_PLAN_MARGIN_MS]


def validate_edit_cuts(cuts: list[EditCut]) -> None:
    """E1·E2·E6 의 표 수준 검사. 정수 ms·이어진 타임라인·구간 길이 = 타임라인 길이(늘리거나 줄인 컷이 없다)·확대 상한."""
    if not cuts:
        raise ExplainerStop("edit_cut_invalid", "편집 컷이 없습니다")
    t = 0
    for c in cuts:
        nums = (c.src_start_ms, c.src_end_ms, c.timeline_start_ms, c.timeline_end_ms)
        if not c.asset_id or not all(isinstance(n, int) and not isinstance(n, bool) for n in nums):
            raise ExplainerStop("edit_cut_invalid", f"{c.cut_id}: asset_id 와 정수 ms 구간이 있어야 합니다(E1)", cut_id=c.cut_id)
        if c.src_start_ms < 0 or c.src_end_ms <= c.src_start_ms:
            raise ExplainerStop("edit_cut_invalid", f"{c.cut_id}: 원본 구간이 잘못됐습니다", cut_id=c.cut_id)
        if c.src_end_ms - c.src_start_ms != c.timeline_end_ms - c.timeline_start_ms:
            raise ExplainerStop("edit_cut_invalid", f"{c.cut_id}: 원본 구간과 타임라인 길이가 다릅니다 — 길이 보정 금지(E2)", cut_id=c.cut_id)
        if c.timeline_start_ms != t:
            raise ExplainerStop("edit_cut_invalid", f"{c.cut_id}: 타임라인에 빈틈·겹침이 있습니다", cut_id=c.cut_id)
        if not 1.0 <= float(c.zoom) <= config.DRINKS_EXPLAINER_ZOOM_MAX:
            raise ExplainerStop("edit_cut_invalid", f"{c.cut_id}: 확대 {c.zoom} 는 상한 {config.DRINKS_EXPLAINER_ZOOM_MAX} 밖입니다(E6)", cut_id=c.cut_id)
        if c.boundary not in config.DRINKS_EXPLAINER_BOUNDARY_KINDS:
            raise ExplainerStop("edit_cut_invalid", f"{c.cut_id}: 알 수 없는 경계 종류 {c.boundary}", cut_id=c.cut_id)
        t = c.timeline_end_ms


# ─────────────────────────────────────────────────────────────
# 자막 층 — 그림 위 위치를 직접 정하고 상자를 계산한다(§2-3 "ASS 위치 → 픽셀 상자")
# ─────────────────────────────────────────────────────────────

def _caption_font(size: int):
    from PIL import ImageFont

    return ImageFont.truetype(os.path.join(FONT_DIR, config.DRINKS_EXPLAINER_FONT_FILE), size)


def layout_caption(kind: str, text: str) -> dict[str, Any]:
    """글자를 안전 영역 폭에 맞춰 줄 나누고 크기를 정한다 → font_size, lines, box, pos, anchor, overflow(순수, 글꼴 파일만 읽는다).
    상한 줄 수에 못 넣으면 자르지 않는다 — overflow 로 표시해 자동 검사가 막게 한다."""
    from PIL import Image, ImageDraw

    spec = config.DRINKS_EXPLAINER_CAPTION_LAYOUT[kind]
    w = config.RENDER_WIDTH
    left, right = config.DRINKS_EXPLAINER_SAFE_LEFT_PX, w - config.DRINKS_EXPLAINER_SAFE_RIGHT_PX
    outline = config.DRINKS_EXPLAINER_OUTLINE_PX
    width = right - left - 2 * outline
    draw = ImageDraw.Draw(Image.new("L", (8, 8)))
    size, lines, font = spec["size"], [text], None
    overflow = True
    for size in range(spec["size"], spec["min_size"] - 1, -2):
        font = _caption_font(size)
        lines = wrap(draw, text, font, width)
        if len(lines) <= spec["max_lines"]:
            overflow = False
            break
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    text_w = int(math.ceil(max(font.getlength(ln) for ln in lines))) if lines else 0
    height = line_h * len(lines)
    anchor, y = spec["anchor"], spec["y"]
    x = left if anchor == 7 else (left + right) // 2
    x0 = x if anchor == 7 else x - text_w // 2
    y0 = y - height if anchor == 2 else y
    box = (x0 - outline, y0 - outline, x0 + text_w + outline, y0 + height + outline)
    return {"font_size": size, "lines": tuple(lines), "box": box, "pos": (x, y), "anchor": anchor, "overflow": overflow}


def make_layer(kind: str, text: str, start_ms: int, end_ms: int, accent: str = "") -> CaptionLayer:
    return CaptionLayer(kind=kind, text=text, start_ms=int(start_ms), end_ms=int(end_ms), accent=accent, **layout_caption(kind, text))


def _beat_spans(beats: list[Beat]) -> list[tuple[Beat, int]]:
    out, t = [], 0
    for b in beats:
        out.append((b, t))
        t += int(b.tts_ms) + int(b.tail_ms)
    return out


def _attach_layers(cuts: list[EditCut], beats: list[Beat], roles: dict[str, str], *, hook_text: str, speed: float) -> tuple[list[EditCut], list[str]]:
    """자막 층을 컷마다 잘라 붙인다. 표 하나가 곧 화면 기록이다(자막이 두 컷에 걸치면 두 조각)."""
    layers: list[CaptionLayer] = []
    warnings: list[str] = []
    for beat, start in _beat_spans(beats):
        speak_end = start + int(beat.tts_ms)
        shown = False
        for s, e, text in subtitles.chunk_text_by_phrase(beat.narration, start / 1000.0, speak_end / 1000.0) if beat.narration.strip() else []:
            accent = beat.keyword if beat.keyword and beat.keyword in text else ""
            shown = shown or bool(accent)
            layers.append(make_layer("phrase", text, int(round(s * 1000)), int(round(e * 1000)), accent))
        if beat.keyword and not shown:
            warnings.append(f"keyword_not_shown:{beat.beat_id}")
        if beat.card_text:
            layers.append(make_layer("card", beat.card_text, start, speak_end))
        if beat.tail_ms and beat.tail_text:
            layers.append(make_layer("tail", beat.tail_text, speak_end, speak_end + int(beat.tail_ms)))
    if hook_text.strip() and cuts:
        hook_end = min(cuts[0].timeline_end_ms, final_to_raw_ms(int(config.DRINKS_EXPLAINER_HOOK_WINDOW_SEC * 1000), speed))
        layers.append(make_layer("hook", hook_text, 0, hook_end))
    out: list[EditCut] = []
    labels = config.DRINKS_EXPLAINER_DEPICTION_LABELS
    for c in cuts:
        pieces = []
        label = labels.get(roles.get(c.asset_id, ""), "")
        if label:
            pieces.append(make_layer("depiction", label, c.timeline_start_ms, c.timeline_end_ms))
        for ly in layers:
            s, e = max(ly.start_ms, c.timeline_start_ms), min(ly.end_ms, c.timeline_end_ms)
            if e > s:
                pieces.append(dataclasses.replace(ly, start_ms=s, end_ms=e))
        out.append(dataclasses.replace(c, subtitle_layers=tuple(pieces)))
    return out, warnings


def _ass_text(text: str) -> str:
    return re.sub(r"[{}\\]", "", str(text or "")).replace("\n", " ")


def _ass_color(hex_rgb: str) -> str:
    v = hex_rgb.lstrip("#")
    return f"&H{v[4:6]}{v[2:4]}{v[0:2]}&".upper()


def _ass_line(ly: CaptionLayer) -> str:
    accent = _ass_color(config.CAPTION_HIGHLIGHT_COLOR)
    parts = []
    for ln in ly.lines:
        t = _ass_text(ln)
        if ly.accent and ly.accent in t:
            t = t.replace(ly.accent, f"{{\\c{accent}}}{_ass_text(ly.accent)}{{\\c&HFFFFFF&}}", 1)
        parts.append(t)
    return f"{{\\an{ly.anchor}\\pos({ly.pos[0]},{ly.pos[1]})\\fs{ly.font_size}}}" + "\\N".join(parts)


def build_ass(cuts: list[EditCut]) -> str:
    """자막 층 → ASS. 줄바꿈은 위에서 정했으므로 자동 줄바꿈을 끈다(WrapStyle 2) — 계산한 상자와 그림이 같아야 검사가 뜻이 있다."""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
            f"Style: Explainer,{config.DRINKS_EXPLAINER_FONT_NAME},64,&H00FFFFFF,&H00000000,&H64000000,1,0,1,{config.DRINKS_EXPLAINER_OUTLINE_PX},0,2,0,0,0\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    rows = []
    for c in cuts:
        for ly in c.subtitle_layers:
            rows.append(f"Dialogue: 0,{subtitles.ass_timestamp(ly.start_ms / 1000.0)},{subtitles.ass_timestamp(ly.end_ms / 1000.0)},Explainer,,0,0,0,,{_ass_line(ly)}")
    return head + "\n".join(rows) + "\n"


# ─────────────────────────────────────────────────────────────
# 강제 조건 E1~E6
# ─────────────────────────────────────────────────────────────

_IMAGE_CODECS = {"png", "mjpeg", "webp", "bmp", "gif", "tiff", "jpeg2000"}


@contextmanager
def free_providers() -> Iterator[None]:
    """E3: 렌더 동안 공급자를 무료로 고정한다(끝나면 되돌린다). 유료가 남아 있으면 시작하지 않는다."""
    prev = (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER)
    config.IMAGE_PROVIDER, config.VIDEO_PROVIDER = "reuse", "placeholder"
    try:
        if config.image_is_paid() or config.video_is_paid():
            raise ExplainerStop("paid_disabled", "유료 이미지·영상 공급자가 켜져 있습니다 — 렌더는 사지 않습니다(E3)")
        yield
    finally:
        config.IMAGE_PROVIDER, config.VIDEO_PROVIDER = prev


def _subprocess(argv: list[str], *, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    # ★ 윈도우 기본 코드 페이지로 읽으면 ffmpeg 가 찍는 한글 경로에서 디코딩이 죽는다 — UTF-8 + 대체 문자로 읽는다.
    return subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd,
                          timeout=config.DRINKS_EXPLAINER_FFMPEG_TIMEOUT_SEC)


def probe_clip(path: str) -> dict[str, Any]:
    """E5: 파일을 실제로 잰다. 길이는 머리 정보와 실제로 읽힌 프레임 수 중 짧은 쪽(손상된 파일은 머리 정보만 멀쩡할 수 있다).
    ffprobe 가 읽지 못하면 ok=False. ffprobe 자체가 없으면 FileNotFoundError 를 그대로 올린다 — 깨진 클립으로 착각하지 않는다."""
    proc = _subprocess(["ffprobe", "-v", "error", "-count_packets",
                        "-show_entries", "stream=codec_type,codec_name,width,height,duration,nb_read_packets,avg_frame_rate,r_frame_rate,sample_rate:format=duration,format_name",
                        "-of", "json", path])
    out: dict[str, Any] = {"ok": False, "has_video": False, "error": "", "duration_ms": 0, "frames": 0, "width": None, "height": None, "fps": None,
                           "video_codec": None, "audio_codec": None, "audio_sample_rate": None, "still": False, "format_name": None}
    if proc.returncode != 0:
        out["error"] = (proc.stderr or "")[-300:]
        return out
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        out["error"] = "ffprobe 응답을 읽지 못했습니다"
        return out
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    out["ok"] = True
    out["format_name"] = fmt.get("format_name")
    if a:
        out["audio_codec"] = a.get("codec_name")
        out["audio_sample_rate"] = int(a["sample_rate"]) if a.get("sample_rate") else None
    if not v:
        return out
    out["has_video"] = True
    out.update(video_codec=v.get("codec_name"), width=v.get("width"), height=v.get("height"))
    fps = _parse_rate(v.get("avg_frame_rate")) or _parse_rate(v.get("r_frame_rate"))
    frames = int(v.get("nb_read_packets") or 0)
    header = _to_float(v.get("duration")) or _to_float(fmt.get("duration")) or 0.0
    decoded = frames / fps if fps else 0.0
    out.update(fps=fps, frames=frames, duration_ms=int(round(1000 * (min(header, decoded) if header and decoded else (decoded or header)))))
    out["still"] = str(v.get("codec_name")) in _IMAGE_CODECS or frames <= 1
    return out


def _parse_rate(raw: Any) -> Optional[float]:
    try:
        num, _, den = str(raw).partition("/")
        val = float(num) / float(den or 1)
        return round(val, 3) if val > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _to_float(raw: Any) -> Optional[float]:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def check_assets(cuts: list[EditCut], assets: dict[str, Asset]) -> dict[str, dict[str, Any]]:
    """E1·E3·E4·E5: 쓰는 자산을 전부 잰다. 하나라도 어긋나면 **편 전체를 멈춘다**(문제 목록을 함께 싣는다). 무엇도 사지 않고, 무엇으로도 바꾸지 않는다."""
    validate_edit_cuts(cuts)
    problems: list[dict[str, Any]] = []
    probes: dict[str, dict[str, Any]] = {}
    last: dict[str, EditCut] = {}
    for c in cuts:
        if c.asset_id not in last or c.src_end_ms > last[c.asset_id].src_end_ms:
            last[c.asset_id] = c

    def bad(code: str, asset_id: str, message: str) -> None:
        problems.append({"code": code, "asset_id": asset_id, "message": message})

    for asset_id, cut in last.items():
        a = assets.get(asset_id)
        if a is None or not a.path or not os.path.isfile(a.path):
            bad("clip_missing", asset_id, f"{asset_id}: 클립 파일이 없습니다")
            continue
        if sha256_file(a.path) != a.sha256:
            bad("clip_corrupt", asset_id, f"{asset_id}: 파일 해시가 기록과 다릅니다")
            continue
        probe = probe_clip(a.path)
        if not probe["ok"]:
            bad("clip_corrupt", asset_id, f"{asset_id}: ffprobe 가 읽지 못합니다 ({probe['error'][:120]})")
            continue
        if not probe["has_video"]:
            bad("clip_corrupt", asset_id, f"{asset_id}: 영상 스트림이 없습니다")
            continue
        if probe["still"]:
            bad("clip_corrupt", asset_id, f"{asset_id}: 움직이는 영상이 아니라 그림입니다(E1)")
            continue
        probes[asset_id] = probe
        if cut.src_end_ms > probe["duration_ms"]:
            bad("clip_short", asset_id, f"{asset_id}: {cut.cut_id} 가 {cut.src_end_ms}ms 까지 쓰는데 실제 길이는 {probe['duration_ms']}ms 입니다")
    if problems:
        first = problems[0]
        raise ExplainerStop(first["code"], first["message"], asset_id=first["asset_id"], problems=problems)
    return probes


# ─────────────────────────────────────────────────────────────
# 렌더
# ─────────────────────────────────────────────────────────────

def _frame(ms: int) -> int:
    return int(round(ms * config.RENDER_FPS / 1000.0))


def cut_filter(zoom: float) -> str:
    """9:16 꽉 채움 + (있으면) 고정 배율 확대. 영상 프레임을 그대로 통과시킨다 — 시간을 건드리는 필터가 없다."""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    parts = [f"fps={config.RENDER_FPS}", f"scale={w}:{h}:force_original_aspect_ratio=increase", f"crop={w}:{h}"]
    if float(zoom) > 1.0:
        z = f"{float(zoom):.3f}"
        parts += [f"crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2", f"scale={w}:{h}"]
    return ",".join(parts + ["setsar=1", "format=yuv420p"])


def build_cut_argv(cut: EditCut, asset_path: str, out_path: str) -> list[str]:
    """원본 구간만 잘라 낸다(소리 버림). 프레임 수는 타임라인에서 계산해 컷이 쌓여도 어긋나지 않게 한다."""
    n = _frame(cut.timeline_end_ms) - _frame(cut.timeline_start_ms)
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{cut.src_start_ms / 1000.0:.3f}", "-i", asset_path,
            "-map", "0:v:0", "-an", "-vf", cut_filter(cut.zoom), "-frames:v", str(n),
            "-c:v", "libx264", "-preset", config.DRINKS_EXPLAINER_X264_PRESET, "-crf", str(config.DRINKS_EXPLAINER_X264_CRF), "-pix_fmt", "yuv420p", out_path]


def build_narration_argv(beats: list[Beat], out_path: str) -> list[str]:
    """비트별 나레이션을 비트 시간에 맞춰 이어 붙인다(말 뒤 꼬리는 무음). 소리 길이가 곧 타임라인 길이다."""
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    parts, labels = [], []
    rate = config.OUTPUT_AUDIO_SAMPLE_RATE
    for i, b in enumerate(beats):
        argv += ["-i", b.narration_path]
        sec = (int(b.tts_ms) + int(b.tail_ms)) / 1000.0
        parts.append(f"[{i}:a]aresample={rate},aformat=channel_layouts=stereo,apad=whole_dur={sec:.3f},atrim=0:{sec:.3f},asetpts=N/SR/TB[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(beats)}:v=0:a=1[a]"
    return argv + ["-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-ar", str(rate), out_path]


def prepare_burn_dir(work_dir: str) -> str:
    """번인에 쓸 글꼴을 작업 폴더 안 ASCII 이름으로 복사한다.

    ★ 2026-11-02 윈도우 실측: 글꼴 경로에 한글이 있으면 ffmpeg 필터가 글꼴을 열다가 프로세스째 죽었다(0xC0000005, drawtext).
      assemble.filter_path 는 콜론·역슬래시만 처리한다. 그래서 필터 안 경로는 전부 상대 경로로 쓰고 작업 폴더에서 실행한다(build_burn_argv)."""
    fonts = os.path.join(work_dir, "fonts")
    os.makedirs(fonts, exist_ok=True)
    shutil.copyfile(os.path.join(FONT_DIR, config.DRINKS_EXPLAINER_FONT_FILE), os.path.join(fonts, config.DRINKS_EXPLAINER_FONT_FILE))
    return fonts


def build_burn_argv(in_name: str, ass_name: str, out_name: str) -> list[str]:
    """자막 번인 — 작업 폴더에서 실행하는 상대 경로 전용(prepare_burn_dir 주석)."""
    vf = f"ass=filename='{assemble.filter_path(ass_name)}':fontsdir=fonts"
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", in_name, "-vf", vf,
            "-c:v", "libx264", "-preset", config.DRINKS_EXPLAINER_X264_PRESET, "-crf", str(config.DRINKS_EXPLAINER_X264_CRF), "-pix_fmt", "yuv420p", "-c:a", "copy", out_name]


@dataclass
class Rendered:
    out_path: str
    manifest_path: str
    manifest: dict[str, Any]
    argv_log: list[list[str]] = field(default_factory=list)


def remeasure_beats(beats: list[Beat]) -> list[Beat]:
    """렌더 직전에 나레이션을 다시 잰다(§3-6 "TTS 가 바뀌면"). 표는 이 값으로 다시 계산된다."""
    out = []
    for b in beats:
        if not b.narration_path or not os.path.isfile(b.narration_path):
            raise ExplainerStop("narration_missing", f"{b.beat_id}: 나레이션 파일이 없습니다")
        measured = media_duration_ms(b.narration_path)
        if measured <= 0:
            raise ExplainerStop("narration_missing", f"{b.beat_id}: 나레이션 길이를 잴 수 없습니다")
        out.append(dataclasses.replace(b, tts_ms=measured))
    return out


def media_duration_ms(path: str) -> int:
    proc = _subprocess(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return int(round(1000 * (_to_float((proc.stdout or "").strip()) or 0.0))) if proc.returncode == 0 else 0


def _layer_row(ly: CaptionLayer) -> dict[str, Any]:
    return {"kind": ly.kind, "text": ly.text, "start_ms": ly.start_ms, "end_ms": ly.end_ms, "accent": ly.accent, "font_size": ly.font_size,
            "box": list(ly.box), "overflow": ly.overflow}


def _detect_freeze(path: str, min_sec: float) -> list[tuple[float, float]]:
    proc = _subprocess(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-an",
                        "-vf", f"freezedetect=n={config.DRINKS_EXPLAINER_FREEZE_NOISE}:d={min_sec:.3f}", "-f", "null", "-"])
    if proc.returncode != 0:
        raise ExplainerStop("render_failed", f"정지 검사 실패: {(proc.stderr or '')[-200:]}")
    return parse_freeze_spans(proc.stderr or "", media_duration_ms(path) / 1000.0)


def render_explainer(beats: list[Beat], assets: dict[str, Asset], *, hook_text: str, out_path: str, work_dir: str,
                     plan_id: str = "rehearsal") -> Rendered:
    """편집표대로 잘라 잇고 → 나레이션 → 자막 층 → 음량 정규화 → 배속 → 1080×1920 mp4 + 렌더 기록(manifest).

    ★ 멈추면 출력 파일이 없다 — 지난번 파일이 남아 있어도 먼저 지운다(옛 결과가 이번 결과로 읽히면 안 된다)."""
    argv_log: list[list[str]] = []

    def run(argv: list[str], cwd: Optional[str] = None) -> None:
        argv_log.append(argv)
        proc = _subprocess(argv, cwd=cwd)
        if proc.returncode != 0:
            raise ExplainerStop("render_failed", f"ffmpeg 실패({proc.returncode}): {(proc.stderr or '')[-400:]}")

    manifest_path = out_path + ".manifest.json"
    for stale in (out_path, manifest_path):
        if os.path.exists(stale):
            os.remove(stale)
    with free_providers():
        speed = playback_speed()
        beats = remeasure_beats(beats)
        tl = build_timeline(beats, {k: a.role for k, a in assets.items()}, hook_text=hook_text, speed=speed)
        probes = check_assets(tl.cuts, assets)
        os.makedirs(work_dir, exist_ok=True)
        cut_paths = []
        for i, c in enumerate(tl.cuts):
            p = os.path.join(work_dir, f"cut_{i:03d}.mp4")
            run(build_cut_argv(c, assets[c.asset_id].path, p))
            got = probe_clip(p)
            want = _frame(c.timeline_end_ms) - _frame(c.timeline_start_ms)
            if not got["ok"] or got["frames"] != want:
                # 원본이 모자라 프레임이 덜 나왔다 — 메우지 않는다(E2).
                raise ExplainerStop("clip_short", f"{c.cut_id}: 프레임 {got['frames']}/{want} — {c.asset_id} 원본 구간이 모자랍니다", asset_id=c.asset_id, cut_id=c.cut_id)
            cut_paths.append(p)
        video_only = os.path.join(work_dir, "_video_only.mp4")
        run(assemble.build_concat_clips_command(clip_paths=cut_paths, out_path=video_only, concat_file=os.path.join(work_dir, "concat.txt")))
        # 자막이 바뀌면 정지 검출이 끊긴다 — 자막 입히기 전 화면에서 따로 잰다(문턱은 최종 시간 기준이라 배속 전으로 환산).
        pre_caption_freeze = _detect_freeze(video_only, config.DRINKS_EXPLAINER_FREEZE_MIN_SEC * speed)
        narration = os.path.join(work_dir, "_narration.m4a")
        run(build_narration_argv(beats, narration))
        muxed = os.path.join(work_dir, "_muxed.mp4")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_only, "-i", narration, "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-c:a", "aac", "-ar", str(config.OUTPUT_AUDIO_SAMPLE_RATE), "-shortest", muxed])
        ass_path = os.path.join(work_dir, "layers.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(build_ass(tl.cuts))
        prepare_burn_dir(work_dir)
        run(build_burn_argv("_muxed.mp4", "layers.ass", "_burned.mp4"), cwd=work_dir)
        burned = os.path.join(work_dir, "_burned.mp4")
        normed = os.path.join(work_dir, "_normed.mp4")
        run(assemble.build_loudnorm_command(burned, normed, config.LOUDNESS_LUFS))
        stage = normed
        if abs(speed - 1.0) > 0.001:
            stage = os.path.join(work_dir, "_sped.mp4")
            run(assemble.build_speed_command(normed, stage, speed))
        manifest = {
            "format": "explainer", "plan_id": plan_id, "playback_speed": speed, "raw_ms": tl.raw_ms, "final_ms": tl.final_ms, "fps": config.RENDER_FPS,
            "cuts": [{"kind": "clip", "cut_id": c.cut_id, "beat_id": c.beat_id, "asset_id": c.asset_id, "asset_sha256": assets[c.asset_id].sha256,
                      "src_start_ms": c.src_start_ms, "src_end_ms": c.src_end_ms, "timeline_start_ms": c.timeline_start_ms, "timeline_end_ms": c.timeline_end_ms,
                      "boundary": c.boundary, "zoom": c.zoom, "subtitle_layers": [_layer_row(ly) for ly in c.subtitle_layers]} for c in tl.cuts],
            "assets": {a: {"sha256": assets[a].sha256, "role": assets[a].role, "duration_ms": p["duration_ms"], "frames": p["frames"],
                           "width": p["width"], "height": p["height"], "fps": p["fps"], "min_src_ms": slot_min_src_ms(tl.cuts)[a]} for a, p in probes.items()},
            "video_fallbacks": [],   # 설명형 렌더에는 사진 대체 경로가 없다 — 자동 검사가 이 칸이 비었는지 본다
            "pre_caption_freeze": [[round(s, 3), round(d, 3)] for s, d in pre_caption_freeze],
            "timeline_warnings": tl.warnings,
        }
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.move(stage, out_path)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
    return Rendered(out_path, manifest_path, manifest, argv_log)


# ─────────────────────────────────────────────────────────────
# 최종 영상 자동 검사(§3-8 A) — 합격은 "돌아간다"이지 품질이 아니다
# ─────────────────────────────────────────────────────────────

@dataclass
class QaResult:
    blocks: list[str]
    warns: list[str]
    signals: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.blocks

    @property
    def state(self) -> str:
        return "auto_qa_pass" if self.ok else "auto_qa_fail"


def measure_final(path: str) -> dict[str, Any]:
    """영상을 재서 신호를 모은다. 잴 수 없으면 errors 에 남긴다 — 평가는 그것을 통과로 치지 않는다."""
    signals: dict[str, Any] = {"probe": probe_clip(path), "bytes": os.path.getsize(path) if os.path.exists(path) else 0, "moov_first": False,
                               "freeze": [], "black": [], "lufs": None, "errors": []}
    if not signals["probe"]["ok"] or not signals["probe"]["has_video"]:
        signals["errors"].append("probe_failed")
        return signals
    signals["moov_first"] = moov_before_mdat(path)
    proc = _subprocess(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                        "-vf", f"freezedetect=n={config.DRINKS_EXPLAINER_FREEZE_NOISE}:d={config.DRINKS_EXPLAINER_FREEZE_MIN_SEC},"
                               f"blackdetect=d={config.DRINKS_EXPLAINER_BLACK_MIN_SEC}:pic_th={config.DRINKS_EXPLAINER_BLACK_PIC_TH}",
                        "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    if proc.returncode != 0:
        signals["errors"].append("detect_failed")
        return signals
    stderr = proc.stderr or ""
    signals["freeze"] = [[round(s, 3), round(d, 3)] for s, d in parse_freeze_spans(stderr, signals["probe"]["duration_ms"] / 1000.0)]
    signals["black"] = [[float(m.group(1)), float(m.group(2))] for m in re.finditer(r"black_start:([0-9.]+)\s+black_end:[0-9.]+\s+black_duration:([0-9.]+)", stderr)]
    loud = re.findall(r"I:\s+(-?[0-9.]+) LUFS", stderr)
    signals["lufs"] = float(loud[-1]) if loud else None
    return signals


def _box_in_safe_area(box: list[int]) -> bool:
    x0, y0, x1, y1 = box
    return (x0 >= 0 and y0 >= 0 and x1 <= config.RENDER_WIDTH - config.DRINKS_EXPLAINER_SAFE_RIGHT_PX
            and y1 <= config.RENDER_HEIGHT - config.DRINKS_EXPLAINER_SAFE_BOTTOM_PX)


def evaluate_auto_qa(signals: dict[str, Any], manifest: dict[str, Any]) -> QaResult:
    """신호 + 렌더 기록 → 막는 코드·알리는 코드(순수 함수)."""
    blocks: list[str] = list(signals.get("errors") or [])
    warns: list[str] = list(manifest.get("timeline_warnings") or [])
    probe = signals.get("probe") or {}
    speed = float(manifest.get("playback_speed") or 1.0)
    dur_sec = float(probe.get("duration_ms") or 0) / 1000.0
    # 1. 규격(엔진 릴스 규격 함수를 그대로 쓴다 — 표지는 이 검사 대상이 아니다)
    spec_probe = {"audio_sample_rate": probe.get("audio_sample_rate"), "duration_sec": dur_sec, "width": probe.get("width"), "fps": probe.get("fps"),
                  "video_codec": probe.get("video_codec"), "audio_codec": probe.get("audio_codec")}
    blocks += reel_spec_warnings(spec_probe, int(signals.get("bytes") or 0), bool(signals.get("moov_first")), config.DRINKS_REEL_SPEC["cover_mime"], 0)
    if (probe.get("width"), probe.get("height")) != (config.RENDER_WIDTH, config.RENDER_HEIGHT):
        blocks.append("spec_not_1080x1920")
    # 2. 길이
    lo, hi = config.DRINKS_EXPLAINER_FINAL_SEC
    if not lo <= dur_sec <= hi:
        blocks.append("duration_out_of_range")
    if abs(dur_sec * 1000 - float(manifest.get("final_ms") or 0)) > 250:
        blocks.append("duration_manifest_mismatch")   # 조립이 조용히 컷을 잃었는지(2026-09-08 실측과 같은 종류)
    # 3. 렌더 기록
    cuts = manifest.get("cuts") or []
    if not cuts:
        blocks.append("manifest_no_cuts")
    if manifest.get("video_fallbacks") != []:
        blocks.append("manifest_fallback_recorded")
    t = 0
    for c in cuts:
        if c.get("kind") != "clip":
            blocks.append(f"manifest_cut_not_clip:{c.get('cut_id')}")
        if not c.get("asset_id") or not isinstance(c.get("src_start_ms"), int) or not isinstance(c.get("src_end_ms"), int) or c["src_end_ms"] <= c["src_start_ms"]:
            blocks.append(f"manifest_cut_no_source:{c.get('cut_id')}")
        if c.get("timeline_start_ms") != t:
            blocks.append(f"manifest_timeline_gap:{c.get('cut_id')}")
        t = c.get("timeline_end_ms") or t
        if float(c.get("zoom") or 1.0) > config.DRINKS_EXPLAINER_ZOOM_MAX:
            blocks.append(f"manifest_zoom_over:{c.get('cut_id')}")
        final_len = (int(c.get("timeline_end_ms") or 0) - int(c.get("timeline_start_ms") or 0)) / speed
        if final_len > config.DRINKS_EXPLAINER_CUT_MAX_FINAL_MS:
            warns.append(f"cut_over_max:{c.get('cut_id')}")
        elif final_len < config.DRINKS_EXPLAINER_CUT_MIN_FINAL_MS:
            warns.append(f"cut_under_min:{c.get('cut_id')}")
    # 4. 정지(0.8초 — 끝까지 얼어 있어도 잡는다)
    if any(float(d) >= config.DRINKS_EXPLAINER_FREEZE_MIN_SEC for _, d in signals.get("freeze") or []):
        blocks.append("freeze")
    if any(float(d) >= config.DRINKS_EXPLAINER_FREEZE_MIN_SEC * speed for _, d in manifest.get("pre_caption_freeze") or []):
        blocks.append("freeze_under_captions")
    # 5. 검은 화면·소리 크기
    if any(float(d) >= config.DRINKS_EXPLAINER_BLACK_MIN_SEC for _, d in signals.get("black") or []):
        blocks.append("black_frames")
    lufs = signals.get("lufs")
    if lufs is None:
        blocks.append("loudness_unmeasured")
    elif abs(float(lufs) - config.LOUDNESS_LUFS) > config.DRINKS_EXPLAINER_LOUDNESS_TOLERANCE_LU:
        blocks.append("loudness_off_target")
    # 6. 자막 상자·훅
    H = config.RENDER_HEIGHT
    band_lo, band_hi = (int(H * p) for p in config.DRINKS_EXPLAINER_HOOK_BAND_PCT)
    window = config.DRINKS_EXPLAINER_HOOK_WINDOW_SEC * 1000
    hook_seen = False
    for i, c in enumerate(cuts):
        for ly in c.get("subtitle_layers") or []:
            box = ly.get("box") or [0, 0, 0, 0]
            if not _box_in_safe_area(box):
                blocks.append(f"caption_out_of_safe_area:{c.get('cut_id')}:{ly.get('kind')}")
            if ly.get("overflow"):
                blocks.append(f"caption_overflow:{c.get('cut_id')}:{ly.get('kind')}")
            if ly.get("kind") != "hook":
                continue
            hook_seen = True
            if i != 0:
                blocks.append("hook_not_first_cut_only")
            if ly["start_ms"] > 0 or ly["end_ms"] / speed > window + 20:
                blocks.append("hook_outside_window")
            if box[1] < band_lo or box[3] > band_hi:
                blocks.append("hook_out_of_band")
    if not hook_seen:
        blocks.append("hook_missing")
    tlo, thi = config.DRINKS_EXPLAINER_TARGET_SEC
    if not tlo <= dur_sec <= thi and lo <= dur_sec <= hi:
        warns.append("duration_outside_target")
    return QaResult(blocks=sorted(set(blocks)), warns=sorted(set(warns)),
                    signals={"duration_sec": dur_sec, "fps": probe.get("fps"), "width": probe.get("width"), "height": probe.get("height"),
                             "lufs": lufs, "freeze": signals.get("freeze"), "black": signals.get("black"), "bytes": signals.get("bytes")})


def run_auto_qa(path: str, manifest: dict[str, Any]) -> QaResult:
    return evaluate_auto_qa(measure_final(path), manifest)


# ─────────────────────────────────────────────────────────────
# 견적(§3-7) — 날짜 붙은 단가표 하나에서만 읽는다
# ─────────────────────────────────────────────────────────────

def clip_price_per_sec(provider: str, resolution: str = "720p") -> float:
    prices = config.DRINKS_EXPLAINER_PRICES
    if provider == "omni":
        p = prices["omni"]
        return p["output_usd_per_mtok"] * p["tokens_per_sec"][resolution] / 1_000_000
    if provider == "veo_fast":
        return prices["veo_fast"]["video_only_usd_per_sec"][resolution]
    raise ValueError(f"견적을 낼 수 없는 공급자입니다: {provider}")


def quote_explainer(provider: str = "omni", resolution: str = "720p") -> dict[str, Any]:
    """한 편(§3-6-2) 예상액·승인 상한. 재시도 예비까지 더한 상한은 10센트 단위로 올린다(문서 표와 같은 방식)."""
    prices, n = config.DRINKS_EXPLAINER_PRICES, config.DRINKS_EXPLAINER_PLAN_COUNTS
    per_sec = clip_price_per_sec(provider, resolution)
    images = n["mechanism_images"] * prices["image"]["mechanism"]["usd"] + n["reality_images"] * prices["image"]["reality"]["usd"]
    image_input = 0.0
    if provider == "omni":
        image_input = (n["mechanism_images"] + n["reality_images"]) * prices["omni"]["input_image_tokens"] * prices["omni"]["input_usd_per_mtok"] / 1_000_000
    estimate = images + n["clip_sec"] * per_sec + image_input + n["second_candidate_sec"] * per_sec
    cap = estimate + n["retry_clip_sec"] * per_sec + n["retry_mechanism_images"] * prices["image"]["mechanism"]["usd"]
    return {"provider": provider, "resolution": resolution, "as_of": prices["as_of"], "per_sec_usd": round(per_sec, 5),
            "estimate_usd": round(estimate, 2), "cap_usd": round(math.ceil(round(cap, 4) * 10) / 10, 2)}
