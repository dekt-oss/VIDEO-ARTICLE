"""근거 오버레이 — 말하지 않고 화면으로 증명하는 레이어 (수정명세 §11 / M-E3).

명세의 핵심 주장은 "모든 근거를 말하지 말고 나머지는 화면으로 증명하라"인데, 이 저장소에는
그 렌더 경로가 **없었다**. `overlay_plan` 이 미구현인 정도가 아니라 기존 `text_overlay:<문구>`
이펙트조차 `assemble.effect_filter` 가 켄번스/팬만 해석해 조용히 버려지고 있었다.

★ 판단: 새 렌더 바이너리는 필요 없다. `engine/subtitles.py:build_ass` 가 이미 이름 있는 Style
  여러 개 + 독립 Dialogue 이벤트를 지원하고, `Footer` 스타일이 "값이 있을 때만 정의 → 기존 출력
  바이트 불변"이라는 정확히 필요한 추가 패턴을 보여준다. ASS 는 언어별로 생성되므로 언어 독립
  에셋 불변식(I1)도 자동으로 지켜진다 — 이미지·영상에 글자를 굽지 않는다.

★ 순수 모듈: 파일·네트워크·ffmpeg 를 모른다. (컷, 시작시각) → ASS 이벤트 튜플만 만든다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from . import config
from .util import log

# 오버레이 유형 → ASS 스타일 이름. 스타일 정의는 subtitles.build_ass 가 만든다.
_STYLE_BY_TYPE: dict[str, str] = {
    "source_card": "Evidence",
    "evidence_card": "Evidence",
    "scope_tag": "Evidence",
    "number_punch": "NumberPunch",
    "caveat_tag": "Caveat",
    # ★ 2026-09-18 기전 교육력(연구 T3). label_pair 는 위·아래 두 이벤트로 갈라지므로
    #   build_overlay_cues 가 따로 다룬다(LabelTop / LabelBottom).
    "legend": "Legend",
    "keyword": "Keyword",
    "pointer": "Pointer",
}
_DEFAULT_STYLE = "Evidence"
_LABEL_TOP_STYLE = "LabelTop"
_LABEL_BOTTOM_STYLE = "LabelBottom"


#: 모델이 한글로 적은 색 이름 → 색 규약 키. 못 알아들으면 흰 네모가 나가는데, 화면의 뇌는
#  파란데 범례는 흰색이면 **범례가 거짓말을 한다**(2026-09-18 재리뷰).
_COLOR_SYNONYM: dict[str, str] = {
    "파랑": "blue", "파란색": "blue", "파란": "blue", "블루": "blue", "청색": "blue",
    "산호": "coral", "산호색": "coral", "코랄": "coral", "주황": "coral", "주황색": "coral",
    "빨강": "coral", "붉은색": "coral", "분홍": "coral",
    "앰버": "amber", "호박": "amber", "호박색": "amber", "노랑": "amber", "노란색": "amber",
    "황색": "amber", "amber": "amber", "orange": "coral", "red": "coral", "yellow": "amber",
}


def _color_key(v: Any) -> str:
    color = str(v or "").strip().lower()
    color = _COLOR_SYNONYM.get(color, color)
    return color if color in config.LEGEND_COLORS_ASS else "white"


def _legend_items(item: dict[str, Any]) -> list[dict[str, str]]:
    """legend 의 항목 [{color, label}]. payload.items 가 정본이고, 없으면 text 를
    'amber=손상 뉴런 / blue=정상 뉴런' 꼴로 읽는다(모델이 payload 를 빼먹어도 살린다)."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    raw = payload.get("items") if isinstance(payload.get("items"), list) else None
    out: list[dict[str, str]] = []
    if raw:
        for it in raw:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label") or "").strip()
            if label:
                out.append({"color": _color_key(it.get("color")), "label": label})
    else:
        for piece in re.split(r"\s*[/|·]\s*", str(item.get("text") or "")):
            color, sep, label = piece.replace(":", "=", 1).partition("=")
            if sep and label.strip():
                out.append({"color": _color_key(color), "label": label.strip()})
    return out[:4]


#: 구역 → (가로 비율, 세로 비율, 화살표가 도는 각도). ASS \frz 는 **반시계** 양수이고 화면 y 는
#  아래로 간다 — 그래서 오른쪽=0, 위=90, 왼쪽=180, 아래=270 이다.
_POINTER_ZONE: dict[str, tuple[float, float, int]] = {
    "left":         (0.30, 0.50,   0),   # 왼쪽 밖에서 들어와 오른쪽을 가리킨다
    "right":        (0.70, 0.50, 180),
    "center":       (0.50, 0.50,   0),
    "top":          (0.50, 0.28, 270),   # 위에서 내려와 아래를 가리킨다
    "bottom":       (0.50, 0.72,  90),
    "top_left":     (0.30, 0.28, 315),
    "top_right":    (0.70, 0.28, 225),
    "bottom_left":  (0.30, 0.72,  45),
    "bottom_right": (0.70, 0.72, 135),
}


def _pointer_zones(item: dict[str, Any]) -> list[str]:
    """이 화살표 오버레이가 가리킬 구역들. payload.at 가 정본이고 text 로도 받는다."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    raw = payload.get("at", payload.get("zone"))
    if raw is None:
        raw = item.get("text")
    vals = raw if isinstance(raw, list) else re.split(r"[,\s]+", str(raw or ""))
    out: list[str] = []
    for v in vals:
        z = str(v).strip().lower()
        if z in _POINTER_ZONE and z not in out:
            out.append(z)
    return out[:config.OVERLAY_POINTER_MAX_PER_CUT]


def content_band() -> tuple[int, int, int]:
    """화살표가 놓일 영역 (왼쪽 x, 위 y, 높이). 레터박스면 중앙 밴드, 아니면 전체 프레임.

    ★ 상하 바 위에 화살표를 그리면 검은 띠를 가리킨다 — 밴드 안에서만 논다.
    """
    if config.LAYOUT_MODE == "center_band":
        return 0, config.LETTERBOX_TOP_PX, config.LETTERBOX_CONTENT_HEIGHT
    return 0, 0, config.RENDER_HEIGHT


#: 구역 → 그림에서 살펴볼 영역 (가로 시작, 가로 끝, 세로 시작, 세로 끝) 비율.
_ZONE_BOX: dict[str, tuple[float, float, float, float]] = {
    "left":         (0.00, 0.50, 0.00, 1.00),
    "right":        (0.50, 1.00, 0.00, 1.00),
    "center":       (0.25, 0.75, 0.00, 1.00),
    "top":          (0.00, 1.00, 0.00, 0.50),
    "bottom":       (0.00, 1.00, 0.50, 1.00),
    "top_left":     (0.00, 0.50, 0.00, 0.55),
    "top_right":    (0.50, 1.00, 0.00, 0.55),
    "bottom_left":  (0.00, 0.50, 0.45, 1.00),
    "bottom_right": (0.50, 1.00, 0.45, 1.00),
}


def _edge_centroid(path: str, zone: str) -> tuple[int, int] | None:
    """그림에서 **그 구역에 실제로 있는 물체**의 무게중심(최종 프레임 좌표). 못 찾으면 None.

    ★ 왜 필요한가(2026-09-18 실측): 구역 격자만 쓰면 화살표가 **빈 벽을 가리킨다.** 모델은
      "오른쪽 뇌"라는 뜻으로 `right` 를 적는데 격자는 화면 오른쪽 **한가운데**를 찍는다 —
      생성된 그림에서 뇌는 아래쪽에 앉아 있었고 화살표는 그 위 허공에 떴다.
      모델에게 좌표를 물을 수는 없다(자기 그림을 본 적이 없다). 그러면 **코드가 그림을 보면 된다.**

    ★ 판정은 윤곽 에너지다 — 물체에는 경계가 있고 빈 배경에는 없다. 밝기 임계값을 쓰면
      밝은 배경/어두운 배경 중 한쪽에서 뒤집힌다(우리 화풍은 둘 다 쓴다).
    """
    try:
        from PIL import Image, ImageFilter  # noqa: PLC0415 — 지연 import
    except Exception:  # noqa: BLE001 — Pillow 가 없으면 격자 기본값으로 간다
        return None
    w, h = config.RENDER_WIDTH, (config.LETTERBOX_CONTENT_HEIGHT
                                 if config.LAYOUT_MODE == "center_band" else config.RENDER_HEIGHT)
    try:
        img = Image.open(path).convert("L")
        # 렌더와 **같은 방식**으로 잘라야 좌표가 맞는다(cover-crop, assemble.effect_filter 와 동일).
        scale = max(w / img.width, h / img.height)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
        left, top = (img.width - w) // 2, (img.height - h) // 2
        img = img.crop((left, top, left + w, top + h))
        small = img.resize((160, max(1, round(160 * h / w))))
        edges = small.filter(ImageFilter.FIND_EDGES)
    except Exception as exc:  # noqa: BLE001 — 그림을 못 읽으면 격자로
        log.warning("화살표 대상 탐색 실패(격자 기본값 사용): %s", str(exc)[:120])
        return None
    x0, x1, y0, y1 = _ZONE_BOX.get(zone, (0.0, 1.0, 0.0, 1.0))
    sw, sh = small.size
    px = edges.load()
    total = sx = sy = 0
    for yy in range(int(sh * y0), int(sh * y1)):
        for xx in range(int(sw * x0), int(sw * x1)):
            v = px[xx, yy]
            if v > config.OVERLAY_POINTER_EDGE_THRESHOLD:
                total += v
                sx += xx * v
                sy += yy * v
    if total <= 0:
        return None
    cx, cy = sx / total / sw, sy / total / sh
    band_top = config.LETTERBOX_TOP_PX if config.LAYOUT_MODE == "center_band" else 0
    return int(cx * w), int(band_top + cy * h)


def pointer_ass_text(zone: str, image_path: str = "") -> str:
    r"""구역 하나 → ASS 도형 화살표 한 개.

    ★ 회전 중심을 **화살촉**에 못박는다(`\org`). 안 그러면 각도마다 촉이 딴 데로 간다 —
      libass 는 도형을 글리프처럼 다루고 기본 회전 중심이 위치 앵커이기 때문이다.
    """
    fx, fy, deg = _POINTER_ZONE[zone]
    _, top, height = content_band()
    length, half = config.OVERLAY_POINTER_LENGTH_PX, config.OVERLAY_POINTER_HALF_HEIGHT_PX
    rad = math.radians(deg)
    tip_x = float(config.RENDER_WIDTH * fx)
    tip_y = float(top + height * fy)
    # ★ 그림이 있으면 **격자가 아니라 물체**를 가리킨다(위 _edge_centroid 주석).
    found = _edge_centroid(image_path, zone) if image_path else None
    if found:
        # 촉이 물체 한가운데를 덮지 않게 들어오는 쪽으로 조금 물린다.
        back = config.OVERLAY_POINTER_TIP_BACKOFF_PX
        tip_x = found[0] - back * math.cos(rad)
        tip_y = found[1] + back * math.sin(rad)
    # ★★ 화살표 **전체**가 화면 안에 있어야 한다(2026-09-18 실측: 꼬리가 오른쪽 밖으로 잘렸다).
    #   촉만 클램프하면 꼬리가 나간다 — 꼬리 좌표까지 구해 둘 다 들어오도록 통째로 민다.
    tail_x, tail_y = tip_x - length * math.cos(rad), tip_y + length * math.sin(rad)
    m = config.OVERLAY_POINTER_EDGE_MARGIN_PX
    dx = (max(0.0, m - min(tip_x, tail_x))
          - max(0.0, max(tip_x, tail_x) - (config.RENDER_WIDTH - m)))
    dy = (max(0.0, (top + m) - min(tip_y, tail_y))
          - max(0.0, max(tip_y, tail_y) - (top + height - m)))
    tip_x, tip_y = int(tip_x + dx), int(tip_y + dy)
    # 촉이 (length, half) 에 오도록 그린다 → 좌상단 앵커(\an7)로 놓고 촉을 목표에 맞춘다.
    barb, shaft = int(length * 0.4), int(half * 0.35)
    shape = (f"m {length} {half} l {barb} 0 l {barb} {half - shaft} l 0 {half - shaft} "
             f"l 0 {half + shaft} l {barb} {half + shaft} l {barb} {half * 2}")
    return (rf"{{\an7\pos({tip_x - length},{tip_y - half})\org({tip_x},{tip_y})"
            rf"\frz{deg}\p1}}{shape}{{\p0}}")


def _label_pair(item: dict[str, Any]) -> tuple[str, str]:
    """label_pair 의 (위, 아래). payload.top/bottom 이 정본, 없으면 text 를 '위 / 아래' 로 읽는다."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    top = str(payload.get("top") or "").strip()
    bottom = str(payload.get("bottom") or "").strip()
    if not (top or bottom):
        parts = [x.strip() for x in re.split(r"\s*[/|]\s*", str(item.get("text") or ""), maxsplit=1)]
        top = parts[0] if parts else ""
        bottom = parts[1] if len(parts) > 1 else ""
    return top, bottom


def legend_ass_text(items: list[dict[str, str]]) -> str:
    r"""범례 → ASS 한 줄(줄바꿈 \N). 색 견본은 ■ 글리프에 인라인 색 오버라이드({\c&H..&}) —
    도형 그리기 없이 자막 레이어만으로 색 범례가 된다."""
    white = config.LEGEND_COLORS_ASS["white"]
    lines = []
    for it in items:
        color = config.LEGEND_COLORS_ASS.get(it.get("color", ""), white)
        lines.append("{\\c" + color + "&}■{\\c" + white + "&} " + str(it.get("label", "")))
    return "\\N".join(lines)


@dataclass(frozen=True)
class OverlayCue:
    """ASS 로 굽기 직전의 오버레이 1건. (start, end) 는 영상 전체 타임라인 기준."""

    start: float
    end: float
    text: str
    style: str

    def as_tuple(self) -> tuple[float, float, str, str]:
        return (self.start, self.end, self.text, self.style)


def sanitize_overlay_type(v: Any) -> str:
    tok = str(v or "").strip().lower()
    return tok if tok in config.OVERLAY_TYPES else "evidence_card"


def _payload_text(item: dict[str, Any]) -> str:
    """오버레이 표시 문구. `text` 가 있으면 그대로, 없으면 payload 를 사람이 읽는 한 줄로."""
    text = str(item.get("text") or "").strip()
    if text:
        return text
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return ""
    parts = [f"{k}: {v}" for k, v in payload.items() if str(v or "").strip()]
    return " · ".join(parts)


def normalize_overlay_plan(v: Any) -> list[dict[str, Any]]:
    """지시서 컷의 `overlay_plan` 정규화 (수정명세 §11-2).

    ★ 코드가 강제하는 것(§11-4): 유형 enum · 최소 노출 2초 · 컷당 최대 2개 ·
      한 화면 핵심 숫자 1개(number_punch 는 컷당 1건만 살린다).
    """
    items = v if isinstance(v, list) else []
    out: list[dict[str, Any]] = []
    number_used = False
    # ★ 구조형(범례·전후 캡션)은 **컷당 상한을 따로 센다**(2026-09-18 재리뷰). 상한의 뜻은
    #   "한 화면에 읽을 카드는 핵심 1 + 보조 1"인데, 범례는 좌하단·캡션은 분할선 옆이라 그
    #   카드들과 자리를 다투지 않는다. 같이 세면 수치 카드 두 장이 슬롯을 먹고 범례가 조용히
    #   잘린다 — 게다가 지금은 수치 카드가 **화면에 나가지도 않는다**(EVIDENCE_OVERLAY_ENABLED).
    plain_used = 0
    structured_used: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        otype = sanitize_overlay_type(item.get("type"))
        # ★ 구조형(legend / label_pair)은 payload 가 정본이다. text 는 사람이 읽는 요약으로
        #   같이 만들어 둔다(화면 목록·옛 경로가 text 만 보므로).
        structured: dict[str, Any] | None = None
        if otype == "legend":
            legend = _legend_items(item)
            if not legend:
                continue
            structured = {"items": legend}
            text = " / ".join(f"{it['color']}={it['label']}" for it in legend)
        elif otype == "pointer":
            zones = _pointer_zones(item)
            if not zones:
                continue
            structured = {"zones": zones}
            text = " · ".join(zones)
        elif otype == "keyword":
            # 낱말 카드는 payload 가 없다 — 글자 그대로다. 줄바꿈만 없앤다(한 줄 카드).
            text = " ".join(str(item.get("text") or "").split())
        elif otype == "label_pair":
            top, bottom = _label_pair(item)
            if not (top and bottom):
                continue
            structured = {"top": top, "bottom": bottom}
            text = f"{top} / {bottom}"
        else:
            text = _payload_text(item)
        if not text:
            continue
        if otype == "number_punch":
            if number_used:
                # §11-4 한 화면에 핵심 숫자는 1개. 두 번째부터는 보조 카드로 강등한다.
                otype = "evidence_card"
            else:
                number_used = True
        try:
            start = max(0.0, float(item.get("start_sec") or 0.0))
        except (TypeError, ValueError):
            start = 0.0
        try:
            dur = float(item.get("duration_sec") or config.OVERLAY_MIN_SEC)
        except (TypeError, ValueError):
            dur = config.OVERLAY_MIN_SEC
        claim_ids = item.get("claim_ids") or []
        if isinstance(claim_ids, str):
            claim_ids = [claim_ids]
        if otype in config.OVERLAY_ANNOTATION_TYPES:
            if otype in structured_used:
                continue
            structured_used.add(otype)
        else:
            if plain_used >= config.OVERLAY_MAX_PER_CUT:
                continue
            plain_used += 1
        out.append({
            "type": otype,
            "text": text,
            **({"payload": structured} if structured else {}),
            "claim_ids": [str(c).strip() for c in claim_ids if str(c).strip()],
            "start_sec": start,
            # 2초 미만으로 지나가는 카드는 읽히지 않는다 — 최소 노출을 코드가 보장한다.
            "duration_sec": max(config.OVERLAY_MIN_SEC, dur),
            "priority": (str(item.get("priority") or "").strip().lower()
                         if str(item.get("priority") or "").strip().lower()
                         in config.OVERLAY_PRIORITIES else config.DEFAULT_OVERLAY_PRIORITY),
        })
    return out


def _legacy_text_overlays(cut: dict[str, Any]) -> list[dict[str, Any]]:
    """`effects` 의 `text_overlay:<문구>` 토큰을 오버레이로 승계한다.

    이 토큰은 지금까지 정규화는 통과하지만 렌더에서 버려졌다. 지시서 프롬프트가 "세부 수치는
    text_overlay 가 담당"이라고 시켜 왔으므로, 그 지시를 이제야 실제로 이행하는 셈이다.
    """
    out: list[dict[str, Any]] = []
    for eff in (cut.get("effects") or []):
        tok = str(eff)
        if not tok.startswith("text_overlay:"):
            continue
        text = tok.split(":", 1)[1].strip()
        if text:
            out.append({"type": "evidence_card", "text": text,
                        "start_sec": 0.0, "duration_sec": config.OVERLAY_MIN_SEC})
    return out


def build_overlay_cues(
    cuts: list[dict[str, Any]], starts: list[float], durations: list[float],
    skip_cut_nos: set[Any] | None = None,
    only_types: set[str] | None = None,
    images: dict[Any, str] | None = None,
    drop_types: set[str] | None = None,
) -> list[tuple[float, float, str, str]]:
    """컷별 overlay_plan → 영상 전체 타임라인의 ASS 이벤트.

    drop_types: 이 유형은 내보내지 않는다. **거짓이 될 카드를 지우는 자리**다 —
      색 코드가 어긋난 지시서에서 범례를 그리면 화면이 거짓말을 한다(2026-09-19).
    images: 컷 번호 → 그 컷의 그림 경로. 주면 화살표가 **격자가 아니라 그림 속 물체**를 가리킨다.
    only_types: 이 유형만 내보낸다(None = 전부). 수치·출처 카드는 꺼 둔 채 범례·캡션만 그릴 때
      쓴다(config.MECHANISM_LABEL_OVERLAYS_ENABLED, 2026-09-18).

    `starts[i]`·`durations[i]` 는 렌더가 실측한 컷 시작시각·화면시간이다(나레이션 실측 기준).
    오버레이는 자기 컷 밖으로 나가지 않도록 컷 끝에서 잘린다 — 다음 컷 화면에 남으면 근거가
    엉뚱한 장면에 붙는다.

    skip_cut_nos: 이 컷들은 오버레이를 내보내지 않는다. 설명판형 코드 보드가 그 텍스트를 화면에
      **직접 그리기 때문**이다 — 둘 다 내면 같은 문장이 두 번 뜨고 자막 위에 겹친다(실측).
      기본 None = 기존 동작 그대로(논문 라인 출력 불변).
    """
    skip = skip_cut_nos or set()
    cues: list[tuple[float, float, str, str]] = []
    for i, cut in enumerate(cuts):
        if i >= len(starts) or i >= len(durations):
            break
        if cut.get("cut_no") in skip:
            continue
        plan = normalize_overlay_plan(cut.get("overlay_plan"))
        if not plan:
            plan = normalize_overlay_plan(_legacy_text_overlays(cut))
        cut_start, cut_dur = starts[i], durations[i]
        for item in plan:
            if only_types is not None and item["type"] not in only_types:
                continue
            if drop_types and item["type"] in drop_types:
                continue
            start = cut_start + min(item["start_sec"], max(0.0, cut_dur - 0.1))
            end = min(cut_start + cut_dur, start + item["duration_sec"])
            if end - start <= 0:
                continue
            if item["type"] == "label_pair":
                pair = item.get("payload") or {}
                cues.append((start, end, str(pair.get("top") or ""), _LABEL_TOP_STYLE))
                cues.append((start, end, str(pair.get("bottom") or ""), _LABEL_BOTTOM_STYLE))
                continue
            if item["type"] == "pointer":
                img = (images or {}).get(cut.get("cut_no"), "")
                for zone in (item.get("payload") or {}).get("zones") or []:
                    cues.append((start, end, pointer_ass_text(zone, img),
                                 _STYLE_BY_TYPE["pointer"]))
                continue
            if item["type"] == "legend":
                cues.append((start, end, legend_ass_text((item.get("payload") or {}).get("items") or []),
                             _STYLE_BY_TYPE["legend"]))
                continue
            cues.append((start, end, item["text"],
                         _STYLE_BY_TYPE.get(item["type"], _DEFAULT_STYLE)))
    return cues


def overlay_warnings(cuts: list[dict[str, Any]]) -> list[str]:
    """승인 화면용 경고 — 화면으로 증명하라고 했는데 카드가 하나도 없는 근거 컷 등."""
    out: list[str] = []
    for cut in cuts:
        plan = cut.get("overlay_plan")
        if isinstance(plan, list) and len(plan) > config.OVERLAY_MAX_PER_CUT:
            out.append(f"too_many_overlays#{cut.get('cut_no')}")
    return out


def cue_visibility_warnings(
    cues: list[tuple[float, float, str, str]],
    min_sec: float | None = None,
) -> list[str]:
    """Q4 출처 가시성(§9) — **실제로 화면에 떠 있던 시간**이 계약보다 짧은 큐.

    ★★ 무엇이 비어 있었나(2026-09-03): `OVERLAY_MIN_SEC`(2.0초, §11-4 "2초 미만으로
      지나가는 복잡한 카드 금지")를 `normalize_overlay_plan` 이 **선언 단계에서** 강제한다
      (`max(config.OVERLAY_MIN_SEC, dur)`). 그런데 `build_overlay_cues` 가 큐를 컷 경계에서
      **잘라낸다**:

          end = min(cut_start + cut_dur, start + item["duration_sec"])

      즉 컷 끝에 붙은 출처 카드는 0.1초까지 줄어들 수 있고, 유일한 방어가
      `if end - start <= 0: continue` 였다. **계약을 선언한 곳과 어기는 곳이 달라서**
      아무도 몰랐다 — 이 저장소가 반복해 겪은 "만들어 놓고 한쪽만 연결"이다.

    ★ 판정이 아니라 **경고**다. 컷이 짧아서 잘린 것은 대본·타이밍 문제라 렌더를 죽여서
      풀리지 않는다. 운영자가 ⑥ 화면에서 보고 대본을 줄이거나 컷을 늘린다.

    ★ 출처(Evidence 스타일)를 먼저 적는다 — 귀속이 안 읽히면 근거 없는 화면이 된다.
    """
    floor = config.OVERLAY_MIN_SEC if min_sec is None else float(min_sec)
    out: list[str] = []
    for start, end, text, style in cues or []:
        shown = float(end) - float(start)
        if shown + 1e-6 >= floor:
            continue
        label = (text or "").strip().replace("\n", " ")[:18]
        out.append(f"overlay_too_brief:{style}:{shown:.1f}s<{floor:.1f}s:'{label}'")
    # 출처가 먼저 보이게 정렬한다(사유가 많을 때 잘려도 중요한 것이 남는다).
    out.sort(key=lambda r: (0 if ":Evidence:" in r else 1, r))
    return out
