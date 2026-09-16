"""설명판 모션 타임라인 — §9 모션 규칙 (v3.4).

왜 이 모듈이 생겼는가 — 실측된 사고:
  v3.3 구현은 보드를 **PNG 몇 장으로 만들어 툭툭 바꿨다.** 명세가 §5-2 에서 정면으로 금지한
  "정적 텍스트가 주인공인 화면"이 그대로 나왔고, 운영자 평은 "존나 허접해"였다. 스와이프 판단이
  일어나는 첫 1~2초에 화면에서 **움직이는 것이 하나도 없었다.**
  → 이제 보드는 30fps 프레임 시퀀스다. 막대는 자라고, 숫자는 올라가고, 축은 그려진다.

★ 순수 모듈이다: PIL·ffmpeg·네트워크를 모른다. "무엇이 언제 얼마나 진행됐는가"만 계산한다.
  실제로 그리는 것은 board_render.py — board_layout.py 와 같은 분리다.

§9 차트 모션 순서(문서 그대로):
  축·기준선 → 첫 데이터 → 비교 데이터 → 차이 강조 → 콜아웃 숫자 → so_what 한 줄
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Step:
    """모션 단계 1개. t0 에 시작해 t1 에 끝난다(초)."""

    name: str
    t0: float
    t1: float

    def progress(self, t: float) -> float:
        """0(시작 전) ~ 1(완료). 이 값이 곧 '막대가 얼마나 자랐나'다."""
        if t <= self.t0:
            return 0.0
        if t >= self.t1 or self.t1 <= self.t0:
            return 1.0
        return (t - self.t0) / (self.t1 - self.t0)


def ease_out_cubic(p: float) -> float:
    """빠르게 시작해 부드럽게 멈춘다. 막대 성장·카운트업의 기본 이징.

    ★ 왜 선형이 아닌가: 선형은 기계가 그린 티가 난다. 끝에서 감속해야 눈이 '도착'을 인지한다.
    """
    p = min(1.0, max(0.0, p))
    return 1.0 - (1.0 - p) ** 3


def ease_out_back(p: float, overshoot: float = 1.12) -> float:
    """살짝 넘어갔다 돌아온다 — 콜아웃 숫자가 '팍' 박히는 느낌.

    ★ §9 금지 목록의 '전요소 바운스'가 아니다. 강조 요소 **하나**에만 쓴다.
    """
    p = min(1.0, max(0.0, p))
    c = overshoot
    return 1.0 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def count_up(target: float, p: float) -> float:
    """카운트업 — 0 에서 target 까지. 이징을 태워 마지막 자릿수가 천천히 멈춘다."""
    return target * ease_out_cubic(p)


def build_timeline(step_names: list[str], total_sec: float, *,
                   lead_in: float | None = None,
                   tail: float | None = None) -> dict[str, Step]:
    """단계 이름 목록 → 이름별 Step. 마지막 단계는 tail 을 남기고 끝난다.

    ★ 왜 tail 을 남기는가: 마지막 요소가 나레이션 끝과 동시에 도착하면 시청자가 그것을 읽을
      시간이 없다. §9 "나레이션보다 빠른 전환 금지"의 반대편 요구다.
    ★ 총 길이는 나레이션 실측이다. 여기서 늘리거나 줄이지 않는다 — 어긋나면 clip_fit 이
      보정에 들어가 줌·페이드가 붙고 밴드 좌표가 깨진다.
    """
    lead = config.EXPLAINER_MOTION_LEAD_IN if lead_in is None else lead_in
    tail_sec = config.EXPLAINER_MOTION_TAIL if tail is None else tail
    names = [n for n in step_names if n]
    if not names:
        return {}
    span = max(0.4, float(total_sec) - lead - tail_sec)
    dur = config.EXPLAINER_MOTION_STEP_SEC
    # 단계가 많아 span 을 넘으면 각 단계를 균등 압축한다(겹침 허용 — 멈춰 있는 것보다 낫다).
    stride = min(dur, span / max(1, len(names))) if len(names) > 1 else span
    out: dict[str, Step] = {}
    for i, name in enumerate(names):
        t0 = lead + i * stride
        out[name] = Step(name, round(t0, 3), round(min(t0 + dur, float(total_sec)), 3))
    return out


# 보드 종류별 §9 단계 순서. 없는 요소는 board_render 가 걸러낸다.
BOARD_STEPS: dict[str, tuple[str, ...]] = {
    # 축·기준선 → 첫 데이터 → 비교 데이터 → 차이 강조 → so_what
    "CHART_BOARD":      ("title", "axis", "bar0", "bar1", "diff", "sowhat"),
    "COMPARISON_BOARD": ("title", "axis", "bar0", "bar1", "diff", "sowhat"),
    # 콜아웃 숫자가 주인공 — 카운트업 먼저, 비교 막대가 뒤를 받친다
    "NUMBER_BOARD":     ("title", "number", "rule", "label", "compare", "sowhat"),
    "VALUATION_BOARD":  ("title", "number", "rule", "label", "compare", "sowhat"),
    # 근거 카드는 마스크로 열리고 문장이 뒤따른다
    "EVIDENCE_BOARD":   ("title", "card", "speaker", "body"),
}
DEFAULT_STEPS: tuple[str, ...] = ("title", "core", "metric")


def steps_for(board: str) -> tuple[str, ...]:
    return BOARD_STEPS.get(str(board or "").upper(), DEFAULT_STEPS)


def frame_times(total_sec: float, fps: int | None = None) -> list[float]:
    """프레임 시각 목록. 총 프레임 수 = round(total_sec * fps) 이어야 길이가 정확히 맞는다."""
    f = int(fps or config.EXPLAINER_MOTION_FPS)
    n = max(1, int(round(float(total_sec) * f)))
    return [i / f for i in range(n)]
