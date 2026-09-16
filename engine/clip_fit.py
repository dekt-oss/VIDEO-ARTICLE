"""클립 길이 보정 판정 (수정명세 v1 §3-3). 순수 함수 — I/O·ffmpeg·파일 접근 없음.

무엇을 푸는가: 생성된 클립 길이와 나레이션 길이는 거의 항상 다르다. Veo 는 4·8초 티어로만
주고 나레이션은 3.7초·9.2초처럼 나온다. 그 갭을 **무엇으로 메울지**가 이 모듈의 전부다.

    클립이 더 길다        → 자른다(trim). 잘린 끝은 페이드아웃
    조금 짧다             → 마지막 프레임을 홀드. 정지 티가 나지 않게 켄번스를 얹는다
    꽤 짧은데 루프 안전    → 정·역 왕복(pingpong)으로 채운다
    너무 짧다             → 보정으로 못 메운다. 플래그를 세워 사람이 본다

★ 계약은 `engine/clip_fit_types.py` 에 **동결**돼 있다(FREEZE). 이 파일은 그 계약의 구현체다 —
  타입·경계값·불변식을 여기서 바꾸지 않는다. 소비자(render·assemble·render_qa)는 계약만 본다.

★ 임계값은 전부 `engine/config` 에서 읽는다(매직넘버 금지 규약). 경계는 계약이 못박은 대로
  **하한 배타·상한 포함**이다:

      ratio <= 0                          → trim
      0 < ratio <= HOLD_RATIO_MAX         → hold
      HOLD_RATIO_MAX < ratio <= PP_MAX    → pingpong (loop_safe=False 면 hold 로 폴백)
      ratio > PINGPONG_RATIO_MAX          → flagged

★ `fade_out_sec` 은 **실제로 잘라낼 때만** > 0 이다. ratio == 0(Manim 클립의 일반 케이스)에
  페이드를 넣으면 컷마다 끝이 검게 죽어 경계가 번쩍인다 — 계약이 명시적으로 금지한다.

★ 모든 kind 에서 `target_sec == narration_sec` 이다. **나레이션이 타임라인의 주인**이고
  flagged 도 예외가 아니다(보정을 안 할 뿐 화면 시간은 그대로다).
"""

from __future__ import annotations

import math

from . import config
from .clip_fit_types import Strategy


def _pingpong_loops(clip_sec: float, target_sec: float) -> int:
    """정·역 왕복 몇 번으로 target 을 덮는가. **최소 1회.**

    한 왕복은 클립 길이의 2배를 덮는다(정방향 + 역방향). 남는 꼬리는 소비자가 자른다 —
    여기서 딱 맞추려고 초를 쪼개면 ffmpeg 필터 인자가 부동소수 오차로 흔들린다.
    """
    span = max(float(clip_sec), 1e-6) * 2.0
    return max(1, int(math.ceil(float(target_sec) / span)))


def decide_strategy(clip_sec: float, narration_sec: float,
                    loop_safe: bool = False) -> Strategy:
    """클립·나레이션 길이 → 보정 전략. 계약(`clip_fit_types.DecideStrategy`)의 구현체.

    ★ `narration_sec <= 0` 은 호출측 결함이다. 계약이 "방어적으로 trim 을 돌려도 된다"고
      허용하므로 **렌더를 죽이지 않는 쪽**을 고른다 — 여기서 예외를 올리면 컷 하나 때문에
      편 전체가 멈춘다. 대신 note 에 그 사실을 남긴다.
    """
    c = max(float(clip_sec), 0.0)
    n = float(narration_sec)
    if n <= 0:
        return Strategy(kind="trim", clip_sec=c, narration_sec=0.0, ratio=0.0,
                        target_sec=c, fade_out_sec=0.0,
                        note="나레이션 길이가 0 이하다(호출측 결함) — 클립을 그대로 쓴다")

    ratio = (n - c) / n

    # ── 클립이 나레이션보다 길거나 같다 → 자른다 ──────────────
    if ratio <= 0:
        # ★ 같을 때는 자를 것이 없으니 페이드도 없다. 계약이 명시한 지점이다.
        fade = config.CLIP_FIT_TRIM_FADE_SEC if c > n else 0.0
        return Strategy(kind="trim", clip_sec=c, narration_sec=n, ratio=ratio,
                        target_sec=n, fade_out_sec=fade,
                        note=(f"클립이 {c - n:.2f}s 길다 — 끝을 자르고 페이드아웃"
                              if c > n else "클립과 나레이션 길이가 같다 — 자를 것 없음"))

    # ── 조금 짧다 → 마지막 프레임 홀드 ────────────────────────
    if ratio <= config.CLIP_FIT_HOLD_RATIO_MAX:
        return Strategy(kind="hold", clip_sec=c, narration_sec=n, ratio=ratio,
                        target_sec=n, hold_sec=n - c, ken_burns=True,
                        note=f"{n - c:.2f}s 부족 — 마지막 프레임 홀드(켄번스로 정지 티를 줄인다)")

    # ── 꽤 짧다 → 루프가 안전하면 왕복, 아니면 홀드 ───────────
    if ratio <= config.CLIP_FIT_PINGPONG_RATIO_MAX:
        if loop_safe:
            return Strategy(kind="pingpong", clip_sec=c, narration_sec=n, ratio=ratio,
                            target_sec=n, loops=_pingpong_loops(c, n),
                            note=f"{n - c:.2f}s 부족 — 정·역 왕복으로 채운다(loop_safe)")
        # ★ loop_safe 가 아니면 왕복이 **부자연스럽다**: 사람이 걷다가 뒤로 걷고, 액체가
        #   거꾸로 흐른다. 지시서가 컷 단위로 안전을 선언하지 않았으면 홀드가 안전측이다.
        return Strategy(kind="hold", clip_sec=c, narration_sec=n, ratio=ratio,
                        target_sec=n, hold_sec=n - c, ken_burns=True,
                        note=(f"{n - c:.2f}s 부족 — 왕복 구간이지만 loop_safe 가 아니라 홀드"
                              " (역재생이 어색한 컷이다)"))

    # ── 너무 짧다 → 보정으로 못 메운다 ────────────────────────
    # ★ 그래도 화면 시간은 나레이션 길이다(계약 불변식). 소비자가 홀드로 채우고,
    #   플래그는 **사람에게 보이는 신호**다 — 조용히 늘려 놓으면 그 컷이 왜 어색한지 모른다.
    return Strategy(kind="flagged", clip_sec=c, narration_sec=n, ratio=ratio,
                    target_sec=n, hold_sec=n - c, ken_burns=True,
                    note=(f"클립이 나레이션의 {c / n:.0%} 뿐이다 — 보정으로 메울 수 없다."
                          " 컷을 쪼개거나 나레이션을 줄여라"))


__all__ = ["decide_strategy"]
