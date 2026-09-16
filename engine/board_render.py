"""설명판 코드 렌더 — 화면의 숫자·차트를 **코드가 그린다** (명세 v3.4 §9·§20·§21·§22).

왜 이 모듈이 생겼는가 — 실측된 사고 두 건:

  ① (v3.3) 이미지 생성 모델이 **가짜 대시보드**를 그렸다. 화면에 243.5%·45.4%·27.5% 가 근거
     없이 박혔고, 정작 나레이션이 말한 리포트 수치는 화면에 없었다. 시청자는 그 픽셀을 리포트
     데이터로 읽는다 — 품질 문제가 아니라 컴플라이언스 사고다.
     → 숫자·차트·축·범례는 전부 여기서 그린다. 생성 이미지는 맥락 배경으로만 남는다.

  ② (v3.4 검수) 그 코드 렌더가 **정지 PNG 를 툭툭 바꾸는 슬라이드쇼**였다. 명세 §5-2 가 정면
     으로 금지한 "정적 텍스트가 주인공인 화면"이 그대로 나갔다. 스와이프 판단이 일어나는 첫
     1~2초에 화면에서 움직이는 것이 하나도 없었다. 운영자 평: "존나 허접해."
     → 이제 보드는 **30fps 프레임 시퀀스**다. 축이 그려지고 막대가 자라고 숫자가 올라간다.
       무엇이 언제 얼마나 진행됐는지는 board_motion.py 가 계산한다(순수).

★ 기술 선택 — PIL(Manim 아님):
  · Pillow 는 requirements.txt 상시, manim 은 libcairo/libpango 때문에 의도적으로 배제돼
    렌더 잡에서만 조건부 설치된다(과거 그 조건부 설치가 잘못 걸려 워커가 죽은 이력이 있다).
  · §20-3 은 좌표 판정이다. PIL 은 그 좌표로 바로 그리고, §20-7·§22-6 검사가 그린 이미지에서
    즉시 계산된다(mp4 디코드 0회).

★ 좌표·폰트·검증의 원본은 engine/visual_contract.py 다(§22-1 — 산문 명세와 충돌하면 모듈이
  이긴다). 이 파일은 그 API 만 쓰고 자체 좌표 로직을 두지 않는다.

★ 길이: 프레임 수를 나레이션 실측에 정확히 맞추면 clip_fit 이 ratio==0 → trim·fade 0 으로
  판정해 줌·페이드가 붙지 않는다 — 보드가 크롭에 잘리지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from . import animation_qa as aqa
from . import board_layout as bl
from . import component_registry as cr
from . import board_motion as bm
from . import config
from . import render_manifest as rm
from . import visual_contract as vc
from .board_layout import Box, Placement
from .util import log

# 보드가 소비하는 오버레이 유형 → 보드 안에서의 역할. ASS 로 또 내보내면 이중 인쇄가 된다.
_OVERLAY_ROLE = {
    "source_card": "source",
    "evidence_card": "body",
    "number_punch": "number",
    "caveat_tag": "caveat",
}

# v3.4 §22 K8 — 폰트 실패는 visual_contract.FontContractError 하나로 통일한다.
# 이 별칭은 기존 호출자(engine/render.py 의 폴백 차단 분기)를 위해 남긴다.
BoardFontError = vc.FontContractError


@dataclass
class BoardResult:
    """보드 1개의 렌더 결과. frame_paths 를 fps 로 이어 붙이면 컷 영상이 된다."""

    frame_paths: list[str]
    fps: int
    placements: list[Placement] = field(default_factory=list)
    layout_qa: dict[str, list[str]] = field(default_factory=dict)
    core_fill: float = 0.0
    # §22-6 완성 프레임 픽셀 판정(visual_contract.validate_frame) · K11 차트 스펙
    frame_qa: dict[str, list[str]] = field(default_factory=dict)
    chart_spec: dict[str, Any] = field(default_factory=dict)
    # §8-1 manifest 선언 ↔ 실제 대조. **기록 전용** — 판정을 바꾸지 않는다.
    manifest: dict[str, Any] = field(default_factory=dict)
    # §9 Q3 애니메이션 계약. animation 은 측정값(기록), animation_fail 은 사유 코드다.
    #   ★ layout_qa 안에 넣지 않는다 — 그쪽은 dict[str, list[str]] 계약이라 dict 를 끼우면
    #     값을 순회하는 소비자가 조용히 깨진다.
    animation: dict[str, Any] = field(default_factory=dict)
    animation_fail: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return len(self.frame_paths) / float(self.fps or config.EXPLAINER_MOTION_FPS)


# ─────────────────────────────────────────────────────────────
# 판정 — 이 컷을 코드 보드로 그릴 것인가 (순수)
# ─────────────────────────────────────────────────────────────
def code_render_board(cut: dict[str, Any], header: dict[str, Any]) -> str | None:
    """explainer 의 코드 렌더 보드면 보드 이름, 아니면 None.

    ★ 논문 라인은 version_type 이 explainer 가 아니라 여기서 즉시 None 이다 — 도달 불가.
    """
    if str((header or {}).get("version_type") or "") != "explainer":
        return None
    board = str((cut or {}).get("board") or "").strip().upper()
    return board if board in config.EXPLAINER_CODE_RENDER_BOARDS else None


# ─────────────────────────────────────────────────────────────
# 폰트 — §22 K8: 역할로만 요청한다. 파일 경로를 고르는 로직은 이 모듈에 없다.
#   전에는 시스템 폰트 후보를 훑어 존재하는 것을 조용히 썼고, 환경마다 다른 폰트로 렌더됐다.
# ─────────────────────────────────────────────────────────────
def _font(size: int, role: str = "body"):  # -> ImageFont.FreeTypeFont
    return vc.load_font(role, int(size))


def _role_font(key: str):
    """config.EXPLAINER_FONT_SIZES 의 키 → 역할에 맞는 폰트."""
    return vc.load_font(config.EXPLAINER_FONT_ROLES.get(key, "body"),
                        config.EXPLAINER_FONT_SIZES[key])


def _text_size(draw, text: str, font) -> tuple[int, int]:
    return vc.text_size(draw, text, font)


# ─────────────────────────────────────────────────────────────
# 지시서 → 보드가 그릴 내용 (순수)
# ─────────────────────────────────────────────────────────────
def board_payload(cut: dict[str, Any], header: dict[str, Any],
                  fact_sheet: dict[str, Any] | None, lang: str = "ko") -> dict[str, Any]:
    """컷 + 헤더 → 보드가 그릴 문자열들. **지시서에 있는 것만** 쓴다(지어내지 않는다).

    숫자는 header.explainer.number_claims 에서 가져온다 — 그 값들은 이미 Fact Sheet 근거로
    해소된 것만 남아 있다(engine/explainer.py). 화면 숫자의 출처가 원장인 셈이다.
    """
    exp = (header or {}).get("explainer") or {}
    claims = {c.get("claim_no"): c for c in (exp.get("number_claims") or [])}
    refs = [claims.get(r) for r in (cut.get("number_claim_refs") or [])]
    claim = next((c for c in refs if c), None)

    overlays: dict[str, list[str]] = {}
    for item in (cut.get("overlay_plan") or []):
        role = _OVERLAY_ROLE.get(str(item.get("type") or ""), "body")
        text = str(item.get("text") or "").strip()
        if text:
            overlays.setdefault(role, []).append(text)

    summary = exp.get("report_claim_summary") or {}
    watch = exp.get("watchpoint") or {}
    return {
        "board": str(cut.get("board") or ""),
        "kicker": summary.get("speaker") or "",
        "title": (overlays.get("body") or [""])[0],
        "number": f"{claim['value']}{claim['unit']}" if claim else "",
        "number_value": (claim or {}).get("value") or "",
        "number_unit": (claim or {}).get("unit") or "",
        "number_label": claim.get("label", "") if claim else "",
        "comparison": (f"{claim['comparison_basis']} {claim['comparison_value']}".strip()
                       if claim and claim.get("comparison_basis") else ""),
        "sowhat": (claim.get("why_significant") if claim else "") or summary.get("statement") or "",
        "source": (overlays.get("source") or [""])[0],
        "caveat": (overlays.get("caveat") or [""])[0],
        "watchpoint": watch.get("text") or "",
        "watch_metric": watch.get("metric") or "",
        "series": config.REPORT_SERIES_TITLE_BY_LANG.get(lang, config.REPORT_SERIES_TITLE),
    }


def _hex(c: str) -> tuple[int, int, int]:
    s = c.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a, b, p: float):
    """색 a → b 를 p(0~1) 만큼 섞는다. 페이드인을 알파 없이 처리한다(배경이 불투명하므로)."""
    p = min(1.0, max(0.0, p))
    return tuple(int(round(a[i] + (b[i] - a[i]) * p)) for i in range(3))


# ─────────────────────────────────────────────────────────────
# 배경 — §20-2 "맨 배경 금지" · §20-3 밀도 원칙 · §20-4 하단 감쇠
# ─────────────────────────────────────────────────────────────
def _draw_background(img, draw, tokens: dict[str, Any], bg_image: str | None) -> list[Placement]:
    """배경을 깐다. 단색 화면은 §20-2 위반이다.

    ★ 왜 이게 '허접함'의 핵심인가: v3.3 산출물은 전 화면이 #0B1220 단색이었고 CORE 밴드의
      비배경 픽셀이 5% 였다. 명세는 CORE 를 **70% 이상** 채우라고 못박았다(§20-3). 글자만으로는
      절대 안 된다 — 배경이 화면을 지탱해야 한다.
    ★ 차트 씬은 가독성 우선이라 실사 배경 대신 **그리드**를 쓴다(§20-2 3번째 항목).
    ★ DEAD_BOTTOM 은 아래로 갈수록 어둡게 감쇠시켜 유튜브 UI 와 섞는다(§20-4).
    """
    from PIL import Image, ImageEnhance

    W, H = config.RENDER_WIDTH, config.RENDER_HEIGHT
    out: list[Placement] = []

    if bg_image and os.path.exists(bg_image):
        # §20-2 딤 처리: 밝기 0.40~0.50 + 네이비 오버레이 α 165~185.
        # §20-4 커버 크롭 앵커는 중앙~상단 40% — 단순 center-crop 이면 피사체가 내려앉는다.
        src = Image.open(bg_image).convert("RGB")
        scale = max(W / src.width, H / src.height)
        rs = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))))
        left = max(0, (rs.width - W) // 2)
        top = max(0, int((rs.height - H) * 0.40))
        rs = rs.crop((left, top, left + W, top + H))
        rs = ImageEnhance.Brightness(rs).enhance(config.EXPLAINER_BG_DIM_BRIGHTNESS)
        img.paste(rs, (0, 0))
        navy = Image.new("RGBA", (W, H), tokens["bg"] + (config.EXPLAINER_BG_NAVY_ALPHA,))
        img.paste(navy, (0, 0), navy)
    else:
        # 그리드 배경. 선이 얇아 글자를 방해하지 않으면서 화면이 '판'으로 읽힌다.
        step = config.EXPLAINER_GRID_SPACING
        grid = _mix(tokens["bg"], tokens["fg"], 0.055)
        for x in range(0, W, step):
            draw.line([(x, 0), (x, H)], fill=grid, width=1)
        for y in range(0, H, step):
            draw.line([(0, y), (W, y)], fill=grid, width=1)

    # CORE 패널 — 밴드를 시각적으로 '설명판'으로 만든다. 요소가 적은 컷에서도 화면이 지탱된다.
    # ★ §20-3 "CORE 가 비면 요소를 키우거나 배경으로 채운다"의 배경 쪽 답이다. 이게 없으면
    #   CORE 비배경 픽셀이 5% 로 떨어져 화면이 검은 구멍으로 보인다(실측).
    # ★ 안전 가로폭(90~930)을 넘지 않는다. 배경이라도 넘기면 §20-3 판정이 fail 이고, 실제로
    #   처음 그렇게 짰다가 걸렸다 — 규칙을 약화시키는 대신 패널을 안으로 들였다.
    # ★ 패널은 CORE 밴드를 **정확히** 채운다. 처음엔 위아래로 16px 씩 넉넉히 그렸는데, 그
    #   16px 이 TITLE 밴드를 침범해 2줄짜리 제목의 아랫줄을 먹었다(실측). 밴드 판정은 텍스트
    #   박스만 보므로 통과했고, 프레임을 눈으로 봐야만 드러났다 — 그래서 아래 밴드 간 침범
    #   검사(board_layout.evaluate_layout)를 같이 넣었다.
    core = bl.band_box("CORE")
    draw.rectangle([core.x1, core.y1, core.x2, core.y2],
                   fill=_mix(tokens["bg"], tokens["fg"], 0.10))
    draw.rectangle([core.x1, core.y1, core.x2, core.y2],
                   outline=_mix(tokens["bg"], tokens["point"], 0.40), width=2)
    # 좌측 앰버 액센트 바 — 시선의 시작점을 만든다.
    draw.rectangle([core.x1, core.y1, core.x1 + 8, core.y2], fill=tokens["accent"])
    out.append(Placement(kind="panel", band="CORE",
                         box=Box(core.x1, core.y1, core.x2, core.y2)))

    # §20-4 DEAD_BOTTOM 그라디언트 감쇠 — 아래로 갈수록 어둡게 해 UI 와 섞는다.
    # ★ 단, 순수 검정까지 내리지 않는다. 내리면 §21 K3 레터박스 판정이 "하단 스트립 100% 검정"
    #   으로 걸린다 — 실제로 걸렸다. 우리가 지우려던 검은 바를 그라디언트로 다시 만든 셈이었다.
    top_y, bot_y = config.EXPLAINER_BANDS["DEAD_BOTTOM"]
    span = max(1, bot_y - top_y)
    floor = _mix(tokens["bg"], (0, 0, 0), 0.55)
    for i in range(0, span, 4):
        draw.rectangle([0, top_y + i, W, top_y + i + 4],
                       fill=_mix(tokens["bg"], floor, min(1.0, (i / span) * 1.4)))
    return out


# ─────────────────────────────────────────────────────────────
# 텍스트 — §22 K9: 말줄임 금지
# ─────────────────────────────────────────────────────────────
def _draw_text_in(draw, box: Box, text: str, size: int, color, *,
                  align: str = "left", valign: str = "top",
                  max_lines: int = 2, role: str = "body",
                  band: str = "", stage: int = 0, min_size: int = 28,
                  stroke: int = 0, grow_to: int = 0) -> Placement | None:
    """박스 안에 텍스트를 그리고 실제 차지한 영역을 Placement 로 돌려준다.

    ★ v3.4 §22 K9 — **말줄임(…)을 쓰지 않는다.** 줄바꿈·축소는 visual_contract.fit_text 가
      폰트 메트릭으로 하고(글자 수 근사로는 한글을 못 맞춘다 — 실측 x=930 → 1268px), 최소
      크기에서도 안 담기면 예외가 난다. 그 예외를 여기서 삼키면 K9 가 무력해지므로 위로 던진다.
      화면에서 정보를 조용히 지우는 대신 "대본 문장을 줄여라"는 신호로 되돌리는 것이 규범이다.
    ★ fit_text 는 가로만 본다. 세로로 넘치면 한 단계 더 줄이고, 그래도 안 되면 역시 예외.
    ★ stroke: §20-2 "배경 위 텍스트는 전부 스트로크(2~4px) 필수".
    ★ valign="center": 글자를 상자 **세로 중앙**에 놓는다. 기본이 top 인데, CORE 패널처럼
      상자가 내용보다 훨씬 큰 자리에서는 글자가 위에 붙고 아래 절반이 **빈 검은 상자**로
      남는다(실측: HOOK·MECHANISM 보드에서 패널 675px 중 아래 400px 이 통째로 비었다).
      중앙에 놓으면 같은 글자로 화면이 균형을 잡는다 — 정보를 늘리지 않고 허전함만 없앤다.
    """
    if not text:
        return None
    size = max(min_size, int(size))
    # ★ §20-3 "CORE 가 비면 요소를 키우거나 배경을 채운다"의 **요소** 쪽 답이다.
    #   지금까지는 줄이기만 했다 — 짧은 문장을 큰 패널에 넣으면 글자는 기준 크기 그대로고
    #   패널 아래가 통째로 비었다. grow_to 를 주면 상자에 담기는 한도까지 키운다.
    #   가로가 먼저 걸리면(fit_text 가 되돌려 줄이면) 거기서 멈춘다 — 억지로 키워 줄을
    #   늘리지 않는다.
    if grow_to > size:
        best = size
        cand = size + 4
        while cand <= grow_to:
            font_c, lines_c = vc.fit_text(draw, str(text), role, cand, box.w,
                                          max_lines=max_lines, min_size=min_size)
            if font_c.size < cand or len(lines_c) * int(font_c.size * 1.32) > box.h:
                break
            best, cand = cand, cand + 4
        size = best
    while True:
        font, lines = vc.fit_text(draw, str(text), role, size, box.w,
                                  max_lines=max_lines, min_size=min_size)
        line_h = int(font.size * 1.32)
        if len(lines) * line_h <= box.h or font.size <= min_size:
            break
        size = max(min_size, font.size - 4)
    line_h = int(font.size * 1.32)
    if len(lines) * line_h > box.h:
        raise ValueError(
            f"BOARD TEXT TOO TALL for band {band or '?'} "
            f"({len(lines)}줄 × {line_h}px > {box.h}px): {text!r}\n"
            f"→ 렌더에서 자르지 말고 대본을 줄일 것(§22 K9).")
    y = box.y1
    if valign == "center":
        y = box.y1 + max(0, (box.h - len(lines) * line_h) // 2)
    top_y = y
    widest = max(_text_size(draw, ln, font)[0] for ln in lines)
    sk = {"stroke_width": stroke, "stroke_fill": (6, 10, 18)} if stroke else {}
    for line in lines:
        w, _ = _text_size(draw, line, font)
        x = box.x1 if align == "left" else box.cx - w // 2
        x = max(box.x1, min(x, box.x2 - w))     # 중앙 정렬이라도 안전 영역을 벗어나지 않게
        draw.text((x, y), line, font=font, fill=color, **sk)
        y += line_h
    x1 = box.x1 if align == "left" else max(box.x1, box.cx - widest // 2)
    # ★ 박스 세로 시작은 box.y1 이 아니라 **실제로 그리기 시작한 y** 다. valign="center" 일 때
    #   box.y1 을 쓰면 글자가 없는 위쪽 여백까지 점유로 세어져 충전율이 부풀고, 좌측 액센트
    #   마커도 글자와 어긋난 자리에 붙는다(마커가 el.box.y1 을 기준으로 자란다).
    return Placement(kind="text", text=text, band=band, stage=stage,
                     box=Box(x1, top_y, min(box.x2, x1 + widest), y))


# ─────────────────────────────────────────────────────────────
# 차트 — §22 K11 최소 요건 + §9 성장 모션
# ─────────────────────────────────────────────────────────────
# 증감 배지가 상자 위에서 내려앉는 최종 오프셋(px). _draw_bars 의 dy 계산과 같은 값이다.
CHART_BADGE_TOP_OFFSET = 20
# 값 라벨이 막대 머리 위로 뜨는 거리(px).
CHART_VALUE_LABEL_LIFT = 56

# 막대 위에 비워 두는 높이(px). 값 라벨과 증감 배지가 **둘 다** 들어가야 한다.
# ★ 예전엔 74px 이었다. 막대가 가장 높은 계열에서 값 라벨이 배지 자리까지 올라와
#   **"43%" 위에 "+4%" 가 겹쳐 찍혔다**(실측 — CHART_BOARD). 판정기는 둘 다 draw.text 로
#   직접 그려 Placement 를 안 남기므로 원리적으로 못 잡는다 — 눈으로 봐야 드러났다.
# ★★ 처음엔 132 로 고쳤는데, 전 구간을 계산해 보니 최악 간격이 **1px** 이었다. 배지가
#    상자 맨 위가 아니라 20px 내려온 자리에 앉는다는 것을 빼먹었기 때문이다. 1px 은
#    폰트가 바뀌거나 숫자가 길어지면 바로 겹친다 — 고친 게 아니라 겨우 비켜 간 것이다.
#    계산: 배지오프셋 20 + 배지높이(label 폰트 1줄) + 여백 24 + 값라벨 뜨는 거리 56.
CHART_TOP_RESERVE = (CHART_BADGE_TOP_OFFSET
                     + int(config.EXPLAINER_FONT_SIZES["label"] * 1.32)
                     + 24 + CHART_VALUE_LABEL_LIFT)


def _draw_bars(draw, box: Box, items: list[tuple[str, float]], tokens: dict[str, Any], *,
               unit: str = "", grow: list[float] | None = None, axis_p: float = 1.0,
               diff_p: float = 0.0, spec_out: dict[str, Any] | None = None) -> list[Placement]:
    """묶음 막대. 축이 그려지고(axis_p) 막대가 자란다(grow) — §9 모션 순서 그대로.

    ★ v3.4 §22 K11 최소 요건을 이 함수가 **구조적으로** 만족시킨다:
      · 막대 폭 ≤ 화면폭 22%. 전에는 남는 폭을 계열 수로 나눠 써서 2계열이면 한 막대가 화면의
        37% 를 먹었다 — 차트가 아니라 "거대 사각형"이었다(실측 결함 F5).
      · 기준선(축) 필수 · 계열 ≤ 3 · 앰버 강조 1계열 · 값 라벨 + 단위.
    """
    out: list[Placement] = []
    if not items:
        return out
    items = items[:vc.CHART_MIN["max_series"]]
    n = len(items)
    grow = grow or [1.0] * n
    vmax = max(abs(v) for _, v in items) or 1.0
    bar_w = min(int(vc.CHART_MIN["bar_max_width_r"] * config.RENDER_WIDTH),
                max(60, box.w // max(n, 2)))
    gap = int(vc.CHART_MIN["bar_gap_r"] * config.RENDER_WIDTH)
    group_w = n * bar_w + (n - 1) * gap
    x0 = box.cx - group_w // 2                   # 폭이 줄었으니 가운데로 모은다
    base_y = box.y2 - 84
    top_room = base_y - box.y1 - CHART_TOP_RESERVE

    # ① 축·기준선이 좌→우로 그려진다(§9 라인 드로잉).
    axis_x2 = box.x1 + int((box.x2 - box.x1) * bm.ease_out_cubic(axis_p))
    if axis_x2 > box.x1:
        draw.line([(box.x1, base_y), (axis_x2, base_y)], fill=_hex("#4A5870"), width=3)
        out.append(Placement(kind="rule", box=Box(box.x1, base_y, axis_x2, base_y + 3),
                             band="CORE"))
    label_font = _role_font("source")
    val_font = _role_font("label")
    for i, (label, value) in enumerate(items):
        p = bm.ease_out_cubic(grow[i] if i < len(grow) else 1.0)
        if p <= 0:
            continue
        full_h = int((abs(value) / vmax) * top_room)
        h = max(2, int(full_h * p))
        x1 = x0 + i * (bar_w + gap)
        emph = i == len(items) - 1                       # 앰버 강조는 마지막 1계열만(K11)
        color = tokens["accent"] if emph else tokens["point"]
        draw.rectangle([x1, base_y - h, x1 + bar_w, base_y], fill=color)
        out.append(Placement(kind="bar", text=label, band="CORE",
                             box=Box(x1, base_y - h, x1 + bar_w, base_y)))
        # ② 값 라벨은 막대 머리를 따라 올라오며 카운트업한다.
        shown = bm.count_up(value, grow[i] if i < len(grow) else 1.0)
        vt = f"{shown:,.1f}{unit}" if abs(value) % 1 else f"{shown:,.0f}{unit}"
        vw, _ = _text_size(draw, vt, val_font)
        draw.text((x1 + bar_w // 2 - vw // 2, base_y - h - CHART_VALUE_LABEL_LIFT), vt,
                  font=val_font, fill=tokens["fg"], stroke_width=2, stroke_fill=(6, 10, 18))
        lw, _ = _text_size(draw, label, label_font)
        draw.text((x1 + bar_w // 2 - lw // 2, base_y + 16), label,
                  font=label_font, fill=tokens["muted"])
    # ③ 차이 강조 — 마지막 계열 위에 델타를 띄운다(§9 "차이 강조").
    # ★ 막대가 **다 자란 뒤에만** 띄운다. 예전에는 막대가 카운트업하는 동안 최종 델타를
    #   미리 보여줘서, 화면이 "39%" 와 "38%" 를 나란히 놓고 "+4%" 라고 말했다(실측: 재생
    #   60% 지점 프레임). 눈에 보이는 두 숫자의 차이는 -1 인데 배지는 +4 다 — 그 순간
    #   시청자는 화면을 믿을 수 없다. 지금 떠 있는 값으로 델타를 다시 계산하는 방법도
    #   있지만, 그러면 성장 이야기에서 "-1.1%" 가 잠깐 스쳐 더 헷갈린다.
    #   §9 가 정한 읽기 순서("첫 데이터 → 비교 데이터 → 차이 강조")도 이쪽이다.
    bars_done = all((grow[i] if i < len(grow) else 1.0) >= 0.999 for i in range(n))
    if diff_p > 0 and n >= 2 and bars_done:
        delta = items[-1][1] - items[0][1]
        dt = f"{'+' if delta >= 0 else ''}{delta:,.1f}{unit}".replace(".0", "")
        f = _role_font("label")
        s = bm.ease_out_back(diff_p)
        dw, _ = _text_size(draw, dt, f)
        cx = x0 + (n - 1) * (bar_w + gap) + bar_w // 2
        dy = box.y1 + int(CHART_BADGE_TOP_OFFSET * (2 - s))
        draw.text((cx - dw // 2, dy), dt, font=f, fill=tokens["accent"],
                  stroke_width=3, stroke_fill=(6, 10, 18))
    if spec_out is not None:
        spec_out.update({
            "baseline": True, "value_labels": True, "unit_label": bool(unit),
            "series": [lbl for lbl, _ in items],
            "bar_width_r": bar_w / float(config.RENDER_WIDTH),
            "emphasis_count": 1,
        })
    return out


# 비교 막대 한 줄의 최대 두께(px). 상한이 없으면 상자를 채우려다 막대가 값보다 커진다.
BAR_ROW_MAX_H = 132


def _draw_compare(draw, box: Box, pair, tokens: dict[str, Any], p: float) -> list[Placement]:
    """비교 기준 ↔ 이 숫자를 가로 막대 두 줄로. 길이가 p 만큼 자란다."""
    out: list[Placement] = []
    vmax = max(abs(v) for _, v in pair) or 1.0
    label_font = _role_font("source")
    val_font = _role_font("label")
    # ★ 막대가 상자를 채우게 한다. 예전엔 row_h 가 84px 로 고정돼, 상자가 400px 이어도 막대
    #   두 줄(190px)만 쓰고 **아래 200px 이 빈 검은 자리**로 남았다(실측 — NUMBER_BOARD).
    #   남은 높이를 나눠 갖되 상한을 둔다(막대가 지나치게 두꺼우면 값보다 띠가 주인공이 된다).
    n = max(1, len(pair))
    gap = 22
    row_h = min(BAR_ROW_MAX_H, max(52, (box.h - gap * (n - 1)) // n))
    # 상한에 걸려 남는 높이는 위아래로 나눠 **세로 가운데**에 놓는다.
    used = row_h * n + gap * (n - 1)
    top0 = box.y1 + max(0, (box.h - used) // 2)
    bar_x = box.x1 + 250
    bar_max = box.x2 - bar_x - 200
    for i, (label, value) in enumerate(pair):
        y = top0 + i * (row_h + gap)
        if y + row_h > box.y2:
            break
        # 두 번째 막대가 살짝 늦게 출발한다 — 비교라는 사실이 읽힌다(§9 "첫 데이터 → 비교 데이터").
        pi = bm.ease_out_cubic(min(1.0, max(0.0, p * 1.6 - i * 0.35)))
        if pi <= 0:
            continue
        color = tokens["accent"] if i == 1 else tokens["point"]
        w = max(6, int((abs(value) / vmax) * bar_max * pi))
        draw.rectangle([bar_x, y, bar_x + w, y + row_h], fill=color)
        # 빈 라벨은 그리지 않는다 — 호출자가 "바로 위 대형 숫자와 같은 말"을 지운 자리다.
        if label:
            lw, lh = _text_size(draw, label, label_font)
            draw.text((box.x1, y + row_h // 2 - lh // 2), label, font=label_font,
                      fill=tokens["muted"])
        # ★ 카운트업 **중간값**도 최종값과 같은 자릿수로 쓴다. ':g' 를 쓰면 877 로 가는 길에
        #   "601.243" 같은 날숫자가 뜬다(실측: 재생 60% 지점 프레임). 금액·비율 화면에서
        #   이건 그냥 고장 나 보인다. _draw_bars 는 이미 이 규칙을 쓰고 있었고 여기만 빠져
        #   있었다 — 목표값이 정수면 정수로, 소수를 가지면 한 자리로.
        shown_v = bm.count_up(value, min(1.0, max(0.0, p * 1.6 - i * 0.35)))
        vt = f"{shown_v:,.1f}" if abs(value) % 1 else f"{shown_v:,.0f}"
        draw.text((bar_x + w + 20, y + row_h // 2 - 22), vt, font=val_font, fill=tokens["fg"],
                  stroke_width=2, stroke_fill=(6, 10, 18))
        vw, _ = _text_size(draw, vt, val_font)
        out.append(Placement(kind="bar", text=label, band="CORE",
                             box=Box(box.x1, y, min(box.x2, bar_x + w + 20 + vw), y + row_h)))
    return out


def _chart_items(header: dict[str, Any],
                 cut: dict[str, Any]) -> tuple[list[tuple[str, float]], str]:
    """차트가 그릴 (값 목록, 단위) — number_claims 에서만 가져온다. 없으면 빈 목록(차트 포기).

    ★ claim_viz.py 와 같은 사상이다: 원장에서 해소되지 않으면 그리지 않는다. 화면에 박힌
      숫자는 시청자가 리포트 수치로 읽으므로 '그럴듯한 기본값'을 그리면 안 된다.
    ★ 단위는 K11 필수 요건이다. 계열마다 다르면 한 축에 섞을 수 없으므로 첫 단위와 다른 값은
      버린다 — %와 억 달러를 같은 막대 그래프에 놓으면 그 차트는 거짓말이 된다.

    ★★ **컷이 선언한 숫자만 쓴다.** 예전에는 `number_claim_refs` 가 없으면 리포트의 *모든*
       number_claims 를 끌어다 썼다. 그 시절엔 그 보드들이 전부 text_core 로 가서 이 값이
       안 쓰였기 때문에 무해했지만, §7-3 라우팅을 켜는 순간 유해해진다 — gauge_fill 은
       items[0] 을 현재값, items[-1] 을 목표로 그리므로, **리포트에 그런 말이 없는데도**
       무관한 두 수치가 "현재 → 목표"로 화면에 박힌다.
       빈 목록을 돌려주면 컴포넌트 가드가 None 을 내고 text_core 로 폴백한다 — 정직한 빈
       화면이 지어낸 차트보다 낫다. 형제 함수 _compare_pair 는 처음부터 이 자세였다.
    """
    exp = (header or {}).get("explainer") or {}
    by_no = {c.get("claim_no"): c for c in (exp.get("number_claims") or [])}
    refs = cut.get("number_claim_refs") or []
    out: list[tuple[str, float]] = []
    unit = ""
    for r in refs:
        c = by_no.get(r)
        if not c:
            continue
        try:
            val = float(str(c.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        cunit = str(c.get("unit") or "")
        if unit and cunit != unit:
            continue
        unit = unit or cunit
        label = str(c.get("comparison_basis") or c.get("label") or "")[:8]
        if c.get("comparison_value"):
            try:
                out.append((label or "비교", float(str(c["comparison_value"]).replace(",", ""))))
            except (TypeError, ValueError):
                pass
        out.append((str(c.get("label") or "")[:8] or "값", val))
    return out[:vc.CHART_MIN["max_series"]], unit


def _labels_look_like_periods(items: list[tuple[str, float]]) -> bool:
    """계열 라벨이 **기간**처럼 보이는가 — 시계열(§7-3 trend)의 최소 조건.

    ★ 판별식은 report_evidence 의 것을 그대로 쓴다(1Q26·2026년·FY26·3분기 …). 같은 개념을
      두 곳에 다르게 적으면 한쪽만 고쳐져 어긋난다 — 이 저장소가 이미 겪은 실패다.
    ★ **전부** 기간형이어야 한다. 하나라도 아니면 그건 추이가 아니라 항목 비교다. 비교를
      추이선으로 그리면 화면이 "시간에 따라 이렇게 변했다"는 없는 주장을 하게 된다.
    """
    from .report_evidence import _PERIOD_MARKER_RE

    labels = [lbl for lbl, _ in items]
    return bool(labels) and all(_PERIOD_MARKER_RE.search(lbl or "") for lbl in labels)


def _compare_pair(header: dict[str, Any],
                  cut: dict[str, Any]) -> tuple[tuple[str, float], tuple[str, float]] | None:
    """(비교 기준, 값) ↔ (이 숫자, 값). 둘 다 수치로 해소돼야만 돌려준다 — 아니면 None."""
    exp = (header or {}).get("explainer") or {}
    by_no = {c.get("claim_no"): c for c in (exp.get("number_claims") or [])}
    for r in (cut.get("number_claim_refs") or []):
        c = by_no.get(r)
        if not c or not c.get("comparison_value"):
            continue
        try:
            base = float(str(c["comparison_value"]).replace(",", ""))
            val = float(str(c.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        return ((str(c.get("comparison_basis") or "비교")[:10], base),
                (str(c.get("label") or "이번")[:10], val))
    return None


# ─────────────────────────────────────────────────────────────
# 프레임 1장
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# 신규 컴포넌트 4종 (v3 §7-1 P2-d)
#   전부 _draw_bars 관례를 따른다: 진행률 p 로 자라고, Placement 를 돌려주고, 좌표는
#   호출자가 준 Box 안에서만 쓴다. 순수 드로잉 — 자기 밴드를 벗어나지 않는다.
# ─────────────────────────────────────────────────────────────
def _draw_step_climb(draw, box: Box, series: list[tuple[str, float]], tokens: dict[str, Any], *,
                     p: float = 1.0, unit: str = "") -> list[Placement]:
    """계단식 추이선이 좌→우로 **그려진다**(§9 라인 드로잉).

    ★ 저장소에 선(line)/패스 드로잉 선례가 없어 새로 만든다. 막대와 달리 "시간에 따라
      쌓여온 것"을 말할 때 쓴다 — 목표가 추이처럼.
    ★ 마지막 점만 앰버로 강조한다(K11 "앰버 강조 1계열" 과 같은 자세 — 강조가 흔해지면
      강조가 아니다).
    """
    out: list[Placement] = []
    if len(series) < 2:
        return out
    series = series[:vc.CHART_MIN["max_series"] + 2]
    n = len(series)
    vmax = max(abs(v) for _, v in series) or 1.0
    base_y = box.y2 - 84
    top_room = base_y - box.y1 - CHART_TOP_RESERVE
    step_w = max(1, (box.w - 40) // (n - 1))
    x0 = box.x1 + 20

    def _pt(i: int) -> tuple[int, int]:
        return x0 + i * step_w, base_y - int((abs(series[i][1]) / vmax) * top_room)

    # 기준선 먼저(막대와 같은 순서).
    draw.line([(box.x1, base_y), (box.x2, base_y)], fill=_hex("#4A5870"), width=3)
    out.append(Placement(kind="rule", box=Box(box.x1, base_y, box.x2, base_y + 3), band="CORE"))

    # 진행률만큼의 구간까지만 그린다 — 계단이 한 칸씩 올라간다.
    eased = bm.ease_out_cubic(min(1.0, max(0.0, p)))
    reach = eased * (n - 1)
    drawn = int(reach)
    label_font = _role_font("source")
    val_font = _role_font("label")
    # ★ 면을 선 **아래**에 깔아야 하므로 두 번에 나눈다: ① 경로 점 계산 → ② 면 → ③ 선.
    #   면을 채우는 이유는 장식이 아니다. 선만 그리면 굵기 6px 이 전부라 CORE 가 텅 비어
    #   보이고(실측 충전율 0.212 — 0.25 게이트 미달로 렌더가 아예 실패했다), 추이의 '쌓여온
    #   양'도 안 읽힌다. 면적 차트는 추이 표현의 표준이고 **없는 정보를 더하지 않는다**.
    segs: list[tuple[int, int, int, int]] = []   # (x_start, x_end, y_from, y_to)
    prev = _pt(0)
    for i in range(1, n):
        cur = _pt(i)
        if i <= drawn:
            end = cur
        elif i == drawn + 1:
            frac = reach - drawn
            end = (int(prev[0] + (cur[0] - prev[0]) * frac),
                   int(prev[1] + (cur[1] - prev[1]) * frac))
        else:
            break
        segs.append((prev[0], end[0], prev[1], end[1]))
        prev = cur if i <= drawn else end

    # ② 면 — 구간마다 사각형 하나. **합쳐서 하나의 큰 상자로 세지 않는다**: 계단 아래 실제로
    #   찬 영역만 세야 충전율이 정직하다(배경 패널을 세지 않는 것과 같은 이유).
    area_fill = _mix(tokens["bg"], tokens["point"], 0.30)
    for xs, xe, y_from, _y_to in segs:
        if xe <= xs or y_from >= base_y:
            continue
        draw.rectangle([xs, y_from, xe, base_y], fill=area_fill)
        out.append(Placement(kind="area", box=Box(xs, y_from, xe, base_y), band="CORE"))

    # ③ 계단선: 가로로 간 뒤 세로로 오른다(대각선이 아니다 — "단계"임을 보이게).
    for xs, xe, y_from, y_to in segs:
        draw.line([(xs, y_from), (xe, y_from)], fill=tokens["point"], width=6)
        draw.line([(xe, y_from), (xe, y_to)], fill=tokens["point"], width=6)
        out.append(Placement(
            kind="path",
            box=Box(xs, min(y_from, y_to), xe, max(y_from, y_to) + 6), band="CORE"))

    # 도달한 마지막 점 강조 + 값.
    if drawn >= 1 or eased >= 1.0:
        last = _pt(min(drawn, n - 1))
        r = 11
        draw.ellipse([last[0] - r, last[1] - r, last[0] + r, last[1] + r], fill=tokens["accent"])
        out.append(Placement(kind="marker", box=Box(last[0] - r, last[1] - r,
                                                    last[0] + r, last[1] + r), band="CORE"))
        val = series[min(drawn, n - 1)][1]
        vt = f"{val:,.1f}{unit}" if abs(val) % 1 else f"{val:,.0f}{unit}"
        vw, _ = _text_size(draw, vt, val_font)
        # ★ 오른쪽 여백 12px — 없으면 마지막 값이 패널 테두리에 딱 붙어 잘린 것처럼 보인다(실측).
        draw.text((max(box.x1, min(last[0] - vw // 2, box.x2 - vw - 12)), last[1] - 64), vt,
                  font=val_font, fill=tokens["fg"], stroke_width=2, stroke_fill=(6, 10, 18))

    # 양 끝 라벨만(전부 적으면 축이 글자로 덮인다).
    for i in (0, n - 1):
        lbl = series[i][0]
        if not lbl:
            continue
        lw, _ = _text_size(draw, lbl, label_font)
        lx = x0 + i * step_w - (lw if i else 0)
        draw.text((max(box.x1, min(lx, box.x2 - lw)), base_y + 16), lbl,
                  font=label_font, fill=tokens["muted"])
    return out


def _draw_gauge_fill(draw, box: Box, value: float, goal: float, tokens: dict[str, Any], *,
                     p: float = 1.0, unit: str = "", label: str = "") -> list[Placement]:
    """게이지가 목표선까지 차오른다. **목표선을 절대 넘지 않는다**(fin_charts V3 clamp).

    ★ 왜 clamp 인가: 넘게 그리면 "목표 초과 달성"이라는 없는 주장을 화면이 하게 된다.
      타입 레벨(GaugeFillParams.breach 항상 False)에서 막은 것을 드로잉에서도 지킨다.
    """
    out: list[Placement] = []
    goal = abs(goal) or 1.0
    ratio = min(1.0, abs(value) / goal)              # ★ clamp — 목표를 못 넘는다
    eased = bm.ease_out_cubic(min(1.0, max(0.0, p)))
    track_h = 64
    y1 = box.cy - track_h // 2
    x1, x2 = box.x1 + 30, box.x2 - 30

    draw.rounded_rectangle([x1, y1, x2, y1 + track_h], radius=track_h // 2, fill=tokens["panel"])
    fill_w = int((x2 - x1) * ratio * eased)
    if fill_w > 4:
        draw.rounded_rectangle([x1, y1, x1 + fill_w, y1 + track_h],
                               radius=track_h // 2, fill=tokens["point"])
    out.append(Placement(kind="gauge", box=Box(x1, y1, x2, y1 + track_h), band="CORE"))

    # 목표 마커 — 게이지 끝에 세로선. 화살표·상승 연출은 없다(V1·V2 와 같은 자세).
    draw.line([(x2, y1 - 14), (x2, y1 + track_h + 14)], fill=tokens["accent"], width=5)
    out.append(Placement(kind="marker", box=Box(x2 - 3, y1 - 14, x2 + 3, y1 + track_h + 14),
                         band="CORE"))

    # 분수 배지 — "지금 / 목표". 퍼센트로 바꾸지 않는다(원문에 없는 수치가 된다).
    f = _role_font("label")
    shown = bm.count_up(abs(value), min(1.0, max(0.0, p)))
    bt = f"{shown:,.0f}{unit} / {goal:,.0f}{unit}"
    bw, bh = _text_size(draw, bt, f)
    by = y1 - bh - 26
    draw.text((box.cx - bw // 2, by), bt, font=f, fill=tokens["fg"],
              stroke_width=2, stroke_fill=(6, 10, 18))
    out.append(Placement(kind="text", text=bt, box=Box(box.cx - bw // 2, by,
                                                       box.cx + bw // 2, by + bh), band="CORE"))
    if label:
        lf = _role_font("source")
        lw, lh = _text_size(draw, label, lf)
        ly = y1 + track_h + 24
        draw.text((box.cx - lw // 2, ly), label, font=lf, fill=tokens["muted"])
        out.append(Placement(kind="text", text=label,
                             box=Box(box.cx - lw // 2, ly, box.cx + lw // 2, ly + lh), band="CORE"))
    return out


def _draw_strike_reveal(draw, box: Box, wrong: str, right: str, tokens: dict[str, Any], *,
                        p: float = 1.0) -> list[Placement]:
    """틀린 통념에 줄이 그어지고(전반부) 옳은 문장이 드러난다(후반부).

    ★ 두 문장을 동시에 띄우지 않는다 — 화면에 상반된 주장이 같이 떠 있으면 시청자가
      어느 쪽이 맞는지 모른다. 줄이 다 그어진 뒤에 정답이 나온다.
    """
    out: list[Placement] = []
    if not wrong:
        return out
    f = _role_font("sowhat")
    half = min(1.0, max(0.0, p)) * 2.0
    strike_p = min(1.0, half)                    # 0~0.5 구간: 취소선
    reveal_p = max(0.0, min(1.0, half - 1.0))    # 0.5~1.0 구간: 정답

    el = _draw_text_in(draw, Box(box.x1, box.y1 + 20, box.x2, box.cy - 20), wrong,
                       config.EXPLAINER_FONT_SIZES["sowhat"],
                       _mix(tokens["fg"], tokens["muted"], strike_p), max_lines=2,
                       role="body", band="CORE")
    if el:
        out.append(el)
        sy = (el.box.y1 + el.box.y2) // 2
        sx2 = el.box.x1 + int((el.box.x2 - el.box.x1) * bm.ease_out_cubic(strike_p))
        if sx2 > el.box.x1:
            draw.line([(el.box.x1, sy), (sx2, sy)], fill=tokens["danger"], width=6)
            out.append(Placement(kind="rule", box=Box(el.box.x1, sy, sx2, sy + 6), band="CORE"))

    if reveal_p > 0 and right:
        rc = _mix(tokens["bg"], tokens["accent"], bm.ease_out_cubic(reveal_p))
        el2 = _draw_text_in(draw, Box(box.x1, box.cy + 20, box.x2, box.y2 - 20), right,
                            config.EXPLAINER_FONT_SIZES["sowhat"], rc, max_lines=2,
                            role="body", band="CORE")
        if el2:
            out.append(el2)
    return out


def _draw_section_kicker(draw, box: Box, text: str, tokens: dict[str, Any], *,
                         p: float = 1.0, eyebrow: str = "") -> list[Placement]:
    """META 밴드 섹션 표지. 좌측 앰버 바가 자라고 글자가 따라 나온다.

    ★ 이 컴포넌트가 META 밴드의 첫 입주자다 — 지금까지 그 밴드는 정의만 있고 한 번도
      그려지지 않았다(visual_contract.BANDS 에 선언, board_render 에 그리는 코드 0).
    """
    out: list[Placement] = []
    if not text:
        return out
    eased = bm.ease_out_cubic(min(1.0, max(0.0, p)))
    bar_h = int((box.h - 12) * eased)
    if bar_h > 2:
        draw.rectangle([box.x1, box.y1 + 6, box.x1 + 8, box.y1 + 6 + bar_h],
                       fill=tokens["accent"])
        out.append(Placement(kind="rule", box=Box(box.x1, box.y1 + 6,
                                                  box.x1 + 8, box.y1 + 6 + bar_h), band="META"))
    f = _role_font("meta")
    shown = f"{eyebrow} · {text}" if eyebrow else text
    color = _mix(tokens["bg"], tokens["muted"], eased)
    tw, th = _text_size(draw, shown, f)
    tx, ty = box.x1 + 26, box.cy - th // 2
    draw.text((tx, ty), shown, font=f, fill=color)
    out.append(Placement(kind="text", text=shown, box=Box(tx, ty, tx + tw, ty + th), band="META"))
    return out


def _fallback_chain(name: str) -> list[str]:
    """레지스트리가 선언한 폴백 사슬(자기 자신 제외). 끝에는 반드시 text_core 가 온다.

    ★ 사슬이 선언돼 있는데 코드가 곧장 text_core 로 뛰면 그 선언은 장식이다. 실측 사고가
      그것이었다 — race_bar 의 fallback 은 number_count 인데 CHART_BOARD 컷이 text_core 로
      떨어졌고, 그 보드는 `core` 단계가 없어 아무것도 안 그려져 잡이 실패했다.
    ★★ 어떤 경우에도 text_core 를 마지막에 둔다. 레지스트리 사슬이 중간에 끊기거나
      (fallback_component=None) 알 수 없는 이름이어도 사슬의 끝은 구현된 것이어야 한다.
    """
    out: list[str] = []
    seen = {name}
    cur = name
    while len(out) < 4:
        try:
            nxt = cr.get_component(cur).fallback_component
        except (KeyError, ValueError):
            break
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        out.append(nxt)
        cur = nxt
    if "text_core" not in out:
        out.append("text_core")
    return out


def _step_prog(prog, ctx, name: str, absent: str = "title") -> float:
    """단계 진행률. 그 보드에 **단계 자체가 없을 때만** 다른 단계를 빌려 쓴다.

    ★ `prog(name) or prog(absent)` 로 쓰면 안 된다(리뷰 지적 — 실측으로 재현했다).
      prog 는 "단계가 없을 때"와 "아직 시작 전일 때"를 똑같이 0 으로 돌려준다. NUMBER_BOARD 처럼
      단계가 **있는** 보드에서는 시작 전 구간에 이미 달리는 title 진행률을 빌려 쓰게 되고,
      숫자가 먼저 나타났다가 진짜 number 단계가 시작되는 순간 **되감긴다**:
        t=0.37 → 0.293 (title 을 빌림) … t=0.40 → 0.033 (number 시작) 로 뚝 떨어진다.
      그래서 값이 아니라 **단계의 존재**로 판단한다.
    """
    steps = (ctx or {}).get("steps") or {}
    return prog(name) if name in steps else prog(absent)


def draw_component(name: str, draw, core: Box, pay, tokens, prog, ctx,
                   stroke) -> list[Placement] | None:
    """레지스트리 컴포넌트 이름 → 실제 드로잉 (v3 §7-1 P2-c).

    기존 드로잉 함수를 **감싸기만 한다** — 본문은 건드리지 않는다. 시그니처가 제각각이던
    것을 한 모양으로 맞춰 `_draw_frame` 이 이름으로 부를 수 있게 하는 것이 전부다.

    ★ `None` 은 "이 컴포넌트가 필요한 데이터가 없다"는 뜻이다. 예전 if 분기가
      `and pay["number"]` · `and ctx["chart_items"]` 로 걸러 텍스트 코어로 떨어뜨리던 조건을
      그대로 옮긴 것 — 이 조건을 빠뜨리면 숫자 없는 NUMBER_BOARD 가 빈 CORE 로 나간다.
      호출자가 이 None 을 레지스트리의 fallback 과 같은 의미로 처리한다.
    """
    if name == "number_count":
        if not pay["number"]:
            return None
        return _draw_number_core(draw, core, pay, tokens, prog, ctx, stroke)
    if name == "race_bar":
        # ★ **막대 하나짜리 차트는 차트가 아니다.** 비교는 비교할 것이 둘 있어야 성립한다.
        #   실측(2026-08-04): CHART_BOARD 컷의 number_claim 이 하나이고 그 claim 의
        #   comparison_value 가 "약 2배"처럼 **숫자가 아닌 서술**이면 _chart_items 가 1개만
        #   돌려준다. 예전 가드(`not chart_items`)는 그걸 통과시켜 CORE 밴드에 막대 하나를
        #   그렸고, 충전율 0.178 이 게이트(0.25)에 걸려 **잡이 통째로 실패**했다(3회 연속).
        #   증권사 리포트의 비교는 대개 서술이라 이 상황은 예외가 아니라 일상이다.
        #   여기서 None 을 내면 레지스트리 폴백(number_count)이 큰 숫자 카드를 그린다 —
        #   §7-3 이 "단일 핵심 수치 → counter_number" 라고 쓴 바로 그 화면이고, 없는 비교를
        #   지어내지도 않는다.
        if len(ctx["chart_items"] or []) < 2:
            return None
        gr = [prog("bar0"), prog("bar1"), prog("bar1")]
        return _draw_bars(
            draw, Box(core.x1 + 20, core.y1 + 36, core.x2 - 20, core.y2 - 10),
            ctx["chart_items"], tokens, unit=ctx["chart_unit"], grow=gr,
            axis_p=prog("axis"), diff_p=prog("diff"), spec_out=ctx["chart_spec"])
    if name == "source_badge":
        return _draw_evidence_core(draw, core, pay, tokens, prog, ctx, stroke)
    if name == "text_core":
        return _draw_text_core(draw, core, pay, tokens, prog, ctx, stroke)
    if name == "step_climb":
        if len(ctx["chart_items"] or []) < 2:
            return None
        return _draw_step_climb(draw, core, ctx["chart_items"], tokens,
                                p=prog("bar1") or prog("core"), unit=ctx["chart_unit"])
    if name == "gauge_fill":
        items = ctx["chart_items"] or []
        if len(items) < 2:
            return None
        return _draw_gauge_fill(draw, core, items[0][1], items[-1][1], tokens,
                                p=prog("bar1") or prog("core"), unit=ctx["chart_unit"],
                                label=items[0][0])
    if name == "strike_reveal":
        if not (pay["title"] and pay["sowhat"]):
            return None
        return _draw_strike_reveal(draw, core, pay["title"], pay["sowhat"], tokens,
                                   p=prog("core") or prog("title"))
    if name == "section_kicker":
        if not pay["kicker"]:
            return None
        return _draw_section_kicker(draw, bl.band_box("META"), pay["kicker"], tokens,
                                    p=prog("title"), eyebrow=pay["series"])
    # 등록은 됐지만 여기 분기가 없는 것. 라우터가 폴백으로 내린다 — 빈 리스트를 돌려주면
    # 그 컷이 통째로 빈 화면이 된다.
    return None


def _grey(rgb) -> int:
    """RGB 토큰 → PIL 이 convert("L") 로 쓰는 것과 **같은 식**의 회색값.

    ★ 표본은 convert("L") 로 뜨므로 배경 기준값도 같은 식으로 구해야 한다. 다른 식을 쓰면
      배경이 배경으로 안 잡혀 잉크 합집합이 화면 전체가 되고, 비율이 늘 0 에 가까워진다.
      PIL: L = R*299/1000 + G*587/1000 + B*114/1000
    """
    r, g, b = (int(x) for x in tuple(rgb)[:3])
    return int(round(r * 299 / 1000 + g * 587 / 1000 + b * 114 / 1000))


def _anim_sample_indices(n_frames: int) -> set[int]:
    """Q3 표본 프레임 번호 — 첫·중간·끝 셋뿐이다(§9: 전체 프레임 diff 금지).

    ★ 첫 프레임을 0 이 아니라 살짝 뒤에서 뜨지 않는다. 0 이 '아직 아무것도 안 그려진'
      상태라는 것이 바로 애니메이션의 출발점이고, 그걸 빼면 '자란 것'을 못 잰다.
    """
    if n_frames <= 0:
        return set()
    return {0, n_frames // 2, n_frames - 1}


def _core_component_box(placements: list[Placement]) -> Box | None:
    """CORE 레이어로 찍힌 placements 의 합집합 상자 (= 그 컴포넌트가 실제로 차지한 자리).

    ★★ 왜 CORE **밴드**가 아니라 이것인가(2026-09-03 실측): 밴드로 재면 배경 패널이
      밴드의 78% 를 정적으로 채우고 있어서, 숫자가 통째로 바뀌어도 변화 비율이 0.21 로
      희석돼 **보드 11종이 전부 계약 미달**로 나왔다. 지시서 §9 가 "컴포넌트 bbox 안에서"
      라고 쓴 이유가 이것이다. 100% 실패는 계약이 아니라 자를 의심하라는 신호다.
    """
    boxes = [p.box for p in (placements or []) if p.meta.get("layer_id") == "core"]
    if not boxes:
        return None
    return Box(min(b.x1 for b in boxes), min(b.y1 for b in boxes),
               max(b.x2 for b in boxes), max(b.y2 for b in boxes))


def _box_pixels(path: str, box: Box) -> list[int]:
    """저장된 프레임에서 상자 부분을 회색조 1차원으로. 축소해서 센다(해상도 불필요)."""
    from PIL import Image          # 모듈 최상단이 아니라 여기서 — 파일의 기존 규약과 같다
    with Image.open(path) as im:
        crop = im.crop((box.x1, box.y1, box.x2, box.y2)).convert("L")
        crop = crop.resize((config.ANIM_QA_SAMPLE_W, config.ANIM_QA_SAMPLE_H))
        # Pillow 14 에서 getdata 가 사라진다 — 있으면 새 이름을 쓴다(양쪽 다 도는 형태).
        getter = getattr(crop, "get_flattened_data", None) or crop.getdata
        return list(getter())


def _measure_animation(frame_paths: list[str], placements: list[Placement],
                       component: str):
    """Q3 판정. 저장된 첫·중간·끝 프레임만 다시 열어 컴포넌트 상자를 비교한다.

    ★ 루프 안에서 뜨지 않는 이유: 컴포넌트 상자는 그리기가 끝나야 확정되는데(placements),
      프레임 이미지는 매 프레임 제자리에서 덮어써진다. 프레임은 어차피 디스크에 남으므로
      끝나고 세 장만 다시 여는 편이 정확하고 싸다.
    """
    box = _core_component_box(placements)
    if box is None or box.x2 <= box.x1 or box.y2 <= box.y1:
        return None
    idx = sorted(_anim_sample_indices(len(frame_paths)))
    if len(idx) < 2:
        return None
    samples = [_box_pixels(frame_paths[i], box) for i in idx]
    mid = samples[len(samples) // 2] if len(samples) >= 3 else samples[0]
    return aqa.evaluate(component, samples[0], mid, samples[-1])


def _draw_frame(img, draw, t: float, ctx: dict[str, Any]) -> list[Placement]:
    """시각 t 의 화면 한 장. 모든 요소는 자기 단계의 진행률만큼 그려진다."""
    pay, tokens, steps = ctx["pay"], ctx["tokens"], ctx["steps"]
    sizes = config.EXPLAINER_FONT_SIZES
    board = pay["board"]
    on_photo = bool(ctx.get("bg_image"))
    stroke = config.EXPLAINER_TEXT_STROKE_PX if on_photo else 0

    def prog(name: str) -> float:
        s = steps.get(name)
        return s.progress(t) if s else 0.0

    # ★ 레이어 정체(meta["layer_id"])는 **여기 호출부에서만** 찍는다(§8-1 · rm.tag 주석 참조).
    #   그리기 함수 본문과 Placement 생성자 18곳은 한 줄도 안 건드린다 — 그래서 픽셀이
    #   바뀌지 않고 골든 해시가 그대로다.
    placements = rm.tag(_draw_background(img, draw, tokens, ctx.get("bg_image")), "backdrop")
    core = bl.band_box("CORE")

    # ── TITLE ──
    p = prog("title")
    if p > 0 and ctx["title_text"]:
        el = _draw_text_in(draw, bl.band_box("TITLE"), ctx["title_text"], sizes["title"],
                           _mix(tokens["bg"], tokens["fg"], bm.ease_out_cubic(p)),
                           max_lines=2, role="head", band="TITLE", stroke=stroke)
        if el:
            placements += rm.tag([el], "title")

    # ── CORE — 레지스트리가 컴포넌트를 고른다 (v3 §7-3 P2-e) ──
    #
    # ★ 예전에는 여기 보드 이름 if 분기 4개가 박혀 있었다. 새 표현을 넣으려면 그 분기를
    #   늘려야 했고, 어떤 수치가 어떤 자리에 들어가는지 선언된 곳이 없었다.
    # ★ 이 교체의 합격기준은 **화면 불변**이다(운영자 결정) — 배선만 바꾸고 나오는 그림은
    #   오늘과 같아야 한다. tests/test_board_render_golden.py 가 보드 11종 PNG 해시로 고정한다.
    #   그래서 라우팅 표도 지금 실제로 나가는 화면에 맞춰 뒀다(MECHANISM·HOOK → text_core).
    # ★ allow_draft=False: 아직 안 그려지는 컴포넌트로 라우팅해 빈 화면을 만들지 않는다.
    # ★ 라우팅 결정은 render_board 가 **이미 끝냈다**(§7-3, ctx["core_component"]). 여기서
    #   다시 풀면 선언(manifest)과 그림이 갈릴 수 있다 — 밴드 배정을 한곳에서 끝내라는
    #   위 §P2-f 주석과 같은 이유다.
    core_component = ctx["core_component"]
    drawn = draw_component(core_component, draw, core, pay, tokens, prog, ctx, stroke)
    if drawn is None:
        # 데이터가 없거나 미구현 — 레지스트리의 fallback 과 같은 의미다. 텍스트 코어가
        # 사슬의 끝이고 반드시 구현돼 있다(component_registry 테스트가 고정).
        # ★ 이 폴백이 일어났다는 사실이 지금까지 **어디에도 안 남았다.** "이 컷이 왜
        #   허전한가"의 답이 대개 여기다 — manifest 가 from/to 로 기록한다(§8-1).
        # ★ 레지스트리가 선언한 사슬을 **실제로 탄다.** 예전에는 여기서 곧장 text_core 로
        #   갔는데, 그러면 race_bar 의 fallback_component="number_count" 선언이 장식이 된다.
        #   실측 사고(2026-08-04): 막대가 하나뿐인 CHART_BOARD 가 text_core 로 떨어졌고,
        #   그 보드는 `core` 단계가 없어 text_core 가 **아무것도 안 그렸다**(충전율 0.00).
        #   숫자 카드로 내려갔어야 할 컷이 빈 화면이 되고 잡이 실패한 것이다.
        fallback_from = core_component
        # ★ 폴백으로 온 컴포넌트는 그 보드의 **CORE 를 혼자 쓴다.** 원래 자리(NUMBER_BOARD)
        #   에서는 다른 요소와 자리를 나눠 쓰던 크기라, 그대로 그리면 넓은 CORE 가 휑하게
        #   남아 충전율 게이트에 걸린다(실측: 폴백 후에도 0.217 < 0.25). 그리는 쪽이 알아야
        #   크기를 키울 수 있으므로 **그리기 전에** 표시한다.
        ctx["core_is_fallback"] = True
        for nxt in _fallback_chain(fallback_from):
            drawn = draw_component(nxt, draw, core, pay, tokens, prog, ctx, stroke)
            core_component = nxt
            if drawn:
                break
        drawn = drawn or []
        # ★★ 폴백 **시도** 자체를 ctx 에 남긴다. placements 에 태그를 찍는 것만으로는 부족한데,
        #    폴백이 아무것도 못 그리면(실측: 숫자 없는 NUMBER_BOARD — text_core 가 `core` 단계가
        #    없는 보드에서 빈 리스트를 낸다) 찍을 placement 가 없어 "그냥 결측"으로만 보인다.
        #    "폴백까지 갔는데도 비었다"와 "애초에 안 그렸다"는 원인이 다르다.
        ctx["core_fallback"] = {"layer_id": "core", "from": fallback_from,
                                "to": core_component}
    placements += rm.tag(drawn, "core", core_component)

    # ── META 밴드 (v3 §7-3 P2-f) ──
    #
    # ★ 이 밴드는 지금까지 **한 번도 그려지지 않았다.** visual_contract.BANDS 가 "킥커 / 시리즈
    #   배지" 자리로 선언해 뒀는데 board_render 에 그리는 코드가 없어서, 화면 상단 60px 이
    #   늘 비어 있었다(CORE 충전율과 별개로 화면이 허전해 보이던 이유 중 하나다).
    #
    # ★★ 이미 그려진 말은 또 찍지 않는다. EVIDENCE_BOARD 는 `_draw_evidence_core` 가 CORE
    #    카드 안에 같은 증권사명을 그린다 — 여기서 무조건 그리면 K10(같은 프레임 중복 텍스트)이
    #    잡아 **잡 전체가 죽는다.** 판정은 킬 스위치와 같은 함수를 쓴다(완전일치뿐 아니라
    #    포함관계도 중복이다). `_OVERLAY_ROLE` 이 ASS 이중 인쇄를 막는 것과 같은 자세다.
    if ctx.get("meta_kicker"):
        placements += rm.tag(draw_component(
            "section_kicker", draw, core, pay, tokens, prog, ctx, stroke) or [],
            "meta", "section_kicker")

    # ── SOURCE 밴드는 여기서 그리지 않는다 ──
    #   출처·면책은 ASS footer 로 나간다(config.EXPLAINER_SOURCE_MARGIN_V 가 그 밴드를
    #   자막 여백으로 쓴다). 여기서 또 그리면 같은 문장이 두 번 인쇄된다 — ASS 를 걷어내는
    #   것은 자막 계약(§Q4)을 건드리는 별개 작업이라 P2 범위 밖이다.

    # ── so_what 한 줄(SOWHAT 밴드) ──
    p = prog("sowhat")
    if p > 0 and pay["sowhat"] and board in ("NUMBER_BOARD", "CHART_BOARD", "VALUATION_BOARD"):
        el = _draw_text_in(draw, bl.band_box("SOWHAT"), pay["sowhat"], sizes["sowhat"],
                           _mix(tokens["bg"], tokens["muted"], bm.ease_out_cubic(p)),
                           max_lines=1, role="body", band="SOWHAT", stroke=stroke)
        if el:
            placements += rm.tag([el], "sowhat")
    return placements


def _draw_number_core(draw, core: Box, pay, tokens, prog, ctx, stroke) -> list[Placement]:
    """대형 숫자가 **카운트업**하며 CORE 를 채운다 — §9 콜아웃 숫자."""
    sizes = config.EXPLAINER_FONT_SIZES
    out: list[Placement] = []
    # ★ 이 보드에 `number` 단계가 없을 수 있다 — 폴백으로 여기 왔을 때다(BOARD_STEPS 는
    #   보드마다 다르다). 그때는 제목 단계를 타고 나타난다. 단계를 새로 추가하면 stride 가
    #   바뀌어 그 보드의 **모든 프레임 타이밍**이 밀리므로, 진행률만 빌려 쓴다.
    p = _step_prog(prog, ctx, "number")
    if p <= 0:
        return out
    # 숫자 폰트 역할: 한글이 섞이면 num_ko. 순수 ASCII 일 때만 num_en(Anton) — Anton 에는
    # 한글 글리프가 없어 그대로 쓰면 두부가 된다.
    num_role = "num_en" if pay["number"].isascii() else "num_ko"
    try:
        target = float(str(pay["number_value"]).replace(",", ""))
        shown = bm.count_up(target, p)
        text = (f"{shown:,.1f}" if abs(target) % 1 else f"{shown:,.0f}") + pay["number_unit"]
    except (TypeError, ValueError):
        text = pay["number"] if p >= 1 else ""
    if not text:
        return out
    size = sizes["big_number"]
    font = _font(size, num_role)
    while size > 72 and _text_size(draw, pay["number"], font)[0] > core.w - 40:
        size -= 6
        font = _font(size, num_role)
    # ★ 폭이 허락하는 만큼 키운다. 예전에는 폴백 컷에서만 키웠는데, 그러면 숫자가 주인공인
    #   NUMBER_BOARD 조차 카드 폭의 절반만 쓰고 아래가 텅 빈다(실측 충전율 0.22 — 이 한
    #   사유로 설명판형 렌더 8건 중 5건이 죽었다). 쇼츠에서 대표 수치는 클수록 읽힌다.
    #   상한은 그대로 EXPLAINER_FALLBACK_NUMBER_MAX_SIZE 를 쓴다.
    while (size < config.EXPLAINER_FALLBACK_NUMBER_MAX_SIZE
           and _text_size(draw, pay["number"], _font(size + 6, num_role))[0] <= core.w - 40):
        size += 6
    font = _font(size, num_role)
    w, h = _text_size(draw, text, font)
    y = core.y1 + 56
    nx = max(core.x1 + 20, core.cx - w // 2)
    draw.text((nx, y), text, font=font, fill=tokens["accent"],
              stroke_width=stroke, stroke_fill=(6, 10, 18))
    # ★ 큰 숫자는 줄 상자 위쪽을 기준으로 그려진다 — 글자는 그보다 한참 아래에서 시작해
    #   `y + h` 보다 아래에서 끝난다(Anton 220pt 기준 67px 차이). 예전에는 `y + h` 를
    #   "글자 아래"로 써서 밑줄과 라벨이 숫자 위로 올라탔다. 실제 잉크 범위를 쓴다.
    ink_top, ink_bottom = vc.text_ink_span(draw, text, font)
    out.append(Placement(kind="number", text=pay["number"], band="CORE",
                         box=Box(nx, y + ink_top, min(core.x2, nx + w), y + ink_bottom)))
    # 앰버 밑줄이 숫자 폭만큼 좌→우로 자란다.
    rp = bm.ease_out_cubic(_step_prog(prog, ctx, "rule"))
    rule_y = y + ink_bottom + 16
    if rp > 0:
        rw = int(w * rp)
        draw.rectangle([nx, rule_y, min(core.x2, nx + rw), rule_y + 7], fill=tokens["accent"])
        out.append(Placement(kind="rule", band="CORE",
                             box=Box(nx, rule_y, min(core.x2, nx + rw), rule_y + 7)))
    lp = _step_prog(prog, ctx, "label")
    if lp > 0:
        el = _draw_text_in(draw, Box(core.x1 + 20, rule_y + 22, core.x2 - 20, core.y2),
                           pay["number_label"], sizes["label"],
                           _mix(tokens["bg"], tokens["fg"], bm.ease_out_cubic(lp)),
                           align="center", max_lines=1, role="body", band="CORE", stroke=stroke)
        if el:
            out.append(el)
    # ★ 같은 이유로 `compare` 단계도 없을 수 있다(폴백 경유). 비교가 빠지면 숫자 카드가
    #   반쪽이 되고 CORE 가 그만큼 빈다 — 실측에서 그 차이가 충전율 0.17 과 0.27 을 갈랐다.
    cp = _step_prog(prog, ctx, "compare")
    if cp > 0 and pay["comparison"]:
        # ★ 비교 기준을 글자로만 적지 않고 막대 두 개로 보여준다(§6 "숫자 → 비교 기준 → 의미").
        #   숫자만 크게 띄우면 시청자는 그게 큰 값인지 알 수 없다.
        cmp_box = Box(core.x1 + 20, rule_y + 96, core.x2 - 20, core.y2 - 12)
        pair = ctx["compare_pair"]
        # ★ 같은 말을 화면에 두 번 쓰지 않는다. 막대 라벨이 바로 위 대형 숫자 라벨과 같으면
        #   ("FY4Q26 매출액"이 숫자 밑에도, 막대 옆에도 있었다 — 실측) 막대 쪽을 비운다.
        #   정보는 안 사라진다: 그 막대는 앰버색이라 위 숫자와 같은 것임이 색으로 읽힌다.
        if pair:
            pair = [("" if vc.is_duplicate_text(lb, pay["number_label"]) else lb, v)
                    for lb, v in pair]
        if pair:
            out += _draw_compare(draw, cmp_box, pair, tokens, cp)
        else:
            el = _draw_text_in(draw, cmp_box, f"↔ {pay['comparison']}", sizes["body"],
                               _mix(tokens["bg"], tokens["point"], bm.ease_out_cubic(cp)),
                               align="center", max_lines=1, role="body", band="CORE",
                               stroke=stroke)
            if el:
                out.append(el)
    return out


# 근거 카드 높이(px). 증권사 2줄 + 인용 본문 3줄이 담기는 크기다.
EVIDENCE_CARD_H = 386


def _draw_evidence_core(draw, core: Box, pay, tokens, prog, ctx, stroke) -> list[Placement]:
    """근거 카드가 위에서 아래로 **열리며**(마스크) 증권사·주장이 뒤따른다."""
    sizes = config.EXPLAINER_FONT_SIZES
    out: list[Placement] = []
    p = bm.ease_out_cubic(prog("card"))
    if p <= 0:
        return out
    # ★ 카드를 CORE 밴드 **세로 가운데**에 놓는다. 예전엔 위에서 44px 지점에 고정 높이로
    #   그려서 카드 아래 250px 가 빈 패널로 남았다(실측 — 위 44 / 아래 250 의 비대칭).
    #   카드 높이는 내용(증권사 2줄 + 본문 3줄)에 맞춘 값이라 늘리지 않는다 — 늘리면 이번엔
    #   카드 **안쪽**이 빈다. 글자에 valign="center" 를 준 것과 같은 처방이다.
    top = core.y1 + max(24, (core.h - EVIDENCE_CARD_H) // 2)
    full = Box(core.x1 + 24, top, core.x2 - 24, top + EVIDENCE_CARD_H)
    h = max(4, int(full.h * p))
    card = Box(full.x1, full.y1, full.x2, full.y1 + h)
    draw.rectangle([card.x1, card.y1, card.x2, card.y2],
                   fill=_mix(tokens["bg"], tokens["fg"], 0.07), outline=tokens["point"], width=3)
    out.append(Placement(kind="card", band="CORE", box=card))
    sp = prog("speaker")
    if sp > 0:
        el = _draw_text_in(draw, Box(full.x1 + 30, full.y1 + 30, full.x2 - 30, full.y2),
                           pay["source"] or pay["kicker"], sizes["label"],
                           _mix(tokens["bg"], tokens["accent"], bm.ease_out_cubic(sp)),
                           max_lines=2, role="head", band="CORE", stroke=stroke)
        if el:
            out.append(el)
    bp = prog("body")
    # ★ K10 이 잡은 실제 중복: 카드 본문이 TITLE 밴드와 같은 문장을 또 찍고 있었다. 이 보드의
    #   역할은 "누가 이 주장을 했나"이므로 본문은 제목과 다른 한 줄만 싣는다. 같으면 비운다.
    body = "" if vc.is_duplicate_text(pay["sowhat"], ctx["title_text"]) else pay["sowhat"]
    if bp > 0 and body:
        el = _draw_text_in(draw, Box(full.x1 + 30, full.y1 + 150, full.x2 - 30, full.y2),
                           body, sizes["body"],
                           _mix(tokens["bg"], tokens["fg"], bm.ease_out_cubic(bp)),
                           max_lines=3, role="body", band="CORE", stroke=stroke)
        if el:
            out.append(el)
    return out


def _draw_text_core(draw, core: Box, pay, tokens, prog, ctx, stroke) -> list[Placement]:
    """HOOK / CLAIM / MECHANISM / REPORT_REASON / WATCHPOINT — 문장이 주역인 보드.

    ★ 그래도 정지 화면은 만들지 않는다: 문장이 아래에서 살짝 올라오며 밝아지고, 좌측 앰버
      마커가 문장 높이만큼 자란다(§9 마스크·하이라이트).

    ★★ **이 폴백은 숫자·차트 보드에서는 일부러 아무것도 안 그린다.** BOARD_STEPS 에 명시된
       다섯 보드(CHART·COMPARISON·NUMBER·VALUATION·EVIDENCE)는 `core` 단계가 없고
       `render_board` 도 `core_text` 를 안 채운다. 그래서 숫자 없는 NUMBER_BOARD 가 여기로
       폴백하면 CORE 가 빈다(실측 core_fill 0.00).

       고치려다 되돌린 이유를 남긴다 — **그 보드들에는 여기 쓸 여분의 문장이 없다.**
       `sowhat` 은 이미 SOWHAT 밴드가 그리고 `title` 은 TITLE 밴드가 그린다. 무엇을 가져와도
       같은 문장이 한 화면에 두 번 뜨고, 그건 K10(같은 프레임 중복 텍스트)이 **잡 전체를
       죽인다.** 빈 화면을 면하려다 같은 말을 두 번 하는 화면을 만드는 셈이다.

       그래서 그대로 둔다. 이 경우는 이미 올바르게 처리된다: 충전율 0.00 이 0.25 게이트에
       걸려 그 컷이 **렌더 실패**로 떨어지고(§22-6), manifest 에 `fallback_empty` 로 남는다.
       빈 화면이 조용히 발행되는 것이 아니라 시끄럽게 멈춘다 — 그게 맞는 동작이다.
       진짜 고칠 곳은 여기가 아니라 **숫자 없는 컷을 만드는 지시서 생성**이다.
    """
    sizes = config.EXPLAINER_FONT_SIZES
    out: list[Placement] = []
    board = pay["board"]
    p = _step_prog(prog, ctx, "core")
    if p <= 0:
        return out
    e = bm.ease_out_cubic(p)
    text = ctx["core_text"]     # 밴드 배정은 render_board 가 이미 끝냈다(중복 회피 포함)
    if not text:
        return out
    lift = int(40 * (1 - e))
    # ★ 세로 중앙. 예전엔 core.y1+96 에서 위로 붙여 그려서, 2줄짜리 문장이면 패널 675px 중
    #   아래 400px 이 빈 검은 상자로 남았다(실측 — HOOK·MECHANISM).
    el = _draw_text_in(draw, Box(core.x1 + 40, core.y1 + 40 + lift, core.x2 - 40, core.y2 - 40),
                       text, sizes["title"], _mix(tokens["bg"], tokens["fg"], e),
                       align="center", valign="center", max_lines=4, role="head",
                       band="CORE", stroke=stroke,
                       grow_to=config.EXPLAINER_CORE_TEXT_MAX_SIZE)
    if el:
        out.append(el)
        mh = int((el.box.y2 - el.box.y1) * e)
        draw.rectangle([core.x1 + 16, el.box.y1, core.x1 + 22, el.box.y1 + mh],
                       fill=tokens["accent"])
    mp = prog("metric")
    if mp > 0 and board == "WATCHPOINT_BOARD" and pay["watch_metric"]:
        el = _draw_text_in(draw, Box(core.x1 + 40, core.y2 - 150, core.x2 - 40, core.y2 - 20),
                           f"지표 · {pay['watch_metric']}", sizes["body"],
                           _mix(tokens["bg"], tokens["accent"], bm.ease_out_cubic(mp)),
                           align="center", max_lines=2, role="body", band="CORE", stroke=stroke)
        if el:
            out.append(el)
    return out


# ─────────────────────────────────────────────────────────────
# 보드 1개 → 프레임 시퀀스
# ─────────────────────────────────────────────────────────────
def render_board(cut: dict[str, Any], header: dict[str, Any],
                 fact_sheet: dict[str, Any] | None, out_dir: str, idx: int,
                 total_sec: float, lang: str = "ko",
                 bg_image: str | None = None) -> BoardResult:
    """보드 1개 → 30fps 프레임 PNG + §20-7·§22-6 판정."""
    from PIL import Image, ImageDraw

    pay = board_payload(cut, header, fact_sheet, lang)
    # ★ 색은 visual_contract.TOKENS 가 유일한 원본이다(§7-4). 예전엔 여기서 fg·muted 를
    #   하드코딩해 visual_contract 의 WHITE·GRAY 와 값이 달랐다 — 화면에 나가는 것은 여기
    #   값이었고 저쪽은 참조 0건인 죽은 상수였다. 지금은 그 살아 있던 값이 정본이다.
    tokens = dict(vc.TOKENS)
    board = pay["board"]

    # ★ 화면에 같은 말이 두 번 뜨지 않게 한다:
    #   · 숫자 보드는 라벨을 숫자 밑에 그리므로 제목에 또 쓰지 않는다.
    #   · so_what 을 따로 그리는 보드는 제목에 so_what 을 쓰지 않는다.
    #
    # ★★ 밴드 배정은 **여기 한곳에서** 끝낸다. 예전에는 TITLE 은 여기서, CORE 문장은
    #   _draw_text_core 안에서 각자 폴백을 골랐다 — 오버레이 본문이 없는 텍스트 보드는
    #   양쪽 폴백이 똑같이 so_what 으로 떨어져 **같은 문장을 두 밴드에 배정**했고, 그
    #   프레임을 다 그린 뒤에야 K10 이 잡아 잡 전체가 죽었다(실측: 리포트 KO 렌더 실패).
    has_sowhat_band = board in ("NUMBER_BOARD", "CHART_BOARD", "VALUATION_BOARD")
    core_text = ""
    if "core" in bm.steps_for(board):     # 문장이 주역인 보드(DEFAULT_STEPS)만 CORE 에 문장을 쓴다
        core_text = (pay["watchpoint"] if board == "WATCHPOINT_BOARD"
                     else (pay["sowhat"] or pay["title"]))
    sowhat_band = pay["sowhat"] if has_sowhat_band else ""
    title_text = pay["title"]
    if not title_text and not has_sowhat_band and not core_text:
        title_text = pay["sowhat"]
    # 전용 밴드(CORE 문장 · SOWHAT 밴드)가 이미 그 말을 하고 있으면 제목은 비운다.
    # 판정은 킬 스위치와 같은 함수를 쓴다 — 완전일치뿐 아니라 포함관계도 K10 위반이다.
    if title_text and (vc.is_duplicate_text(title_text, core_text)
                       or vc.is_duplicate_text(title_text, sowhat_band)):
        title_text = ""

    chart_items, chart_unit = _chart_items(header, cut)

    # ── META 밴드 배정 (v3 §7-3 P2-f) ──
    # ★★ 위 주석과 같은 이유로 **여기 한곳에서** 정한다. 프레임마다 "이미 그려졌나"를 보고
    #    정하면 킥커가 컷 도중에 나타났다 사라진다 — CORE 의 증권사명은 prog("speaker") 가
    #    올라간 뒤에야 그려지므로, 앞 프레임엔 중복이 아니고 뒷 프레임엔 중복이 된다.
    #    (실제로 그렇게 짰다가 EVIDENCE_BOARD 에서 깜빡이는 것을 잡았다.)
    # ★ EVIDENCE_BOARD 는 CORE 카드가 같은 증권사명을 그린다(_draw_evidence_core). 거기에
    #   META 까지 그리면 K10(같은 프레임 중복 텍스트)이 잡아 **잡 전체가 죽는다.**
    # ★ §7-3 의미 라우팅 — 컷이 선언한 데이터의 모양까지 보고 정한다. **여기 한 번만** 정하고
    #   ctx 에 실어 보낸다: _draw_frame 과 render_manifest.declare 가 같은 답을 봐야 manifest
    #   가 거짓말을 안 한다(선언과 그림이 갈리면 대조가 무의미해진다).
    core_spec = cr.resolve_for_cut(
        board, series_len=len(chart_items),
        period_like=_labels_look_like_periods(chart_items), allow_draft=False)
    core_component = core_spec.component
    meta_kicker = "" if core_component == "source_badge" else pay["kicker"]

    ctx: dict[str, Any] = {
        "pay": pay, "tokens": tokens, "title_text": title_text, "core_text": core_text,
        "chart_items": chart_items, "chart_unit": chart_unit,
        "compare_pair": _compare_pair(header, cut),
        "chart_spec": {}, "bg_image": bg_image, "meta_kicker": meta_kicker,
        "core_component": core_component,
        "steps": bm.build_timeline(list(bm.steps_for(board)), float(total_sec)),
    }

    # ★ 선언은 **그리기 전에**, 그리고 컷 dict 이 아니라 ctx 로 한다 — 선언과 그리기가 같은
    #   데이터를 봐야 manifest 가 거짓말을 안 한다(render_manifest.declare 주석).
    try:
        declared = rm.declare(board, ctx)
    except Exception as exc:  # noqa: BLE001
        log.warning("manifest 선언 실패 — 대조를 건너뛴다(렌더는 계속): %s", exc)
        declared = {}

    frames = bm.frame_times(total_sec)
    frame_paths: list[str] = []
    placements: list[Placement] = []
    img = Image.new("RGB", (config.RENDER_WIDTH, config.RENDER_HEIGHT), tokens["bg"])
    for i, t in enumerate(frames):
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, config.RENDER_WIDTH, config.RENDER_HEIGHT], fill=tokens["bg"])
        placements = _draw_frame(img, draw, t, ctx)
        path = os.path.join(out_dir, f"board_{idx}_{i:05d}.png")
        img.save(path, "PNG", compress_level=1)
        frame_paths.append(path)

    # ★ v3.4 §22 K10 — 같은 프레임에 같은 문장이 두 번 뜨면 실패. 판정 대상은 payload 후보가
    #   아니라 **실제로 그려진 텍스트**(Placement.text)다. 후보로 검사하면 "제목 자리에 so_what
    #   을 쓰고 SOWHAT 밴드는 비운" 정상 배치도 중복으로 잡힌다 — 그건 한 번만 그려진다.
    vc.assert_no_duplicate_text(*[p.text for p in placements if p.kind == "text" and p.text])

    # CORE 밀도는 요소 점유 면적으로 잰다(board_layout.core_coverage 주석 — 픽셀 비율은
    # 글자 획이 얇아 늘 낮게 나와 '허전한 화면'을 구분하지 못한다).
    # K11 최소 요건 중 so_what·source 는 차트 함수 밖(SOWHAT 밴드 · ASS footer)에서 그려지므로
    # 여기서 스펙에 채워 넣는다.
    if ctx["chart_spec"]:
        ctx["chart_spec"]["so_what"] = bool(pay["sowhat"])
        ctx["chart_spec"]["source"] = bool(pay["source"] or pay["kicker"])

    core_fill = bl.core_coverage(placements)
    qa = bl.evaluate_layout(placements, core_fill_ratio=core_fill)

    # ★ Q3 애니메이션 계약(§9). 레지스트리의 min_change_ratio 를 **실제로 읽는 유일한 지점**이다.
    #   판정(qa["fail"])에는 넣지 않는다 — 화면은 그려져 있고 움직임만 없는 상태라
    #   잡을 죽이는 대신 board_qa 의 animation_fail 로 올려 degraded(사람 확인)로 보낸다
    #   (core_underfilled 가 배운 처방 — config.LAYOUT_FAIL_REVIEWABLE 주석).
    anim_result = None
    if config.ANIM_QA_ENABLED and len(frame_paths) >= 2:
        try:
            # ★ 배경 기준값을 토큰에서 주지 않는다 — 컴포넌트 뒤에는 더 밝은 패널이 깔려
            #   있어서 페이지 배경과 다르다(animation_qa.baseline 주석의 실측).
            anim_result = _measure_animation(frame_paths, placements, ctx["core_component"])
        except Exception as exc:  # noqa: BLE001 — 관측이 렌더를 죽이지 않는다(manifest 와 같은 규율)
            log.warning("Q3 애니메이션 검사 실패 — 기록만 건너뛴다(렌더는 계속): %s", exc)
    animation = anim_result.as_dict() if anim_result else {}
    animation_fail = aqa.board_signals(anim_result)

    # ★ §8-1 manifest 대조 — 기록 전용. 선언(declare)은 그리기 전 ctx 로 했고, 여기서
    #   마지막 프레임 placements 와 맞춘다. **판정(qa)에는 한 글자도 넣지 않는다.**
    #   try 로 감싸는 이유는 report_render 의 run_qa 와 같다 — 관측을 켜다가 잘 그려진
    #   보드를 잃으면 안 된다. 실패해도 렌더는 계속되고 사유만 남는다.
    try:
        fb = [ctx["core_fallback"]] if ctx.get("core_fallback") else []
        manifest = rm.reconcile(declared, placements, attempted_fallbacks=fb)
    except Exception as exc:  # noqa: BLE001
        log.warning("manifest 대조 실패 — 기록만 건너뛴다(렌더는 계속): %s", exc)
        manifest = {"policy": "record_only",
                    "manifest_error": f"{type(exc).__name__}: {exc}"[:200]}

    # ★ v3.4 §22-6 — 완성된 마지막 프레임을 **픽셀로** 다시 판정한다. evaluate_layout 은 우리가
    #   "놓겠다고 계산한 박스"만 본다. 그리는 중에 어긋나면(레터박스·DEAD 밴드 침범·9:16 아님)
    #   박스 계산은 멀쩡한데 화면은 틀린다 — 실제로 그렇게 검은 바를 놓쳤다.
    frame_qa = vc.validate_frame(img, bg=tokens["bg"])
    qa["fail"] = sorted(set(qa["fail"]) | {f"frame:{m}" for m in frame_qa["fail"]}
                        | {f"chart:{m}" for m in vc.validate_chart_spec(ctx["chart_spec"])
                           if ctx["chart_spec"]})
    qa["warn"] = sorted(set(qa["warn"]) | {f"frame:{m}" for m in frame_qa["warn"]})
    if qa["fail"]:
        log.warning("보드 레이아웃 위반 컷=%s: %s", cut.get("cut_no"), ", ".join(qa["fail"]))
    return BoardResult(frame_paths=frame_paths, fps=config.EXPLAINER_MOTION_FPS,
                       placements=placements, layout_qa=qa, core_fill=core_fill,
                       frame_qa=frame_qa, chart_spec=ctx["chart_spec"],
                       manifest=manifest, animation=animation,
                       animation_fail=animation_fail)


def band_pad(box: Box, pad: int = 12) -> Box:
    return Box(box.x1, box.y1 + pad, box.x2, box.y2)
