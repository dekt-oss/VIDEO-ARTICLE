"""시점 오류 — 논문이 미래로 쓴 일을 **제작 시점에도 미래로** 읽는 것 (§21, 2026-09-02).

무엇이 문제인가
---------------
논문은 쓰인 시점의 시제로 말한다. 2024년 논문이 "탐사선이 2025년에 달에 충돌할 **예정**"
이라 쓰면 그건 그때 기준으로 맞는 말이다. 그런데 우리가 2026년에 그 문장을 그대로
화면에 올리면 **이미 일어난 일을 아직 안 일어난 일처럼** 말하게 된다.

시청자에게는 이게 그냥 틀린 정보다. 그리고 이 오류는 게이트가 지금까지 본 적이 없다 —
`cut_detail_not_in_source` 는 "원문에 있는 말인가"를 보는데, 이 문장은 **원문에 있다.**
원문에 있는 것이 지금도 참인지는 아무도 묻지 않았다.

어떻게 판정하나
---------------
두 가지가 **한 컷 안에서 겹칠 때만** 잡는다.

  ① 미래 시제 표현이 있다          ("예정", "will", "예상된다" …)
  ② 그 컷이 말하는 연도가 이미 지났다  (논문 발표 연도보다 크고, 오늘보다 작다)

★ 왜 둘 다 필요한가: 미래 표현만 보면 "앞으로 연구가 필요하다" 같은 정상 문장을 전부
  잡는다. 연도만 보면 과거를 과거로 말하는 정상 컷을 잡는다. 겹칠 때만 위험하다.

★ 왜 논문 발표 연도보다 커야 하나: 논문이 2024년에 쓰였는데 컷이 2023년을 말하면서
  미래형을 썼다면 그건 시점 오류가 아니라 다른 종류의 오류다(우리가 판정할 수 없다).
  **판정할 수 있는 것만 판정한다** — 이 저장소의 자세 그대로다.

★★ 차단하지 않고 **경고**한다. 어휘 목록으로 시제를 판정하는 것은 오탐이 크고, 리뷰
  §17 이 경고한 "정상 콘텐츠를 벌하는 게이트"가 될 위험이 실익보다 크다. 실제 지시서에서
  오탐률을 보고 나서 차단으로 올릴지 정한다 — world_drift·text_burn_in 과 같은 자리다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

#: 미래를 가리키는 표현. 한국어 나레이션과 영어 프롬프트 양쪽을 본다.
#: ★ "예정"처럼 조사가 붙는 말은 부분 일치로 잡고, 영어는 단어 경계를 준다
#:   ("will" 이 "willing"·"willow" 에 걸리면 오탐이 된다).
_FUTURE_KO: tuple[str, ...] = (
    "예정", "예상된다", "예상됩니다", "전망이다", "전망입니다",
    "할 것이다", "할 것입니다", "머지않아", "앞두고",
)
_FUTURE_EN: tuple[str, ...] = (
    "will", "upcoming", "is expected to", "are expected to", "slated to",
)

#: 화면·나레이션에서 시점을 말할 수 있는 필드.
_TEXT_FIELDS: tuple[str, ...] = ("narration", "visual_prompt", "motion_prompt",
                                 "state_change", "overlay_text")

# ★★ 워드 경계(`\b`)를 쓰지 않는다. 한글은 `\w` 라서 "2025년" 에는 5 와 년 사이에
#   **경계가 없다** — `\b` 로 쓰면 한국어 나레이션의 연도를 통째로 놓친다(테스트가 잡았다).
#   이 저장소는 워드 경계로 이미 두 번 사고를 냈다(§9-10). 원인은 달라도 결과는 같다:
#   **게이트가 조용히 죽는다.** 그래서 숫자 경계로만 자른다.
_YEAR = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")


def _text_of(cut: dict[str, Any]) -> str:
    parts = [str(cut.get(k) or "") for k in _TEXT_FIELDS]
    plan = cut.get("overlay_plan")
    if isinstance(plan, dict):
        parts += [str(v) for v in plan.values() if isinstance(v, str)]
    return " ".join(parts)


def has_future_tense(text: str) -> bool:
    """미래 시제 표현이 있는가. 한국어는 부분 일치, 영어는 단어 경계."""
    low = text.lower()
    if any(w in text for w in _FUTURE_KO):
        return True
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in _FUTURE_EN)


def stale_years(text: str, published_year: int, today_year: int) -> list[int]:
    """이 문장이 말하는 연도 중 **논문 이후이면서 이미 지난** 것들.

    ★ 경계: 올해는 넣지 않는다. 올해 안에 일어날 일을 미래형으로 말하는 것은 옳다.
    """
    out = {int(y) for y in _YEAR.findall(text)
           if published_year < int(y) < today_year}
    return sorted(out)


def warnings_for(cuts: list[dict[str, Any]] | None,
                 published_year: int | None,
                 today: date | None = None) -> list[str]:
    """시점 오류가 의심되는 컷들의 경고 코드. 순수 함수.

    반환 형식은 저장소 관례를 따른다: `사유:컷번호,컷번호`.
    판정할 근거가 없으면(발표 연도 모름) **아무것도 내지 않는다** — 판정 불가를
    위반으로 기록하지 않는다.
    """
    if not cuts or not published_year:
        return []
    today_year = (today or date.today()).year
    hits: list[str] = []
    for c in cuts:
        text = _text_of(c)
        if not text or not has_future_tense(text):
            continue
        if stale_years(text, int(published_year), today_year):
            hits.append(str(c.get("cut_no")))
    if not hits:
        return []
    return [f"cut_stale_future_tense:{','.join(hits)}"]


def published_year_of(fact_sheet: dict[str, Any] | None,
                      paper: dict[str, Any] | None = None) -> int | None:
    """논문 발표 연도. Fact Sheet 우선, 없으면 papers 행. 못 찾으면 None.

    ★ None 을 0 이나 올해로 대체하지 않는다. 모르면 판정을 아예 안 하는 것이
      틀린 기준으로 판정하는 것보다 낫다.
    """
    for src in (fact_sheet or {}, paper or {}):
        for key in ("published_year", "published_date", "year", "date"):
            raw = str(src.get(key) or "")
            m = re.search(r"(19\d{2}|20\d{2})", raw)
            if m:
                return int(m.group(1))
    return None
