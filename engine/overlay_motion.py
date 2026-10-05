r"""화면 표현 다음 단계 S2~S5 — 코드가 그리는 움직임 (원 작업지시서 Phase 11 · Phase 12).

2026-10-05 조사: 영상에서 움직이는 것은 유료 생성 클립과 스틸 위 켄번스뿐이었고, 코드가 그리는 화면
글자는 전부 정지였다. 원안 Phase 11 의 우선순위("① 코드가 그리는 움직임 ② 정지 그림 + 합성 ③ 생성
영상")대로, 돈이 들지 않는 층부터 움직이게 한다.

  S2  화면 글자 등장 — 페이드 · 살짝 커지며 나타나기(pop) · 화살표 그려지기 · 전후 캡션 차례로
  S3  숫자 카운트업 — 화면 숫자 카드의 숫자가 0 에서 올라간다(설명판형 `board_motion` 이징 재사용)
  S4  장면 동작 → 스틸 컷 카메라(밀어 들어가기·빠져나오기·따라가기) + 드러내기 막 걷힘(+흐름 화살표, 기본 꺼짐)
  S5  실적/전망 · 관측/모델/가설 구분 — 숫자 카드에 이름표와 다른 상자 모양

★ 전부 ASS 태그·ffmpeg 필터다. 그림을 새로 사지 않고, 글자를 그림에 굽지 않으므로 언어별로 나간다.
★ 순수 모듈: 파일·네트워크·ffmpeg 를 모른다. 문자열과 시각만 만든다(단위 테스트로 고정).
"""

from __future__ import annotations

import re
from typing import Any

from . import board_motion, config, spoken_numbers

Cue = tuple[float, float, str, str]

# ─────────────────────────────────────────────────────────────
# S2 — 화면 글자 등장 움직임
# ─────────────────────────────────────────────────────────────
_POP_STYLES = {"Keyword", "ScreenFact", "ScreenFactEstimate", "NumberPunch"}
_FADE_STYLES = {"Evidence", "Caveat", "Legend", "LabelTop", "LabelBottom"}


def _fade() -> str:
    return rf"\fad({config.OVERLAY_FADE_IN_MS},{config.OVERLAY_FADE_OUT_MS})"


def _pop() -> str:
    s = config.OVERLAY_POP_START_PCT
    return rf"\fscx{s}\fscy{s}\t(0,{config.OVERLAY_POP_MS},\fscx100\fscy100)"


def entrance_tags(style: str) -> str:
    """스타일별 등장 태그 블록. 움직임이 꺼져 있거나 모르는 스타일이면 빈 문자열."""
    if not config.OVERLAY_MOTION_ENABLED:
        return ""
    if style in _POP_STYLES:
        return "{" + _fade() + _pop() + "}"
    if style == "Pointer":
        # 앵커가 꼬리 쪽(\an7)이라 가로 배율 0 → 100 이 곧 "꼬리에서 촉으로 그려진다".
        return "{" + _fade() + rf"\fscx0\t(0,{config.OVERLAY_POINTER_DRAW_MS},\fscx100)" + "}"
    if style in _FADE_STYLES:
        return "{" + _fade() + "}"
    return ""


def has_entrance(text: str) -> bool:
    """이미 등장 처리가 된 큐인가 — 페이드 태그, 또는 카운트업 프레임의 직접 계산한 불투명도."""
    head = text.split("}", 1)[0] if text.startswith("{") else ""
    return r"\fad(" in head or r"\alpha" in head


def strip_entrance(text: str) -> str:
    """등장 태그 블록을 뗀 문구(검사·비교용)."""
    return text.split("}", 1)[1] if has_entrance(text) else text


def animate(cues: list[Cue]) -> list[Cue]:
    """큐마다 등장 움직임을 붙이고, 전후 캡션은 아래(후)를 조금 늦게 띄운다.

    이미 자기 등장 태그가 있는 큐(카운트업 프레임 등)는 건드리지 않는다.
    """
    if not config.OVERLAY_MOTION_ENABLED:
        return list(cues)
    out: list[Cue] = []
    for start, end, text, style in cues:
        if style == "LabelBottom":
            later = start + config.OVERLAY_LABEL_STAGGER_SEC
            if end - later >= config.OVERLAY_MIN_SEC:   # 늦춰도 읽을 시간이 남을 때만
                start = later
        if not has_entrance(text):
            text = entrance_tags(style) + text
        out.append((start, end, text, style))
    return out


# ─────────────────────────────────────────────────────────────
# S3 — 숫자 카운트업
# ─────────────────────────────────────────────────────────────
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _format_like(value: float, sample: str) -> str:
    """sample 과 같은 모양(소수 자릿수·천 단위 쉼표)으로 value 를 적는다."""
    decimals = len(sample.rsplit(".", 1)[1]) if "." in sample else 0
    text = f"{value:,.{decimals}f}" if "," in sample else f"{value:.{decimals}f}"
    return text


def _parse(sample: str) -> float | None:
    try:
        return float(sample.replace(",", ""))
    except ValueError:
        return None


def number_positions(text: str) -> list[tuple[int, int, float, str]]:
    """올라갈 숫자의 (시작, 끝, 값, 원문) — 값 숫자만(시점 3Q26E·이름 HBM4 는 그대로 둔다)."""
    out: list[tuple[int, int, float, str]] = []
    for start, end, _ in spoken_numbers.value_spans(text):
        for m in _NUMBER.finditer(text, start, end):
            value = _parse(m.group(0))
            if value is not None:
                out.append((m.start(), m.end(), value, m.group(0)))
    return out


def counted_text(text: str, p: float) -> str:
    """진행도 p(0~1)에서의 문구. 숫자만 바뀌고 나머지 글자는 그대로다."""
    positions = number_positions(text)
    if not positions:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end, value, sample in positions:
        parts.append(text[cursor:start])
        parts.append(_format_like(board_motion.count_up(value, p), sample))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _alpha(p: float) -> str:
    """불투명도 p(0 투명 ~ 1 불투명) → ASS \alpha (00 불투명 ~ FF 투명)."""
    return f"&H{int(round(255 * (1 - min(1.0, max(0.0, p))))):02X}&"


def count_up_cues(start: float, end: float, text: str, style: str,
                  prefix: str = "") -> list[Cue]:
    """숫자 카드 한 장 → 프레임별 큐 + 마지막 고정 큐.

    자막 이벤트 하나가 한 프레임이다. 짧은 이벤트에는 `\fad` 가 제대로 안 먹으므로 페이드·커지기를
    프레임마다 직접 계산해 적는다. prefix 는 숫자가 아닌 앞머리(S5 이름표)로, 처음부터 그대로 보인다.
    """
    fps = max(1, int(config.OVERLAY_COUNT_UP_FPS))
    frames = max(1, int(round(config.OVERLAY_COUNT_UP_SEC * fps)))
    final = prefix + text
    if (not config.OVERLAY_COUNT_UP_ENABLED or not number_positions(text)
            or end - start < frames / fps + config.OVERLAY_MIN_SEC * 0.5):
        return [(start, end, entrance_tags(style) + final, style)]
    fade_sec = config.OVERLAY_FADE_IN_MS / 1000.0
    pop_sec = config.OVERLAY_POP_MS / 1000.0
    s0 = config.OVERLAY_POP_START_PCT
    cues: list[Cue] = []
    for i in range(frames):
        t = i / fps
        scale = s0 + (100 - s0) * min(1.0, t / pop_sec) if pop_sec > 0 else 100
        alpha = _alpha(t / fade_sec if fade_sec > 0 else 1.0)
        tags = rf"{{\alpha{alpha}\fscx{scale:.0f}\fscy{scale:.0f}}}"
        cues.append((round(start + t, 3), round(start + (i + 1) / fps, 3),
                     tags + prefix + counted_text(text, i / frames), style))
    hold_start = round(start + frames / fps, 3)
    cues.append((hold_start, end, rf"{{\fad(0,{config.OVERLAY_FADE_OUT_MS})}}" + final, style))
    return cues


# ─────────────────────────────────────────────────────────────
# S5 — 실적/전망 · 관측/모델/가설
# ─────────────────────────────────────────────────────────────
_FORECAST_PERIOD = re.compile(r"\d\s*[QH]\s*\d{2}\s*[EF]|\d{2,4}\s*[EF](?![A-Za-z])")


def fact_kind(text: Any, domain: str) -> str:
    """숫자 카드 문장의 종류. 실적·관측(표시 없음)이면 빈 문자열.

    결정론적 낱말 규칙이다 — 문장에 "전망"·"3Q26E" 가 있으면 전망, "시뮬레이션" 이면 모델 추정.
    """
    body = str(text or "")
    lowered = body.lower()
    kinds = config.SCREEN_FACT_KINDS_BY_DOMAIN.get(domain, ())
    for kind in kinds:
        if any(term.lower() in lowered for term in config.SCREEN_FACT_KIND_TERMS.get(kind, ())):
            return kind
    if domain == "report" and _FORECAST_PERIOD.search(body):
        return "forecast"
    return ""


def badge_prefix(kind: str) -> str:
    """이름표 앞머리(강조색 글자 + 가운뎃점). 표시 없는 종류면 빈 문자열."""
    label = config.SCREEN_FACT_KIND_BADGE.get(kind, "")
    if not label:
        return ""
    accent, white = config.OVERLAY_ANNOTATION_COLOR_ASS, config.OVERLAY_KEYWORD_COLOR_ASS
    return "{\\c" + accent + "&}" + label + "{\\c" + white + "&} · "


def screen_fact_style(kind: str) -> str:
    """실적·관측 = 꽉 찬 상자(ScreenFact), 전망·추정·가설 = 속 빈 테두리 상자(ScreenFactEstimate)."""
    return "ScreenFactEstimate" if kind in config.SCREEN_FACT_KIND_BADGE else "ScreenFact"


def screen_fact_cues(start: float, end: float, text: str, kind: str = "") -> list[Cue]:
    """숫자 카드 한 장의 최종 큐들(S3 카운트업 + S5 표시)."""
    return count_up_cues(start, end, text, screen_fact_style(kind), prefix=badge_prefix(kind))


# ─────────────────────────────────────────────────────────────
# S4 — 장면 동작 → 실제 움직임
# ─────────────────────────────────────────────────────────────
def stage_effect(stage: dict[str, Any] | None) -> str:
    """stage 의 카메라 동작이 먼저, 없으면 물체 동작으로 스틸 컷의 카메라 움직임을 고른다. 없으면 ""."""
    if not config.STAGE_MOTION_ENABLED or not isinstance(stage, dict):
        return ""
    camera = str(stage.get("camera_operation") or "").upper()
    if camera in config.STAGE_CAMERA_EFFECT:
        return config.STAGE_CAMERA_EFFECT[camera]
    return config.STAGE_OPERATION_EFFECT.get(str(stage.get("operation") or "").upper(), "")


def _ease_out_accel() -> str:
    return "0.5"           # \t 가속 계수 < 1 → 빨리 시작해 부드럽게 멈춘다(ease-out)


def flow_arrow_ass(top: int, height: int) -> str:
    r"""왼쪽 → 오른쪽 흐름 화살표가 그려진다(사각 clip 이 넓어지며 드러난다)."""
    w = config.RENDER_WIDTH
    margin = config.OVERLAY_SIDE_MARGIN_PX
    y = int(top + height * config.STAGE_FLOW_ARROW_Y_FRAC)
    half = config.STAGE_FLOW_ARROW_THICK_PX // 2
    head = config.STAGE_FLOW_ARROW_THICK_PX * 2
    x0, x1 = margin, w - margin
    shape = (f"m {x0} {y - half} l {x1 - head} {y - half} l {x1 - head} {y - head} l {x1} {y} "
             f"l {x1 - head} {y + head} l {x1 - head} {y + half} l {x0} {y + half}")
    ms = int(config.STAGE_FLOW_ARROW_DRAW_SEC * 1000)
    clip0 = rf"\clip({x0},{y - head},{x0},{y + head})"
    clip1 = rf"\clip({x0},{y - head},{x1},{y + head})"
    return (rf"{{\an7\pos(0,0)\fad(0,{config.OVERLAY_FADE_OUT_MS}){clip0}"
            rf"\t(0,{ms},{_ease_out_accel()},{clip1})\p1}}{shape}{{\p0}}")


def reveal_wipe_ass(top: int, height: int) -> str:
    r"""어두운 막이 왼쪽부터 걷히며 장면이 드러난다(마스크 와이프)."""
    w = config.RENDER_WIDTH
    shape = f"m 0 {top} l {w} {top} l {w} {top + height} l 0 {top + height}"
    ms = int(config.STAGE_REVEAL_WIPE_SEC * 1000)
    return (rf"{{\an7\pos(0,0)\1c&H000000&\1a{config.STAGE_REVEAL_WIPE_ALPHA}"
            rf"\clip(0,{top},{w},{top + height})"
            rf"\t(0,{ms},{_ease_out_accel()},\clip({w},{top},{w},{top + height}))\p1}}{shape}{{\p0}}")


STAGE_LAYER_STYLE = "StageMotion"


def stage_motion_cues(cuts: list[dict[str, Any]], starts: list[float], durations: list[float],
                      stage_of: dict[int, dict[str, Any]], band: tuple[int, int, int]) -> list[Cue]:
    """스틸 컷의 장면 동작 → 화면 위 움직임 큐(드러내기 막 · 흐름 화살표).

    생성 영상 컷(motion_source=video)은 이미 움직이므로 건드리지 않는다. 한 stage 가 여러 컷을 맡으면
    **첫 컷에만** 붙인다 — 같은 막이 컷마다 다시 걷히면 장면이 새로 시작하는 것처럼 보인다.
    """
    _, top, height = band
    seen: set[str] = set()
    out: list[Cue] = []
    for i, cut in enumerate(cuts):
        if i >= len(starts) or i >= len(durations):
            break
        if str(cut.get("motion_source") or "") == "video":
            continue
        stage = stage_of.get(int(cut.get("cut_no") or (i + 1)))
        if not stage:
            continue
        sid = str(stage.get("stage_id") or "")
        if sid in seen:
            continue
        seen.add(sid)
        op = str(stage.get("operation") or "").upper()
        start, end = starts[i], starts[i] + durations[i]
        if config.STAGE_REVEAL_WIPE_ENABLED and op in config.STAGE_REVEAL_WIPE_OPERATIONS:
            out.append((start, min(end, start + config.STAGE_REVEAL_WIPE_SEC + 0.1),
                        reveal_wipe_ass(top, height), STAGE_LAYER_STYLE))
        if config.STAGE_FLOW_ARROW_ENABLED and op in config.STAGE_FLOW_ARROW_OPERATIONS:
            out.append((start, end, flow_arrow_ass(top, height), STAGE_LAYER_STYLE))
    return out
