# -*- coding: utf-8 -*-
"""visual_contract.py — 하루한리포트 explainer 시각 구현 계약 (규범적 · normative)

이 모듈은 명세서 §20~§22의 **실행 가능한 형태**다. 산문 명세와 충돌하면 이 코드가 우선한다.
렌더러는 반드시 이 모듈의 상수·함수를 사용해야 하며, 자체 좌표/폰트 로직을 재구현하지 않는다.

해결하는 실패 (2026.07.30 실출력 검수에서 실측):
  F1 폰트 폴백 → 모노스페이스로 렌더  → load_font() 하드 실패
  F2 절대좌표 밴드가 해상도 바뀌며 깨짐 → 비율 기반 Band
  F3 자막 "..." 잘림                    → fit_text() 축소, 말줄임 금지
  F4 제목/본문 문장 중복                 → assert_no_duplicate_text()
  F5 차트 축·기준선·so_what 부재         → CHART_MIN 요건 + validate_chart_spec()
  F6 레터박스/블리드                     → validate_frame()

────────────────────────────────────────────────────────────────────────────
저장소 반영 시 기록한 편차 3건 (§22-1 "모듈이 우선" 원칙을 지키되 배선만 맞춘 것):

  A1  PIL import 를 **지연 import** 로 바꿨다. 이 모듈이 engine/config.py 에서 참조되고,
      config 는 수집·채점 잡도 import 한다. 원본처럼 모듈 최상단에서 PIL 을 당기면 렌더와
      무관한 잡이 Pillow 에 묶인다. 저장소 관례와 같다(engine/crop.py, board_render.py).
      `from __future__ import annotations` 덕에 타입 주석은 평가되지 않는다. 동작 동일.

  A2  FONT_DIR 기본값을 **저장소 루트 기준 절대경로**로 해소한다. 원본의 상대경로
      "assets/fonts" 는 워커 cwd 에 따라 빗나가고, 그 결과가 하필 K8 이 막으려는 "폰트 없음"
      이라 진짜 결함과 구분되지 않는다. 환경변수 EXPLAINER_FONT_DIR 오버라이드는 그대로다.

  A3  num_ko 를 **Pretendard-Black** 으로 명시 지정한다. 원본이 지정한 SCDream9(에스코어드림
      9 Black)은 라이선스 미확인 상태다(docs/deviation-fin-visual-v1.md FVD2). §22-2 는
      "숫자 폰트 라이선스 미확정 시 대체 폰트를 **명시적으로 지정**하고 기록 — 침묵 폴백
      금지"를 허용한다. 여기 적는 것이 그 기록이고, 파일이 없으면 여전히 예외로 죽는다.
      라이선스가 확정되면 FONT_FILES 한 줄만 되돌리면 된다.

  A4  fit_text() 의 합격 조건에 "각 줄이 실제로 max_w 안에 든다"를 추가했다. wrap_by_width 는
      `or not cur` 때문에 **한 어절이 max_w 보다 길면 그 어절만으로 한 줄을 만든다** — 줄 수는
      기준을 통과하지만 글자는 안전선 밖으로 나간다. 이것이 v3.3 구현에서 한글이 x=930 을
      1268px 까지 넘긴 그 결함이다(F2). 줄 수만 보면 못 잡는다. 못 담으면 K9 대로 예외.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Sequence

# ─────────────────────────────────────────────────────────────
# 0. 캔버스 & 디자인 토큰
# ─────────────────────────────────────────────────────────────
CANVAS = (1080, 1920)          # 기준 해상도. 다른 해상도로 렌더하려면 비율 상수만 쓸 것.

# ★ TOKENS 가 색의 **유일한 원본**이다 (v3 §7-4 · §22-1 "산문 명세와 충돌하면 모듈이 이긴다").
#
# 왜 여기로 모았나: 색이 세 곳에 있었다 — 이 파일의 상수들, `config.FIN_TOKEN_*`(hex 문자열),
# 그리고 `board_render.render_board` 안의 dict 리터럴. 앞의 둘은 값이 같았지만 board_render 의
# `fg`·`muted` 는 이 파일의 `WHITE`·`GRAY` 와 **달랐다**. 화면에 실제로 나가는 것은 board_render
# 쪽이었고, 이 파일의 색 상수 7종은 **참조가 0건인 죽은 값**이었다.
#
# ★ 그래서 통일 방향을 뒤집었다 — 죽은 상수의 값을 채택하면 픽셀이 바뀐다.
#   **실제로 렌더되던 값**을 정본으로 올리고, 죽은 상수는 여기를 가리키는 별칭으로 남긴다.
#   덕분에 이 통합은 화면을 한 점도 바꾸지 않는다(tests/test_board_render_golden.py 가 고정).
TOKENS: dict[str, tuple[int, int, int]] = {
    "bg":     (11, 18, 32),      # #0B1220
    "bg_dim": (8, 13, 24),
    "accent": (255, 176, 32),    # #FFB020  강조·위험·핵심수치 전용 (운영자 결정: 현행 유지)
    "point":  (59, 130, 246),    # #3B82F6
    "fg":     (238, 242, 247),   # ← board_render 가 실제로 쓰던 값
    "muted":  (156, 170, 188),   # ← board_render 가 실제로 쓰던 값
    "caption_hl": (255, 224, 0),  # #FFE000  자막 활성 어절
    # 신규(§7-4). panel 은 지금까지 그릴 때마다 계산했고, danger 는 아예 없어서 위험 표시가
    # accent 와 같은 색이었다 — "강조"와 "위험"이 화면에서 구분되지 않았다.
    "panel":  (18, 26, 43),
    "danger": (239, 68, 68),     # #EF4444
}

# 하위호환 별칭. 참조 0건이라 지워도 됐지만, 외부 문서·명세가 이 이름으로 색을 부르므로
# 이름은 남기고 값만 TOKENS 에서 끌어온다(두 벌이 갈라지는 것을 구조적으로 막는다).
BG          = TOKENS["bg"]
BG_DIM      = TOKENS["bg_dim"]
AMBER       = TOKENS["accent"]
BLUE        = TOKENS["point"]
CAPTION_HL  = TOKENS["caption_hl"]
WHITE       = TOKENS["fg"]
GRAY        = TOKENS["muted"]
DGRAY       = (100, 112, 130)


def token_hex(name: str) -> str:
    """TOKENS 값을 '#RRGGBB' 로. config.FIN_TOKEN_* 이 hex 문자열을 요구한다."""
    r, g, b = TOKENS[name]
    return f"#{r:02X}{g:02X}{b:02X}"

# ─────────────────────────────────────────────────────────────
# 1. 비율 기반 밴드 그리드  (§20-3을 해상도 독립으로 재정의)
#    y_ratio = y / height,  x_ratio = x / width
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Band:
    name: str
    top: float      # y 비율
    bottom: float
    allow_content: bool

BANDS: tuple[Band, ...] = (
    Band("DEAD_TOP",     0.000, 0.112, False),  # 0~215px
    Band("META",         0.112, 0.172, True),   # 킥커 / 시리즈 배지
    Band("TITLE",        0.172, 0.260, True),   # 보드 제목 (≤2줄)
    Band("CORE",         0.260, 0.615, True),   # 차트·대형숫자 = 주인공
    Band("SOWHAT",       0.615, 0.672, True),   # so_what 한 줄
    Band("CAPTION",      0.672, 0.729, True),   # 나레이션 자막 (≤2줄)
    Band("SOURCE",       0.729, 0.781, True),   # 출처+면책 바
    Band("DEAD_BOTTOM",  0.781, 1.000, False),  # 유튜브/틱톡 UI 구역
)
X_LEFT_R, X_RIGHT_R = 0.083, 0.861   # 90px ~ 930px  (우측 버튼 스택 회피)
CORE_ANCHOR_R = 0.437                # 시각 무게중심 y (≈840px)
CORE_MIN_FILL = 0.30                 # CORE 밴드 최소 비배경 **픽셀** 비율 (미만 → warn)
# ★ 면적 기준은 픽셀 기준과 **다른 척도라 상수도 따로 둔다.** 글자는 획이 얇아 잘 채운
#   화면도 픽셀로는 4~5% 밖에 안 나온다(board_layout.core_coverage 주석). 두 검사가 값 하나를
#   공유하면 한쪽 기준을 손볼 때 다른 쪽 판정이 말없이 함께 움직인다.
#   0.25 는 실측 분포에서 정한 값이다 — docs/measure-core-fill-2026-08-03.md.
CORE_MIN_AREA_FILL = 0.25            # CORE 밴드 최소 요소 **면적** 점유율 (미만 → fail)

def band(name: str) -> Band:
    for b in BANDS:
        if b.name == name:
            return b
    raise KeyError(f"unknown band: {name}")

def y_of(band_name: str, pos: float = 0.5, height: int = CANVAS[1]) -> int:
    """밴드 내 상대 위치(0=상단,1=하단)를 절대 y로. 렌더러는 반드시 이걸로 좌표를 얻는다."""
    b = band(band_name)
    return int((b.top + (b.bottom - b.top) * pos) * height)

def x_bounds(width: int = CANVAS[0]) -> tuple[int, int]:
    return int(X_LEFT_R * width), int(X_RIGHT_R * width)

def content_box(width: int = CANVAS[0], height: int = CANVAS[1]) -> tuple[int, int, int, int]:
    x0, x1 = x_bounds(width)
    return x0, int(band("META").top * height), x1, int(band("SOURCE").bottom * height)

# ─────────────────────────────────────────────────────────────
# 2. 폰트 계약 — 폴백 금지 (F1)
# ─────────────────────────────────────────────────────────────
# A2: 상대경로가 아니라 저장소 루트 기준. engine/ 의 부모가 루트다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.environ.get("EXPLAINER_FONT_DIR") or os.path.join(_REPO_ROOT, "assets", "fonts")
FONT_FILES = {
    # A3: SCDream9(에스코어드림 9 Black) 라이선스 미확인 → Pretendard-Black 명시 지정.
    "num_ko":   "Pretendard-Black.otf",      # 대형 숫자 KO (원 지정: SCDream9.otf)
    "num_en":   "Anton-Regular.ttf",         # 대형 숫자 EN
    "head":     "Pretendard-ExtraBold.otf",  # 제목·자막
    "body":     "Pretendard-Bold.otf",
    "small":    "Pretendard-Medium.otf",     # 출처·면책·라벨
}

class FontContractError(RuntimeError):
    pass

_cache: dict = {}

def load_font(role: str, size: int):
    """
    지정 폰트를 로드한다. 파일이 없으면 **예외를 던진다** — 절대 기본 폰트로 폴백하지 않는다.
    (실출력 결함 F1: 폴백된 모노스페이스가 조용히 렌더되어 미학 전체가 붕괴)
    """
    from PIL import ImageFont   # A1 지연 import

    key = (role, size)
    if key in _cache:
        return _cache[key]
    if role not in FONT_FILES:
        raise FontContractError(f"unknown font role: {role}")
    path = os.path.join(FONT_DIR, FONT_FILES[role])
    if not os.path.exists(path):
        raise FontContractError(
            f"REQUIRED FONT MISSING: {path}\n"
            f"→ 렌더를 중단한다. 폴백 렌더 금지(§22 K8). 폰트 자산을 배치한 뒤 재시도할 것."
        )
    f = ImageFont.truetype(path, size)
    _cache[key] = f
    return f

def preflight_fonts() -> None:
    """파이프라인 시작 시 1회 호출. 하나라도 없으면 즉시 실패."""
    missing = [n for n in FONT_FILES.values() if not os.path.exists(os.path.join(FONT_DIR, n))]
    if missing:
        raise FontContractError(f"missing fonts: {missing} (dir={FONT_DIR})")

# ─────────────────────────────────────────────────────────────
# 3. 텍스트 — 말줄임 금지, 축소·줄바꿈으로 해결 (F3)
# ─────────────────────────────────────────────────────────────
def text_size(draw, s: str, font) -> tuple[int, int]:
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0], b[3] - b[1]


def text_ink_span(draw, s: str, font) -> tuple[int, int]:
    """draw.text((x, y), …) 로 그렸을 때 **글자가 실제로 차지하는** (위, 아래) 오프셋.

    ★ 왜 필요한가: `text_size` 는 잉크의 높이만 준다. 그런데 `draw.text` 는 그 높이가 아니라
      **줄 상자의 위쪽**을 기준점으로 삼는다. 큰 폰트일수록 그 둘의 차이(윗여백)가 커서,
      `y + text_size()[1]` 을 "글자 아래"로 쓰면 실제보다 한참 위를 가리킨다.
      실측: Anton 220pt 의 "18.5%" 는 bbox=(0, 67, 573, 262) 이라 높이는 195 지만 실제 바닥은
      262 다 — 67px 차이. 이 오차 때문에 숫자 밑에 그리던 밑줄과 라벨이 숫자 위로 올라타
      NUMBER_BOARD·CHART_BOARD 의 글자가 서로 겹쳤다(실측 화면으로 확인).
    """
    b = draw.textbbox((0, 0), s, font=font)
    return b[1], b[3]

def wrap_by_width(draw, s: str, font, max_w: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_size(draw, t, font)[0] <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines

def fit_text(draw, s: str, role: str, base_size: int, max_w: int,
             max_lines: int = 2, min_size: int = 28):
    """
    폭·줄수에 맞을 때까지 폰트를 줄여가며 (font, lines)를 반환.
    말줄임표('...')를 쓰지 않는다 — 정보 소실 금지(§22 K9).
    최소 크기에서도 초과하면 예외 → 대본 단계에서 문장을 줄여야 한다는 신호.
    """
    size = base_size
    while size >= min_size:
        f = load_font(role, size)
        lines = wrap_by_width(draw, s, f, max_w)
        if len(lines) <= max_lines and all(text_size(draw, ln, f)[0] <= max_w for ln in lines):
            return f, lines
        size -= 2
    raise ValueError(
        f"TEXT TOO LONG for {max_lines} lines @min {min_size}px: {s!r}\n"
        f"→ 렌더에서 자르지 말고 대본을 줄일 것."
    )

def normalize(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())

def is_duplicate_text(a: str, b: str) -> bool:
    """두 문장이 같은 화면에 함께 뜨면 K10 위반인가.

    ★ 레이아웃이 "무엇을 어느 밴드에 둘지" 정할 때 쓰는 판정과 킬 스위치가 쓰는 판정은
      **같은 함수여야 한다.** 레이아웃이 완전일치(!=)로만 피하면 포함관계(제목이 본문의
      앞부분과 같은 흔한 사고)는 그대로 통과해 렌더 마지막에 잡이 죽는다.
    """
    na, nb = normalize(a or ""), normalize(b or "")
    if len(na) < 8 or len(nb) < 8:
        return False
    return na == nb or na in nb or nb in na

def assert_no_duplicate_text(*blocks: str) -> None:
    """
    같은 프레임 안에서 제목/본문/인용/자막이 동일 문장을 반복하면 실패 (F4).
    자막은 설명판 문장을 복제하지 않는다 — 차트가 숫자를 보이면 자막은 의미를 말한다.
    """
    seen: list[str] = []
    for b in blocks:
        if len(normalize(b or "")) < 8:
            continue
        for prev in seen:
            if is_duplicate_text(prev, b):
                raise ValueError(f"DUPLICATE ON-SCREEN TEXT: {prev!r} ↔ {b!r}")
        seen.append(b)

# ─────────────────────────────────────────────────────────────
# 4. 자막 — 2어절 하이라이트 윈도우 (§20-5)
# ─────────────────────────────────────────────────────────────
HL_HOLD = 0.12   # 어절 종료 후 하이라이트 잔류(초)

def highlight_indices(words: Sequence[dict], t: float) -> set[int]:
    """활성 어절 + 직전 어절 = 항상 2개. 첫 어절이면 {i, i+1}로 선행 표시."""
    active = None
    for i, w in enumerate(words):
        if w["t"] <= t < w["t"] + w["d"] + HL_HOLD:
            active = i
    if active is None:
        for i, w in enumerate(words):
            if w["t"] <= t:
                active = i
    if active is None:
        return set()
    if active == 0 and len(words) > 1:
        return {0, 1}
    return {active - 1, active} if active > 0 else {active}

def chunk_words(words: Sequence[dict], max_words: int = 4,
                gap_break: float = 0.28, tail_max: float = 0.5) -> list[dict]:
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = (words[i+1]["t"] - (w["t"] + w["d"])) if i + 1 < len(words) else 1.0
        if len(cur) >= max_words or nxt > gap_break:
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        t1 = g[-1]["t"] + g[-1]["d"]
        gap = (groups[i+1][0]["t"] - t1) if i + 1 < len(groups) else tail_max
        out.append({"words": g, "t0": g[0]["t"], "t1": t1 + min(max(gap, 0), tail_max)})
    return out

# ─────────────────────────────────────────────────────────────
# 5. 차트 최소 요건 (F5)
# ─────────────────────────────────────────────────────────────
CHART_MIN = {
    "baseline": True,        # 기준선/축 필수 — 막대만 떠 있으면 안 됨
    "value_labels": True,    # 각 계열 값 라벨
    "unit_label": True,      # 단위(%, 억 달러, 배 …) 명시
    "so_what": True,         # 숫자 아래 의미 한 줄
    "source": True,          # 출처+페이지
    "max_series": 3,
    "bar_max_width_r": 0.22, # 막대 폭 ≤ 화면폭 22% (거대 사각형 금지)
    "bar_gap_r": 0.06,
    "emphasis_series": 1,    # 앰버 강조는 1개 계열만
}

def validate_chart_spec(spec: dict) -> list[str]:
    errs = []
    for k in ("baseline", "value_labels", "unit_label", "so_what", "source"):
        if not spec.get(k):
            errs.append(f"chart missing required element: {k}")
    if len(spec.get("series", [])) > CHART_MIN["max_series"]:
        errs.append("too many series (>3)")
    if spec.get("bar_width_r", 0) > CHART_MIN["bar_max_width_r"]:
        errs.append("bar too wide (>22% of width) — 거대 사각형 금지")
    if spec.get("emphasis_count", 1) > CHART_MIN["emphasis_series"]:
        errs.append("amber emphasis must be a single series")
    return errs

# ─────────────────────────────────────────────────────────────
# 6. 프레임 검증 — 렌더 QA 게이트 (F6 · §20-7 · §21 K3)
# ─────────────────────────────────────────────────────────────
def _luma(px) -> float:
    r, g, b = px[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def _dark_ratio(im, box, thr: int = 8) -> float:
    """박스 영역에서 휘도 < thr 인 픽셀 비율 (히스토그램 기반 — 대용량 프레임에서도 빠름)."""
    g = im.crop(box).convert("L")
    h = g.histogram()
    tot = sum(h) or 1
    return sum(h[:thr]) / tot

def _content_ratio(im, box, bg_luma: float, delta: int = 26) -> float:
    """배경 휘도에서 delta 이상 벗어난 픽셀 비율 = '콘텐츠'로 간주."""
    g = im.crop(box).convert("L")
    h = g.histogram()
    tot = sum(h) or 1
    lo, hi = int(bg_luma - delta), int(bg_luma + delta)
    inside = sum(h[max(lo, 0):min(hi + 1, 256)])
    return 1 - inside / tot

def validate_frame(img, bg=BG) -> dict:
    """
    반환: {"fail": [...], "warn": [...]}  — fail 이 하나라도 있으면 렌더 차단.
    """
    im = img.convert("RGB")
    W, H = im.size
    bgl = _luma(bg)
    fails, warns = [], []

    if abs(W / H - 9 / 16) > 0.01:
        fails.append(f"aspect ratio not 9:16 ({W}x{H})")

    # K3 레터박스: 상·하단 스트립이 순수 검정으로 덮였는가
    for label, y0, y1 in (("top", 0, int(0.104 * H)), ("bottom", int(0.896 * H), H)):
        r = _dark_ratio(im, (0, y0, W, y1))
        if r > 0.90:
            fails.append(f"letterbox detected ({label} strip {r:.0%} pure black)")

    # DEAD 밴드 콘텐츠 침범
    for b in BANDS:
        if b.allow_content:
            continue
        y0, y1 = int(b.top * H), int(b.bottom * H)
        if y1 - y0 < 4:
            continue
        r = _content_ratio(im, (0, y0, W, y1), bgl)
        if r > 0.06:
            fails.append(f"content in {b.name} band ({r:.1%}) — UI 가림 위험")

    # 우측 세이프존 침범
    x1 = int(X_RIGHT_R * W)
    r = _content_ratio(im, (x1, int(0.112 * H), W, int(0.781 * H)), bgl)
    if r > 0.10:
        warns.append(f"content beyond x={x1} ({r:.0%}) — 쇼츠 버튼과 겹칠 수 있음")

    # CORE 밀도 (허전한 화면 감지)
    cb = band("CORE")
    fill = _content_ratio(im, (0, int(cb.top * H), W, int(cb.bottom * H)), bgl, delta=20)
    if fill < CORE_MIN_FILL:
        warns.append(f"CORE band sparse ({fill:.0%} < {CORE_MIN_FILL:.0%}) — 요소를 키우거나 배경을 채울 것")

    return {"fail": fails, "warn": warns}

# ─────────────────────────────────────────────────────────────
# 7. 스모크 테스트 — 파이프라인 착수 전 1회 통과 필수
# ─────────────────────────────────────────────────────────────
def smoke_test() -> None:
    from PIL import Image, ImageDraw   # A1 지연 import

    preflight_fonts()
    im = Image.new("RGB", CANVAS, BG)
    d = ImageDraw.Draw(im)
    f, lines = fit_text(d, "클라우드 성장이 둔화되지 않고 오히려 가속되고 있습니다",
                        "head", 62, x_bounds()[1] - x_bounds()[0])
    y = y_of("CAPTION", 0.2)
    for i, ln in enumerate(lines):
        d.text((CANVAS[0] // 2, y + i * (f.size + 10)), ln, font=f, fill=WHITE, anchor="ma")
    assert_no_duplicate_text("클라우드 부문이 폭발적인 성장을 주도", "Azure 연간 성장률")
    r = validate_frame(im)
    assert not r["fail"], r["fail"]
    print("smoke_test OK", r)

if __name__ == "__main__":
    smoke_test()
