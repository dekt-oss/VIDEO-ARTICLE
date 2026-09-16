"""클립 길이 보정 전략 — 타입 계약 (FREEZE). 수정명세 v1 §3-3 / §4.

이 파일은 **경계 계약**이다. 판정 로직(`decide_strategy`)의 구현체는 `engine/clip_fit.py`
(소유: Codex, 순수 함수 + 경계값 단위테스트)에 있고, 소비자(`engine/render.py`,
`engine/assemble.py`, `engine/render_qa.py`, 소유: Claude Code)는 여기 정의된 타입만 본다.
→ 한쪽이 바뀌어도 다른 쪽이 깨지지 않게 하려면 이 파일을 고치지 말 것(FREEZE).

계약:
    decide_strategy(clip_sec: float, narration_sec: float, loop_safe: bool) -> Strategy

  - 순수 함수. I/O·ffmpeg 호출·파일 접근 금지.
  - 임계값은 매직넘버 금지 규약에 따라 `engine/config` 에서 읽는다
    (CLIP_FIT_HOLD_RATIO_MAX=0.15, CLIP_FIT_PINGPONG_RATIO_MAX=0.60, CLIP_FIT_TRIM_FADE_SEC=0.2).
  - 경계값(`ratio` 가 정확히 0 / 0.15 / 0.60)은 **아래 구간 정의대로 하한 포함·상한 포함**이다:
      ratio <= 0                          → trim
      0 < ratio <= HOLD_RATIO_MAX         → hold
      HOLD_RATIO_MAX < ratio <= PP_MAX    → pingpong (loop_safe=False 면 hold 로 폴백)
      ratio > PINGPONG_RATIO_MAX          → flagged
  - `narration_sec <= 0` 은 호출측 결함이다. 방어적으로 trim(target=clip_sec)을 돌려도 되고
    ValueError 를 올려도 된다 — 소비자는 두 경우 모두 렌더를 막지 않는다.
  - **`fade_out_sec` 은 실제로 잘라내는 경우에만 > 0 이다.** `ratio == 0`(클립과 나레이션 길이가
    같음 — Manim 클립은 나레이션 실측으로 렌더되므로 항상 이 경우다)은 잘라낼 것이 없으니
    페이드도 넣지 않는다. 넣으면 컷마다 끝이 0.2s 검게 죽어 경계가 번쩍인다.
    소비자(`assemble.clip_fit_video_filter`)도 같은 조건으로 한 번 더 막지만, 판정에서 0 으로 주는 게 맞다.

불변식(모든 kind 공통):
  - `target_sec` == narration_sec (나레이션이 타임라인의 주인). flagged 도 마찬가지 —
    보정을 하지 않을 뿐 컷 화면 시간은 여전히 나레이션 길이다(뒤가 정지/검은 화면이 되지 않게
    소비자가 hold 로 채운다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

# 전략 enum. 로그·QA·DB 에 이 문자열 그대로 남는다(변경 금지).
StrategyKind = Literal["trim", "hold", "pingpong", "flagged"]
STRATEGY_KINDS: tuple[str, ...] = ("trim", "hold", "pingpong", "flagged")


@dataclass(frozen=True)
class Strategy:
    """컷 1개의 길이 보정 결정. 순수 데이터 — ffmpeg 인자는 assemble.py 가 이걸 보고 만든다."""

    kind: StrategyKind
    clip_sec: float          # 입력 클립 실측 길이(ffprobe)
    narration_sec: float     # TTS 실측 길이
    ratio: float             # (narration_sec - clip_sec) / narration_sec
    target_sec: float        # 컷 최종 화면 시간 — 항상 narration_sec
    hold_sec: float = 0.0    # kind='hold' 일 때 마지막 프레임으로 채울 초(>0)
    loops: int = 0           # kind='pingpong' 일 때 정+역 왕복 횟수(>=1)
    fade_out_sec: float = 0.0  # kind='trim' 일 때 끝 페이드아웃 초
    ken_burns: bool = False  # hold 구간에 켄번스(zoom 1.00→1.04)를 얹을지
    note: str = ""           # 사람이 읽는 판정 근거(로그·QA 표시용)

    def as_log_row(self) -> dict[str, Any]:
        """§3-6 렌더 로그/QA 행. 전략 선택이 사후 검증 가능해야 한다."""
        return {
            "clip_sec": round(float(self.clip_sec), 3),
            "narration_sec": round(float(self.narration_sec), 3),
            "ratio": round(float(self.ratio), 4),
            "strategy": self.kind,
            "note": self.note,
        }


class DecideStrategy(Protocol):
    """`engine.clip_fit.decide_strategy` 가 만족해야 하는 시그니처."""

    def __call__(self, clip_sec: float, narration_sec: float,
                 loop_safe: bool) -> Strategy: ...


# ─────────────────────────────────────────────────────────────
# 보수적 폴백 — `engine/clip_fit.py`(Codex 인계분) 미배선 구간용.
# ★ 이 함수는 계약의 일부가 아니다. clip_fit.py 가 들어오면 소비자는 그것만 쓴다.
#   trim/hold 만 내주므로 "나레이션이 잘리거나 영상이 먼저 끝나는 컷 = 0" 은 지키되,
#   pingpong·flagged 판정은 하지 않는다(=현재 동작과 동등 + 트림 페이드아웃만 추가).
# ─────────────────────────────────────────────────────────────
def fallback_decide_strategy(clip_sec: float, narration_sec: float,
                             loop_safe: bool = False) -> Strategy:
    from . import config  # 지연 import — 이 모듈은 계약만 들고 config 에 묶이지 않는다

    n = max(float(narration_sec), 1e-6)
    c = max(float(clip_sec), 0.0)
    ratio = (n - c) / n
    if ratio <= 0:
        # ★ 실제로 잘라낼 때만 페이드. clip_sec == narration_sec(Manim 클립의 일반 케이스)면
        #   자를 게 없으니 페이드도 없다 — 넣으면 컷마다 끝이 검게 죽는다.
        fade = config.CLIP_FIT_TRIM_FADE_SEC if c > n else 0.0
        return Strategy(kind="trim", clip_sec=c, narration_sec=n, ratio=ratio, target_sec=n,
                        fade_out_sec=fade,
                        note="clip_fit 미배선 폴백: 트림" + ("" if fade else "(자를 것 없음)"))
    return Strategy(kind="hold", clip_sec=c, narration_sec=n, ratio=ratio, target_sec=n,
                    hold_sec=n - c, ken_burns=True,
                    note="clip_fit 미배선 폴백: 홀드(핑퐁·플래그 판정 없음)")


def decide(clip_sec: float, narration_sec: float, loop_safe: bool = False) -> Strategy:
    """소비자용 단일 진입점. `engine.clip_fit` 이 있으면 그것을, 없으면 보수 폴백을 쓴다."""
    try:
        from .clip_fit import decide_strategy  # type: ignore[attr-defined]
    except ImportError:
        from .util import log
        log.warning("engine/clip_fit.py 미배선 → 보수 폴백(trim/hold 만). "
                    "핑퐁·QA 플래그는 clip_fit 인계 후 활성화된다.")
        return fallback_decide_strategy(clip_sec, narration_sec, loop_safe)
    return decide_strategy(clip_sec, narration_sec, loop_safe)


__all__ = ["Strategy", "StrategyKind", "STRATEGY_KINDS", "DecideStrategy",
           "decide", "fallback_decide_strategy"]
