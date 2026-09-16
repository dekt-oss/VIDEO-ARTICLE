"""설명판 레이아웃 — 밴드 그리드 해소와 §20-7 판정 (최종명세 v3.3).

★ 순수 모듈이다: PIL·ffmpeg·네트워크를 모른다. "무엇을 어디에 놓을지"만 계산하고,
  실제로 그리는 것은 engine/board_render.py 다. 저장소의 기존 분리 방식과 같다
  (render_qa.evaluate_qa 순수 ↔ probe_signals IO / evidence_overlay 순수).

★ 왜 이 분리가 값어치를 하는가: §20-7 검사(밴드 침범 · x>930 · CORE 밀도)를 **그리기 전에**
  판정할 수 있다. 산출 mp4 를 디코드해 픽셀을 세지 않아도 되고, 단위 테스트가 PIL 없이 돈다.

밴드(§20-3):
  DEAD_TOP 배치금지 / META / TITLE / **CORE 화면의 주인공** /
  SOWHAT / CAPTION / SOURCE 출처·면책 / DEAD_BOTTOM 배치금지

★ 밴드 좌표를 여기에 적지 않는다. 원본은 engine/visual_contract.py 의 **비율** BANDS 이고
  (v3.4 §22-1 — 그 모듈이 규범), config.EXPLAINER_BANDS 가 렌더 해상도로 해소한 값을 쓴다.
  절대 픽셀을 두 곳에 적으면 해상도가 바뀌는 순간 어긋난다(실측 결함 F2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config

# 정보를 놓으면 안 되는 밴드 — 플랫폼 UI 가 덮거나 잘린다.
FORBIDDEN_BANDS: tuple[str, ...] = ("DEAD_TOP", "DEAD_BOTTOM")

# 밴드 경계 허용 오차(px). 글자는 폰트 어센더·디센더 때문에 선언 박스가 몇 px 흔들린다 —
# 0 으로 두면 정상 배치가 계속 fail 로 잡혀 게이트를 아무도 안 믿게 된다.
BAND_TOLERANCE_PX: int = 6


@dataclass(frozen=True)
class Box:
    """화면 위 사각형(픽셀). y2/x2 는 배타적."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def w(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def h(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2


@dataclass
class Placement:
    """보드가 실제로 그린 요소 1개. §20-7 판정의 입력이자 렌더러의 지시다."""

    kind: str          # "text" | "number" | "bar" | "rule" | "card" | "image"
    box: Box
    text: str = ""
    band: str = ""     # 의도한 밴드(판정 메시지에 쓴다)
    stage: int = 0     # 단계 등장 순서(0 = 처음부터 보임)
    meta: dict[str, Any] = field(default_factory=dict)


def band_box(name: str, *, pad_x: int = 0, pad_y: int = 0) -> Box:
    """밴드 이름 → 안전 가로폭이 적용된 박스. 밴드 밖으로 나갈 일이 없게 여기서만 만든다."""
    top, bottom = config.EXPLAINER_BANDS[name]
    x1, x2 = config.EXPLAINER_SAFE_X
    return Box(x1 + pad_x, top + pad_y, x2 - pad_x, bottom - pad_y)


def _overlaps(box: Box, band: str) -> bool:
    top, bottom = config.EXPLAINER_BANDS[band]
    return box.y1 < bottom and box.y2 > top


def core_coverage(placements: list[Placement], cell: int = 10) -> float:
    """CORE 밴드를 요소들이 **면적으로** 얼마나 덮는가(0~1). 순수 계산.

    ★ 왜 픽셀이 아니라 박스인가: 명세 §20-7 은 "CORE 비배경 픽셀 비율"로 썼지만, 글자는 획이
      얇아 잘 채운 화면도 4~5% 밖에 안 나온다(실측). 그 수치로는 "허전한 화면"을 구분할 수
      없다 — 늘 경고가 뜨거나, 임계를 낮추면 진짜 빈 화면을 놓친다. 운영자가 보는 '허전함'은
      요소가 차지한 **면적**이므로 그것을 재고, 편차는 문서에 남긴다.
    ★ 박스가 겹쳐도 두 번 세지 않도록 격자에 찍어 센다(합집합 면적).
    ★ 배경 패널(kind="panel")은 세지 않는다. 그건 CORE 를 통째로 덮으므로 넣으면 이 지표가
      항상 100% 가 돼 쓸모가 없어진다 — 지표를 만족시키려고 지표를 무의미하게 만드는 꼴이다.
      배경이 실제로 화면을 채웠는지는 visual_contract.validate_frame 의 픽셀 판정이 본다.
    """
    placements = [p for p in placements if p.kind != "panel"]
    top, bottom = config.EXPLAINER_BANDS["CORE"]
    x1, x2 = config.EXPLAINER_SAFE_X
    cols = max(1, (x2 - x1) // cell)
    rows = max(1, (bottom - top) // cell)
    grid = bytearray(cols * rows)
    for p in placements:
        b = p.box
        c0 = max(0, (b.x1 - x1) // cell)
        c1 = min(cols, (b.x2 - x1 + cell - 1) // cell)
        r0 = max(0, (b.y1 - top) // cell)
        r1 = min(rows, (b.y2 - top + cell - 1) // cell)
        for r in range(r0, r1):
            base = r * cols
            for c in range(c0, c1):
                grid[base + c] = 1
    return sum(grid) / float(cols * rows)


def evaluate_layout(placements: list[Placement],
                    core_fill_ratio: float | None = None) -> dict[str, list[str]]:
    """§20-7 렌더 QA. 반환: {"fail": [...], "warn": [...]}.

    fail 은 **되돌릴 수 없는 것**만 담는다 — 잘리거나, UI 에 가려지거나, 화면이 비었거나.

    ★ "허전한 화면"이 fail 로 올라온 이력(v3 §9 · P3-b). 예전에는 warn 이었고 주석에
      "허전함은 경고지 차단이 아니다"라고 적혀 있었다. 그 정책 아래 CORE 충전율 0.235 짜리
      화면이 `fail: []` 로 통과해 그대로 발행됐다. **발행되고 나면 그것도 되돌릴 수 없다** —
      경고는 아무도 안 읽고, 읽어도 이미 나간 뒤였다. 그래서 차단으로 올렸다.
      기준값 0.25 는 저장된 지시서를 실제로 그려 낸 분포에서 정했다:
      docs/measure-core-fill-2026-08-03.md. **이 승격을 되돌리기 전에 그 문서를 읽을 것.**

    core_fill_ratio 를 주면 렌더러가 잰 값을 쓴다(안 주면 여기서 계산한다).
    """
    fails: list[str] = []
    warns: list[str] = []
    _, safe_x2 = config.EXPLAINER_SAFE_X
    safe_x1 = config.EXPLAINER_SAFE_X[0]

    for p in placements:
        label = f"{p.kind}('{p.text[:14]}')" if p.text else p.kind
        for band in FORBIDDEN_BANDS:
            if _overlaps(p.box, band):
                fails.append(f"band_violation:{band}:{label}")
        if p.box.x2 > safe_x2:
            fails.append(f"safe_x_overflow:{p.box.x2}>{safe_x2}:{label}")
        if p.box.x1 < safe_x1:
            fails.append(f"safe_x_underflow:{p.box.x1}<{safe_x1}:{label}")

    # 출처 바는 SOURCE 밴드 안에 있어야 한다. 바닥에 붙으면 UI 에 가려진다.
    for p in placements:
        if p.band == "SOURCE" and not _inside(p.box, "SOURCE"):
            fails.append(f"source_bar_outside_band:{p.box.y1}-{p.box.y2}")

    # ★ 자기가 선언한 밴드를 넘는 요소 — 이게 없어서 놓친 결함이 있다: CORE 배경 패널이 위로
    #   16px 튀어나와 TITLE 밴드 2줄짜리 제목의 아랫줄을 덮었다. 위 검사들은 "금지 밴드 침범"
    #   과 "가로 초과"만 봐서 전부 통과했고, 프레임을 눈으로 봐야만 드러났다. 밴드를 선언한
    #   요소는 그 밴드 안에 있어야 한다 — 안 그러면 밴드 그리드가 이름뿐이다.
    for p in placements:
        if not p.band or p.band in FORBIDDEN_BANDS or p.band not in config.EXPLAINER_BANDS:
            continue
        top, bottom = config.EXPLAINER_BANDS[p.band]
        if p.box.y1 < top - BAND_TOLERANCE_PX or p.box.y2 > bottom + BAND_TOLERANCE_PX:
            label = f"{p.kind}('{p.text[:14]}')" if p.text else p.kind
            fails.append(
                f"band_overflow:{p.band}:{p.box.y1}-{p.box.y2}∉{top}-{bottom}:{label}")

    coverage = core_fill_ratio if core_fill_ratio is not None else core_coverage(placements)
    if coverage < config.EXPLAINER_CORE_MIN_FILL:
        # warn → fail 승격(v3 §9). 위 docstring 의 이력을 읽고 나서 되돌릴 것.
        fails.append(f"core_underfilled:{coverage:.2f}")

    return {"fail": sorted(set(fails)), "warn": sorted(set(warns))}


def _inside(box: Box, band: str) -> bool:
    top, bottom = config.EXPLAINER_BANDS[band]
    return box.y1 >= top and box.y2 <= bottom


# ★ 줄바꿈·자동 축소 함수는 **여기서 없앴다**(v3.4 §22 K9).
#   이전에는 글자 수로 폭을 근사해 줄을 나누고, 넘치면 마지막 줄에 말줄임(…)을 붙였다. 두 가지가
#   다 틀렸다: ① 한글은 글자당 폭이 라틴의 두 배 가까워 글자 수 근사가 안전선을 넘겼고(실측
#   x=930 → 1268px), ② 말줄임은 화면에서 정보를 조용히 지운다 — 시청자는 무엇이 잘렸는지
#   모른다. 이제 폭은 폰트 메트릭으로만 재고(visual_contract.fit_text), 담기지 않으면 잘라내는
#   대신 예외를 던져 "대본 문장을 줄여라"는 신호로 되돌린다.


def stage_durations(total_sec: float, stages: int) -> list[float]:
    """단계 등장 길이 배분. 총합은 정확히 total_sec 이어야 한다.

    ★ 총합이 나레이션 실측과 어긋나면 clip_fit 이 보정에 들어가 줌·페이드가 붙고, 그 순간
      밴드 좌표가 깨진다(assemble.clip_fit_video_filter). 그래서 마지막 단계로 잔차를 흡수한다.
    """
    stages = max(1, min(int(stages), config.EXPLAINER_STAGE_MAX))
    total = max(float(total_sec), config.EXPLAINER_STAGE_MIN_SEC * stages)
    if stages == 1:
        return [round(total, 3)]
    # 첫 단계를 조금 길게(정보가 자리잡을 시간), 나머지는 균등.
    head = max(config.EXPLAINER_STAGE_MIN_SEC, total * 0.34)
    rest = (total - head) / (stages - 1)
    out = [round(head, 3)] + [round(rest, 3) for _ in range(stages - 2)]
    out.append(round(total - sum(out), 3))
    return out
