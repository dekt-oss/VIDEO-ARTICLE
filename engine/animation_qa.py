"""Q3 애니메이션 계약 검사 (지시서 v3 §9 Post-render Q3).

무엇을 푸는가
--------------
`component_registry` 는 컴포넌트마다 **애니메이션 계약**을 선언한다 —
`count_up` 은 min_change_ratio 0.60, `bar_grow` 는 0.50 … 즉 "이 컴포넌트는 시간에 따라
이만큼은 달라져야 한다". 그런데 **그 값을 읽는 코드가 어디에도 없었다**(2026-09-03 확인:
`min_change_ratio` 참조가 정의부와 주석 두 줄뿐). 계약만 있고 검사가 없으면,
카운트업이 정지된 숫자로 나가도, 막대가 안 자라도 **아무도 모른다.**

지시서 §14-1 하드 게이트가 "카운트업·바 채움·차트 드로우가 **Q3 계약으로 확인됨**"을
Phase 4 검증 렌더의 조건으로 걸어 놨다. 그래서 렌더보다 이것이 먼저다.

★★★ **적용 범위 주의(2026-09-03 확인) — 이 검사는 보드 컷에만 붙는다.**
  보드는 `explainer`(설명판형) 버전의 화면 문법인데 **그 버전은 2026-08-28 에 폐기됐다**
  (`docs/deviation-drop-explainer-webtoon.md`). 새 지시서는 `board` 필드를 만들지 않으므로
  `board_render.code_render_board()` 가 항상 False 이고, 따라서 **새로 만드는 콘텐츠에는
  이 검사가 작동하지 않는다.** 살아 있는 곳은 **저장된 옛 explainer 지시서를 재렌더할 때**뿐이다.
  지금 개발 중인 `photo`(실사형)는 보드를 쓰지 않는다 — 거기서 움직임을 보는 것은
  `clip_candidates`(후보 채점)와 Q1 정지 화면 검사다.
  이 모듈을 지우지 않는 이유는 옛 지시서 재생을 살려 두는 저장소 관례 때문이다(editorial 전례).

무엇을 재는가 — "잉크가 얼마나 달라졌나"
------------------------------------------
전체 프레임 diff 가 아니다(§9 가 명시적으로 금지한다). 컴포넌트 영역 안에서
**첫 / 중간 / 끝** 세 프레임만 본다.

    ink(f)  = 배경과 tol 이상 다른 픽셀 (= 실제로 뭔가 그려진 자리)
    changed = |f_last - f_first| 가 tol 이상인 픽셀
    ratio   = |changed| / |ink(first) ∪ ink(last)|

★ 왜 bbox 넓이가 아니라 **잉크 합집합**으로 나누는가: 숫자 한 줄은 제 영역의 20% 도 안
  덮는다. 넓이로 나누면 카운트업이 아무리 완벽하게 돌아도 비율이 0.2 를 못 넘어
  min_change_ratio 0.60 을 **영원히 통과 못 한다** — 계약값이 통째로 무의미해진다.
  잉크로 나누면 "그려진 것 중 얼마가 달라졌나"가 되어 계약값과 같은 축에 놓인다:
    · 카운트업(숫자가 전부 바뀜)   → ~1.0
    · 막대 자람(0 → 가득)          → ~1.0
    · 페이드인(배경 → 글자)        → ~1.0
    · 정지된 카드                  → 0.0

★ 중간 프레임은 **단조성**을 본다(보조 신호). 첫·끝만 보면 "깜빡였다 제자리"도 통과한다.
  다만 판정은 첫↔끝으로 한다 — 중간은 경고만 낸다.

★★ 이 검사가 **못 잡는 것을 분명히 해 둔다**(과장 금지). 계약이 선언한 것은 문자 그대로
  "첫 프레임 대비 끝 프레임이 이만큼 달라졌나"다. 그래서:
    · 잡는다 — 컴포넌트가 **처음부터 끝까지 그대로**인 경우(카운트업이 정지된 숫자로,
      막대가 안 자란 채로 나감). 이때 ratio ≈ 0 이라 확실히 걸린다.
    · 못 잡는다 — 최종 상태가 **첫 프레임에 통째로 나타나고 그 뒤 멈춘** 경우. 빈 화면에서
      무엇이든 나타나면 잉크 기준 변화가 1.00 이라 계약을 통과한다.
  실측(2026-09-03) 보드 11종이 전부 1.00 인 이유가 이것이다 — 첫 프레임이 설계상 비어
  있어서, "나타났다"만으로 만점이 된다. **즉 이 값은 하한선이지 충실도 점수가 아니다.**
  후자를 가르려면 중간→끝 변화(mid_to_last)를 봐야 하는데, 일찍 끝나는 연출(페이드인이
  중간 전에 완료)이 정상적으로 0 을 내므로 **지금 문턱을 정할 근거가 없다.**
  그래서 mid_to_last 는 **기록만 한다** — world_drift·text_burn_in 과 같은 자리다.

판정을 어떻게 쓰는가
---------------------
`min_change_ratio == 0` 인 컴포넌트(정적 카드류)는 **검사하지 않는다**.
실패는 잡을 죽이지 않고 `important`(degraded — 사람이 보고 정함)로 올린다.
`config.LAYOUT_FAIL_REVIEWABLE` 이 core_underfilled 에 대해 배운 것과 같은 처방이다:
이미 이미지·TTS·조립 비용을 다 쓴 뒤 산출물을 버리면 운영자에게 남는 것이 로그 한 줄뿐이다.

이 모듈은 **순수 함수다** — PIL·파일·네트워크를 모른다. 호출부가 픽셀을 떠 온다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from . import component_registry as cr
from . import config


@dataclass(frozen=True)
class AnimationResult:
    component: str
    contract_type: str
    required: float
    ratio: float
    passed: bool
    reason: str = ""
    monotonic: bool = True
    # 중간→끝 변화(기록 전용, 문턱 없음). ratio 가 "나타나기라도 했나"라면 이쪽은
    # "중간에도 진행 중이었나"다 — 아래 docstring 의 한계 참조.
    mid_to_last: float = -1.0

    def as_dict(self) -> dict[str, object]:
        return {"component": self.component, "type": self.contract_type,
                "required": round(self.required, 3), "ratio": round(self.ratio, 3),
                "passed": self.passed, "reason": self.reason,
                "monotonic": self.monotonic, "mid_to_last": round(self.mid_to_last, 3)}


def _ink(sample: Sequence[int], bg: int, tol: int) -> list[bool]:
    return [abs(int(v) - bg) > tol for v in sample]


def baseline(first: Sequence[int]) -> int:
    """이 컴포넌트 자리의 **배경 기준값** — 첫 프레임의 중앙값.

    ★★ 페이지 배경 토큰(bg)을 쓰면 안 된다(2026-09-03 실측). 보드는 컴포넌트 뒤에 더 밝은
      패널을 깔기 때문에, 컴포넌트 자리의 배경은 페이지 배경이 아니다. 실측:
      NUMBER_BOARD 의 첫 프레임 크롭이 **전 픽셀 40**(패널색)인데 토큰 배경은 18 이라
      |40-18|=22 > tol 로 **빈 프레임 전체가 잉크로 잡혔다.** 그래서 분모가 크롭 전체가
      되고, 숫자가 0 에서 통째로 나타났는데도 비율이 0.43 으로 나왔다.
      첫 프레임은 설계상 "아직 아무것도 안 그려진" 상태이므로 그 중앙값이 곧 이 자리의
      배경이다. 자를 바깥에서 가져오지 말고 **재는 대상에서** 얻는다.
    """
    return int(statistics.median(first)) if first else 0


def change_ratio(first: Sequence[int], last: Sequence[int], *,
                 bg: int | None = None, tol: int | None = None) -> float:
    """첫↔끝 프레임의 **잉크 변화 비율**. 0(그대로) ~ 1(전부 달라짐).

    bg 를 안 주면 첫 프레임 중앙값을 기준으로 쓴다(baseline 주석 참조).
    ★ 길이가 다르면 판정하지 않는다(-1). 크롭이 어긋난 것이지 애니메이션 문제가 아니다.
    """
    if not first or not last or len(first) != len(last):
        return -1.0
    if bg is None:
        bg = baseline(first)
    t = config.ANIM_QA_PIXEL_TOL if tol is None else tol
    ink_a = _ink(first, bg, t)
    ink_b = _ink(last, bg, t)
    denom = sum(1 for a, b in zip(ink_a, ink_b) if a or b)
    if denom <= 0:
        return 0.0            # 양쪽 다 배경 — 아무것도 안 그려졌다(Q1 이 잡을 일)
    changed = sum(1 for a, b in zip(first, last) if abs(int(a) - int(b)) > t)
    return min(1.0, changed / float(denom))


def evaluate(component: str, first: Sequence[int], mid: Sequence[int],
             last: Sequence[int], *, bg: int | None = None) -> AnimationResult | None:
    """컴포넌트 1종의 애니메이션 계약 판정. 계약이 없거나 정적이면 None(검사 안 함)."""
    spec = cr.CORE_COMPONENTS.get(component)
    if spec is None:
        return None
    contract = spec.animation
    required = float(contract.min_change_ratio or 0.0)
    if required <= 0:
        return None                       # 정적 허용 — 판정 대상이 아니다
    ratio = change_ratio(first, last, bg=bg)
    if ratio < 0:
        return AnimationResult(component, contract.type, required, 0.0, True,
                               reason="not_measured", monotonic=True)
    # 중간 프레임 단조성: 첫→중 변화가 첫→끝 변화보다 크면 "갔다가 되돌아왔다".
    mono = True
    mid_ratio = change_ratio(first, mid, bg=bg) if mid else -1.0
    if mid_ratio >= 0 and ratio >= 0 and mid_ratio > ratio + config.ANIM_QA_MONOTONIC_SLACK:
        mono = False
    passed = ratio + 1e-9 >= required
    reason = "" if passed else f"{contract.type}:{ratio:.2f}<{required:.2f}"
    tail = change_ratio(mid, last, bg=bg) if mid else -1.0
    return AnimationResult(component, contract.type, required, ratio, passed, reason,
                           mono, tail)


def board_signals(result: AnimationResult | None) -> list[str]:
    """판정 → board_qa 에 실을 사유 코드. 통과·미검사면 빈 목록.

    ★ 코드 접두사 `animation_contract:` 는 render_manifest.terminal_status 가 보는 이름이다.
      두 곳이 어긋나면 검사는 도는데 상태가 안 바뀐다 — 테스트가 둘을 같이 박는다.
    """
    if result is None or result.passed:
        out: list[str] = []
    else:
        out = [f"{config.ANIM_QA_REASON_PREFIX}{result.reason}"]
    if result is not None and not result.monotonic:
        out.append(f"{config.ANIM_QA_REASON_PREFIX}non_monotonic:{result.component}")
    return out
