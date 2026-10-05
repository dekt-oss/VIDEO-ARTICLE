"""Spoken-number accounting shared by Explanation Engine v2 Phase 5, 6 and 8.

★ 왜 한 자리인가(Phase 12 파일럿, 2026-10-04). 세 단계가 숫자를 서로 다르게 다뤄서 풀 수 없는
  충돌이 났다 — Phase 5 는 근거 문장을 숫자째 전부 대본 재료로 넘기고, Phase 6 은 숫자를 하나라도
  빼면 거절하고, Phase 8 은 소리 내 읽는 숫자가 `MAX_SPOKEN_NUMBERS`(2)를 넘으면 재생성을
  요구했다. 재생성해도 재료가 같으니 영원히 못 넘는다(실측 16·15개).
  이제 Phase 5 가 **말로 읽을 대표 숫자**를 고르고 나머지는 화면 카드로 보낸다(원안 Phase 6
  "숫자를 너무 많이 읽는가", Production 의 말할/보여줄 근거 `EVIDENCE_DELIVERY` 와 같은 생각).
  세는 방법은 이 모듈 하나다.

시점 표현(연도·분기·월·3Q26E 같은 기간 표기)은 "읽는 수치"가 아니라 맥락이다. 개수에서 빼고,
대본에서 바꾸거나 빼지 못하게 한다(전망 시점이 사라지면 뜻이 바뀐다).
"""

from __future__ import annotations

import re
from typing import Any

from . import config

# 시점 표현 — 값이 아니라 언제인지를 말한다. 긴 것부터 지운다.
_PERIOD = re.compile(
    r"[1-4]\s*Q\s*\d{2}\s*[EFP]?"           # 3Q26, 3Q26E
    r"|[1-2]\s*H\s*\d{2}\s*[EFP]?"          # 1H26E
    r"|\d{4}\s*년(?:\s*\d{1,2}\s*월)?"       # 2026년, 2026년 3월
    r"|\d{2,4}\s*[EF](?![A-Za-z])"          # 2026F, 26E
    r"|\d\s*분기"                            # 3분기
    r"|\d{1,2}\s*월(?!\s*[가-힣]*원)"         # 3월 (단, '3월원' 같은 금액 표기는 제외)
)
# 이름의 일부인 숫자 — 값이 아니다(HBM4, DDR5, A100, COVID-19, GPT-4o, 5G, 4K).
# 파일럿 실데이터에서 "HBM4" 의 4 가 화면용 숫자로 잡혀, 모델이 제품명을 말하기만 해도
# `screen_number_spoken` 으로 거절될 뻔했다.
_IDENTIFIER = re.compile(r"[A-Za-z]+-?\d+[A-Za-z0-9]*|\d+[A-Z](?![A-Za-z])")
# 값으로 읽히는 수. 단위는 붙여서 하나로 센다(`spoken_narration` 의 종전 정의와 같다).
_VALUE = re.compile(
    r"[+-]?\d+(?:[.,]\d+)*\s*(?:퍼센트|개월|시간|억원|만원|조원|달러|USD|KRW|%p|%|배|년|"
    r"주|일|분|초|명|마리|건|개|회|원|kg|km|mg|ml|mm|cm|g|m|L)?"
)


def _norm(token: str) -> str:
    return re.sub(r"\s+", "", token)


def period_tokens(text: Any) -> list[str]:
    """시점 표현 목록(정렬). 개수 상한에 들어가지 않는다."""
    return sorted(_norm(m.group(0)) for m in _PERIOD.finditer(str(text or "")))


def _is_name_number(text: str, match: re.Match[str]) -> bool:
    """단위 없이 한글이 바로 붙은 숫자는 이름의 일부다("조선 3사", "4행정 엔진") — 값이 아니다.

    ★ 실측(Shipbuilding, 2026-10-05): "3사"·"4행정" 이 값으로 잡혀 말할 숫자/화면 숫자에 들어갔고,
      모델이 "조선 3사"라고만 말해도 거절됐다. 명·마리·배·원처럼 `_VALUE` 단위가 붙은 수는 그대로 센다.
    """
    token = match.group(0)
    if not token or not token[-1].isdigit():
        return False                                  # 단위가 붙었다 — 값이다
    following = text[match.end():match.end() + 3]
    if not following or not ("가" <= following[0] <= "힣"):
        return False
    # 조사가 붙은 수는 값이다("1에서 2를 거쳐 3으로", "수치는 3이다").
    return not following.startswith(_PARTICLES)


_PARTICLES = ("에서", "으로", "부터", "까지", "보다", "이다", "입니", "이며", "이고",
              "이", "가", "을", "를", "은", "는", "과", "와", "로", "에", "의", "도", "만")


def value_tokens(text: Any) -> list[str]:
    """소리 내 읽는 값 목록(정렬, 중복 유지). 시점 표현·이름 속 숫자를 먼저 지우고 센다."""
    masked = _IDENTIFIER.sub(" ", _PERIOD.sub(" ", str(text or "")))
    return sorted(
        _norm(m.group(0)) for m in _VALUE.finditer(masked)
        if any(ch.isdigit() for ch in m.group(0)) and not _is_name_number(masked, m)
    )


def _sub(left: list[str], right: list[str]) -> list[str]:
    rest = list(left)
    for token in right:
        if token in rest:
            rest.remove(token)
    return rest


def multiset_minus(left: list[str], right: list[str]) -> list[str]:
    """left − right (중복 유지)."""
    return sorted(_sub(left, right))


def assign(points: list[dict[str, Any]], *, thesis: str = "",
           budget: int | None = None) -> dict[str, dict[str, Any]]:
    """말로 읽을 근거 단위를 고른다 — 결정론적, 모델 판단 없음.

    points: [{"ref", "text", "role"}] (이야기 순서). 반환: ref → {"spoken": bool, "numbers": [...]}.
    우선순위 ① 핵심 주장(thesis)과 같은 문장 ② 결과·귀결 역할(result/payoff) ③ 나머지 — 각각 이야기
    순서대로. 한 단위의 숫자는 **전부 말하거나 전부 화면으로** 간다(범위 "26%에서 41%" 를 반쪽만
    읽지 않게). 남은 예산보다 숫자가 많은 단위는 화면으로 간다.
    """
    remaining = config.MAX_SPOKEN_NUMBERS if budget is None else budget
    numbered = [(position, point) for position, point in enumerate(points)
                if value_tokens(point.get("text"))]

    def rank(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        position, point = item
        if thesis and str(point.get("text") or "").strip() == thesis.strip():
            return (0, position)
        if point.get("role") in {"result", "payoff"}:
            return (1, position)
        return (2, position)

    decision: dict[str, dict[str, Any]] = {}
    for _, point in sorted(numbered, key=rank):
        numbers = value_tokens(point.get("text"))
        spoken = len(numbers) <= remaining
        if spoken:
            remaining -= len(numbers)
        decision[str(point["ref"])] = {"spoken": spoken, "numbers": numbers}
    return decision
